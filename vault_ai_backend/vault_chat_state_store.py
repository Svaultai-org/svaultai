"""Shared cross-worker state store for chat/session-scoped state.

Fixes the 2026-07-22 production incident where pending-save state
(generated credential drafts, secure-item drafts, chat memory) was
lost between chat turns because each Uvicorn worker held its own
module-level dict and there is no nginx session affinity — the
"save it" turn would round-robin to a different worker than the
turn that produced the draft.

Design:

* A shared key-value backend used by the pending-state modules
  (``vault_credential_draft``, ``vault_secure_item_draft``,
  ``vault_chat_memory``). Values are opaque bytes (callers
  serialize/deserialize to their preferred format — typically
  JSON of the dataclass fields).

* Two implementations:

    - ``RedisSharedStateBackend`` — production. Keys live in Redis
      under the ``chatst:v1:`` namespace, one physical Redis key
      per logical vault-scoped entry. TTL is enforced by Redis
      itself (``PEX``) so expired entries are reaped without a
      Python-side GC loop.

    - ``InMemoryChatStateBackend`` — dev / test / Redis-outage
      fallback. Same semantics as the previous per-module in-process
      dicts, so nothing regresses when Redis is unavailable — it
      just returns to the pre-fix worker-hop failure mode
      (documented as an operational risk in the module docstring)
      rather than crashing the chat pipeline.

* Reuses the SAME Redis URL config as the rate-limit backend
  (``VAULTAI_RATE_LIMIT_REDIS_URL`` / ``RATE_LIMIT_REDIS_URL``).
  No new env var, no new dependency, no new migration.

Failure policy:

  Chat is a fail-open surface — a Redis outage must not brick the
  chat UX. On any Redis error, the backend logs a warning and
  degrades to a per-process in-memory shim for that call only. The
  process-local shim was the previous behavior in production, so
  the worst case is that we return to pre-fix behavior. Redis
  recovery is transparent — subsequent calls try Redis again.

Security:

  * Vault IDs, draft IDs, and any user identifier that ends up in
    a key are hashed (SHA-256, first 16 hex) before being written
    to Redis, matching the rate-limit backend convention. Raw
    vault IDs and draft IDs never appear in Redis command logs.

  * Values are opaque bytes to this module. Callers are
    responsible for not writing plaintext secrets they wouldn't
    write to disk. Credential drafts (``vault_credential_draft``)
    write username/password into Redis — that is unavoidable
    because "save it" needs to recover those exact values in the
    following turn. Redis in production is on a private network
    and requires AUTH; the same trust boundary as Postgres.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional


logger = logging.getLogger(__name__)


_KEY_NAMESPACE: str = "chatst:v1"
_KEY_HASH_PREFIX_LEN: int = 16
_INMEM_LRU_CAP: int = 8192


def _hash_component(raw: str) -> str:
    """SHA-256(raw)[:16 hex]. Same input → same key, but the raw
    value never leaves this function. Mirrors the rate-limit
    backend's key-derivation convention."""
    if not raw:
        return "anon"
    return hashlib.sha256(
        raw.encode("utf-8"),
    ).hexdigest()[:_KEY_HASH_PREFIX_LEN]


def compose_key(*, bucket: str, vault_id: str, sub: str = "") -> str:
    """Compose a shared-store key from a caller-owned bucket name,
    the vault_id, and an optional sub-key (e.g. draft_id).

    Bucket names are closed-set operational text (module-owned) and
    are NOT hashed. Vault IDs and sub-keys ARE hashed so raw values
    never appear in Redis logs.
    """
    if not bucket:
        raise ValueError("bucket required")
    if not vault_id:
        raise ValueError("vault_id required")
    parts = [_KEY_NAMESPACE, bucket, _hash_component(vault_id)]
    if sub:
        parts.append(_hash_component(sub))
    return ":".join(parts)


def compose_index_key(*, bucket: str, vault_id: str) -> str:
    """The Redis Set used to enumerate every sub-key currently
    written under (bucket, vault_id). Needed by callers that
    implement "return the latest / newest draft" semantics — Redis
    has no wildcard SCAN we can use safely without a full keyspace
    walk, so we maintain an explicit index Set per vault."""
    return compose_key(bucket=bucket, vault_id=vault_id) + ":idx"


class SharedStateBackend(ABC):

    backend_name: str = "abstract"

    @abstractmethod
    def get(self, key: str) -> Optional[bytes]:
        raise NotImplementedError

    @abstractmethod
    def set(
        self, key: str, value: bytes, ttl_seconds: int,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def sadd(
        self, key: str, member: str, ttl_seconds: int,
    ) -> None:
        """Add ``member`` to the Set at ``key``. Refresh TTL."""
        raise NotImplementedError

    @abstractmethod
    def smembers(self, key: str) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def srem(self, key: str, member: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def sclear(self, key: str) -> None:
        raise NotImplementedError

    def health(self) -> dict:
        return {"backend": self.backend_name, "ok": True}


class InMemoryChatStateBackend(SharedStateBackend):
    """Single-process fallback. Thread-safe. LRU-capped.

    Semantics match a naive dict with per-entry expiry checked on
    read. Sufficient for tests and single-worker dev.

    NOT sufficient for multi-worker production — that is exactly
    the incident this whole module exists to fix. If this backend
    is chosen at process start, ``get_chat_state_backend`` logs a
    warning if the process appears to be running in production so
    the operator notices.
    """

    backend_name = "in_memory"

    def __init__(self, *, lru_cap: int = _INMEM_LRU_CAP) -> None:
        self._lock = threading.Lock()
        self._kv: dict[str, tuple[float, bytes]] = {}
        self._sets: dict[str, dict[str, float]] = {}
        self._lru_cap = max(64, int(lru_cap))

    def _now(self) -> float:
        return time.time()

    def _evict_expired_kv(self, now: float) -> None:
        dead = [k for k, (exp, _) in self._kv.items() if exp <= now]
        for k in dead:
            self._kv.pop(k, None)

    def _evict_expired_set(
        self, key: str, now: float,
    ) -> None:
        members = self._sets.get(key)
        if not members:
            return
        dead = [m for m, exp in members.items() if exp <= now]
        for m in dead:
            members.pop(m, None)
        if not members:
            self._sets.pop(key, None)

    def _evict_kv_lru_if_needed(self) -> None:
        while len(self._kv) > self._lru_cap:
            oldest = min(
                self._kv.items(), key=lambda kv: kv[1][0],
            )[0]
            self._kv.pop(oldest, None)

    def get(self, key: str) -> Optional[bytes]:
        now = self._now()
        with self._lock:
            entry = self._kv.get(key)
            if entry is None:
                return None
            exp, value = entry
            if exp <= now:
                self._kv.pop(key, None)
                return None
            return value

    def set(
        self, key: str, value: bytes, ttl_seconds: int,
    ) -> None:
        ttl = max(1, int(ttl_seconds))
        expires = self._now() + ttl
        with self._lock:
            self._evict_expired_kv(self._now())
            self._kv[key] = (expires, value)
            self._evict_kv_lru_if_needed()

    def delete(self, key: str) -> None:
        with self._lock:
            self._kv.pop(key, None)

    def sadd(
        self, key: str, member: str, ttl_seconds: int,
    ) -> None:
        ttl = max(1, int(ttl_seconds))
        expires = self._now() + ttl
        with self._lock:
            self._evict_expired_set(key, self._now())
            members = self._sets.setdefault(key, {})
            members[member] = expires

    def smembers(self, key: str) -> list[str]:
        now = self._now()
        with self._lock:
            self._evict_expired_set(key, now)
            members = self._sets.get(key)
            if not members:
                return []
            return list(members.keys())

    def srem(self, key: str, member: str) -> None:
        with self._lock:
            members = self._sets.get(key)
            if not members:
                return
            members.pop(member, None)
            if not members:
                self._sets.pop(key, None)

    def sclear(self, key: str) -> None:
        with self._lock:
            self._sets.pop(key, None)

    def _reset_for_test(self) -> None:
        with self._lock:
            self._kv.clear()
            self._sets.clear()

    def health(self) -> dict:
        with self._lock:
            return {
                "backend":   self.backend_name,
                "ok":        True,
                "kv_count":  len(self._kv),
                "set_count": len(self._sets),
                "lru_cap":   self._lru_cap,
            }


class RedisSharedStateBackend(SharedStateBackend):
    """Redis-backed implementation. Production backend.

    * ``get/set/delete`` translate to ``GET/SET PEX/DEL``.
    * ``sadd/smembers/srem/sclear`` translate to
      ``SADD/SMEMBERS/SREM/DEL``. TTL on the set is renewed on
      every ``SADD`` via ``PEXPIRE`` — safe because sets are only
      grown by ``store_draft``-style writes and callers use them
      as short-lived indexes.
    * Any Redis exception is caught, logged as a warning, and the
      call degrades to a per-call in-memory shim (kept on the
      instance) so chat continues. The next call retries Redis
      automatically.
    """

    backend_name = "redis"

    def __init__(
        self,
        *,
        url: str,
        client=None,
        fallback: Optional[InMemoryChatStateBackend] = None,
    ) -> None:
        self._url = url
        self._client = client
        self._fallback = fallback or InMemoryChatStateBackend()
        if self._client is None:
            try:
                import redis
                self._client = redis.Redis.from_url(
                    url, decode_responses=False,
                )
            except Exception as e:
                logger.warning(
                    "RedisSharedStateBackend init failed (%s). "
                    "Chat state will degrade to per-process "
                    "in-memory until Redis is reachable — the "
                    "pre-fix worker-hop symptom may return.",
                    type(e).__name__,
                )
                self._client = None

    def _degrade_warn(self, op: str, err: Exception) -> None:
        logger.warning(
            "Redis chat-state %s failed (%s) — degrading to "
            "in-memory for this call. Cross-worker consistency "
            "is lost until Redis recovers.",
            op, type(err).__name__,
        )

    def get(self, key: str) -> Optional[bytes]:
        if self._client is None:
            return self._fallback.get(key)
        try:
            raw = self._client.get(key)
            return raw if isinstance(raw, (bytes, bytearray)) else (
                raw.encode("utf-8") if isinstance(raw, str) else None
            )
        except Exception as e:
            self._degrade_warn("GET", e)
            return self._fallback.get(key)

    def set(
        self, key: str, value: bytes, ttl_seconds: int,
    ) -> None:
        ttl_ms = max(1000, int(ttl_seconds) * 1000)
        if self._client is None:
            self._fallback.set(key, value, ttl_seconds)
            return
        try:
            self._client.set(key, value, px=ttl_ms)
        except Exception as e:
            self._degrade_warn("SET", e)
            self._fallback.set(key, value, ttl_seconds)

    def delete(self, key: str) -> None:
        if self._client is None:
            self._fallback.delete(key)
            return
        try:
            self._client.delete(key)
        except Exception as e:
            self._degrade_warn("DEL", e)
            self._fallback.delete(key)

    def sadd(
        self, key: str, member: str, ttl_seconds: int,
    ) -> None:
        ttl_ms = max(1000, int(ttl_seconds) * 1000)
        if self._client is None:
            self._fallback.sadd(key, member, ttl_seconds)
            return
        try:
            pipe = self._client.pipeline()
            pipe.sadd(key, member)
            pipe.pexpire(key, ttl_ms)
            pipe.execute()
        except Exception as e:
            self._degrade_warn("SADD", e)
            self._fallback.sadd(key, member, ttl_seconds)

    def smembers(self, key: str) -> list[str]:
        if self._client is None:
            return self._fallback.smembers(key)
        try:
            raw = self._client.smembers(key)
            out = []
            for m in raw or []:
                if isinstance(m, (bytes, bytearray)):
                    out.append(m.decode("utf-8"))
                elif isinstance(m, str):
                    out.append(m)
            return out
        except Exception as e:
            self._degrade_warn("SMEMBERS", e)
            return self._fallback.smembers(key)

    def srem(self, key: str, member: str) -> None:
        if self._client is None:
            self._fallback.srem(key, member)
            return
        try:
            self._client.srem(key, member)
        except Exception as e:
            self._degrade_warn("SREM", e)
            self._fallback.srem(key, member)

    def sclear(self, key: str) -> None:
        if self._client is None:
            self._fallback.sclear(key)
            return
        try:
            self._client.delete(key)
        except Exception as e:
            self._degrade_warn("DEL(set)", e)
            self._fallback.sclear(key)

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


def _redact_redis_url(url: str) -> str:
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


_singleton: Optional[SharedStateBackend] = None
_singleton_lock = threading.Lock()


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


def _log_backend_resolved(
    backend: SharedStateBackend,
    *,
    choice_env: str,
    url_present: bool,
    is_prod: bool,
) -> None:
    """Emit one authoritative startup line naming the resolved
    backend and whether it satisfies the multi-worker requirement.
    Operator greppable — search production container logs for
    ``[CHAT-STATE] backend_resolved`` to confirm Redis is in use
    before deploying a fix that depends on it.
    """
    try:
        health = backend.health()
    except Exception:
        health = {}
    ok = bool(health.get("ok"))
    name = health.get("backend") or getattr(
        backend, "backend_name", "unknown",
    )
    cross_worker = name == "redis" and ok
    logger.warning(
        "[CHAT-STATE] backend_resolved name=%s ok=%s "
        "cross_worker_safe=%s "
        "choice_env=%s url_env_present=%s is_prod=%s health=%s",
        name, ok, cross_worker, choice_env or "(unset)",
        url_present, is_prod, health,
    )
    if is_prod and not cross_worker:
        logger.error(
            "[CHAT-STATE] PRODUCTION IS NOT CROSS-WORKER SAFE — "
            "pending-save state will be lost on Uvicorn "
            "worker-hop. Set VAULTAI_RATE_LIMIT_REDIS_URL (or "
            "VAULTAI_CHAT_STATE_BACKEND=redis + a URL) and "
            "restart. Currently resolved backend=%s ok=%s",
            name, ok,
        )


def get_chat_state_backend() -> SharedStateBackend:
    """Return the process-wide singleton chat-state backend.

    Selection order:

      1. Explicit ``VAULTAI_CHAT_STATE_BACKEND=redis`` (or ``=memory``)
         if set.
      2. Otherwise, if a rate-limit Redis URL is present (either
         ``VAULTAI_RATE_LIMIT_REDIS_URL`` or ``RATE_LIMIT_REDIS_URL``),
         use Redis at that URL.
      3. Otherwise fall back to in-memory. If we appear to be in
         production, log a warning about worker-hop state loss.

    Emits a one-line ``[CHAT-STATE] backend_resolved`` warning on
    first resolution so operators can confirm which backend is
    active from container startup logs.
    """
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is not None:
            return _singleton

        choice = os.getenv(
            "VAULTAI_CHAT_STATE_BACKEND", "",
        ).strip().lower()
        url = (
            os.getenv("VAULTAI_RATE_LIMIT_REDIS_URL", "").strip()
            or os.getenv("RATE_LIMIT_REDIS_URL", "").strip()
        )
        is_prod = _is_production()

        if choice == "memory":
            _singleton = InMemoryChatStateBackend()
            _log_backend_resolved(
                _singleton, choice_env=choice,
                url_present=bool(url), is_prod=is_prod,
            )
            return _singleton

        if choice == "redis" or (choice == "" and url):
            if not url:
                logger.warning(
                    "VAULTAI_CHAT_STATE_BACKEND=redis but no "
                    "Redis URL is set. Falling back to in-memory "
                    "— cross-worker chat state will NOT survive.",
                )
                _singleton = InMemoryChatStateBackend()
            else:
                _singleton = RedisSharedStateBackend(url=url)
            _log_backend_resolved(
                _singleton, choice_env=choice,
                url_present=bool(url), is_prod=is_prod,
            )
            return _singleton

        if is_prod:
            logger.warning(
                "[CHAT-STATE] production is running with the "
                "in-memory chat-state backend. Multi-worker "
                "deployments will lose pending-save state on "
                "worker-hop. Set VAULTAI_RATE_LIMIT_REDIS_URL "
                "(or VAULTAI_CHAT_STATE_BACKEND=redis + a URL) "
                "to enable cross-worker consistency.",
            )
        _singleton = InMemoryChatStateBackend()
        _log_backend_resolved(
            _singleton, choice_env=choice,
            url_present=bool(url), is_prod=is_prod,
        )
        return _singleton


def reset_chat_state_backend_for_tests() -> None:
    """Test-only. Drop the singleton so the next call resolves
    fresh env vars. Also resets any in-memory data."""
    global _singleton
    with _singleton_lock:
        if isinstance(_singleton, InMemoryChatStateBackend):
            _singleton._reset_for_test()
        _singleton = None


def install_backend_for_tests(backend: SharedStateBackend) -> None:
    """Test-only. Force a specific backend into the singleton
    without touching env vars — mirrors the pattern used by the
    rate-limit backend."""
    global _singleton
    with _singleton_lock:
        _singleton = backend


__all__ = [
    "SharedStateBackend",
    "InMemoryChatStateBackend",
    "RedisSharedStateBackend",
    "compose_key",
    "compose_index_key",
    "get_chat_state_backend",
    "reset_chat_state_backend_for_tests",
    "install_backend_for_tests",
]
