"""Tests for commit 7: shadow-mode readiness (metrics aggregator +
diagnostics module).

Covers:
    * ShadowMetrics counters (diff, exception, parity, thread-safety)
    * record_shadow_diff idempotency + concurrent safety
    * record_pipeline_exception stage allowlist
    * get_metrics_snapshot deep-copy safety
    * validate_shadow_configuration (mode, fingerprint secret,
      fallback env)
    * run_startup_self_test synthetic pipeline pass
    * shadow_health_summary aggregation + thresholds
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import unittest
from typing import Any
from unittest import mock

import vault_chat_shadow_metrics_v2 as sm
import vault_chat_shadow_recorder_v2 as sr
import vault_chat_v2_diagnostics as diag

from vault_chat_decision_router_v2 import (
    ACTION_KIND_CONFIRM_SAVE,
    ACTION_KINDS,
)


TEST_FP_SECRET: bytes = (
    b"test-diagnostics-fingerprint-secret-please-use-in-tests"
)


def _fresh_diff(
    *, match: str = sr.MATCH_INTENT_EQUIVALENT,
    fp_available: bool = True,
    router_handled: bool = True,
    action_kind: str = "",
    v1_handled: bool = True,
    with_router_view: bool = True,
) -> sr.ShadowDiffRecordV2:
    router_view = None
    if with_router_view:
        router_view = sr.ShadowRouterView(
            handled=router_handled,
            reply_kind="none",
            next_state="execute" if router_handled else "fallthrough",
            action_kind=action_kind,
        )
    return sr.ShadowDiffRecordV2(
        vault_hmac64="aaaa", session_hmac64="bbbb", turn_hmac64="cccc",
        v1_tool="fallthrough", v1_handled=v1_handled,
        v2_intent="confirm_draft", v2_target_kind="draft",
        v2_target_id_hmac64="dddd",
        v2_outcome="allow", v2_reason_code="ALLOWED",
        v2_confidence_bucket="gte95", v2_fingerprint="ffff",
        match=match, router_view=router_view,
        fp_available=fp_available,
    )


# =====================================================================
# ShadowMetrics
# =====================================================================

class ShadowMetricsTest(unittest.TestCase):

    def setUp(self):
        sm.reset_metrics_for_tests()

    def tearDown(self):
        sm.reset_metrics_for_tests()

    def test_initial_snapshot_all_zeros(self):
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["diff_count"], 0)
        for cat in sr.MATCH_CATEGORIES:
            self.assertEqual(snap["matches"][cat], 0)
        for stage in sm.SHADOW_PIPELINE_STAGES:
            self.assertEqual(snap["pipeline_exceptions"][stage], 0)

    def test_record_shadow_diff_increments(self):
        sm.record_shadow_diff(_fresh_diff())
        sm.record_shadow_diff(_fresh_diff(match=sr.MATCH_DIFFERENT_SEMANTICS))
        sm.record_shadow_diff(_fresh_diff(match=sr.MATCH_V2_VALIDATION_ERROR))
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["diff_count"], 3)
        self.assertEqual(snap["matches"][sr.MATCH_INTENT_EQUIVALENT], 1)
        self.assertEqual(snap["matches"][sr.MATCH_DIFFERENT_SEMANTICS], 1)
        self.assertEqual(snap["matches"][sr.MATCH_V2_VALIDATION_ERROR], 1)

    def test_match_ratios_reflect_percentages(self):
        for _ in range(4):
            sm.record_shadow_diff(_fresh_diff(match=sr.MATCH_INTENT_EQUIVALENT))
        sm.record_shadow_diff(_fresh_diff(match=sr.MATCH_DIFFERENT_SEMANTICS))
        snap = sm.get_metrics_snapshot()
        self.assertEqual(
            snap["match_ratios_pct"][sr.MATCH_INTENT_EQUIVALENT], 80.0,
        )
        self.assertEqual(
            snap["match_ratios_pct"][sr.MATCH_DIFFERENT_SEMANTICS], 20.0,
        )

    def test_fp_available_and_unavailable_counters(self):
        for _ in range(3):
            sm.record_shadow_diff(_fresh_diff(fp_available=True))
        for _ in range(1):
            sm.record_shadow_diff(_fresh_diff(fp_available=False))
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["fp_available_count"], 3)
        self.assertEqual(snap["fp_unavailable_count"], 1)
        self.assertEqual(snap["fp_available_ratio_pct"], 75.0)

    def test_action_kind_counts_bounded_to_action_kinds(self):
        sm.record_shadow_diff(_fresh_diff(action_kind=ACTION_KIND_CONFIRM_SAVE))
        sm.record_shadow_diff(_fresh_diff(action_kind="not_a_real_action"))
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["action_kind_counts"][ACTION_KIND_CONFIRM_SAVE], 1)
        self.assertNotIn("not_a_real_action", snap["action_kind_counts"])
        # Every real action kind is present in the counts dict
        # (even at zero) so operators can enumerate exhaustively.
        for kind in ACTION_KINDS:
            self.assertIn(kind, snap["action_kind_counts"])

    def test_pipeline_exception_recording(self):
        sm.record_pipeline_exception("decider", "TimeoutError")
        sm.record_pipeline_exception("decider", "TimeoutError")
        sm.record_pipeline_exception("router", "AssertionError")
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["pipeline_exceptions"]["decider"], 2)
        self.assertEqual(snap["pipeline_exceptions"]["router"], 1)
        self.assertEqual(
            snap["pipeline_exception_types"]["decider"]["TimeoutError"], 2,
        )
        self.assertEqual(
            snap["pipeline_exception_types"]["router"]["AssertionError"], 1,
        )

    def test_pipeline_exception_unknown_stage_dropped(self):
        # Not raised -- logged and dropped. Snapshot stays clean.
        sm.record_pipeline_exception("mystery", "SomeError")
        snap = sm.get_metrics_snapshot()
        for stage in sm.SHADOW_PIPELINE_STAGES:
            self.assertEqual(snap["pipeline_exceptions"][stage], 0)

    def test_snapshot_returns_deep_copy(self):
        sm.record_shadow_diff(_fresh_diff())
        snap1 = sm.get_metrics_snapshot()
        # Mutating the snapshot must not affect subsequent snapshots.
        snap1["matches"][sr.MATCH_INTENT_EQUIVALENT] = 99999
        snap1["pipeline_exceptions"]["decider"] = 99999
        snap2 = sm.get_metrics_snapshot()
        self.assertEqual(snap2["matches"][sr.MATCH_INTENT_EQUIVALENT], 1)
        self.assertEqual(snap2["pipeline_exceptions"]["decider"], 0)

    def test_router_and_v1_counters(self):
        sm.record_shadow_diff(_fresh_diff(router_handled=True, v1_handled=True))
        sm.record_shadow_diff(_fresh_diff(router_handled=False, v1_handled=False))
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["router_handled_count"], 1)
        self.assertEqual(snap["router_fallthrough_count"], 1)
        self.assertEqual(snap["v1_handled_count"], 1)
        self.assertEqual(snap["v1_fallthrough_count"], 1)

    def test_concurrent_writes_are_safe(self):
        # Fire N threads recording M diffs each; verify total.
        N_THREADS = 8
        M_PER_THREAD = 50
        def worker():
            for _ in range(M_PER_THREAD):
                sm.record_shadow_diff(_fresh_diff())
        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["diff_count"], N_THREADS * M_PER_THREAD)

    def test_bound_exception_type_length(self):
        # A pathologically-long type name must be truncated so it
        # cannot bloat the dict indefinitely.
        long_name = "A" * 500
        sm.record_pipeline_exception("decider", long_name)
        snap = sm.get_metrics_snapshot()
        for k in snap["pipeline_exception_types"]["decider"]:
            self.assertLessEqual(len(k), 64)


# =====================================================================
# validate_shadow_configuration
# =====================================================================

class ValidateShadowConfigurationTest(unittest.TestCase):

    def setUp(self):
        # Clear env + test-injected fingerprint secret so each
        # test starts pristine.
        for k in (
            "VAULTAI_CHAT_BRAIN_MODE",
            "VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET",
            "VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK",
        ):
            os.environ.pop(k, None)
        sr.reset_fingerprint_secret_for_tests()

    def tearDown(self):
        self.setUp()

    def test_default_off_mode_is_ok_without_secret(self):
        report = diag.validate_shadow_configuration()
        self.assertTrue(report.ok)
        self.assertEqual(report.mode, "off")

    def test_shadow_mode_without_secret_reports_error(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "shadow"
        report = diag.validate_shadow_configuration()
        self.assertFalse(report.ok)
        codes = [f.code for f in report.findings]
        self.assertIn("fingerprint_secret_missing_or_too_short", codes)

    def test_shadow_mode_with_short_env_secret_reports_error(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "shadow"
        os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"] = "short"
        report = diag.validate_shadow_configuration()
        self.assertFalse(report.ok)

    def test_shadow_mode_with_valid_secret_is_ok(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "shadow"
        os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"] = (
            "a-sufficiently-long-fingerprint-secret-for-tests-only"
        )
        report = diag.validate_shadow_configuration()
        self.assertTrue(report.ok)
        codes = [f.code for f in report.findings]
        self.assertIn("fingerprint_secret_present", codes)

    def test_on_mode_without_explicit_fallback_env_warns(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "on"
        os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"] = (
            "a-sufficiently-long-fingerprint-secret-for-tests-only"
        )
        report = diag.validate_shadow_configuration()
        # Warn does NOT flip ok=False.
        self.assertTrue(report.ok)
        codes = [f.code for f in report.findings]
        self.assertIn("v1_fallback_env_unset", codes)

    def test_unknown_mode_string_warns(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "sideways"
        report = diag.validate_shadow_configuration()
        # read_brain_mode already normalized to "off", so no
        # error, but the raw-value warning surfaces.
        self.assertEqual(report.mode, "off")
        codes = [f.code for f in report.findings]
        self.assertIn("mode_unrecognized_value", codes)


# =====================================================================
# run_startup_self_test
# =====================================================================

class StartupSelfTestTest(unittest.TestCase):

    def test_synthetic_pass_returns_ok(self):
        report = diag.run_startup_self_test()
        self.assertTrue(report.ok, msg=str(report.as_dict()))
        stage_names = [s.name for s in report.stages]
        self.assertEqual(
            stage_names, ["snapshot", "decider", "policy", "router"],
        )
        for stage in report.stages:
            self.assertTrue(stage.ok, msg=f"{stage.name} failed: {stage.detail}")

    def test_report_has_duration_ms(self):
        report = diag.run_startup_self_test()
        self.assertGreaterEqual(report.duration_ms, 0)

    def test_decider_exception_surfaces_but_test_does_not_raise(self):
        async def broken_provider(**kwargs):
            raise RuntimeError("provider blown up")

        report = diag.run_startup_self_test(ai_provider=broken_provider)
        # decide_v2 catches internally and returns a fallthrough
        # decision with error set. The self-test's "decider" stage
        # itself does not fail -- decide_v2's exception surface is
        # part of its contract. The test verifies the pipeline
        # remains stable.
        self.assertTrue(any(s.name == "decider" for s in report.stages))


# =====================================================================
# shadow_health_summary
# =====================================================================

class ShadowHealthSummaryTest(unittest.TestCase):

    def setUp(self):
        sm.reset_metrics_for_tests()
        for k in (
            "VAULTAI_CHAT_BRAIN_MODE",
            "VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET",
            "VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK",
        ):
            os.environ.pop(k, None)
        sr.reset_fingerprint_secret_for_tests()

    def tearDown(self):
        self.setUp()

    def test_default_configuration_is_ready(self):
        report = diag.shadow_health_summary()
        self.assertEqual(report.status, diag.HEALTH_READY)
        self.assertEqual(list(report.reasons), [])

    def test_shadow_mode_missing_secret_is_unready(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "shadow"
        report = diag.shadow_health_summary()
        self.assertEqual(report.status, diag.HEALTH_UNREADY)
        self.assertTrue(any(
            r.startswith("config.fingerprint_secret_missing")
            for r in report.reasons
        ))

    def test_pipeline_exceptions_cause_degraded(self):
        os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"] = (
            "a-sufficiently-long-fingerprint-secret-for-tests-only"
        )
        sm.record_pipeline_exception("decider", "TimeoutError")
        report = diag.shadow_health_summary()
        # No config error -> DEGRADED (not UNREADY).
        self.assertEqual(report.status, diag.HEALTH_DEGRADED)
        self.assertTrue(any(
            r.startswith("pipeline.exception.decider=")
            for r in report.reasons
        ))

    def test_parity_break_is_unready_when_registry_supplied(self):
        # Empty registry breaks parity by the EXECUTOR_REQUIRED set.
        import vault_chat_integration_v2 as vi
        empty = vi.ExecutorRegistry()
        report = diag.shadow_health_summary(registry=empty)
        self.assertEqual(report.status, diag.HEALTH_UNREADY)
        self.assertTrue(any(
            r == "parity.action_inventory_mismatch" for r in report.reasons
        ))
        self.assertFalse(report.parity_ok)

    def test_quality_thresholds_trip_only_after_min_diffs(self):
        # A single v2_validation_error record shouldn't trip the
        # threshold because the sample size is below the minimum.
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)
        try:
            sm.record_shadow_diff(_fresh_diff(match=sr.MATCH_V2_VALIDATION_ERROR))
            report = diag.shadow_health_summary()
            self.assertNotIn(
                "quality.v2_validation_error_pct=100.0",
                report.reasons,
            )
        finally:
            sr.reset_fingerprint_secret_for_tests()

    def test_quality_thresholds_trip_with_enough_samples(self):
        # Fill above the min-samples threshold with all
        # v2_validation_error -> DEGRADED with quality reason.
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)
        try:
            for _ in range(101):
                sm.record_shadow_diff(_fresh_diff(match=sr.MATCH_V2_VALIDATION_ERROR))
            report = diag.shadow_health_summary()
            self.assertEqual(report.status, diag.HEALTH_DEGRADED)
            self.assertTrue(any(
                r.startswith("quality.v2_validation_error_pct=")
                for r in report.reasons
            ))
        finally:
            sr.reset_fingerprint_secret_for_tests()

    def test_report_as_dict_serializable(self):
        report = diag.shadow_health_summary()
        d = report.as_dict()
        self.assertIn("status", d)
        self.assertIn("reasons", d)
        self.assertIn("validation", d)
        self.assertIn("metrics", d)


if __name__ == "__main__":
    unittest.main()
