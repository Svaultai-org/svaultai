"""Synthetic bounds and immutable retries for client-encrypted file staging."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes import file_v2_routes as route


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class _ChunkCursor:
    def __init__(self, state):
        self.state = state
        self.result = None

    def execute(self, sql, params):
        compact = " ".join(sql.lower().split())
        if compact.startswith("select verification_state, lifecycle_state"):
            self.result = self.state["record"]
        elif compact.startswith("insert into file_v2_chunks"):
            file_id, index, ciphertext = params
            key = (file_id, index)
            if key not in self.state["chunks"]:
                self.state["chunks"][key] = ciphertext
                self.result = (index,)
            else:
                self.result = None
        elif compact.startswith("select 1 from file_v2_chunks"):
            file_id, index, ciphertext = params
            self.result = (1,) if self.state["chunks"].get((file_id, index)) == ciphertext else None
        else:
            raise AssertionError(f"unexpected SQL: {compact}")

    def fetchone(self):
        return self.result


class _ChunkConnection:
    def __init__(self, record):
        self.state = {"record": record, "chunks": {}}
        self.cursor_object = _ChunkCursor(self.state)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_object

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@pytest.fixture
def staged(monkeypatch):
    conn = _ChunkConnection(("not_verified", "file_v2_written", 1024, 1, 3))
    monkeypatch.setattr(route, "get_db", lambda: conn)
    monkeypatch.setattr(route, "_enabled", lambda *_: None)
    monkeypatch.setattr(route, "require_content_write", lambda *_: None)
    return conn


def test_new_file_manifest_is_default_off_before_db(monkeypatch):
    monkeypatch.delenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", raising=False)
    monkeypatch.setattr(route, "_enabled", lambda *_: None)
    monkeypatch.setattr(route, "require_content_write", lambda *_: None)
    monkeypatch.setattr(route, "get_db", lambda: pytest.fail("DB reached"))
    payload = route.Manifest(
        file_id="synthetic", crypto_version="client_mvk_v2",
        manifest_ciphertext="AQID", total_bytes=3, chunk_size=1024,
        chunk_count=1,
    )
    with pytest.raises(HTTPException) as raised:
        route.create_manifest(payload, {"vault_id": "synthetic-vault"})
    assert raised.value.status_code == 404
    assert raised.value.detail == "new_file_v2_disabled"


@pytest.mark.parametrize("field,value", [
    ("total_bytes", route.MAX_FILE_BYTES + 1),
    ("chunk_size", route.MAX_CHUNK_BYTES + 1),
    ("chunk_count", route.MAX_CHUNKS + 1),
])
def test_manifest_caps_are_enforced(field, value):
    payload = {
        "file_id": "synthetic", "crypto_version": "client_mvk_v2",
        "manifest_ciphertext": "AQID", "total_bytes": 3,
        "chunk_size": 1024, "chunk_count": 1,
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        route.Manifest(**payload)


def test_manifest_requires_exact_chunk_count():
    with pytest.raises(ValidationError, match="file_v2_chunk_count_mismatch"):
        route.Manifest(
            file_id="synthetic", crypto_version="client_mvk_v2",
            manifest_ciphertext="AQID", total_bytes=1025,
            chunk_size=1024, chunk_count=1,
        )


def test_chunk_retry_with_same_bytes_is_idempotent(staged):
    payload = route.Chunk(
        file_id="synthetic", chunk_index=0,
        ciphertext=_encoded(b"a" * (3 + route.GCM_FRAMING_BYTES)),
    )
    principal = {"vault_id": "synthetic-vault"}
    assert route.put_chunk(payload, principal) == route.put_chunk(payload, principal)
    assert staged.commits == 2
    assert len(staged.state["chunks"]) == 1


def test_chunk_retry_with_different_bytes_is_rejected(staged):
    first = route.Chunk(file_id="synthetic", chunk_index=0,
                        ciphertext=_encoded(b"a" * (3 + route.GCM_FRAMING_BYTES)))
    second = first.model_copy(update={
        "ciphertext": _encoded(b"b" * (3 + route.GCM_FRAMING_BYTES)),
    })
    principal = {"vault_id": "synthetic-vault"}
    route.put_chunk(first, principal)
    with pytest.raises(HTTPException) as raised:
        route.put_chunk(second, principal)
    assert raised.value.status_code == 409
    assert raised.value.detail == "file_v2_chunk_conflict"
    assert staged.commits == 1
    assert staged.rollbacks == 1


@pytest.mark.parametrize("index,length,detail", [
    (1, 31, "file_v2_chunk_index_out_of_range"),
    (0, 30, "file_v2_chunk_length_mismatch"),
])
def test_chunk_framing_is_checked_before_write(staged, index, length, detail):
    payload = route.Chunk(
        file_id="synthetic", chunk_index=index, ciphertext=_encoded(b"x" * length),
    )
    with pytest.raises(HTTPException) as raised:
        route.put_chunk(payload, {"vault_id": "synthetic-vault"})
    assert raised.value.status_code == 400
    assert raised.value.detail == detail
    assert staged.state["chunks"] == {}


def test_published_new_file_cannot_be_changed_or_deleted(staged):
    staged.state["record"] = ("not_verified", "client_v2_ready", 1024, 1, 3)
    payload = route.Chunk(
        file_id="synthetic", chunk_index=0,
        ciphertext=_encoded(b"x" * (3 + route.GCM_FRAMING_BYTES)),
    )
    with pytest.raises(HTTPException) as put:
        route.put_chunk(payload, {"vault_id": "synthetic-vault"})
    assert put.value.status_code == 409
    assert put.value.detail == "file_v2_verified_immutable"

    db = MagicMock()
    db.cursor.return_value.fetchone.return_value = ("not_verified", "client_v2_ready")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(route, "get_db", lambda: db)
        with pytest.raises(HTTPException) as delete:
            route.delete_file("synthetic", {"vault_id": "synthetic-vault"})
    assert delete.value.status_code == 409
    assert delete.value.detail == "file_v2_verified_delete_requires_confirmed_path"


def test_stale_cleanup_excludes_published_and_legacy_migration_rows(monkeypatch):
    monkeypatch.setattr(route, "_enabled", lambda *_: None)
    db = MagicMock()
    db.cursor.return_value.fetchall.return_value = []
    monkeypatch.setattr(route, "get_db", lambda: db)
    assert route.list_files({"vault_id": "synthetic-vault"}) == {"files": []}
    sql = db.cursor.return_value.execute.call_args_list[0].args[0]
    assert "INTERVAL '24 hours'" in sql
    assert "lifecycle_state='file_v2_written'" in sql
    assert "NOT EXISTS" in sql and "uploaded_files" in sql
