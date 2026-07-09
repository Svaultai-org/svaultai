

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import unittest
from typing import Optional
from unittest import mock


import vault_startup


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Captured(unittest.TestCase):


    pass


class _LogCapture(logging.Handler):


    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]

    def any(self, fragment: str) -> bool:
        return any(fragment in m for m in self.messages())


class ScheduleDoesNotAwaitReconcilerTests(_Captured):


    def test_schedule_returns_before_reconciler_finishes(self) -> None:
        async def _slow_reconciler():
            await asyncio.sleep(5.0)

        async def _fake_startup_daemon():
            return None

                                                  
        fake_reconciler_module = mock.Mock()
        fake_reconciler_module.reconcile_all_vaults_at_startup = mock.Mock(
            side_effect=lambda: time.sleep(5.0),
        )
        fake_daemon_module = mock.Mock()
        fake_daemon_module.startup_daemon = mock.AsyncMock(
            side_effect=_fake_startup_daemon,
        )

        with mock.patch.dict(sys.modules, {
            "vault_reconciler": fake_reconciler_module,
            "vault_analysis_daemon": fake_daemon_module,
        }):
            async def _go():
                started_at = time.monotonic()
                tasks = await vault_startup.schedule_background_startup_tasks()
                elapsed = time.monotonic() - started_at
                self.assertLess(
                    elapsed, 1.0,
                    f"schedule blocked for {elapsed:.2f}s — must "
                    "return immediately so /health can respond",
                )
                                                            
                self.assertIsNotNone(tasks.reconciler)
                self.assertFalse(tasks.reconciler.done())
                                                                 
                                
                await vault_startup.cancel_background_startup_tasks(tasks)

            _run(_go())

    def test_schedule_logs_spec_prefixes(self) -> None:


        async def _fake_startup_daemon():
            return None

        fake_reconciler_module = mock.Mock()
        fake_reconciler_module.reconcile_all_vaults_at_startup = mock.Mock(
            return_value={"vaults_touched": 0},
        )
        fake_daemon_module = mock.Mock()
        fake_daemon_module.startup_daemon = mock.AsyncMock(
            side_effect=_fake_startup_daemon,
        )

        with mock.patch.object(vault_startup, "logger") as fake_logger:
            with mock.patch.dict(sys.modules, {
                "vault_reconciler": fake_reconciler_module,
                "vault_analysis_daemon": fake_daemon_module,
            }):
                async def _go():
                    tasks = await vault_startup.schedule_background_startup_tasks()
                    if tasks.reconciler is not None:
                        await tasks.reconciler

                _run(_go())

            info_msgs = " | ".join(
                str(call.args[0]) if call.args else ""
                for call in fake_logger.info.call_args_list
            )

        self.assertIn("startup: scheduling vault reconciler", info_msgs)
        self.assertIn("reconciler: started in background", info_msgs)
        self.assertIn("reconciler: finished", info_msgs)
        self.assertIn("daemon: started", info_msgs)
        self.assertIn("startup: app ready", info_msgs)


class ReconcilerErrorIsLoggedNotRaisedTests(_Captured):


    def test_reconciler_raise_is_swallowed(self) -> None:
        async def _fake_startup_daemon():
            return None

        fake_reconciler_module = mock.Mock()
        fake_reconciler_module.reconcile_all_vaults_at_startup = mock.Mock(
            side_effect=RuntimeError("simulated DB outage"),
        )
        fake_daemon_module = mock.Mock()
        fake_daemon_module.startup_daemon = mock.AsyncMock(
            side_effect=_fake_startup_daemon,
        )

        with mock.patch.object(vault_startup, "logger") as fake_logger:
            with mock.patch.dict(sys.modules, {
                "vault_reconciler": fake_reconciler_module,
                "vault_analysis_daemon": fake_daemon_module,
            }):
                async def _go():
                    tasks = await vault_startup.schedule_background_startup_tasks()
                    if tasks.reconciler is not None:
                        await tasks.reconciler

                _run(_go())

                                                                   
            exc_msgs = " | ".join(
                str(call.args[0]) if call.args else ""
                for call in fake_logger.exception.call_args_list
            )

        self.assertIn("reconciler: failed", exc_msgs)


class ReconcilerTimeoutTests(_Captured):


    def test_timeout_surfaces_log(self) -> None:
        async def _fake_startup_daemon():
            return None

        fake_reconciler_module = mock.Mock()
        fake_reconciler_module.reconcile_all_vaults_at_startup = mock.Mock(
            side_effect=lambda: time.sleep(5.0),
        )
        fake_daemon_module = mock.Mock()
        fake_daemon_module.startup_daemon = mock.AsyncMock(
            side_effect=_fake_startup_daemon,
        )

                                                 
        with mock.patch.object(vault_startup, "logger") as fake_logger:
            with mock.patch.dict(os.environ, {
                "VAULTAI_RECONCILER_TIMEOUT_SECS": "0.1",
            }):
                with mock.patch.dict(sys.modules, {
                    "vault_reconciler": fake_reconciler_module,
                    "vault_analysis_daemon": fake_daemon_module,
                }):
                    async def _go():
                        tasks = await vault_startup.schedule_background_startup_tasks()
                        if tasks.reconciler is not None:
                            await tasks.reconciler

                    _run(_go())

                                            
            warn_msgs = " | ".join(
                str(call.args[0]) if call.args else ""
                for call in fake_logger.warning.call_args_list
            )

        self.assertIn("reconciler: timed out", warn_msgs)

    def test_default_timeout_value(self) -> None:
        self.assertEqual(
            vault_startup.DEFAULT_RECONCILER_TIMEOUT_SECS, 60.0,
        )

    def test_env_override_parses(self) -> None:
        prior = os.environ.pop("VAULTAI_RECONCILER_TIMEOUT_SECS", None)
        try:
            os.environ["VAULTAI_RECONCILER_TIMEOUT_SECS"] = "123.5"
            self.assertEqual(
                vault_startup._reconciler_timeout_secs(), 123.5,
            )
        finally:
            os.environ.pop("VAULTAI_RECONCILER_TIMEOUT_SECS", None)
            if prior is not None:
                os.environ["VAULTAI_RECONCILER_TIMEOUT_SECS"] = prior

    def test_env_override_invalid_falls_back(self) -> None:
        prior = os.environ.pop("VAULTAI_RECONCILER_TIMEOUT_SECS", None)
        try:
            os.environ["VAULTAI_RECONCILER_TIMEOUT_SECS"] = "not-a-number"
            self.assertEqual(
                vault_startup._reconciler_timeout_secs(),
                vault_startup.DEFAULT_RECONCILER_TIMEOUT_SECS,
            )
        finally:
            os.environ.pop("VAULTAI_RECONCILER_TIMEOUT_SECS", None)
            if prior is not None:
                os.environ["VAULTAI_RECONCILER_TIMEOUT_SECS"] = prior


class DaemonStartupFailureDoesNotCrashTests(_Captured):


    def test_daemon_failure_is_swallowed(self) -> None:
        fake_reconciler_module = mock.Mock()
        fake_reconciler_module.reconcile_all_vaults_at_startup = mock.Mock(
            return_value={"vaults_touched": 0},
        )

        async def _failing_daemon():
            raise RuntimeError("daemon refuses to start")

        fake_daemon_module = mock.Mock()
        fake_daemon_module.startup_daemon = mock.AsyncMock(
            side_effect=_failing_daemon,
        )

        with mock.patch.dict(sys.modules, {
            "vault_reconciler": fake_reconciler_module,
            "vault_analysis_daemon": fake_daemon_module,
        }):
            async def _go():
                tasks = await vault_startup.schedule_background_startup_tasks()
                if tasks.reconciler is not None:
                    await tasks.reconciler
                return tasks

            tasks = _run(_go())
                                                              
                                       
            self.assertIsNotNone(tasks)


class CancelDuringShutdownTests(_Captured):


    def test_cancel_finished_task_is_no_op(self) -> None:
        async def _fake_startup_daemon():
            return None

        fake_reconciler_module = mock.Mock()
        fake_reconciler_module.reconcile_all_vaults_at_startup = mock.Mock(
            return_value={"vaults_touched": 0},
        )
        fake_daemon_module = mock.Mock()
        fake_daemon_module.startup_daemon = mock.AsyncMock(
            side_effect=_fake_startup_daemon,
        )

        with mock.patch.dict(sys.modules, {
            "vault_reconciler": fake_reconciler_module,
            "vault_analysis_daemon": fake_daemon_module,
        }):
            async def _go():
                tasks = await vault_startup.schedule_background_startup_tasks()
                                            
                if tasks.reconciler is not None:
                    await tasks.reconciler
                                                 
                await vault_startup.cancel_background_startup_tasks(tasks)

            _run(_go())

    def test_cancel_running_task_is_clean(self) -> None:
        async def _fake_startup_daemon():
            return None

        fake_reconciler_module = mock.Mock()
        fake_reconciler_module.reconcile_all_vaults_at_startup = mock.Mock(
            side_effect=lambda: time.sleep(60.0),
        )
        fake_daemon_module = mock.Mock()
        fake_daemon_module.startup_daemon = mock.AsyncMock(
            side_effect=_fake_startup_daemon,
        )

        with mock.patch.dict(sys.modules, {
            "vault_reconciler": fake_reconciler_module,
            "vault_analysis_daemon": fake_daemon_module,
        }):
            async def _go():
                tasks = await vault_startup.schedule_background_startup_tasks()
                                                   
                await vault_startup.cancel_background_startup_tasks(tasks)
                                                                      
                               
                self.assertTrue(tasks.reconciler.done())

            _run(_go())


class StartupTasksDataclassTests(unittest.TestCase):
    def test_default_handles_are_none(self) -> None:
        st = vault_startup.StartupTasks()
        self.assertIsNone(st.reconciler)
        self.assertIsNone(st.daemon)


if __name__ == "__main__":
    unittest.main()
