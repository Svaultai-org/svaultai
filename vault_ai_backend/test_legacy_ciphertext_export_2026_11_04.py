"""Synthetic, database-free checks for the OPAQUE-gated legacy export."""

from __future__ import annotations

import json
import time
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routes import legacy_ciphertext_export_routes as export


VAULT = "11111111-1111-1111-1111-111111111111"
OTHER_VAULT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SESSION = "22222222-2222-2222-2222-222222222222"
OTHER_SESSION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PRINCIPAL = {"vault_id": VAULT, "token_id": SESSION}


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.rows = []
        self.executed = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        if normalized.startswith("SELECT vault_handle IS NOT NULL"):
            self.rows = [(True,)]
        elif normalized.startswith("INSERT INTO vault_zk_login_slots"):
            token, vault_id, state, expires_at = params
            self.db.grants[token] = {
                "vault_id": vault_id,
                "state": bytes(state),
                "expires_at": expires_at,
            }
            self.rows = []
        elif normalized.startswith("SELECT server_state FROM vault_zk_login_slots"):
            token, vault_id = params
            grant = self.db.grants.get(token)
            if grant is None or grant["vault_id"] != vault_id:
                self.rows = []
            else:
                self.rows = [{"server_state": grant["state"]}]
        elif normalized.startswith("UPDATE vault_zk_login_slots SET server_state"):
            state, token, vault_id = params
            assert self.db.grants[token]["vault_id"] == vault_id
            self.db.grants[token]["state"] = bytes(state)
            self.rows = []
        elif normalized.startswith("SELECT id, LEFT(item_type"):
            self.rows = [{
                "id": 7,
                "item_type": "login",
                "service": "example",
                "ciphertext_chars": 16,
            }]
        elif normalized.startswith("SELECT LENGTH(encrypted_data)"):
            vault_id, item_id = params
            if vault_id != VAULT or item_id != 7:
                self.rows = []
            else:
                ct = "SYNTHETIC_B64_CT"
                self.rows = [{"total_chars": len(ct)}]
        elif normalized.startswith("SELECT encrypted_data, item_type, service,"):
            vault_id, item_id = params
            self.rows = [{
                "encrypted_data": "SYNTHETIC_B64_CT",
                "item_type": "login",
                "service": "example",
                "item_type_ciphertext": None,
                "service_ciphertext": None,
            }] if vault_id == VAULT and item_id == 7 else []
        elif normalized.startswith("SELECT LENGTH(encrypted_file_data) AS total_chars"):
            vault_id, file_id = params
            self.rows = [{
                "total_chars": len(self.db.file["encrypted_file_data"]),
            }] if vault_id == VAULT and file_id == self.db.file["id"] else []
        elif normalized.startswith("SELECT LENGTH(encrypted_file_data) AS legacy_chars"):
            vault_id, file_id = params
            self.rows = [{
                "legacy_chars": len(self.db.file["encrypted_file_data"]),
                "path_bytes": len((self.db.file["relative_path"] or "").encode()),
                "text_bytes": len((self.db.file["extracted_text"] or "").encode()),
            }] if vault_id == VAULT and file_id == self.db.file["id"] else []
        elif normalized.startswith("SELECT encrypted_file_data, file_size,"):
            vault_id, file_id = params
            self.rows = [dict(self.db.file)] if (
                vault_id == VAULT and file_id == self.db.file["id"]
            ) else []
        else:
            raise AssertionError(f"Unexpected SQL shape: {normalized[:80]}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConnection:
    def __init__(self, db):
        self.db = db
        self.cursor_obj = FakeCursor(db)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **_kwargs):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class FakeDb:
    def __init__(self):
        self.grants = {}
        self.connections = []
        self.file = {
            "id": "synthetic-file",
            "encrypted_file_data": "SYNTHETIC_B64_FILE",
            "file_size": 3,
            "file_name": "synthetic.txt",
            "saved_name": None,
            "content_type": "text/plain",
            "detected_type": None,
            "detected_service": None,
            "asset_type": None,
            "relative_path": "synthetic/folder/file.txt",
            "extracted_text": "synthetic private document text",
            "file_name_ciphertext": None,
            "saved_name_ciphertext": None,
            "content_type_ciphertext": None,
            "detected_type_ciphertext": None,
            "detected_service_ciphertext": None,
            "asset_type_ciphertext": None,
        }

    def connect(self):
        conn = FakeConnection(self)
        self.connections.append(conn)
        return conn


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic_session_signing_secret_for_offline_tests_123456")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_EXPORT_ENABLED", "true")
    from auth_local import reset_secret_for_tests
    reset_secret_for_tests()
    db = FakeDb()
    monkeypatch.setattr(export, "get_db", db.connect)
    consumed = mock.Mock()
    monkeypatch.setattr(export, "consume_recent_zk_proof", consumed)
    yield db, consumed
    reset_secret_for_tests()


def _start(db, consumed):
    result = export.legacy_export_start(
        export.LegacyExportStartRequest(zk_proof_token="synthetic-proof"),
        PRINCIPAL,
    )
    consumed.assert_called_once_with("synthetic-proof", PRINCIPAL)
    assert result["pages_remaining"] == export.GRANT_MAX_PAGES
    assert result["bytes_remaining"] == export.GRANT_MAX_BYTES
    assert result["export_token"] in db.grants
    return result


def test_start_consumes_one_opaque_proof_and_binds_grant(runtime):
    db, consumed = runtime
    result = _start(db, consumed)
    token = result["export_token"]
    assert export._grant_belongs_to_session(token, PRINCIPAL)
    assert not export._grant_belongs_to_session(
        token, {**PRINCIPAL, "token_id": OTHER_SESSION},
    )
    assert not export._grant_belongs_to_session(
        token, {**PRINCIPAL, "vault_id": OTHER_VAULT},
    )
    assert not export._grant_belongs_to_session(
        token, PRINCIPAL, now_ts=int(time.time()) + 301,
    )


def test_export_http_responses_are_not_stored(runtime, monkeypatch):
    app = FastAPI()
    app.include_router(export.router)
    app.dependency_overrides[export.verify_trusted_device] = lambda: PRINCIPAL
    client = TestClient(app)
    started = client.post(
        "/vault/legacy-ciphertext/export/start",
        json={"zk_proof_token": "synthetic-proof"},
    )
    assert started.status_code == 200
    assert started.headers["cache-control"] == "no-store"
    grant = started.json()["export_token"]
    page = client.post(
        "/vault/legacy-ciphertext/export/page",
        json={"export_token": grant, "sequence": 0, "mode": "list_items"},
    )
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED", "true")
    extra = client.post(
        "/vault/legacy-ciphertext/export/page",
        json={"export_token": grant, "sequence": 1,
              "mode": "read_file_extra", "file_id": "synthetic-file"},
    )
    assert extra.status_code == 200
    assert extra.headers["cache-control"] == "no-store"


def test_page_is_bounded_and_sequence_replay_fails(runtime):
    db, consumed = runtime
    token = _start(db, consumed)["export_token"]
    request = export.LegacyExportPageRequest(
        export_token=token, sequence=0, mode="list_items",
    )
    result = export.legacy_export_page(request, PRINCIPAL)
    assert result["records"] == [{
        "item_id": 7, "item_type": "login", "service": "example",
        "item_type_ciphertext": None, "service_ciphertext": None,
        "ciphertext_chars": 16,
    }]
    assert result["next_sequence"] == 1
    assert result["pages_remaining"] == export.GRANT_MAX_PAGES - 1
    assert result["bytes_remaining"] < export.GRANT_MAX_BYTES
    with pytest.raises(HTTPException) as exc:
        export.legacy_export_page(request, PRINCIPAL)
    assert exc.value.status_code == 409


def test_cross_vault_and_session_pages_never_query_database(runtime):
    db, consumed = runtime
    token = _start(db, consumed)["export_token"]
    before = len(db.connections)
    request = export.LegacyExportPageRequest(
        export_token=token, sequence=0, mode="list_items",
    )
    for principal in (
        {**PRINCIPAL, "vault_id": OTHER_VAULT},
        {**PRINCIPAL, "token_id": OTHER_SESSION},
    ):
        with pytest.raises(HTTPException) as exc:
            export.legacy_export_page(request, principal)
        assert exc.value.status_code == 401
    assert len(db.connections) == before


def test_item_chunk_returns_only_ciphertext_and_enforces_budget(runtime):
    db, consumed = runtime
    token = _start(db, consumed)["export_token"]
    request = export.LegacyExportPageRequest(
        export_token=token, sequence=0, mode="read_item",
        item_id=7, offset=0, max_chars=8,
    )
    result = export.legacy_export_page(request, PRINCIPAL)
    assert result["ciphertext_chunk"] == "SYNTHETI"
    assert "pin" not in result
    assert "encrypted_data" not in result
    assert result["next_offset"] == 8
    assert result["done"] is False
    assert len(result["source_snapshot"]) == 43
    assert result["source_metadata"]["service"] == "example"

    state = json.loads(db.grants[token]["state"].decode())
    state["bytes_left"] = 1
    db.grants[token]["state"] = json.dumps(state).encode()
    with pytest.raises(HTTPException) as exc:
        export.legacy_export_page(
            export.LegacyExportPageRequest(
                export_token=token, sequence=1, mode="read_item",
                item_id=7, offset=8, max_chars=8,
            ), PRINCIPAL,
        )
    assert exc.value.status_code == 413
    assert json.loads(db.grants[token]["state"].decode())["sequence"] == 1


def test_file_extra_export_is_default_off_before_grant_or_database(runtime, monkeypatch):
    db, _ = runtime
    monkeypatch.delenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED", raising=False)
    before = len(db.connections)
    with pytest.raises(HTTPException) as blocked:
        export.legacy_export_page(export.LegacyExportPageRequest(
            export_token="synthetic-grant", sequence=0,
            mode="read_file_extra", file_id=db.file["id"],
        ), PRINCIPAL)
    assert blocked.value.status_code == 404
    assert len(db.connections) == before


def test_file_extras_are_one_proof_bound_page_with_source_snapshot(runtime, monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED", "true")
    db, consumed = runtime
    token = _start(db, consumed)["export_token"]
    result = export.legacy_export_page(export.LegacyExportPageRequest(
        export_token=token, sequence=0, mode="read_file_extra",
        file_id=db.file["id"],
    ), PRINCIPAL)
    assert result["legacy_extra"] == {
        "relative_path": "synthetic/folder/file.txt",
        "extracted_text": "synthetic private document text",
    }
    assert len(result["source_snapshot"]) == 43
    assert "encrypted_file_data" not in result
    assert "pin" not in result
    with pytest.raises(HTTPException) as replay:
        export.legacy_export_page(export.LegacyExportPageRequest(
            export_token=token, sequence=0, mode="read_file_extra",
            file_id=db.file["id"],
        ), PRINCIPAL)
    assert replay.value.status_code == 409


def test_normal_file_page_discloses_only_extra_presence(runtime):
    db, consumed = runtime
    token = _start(db, consumed)["export_token"]
    result = export.legacy_export_page(export.LegacyExportPageRequest(
        export_token=token, sequence=0, mode="read_file",
        file_id=db.file["id"], offset=0, max_chars=100,
    ), PRINCIPAL)
    assert result["source_metadata"]["has_legacy_extra_data"] is True
    assert "extracted_text" not in result["source_metadata"]
    assert "relative_path" not in result["source_metadata"]
    assert result["ciphertext_chunk"] == db.file["encrypted_file_data"]


def test_oversized_extra_text_is_rejected_before_full_row_read(runtime, monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED", "true")
    db, consumed = runtime
    db.file["extracted_text"] = "x" * (export.MAX_FILE_EXTRA_BYTES + 1)
    token = _start(db, consumed)["export_token"]
    with pytest.raises(HTTPException) as large:
        export.legacy_export_page(export.LegacyExportPageRequest(
            export_token=token, sequence=0, mode="read_file_extra",
            file_id=db.file["id"],
        ), PRINCIPAL)
    assert large.value.status_code == 413
    executed = db.connections[-1].cursor_obj.executed
    assert not any(sql.startswith("SELECT encrypted_file_data, file_size,")
                   for sql, _ in executed)


def test_v3_extra_export_is_default_off_and_preserves_full_synthetic_text(
    runtime, monkeypatch,
):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED", "true")
    monkeypatch.delenv(export.FILE_EXTRA_V3_FLAG, raising=False)
    db, consumed = runtime
    db.file["extracted_text"] = "private synthetic text " * 10_000
    assert export.MAX_FILE_EXTRA_BYTES < len(db.file["extracted_text"].encode())
    assert len(db.file["extracted_text"].encode()) < export.MAX_FILE_EXTRA_V3_BYTES
    token = _start(db, consumed)["export_token"]
    request = export.LegacyExportPageRequest(
        export_token=token, sequence=0, mode="read_file_extra_v3",
        file_id=db.file["id"],
    )
    with pytest.raises(HTTPException) as disabled:
        export.legacy_export_page(request, PRINCIPAL)
    assert disabled.value.status_code == 404
    assert db.connections[-1].cursor_obj.executed[-1][0].startswith(
        "INSERT INTO vault_zk_login_slots"
    )

    monkeypatch.setenv(export.FILE_EXTRA_V3_FLAG, "true")
    result = export.legacy_export_page(request, PRINCIPAL)
    assert result["legacy_extra_version"] == 3
    assert result["legacy_extra"]["extracted_text"] == db.file["extracted_text"]
    assert result["source_snapshot"]
    assert result["mode"] == "read_file_extra_v3"


def test_v3_extra_export_rejects_over_256k_before_full_row_read(
    runtime, monkeypatch,
):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED", "true")
    monkeypatch.setenv(export.FILE_EXTRA_V3_FLAG, "true")
    db, consumed = runtime
    db.file["extracted_text"] = "x" * (export.MAX_FILE_EXTRA_V3_BYTES + 1)
    token = _start(db, consumed)["export_token"]
    with pytest.raises(HTTPException) as too_large:
        export.legacy_export_page(export.LegacyExportPageRequest(
            export_token=token, sequence=0, mode="read_file_extra_v3",
            file_id=db.file["id"],
        ), PRINCIPAL)
    assert too_large.value.status_code == 413
    executed = db.connections[-1].cursor_obj.executed
    assert not any(sql.startswith("SELECT encrypted_file_data, file_size,")
                   for sql, _ in executed)


def test_v3_extra_export_requires_above_64k_and_counts_utf8_bytes(
    runtime, monkeypatch,
):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED", "true")
    monkeypatch.setenv(export.FILE_EXTRA_V3_FLAG, "true")
    db, consumed = runtime
    token = _start(db, consumed)["export_token"]
    request = export.LegacyExportPageRequest(
        export_token=token, sequence=0, mode="read_file_extra_v3",
        file_id=db.file["id"],
    )
    db.file["extracted_text"] = "é" * (32 * 1024)
    with pytest.raises(HTTPException) as small:
        export.legacy_export_page(request, PRINCIPAL)
    assert small.value.detail == "legacy_file_extra_v3_size_required"
    db.file["extracted_text"] = "é" * (128 * 1024 + 1)
    with pytest.raises(HTTPException) as large:
        export.legacy_export_page(request, PRINCIPAL)
    assert large.value.status_code == 413
    assert json.loads(db.grants[token]["state"])["sequence"] == 0
