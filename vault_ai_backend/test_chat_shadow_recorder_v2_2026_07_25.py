"""Tests for the shadow-mode diff logger."""

from __future__ import annotations

import os
import unittest
from unittest import mock

import vault_chat_shadow_recorder_v2 as sr
from vault_chat_decision_router_v2 import (
    ACTION_KIND_CONFIRM_SAVE,
    ExecutionPlanV2,
    FOCUS_ACTION_CLEAR_IF_MATCHES,
    FOCUS_ACTION_SET,
    FocusUpdate,
    NEXT_STATE_EXECUTE,
    PRESERVE_FOCUS,
    REPLY_KIND_EXECUTION_REQUIRED,
    RouterResultV2,
)
from vault_chat_focus import (
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
    FOCUS_KIND_DRAFT,
)
from vault_chat_policy_v2 import (
    OUTCOME_ALLOW,
    OUTCOME_CLARIFY,
    OUTCOME_REJECT,
    PolicyResultV2,
    REASON_ALLOWED,
    REASON_INSUFFICIENT_CONTEXT,
    REASON_LOW_CONFIDENCE,
    REASON_TARGET_KIND_MISMATCH,
)
from vault_chat_semantic_decision_v2 import (
    ACTION_SAVE,
    Authorization,
    FieldPatchItem,
    INTENT_CONFIRM_DRAFT,
    INTENT_FALLTHROUGH,
    make_fallthrough,
    SEMANTIC_DECISION_V2_SCHEMA_VERSION,
    SemanticDecisionV2,
    TARGET_KIND_DRAFT,
    TARGET_KIND_NONE,
    TargetRef,
)


TEST_FP_SECRET: bytes = b"test-shadow-fingerprint-secret-please-use-in-tests-only"


def _decision(intent=INTENT_CONFIRM_DRAFT, target_id="d-1",
              confidence=0.9) -> SemanticDecisionV2:
    return SemanticDecisionV2(
        schema_version=SEMANTIC_DECISION_V2_SCHEMA_VERSION,
        intent=intent,
        target=TargetRef(kind=TARGET_KIND_DRAFT, id=target_id),
        field_patch={}, requested_operations=(),
        authorization=Authorization(granted=False),
        confidence=confidence, reason="",
    )


def _policy(intent=INTENT_CONFIRM_DRAFT, outcome=OUTCOME_ALLOW,
            reason=REASON_ALLOWED,
            target_kind=TARGET_KIND_DRAFT, target_id="d-1"):
    if outcome == OUTCOME_ALLOW:
        allowed = True
    else:
        allowed = False
    return PolicyResultV2(
        allowed=allowed, outcome=outcome,
        normalized_intent=intent,
        target_kind=target_kind, target_id=target_id,
        authorization_to_mint=None, validated_patch=None,
        reason_code=reason,
    )


class _SecretFixtureMixin:
    """Every fingerprint-dependent test injects a test-only secret
    via configure_fingerprint_secret_for_tests and resets on
    tearDown so no test leaks state to any other."""

    def setUp(self):
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)

    def tearDown(self):
        sr.reset_fingerprint_secret_for_tests()


# =====================================================================
# Fingerprint (with test secret injected)
# =====================================================================

class FingerprintTest(_SecretFixtureMixin, unittest.TestCase):

    def test_fingerprint_stable_for_same_inputs(self):
        a = sr.fingerprint(intent="edit_draft",
                            target_kind="draft", target_id="d-1",
                            reason_code="ALLOWED", outcome="allow")
        b = sr.fingerprint(intent="edit_draft",
                            target_kind="draft", target_id="d-1",
                            reason_code="ALLOWED", outcome="allow")
        self.assertEqual(a, b)

    def test_fingerprint_differs_for_different_target_id(self):
        a = sr.fingerprint(intent="edit_draft",
                            target_kind="draft", target_id="d-1",
                            reason_code="ALLOWED", outcome="allow")
        b = sr.fingerprint(intent="edit_draft",
                            target_kind="draft", target_id="d-2",
                            reason_code="ALLOWED", outcome="allow")
        self.assertNotEqual(a, b)

    def test_fingerprint_length(self):
        fp = sr.fingerprint(intent="chat", target_kind="none",
                             target_id=None, reason_code="ALLOWED",
                             outcome="allow")
        # 16 hex chars = 64-bit truncation.
        self.assertEqual(len(fp), 16)
        int(fp, 16)

    def test_target_id_fingerprint_never_leaks_id(self):
        raw_id = "supersecret-target-abc-123"
        fp = sr.target_id_fingerprint("vault-x", raw_id)
        self.assertNotIn(raw_id, fp)
        self.assertEqual(len(fp), 16)


# =====================================================================
# Fingerprint-secret contract (commit 5a)
# =====================================================================

class FingerprintSecretContractTest(unittest.TestCase):

    def setUp(self):
        sr.reset_fingerprint_secret_for_tests()
        # Ensure env var is not set for these tests.
        self._prev_env = os.environ.pop(
            "VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET", None,
        )

    def tearDown(self):
        sr.reset_fingerprint_secret_for_tests()
        if self._prev_env is not None:
            os.environ[
                "VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"
            ] = self._prev_env

    def test_fingerprint_returns_sentinel_when_no_secret(self):
        # No env var, no test injection -> NOFP_SENTINEL.
        fp = sr.fingerprint(
            intent="chat", target_kind="none", target_id=None,
            reason_code="ALLOWED", outcome="allow",
        )
        self.assertEqual(fp, sr.NOFP_SENTINEL)

    def test_short_correlation_returns_sentinel_when_no_secret(self):
        val = sr._short_correlation("vault-abc")
        self.assertEqual(val, sr.NOFP_SENTINEL)

    def test_target_id_fingerprint_returns_sentinel_when_no_secret(self):
        val = sr.target_id_fingerprint("vault-abc", "target-xyz")
        self.assertEqual(val, sr.NOFP_SENTINEL)

    def test_env_var_too_short_treated_as_missing(self):
        os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"] = "tiny"
        try:
            fp = sr.fingerprint(
                intent="chat", target_kind="none", target_id=None,
                reason_code="ALLOWED", outcome="allow",
            )
            self.assertEqual(fp, sr.NOFP_SENTINEL)
        finally:
            del os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"]

    def test_env_var_with_valid_length_produces_real_hash(self):
        os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"] = (
            "sufficiently-long-secret-value-with-plenty-of-entropy"
        )
        try:
            fp = sr.fingerprint(
                intent="chat", target_kind="none", target_id=None,
                reason_code="ALLOWED", outcome="allow",
            )
            self.assertNotEqual(fp, sr.NOFP_SENTINEL)
            self.assertEqual(len(fp), 16)
            int(fp, 16)
        finally:
            del os.environ["VAULTAI_CHAT_BRAIN_V2_FINGERPRINT_SECRET"]

    def test_no_module_level_default_constant(self):
        # There must be no _DEFAULT_FINGERPRINT_SECRET-shaped
        # attribute on the module. Prevents accidental
        # reintroduction of a compile-time fallback.
        for attr in dir(sr):
            self.assertFalse(
                "DEFAULT" in attr and "SECRET" in attr,
                msg=(
                    f"module attribute {attr!r} looks like a "
                    "default fingerprint secret; commit 5a forbids "
                    "compile-time fallbacks"
                ),
            )

    def test_build_and_log_diff_emits_record_without_secret(self):
        # No secret configured. build_and_log_diff must still
        # produce a record (fingerprint-free) so shadow
        # observability degrades gracefully.
        rec = sr.build_and_log_diff(
            vault_id="v-abc", session_id="s-def", turn_id="t-ghi",
            v1_tool="fallthrough", v1_handled=False,
            v2_decision=_decision(target_id="d-1"),
            v2_policy=_policy(),
        )
        self.assertIsNotNone(rec)
        self.assertFalse(rec.fp_available)
        # All correlation fields are the sentinel, not truncations.
        self.assertEqual(rec.vault_hmac64, sr.NOFP_SENTINEL)
        self.assertEqual(rec.session_hmac64, sr.NOFP_SENTINEL)
        self.assertEqual(rec.turn_hmac64, sr.NOFP_SENTINEL)
        self.assertEqual(rec.v2_target_id_hmac64, sr.NOFP_SENTINEL)
        self.assertEqual(rec.v2_fingerprint, sr.NOFP_SENTINEL)
        # Log line marks unavailability explicitly.
        line = rec.to_log_line()
        self.assertIn("fp_available=0", line)


# =====================================================================
# Category classifier
# =====================================================================

class ClassifyMatchTest(_SecretFixtureMixin, unittest.TestCase):

    def test_v2_error_becomes_validation_error(self):
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="fallthrough", v1_handled=False,
            v2_decision=make_fallthrough(error="bad_json"),
            v2_policy=None,
        )
        self.assertEqual(rec.match, sr.MATCH_V2_VALIDATION_ERROR)

    def test_v1_fallthrough_and_v2_fallthrough_equivalent(self):
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="fallthrough", v1_handled=False,
            v2_decision=_decision(intent=INTENT_FALLTHROUGH),
            v2_policy=_policy(intent=INTENT_FALLTHROUGH,
                              outcome=OUTCOME_ALLOW,
                              reason="FALLTHROUGH"),
        )
        self.assertEqual(rec.match, sr.MATCH_INTENT_EQUIVALENT)

    def test_v1_confirm_delete_and_v2_confirm_pending_action_equivalent(self):
        d = _decision(intent="confirm_pending_action")
        p = _policy(intent="confirm_pending_action",
                    outcome=OUTCOME_ALLOW, reason=REASON_ALLOWED)
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="confirm_pending_delete", v1_handled=True,
            v2_decision=d, v2_policy=p,
        )
        self.assertEqual(rec.match, sr.MATCH_INTENT_EQUIVALENT)

    def test_insufficient_shadow_context_for_focus_reasons(self):
        d = _decision(intent=INTENT_CONFIRM_DRAFT)
        p = _policy(outcome=OUTCOME_CLARIFY,
                    reason=REASON_INSUFFICIENT_CONTEXT)
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="confirm_pending_save", v1_handled=True,
            v2_decision=d, v2_policy=p,
        )
        self.assertEqual(rec.match, sr.MATCH_INSUFFICIENT_CONTEXT)

    def test_different_semantics_when_neither_maps(self):
        d = _decision(intent=INTENT_CONFIRM_DRAFT)
        p = _policy(outcome=OUTCOME_REJECT,
                    reason=REASON_TARGET_KIND_MISMATCH)
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="cancel_pending_delete", v1_handled=True,
            v2_decision=d, v2_policy=p,
        )
        self.assertEqual(rec.match, sr.MATCH_DIFFERENT_SEMANTICS)


# =====================================================================
# Router summary view (commit 5a)
# =====================================================================

class RouterViewSummaryTest(_SecretFixtureMixin, unittest.TestCase):

    def _plan(self):
        return ExecutionPlanV2(
            action_kind=ACTION_KIND_CONFIRM_SAVE,
            target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            authorization_intent=None, validated_patch=None,
            success_focus_update=FocusUpdate(
                action=FOCUS_ACTION_CLEAR_IF_MATCHES,
                kind=FOCUS_KIND_DRAFT, id="d-1",
            ),
            failure_focus_update=FocusUpdate(
                action=FOCUS_ACTION_SET,
                kind=FOCUS_KIND_DRAFT, id="d-1",
                assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            ),
            success_reply_key="save_draft",
            failure_reply_key="save_draft",
        )

    def test_router_view_carries_closed_set_fields_only(self):
        rr = RouterResultV2(
            handled=True,
            reply_kind=REPLY_KIND_EXECUTION_REQUIRED,
            reply_text="",
            focus_update=PRESERVE_FOCUS,
            execution_plan=self._plan(),
            next_state=NEXT_STATE_EXECUTE,
            normalized_intent="confirm_draft",
            reason_code=REASON_ALLOWED,
        )
        view = sr.ShadowRouterView.from_router(rr)
        self.assertTrue(view.handled)
        self.assertEqual(view.reply_kind, REPLY_KIND_EXECUTION_REQUIRED)
        self.assertEqual(view.next_state, NEXT_STATE_EXECUTE)
        self.assertEqual(view.action_kind, ACTION_KIND_CONFIRM_SAVE)
        # ShadowRouterView is a frozen dataclass with only closed-set
        # fields. Confirm no reply_text / focus / diagnostic sneaks in.
        for attr in (
            "reply_text", "focus_update", "diagnostic",
            "execution_plan", "target_id",
        ):
            self.assertFalse(
                hasattr(view, attr),
                msg=f"ShadowRouterView must not expose {attr!r}",
            )

    def test_build_and_log_diff_includes_router_view_when_supplied(self):
        rr = RouterResultV2(
            handled=True,
            reply_kind=REPLY_KIND_EXECUTION_REQUIRED,
            reply_text="",
            focus_update=PRESERVE_FOCUS,
            execution_plan=self._plan(),
            next_state=NEXT_STATE_EXECUTE,
            normalized_intent="confirm_draft",
            reason_code=REASON_ALLOWED,
        )
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="confirm_pending_save", v1_handled=True,
            v2_decision=_decision(),
            v2_policy=_policy(),
            v2_router=rr,
        )
        self.assertIsNotNone(rec.router_view)
        self.assertEqual(
            rec.router_view.action_kind, ACTION_KIND_CONFIRM_SAVE,
        )
        line = rec.to_log_line()
        self.assertIn(
            f"v2_router_action_kind={ACTION_KIND_CONFIRM_SAVE}", line,
        )
        self.assertIn("v2_router_handled=1", line)
        self.assertIn(f"v2_router_next_state={NEXT_STATE_EXECUTE}", line)


# =====================================================================
# No sensitive data in log lines
# =====================================================================

class NoSensitiveDataInLogLineTest(_SecretFixtureMixin, unittest.TestCase):
    """The log line must never contain raw vault/session/turn ids,
    the raw target id, the LLM's reason text, the policy's
    diagnostic text, usernames, email addresses, target labels,
    tokens, ciphertext, authorization ids, or Redis keys."""

    def test_raw_ids_never_in_log_line(self):
        rec = sr.build_and_log_diff(
            vault_id="RAW_VAULT_ABC123",
            session_id="RAW_SESSION_XYZ",
            turn_id="RAW_TURN_QWERTY",
            v1_tool="confirm_pending_save", v1_handled=True,
            v2_decision=_decision(target_id="RAW_TARGET_HIDDEN"),
            v2_policy=_policy(reason=REASON_LOW_CONFIDENCE,
                              outcome=OUTCOME_CLARIFY),
        )
        line = rec.to_log_line()
        self.assertNotIn("RAW_VAULT_ABC123", line)
        self.assertNotIn("RAW_SESSION_XYZ", line)
        self.assertNotIn("RAW_TURN_QWERTY", line)
        self.assertNotIn("RAW_TARGET_HIDDEN", line)

    def test_log_line_uses_hmac64_correlations(self):
        rec = sr.build_and_log_diff(
            vault_id="v-abc", session_id="s-def", turn_id="t-ghi",
            v1_tool="fallthrough", v1_handled=False,
            v2_decision=_decision(target_id="d-1"),
            v2_policy=_policy(outcome=OUTCOME_ALLOW),
        )
        line = rec.to_log_line()
        self.assertIn("vault=", line)
        self.assertIn("sess=", line)
        self.assertIn("turn=", line)
        self.assertIn("v2_target_hmac64=", line)
        self.assertIn("v2_fp=", line)

    def test_confidence_appears_as_bucket_not_float(self):
        rec = sr.build_and_log_diff(
            vault_id="v", session_id="s", turn_id="t",
            v1_tool="fallthrough", v1_handled=False,
            v2_decision=_decision(confidence=0.87),
            v2_policy=_policy(),
        )
        line = rec.to_log_line()
        self.assertIn("v2_conf_bucket=", line)
        self.assertNotIn("0.87", line)


if __name__ == "__main__":
    unittest.main()
