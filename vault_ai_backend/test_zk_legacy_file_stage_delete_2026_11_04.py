"""Synthetic transaction checks for explicit legacy-file deletion after V2 staging."""

from __future__ import annotations

import asyncio
import copy
from unittest import mock

import pytest
from fastapi import HTTPException


VAULT_ID = "synthetic-vault"
FILE_ID = "synthetic-file"


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.result = None

    def execute(self, sql, params):
        query = " ".join(sql.lower().split())
        self.db.queries.append(query)
        assert params[-2:] == (VAULT_ID, FILE_ID) or params[-2:] == (FILE_ID, VAULT_ID) or query.startswith("update vaults")
        if query.startswith("select pg_advisory_xact_lock"):
            self.result = None
        elif query.startswith("select storage_mode") and "from uploaded_files" in query:
            self.result = {"has_legacy_inline": self.db.state["legacy"] is not None}
        elif query.startswith("select migrating_legacy") and "from file_v2_records" in query:
            self.result = self.db.state["v2"]
        elif query.startswith("delete from file_v2_records"):
            assert self.db.state["v2"] is not None
            self.db.state["v2"] = None
            self.db.state["chunks"] = []  # ON DELETE CASCADE
            self.result = {"file_id": FILE_ID}
        elif query.startswith("delete from uploaded_files"):
            self.result = self.db.state["legacy"]
            if not self.db.missing_old_delete:
                self.db.state["legacy"] = None
            else:
                self.result = None
        elif query.startswith("update vaults"):
            assert self.result is not None
            self.db.state["quota"] -= params[0]
        else:
            raise AssertionError(f"Unexpected SQL: {query[:110]}")

    def fetchone(self):
        return self.result


class _Db:
    def __init__(self, *, marked=True, verified=False, missing_old_delete=False):
        self.state = {
            "legacy": {"id": FILE_ID, "file_name": "synthetic.txt", "file_size": 37},
            "v2": {
                "migrating_legacy": marked,
                "lifecycle_state": "client_v2_ready" if verified else "file_v2_written",
                "verification_state": "client_verified" if verified else "not_verified",
            },
            "chunks": ["synthetic-ciphertext-chunk"],
            "quota": 137,
        }
        self.initial = copy.deepcopy(self.state)
        self.missing_old_delete = missing_old_delete
        self.queries = []
        self.cur = _Cursor(self)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **_kwargs):
        return self.cur

    def commit(self):
        self.commits += 1
        self.initial = copy.deepcopy(self.state)

    def rollback(self):
        self.rollbacks += 1
        self.state = copy.deepcopy(self.initial)

    def close(self):
        pass


@pytest.mark.parametrize("path", ["primary", "vault_manage"])
def test_explicit_old_file_delete_atomically_removes_only_marked_stage(
    monkeypatch, path,
):
    import main
    from routes import vault_manage_routes
    import pin_only_action_gate

    db = _Db()
    monkeypatch.setattr(pin_only_action_gate, "authorize_pin_only_action", mock.Mock())
    monkeypatch.setattr(vault_manage_routes, "authorize_pin_only_action", mock.Mock())
    if path == "primary":
        monkeypatch.setattr(main, "get_db", lambda: db)
        quota_bump = mock.Mock(side_effect=lambda _vault, delta: db.state.__setitem__(
            "quota", db.state["quota"] + delta,
        ))
        monkeypatch.setattr(main, "bump_vault_total_bytes", quota_bump)
        result = asyncio.run(main.delete_file_endpoint(
            mock.Mock(),
            main.DeleteFileRequest(vault_name="synthetic", file_id=FILE_ID, pin="123456"),
            {"vault_id": VAULT_ID},
        ))
        quota_bump.assert_called_once_with(VAULT_ID, -37)
    else:
        monkeypatch.setattr(vault_manage_routes, "get_db", lambda: db)
        result = vault_manage_routes._delete_file_impl(
            vault_manage_routes.FileDeleteRequest(
                vault_name="synthetic", file_id=FILE_ID, pin="123456",
            ), VAULT_ID,
        )
    assert result["status"] == "deleted"
    assert db.commits == 1
    assert db.state == {"legacy": None, "v2": None, "chunks": [], "quota": 100}
    assert sum(q.startswith("delete from file_v2_records") for q in db.queries) == 1
    assert sum(q.startswith("delete from uploaded_files") for q in db.queries) == 1


@pytest.mark.parametrize("marked,verified", [(False, False), (True, True)])
@pytest.mark.parametrize("path", ["primary", "vault_manage"])
def test_unmarked_or_verified_v2_cannot_be_removed_by_legacy_delete(
    monkeypatch, marked, verified, path,
):
    import main
    from routes import vault_manage_routes
    import pin_only_action_gate

    db = _Db(marked=marked, verified=verified)
    monkeypatch.setattr(pin_only_action_gate, "authorize_pin_only_action", mock.Mock())
    monkeypatch.setattr(vault_manage_routes, "authorize_pin_only_action", mock.Mock())
    if path == "primary":
        monkeypatch.setattr(main, "get_db", lambda: db)
        monkeypatch.setattr(main, "bump_vault_total_bytes", mock.Mock())
        action = lambda: asyncio.run(main.delete_file_endpoint(
            mock.Mock(), main.DeleteFileRequest(
                vault_name="synthetic", file_id=FILE_ID, pin="123456",
            ), {"vault_id": VAULT_ID},
        ))
    else:
        monkeypatch.setattr(vault_manage_routes, "get_db", lambda: db)
        action = lambda: vault_manage_routes._delete_file_impl(
            vault_manage_routes.FileDeleteRequest(
                vault_name="synthetic", file_id=FILE_ID, pin="123456",
            ), VAULT_ID,
        )
    with pytest.raises(HTTPException) as raised:
        action()
    assert raised.value.status_code == 409
    assert db.state == db.initial
    assert db.commits == 0
    assert not any(q.startswith("delete from") for q in db.queries)


@pytest.mark.parametrize("path", ["primary", "vault_manage"])
def test_failed_old_row_delete_rolls_back_stage_cleanup(monkeypatch, path):
    import main
    from routes import vault_manage_routes
    import pin_only_action_gate

    db = _Db(missing_old_delete=True)
    monkeypatch.setattr(pin_only_action_gate, "authorize_pin_only_action", mock.Mock())
    monkeypatch.setattr(vault_manage_routes, "authorize_pin_only_action", mock.Mock())
    if path == "primary":
        monkeypatch.setattr(main, "get_db", lambda: db)
        monkeypatch.setattr(main, "bump_vault_total_bytes", mock.Mock())
        action = lambda: asyncio.run(main.delete_file_endpoint(
            mock.Mock(), main.DeleteFileRequest(
                vault_name="synthetic", file_id=FILE_ID, pin="123456",
            ), {"vault_id": VAULT_ID},
        ))
    else:
        monkeypatch.setattr(vault_manage_routes, "get_db", lambda: db)
        action = lambda: vault_manage_routes._delete_file_impl(
            vault_manage_routes.FileDeleteRequest(
                vault_name="synthetic", file_id=FILE_ID, pin="123456",
            ), VAULT_ID,
        )
    with pytest.raises(HTTPException) as raised:
        action()
    assert raised.value.status_code == 404
    assert db.rollbacks == 1
    assert db.commits == 0
    assert db.state == db.initial


def test_manifest_persists_stage_marker_and_retry_cannot_change_it(monkeypatch):
    from routes import file_v2_routes

    class ManifestCursor:
        def __init__(self):
            self.recorded_marker = None
            self.result = None
            self.queries = []

        def execute(self, sql, params):
            query = " ".join(sql.lower().split())
            self.queries.append(query)
            if query.startswith("select pg_advisory"):
                self.result = None
            elif query.startswith("select 1 from uploaded_files"):
                self.result = (1,)
            elif query.startswith("insert into file_v2_records"):
                assert "migrating_legacy" in query
                marker = params[-1]
                if self.recorded_marker is None:
                    self.recorded_marker = marker
                    self.result = (FILE_ID,)
                else:
                    self.result = None
            elif query.startswith("select 1 from file_v2_records"):
                assert "migrating_legacy=%s" in query
                self.result = (1,) if params[-2] == self.recorded_marker else None
            else:
                raise AssertionError(f"Unexpected SQL: {query[:100]}")

        def fetchone(self):
            return self.result

    class ManifestDb:
        def __init__(self):
            self.cur = ManifestCursor()
            self.commits = 0

        def cursor(self):
            return self.cur

        def commit(self):
            self.commits += 1

        def rollback(self):
            pass

        def close(self):
            pass

    db = ManifestDb()
    monkeypatch.setattr(file_v2_routes, "get_db", lambda: db)
    monkeypatch.setattr(file_v2_routes, "require_content_write", mock.Mock())
    monkeypatch.setattr(file_v2_routes, "_enabled", lambda *_args: None)
    monkeypatch.setattr(file_v2_routes, "_new_files_enabled", lambda: True)
    marked = file_v2_routes.Manifest(
        file_id=FILE_ID, crypto_version="client_mvk_v2",
        manifest_ciphertext="AQID", total_bytes=37,
        chunk_size=1024, chunk_count=1, migrating_legacy=True,
    )
    principal = {"vault_id": VAULT_ID}
    file_v2_routes.create_manifest(marked, principal)
    file_v2_routes.create_manifest(marked, principal)
    assert db.cur.recorded_marker is True
    assert db.commits == 2
    with pytest.raises(HTTPException) as raised:
        file_v2_routes.create_manifest(
            marked.model_copy(update={"migrating_legacy": False}), principal,
        )
    assert raised.value.status_code == 409
    assert raised.value.detail == "file_v2_manifest_conflict"
    assert db.commits == 2
