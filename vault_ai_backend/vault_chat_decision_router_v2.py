"""Pure orchestration router for the chat-brain v2 semantic
reasoning path — rev 2 (commit 4a corrections).

Given a validated ``SemanticDecisionV2`` and its
``PolicyResultV2``, the router produces a ``RouterResultV2``
describing WHAT should happen next:

    * reply_kind + reply_text        (deterministic template, empty
                                       for execution-required paths)
    * focus_update                    (IMMEDIATE — applied before
                                       any executor runs)
    * execution_plan                  (optional; carries staged focus
                                       + auth handoff + deferred
                                       reply keys)
    * next_state                      (execute / apply_patch / apply_cancel /
                                       apply_create / fallthrough / await_user)

Scope of this module (commit 4 + 4a)
------------------------------------
This module is the *single owner* of:

    * focus creation, clearing, preservation, and SET intent
    * routing decisions
    * authorization-intent handoff
    * reply-template choice

It has NO side effects: no Redis writes, no
``mint_authorization`` calls, no executor invocations, no
mutation of the decision or policy result. The integration layer
(commit 5) applies the router's declared intent — it never
decides what to focus or when to say "Saved.".

Staged focus + deferred replies (commit 4a rev 7)
-------------------------------------------------
Confirmation / cancel / edit / create paths carry an
``ExecutionPlanV2`` with:

    * ``success_focus_update`` — applied after successful execution
    * ``failure_focus_update`` — applied on failure
    * ``success_reply_key`` / ``failure_reply_key`` — deferred
      template keys the integration looks up via
      ``get_success_reply`` / ``get_failure_reply``

The router's ``RouterResultV2.focus_update`` is the IMMEDIATE
focus decision — typically ``PRESERVE_FOCUS`` for execute paths.
The router's ``RouterResultV2.reply_text`` is ``""`` for
execution-required paths (``reply_kind=REPLY_KIND_EXECUTION_REQUIRED``)
so no "Saved." text ever escapes before the save actually happens.

Reply-text guarantees
---------------------
* Deterministic — depends only on ``(outcome, normalized_intent,
  reason_code)``, plus (for confirms) the action shape.
* Independent of the free-form ``diagnostic`` on
  ``PolicyResultV2``. The diagnostic is dev-facing text only.
* Never inspects the LLM's ``decision.reason`` field.

Fallthrough intents
-------------------
Phase 1 routes ``INTENT_FALLTHROUGH``, ``INTENT_CHAT``, and
``INTENT_ANSWER_QUESTION`` back to the legacy pipeline
(``handled=False``, ``next_state=NEXT_STATE_FALLTHROUGH``).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional

from vault_chat_focus import (
    FOCUS_ACT_ASKED_CLARIFICATION,
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
REPLY_KIND_EXECUTION_REQUIRED:  str = "execution_required"
REPLY_KIND_CHAT:                str = "chat"

REPLY_KINDS: frozenset[str] = frozenset({
    REPLY_KIND_NONE,
    REPLY_KIND_CLARIFICATION,
    REPLY_KIND_REJECTION,
    REPLY_KIND_EXECUTION_REQUIRED,
    REPLY_KIND_CHAT,
})


# =====================================================================
# Focus actions (closed set)
# =====================================================================

FOCUS_ACTION_PRESERVE:           str = "preserve"
FOCUS_ACTION_SET:                str = "set"
FOCUS_ACTION_SET_ON_CREATE:      str = "set_on_create"
FOCUS_ACTION_CLEAR:              str = "clear"
FOCUS_ACTION_CLEAR_IF_MATCHES:   str = "clear_if_matches"

FOCUS_ACTIONS: frozenset[str] = frozenset({
    FOCUS_ACTION_PRESERVE,
    FOCUS_ACTION_SET,
    FOCUS_ACTION_SET_ON_CREATE,
    FOCUS_ACTION_CLEAR,
    FOCUS_ACTION_CLEAR_IF_MATCHES,
})


@dataclass(frozen=True)
class FocusUpdate:
    """Router-declared focus intent. Integration applies it —
    integration NEVER chooses target_kind or assistant_act.

    For ``SET_ON_CREATE``, the router knows the assistant will
    present a to-be-created target of a given kind, but the
    target_id will only exist after integration mints the entity.
    Integration fills in the target_id at apply time.
    """
    action:         str
    kind:           Optional[str] = None
    id:             Optional[str] = None
    assistant_act:  Optional[str] = None

    def __post_init__(self) -> None:
        if self.action not in FOCUS_ACTIONS:
            raise ValueError(f"unknown focus action {self.action!r}")
        if self.action == FOCUS_ACTION_SET:
            if not self.kind or not self.id or not self.assistant_act:
                raise ValueError(
                    "focus set requires kind + id + assistant_act"
                )
        elif self.action == FOCUS_ACTION_SET_ON_CREATE:
            # id is deliberately absent — integration mints it.
            if not self.kind or not self.assistant_act:
                raise ValueError(
                    "focus set_on_create requires kind + assistant_act"
                )
            if self.id is not None:
                raise ValueError(
                    "focus set_on_create must not carry an id "
                    "(integration mints it)"
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

_EXECUTE_NEXT_STATES: frozenset[str] = frozenset({
    NEXT_STATE_EXECUTE,
    NEXT_STATE_APPLY_PATCH,
    NEXT_STATE_APPLY_CANCEL,
    NEXT_STATE_APPLY_CREATE,
})


# =====================================================================
# Action kinds inside ExecutionPlanV2
# =====================================================================

ACTION_KIND_CONFIRM_SAVE:            str = "confirm_save"
ACTION_KIND_CONFIRM_DELETE:          str = "confirm_delete"
ACTION_KIND_CONFIRM_SAVE_ATTACHMENT: str = "confirm_save_attachment"
ACTION_KIND_CANCEL_DRAFT:            str = "cancel_draft"
ACTION_KIND_CANCEL_PENDING:          str = "cancel_pending"
ACTION_KIND_APPLY_EDIT:              str = "apply_edit"
ACTION_KIND_APPLY_CREATE:            str = "apply_create"

ACTION_KINDS: frozenset[str] = frozenset({
    ACTION_KIND_CONFIRM_SAVE,
    ACTION_KIND_CONFIRM_DELETE,
    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
    ACTION_KIND_CANCEL_DRAFT,
    ACTION_KIND_CANCEL_PENDING,
    ACTION_KIND_APPLY_EDIT,
    ACTION_KIND_APPLY_CREATE,
})


# =====================================================================
# Deferred reply templates
#
# Integration calls get_success_reply(key) / get_failure_reply(key)
# AFTER the executor completes. The router itself never sends
# "Saved." text before the save actually happens.
# =====================================================================

_REPLY_KEY_SAVE_DRAFT:       str = "save_draft"
_REPLY_KEY_SAVE_PENDING:     str = "save_pending"
_REPLY_KEY_DELETE_PENDING:   str = "delete_pending"
_REPLY_KEY_SAVE_ATTACHMENT:  str = "save_attachment_pending"
_REPLY_KEY_CANCEL_DRAFT:     str = "cancel_draft"
_REPLY_KEY_CANCEL_PENDING:   str = "cancel_pending"
_REPLY_KEY_APPLY_EDIT:       str = "apply_edit"
_REPLY_KEY_APPLY_CREATE:     str = "apply_create"


SUCCESS_REPLY_TEMPLATES: Mapping[str, str] = MappingProxyType({
    _REPLY_KEY_SAVE_DRAFT:      "Saved your draft to your vault.",
    _REPLY_KEY_SAVE_PENDING:    "Saved.",
    _REPLY_KEY_DELETE_PENDING:  "Deleted.",
    _REPLY_KEY_SAVE_ATTACHMENT: "Saved your file.",
    _REPLY_KEY_CANCEL_DRAFT:    "Okay, cancelled.",
    _REPLY_KEY_CANCEL_PENDING:  "Okay, cancelled.",
    _REPLY_KEY_APPLY_EDIT:      "Updated the draft.",
    _REPLY_KEY_APPLY_CREATE:    "Started a new draft.",
})


FAILURE_REPLY_TEMPLATES: Mapping[str, str] = MappingProxyType({
    _REPLY_KEY_SAVE_DRAFT:      "I couldn't save that right now. Would you like to try again?",
    _REPLY_KEY_SAVE_PENDING:    "I couldn't save that right now. Would you like to try again?",
    _REPLY_KEY_DELETE_PENDING:  "I couldn't delete that right now. Would you like to try again?",
    _REPLY_KEY_SAVE_ATTACHMENT: "I couldn't save your file right now. Would you like to try again?",
    _REPLY_KEY_CANCEL_DRAFT:    "I couldn't cancel that right now.",
    _REPLY_KEY_CANCEL_PENDING:  "I couldn't cancel that right now.",
    _REPLY_KEY_APPLY_EDIT:      "I couldn't update the draft right now.",
    _REPLY_KEY_APPLY_CREATE:    "I couldn't start that draft right now.",
})


REPLY_KEYS: frozenset[str] = frozenset(SUCCESS_REPLY_TEMPLATES.keys())


def get_success_reply(reply_key: str) -> str:
    """Look up the success reply template for a key returned by
    the router in ``ExecutionPlanV2.success_reply_key``. Returns
    an empty string if the key is unknown — integration should
    never see an unknown key from a router that produced the
    plan.
    """
    return SUCCESS_REPLY_TEMPLATES.get(reply_key, "")


def get_failure_reply(reply_key: str) -> str:
    """Look up the failure reply template. Same contract as
    ``get_success_reply``."""
    return FAILURE_REPLY_TEMPLATES.get(reply_key, "")


# =====================================================================
# ExecutionPlanV2
# =====================================================================

@dataclass(frozen=True)
class ExecutionPlanV2:
    """Router's typed description of the execute path.

    The integration layer (commit 5) uses this plan to:
      1. mint an ``AuthorizationRecord`` (only for confirm-*
         action_kinds, i.e. when ``authorization_intent`` is set)
      2. atomically CAS-consume that record
      3. execute the underlying action exactly once (save, delete,
         cancel, or apply-patch)
      4. apply ``success_focus_update`` on success or
         ``failure_focus_update`` on failure
      5. render the reply via ``get_success_reply(success_reply_key)``
         or ``get_failure_reply(failure_reply_key)``

    None of the above steps happen inside the router.
    """
    action_kind:             str
    target_kind:             str
    target_id:               Optional[str]
    authorization_intent:    Optional[AuthorizationIntent]
    validated_patch:         Optional[Mapping[str, FieldPatchItem]]
    success_focus_update:    FocusUpdate
    failure_focus_update:    FocusUpdate
    success_reply_key:       str
    failure_reply_key:       str

    def __post_init__(self) -> None:
        if self.action_kind not in ACTION_KINDS:
            raise ValueError(f"unknown action_kind {self.action_kind!r}")
        if self.success_reply_key not in REPLY_KEYS:
            raise ValueError(
                f"unknown success_reply_key {self.success_reply_key!r}"
            )
        if self.failure_reply_key not in REPLY_KEYS:
            raise ValueError(
                f"unknown failure_reply_key {self.failure_reply_key!r}"
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
# RouterResultV2
# =====================================================================

@dataclass(frozen=True)
class RouterResultV2:
    handled:               bool
    reply_kind:            str
    reply_text:            str
    focus_update:          FocusUpdate                 # IMMEDIATE
    execution_plan:        Optional[ExecutionPlanV2]
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
        # handled=False ⟺ next_state=FALLTHROUGH
        if not self.handled and self.next_state != NEXT_STATE_FALLTHROUGH:
            raise ValueError(
                "handled=False requires next_state=fallthrough"
            )
        if self.handled and self.next_state == NEXT_STATE_FALLTHROUGH:
            raise ValueError(
                "handled=True must not have next_state=fallthrough"
            )
        # Execution-required MUST carry an execution_plan.
        if self.reply_kind == REPLY_KIND_EXECUTION_REQUIRED:
            if self.execution_plan is None:
                raise ValueError(
                    "reply_kind=execution_required requires an "
                    "execution_plan"
                )
            if self.reply_text != "":
                raise ValueError(
                    "reply_kind=execution_required must have empty "
                    "reply_text (deferred to integration)"
                )
        # Non-execute reply_kinds MUST NOT carry an execution_plan.
        if self.reply_kind != REPLY_KIND_EXECUTION_REQUIRED \
                and self.execution_plan is not None:
            raise ValueError(
                f"reply_kind={self.reply_kind!r} must not carry an "
                "execution_plan"
            )
        # execution_plan must appear only on execute-family next_states.
        if self.execution_plan is not None \
                and self.next_state not in _EXECUTE_NEXT_STATES:
            raise ValueError(
                f"execution_plan requires an execute-family "
                f"next_state, got {self.next_state!r}"
            )


# =====================================================================
# Immediate reply templates (clarify + reject)
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


# =====================================================================
# Public entry point
# =====================================================================

def route_v2(
    *, policy_result: PolicyResultV2,
    decision: SemanticDecisionV2,
) -> RouterResultV2:
    """Pure orchestration. Produces a ``RouterResultV2`` from the
    policy result. Never writes to Redis, never mints an
    ``AuthorizationRecord``, never touches focus storage.
    """
    if policy_result.outcome not in OUTCOMES:
        return _reject_generic(
            policy_result, override_reason=REASON_INTENT_UNKNOWN,
        )

    intent = policy_result.normalized_intent

    if intent == INTENT_FALLTHROUGH:
        return _fallthrough_result(policy_result)
    if intent in (INTENT_CHAT, INTENT_ANSWER_QUESTION):
        return _fallthrough_result(policy_result)
    if intent == INTENT_ASK_CLARIFICATION:
        return _clarify_result(policy_result)

    if policy_result.outcome == OUTCOME_CLARIFY:
        return _clarify_result(policy_result)
    if policy_result.outcome == OUTCOME_REJECT:
        return _reject_result(policy_result)

    # OUTCOME_ALLOW for target-carrying intents.
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
# Result builders — clarify / reject / fallthrough
# =====================================================================

def _fallthrough_result(policy_result: PolicyResultV2) -> RouterResultV2:
    return RouterResultV2(
        handled=False,
        reply_kind=REPLY_KIND_NONE,
        reply_text="",
        focus_update=PRESERVE_FOCUS,
        execution_plan=None,
        next_state=NEXT_STATE_FALLTHROUGH,
        normalized_intent=policy_result.normalized_intent,
        reason_code=policy_result.reason_code,
    )


def _clarify_result(policy_result: PolicyResultV2) -> RouterResultV2:
    """Reason-code-driven clarification with a matching focus rule
    (design memo rev 7 table).
    """
    reason = policy_result.reason_code
    reply_text = _CLARIFICATION_TEMPLATES.get(reason, _GENERIC_CLARIFICATION)

    # Determine the focus update per-reason.
    focus_update = _clarify_focus_for(policy_result)

    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_CLARIFICATION,
        reply_text=reply_text,
        focus_update=focus_update,
        execution_plan=None,
        next_state=NEXT_STATE_AWAIT_USER,
        normalized_intent=policy_result.normalized_intent,
        reason_code=reason,
    )


def _clarify_focus_for(policy_result: PolicyResultV2) -> FocusUpdate:
    reason = policy_result.reason_code
    target_kind = policy_result.target_kind
    target_id = policy_result.target_id

    if reason == REASON_EXPIRED_FOCUS:
        return CLEAR_FOCUS
    if reason == REASON_AMBIGUOUS_TARGET:
        # Never pick an arbitrary candidate. Router lacks the snapshot
        # to check whether the existing focus is still one of the
        # candidates, so CLEAR is the safe deterministic default.
        return CLEAR_FOCUS
    if reason in (REASON_TARGET_NOT_FOUND, REASON_TARGET_EXPIRED):
        # Only clear if the current focus actually points at the
        # missing/dead target. Preserves other focus that may still
        # be relevant.
        if target_kind and target_id:
            return FocusUpdate(
                action=FOCUS_ACTION_CLEAR_IF_MATCHES,
                kind=_focus_kind_for(target_kind),
                id=target_id,
            )
        return PRESERVE_FOCUS
    if reason == REASON_TARGET_NOT_FOCUSED:
        # Router asks the user about the specific target they
        # referenced. SET focus to that target with
        # asked_clarification.
        if target_kind and target_id:
            return FocusUpdate(
                action=FOCUS_ACTION_SET,
                kind=_focus_kind_for(target_kind),
                id=target_id,
                assistant_act=FOCUS_ACT_ASKED_CLARIFICATION,
            )
        return PRESERVE_FOCUS
    if reason == REASON_ALLOWED:
        # INTENT_ASK_CLARIFICATION with outcome=allow — model chose
        # to ask. If it named a target, SET focus to that target.
        if target_kind and target_id:
            return FocusUpdate(
                action=FOCUS_ACTION_SET,
                kind=_focus_kind_for(target_kind),
                id=target_id,
                assistant_act=FOCUS_ACT_ASKED_CLARIFICATION,
            )
        return PRESERVE_FOCUS
    # INSUFFICIENT_CONTEXT, LOW_CONFIDENCE, AUTH_MISSING_GRANT, etc.
    return PRESERVE_FOCUS


def _focus_kind_for(policy_target_kind: str) -> str:
    if policy_target_kind == TARGET_KIND_DRAFT:
        return FOCUS_KIND_DRAFT
    if policy_target_kind == TARGET_KIND_PENDING_ACTION:
        return FOCUS_KIND_PENDING_ACTION
    # active_entity or none — clarify handlers won't stamp SET for
    # those. Callers guard the SET emit above.
    return FOCUS_KIND_DRAFT


def _reject_result(policy_result: PolicyResultV2) -> RouterResultV2:
    template = _REJECTION_TEMPLATES.get(
        policy_result.reason_code, _GENERIC_REJECTION,
    )
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_REJECTION,
        reply_text=template,
        focus_update=PRESERVE_FOCUS,
        execution_plan=None,
        next_state=NEXT_STATE_AWAIT_USER,
        normalized_intent=policy_result.normalized_intent,
        reason_code=policy_result.reason_code,
    )


def _reject_generic(
    policy_result: PolicyResultV2, *, override_reason: str,
) -> RouterResultV2:
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_REJECTION,
        reply_text=_REJECTION_TEMPLATES.get(
            override_reason, _GENERIC_REJECTION,
        ),
        focus_update=PRESERVE_FOCUS,
        execution_plan=None,
        next_state=NEXT_STATE_AWAIT_USER,
        normalized_intent=policy_result.normalized_intent,
        reason_code=override_reason,
    )


# =====================================================================
# Result builders — allow paths (produce ExecutionPlanV2)
#
# Each allow builder returns:
#     RouterResultV2.focus_update = PRESERVE_FOCUS (IMMEDIATE)
#     RouterResultV2.reply_kind   = REPLY_KIND_EXECUTION_REQUIRED
#     RouterResultV2.reply_text   = ""
#     RouterResultV2.execution_plan = ExecutionPlanV2(...)
#
# Integration reads the plan's success/failure focus + reply key
# after executing.
# =====================================================================

def _allow_confirm_draft(policy_result: PolicyResultV2) -> RouterResultV2:
    tid = policy_result.target_id or ""
    plan = ExecutionPlanV2(
        action_kind=ACTION_KIND_CONFIRM_SAVE,
        target_kind=TARGET_KIND_DRAFT,
        target_id=tid,
        authorization_intent=policy_result.authorization_to_mint,
        validated_patch=None,
        success_focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_DRAFT, id=tid,
        ),
        failure_focus_update=FocusUpdate(
            action=FOCUS_ACTION_SET,
            kind=FOCUS_KIND_DRAFT, id=tid,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        ),
        success_reply_key=_REPLY_KEY_SAVE_DRAFT,
        failure_reply_key=_REPLY_KEY_SAVE_DRAFT,
    )
    return _execution_required_result(
        policy_result, plan, NEXT_STATE_EXECUTE,
    )


def _allow_confirm_pending(policy_result: PolicyResultV2) -> RouterResultV2:
    tid = policy_result.target_id or ""
    auth = policy_result.authorization_to_mint
    action = auth.action if auth is not None else None
    action_kind, reply_key = _pending_confirm_action_and_key(action)
    plan = ExecutionPlanV2(
        action_kind=action_kind,
        target_kind=TARGET_KIND_PENDING_ACTION,
        target_id=tid,
        authorization_intent=auth,
        validated_patch=None,
        success_focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_PENDING_ACTION, id=tid,
        ),
        failure_focus_update=FocusUpdate(
            action=FOCUS_ACTION_SET,
            kind=FOCUS_KIND_PENDING_ACTION, id=tid,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        ),
        success_reply_key=reply_key,
        failure_reply_key=reply_key,
    )
    return _execution_required_result(
        policy_result, plan, NEXT_STATE_EXECUTE,
    )


def _pending_confirm_action_and_key(action: Optional[str]) -> tuple:
    if action == ACTION_DELETE:
        return ACTION_KIND_CONFIRM_DELETE, _REPLY_KEY_DELETE_PENDING
    if action == ACTION_SAVE_ATTACHMENT:
        return ACTION_KIND_CONFIRM_SAVE_ATTACHMENT, _REPLY_KEY_SAVE_ATTACHMENT
    # ACTION_SAVE fallback for the credential/login-draft/secure-item
    # save-flavored kinds.
    return ACTION_KIND_CONFIRM_SAVE, _REPLY_KEY_SAVE_PENDING


def _allow_cancel_draft(policy_result: PolicyResultV2) -> RouterResultV2:
    tid = policy_result.target_id or ""
    plan = ExecutionPlanV2(
        action_kind=ACTION_KIND_CANCEL_DRAFT,
        target_kind=TARGET_KIND_DRAFT,
        target_id=tid,
        authorization_intent=None,
        validated_patch=None,
        success_focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_DRAFT, id=tid,
        ),
        # Cancel failure: the target still exists; if focus already
        # points at it, keep it there. Preserve.
        failure_focus_update=PRESERVE_FOCUS,
        success_reply_key=_REPLY_KEY_CANCEL_DRAFT,
        failure_reply_key=_REPLY_KEY_CANCEL_DRAFT,
    )
    return _execution_required_result(
        policy_result, plan, NEXT_STATE_APPLY_CANCEL,
    )


def _allow_cancel_pending(policy_result: PolicyResultV2) -> RouterResultV2:
    tid = policy_result.target_id or ""
    plan = ExecutionPlanV2(
        action_kind=ACTION_KIND_CANCEL_PENDING,
        target_kind=TARGET_KIND_PENDING_ACTION,
        target_id=tid,
        authorization_intent=None,
        validated_patch=None,
        success_focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_PENDING_ACTION, id=tid,
        ),
        failure_focus_update=PRESERVE_FOCUS,
        success_reply_key=_REPLY_KEY_CANCEL_PENDING,
        failure_reply_key=_REPLY_KEY_CANCEL_PENDING,
    )
    return _execution_required_result(
        policy_result, plan, NEXT_STATE_APPLY_CANCEL,
    )


def _allow_edit_draft(policy_result: PolicyResultV2) -> RouterResultV2:
    tid = policy_result.target_id or ""
    plan = ExecutionPlanV2(
        action_kind=ACTION_KIND_APPLY_EDIT,
        target_kind=TARGET_KIND_DRAFT,
        target_id=tid,
        authorization_intent=None,
        validated_patch=policy_result.validated_patch,
        # On successful edit, the assistant is presenting the
        # updated draft — SET focus to it.
        success_focus_update=FocusUpdate(
            action=FOCUS_ACTION_SET,
            kind=FOCUS_KIND_DRAFT, id=tid,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        ),
        failure_focus_update=PRESERVE_FOCUS,
        success_reply_key=_REPLY_KEY_APPLY_EDIT,
        failure_reply_key=_REPLY_KEY_APPLY_EDIT,
    )
    return _execution_required_result(
        policy_result, plan, NEXT_STATE_APPLY_PATCH,
    )


def _allow_create_draft(policy_result: PolicyResultV2) -> RouterResultV2:
    # target_id is None here — the draft doesn't exist yet.
    # Integration mints the id and fills it in when applying the
    # SET_ON_CREATE focus intent.
    plan = ExecutionPlanV2(
        action_kind=ACTION_KIND_APPLY_CREATE,
        target_kind=TARGET_KIND_DRAFT,
        target_id=None,
        authorization_intent=None,
        validated_patch=policy_result.validated_patch,
        success_focus_update=FocusUpdate(
            action=FOCUS_ACTION_SET_ON_CREATE,
            kind=FOCUS_KIND_DRAFT,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        ),
        failure_focus_update=PRESERVE_FOCUS,
        success_reply_key=_REPLY_KEY_APPLY_CREATE,
        failure_reply_key=_REPLY_KEY_APPLY_CREATE,
    )
    return _execution_required_result(
        policy_result, plan, NEXT_STATE_APPLY_CREATE,
    )


def _execution_required_result(
    policy_result: PolicyResultV2,
    plan: ExecutionPlanV2,
    next_state: str,
) -> RouterResultV2:
    """All allow-through-integration paths share this shape.

    IMMEDIATE focus is PRESERVE. Reply text is empty. The plan
    carries success/failure focus and deferred reply keys.
    """
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_EXECUTION_REQUIRED,
        reply_text="",
        focus_update=PRESERVE_FOCUS,
        execution_plan=plan,
        next_state=next_state,
        normalized_intent=policy_result.normalized_intent,
        reason_code=policy_result.reason_code,
    )


__all__ = [
    # reply kinds
    "REPLY_KIND_NONE", "REPLY_KIND_CLARIFICATION",
    "REPLY_KIND_REJECTION", "REPLY_KIND_EXECUTION_REQUIRED",
    "REPLY_KIND_CHAT",
    "REPLY_KINDS",
    # focus actions
    "FOCUS_ACTION_PRESERVE", "FOCUS_ACTION_SET",
    "FOCUS_ACTION_SET_ON_CREATE",
    "FOCUS_ACTION_CLEAR", "FOCUS_ACTION_CLEAR_IF_MATCHES",
    "FOCUS_ACTIONS",
    "FocusUpdate", "PRESERVE_FOCUS", "CLEAR_FOCUS",
    # next state
    "NEXT_STATE_AWAIT_USER", "NEXT_STATE_EXECUTE",
    "NEXT_STATE_APPLY_PATCH", "NEXT_STATE_APPLY_CANCEL",
    "NEXT_STATE_APPLY_CREATE", "NEXT_STATE_FALLTHROUGH",
    "NEXT_STATES",
    # execution plan
    "ACTION_KIND_CONFIRM_SAVE", "ACTION_KIND_CONFIRM_DELETE",
    "ACTION_KIND_CONFIRM_SAVE_ATTACHMENT",
    "ACTION_KIND_CANCEL_DRAFT", "ACTION_KIND_CANCEL_PENDING",
    "ACTION_KIND_APPLY_EDIT", "ACTION_KIND_APPLY_CREATE",
    "ACTION_KINDS",
    "ExecutionPlanV2",
    # deferred reply templates
    "SUCCESS_REPLY_TEMPLATES", "FAILURE_REPLY_TEMPLATES",
    "REPLY_KEYS",
    "get_success_reply", "get_failure_reply",
    # main dataclass + entry point
    "RouterResultV2",
    "route_v2",
]
