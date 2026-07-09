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
    an unreachable Redis returns a denied decision that mimics a
    rate-limit hit. That way an outage cannot let a distributed
    brute-force attacker walk past the limits.

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
from typing import Deque, Optional


logger = logging.getLogger(__name__)


_DEFAULT_LRU_CAP = 8192


_KEY_HASH_PREFIX_LEN: int = 16


_KEY_NAMESPACE: str = "rl:v1"


BUCKET_RISK_HIGH: frozenset[str] = frozenset({
    "auth_signup",
    "auth_login",
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

    __slots__ = ("allowed", "remaining", "reset_in_seconds")

    def __init__(
        self,
        *,
        allowed: bool,
        remaining: int,
        reset_in_seconds: int,
    ) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.reset_in_seconds = reset_in_seconds

    def __bool__(self) -> bool:
        return self.allowed

    def __repr__(self) -> str:
        return (
            f"RateLimitDecision(allowed={self.allowed}, "
            f"remaining={self.remaining}, "
            f"reset_in={self.reset_in_seconds}s)"
        )


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


class RedisRateLimitBackend(RateLimitBackend):

    backend_name = "redis"

    def __init__(
        self,
        *,
        url: str,
        client=None,
    ) -> None:
        self._url = url
        self._client = client
        self._script_sha: Optional[str] = None
        if self._client is None:
            try:
                import redis
                self._client = redis.Redis.from_url(
                    url, decode_responses=False,
                )
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
        try:
            self._script_sha = self._client.script_load(
                _REDIS_SLIDING_WINDOW_LUA,
            )
            if isinstance(self._script_sha, bytes):
                self._script_sha = self._script_sha.decode("ascii")
        except Exception as e:
            logger.warning(
                "Redis SCRIPT LOAD failed (%s)",
                type(e).__name__,
            )
            self._script_sha = None
        return self._script_sha

    def _run_script(
        self, key: str, now_ms: int, window_ms: int, limit: int,
    ) -> tuple[int, int, int]:
        sha = self._load_script()
        if sha is None:
            raise RuntimeError("script not loaded")
        member = f"{now_ms}:{uuid.uuid4().hex}"
        try:
            raw = self._client.evalsha(
                sha, 1, key,
                str(now_ms), str(window_ms), str(limit), member,
            )
        except Exception as e:

            if type(e).__name__ == "NoScriptError":
                self._script_sha = None
                sha = self._load_script()
                if sha is None:
                    raise
                raw = self._client.evalsha(
                    sha, 1, key,
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

    High-risk buckets fail CLOSED: return a denied decision with
    reset_in = window_seconds. That way an attacker cannot use a
    Redis outage to bypass the limit.

    Low-risk buckets fail OPEN: allow with remaining = 1 so we
    do not brick the UX during a Redis blip.
    """
    if _bucket_is_high_risk(bucket):
        return RateLimitDecision(
            allowed=False,
            remaining=0,
            reset_in_seconds=int(window_seconds),
        )
    return RateLimitDecision(
        allowed=True,
        remaining=1,
        reset_in_seconds=int(window_seconds),
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
    "InMemoryRateLimitBackend",
    "RedisRateLimitBackend",
    "get_rate_limit_backend",
    "reset_rate_limit_backend_for_tests",
    "install_backend_for_tests",
]
