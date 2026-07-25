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
    from vault_chat_v2_versions import compute_v2_revision_stamp
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
        v2_revision_stamp=compute_v2_revision_stamp(),
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
            stage_names,
            ["enum_consistency", "snapshot", "decider", "policy", "router"],
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


# =====================================================================
# check_enum_consistency (commit 8-c)
# =====================================================================

class CheckEnumConsistencyTest(unittest.TestCase):

    def test_current_codebase_is_consistent(self):
        ok, violations = diag.check_enum_consistency()
        self.assertTrue(ok, msg=f"violations: {violations}")
        self.assertEqual(violations, [])

    def test_detects_missing_classification(self):
        # diag imported ACTION_KIND_CLASSIFICATION at module load;
        # patch its local binding.
        original = diag.ACTION_KIND_CLASSIFICATION
        try:
            from types import MappingProxyType
            partial = {k: v for k, v in original.items()}
            some_key = next(iter(partial.keys()))
            del partial[some_key]
            diag.ACTION_KIND_CLASSIFICATION = MappingProxyType(partial)
            ok, violations = diag.check_enum_consistency()
            self.assertFalse(ok)
            self.assertTrue(any("no classification entry" in v for v in violations))
        finally:
            diag.ACTION_KIND_CLASSIFICATION = original

    def test_detects_missing_reply_template(self):
        # Same import-binding caveat as above.
        from types import MappingProxyType
        original_success = diag.SUCCESS_REPLY_TEMPLATES
        original_failure = diag.FAILURE_REPLY_TEMPLATES
        try:
            # Drop 'save_draft' from success but leave failure
            # side intact -- that creates a mismatch the checker
            # must catch.
            reduced_success = {
                k: v for k, v in original_success.items() if k != "save_draft"
            }
            diag.SUCCESS_REPLY_TEMPLATES = MappingProxyType(reduced_success)
            ok, violations = diag.check_enum_consistency()
            self.assertFalse(ok)
            self.assertTrue(any(
                "'save_draft'" in v and "no success template" in v
                for v in violations
            ))
        finally:
            diag.SUCCESS_REPLY_TEMPLATES = original_success
            diag.FAILURE_REPLY_TEMPLATES = original_failure


# =====================================================================
# Split HealthReport dimensions (commit 8-d)
# =====================================================================

class HealthReportDimensionsTest(unittest.TestCase):

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

    def test_default_all_dimensions_present(self):
        report = diag.shadow_health_summary()
        self.assertEqual(report.configuration_status, diag.DIM_CONFIG_PASS)
        self.assertEqual(report.startup_status, diag.DIM_STARTUP_SKIP)
        self.assertEqual(report.runtime_status, diag.DIM_RUNTIME_PASS)
        # No samples -> insufficient samples, not degraded.
        self.assertEqual(
            report.behavior_status,
            diag.DIM_BEHAVIOR_INSUFFICIENT_SAMPLES,
        )

    def test_configuration_fail_flips_only_config_dimension(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "shadow"
        report = diag.shadow_health_summary()
        self.assertEqual(report.configuration_status, diag.DIM_CONFIG_FAIL)
        # Runtime + behavior separately -- still fine.
        self.assertEqual(report.runtime_status, diag.DIM_RUNTIME_PASS)

    def test_pipeline_exception_flips_only_runtime_dimension(self):
        os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"] = (
            "a-sufficiently-long-fingerprint-secret-for-tests-only"
        )
        sm.record_pipeline_exception("decider", "TimeoutError")
        report = diag.shadow_health_summary()
        self.assertEqual(report.runtime_status, diag.DIM_RUNTIME_DEGRADED)
        # Configuration unaffected.
        self.assertEqual(report.configuration_status, diag.DIM_CONFIG_PASS)

    def test_reasons_by_dimension_shape(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "shadow"
        sm.record_pipeline_exception("decider", "TimeoutError")
        report = diag.shadow_health_summary()
        # Both dimensions have reasons.
        self.assertIn("configuration", report.reasons_by_dimension)
        self.assertIn("runtime", report.reasons_by_dimension)


# =====================================================================
# Sample-size confidence tier (commit 8-e)
# =====================================================================

class ConfidenceTierTest(unittest.TestCase):

    def setUp(self):
        sm.reset_metrics_for_tests()
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)

    def tearDown(self):
        sm.reset_metrics_for_tests()
        sr.reset_fingerprint_secret_for_tests()

    def test_zero_diffs_is_low_confidence(self):
        report = diag.shadow_health_summary()
        self.assertEqual(report.confidence_tier, diag.CONFIDENCE_LOW)
        self.assertFalse(report.sample_size_ok)

    def test_below_min_samples_is_low_and_sample_not_ok(self):
        for _ in range(50):
            sm.record_shadow_diff(_fresh_diff())
        report = diag.shadow_health_summary()
        self.assertEqual(report.confidence_tier, diag.CONFIDENCE_LOW)
        self.assertFalse(report.sample_size_ok)

    def test_at_min_samples_is_low_but_sample_ok(self):
        for _ in range(100):
            sm.record_shadow_diff(_fresh_diff())
        report = diag.shadow_health_summary()
        self.assertEqual(report.confidence_tier, diag.CONFIDENCE_LOW)
        self.assertTrue(report.sample_size_ok)

    def test_medium_confidence_at_1k(self):
        for _ in range(1000):
            sm.record_shadow_diff(_fresh_diff())
        report = diag.shadow_health_summary()
        self.assertEqual(report.confidence_tier, diag.CONFIDENCE_MEDIUM)

    def test_high_confidence_at_10k(self):
        for _ in range(10_000):
            sm.record_shadow_diff(_fresh_diff())
        report = diag.shadow_health_summary()
        self.assertEqual(report.confidence_tier, diag.CONFIDENCE_HIGH)


# =====================================================================
# Authoritative readiness gate (commit 8-f)
# =====================================================================

class AuthoritativeReadinessGateTest(unittest.TestCase):

    def setUp(self):
        sm.reset_metrics_for_tests()
        for k in (
            "VAULTAI_CHAT_BRAIN_MODE",
            "VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET",
            "VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK",
        ):
            os.environ.pop(k, None)
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)
        # Complete production registry.
        import vault_chat_executor_adapters_v2 as adapters
        self.registry = adapters.build_production_executor_registry()

    def tearDown(self):
        sm.reset_metrics_for_tests()
        sr.reset_fingerprint_secret_for_tests()

    def _pass_config(self):
        os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"] = (
            "a-sufficiently-long-fingerprint-secret-for-tests-only"
        )

    def _good_evidence(self):
        # Build a well-formed evidence payload that would pass
        # validation against the current running code.
        from vault_chat_v2_rollout_evidence import RolloutEvidenceV2
        from vault_chat_v2_versions import compute_v2_revision_stamp
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        return RolloutEvidenceV2(
            evidence_version=1,
            v2_revision_stamp=compute_v2_revision_stamp(),
            environment="staging",
            observation_started_at=now - timedelta(days=3),
            observation_ended_at=now - timedelta(hours=1),
            total_diffs=50_000,
            workers_observed=8,
            pipeline_exception_count=10,       # 0.02% rate
            different_semantics_pct=0.5,
            validation_error_pct=0.1,
            fingerprint_available_pct=99.9,
            disagreement_source_counts={"NONE": 49_900, "SEMANTIC": 100},
            approved_at=now - timedelta(minutes=30),
            expires_at=now + timedelta(days=1),
            approval_id="approval-2026-07-25-01",
        )

    def test_empty_registry_refused_even_with_valid_evidence(self):
        self._pass_config()
        import vault_chat_integration_v2 as vi
        gate = diag.is_v2_authoritative_ready(
            vi.ExecutorRegistry(),
            self._good_evidence(),
            require_self_test=False,
            current_environment="staging",
        )
        self.assertFalse(gate.ready)
        self.assertTrue(any(
            b.startswith("registry.missing_executors")
            for b in gate.blockers
        ))

    def test_missing_evidence_refuses_even_with_full_registry(self):
        self._pass_config()
        # No env vars set for evidence -> load path returns
        # missing.
        for k in (
            "VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_PATH",
            "VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_HMAC_SECRET",
        ):
            os.environ.pop(k, None)
        gate = diag.is_v2_authoritative_ready(
            self.registry,
            None,
            require_self_test=False,
        )
        self.assertFalse(gate.ready)
        self.assertIn("evidence.missing", gate.blockers)

    def test_ready_with_valid_evidence_and_full_registry(self):
        self._pass_config()
        gate = diag.is_v2_authoritative_ready(
            self.registry,
            self._good_evidence(),
            require_self_test=True,
            current_environment="staging",
        )
        self.assertTrue(gate.ready, msg=f"blockers={gate.blockers}")
        self.assertEqual(gate.blockers, ())

    def test_local_pipeline_exception_does_not_block_valid_evidence(self):
        # Commit 8a: local metrics are process-local; a single
        # transient exception must NOT block the authoritative
        # gate when the durable evidence is clean.
        self._pass_config()
        sm.record_pipeline_exception("router", "AssertionError")
        gate = diag.is_v2_authoritative_ready(
            self.registry,
            self._good_evidence(),
            require_self_test=True,
            current_environment="staging",
        )
        self.assertTrue(gate.ready, msg=f"blockers={gate.blockers}")

    def test_zero_local_samples_ready_when_evidence_valid(self):
        # New worker with zero local diffs -- fleet evidence is
        # what matters.
        self._pass_config()
        gate = diag.is_v2_authoritative_ready(
            self.registry,
            self._good_evidence(),
            require_self_test=True,
            current_environment="staging",
        )
        self.assertTrue(gate.ready, msg=f"blockers={gate.blockers}")

    def test_high_local_samples_cannot_replace_missing_evidence(self):
        # A worker with abundant local samples MUST NOT bypass
        # the evidence requirement.
        self._pass_config()
        for _ in range(50_000):
            sm.record_shadow_diff(_fresh_diff())
        for k in (
            "VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_PATH",
            "VAULTAI_CHAT_BRAIN_V2_ROLLOUT_EVIDENCE_HMAC_SECRET",
        ):
            os.environ.pop(k, None)
        gate = diag.is_v2_authoritative_ready(
            self.registry,
            None,
            require_self_test=False,
        )
        self.assertFalse(gate.ready)
        self.assertIn("evidence.missing", gate.blockers)

    def test_startup_selftest_failure_still_blocks_with_valid_evidence(self):
        self._pass_config()
        # Force the self-test to fail by injecting an enum drift
        # that check_enum_consistency will catch.
        from types import MappingProxyType
        original = diag.ACTION_KIND_CLASSIFICATION
        try:
            partial = {k: v for k, v in original.items()}
            some_key = next(iter(partial.keys()))
            del partial[some_key]
            diag.ACTION_KIND_CLASSIFICATION = MappingProxyType(partial)
            gate = diag.is_v2_authoritative_ready(
                self.registry,
                self._good_evidence(),
                require_self_test=True,
                current_environment="staging",
            )
            self.assertFalse(gate.ready)
            self.assertTrue(any(
                "self_test.enum_consistency_failed" in b
                for b in gate.blockers
            ))
        finally:
            diag.ACTION_KIND_CLASSIFICATION = original

    def test_configuration_error_refuses_readiness(self):
        os.environ["VAULTAI_CHAT_BRAIN_MODE"] = "shadow"
        sr.reset_fingerprint_secret_for_tests()
        try:
            gate = diag.is_v2_authoritative_ready(
                self.registry,
                self._good_evidence(),
                require_self_test=False,
                current_environment="staging",
            )
            self.assertFalse(gate.ready)
            self.assertTrue(any(
                b == "configuration=FAIL" or "config." in b
                for b in gate.blockers
            ))
        finally:
            os.environ.pop("VAULTAI_CHAT_BRAIN_MODE", None)
            sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)

    def test_gate_as_dict_serializable(self):
        self._pass_config()
        gate = diag.is_v2_authoritative_ready(
            self.registry,
            self._good_evidence(),
            require_self_test=False,
            current_environment="staging",
        )
        d = gate.as_dict()
        self.assertIn("ready", d)
        self.assertIn("blockers", d)
        self.assertIn("evidence_present", d)
        self.assertIn("evidence_valid", d)


# =====================================================================
# Revision stamp (commit 8-a)
# =====================================================================

class RevisionStampTest(unittest.TestCase):

    def test_stamp_shape(self):
        from vault_chat_v2_versions import compute_v2_revision_stamp
        s = compute_v2_revision_stamp()
        # Format: b<n>.p<n>.r<n>.s<n>.q<n>.i<n>
        parts = s.split(".")
        self.assertEqual(len(parts), 6)
        for prefix, part in zip("bprsqi", parts):
            self.assertTrue(part.startswith(prefix))
            int(part[1:])  # tail is numeric

    def test_shadow_diff_record_carries_stamp(self):
        rec = _fresh_diff()
        # commit 8: every fresh diff carries the stamp.
        self.assertNotEqual(rec.v2_revision_stamp, "")

    def test_metrics_track_revision_stamps(self):
        sm.reset_metrics_for_tests()
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)
        try:
            for _ in range(5):
                sm.record_shadow_diff(_fresh_diff())
            snap = sm.get_metrics_snapshot()
            self.assertIn("revision_stamps", snap)
            # exactly one stamp seen.
            self.assertEqual(sum(snap["revision_stamps"].values()), 5)
        finally:
            sm.reset_metrics_for_tests()
            sr.reset_fingerprint_secret_for_tests()


# =====================================================================
# Disagreement source attribution (commit 8-b)
# =====================================================================

class DisagreementSourceAttributionTest(unittest.TestCase):

    def setUp(self):
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)

    def tearDown(self):
        sr.reset_fingerprint_secret_for_tests()

    def _decision(self, intent="confirm_draft", target_id="d-1"):
        from vault_chat_semantic_decision_v2 import (
            Authorization, SEMANTIC_DECISION_V2_SCHEMA_VERSION,
            SemanticDecisionV2, TARGET_KIND_DRAFT, TargetRef,
        )
        return SemanticDecisionV2(
            schema_version=SEMANTIC_DECISION_V2_SCHEMA_VERSION,
            intent=intent,
            target=TargetRef(kind=TARGET_KIND_DRAFT, id=target_id),
            field_patch={}, requested_operations=(),
            authorization=Authorization(granted=False),
            confidence=0.95, reason="",
        )

    def _policy(self, outcome="allow", reason="ALLOWED"):
        from vault_chat_policy_v2 import PolicyResultV2
        return PolicyResultV2(
            allowed=(outcome == "allow"),
            outcome=outcome, normalized_intent="confirm_draft",
            target_kind="draft", target_id="d-1",
            authorization_to_mint=None, validated_patch=None,
            reason_code=reason,
        )

    def test_agreement_yields_source_none(self):
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="confirm_pending_save", v1_handled=True,
            v2_decision=self._decision(),
            v2_policy=self._policy(),
        )
        self.assertEqual(
            rec.disagreement_source, sr.DISAGREEMENT_SOURCE_NONE,
        )

    def test_semantic_disagreement_when_intent_differs(self):
        # v1 chose confirm_pending_save; v2 chose cancel_draft.
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="confirm_pending_save", v1_handled=True,
            v2_decision=self._decision(intent="cancel_draft"),
            v2_policy=self._policy(),
        )
        self.assertEqual(
            rec.disagreement_source, sr.DISAGREEMENT_SOURCE_SEMANTIC,
        )

    def test_policy_disagreement_when_intent_agrees_but_policy_rejects(self):
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="confirm_pending_save", v1_handled=True,
            v2_decision=self._decision(intent="confirm_draft"),
            v2_policy=self._policy(
                outcome="reject", reason="TARGET_KIND_MISMATCH",
            ),
        )
        # intent agrees (family map), but policy rejected.
        self.assertEqual(
            rec.disagreement_source, sr.DISAGREEMENT_SOURCE_POLICY,
        )

    def test_v2_error_disagreement(self):
        from vault_chat_semantic_decision_v2 import make_fallthrough
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="fallthrough", v1_handled=False,
            v2_decision=make_fallthrough(error="bad_json"),
            v2_policy=None,
        )
        self.assertEqual(
            rec.disagreement_source, sr.DISAGREEMENT_SOURCE_V2_ERROR,
        )

    def test_insufficient_context_source(self):
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="confirm_pending_save", v1_handled=True,
            v2_decision=self._decision(),
            v2_policy=self._policy(
                outcome="clarify", reason="INSUFFICIENT_CONTEXT",
            ),
        )
        self.assertEqual(
            rec.disagreement_source,
            sr.DISAGREEMENT_SOURCE_INSUFFICIENT_CONTEXT,
        )


if __name__ == "__main__":
    unittest.main()
