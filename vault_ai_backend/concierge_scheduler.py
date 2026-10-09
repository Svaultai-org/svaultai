"""Controlled consented-email poller, separate from vault decryption daemons."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from concierge_exposure import Settings, run_background_iteration

logger = logging.getLogger(__name__)


@dataclass
class SchedulerHandle:
    task: asyncio.Task
    stopping: asyncio.Event


async def _run(stopping: asyncio.Event) -> None:
    while not stopping.is_set():
        try:
            await asyncio.to_thread(run_background_iteration)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider/network/DB exceptions can carry consented targets or URLs.
            logger.warning("Concierge poll attempt unavailable; no successful check claimed")
        try:
            await asyncio.wait_for(stopping.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


def start_concierge_scheduler() -> SchedulerHandle | None:
    settings = Settings.from_environment()
    if not settings.enabled or not settings.background_enabled:
        return None
    stopping = asyncio.Event()
    task = asyncio.create_task(_run(stopping), name="concierge-consented-monitoring")
    return SchedulerHandle(task, stopping)


async def stop_concierge_scheduler(handle: SchedulerHandle | None) -> None:
    if handle is not None:
        handle.stopping.set()
        try:
            # Cancelling asyncio.to_thread does not stop its underlying thread.
            # Drain the bounded current check before main closes the shared pool;
            # do not begin another check after the shutdown event.
            await asyncio.shield(handle.task)
        except asyncio.CancelledError:
            raise
