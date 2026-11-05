"""A stale Redis socket may be retried only before a rate-limit write."""

from __future__ import annotations

import time
import pytest
import redis
from fastapi import HTTPException

import rate_limit_auth as auth
from rate_limit_backend import (
    RateLimitCheck,
    RateLimitDecision,
    RedisRateLimitBackend,
)


class FakeConnection:
    def __init__(self, *, idle: bool, ping_error=None, eval_error=None, reply=None):
        self.next_health_check = 0 if idle else time.monotonic() + 30
        self.ping_error = ping_error
        self.eval_error = eval_error
        self.reply = reply or [1, 9, 60]
        self.commands = []
        self.disconnected = False

    def send_command(self, command, *args, **kwargs):
        self.commands.append(command)
        assert kwargs.get("check_health") is False
        if command == "PING" and self.ping_error:
            raise self.ping_error

    def read_response(self):
        self.next_health_check = time.monotonic() + 30
        return b"PONG"

    def disconnect(self):
        self.disconnected = True


class FakePool:
    def __init__(self, *connections):
        self.connections = list(connections)
        self.borrowed = []
        self.released = []

    def get_connection(self):
        connection = self.connections.pop(0)
        self.borrowed.append(connection)
        return connection

    def release(self, connection):
        self.released.append(connection)


class FakeRedis:
    def __init__(self, pool):
        self.connection_pool = pool

    def parse_response(self, connection, command):
        assert command in {"EVAL", "EVALSHA", "SCRIPT LOAD"}
        if connection.eval_error:
            raise connection.eval_error
        return connection.reply

    def eval(self, *_args):
        raise AssertionError("high-level EVAL would borrow another connection")

    def evalsha(self, *_args):
        raise AssertionError("high-level EVALSHA would borrow another connection")

    def script_load(self, *_args):
        raise AssertionError("high-level SCRIPT LOAD would borrow another connection")


def _backend(monkeypatch, *connections):
    monkeypatch.setattr(redis, "Redis", FakeRedis)
    pool = FakePool(*connections)
    return RedisRateLimitBackend(
        url="redis://synthetic", client=FakeRedis(pool), batch_enabled=True,
    ), pool


def _check():
    return [RateLimitCheck("synthetic-source", "auth_login", 10, 60)]


def test_stale_socket_recovers_with_ping_before_one_eval(monkeypatch):
    stale = FakeConnection(idle=True, ping_error=redis.exceptions.ConnectionError("stale"))
    fresh = FakeConnection(idle=True)
    backend, pool = _backend(monkeypatch, stale, fresh)

    decisions = backend.check_and_increment_many(_check())

    assert decisions[0].allowed and not decisions[0].backend_unavailable
    assert stale.commands == ["PING"]
    assert stale.disconnected
    assert fresh.commands == ["PING", "EVAL"]
    assert pool.released == [stale, fresh]


def test_recent_socket_skips_ping_and_sends_one_eval(monkeypatch):
    recent = FakeConnection(idle=False)
    backend, pool = _backend(monkeypatch, recent)

    assert backend.check_and_increment_many(_check())[0].allowed
    assert recent.commands == ["EVAL"]
    assert pool.released == [recent]


def test_two_ping_failures_never_send_eval_and_report_unavailable(monkeypatch):
    first = FakeConnection(idle=True, ping_error=redis.exceptions.ConnectionError("stale"))
    second = FakeConnection(idle=True, ping_error=redis.exceptions.ConnectionError("offline"))
    backend, pool = _backend(monkeypatch, first, second)

    decision = backend.check_and_increment_many(_check())[0]

    assert not decision.allowed and decision.backend_unavailable
    assert first.commands == second.commands == ["PING"]
    assert pool.released == [first, second]


def test_uncertain_eval_reply_is_never_retried(monkeypatch):
    connection = FakeConnection(
        idle=False, eval_error=redis.exceptions.ConnectionError("reply lost"),
    )
    backend, pool = _backend(monkeypatch, connection)

    decision = backend.check_and_increment_many(_check())[0]

    assert not decision.allowed and decision.backend_unavailable
    assert connection.commands == ["EVAL"]
    assert connection.disconnected
    assert pool.borrowed == [connection]


def test_stale_socket_recovers_before_single_key_evalsha(monkeypatch):
    stale = FakeConnection(idle=True, ping_error=redis.exceptions.ConnectionError("stale"))
    fresh = FakeConnection(idle=True)
    backend, pool = _backend(monkeypatch, stale, fresh)
    backend._script_sha = "synthetic-sha"

    decision = backend.check_and_increment(
        user_id="synthetic-source", bucket="auth_login_finalize",
        limit_per_window=30, window_seconds=60,
    )

    assert decision.allowed and not decision.backend_unavailable
    assert stale.commands == ["PING"]
    assert fresh.commands == ["PING", "EVALSHA"]
    assert pool.released == [stale, fresh]


def test_script_load_can_retry_because_it_cannot_increment_a_budget(monkeypatch):
    first = FakeConnection(
        idle=False, eval_error=redis.exceptions.ConnectionError("reply lost"),
    )
    second = FakeConnection(idle=False, reply=b"synthetic-sha")
    third = FakeConnection(idle=False)
    backend, pool = _backend(monkeypatch, first, second, third)

    decision = backend.check_and_increment(
        user_id="synthetic-source", bucket="auth_login_finalize",
        limit_per_window=30, window_seconds=60,
    )

    assert decision.allowed
    assert first.commands == second.commands == ["SCRIPT LOAD"]
    assert third.commands == ["EVALSHA"]
    assert pool.released == [first, second, third]


def test_transport_failure_is_503_but_real_budget_denial_remains_429():
    with pytest.raises(HTTPException) as unavailable:
        auth._deny_login(RateLimitDecision(
            allowed=False, remaining=0, reset_in_seconds=60,
            backend_unavailable=True,
        ))
    assert unavailable.value.status_code == 503
    assert unavailable.value.detail["code"] == "auth_temporarily_unavailable"
    assert unavailable.value.headers["Retry-After"] == "2"

    with pytest.raises(HTTPException) as limited:
        auth._deny_login(RateLimitDecision(
            allowed=False, remaining=0, reset_in_seconds=17,
        ))
    assert limited.value.status_code == 429
    assert limited.value.detail["code"] == "rate_limited"
    assert limited.value.headers["Retry-After"] == "17"
