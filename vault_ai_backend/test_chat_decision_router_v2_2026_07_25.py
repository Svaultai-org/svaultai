"""Tests for vault_chat_decision_router_v2 — the pure orchestrator
with staged focus, deferred reply templates, and an
ExecutionPlanV2 for the execute path.

Covers the mandatory matrix from commit-4 review AND the five
corrections from the commit-4a review:

    Correction 1 — router owns SET focus intent
        * draft presentation emits SET focus intent
        * target-specific clarification emits SET(asked_clarification)
        * ambiguous clarification never focuses an arbitrary candidate
        * target-not-found clears matching stale focus
    Correction 2 — clarification focus rules per reason_code
    Correction 3 — confirmation does not clear focus before execution
        * confirmation does not request immediate focus clearing
        * confirmation success plan clears focus after success
        * confirmation failure plan preserves or resets target focus
    Correction 4 — typed ExecutionPlanV2
        * every allow path produces an ExecutionPlanV2
        * plan carries success/failure focus and reply keys
    Correction 5 — no premature success replies
        * execution-required result contains empty reply_text
        * integration is responsible only for applying, not deciding, focus
    Router purity
        * router performs zero backend writes
"""

from __future__ import annotations

import unittest
from types import MappingProxyType
from typing import Optional

import vault_chat_decision_router_v2 as vr
import vault_chat_policy_v2 as vp

from vault_chat_focus import (
    FOCUS_ACT_ASKED_CLARIFICATION,
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
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
        self.assertIsNone(r.execution_plan)

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


# =====================================================================
# Correction 2 — clarification focus per reason_code
# =====================================================================

class ClarifyFocusRulesTest(unittest.TestCase):

    def test_insufficient_context_preserves_focus(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_INSUFFICIENT_CONTEXT,
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_expired_focus_clarify_clears_focus(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_EXPIRED_FOCUS,
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_CLEAR)

    def test_ambiguous_target_clears_focus_never_picks_arbitrary(self):
        # Even if the policy names a target_id (one of several
        # candidates), the router does NOT SET focus to it. Router
        # CLEARs.
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_AMBIGUOUS_TARGET,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_CLEAR)

    def test_target_not_found_clears_if_matches_stale_focus(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_EDIT_DRAFT,
                reason=vp.REASON_TARGET_NOT_FOUND,
                target_kind=TARGET_KIND_DRAFT, target_id="d-missing",
            ),
            decision=_decision(INTENT_EDIT_DRAFT),
        )
        self.assertEqual(
            r.focus_update.action, vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
        )
        self.assertEqual(r.focus_update.kind, FOCUS_KIND_DRAFT)
        self.assertEqual(r.focus_update.id, "d-missing")

    def test_target_not_found_without_target_id_preserves(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_EDIT_DRAFT,
                reason=vp.REASON_TARGET_NOT_FOUND,
                target_kind=None, target_id=None,
            ),
            decision=_decision(INTENT_EDIT_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_target_expired_clears_if_matches(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_TARGET_EXPIRED,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(
            r.focus_update.action, vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
        )

    def test_target_not_focused_sets_asked_clarification(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_TARGET_NOT_FOCUSED,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_SET)
        self.assertEqual(r.focus_update.kind, FOCUS_KIND_DRAFT)
        self.assertEqual(r.focus_update.id, "d-1")
        self.assertEqual(
            r.focus_update.assistant_act, FOCUS_ACT_ASKED_CLARIFICATION,
        )

    def test_low_confidence_preserves_focus(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_LOW_CONFIDENCE,
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_auth_missing_grant_preserves(self):
        r = vr.route_v2(
            policy_result=_policy_clarify(
                intent=INTENT_CONFIRM_DRAFT,
                reason=vp.REASON_AUTH_MISSING_GRANT,
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_ask_clarification_with_specific_target_sets(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_ASK_CLARIFICATION,
                target_kind=TARGET_KIND_DRAFT, target_id="d-2",
            ),
            decision=_decision(INTENT_ASK_CLARIFICATION),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_SET)
        self.assertEqual(r.focus_update.id, "d-2")
        self.assertEqual(
            r.focus_update.assistant_act, FOCUS_ACT_ASKED_CLARIFICATION,
        )

    def test_ask_clarification_without_target_preserves(self):
        r = vr.route_v2(
            policy_result=_policy_allow(intent=INTENT_ASK_CLARIFICATION),
            decision=_decision(INTENT_ASK_CLARIFICATION),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)


class ClarifyReplyTemplatesTest(unittest.TestCase):

    def test_every_documented_reason_has_nonempty_template(self):
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
                        target_kind=TARGET_KIND_DRAFT, target_id="d-1",
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
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)
        self.assertIsNone(r.execution_plan)


# =====================================================================
# Correction 3 + 4 — confirm draft uses ExecutionPlan with staged focus
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

    def test_immediate_focus_is_preserve_not_clear(self):
        # Correction 3: don't clear focus before execution.
        r = self._confirm("d-1")
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_execution_plan_success_clears_focus(self):
        r = self._confirm("d-1")
        self.assertIsNotNone(r.execution_plan)
        self.assertEqual(
            r.execution_plan.success_focus_update.action,
            vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
        )
        self.assertEqual(
            r.execution_plan.success_focus_update.kind, FOCUS_KIND_DRAFT,
        )
        self.assertEqual(
            r.execution_plan.success_focus_update.id, "d-1",
        )

    def test_execution_plan_failure_restores_target_focus(self):
        r = self._confirm("d-1")
        self.assertEqual(
            r.execution_plan.failure_focus_update.action,
            vr.FOCUS_ACTION_SET,
        )
        self.assertEqual(
            r.execution_plan.failure_focus_update.id, "d-1",
        )
        self.assertEqual(
            r.execution_plan.failure_focus_update.assistant_act,
            FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        )

    def test_execution_plan_carries_authorization_intent(self):
        r = self._confirm("d-1")
        self.assertIsNotNone(r.execution_plan.authorization_intent)
        self.assertEqual(
            r.execution_plan.authorization_intent.target_id, "d-1",
        )
        self.assertEqual(
            r.execution_plan.authorization_intent.action, ACTION_SAVE,
        )

    def test_reply_kind_is_execution_required(self):
        # Correction 5: no premature success text.
        r = self._confirm("d-1")
        self.assertEqual(
            r.reply_kind, vr.REPLY_KIND_EXECUTION_REQUIRED,
        )
        self.assertEqual(r.reply_text, "")

    def test_execution_plan_carries_deferred_reply_keys(self):
        r = self._confirm("d-1")
        self.assertIn(
            r.execution_plan.success_reply_key, vr.REPLY_KEYS,
        )
        self.assertIn(
            r.execution_plan.failure_reply_key, vr.REPLY_KEYS,
        )

    def test_next_state_is_execute(self):
        r = self._confirm("d-1")
        self.assertEqual(r.next_state, vr.NEXT_STATE_EXECUTE)


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

    def test_immediate_focus_is_preserve(self):
        r = self._confirm_pending(ACTION_DELETE)
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_reply_kind_execution_required(self):
        r = self._confirm_pending(ACTION_SAVE)
        self.assertEqual(
            r.reply_kind, vr.REPLY_KIND_EXECUTION_REQUIRED,
        )
        self.assertEqual(r.reply_text, "")

    def test_delete_action_kind_and_reply_key(self):
        r = self._confirm_pending(ACTION_DELETE)
        self.assertEqual(
            r.execution_plan.action_kind, vr.ACTION_KIND_CONFIRM_DELETE,
        )
        # Deferred success reply is "Deleted." not present in
        # immediate reply.
        self.assertNotIn("delet", r.reply_text.lower())
        success_reply = vr.get_success_reply(
            r.execution_plan.success_reply_key,
        )
        self.assertIn("delet", success_reply.lower())

    def test_save_attachment_action_kind(self):
        r = self._confirm_pending(ACTION_SAVE_ATTACHMENT)
        self.assertEqual(
            r.execution_plan.action_kind,
            vr.ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
        )

    def test_success_focus_clears_pending_kind(self):
        r = self._confirm_pending(ACTION_DELETE)
        self.assertEqual(
            r.execution_plan.success_focus_update.kind,
            FOCUS_KIND_PENDING_ACTION,
        )


# =====================================================================
# Cancel allow
# =====================================================================

class CancelAllowTest(unittest.TestCase):

    def test_cancel_draft_immediate_focus_preserve(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CANCEL_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            ),
            decision=_decision(INTENT_CANCEL_DRAFT),
        )
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_cancel_success_clears_focus(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CANCEL_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            ),
            decision=_decision(INTENT_CANCEL_DRAFT),
        )
        self.assertEqual(
            r.execution_plan.success_focus_update.action,
            vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
        )
        self.assertEqual(
            r.execution_plan.failure_focus_update.action,
            vr.FOCUS_ACTION_PRESERVE,
        )
        self.assertEqual(r.next_state, vr.NEXT_STATE_APPLY_CANCEL)

    def test_cancel_has_no_authorization_intent(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CANCEL_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION, target_id="p-1",
            ),
            decision=_decision(INTENT_CANCEL_PENDING_ACTION),
        )
        self.assertIsNone(r.execution_plan.authorization_intent)


# =====================================================================
# Correction 1 — Edit / Create emit SET focus intent on success
# =====================================================================

class EditDraftAllowTest(unittest.TestCase):

    def _edit(self):
        return vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="alice@example.org",
                )},
            ),
            decision=_decision(INTENT_EDIT_DRAFT),
        )

    def test_edit_immediate_focus_preserve(self):
        r = self._edit()
        self.assertEqual(r.focus_update.action, vr.FOCUS_ACTION_PRESERVE)

    def test_edit_success_focus_sets_presented_for_confirmation(self):
        # Correction 1: draft presentation emits SET focus intent.
        r = self._edit()
        self.assertEqual(
            r.execution_plan.success_focus_update.action,
            vr.FOCUS_ACTION_SET,
        )
        self.assertEqual(
            r.execution_plan.success_focus_update.kind, FOCUS_KIND_DRAFT,
        )
        self.assertEqual(
            r.execution_plan.success_focus_update.id, "d-1",
        )
        self.assertEqual(
            r.execution_plan.success_focus_update.assistant_act,
            FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        )

    def test_edit_failure_preserves_focus(self):
        r = self._edit()
        self.assertEqual(
            r.execution_plan.failure_focus_update.action,
            vr.FOCUS_ACTION_PRESERVE,
        )

    def test_edit_carries_validated_patch(self):
        r = self._edit()
        self.assertIsNotNone(r.execution_plan.validated_patch)
        self.assertIn("username", r.execution_plan.validated_patch)

    def test_edit_no_authorization_intent(self):
        r = self._edit()
        self.assertIsNone(r.execution_plan.authorization_intent)

    def test_edit_next_state_apply_patch(self):
        r = self._edit()
        self.assertEqual(r.next_state, vr.NEXT_STATE_APPLY_PATCH)

    def test_edit_reply_kind_execution_required(self):
        r = self._edit()
        self.assertEqual(
            r.reply_kind, vr.REPLY_KIND_EXECUTION_REQUIRED,
        )
        self.assertEqual(r.reply_text, "")


class CreateDraftAllowTest(unittest.TestCase):

    def _create(self):
        return vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CREATE_DRAFT,
                target_kind=None, target_id=None,
                patch={"service": FieldPatchItem(
                    op=OP_REPLACE, value="Netflix",
                )},
            ),
            decision=_decision(INTENT_CREATE_DRAFT),
        )

    def test_create_success_focus_is_set_on_create(self):
        r = self._create()
        # SET_ON_CREATE — integration will fill in target_id after
        # minting the new draft.
        self.assertEqual(
            r.execution_plan.success_focus_update.action,
            vr.FOCUS_ACTION_SET_ON_CREATE,
        )
        self.assertEqual(
            r.execution_plan.success_focus_update.kind, FOCUS_KIND_DRAFT,
        )
        self.assertIsNone(
            r.execution_plan.success_focus_update.id,
        )
        self.assertEqual(
            r.execution_plan.success_focus_update.assistant_act,
            FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        )

    def test_create_carries_validated_patch(self):
        r = self._create()
        self.assertIn("service", r.execution_plan.validated_patch)

    def test_create_next_state_apply_create(self):
        r = self._create()
        self.assertEqual(r.next_state, vr.NEXT_STATE_APPLY_CREATE)

    def test_create_target_id_is_none_router_does_not_invent(self):
        r = self._create()
        self.assertIsNone(r.execution_plan.target_id)


# =====================================================================
# Deferred reply templates
# =====================================================================

class DeferredRepliesTest(unittest.TestCase):

    def test_every_reply_key_has_success_and_failure_template(self):
        for k in vr.REPLY_KEYS:
            with self.subTest(reply_key=k):
                self.assertTrue(vr.get_success_reply(k))
                self.assertTrue(vr.get_failure_reply(k))

    def test_success_and_failure_templates_are_different(self):
        for k in vr.REPLY_KEYS:
            with self.subTest(reply_key=k):
                self.assertNotEqual(
                    vr.get_success_reply(k), vr.get_failure_reply(k),
                    f"success and failure templates for {k!r} are the "
                    "same — failure should signal the failure clearly",
                )

    def test_unknown_reply_key_returns_empty_string(self):
        self.assertEqual(vr.get_success_reply("no_such_key"), "")
        self.assertEqual(vr.get_failure_reply("no_such_key"), "")


# =====================================================================
# Correction 5 — pre-execution reply text is empty
# =====================================================================

class NoPrematureSuccessTest(unittest.TestCase):
    """Every execution-required RouterResultV2 must have empty
    reply_text. Deferred success templates must not appear in
    pre-execution reply_text.
    """

    def test_confirm_draft_reply_text_empty(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                auth=_auth(),
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r.reply_text, "")
        # And the success template exists but is NOT surfaced yet.
        self.assertTrue(vr.get_success_reply(
            r.execution_plan.success_reply_key,
        ))

    def test_confirm_pending_delete_reply_text_empty(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CONFIRM_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION, target_id="p-1",
                auth=_auth(
                    TARGET_KIND_PENDING_ACTION, "p-1", ACTION_DELETE,
                ),
            ),
            decision=_decision(INTENT_CONFIRM_PENDING_ACTION),
        )
        self.assertEqual(r.reply_text, "")
        self.assertNotIn("delet", r.reply_text.lower())

    def test_cancel_reply_text_empty(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CANCEL_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            ),
            decision=_decision(INTENT_CANCEL_DRAFT),
        )
        self.assertEqual(r.reply_text, "")

    def test_edit_reply_text_empty(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="x@y.z",
                )},
            ),
            decision=_decision(INTENT_EDIT_DRAFT),
        )
        self.assertEqual(r.reply_text, "")

    def test_create_reply_text_empty(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CREATE_DRAFT,
                patch={"service": FieldPatchItem(
                    op=OP_REPLACE, value="Netflix",
                )},
            ),
            decision=_decision(INTENT_CREATE_DRAFT),
        )
        self.assertEqual(r.reply_text, "")


# =====================================================================
# Integration ownership boundary
# =====================================================================

class IntegrationOwnershipTest(unittest.TestCase):
    """Integration is responsible only for APPLYING the router's
    intent — never deciding target/act. Router always emits fully-
    specified focus intent for SET (except SET_ON_CREATE which
    integration completes with the freshly-minted id).
    """

    def test_confirm_focus_intents_fully_specified(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                auth=_auth(),
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        # Success and failure focus updates must have the target
        # kind and id filled in by the router — integration only
        # applies.
        for fu in (
            r.execution_plan.success_focus_update,
            r.execution_plan.failure_focus_update,
        ):
            if fu.action in (
                vr.FOCUS_ACTION_SET,
                vr.FOCUS_ACTION_CLEAR_IF_MATCHES,
            ):
                self.assertTrue(fu.kind, msg=f"kind missing on {fu}")
                self.assertTrue(fu.id, msg=f"id missing on {fu}")
            if fu.action == vr.FOCUS_ACTION_SET:
                self.assertTrue(
                    fu.assistant_act,
                    msg=f"assistant_act missing on SET {fu}",
                )

    def test_create_focus_set_on_create_has_kind_and_act_but_no_id(self):
        r = vr.route_v2(
            policy_result=_policy_allow(
                intent=INTENT_CREATE_DRAFT,
                patch={"service": FieldPatchItem(
                    op=OP_REPLACE, value="Netflix",
                )},
            ),
            decision=_decision(INTENT_CREATE_DRAFT),
        )
        fu = r.execution_plan.success_focus_update
        self.assertEqual(fu.action, vr.FOCUS_ACTION_SET_ON_CREATE)
        self.assertTrue(fu.kind)
        self.assertTrue(fu.assistant_act)
        self.assertIsNone(fu.id)


# =====================================================================
# Reply independence + purity
# =====================================================================

class ReplyIndependenceTest(unittest.TestCase):

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
                diagnostic="wildly different internal note",
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
                diagnostic="target d-9 vs scope d-1",
            ),
            decision=_decision(INTENT_CONFIRM_DRAFT),
        )
        self.assertEqual(r1.reply_text, r2.reply_text)


class RouterPurityTest(unittest.TestCase):

    def test_router_performs_zero_backend_writes(self):
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
                _policy_allow(
                    intent=INTENT_CREATE_DRAFT,
                    patch={"service": FieldPatchItem(
                        op=OP_REPLACE, value="Netflix",
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
                _policy_clarify(
                    intent=INTENT_CONFIRM_DRAFT,
                    reason=vp.REASON_TARGET_NOT_FOCUSED,
                    target_kind=TARGET_KIND_DRAFT, target_id="d-1",
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
# Policy → Router shape (kept from commit-4)
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
        self.assertEqual(r.reply_kind, vr.REPLY_KIND_REJECTION)


# =====================================================================
# Shape invariants
# =====================================================================

class FocusUpdateShapeTest(unittest.TestCase):

    def test_set_requires_kind_id_act(self):
        with self.assertRaises(ValueError):
            vr.FocusUpdate(action=vr.FOCUS_ACTION_SET)
        with self.assertRaises(ValueError):
            vr.FocusUpdate(
                action=vr.FOCUS_ACTION_SET,
                kind=FOCUS_KIND_DRAFT, id="d-1",
            )

    def test_set_on_create_requires_kind_and_act_but_no_id(self):
        # Valid
        vr.FocusUpdate(
            action=vr.FOCUS_ACTION_SET_ON_CREATE,
            kind=FOCUS_KIND_DRAFT,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        )
        # Missing kind
        with self.assertRaises(ValueError):
            vr.FocusUpdate(
                action=vr.FOCUS_ACTION_SET_ON_CREATE,
                assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            )
        # Missing act
        with self.assertRaises(ValueError):
            vr.FocusUpdate(
                action=vr.FOCUS_ACTION_SET_ON_CREATE,
                kind=FOCUS_KIND_DRAFT,
            )
        # id present → refused
        with self.assertRaises(ValueError):
            vr.FocusUpdate(
                action=vr.FOCUS_ACTION_SET_ON_CREATE,
                kind=FOCUS_KIND_DRAFT, id="d-1",
                assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            )

    def test_clear_if_matches_requires_kind_id(self):
        with self.assertRaises(ValueError):
            vr.FocusUpdate(action=vr.FOCUS_ACTION_CLEAR_IF_MATCHES)

    def test_preserve_and_clear_forbid_kind_id(self):
        with self.assertRaises(ValueError):
            vr.FocusUpdate(
                action=vr.FOCUS_ACTION_PRESERVE, kind=FOCUS_KIND_DRAFT,
            )
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
                execution_plan=None,
                next_state=vr.NEXT_STATE_EXECUTE,
                normalized_intent=INTENT_CHAT,
                reason_code=vp.REASON_ALLOWED,
            )

    def test_handled_true_forbids_fallthrough_next_state(self):
        with self.assertRaises(ValueError):
            vr.RouterResultV2(
                handled=True, reply_kind=vr.REPLY_KIND_CHAT,
                reply_text="hi",
                focus_update=vr.PRESERVE_FOCUS,
                execution_plan=None,
                next_state=vr.NEXT_STATE_FALLTHROUGH,
                normalized_intent=INTENT_CHAT,
                reason_code=vp.REASON_ALLOWED,
            )

    def test_execution_required_requires_plan(self):
        with self.assertRaises(ValueError):
            vr.RouterResultV2(
                handled=True,
                reply_kind=vr.REPLY_KIND_EXECUTION_REQUIRED,
                reply_text="",
                focus_update=vr.PRESERVE_FOCUS,
                execution_plan=None,
                next_state=vr.NEXT_STATE_EXECUTE,
                normalized_intent=INTENT_CONFIRM_DRAFT,
                reason_code=vp.REASON_ALLOWED,
            )

    def test_execution_required_forbids_nonempty_reply_text(self):
        plan = vr.ExecutionPlanV2(
            action_kind=vr.ACTION_KIND_CONFIRM_SAVE,
            target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            authorization_intent=None,
            validated_patch=None,
            success_focus_update=vr.PRESERVE_FOCUS,
            failure_focus_update=vr.PRESERVE_FOCUS,
            success_reply_key="save_draft",
            failure_reply_key="save_draft",
        )
        with self.assertRaises(ValueError):
            vr.RouterResultV2(
                handled=True,
                reply_kind=vr.REPLY_KIND_EXECUTION_REQUIRED,
                reply_text="Saved!",  # forbidden
                focus_update=vr.PRESERVE_FOCUS,
                execution_plan=plan,
                next_state=vr.NEXT_STATE_EXECUTE,
                normalized_intent=INTENT_CONFIRM_DRAFT,
                reason_code=vp.REASON_ALLOWED,
            )

    def test_non_execute_reply_kind_forbids_plan(self):
        plan = vr.ExecutionPlanV2(
            action_kind=vr.ACTION_KIND_CONFIRM_SAVE,
            target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            authorization_intent=None,
            validated_patch=None,
            success_focus_update=vr.PRESERVE_FOCUS,
            failure_focus_update=vr.PRESERVE_FOCUS,
            success_reply_key="save_draft",
            failure_reply_key="save_draft",
        )
        with self.assertRaises(ValueError):
            vr.RouterResultV2(
                handled=True,
                reply_kind=vr.REPLY_KIND_CLARIFICATION,
                reply_text="hm?",
                focus_update=vr.PRESERVE_FOCUS,
                execution_plan=plan,   # forbidden for non-execute reply_kind
                next_state=vr.NEXT_STATE_AWAIT_USER,
                normalized_intent=INTENT_CONFIRM_DRAFT,
                reason_code=vp.REASON_LOW_CONFIDENCE,
            )

    def test_unknown_reply_kind_rejected(self):
        with self.assertRaises(ValueError):
            vr.RouterResultV2(
                handled=True, reply_kind="mystery",
                reply_text="", focus_update=vr.PRESERVE_FOCUS,
                execution_plan=None,
                next_state=vr.NEXT_STATE_AWAIT_USER,
                normalized_intent=INTENT_CHAT,
                reason_code=vp.REASON_ALLOWED,
            )


class ExecutionPlanShapeTest(unittest.TestCase):

    def test_unknown_action_kind_rejected(self):
        with self.assertRaises(ValueError):
            vr.ExecutionPlanV2(
                action_kind="whatever",
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                authorization_intent=None,
                validated_patch=None,
                success_focus_update=vr.PRESERVE_FOCUS,
                failure_focus_update=vr.PRESERVE_FOCUS,
                success_reply_key="save_draft",
                failure_reply_key="save_draft",
            )

    def test_unknown_reply_key_rejected(self):
        with self.assertRaises(ValueError):
            vr.ExecutionPlanV2(
                action_kind=vr.ACTION_KIND_CONFIRM_SAVE,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                authorization_intent=None,
                validated_patch=None,
                success_focus_update=vr.PRESERVE_FOCUS,
                failure_focus_update=vr.PRESERVE_FOCUS,
                success_reply_key="never_defined",
                failure_reply_key="save_draft",
            )


if __name__ == "__main__":
    unittest.main()
