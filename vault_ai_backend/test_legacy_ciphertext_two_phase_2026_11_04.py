"""Synthetic two-phase migration tests; no live DB, PIN, or vault content."""

from __future__ import annotations

from copy import deepcopy
from unittest import mock

import pytest
from fastapi import HTTPException

from routes import legacy_ciphertext_migration_routes as migration


VAULT = "11111111-1111-1111-1111-111111111111"
OTHER_VAULT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SESSION = "22222222-2222-2222-2222-222222222222"
OTHER_SESSION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PRINCIPAL = {"vault_id": VAULT, "token_id": SESSION}


def _item():
    return {
        "encrypted_data": "SYNTHETIC_LEGACY_CT",
        "item_type": "login",
        "service": "example",
        "item_type_ciphertext": None,
        "service_ciphertext": None,
        "payload_ciphertext": None,
    }


def _file():
    return {
        "id": "synthetic-file-id",
        "file_size": 4,
        "file_name": "synthetic-name",
        "saved_name": None,
        "content_type": "application/octet-stream",
        "detected_type": None,
        "detected_service": None,
        "asset_type": "file",
        "extracted_text": None,
        "relative_path": None,
        "encrypted_file_data": "SYNTHETIC_FILE_CT",
        "file_name_ciphertext": b"name-ct",
        "saved_name_ciphertext": None,
        "content_type_ciphertext": b"type-ct",
        "detected_type_ciphertext": None,
        "detected_service_ciphertext": None,
        "asset_type_ciphertext": b"asset-ct",
        "manifest_ciphertext": b"manifest-ct",
        "total_bytes": 4,
        "chunk_size": 2,
        "chunk_count": 2,
        "crypto_version": "client_mvk_v2",
        "verification_state": "not_verified",
        "migration_metadata_version": 1,
    }


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.result = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.rowcount = 0
        if normalized.startswith("SELECT pg_advisory_xact_lock"):
            self.result = []
        elif normalized.startswith("SELECT encrypted_data, item_type"):
            vault_id, item_id = params
            self.result = [deepcopy(self.db.item)] if vault_id == VAULT and item_id == 7 else []
        elif normalized.startswith("UPDATE vault_items SET item_type_ciphertext"):
            it_ct, svc_ct, payload_ct, item_id, vault_id = params
            if vault_id == VAULT and item_id == 7 and self.db.item["encrypted_data"]:
                self.db.item.update(
                    item_type_ciphertext=it_ct,
                    service_ciphertext=svc_ct,
                    payload_ciphertext=payload_ct,
                )
                self.rowcount = 1
            self.result = []
        elif normalized.startswith("UPDATE vault_items SET encrypted_data = NULL"):
            item_id, vault_id = params
            if vault_id == VAULT and item_id == 7 and self.db.item["encrypted_data"]:
                self.db.item.update(encrypted_data=None, item_type=None, service=None)
                self.rowcount = 1
            self.result = []
        elif normalized.startswith("SELECT LENGTH(encrypted_file_data)"):
            file_id, vault_id = params
            self.result = [{
                "legacy_chars": len(self.db.file["encrypted_file_data"] or ""),
                "text_bytes": len((self.db.file["extracted_text"] or "").encode()),
                "path_bytes": len((self.db.file["relative_path"] or "").encode()),
            }] if (
                file_id == self.db.file["id"] and vault_id == VAULT
            ) else []
        elif normalized.startswith("SELECT OCTET_LENGTH(manifest_ciphertext)"):
            file_id, vault_id = params
            self.result = [{
                "manifest_bytes": len(self.db.file["manifest_ciphertext"]),
                "migration_metadata_version": self.db.file["migration_metadata_version"],
            }] if (
                file_id == self.db.file["id"] and vault_id == VAULT
            ) else []
        elif "FROM uploaded_files u JOIN file_v2_records r" in normalized:
            vault_a, file_id, vault_b = params
            self.result = [deepcopy(self.db.file)] if (
                vault_a == VAULT and vault_b == VAULT and file_id == self.db.file["id"]
            ) else []
        elif normalized.startswith("SELECT COUNT(*) AS chunk_count"):
            self.result = [{
                "chunk_count": len(self.db.chunks),
                "ciphertext_bytes": sum(len(c["ciphertext"]) for c in self.db.chunks),
            }]
        elif normalized.startswith("SELECT chunk_index, ciphertext"):
            self.result = deepcopy(self.db.chunks)
        elif normalized.startswith("UPDATE uploaded_files SET encrypted_file_data = NULL"):
            file_id, vault_id = params
            if vault_id == VAULT and file_id == self.db.file["id"] and self.db.file["encrypted_file_data"]:
                self.db.file.update(
                    encrypted_file_data=None, file_name=None, saved_name=None,
                    content_type=None, detected_type=None,
                    detected_service=None, asset_type=None,
                    extracted_text=None, relative_path=None,
                )
                self.rowcount = 1
            self.result = []
        elif normalized.startswith("UPDATE file_v2_records SET verification_state"):
            file_id, vault_id = params
            if vault_id == VAULT and file_id == self.db.file["id"]:
                self.db.file["verification_state"] = "client_verified"
                self.rowcount = 1
            self.result = []
        else:
            raise AssertionError(f"unexpected SQL: {normalized[:100]}")

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return list(self.result)


class FakeConnection:
    def __init__(self, db):
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
        self.item = _item()
        self.file = _file()
        self.chunks = [
            {"chunk_index": 0, "ciphertext": b"chunk-one"},
            {"chunk_index": 1, "ciphertext": b"chunk-two"},
        ]
        self.connections = []

    def connect(self):
        conn = FakeConnection(self)
        self.connections.append(conn)
        return conn


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic_session_signing_secret_for_offline_tests_123456")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_ITEM_RETIRE_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_RETIRE_ENABLED", "true")
    from auth_local import reset_secret_for_tests
    reset_secret_for_tests()
    db = FakeDb()
    proof = mock.Mock()
    monkeypatch.setattr(migration, "get_db", db.connect)
    monkeypatch.setattr(migration, "consume_recent_zk_proof", proof)
    monkeypatch.setattr(migration, "require_content_write", mock.Mock())
    yield db, proof
    reset_secret_for_tests()


def _stage_item(source=None):
    return migration.ItemStageRequest(
        item_id=7,
        item_type_ciphertext=migration._b64(b"type-v2"),
        service_ciphertext=migration._b64(b"service-v2"),
        payload_ciphertext=migration._b64(b"payload-v2"),
        source_snapshot=migration.legacy_source_snapshot(
            "item", source or _item(), vault_id=VAULT, record_id=7,
        ),
    )


def test_item_stage_retains_legacy_and_exact_retry_is_idempotent(runtime):
    db, _ = runtime
    first = migration.stage_legacy_item(_stage_item(), PRINCIPAL)
    assert first == {
        "item_id": 7, "staged": True, "created": True,
        "source_snapshot": migration.legacy_source_snapshot(
            "item", db.item, vault_id=VAULT, record_id=7,
        ),
    }
    assert db.item["encrypted_data"] == "SYNTHETIC_LEGACY_CT"
    second = migration.stage_legacy_item(_stage_item(db.item), PRINCIPAL)
    assert second["created"] is False
    with pytest.raises(HTTPException) as exc:
        migration.stage_legacy_item(
            _stage_item(db.item).model_copy(update={
                "payload_ciphertext": migration._b64(b"different-v2"),
            }), PRINCIPAL,
        )
    assert exc.value.status_code == 409
    assert db.item["payload_ciphertext"] == b"payload-v2"


def test_item_stage_rejects_source_edit_after_export(runtime):
    db, _ = runtime
    exported = _stage_item()
    db.item["encrypted_data"] = "new-synthetic-legacy-ciphertext"
    with pytest.raises(HTTPException) as exc:
        migration.stage_legacy_item(exported, PRINCIPAL)
    assert exc.value.status_code == 409
    assert exc.value.detail == "legacy_source_changed"
    assert db.item["payload_ciphertext"] is None


def test_item_stage_accepts_metadata_only_partial_row(runtime):
    db, _ = runtime
    db.item["item_type_ciphertext"] = b"earlier-type-metadata"
    db.item["service_ciphertext"] = b"earlier-service-metadata"
    response = migration.stage_legacy_item(_stage_item(db.item), PRINCIPAL)
    assert response["created"] is True
    assert db.item["encrypted_data"] == "SYNTHETIC_LEGACY_CT"
    assert db.item["payload_ciphertext"] == b"payload-v2"


def test_item_retire_requires_same_session_readback_and_opaque_proof(runtime):
    db, proof = runtime
    migration.stage_legacy_item(_stage_item(), PRINCIPAL)
    readback = migration.readback_staged_item(7, PRINCIPAL)
    assert readback["item_id"] == 7
    assert readback["payload_ciphertext"] == migration._b64(b"payload-v2")
    assert "encrypted_data" not in readback
    request = migration.ItemRetireRequest(
        item_id=7, readback_receipt=readback["readback_receipt"],
        zk_proof_token="synthetic-one-time-proof",
        source_snapshot=readback["source_snapshot"],
    )
    with pytest.raises(HTTPException) as exc:
        migration.retire_legacy_item(
            request, {**PRINCIPAL, "token_id": OTHER_SESSION},
        )
    assert exc.value.status_code == 409
    proof.assert_not_called()
    result = migration.retire_legacy_item(request, PRINCIPAL)
    assert result["retired"] is True
    proof.assert_called_once_with("synthetic-one-time-proof", PRINCIPAL)
    assert db.item["encrypted_data"] is None
    assert db.item["payload_ciphertext"] == b"payload-v2"


def test_item_source_change_blocks_retirement_without_consuming_proof(runtime):
    db, proof = runtime
    migration.stage_legacy_item(_stage_item(), PRINCIPAL)
    readback = migration.readback_staged_item(7, PRINCIPAL)
    receipt = readback["readback_receipt"]
    db.item["encrypted_data"] = "CHANGED_SYNTHETIC_CT"
    with pytest.raises(HTTPException) as exc:
        migration.retire_legacy_item(migration.ItemRetireRequest(
            item_id=7, readback_receipt=receipt, zk_proof_token="synthetic-proof",
            source_snapshot=readback["source_snapshot"],
        ), PRINCIPAL)
    assert exc.value.status_code == 409
    proof.assert_not_called()
    assert db.item["encrypted_data"] is not None


def test_new_item_readback_receipt_cannot_certify_earlier_export(runtime):
    db, proof = runtime
    migration.stage_legacy_item(_stage_item(), PRINCIPAL)
    earlier = migration.readback_staged_item(7, PRINCIPAL)
    db.item["encrypted_data"] = "new-synthetic-legacy-ciphertext"
    later = migration.readback_staged_item(7, PRINCIPAL)
    assert later["source_snapshot"] != earlier["source_snapshot"]
    # The new receipt describes the edited row, but the client only verified
    # the earlier export. That earlier snapshot cannot authorize retirement.
    with pytest.raises(HTTPException) as exc:
        migration.retire_legacy_item(migration.ItemRetireRequest(
            item_id=7, readback_receipt=later["readback_receipt"],
            source_snapshot=earlier["source_snapshot"],
            zk_proof_token="synthetic-proof",
        ), PRINCIPAL)
    assert exc.value.status_code == 409
    assert exc.value.detail == "legacy_source_changed"
    proof.assert_not_called()
    assert db.item["encrypted_data"] is not None


def test_file_readback_requires_complete_chunks_and_retirement_is_separate(runtime):
    db, proof = runtime
    db.chunks.pop()
    with pytest.raises(HTTPException) as exc:
        migration.readback_staged_file(db.file["id"], PRINCIPAL)
    assert exc.value.status_code == 409
    db.chunks.append({"chunk_index": 1, "ciphertext": b"chunk-two"})
    readback = migration.readback_staged_file(db.file["id"], PRINCIPAL)
    assert readback["chunk_count"] == 2
    assert "encrypted_file_data" not in readback
    assert db.file["encrypted_file_data"] == "SYNTHETIC_FILE_CT"
    request = migration.FileRetireRequest(
        file_id=db.file["id"],
        readback_receipt=readback["readback_receipt"],
        zk_proof_token="synthetic-file-proof",
        client_verified_exact_bytes=True,
        source_snapshot=readback["source_snapshot"],
    )
    result = migration.retire_legacy_file(request, PRINCIPAL)
    assert result["retired"] is True
    proof.assert_called_once_with("synthetic-file-proof", PRINCIPAL)
    assert db.file["encrypted_file_data"] is None
    assert db.file["verification_state"] == "client_verified"


def test_file_retire_rejects_missing_client_verification(runtime):
    db, proof = runtime
    receipt = migration.readback_staged_file(db.file["id"], PRINCIPAL)
    with pytest.raises(HTTPException) as exc:
        migration.retire_legacy_file(migration.FileRetireRequest(
            file_id=db.file["id"],
            readback_receipt=receipt["readback_receipt"],
            zk_proof_token="synthetic-proof",
            client_verified_exact_bytes=False,
            source_snapshot=receipt["source_snapshot"],
        ), PRINCIPAL)
    assert exc.value.status_code == 400
    proof.assert_not_called()
    assert db.file["encrypted_file_data"] is not None


def test_extra_fields_require_version_two_and_same_source_receipt(runtime, monkeypatch):
    db, proof = runtime
    db.file["extracted_text"] = "synthetic private document text"
    db.file["relative_path"] = "synthetic/folder/file.txt"
    with pytest.raises(HTTPException) as blocked:
        migration.readback_staged_file(db.file["id"], PRINCIPAL)
    assert blocked.value.status_code == 409
    assert blocked.value.detail == "file_extra_legacy_data_requires_migration"
    assert db.file["encrypted_file_data"] is not None

    db.file["migration_metadata_version"] = 2
    readback = migration.readback_staged_file(db.file["id"], PRINCIPAL)
    assert readback["migration_metadata_version"] == 2
    assert "extracted_text" not in readback
    request = migration.FileRetireRequest(
        file_id=db.file["id"],
        readback_receipt=readback["readback_receipt"],
        zk_proof_token="synthetic-extra-proof",
        client_verified_exact_bytes=True,
        source_snapshot=readback["source_snapshot"],
    )
    with pytest.raises(HTTPException) as extra_flag_off:
        migration.retire_legacy_file(request, PRINCIPAL)
    assert extra_flag_off.value.detail == "file_extra_retire_disabled"
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_RETIRE_ENABLED", "true")
    with pytest.raises(HTTPException) as missing_extra_proof:
        migration.retire_legacy_file(request, PRINCIPAL)
    assert missing_extra_proof.value.detail == "client_extra_readback_required"
    assert db.file["encrypted_file_data"] is not None
    request = request.model_copy(update={"client_verified_extra_fields": True})
    db.file["extracted_text"] = "new synthetic text"
    with pytest.raises(HTTPException) as changed:
        migration.retire_legacy_file(request, PRINCIPAL)
    assert changed.value.detail == "legacy_source_changed"
    proof.assert_not_called()
    assert db.file["encrypted_file_data"] is not None

    fresh = migration.readback_staged_file(db.file["id"], PRINCIPAL)
    result = migration.retire_legacy_file(request.model_copy(update={
        "readback_receipt": fresh["readback_receipt"],
        "source_snapshot": fresh["source_snapshot"],
    }), PRINCIPAL)
    assert result["retired"] is True
    assert db.file["extracted_text"] is None
    assert db.file["relative_path"] is None
    assert db.file["encrypted_file_data"] is None


def test_v3_large_extra_requires_exact_readback_and_flag_to_retire(
    runtime, monkeypatch,
):
    db, proof = runtime
    db.file["extracted_text"] = "x" * (201 * 1024)
    db.file["relative_path"] = "synthetic/path.txt"
    db.file["migration_metadata_version"] = 2
    with pytest.raises(HTTPException) as old_limit:
        migration.readback_staged_file(db.file["id"], PRINCIPAL)
    assert old_limit.value.status_code == 413
    assert db.file["encrypted_file_data"] is not None

    db.file["migration_metadata_version"] = 3
    readback = migration.readback_staged_file(db.file["id"], PRINCIPAL)
    assert readback["migration_metadata_version"] == 3
    assert "extracted_text" not in readback
    assert "PIN" not in str(readback)
    request = migration.FileRetireRequest(
        file_id=db.file["id"], readback_receipt=readback["readback_receipt"],
        zk_proof_token="synthetic-v3-proof", source_snapshot=readback["source_snapshot"],
        client_verified_exact_bytes=True, client_verified_extra_fields=True,
    )
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_EXTRA_RETIRE_ENABLED", "true")
    monkeypatch.delenv(migration.FILE_EXTRA_V3_FLAG, raising=False)
    with pytest.raises(HTTPException) as disabled:
        migration.retire_legacy_file(request, PRINCIPAL)
    assert disabled.value.detail == "file_extra_v3_retire_disabled"
    proof.assert_not_called()
    assert db.file["encrypted_file_data"] is not None

    monkeypatch.setenv(migration.FILE_EXTRA_V3_FLAG, "true")
    db.file["extracted_text"] += "changed"
    with pytest.raises(HTTPException) as changed:
        migration.retire_legacy_file(request, PRINCIPAL)
    assert changed.value.detail == "legacy_source_changed"
    proof.assert_not_called()
    assert db.file["encrypted_file_data"] is not None

    fresh = migration.readback_staged_file(db.file["id"], PRINCIPAL)
    result = migration.retire_legacy_file(request.model_copy(update={
        "readback_receipt": fresh["readback_receipt"],
        "source_snapshot": fresh["source_snapshot"],
    }), PRINCIPAL)
    assert result["retired"] is True
    proof.assert_called_once()
    assert db.file["encrypted_file_data"] is None
    assert db.file["extracted_text"] is None


def test_v3_rejects_text_over_256k_without_retiring(runtime, monkeypatch):
    db, proof = runtime
    monkeypatch.setenv(migration.FILE_EXTRA_V3_FLAG, "true")
    db.file["extracted_text"] = "x" * (migration.MAX_FILE_EXTRA_V3_BYTES + 1)
    db.file["migration_metadata_version"] = 3
    with pytest.raises(HTTPException) as too_large:
        migration.readback_staged_file(db.file["id"], PRINCIPAL)
    assert too_large.value.status_code == 413
    proof.assert_not_called()
    assert db.file["encrypted_file_data"] is not None


def test_file_rename_after_export_cannot_use_new_receipt_for_old_copy(runtime):
    db, proof = runtime
    earlier = migration.readback_staged_file(db.file["id"], PRINCIPAL)
    db.file["saved_name"] = "new-synthetic-name"
    later = migration.readback_staged_file(db.file["id"], PRINCIPAL)
    assert later["source_snapshot"] != earlier["source_snapshot"]
    with pytest.raises(HTTPException) as exc:
        migration.retire_legacy_file(migration.FileRetireRequest(
            file_id=db.file["id"],
            readback_receipt=later["readback_receipt"],
            source_snapshot=earlier["source_snapshot"],
            zk_proof_token="synthetic-proof",
            client_verified_exact_bytes=True,
        ), PRINCIPAL)
    assert exc.value.status_code == 409
    assert exc.value.detail == "legacy_source_changed"
    proof.assert_not_called()


def test_cross_vault_migration_cannot_read_records(runtime):
    db, proof = runtime
    with pytest.raises(HTTPException) as exc:
        migration.stage_legacy_item(_stage_item(),
                                    {**PRINCIPAL, "vault_id": OTHER_VAULT})
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        migration.readback_staged_file(db.file["id"],
                                       {**PRINCIPAL, "vault_id": OTHER_VAULT})
    assert exc.value.status_code == 404
    proof.assert_not_called()
