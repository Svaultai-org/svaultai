

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional


try:
    from vault_config import cache as _cache_cfg
    _c = _cache_cfg()
    _DEFAULT_IDLE_TTL_SECONDS = _c.vault_key_idle_ttl_secs
    _DEFAULT_HARD_TTL_SECONDS = _c.vault_key_hard_ttl_secs
except Exception:
    _DEFAULT_IDLE_TTL_SECONDS = 30 * 60
    _DEFAULT_HARD_TTL_SECONDS = 8 * 60 * 60


@dataclass
class _Entry:
    key: bytes
    vault_id: str
    token_id: str
    created_at: float
    last_used_at: float

    def expired(self, now: float, idle_ttl: float, hard_ttl: float) -> bool:
        if now - self.last_used_at > idle_ttl:
            return True
        if now - self.created_at > hard_ttl:
            return True
        return False


class _VaultKeyCache:


    def __init__(
        self,
        *,
        idle_ttl_seconds: float = _DEFAULT_IDLE_TTL_SECONDS,
        hard_ttl_seconds: float = _DEFAULT_HARD_TTL_SECONDS,
    ) -> None:
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._lock = threading.Lock()
        self._idle_ttl = float(idle_ttl_seconds)
        self._hard_ttl = float(hard_ttl_seconds)

    def store(self, *, vault_id: str, token_id: str, key: bytes) -> None:


        if not vault_id or not token_id:
            return
        if not isinstance(key, (bytes, bytearray)):
            raise TypeError("key must be bytes")
        now = time.time()
        with self._lock:
            self._entries[(vault_id, token_id)] = _Entry(
                key=bytes(key),
                vault_id=vault_id,
                token_id=token_id,
                created_at=now,
                last_used_at=now,
            )

    def get(self, *, vault_id: str, token_id: str) -> Optional[bytes]:


        if not vault_id or not token_id:
            return None
        now = time.time()
        with self._lock:
            entry = self._entries.get((vault_id, token_id))
            if entry is None:
                return None
            if entry.expired(now, self._idle_ttl, self._hard_ttl):
                del self._entries[(vault_id, token_id)]
                return None
                                                                      
                                                                     
            if entry.vault_id != vault_id or entry.token_id != token_id:
                return None
            entry.last_used_at = now
            return entry.key

    def clear_session(self, token_id: str) -> int:


        if not token_id:
            return 0
        with self._lock:
            drop = [k for k in self._entries if k[1] == token_id]
            for k in drop:
                del self._entries[k]
            return len(drop)

    def clear_vault(self, vault_id: str) -> int:


        if not vault_id:
            return 0
        with self._lock:
            drop = [k for k in self._entries if k[0] == vault_id]
            for k in drop:
                del self._entries[k]
            return len(drop)

    def clear_all(self) -> int:

        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n

    def vacuum(self) -> int:

        now = time.time()
        with self._lock:
            drop = [
                k for k, e in self._entries.items()
                if e.expired(now, self._idle_ttl, self._hard_ttl)
            ]
            for k in drop:
                del self._entries[k]
            return len(drop)

    def active_scopes(self) -> list[tuple[str, str]]:


        self.vacuum()
        with self._lock:
            return [(e.vault_id, e.token_id) for e in self._entries.values()]

    def snapshot_counts(self) -> dict:


        self.vacuum()
        with self._lock:
            return {
                "active_entries":     len(self._entries),
                "distinct_vaults":    len({k[0] for k in self._entries}),
                "distinct_sessions":  len({k[1] for k in self._entries}),
                "idle_ttl_seconds":   self._idle_ttl,
                "hard_ttl_seconds":   self._hard_ttl,
            }


_CACHE: Optional[_VaultKeyCache] = None
_INIT_LOCK = threading.Lock()


def get_cache() -> _VaultKeyCache:
    global _CACHE
    if _CACHE is None:
        with _INIT_LOCK:
            if _CACHE is None:
                _CACHE = _VaultKeyCache()
    return _CACHE


def reset_for_tests(
    *,
    idle_ttl_seconds: float = _DEFAULT_IDLE_TTL_SECONDS,
    hard_ttl_seconds: float = _DEFAULT_HARD_TTL_SECONDS,
) -> _VaultKeyCache:


    global _CACHE
    with _INIT_LOCK:
        _CACHE = _VaultKeyCache(
            idle_ttl_seconds=idle_ttl_seconds,
            hard_ttl_seconds=hard_ttl_seconds,
        )
    return _CACHE


__all__ = ["get_cache", "reset_for_tests"]
