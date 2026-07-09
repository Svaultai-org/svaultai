

from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest import mock


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class _AsyncCase(unittest.TestCase):
    def setUp(self) -> None:
        from vault_key_cache import reset_for_tests as reset_cache
        from vault_analysis_daemon import reset_for_tests as reset_daemon
        reset_cache(idle_ttl_seconds=60, hard_ttl_seconds=3600)
        reset_daemon()


class RunOneIterationTests(_AsyncCase):
    def test_no_active_vaults_is_a_quiet_noop(self) -> None:
        import vault_analysis_daemon as vd
        stats = _run(vd.run_one_iteration())
        self.assertEqual(stats, {"drained": 0, "failed": 0,
                                 "reconciled": 0, "vaults": 0})
        self.assertEqual(vd.get_status().iterations_completed, 1)
        self.assertEqual(vd.get_status().active_vault_count, 0)
        self.assertIsNone(vd.get_status().last_error)

    def test_one_active_vault_reconciles_then_drains(self) -> None:
        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
        get_cache().store(vault_id="v1", token_id="t1", key=b"K" * 32)

        drain_calls: list[dict] = []
        def fake_text_drain(*, vault_id, key, max_jobs):
            drain_calls.append({"vault_id": vault_id, "key_len": len(key),
                                "max_jobs": max_jobs, "stage": "text"})
            return {"processed": 4, "succeeded": 4, "failed": 0}

        with mock.patch.object(
            vd, "_drain_registry",
            return_value=({"text_extraction": fake_text_drain}, ()),
        ), mock.patch(
            "vault_reconciler.reconcile_vault",
        ) as recon:
            from vault_reconciler import ReconcilerReport
            recon.return_value = ReconcilerReport(
                vault_id="v1", status_drift_repaired=2,
            )
            stats = _run(vd.run_one_iteration())

        self.assertEqual(stats["vaults"], 1)
        self.assertEqual(stats["drained"], 4)
        self.assertEqual(stats["reconciled"], 2)
        self.assertEqual(stats["failed"], 0)
        recon.assert_called_once_with("v1")
        self.assertEqual(len(drain_calls), 1)
        self.assertEqual(drain_calls[0]["vault_id"], "v1")
        self.assertEqual(drain_calls[0]["key_len"], 32)
        self.assertEqual(drain_calls[0]["max_jobs"],
                         vd.DRAIN_BUDGET_PER_VAULT_PER_ITER)

    def test_two_sessions_same_vault_collapse_to_one_pass(self) -> None:


        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
        get_cache().store(vault_id="v1", token_id="phone", key=b"P" * 32)
        get_cache().store(vault_id="v1", token_id="laptop", key=b"L" * 32)

        drain_count = [0]
        def fake(*, vault_id, key, max_jobs):
            drain_count[0] += 1
            return {"processed": 1, "succeeded": 1, "failed": 0}

        with mock.patch.object(
            vd, "_drain_registry",
            return_value=({"text_extraction": fake}, ()),
        ), mock.patch(
            "vault_reconciler.reconcile_vault",
        ) as recon:
            from vault_reconciler import ReconcilerReport
            recon.return_value = ReconcilerReport(vault_id="v1")
            _run(vd.run_one_iteration())

        self.assertEqual(recon.call_count, 1,
            "vault should be reconciled ONCE per iteration even when "
            "two sessions are active")
        self.assertEqual(drain_count[0], 1,
            "drain should run ONCE per vault per iteration")

    def test_two_different_vaults_each_get_a_pass(self) -> None:
        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
        get_cache().store(vault_id="vA", token_id="tA", key=b"A" * 32)
        get_cache().store(vault_id="vB", token_id="tB", key=b"B" * 32)

        seen_vaults: list[str] = []
        def fake(*, vault_id, key, max_jobs):
            seen_vaults.append(vault_id)
            return {"processed": 1, "succeeded": 1, "failed": 0}

        with mock.patch.object(
            vd, "_drain_registry",
            return_value=({"text_extraction": fake}, ()),
        ), mock.patch(
            "vault_reconciler.reconcile_vault",
        ) as recon:
            from vault_reconciler import ReconcilerReport
            recon.return_value = ReconcilerReport(vault_id="v")
            _run(vd.run_one_iteration())

        self.assertEqual(set(seen_vaults), {"vA", "vB"})
        self.assertEqual(recon.call_count, 2)

    def test_drain_returning_zero_falls_through_to_next_stage(self) -> None:
        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
        get_cache().store(vault_id="v1", token_id="t1", key=b"K" * 32)

        text_called = [0]; ocr_called = [0]
        def text(*, vault_id, key, max_jobs):
            text_called[0] += 1
            return {"processed": 0, "succeeded": 0, "failed": 0}
        def ocr(*, vault_id, key, max_jobs):
            ocr_called[0] += 1
            return {"processed": 3, "succeeded": 3, "failed": 0}

        with mock.patch.object(
            vd, "_drain_registry",
            return_value=({"text_extraction": text, "ocr": ocr}, ()),
        ), mock.patch(
            "vault_reconciler.reconcile_vault",
        ) as recon:
            from vault_reconciler import ReconcilerReport
            recon.return_value = ReconcilerReport(vault_id="v1")
            stats = _run(vd.run_one_iteration())

        self.assertEqual(text_called[0], 1)
        self.assertEqual(ocr_called[0], 1)
        self.assertEqual(stats["drained"], 3)

    def test_drain_raise_caught_loop_continues(self) -> None:
        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
        get_cache().store(vault_id="v1", token_id="t1", key=b"K" * 32)

        def text(*, vault_id, key, max_jobs):
            raise RuntimeError("worker crashed")
        def ocr(*, vault_id, key, max_jobs):
            return {"processed": 2, "succeeded": 2, "failed": 0}

        with mock.patch.object(
            vd, "_drain_registry",
            return_value=({"text_extraction": text, "ocr": ocr}, ()),
        ), mock.patch(
            "vault_reconciler.reconcile_vault",
        ) as recon:
            from vault_reconciler import ReconcilerReport
            recon.return_value = ReconcilerReport(vault_id="v1")
            stats = _run(vd.run_one_iteration())

        self.assertEqual(stats["drained"], 2,
            "OCR drain must still run after text drain raised")

    def test_reconcile_raise_does_not_skip_drain(self) -> None:
        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
        get_cache().store(vault_id="v1", token_id="t1", key=b"K" * 32)

        def text(*, vault_id, key, max_jobs):
            return {"processed": 1, "succeeded": 1, "failed": 0}

        with mock.patch.object(
            vd, "_drain_registry",
            return_value=({"text_extraction": text}, ()),
        ), mock.patch(
            "vault_reconciler.reconcile_vault",
            side_effect=RuntimeError("reconciler crashed"),
        ):
            stats = _run(vd.run_one_iteration())

        self.assertEqual(stats["drained"], 1)
        self.assertEqual(stats["reconciled"], 0)

    def test_missing_drains_surfaced_in_status(self) -> None:
        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
        get_cache().store(vault_id="v1", token_id="t1", key=b"K" * 32)

        def text(*, vault_id, key, max_jobs):
            return {"processed": 1, "succeeded": 1, "failed": 0}

        with mock.patch.object(
            vd, "_drain_registry",
            return_value=({"text_extraction": text},
                          ("ocr", "audio_transcription")),
        ), mock.patch(
            "vault_reconciler.reconcile_vault",
        ) as recon:
            from vault_reconciler import ReconcilerReport
            recon.return_value = ReconcilerReport(vault_id="v1")
            _run(vd.run_one_iteration())

        st = vd.get_status()
        self.assertIn("ocr", st.missing_drains)
        self.assertIn("audio_transcription", st.missing_drains)
        self.assertIn("text_extraction", st.registered_drains)

    def test_expired_key_is_skipped_quietly(self) -> None:
        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
                                                             
        from vault_key_cache import reset_for_tests
        reset_for_tests(idle_ttl_seconds=0.01, hard_ttl_seconds=0.01)
        get_cache().store(vault_id="v1", token_id="t1", key=b"K" * 32)
        import time
        time.sleep(0.05)
        with mock.patch.object(vd, "_drain_registry",
                               return_value=({}, ())):
            stats = _run(vd.run_one_iteration())
                                                                
        self.assertEqual(stats["vaults"], 0)


class StatusSnapshotTests(_AsyncCase):
    def test_to_dict_is_closed_set(self) -> None:
        import vault_analysis_daemon as vd
        snap = vd.get_status().to_dict()
        self.assertEqual(
            set(snap.keys()),
            {
                "running", "started_at_unix", "iterations_completed",
                "last_iteration_at_unix", "last_iteration_drained",
                "last_iteration_failed", "last_iteration_reconciled",
                "cumulative_drained", "cumulative_failed",
                "cumulative_reconciled", "active_vault_count",
                "registered_drains", "missing_drains", "last_error",
            },
        )

    def test_status_never_contains_key_bytes_or_vault_ids(self) -> None:
        import vault_analysis_daemon as vd
        from vault_key_cache import get_cache
        get_cache().store(vault_id="vault-secret-123",
                          token_id="session-secret",
                          key=b"S" * 32)
        with mock.patch.object(vd, "_drain_registry",
                               return_value=({}, ())), mock.patch(
            "vault_reconciler.reconcile_vault",
        ) as recon:
            from vault_reconciler import ReconcilerReport
            recon.return_value = ReconcilerReport(vault_id="vault-secret-123")
            _run(vd.run_one_iteration())
        snap = vd.get_status().to_dict()
        flat = repr(snap)
        self.assertNotIn("vault-secret-123", flat,
            "status snapshot must not echo vault_ids")
        self.assertNotIn("session-secret", flat)
        self.assertNotIn("SSSS", flat)                


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        from vault_key_cache import reset_for_tests as reset_cache
        from vault_analysis_daemon import reset_for_tests as reset_daemon
        reset_cache(idle_ttl_seconds=60, hard_ttl_seconds=3600)
        reset_daemon()

    def test_startup_then_shutdown_round_trip(self) -> None:
        import vault_analysis_daemon as vd

        async def go():
            with mock.patch.object(vd, "_drain_registry",
                                   return_value=({}, ())):
                await vd.startup_daemon()
                await asyncio.sleep(0.05)                         
                self.assertTrue(vd.get_status().running)
                await vd.shutdown_daemon()
                self.assertFalse(vd.get_status().running)

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(go())

    def test_startup_idempotent(self) -> None:
        import vault_analysis_daemon as vd

        async def go():
            with mock.patch.object(vd, "_drain_registry",
                                   return_value=({}, ())):
                await vd.startup_daemon()
                await vd.startup_daemon()                      
                await asyncio.sleep(0.02)
                self.assertTrue(vd.get_status().running)
                await vd.shutdown_daemon()

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(go())


class IndependenceFromChatTests(unittest.TestCase):


    def test_daemon_module_does_not_import_chat_or_routes(self) -> None:
        import vault_analysis_daemon as vd
        src = inspect.getsource(vd)
        self.assertNotIn("from main import", src,
            "daemon must not depend on chat handler — that's the "
            "whole point of the daemon")
        self.assertNotIn("from routes.", src,
            "daemon must not depend on FastAPI routes")
        self.assertNotIn("step_deep_answer", src,
            "daemon must not call the chat-side engine")

    def test_daemon_module_does_not_log_keys(self) -> None:
        import vault_analysis_daemon as vd
        src = inspect.getsource(vd)
                                                                     
                                                                    
        for line in src.split("\n"):
            stripped = line.strip()
            if not stripped.startswith("logger."):
                continue
            self.assertNotIn(" key)", line,
                f"daemon log call may emit key bytes: {line!r}")
            self.assertNotIn("key=", line,
                f"daemon log call may emit key bytes: {line!r}")


if __name__ == "__main__":
    unittest.main()
