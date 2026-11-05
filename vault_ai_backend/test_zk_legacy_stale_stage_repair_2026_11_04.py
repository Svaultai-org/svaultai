"""Synthetic compatibility checks for edits made after V2 staging."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from legacy_source_snapshot import source_snapshot
from routes import file_v2_routes, vault_ciphertext_write_routes, vault_manage_routes


VAULT = "synthetic-vault"
FILE = "synthetic-file"


def test_source_snapshot_distinguishes_null_and_empty_metadata():
    row = {"encrypted_data": "synthetic-ciphertext", "item_type": "login",
           "service": None}
    first = source_snapshot("item", row, vault_id=VAULT, record_id=7)
    assert len(first) == 43
    assert source_snapshot("item", row, vault_id="other-vault", record_id=7) != first
    assert source_snapshot("item", row, vault_id=VAULT, record_id=8) != first
    row["service"] = ""
    assert source_snapshot("item", row, vault_id=VAULT, record_id=7) != first


class _FileCursor:
    def __init__(self, state):
        self.state = state
        self.result = None
        self.rowcount = 0
        self.queries = []

    def execute(self, sql, params):
        query = " ".join(sql.lower().split())
        self.queries.append(query)
        if query.startswith("select pg_advisory_xact_lock"):
            self.result = None
            return
        if query.startswith("select migrating_legacy"):
            assert any("pg_advisory_xact_lock" in q for q in self.queries[:-1])
            assert query.endswith("for update")
            self.result = self.state
            return
        if query.startswith("delete from file_v2_records"):
            assert self.state == (True, "file_v2_written", "not_verified")
            self.state = None
            self.result = (FILE,)
            return
        if query.startswith("update uploaded_files"):
            assert self.state is None
            self.rowcount = 1
            self.result = {
                "id": FILE, "file_name": "synthetic-file.txt",
                "saved_name": "new-name",
            }
            return
        raise AssertionError(f"Unexpected synthetic SQL: {query[:100]}")

    def fetchone(self):
        return self.result


class _FileDb:
    def __init__(self, state):
        self.cur = _FileCursor(state)
        self.commits = 0

    def cursor(self, **_kwargs):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def test_old_ciphertext_rename_invalidates_unfinished_stage_atomically(monkeypatch):
    db = _FileDb((True, "file_v2_written", "not_verified"))
    monkeypatch.setattr(vault_ciphertext_write_routes, "get_db", lambda: db)
    monkeypatch.setattr(vault_ciphertext_write_routes,
                        "require_content_write", lambda _principal: None)
    payload = vault_ciphertext_write_routes.UploadedFileMetadataRequest(
        file_id=FILE, saved_name_ciphertext="AQID",
    )

    result = vault_ciphertext_write_routes.uploaded_file_metadata_ciphertext(
        payload, {"vault_id": VAULT},
    )

    assert result.file_id == FILE
    assert result.updated_columns == ["saved_name_ciphertext"]
    assert db.commits == 1
    queries = db.cur.queries
    assert next(i for i, q in enumerate(queries) if q.startswith("delete")) < next(
        i for i, q in enumerate(queries) if q.startswith("update"))


def test_old_plaintext_rename_invalidates_unfinished_stage_atomically(monkeypatch):
    db = _FileDb((True, "file_v2_written", "not_verified"))
    monkeypatch.setattr(vault_manage_routes, "get_db", lambda: db)
    monkeypatch.setattr(vault_manage_routes, "require_content_write",
                        lambda _principal: None)
    monkeypatch.setattr(vault_manage_routes, "verify_vault_pin",
                        lambda *_args: b"synthetic-key")
    monkeypatch.setattr(file_v2_routes, "reject_legacy_zk_file_rename",
                        lambda _principal: None)
    payload = vault_manage_routes.FileRenameRequest(
        vault_name="synthetic-vault", file_id=FILE,
        saved_name="new-name", pin="synthetic-pin",
    )

    result = asyncio.run(vault_manage_routes.rename_file(
        payload, {"vault_id": VAULT},
    ))

    assert result["status"] == "renamed"
    assert db.commits == 1
    assert db.cur.state is None
    assert next(i for i, q in enumerate(db.cur.queries)
                if q.startswith("delete")) < next(
                    i for i, q in enumerate(db.cur.queries)
                    if q.startswith("update"))


@pytest.mark.parametrize("state", [
    (False, "file_v2_written", "not_verified"),
    (True, "legacy_migration_retired", "client_verified"),
])
def test_old_ciphertext_rename_cannot_change_unmarked_or_retired_v2(
    monkeypatch, state,
):
    db = _FileDb(state)
    monkeypatch.setattr(vault_ciphertext_write_routes, "get_db", lambda: db)
    monkeypatch.setattr(vault_ciphertext_write_routes,
                        "require_content_write", lambda _principal: None)
    payload = vault_ciphertext_write_routes.UploadedFileMetadataRequest(
        file_id=FILE, saved_name_ciphertext="AQID",
    )
    with pytest.raises(HTTPException) as raised:
        vault_ciphertext_write_routes.uploaded_file_metadata_ciphertext(
            payload, {"vault_id": VAULT},
        )
    assert raised.value.status_code == 409
    assert db.commits == 0
    assert not any(q.startswith("update uploaded_files") for q in db.cur.queries)


def test_old_login_edit_invalidates_staged_item_without_deleting_legacy(monkeypatch):
    class Cursor:
        rowcount = 0

        def __init__(self):
            self.queries = []
            self.result = None

        def execute(self, sql, params):
            query = " ".join(sql.lower().split())
            self.queries.append(query)
            if query.startswith("select id, encrypted_data"):
                self.result = {"id": 7, "encrypted_data": "synthetic-legacy"}
            elif query.startswith("update vault_items"):
                assert "service_ciphertext = null" in query
                assert "payload_ciphertext = null" in query
                assert "and encrypted_data is not null" in query
                assert params[-2:] == (7, VAULT)
                self.rowcount = 1
                self.result = None
            else:
                raise AssertionError(f"Unexpected synthetic SQL: {query[:100]}")

        def fetchone(self):
            return self.result

    class Db:
        def __init__(self):
            self.cur = Cursor()
            self.commits = 0

        def cursor(self, **_kwargs):
            return self.cur

        def commit(self):
            self.commits += 1

        def close(self):
            pass

    db = Db()
    monkeypatch.setattr(vault_manage_routes, "get_db", lambda: db)
    monkeypatch.setattr(vault_manage_routes, "require_content_write",
                        lambda _principal: None)
    monkeypatch.setattr(vault_manage_routes, "verify_vault_pin",
                        lambda *_args: b"synthetic-key")
    monkeypatch.setattr(vault_manage_routes, "decrypt_message",
                        lambda *_args: "{}")
    monkeypatch.setattr(vault_manage_routes, "encrypt_message",
                        lambda *_args: "synthetic-updated-legacy")
    payload = vault_manage_routes.LoginUpdateRequest(
        vault_name="synthetic-vault", old_service="Old",
        new_service="New", pin="synthetic-pin",
    )

    result = asyncio.run(vault_manage_routes.update_login(
        payload, {"vault_id": VAULT},
    ))

    assert result == {"status": "updated", "service": "new"}
    assert db.commits == 1
    assert not any(q.startswith("delete") for q in db.cur.queries)


def test_file_invalidation_helper_requires_locked_unverified_marker():
    cursor = _FileCursor((True, "file_v2_written", "not_verified"))
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                   (VAULT, FILE))
    assert file_v2_routes.invalidate_unverified_legacy_stage_for_file_mutation(
        cursor, VAULT, FILE,
    )
    assert cursor.state is None


def test_file_manifest_rejects_stale_export_snapshot_before_insert(monkeypatch):
    class Cursor:
        def __init__(self):
            self.result = None
            self.queries = []

        def execute(self, sql, _params):
            query = " ".join(sql.lower().split())
            self.queries.append(query)
            if query.startswith("select pg_advisory_xact_lock"):
                self.result = None
            elif query.startswith("select length(encrypted_file_data)"):
                self.result = (24,)
            elif query.startswith("select encrypted_file_data,"):
                self.result = tuple(
                    "synthetic-ciphertext-data"
                    if field == "encrypted_file_data" else
                    4 if field == "file_size" else None
                    for field in file_v2_routes.FILE_SOURCE_FIELDS
                )
            else:
                raise AssertionError(f"Unexpected synthetic SQL: {query[:100]}")

        def fetchone(self):
            return self.result

    class Db:
        def __init__(self):
            self.cur = Cursor()
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

    db = Db()
    monkeypatch.setattr(file_v2_routes, "get_db", lambda: db)
    monkeypatch.setattr(file_v2_routes, "_enabled", lambda _write: None)
    monkeypatch.setattr(file_v2_routes, "require_content_write",
                        lambda _principal: None)
    payload = file_v2_routes.Manifest(
        file_id=FILE, crypto_version="client_mvk_v2",
        manifest_ciphertext="AQID", total_bytes=4,
        chunk_size=1024, chunk_count=1, migrating_legacy=True,
        source_snapshot="X" * 43,
    )

    with pytest.raises(HTTPException) as raised:
        file_v2_routes.create_manifest(payload, {"vault_id": VAULT})

    assert raised.value.status_code == 409
    assert raised.value.detail == "legacy_source_changed"
    assert db.commits == 0
    assert db.rollbacks == 1
    assert not any(q.startswith("insert") for q in db.cur.queries)
