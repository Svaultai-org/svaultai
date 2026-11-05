"""Synthetic auth latency and temporary budgets; no production requests."""

import asyncio
import base64
import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from unittest import mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import rate_limit_auth as limits
import rate_limit_backend as backends

# Imports require a DB URL; every DB boundary below is mocked and this
# deliberately unreachable loopback endpoint cannot address production.
os.environ.setdefault("DATABASE_URL", "postgresql://synthetic:synthetic@127.0.0.1:1/synthetic")
from routes import auth_routes, auth_zk_routes
from vault_handle import to_display


def request(ip="192.0.2.1"):
    return Request({"type": "http", "client": (ip, 12345), "headers": []})


@pytest.fixture
def isolated_limits(monkeypatch):
    backend = backends.InMemoryRateLimitBackend()
    monkeypatch.delenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", raising=False)
    monkeypatch.setattr(limits, "get_rate_limit_backend", lambda: backend)
    monkeypatch.setattr(limits, "LOGIN_LIMIT_PER_WINDOW", 10)
    monkeypatch.setattr(limits, "LOGIN_WINDOW_SECONDS", 60)
    monkeypatch.setattr(limits, "LOGIN_VAULT_LIMIT", 10)
    return backend


def test_malformed_probe_is_fast_counted_and_expires(monkeypatch, isolated_limits, caplog):
    clock = [100.0]
    monkeypatch.setattr(backends.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(auth_routes, "get_db", mock.Mock(side_effect=AssertionError("DB reached")))
    monkeypatch.setattr(auth_routes, "derive_key", mock.Mock(side_effect=AssertionError("KDF reached")))
    app = FastAPI()
    app.include_router(auth_routes.router)
    client = TestClient(app)
    payload = {"username_lookup": "QA-RATELIMIT-PROBE-2099", "pin": "000000"}
    with caplog.at_level(logging.INFO, logger=auth_routes.__name__):
        for _ in range(10):
            started = time.perf_counter()
            response = client.post("/auth/login", json=payload)
            assert time.perf_counter() - started < 1.0
            assert response.status_code == 400
            assert response.json()["detail"] == "Invalid username lookup"
        blocked = client.post("/auth/login", json=payload)
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert not auth_routes.get_db.called and not auth_routes.derive_key.called
    diagnostic = "\n".join(record.getMessage() for record in caplog.records)
    assert all(name in diagnostic for name in ("limiter_ms=", "validation_ms=", "db_ms=", "kdf_ms=", "total_ms="))
    assert payload["username_lookup"] not in diagnostic and payload["pin"] not in diagnostic
    clock[0] = 159.9
    assert client.post("/auth/login", json=payload).status_code == 429
    clock[0] = 160.01
    assert client.post("/auth/login", json=payload).status_code == 400


def test_login_minute_window_does_not_shorten_signup_window(monkeypatch, isolated_limits):
    clock = [100.0]
    monkeypatch.setattr(backends.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(limits, "WINDOW_SECONDS", 3600)
    monkeypatch.setattr(limits, "SIGNUP_LIMIT_PER_WINDOW", 1)
    limits.enforce_signup_rate_limit(request())
    for _ in range(10):
        limits.enforce_login_rate_limit(request())
    clock[0] = 160.01
    limits.enforce_login_rate_limit(request())
    with pytest.raises(HTTPException) as denied:
        limits.enforce_signup_rate_limit(request())
    assert denied.value.status_code == 429
    assert int(denied.value.headers["Retry-After"]) > 60


def test_distributed_vault_budget_is_temporary_and_other_vault_works(monkeypatch, isolated_limits):
    clock = [100.0]
    monkeypatch.setattr(backends.time, "monotonic", lambda: clock[0])
    identity = b"v" * 32
    for source in range(1, 11):
        limits.enforce_login_credential_rate_limit(request(f"192.0.2.{source}"), credential_id=identity, kind="lookup")
    with pytest.raises(HTTPException) as blocked:
        limits.enforce_login_credential_rate_limit(request("192.0.2.11"), credential_id=identity, kind="lookup")
    assert blocked.value.status_code == 429
    assert int(blocked.value.headers["Retry-After"]) == 60
    limits.enforce_login_credential_rate_limit(request("192.0.2.11"), credential_id=b"w" * 32, kind="lookup")
    clock[0] = 159.9
    with pytest.raises(HTTPException):
        limits.enforce_login_credential_rate_limit(request("192.0.2.12"), credential_id=identity, kind="lookup")
    clock[0] = 160.01
    limits.enforce_login_credential_rate_limit(request("192.0.2.13"), credential_id=identity, kind="lookup")
    assert not any(identity.hex() in key or "192.0.2." in key for key in isolated_limits._state)


def test_modern_and_legacy_share_global_lookup_budget(monkeypatch, isolated_limits):
    lookup = base64.urlsafe_b64encode(b"l" * 32).decode()
    monkeypatch.setattr(limits, "_client_ip", lambda req: req.headers["x-test-source"])
    connection = mock.Mock()
    connection.cursor.return_value.fetchone.return_value = None
    monkeypatch.setattr(auth_routes, "get_db", lambda: connection)
    monkeypatch.setattr(auth_zk_routes, "get_db", lambda: connection)
    monkeypatch.setattr(auth_routes, "_do_dummy_derive", lambda pin: None)
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(auth_zk_routes.router)
    client = TestClient(app)
    modern = {"vault_handle": to_display(b"h" * 15), "username_lookup": lookup, "ke1": "eA"}
    legacy = {"username_lookup": lookup, "pin": "000000"}
    for number in range(10):
        path, payload = ("/auth/zk-login-init", modern) if number % 2 else ("/auth/login", legacy)
        response = client.post(path, json=payload, headers={"x-test-source": f"192.0.2.{number + 1}"})
        assert response.status_code == 401
    prior_calls = connection.cursor.call_count
    for path, payload in (("/auth/login", legacy), ("/auth/zk-login-init", modern)):
        blocked = client.post(path, json=payload, headers={"x-test-source": "192.0.2.20"})
        assert blocked.status_code == 429
        assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert connection.cursor.call_count == prior_calls


@contextmanager
def redis_blackhole():
    """Accept local TCP connections but never answer a Redis command."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.05)
    stop = threading.Event()
    accepted = []

    def serve():
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            accepted.append(conn)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield f"redis://127.0.0.1:{listener.getsockname()[1]}/0", accepted
    finally:
        stop.set()
        listener.close()
        for conn in accepted:
            conn.close()
        thread.join(timeout=1)


def test_real_blackhole_socket_is_bounded_and_auth_fails_closed():
    pytest.importorskip("redis")
    with redis_blackhole() as (url, accepted):
        backend = backends.RedisRateLimitBackend(url=url)
        started = time.perf_counter()
        decision = backend.check_and_increment(user_id="ip:192.0.2.1", bucket="auth_login", limit_per_window=10, window_seconds=60)
        elapsed = time.perf_counter() - started
        assert not decision.allowed and decision.reset_in_seconds == 60
        assert elapsed < 0.8
        assert len(accepted) == 1, "A timed-out connection must not be retried"
        backend._client.close()


def test_redis_url_cannot_override_socket_or_retry_bounds():
    pytest.importorskip("redis")
    backend = backends.RedisRateLimitBackend(url="redis://127.0.0.1:1/0?socket_timeout=16&socket_connect_timeout=16&retry_on_timeout=True&health_check_interval=30")
    kwargs = backend._client.connection_pool.connection_kwargs
    assert kwargs["socket_timeout"] == kwargs["socket_connect_timeout"] == 0.2
    assert kwargs["retry_on_timeout"] is False
    assert kwargs["retry_on_error"] == [] and kwargs["health_check_interval"] == 0
    assert kwargs["retry"].get_retries() == 0
    backend._client.close()


@pytest.mark.parametrize("path,limiter", [
    ("/auth/zk-login-init", "enforce_login_init_rate_limits"),
    ("/auth/zk-register-init", "enforce_signup_rate_limit"),
])
def test_blocked_auth_dependency_does_not_stall_unrelated_route(monkeypatch, path, limiter):
    entered, release = threading.Event(), threading.Event()

    def blocked(req, **_kwargs):
        entered.set()
        release.wait(timeout=2)
        raise HTTPException(status_code=429, detail="synthetic limit")

    monkeypatch.setattr(auth_zk_routes, limiter, blocked)
    app = FastAPI()
    app.include_router(auth_zk_routes.router)

    @app.get("/unrelated")
    async def unrelated():
        return {"ok": True}

    payload = {"vault_handle": to_display(b"h" * 15), "username_lookup": base64.urlsafe_b64encode(b"l" * 32).decode(), "ke1": "eA"}

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://synthetic") as client:
            started = time.perf_counter()
            pending = asyncio.create_task(client.post(path, json=payload))
            try:
                assert await asyncio.to_thread(entered.wait, 0.5)
                assert time.perf_counter() - started < 0.5
                assert not pending.done()
                ping_started = time.perf_counter()
                response = await client.get("/unrelated")
                assert response.status_code == 200
                assert time.perf_counter() - ping_started < 0.5
            finally:
                release.set()
                response = await pending
            assert response.status_code == 429

    asyncio.run(exercise())
