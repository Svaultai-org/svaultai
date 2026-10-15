"""Synthetic auth throttles: no database, secrets or customer records."""

import asyncio
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import rate_limit_auth as limits
import rate_limit_backend as backends


def request(ip="192.0.2.1", headers=()):
    return Request({"type": "http", "client": (ip, 12345), "headers": headers})


@pytest.fixture(autouse=True)
def isolated_limiter(monkeypatch):
    monkeypatch.delenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", raising=False)
    backend = backends.InMemoryRateLimitBackend()
    monkeypatch.setattr(limits, "get_rate_limit_backend", lambda: backend)
    return backend


def check(req, identity=b"x" * 32, kind="lookup"):
    limits.enforce_login_credential_rate_limit(
        req, credential_id=identity, kind=kind,
    )


def test_six_exchanges_then_explicit_bounded_retry(isolated_limiter):
    for _ in range(6):
        check(request())
    with pytest.raises(HTTPException) as caught:
        check(request())
    error = caught.value
    assert error.status_code == 429
    assert 1 <= error.detail["reset_in_seconds"] <= 60
    assert error.headers["Retry-After"] == str(error.detail["reset_in_seconds"])
    assert str(error.detail["reset_in_seconds"]) in error.detail["message"]
    # Both source and opaque identifier are hashed by the shared backend.
    assert not any("192.0.2.1" in key or (b"x" * 32).hex() in key for key in isolated_limiter._state)


def test_another_source_or_identifier_is_not_globally_locked():
    for _ in range(6):
        check(request())
    check(request("192.0.2.2"))
    check(request(), b"y" * 32)
    with pytest.raises(HTTPException):
        check(request())


def test_forwarded_headers_do_not_select_fresh_source_budgets():
    for number in range(6):
        check(request(headers=[
            (b"x-forwarded-for", f"198.51.100.{number}".encode()),
            (b"x-real-ip", f"203.0.113.{number}".encode()),
        ]))
    with pytest.raises(HTTPException):
        check(request(headers=[(b"x-forwarded-for", b"203.0.113.99")]))


def test_verified_single_hop_uses_overwritten_real_ip_not_forged_asgi_prefix(monkeypatch):
    monkeypatch.setenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", "nginx_single_hop")
    for number in range(6):
        check(request(f"198.51.100.{number}", headers=[
            (b"x-real-ip", b"192.0.2.44"),
            (b"x-forwarded-for", f"198.51.100.{number}, 192.0.2.44".encode()),
        ]))
    with pytest.raises(HTTPException):
        check(request("203.0.113.99", headers=[
            (b"x-real-ip", b"192.0.2.44"),
            (b"x-forwarded-for", b"203.0.113.99, 192.0.2.44"),
        ]))
    # Another actual source still has its own budget.
    check(request(headers=[(b"x-real-ip", b"192.0.2.45"), (b"x-forwarded-for", b"192.0.2.45")]))


@pytest.mark.parametrize("headers", [
    [], [(b"x-real-ip", b"192.0.2.44")],
    [(b"x-real-ip", b"192.0.2.44"), (b"x-forwarded-for", b"192.0.2.45")],
    [(b"x-real-ip", b"not-an-ip"), (b"x-forwarded-for", b"not-an-ip")],
    [(b"x-real-ip", b"fe80::1%eth0"), (b"x-forwarded-for", b"fe80::1%eth0")],
    [(b"x-real-ip", b"192.0.2.44"), (b"x-forwarded-for", b"x" * 1025)],
    [(b"x-real-ip", b"192.0.2.44"), (b"x-forwarded-for", b"192.0.2.44," * 17 + b"192.0.2.44")],
])
def test_malformed_boundary_collapses_to_one_fixed_budget(monkeypatch, headers):
    monkeypatch.setenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", "nginx_single_hop")
    assert limits._client_ip(request("203.0.113.1", headers)) == "unknown"
    assert limits._client_ip(request("203.0.113.2", headers)) == "unknown"


def test_ipv6_boundary_normalizes_both_addresses(monkeypatch):
    monkeypatch.setenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", "nginx_single_hop")
    req = request(headers=[(b"x-real-ip", b"2001:db8::1"), (b"x-forwarded-for", b"2001:0db8:0:0:0:0:0:1")])
    assert limits._client_ip(req) == "2001:db8::1"


def test_unknown_boundary_mode_fails_closed_before_limiter(monkeypatch):
    monkeypatch.setenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", "untrusted")
    with pytest.raises(HTTPException) as caught:
        check(request())
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == "auth_temporarily_unavailable"


def test_budget_expires_without_extending_on_rejected_requests(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(backends.time, "monotonic", lambda: clock[0])
    for _ in range(6):
        check(request())
    clock[0] = 159.9
    with pytest.raises(HTTPException) as caught:
        check(request())
    assert caught.value.headers["Retry-After"] == "1"
    clock[0] = 160.01
    check(request())


@pytest.mark.parametrize("identity,kind", [(b"x", "lookup"), ("x" * 32, "lookup"), (b"x" * 32, "name")])
def test_raw_names_and_invalid_identifier_shapes_are_not_accepted(identity, kind):
    with pytest.raises(ValueError):
        check(request(), identity, kind)


def test_new_buckets_fail_closed_when_redis_is_unavailable(monkeypatch):
    offline = backends.RedisRateLimitBackend(url="redis://unused", client=mock.Mock())
    offline._client = None
    monkeypatch.setattr(limits, "get_rate_limit_backend", lambda: offline)
    with pytest.raises(HTTPException) as caught:
        check(request())
    assert caught.value.status_code == 429
    with pytest.raises(HTTPException):
        limits.enforce_login_finalize_rate_limit(request())


def test_legacy_and_zk_init_throttle_before_any_account_lookup(monkeypatch):
    from routes import auth_routes, auth_zk_routes
    from vault_handle import to_display
    import base64

    identity = b"x" * 32
    lookup = base64.urlsafe_b64encode(identity).decode().rstrip("=")
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(auth_zk_routes.router)
    client = TestClient(app)
    # The request's synthetic IP is not a real address. Unknown still has a
    # stable budget; a forged forwarding header cannot change it.
    for _ in range(6):
        check(request("testclient"), identity)
    monkeypatch.setattr(auth_routes, "enforce_login_rate_limit", lambda req: None)
    monkeypatch.setattr(auth_zk_routes, "enforce_login_rate_limit", lambda req: None)
    with mock.patch.object(auth_routes, "get_db", side_effect=AssertionError("DB reached")), \
         mock.patch.object(auth_zk_routes, "get_db", side_effect=AssertionError("DB reached")):
        legacy = client.post("/auth/login", json={"username_lookup": lookup, "pin": "000001"})
        zk = client.post("/auth/zk-login-init", json={
            "vault_handle": to_display(b"h" * 15), "username_lookup": lookup,
            "ke1": base64.urlsafe_b64encode(b"synthetic-ke1").decode(),
        })
    assert legacy.status_code == zk.status_code == 429
    assert legacy.json()["detail"]["code"] == zk.json()["detail"]["code"] == "rate_limited"
    assert "Retry-After" in legacy.headers and "Retry-After" in zk.headers


def test_finalize_throttle_precedes_slot_consumption(monkeypatch):
    from routes import auth_zk_routes
    monkeypatch.setattr(limits, "LOGIN_FINALIZE_LIMIT", 2)
    limits.enforce_login_finalize_rate_limit(request())
    limits.enforce_login_finalize_rate_limit(request())
    with mock.patch.object(auth_zk_routes, "get_db", side_effect=AssertionError("slot consumed")):
        with pytest.raises(HTTPException) as caught:
            asyncio.run(auth_zk_routes.zk_login_finalize(
                auth_zk_routes.ZkLoginFinalizeRequest(slot_id="synthetic", ke3="eA"), request(),
            ))
    assert caught.value.status_code == 429


class LegacyConnection:
    def __init__(self, row, now):
        self.row, self.now = row, now
        self.statements = []
        self.commits = 0
        self.closed = False

    def cursor(self, **kwargs):
        return self

    def execute(self, sql, parameters=()):
        self.statements.append(" ".join(sql.lower().split()))

    def fetchone(self):
        return {"now": self.now} if self.statements[-1].startswith("select now()") else self.row

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.closed = True


def legacy_fixture(monkeypatch, *, correct, locked=False):
    from routes import auth_routes
    from datetime import datetime, timedelta, timezone
    import base64
    now = datetime.now(timezone.utc)
    row = {
        "vault_id": "00000000-0000-0000-0000-000000000001",
        "pin_salt": "synthetic", "pin_verifier": "synthetic",
        "kdf_iterations": 600000, "failed_pin_attempts": 4,
        "locked_until": now + timedelta(seconds=59) if locked else None,
        "must_reset": False,
    }
    connection = LegacyConnection(row, now)
    monkeypatch.setattr(auth_routes, "get_db", lambda: connection)
    monkeypatch.setattr(auth_routes, "enforce_login_rate_limit", lambda req: None)
    monkeypatch.setattr(auth_routes, "derive_key", lambda *args, **kwargs: b"synthetic-key")
    monkeypatch.setattr(auth_routes, "decrypt_message", lambda *args: auth_routes.PIN_VERIFIER_PLAINTEXT if correct else "invalid")
    payload = auth_routes.LoginRequest(username_lookup=base64.urlsafe_b64encode(b"l" * 32).decode(), pin="000001")
    return auth_routes, payload, connection


@pytest.mark.parametrize("locked", [False, True])
def test_wrong_legacy_pin_does_not_change_global_vault_lock_or_reveal_lock(monkeypatch, locked):
    routes, payload, connection = legacy_fixture(monkeypatch, correct=False, locked=locked)
    with pytest.raises(HTTPException) as caught:
        routes.login(payload, request())
    assert caught.value.status_code == 401
    assert caught.value.detail == routes.GENERIC_LOGIN_ERROR
    assert not any(sql.startswith("update") for sql in connection.statements)
    assert connection.commits == 0 and connection.closed


def test_verified_legacy_pin_preserves_existing_lock_with_retry_after(monkeypatch):
    routes, payload, connection = legacy_fixture(monkeypatch, correct=True, locked=True)
    with pytest.raises(HTTPException) as caught:
        routes.login(payload, request())
    error = caught.value
    assert error.status_code == 423
    assert error.detail["code"] == "pin_locked"
    assert error.detail["reset_in_seconds"] == 60
    assert error.headers["Retry-After"] == "60"
    assert "60 seconds" in error.detail["message"]
    assert not any(sql.startswith("update") for sql in connection.statements)
    assert connection.commits == 0 and connection.closed


def test_zk_init_three_two_exchange_submissions_then_retry_and_recovery(monkeypatch):
    """OPAQUE never sends a PIN to the init endpoint. Its two compatibility
    exchanges are bounded, and recovery needs no vault lock/credential edit.
    The OPAQUE boundary is synthetic; actual crypto is unchanged and tested
    by the existing protocol suites rather than asserted by this fixture.
    """
    import base64
    from datetime import datetime, timezone
    from routes import auth_zk_routes
    from vault_handle import to_display
    clock = [100.0]
    monkeypatch.setattr(backends.time, "monotonic", lambda: clock[0])
    row = {
        "vault_id": "00000000-0000-0000-0000-000000000001",
        "vault_handle": b"h" * 15,
        "username_lookup_v1": b"l" * 32,
        "opaque_registration_record": b"synthetic-record",
    }
    connections = []

    def get_db():
        connection = LegacyConnection(row, datetime.now(timezone.utc))
        connections.append(connection)
        return connection

    monkeypatch.setattr(auth_zk_routes, "get_db", get_db)
    opaque = mock.Mock(return_value=(b"synthetic-ke2", b"synthetic-state"))
    monkeypatch.setattr(auth_zk_routes, "opaque_login_start", opaque)
    app = FastAPI()
    app.include_router(auth_zk_routes.router)
    client = TestClient(app)
    payload = {
        "vault_handle": to_display(row["vault_handle"]),
        "username_lookup": base64.urlsafe_b64encode(row["username_lookup_v1"]).decode(),
        "ke1": base64.urlsafe_b64encode(b"synthetic-ke1").decode(),
    }
    for _ in range(3):
        for _ in range(2):
            assert client.post("/auth/zk-login-init", json=payload).status_code == 200
    assert opaque.call_count == 6
    before = len(connections)
    blocked = client.post("/auth/zk-login-init", json=payload)
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["reset_in_seconds"] == 60
    assert blocked.headers["Retry-After"] == "60"
    assert len(connections) == before and opaque.call_count == 6
    # A rejected retry must not extend the cooldown. A fresh exchange after
    # expiration is accepted without resetting names, PINs, keys or rows.
    clock[0] = 160.01
    recovered = client.post("/auth/zk-login-init", json=payload)
    assert recovered.status_code == 200 and opaque.call_count == 7
    assert not any(sql.startswith("update vaults") for conn in connections for sql in conn.statements)
    assert all(conn.closed for conn in connections)


def test_distinct_modern_handle_and_legacy_lookup_share_lookup_budget(monkeypatch, isolated_limiter):
    """Actual HTTP sequence with H15 and L32: init increments both, legacy
    login increments the SAME L32 budget, not a fresh legacy-kind bucket.
    All database/OPAQUE/PIN/session boundaries remain synthetic fixtures.
    """
    import base64
    from datetime import datetime, timedelta, timezone
    from routes import auth_zk_routes
    from vault_handle import to_display
    legacy, legacy_payload, template = legacy_fixture(monkeypatch, correct=False)
    # Include the real coarse source budget too; the short identifier budget
    # is what should deny this sequence, not a test-only transport shortcut.
    monkeypatch.setattr(legacy, "enforce_login_rate_limit", limits.enforce_login_rate_limit)
    handle = b"h" * 15
    lookup = b"l" * 32
    clock = [100.0]
    monkeypatch.setattr(backends.time, "monotonic", lambda: clock[0])
    connections = []

    def connection(row):
        value = LegacyConnection(row, template.now)
        connections.append(value)
        return value

    monkeypatch.setattr(legacy, "get_db", lambda: connection(template.row))
    monkeypatch.setattr(auth_zk_routes, "get_db", lambda: connection({
        "vault_id": template.row["vault_id"],
        "vault_handle": handle, "username_lookup_v1": lookup,
        "opaque_registration_record": b"synthetic-record",
    }))
    monkeypatch.setattr(auth_zk_routes, "opaque_login_start", lambda *args: (b"synthetic-ke2", b"synthetic-state"))
    app = FastAPI()
    app.include_router(legacy.router)
    app.include_router(auth_zk_routes.router)
    client = TestClient(app)
    modern_payload = {
        "vault_handle": to_display(handle),
        "username_lookup": base64.urlsafe_b64encode(lookup).decode(),
        "ke1": base64.urlsafe_b64encode(b"synthetic-ke1").decode(),
    }
    for _ in range(3):
        assert client.post("/auth/zk-login-init", json=modern_payload).status_code == 200
        assert client.post("/auth/login", json=legacy_payload.model_dump()).status_code == 401
    handle_key = backends._compose_key(limits.BUCKET_LOGIN_CREDENTIAL, f"ip:unknown:handle:{handle.hex()}")
    lookup_key = backends._compose_key(limits.BUCKET_LOGIN_CREDENTIAL, f"ip:unknown:lookup:{lookup.hex()}")
    assert len(isolated_limiter._state[handle_key]) == 3
    assert len(isolated_limiter._state[lookup_key]) == 6
    before = len(connections)
    # Even though H has only three uses, L's six shared exchanges must deny
    # both modern and legacy correct-proof attempts BEFORE account lookup.
    modern_blocked = client.post("/auth/zk-login-init", json=modern_payload)
    legacy_blocked = client.post("/auth/login", json=legacy_payload.model_dump())
    assert modern_blocked.status_code == legacy_blocked.status_code == 429
    assert modern_blocked.headers["Retry-After"] == legacy_blocked.headers["Retry-After"] == "60"
    assert len(connections) == before
    assert not any(sql.startswith("update vaults") for conn in connections for sql in conn.statements)

    clock[0] = 160.01
    monkeypatch.setattr(legacy, "decrypt_message", lambda *args: legacy.PIN_VERIFIER_PLAINTEXT)
    monkeypatch.setattr(legacy, "issue_session_token", lambda **kwargs: {
        "token": "synthetic-test-session", "token_id": "synthetic-test-token-id",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "vault_id": template.row["vault_id"], "vault_name": "",
        "client_label": "Unknown device",
    })
    recovered = client.post("/auth/login", json=legacy_payload.model_dump())
    assert recovered.status_code == 200
    assert recovered.json()["session_token"] == "synthetic-test-session"
