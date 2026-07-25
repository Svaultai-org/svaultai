"""Tests for the shadow-mode diff logger."""

from __future__ import annotations

import unittest

import vault_chat_shadow_recorder_v2 as sr
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


class FingerprintTest(unittest.TestCase):

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
        self.assertEqual(len(fp), 16)
        int(fp, 16)  # hex-parseable

    def test_target_id_fingerprint_never_leaks_id(self):
        raw_id = "supersecret-target-abc-123"
        fp = sr.target_id_fingerprint("vault-x", raw_id)
        self.assertNotIn(raw_id, fp)
        self.assertEqual(len(fp), 16)


class ClassifyMatchTest(unittest.TestCase):

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


class NoSensitiveDataInLogLineTest(unittest.TestCase):
    """The log line must never contain raw vault/session/turn ids,
    the raw target id, the LLM's reason text, or the policy's
    diagnostic text."""

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

    def test_log_line_uses_hmac8_correlations(self):
        rec = sr.build_and_log_diff(
            vault_id="v-abc", session_id="s-def", turn_id="t-ghi",
            v1_tool="fallthrough", v1_handled=False,
            v2_decision=_decision(target_id="d-1"),
            v2_policy=_policy(outcome=OUTCOME_ALLOW),
        )
        line = rec.to_log_line()
        # correlation tokens present
        self.assertIn("vault=", line)
        self.assertIn("sess=", line)
        self.assertIn("turn=", line)
        self.assertIn("v2_target_hmac8=", line)
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
