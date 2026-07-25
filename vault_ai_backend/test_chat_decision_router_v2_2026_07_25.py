"""Tests for vault_chat_decision_router_v2 — the pure orchestrator.

Covers the mandatory matrix from the commit-4 review:

    * confirm_draft → produces AuthorizationIntent
    * edit_draft   → produces validated draft presentation (no auth)
    * clarify      → produces clarification reply
    * fallthrough  → handled=False
    * reject       → deterministic rejection reply
    * allow        → handled=True
    * focus update emitted (all confirm/cancel paths)
    * focus preserved (edit/create/clarify — except EXPIRED_FOCUS)
    * focus cleared_if_matches (confirm + cancel)
    * authorization_intent preserved
    * authorization_intent omitted for edits
    * reply text independent of diagnostic text
    * router performs zero backend writes

Plus:

    * PolicyResult(ALLOW)   → RouterResult
    * PolicyResult(CLARIFY) → RouterResult
    * PolicyResult(REJECT)  → RouterResult

The tests do NOT involve any production routing, semantic decider,
Redis, or executor calls.
"""

from __future__ import annotations

import unittest
from types import MappingProxyType
from typing import Optional

import vault_chat_decision_router_v2 as vr
import vault_chat_policy_v2 as vp

from vault_chat_focus import (
    FOCUS_KIND_DRAFT,
    FOCUS_KIND_PENDING_ACTION,
)
from vault_chat_semantic_decision_v2 import (
    ACTION_DELETE,
    ACTION_SAVE,
    ACTION_SAVE_ATTACHMENT,
    Authorization,
    AuthorizationScope,
    FieldPatchItem,
    INTENT_ANSWER_QUESTION,
    INTENT_ASK_CLARIFICATION,
    INTENT_CANCEL_DRAFT,
    INTENT_CANCEL_PENDING_ACTION,
    INTENT_CHAT,
    INTENT_CONFIRM_DRAFT,
    INTENT_CONFIRM_PENDING_ACTION,
    INTENT_CREATE_DRAFT,
    INTENT_EDIT_DRAFT,
    INTENT_FALLTHROUGH,
    OP_REPLACE,
    SEMANTIC_DECISION_V2_SCHEMA_VERSION,
    SemanticDecisionV2,
    TARGET_KIND_DRAFT,
    TARGET_KIND_NONE,
    TARGET_KIND_PENDING_ACTION,
    TargetRef,
)


# =====================================================================
# Helpers
# =====================================================================

def _policy_allow(
    *, intent, target_kind=None, target_id=None,
    auth=None, patch=None, reason=vp.REASON_ALLOWED,
    diagnostic="",
) -> vp.PolicyResultV2:
    return vp.PolicyResultV2(
        allowed=True, outcome=vp.OUTCOME_ALLOW,
        normalized_intent=intent,
        target_kind=target_kind, target_id=target_id,
        authorization_to_mint=auth,
        validated_patch=patch,
        reason_code=reason,
        diagnostic=diagnostic,
    )


def _policy_clarify(*, intent, reason, target_kind=None, target_id=None,
                    diagnostic="") -> vp.PolicyResultV2:
    return vp.PolicyResultV2(
        allowed=False, outcome=vp.OUTCOME_CLARIFY,
        normalized_intent=intent,
        target_kind=target_kind, target_id=target_id,
        authorization_to_mint=None,
        validated_patch=None,
        reason_code=reason,
        diagnostic=diagnostic,
    )


def _policy_reject(*, intent, reason, target_kind=None, target_id=None,
                   diagnostic="") -> vp.PolicyResultV2:
    return vp.PolicyResultV2(
        allowed=False, outcome=vp.OUTCOME_REJECT,
        normalized_intent=intent,
        target_kind=target_kind, target_id=target_id,
        authorization_to_mint=None,
        validated_patch=None,
        reason_code=reason,
        diagnostic=diagnostic,
    )


def _decision(intent=INTENT_FALLTHROUGH) -> SemanticDecisionV2:
    return SemanticDecisionV2(
        schema_version=SEMANTIC_DECISION_V2_SCHEMA_VERSION,
        intent=intent,
        target=TargetRef(kind=TARGET_KIND_NONE, id=None),
        field_patch={},
        requested_operations=(),
        authorization=Authorization(granted=False),
        confidence=0.9,
        reason="",
    )


def _auth(target_kind=TARGET_KIND_DRAFT, target_id="d-1",
          action=ACTION_SAVE, confidence=0.9) -> vp.AuthorizationIntent:
    return vp.AuthorizationIntent(
        target_kind=target_kind, target_id=target_id,
        action=action,
        authorizing_user_turn_id="u-1",
        preceding_assistant_turn_id="a-1",
        confidence=confidence,
    )


# =====================================================================
# Fallthrough paths
# =====================================================================

class FallthroughTest(unittest.TestCase):

    def test_fallthrough_intent_returns_unhandled(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_FALLTHROUGH,
                reason=vp.REASON_FALLTHROUGH,
            ),
            decision=_decision(INTENT_FALLTHROUGH),
        )
        self.assertFalse(r.handled)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_NONE)
        self.assertEqual(r.reply_text, "")
        self.assertEqual(r.next_state, vr.NEXT_STATE_FALLTHROUGH)
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)
        self.assertIsNone(r.authorization_intent)
        self.assertIsNone(r.validated_patch)

    def test_chat_intent_falls_through_in_phase_1(self):
        r = vr.route_v2(
            policy_result=_policy_allow(intent=INTENT_CHAT),
            decision=_decision(INTENT_CHAT),
        )
        self.assertFalse(r.handled)
        self.assertEqual(r.next_state, vr.NEXT_STATE_FALLTHROUGH)

    def test_answer_question_falls_through_in_phase_1(self):
        r = vr.route_v2(
            policy_result=_policy_allow(intent=INTENT_ANSWER_QUESTION),
            decision=_decision(INTENT_ANSWER_QUESTION),
        )
        self.assertFalse(r.handled)
        self.assertEqual(r.next_state, vr.NEXT_STATE_FALLTHROUGH)


# =====================================================================
# Clarification path
# =====================================================================

class ClarificationTest(unittest.TestCase):

    def test_clarify_produces_clarification_reply(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_INSUFFICIENT_CONTEXT,
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertTrue(r.handled)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_CLARIFICATION)
        self.assertTrue(r.reply_text)
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)
        self.assertIsNone(r.authorization_intent)
        self.assertEqual(r.next_state, vr.NEXT_STATE_AWAIT_USER)

    def test_expired_focus_clarify_clears_focus(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_EXPIRED_FOCUS,
                target_kind=TARGET_KIND_DRAFT,
                target_id="d-1",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_CLEAR)

    def test_ask_clarification_always_clarifies_even_on_allow(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_ASK_CLARIFICATION,
                reason=vp.REASON_ALLOWED,
            ),
            decision=_decision(INTENT_ASK_CLARIFICATION),
        )
        self.assertTrue(r.handled)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_CLARIFICATION)
        self.assertTrue(r.reply_text)

    def test_clarify_reply_per_reason_code(self):
        # Every documented reason has a distinct, non-empty template
        # (or falls back to the generic).
        for reason in (
            vp.REASON_INSUFFICIENT_CONTEXT,
            vp.REASON_EXPIRED_FOCUS,
            vp.REASON_TARGET_NOT_FOCUSED,
            vp.REASON_AMBIGUOUS_TARGET,
            vp.REASON_LOW_CONFIDENCE,
            vp.REASON_TARGET_EXPIRED,
            vp.REASON_TARGET_NOT_FOUND,
            vp.REASON_AUTH_MISSING_GRANT,
        ):
            with self.subTest(reason=reason):
                r = vr.route_v2(
                    policy_result=_policy_clarify(
                        intent=INTENT_CONFIRM_DRAFT,
                        reason=reason,
                    ),
                    decision=_decision(INTENT_CONFIRM_DRAFT),
                )
                self.assertTrue(r.reply_text.strip())


# =====================================================================
# Reject path
# =====================================================================

class RejectTest(unittest.TestCase):

    def test_reject_produces_rejection_reply(self):
        r = vr.route_v2(
            policy_result=_policy_reject(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_AUTH_SCOPE_MISMATCH,
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertTrue(r.handled)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_REJECTION)
        self.assertTrue(r.reply_text)
        self.assertEqual(r.next_state, vr.NEXT_STATE_AWAIT_USER)
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)
        self.assertIsNone(r.authorization_intent)

    def test_wrong_vault_reject_reply(self):
        r = vr.route_v2(
            policy_result=_policy_reject(
                intent=INTENT_CANCEL_DRAFT,
                reason=vp.REASON_WRONG_VAULT,
            ),
            decision=_decision(INTENT_CANCEL_DRAFT),
        )
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_REJECTION)
        self.assertIn("can't", r.reply_text.lower())


# =====================================================================
# Allow — confirm draft
# =====================================================================

class ConfirmDraftAllowTest(unittest.TestCase):

    def _confirm(self, target_id="d-1"):
        return vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT,
                target_id=target_id,
                auth=_auth(TARGET_KIND_DRAFT, target_id, ACTION_SAVE),
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )

    def test_produces_authorization_intent(self):
        r = self._confirm("d-1")
        self.assertTrue(r.handled)
        self.assertIsNotNone(r.authorization_intent)
        self.assertEqual(r.authorization_intent.target_id, "d-1")
        self.assertEqual(r.authorization_intent.action, ACTION_SAVE)

    def test_reply_kind_and_text(self):
        r = self._confirm("d-1")
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_CONFIRMATION_ACK)
        self.assertTrue(r.reply_text)

    def test_focus_clears_if_matches(self):
        r = self._confirm("d-1")
        self.assertEqual(
            r.focus_update.action, vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
        )
        self.assertEqual(r.focus_update.kind, FOCUS_KIND_DRAFT)
        self.assertEqual(r.focus_update.id, "d-1")

    def test_next_state_is_execute(self):
        r = self._confirm("d-1")
        self.assertEqual(r.next_state, vr.NEXT_STATE_EXECUTE)


# =====================================================================
# Allow — confirm pending action
# =====================================================================

class ConfirmPendingAllowTest(unittest.TestCase):

    def _confirm_pending(self, action):
        return vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CONFIRM_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id="p-1",
                auth=_auth(TARGET_KIND_PENDING_ACTION, "p-1", action),
            ),
            decision=_decision(INTENT_CONFIRM_PENDING_ACTION),
        )

    def test_save_action(self):
        r = self._confirm_pending(ACTION_SAVE)
        self.assertEqual(r.authorization_intent.action, ACTION_SAVE)
        self.assertTrue(r.reply_text)

    def test_delete_action(self):
        r = self._confirm_pending(ACTION_DELETE)
        self.assertEqual(r.authorization_intent.action, ACTION_DELETE)
        self.assertIn("delet", r.reply_text.lower())

    def test_save_attachment_action(self):
        r = self._confirm_pending(ACTION_SAVE_ATTACHMENT)
        self.assertEqual(
            r.authorization_intent.action, ACTION_SAVE_ATTACHMENT,
        )
        self.assertIn("file", r.reply_text.lower())

    def test_focus_clears_if_matches_pending_kind(self):
        r = self._confirm_pending(ACTION_DELETE)
        self.assertEqual(
            r.focus_update.action, vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
        )
        self.assertEqual(r.focus_update.kind, FOCUS_KIND_PENDING_ACTION)


# =====================================================================
# Allow — cancel
# =====================================================================

class CancelAllowTest(unittest.TestCase):

    def test_cancel_draft_no_authorization(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CANCEL_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            ),
            decision=_decision(INTENT_CANCEL_DRAFT),
        )
        self.assertIsNone(r.authorization_intent)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_CANCELLATION_ACK)
        self.assertEqual(r.next_state, vr.NEXT_STATE_APPLY_CANCEL)
        self.assertEqual(
            r.focus_update.action, vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
        )
        self.assertEqual(r.focus_update.kind, FOCUS_KIND_DRAFT)

    def test_cancel_pending_no_authorization(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CANCEL_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION, target_id="p-1",
            ),
            decision=_decision(INTENT_CANCEL_PENDING_ACTION),
        )
        self.assertIsNone(r.authorization_intent)
        self.assertEqual(
            r.focus_update.action, vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
        )
        self.assertEqual(r.focus_update.kind, FOCUS_KIND_PENDING_ACTION)


# =====================================================================
# Allow — edit / create draft
# =====================================================================

class EditCreateAllowTest(unittest.TestCase):

    def _edit(self, patch):
        return vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                patch=patch,
            ),
            decision=_decision(INTENT_EDIT_DRAFT),
        )

    def _create(self, patch):
        return vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CREATE_DRAFT,
                target_kind=None, target_id=None,
                patch=patch,
            ),
            decision=_decision(INTENT_CREATE_DRAFT),
        )

    def test_edit_produces_validated_patch(self):
        patch = {"username": FieldPatchItem(
            op=OP_REPLACE, value="alice@example.org",
        )}
        r = self._edit(patch)
        self.assertTrue(r.handled)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_DRAFT_PRESENTATION)
        self.assertIsNotNone(r.validated_patch)
        self.assertIn("username", r.validated_patch)
        self.assertEqual(r.next_state, vr.NEXT_STATE_APPLY_PATCH)

    def test_edit_produces_no_authorization_intent(self):
        r = self._edit({"username": FieldPatchItem(
            op=OP_REPLACE, value="x@y.z",
        )})
        self.assertIsNone(r.authorization_intent)

    def test_edit_preserves_focus(self):
        r = self._edit({"username": FieldPatchItem(
            op=OP_REPLACE, value="x@y.z",
        )})
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_create_produces_validated_patch(self):
        patch = {"service": FieldPatchItem(
            op=OP_REPLACE, value="Netflix",
        )}
        r = self._create(patch)
        self.assertTrue(r.handled)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_DRAFT_PRESENTATION)
        self.assertEqual(r.next_state, vr.NEXT_STATE_APPLY_CREATE)
        self.assertIn("service", r.validated_patch)

    def test_create_preserves_focus(self):
        # Integration stamps focus after minting the fresh draft id.
        r = self._create({"service": FieldPatchItem(
            op=OP_REPLACE, value="Netflix",
        )})
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)


# =====================================================================
# Reply text independence + purity
# =====================================================================

class ReplyIndependenceTest(unittest.TestCase):
    """Reply text depends only on (outcome, intent, reason_code)
    plus (for confirms) the auth action. Diagnostic is dev-facing
    only and must NOT influence reply_text.
    """

    def test_reply_text_ignores_diagnostic_on_clarify(self):
        r1 = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_INSUFFICIENT_CONTEXT,
                diagnostic="",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        r2 = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_INSUFFICIENT_CONTEXT,
                diagnostic="wildly different internal note about the model's plan",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r1.reply_text, r2.reply_text)

    def test_reply_text_ignores_diagnostic_on_reject(self):
        r1 = vr.route_v2(
            policy_result=_policy_reject(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_AUTH_SCOPE_MISMATCH,
                diagnostic="",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        r2 = vr.route_v2(
            policy_result=_policy_reject(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_AUTH_SCOPE_MISMATCH,
                diagnostic="target_id was d-9 but scope said d-1",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r1.reply_text, r2.reply_text)


class RouterPurityTest(unittest.TestCase):

    def test_router_performs_zero_backend_writes(self):
        # Trap the shared-state backend; any write raises.
        import vault_chat_state_store as st

        class TrapBackend(st.SharedStateBackend):
            def get(self, key): return None
            def set(self, key, value, ttl_seconds):
                raise AssertionError(f"router wrote to key={key!r}")
            def delete(self, key):
                raise AssertionError(f"router deleted key={key!r}")
            def sadd(self, key, member, ttl_seconds):
                raise AssertionError("router sadd")
            def smembers(self, key): return set()
            def srem(self, key, member):
                raise AssertionError("router srem")
            def sclear(self, key):
                raise AssertionError("router sclear")
            def health(self): return True

        st.install_backend_for_tests(TrapBackend())
        try:
            # Route several representative outcomes.
            for pr in (
                _policy_allow(
                    intent=INTENT_CONFIRM_DRAFT,
                    target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                    auth=_auth(),
                ),
                _policy_allow(
                    intent=INTENT_EDIT_DRAFT,
                    target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                    patch={"username": FieldPatchItem(
                        op=OP_REPLACE, value="x@y.z",
                    )},
                ),
                _policy_clarify(
                    intent=INTENT_CONFIRM_DRAFT,
                    reason=vp.REASON_INSUFFICIENT_CONTEXT,
                ),
                _policy_clarify(
                    intent=INTENT_CONFIRM_DRAFT,
                    reason=vp.REASON_EXPIRED_FOCUS,
                ),
                _policy_reject(
                    intent=INTENT_CONFIRM_DRAFT,
                    reason=vp.REASON_AUTH_ACTION_MISMATCH,
                ),
            ):
                vr.route_v2(
                    policy_result=pr,
                    decision=_decision(pr.normalized_intent),
                )
        finally:
            st.reset_chat_state_backend_for_tests()


# =====================================================================
# Policy → Router shape (per your explicit test list)
# =====================================================================

class PolicyToRouterShapeTest(unittest.TestCase):

    def test_policy_allow_produces_router_result(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                auth=_auth(),
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertIsInstance(r, vr.RouterResultV2)
        self.assertTrue(r.handled)

    def test_policy_clarify_produces_router_result(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_LOW_CONFIDENCE,
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertIsInstance(r, vr.RouterResultV2)
        self.assertTrue(r.handled)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_CLARIFICATION)

    def test_policy_reject_produces_router_result(self):
        r = vr.route_v2(
            policy_result=_policy_reject(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_TARGET_KIND_MISMATCH,
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertIsInstance(r, vr.RouterResultV2)
        self.assertTrue(r.handled)
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_REJECTION)


# =====================================================================
# FocusUpdate / RouterResultV2 shape invariants
# =====================================================================

class FocusUpdateShapeTest(unittest.TestCase):

    def test_set_requires_kind_id_act(self):
        with self.assertRaises(ValueError):
            vr.FocusUpdate(action=vr.FOCUS_ACTION_SET)
        with self.assertRaises(ValueError):
            vr.FocusUpdate(
                action=vr.FOCUS_ACTION_SET,
                kind=FOCUS_KIND_DRAFT, id="d-1",
                # missing assistant_act
            )

    def test_clear_if_matches_requires_kind_id(self):
        with self.assertRaises(ValueError):
            vr.FocusUpdate(action=vr.FOCUS_ACTION_CLEAR_IF_MATCHES)

    def test_preserve_forbids_kind_id_act(self):
        with self.assertRaises(ValueError):
            vr.FocusUpdate(
                action=vr.FOCUS_ACTION_PRESERVE, kind=FOCUS_KIND_DRAFT,
            )

    def test_clear_forbids_kind_id_act(self):
        with self.assertRaises(ValueError):
            vr.FocusUpdate(
                action=vr.FOCUS_ACTION_CLEAR, id="d-1",
            )


class RouterResultShapeTest(unittest.TestCase):

    def test_handled_false_requires_fallthrough_next_state(self):
        with self.assertRaises(ValueError):
            vr.RouterResultV2(
                handled=False, reply_kind=vr.REPLY_KIND_NONE,
                reply_text="",
                focus_update=vr.PRESERVE_FOCUS,
                authorization_intent=None, validated_patch=None,
                next_state=vr.NEXT_STATE_EXECUTE,   # wrong
                normalized_intent=INTENT_CHAT,
                reason_code=vp.REASON_ALLOWED,
            )

    def test_handled_true_forbids_fallthrough_next_state(self):
        with self.assertRaises(ValueError):
            vr.RouterResultV2(
                handled=True, reply_kind=vr.REPLY_KIND_CHAT,
                reply_text="hi",
                focus_update=vr.PRESERVE_FOCUS,
                authorization_intent=None, validated_patch=None,
                next_state=vr.NEXT_STATE_FALLTHROUGH,
                normalized_intent=INTENT_CHAT,
                reason_code=vp.REASON_ALLOWED,
            )

    def test_unknown_reply_kind_rejected(self):
        with self.assertRaises(ValueError):
            vr.RouterResultV2(
                handled=True, reply_kind="mystery",
                reply_text="", focus_update=vr.PRESERVE_FOCUS,
                authorization_intent=None, validated_patch=None,
                next_state=vr.NEXT_STATE_AWAIT_USER,
                normalized_intent=INTENT_CHAT,
                reason_code=vp.REASON_ALLOWED,
            )


if __name__ == "__main__":
    unittest.main()
