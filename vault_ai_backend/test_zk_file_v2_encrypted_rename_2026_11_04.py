"""Synthetic V2 encrypted-name CAS/readback checks; no real vault or DB."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import main
import vault_core
from routes import file_v2_routes as routes
from routes import vault_manage_routes
from routes import zk_metadata_inventory_routes as inventory


PRINCIPAL = {
    "vault_id": "synthetic-vault",
    "token_id": "synthetic-session",
    "device_id": "synthetic-trusted-device",
}
CT = base64.urlsafe_b64encode(b"\x00" * 32).decode().rstrip("=")


class _State:
    def __init__(self):
        self.lock = Lock()
        self.version = 0
        self.ciphertext = None
        self.lifecycle = "client_v2_ready"
        self.verified = "client_verified"
        self.marker = True
        self.sql = []


class _Connection:
    def __init__(self, state):
        self.state = state
        self.locked = False
        self.next_row = None
        self.committed = False

    def cursor(self, **_kwargs):
        return self

    def execute(self, sql, params):
        self.state.sql.append(sql)
        if "pg_advisory_xact_lock" in sql:
            self.state.lock.acquire()
            self.locked = True
        elif "SELECT verification_state,lifecycle_state,name_version" in sql:
            self.next_row = (
                (self.state.verified, self.state.lifecycle, self.state.version)
                if params == ("synthetic-file", PRINCIPAL["vault_id"])
                else None
            )
        elif "SELECT 1 FROM uploaded_files" in sql:
            self.next_row = (1,) if self.state.marker else None
        elif "UPDATE file_v2_records SET saved_name_override_ciphertext" in sql:
            if params[3] == self.state.version:
                self.state.ciphertext = params[0]
                self.state.version += 1
                self.next_row = (self.state.version,)
            else:
                self.next_row = None
        else:
            raise AssertionError(sql)

    def fetchone(self):
        row = self.next_row
        self.next_row = None
        return row

    def commit(self):
        self.committed = True
        self._release()

    def rollback(self):
        self._release()

    def close(self):
        self._release()

    def _release(self):
        if self.locked:
            self.locked = False
            self.state.lock.release()


@pytest.fixture
def rename_gate(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_FILE_V2_RENAME_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_V2_FILE_READ_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_V2_FILE_WRITE_ENABLED", "true")
    monkeypatch.setattr(routes, "_enabled", lambda *_: None)
    monkeypatch.setattr(routes, "require_content_write", lambda *_: None)
    monkeypatch.setattr(routes, "require_file_read", lambda *_: None)
    monkeypatch.setattr(routes, "is_vault_zk_adopted", lambda *_: True)
    monkeypatch.setattr(vault_core, "is_vault_zk_adopted", lambda *_: True)
    consume = mock.Mock()
    monkeypatch.setattr(routes, "consume_recent_zk_proof", consume)
    state = _State()
    monkeypatch.setattr(routes, "get_db", lambda: _Connection(state))
    return state, consume


def _payload(token="proof-one", version=0):
    return routes.EncryptedFileRename(
        zk_proof_token=token,
        expected_name_version=version,
        saved_name_ciphertext=CT,
    )


def test_encrypted_rename_is_versioned_and_proof_gated(rename_gate):
    state, consume = rename_gate
    result = routes.rename_ready_file("synthetic-file", _payload(), PRINCIPAL)
    assert result == {
        "file_id": "synthetic-file", "name_version": 1, "renamed": True,
    }
    assert state.version == 1
    assert state.ciphertext == b"\x00" * 32
    assert any("FOR UPDATE" in sql for sql in state.sql)
    assert any("name_version=%s" in sql for sql in state.sql)
    consume.assert_called_once_with("proof-one", PRINCIPAL)


def test_two_concurrent_renames_with_same_version_have_one_winner(rename_gate):
    state, consume = rename_gate
    def submit(token):
        try:
            return routes.rename_ready_file(
                "synthetic-file", _payload(token=token), PRINCIPAL,
            )
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, ("proof-one", "proof-two")))
    assert sum(isinstance(result, dict) for result in results) == 1
    rejected = next(result for result in results if isinstance(result, HTTPException))
    assert rejected.status_code == 409
    assert rejected.detail == "file_v2_name_version_conflict"
    assert state.version == 1
    assert consume.call_count == 1


def test_stale_version_not_ready_and_missing_marker_do_not_spend_proof(rename_gate):
    state, consume = rename_gate
    for attribute, value, expected in (
        ("version", 1, "file_v2_name_version_conflict"),
        ("lifecycle", "file_v2_written", "file_v2_not_ready"),
        ("marker", False, "file_v2_marker_missing"),
    ):
        old = getattr(state, attribute)
        setattr(state, attribute, value)
        with pytest.raises(HTTPException) as raised:
            routes.rename_ready_file("synthetic-file", _payload(), PRINCIPAL)
        assert raised.value.detail == expected
        setattr(state, attribute, old)
    consume.assert_not_called()
    assert state.ciphertext is None


def test_flag_off_cross_vault_and_plaintext_requests_are_rejected(
    monkeypatch, rename_gate,
):
    state, consume = rename_gate
    with pytest.raises(ValidationError):
        routes.EncryptedFileRename.model_validate({
            "zk_proof_token": "proof-one", "expected_name_version": 0,
            "saved_name_ciphertext": CT, "pin": "synthetic-pin",
        })
    with pytest.raises(ValidationError):
        routes.EncryptedFileRename.model_validate({
            "zk_proof_token": "proof-one", "expected_name_version": 0,
            "saved_name_ciphertext": CT, "saved_name": "private name",
        })
    monkeypatch.setenv("VAULTAI_ZK_FILE_V2_RENAME_ENABLED", "false")
    with pytest.raises(HTTPException) as disabled:
        routes.rename_ready_file("synthetic-file", _payload(), PRINCIPAL)
    assert disabled.value.status_code == 404
    assert not state.sql
    monkeypatch.setenv("VAULTAI_ZK_FILE_V2_RENAME_ENABLED", "true")
    other = {**PRINCIPAL, "vault_id": "other-vault"}
    with pytest.raises(HTTPException) as missing:
        routes.rename_ready_file("synthetic-file", _payload(), other)
    assert missing.value.status_code == 404
    consume.assert_not_called()


def test_manifest_and_inventory_read_back_same_override(monkeypatch, rename_gate):
    _, _ = rename_gate
    override = b"\x01" * 32
    encoded = base64.urlsafe_b64encode(override).decode().rstrip("=")

    class ManifestConn:
        def cursor(self, **_kwargs):
            return self

        def execute(self, sql, params):
            assert "saved_name_override_ciphertext" in sql
            assert params == ("synthetic-file", PRINCIPAL["vault_id"])

        def fetchone(self):
            return {
                "file_id": "synthetic-file", "crypto_version": "client_mvk_v2",
                "manifest_ciphertext": b"\x02" * 32, "total_bytes": 3,
                "chunk_size": 3, "chunk_count": 1,
                "lifecycle_state": "client_v2_ready",
                "verification_state": "client_verified",
                "saved_name_override_ciphertext": override, "name_version": 1,
            }

        def close(self):
            pass

    monkeypatch.setattr(routes, "get_db", ManifestConn)
    manifest = routes.get_manifest("synthetic-file", PRINCIPAL)
    assert manifest["saved_name_override_ciphertext"] == encoded
    assert manifest["name_version"] == 1

    class InventoryConn:
        def cursor(self, **_kwargs):
            return self

        def execute(self, sql, params):
            assert "COALESCE(r.saved_name_override_ciphertext" in sql
            assert params == (PRINCIPAL["vault_id"], "", 101)

        def fetchall(self):
            return [{
                "id": "synthetic-file", "file_size": 3,
                "storage_mode": "inline", "upload_status": "complete",
                "file_name_ciphertext": None,
                "saved_name_ciphertext": override,
                "content_type_ciphertext": None,
                "detected_type_ciphertext": None,
                "detected_service_ciphertext": None,
                "asset_type_ciphertext": None,
                "has_inline_ciphertext": False,
                "created_at": None, "lifecycle_state": "client_v2_ready",
                "verification_state": "client_verified", "name_version": 1,
            }]

        def close(self):
            pass

    monkeypatch.setattr(inventory, "_require_inventory", lambda *_: None)
    monkeypatch.setattr(inventory, "get_db", InventoryConn)
    listed = inventory.file_metadata_inventory("", 100, PRINCIPAL)
    assert listed["records"][0]["saved_name_ciphertext"] == encoded
    assert listed["records"][0]["name_version"] == 1


def test_folder_tree_uses_encrypted_override_without_plaintext(monkeypatch, rename_gate):
    _, _ = rename_gate
    override = b"\x03" * 32
    encoded = base64.urlsafe_b64encode(override).decode().rstrip("=")
    old = b"\x04" * 32
    rows = [{
        "id": "synthetic-file", "file_name": None, "saved_name": None,
        "file_name_ciphertext": None, "saved_name_ciphertext": old,
        "relative_path": None,
    }]
    monkeypatch.setattr(main, "list_uploaded_files", lambda *_args, **_kw: rows)

    class FolderConn:
        def cursor(self, **_kwargs):
            return self

        def execute(self, sql, params):
            assert "saved_name_override_ciphertext" in sql
            assert params == (PRINCIPAL["vault_id"], ["synthetic-file"])

        def fetchall(self):
            return [{
                "file_id": "synthetic-file",
                "saved_name_override_ciphertext": override,
            }]

        def close(self):
            pass

    monkeypatch.setattr(main, "get_db", FolderConn)
    tree = main.build_folder_tree(vault_id=PRINCIPAL["vault_id"])
    assert tree["files"][0]["saved_name_ciphertext"] == encoded
    assert tree["files"][0]["saved_name"] is None
    assert rows[0]["saved_name_ciphertext"] == old


def test_old_pin_plaintext_rename_paths_fail_before_verification(
    monkeypatch, rename_gate,
):
    verify_main = mock.Mock()
    verify_manage = mock.Mock()
    monkeypatch.setattr(main, "verify_vault_pin", verify_main)
    monkeypatch.setattr(vault_manage_routes, "verify_vault_pin", verify_manage)
    monkeypatch.setattr(vault_manage_routes, "require_content_write", lambda *_: None)
    with pytest.raises(HTTPException) as old_form:
        asyncio.run(main.name_file_endpoint(
            None, "", "synthetic-file", "private", "synthetic-pin", PRINCIPAL,
        ))
    assert old_form.value.detail == "zk_v2_rename_required"
    with pytest.raises(HTTPException) as old_json:
        asyncio.run(vault_manage_routes.rename_file(
            vault_manage_routes.FileRenameRequest(
                vault_name="", file_id="synthetic-file",
                saved_name="private", pin="synthetic-pin",
            ),
            PRINCIPAL,
        ))
    assert old_json.value.detail == "zk_v2_rename_required"
    verify_main.assert_not_called()
    verify_manage.assert_not_called()
