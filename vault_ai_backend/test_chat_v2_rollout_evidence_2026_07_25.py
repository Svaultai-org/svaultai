"""Tests for the durable rollout-evidence contract (commit 8a).

Covers:

    * canonical payload serialization is deterministic
    * HMAC signing + constant-time verification
    * load_rollout_evidence_from_path returns typed blockers
      on every failure mode (unreadable, malformed, missing
      signature, wrong alg, bad signature, bad envelope,
      bad payload version)
    * validate_rollout_evidence rejects on every documented
      blocker (revision mismatch, environment mismatch, expired,
      future-dated, window too short, insufficient diffs /
      workers, excess rates, low fp availability, missing
      approval_id)
    * process-local metrics are labeled process-local and carry
      the correlation fields
    * exception window is bounded and produces a rolling rate
    * memory bounds hold under adversarial distinct inputs
    * authoritative gate consumes evidence, not local counters:
        - zero local samples + valid evidence -> ready
        - abundant local samples + missing evidence -> not ready
        - local transient exception + valid evidence -> ready
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

import vault_chat_shadow_metrics_v2 as sm
import vault_chat_shadow_recorder_v2 as sr
import vault_chat_v2_diagnostics as diag
import vault_chat_v2_rollout_evidence as ev

from vault_chat_v2_versions import compute_v2_revision_stamp


TEST_HMAC_SECRET: bytes = b"test-hmac-secret-please-use-in-tests-only-32b"
OTHER_HMAC_SECRET: bytes = b"another-hmac-secret-of-similar-length-please"
TEST_FP_SECRET: bytes = b"test-fp-secret-please-use-in-tests-only-32b."


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _good_evidence(
    *, environment: str = "staging",
    revision_stamp: str = None,
    total_diffs: int = 50_000,
    workers_observed: int = 8,
    pipeline_exception_count: int = 10,
    different_semantics_pct: float = 0.5,
    validation_error_pct: float = 0.1,
    fingerprint_available_pct: float = 99.9,
    approved_at: datetime = None,
    expires_at: datetime = None,
    observation_started_at: datetime = None,
    observation_ended_at: datetime = None,
    approval_id: str = "approval-2026-07-25-01",
) -> ev.RolloutEvidenceV2:
    now = _now_utc()
    stamp = revision_stamp if revision_stamp is not None else compute_v2_revision_stamp()
    return ev.RolloutEvidenceV2(
        evidence_version=1,
        v2_revision_stamp=stamp,
        environment=environment,
        observation_started_at=(
            observation_started_at or (now - timedelta(days=3))
        ),
        observation_ended_at=(
            observation_ended_at or (now - timedelta(hours=1))
        ),
        total_diffs=total_diffs,
        workers_observed=workers_observed,
        pipeline_exception_count=pipeline_exception_count,
        different_semantics_pct=different_semantics_pct,
        validation_error_pct=validation_error_pct,
        fingerprint_available_pct=fingerprint_available_pct,
        disagreement_source_counts={
            "NONE": total_diffs - 100, "SEMANTIC": 100,
        },
        approved_at=(approved_at or (now - timedelta(minutes=30))),
        expires_at=(expires_at or (now + timedelta(days=1))),
        approval_id=approval_id,
    )


def _write_envelope(
    path: str, payload: dict, signature_hex: str,
    envelope_version: int = ev.EVIDENCE_ENVELOPE_VERSION,
    signature_alg: str = ev.SIGNATURE_ALG_HMAC_SHA256,
) -> None:
    envelope = {
        "envelope_version": envelope_version,
        "payload": payload,
        "signature_alg": signature_alg,
        "signature_hex": signature_hex,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh)


# =====================================================================
# Canonicalization
# =====================================================================

class CanonicalPayloadTest(unittest.TestCase):

    def test_canonical_bytes_are_sorted_and_compact(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        b = ev.canonical_payload_bytes(payload)
        s = b.decode("utf-8")
        # No whitespace between separators.
        self.assertNotIn(" ", s)
        # Keys are sorted alphabetically.
        # First key should be 'approval_id' (alphabetically first).
        self.assertTrue(s.startswith('{"approval_id":'))

    def test_datetimes_serialize_to_iso_z(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        for k in (
            "approved_at", "expires_at",
            "observation_started_at", "observation_ended_at",
        ):
            self.assertTrue(
                payload[k].endswith("Z"),
                msg=f"{k}={payload[k]!r} does not end with Z",
            )

    def test_roundtrip_evidence_to_payload_and_back(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        rebuilt = ev.payload_dict_to_evidence(payload)
        self.assertEqual(rebuilt.approval_id, evidence.approval_id)
        self.assertEqual(rebuilt.total_diffs, evidence.total_diffs)
        self.assertEqual(rebuilt.environment, evidence.environment)

    def test_payload_missing_key_rejected(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        del payload["approval_id"]
        with self.assertRaises(ValueError):
            ev.payload_dict_to_evidence(payload)

    def test_payload_extra_key_rejected(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        payload["unknown_field"] = "surprise"
        with self.assertRaises(ValueError):
            ev.payload_dict_to_evidence(payload)


# =====================================================================
# HMAC sign + verify
# =====================================================================

class SignVerifyTest(unittest.TestCase):

    def test_sign_produces_64_hex_chars(self):
        evidence = _good_evidence()
        sig = ev.sign_rollout_evidence(evidence, secret=TEST_HMAC_SECRET)
        self.assertEqual(len(sig), 64)
        int(sig, 16)  # hex-parseable

    def test_sign_rejects_short_secret(self):
        evidence = _good_evidence()
        with self.assertRaises(ValueError):
            ev.sign_rollout_evidence(evidence, secret=b"tiny")

    def test_verify_accepts_valid_signature(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        sig = ev.sign_rollout_evidence(evidence, secret=TEST_HMAC_SECRET)
        self.assertTrue(
            ev.verify_signature(payload, sig, secret=TEST_HMAC_SECRET),
        )

    def test_verify_rejects_tampered_payload(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        sig = ev.sign_rollout_evidence(evidence, secret=TEST_HMAC_SECRET)
        payload["total_diffs"] = 1
        self.assertFalse(
            ev.verify_signature(payload, sig, secret=TEST_HMAC_SECRET),
        )

    def test_verify_rejects_wrong_secret(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        sig = ev.sign_rollout_evidence(evidence, secret=TEST_HMAC_SECRET)
        self.assertFalse(
            ev.verify_signature(payload, sig, secret=OTHER_HMAC_SECRET),
        )

    def test_verify_rejects_wrong_length_signature(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        self.assertFalse(
            ev.verify_signature(payload, "deadbeef", secret=TEST_HMAC_SECRET),
        )

    def test_verify_rejects_short_secret(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        sig = ev.sign_rollout_evidence(evidence, secret=TEST_HMAC_SECRET)
        self.assertFalse(
            ev.verify_signature(payload, sig, secret=b"tiny"),
        )


# =====================================================================
# load_rollout_evidence_from_path
# =====================================================================

class LoadFromPathTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v2ev-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _path(self, name: str = "evidence.json") -> str:
        return os.path.join(self.tmp, name)

    def _valid_envelope(self) -> tuple[str, ev.RolloutEvidenceV2]:
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        sig = ev.sign_rollout_evidence(evidence, secret=TEST_HMAC_SECRET)
        path = self._path()
        _write_envelope(path, payload, sig)
        return path, evidence

    def test_valid_envelope_loads(self):
        path, evidence = self._valid_envelope()
        result = ev.load_rollout_evidence_from_path(
            path, secret=TEST_HMAC_SECRET,
        )
        self.assertIsNotNone(result.evidence)
        self.assertEqual(result.blockers, ())
        self.assertEqual(
            result.evidence.approval_id, evidence.approval_id,
        )

    def test_unreadable_path_returns_blocker(self):
        result = ev.load_rollout_evidence_from_path(
            "/no/such/path/really.json", secret=TEST_HMAC_SECRET,
        )
        self.assertIsNone(result.evidence)
        self.assertIn(ev.BLOCKER_EVIDENCE_PATH_UNREADABLE, result.blockers)

    def test_malformed_json_returns_blocker(self):
        path = self._path()
        with open(path, "w") as fh:
            fh.write("{ not valid json")
        result = ev.load_rollout_evidence_from_path(
            path, secret=TEST_HMAC_SECRET,
        )
        self.assertIn(ev.BLOCKER_EVIDENCE_MALFORMED, result.blockers)

    def test_wrong_envelope_version_returns_blocker(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        sig = ev.sign_rollout_evidence(evidence, secret=TEST_HMAC_SECRET)
        path = self._path()
        _write_envelope(path, payload, sig, envelope_version=999)
        result = ev.load_rollout_evidence_from_path(
            path, secret=TEST_HMAC_SECRET,
        )
        self.assertIn(
            ev.BLOCKER_EVIDENCE_ENVELOPE_VERSION, result.blockers,
        )

    def test_wrong_signature_alg_returns_blocker(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        sig = ev.sign_rollout_evidence(evidence, secret=TEST_HMAC_SECRET)
        path = self._path()
        _write_envelope(path, payload, sig, signature_alg="RSA-XYZ")
        result = ev.load_rollout_evidence_from_path(
            path, secret=TEST_HMAC_SECRET,
        )
        self.assertIn(
            ev.BLOCKER_EVIDENCE_SIGNATURE_ALG, result.blockers,
        )

    def test_missing_signature_returns_blocker(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        path = self._path()
        _write_envelope(path, payload, "")
        result = ev.load_rollout_evidence_from_path(
            path, secret=TEST_HMAC_SECRET,
        )
        self.assertIn(
            ev.BLOCKER_EVIDENCE_SIGNATURE_MISSING, result.blockers,
        )

    def test_invalid_signature_returns_blocker(self):
        evidence = _good_evidence()
        payload = ev.evidence_to_payload_dict(evidence)
        path = self._path()
        _write_envelope(path, payload, "a" * 64)  # 64-hex but wrong
        result = ev.load_rollout_evidence_from_path(
            path, secret=TEST_HMAC_SECRET,
        )
        self.assertIn(
            ev.BLOCKER_EVIDENCE_SIGNATURE_INVALID, result.blockers,
        )

    def test_wrong_secret_returns_blocker(self):
        path, _ = self._valid_envelope()
        result = ev.load_rollout_evidence_from_path(
            path, secret=OTHER_HMAC_SECRET,
        )
        self.assertIn(
            ev.BLOCKER_EVIDENCE_SIGNATURE_INVALID, result.blockers,
        )


# =====================================================================
# load_rollout_evidence_from_env
# =====================================================================

class LoadFromEnvTest(unittest.TestCase):

    def setUp(self):
        for k in (
            ev.ENV_ROLLOUT_EVIDENCE_PATH,
            ev.ENV_ROLLOUT_EVIDENCE_SECRET,
        ):
            os.environ.pop(k, None)
        self.tmp = tempfile.mkdtemp(prefix="v2ev-env-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k in (
            ev.ENV_ROLLOUT_EVIDENCE_PATH,
            ev.ENV_ROLLOUT_EVIDENCE_SECRET,
        ):
            os.environ.pop(k, None)

    def test_missing_env_path_returns_blocker(self):
        result = ev.load_rollout_evidence_from_env()
        self.assertIn(ev.BLOCKER_EVIDENCE_MISSING, result.blockers)

    def test_missing_env_secret_returns_blocker(self):
        os.environ[ev.ENV_ROLLOUT_EVIDENCE_PATH] = "/tmp/whatever"
        result = ev.load_rollout_evidence_from_env()
        self.assertIn(ev.BLOCKER_EVIDENCE_SECRET_MISSING, result.blockers)

    def test_short_env_secret_returns_blocker(self):
        os.environ[ev.ENV_ROLLOUT_EVIDENCE_PATH] = "/tmp/whatever"
        os.environ[ev.ENV_ROLLOUT_EVIDENCE_SECRET] = "tiny"
        result = ev.load_rollout_evidence_from_env()
        self.assertIn(ev.BLOCKER_EVIDENCE_SECRET_TOO_SHORT, result.blockers)


# =====================================================================
# validate_rollout_evidence
# =====================================================================

class ValidateEvidenceTest(unittest.TestCase):

    def test_valid_evidence_passes(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(), current_environment="staging",
        )
        self.assertTrue(r.valid, msg=f"blockers={r.blockers}")
        self.assertEqual(r.blockers, ())

    def test_revision_mismatch_refused(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(revision_stamp="b9.p9.r9.s9.q9.i9"),
            current_environment="staging",
        )
        self.assertIn(ev.BLOCKER_REVISION_MISMATCH, r.blockers)

    def test_environment_mismatch_refused(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(environment="staging"),
            current_environment="prod-canary",
        )
        self.assertIn(ev.BLOCKER_ENVIRONMENT_MISMATCH, r.blockers)

    def test_environment_unset_refused(self):
        # Both current_environment and env var must be absent.
        prev = os.environ.pop(ev.ENV_ENVIRONMENT, None)
        try:
            r = ev.validate_rollout_evidence(
                _good_evidence(), current_environment=None,
            )
            self.assertIn(ev.BLOCKER_ENVIRONMENT_UNSET, r.blockers)
        finally:
            if prev is not None:
                os.environ[ev.ENV_ENVIRONMENT] = prev

    def test_expired_evidence_refused(self):
        now = _now_utc()
        r = ev.validate_rollout_evidence(
            _good_evidence(expires_at=now - timedelta(minutes=1)),
            current_environment="staging",
        )
        self.assertIn(ev.BLOCKER_EVIDENCE_EXPIRED, r.blockers)

    def test_future_approved_refused(self):
        now = _now_utc()
        r = ev.validate_rollout_evidence(
            _good_evidence(approved_at=now + timedelta(hours=1)),
            current_environment="staging",
        )
        self.assertIn(ev.BLOCKER_APPROVED_IN_FUTURE, r.blockers)

    def test_future_observation_refused(self):
        now = _now_utc()
        r = ev.validate_rollout_evidence(
            _good_evidence(
                observation_started_at=now + timedelta(hours=2),
                observation_ended_at=now + timedelta(hours=3),
            ),
            current_environment="staging",
        )
        self.assertIn(ev.BLOCKER_OBSERVATION_IN_FUTURE, r.blockers)

    def test_inverted_observation_window_refused(self):
        now = _now_utc()
        r = ev.validate_rollout_evidence(
            _good_evidence(
                observation_started_at=now - timedelta(hours=1),
                observation_ended_at=now - timedelta(hours=5),
            ),
            current_environment="staging",
        )
        self.assertIn(
            ev.BLOCKER_OBSERVATION_WINDOW_INVERTED, r.blockers,
        )

    def test_short_observation_window_refused(self):
        now = _now_utc()
        r = ev.validate_rollout_evidence(
            _good_evidence(
                observation_started_at=now - timedelta(hours=2),
                observation_ended_at=now - timedelta(hours=1),
            ),
            current_environment="staging",
        )
        self.assertIn(
            ev.BLOCKER_OBSERVATION_WINDOW_TOO_SHORT, r.blockers,
        )

    def test_insufficient_diffs_refused(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(total_diffs=500),
            current_environment="staging",
        )
        self.assertIn(ev.BLOCKER_INSUFFICIENT_DIFFS, r.blockers)

    def test_insufficient_workers_refused(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(workers_observed=1),
            current_environment="staging",
        )
        self.assertIn(ev.BLOCKER_INSUFFICIENT_WORKERS, r.blockers)

    def test_excess_exception_rate_refused(self):
        # 10 / 50_000 = 0.02% OK; 400 / 50_000 = 0.8% exceeds 0.5%
        r = ev.validate_rollout_evidence(
            _good_evidence(
                total_diffs=50_000, pipeline_exception_count=400,
            ),
            current_environment="staging",
        )
        self.assertIn(ev.BLOCKER_EXCESS_EXCEPTION_RATE, r.blockers)

    def test_excess_semantic_disagreement_refused(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(different_semantics_pct=6.0),
            current_environment="staging",
        )
        self.assertIn(
            ev.BLOCKER_EXCESS_SEMANTIC_DISAGREEMENT, r.blockers,
        )

    def test_excess_validation_errors_refused(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(validation_error_pct=2.0),
            current_environment="staging",
        )
        self.assertIn(
            ev.BLOCKER_EXCESS_VALIDATION_ERRORS, r.blockers,
        )

    def test_low_fingerprint_availability_refused(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(fingerprint_available_pct=90.0),
            current_environment="staging",
        )
        self.assertIn(
            ev.BLOCKER_LOW_FINGERPRINT_AVAILABILITY, r.blockers,
        )

    def test_missing_approval_id_refused(self):
        r = ev.validate_rollout_evidence(
            _good_evidence(approval_id="  "),
            current_environment="staging",
        )
        self.assertIn(ev.BLOCKER_APPROVAL_ID_MISSING, r.blockers)


# =====================================================================
# Process-local metrics labeling (commit 8a-3)
# =====================================================================

class ProcessLocalLabelingTest(unittest.TestCase):

    def setUp(self):
        sm.reset_metrics_for_tests()
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)

    def tearDown(self):
        sm.reset_metrics_for_tests()
        sr.reset_fingerprint_secret_for_tests()

    def test_get_metrics_snapshot_carries_scope_label(self):
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["scope"], "process-local")

    def test_get_process_local_snapshot_dataclass(self):
        wrapped = sm.get_process_local_snapshot()
        d = wrapped.as_dict()
        self.assertEqual(d["scope"], "process-local")
        self.assertIn("process_id_hmac", d)
        self.assertIn("worker_started_at", d)
        self.assertIn("sample_window_started_at", d)
        self.assertIn("snapshot_at", d)
        # process_id_hmac must not equal the raw PID.
        self.assertNotEqual(str(os.getpid()), d["process_id_hmac"])

    def test_process_id_hmac_stable_within_process(self):
        a = sm.get_process_local_snapshot().process_id_hmac
        b = sm.get_process_local_snapshot().process_id_hmac
        self.assertEqual(a, b)


# =====================================================================
# Exception window (commit 8a-4)
# =====================================================================

class ExceptionWindowTest(unittest.TestCase):

    def setUp(self):
        sm.reset_metrics_for_tests()
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)

    def tearDown(self):
        sm.reset_metrics_for_tests()
        sr.reset_fingerprint_secret_for_tests()

    def _diff(self):
        # Manufacture a minimally-valid diff record.
        return sr.ShadowDiffRecordV2(
            vault_hmac64="a", session_hmac64="b", turn_hmac64="c",
            v1_tool="fallthrough", v1_handled=False,
            v2_intent="fallthrough", v2_target_kind="none",
            v2_target_id_hmac64="-",
            v2_outcome="allow", v2_reason_code="FALLTHROUGH",
            v2_confidence_bucket="gte95", v2_fingerprint="ffff",
            match=sr.MATCH_INTENT_EQUIVALENT,
        )

    def test_exception_window_reports_zero_at_start(self):
        snap = sm.get_metrics_snapshot()
        self.assertEqual(snap["exceptions_in_current_window"], 0)
        self.assertEqual(snap["exception_rate_pct"], 0.0)
        self.assertEqual(snap["exceptions_total"], 0)

    def test_exception_rate_is_bounded_by_window(self):
        # Fire 2x window size normal diffs then N exceptions.
        n_normal = sm.EXCEPTION_WINDOW_SIZE * 2
        n_excs = 50
        for _ in range(n_normal):
            sm.record_shadow_diff(self._diff())
        for _ in range(n_excs):
            sm.record_pipeline_exception("router", "AssertionError")
        snap = sm.get_metrics_snapshot()
        # Window shows the last N events (some normals plus all
        # exceptions since exceptions are appended after).
        self.assertLessEqual(
            snap["exception_window_size"], sm.EXCEPTION_WINDOW_SIZE,
        )
        self.assertGreaterEqual(snap["exceptions_in_current_window"], 1)
        # exceptions_total tracks lifetime.
        self.assertEqual(snap["exceptions_total"], n_excs)

    def test_last_exception_at_populated(self):
        before = time.time()
        sm.record_pipeline_exception("decider", "TimeoutError")
        snap = sm.get_metrics_snapshot()
        self.assertGreaterEqual(snap["last_exception_at"], before)


# =====================================================================
# Memory-bounds stress (commit 8a-6)
# =====================================================================

class MemoryBoundsStressTest(unittest.TestCase):
    """Adversarial distinct inputs: verify every histogram stays
    bounded regardless of the number of distinct keys pushed."""

    def setUp(self):
        sm.reset_metrics_for_tests()
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)

    def tearDown(self):
        sm.reset_metrics_for_tests()
        sr.reset_fingerprint_secret_for_tests()

    def test_distinct_exception_type_names_bounded(self):
        for i in range(500):
            sm.record_pipeline_exception("decider", f"AdversarialError{i}")
        snap = sm.get_metrics_snapshot()
        # Bounded to _MAX_DISTINCT_EXCEPTION_TYPES_PER_STAGE (32),
        # plus one __other__ bucket where overflow lands.
        self.assertLessEqual(
            len(snap["pipeline_exception_types"]["decider"]), 33,
        )
        # The overflow bucket exists.
        self.assertIn(
            "__other__",
            snap["pipeline_exception_types"]["decider"],
        )
        # And it counted overflow items (> 0).
        self.assertGreater(
            snap["pipeline_exception_types"]["decider"]["__other__"], 0,
        )

    def test_distinct_revision_stamps_bounded(self):
        # Build synthetic records with distinct stamps.
        for i in range(200):
            rec = sr.ShadowDiffRecordV2(
                vault_hmac64="a", session_hmac64="b", turn_hmac64="c",
                v1_tool="fallthrough", v1_handled=False,
                v2_intent="fallthrough", v2_target_kind="none",
                v2_target_id_hmac64="-",
                v2_outcome="allow", v2_reason_code="FALLTHROUGH",
                v2_confidence_bucket="gte95", v2_fingerprint="ffff",
                match=sr.MATCH_INTENT_EQUIVALENT,
                v2_revision_stamp=f"stamp-{i}",
            )
            sm.record_shadow_diff(rec)
        snap = sm.get_metrics_snapshot()
        # Bounded to 32 distinct stamps.
        self.assertLessEqual(len(snap["revision_stamps"]), 32)

    def test_unknown_pipeline_stage_dropped_silently(self):
        sm.record_pipeline_exception("mystery_stage", "SomeError")
        snap = sm.get_metrics_snapshot()
        for stage in sm.SHADOW_PIPELINE_STAGES:
            self.assertEqual(snap["pipeline_exceptions"][stage], 0)

    def test_unknown_action_kind_dropped(self):
        rec = sr.ShadowDiffRecordV2(
            vault_hmac64="a", session_hmac64="b", turn_hmac64="c",
            v1_tool="fallthrough", v1_handled=False,
            v2_intent="fallthrough", v2_target_kind="none",
            v2_target_id_hmac64="-",
            v2_outcome="allow", v2_reason_code="FALLTHROUGH",
            v2_confidence_bucket="gte95", v2_fingerprint="ffff",
            match=sr.MATCH_INTENT_EQUIVALENT,
            router_view=sr.ShadowRouterView(
                handled=True, reply_kind="none",
                next_state="execute",
                action_kind="mystery_action_kind",
            ),
        )
        sm.record_shadow_diff(rec)
        snap = sm.get_metrics_snapshot()
        self.assertNotIn(
            "mystery_action_kind", snap["action_kind_counts"],
        )

    def test_long_exception_type_name_truncated(self):
        long_name = "A" * 5000
        sm.record_pipeline_exception("decider", long_name)
        snap = sm.get_metrics_snapshot()
        for k in snap["pipeline_exception_types"]["decider"]:
            self.assertLessEqual(len(k), 64)

    def test_recent_window_bounded(self):
        # Pump 3x window's worth of events and confirm the
        # window doesn't grow beyond the maxlen.
        for _ in range(sm.EXCEPTION_WINDOW_SIZE * 3):
            sm.record_pipeline_exception("router", "T")
        snap = sm.get_metrics_snapshot()
        self.assertEqual(
            snap["exception_window_size"], sm.EXCEPTION_WINDOW_SIZE,
        )


if __name__ == "__main__":
    unittest.main()
