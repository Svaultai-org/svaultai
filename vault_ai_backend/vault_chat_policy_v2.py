"""Deterministic policy layer for the chat-brain v2 semantic
reasoning path.

The policy is a pure function over an immutable, redacted
snapshot: it takes a ``PolicySnapshotV2`` plus a validated
``SemanticDecisionV2`` and returns a ``PolicyResultV2`` describing
whether — and how — the decision may be acted on. Policy does not
mint authorization records, does not write to Redis, does not
touch drafts or focus, does not call any executor. Those are the
router's responsibility (commit 4).

Two layers, cleanly separated (per design memo rev 5)
-----------------------------------------------------
1. **Structural validation** — done in
   ``vault_chat_semantic_decision_v2`` (commit 2): schema
   version, closed enums, well-formed IDs, internally consistent
   fields.
2. **Snapshot-aware policy validation** — done here: target
   exists NOW, ownership match, kind match, status permits
   operation, focus binding, action↔kind compatibility with the
   actual target, per-``draft_kind`` patch validation.

Reason codes are a closed set (``REASON_*`` constants). Downstream
behavior branches only on ``outcome`` and ``reason_code`` — never
on the free-form ``diagnostic`` field, which is developer-facing
text for logs and test messages.

Security posture
----------------
* Confidence is expressed via the ``vault_chat_confidence_thresholds``
  predicates only — no float literal comparisons in policy code.
* Confidence NEVER overrides: unknown target, wrong ownership,
  action mismatch, invalid state, invalid patch, schema failure.
* Focus expiration always produces ``clarify``, never a permanent
  ``reject``.
* Ambiguity produces ``clarify``, never a "most recent wins"
  heuristic.
* Patch validation is all-or-nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Tuple, Union

from vault_chat_confidence_thresholds import (
    is_valid_confidence,
    may_execute_high_context,
    requires_clarification,
)
from vault_chat_draft import (
    CLEARED,
    Draft,
    DRAFT_LOGIN,
    FIELD_SOURCES,
    FieldFormatError,
    PENDING_GENERATION,
    SOURCE_USER_EXPLICIT,
    STATUS_EDITABLE,
    STATUS_PRESENTED_FOR_CONFIRMATION,
    is_allowed_field,
    schema_for,
    validate_field_value,
)
from vault_chat_focus import (
    ConversationalFocus,
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
    FOCUS_KIND_DRAFT,
    FOCUS_KIND_PENDING_ACTION,
)
from vault_chat_pending_action import (
    DESTRUCTIVE_KINDS,
    KIND_DELETE_SECURE_ITEM,
    KIND_SAVE_ATTACHMENT,
    KIND_SAVE_CREDENTIAL,
    KIND_SAVE_LOGIN_DRAFT,
    KIND_SAVE_SECURE_ITEM,
    PendingAction,
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
    OPERATION_GENERATE_PASSWORD,
    OP_CLEAR,
    OP_REGENERATE,
    OP_REPLACE,
    OP_UNCHANGED,
    SemanticDecisionV2,
    TARGET_KIND_ACTIVE_ENTITY,
    TARGET_KIND_DRAFT,
    TARGET_KIND_NONE,
    TARGET_KIND_PENDING_ACTION,
)


# =====================================================================
# Outcomes and reason codes
# =====================================================================

OUTCOME_ALLOW:    str = "allow"
OUTCOME_CLARIFY:  str = "clarify"
OUTCOME_REJECT:   str = "reject"

OUTCOMES: frozenset[str] = frozenset({
    OUTCOME_ALLOW, OUTCOME_CLARIFY, OUTCOME_REJECT,
})


# Success + fallthrough
REASON_ALLOWED:                              str = "ALLOWED"
REASON_FALLTHROUGH:                          str = "FALLTHROUGH"

# Target lookup / ownership
REASON_TARGET_NOT_FOUND:                     str = "TARGET_NOT_FOUND"
REASON_TARGET_KIND_MISMATCH:                 str = "TARGET_KIND_MISMATCH"
REASON_WRONG_VAULT:                          str = "WRONG_VAULT"
REASON_WRONG_SESSION:                        str = "WRONG_SESSION"
REASON_TARGET_EXPIRED:                       str = "TARGET_EXPIRED"
REASON_TARGET_STATUS_INVALID:                str = "TARGET_STATUS_INVALID"

# Focus + ambiguity
REASON_TARGET_NOT_FOCUSED:                   str = "TARGET_NOT_FOCUSED"
REASON_INSUFFICIENT_CONTEXT:                 str = "INSUFFICIENT_CONTEXT"
REASON_EXPIRED_FOCUS:                        str = "EXPIRED_FOCUS"
REASON_AMBIGUOUS_TARGET:                     str = "AMBIGUOUS_TARGET"

# Confidence
REASON_LOW_CONFIDENCE:                       str = "LOW_CONFIDENCE"

# Patch validation
REASON_PATCH_FIELD_NOT_ALLOWED:              str = "PATCH_FIELD_NOT_ALLOWED"
REASON_PATCH_OP_INVALID:                     str = "PATCH_OP_INVALID"
REASON_PATCH_VALUE_INVALID:                  str = "PATCH_VALUE_INVALID"
REASON_PATCH_REGENERATE_WITHOUT_OP:          str = "PATCH_REGENERATE_WITHOUT_OP"
REASON_PATCH_RAW_PASSWORD:                   str = "PATCH_RAW_PASSWORD"

# Requested operations
REASON_REQUESTED_OP_INVALID_FIELD:           str = "REQUESTED_OP_INVALID_FIELD"

# Authorization
REASON_AUTH_ACTION_MISMATCH:                 str = "AUTH_ACTION_MISMATCH"
REASON_AUTH_SCOPE_MISMATCH:                  str = "AUTH_SCOPE_MISMATCH"
REASON_AUTH_MISSING_GRANT:                   str = "AUTH_MISSING_GRANT"

# Defensive
REASON_SCHEMA_INVALID:                       str = "SCHEMA_INVALID"
REASON_INTENT_UNKNOWN:                       str = "INTENT_UNKNOWN"


REASON_CODES: frozenset[str] = frozenset({
    REASON_ALLOWED,
    REASON_FALLTHROUGH,
    REASON_TARGET_NOT_FOUND,
    REASON_TARGET_KIND_MISMATCH,
    REASON_WRONG_VAULT,
    REASON_WRONG_SESSION,
    REASON_TARGET_EXPIRED,
    REASON_TARGET_STATUS_INVALID,
    REASON_TARGET_NOT_FOCUSED,
    REASON_INSUFFICIENT_CONTEXT,
    REASON_EXPIRED_FOCUS,
    REASON_AMBIGUOUS_TARGET,
    REASON_LOW_CONFIDENCE,
    REASON_PATCH_FIELD_NOT_ALLOWED,
    REASON_PATCH_OP_INVALID,
    REASON_PATCH_VALUE_INVALID,
    REASON_PATCH_REGENERATE_WITHOUT_OP,
    REASON_PATCH_RAW_PASSWORD,
    REASON_REQUESTED_OP_INVALID_FIELD,
    REASON_AUTH_ACTION_MISMATCH,
    REASON_AUTH_SCOPE_MISMATCH,
    REASON_AUTH_MISSING_GRANT,
    REASON_SCHEMA_INVALID,
    REASON_INTENT_UNKNOWN,
})


# =====================================================================
# Action <-> PendingAction.kind mapping
# =====================================================================

# Which action is compatible with which pending kind. This is a
# narrower map than vault_chat_authorization_record's
# target_kind-level compatibility.
_PENDING_KIND_TO_ACTION: Mapping[str, str] = MappingProxyType({
    KIND_DELETE_SECURE_ITEM: ACTION_DELETE,
    KIND_SAVE_ATTACHMENT:    ACTION_SAVE_ATTACHMENT,
    KIND_SAVE_CREDENTIAL:    ACTION_SAVE,
    KIND_SAVE_LOGIN_DRAFT:   ACTION_SAVE,
    KIND_SAVE_SECURE_ITEM:   ACTION_SAVE,
})


def _action_matches_pending_kind(action: str, kind: str) -> bool:
    return _PENDING_KIND_TO_ACTION.get(kind) == action


# =====================================================================
# Phase-1 draft kind assumption
# =====================================================================

# Phase 1 supports only DRAFT_LOGIN. Adding a new draft kind is a
# multi-file change (schema in vault_chat_draft, extractor, tests
# here, and a scope decision in the memo). The create_draft path
# uses this constant; expanding it is a policy change.
_PHASE_1_CREATE_DRAFT_KIND: str = DRAFT_LOGIN


# =====================================================================
# Dataclasses
# =====================================================================

@dataclass(frozen=True)
class AuthorizationIntent:
    """A validated request to mint an ``AuthorizationRecord`` — but
    NOT the record itself. The router (commit 4) is the only
    caller that actually calls ``mint_authorization``.

    Fields chosen to match ``AuthorizationRecord`` so the router
    can plumb them through without additional lookups.
    """
    target_kind:                     str
    target_id:                       str
    action:                          str
    authorizing_user_turn_id:        str
    preceding_assistant_turn_id:     str
    confidence:                      float

    def __post_init__(self) -> None:
        if not is_valid_confidence(self.confidence):
            raise ValueError("authorization confidence must be in [0, 1]")
        if not isinstance(self.authorizing_user_turn_id, str):
            raise TypeError("authorizing_user_turn_id must be a string")


@dataclass(frozen=True)
class PolicyResultV2:
    allowed:                bool
    outcome:                str
    normalized_intent:      str
    target_kind:            Optional[str]
    target_id:              Optional[str]
    authorization_to_mint:  Optional[AuthorizationIntent]
    validated_patch:        Optional[Mapping[str, FieldPatchItem]]
    reason_code:            str
    diagnostic:             str = ""

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {self.outcome!r}")
        if self.reason_code not in REASON_CODES:
            raise ValueError(f"unknown reason_code {self.reason_code!r}")
        # allowed ⟺ outcome == "allow"
        if self.allowed != (self.outcome == OUTCOME_ALLOW):
            raise ValueError("allowed must be True iff outcome=='allow'")
        # authorization_to_mint requires an allow outcome
        if self.authorization_to_mint is not None and self.outcome != OUTCOME_ALLOW:
            raise ValueError(
                "authorization_to_mint requires outcome=='allow'"
            )
        # validated_patch requires an allow outcome
        if self.validated_patch is not None and self.outcome != OUTCOME_ALLOW:
            raise ValueError(
                "validated_patch requires outcome=='allow'"
            )
        # Freeze the patch mapping
        if self.validated_patch is not None and not isinstance(
            self.validated_patch, MappingProxyType,
        ):
            object.__setattr__(
                self, "validated_patch",
                MappingProxyType(dict(self.validated_patch)),
            )


@dataclass(frozen=True)
class PolicySnapshotV2:
    """Immutable input to ``authorize_v2``.

    Callers (integration in commit 5) build this from a
    ``TurnSnapshot`` + live Redis reads. This module never
    reads Redis or mutates state.
    """
    vault_id:                    str
    session_id:                  Optional[str]
    current_user_turn_id:        str
    preceding_assistant_turn_id: str
    now:                         float
    active_drafts:               Tuple[Draft, ...] = ()
    pending_actions:             Tuple[PendingAction, ...] = ()
    focus:                       Optional[ConversationalFocus] = None

    def __post_init__(self) -> None:
        if not self.vault_id:
            raise ValueError("vault_id required")
        if not isinstance(self.current_user_turn_id, str):
            raise TypeError("current_user_turn_id must be a string")
        if not isinstance(self.preceding_assistant_turn_id, str):
            raise TypeError("preceding_assistant_turn_id must be a string")

    def known_draft_ids(self) -> frozenset[str]:
        return frozenset(d.draft_id for d in self.active_drafts)

    def known_pending_action_ids(self) -> frozenset[str]:
        return frozenset(a.action_id for a in self.pending_actions)

    def find_draft(self, draft_id: str) -> Optional[Draft]:
        for d in self.active_drafts:
            if d.draft_id == draft_id:
                return d
        return None

    def find_pending(self, action_id: str) -> Optional[PendingAction]:
        for a in self.pending_actions:
            if a.action_id == action_id:
                return a
        return None

    def count_drafts_of_kind(self, draft_kind: str) -> int:
        return sum(1 for d in self.active_drafts if d.draft_kind == draft_kind)

    def count_pending_of_kind(self, kind: str) -> int:
        return sum(1 for a in self.pending_actions if a.kind == kind)


# =====================================================================
# Result factories
# =====================================================================

def _allow(intent: str, *, reason: str = REASON_ALLOWED,
           target_kind: Optional[str] = None,
           target_id: Optional[str] = None,
           authorization: Optional[AuthorizationIntent] = None,
           patch: Optional[Mapping[str, FieldPatchItem]] = None,
           diagnostic: str = "") -> PolicyResultV2:
    return PolicyResultV2(
        allowed=True,
        outcome=OUTCOME_ALLOW,
        normalized_intent=intent,
        target_kind=target_kind,
        target_id=target_id,
        authorization_to_mint=authorization,
        validated_patch=patch,
        reason_code=reason,
        diagnostic=diagnostic,
    )


def _clarify(intent: str, reason: str, *,
             target_kind: Optional[str] = None,
             target_id: Optional[str] = None,
             diagnostic: str = "") -> PolicyResultV2:
    return PolicyResultV2(
        allowed=False,
        outcome=OUTCOME_CLARIFY,
        normalized_intent=intent,
        target_kind=target_kind,
        target_id=target_id,
        authorization_to_mint=None,
        validated_patch=None,
        reason_code=reason,
        diagnostic=diagnostic,
    )


def _reject(intent: str, reason: str, *,
            target_kind: Optional[str] = None,
            target_id: Optional[str] = None,
            diagnostic: str = "") -> PolicyResultV2:
    return PolicyResultV2(
        allowed=False,
        outcome=OUTCOME_REJECT,
        normalized_intent=intent,
        target_kind=target_kind,
        target_id=target_id,
        authorization_to_mint=None,
        validated_patch=None,
        reason_code=reason,
        diagnostic=diagnostic,
    )


# =====================================================================
# Public entry point
# =====================================================================

def authorize_v2(
    *, snapshot: PolicySnapshotV2, decision: SemanticDecisionV2,
) -> PolicyResultV2:
    """Pure policy over an immutable, redacted snapshot. No side
    effects. Returns a ``PolicyResultV2`` describing whether — and
    how — the decision may be acted on.

    Preconditions:
        * ``decision`` MUST already have passed structural validation
          (i.e., come from
          ``vault_chat_semantic_decision_v2.parse_semantic_decision_v2``
          or ``validate_semantic_decision_v2``). If it hasn't, the
          policy still runs but may produce ``SCHEMA_INVALID``.
    """
    intent = decision.intent

    # Fallthrough — the pipeline handles this turn; policy passes it
    # through unchanged.
    if intent == INTENT_FALLTHROUGH:
        return _allow(intent, reason=REASON_FALLTHROUGH)

    # No-target intents: chat, answer_question, ask_clarification.
    # These do not carry authorization or field mutations; they are
    # simple assistant-produced replies. Policy passes them.
    if intent in (INTENT_CHAT, INTENT_ANSWER_QUESTION,
                   INTENT_ASK_CLARIFICATION):
        return _allow(intent)

    # Target-carrying intents.
    if intent == INTENT_CREATE_DRAFT:
        return _authorize_create_draft(snapshot, decision)
    if intent == INTENT_EDIT_DRAFT:
        return _authorize_edit_draft(snapshot, decision)
    if intent == INTENT_CONFIRM_DRAFT:
        return _authorize_confirm_draft(snapshot, decision)
    if intent == INTENT_CANCEL_DRAFT:
        return _authorize_cancel_draft(snapshot, decision)
    if intent == INTENT_CONFIRM_PENDING_ACTION:
        return _authorize_confirm_pending(snapshot, decision)
    if intent == INTENT_CANCEL_PENDING_ACTION:
        return _authorize_cancel_pending(snapshot, decision)

    # Defensive — should not reach here on a validated decision.
    return _reject(intent, REASON_INTENT_UNKNOWN,
                   diagnostic=f"unhandled intent {intent!r}")


# =====================================================================
# Intent handlers
# =====================================================================

def _authorize_create_draft(
    snapshot: PolicySnapshotV2, decision: SemanticDecisionV2,
) -> PolicyResultV2:
    # A create request does not reference a live target; target.kind
    # should be "none".
    if decision.target.kind != TARGET_KIND_NONE:
        return _reject(
            INTENT_CREATE_DRAFT, REASON_TARGET_KIND_MISMATCH,
            diagnostic=(
                f"create_draft target.kind must be 'none', got "
                f"{decision.target.kind!r}"
            ),
        )

    # Phase 1 = DRAFT_LOGIN only.
    patch_result = _validate_new_patch(
        draft_kind=_PHASE_1_CREATE_DRAFT_KIND,
        field_patch=dict(decision.field_patch),
        requested_operations=decision.requested_operations,
    )
    if isinstance(patch_result, PolicyResultV2):
        return patch_result  # already a reject
    validated = patch_result  # dict[str, FieldPatchItem]

    return _allow(
        INTENT_CREATE_DRAFT,
        target_kind=None,
        target_id=None,
        authorization=None,
        patch=MappingProxyType(validated),
    )


def _authorize_edit_draft(
    snapshot: PolicySnapshotV2, decision: SemanticDecisionV2,
) -> PolicyResultV2:
    if decision.target.kind != TARGET_KIND_DRAFT:
        return _reject(
            INTENT_EDIT_DRAFT, REASON_TARGET_KIND_MISMATCH,
            diagnostic="edit_draft requires target.kind='draft'",
        )
    target = snapshot.find_draft(decision.target.id)  # type: ignore[arg-type]
    if target is None:
        # Case A: model referenced an ID that does not exist. Not
        # an authorization failure — a conversational mismatch.
        # Ask the user to clarify or restart. Case B (ID exists but
        # belongs to a different vault/session) is caught below by
        # the ownership check and remains a hard reject.
        return _clarify(
            INTENT_EDIT_DRAFT, REASON_TARGET_NOT_FOUND,
            target_kind=TARGET_KIND_DRAFT,
            target_id=decision.target.id,
        )
    ownership = _check_ownership(target, snapshot, INTENT_EDIT_DRAFT)
    if ownership is not None:
        return ownership
    if target.is_expired(snapshot.now):
        return _clarify(
            INTENT_EDIT_DRAFT, REASON_TARGET_EXPIRED,
            target_kind=TARGET_KIND_DRAFT, target_id=target.draft_id,
        )
    # Only EDITABLE drafts may be edited. Anything else — awaiting
    # confirmation, authorized, executing, consumed, cancelled —
    # rejects.
    if target.status != STATUS_EDITABLE:
        return _reject(
            INTENT_EDIT_DRAFT, REASON_TARGET_STATUS_INVALID,
            target_kind=TARGET_KIND_DRAFT, target_id=target.draft_id,
            diagnostic=f"draft status is {target.status!r}",
        )

    patch_result = _validate_edit_patch(
        target=target,
        field_patch=dict(decision.field_patch),
        requested_operations=decision.requested_operations,
    )
    if isinstance(patch_result, PolicyResultV2):
        return patch_result
    validated = patch_result

    return _allow(
        INTENT_EDIT_DRAFT,
        target_kind=TARGET_KIND_DRAFT,
        target_id=target.draft_id,
        authorization=None,
        patch=MappingProxyType(validated),
    )


def _authorize_confirm_draft(
    snapshot: PolicySnapshotV2, decision: SemanticDecisionV2,
) -> PolicyResultV2:
    if decision.target.kind != TARGET_KIND_DRAFT:
        return _reject(
            INTENT_CONFIRM_DRAFT, REASON_TARGET_KIND_MISMATCH,
            diagnostic="confirm_draft requires target.kind='draft'",
        )
    target = snapshot.find_draft(decision.target.id)  # type: ignore[arg-type]
    if target is None:
        # Case A: unknown ID → clarify, not reject.
        return _clarify(
            INTENT_CONFIRM_DRAFT, REASON_TARGET_NOT_FOUND,
            target_kind=TARGET_KIND_DRAFT,
            target_id=decision.target.id,
        )
    ownership = _check_ownership(target, snapshot, INTENT_CONFIRM_DRAFT)
    if ownership is not None:
        return ownership
    if target.is_expired(snapshot.now):
        return _clarify(
            INTENT_CONFIRM_DRAFT, REASON_TARGET_EXPIRED,
            target_kind=TARGET_KIND_DRAFT, target_id=target.draft_id,
        )
    # Only EDITABLE or PRESENTED_FOR_CONFIRMATION drafts may be
    # confirmed. AUTHORIZED_ONCE/EXECUTING/CONSUMED/CANCELLED reject.
    if target.status not in (
        STATUS_EDITABLE, STATUS_PRESENTED_FOR_CONFIRMATION,
    ):
        return _reject(
            INTENT_CONFIRM_DRAFT, REASON_TARGET_STATUS_INVALID,
            target_kind=TARGET_KIND_DRAFT, target_id=target.draft_id,
            diagnostic=f"draft status is {target.status!r}",
        )

    # Authorization must have been granted by the model.
    if not decision.authorization.granted:
        return _clarify(
            INTENT_CONFIRM_DRAFT, REASON_AUTH_MISSING_GRANT,
            target_kind=TARGET_KIND_DRAFT, target_id=target.draft_id,
            diagnostic="confirm_draft without authorization.granted=true",
        )
    # Scope: action must be 'save' and target_id must match (both
    # structurally validated in commit 2, but re-check for defense).
    scope = decision.authorization.scope
    if scope is None or scope.target_id != target.draft_id:
        return _reject(
            INTENT_CONFIRM_DRAFT, REASON_AUTH_SCOPE_MISMATCH,
            target_kind=TARGET_KIND_DRAFT, target_id=target.draft_id,
        )
    if scope.action != ACTION_SAVE:
        return _reject(
            INTENT_CONFIRM_DRAFT, REASON_AUTH_ACTION_MISMATCH,
            target_kind=TARGET_KIND_DRAFT, target_id=target.draft_id,
            diagnostic=(
                f"confirm_draft requires action=save, got {scope.action!r}"
            ),
        )

    # Focus binding (with high-context bypass).
    focus_check = _check_focus_binding(
        snapshot=snapshot, decision=decision,
        target_kind=TARGET_KIND_DRAFT,
        target_id=target.draft_id,
        candidate_count=snapshot.count_drafts_of_kind(target.draft_kind),
    )
    if focus_check is not None:
        return focus_check

    # Confidence check — non-destructive threshold.
    if requires_clarification(decision.confidence, destructive=False):
        return _clarify(
            INTENT_CONFIRM_DRAFT, REASON_LOW_CONFIDENCE,
            target_kind=TARGET_KIND_DRAFT, target_id=target.draft_id,
        )

    auth_intent = AuthorizationIntent(
        target_kind=TARGET_KIND_DRAFT,
        target_id=target.draft_id,
        action=ACTION_SAVE,
        authorizing_user_turn_id=snapshot.current_user_turn_id,
        preceding_assistant_turn_id=_preceding_assistant_turn(
            snapshot, target_kind=FOCUS_KIND_DRAFT,
            target_id=target.draft_id,
        ),
        confidence=float(decision.confidence),
    )
    return _allow(
        INTENT_CONFIRM_DRAFT,
        target_kind=TARGET_KIND_DRAFT,
        target_id=target.draft_id,
        authorization=auth_intent,
    )


def _authorize_cancel_draft(
    snapshot: PolicySnapshotV2, decision: SemanticDecisionV2,
) -> PolicyResultV2:
    if decision.target.kind != TARGET_KIND_DRAFT:
        return _reject(
            INTENT_CANCEL_DRAFT, REASON_TARGET_KIND_MISMATCH,
            diagnostic="cancel_draft requires target.kind='draft'",
        )
    target = snapshot.find_draft(decision.target.id)  # type: ignore[arg-type]
    if target is None:
        # Case A: unknown ID → clarify. Cancelling something that
        # is not there is a no-op from the user's perspective, but
        # asking for confirmation is safer than a silent success.
        return _clarify(
            INTENT_CANCEL_DRAFT, REASON_TARGET_NOT_FOUND,
            target_kind=TARGET_KIND_DRAFT,
            target_id=decision.target.id,
        )
    ownership = _check_ownership(target, snapshot, INTENT_CANCEL_DRAFT)
    if ownership is not None:
        return ownership
    # Cancel does not need focus binding or a confidence threshold —
    # user is backing out; no authorization record is minted.
    return _allow(
        INTENT_CANCEL_DRAFT,
        target_kind=TARGET_KIND_DRAFT,
        target_id=target.draft_id,
        authorization=None,
    )


def _authorize_confirm_pending(
    snapshot: PolicySnapshotV2, decision: SemanticDecisionV2,
) -> PolicyResultV2:
    if decision.target.kind != TARGET_KIND_PENDING_ACTION:
        return _reject(
            INTENT_CONFIRM_PENDING_ACTION, REASON_TARGET_KIND_MISMATCH,
            diagnostic=(
                "confirm_pending_action requires "
                "target.kind='pending_action'"
            ),
        )
    target = snapshot.find_pending(decision.target.id)  # type: ignore[arg-type]
    if target is None:
        # Case A: unknown ID → clarify, not reject.
        return _clarify(
            INTENT_CONFIRM_PENDING_ACTION, REASON_TARGET_NOT_FOUND,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=decision.target.id,
        )
    ownership = _check_ownership(target, snapshot, INTENT_CONFIRM_PENDING_ACTION)
    if ownership is not None:
        return ownership
    if target.is_expired(snapshot.now):
        return _clarify(
            INTENT_CONFIRM_PENDING_ACTION, REASON_TARGET_EXPIRED,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=target.action_id,
        )
    if not decision.authorization.granted:
        return _clarify(
            INTENT_CONFIRM_PENDING_ACTION, REASON_AUTH_MISSING_GRANT,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=target.action_id,
        )
    scope = decision.authorization.scope
    if scope is None or scope.target_id != target.action_id:
        return _reject(
            INTENT_CONFIRM_PENDING_ACTION, REASON_AUTH_SCOPE_MISMATCH,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=target.action_id,
        )
    # Action must match the pending kind exactly.
    if scope.action is None or not _action_matches_pending_kind(
        scope.action, target.kind,
    ):
        return _reject(
            INTENT_CONFIRM_PENDING_ACTION, REASON_AUTH_ACTION_MISMATCH,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=target.action_id,
            diagnostic=(
                f"action {scope.action!r} incompatible with "
                f"pending kind {target.kind!r}"
            ),
        )

    is_destructive = target.kind in DESTRUCTIVE_KINDS

    focus_check = _check_focus_binding(
        snapshot=snapshot, decision=decision,
        target_kind=TARGET_KIND_PENDING_ACTION,
        target_id=target.action_id,
        candidate_count=snapshot.count_pending_of_kind(target.kind),
    )
    if focus_check is not None:
        return focus_check

    if requires_clarification(decision.confidence,
                              destructive=is_destructive):
        return _clarify(
            INTENT_CONFIRM_PENDING_ACTION, REASON_LOW_CONFIDENCE,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=target.action_id,
        )

    auth_intent = AuthorizationIntent(
        target_kind=TARGET_KIND_PENDING_ACTION,
        target_id=target.action_id,
        action=scope.action,
        authorizing_user_turn_id=snapshot.current_user_turn_id,
        preceding_assistant_turn_id=_preceding_assistant_turn(
            snapshot, target_kind=FOCUS_KIND_PENDING_ACTION,
            target_id=target.action_id,
        ),
        confidence=float(decision.confidence),
    )
    return _allow(
        INTENT_CONFIRM_PENDING_ACTION,
        target_kind=TARGET_KIND_PENDING_ACTION,
        target_id=target.action_id,
        authorization=auth_intent,
    )


def _authorize_cancel_pending(
    snapshot: PolicySnapshotV2, decision: SemanticDecisionV2,
) -> PolicyResultV2:
    if decision.target.kind != TARGET_KIND_PENDING_ACTION:
        return _reject(
            INTENT_CANCEL_PENDING_ACTION, REASON_TARGET_KIND_MISMATCH,
            diagnostic=(
                "cancel_pending_action requires "
                "target.kind='pending_action'"
            ),
        )
    target = snapshot.find_pending(decision.target.id)  # type: ignore[arg-type]
    if target is None:
        # Case A: unknown ID → clarify.
        return _clarify(
            INTENT_CANCEL_PENDING_ACTION, REASON_TARGET_NOT_FOUND,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=decision.target.id,
        )
    ownership = _check_ownership(target, snapshot, INTENT_CANCEL_PENDING_ACTION)
    if ownership is not None:
        return ownership
    return _allow(
        INTENT_CANCEL_PENDING_ACTION,
        target_kind=TARGET_KIND_PENDING_ACTION,
        target_id=target.action_id,
        authorization=None,
    )


# =====================================================================
# Ownership + focus + patch helpers
# =====================================================================

def _check_ownership(
    target: Union[Draft, PendingAction],
    snapshot: PolicySnapshotV2,
    intent: str,
) -> Optional[PolicyResultV2]:
    """Vault + session ownership check. Returns a rejection or None
    if ownership is OK.
    """
    if target.vault_id != snapshot.vault_id:
        target_kind = (
            TARGET_KIND_DRAFT if isinstance(target, Draft)
            else TARGET_KIND_PENDING_ACTION
        )
        target_id = (
            target.draft_id if isinstance(target, Draft)
            else target.action_id
        )
        return _reject(
            intent, REASON_WRONG_VAULT,
            target_kind=target_kind, target_id=target_id,
        )
    stored_session = target.session_id
    # An unstamped (session_id=None) record is visible to any reader —
    # matches the existing arbiter rule. A stamped record must match
    # the reader's session.
    if stored_session is not None and stored_session != snapshot.session_id:
        target_kind = (
            TARGET_KIND_DRAFT if isinstance(target, Draft)
            else TARGET_KIND_PENDING_ACTION
        )
        target_id = (
            target.draft_id if isinstance(target, Draft)
            else target.action_id
        )
        return _reject(
            intent, REASON_WRONG_SESSION,
            target_kind=target_kind, target_id=target_id,
        )
    return None


def _check_focus_binding(
    *,
    snapshot:        PolicySnapshotV2,
    decision:        SemanticDecisionV2,
    target_kind:     str,
    target_id:       str,
    candidate_count: int,
) -> Optional[PolicyResultV2]:
    """Return a clarify result if focus binding fails; None if OK.

    Logic:
        * If focus is bound to (target_kind, target_id) AND focus is
          live AND focus.assistant_act == PRESENTED_FOR_CONFIRMATION →
          binding satisfied.
        * Else if confidence is high-context AND the specific target
          is uniquely identified (only one candidate of that kind
          exists) → binding bypassed.
        * Else → clarify with a specific reason.

    ``candidate_count`` is the number of live targets of the same
    kind in the snapshot (used to detect ambiguity for the
    high-context bypass case).
    """
    focus = snapshot.focus
    focus_kind = (
        FOCUS_KIND_DRAFT if target_kind == TARGET_KIND_DRAFT
        else FOCUS_KIND_PENDING_ACTION
    )

    if focus is not None and not focus.is_expired(snapshot.now) \
            and focus.targets(focus_kind, target_id) \
            and focus.assistant_act == FOCUS_ACT_PRESENTED_FOR_CONFIRMATION:
        return None   # bound

    # Focus not bound. Consider high-context bypass.
    if may_execute_high_context(decision.confidence):
        # Bypass allowed only when the specific target is
        # unambiguous (there is only one live target of that kind).
        if candidate_count <= 1:
            return None   # bypass
        # Multiple candidates of this kind exist — cannot bypass;
        # need focus to disambiguate.
        return _clarify(
            decision.intent, REASON_AMBIGUOUS_TARGET,
            target_kind=target_kind, target_id=target_id,
        )

    # Low-context: focus binding required. Report the most-specific
    # reason.
    if focus is None:
        return _clarify(
            decision.intent, REASON_INSUFFICIENT_CONTEXT,
            target_kind=target_kind, target_id=target_id,
        )
    if focus.is_expired(snapshot.now):
        return _clarify(
            decision.intent, REASON_EXPIRED_FOCUS,
            target_kind=target_kind, target_id=target_id,
        )
    return _clarify(
        decision.intent, REASON_TARGET_NOT_FOCUSED,
        target_kind=target_kind, target_id=target_id,
    )


def _preceding_assistant_turn(
    snapshot: PolicySnapshotV2, *,
    target_kind: str, target_id: str,
) -> str:
    """Return the id of the preceding assistant turn to bind the
    authorization to. Prefers the focus's assistant_turn_id when
    focus targets the same object; else falls back to the
    snapshot's ``preceding_assistant_turn_id``.
    """
    focus = snapshot.focus
    if focus is not None and focus.targets(target_kind, target_id):
        return focus.assistant_turn_id
    return snapshot.preceding_assistant_turn_id


# =====================================================================
# Patch validation
# =====================================================================

def _validate_new_patch(
    *, draft_kind: str,
    field_patch: dict[str, FieldPatchItem],
    requested_operations: Tuple,
) -> Union[dict[str, FieldPatchItem], PolicyResultV2]:
    """Validate a patch for a NEW draft (create_draft). Returns
    either a cleaned patch dict or a rejection ``PolicyResultV2``.
    """
    # Same rules as edit patch for the field-level checks; the
    # difference is that for create there is no existing draft to
    # bound status/source against — the caller (router) will
    # instantiate a fresh Draft and apply the patch via
    # vault_chat_draft_merge with SOURCE_USER_EXPLICIT.
    return _validate_patch_common(
        intent=INTENT_CREATE_DRAFT,
        draft_kind=draft_kind,
        field_patch=field_patch,
        requested_operations=requested_operations,
    )


def _validate_edit_patch(
    *, target: Draft,
    field_patch: dict[str, FieldPatchItem],
    requested_operations: Tuple,
) -> Union[dict[str, FieldPatchItem], PolicyResultV2]:
    """Validate a patch for an EDIT of an existing draft."""
    return _validate_patch_common(
        intent=INTENT_EDIT_DRAFT,
        draft_kind=target.draft_kind,
        field_patch=field_patch,
        requested_operations=requested_operations,
        existing_draft=target,
    )


def _validate_patch_common(
    *, intent: str,
    draft_kind: str,
    field_patch: dict[str, FieldPatchItem],
    requested_operations: Tuple,
    existing_draft: Optional[Draft] = None,
) -> Union[dict[str, FieldPatchItem], PolicyResultV2]:
    schema = schema_for(draft_kind)

    # Check every requested_operation's target field is allowed.
    for i, op in enumerate(requested_operations):
        if op.field not in schema:
            return _reject(
                intent, REASON_REQUESTED_OP_INVALID_FIELD,
                diagnostic=(
                    f"requested_operations[{i}] targets unknown "
                    f"field {op.field!r} for draft_kind {draft_kind!r}"
                ),
            )
        # For generate_password, the field must allow regenerate.
        if op.operation == OPERATION_GENERATE_PASSWORD:
            spec = schema[op.field]
            if not spec.allows_regenerate:
                return _reject(
                    intent, REASON_REQUESTED_OP_INVALID_FIELD,
                    diagnostic=(
                        f"generate_password on field {op.field!r} "
                        "which does not allow regenerate"
                    ),
                )

    regenerate_fields_in_ops = frozenset(
        op.field for op in requested_operations
        if op.operation == OPERATION_GENERATE_PASSWORD
    )

    validated: dict[str, FieldPatchItem] = {}
    for name, item in field_patch.items():
        if not is_allowed_field(draft_kind, name):
            return _reject(
                intent, REASON_PATCH_FIELD_NOT_ALLOWED,
                diagnostic=(
                    f"field {name!r} not allowed for draft_kind "
                    f"{draft_kind!r}"
                ),
            )
        spec = schema[name]
        if item.op == OP_UNCHANGED:
            validated[name] = item
            continue
        if item.op == OP_CLEAR:
            if spec.required:
                return _reject(
                    intent, REASON_PATCH_OP_INVALID,
                    diagnostic=(
                        f"cannot clear required field {name!r}"
                    ),
                )
            validated[name] = item
            continue
        if item.op == OP_REGENERATE:
            if not spec.allows_regenerate:
                return _reject(
                    intent, REASON_PATCH_OP_INVALID,
                    diagnostic=(
                        f"field {name!r} does not allow regenerate"
                    ),
                )
            if name not in regenerate_fields_in_ops:
                return _reject(
                    intent, REASON_PATCH_REGENERATE_WITHOUT_OP,
                    diagnostic=(
                        f"op=regenerate on {name!r} requires a "
                        "matching requested_operations entry"
                    ),
                )
            # In edit_draft mode, refuse to regenerate a field
            # currently sourced user_explicit. The merge layer
            # enforces this too, but rejecting here surfaces the
            # right reason code without partial validation.
            if existing_draft is not None:
                current = existing_draft.fields.get(name)
                if current is not None \
                        and current.source == SOURCE_USER_EXPLICIT:
                    return _reject(
                        intent, REASON_PATCH_OP_INVALID,
                        diagnostic=(
                            f"cannot regenerate {name!r}: current "
                            "value is user_explicit"
                        ),
                    )
            validated[name] = item
            continue
        # op == OP_REPLACE
        try:
            validate_field_value(draft_kind, name, item.value)
        except FieldFormatError as exc:
            # Special-case password_ref → a raw-password-shaped
            # string is exactly what the invariant "no raw password
            # in patch" is about. Reason code is more specific.
            if name == "password_ref":
                return _reject(
                    intent, REASON_PATCH_RAW_PASSWORD,
                    diagnostic=str(exc),
                )
            return _reject(
                intent, REASON_PATCH_VALUE_INVALID,
                diagnostic=f"field {name!r}: {exc}",
            )
        validated[name] = item

    return validated


__all__ = [
    # Outcomes
    "OUTCOME_ALLOW", "OUTCOME_CLARIFY", "OUTCOME_REJECT", "OUTCOMES",
    # Reason codes
    "REASON_ALLOWED", "REASON_FALLTHROUGH",
    "REASON_TARGET_NOT_FOUND", "REASON_TARGET_KIND_MISMATCH",
    "REASON_WRONG_VAULT", "REASON_WRONG_SESSION",
    "REASON_TARGET_EXPIRED", "REASON_TARGET_STATUS_INVALID",
    "REASON_TARGET_NOT_FOCUSED", "REASON_INSUFFICIENT_CONTEXT",
    "REASON_EXPIRED_FOCUS", "REASON_AMBIGUOUS_TARGET",
    "REASON_LOW_CONFIDENCE",
    "REASON_PATCH_FIELD_NOT_ALLOWED", "REASON_PATCH_OP_INVALID",
    "REASON_PATCH_VALUE_INVALID", "REASON_PATCH_REGENERATE_WITHOUT_OP",
    "REASON_PATCH_RAW_PASSWORD",
    "REASON_REQUESTED_OP_INVALID_FIELD",
    "REASON_AUTH_ACTION_MISMATCH", "REASON_AUTH_SCOPE_MISMATCH",
    "REASON_AUTH_MISSING_GRANT",
    "REASON_SCHEMA_INVALID", "REASON_INTENT_UNKNOWN",
    "REASON_CODES",
    # Dataclasses
    "AuthorizationIntent", "PolicyResultV2", "PolicySnapshotV2",
    # Entry point
    "authorize_v2",
]
