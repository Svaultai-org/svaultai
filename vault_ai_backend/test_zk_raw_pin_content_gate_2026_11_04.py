"""Synthetic cutover tests: old raw-PIN content calls cannot use ZK rows."""

from __future__ import annotations

import asyncio
import os
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://fixture.invalid/test")
os.environ.setdefault("OPENAI_API_KEY", "synthetic-unused")
os.environ.setdefault("VAULT_SESSION_SECRET", "synthetic-test-session-secret-2026-11-04")

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import vault_core
from zk_raw_pin_content_gate import (
    FLAG_NAME, raw_pin_content_disabled, reject_zk_raw_pin_content,
)


VAULT = "11111111-1111-1111-1111-111111111111"
PIN = "123456"


class _Cursor:
    def __init__(self, zk: bool):
        self.zk = zk
        self.sql = []
        self.result = None

    def execute(self, sql, params=()):
        statement = " ".join(sql.lower().split())
        self.sql.append(statement)
        if "from vaults" in statement and "pin_salt" in statement:
            self.result = {
                "pin_salt": "synthetic-salt",
                "pin_verifier": "synthetic-verifier",
                "locked_until": None,
                "kdf_iterations": 1000,
                "must_reset": False,
                "failed_pin_attempts": 0,
                "vault_handle": b"synthetic-handle" if self.zk else None,
            }
        elif statement.startswith("select vault_handle is not null"):
            self.result = (self.zk,)
        elif statement.startswith("select now()"):
            self.result = {"now": None}
        elif statement.startswith("update vaults"):
            self.result = None
        else:
            raise AssertionError(f"unexpected SQL: {statement}")

    def fetchone(self):
        return self.result


class _Db:
    def __init__(self, zk: bool):
        self.cur = _Cursor(zk)
        self.commits = 0
        self.closed = False

    def cursor(self, **_):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv(FLAG_NAME, raising=False)
    assert not raw_pin_content_disabled()


def test_zk_pin_verification_rejected_before_kdf_or_lockout(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "true")
    db = _Db(zk=True)
    monkeypatch.setattr(vault_core, "get_db", lambda: db)
    derive = mock.Mock()
    monkeypatch.setattr(vault_core, "derive_key", derive)
    with pytest.raises(HTTPException) as caught:
        vault_core.verify_vault_pin(VAULT, PIN)
    assert caught.value.status_code == 409
    assert caught.value.detail == "zk_client_update_required"
    assert PIN not in repr(caught.value.detail)
    derive.assert_not_called()
    assert len(db.cur.sql) == 1 and db.commits == 0 and db.closed


@pytest.mark.parametrize("zk,flag", [(False, "true"), (True, "false")])
def test_legacy_account_or_flag_off_preserves_pin_path(monkeypatch, zk, flag):
    monkeypatch.setenv(FLAG_NAME, flag)
    db = _Db(zk=zk)
    monkeypatch.setattr(vault_core, "get_db", lambda: db)
    monkeypatch.setattr(vault_core, "derive_key", lambda *_args, **_kw: b"synthetic-key")
    monkeypatch.setattr(vault_core, "decrypt_message",
                        lambda *_args: vault_core.PIN_VERIFIER_PLAINTEXT)
    assert vault_core.verify_vault_pin(VAULT, PIN) == b"synthetic-key"
    assert db.commits == 1 and db.closed


def test_authoritative_zk_lookup_fails_closed_on_database_error(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "true")

    def unavailable():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(vault_core, "get_db", unavailable)
    with pytest.raises(RuntimeError, match="database unavailable"):
        reject_zk_raw_pin_content(VAULT)


def test_legacy_file_delete_rejects_zk_pin_before_delete(monkeypatch):
    from routes import vault_manage_routes as manage

    monkeypatch.setenv(FLAG_NAME, "true")
    monkeypatch.delenv("VAULTAI_ZK_FILE_DELETE_PROOF_ENABLED", raising=False)
    db = _Db(zk=True)
    monkeypatch.setattr(vault_core, "get_db", lambda: db)
    monkeypatch.setattr(manage, "get_db", lambda: (_ for _ in ()).throw(
        AssertionError("file delete must not reach storage")))
    with pytest.raises(HTTPException) as caught:
        manage._delete_file_impl(
            manage.FileDeleteRequest(vault_name="", file_id="synthetic-file", pin=PIN),
            VAULT,
            {"vault_id": VAULT, "token_id": "synthetic-session"},
        )
    assert caught.value.status_code == 409
    assert db.commits == 0


def test_metadata_route_rejects_zk_pin_before_salt_or_storage(monkeypatch):
    import main

    monkeypatch.setenv(FLAG_NAME, "true")
    db = _Db(zk=True)
    monkeypatch.setattr(vault_core, "get_db", lambda: db)
    monkeypatch.setattr(main, "get_or_create_pin_salt", lambda *_: (_ for _ in ()).throw(
        AssertionError("salt lookup must not run")))
    request = Request({"type": "http", "method": "POST", "path": "/get-or-create-vault-meta",
                       "headers": []})
    with pytest.raises(HTTPException) as caught:
        asyncio.run(main.get_or_create_vault_meta_endpoint(
            request, main.VaultMetaRequest(vault_name="", pin=PIN),
            {"vault_id": VAULT},
        ))
    assert caught.value.status_code == 409
    assert db.cur.sql == [
        "select vault_handle is not null from vaults where vault_id=%s limit 1"
    ]


def test_deep_answer_poll_rejects_zk_pin_even_when_job_is_ready(monkeypatch):
    from routes import deep_answer_routes as deep
    import vault_deep_answer

    monkeypatch.setenv(FLAG_NAME, "true")
    db = _Db(zk=True)
    monkeypatch.setattr(vault_core, "get_db", lambda: db)
    monkeypatch.setattr(vault_deep_answer, "get_job", lambda *_: (_ for _ in ()).throw(
        AssertionError("job lookup must not run")))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(deep.deep_answer_poll(
            "synthetic-job", deep._DeepAnswerPollRequest(pin=PIN),
            {"vault_id": VAULT},
        ))
    assert caught.value.status_code == 409


def test_legacy_chat_rejects_zk_pin_before_kdf_or_content_work(monkeypatch):
    import main
    import rate_limit_sensitive

    monkeypatch.setenv(FLAG_NAME, "true")
    db = _Db(zk=True)
    monkeypatch.setattr(vault_core, "get_db", lambda: db)
    monkeypatch.setattr(rate_limit_sensitive, "enforce_chat_rate_limit", lambda *_a, **_k: None)
    monkeypatch.setattr(main, "get_db", lambda: (_ for _ in ()).throw(
        AssertionError("chat must not reach KDF or content storage")))
    request = Request({"type": "http", "method": "POST", "path": "/chat",
                       "headers": [], "client": ("test", 1234)})
    with pytest.raises(HTTPException) as caught:
        asyncio.run(main.chat_endpoint(
            request,
            main.ChatRequest(encrypted_message="synthetic-ciphertext", vault_name="", pin=PIN),
            {"vault_id": VAULT, "token_id": "synthetic-session"},
        ))
    assert caught.value.status_code == 409
    assert db.cur.sql == ["select vault_handle is not null from vaults where vault_id=%s limit 1"]


def test_verify_pin_rejects_zk_before_diagnostic_or_derivation(monkeypatch, capsys):
    import main
    import rate_limit_sensitive

    monkeypatch.setenv(FLAG_NAME, "true")
    db = _Db(zk=True)
    monkeypatch.setattr(vault_core, "get_db", lambda: db)
    monkeypatch.setattr(rate_limit_sensitive, "enforce_pin_verify_rate_limit", lambda *_a, **_k: None)
    request = Request({"type": "http", "method": "POST", "path": "/verify-pin",
                       "headers": [], "client": ("test", 1234)})
    with pytest.raises(HTTPException) as caught:
        asyncio.run(main.verify_pin_endpoint(
            main.VerifyPinRequest(vault_name="", pin=PIN), request,
            {"vault_id": VAULT},
        ))
    assert caught.value.status_code == 409
    assert capsys.readouterr().out == ""


def test_beneficiary_action_rejects_zk_pin_with_proof_flag_off(monkeypatch):
    import main

    monkeypatch.setenv(FLAG_NAME, "true")
    monkeypatch.delenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", raising=False)
    db = _Db(zk=True)
    monkeypatch.setattr(vault_core, "get_db", lambda: db)
    with pytest.raises(HTTPException) as caught:
        main._verify_beneficiary_action(
            {"vault_id": VAULT}, pin=PIN, proof_token=None,
        )
    assert caught.value.status_code == 409
    assert db.commits == 0


def test_delete_confirm_rejects_zk_pin_before_challenge_or_delete(monkeypatch):
    from routes import vault_delete_routes as delete

    monkeypatch.setenv(FLAG_NAME, "true")
    monkeypatch.setattr(vault_core, "get_db", lambda: _Db(zk=True))
    monkeypatch.setattr(delete, "enforce_delete_vault_rate_limit", lambda *_a, **_k: None)
    monkeypatch.setattr(delete, "_verify_challenge", lambda *_a: (_ for _ in ()).throw(
        AssertionError("challenge must not be reached")))
    request = Request({"type": "http", "method": "POST", "path": "/vault/delete/confirm",
                       "headers": [], "client": ("test", 1234)})
    with pytest.raises(HTTPException) as caught:
        delete.confirm_delete(
            delete.DeleteConfirmRequest(request_token="synthetic", pin=PIN,
                                        confirmation_phrase="wrong"),
            request, {"vault_id": VAULT},
        )
    assert caught.value.status_code == 409
