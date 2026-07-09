

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


DEFAULT_DEBOUNCE_SECONDS: float = 5.0

                                                                  
DEFAULT_PERIODIC_SECONDS: float = 60.0


TRIGGER_STARTUP            = "startup"
TRIGGER_UNLOCK             = "unlock"
TRIGGER_FILE_UPLOADED      = "file_uploaded"
TRIGGER_FILE_EXTRACTED     = "file_extracted"
TRIGGER_FILE_OCR           = "file_ocr"
TRIGGER_FILE_TRANSCRIBED   = "file_transcribed"
TRIGGER_FILE_CHUNKED       = "file_chunked"
TRIGGER_CREDENTIAL_CHANGED = "credential_changed"
TRIGGER_PERIODIC           = "periodic"
TRIGGER_CHAT_FALLBACK      = "chat_fallback"

TRIGGER_KINDS = (
    TRIGGER_STARTUP, TRIGGER_UNLOCK,
    TRIGGER_FILE_UPLOADED, TRIGGER_FILE_EXTRACTED,
    TRIGGER_FILE_OCR, TRIGGER_FILE_TRANSCRIBED, TRIGGER_FILE_CHUNKED,
    TRIGGER_CREDENTIAL_CHANGED, TRIGGER_PERIODIC, TRIGGER_CHAT_FALLBACK,
)


@dataclass
class _DirtyEntry:

    vault_id:        str
    last_trigger_at: float
    trigger_kinds:   set[str] = field(default_factory=set)
    refresh_count:   int = 0


_dirty_set: dict[str, _DirtyEntry] = {}
_dirty_lock: Optional[asyncio.Lock] = None


def _ensure_lock() -> asyncio.Lock:
    global _dirty_lock
    if _dirty_lock is None:
        _dirty_lock = asyncio.Lock()
    return _dirty_lock


def _normalize_trigger(trigger_kind: str) -> str:
    if trigger_kind in TRIGGER_KINDS:
        return trigger_kind
    return TRIGGER_PERIODIC


def mark_vault_dirty(
    vault_id: str,
    *,
    trigger_kind: str = TRIGGER_PERIODIC,
) -> None:


    if not vault_id:
        return
    kind = _normalize_trigger(trigger_kind)
    now = time.time()
    entry = _dirty_set.get(vault_id)
    if entry is None:
        _dirty_set[vault_id] = _DirtyEntry(
            vault_id=vault_id,
            last_trigger_at=now,
            trigger_kinds={kind},
        )
    else:
        entry.last_trigger_at = now
        entry.trigger_kinds.add(kind)
    logger.info(
        "[INTEL-UPDATER] mark_dirty vault=%s trigger=%s pending=%d",
        (vault_id or "")[:8] + "...",
        kind,
        len(_dirty_set),
    )
                                                             
                                                    
    try:
        from vault_intelligence_cache import mark_stale
        mark_stale(vault_id)
    except Exception:
        logger.exception(
            "[INTEL-UPDATER] mark_stale failed vault=%s",
            (vault_id or "")[:8] + "...",
        )


def get_dirty_count() -> int:

    return len(_dirty_set)


def clear_dirty_for_tests() -> None:

    _dirty_set.clear()


def refresh_vault_intelligence(
    vault_id: str,
    key: Optional[bytes],
) -> bool:


    from vault_intelligence_cache import (
        mark_refreshing,
        write_cache,
        REFRESH_REFRESHING,
        REFRESH_FAILED,
    )

    if not vault_id:
        return False

                                                              
    mark_refreshing(vault_id)

    try:
        snapshot = _compute_snapshot(vault_id, key)
    except Exception:
        logger.exception(
            "[INTEL-UPDATER] compute failed vault=%s",
            (vault_id or "")[:8] + "...",
        )
        return False

    if snapshot is None:
                                                              
                                                   
        return False

    return write_cache(vault_id, key, snapshot)


def _compute_snapshot(
    vault_id: str, key: Optional[bytes],
) -> Optional[dict]:


    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return None
    try:
        import json as _json
        from vault_knowledge_tools import get_vault_intelligence
        blob = get_vault_intelligence(vault_id=vault_id, key=key)
        return _json.loads(blob)
    except Exception:
        logger.exception(
            "[INTEL-UPDATER] live collector failed vault=%s",
            (vault_id or "")[:8] + "...",
        )
        return None


_worker_task: Optional[asyncio.Task] = None
_worker_stop: Optional[asyncio.Event] = None


async def _worker_loop(
    debounce_seconds: float,
    periodic_seconds: float,
) -> None:


    global _worker_stop
    if _worker_stop is None:
        _worker_stop = asyncio.Event()
    last_periodic = time.time()
    while not _worker_stop.is_set():
        try:
            await asyncio.sleep(debounce_seconds)
        except asyncio.CancelledError:
            break

                                                                
        lock = _ensure_lock()
        async with lock:
            entries = list(_dirty_set.values())
            _dirty_set.clear()

                                                               
        now = time.time()
        if now - last_periodic >= periodic_seconds:
            last_periodic = now
            try:
                periodic_ids = _vaults_with_cached_keys()
            except Exception:
                periodic_ids = []
            for vid in periodic_ids:
                if not any(e.vault_id == vid for e in entries):
                    entries.append(_DirtyEntry(
                        vault_id=vid,
                        last_trigger_at=now,
                        trigger_kinds={TRIGGER_PERIODIC},
                    ))

        for entry in entries:
            try:
                key = _lookup_vault_key(entry.vault_id)
            except Exception:
                key = None
            try:
                await asyncio.to_thread(
                    refresh_vault_intelligence,
                    entry.vault_id, key,
                )
            except Exception:
                logger.exception(
                    "[INTEL-UPDATER] refresh raised vault=%s",
                    (entry.vault_id or "")[:8] + "...",
                )


def _lookup_vault_key(vault_id: str) -> Optional[bytes]:


    try:
        from vault_key_cache import get_cache
        cache = get_cache()
        for vid, token_id in cache.active_scopes():
            if vid == vault_id:
                key = cache.get(vault_id=vid, token_id=token_id)
                if key is not None:
                    return key
        return None
    except Exception:
        return None


def _vaults_with_cached_keys() -> list[str]:
    try:
        from vault_key_cache import get_cache
        cache = get_cache()
        return sorted({vid for vid, _ in cache.active_scopes()})
    except Exception:
        return []


async def startup_intelligence_updater(
    *,
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
    periodic_seconds: float = DEFAULT_PERIODIC_SECONDS,
) -> None:

    global _worker_task, _worker_stop
    if _worker_task is not None and not _worker_task.done():
        return
    if _is_disabled():
        logger.info(
            "[INTEL-UPDATER] disabled by "
            "VAULTAI_INTELLIGENCE_UPDATER_ENABLED=false; skipping",
        )
        return
    _worker_stop = asyncio.Event()
    _worker_task = asyncio.create_task(
        _worker_loop(debounce_seconds, periodic_seconds),
        name="vault-intelligence-updater",
    )
    logger.info(
        "[INTEL-UPDATER] started debounce=%.1fs periodic=%.1fs",
        debounce_seconds, periodic_seconds,
    )


async def shutdown_intelligence_updater() -> None:

    global _worker_task, _worker_stop
    if _worker_stop is not None:
        _worker_stop.set()
    if _worker_task is not None:
        try:
            _worker_task.cancel()
            try:
                await _worker_task
            except (asyncio.CancelledError, Exception):
                pass
        finally:
            _worker_task = None
            _worker_stop = None


def _is_disabled() -> bool:
    raw = os.getenv("VAULTAI_INTELLIGENCE_UPDATER_ENABLED", "").strip().lower()
    if raw in ("", "1", "true", "yes", "on"):
        return False
    return True


def on_vault_unlock(vault_id: str) -> None:
    mark_vault_dirty(vault_id, trigger_kind=TRIGGER_UNLOCK)


def on_file_uploaded(vault_id: str) -> None:
    mark_vault_dirty(vault_id, trigger_kind=TRIGGER_FILE_UPLOADED)


def on_file_extracted(vault_id: str) -> None:
    mark_vault_dirty(vault_id, trigger_kind=TRIGGER_FILE_EXTRACTED)


def on_file_ocr(vault_id: str) -> None:
    mark_vault_dirty(vault_id, trigger_kind=TRIGGER_FILE_OCR)


def on_file_transcribed(vault_id: str) -> None:
    mark_vault_dirty(vault_id, trigger_kind=TRIGGER_FILE_TRANSCRIBED)


def on_file_chunked(vault_id: str) -> None:
    mark_vault_dirty(vault_id, trigger_kind=TRIGGER_FILE_CHUNKED)


def on_credential_changed(vault_id: str) -> None:
    mark_vault_dirty(vault_id, trigger_kind=TRIGGER_CREDENTIAL_CHANGED)


__all__ = [
    "DEFAULT_DEBOUNCE_SECONDS",
    "DEFAULT_PERIODIC_SECONDS",
    "TRIGGER_STARTUP", "TRIGGER_UNLOCK", "TRIGGER_FILE_UPLOADED",
    "TRIGGER_FILE_EXTRACTED", "TRIGGER_FILE_OCR",
    "TRIGGER_FILE_TRANSCRIBED", "TRIGGER_FILE_CHUNKED",
    "TRIGGER_CREDENTIAL_CHANGED", "TRIGGER_PERIODIC",
    "TRIGGER_CHAT_FALLBACK", "TRIGGER_KINDS",
    "mark_vault_dirty",
    "get_dirty_count",
    "clear_dirty_for_tests",
    "refresh_vault_intelligence",
    "startup_intelligence_updater",
    "shutdown_intelligence_updater",
    "on_vault_unlock",
    "on_file_uploaded",
    "on_file_extracted",
    "on_file_ocr",
    "on_file_transcribed",
    "on_file_chunked",
    "on_credential_changed",
]
