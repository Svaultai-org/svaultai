"""Offline grant tests for bounded, PIN-free legacy ciphertext export."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


VAULT_A = "11111111-1111-1111-1111-111111111111"
VAULT_B = "22222222-2222-2222-2222-222222222222"
SESSION_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SESSION_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.one = None
        self.many = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.lower().split())
        self.one = None
        self.many = []
        if "select vault_handle is not null from vaults" in normalized:
            self.one = (True,)
        elif "insert into vault_zk_login_slots" in normalized:
            token, vault_id, state, expiry = params
            self.db.slots[token] = (vault_id, state, expiry)
        elif "select server_state from vault_zk_login_slots" in normalized:
            token, vault_id = params
            slot = self.db.slots.get(token)
            if slot and slot[0] == vault_id and slot[2] > datetime.now(timezone.utc):
                self.one = {"server_state": slot[1]}
        elif "select id, left(item_type" in normalized:
            vault_id, after_id, limit = params
            self.many = [row for row in self.db.items
                         if row["id"] > after_id][:limit]
        elif "select id, file_size" in normalized:
            vault_id, after_id, limit = params
            self.many = [row for row in self.db.files
                         if row["id"] > after_id][:limit]
        elif "select length(encrypted_data)" in normalized:
            vault_id, record_id = params
            text = self.db.item_ciphertext[record_id]
            self.one = {"total_chars": len(text)}
        elif normalized.startswith("select encrypted_data, item_type, service,"):
            vault_id, record_id = params
            self.one = {
                "encrypted_data": self.db.item_ciphertext[record_id],
                "item_type": "login", "service": "synthetic",
                "item_type_ciphertext": None,
                "service_ciphertext": None,
                "payload_ciphertext": None,
            }
        elif "select length(encrypted_file_data)" in normalized:
            vault_id, record_id = params
            text = self.db.file_ciphertext[record_id]
            self.one = {"total_chars": len(text)}
        elif normalized.startswith("select encrypted_file_data, file_size,"):
            vault_id, record_id = params
            self.one = {
                "encrypted_file_data": self.db.file_ciphertext[record_id],
                "file_size": 42,
                "file_name": "synthetic-file.txt",
                "saved_name": None,
                "content_type": "text/plain",
                "detected_type": None,
                "detected_service": None,
                "asset_type": "file",
                "relative_path": None,
                "extracted_text": None,
                **{name: None for name in (
                    "file_name_ciphertext", "saved_name_ciphertext",
                    "content_type_ciphertext", "detected_type_ciphertext",
                    "detected_service_ciphertext", "asset_type_ciphertext",
                )},
            }
        elif "update vault_zk_login_slots set server_state" in normalized:
            state, token, vault_id = params
            existing = self.db.slots[token]
            self.db.slots[token] = (vault_id, state, existing[2])
        else:
            raise AssertionError(f"unexpected SQL in synthetic export fixture: {normalized[:100]}")

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class _Db:
    def __init__(self):
        self.slots = {}
        self.items = [{"id": 7, "item_type": "login", "service": "synthetic",
                       "ciphertext_chars": 11}]
        self.files = [{
            "id": "synthetic-file-1", "file_size": 42,
            "content_type": "text/plain", "ciphertext_chars": 12,
            "extra_text_bytes": None, "extra_path_bytes": None,
            **{name: None for name in (
                "file_name_ciphertext", "saved_name_ciphertext",
                "content_type_ciphertext", "detected_type_ciphertext",
                "detected_service_ciphertext", "asset_type_ciphertext",
            )},
        }]
        self.item_ciphertext = {7: "ENC-ITEM-07"}
        self.file_ciphertext = {"synthetic-file-1": "ENC-FILE-042"}
        self.rollbacks = 0

    def cursor(self, cursor_factory=None):
        return _Cursor(self)

    def commit(self):
        pass

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@pytest.fixture
def export_harness():
    from routes import legacy_ciphertext_export_routes as export

    db = _Db()
    selected = {"principal": {"vault_id": VAULT_A, "token_id": SESSION_A}}
    app = FastAPI()
    app.include_router(export.router)
    app.dependency_overrides[export.verify_trusted_device] = lambda: selected["principal"]
    with (
        mock.patch.dict("os.environ", {"VAULTAI_ZK_LEGACY_EXPORT_ENABLED": "true"}),
        mock.patch.object(export, "get_db", return_value=db),
        mock.patch.object(export, "_get_secret", return_value=b"synthetic-export-secret-32-bytes-long"),
        mock.patch.object(export, "consume_recent_zk_proof") as consume,
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield export, client, db, selected, consume


def _start(client):
    response = client.post("/vault/legacy-ciphertext/export/start", json={
        "zk_proof_token": "synthetic-opaque-proof",
    })
    assert response.status_code == 200, response.text
    return response.json()["export_token"]


def _page(client, token, sequence=0, **extra):
    return client.post("/vault/legacy-ciphertext/export/page", json={
        "export_token": token,
        "sequence": sequence,
        "mode": "list_items",
        **extra,
    })


def test_start_consumes_proof_and_returns_bounded_grant(export_harness):
    export, client, db, selected, consume = export_harness
    token = _start(client)
    consume.assert_called_once_with("synthetic-opaque-proof", selected["principal"])
    assert token.startswith("e1.")
    assert json.loads(db.slots[token][1]) == {
        "sequence": 0,
        "pages_left": export.GRANT_MAX_PAGES,
        "bytes_left": export.GRANT_MAX_BYTES,
    }


@pytest.mark.parametrize("other", [
    {"vault_id": VAULT_A, "token_id": SESSION_B},
    {"vault_id": VAULT_B, "token_id": SESSION_A},
])
def test_grant_cannot_cross_session_or_vault(export_harness, other):
    export, client, db, selected, consume = export_harness
    token = _start(client)
    selected["principal"] = other
    assert _page(client, token).status_code == 401
    assert json.loads(db.slots[token][1])["sequence"] == 0


def test_page_sequence_replay_is_rejected(export_harness):
    export, client, db, selected, consume = export_harness
    token = _start(client)
    first = _page(client, token)
    assert first.status_code == 200, first.text
    assert first.json()["next_sequence"] == 1
    assert _page(client, token).status_code == 409
    assert _page(client, token, sequence=1).status_code == 200


def test_expired_grant_rejected_before_read(export_harness):
    export, client, db, selected, consume = export_harness
    token = _start(client)
    expiry_ts = int(token.split(".")[1])
    with mock.patch.object(export.time, "time", return_value=expiry_ts + 1):
        assert _page(client, token).status_code == 401
    assert json.loads(db.slots[token][1])["sequence"] == 0


def test_per_page_budget_fails_without_spending_sequence(export_harness):
    export, client, db, selected, consume = export_harness
    token = _start(client)
    with mock.patch.object(export, "PAGE_MAX_BYTES", 64):
        limited = _page(client, token)
    assert limited.status_code == 413
    assert json.loads(db.slots[token][1])["sequence"] == 0
    assert _page(client, token).status_code == 200


def test_list_and_read_return_ciphertext_only(export_harness):
    export, client, db, selected, consume = export_harness
    token = _start(client)
    listed = _page(client, token)
    assert listed.status_code == 200
    assert listed.json()["records"][0]["item_id"] == 7
    assert "encrypted_data" not in listed.text
    item = _page(client, token, sequence=1, mode="read_item", item_id=7)
    assert item.status_code == 200, item.text
    assert item.json()["ciphertext_chunk"] == db.item_ciphertext[7]
    assert len(item.json()["source_snapshot"]) == 43
    assert "plaintext" not in item.text
    files = _page(client, token, sequence=2, mode="list_files")
    assert files.status_code == 200, files.text
    assert files.json()["records"][0]["file_id"] == "synthetic-file-1"
    file_read = _page(client, token, sequence=3, mode="read_file",
                      file_id="synthetic-file-1")
    assert file_read.status_code == 200, file_read.text
    assert file_read.json()["ciphertext_chunk"] == db.file_ciphertext["synthetic-file-1"]
    assert file_read.json()["source_metadata"]["file_name"] == "synthetic-file.txt"
    assert "plaintext" not in file_read.text


@pytest.mark.parametrize("field", ["pin", "vault_key", "file_content"])
def test_request_rejects_secret_fields(export_harness, field):
    export, client, db, selected, consume = export_harness
    token = _start(client)
    response = _page(client, token, **{field: "synthetic-secret"})
    assert response.status_code == 422
