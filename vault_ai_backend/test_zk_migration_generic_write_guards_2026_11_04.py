"""Keep generic writes from bypassing verified legacy migration.

These synthetic route tests also require row-lock serialization: a read of
verification_state without FOR UPDATE can race retirement and destroy the
sole MVK copy after the legacy ciphertext has been removed.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest
from fastapi import HTTPException


class _FileCursor:
    def __init__(self, verification_state="client_verified",
                 lifecycle_state="legacy_migration_retired"):
        self.state = (verification_state, lifecycle_state)
        self.queries = []
        self.result = None
        self.rowcount = 0

    def execute(self, sql, params):
        normalized = " ".join(sql.lower().split())
        self.queries.append(normalized)
        if normalized.startswith("select") and "from file_v2_records" in normalized:
            self.result = self.state
        elif normalized.startswith(("insert", "delete", "update")):
            # A retired file must not reach any mutating statement.
            raise AssertionError("generic route attempted to mutate retired file")
        else:
            raise AssertionError(f"unexpected synthetic SQL: {normalized[:100]}")

    def fetchone(self):
        return self.result


class _FileDb:
    def __init__(self):
        self.cur = _FileCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@pytest.fixture
def file_v2_harness(monkeypatch):
    from routes import file_v2_routes as route

    db = _FileDb()
    monkeypatch.setattr(route, "get_db", lambda: db)
    monkeypatch.setattr(route, "_enabled", lambda write=False: None)
    monkeypatch.setattr(route, "require_content_write", mock.Mock())
    return route, db


def _assert_serialized_state_check(db):
    state_reads = [sql for sql in db.cur.queries
                   if sql.startswith("select") and "from file_v2_records" in sql]
    assert len(state_reads) == 1
    assert "for update" in state_reads[0], (
        "file-v2 state check must lock the row that migration retirement locks"
    )


def test_generic_chunk_put_cannot_overwrite_retired_file(file_v2_harness):
    route, db = file_v2_harness
    request = route.Chunk(file_id="synthetic-file", chunk_index=0,
                          ciphertext="AQID")
    with pytest.raises(HTTPException) as raised:
        route.put_chunk(request, {"vault_id": "synthetic-vault"})
    assert raised.value.status_code == 409
    _assert_serialized_state_check(db)
    assert db.commits == 0


def test_generic_file_delete_cannot_remove_retired_file(file_v2_harness):
    route, db = file_v2_harness
    with pytest.raises(HTTPException) as raised:
        route.delete_file("synthetic-file", {"vault_id": "synthetic-vault"})
    assert raised.value.status_code == 409
    _assert_serialized_state_check(db)
    assert db.commits == 0


def test_generic_item_edit_cannot_clear_unverified_legacy_copy(monkeypatch):
    from routes import vault_ciphertext_write_routes as route

    cursor = mock.Mock()
    cursor.rowcount = 0  # The conditional edit must reject a legacy row.
    cursor.fetchone.return_value = {"has_legacy": True}
    conn = mock.Mock()
    conn.cursor.return_value = cursor
    monkeypatch.setattr(route, "get_db", lambda: conn)
    monkeypatch.setattr(route, "require_content_write", mock.Mock())
    request = route.VaultItemUpsertRequest(
        mutation_intent="edit", item_id=7,
        item_type_ciphertext="AQ", service_ciphertext="Ag",
        payload_ciphertext="Aw",
    )
    with pytest.raises(HTTPException) as raised:
        route.vault_item_upsert_ciphertext(
            request, {"vault_id": "synthetic-vault"},
        )
    assert raised.value.status_code == 409
    assert raised.value.detail == "legacy_item_migration_required"
    first_sql = " ".join(cursor.execute.call_args_list[0].args[0].lower().split())
    assert "update vault_items" in first_sql
    assert "and encrypted_data is null" in first_sql
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


class _LegacyDeleteCursor:
    def __init__(self):
        self.queries = []
        self.rowcount = 0
        self.result = None

    def execute(self, sql, params):
        normalized = " ".join(sql.lower().split())
        self.queries.append(normalized)
        if normalized.startswith("select pg_advisory_xact_lock"):
            self.result = None
            return
        if "from uploaded_files" in normalized:
            self.result = {"has_legacy_inline": True}
            return
        if "from file_v2_records" in normalized:
            # An unmarked V2 record may be a new upload, so legacy delete
            # must leave it alone even if an inline row shares the ID.
            self.result = {
                "migrating_legacy": False,
                "lifecycle_state": "file_v2_written",
                "verification_state": "not_verified",
            }
            return
        raise AssertionError("legacy route attempted to mutate a file with V2 copy")

    def fetchone(self):
        return self.result


class _LegacyDeleteDb:
    def __init__(self):
        self.cur = _LegacyDeleteCursor()
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _assert_legacy_delete_refused(db):
    assert len(db.cur.queries) == 3
    assert "pg_advisory_xact_lock" in db.cur.queries[0]
    assert "from uploaded_files" in db.cur.queries[1]
    assert "for update" in db.cur.queries[1]
    assert "from file_v2_records" in db.cur.queries[2]
    assert "for update" in db.cur.queries[2]
    assert db.commits == 0


def test_vault_manage_legacy_delete_refuses_unmarked_v2_file(monkeypatch):
    from routes import vault_manage_routes as route

    db = _LegacyDeleteDb()
    monkeypatch.setattr(route, "get_db", lambda: db)
    monkeypatch.setattr(route, "verify_vault_pin", mock.Mock())
    payload = route.FileDeleteRequest(
        vault_name="synthetic", file_id="synthetic-file", pin="123456",
    )
    with pytest.raises(HTTPException) as raised:
        route._delete_file_impl(payload, "synthetic-vault")
    assert raised.value.status_code == 409
    _assert_legacy_delete_refused(db)


def test_primary_legacy_delete_refuses_unmarked_v2_file(monkeypatch):
    import main

    db = _LegacyDeleteDb()
    monkeypatch.setattr(main, "get_db", lambda: db)
    monkeypatch.setattr(main, "verify_vault_pin", mock.Mock())
    payload = main.DeleteFileRequest(
        vault_name="synthetic", file_id="synthetic-file", pin="123456",
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.delete_file_endpoint(
            mock.Mock(), payload, {"vault_id": "synthetic-vault"},
        ))
    assert raised.value.status_code == 409
    _assert_legacy_delete_refused(db)
