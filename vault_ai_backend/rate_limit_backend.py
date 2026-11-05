"""Rate limit backends.

Two implementations:

  * InMemoryRateLimitBackend — sliding window over a deque of
    monotonic timestamps. LRU-capped. Safe for single-instance dev.
    NOT safe for a multi-instance production deploy: each instance
    holds its own counter, so an attacker can cycle across replicas.

  * RedisRateLimitBackend — sliding window over a Redis sorted set,
    driven by a single Lua script that runs atomically inside Redis.
    Two backend instances sharing one Redis see one counter. This is
    the production backend.

Interface (both):

    decision = backend.check_and_increment(
        user_id="ip:1.2.3.4" or "pin:<hashed>:1.2.3.4",
        bucket="auth_login",
        limit_per_window=30,
        window_seconds=3600,
    )

`user_id` may contain vault ids, IPs, or device ids from callers.
Both backends hash `user_id` with SHA-256 before it becomes a key —
so the raw vault id / IP never appears in Redis command logs or in
the in-memory dict.

Risk classification:

    High-risk buckets (auth, PIN, delete vault, crypto reveal,
    burst guards, export) fail CLOSED when Redis is unreachable —
    an unreachable Redis returns a denied decision marked as a backend
    failure. Auth maps that marker to HTTP 503 instead of falsely
    claiming too many attempts. An outage still cannot let a
    distributed brute-force attacker walk past the limits.

    Low-risk buckets (chat) fail OPEN — the request goes through
    so a Redis blip does not brick user chat. The slowapi IP
    decorator on the same route still applies.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Deque, Optional, Sequence


logger = logging.getLogger(__name__)


_DEFAULT_LRU_CAP = 8192


_KEY_HASH_PREFIX_LEN: int = 16


_KEY_NAMESPACE: str = "rl:v1"

# Redis client defaults vary by version. Explicit socket bounds and zero
# network retries keep auth waits predictable without abandoning workers.
_REDIS_SOCKET_TIMEOUT_SECONDS: float = 0.5
_REDIS_IDLE_HEALTH_CHECK_SECONDS: int = 30


BUCKET_RISK_HIGH: frozenset[str] = frozenset({
    "auth_signup",
    "auth_login",
    "auth_login_credential",
    "auth_login_vault",
    "auth_login_finalize",
    "pin_verify",
    "delete_vault",
    "upload_burst",
    "delete_burst",
    "export",
    "crypto_reveal",
})


BUCKET_RISK_LOW: frozenset[str] = frozenset({
    "chat",
})


def _bucket_is_high_risk(bucket: str) -> bool:
    if bucket in BUCKET_RISK_HIGH:
        return True
    if bucket in BUCKET_RISK_LOW:
        return False

    return True


def _hash_user_id(raw: str) -> str:
    """SHA-256(raw)[:16 hex]. Same input → same key, but the raw
    value never leaves this function."""
    if not raw:
        return "anon"
    return hashlib.sha256(
        raw.encode("utf-8"),
    ).hexdigest()[:_KEY_HASH_PREFIX_LEN]


def _compose_key(bucket: str, user_id: str) -> str:
    """Full storage key: `rl:v1:<bucket>:<hashed_user_id>`. Bucket
    is closed-set operational text; user_id is hashed."""
    return f"{_KEY_NAMESPACE}:{bucket}:{_hash_user_id(user_id)}"


class RateLimitDecision:

    __slots__ = ("allowed", "remaining", "reset_in_seconds", "backend_unavailable")

    def __init__(
        self,
        *,
        allowed: bool,
        remaining: int,
        reset_in_seconds: int,
        backend_unavailable: bool = False,
    ) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.reset_in_seconds = reset_in_seconds
        self.backend_unavailable = backend_unavailable

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        return (
            f"RateLimitDecision(allowed={self.allowed}, "
            f"remaining={self.remaining}, "
            f"reset_in={self.reset_in_seconds}s, "
            f"backend_unavailable={self.backend_unavailable})"
        )


@dataclass(frozen=True)
class RateLimitCheck:
    """One ordered budget check; identifiers are hashed before storage."""

    user_id: str
    bucket: str
    limit_per_window: int
    window_seconds: int


class RateLimitBackend(ABC):

    backend_name: str = "abstract"

    @abstractmethod
    def check_and_increment(
        self,
        *,
        user_id: str,
        bucket: str,
        limit_per_window: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        raise NotImplementedError

    def check_and_increment_many(
        self, checks: Sequence[RateLimitCheck],
    ) -> list[RateLimitDecision]:
        """Check in order, stopping on denial and retaining earlier increments.

        The sequential default preserves behavior for in-memory and custom
        backends. Redis may batch the same ordered work when enabled.
        """
        decisions = []
        for check in checks:
            decision = self.check_and_increment(
                user_id=check.user_id,
                bucket=check.bucket,
                limit_per_window=check.limit_per_window,
                window_seconds=check.window_seconds,
            )
            decisions.append(decision)
            if not decision.allowed:
                break
        return decisions

    def health(self) -> dict:
        return {"backend": self.backend_name, "ok": True}


class InMemoryRateLimitBackend(RateLimitBackend):

    backend_name = "in_memory"

    def __init__(self, *, lru_cap: int = _DEFAULT_LRU_CAP) -> None:
        self._state: "OrderedDict[str, Deque[float]]" = OrderedDict()
        self._lru_cap = max(64, int(lru_cap))

    def check_and_increment(
        self,
        *,
        user_id: str,
        bucket: str,
        limit_per_window: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        now = time.monotonic()
        cutoff = now - max(1.0, float(window_seconds))
        key = _compose_key(bucket, user_id)
        timestamps = self._state.get(key)
        if timestamps is None:
            timestamps = deque()
            self._state[key] = timestamps
            self._evict_if_needed()
        self._state.move_to_end(key)
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if len(timestamps) >= max(1, limit_per_window):
            earliest = timestamps[0] if timestamps else now
            reset_in = max(0, int((earliest + window_seconds) - now))
            return RateLimitDecision(
                allowed=False, remaining=0, reset_in_seconds=reset_in,
            )
        timestamps.append(now)
        remaining = max(0, limit_per_window - len(timestamps))
        return RateLimitDecision(
            allowed=True,
            remaining=remaining,
            reset_in_seconds=int(window_seconds),
        )

    def _evict_if_needed(self) -> None:
        while len(self._state) > self._lru_cap:
            self._state.popitem(last=False)

    def health(self) -> dict:
        return {
            "backend":   self.backend_name,
            "ok":        True,
            "key_count": len(self._state),
            "lru_cap":   self._lru_cap,
        }


_REDIS_SLIDING_WINDOW_LUA: str = """
local now = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local cutoff = now - window_ms
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, cutoff)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local reset_ms
    if #oldest >= 2 then
        reset_ms = (tonumber(oldest[2]) + window_ms) - now
    else
        reset_ms = window_ms
    end
    if reset_ms < 0 then reset_ms = 0 end
    return {0, 0, math.ceil(reset_ms / 1000)}
end
redis.call('ZADD', KEYS[1], now, member)
redis.call('PEXPIRE', KEYS[1], window_ms + 1000)
return {1, limit - count - 1, math.ceil(window_ms / 1000)}
"""


_REDIS_ORDERED_WINDOWS_LUA: str = """
local now = tonumber(ARGV[1])
local member_prefix = ARGV[2]
local decisions = {}
for i = 1, #KEYS do
    local window_ms = tonumber(ARGV[2 * i + 1])
    local limit = tonumber(ARGV[2 * i + 2])
    local cutoff = now - window_ms
    redis.call('ZREMRANGEBYSCORE', KEYS[i], 0, cutoff)
    local count = redis.call('ZCARD', KEYS[i])
    if count >= limit then
        local oldest = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
        local reset_ms = window_ms
        if #oldest >= 2 then
            reset_ms = (tonumber(oldest[2]) + window_ms) - now
        end
        if reset_ms < 0 then reset_ms = 0 end
        decisions[#decisions + 1] = 0
        decisions[#decisions + 1] = 0
        decisions[#decisions + 1] = math.ceil(reset_ms / 1000)
        return decisions
    end
    redis.call('ZADD', KEYS[i], now, member_prefix .. ':' .. i)
    redis.call('PEXPIRE', KEYS[i], window_ms + 1000)
    decisions[#decisions + 1] = 1
    decisions[#decisions + 1] = limit - count - 1
    decisions[#decisions + 1] = math.ceil(window_ms / 1000)
end
return decisions
"""


class RedisRateLimitBackend(RateLimitBackend):

    backend_name = "redis"

    def __init__(
        self,
        *,
        url: str,
        client=None,
        batch_enabled: Optional[bool] = None,
    ) -> None:
        self._url = url
        self._client = client
        # Unchanged rl:v1 keys do not share a Redis Cluster hash slot. Enable
        # only after proving this deployment permits atomic multi-key Lua.
        self._batch_enabled = (
            os.getenv("VAULTAI_RATE_LIMIT_REDIS_BATCH_ENABLED", "false")
            .strip().lower() in {"true", "1", "yes", "on"}
            if batch_enabled is None else bool(batch_enabled)
        )
        self._script_sha: Optional[str] = None
        if self._client is None:
            try:
                import redis
                from redis.backoff import NoBackoff
                from redis.retry import Retry

                connection_limits = {
                    "socket_connect_timeout": _REDIS_SOCKET_TIMEOUT_SECONDS,
                    "socket_timeout": _REDIS_SOCKET_TIMEOUT_SECONDS,
                    "retry": Retry(NoBackoff(), 0),
                    "retry_on_timeout": False,
                    "retry_on_error": [],
                    "health_check_interval": _REDIS_IDLE_HEALTH_CHECK_SECONDS,
                }
                self._client = redis.Redis.from_url(
                    url, decode_responses=False,
                    **connection_limits,
                )
                # redis-py gives URL query parameters precedence over kwargs.
                # Apply our hard bounds to the effective pool before its first
                # connection is created, even for URLs containing timeouts.
                pool = getattr(self._client, "connection_pool", None)
                if pool is not None:
                    pool.connection_kwargs.update(connection_limits)
            except Exception as e:
                logger.warning(
                    "RedisRateLimitBackend init failed (%s). "
                    "High-risk buckets will FAIL CLOSED until "
                    "Redis is reachable; low-risk buckets will "
                    "fail open.",
                    type(e).__name__,
                )
                self._client = None

    def _load_script(self) -> Optional[str]:
        if self._script_sha is not None:
            return self._script_sha
        if self._client is None:
            return None
        for attempt in range(2):
            try:
                # Repeating SCRIPT LOAD is safe: it caches the same script
                # hash and never touches a rate-limit counter.
                self._script_sha = self._execute_checked(
                    "SCRIPT LOAD", _REDIS_SLIDING_WINDOW_LUA,
                )
                if isinstance(self._script_sha, bytes):
                    self._script_sha = self._script_sha.decode("ascii")
                break
            except Exception as e:
                if attempt == 0 and type(e).__name__ in {
                    "ConnectionError", "TimeoutError",
                }:
                    continue
                logger.warning("Redis SCRIPT LOAD failed (%s)", type(e).__name__)
                self._script_sha = None
                break
        return self._script_sha

    def _execute_checked(self, command: str, *args):
        """Use one pooled socket from idle check through the rate-limit write.

        A stale socket may be reconnected once while the only command sent is
        read-only PING. After EVAL/EVALSHA is sent, a lost reply is ambiguous:
        the script may have incremented a counter, so never retry the write.
        Each concurrent caller borrows its own connection from redis-py's pool.
        """
        client = self._client
        try:
            import redis
            from redis.exceptions import ConnectionError as RedisConnectionError
            from redis.exceptions import TimeoutError as RedisTimeoutError
        except ImportError:
            redis = None
        if redis is None or not isinstance(client, redis.Redis):
            if command == "EVAL":
                return client.eval(*args)
            if command == "EVALSHA":
                return client.evalsha(*args)
            if command == "SCRIPT LOAD":
                return client.script_load(*args)
            raise ValueError("unsupported rate-limit command")

        pool = client.connection_pool
        connection = None
        for attempt in range(2):
            connection = None
            ready = False
            try:
                connection = pool.get_connection()
                if time.monotonic() >= connection.next_health_check:
                    connection.send_command("PING", check_health=False)
                    if connection.read_response() not in (b"PONG", "PONG"):
                        raise RedisConnectionError("Unexpected Redis health response")
                ready = True
                break
            except Exception as exc:
                if connection is not None:
                    connection.disconnect()
                if attempt or not isinstance(
                    exc, (RedisConnectionError, RedisTimeoutError, OSError)
                ):
                    raise
            finally:
                if not ready and connection is not None:
                    pool.release(connection)

        try:
            connection.send_command(command, *args, check_health=False)
            return client.parse_response(connection, command)
        except Exception:
            connection.disconnect()
            raise
        finally:
            pool.release(connection)

    def _run_script(
        self, key: str, now_ms: int, window_ms: int, limit: int,
    ) -> tuple[int, int, int]:
        sha = self._load_script()
        if sha is None:
            raise RuntimeError("script not loaded")
        member = f"{now_ms}:{uuid.uuid4().hex}"
        try:
            raw = self._execute_checked(
                "EVALSHA", sha, 1, key,
                str(now_ms), str(window_ms), str(limit), member,
            )
        except Exception as e:

            if type(e).__name__ == "NoScriptError":
                self._script_sha = None
                sha = self._load_script()
                if sha is None:
                    raise
                raw = self._execute_checked(
                    "EVALSHA", sha, 1, key,
                    str(now_ms), str(window_ms), str(limit), member,
                )
            else:
                raise

        allowed = int(raw[0])
        remaining = int(raw[1])
        reset_in_seconds = int(raw[2])
        return (allowed, remaining, reset_in_seconds)

    def check_and_increment(
        self,
        *,
        user_id: str,
        bucket: str,
        limit_per_window: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        limit = max(1, int(limit_per_window))
        window_seconds = max(1, int(window_seconds))
        key = _compose_key(bucket, user_id)

        if self._client is None:

            return _failure_decision(bucket, window_seconds)

        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        try:
            allowed, remaining, reset_in = self._run_script(
                key, now_ms, window_ms, limit,
            )
        except Exception as e:
            logger.warning(
                "Redis rate-limit call failed (%s) — "
                "applying %s policy for bucket=%s",
                type(e).__name__,
                "fail-closed" if _bucket_is_high_risk(bucket)
                else "fail-open",
                bucket,
            )
            return _failure_decision(bucket, window_seconds)

        return RateLimitDecision(
            allowed=bool(allowed),
            remaining=remaining,
            reset_in_seconds=reset_in,
        )

    def check_and_increment_many(
        self, checks: Sequence[RateLimitCheck],
    ) -> list[RateLimitDecision]:
        if not self._batch_enabled:
            return super().check_and_increment_many(checks)
        checks = tuple(checks)
        if not checks:
            return []
        keys = [_compose_key(check.bucket, check.user_id) for check in checks]
        now_ms = int(time.time() * 1000)
        # Each attempt gets a unique member even when several arrive in the
        # same millisecond or the same storage key appears twice in a batch.
        argv = [str(now_ms), f"{now_ms}:{uuid.uuid4().hex}"]
        for check in checks:
            argv.extend((
                str(max(1, int(check.window_seconds)) * 1000),
                str(max(1, int(check.limit_per_window))),
            ))
        try:
            if self._client is None:
                raise RuntimeError("Redis unavailable")
            # Direct EVAL is one round trip on both cold and warm clients.
            # Never retry an uncertain write: the script may already have
            # incremented earlier budgets before a transport failure.
            raw = self._execute_checked(
                "EVAL", _REDIS_ORDERED_WINDOWS_LUA, len(keys), *keys, *argv,
            )
            if not isinstance(raw, (list, tuple)) or not raw or len(raw) % 3:
                raise ValueError("invalid Redis batch result")
            count = len(raw) // 3
            if count > len(checks):
                raise ValueError("invalid Redis batch result")
            decisions = []
            for i in range(count):
                allowed, remaining, reset = map(int, raw[i * 3:i * 3 + 3])
                if allowed not in (0, 1) or remaining < 0 or reset < 0:
                    raise ValueError("invalid Redis batch decision")
                if (not allowed and (i != count - 1 or remaining != 0)) or (
                    allowed and i == count - 1 and count != len(checks)
                ):
                    raise ValueError("invalid Redis batch decision order")
                decisions.append(RateLimitDecision(
                    allowed=bool(allowed), remaining=remaining,
                    reset_in_seconds=reset,
                ))
            return decisions
        except Exception as exc:
            logger.warning(
                "Redis ordered rate-limit call failed (%s); applying bucket "
                "failure policy without retry", type(exc).__name__,
            )
            decisions = []
            for check in checks:
                decision = _failure_decision(
                    check.bucket, max(1, int(check.window_seconds)),
                )
                decisions.append(decision)
                if not decision.allowed:
                    break
            return decisions

    def health(self) -> dict:
        ok = False
        if self._client is not None:
            try:
                pong = self._client.ping()
                ok = bool(pong)
            except Exception:
                ok = False
        return {
            "backend": self.backend_name,
            "ok":      ok,
            "url":     _redact_redis_url(self._url),
        }


def _failure_decision(
    bucket: str, window_seconds: int,
) -> RateLimitDecision:
    """Backend-failure policy per bucket risk.

    High-risk buckets fail CLOSED: return a denied decision marked
    backend_unavailable. Auth reports this as HTTP 503, distinct from
    a real exhausted budget's HTTP 429. The decision still blocks
    requests while Redis is unavailable.

    Low-risk buckets fail OPEN: allow with remaining = 1 so we
    do not brick the UX during a Redis blip.
    """
    if _bucket_is_high_risk(bucket):
        return RateLimitDecision(
            allowed=False,
            remaining=0,
            reset_in_seconds=int(window_seconds),
            backend_unavailable=True,
        )
    return RateLimitDecision(
        allowed=True,
        remaining=1,
        reset_in_seconds=int(window_seconds),
        backend_unavailable=True,
    )


def _redact_redis_url(url: str) -> str:
    """Never leak the Redis password if the URL is
    `redis://user:password@host`. Only host+port survive to logs."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parts = urlparse(url)
        host = parts.hostname or ""
        port = parts.port
        scheme = parts.scheme or "redis"
        if port:
            return f"{scheme}://{host}:{port}"
        return f"{scheme}://{host}"
    except Exception:
        return "<redacted>"


_singleton: Optional[RateLimitBackend] = None


_ENV_TOKENS_PROD: frozenset[str] = frozenset({
    "prod", "production", "live",
})


def _is_production() -> bool:
    for var in (
        "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
    ):
        if os.getenv(var, "").strip().lower() in _ENV_TOKENS_PROD:
            return True
    return False


def get_rate_limit_backend() -> RateLimitBackend:
    """Resolve the singleton rate-limit backend.

    Explicit `VAULTAI_RATE_LIMIT_BACKEND=redis` uses Redis (via
    `VAULTAI_RATE_LIMIT_REDIS_URL` or `RATE_LIMIT_REDIS_URL`).

    In production, if `VAULTAI_RATE_LIMIT_BACKEND` is unset but a
    Redis URL IS set, Redis is used automatically.

    Otherwise falls back to InMemoryRateLimitBackend and — if in
    production — emits a warning that multi-instance deploys
    should switch to Redis.
    """
    global _singleton
    if _singleton is not None:
        return _singleton

    choice = os.getenv(
        "VAULTAI_RATE_LIMIT_BACKEND", "",
    ).strip().lower()
    url = (
        os.getenv("VAULTAI_RATE_LIMIT_REDIS_URL", "").strip()
        or os.getenv("RATE_LIMIT_REDIS_URL", "").strip()
    )

    if choice == "redis" or (choice == "" and url):
        if not url:
            logger.warning(
                "VAULTAI_RATE_LIMIT_BACKEND=redis but no "
                "VAULTAI_RATE_LIMIT_REDIS_URL / "
                "RATE_LIMIT_REDIS_URL. Falling back to in-memory.",
            )
            _singleton = InMemoryRateLimitBackend()
        else:
            _singleton = RedisRateLimitBackend(url=url)
        return _singleton

    if _is_production():
        logger.warning(
            "[RATE-LIMIT] production is running with the "
            "in-memory rate-limit backend. Multi-instance "
            "deployments SHOULD set "
            "VAULTAI_RATE_LIMIT_REDIS_URL so rate limits are "
            "enforced across replicas.",
        )

    _singleton = InMemoryRateLimitBackend()
    return _singleton


def reset_rate_limit_backend_for_tests() -> None:
    global _singleton
    _singleton = None


def install_backend_for_tests(backend: RateLimitBackend) -> None:
    """Test-only injection point — pre-populate the singleton with
    a specific backend so route tests can hit a known
    implementation without touching env vars."""
    global _singleton
    _singleton = backend


__all__ = [
    "BUCKET_RISK_HIGH",
    "BUCKET_RISK_LOW",
    "RateLimitBackend",
    "RateLimitDecision",
    "RateLimitCheck",
    "InMemoryRateLimitBackend",
    "RedisRateLimitBackend",
    "get_rate_limit_backend",
    "reset_rate_limit_backend_for_tests",
    "install_backend_for_tests",
]
