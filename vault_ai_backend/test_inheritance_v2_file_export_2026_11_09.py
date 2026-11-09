"""Released inheritance file reads use synthetic ciphertext only."""

from __future__ import annotations

import base64
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from inheritance_protocol import ZK_BENEFICIARY_V2_MARKER
from routes import inheritance_v2_file_export_routes as export
from security_headers import SecurityHeadersMiddleware


BENEFICIARY = {"vault_id": "synthetic-beneficiary"}
FILE_ID = "v2-synthetic"
MANIFEST = b"\x01" + b"n" * 12 + b"m" * 32 + b"t" * 16
CHUNK = b"\x01" + b"n" * 12 + b"data" + b"t" * 16


class FakeDb:
    def __init__(self):
        self.link = {
            "passer_vault_id": "synthetic-owner",
            "wrapped_vault_key": ZK_BENEFICIARY_V2_MARKER,
            "pairing_state": "released",
            "crypto_version": 2,
        }
        self.incomplete = False
        self.file = {
            "file_id": FILE_ID,
            "crypto_version": "client_mvk_v2",
            "manifest_ciphertext": MANIFEST,
            "total_bytes": 4,
            "chunk_size": 4,
            "chunk_count": 1,
            "lifecycle_state": "client_v2_ready",
            "verification_state": "client_verified",
            "saved_name_override_ciphertext": None,
            "name_version": 0,
            "migration_metadata_version": 1,
        }
        self.queries = []

    def cursor(self, **_kwargs):
        return FakeCursor(self)

    def close(self):
        pass


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.value = None

    def execute(self, sql, params):
        normalized = " ".join(sql.split()).upper()
        self.db.queries.append((normalized, params))
        if "FROM BENEFICIARY_LINKS BL" in normalized:
            self.value = self.db.link if params == (
                17, BENEFICIARY["vault_id"],
            ) else None
        elif "SELECT 1 FROM UPLOADED_FILES U" in normalized:
            self.value = {"exists": 1} if self.db.incomplete else None
        elif "SELECT R.FILE_ID, R.TOTAL_BYTES" in normalized:
            self.value = [self.db.file] if params[:2] == (
                "synthetic-owner", "",
            ) else []
        elif "SELECT R.FILE_ID, R.CRYPTO_VERSION" in normalized:
            self.value = self.db.file if params == (
                FILE_ID, "synthetic-owner",
            ) else None
        elif "SELECT C.CIPHERTEXT FROM FILE_V2_CHUNKS C" in normalized:
            self.value = {"ciphertext": CHUNK} if params == (
                FILE_ID, 0, "synthetic-owner",
            ) else None
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.value

    def fetchall(self):
        return self.value


@pytest.fixture
def ready(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(export, "get_db", lambda: db)
    monkeypatch.setattr(export, "require_file_read", mock.Mock())
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    monkeypatch.setenv(export.FLAG_NAME, "true")
    return db


def test_file_export_disabled_before_database(monkeypatch):
    monkeypatch.delenv(export.FLAG_NAME, raising=False)
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED", "true")
    monkeypatch.setattr(export, "get_db", lambda: pytest.fail("database opened"))
    with pytest.raises(HTTPException) as err:
        export.list_released_v2_files(
            17, after_file_id="", limit=50, principal=BENEFICIARY,
        )
    assert err.value.status_code == 404


def test_only_released_beneficiary_can_read_owner_files(ready):
    with pytest.raises(HTTPException) as wrong:
        export.list_released_v2_files(
            17, after_file_id="", limit=50,
            principal={"vault_id": "another-vault"},
        )
    assert wrong.value.status_code == 404
    assert len(ready.queries) == 1
    ready.queries.clear()
    ready.link["pairing_state"] = "approved"
    with pytest.raises(HTTPException) as early:
        export.get_released_v2_file_manifest(17, FILE_ID, BENEFICIARY)
    assert early.value.status_code == 404
    assert len(ready.queries) == 1


@pytest.mark.parametrize("action", ["list", "manifest", "chunk"])
def test_partial_owner_migration_blocks_every_file_export(ready, action):
    ready.incomplete = True
    with pytest.raises(HTTPException) as err:
        if action == "list":
            export.list_released_v2_files(
                17, after_file_id="", limit=50, principal=BENEFICIARY,
            )
        elif action == "manifest":
            export.get_released_v2_file_manifest(17, FILE_ID, BENEFICIARY)
        else:
            export.get_released_v2_file_chunk(17, FILE_ID, 0, BENEFICIARY)
    assert err.value.status_code == 409
    assert err.value.detail == "owner_files_need_private_migration"
    assert len(ready.queries) == 2


def test_released_file_inventory_manifest_and_chunk_are_ciphertext_only(ready):
    listed = export.list_released_v2_files(
        17, after_file_id="", limit=50, principal=BENEFICIARY,
    )
    assert listed == {
        "owner_vault_id": "synthetic-owner",
        "beneficiary_link_id": 17,
        "files": [{
            "file_id": FILE_ID,
            "total_bytes": 4,
            "chunk_size": 4,
            "chunk_count": 1,
        }],
        "next_after_file_id": None,
    }
    manifest = export.get_released_v2_file_manifest(17, FILE_ID, BENEFICIARY)
    chunk = export.get_released_v2_file_chunk(17, FILE_ID, 0, BENEFICIARY)
    assert base64.urlsafe_b64decode(
        manifest["manifest_ciphertext"] + "==",
    ) == MANIFEST
    assert base64.urlsafe_b64decode(chunk["ciphertext"] + "==") == CHUNK
    assert "file_name" not in str(listed) + str(manifest) + str(chunk)
    assert export.require_file_read.call_count == 2


def test_corrupt_or_missing_chunk_fails_closed(ready):
    ready.file["chunk_count"] = 2
    with pytest.raises(HTTPException) as framing:
        export.get_released_v2_file_manifest(17, FILE_ID, BENEFICIARY)
    assert framing.value.status_code == 409


def test_inheritance_responses_are_not_cacheable():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/inheritance/v2/17/files")
    def inheritance_fixture():
        return {"ciphertext": "synthetic"}

    response = TestClient(app).get("/inheritance/v2/17/files")
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
