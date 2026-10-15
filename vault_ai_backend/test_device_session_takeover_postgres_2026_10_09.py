"""Real PostgreSQL current-head single-device takeover regressions.

Opt-in ONLY to the exact ephemeral local forwarded database below. Never
truncate or upgrade a database; fixture cleanup deletes only IDs generated
by this suite, after checking database/user/server version. Production URLs
are rejected before any connection is opened. No real vault data is used.
"""
from __future__ import annotations

import asyncio
import base64
import os
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import psycopg2
import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from psycopg2.extras import RealDictCursor

import auth_local
import device_gate
import device_monitor
import rate_limit_auth
from rate_limit_backend import InMemoryRateLimitBackend
from routes import auth_routes, device_routes
from vault_core import KDF_TARGET_ITERATIONS, PIN_VERIFIER_PLAINTEXT, derive_key, encrypt_message


DISPOSABLE_DSN = (
    "postgresql://svaultai_session_tests:disposable-local-test-only"
    "@127.0.0.1:55437/svaultai_session_tests"
)
EXPECTED_HEAD = "0049_kag_encrypted_draft_binding"
DEVICE_A = "device-test-phone-aaaaaaaaaaaa"
DEVICE_B = "device-test-phone-bbbbbbbbbbbb"
DEVICE_C = "device-test-phone-cccccccccccc"


def _connect():
    configured = os.environ.get("VAULTAI_TEST_DATABASE_URL", "").strip()
    if not configured:
        pytest.skip("exact disposable PostgreSQL takeover test database not configured")
    if configured != DISPOSABLE_DSN:
        raise RuntimeError("refusing database other than the exact disposable takeover test DSN")
    conn = psycopg2.connect(DISPOSABLE_DSN, connect_timeout=5)
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(), current_user, current_setting('server_version_num')")
        database, user, version = cur.fetchone()
        if database != "svaultai_session_tests" or user != "svaultai_session_tests" or not 170000 <= int(version) < 180000:
            conn.close()
            raise RuntimeError("disposable PostgreSQL identity/version guard failed")
    conn.rollback()
    return conn


def _rows(sql, params=()):
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def _request(token, device_id, path="/auth/me"):
    return Request({"type": "http", "method": "GET", "path": path,
                    "headers": [(b"authorization", f"Bearer {token}".encode()),
                                (b"x-device-id", device_id.encode())]})


@pytest.fixture
def vault(monkeypatch):
    conn = _connect()
    account_id, vault_id = str(uuid.uuid4()), str(uuid.uuid4())
    ciphertext = secrets.token_bytes(48)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            assert {r[0] for r in cur.fetchall()} == {EXPECTED_HEAD}, "initialize disposable schema to current Alembic head first"
            cur.execute("INSERT INTO accounts (account_id,account_type,sales_channel) VALUES (%s,'individual','self_service')", (account_id,))
            cur.execute(
                """INSERT INTO vaults (vault_id,vault_name,pin_salt,pin_verifier,
                     account_id,acknowledged_irrecoverable,username_lookup_v1,
                     vault_handle,opaque_registration_record,wrapped_mvk,
                     wrapped_sk_vault,pk_vault_public,display_name_ciphertext)
                   VALUES (%s,%s,'','',%s,TRUE,%s,%s,%s,%s,%s,%s,%s)""",
                (vault_id, "vault-" + vault_id.replace("-", ""), account_id,
                 secrets.token_bytes(32), secrets.token_bytes(15), b"fixture-opaque",
                 ciphertext, ciphertext, secrets.token_bytes(32), ciphertext),
            )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("VAULT_SESSION_SECRET", "disposable-takeover-session-secret-" + "x" * 48)
    auth_local.reset_secret_for_tests()
    for module in (auth_local, device_gate, device_monitor, auth_routes, device_routes):
        monkeypatch.setattr(module, "get_db", _connect)
    device_monitor._reset_monitor_cache_for_tests()
    try:
        yield {"vault_id": vault_id, "account_id": account_id, "ciphertext": ciphertext}
    finally:
        auth_local.reset_secret_for_tests()
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM vaults WHERE vault_id = %s AND account_id = %s", (vault_id, account_id))
                cur.execute("DELETE FROM accounts WHERE account_id = %s", (account_id,))
            conn.commit()
        finally:
            conn.close()


def _issue(vault, device):
    return auth_local.issue_session_token(vault_id=vault["vault_id"], device_id=device,
                                          client_label="Safari on iOS")


def _register(vault, issued, device):
    return device_monitor.register_or_refresh(
        vault_id=vault["vault_id"], session_token_id=issued["token_id"], device_id=device,
        label="Synthetic device name", user_agent_brand="Synthetic metadata", ip_prefix=None,
    )


def _state(vault):
    return {
        "sessions": _rows("SELECT token_id::text, device_id, revoked_reason, revoked_at FROM auth_sessions WHERE vault_id=%s ORDER BY issued_at,token_id", (vault["vault_id"],)),
        "devices": _rows("SELECT device_id,status FROM trusted_devices WHERE vault_id=%s ORDER BY device_id", (vault["vault_id"],)),
        "events": _rows("SELECT event_type,client_label FROM vault_security_events WHERE vault_id=%s ORDER BY event_id", (vault["vault_id"],)),
    }


def _assert_ciphertext_preserved(vault):
    row = _rows("SELECT account_id::text, wrapped_mvk,wrapped_sk_vault,display_name_ciphertext FROM vaults WHERE vault_id=%s", (vault["vault_id"],))[0]
    assert row["account_id"] == vault["account_id"]
    assert all(bytes(row[field]) == vault["ciphertext"] for field in
               ("wrapped_mvk", "wrapped_sk_vault", "display_name_ciphertext"))


def test_real_new_login_replaces_old_and_auth_me_accepts_only_winner(vault):
    old = _issue(vault, DEVICE_A)
    winner = _issue(vault, DEVICE_B)
    state = _state(vault)
    assert [r["device_id"] for r in state["sessions"] if r["revoked_at"] is None] == [DEVICE_B]
    assert state["devices"] == [{"device_id": DEVICE_A, "status": "revoked"},
                                {"device_id": DEVICE_B, "status": "trusted"}]
    assert state["sessions"][0]["revoked_reason"] == "superseded-by-new-login"
    app = FastAPI()
    app.include_router(auth_routes.router)
    with TestClient(app) as client:
        before = client.get("/auth/me", headers={"Authorization": f"Bearer {old['token']}", "X-Device-ID": DEVICE_A})
        after = client.get("/auth/me", headers={"Authorization": f"Bearer {winner['token']}", "X-Device-ID": DEVICE_B})
    assert before.status_code == 401
    assert before.json()["detail"]["code"] == "session_superseded"
    assert after.status_code == 200
    assert after.json()["vault_id"] == vault["vault_id"]
    assert after.json()["vault_name"] is None
    _assert_ciphertext_preserved(vault)


def test_real_pin_login_http_takes_over_only_after_correct_credentials(vault, monkeypatch):
    """Exercise the real PIN verifier, issuer and device gate with two phones."""
    pin = "124578"
    salt = base64.b64encode(secrets.token_bytes(16)).decode()
    verifier = encrypt_message(
        PIN_VERIFIER_PLAINTEXT,
        derive_key(pin, salt, iterations=KDF_TARGET_ITERATIONS),
    )
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE vaults SET pin_salt=%s,pin_verifier=%s,kdf_iterations=%s
                     WHERE vault_id=%s AND account_id=%s RETURNING username_lookup_v1""",
                (salt, verifier, KDF_TARGET_ITERATIONS, vault["vault_id"], vault["account_id"]),
            )
            lookup = bytes(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    limiter = InMemoryRateLimitBackend()
    monkeypatch.setattr(rate_limit_auth, "get_rate_limit_backend", lambda: limiter)
    monkeypatch.delenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", raising=False)
    monkeypatch.setenv("VAULTAI_DEVICE_GATE_ENFORCE", "true")
    monkeypatch.setenv("VAULTAI_DEVICE_GATE_DEV_DISABLE", "false")
    payload = {"username_lookup": base64.urlsafe_b64encode(lookup).decode().rstrip("="), "pin": pin}
    app = FastAPI()
    app.include_router(auth_routes.router)

    @app.get("/synthetic-device-protected")
    def protected(principal=Depends(device_gate.verify_trusted_device)):
        return {"vault_id": principal["vault_id"]}

    def headers(token, device):
        return {"Authorization": "Bearer " + token, "X-Device-ID": device}

    with TestClient(app) as client:
        first = client.post("/auth/login", json=payload, headers={"X-Device-ID": DEVICE_A})
        assert first.status_code == 200, first.text
        old_token = first.json()["session_token"]
        assert client.get("/synthetic-device-protected", headers=headers(old_token, DEVICE_A)).status_code == 200
        failed = client.post("/auth/login", json={**payload, "pin": "000000"}, headers={"X-Device-ID": DEVICE_B})
        assert failed.status_code == 401
        assert client.get("/auth/me", headers=headers(old_token, DEVICE_A)).status_code == 200
        second = client.post("/auth/login", json=payload, headers={"X-Device-ID": DEVICE_B})
        assert second.status_code == 200, second.text
        new_token = second.json()["session_token"]
        old = client.get("/auth/me", headers=headers(old_token, DEVICE_A))
        assert old.status_code == 401 and old.json()["detail"]["code"] == "session_superseded"
        assert client.get("/auth/me", headers=headers(new_token, DEVICE_B)).status_code == 200
        assert client.get("/synthetic-device-protected", headers=headers(old_token, DEVICE_A)).status_code == 401
        assert client.get("/synthetic-device-protected", headers=headers(new_token, DEVICE_B)).status_code == 200
    state = _state(vault)
    assert [row["device_id"] for row in state["sessions"] if row["revoked_at"] is None] == [DEVICE_B]
    assert [row["device_id"] for row in state["devices"] if row["status"] == "trusted"] == [DEVICE_B]
    _assert_ciphertext_preserved(vault)


def test_real_concurrent_logins_keep_session_and_trusted_device_consistent(vault):
    for _ in range(4):
        barrier = threading.Barrier(3)
        def login(device):
            barrier.wait(timeout=10)
            return _issue(vault, device)
        with ThreadPoolExecutor(max_workers=3) as pool:
            issued = list(pool.map(login, (DEVICE_A, DEVICE_B, DEVICE_C)))
        state = _state(vault)
        active = [r for r in state["sessions"] if r["revoked_at"] is None]
        trusted = [r for r in state["devices"] if r["status"] == "trusted"]
        assert len(active) == len(trusted) == 1
        assert active[0]["device_id"] == trusted[0]["device_id"]
        successful = []
        for device, session in zip((DEVICE_A, DEVICE_B, DEVICE_C), issued):
            try:
                principal = asyncio.run(auth_local.verify_session_token(_request(session["token"], device)))
                successful.append(principal["token_id"])
            except HTTPException as err:
                assert err.status_code == 401 and err.detail["code"] == "session_superseded"
        assert successful == [active[0]["token_id"]]
    _assert_ciphertext_preserved(vault)


def test_real_late_old_request_and_spoofed_header_cannot_retrust_old_device(vault):
    old = _issue(vault, DEVICE_A)
    old_principal = asyncio.run(auth_local.verify_session_token(_request(old["token"], DEVICE_A)))
    winner = _issue(vault, DEVICE_B)
    before = _state(vault)
    device_monitor._reset_monitor_cache_for_tests()
    device_monitor.monitor_best_effort(_request(old["token"], DEVICE_A), old_principal)
    device_monitor.monitor_best_effort(_request(old["token"], DEVICE_B), old_principal)
    with pytest.raises(HTTPException) as old_err:
        _register(vault, old, DEVICE_A)
    assert old_err.value.status_code == 401 and old_err.value.detail["code"] == "session_superseded"
    with pytest.raises(HTTPException) as pivot_err:
        _register(vault, winner, DEVICE_A)
    assert pivot_err.value.status_code == 403 and pivot_err.value.detail["code"] == "device_session_mismatch"
    assert _state(vault) == before
    assert _register(vault, winner, DEVICE_B)["status"] == "trusted"
    _assert_ciphertext_preserved(vault)


def test_real_mid_transaction_database_error_preserves_old_session_and_device(vault):
    old = _issue(vault, DEVICE_A)
    before = _state(vault)
    real_takeover = device_monitor.apply_login_device_takeover
    def fail_after_device_writes(cursor, **kwargs):
        real_takeover(cursor, **kwargs)
        cursor.execute("SELECT 1 / 0")
    with mock.patch.object(device_monitor, "apply_login_device_takeover", side_effect=fail_after_device_writes), \
         mock.patch.object(auth_local, "_format_token") as format_token:
        with pytest.raises(psycopg2.errors.DivisionByZero):
            _issue(vault, DEVICE_B)
    format_token.assert_not_called()
    assert _state(vault) == before
    principal = asyncio.run(auth_local.verify_session_token(_request(old["token"], DEVICE_A)))
    assert principal["token_id"] == old["token_id"]
    _assert_ciphertext_preserved(vault)


def test_real_legacy_null_device_session_binds_once_not_to_arbitrary_later_device(vault):
    _issue(vault, DEVICE_A)
    current = _issue(vault, None)
    assert all(r["status"] == "revoked" for r in _state(vault)["devices"])
    assert _register(vault, current, DEVICE_B)["status"] == "trusted"
    before = _state(vault)
    with pytest.raises(HTTPException) as err:
        _register(vault, current, DEVICE_A)
    assert err.value.detail["code"] == "device_session_mismatch"
    assert _state(vault) == before
    _assert_ciphertext_preserved(vault)


def test_real_explicit_device_revocation_requires_fresh_login(vault):
    current = _issue(vault, DEVICE_A)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE trusted_devices SET status='revoked',revoked_at=NOW() WHERE vault_id=%s AND device_id=%s", (vault["vault_id"], DEVICE_A))
        conn.commit()
    finally:
        conn.close()
    before = _state(vault)
    with pytest.raises(HTTPException) as err:
        _register(vault, current, DEVICE_A)
    assert err.value.status_code == 403 and err.value.detail["code"] == "device_revoked"
    assert _state(vault) == before
    replacement = _issue(vault, DEVICE_A)
    assert _register(vault, replacement, DEVICE_A)["status"] == "trusted"
    _assert_ciphertext_preserved(vault)


def test_real_device_register_route_binds_only_its_current_session(vault):
    current = _issue(vault, DEVICE_A)
    app = FastAPI()
    app.include_router(device_routes.router)
    with TestClient(app) as client:
        same = client.post("/devices/register", headers={"Authorization": f"Bearer {current['token']}", "X-Device-ID": DEVICE_A}, json={"device_id": DEVICE_A, "label": "Synthetic phone name"})
        pivot = client.post("/devices/register", headers={"Authorization": f"Bearer {current['token']}", "X-Device-ID": DEVICE_B}, json={"device_id": DEVICE_B})
    assert same.status_code == 200 and same.json()["status"] == "trusted"
    assert pivot.status_code == 403 and pivot.json()["detail"]["code"] == "device_session_mismatch"
    assert [r for r in _state(vault)["devices"] if r["status"] == "trusted"] == [{"device_id": DEVICE_A, "status": "trusted"}]


def test_real_late_old_revoke_cannot_touch_winning_device_but_current_can_revoke_self(vault):
    old = _issue(vault, DEVICE_A)
    captured_principal = asyncio.run(auth_local.verify_session_token(_request(old["token"], DEVICE_A)))
    winner = _issue(vault, DEVICE_B)
    before = _state(vault)
    # Resume an endpoint that already passed entry-time authentication before
    # the winning login. It must now revalidate under the same vault lock.
    with mock.patch.object(device_routes, "_notify") as notify:
        with pytest.raises(HTTPException) as err:
            asyncio.run(device_routes.revoke_device_endpoint(
                device_routes.TargetDeviceRequest(device_id=DEVICE_B),
                _request(old["token"], DEVICE_A, "/devices/revoke"), captured_principal,
            ))
        assert err.value.status_code == 401 and err.value.detail["code"] == "session_superseded"
        assert _state(vault) == before
        notify.assert_not_called()
        current_principal = asyncio.run(auth_local.verify_session_token(_request(winner["token"], DEVICE_B)))
        result = asyncio.run(device_routes.revoke_device_endpoint(
            device_routes.TargetDeviceRequest(device_id=DEVICE_B),
            _request(winner["token"], DEVICE_B, "/devices/revoke"), current_principal,
        ))
        assert result["status"] == "revoked" and result["caller_revoked"] is True
        notify.assert_called_once()
    assert all(r["status"] == "revoked" for r in _state(vault)["devices"])
    _assert_ciphertext_preserved(vault)
