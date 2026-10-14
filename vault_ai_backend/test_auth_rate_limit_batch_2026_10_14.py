"""Ordered auth budgets retain legacy counters and stop at the same denial.

The protocol fake checks key/argument construction and ordered decisions.
Set VAULTAI_RATE_LIMIT_BATCH_TEST_REDIS_URL to an explicitly approved synthetic
test Redis to additionally execute the Lua against a real Redis engine.
"""

from __future__ import annotations

import os
import types
import uuid
from unittest import mock

import pytest
from fastapi import HTTPException

import rate_limit_auth as auth
from rate_limit_backend import (
    InMemoryRateLimitBackend,
    RateLimitBackend,
    RateLimitCheck,
    RateLimitDecision,
    RedisRateLimitBackend,
    _REDIS_ORDERED_WINDOWS_LUA,
    _REDIS_SLIDING_WINDOW_LUA,
    _compose_key,
)
from test_rate_limit_redis_backend_2026_07_08 import _FakeRedis


HANDLE = bytes(range(15))
LOOKUP = bytes(range(32))


def request(ip="192.0.2.10"):
    return types.SimpleNamespace(headers={}, client=types.SimpleNamespace(host=ip))


def checks(ip="192.0.2.10", handle=HANDLE, lookup=LOOKUP):
    # Reference the exact original single-check identifiers, including the
    # shared legacy lookup namespace; this does not use the new builder.
    result = [RateLimitCheck(f"ip:{ip}", "auth_login", 10, 60)]
    for kind, opaque_id in (("handle", handle), ("lookup", lookup)):
        if opaque_id is None:
            continue
        result.extend((
            RateLimitCheck(f"ip:{ip}:{kind}:{opaque_id.hex()}", "auth_login_credential", 6, 60),
            RateLimitCheck(f"{kind}:{opaque_id.hex()}", "auth_login_vault", 10, 60),
        ))
    return result


class ProtocolRedis(_FakeRedis):
    """Reuse the legacy protocol model for each declared batch key."""
    def __init__(self):
        super().__init__()
        self.eval_calls = []
        self.single_sha = self.script_load(_REDIS_SLIDING_WINDOW_LUA)

    def eval(self, script, numkeys, *args):
        assert script == _REDIS_ORDERED_WINDOWS_LUA
        self.eval_calls.append((numkeys, args))
        keys = args[:numkeys]
        argv = args[numkeys:]
        now, prefix = argv[:2]
        result = []
        for i, key in enumerate(keys):
            window_ms, limit = argv[2 + 2 * i:4 + 2 * i]
            decision = super().evalsha(
                self.single_sha, 1, key, now, window_ms, limit, f"{prefix}:{i + 1}",
            )
            result.extend(decision)
            if not decision[0]:
                break
        return result


def summary(decisions):
    return [(d.allowed, d.remaining, d.reset_in_seconds) for d in decisions]


def state(client):
    return {key: [score for score, _member in values] for key, values in client._state.items()}


@pytest.mark.parametrize("denial_index", (None, 0, 1, 2, 3, 4))
def test_batch_matches_sequential_counts_denial_order_and_expiry(denial_index):
    ordered = checks()
    single_client, batch_client = ProtocolRedis(), ProtocolRedis()
    single = RedisRateLimitBackend(url="redis://synthetic", client=single_client, batch_enabled=False)
    batch = RedisRateLimitBackend(url="redis://synthetic", client=batch_client, batch_enabled=True)
    if denial_index is not None:
        check = ordered[denial_index]
        with mock.patch("rate_limit_backend.time.time", return_value=1000):
            for backend in (single, batch):
                for _ in range(check.limit_per_window):
                    assert backend.check_and_increment(**check.__dict__).allowed
    with mock.patch("rate_limit_backend.time.time", return_value=1010):
        expected = single.check_and_increment_many(ordered)
        actual = batch.check_and_increment_many(ordered)
    assert summary(actual) == summary(expected)
    assert state(batch_client) == state(single_client)
    assert batch_client._expires == single_client._expires
    assert len(batch_client.eval_calls) == 1
    assert not single_client.eval_calls
    if denial_index is not None:
        assert len(actual) == denial_index + 1
        denied_key = _compose_key(ordered[denial_index].bucket, ordered[denial_index].user_id).encode()
        assert batch_client._expires[denied_key] == 1_061_000


def test_expired_batch_and_single_hits_share_existing_storage_keys():
    client = ProtocolRedis()
    backend = RedisRateLimitBackend(url="redis://synthetic", client=client, batch_enabled=True)
    check = RateLimitCheck("synthetic-shared-lookup", "auth_login_vault", 1, 60)
    with mock.patch("rate_limit_backend.time.time", return_value=1000):
        assert backend.check_and_increment(**check.__dict__).allowed
        assert not backend.check_and_increment_many([check])[0].allowed
    with mock.patch("rate_limit_backend.time.time", return_value=1060):
        assert backend.check_and_increment_many([check])[0].allowed
        assert not backend.check_and_increment(**check.__dict__).allowed
    assert list(client._state) == [_compose_key(check.bucket, check.user_id).encode()]


def test_no_raw_identifiers_are_sent_in_batch_keys_or_arguments():
    client = ProtocolRedis()
    backend = RedisRateLimitBackend(url="redis://synthetic", client=client, batch_enabled=True)
    with mock.patch("rate_limit_backend.time.time", return_value=1000):
        backend.check_and_increment_many(checks())
    numkeys, args = client.eval_calls[0]
    assert list(args[:numkeys]) == [_compose_key(c.bucket, c.user_id) for c in checks()]
    transmitted = " ".join(str(value) for value in args)
    assert "192.0.2.10" not in transmitted
    assert HANDLE.hex() not in transmitted
    assert LOOKUP.hex() not in transmitted


@pytest.mark.parametrize("response", (
    [], [1, 9], [1, 9, 60], [0, 0, 60, 1, 9, 60],
    [2, 0, 60], [0, 1, 60], [0, 0, -1],
))
def test_invalid_batch_replies_fail_closed_without_retry(response):
    client = mock.Mock()
    client.eval.return_value = response
    backend = RedisRateLimitBackend(url="redis://synthetic", client=client, batch_enabled=True)
    result = backend.check_and_increment_many(checks())
    assert summary(result) == [(False, 0, 60)]
    assert client.eval.call_count == 1
    client.evalsha.assert_not_called()
    client.script_load.assert_not_called()


@pytest.mark.parametrize("error", (TimeoutError("synthetic timeout"), RuntimeError("CROSSSLOT")))
def test_transport_or_cross_slot_failure_never_retries_uncertain_increments(error):
    client = mock.Mock()
    client.eval.side_effect = error
    backend = RedisRateLimitBackend(url="redis://synthetic", client=client, batch_enabled=True)
    assert summary(backend.check_and_increment_many(checks())) == [(False, 0, 60)]
    assert client.eval.call_count == 1
    client.evalsha.assert_not_called()


def test_empty_batch_never_calls_redis():
    client = mock.Mock()
    backend = RedisRateLimitBackend(url="redis://synthetic", client=client, batch_enabled=True)
    assert backend.check_and_increment_many([]) == []
    client.eval.assert_not_called()


def test_default_batch_flag_retains_the_single_key_protocol(monkeypatch):
    monkeypatch.delenv("VAULTAI_RATE_LIMIT_REDIS_BATCH_ENABLED", raising=False)
    client = ProtocolRedis()
    backend = RedisRateLimitBackend(url="redis://synthetic", client=client)
    assert len(backend.check_and_increment_many(checks())) == 5
    assert not client.eval_calls


@pytest.mark.parametrize("lookup", (LOOKUP, None))
def test_init_helper_uses_exact_original_key_order(monkeypatch, lookup):
    backend = InMemoryRateLimitBackend()
    capture = mock.Mock(wraps=backend.check_and_increment_many)
    monkeypatch.setattr(backend, "check_and_increment_many", capture)
    monkeypatch.setattr(auth, "get_rate_limit_backend", lambda: backend)
    monkeypatch.delenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", raising=False)
    auth.enforce_login_init_rate_limits(request(), handle_bytes=HANDLE, lookup_bytes=lookup)
    assert capture.call_args.args == (checks(lookup=lookup),)


@pytest.mark.parametrize("handle,lookup", (
    (b"", LOOKUP), (bytes(16), LOOKUP), (HANDLE, bytes(31)), (HANDLE, bytes(33)),
))
def test_invalid_binary_identifiers_are_rejected_before_backend_access(monkeypatch, handle, lookup):
    backend = mock.Mock()
    monkeypatch.setattr(auth, "get_rate_limit_backend", backend)
    monkeypatch.delenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", raising=False)
    with pytest.raises(ValueError):
        auth.enforce_login_init_rate_limits(request(), handle_bytes=handle, lookup_bytes=lookup)
    backend.assert_not_called()


def test_duck_typed_and_spec_mock_backends_keep_sequential_denial_order(monkeypatch):
    backend = mock.Mock(spec=RateLimitBackend)
    backend.check_and_increment.side_effect = [
        RateLimitDecision(allowed=True, remaining=9, reset_in_seconds=60),
        RateLimitDecision(allowed=False, remaining=0, reset_in_seconds=17),
    ]
    monkeypatch.setattr(auth, "get_rate_limit_backend", lambda: backend)
    monkeypatch.delenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", raising=False)
    with pytest.raises(HTTPException) as caught:
        auth.enforce_login_init_rate_limits(request(), handle_bytes=HANDLE, lookup_bytes=LOOKUP)
    assert caught.value.status_code == 429
    assert caught.value.headers["Retry-After"] == "17"
    assert backend.check_and_increment.call_count == 2
    backend.check_and_increment_many.assert_not_called()


def test_legacy_lookup_budget_is_shared_with_modern_init(monkeypatch):
    backend = InMemoryRateLimitBackend()
    monkeypatch.setattr(auth, "get_rate_limit_backend", lambda: backend)
    monkeypatch.delenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", raising=False)
    auth.enforce_login_init_rate_limits(request(), handle_bytes=HANDLE, lookup_bytes=LOOKUP)
    for _ in range(5):
        auth.enforce_login_credential_rate_limit(request(), credential_id=LOOKUP, kind="lookup")
    with pytest.raises(HTTPException) as caught:
        auth.enforce_login_credential_rate_limit(request(), credential_id=LOOKUP, kind="lookup")
    assert caught.value.status_code == 429
    assert len(backend._state[_compose_key("auth_login_credential", f"ip:192.0.2.10:lookup:{LOOKUP.hex()}")]) == 6
    assert len(backend._state[_compose_key("auth_login_vault", f"lookup:{LOOKUP.hex()}")]) == 6


def test_global_denial_retains_preceding_source_hit_and_skips_later_lookup(monkeypatch):
    backend = InMemoryRateLimitBackend()
    monkeypatch.setattr(auth, "get_rate_limit_backend", lambda: backend)
    monkeypatch.delenv("VAULTAI_AUTH_PROXY_HEADER_BOUNDARY", raising=False)
    for n in range(1, 11):
        auth.enforce_login_init_rate_limits(request(f"192.0.2.{n}"), handle_bytes=HANDLE, lookup_bytes=LOOKUP)
    with pytest.raises(HTTPException) as caught:
        auth.enforce_login_init_rate_limits(request("192.0.2.11"), handle_bytes=HANDLE, lookup_bytes=LOOKUP)
    assert caught.value.status_code == 429
    assert len(backend._state[_compose_key("auth_login", "ip:192.0.2.11")]) == 1
    assert len(backend._state[_compose_key("auth_login_credential", f"ip:192.0.2.11:handle:{HANDLE.hex()}")]) == 1
    assert _compose_key("auth_login_credential", f"ip:192.0.2.11:lookup:{LOOKUP.hex()}") not in backend._state


_TEST_REDIS_URL = os.getenv("VAULTAI_RATE_LIMIT_BATCH_TEST_REDIS_URL", "").strip()


@pytest.mark.skipif(not _TEST_REDIS_URL, reason="No explicitly approved synthetic test Redis configured")
def test_real_redis_lua_shares_single_key_counts_and_expiry():
    import redis
    client = redis.Redis.from_url(_TEST_REDIS_URL, socket_timeout=0.2, socket_connect_timeout=0.2)
    identifier = f"synthetic-auth-batch-{uuid.uuid4().hex}"
    ordered = [RateLimitCheck(f"{identifier}-{i}", "auth_login", 2, 60) for i in range(5)]
    keys = [_compose_key(c.bucket, c.user_id) for c in ordered]
    backend = RedisRateLimitBackend(url="redis://synthetic", client=client, batch_enabled=True)
    try:
        assert all(d.allowed for d in backend.check_and_increment_many(ordered))
        assert backend.check_and_increment(**ordered[2].__dict__).allowed
        before_ttl = client.pttl(keys[2])
        result = backend.check_and_increment_many(ordered)
        assert [d.allowed for d in result] == [True, True, False]
        assert [client.zcard(key) for key in keys] == [2, 2, 2, 1, 1]
        assert 0 < client.pttl(keys[2]) <= before_ttl
    finally:
        # Exact generated keys only; no pattern scan or shared-key deletion.
        for key in keys:
            client.delete(key)
