"""A plaintext legacy login must never authenticate an OPAQUE vault."""

import base64
import os
from unittest import mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

os.environ.setdefault("VAULT_SESSION_SECRET", "synthetic_test_only_secret_12345678901234567890")
os.environ.setdefault("VAULTAI_ENV", "local")

from routes import auth_routes as auth


class _Cursor:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params=()):
        assert "FROM vaults" in sql

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.cursor_value = _Cursor(row)
        self.closed = False

    def cursor(self, **kwargs):
        return self.cursor_value

    def close(self):
        self.closed = True

    def rollback(self):
        pass


def _login_attempt(vault_handle, *, legacy_gate="true", raw_pin_gate="false"):
    row = {
        "vault_id": "synthetic-vault-id",
        "vault_handle": vault_handle,
        "pin_salt": "synthetic-salt",
        "pin_verifier": "synthetic-verifier",
        "kdf_iterations": 1000,
    }
    connection = _Connection(row)
    lookup = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    payload = auth.LoginRequest(username_lookup=lookup, pin="123456")
    request = Request({"type": "http", "headers": [], "client": ("test", 1234)})
    timings = {"limiter": 0.0, "validation": 0.0, "db": 0.0, "kdf": 0.0}
    with (
        mock.patch.dict(os.environ, {
            "VAULTAI_ZK_LEGACY_LOGIN_DISABLED": legacy_gate,
            "VAULTAI_ZK_RAW_PIN_CONTENT_DISABLED": raw_pin_gate,
        }),
        mock.patch.object(auth, "enforce_login_rate_limit"),
        mock.patch.object(auth, "enforce_login_credential_rate_limit"),
        mock.patch.object(auth, "get_db", return_value=connection),
        mock.patch.object(auth, "_do_dummy_derive") as dummy,
        mock.patch.object(auth, "derive_key", return_value=b"synthetic-key") as derive,
        mock.patch.object(auth, "decrypt_message", return_value="not-verifier"),
    ):
        with pytest.raises(HTTPException) as caught:
            auth._login_impl(payload, request, timings)
    return caught.value, connection, dummy, derive


def test_zk_row_rejected_before_pin_verifier_check():
    error, connection, dummy, derive = _login_attempt(b"synthetic-handle")
    assert error.status_code == 401
    assert error.detail == auth.GENERIC_LOGIN_ERROR
    dummy.assert_called_once()
    derive.assert_not_called()
    assert connection.closed


def test_legacy_row_still_reaches_pin_verification():
    error, connection, dummy, derive = _login_attempt(None)
    assert error.status_code == 401  # synthetic verifier deliberately fails
    dummy.assert_not_called()
    derive.assert_called_once()
    assert connection.closed


def test_new_cutover_gate_blocks_zk_login_without_old_login_gate():
    error, connection, dummy, derive = _login_attempt(
        b"synthetic-handle", legacy_gate="false", raw_pin_gate="true",
    )
    assert error.status_code == 401
    assert error.detail == auth.GENERIC_LOGIN_ERROR
    dummy.assert_called_once()
    derive.assert_not_called()
    assert connection.closed


def test_new_cutover_gate_preserves_legacy_only_login():
    error, connection, dummy, derive = _login_attempt(
        None, legacy_gate="false", raw_pin_gate="true",
    )
    assert error.status_code == 401  # synthetic verifier deliberately fails
    dummy.assert_not_called()
    derive.assert_called_once()
    assert connection.closed
