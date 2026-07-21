"""Per-vault chat memory: last-service, pending draft, last-file-search, etc.

Backed by ``vault_chat_state_store`` (Redis in production, in-memory
elsewhere) so state survives worker-hop in a multi-worker Uvicorn
deploy. Prior to 2026-07-22 this module held every vault's memory
in a per-process ``TTLDict``; the "generate login" turn would land
on worker A and the "save it" turn would round-robin to worker B
whose dict was empty, and the assistant would reply "I don't have
a pending save right now".

Public API (deliberately unchanged from the pre-fix module — every
main.py caller of ``memory[...]``, ``memory.get(...)``,
``memory.pop(...)`` continues to work without modification, and
the source-scanning tests that assert those exact patterns still
pass):

    get_memory(vault_id) → dict-like ``SavedDict`` — read/write.
    remember_service(vault_id, service)
    set_pending_edit(vault_id, service, field?)
    clear_pending(vault_id)
    set_last_file_search_results(vault_id, kind=, results=)
    get_last_file_search_results(vault_id) → Optional[dict]
    clear_last_file_search_results(vault_id)

    CHAT_MEMORY — the module-wide singleton store. Kept for a
    handful of legacy call sites that reach into it directly
    (e.g. ``CHAT_MEMORY.get(memory_key(vault_id))``).
    Internally now delegates to ``_ChatMemoryStore``, which
    write-throughs to the shared backend on every mutation.

Cross-worker semantics:

    ``get_memory(vault_id)`` always reads the authoritative payload
    from the shared backend (Redis in prod) and returns a
    ``SavedDict``. In-place mutations to the returned dict
    (``memory["pending_login_draft"] = {...}``, ``memory.pop("k")``)
    flush to the shared backend immediately, so the next worker
    that calls ``get_memory(vault_id)`` sees the write. TTL
    matches ``CHAT_MEMORY_TTL_SECONDS`` (env-configurable, default
    1 hour). No Python-side GC loop; TTL is enforced by the
    backend.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from typing import Any, Optional

from vault_chat_state_store import (
    compose_key, get_chat_state_backend,
)


logger = logging.getLogger(__name__)


CHAT_MEMORY_TTL_SECONDS = int(os.getenv("CHAT_MEMORY_TTL_SECONDS", str(60 * 60)))
CHAT_MEMORY_MAX_ENTRIES = int(os.getenv("CHAT_MEMORY_MAX_ENTRIES", "10000"))


_BUCKET: str = "chat_memory"


def _now() -> float:
    return time.time()


def _memory_key_redis(vault_id: str) -> str:
    return compose_key(bucket=_BUCKET, vault_id=vault_id)


def _serialize(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _deserialize(raw: Optional[bytes]) -> Optional[dict]:
    if not raw:
        return None
    try:
        d = json.loads(raw.decode("utf-8"))
        if isinstance(d, dict):
            return d
        return None
    except Exception as e:
        logger.warning(
            "chat_memory deserialization failed (%s) — dropping "
            "the entry", type(e).__name__,
        )
        return None


class SavedDict(dict):
    """A ``dict`` subclass that write-throughs to the shared
    backend after every mutation. Wraps ``__setitem__``,
    ``__delitem__``, ``pop``, ``popitem``, ``clear``, ``setdefault``,
    ``update``, and ``|=`` (``__ior__``). Read paths (``__getitem__``,
    ``get``, ``keys``, iteration) are inherited and NOT hooked —
    they operate on the local cached payload only, which is fine
    because ``get_memory`` refetches from the backend on every
    call so the local instance is always freshly loaded.

    ``_vault_id`` is stored so mutations know where to flush.
    Marked with a leading underscore so it does not appear in
    dict.__iter__ / .keys() (dict subclasses can hold instance
    attributes independent of key-value pairs).
    """

    __slots__ = ("_vault_id", "_flush_disabled")

    def __init__(
        self,
        vault_id: str,
        initial: Optional[dict] = None,
    ) -> None:
        super().__init__(initial or {})
        self._vault_id: str = vault_id
        self._flush_disabled: bool = False

    def _flush(self) -> None:
        if self._flush_disabled or not self._vault_id:
            return
        try:
            backend = get_chat_state_backend()
            backend.set(
                _memory_key_redis(self._vault_id),
                _serialize(dict(self)),
                CHAT_MEMORY_TTL_SECONDS,
            )
        except Exception as e:
            logger.warning(
                "chat_memory flush failed (%s) — mutation kept "
                "in-process only",
                type(e).__name__,
            )

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        self._flush()

    def __delitem__(self, key) -> None:
        super().__delitem__(key)
        self._flush()

    def pop(self, key, *args, **kwargs):
        had = key in self
        result = super().pop(key, *args, **kwargs)
        if had:
            self._flush()
        return result

    def popitem(self):
        result = super().popitem()
        self._flush()
        return result

    def clear(self) -> None:
        super().clear()
        self._flush()

    def setdefault(self, key, default=None):
        missing = key not in self
        result = super().setdefault(key, default)
        if missing:
            self._flush()
        return result

    def update(self, *args, **kwargs) -> None:
        super().update(*args, **kwargs)
        self._flush()

    def __ior__(self, other):
        result = super().__ior__(other)
        self._flush()
        return result


class _ChatMemoryStore:
    """Legacy compatibility shim for the pre-fix ``TTLDict``
    singleton. Old callers that reach directly into ``CHAT_MEMORY``
    (``CHAT_MEMORY.get(memory_key(vault_id))``, ``CHAT_MEMORY.set(...)``,
    ``CHAT_MEMORY.pop(...)``) keep working; internally each call
    delegates to the shared backend.

    Note: values passed to ``.set`` must be JSON-serializable dicts.
    That is already the case in every existing caller — the payload
    is a plain dict of primitives.
    """

    __slots__ = ("max_size", "ttl_seconds")

    def __init__(self, max_size: int, ttl_seconds: int) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def get(self, key: str) -> Optional[Any]:
        if not key:
            return None
        try:
            backend = get_chat_state_backend()
            raw = backend.get(
                compose_key(bucket=_BUCKET, vault_id=key),
            )
        except Exception as e:
            logger.warning(
                "chat_memory get failed (%s)", type(e).__name__,
            )
            return None
        payload = _deserialize(raw)
        if payload is None:
            return None

        return SavedDict(vault_id=key, initial=payload)

    def set(self, key: str, value: Any) -> None:
        if not key:
            return
        if not isinstance(value, dict):

            value = {"value": value}
        try:
            backend = get_chat_state_backend()
            backend.set(
                compose_key(bucket=_BUCKET, vault_id=key),
                _serialize(dict(value)),
                self.ttl_seconds,
            )
        except Exception as e:
            logger.warning(
                "chat_memory set failed (%s)", type(e).__name__,
            )

    def pop(self, key: str, default: Any = None) -> Any:
        current = self.get(key)
        try:
            backend = get_chat_state_backend()
            backend.delete(
                compose_key(bucket=_BUCKET, vault_id=key),
            )
        except Exception as e:
            logger.warning(
                "chat_memory pop failed (%s)", type(e).__name__,
            )
        if current is None:
            return default
        return dict(current)

    def delete(self, key: str) -> None:
        try:
            backend = get_chat_state_backend()
            backend.delete(
                compose_key(bucket=_BUCKET, vault_id=key),
            )
        except Exception as e:
            logger.warning(
                "chat_memory delete failed (%s)", type(e).__name__,
            )

    def __len__(self) -> int:



        return 0


CHAT_MEMORY = _ChatMemoryStore(
    max_size=CHAT_MEMORY_MAX_ENTRIES,
    ttl_seconds=CHAT_MEMORY_TTL_SECONDS,
)


def memory_key(vault_id: str) -> str:
    return str(vault_id)


def get_memory(vault_id: str) -> SavedDict:
    """Return the vault's chat memory as a SavedDict.

    * If the backend has an existing payload, load it and return
      a SavedDict wrapping that payload.
    * Otherwise write the default seed payload to the backend and
      return a SavedDict wrapping it.

    Every mutation to the returned SavedDict flushes to the shared
    backend, so the next worker that calls ``get_memory`` for the
    same vault sees the update.
    """
    key = memory_key(vault_id)
    if not key:
        return SavedDict(vault_id="", initial={})
    backend = get_chat_state_backend()
    try:
        raw = backend.get(_memory_key_redis(key))
    except Exception as e:
        logger.warning(
            "chat_memory read failed (%s) — returning empty",
            type(e).__name__,
        )
        raw = None
    payload = _deserialize(raw)
    if payload is None:
        payload = {
            "last_service": None,
            "pending_action": None,
            "pending_field": None,
        }
        try:
            backend.set(
                _memory_key_redis(key),
                _serialize(payload),
                CHAT_MEMORY_TTL_SECONDS,
            )
        except Exception as e:
            logger.warning(
                "chat_memory seed write failed (%s)",
                type(e).__name__,
            )
    return SavedDict(vault_id=key, initial=payload)


def remember_service(vault_id: str, service: Optional[str]):
    if service and service != "general":
        memory = get_memory(vault_id)
        memory["last_service"] = service


def set_pending_edit(
    vault_id: str, service: str, field: Optional[str] = None,
) -> None:
    memory = get_memory(vault_id)



    memory._flush_disabled = True
    memory["pending_action"] = "edit_login"
    memory["pending_field"] = field
    memory["last_service"] = service
    memory._flush_disabled = False
    memory._flush()


def clear_pending(vault_id: str) -> None:
    memory = get_memory(vault_id)
    memory._flush_disabled = True
    memory["pending_action"] = None
    memory["pending_field"] = None
    memory._flush_disabled = False
    memory._flush()


LAST_FILE_SEARCH_MAX_ITEMS = 25


def set_last_file_search_results(
    vault_id: str,
    *,
    kind: str,
    results: list,
) -> None:
    memory = get_memory(vault_id)
    snapshot = []
    for raw in results[:LAST_FILE_SEARCH_MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue

        raw_reasons = raw.get("reasons")
        if isinstance(raw_reasons, list):
            safe_reasons = [
                str(r) for r in raw_reasons
                if isinstance(r, str) and r.strip()
            ]
        else:
            safe_reasons = []

        density_raw = raw.get("credential_density")
        density = (
            round(float(density_raw), 4)
            if isinstance(density_raw, (int, float)) else 0.0
        )
        block_count_raw = raw.get("credential_block_count")
        block_count = (
            int(block_count_raw)
            if isinstance(block_count_raw, int) else 0
        )
        service_count_raw = raw.get("service_count")
        service_count = (
            int(service_count_raw)
            if isinstance(service_count_raw, int) else 0
        )

        purpose_raw = raw.get("purpose")
        purpose = (
            str(purpose_raw)
            if isinstance(purpose_raw, str) and purpose_raw.strip()
            else ""
        )
        purpose_label_raw = raw.get("purpose_label")
        purpose_label = (
            str(purpose_label_raw).strip()
            if isinstance(purpose_label_raw, str) else ""
        )
        snapshot.append({
            "file_id":               str(raw.get("file_id") or raw.get("id") or ""),
            "file_name":             raw.get("file_name") or "",
            "saved_name":            raw.get("saved_name") or "",
            "relative_path":         raw.get("relative_path") or "",
            "mime_type":             raw.get("mime_type") or raw.get("content_type") or "",
            "asset_type":            raw.get("asset_type") or "file",
            "confidence":            (raw.get("confidence") or "").lower(),
            "reasons":               safe_reasons,
            "credential_density":    density,
            "credential_block_count": block_count,
            "service_count":         service_count,
            "mostly_credentials":    bool(raw.get("mostly_credentials") or False),
            "best_match":            bool(raw.get("best_match") or False),
            "purpose":               purpose,
            "purpose_label":         purpose_label,
        })
    memory["last_file_search"] = {
        "kind":    str(kind or ""),
        "results": snapshot,
    }


def get_last_file_search_results(vault_id: str) -> Optional[dict]:
    memory = get_memory(vault_id)
    snapshot = memory.get("last_file_search")
    if not snapshot or not isinstance(snapshot, dict):
        return None
    results = snapshot.get("results") or []
    if not results:
        return None
    return snapshot


def clear_last_file_search_results(vault_id: str) -> None:
    memory = get_memory(vault_id)
    if "last_file_search" in memory:
        memory.pop("last_file_search", None)


def _reset_for_test() -> None:
    """Test-only. Reset the shared backend."""
    from vault_chat_state_store import (
        reset_chat_state_backend_for_tests,
    )
    reset_chat_state_backend_for_tests()


class TTLDict:
    """Process-local LRU dict with per-entry TTL.

    Kept as a compatibility export for callers that need a
    lightweight in-process cache that does NOT require cross-
    worker consistency (e.g. ``main.LAST_SERVICE_CACHE`` — a
    prompt-context hint whose loss on worker-hop is acceptable).

    New per-vault chat state (pending drafts, pending login draft,
    etc.) MUST use ``get_memory()`` / ``SavedDict`` / ``CHAT_MEMORY``
    which write-through to the shared backend. Do not add new
    cross-turn state to TTLDict — it will only work reliably in a
    single-worker deploy.
    """

    __slots__ = ("_data", "max_size", "ttl_seconds")

    def __init__(self, max_size: int, ttl_seconds: int) -> None:
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def _evict_expired(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        while self._data:
            key = next(iter(self._data))
            ts, _ = self._data[key]
            if ts < cutoff:
                self._data.popitem(last=False)
            else:
                break

    def get(self, key: str) -> Optional[Any]:
        if key not in self._data:
            return None
        ts, value = self._data[key]
        if time.time() - ts > self.ttl_seconds:
            del self._data[key]
            return None
        self._data[key] = (time.time(), value)
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._evict_expired()
        self._data[key] = (time.time(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def pop(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            _, value = self._data.pop(key)
            return value
        return default

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def __len__(self) -> int:
        return len(self._data)
