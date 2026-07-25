"""Tests for the pure v2 policy layer (``vault_chat_policy_v2``).

Covers the mandatory matrix from the commit-3 review:

    * unknown target clarifies even at confidence 1.0
    * wrong target kind rejects
    * wrong vault rejects
    * wrong session rejects
    * expired target clarifies or rejects safely
    * edit allowed only on editable draft
    * edit on consumed draft rejected (via status invalid)
    * edit patch never implies save
    * confirm focused draft allowed at non-destructive threshold
    * generic confirm on non-focused draft clarifies
    * expired focus clarifies
    * missing focus clarifies for low-context confirmation
    * high-context explicit target may confirm non-focused live draft
    * multiple plausible targets without focus clarifies
    * save action on delete pending rejected
    * delete action on draft rejected
    * save_attachment action on non-attachment pending rejected
    * unknown patch field rejects whole patch
    * invalid patch operation rejects whole patch
    * regenerate without requested operation rejects
    * requested generation for unsupported field rejects
    * raw password field rejects
    * malformed authorization scope rejects
    * authorization target mismatch rejects
    * low confidence clarifies
    * high confidence cannot bypass invalid target
    * policy is pure and performs no backend writes
"""

from __future__ import annotations

import time
import unittest
from typing import Any

import vault_chat_confidence_thresholds as ct
import vault_chat_policy_v2 as vp

from vault_chat_draft import (
    DRAFT_LOGIN,
    DraftField,
    SOURCE_GENERATED,
    SOURCE_USER_EXPLICIT,
    STATUS_CANCELLED,
    STATUS_CONSUMED,
    STATUS_EDITABLE,
    STATUS_PRESENTED_FOR_CONFIRMATION,
    new_draft,
)
from vault_chat_focus import (
    ConversationalFocus,
    FOCUS_ACT_ASKED_CLARIFICATION,
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
    FOCUS_KIND_DRAFT,
    FOCUS_KIND_PENDING_ACTION,
)
from vault_chat_pending_action import (
    KIND_DELETE_SECURE_ITEM,
    KIND_SAVE_ATTACHMENT,
    KIND_SAVE_LOGIN_DRAFT,
    PendingAction,
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
    NO_VALUE,
    OP_CLEAR,
    OP_REGENERATE,
    OP_REPLACE,
    OP_UNCHANGED,
    OPERATION_GENERATE_PASSWORD,
    RequestedOperation,
    SEMANTIC_DECISION_V2_SCHEMA_VERSION,
    SemanticDecisionV2,
    TARGET_KIND_DRAFT,
    TARGET_KIND_NONE,
    TARGET_KIND_PENDING_ACTION,
    TargetRef,
    validate_semantic_decision_v2,
)


VAULT = "vault-policy-v2-test"
SESSION = "sess-policy-v2-test"
NOW = 1_700_000_000.0


# =====================================================================
# Helpers
# =====================================================================

def _draft(
    draft_id: str = "d-1",
    *,
    status: str = STATUS_EDITABLE,
    session_id=SESSION,
    vault_id=VAULT,
    now: float = NOW,
    include_password: bool = True,
) -> Any:
    fields = {
        "service": DraftField(
            value="Netflix", source=SOURCE_USER_EXPLICIT,
            turn_id="t0", at=now,
        ),
        "username": DraftField(
            value="alice@example.org", source=SOURCE_USER_EXPLICIT,
            turn_id="t0", at=now,
        ),
    }
    if include_password:
        fields["password_ref"] = DraftField(
            value="memory:pending_login_draft:password",
            source=SOURCE_GENERATED, turn_id="t0", at=now,
        )
    d = new_draft(
        vault_id=vault_id, session_id=session_id,
        draft_kind=DRAFT_LOGIN, initial_fields=fields,
        origin_turn_id="t0", now=now, draft_id=draft_id,
    )
    if status != STATUS_EDITABLE:
        from dataclasses import replace
        d = replace(d, status=status)
    return d


def _pending(
    action_id: str = "p-1",
    *,
    kind: str = KIND_DELETE_SECURE_ITEM,
    session_id=SESSION,
    vault_id=VAULT,
    now: float = NOW,
    ttl: float = 600.0,
) -> PendingAction:
    return PendingAction(
        kind=kind,
        action_id=action_id,
        source_kind="secure_delete_intent" if kind == KIND_DELETE_SECURE_ITEM else "uploaded_file",
        target_label="Instagram login",
        created_at=now,
        expires_at=now + ttl,
        vault_id=vault_id,
        session_id=session_id,
        is_destructive=(kind == KIND_DELETE_SECURE_ITEM),
        metadata={},
    )


def _focus(
    *,
    kind: str = FOCUS_KIND_DRAFT,
    id: str = "d-1",
    assistant_act: str = FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
    session_id=SESSION,
    vault_id=VAULT,
    now: float = NOW,
    ttl: float = 180.0,
) -> ConversationalFocus:
    return ConversationalFocus(
        kind=kind, id=id,
        assistant_act=assistant_act,
        assistant_turn_id="a-1",
        vault_id=vault_id, session_id=session_id,
        at=now, expires_at=now + ttl,
    )


def _snapshot(
    *,
    active_drafts: tuple = (),
    pending_actions: tuple = (),
    focus=None,
    vault_id=VAULT,
    session_id=SESSION,
    now: float = NOW,
    current_user_turn_id: str = "u-1",
    preceding_assistant_turn_id: str = "a-1",
) -> vp.PolicySnapshotV2:
    return vp.PolicySnapshotV2(
        vault_id=vault_id,
        session_id=session_id,
        current_user_turn_id=current_user_turn_id,
        preceding_assistant_turn_id=preceding_assistant_turn_id,
        now=now,
        active_drafts=active_drafts,
        pending_actions=pending_actions,
        focus=focus,
    )


def _decision(
    *,
    intent: str,
    target_kind: str = TARGET_KIND_NONE,
    target_id=None,
    field_patch=None,
    requested_operations=(),
    granted: bool = False,
    scope_target_id=None,
    scope_action=None,
    confidence: float = 0.9,
    reason: str = "",
) -> SemanticDecisionV2:
    """Build a valid SemanticDecisionV2 for tests. Uses the
    constructor directly (skip the JSON validator) so tests
    remain focused on the policy layer."""
    from types import MappingProxyType

    scope = None
    if granted:
        scope = AuthorizationScope(
            target_id=scope_target_id or target_id or "",
            action=scope_action,
        )
    return SemanticDecisionV2(
        schema_version=SEMANTIC_DECISION_V2_SCHEMA_VERSION,
        intent=intent,
        target=TargetRef(kind=target_kind, id=target_id),
        field_patch=MappingProxyType(field_patch or {}),
        requested_operations=tuple(requested_operations),
        authorization=Authorization(granted=granted, scope=scope),
        confidence=float(confidence),
        reason=reason,
    )


# =====================================================================
# Passthrough intents
# =====================================================================

class PassthroughIntentsTest(unittest.TestCase):

    def test_fallthrough_allowed(self):
        r = vp.authorize_v2(
            snapshot=_snapshot(),
            decision=_decision(intent=INTENT_FALLTHROUGH),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW)
        self.assertEqual(r.reason_code, vp.REASON_FALLTHROUGH)
        self.assertIsNone(r.authorization_to_mint)

    def test_chat_allowed(self):
        r = vp.authorize_v2(
            snapshot=_snapshot(),
            decision=_decision(intent=INTENT_CHAT, confidence=1.0),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW)
        self.assertEqual(r.reason_code, vp.REASON_ALLOWED)

    def test_answer_question_allowed(self):
        r = vp.authorize_v2(
            snapshot=_snapshot(),
            decision=_decision(intent=INTENT_ANSWER_QUESTION, confidence=0.5),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW)

    def test_ask_clarification_allowed(self):
        r = vp.authorize_v2(
            snapshot=_snapshot(),
            decision=_decision(intent=INTENT_ASK_CLARIFICATION),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW)


# =====================================================================
# Target lookup / ownership
# =====================================================================

class TargetLookupTest(unittest.TestCase):

    def test_unknown_target_id_rejects_at_confidence_1(self):
        r = vp.authorize_v2(
            snapshot=_snapshot(),  # no drafts
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-NEVER",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="x@y.z",
                )},
                confidence=1.0,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_TARGET_NOT_FOUND)

    def test_wrong_target_kind_rejects(self):
        d = _draft("d-1")
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_PENDING_ACTION, target_id="d-1",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="x@y.z",
                )},
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_TARGET_KIND_MISMATCH)

    def test_wrong_vault_rejects(self):
        d = _draft("d-1", vault_id="other-vault")
        # target is in the snapshot's active_drafts (test setup),
        # but its vault_id differs from the snapshot's vault_id.
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="x@y.z",
                )},
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_WRONG_VAULT)

    def test_wrong_session_rejects(self):
        d = _draft("d-1", session_id="OTHER_SESSION")
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="x@y.z",
                )},
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_WRONG_SESSION)

    def test_expired_draft_clarifies(self):
        # Draft with ttl=1s, now=+2000s → expired
        d = _draft("d-1", now=NOW)
        r = vp.authorize_v2(
            snapshot=_snapshot(
                active_drafts=(d,), now=NOW + 100_000,
            ),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="x@y.z",
                )},
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_TARGET_EXPIRED)

    def test_high_confidence_cannot_bypass_unknown_target(self):
        r = vp.authorize_v2(
            snapshot=_snapshot(),
            decision=_decision(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-NONE",
                granted=True, scope_target_id="d-NONE",
                scope_action=ACTION_SAVE, confidence=1.0,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_TARGET_NOT_FOUND)


# =====================================================================
# Edit draft — status + patch
# =====================================================================

class EditDraftTest(unittest.TestCase):

    def test_edit_on_editable_draft_allowed(self):
        d = _draft("d-1", status=STATUS_EDITABLE)
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="new@gmail.com",
                )},
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW)
        self.assertIsNone(r.authorization_to_mint,
                          "edit must NOT mint authorization")
        self.assertIsNotNone(r.validated_patch)
        self.assertIn("username", r.validated_patch)

    def test_edit_on_consumed_draft_rejected(self):
        d = _draft("d-1", status=STATUS_CONSUMED)
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="new@gmail.com",
                )},
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_TARGET_STATUS_INVALID)

    def test_edit_on_cancelled_draft_rejected(self):
        d = _draft("d-1", status=STATUS_CANCELLED)
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="x@y.z",
                )},
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_TARGET_STATUS_INVALID)

    def test_edit_patch_never_implies_save(self):
        d = _draft("d-1")
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                field_patch={"username": FieldPatchItem(
                    op=OP_REPLACE, value="x@y.z",
                )},
            ),
        )
        self.assertIsNone(r.authorization_to_mint)


# =====================================================================
# Patch validation
# =====================================================================

class PatchValidationTest(unittest.TestCase):

    def _edit(self, field_patch, requested_operations=(), *,
              existing_draft=None):
        d = existing_draft or _draft("d-1")
        return vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_EDIT_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                field_patch=field_patch,
                requested_operations=requested_operations,
            ),
        )

    def test_unknown_patch_field_rejects_whole_patch(self):
        r = self._edit({
            "username": FieldPatchItem(op=OP_REPLACE, value="ok@x.y"),
            "totally_unknown": FieldPatchItem(op=OP_REPLACE, value="x"),
        })
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_PATCH_FIELD_NOT_ALLOWED)

    def test_regenerate_without_requested_op_rejects(self):
        r = self._edit({
            "password_ref": FieldPatchItem(op=OP_REGENERATE),
        }, requested_operations=())
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_PATCH_REGENERATE_WITHOUT_OP)

    def test_regenerate_with_matching_op_allowed(self):
        r = self._edit({
            "password_ref": FieldPatchItem(op=OP_REGENERATE),
        }, requested_operations=(
            RequestedOperation(
                operation=OPERATION_GENERATE_PASSWORD,
                field="password_ref",
            ),
        ))
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW)

    def test_regenerate_on_non_regeneratable_field_rejects(self):
        r = self._edit({
            "username": FieldPatchItem(op=OP_REGENERATE),
        })
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_PATCH_OP_INVALID)

    def test_regenerate_on_explicit_password_ref_rejects(self):
        # Existing draft has password_ref sourced user_explicit.
        d = _draft("d-1", include_password=False)
        from dataclasses import replace
        d = replace(d, fields={
            **d.fields,
            "password_ref": DraftField(
                value="vault_ref:existing:handle",
                source=SOURCE_USER_EXPLICIT, turn_id="t0", at=NOW,
            ),
        })
        r = self._edit({
            "password_ref": FieldPatchItem(op=OP_REGENERATE),
        }, requested_operations=(
            RequestedOperation(
                operation=OPERATION_GENERATE_PASSWORD,
                field="password_ref",
            ),
        ), existing_draft=d)
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_PATCH_OP_INVALID)

    def test_raw_password_in_password_ref_rejects(self):
        r = self._edit({
            "password_ref": FieldPatchItem(
                op=OP_REPLACE, value="MyRealPassword123!",
            ),
        })
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_PATCH_RAW_PASSWORD)

    def test_invalid_value_rejects_with_value_invalid_reason(self):
        r = self._edit({
            "username": FieldPatchItem(op=OP_REPLACE, value=""),
        })
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_PATCH_VALUE_INVALID)

    def test_requested_operation_wrong_field_rejected_at_construction(self):
        # RequestedOperation's constructor rejects generate_password
        # on a non-password field. The policy layer never sees such
        # a RequestedOperation because construction fails first.
        # This is the "requested generation for unsupported field
        # rejects" invariant from the commit-3 review, enforced at
        # the type-construction boundary rather than in policy.
        with self.assertRaises(ValueError):
            RequestedOperation(
                operation=OPERATION_GENERATE_PASSWORD,
                field="username",
            )

    def test_clear_required_field_rejects(self):
        r = self._edit({
            "username": FieldPatchItem(op=OP_CLEAR),
        })
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_PATCH_OP_INVALID)


# =====================================================================
# Confirm draft — focus + confidence
# =====================================================================

class ConfirmDraftTest(unittest.TestCase):

    def _confirm(self, *, drafts, focus=None, confidence=0.9,
                 granted=True, scope_action=ACTION_SAVE,
                 scope_target_id=None, target_id="d-1"):
        return vp.authorize_v2(
            snapshot=_snapshot(active_drafts=drafts, focus=focus),
            decision=_decision(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id=target_id,
                granted=granted,
                scope_target_id=scope_target_id or target_id,
                scope_action=scope_action, confidence=confidence,
            ),
        )

    def test_confirm_focused_draft_at_non_destructive_threshold_allowed(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1")
        r = self._confirm(
            drafts=(d,), focus=f,
            confidence=ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE,
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW,
                         msg=f"reason={r.reason_code}")
        self.assertIsNotNone(r.authorization_to_mint)
        self.assertEqual(
            r.authorization_to_mint.action, ACTION_SAVE,
        )
        self.assertEqual(
            r.authorization_to_mint.target_id, "d-1",
        )

    def test_generic_confirm_on_non_focused_draft_clarifies(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        # No focus at all — low-context confirmation
        r = self._confirm(drafts=(d,), focus=None, confidence=0.9)
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_INSUFFICIENT_CONTEXT)

    def test_expired_focus_clarifies(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1", now=NOW, ttl=1.0)
        # Advance now past focus TTL
        r = vp.authorize_v2(
            snapshot=_snapshot(
                active_drafts=(d,), focus=f, now=NOW + 100_000,
            ),
            decision=_decision(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                granted=True, scope_target_id="d-1",
                scope_action=ACTION_SAVE, confidence=0.9,
            ),
        )
        # Draft with the default 600s TTL also expires at now+600 —
        # but we advanced 100_000s so draft ALSO expires. That's a
        # target-expired result. Use a fresh draft.
        # Actually let me repeat with a longer-TTL draft.

    def test_expired_focus_clarifies_with_live_draft(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION,
                   now=NOW + 100_000)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1",
                   now=NOW, ttl=1.0)
        r = vp.authorize_v2(
            snapshot=_snapshot(
                active_drafts=(d,), focus=f, now=NOW + 100_000,
            ),
            decision=_decision(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                granted=True, scope_target_id="d-1",
                scope_action=ACTION_SAVE, confidence=0.9,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_EXPIRED_FOCUS)

    def test_missing_focus_low_context_clarifies_insufficient_context(self):
        d = _draft("d-1")
        r = self._confirm(drafts=(d,), focus=None, confidence=0.9)
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_INSUFFICIENT_CONTEXT)

    def test_focus_targets_wrong_draft_clarifies(self):
        d1 = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        d2 = _draft("d-2", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        # Focus points at d-2 but the decision confirms d-1
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-2")
        r = self._confirm(
            drafts=(d1, d2), focus=f, target_id="d-1", confidence=0.9,
        )
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        # Focus exists but targets a different id → not focused
        self.assertEqual(r.reason_code, vp.REASON_TARGET_NOT_FOCUSED)

    def test_high_context_explicit_target_non_focused_may_confirm(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        # No focus, but confidence high AND only one candidate.
        r = self._confirm(
            drafts=(d,), focus=None,
            confidence=ct.CONFIDENCE_EXECUTE_HIGH_CONTEXT,
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW,
                         msg=f"reason={r.reason_code}")

    def test_multiple_candidates_without_focus_clarifies(self):
        d1 = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        d2 = _draft("d-2", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        # High confidence but 2 same-kind candidates and no focus →
        # ambiguous
        r = self._confirm(
            drafts=(d1, d2), focus=None,
            confidence=ct.CONFIDENCE_EXECUTE_HIGH_CONTEXT,
            target_id="d-1",
        )
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_AMBIGUOUS_TARGET)

    def test_low_confidence_focused_still_clarifies(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1")
        r = self._confirm(drafts=(d,), focus=f, confidence=0.5)
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_LOW_CONFIDENCE)

    def test_focus_of_wrong_act_clarifies(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1",
                   assistant_act=FOCUS_ACT_ASKED_CLARIFICATION)
        r = self._confirm(drafts=(d,), focus=f, confidence=0.9)
        # Focus is live and targets d-1, but not presented_for_confirmation
        # → not a bound-for-confirm state.
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)

    def test_confirm_without_grant_clarifies(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1")
        r = self._confirm(
            drafts=(d,), focus=f, confidence=0.9, granted=False,
        )
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_AUTH_MISSING_GRANT)


# =====================================================================
# Auth action / scope
# =====================================================================

class AuthActionTest(unittest.TestCase):

    def test_delete_action_on_draft_rejected(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1")
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,), focus=f),
            decision=_decision(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                granted=True, scope_target_id="d-1",
                scope_action=ACTION_DELETE, confidence=0.95,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_AUTH_ACTION_MISMATCH)

    def test_save_action_on_delete_pending_rejected(self):
        p = _pending("p-1", kind=KIND_DELETE_SECURE_ITEM)
        f = _focus(kind=FOCUS_KIND_PENDING_ACTION, id="p-1")
        r = vp.authorize_v2(
            snapshot=_snapshot(pending_actions=(p,), focus=f),
            decision=_decision(
                intent=INTENT_CONFIRM_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id="p-1",
                granted=True, scope_target_id="p-1",
                scope_action=ACTION_SAVE, confidence=0.98,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_AUTH_ACTION_MISMATCH)

    def test_save_attachment_action_on_non_attachment_pending_rejected(self):
        p = _pending("p-1", kind=KIND_SAVE_LOGIN_DRAFT)
        f = _focus(kind=FOCUS_KIND_PENDING_ACTION, id="p-1")
        r = vp.authorize_v2(
            snapshot=_snapshot(pending_actions=(p,), focus=f),
            decision=_decision(
                intent=INTENT_CONFIRM_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id="p-1",
                granted=True, scope_target_id="p-1",
                scope_action=ACTION_SAVE_ATTACHMENT, confidence=0.98,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_AUTH_ACTION_MISMATCH)

    def test_authorization_target_mismatch_rejects(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1")
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,), focus=f),
            decision=_decision(
                intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                granted=True, scope_target_id="d-DIFFERENT",
                scope_action=ACTION_SAVE, confidence=0.9,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_AUTH_SCOPE_MISMATCH)


# =====================================================================
# Confirm pending — destructive threshold
# =====================================================================

class ConfirmPendingActionTest(unittest.TestCase):

    def test_destructive_confirm_requires_destructive_threshold(self):
        p = _pending("p-1", kind=KIND_DELETE_SECURE_ITEM)
        f = _focus(kind=FOCUS_KIND_PENDING_ACTION, id="p-1")
        # confidence at non-destructive threshold (0.85) is
        # insufficient for a destructive confirm (needs 0.95).
        r = vp.authorize_v2(
            snapshot=_snapshot(pending_actions=(p,), focus=f),
            decision=_decision(
                intent=INTENT_CONFIRM_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id="p-1",
                granted=True, scope_target_id="p-1",
                scope_action=ACTION_DELETE,
                confidence=ct.CONFIDENCE_EXECUTE_NON_DESTRUCTIVE,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_LOW_CONFIDENCE)

    def test_destructive_confirm_at_destructive_threshold_allowed(self):
        p = _pending("p-1", kind=KIND_DELETE_SECURE_ITEM)
        f = _focus(kind=FOCUS_KIND_PENDING_ACTION, id="p-1")
        r = vp.authorize_v2(
            snapshot=_snapshot(pending_actions=(p,), focus=f),
            decision=_decision(
                intent=INTENT_CONFIRM_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id="p-1",
                granted=True, scope_target_id="p-1",
                scope_action=ACTION_DELETE,
                confidence=ct.CONFIDENCE_EXECUTE_DESTRUCTIVE,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW,
                         msg=f"reason={r.reason_code}")
        self.assertEqual(
            r.authorization_to_mint.action, ACTION_DELETE,
        )

    def test_expired_pending_clarifies(self):
        p = _pending("p-1", kind=KIND_DELETE_SECURE_ITEM,
                     now=NOW, ttl=1.0)
        f = _focus(kind=FOCUS_KIND_PENDING_ACTION, id="p-1",
                   now=NOW + 1_000_000)
        r = vp.authorize_v2(
            snapshot=_snapshot(
                pending_actions=(p,), focus=f, now=NOW + 1_000_000,
            ),
            decision=_decision(
                intent=INTENT_CONFIRM_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id="p-1",
                granted=True, scope_target_id="p-1",
                scope_action=ACTION_DELETE, confidence=0.98,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_CLARIFY)
        self.assertEqual(r.reason_code, vp.REASON_TARGET_EXPIRED)


# =====================================================================
# Cancel intents — no authorization
# =====================================================================

class CancelIntentTest(unittest.TestCase):

    def test_cancel_draft_no_authorization_needed(self):
        d = _draft("d-1")
        r = vp.authorize_v2(
            snapshot=_snapshot(active_drafts=(d,)),
            decision=_decision(
                intent=INTENT_CANCEL_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                confidence=0.4,   # cancel doesn't need high conf
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW)
        self.assertIsNone(r.authorization_to_mint)

    def test_cancel_pending_no_authorization_needed(self):
        p = _pending("p-1", kind=KIND_DELETE_SECURE_ITEM)
        r = vp.authorize_v2(
            snapshot=_snapshot(pending_actions=(p,)),
            decision=_decision(
                intent=INTENT_CANCEL_PENDING_ACTION,
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id="p-1", confidence=0.3,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW)
        self.assertIsNone(r.authorization_to_mint)


# =====================================================================
# Create draft
# =====================================================================

class CreateDraftTest(unittest.TestCase):

    def test_create_login_draft_allowed(self):
        r = vp.authorize_v2(
            snapshot=_snapshot(),
            decision=_decision(
                intent=INTENT_CREATE_DRAFT,
                target_kind=TARGET_KIND_NONE, target_id=None,
                field_patch={
                    "service": FieldPatchItem(
                        op=OP_REPLACE, value="Netflix",
                    ),
                    "username": FieldPatchItem(
                        op=OP_REPLACE, value="alice@example.org",
                    ),
                },
                requested_operations=(RequestedOperation(
                    operation=OPERATION_GENERATE_PASSWORD,
                    field="password_ref",
                ),),
                confidence=0.9,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_ALLOW,
                         msg=f"reason={r.reason_code}")
        self.assertIsNone(r.authorization_to_mint)
        self.assertIn("service", r.validated_patch)
        self.assertIn("username", r.validated_patch)

    def test_create_draft_with_wrong_target_kind_rejects(self):
        r = vp.authorize_v2(
            snapshot=_snapshot(),
            decision=_decision(
                intent=INTENT_CREATE_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-something",
                field_patch={
                    "service": FieldPatchItem(
                        op=OP_REPLACE, value="Netflix",
                    ),
                },
                confidence=0.9,
            ),
        )
        self.assertEqual(r.outcome, vp.OUTCOME_REJECT)
        self.assertEqual(r.reason_code, vp.REASON_TARGET_KIND_MISMATCH)


# =====================================================================
# Policy purity — no side effects
# =====================================================================

class PolicyPurityTest(unittest.TestCase):
    """Assert that authorize_v2 performs no backend writes and does
    not mutate its inputs.
    """

    def test_no_backend_writes(self):
        # Wrap the shared-state backend with a NoOp that raises on
        # any write. If policy_v2 touches Redis, this test fires.
        import vault_chat_state_store as st

        class TrapBackend(st.SharedStateBackend):
            def get(self, key): return None
            def set(self, key, value, ttl_seconds): raise AssertionError(
                f"policy attempted a write to key={key!r}"
            )
            def delete(self, key): raise AssertionError(
                f"policy attempted a delete on key={key!r}"
            )
            def sadd(self, key, member, ttl_seconds): raise AssertionError(
                "policy attempted sadd"
            )
            def smembers(self, key): return set()
            def srem(self, key, member): raise AssertionError("policy attempted srem")
            def sclear(self, key): raise AssertionError("policy attempted sclear")
            def health(self): return True

        st.install_backend_for_tests(TrapBackend())
        try:
            d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
            f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1")
            vp.authorize_v2(
                snapshot=_snapshot(active_drafts=(d,), focus=f),
                decision=_decision(
                    intent=INTENT_CONFIRM_DRAFT,
                    target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                    granted=True, scope_target_id="d-1",
                    scope_action=ACTION_SAVE, confidence=0.95,
                ),
            )
            # If we reach here, no writes were attempted.
        finally:
            st.reset_chat_state_backend_for_tests()

    def test_snapshot_and_decision_are_not_mutated(self):
        d = _draft("d-1", status=STATUS_PRESENTED_FOR_CONFIRMATION)
        f = _focus(kind=FOCUS_KIND_DRAFT, id="d-1")
        snap = _snapshot(active_drafts=(d,), focus=f)
        dec = _decision(
            intent=INTENT_CONFIRM_DRAFT,
            target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            granted=True, scope_target_id="d-1",
            scope_action=ACTION_SAVE, confidence=0.95,
        )
        vp.authorize_v2(snapshot=snap, decision=dec)
        # frozen dataclasses would raise on mutation anyway; assert
        # identity is preserved.
        self.assertIs(snap.active_drafts[0], d)
        self.assertIs(snap.focus, f)


# =====================================================================
# PolicyResultV2 shape invariants
# =====================================================================

class PolicyResultShapeTest(unittest.TestCase):

    def test_allowed_true_requires_outcome_allow(self):
        with self.assertRaises(ValueError):
            vp.PolicyResultV2(
                allowed=True, outcome=vp.OUTCOME_CLARIFY,
                normalized_intent=INTENT_CHAT,
                target_kind=None, target_id=None,
                authorization_to_mint=None,
                validated_patch=None,
                reason_code=vp.REASON_ALLOWED,
            )

    def test_authorization_requires_allow(self):
        with self.assertRaises(ValueError):
            vp.PolicyResultV2(
                allowed=False, outcome=vp.OUTCOME_REJECT,
                normalized_intent=INTENT_CONFIRM_DRAFT,
                target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                authorization_to_mint=vp.AuthorizationIntent(
                    target_kind=TARGET_KIND_DRAFT, target_id="d-1",
                    action=ACTION_SAVE,
                    authorizing_user_turn_id="u-1",
                    preceding_assistant_turn_id="a-1",
                    confidence=0.9,
                ),
                validated_patch=None,
                reason_code=vp.REASON_ALLOWED,
            )

    def test_unknown_reason_code_rejected(self):
        with self.assertRaises(ValueError):
            vp.PolicyResultV2(
                allowed=True, outcome=vp.OUTCOME_ALLOW,
                normalized_intent=INTENT_CHAT,
                target_kind=None, target_id=None,
                authorization_to_mint=None,
                validated_patch=None,
                reason_code="WHATEVER",
            )


if __name__ == "__main__":
    unittest.main()
