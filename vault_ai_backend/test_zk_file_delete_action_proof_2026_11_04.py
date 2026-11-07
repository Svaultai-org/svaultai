"""Synthetic PIN-free authorization for the two legacy file delete paths."""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import main
import vault_core
from pin_only_action_gate import authorize_pin_only_action
from routes import auth_zk_routes, vault_manage_routes


PRINCIPAL = {
    "vault_id": "synthetic-vault",
    "token_id": "synthetic-session",
    "device_id": "synthetic-trusted-device",
}


class _StagedFileCursor:
    def __init__(self):
        self.sql = []
        self.result = None

    def execute(self, sql, params):
        self.sql.append((sql, params))
        normalized = " ".join(sql.lower().split())
        if "from uploaded_files" in normalized:
            self.result = {"has_legacy_inline": True}
        elif "from file_v2_records" in normalized:
            self.result = {
                "migrating_legacy": False,
                "lifecycle_state": "file_v2_written",
                "verification_state": "not_verified",
            }
        else:
            self.result = None

    def fetchone(self):
        return self.result


class _StagedFileDb:
    def __init__(self):
        self.cur = _StagedFileCursor()
        self.commits = 0

    def cursor(self, **_kwargs):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


class _ProofDeleteDb(_StagedFileDb):
    def __init__(self):
        super().__init__()

        def execute(sql, params):
            self.cur.sql.append((sql, params))
            normalized = " ".join(sql.lower().split())
            if "select storage_mode" in normalized:
                self.cur.result = {"has_legacy_inline": True}
            elif "from file_v2_records" in normalized:
                self.cur.result = None
            elif "delete from uploaded_files" in normalized:
                self.cur.result = {
                    "id": "synthetic-file", "file_name": "opaque-label",
                    "file_size": 4,
                }
            else:
                self.cur.result = None

        self.cur.execute = execute


@pytest.fixture
def proof_gate(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_FILE_DELETE_PROOF_ENABLED", "true")
    monkeypatch.setattr(vault_core, "is_vault_zk_adopted", lambda *_: True)
    consume = mock.Mock()
    monkeypatch.setattr(auth_zk_routes, "consume_recent_zk_proof", consume)
    return consume


def test_primary_delete_uses_proof_without_pin_and_preserves_v2_guard(
    monkeypatch, proof_gate,
):
    db = _StagedFileDb()
    verify_pin = mock.Mock()
    monkeypatch.setattr(main, "get_db", lambda: db)
    monkeypatch.setattr(main, "verify_vault_pin", verify_pin)
    payload = main.DeleteFileRequest(
        vault_name="", file_id="synthetic-file",
        zk_proof_token="synthetic-proof",
    )
    assert payload.pin is None
    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.delete_file_endpoint(mock.Mock(), payload, PRINCIPAL))
    assert raised.value.status_code == 409  # unmarked V2 file cannot be orphaned
    assert raised.value.detail == "file_v2_migration_requires_confirmed_delete"
    proof_gate.assert_called_once_with("synthetic-proof", PRINCIPAL)
    verify_pin.assert_not_called()
    assert len(db.cur.sql) == 3
    assert "pg_advisory_xact_lock" in db.cur.sql[0][0]
    assert "uploaded_files" in db.cur.sql[1][0]
    assert "file_v2_records" in db.cur.sql[2][0]
    assert db.commits == 0


def test_vault_manage_delete_aliases_pass_session_to_proof_gate(
    monkeypatch, proof_gate,
):
    db = _StagedFileDb()
    verify_pin = mock.Mock()
    monkeypatch.setattr(vault_manage_routes, "get_db", lambda: db)
    monkeypatch.setattr(vault_manage_routes, "verify_vault_pin", verify_pin)
    payload = vault_manage_routes.FileDeleteRequest(
        vault_name="", file_id="synthetic-file",
        zk_proof_token="synthetic-proof",
    )
    for handler in (vault_manage_routes.delete_file,
                    vault_manage_routes.delete_file_post):
        proof_gate.reset_mock()
        with pytest.raises(HTTPException) as raised:
            asyncio.run(handler(payload, PRINCIPAL))
        assert raised.value.status_code == 409
        proof_gate.assert_called_once_with("synthetic-proof", PRINCIPAL)
    verify_pin.assert_not_called()


def test_proof_only_file_delete_roundtrip_and_no_pin_field(
    monkeypatch, proof_gate,
):
    db = _ProofDeleteDb()
    verify_pin = mock.Mock()
    monkeypatch.setattr(vault_manage_routes, "get_db", lambda: db)
    monkeypatch.setattr(vault_manage_routes, "verify_vault_pin", verify_pin)
    payload = vault_manage_routes.FileDeleteProofRequest(
        vault_name="", file_id="synthetic-file",
        zk_proof_token="synthetic-proof",
    )
    result = asyncio.run(vault_manage_routes.delete_file_proof(payload, PRINCIPAL))
    assert result["status"] == "deleted"
    assert result["file"]["id"] == "synthetic-file"
    assert db.commits == 1
    assert any("DELETE FROM uploaded_files" in sql for sql, _ in db.cur.sql)
    proof_gate.assert_called_once_with("synthetic-proof", PRINCIPAL)
    verify_pin.assert_not_called()
    with pytest.raises(ValidationError):
        vault_manage_routes.FileDeleteProofRequest.model_validate({
            "vault_name": "", "file_id": "synthetic-file",
            "zk_proof_token": "synthetic-proof", "pin": "synthetic-pin",
        })


@pytest.mark.parametrize("pin,proof,expected", [
    ("synthetic-pin", None, "zk_client_update_required"),
    (None, None, "zk_proof_token_required"),
    ("synthetic-pin", "synthetic-proof", "zk_client_update_required"),
])
def test_zk_file_delete_rejects_old_client_or_missing_proof_before_db(
    monkeypatch, proof_gate, pin, proof, expected,
):
    monkeypatch.setattr(main, "get_db", lambda: pytest.fail("DB reached"))
    monkeypatch.setattr(main, "verify_vault_pin", mock.Mock())
    payload = main.DeleteFileRequest(
        vault_name="", file_id="synthetic-file",
        pin=pin, zk_proof_token=proof,
    )
    with pytest.raises(HTTPException) as raised:
        asyncio.run(main.delete_file_endpoint(mock.Mock(), payload, PRINCIPAL))
    assert raised.value.detail == expected
    main.verify_vault_pin.assert_not_called()
    proof_gate.assert_not_called()


def test_flag_off_and_legacy_vault_keep_pin_only(monkeypatch, proof_gate):
    verify_pin = mock.Mock()
    monkeypatch.setenv("VAULTAI_ZK_FILE_DELETE_PROOF_ENABLED", "false")
    authorize_pin_only_action(
        PRINCIPAL, pin="synthetic-legacy-pin", zk_proof_token=None,
        flag_name="VAULTAI_ZK_FILE_DELETE_PROOF_ENABLED",
        verify_pin=verify_pin,
    )
    verify_pin.assert_called_once_with(PRINCIPAL["vault_id"], "synthetic-legacy-pin")
    proof_gate.assert_not_called()
    with pytest.raises(HTTPException) as denied:
        authorize_pin_only_action(
            PRINCIPAL, pin=None, zk_proof_token="synthetic-proof",
            flag_name="VAULTAI_ZK_FILE_DELETE_PROOF_ENABLED",
            verify_pin=verify_pin,
        )
    assert denied.value.status_code == 409

    monkeypatch.setenv("VAULTAI_ZK_FILE_DELETE_PROOF_ENABLED", "true")
    monkeypatch.setattr(vault_core, "is_vault_zk_adopted", lambda *_: False)
    verify_pin.reset_mock()
    authorize_pin_only_action(
        PRINCIPAL, pin="synthetic-legacy-pin", zk_proof_token=None,
        flag_name="VAULTAI_ZK_FILE_DELETE_PROOF_ENABLED",
        verify_pin=verify_pin,
    )
    verify_pin.assert_called_once_with(PRINCIPAL["vault_id"], "synthetic-legacy-pin")
    proof_gate.assert_not_called()
