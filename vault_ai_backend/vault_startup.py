

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional


logger = logging.getLogger(__name__)
                                                                   
                                                                     
if logger.level == logging.NOTSET or logger.level > logging.INFO:
    logger.setLevel(logging.INFO)


DEFAULT_RECONCILER_TIMEOUT_SECS = 60.0


@dataclass(frozen=True)
class StartupTasks:


    reconciler:         Optional[asyncio.Task] = None
    daemon:             Optional[asyncio.Task] = None
    inactive_cleanup:   Optional[asyncio.Task] = None


def _reconciler_timeout_secs() -> float:
    raw = os.getenv("VAULTAI_RECONCILER_TIMEOUT_SECS", "").strip()
    if not raw:
        return DEFAULT_RECONCILER_TIMEOUT_SECS
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        logger.warning(
            "[startup] VAULTAI_RECONCILER_TIMEOUT_SECS=%r is not a "
            "number; using default %fs",
            raw, DEFAULT_RECONCILER_TIMEOUT_SECS,
        )
        return DEFAULT_RECONCILER_TIMEOUT_SECS


async def _run_reconciler_with_timeout(timeout_secs: float) -> None:


    logger.info("reconciler: started in background")
    try:
        from vault_reconciler import reconcile_all_vaults_at_startup
    except Exception:
        logger.exception(
            "reconciler: failed to import vault_reconciler; skipping",
        )
        return
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(reconcile_all_vaults_at_startup),
            timeout=timeout_secs,
        )
        logger.info("reconciler: finished result=%s", result)
    except asyncio.TimeoutError:
        logger.warning(
            "reconciler: timed out after %.1fs; reconciliation will "
            "resume on the next chat poll for each vault.",
            timeout_secs,
        )
    except asyncio.CancelledError:
                                                       
        logger.info("reconciler: cancelled during server shutdown")
        raise
    except Exception:
                                                                 
                                                                    
        logger.exception(
            "reconciler: failed; reconciliation will resume on the "
            "next chat poll for each vault",
        )


async def _spawn_daemon() -> Optional[asyncio.Task]:


    try:
        from vault_analysis_daemon import startup_daemon
        await startup_daemon()
        logger.info("daemon: started")
    except Exception:
        logger.exception(
            "daemon: startup_daemon failed; analysis will only run "
            "from chat polls until restart",
        )
        return None
    return None


async def schedule_background_startup_tasks() -> StartupTasks:


    for name, lg in list(logging.root.manager.loggerDict.items()):
        if isinstance(lg, logging.Logger) and lg.disabled:
            lg.disabled = False

    logger.info("startup: scheduling vault reconciler")
    timeout = _reconciler_timeout_secs()
    reconciler_task = asyncio.create_task(
        _run_reconciler_with_timeout(timeout),
        name="vault-reconciler-startup",
    )

                                                                 
    await _spawn_daemon()

                                                                
    try:
        from vault_intelligence_updater import (
            startup_intelligence_updater,
        )
        await startup_intelligence_updater()
    except Exception:
        logger.exception(
            "intelligence-updater: startup failed; cache will "
            "refresh from chat-fallback paths only",
        )

  
    logger.info("startup: app ready")

    inactive_cleanup_task: Optional[asyncio.Task] = None
    try:
        from inactive_unpaid_cleanup import run_forever_daily
        inactive_cleanup_task = asyncio.create_task(
            run_forever_daily(),
            name="inactive-unpaid-cleanup",
        )
        logger.info(
            "inactive-cleanup: scheduled daily background loop",
        )
    except Exception:
        logger.exception(
            "inactive-cleanup: failed to schedule; "
            "unpaid-inactive-6-months cleanup will not run "
            "until next restart",
        )

    return StartupTasks(
        reconciler=reconciler_task,
        daemon=None,
        inactive_cleanup=inactive_cleanup_task,
    )


async def cancel_background_startup_tasks(tasks: StartupTasks) -> None:


    if tasks.reconciler is not None and not tasks.reconciler.done():
        tasks.reconciler.cancel()
        try:
            await tasks.reconciler
        except (asyncio.CancelledError, Exception):
                                                                  
                                                     
            pass


__all__ = [
    "StartupTasks",
    "DEFAULT_RECONCILER_TIMEOUT_SECS",
    "schedule_background_startup_tasks",
    "cancel_background_startup_tasks",
]
