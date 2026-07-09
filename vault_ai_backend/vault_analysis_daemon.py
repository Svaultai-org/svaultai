

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


try:
    from vault_config import worker as _worker_cfg
    _w = _worker_cfg()
    ITERATION_INTERVAL_SECONDS = _w.daemon_iteration_sleep_secs
    DRAIN_BUDGET_PER_VAULT_PER_ITER = _w.drain_budget_per_iter
    SHUTDOWN_GRACE_SECONDS = _w.daemon_shutdown_grace_secs
except Exception:
    ITERATION_INTERVAL_SECONDS = 1.0
    DRAIN_BUDGET_PER_VAULT_PER_ITER = 6
    SHUTDOWN_GRACE_SECONDS = 5.0


@dataclass
class DaemonStatus:


    running: bool = False
    started_at_unix: float = 0.0
    iterations_completed: int = 0
    last_iteration_at_unix: float = 0.0
    last_iteration_drained: int = 0
    last_iteration_failed: int = 0
    last_iteration_reconciled: int = 0
    cumulative_drained: int = 0
    cumulative_failed: int = 0
    cumulative_reconciled: int = 0
    active_vault_count: int = 0
    registered_drains: tuple[str, ...] = ()
    missing_drains: tuple[str, ...] = ()
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "running":                    bool(self.running),
            "started_at_unix":            float(self.started_at_unix),
            "iterations_completed":       int(self.iterations_completed),
            "last_iteration_at_unix":     float(self.last_iteration_at_unix),
            "last_iteration_drained":     int(self.last_iteration_drained),
            "last_iteration_failed":      int(self.last_iteration_failed),
            "last_iteration_reconciled":  int(self.last_iteration_reconciled),
            "cumulative_drained":         int(self.cumulative_drained),
            "cumulative_failed":          int(self.cumulative_failed),
            "cumulative_reconciled":      int(self.cumulative_reconciled),
            "active_vault_count":         int(self.active_vault_count),
            "registered_drains":          list(self.registered_drains),
            "missing_drains":             list(self.missing_drains),
            "last_error":                 self.last_error,
        }


_STATUS = DaemonStatus()
_TASK: Optional[asyncio.Task] = None
_SHUTDOWN: Optional[asyncio.Event] = None


def get_status() -> DaemonStatus:
    return _STATUS


def reset_for_tests() -> DaemonStatus:

    global _STATUS, _TASK, _SHUTDOWN
    _STATUS = DaemonStatus()
    _TASK = None
    _SHUTDOWN = None
    return _STATUS


_ALL_DRAIN_STAGES: tuple[str, ...] = (
    "text_extraction", "ocr", "archive_indexing",
    "audio_transcription", "file_understanding",
                                                            
                                                         
    "content_chunking",
)


def _drain_registry() -> tuple[dict, tuple[str, ...]]:


    out: dict = {}
    missing: list[str] = []
    try:
        from vault_analysis_worker import drain_text_extraction
        out["text_extraction"] = drain_text_extraction
    except Exception:
        missing.append("text_extraction")
        logger.exception("daemon: drain_text_extraction import failed")
    try:
        from vault_ocr_worker import drain_ocr
        out["ocr"] = drain_ocr
    except Exception:
        missing.append("ocr")
        logger.exception("daemon: drain_ocr import failed")
    try:
        from vault_archive_worker import drain_archive_indexing
        out["archive_indexing"] = drain_archive_indexing
    except Exception:
        missing.append("archive_indexing")
        logger.exception("daemon: drain_archive_indexing import failed")
    try:
        from vault_audio_worker import drain_audio_transcription
        out["audio_transcription"] = drain_audio_transcription
    except Exception:
        missing.append("audio_transcription")
        logger.exception("daemon: drain_audio_transcription import failed")
    try:
        from vault_understanding_worker import drain_file_understanding
        out["file_understanding"] = drain_file_understanding
    except Exception:
        missing.append("file_understanding")
        logger.exception("daemon: drain_file_understanding import failed")
    try:
        from vault_brain_worker import drain_content_chunking
        out["content_chunking"] = drain_content_chunking
    except Exception:
        missing.append("content_chunking")
        logger.exception("daemon: drain_content_chunking import failed")
    return out, tuple(missing)


async def run_one_iteration() -> dict:


    try:
        from vault_key_cache import get_cache
        from vault_reconciler import reconcile_vault
    except Exception as exc:
        _STATUS.last_error = f"import:{type(exc).__name__}"
        return {"drained": 0, "failed": 0, "reconciled": 0, "vaults": 0}

    cache = get_cache()
    scopes = cache.active_scopes()
    _STATUS.active_vault_count = len({s[0] for s in scopes})

    drain_fns, missing = _drain_registry()
    _STATUS.registered_drains = tuple(sorted(drain_fns.keys()))
    _STATUS.missing_drains = missing

    iter_drained = iter_failed = iter_reconciled = 0
                                                                  
                                                                   
    seen: set[str] = set()
    for vault_id, token_id in scopes:
        if vault_id in seen:
            continue
        seen.add(vault_id)
                                                                     
                                         
        key = cache.get(vault_id=vault_id, token_id=token_id)
        if key is None:
            continue
        try:
            report = await asyncio.to_thread(reconcile_vault, vault_id)
            iter_reconciled += int(report.total_repairs())
        except Exception:
            logger.exception(
                "daemon: reconcile_vault raised vault=%s", vault_id,
            )
        for stage in _ALL_DRAIN_STAGES:
            drain_fn = drain_fns.get(stage)
            if drain_fn is None:
                continue
            try:
                result = await asyncio.to_thread(
                    drain_fn,
                    vault_id=vault_id, key=key,
                    max_jobs=DRAIN_BUDGET_PER_VAULT_PER_ITER,
                )
            except Exception:
                logger.exception(
                    "daemon: drain %s raised vault=%s", stage, vault_id,
                )
                continue
            processed = int((result or {}).get("processed") or 0)
            failed = int((result or {}).get("failed") or 0)
            iter_drained += processed
            iter_failed += failed
            if processed > 0:
                break

    _STATUS.last_iteration_at_unix = time.time()
    _STATUS.last_iteration_drained = iter_drained
    _STATUS.last_iteration_failed = iter_failed
    _STATUS.last_iteration_reconciled = iter_reconciled
    _STATUS.cumulative_drained += iter_drained
    _STATUS.cumulative_failed += iter_failed
    _STATUS.cumulative_reconciled += iter_reconciled
    _STATUS.iterations_completed += 1
    return {
        "drained":    iter_drained,
        "failed":     iter_failed,
        "reconciled": iter_reconciled,
        "vaults":     len(seen),
    }


async def _loop() -> None:
    global _SHUTDOWN
    if _SHUTDOWN is None:
        _SHUTDOWN = asyncio.Event()
    _STATUS.running = True
    _STATUS.started_at_unix = time.time()
    logger.info(
        "[daemon] vault analysis daemon started: interval=%.1fs budget=%d",
        ITERATION_INTERVAL_SECONDS,
        DRAIN_BUDGET_PER_VAULT_PER_ITER,
    )
    try:
        while not _SHUTDOWN.is_set():
            try:
                stats = await run_one_iteration()
                _STATUS.last_error = None
                                                                   
                                                  
                if _STATUS.iterations_completed % 60 == 0:
                    logger.info(
                        "[daemon] tick=%d active_vaults=%d drained=%d "
                        "failed=%d reconciled=%d registered=%s missing=%s",
                        _STATUS.iterations_completed,
                        _STATUS.active_vault_count,
                        stats["drained"], stats["failed"],
                        stats["reconciled"],
                        ",".join(_STATUS.registered_drains) or "-",
                        ",".join(_STATUS.missing_drains) or "-",
                    )
            except Exception as exc:
                                                                      
                                               
                _STATUS.last_error = f"loop:{type(exc).__name__}"
                logger.exception("daemon: loop iteration crashed")
            try:
                await asyncio.wait_for(
                    _SHUTDOWN.wait(),
                    timeout=ITERATION_INTERVAL_SECONDS,
                )
            except asyncio.TimeoutError:
                pass
    finally:
        _STATUS.running = False
        logger.info("[daemon] vault analysis daemon stopped")


async def startup_daemon() -> None:

    global _TASK, _SHUTDOWN
    if _TASK is not None and not _TASK.done():
        return
    _SHUTDOWN = asyncio.Event()
    _TASK = asyncio.create_task(_loop(), name="vault_analysis_daemon")


async def shutdown_daemon() -> None:

    global _TASK, _SHUTDOWN
    if _SHUTDOWN is not None:
        _SHUTDOWN.set()
    if _TASK is not None:
        try:
            await asyncio.wait_for(_TASK, timeout=SHUTDOWN_GRACE_SECONDS)
        except asyncio.TimeoutError:
            _TASK.cancel()
            try:
                await _TASK
            except (asyncio.CancelledError, Exception):
                pass
    _TASK = None
    _SHUTDOWN = None


__all__ = [
    "DaemonStatus",
    "ITERATION_INTERVAL_SECONDS",
    "DRAIN_BUDGET_PER_VAULT_PER_ITER",
    "get_status",
    "reset_for_tests",
    "run_one_iteration",
    "startup_daemon",
    "shutdown_daemon",
]
