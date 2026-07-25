"""Pure orchestration router for the chat-brain v2 semantic
reasoning path.

Given a validated ``SemanticDecisionV2`` and its
``PolicyResultV2``, the router produces a ``RouterResultV2``
describing WHAT should happen next:

    * reply_kind + reply_text        (deterministic template)
    * focus_update                    (set / clear / clear_if_matches / preserve)
    * authorization_intent            (handoff from policy — router does NOT mint)
    * validated_patch                 (handoff for edit/create — router does NOT apply)
    * next_state                      (execute / apply_patch / apply_cancel / fallthrough)

Scope of this module (commit 4)
-------------------------------
This module is the *single owner* of:

    * focus creation, clearing, preservation
    * routing decisions
    * authorization-intent handoff

It has NO side effects: no Redis writes, no
``mint_authorization`` calls, no executor invocations, no
mutation of the decision or policy result. The integration layer
(commit 5) applies the focus updates, mints the authorization,
applies the patch, calls the executor — it is the only place
that touches state.

Reply-text guarantees
---------------------
* Deterministic — depends only on ``(outcome, normalized_intent,
  reason_code)``, plus (for allow-confirm variants) the
  ``authorization_intent.action`` shape.
* Independent of the free-form ``diagnostic`` on
  ``PolicyResultV2``. The diagnostic is dev-facing text only.
* Never inspects the LLM's ``decision.reason`` field. That is
  debug-only per the security posture in the design memo.

Fallthrough intents
-------------------
Phase 1 routes ``INTENT_FALLTHROUGH``, ``INTENT_CHAT``, and
``INTENT_ANSWER_QUESTION`` back to the legacy pipeline
(``handled=False``, ``next_state=NEXT_STATE_FALLTHROUGH``). The
legacy pipeline already handles chat, greetings, and vault-state
questions, and this keeps commit-4 templates minimal and safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional

from vault_chat_focus import (
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
    FOCUS_KIND_DRAFT,
    FOCUS_KIND_PENDING_ACTION,
)
from vault_chat_policy_v2 import (
    AuthorizationIntent,
    OUTCOME_ALLOW,
    OUTCOME_CLARIFY,
    OUTCOME_REJECT,
    OUTCOMES,
    PolicyResultV2,
    REASON_AMBIGUOUS_TARGET,
    REASON_ALLOWED,
    REASON_AUTH_ACTION_MISMATCH,
    REASON_AUTH_MISSING_GRANT,
    REASON_AUTH_SCOPE_MISMATCH,
    REASON_CODES,
    REASON_EXPIRED_FOCUS,
    REASON_FALLTHROUGH,
    REASON_INSUFFICIENT_CONTEXT,
    REASON_INTENT_UNKNOWN,
    REASON_LOW_CONFIDENCE,
    REASON_PATCH_FIELD_NOT_ALLOWED,
    REASON_PATCH_OP_INVALID,
    REASON_PATCH_RAW_PASSWORD,
    REASON_PATCH_REGENERATE_WITHOUT_OP,
    REASON_PATCH_VALUE_INVALID,
    REASON_REQUESTED_OP_INVALID_FIELD,
    REASON_SCHEMA_INVALID,
    REASON_TARGET_EXPIRED,
    REASON_TARGET_KIND_MISMATCH,
    REASON_TARGET_NOT_FOCUSED,
    REASON_TARGET_NOT_FOUND,
    REASON_TARGET_STATUS_INVALID,
    REASON_WRONG_SESSION,
    REASON_WRONG_VAULT,
)
from vault_chat_semantic_decision_v2 import (
    ACTION_DELETE,
    ACTION_SAVE,
    ACTION_SAVE_ATTACHMENT,
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
    SemanticDecisionV2,
    TARGET_KIND_DRAFT,
    TARGET_KIND_PENDING_ACTION,
)


# =====================================================================
# Reply kinds (closed set)
# =====================================================================

REPLY_KIND_NONE:                str = "none"
REPLY_KIND_CLARIFICATION:       str = "clarification"
REPLY_KIND_REJECTION:           str = "rejection"
REPLY_KIND_CONFIRMATION_ACK:    str = "confirmation_ack"
REPLY_KIND_CANCELLATION_ACK:    str = "cancellation_ack"
REPLY_KIND_DRAFT_PRESENTATION:  str = "draft_presentation"
REPLY_KIND_CHAT:                str = "chat"

REPLY_KINDS: frozenset[str] = frozenset({
    REPLY_KIND_NONE,
    REPLY_KIND_CLARIFICATION,
    REPLY_KIND_REJECTION,
    REPLY_KIND_CONFIRMATION_ACK,
    REPLY_KIND_CANCELLATION_ACK,
    REPLY_KIND_DRAFT_PRESENTATION,
    REPLY_KIND_CHAT,
})


# =====================================================================
# Focus updates (closed set)
# =====================================================================

FOCUS_ACTION_PRESERVE:           str = "preserve"
FOCUS_ACTION_SET:                str = "set"
FOCUS_ACTION_CLEAR:              str = "clear"
FOCUS_ACTION_CLEAR_IF_MATCHES:   str = "clear_if_matches"

FOCUS_ACTIONS: frozenset[str] = frozenset({
    FOCUS_ACTION_PRESERVE,
    FOCUS_ACTION_SET,
    FOCUS_ACTION_CLEAR,
    FOCUS_ACTION_CLEAR_IF_MATCHES,
})


@dataclass(frozen=True)
class FocusUpdate:
    action:         str
    kind:           Optional[str] = None    # required for set / clear_if_matches
    id:             Optional[str] = None    # required for set / clear_if_matches
    assistant_act:  Optional[str] = None    # required for set

    def __post_init__(self) -> None:
        if self.action not in FOCUS_ACTIONS:
            raise ValueError(f"unknown focus action {self.action!r}")
        if self.action == FOCUS_ACTION_SET:
            if not self.kind or not self.id or not self.assistant_act:
                raise ValueError(
                    "focus set requires kind + id + assistant_act"
                )
        elif self.action == FOCUS_ACTION_CLEAR_IF_MATCHES:
            if not self.kind or not self.id:
                raise ValueError(
                    "focus clear_if_matches requires kind + id"
                )
        elif self.action in (FOCUS_ACTION_PRESERVE, FOCUS_ACTION_CLEAR):
            if self.kind or self.id or self.assistant_act:
                raise ValueError(
                    f"focus {self.action!r} must not carry kind/id/act"
                )


PRESERVE_FOCUS: FocusUpdate = FocusUpdate(action=FOCUS_ACTION_PRESERVE)
CLEAR_FOCUS:    FocusUpdate = FocusUpdate(action=FOCUS_ACTION_CLEAR)


# =====================================================================
# Next-state hints (closed set)
# =====================================================================

NEXT_STATE_AWAIT_USER:      str = "await_user"
NEXT_STATE_EXECUTE:         str = "execute"
NEXT_STATE_APPLY_PATCH:     str = "apply_patch"
NEXT_STATE_APPLY_CANCEL:    str = "apply_cancel"
NEXT_STATE_APPLY_CREATE:    str = "apply_create"
NEXT_STATE_FALLTHROUGH:     str = "fallthrough"

NEXT_STATES: frozenset[str] = frozenset({
    NEXT_STATE_AWAIT_USER,
    NEXT_STATE_EXECUTE,
    NEXT_STATE_APPLY_PATCH,
    NEXT_STATE_APPLY_CANCEL,
    NEXT_STATE_APPLY_CREATE,
    NEXT_STATE_FALLTHROUGH,
})


# =====================================================================
# RouterResultV2
# =====================================================================

@dataclass(frozen=True)
class RouterResultV2:
    handled:               bool
    reply_kind:            str
    reply_text:            str
    focus_update:          FocusUpdate
    authorization_intent:  Optional[AuthorizationIntent]
    validated_patch:       Optional[Mapping[str, FieldPatchItem]]
    next_state:            str
    normalized_intent:     str
    reason_code:           str
    diagnostic:            str = ""

    def __post_init__(self) -> None:
        if self.reply_kind not in REPLY_KINDS:
            raise ValueError(f"unknown reply_kind {self.reply_kind!r}")
        if self.next_state not in NEXT_STATES:
            raise ValueError(f"unknown next_state {self.next_state!r}")
        if self.reason_code not in REASON_CODES:
            raise ValueError(f"unknown reason_code {self.reason_code!r}")
        # handled=True MUST come with a producing reply_kind or an
        # explicit next-state action; handled=False MUST be fallthrough.
        if not self.handled and self.next_state != NEXT_STATE_FALLTHROUGH:
            raise ValueError(
                "handled=False requires next_state=fallthrough"
            )
        if self.handled and self.next_state == NEXT_STATE_FALLTHROUGH:
            raise ValueError(
                "handled=True must not have next_state=fallthrough"
            )
        # Freeze the patch mapping.
        if self.validated_patch is not None and not isinstance(
            self.validated_patch, MappingProxyType,
        ):
            object.__setattr__(
                self, "validated_patch",
                MappingProxyType(dict(self.validated_patch)),
            )


# =====================================================================
# Reply templates (deterministic)
#
# Keys are stable machine-readable reason codes / intent+action
# tuples. Templates are short, neutral, and safe to render for
# any user without leaking snapshot state. Adding a new phrase or
# tone here requires an intentional edit, not a model influence.
# =====================================================================

_CLARIFICATION_TEMPLATES: Mapping[str, str] = MappingProxyType({
    REASON_INSUFFICIENT_CONTEXT:
        "Could you re-state what you'd like me to do?",
    REASON_EXPIRED_FOCUS:
        "That last suggestion expired — could you re-state your request?",
    REASON_TARGET_NOT_FOCUSED:
        "Which item did you mean? Please name it.",
    REASON_AMBIGUOUS_TARGET:
        "There are multiple matches — which one did you mean?",
    REASON_LOW_CONFIDENCE:
        "I'm not sure I understood. Could you rephrase?",
    REASON_TARGET_EXPIRED:
        "That item has expired. Would you like to start over?",
    REASON_TARGET_NOT_FOUND:
        "I don't have that item on hand. Could you clarify or start fresh?",
    REASON_AUTH_MISSING_GRANT:
        "Are you sure? Please say yes or no.",
    # INTENT_ASK_CLARIFICATION on outcome=ALLOW uses REASON_ALLOWED
    # since the policy assigned no specific reason.
    REASON_ALLOWED:
        "Could you clarify what you'd like to do?",
})


_GENERIC_CLARIFICATION: str = "Could you re-state that?"


_REJECTION_TEMPLATES: Mapping[str, str] = MappingProxyType({
    REASON_WRONG_VAULT:
        "I can't process that request.",
    REASON_WRONG_SESSION:
        "I can't process that request.",
    REASON_TARGET_KIND_MISMATCH:
        "That request doesn't match what I expected.",
    REASON_TARGET_STATUS_INVALID:
        "That item can no longer be changed.",
    REASON_AUTH_ACTION_MISMATCH:
        "The requested action doesn't apply to that item.",
    REASON_AUTH_SCOPE_MISMATCH:
        "I can't process that confirmation.",
    REASON_PATCH_FIELD_NOT_ALLOWED:
        "One of the fields you named isn't valid for this item.",
    REASON_PATCH_OP_INVALID:
        "That change isn't allowed on this field.",
    REASON_PATCH_VALUE_INVALID:
        "One of the values you provided isn't valid.",
    REASON_PATCH_REGENERATE_WITHOUT_OP:
        "I can't regenerate that field right now.",
    REASON_PATCH_RAW_PASSWORD:
        "For security I need to generate the password rather than "
        "accept one directly.",
    REASON_REQUESTED_OP_INVALID_FIELD:
        "That generation request isn't valid.",
    REASON_SCHEMA_INVALID:
        "Something went wrong with that request. Please try again.",
    REASON_INTENT_UNKNOWN:
        "I couldn't understand what you'd like to do.",
})


_GENERIC_REJECTION: str = "I can't process that request."


# Allow-confirm ACK templates. Keys are (intent, action).
_CONFIRM_ACK_TEMPLATES: Mapping[tuple, str] = MappingProxyType({
    (INTENT_CONFIRM_DRAFT,          ACTION_SAVE):
        "Okay, saving your draft.",
    (INTENT_CONFIRM_PENDING_ACTION, ACTION_SAVE):
        "Okay, saving.",
    (INTENT_CONFIRM_PENDING_ACTION, ACTION_DELETE):
        "Okay, deleting.",
    (INTENT_CONFIRM_PENDING_ACTION, ACTION_SAVE_ATTACHMENT):
        "Okay, saving your file.",
})


_CANCEL_ACK_TEMPLATE: str = "Okay, cancelled."
_EDIT_ACK_TEMPLATE:   str = "Updated the draft."
_CREATE_ACK_TEMPLATE: str = "Started a new draft."


# =====================================================================
# Public entry point
# =====================================================================

def route_v2(
    *, policy_result: PolicyResultV2,
    decision: SemanticDecisionV2,
) -> RouterResultV2:
    """Pure orchestration. Produces a ``RouterResultV2`` from the
    policy result. Never writes to Redis, never mints an
    ``AuthorizationRecord``, never touches focus storage. The
    integration layer (commit 5) applies the router's declared
    intent.
    """
    if policy_result.outcome not in OUTCOMES:
        # Defensive — should not happen with a validated PolicyResultV2
        return _reject_generic(
            policy_result, override_reason=REASON_INTENT_UNKNOWN,
        )

    intent = policy_result.normalized_intent

    # -----------------------------------------------------------------
    # Fallthrough intents (phase 1 also routes chat / answer_question
    # back to the legacy pipeline).
    # -----------------------------------------------------------------
    if intent == INTENT_FALLTHROUGH:
        return _fallthrough_result(policy_result)
    if intent in (INTENT_CHAT, INTENT_ANSWER_QUESTION):
        return _fallthrough_result(policy_result)

    # -----------------------------------------------------------------
    # ASK_CLARIFICATION always emits a clarification reply,
    # regardless of the policy outcome (typically allow).
    # -----------------------------------------------------------------
    if intent == INTENT_ASK_CLARIFICATION:
        return _clarify_result(policy_result)

    # -----------------------------------------------------------------
    # Non-passthrough outcomes.
    # -----------------------------------------------------------------
    if policy_result.outcome == OUTCOME_CLARIFY:
        return _clarify_result(policy_result)
    if policy_result.outcome == OUTCOME_REJECT:
        return _reject_result(policy_result)

    # OUTCOME_ALLOW below.
    if intent == INTENT_CONFIRM_DRAFT:
        return _allow_confirm_draft(policy_result)
    if intent == INTENT_CONFIRM_PENDING_ACTION:
        return _allow_confirm_pending(policy_result)
    if intent == INTENT_CANCEL_DRAFT:
        return _allow_cancel_draft(policy_result)
    if intent == INTENT_CANCEL_PENDING_ACTION:
        return _allow_cancel_pending(policy_result)
    if intent == INTENT_EDIT_DRAFT:
        return _allow_edit_draft(policy_result)
    if intent == INTENT_CREATE_DRAFT:
        return _allow_create_draft(policy_result)

    return _reject_generic(
        policy_result, override_reason=REASON_INTENT_UNKNOWN,
    )


# =====================================================================
# Result builders — one per outcome branch
# =====================================================================

def _fallthrough_result(policy_result: PolicyResultV2) -> RouterResultV2:
    return RouterResultV2(
        handled=False,
        reply_kind=REPLY_KIND_NONE,
        reply_text="",
        focus_update=PRESERVE_FOCUS,
        authorization_intent=None,
        validated_patch=None,
        next_state=NEXT_STATE_FALLTHROUGH,
        normalized_intent=policy_result.normalized_intent,
        reason_code=policy_result.reason_code,
    )


def _clarify_result(policy_result: PolicyResultV2) -> RouterResultV2:
    template = _CLARIFICATION_TEMPLATES.get(
        policy_result.reason_code, _GENERIC_CLARIFICATION,
    )
    # For EXPIRED_FOCUS, the focus is known-stale — clear it so
    # the next turn does not use a phantom bind. For other clarify
    # reasons, preserve focus (user may still be talking about the
    # same object).
    focus = (
        CLEAR_FOCUS if policy_result.reason_code == REASON_EXPIRED_FOCUS
        else PRESERVE_FOCUS
    )
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_CLARIFICATION,
        reply_text=template,
        focus_update=focus,
        authorization_intent=None,
        validated_patch=None,
        next_state=NEXT_STATE_AWAIT_USER,
        normalized_intent=policy_result.normalized_intent,
        reason_code=policy_result.reason_code,
    )


def _reject_result(policy_result: PolicyResultV2) -> RouterResultV2:
    template = _REJECTION_TEMPLATES.get(
        policy_result.reason_code, _GENERIC_REJECTION,
    )
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_REJECTION,
        reply_text=template,
        focus_update=PRESERVE_FOCUS,
        authorization_intent=None,
        validated_patch=None,
        next_state=NEXT_STATE_AWAIT_USER,
        normalized_intent=policy_result.normalized_intent,
        reason_code=policy_result.reason_code,
    )


def _reject_generic(
    policy_result: PolicyResultV2, *, override_reason: str,
) -> RouterResultV2:
    """Fallback reject for defensive branches (unknown outcome or
    intent). Uses the override reason so callers get the same
    template family."""
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_REJECTION,
        reply_text=_REJECTION_TEMPLATES.get(
            override_reason, _GENERIC_REJECTION,
        ),
        focus_update=PRESERVE_FOCUS,
        authorization_intent=None,
        validated_patch=None,
        next_state=NEXT_STATE_AWAIT_USER,
        normalized_intent=policy_result.normalized_intent,
        reason_code=override_reason,
    )


def _allow_confirm_draft(policy_result: PolicyResultV2) -> RouterResultV2:
    auth = policy_result.authorization_to_mint
    reply_text = _CONFIRM_ACK_TEMPLATES.get(
        (INTENT_CONFIRM_DRAFT, ACTION_SAVE),
        "Okay.",
    )
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_CONFIRMATION_ACK,
        reply_text=reply_text,
        focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_DRAFT,
            id=policy_result.target_id or "",
        ),
        authorization_intent=auth,
        validated_patch=None,
        next_state=NEXT_STATE_EXECUTE,
        normalized_intent=INTENT_CONFIRM_DRAFT,
        reason_code=policy_result.reason_code,
    )


def _allow_confirm_pending(policy_result: PolicyResultV2) -> RouterResultV2:
    auth = policy_result.authorization_to_mint
    action = auth.action if auth is not None else None
    reply_text = _CONFIRM_ACK_TEMPLATES.get(
        (INTENT_CONFIRM_PENDING_ACTION, action),
        "Okay.",
    )
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_CONFIRMATION_ACK,
        reply_text=reply_text,
        focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_PENDING_ACTION,
            id=policy_result.target_id or "",
        ),
        authorization_intent=auth,
        validated_patch=None,
        next_state=NEXT_STATE_EXECUTE,
        normalized_intent=INTENT_CONFIRM_PENDING_ACTION,
        reason_code=policy_result.reason_code,
    )


def _allow_cancel_draft(policy_result: PolicyResultV2) -> RouterResultV2:
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_CANCELLATION_ACK,
        reply_text=_CANCEL_ACK_TEMPLATE,
        focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_DRAFT,
            id=policy_result.target_id or "",
        ),
        authorization_intent=None,
        validated_patch=None,
        next_state=NEXT_STATE_APPLY_CANCEL,
        normalized_intent=INTENT_CANCEL_DRAFT,
        reason_code=policy_result.reason_code,
    )


def _allow_cancel_pending(policy_result: PolicyResultV2) -> RouterResultV2:
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_CANCELLATION_ACK,
        reply_text=_CANCEL_ACK_TEMPLATE,
        focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_PENDING_ACTION,
            id=policy_result.target_id or "",
        ),
        authorization_intent=None,
        validated_patch=None,
        next_state=NEXT_STATE_APPLY_CANCEL,
        normalized_intent=INTENT_CANCEL_PENDING_ACTION,
        reason_code=policy_result.reason_code,
    )


def _allow_edit_draft(policy_result: PolicyResultV2) -> RouterResultV2:
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_DRAFT_PRESENTATION,
        reply_text=_EDIT_ACK_TEMPLATE,
        focus_update=PRESERVE_FOCUS,
        authorization_intent=None,
        validated_patch=policy_result.validated_patch,
        next_state=NEXT_STATE_APPLY_PATCH,
        normalized_intent=INTENT_EDIT_DRAFT,
        reason_code=policy_result.reason_code,
    )


def _allow_create_draft(policy_result: PolicyResultV2) -> RouterResultV2:
    # A new draft has no id yet — integration will stamp focus
    # after creating it. Router preserves focus for now.
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_DRAFT_PRESENTATION,
        reply_text=_CREATE_ACK_TEMPLATE,
        focus_update=PRESERVE_FOCUS,
        authorization_intent=None,
        validated_patch=policy_result.validated_patch,
        next_state=NEXT_STATE_APPLY_CREATE,
        normalized_intent=INTENT_CREATE_DRAFT,
        reason_code=policy_result.reason_code,
    )


__all__ = [
    # reply kinds
    "REPLY_KIND_NONE", "REPLY_KIND_CLARIFICATION",
    "REPLY_KIND_REJECTION", "REPLY_KIND_CONFIRMATION_ACK",
    "REPLY_KIND_CANCELLATION_ACK", "REPLY_KIND_DRAFT_PRESENTATION",
    "REPLY_KIND_CHAT",
    "REPLY_KINDS",
    # focus actions
    "FOCUS_ACTION_PRESERVE", "FOCUS_ACTION_SET",
    "FOCUS_ACTION_CLEAR", "FOCUS_ACTION_CLEAR_IF_MATCHES",
    "FOCUS_ACTIONS",
    "FocusUpdate", "PRESERVE_FOCUS", "CLEAR_FOCUS",
    # next state
    "NEXT_STATE_AWAIT_USER", "NEXT_STATE_EXECUTE",
    "NEXT_STATE_APPLY_PATCH", "NEXT_STATE_APPLY_CANCEL",
    "NEXT_STATE_APPLY_CREATE", "NEXT_STATE_FALLTHROUGH",
    "NEXT_STATES",
    # dataclass + entry point
    "RouterResultV2",
    "route_v2",
]
