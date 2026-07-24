"""SemanticDecisionV2 — the chat-brain v2 decider's structured
return value, its parser, and its validator.

The v2 semantic decider prompts the LLM to return a decision in a
strict JSON contract. This module defines that contract as a set
of frozen dataclasses, plus a parser that never raises (any
malformed model output becomes a fallthrough decision with a
diagnostic ``error`` field) and a validator that runs strict
structural checks.

Scope of this module (commit 2)
-------------------------------
Structural validation only:

    * schema version
    * closed enums (intent, target.kind, field_patch op,
      requested_operations.operation, authorization.scope.action)
    * shape of nested objects (target, field_patch items,
      requested_operations items, authorization/scope)
    * op-value coherency (op=clear must not carry value;
      op=regenerate must have a matching requested_operations
      entry; op=replace must carry value)
    * authorization.scope.target_id == target.id when granted
    * confidence type/range (via
      ``vault_chat_confidence_thresholds.is_valid_confidence``)
    * intent-consistency (which intents may carry patch,
      requested_operations, or authorization.granted)

Explicitly NOT in scope for commit 2 (delegated to commit 3
policy layer, which has the TurnSnapshot in hand):

    * target.id ∈ snapshot's known IDs (draft/pending_action/
      active_entity) — the validator here can OPTIONALLY check
      membership if the caller passes a ``known_target_ids`` set,
      but the enforcement point is the policy layer.
    * focus binding
    * per-draft_kind field-name allowlist for field_patch keys
      (requires access to the target Draft's schema — a policy
      concern)
    * confidence-threshold execution decisions
      (may_execute_non_destructive / etc.)

Wire schema (JSON returned by the model)
----------------------------------------
::

    {
      "schema_version": 1,
      "intent": "edit_draft" | ... ,
      "target": {"kind": "draft"|..., "id": "<...>"|null},
      "field_patch": {
        "<field_name>": {"op": "replace"|"clear"|"regenerate"|"unchanged",
                         "value": "<...>"    # only for op=replace
                        }
      },
      "requested_operations": [
        {"operation": "generate_password",
         "field": "password_ref",
         "policy_hint": "stronger"|"different"|null}
      ],
      "authorization": {
        "granted": true | false,
        "scope": {"target_id": "<same as target.id>",
                  "action": "save"|"delete"|"save_attachment"|null}
      },
      "confidence": 0.0 .. 1.0,
      "reason": "one short semantic explanation"
    }

``reason`` is explanatory text for the debug log only. It is NOT
a security control — the policy layer never branches on
``reason`` content. See design memo §5.1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from vault_chat_confidence_thresholds import is_valid_confidence


# -------------------------------------------------------------------
# Schema version — bump requires an explicit migration path.
# -------------------------------------------------------------------

SEMANTIC_DECISION_V2_SCHEMA_VERSION: int = 1


# -------------------------------------------------------------------
# Closed enums (intent, target_kind, op, operation, action).
# -------------------------------------------------------------------

INTENT_EDIT_DRAFT:              str = "edit_draft"
INTENT_CREATE_DRAFT:            str = "create_draft"
INTENT_CONFIRM_DRAFT:           str = "confirm_draft"
INTENT_CANCEL_DRAFT:            str = "cancel_draft"
INTENT_CONFIRM_PENDING_ACTION:  str = "confirm_pending_action"
INTENT_CANCEL_PENDING_ACTION:   str = "cancel_pending_action"
INTENT_ANSWER_QUESTION:         str = "answer_question"
INTENT_ASK_CLARIFICATION:       str = "ask_clarification"
INTENT_CHAT:                    str = "chat"
INTENT_FALLTHROUGH:             str = "fallthrough"

INTENTS: frozenset[str] = frozenset({
    INTENT_EDIT_DRAFT, INTENT_CREATE_DRAFT,
    INTENT_CONFIRM_DRAFT, INTENT_CANCEL_DRAFT,
    INTENT_CONFIRM_PENDING_ACTION, INTENT_CANCEL_PENDING_ACTION,
    INTENT_ANSWER_QUESTION, INTENT_ASK_CLARIFICATION,
    INTENT_CHAT, INTENT_FALLTHROUGH,
})

_INTENTS_ALLOWING_FIELD_PATCH: frozenset[str] = frozenset({
    INTENT_CREATE_DRAFT, INTENT_EDIT_DRAFT,
})

_INTENTS_ALLOWING_REQUESTED_OPS: frozenset[str] = frozenset({
    INTENT_CREATE_DRAFT, INTENT_EDIT_DRAFT,
})

_INTENTS_ALLOWING_AUTH_GRANT: frozenset[str] = frozenset({
    INTENT_CONFIRM_DRAFT, INTENT_CANCEL_DRAFT,
    INTENT_CONFIRM_PENDING_ACTION, INTENT_CANCEL_PENDING_ACTION,
})


TARGET_KIND_DRAFT:          str = "draft"
TARGET_KIND_PENDING_ACTION: str = "pending_action"
TARGET_KIND_ACTIVE_ENTITY:  str = "active_entity"
TARGET_KIND_NONE:           str = "none"

TARGET_KINDS: frozenset[str] = frozenset({
    TARGET_KIND_DRAFT, TARGET_KIND_PENDING_ACTION,
    TARGET_KIND_ACTIVE_ENTITY, TARGET_KIND_NONE,
})


OP_REPLACE:    str = "replace"
OP_CLEAR:      str = "clear"
OP_REGENERATE: str = "regenerate"
OP_UNCHANGED:  str = "unchanged"

PATCH_OPS: frozenset[str] = frozenset({
    OP_REPLACE, OP_CLEAR, OP_REGENERATE, OP_UNCHANGED,
})

_OPS_FORBIDDING_VALUE: frozenset[str] = frozenset({
    OP_CLEAR, OP_REGENERATE, OP_UNCHANGED,
})


# Currently the only supported requested-operation is password
# generation. Adding a new operation requires updating this set
# AND the per-operation-field allowlist below.
OPERATION_GENERATE_PASSWORD: str = "generate_password"

REQUESTED_OPERATIONS: frozenset[str] = frozenset({
    OPERATION_GENERATE_PASSWORD,
})

# Per-operation: which fields the operation is allowed to target.
# The decider must not request generate_password on an arbitrary
# field name.
_OPERATION_ALLOWED_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType({
    OPERATION_GENERATE_PASSWORD: frozenset({"password_ref"}),
})


ACTION_SAVE:            str = "save"
ACTION_DELETE:          str = "delete"
ACTION_SAVE_ATTACHMENT: str = "save_attachment"

ACTIONS: frozenset[str] = frozenset({
    ACTION_SAVE, ACTION_DELETE, ACTION_SAVE_ATTACHMENT,
})


# Which target_kind is compatible with which action.
# Duplicated deliberately from vault_chat_authorization_record so
# validator can enforce here without pulling in the auth module.
# Kept in sync via test in test_chat_semantic_decision_v2.
_ACTION_COMPATIBLE_TARGET_KINDS: Mapping[str, frozenset[str]] = MappingProxyType({
    ACTION_SAVE:            frozenset({TARGET_KIND_DRAFT, TARGET_KIND_PENDING_ACTION}),
    ACTION_DELETE:          frozenset({TARGET_KIND_PENDING_ACTION}),
    ACTION_SAVE_ATTACHMENT: frozenset({TARGET_KIND_PENDING_ACTION}),
})


# -------------------------------------------------------------------
# Sentinel for "no value present in a patch item"
# -------------------------------------------------------------------

class _NoValueType:
    """Sentinel meaning 'the JSON did not carry a value for this
    patch item'. Distinct from JSON null."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "NO_VALUE"

    def __bool__(self) -> bool:
        return False


NO_VALUE: _NoValueType = _NoValueType()


# -------------------------------------------------------------------
# Dataclasses
# -------------------------------------------------------------------

@dataclass(frozen=True)
class TargetRef:
    kind: str
    id:   Optional[str]

    def __post_init__(self) -> None:
        if self.kind not in TARGET_KINDS:
            raise ValueError(f"unknown target kind {self.kind!r}")
        if self.kind == TARGET_KIND_NONE and self.id not in (None, ""):
            raise ValueError("target.kind=none must not carry an id")
        if self.kind != TARGET_KIND_NONE and (
            not isinstance(self.id, str) or not self.id.strip()
        ):
            raise ValueError(
                f"target.kind={self.kind!r} requires a non-empty id"
            )


@dataclass(frozen=True)
class FieldPatchItem:
    op:    str
    value: Any = NO_VALUE

    def __post_init__(self) -> None:
        if self.op not in PATCH_OPS:
            raise ValueError(f"unknown patch op {self.op!r}")
        has_value = not isinstance(self.value, _NoValueType)
        if self.op == OP_REPLACE and not has_value:
            raise ValueError("op=replace requires a 'value'")
        if self.op in _OPS_FORBIDDING_VALUE and has_value:
            raise ValueError(
                f"op={self.op!r} must NOT carry a 'value'"
            )


@dataclass(frozen=True)
class RequestedOperation:
    operation:    str
    field:        str
    policy_hint:  Optional[str] = None

    def __post_init__(self) -> None:
        if self.operation not in REQUESTED_OPERATIONS:
            raise ValueError(f"unknown operation {self.operation!r}")
        allowed = _OPERATION_ALLOWED_FIELDS.get(self.operation, frozenset())
        if self.field not in allowed:
            raise ValueError(
                f"operation {self.operation!r} not allowed on "
                f"field {self.field!r}"
            )
        if self.policy_hint is not None and not isinstance(self.policy_hint, str):
            raise TypeError("policy_hint must be str or None")


@dataclass(frozen=True)
class AuthorizationScope:
    target_id: str
    action:    Optional[str]

    def __post_init__(self) -> None:
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("scope.target_id must be a non-empty string")
        if self.action is not None and self.action not in ACTIONS:
            raise ValueError(f"unknown scope.action {self.action!r}")


@dataclass(frozen=True)
class Authorization:
    granted: bool
    scope:   Optional[AuthorizationScope] = None

    def __post_init__(self) -> None:
        if not isinstance(self.granted, bool):
            raise TypeError("authorization.granted must be a bool")
        if self.granted and self.scope is None:
            raise ValueError(
                "authorization.granted=true requires a scope"
            )


@dataclass(frozen=True)
class SemanticDecisionV2:
    schema_version:       int
    intent:               str
    target:               TargetRef
    field_patch:          Mapping[str, FieldPatchItem]
    requested_operations: Tuple[RequestedOperation, ...]
    authorization:        Authorization
    confidence:           float
    reason:               str
    error:                str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SEMANTIC_DECISION_V2_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported semantic_decision_v2 schema_version "
                f"{self.schema_version!r}"
            )
        if self.intent not in INTENTS:
            raise ValueError(f"unknown intent {self.intent!r}")
        if not is_valid_confidence(self.confidence):
            raise ValueError(
                "confidence must be a number in [0.0, 1.0] "
                "(bool is rejected)"
            )
        if not isinstance(self.reason, str):
            raise TypeError("reason must be a string")
        if not isinstance(self.error, str):
            raise TypeError("error must be a string")
        # Freeze field_patch so callers can't smuggle mutations.
        if not isinstance(self.field_patch, MappingProxyType):
            object.__setattr__(
                self, "field_patch",
                MappingProxyType(dict(self.field_patch)),
            )

    def is_fallthrough(self) -> bool:
        return self.intent == INTENT_FALLTHROUGH


# -------------------------------------------------------------------
# Validation error
# -------------------------------------------------------------------

class SemanticDecisionValidationError(ValueError):
    """Structural validator refused a decision. The message is
    a machine-friendly short reason (used by the parser to
    populate ``SemanticDecisionV2.error``)."""


# -------------------------------------------------------------------
# Fallthrough factory (used by the parser on any error path).
# -------------------------------------------------------------------

def make_fallthrough(error: str, confidence: float = 0.0,
                     reason: str = "") -> SemanticDecisionV2:
    """Construct a canonical fallthrough decision.

    Used by the parser when the model's response can't be validated,
    and available to the policy layer when it needs to synthesize
    a fallthrough on a rule violation.
    """
    return SemanticDecisionV2(
        schema_version=SEMANTIC_DECISION_V2_SCHEMA_VERSION,
        intent=INTENT_FALLTHROUGH,
        target=TargetRef(kind=TARGET_KIND_NONE, id=None),
        field_patch=MappingProxyType({}),
        requested_operations=(),
        authorization=Authorization(granted=False, scope=None),
        confidence=float(confidence),
        reason=reason,
        error=error,
    )


# -------------------------------------------------------------------
# Validator (dict -> SemanticDecisionV2) — strict, raises on error.
# -------------------------------------------------------------------

_ALLOWED_TOP_LEVEL_KEYS: frozenset[str] = frozenset({
    "schema_version", "intent", "target",
    "field_patch", "requested_operations",
    "authorization", "confidence", "reason",
})


def validate_semantic_decision_v2(
    payload: Any,
    *,
    known_target_ids: Optional[frozenset[str]] = None,
) -> SemanticDecisionV2:
    """Strict structural validator.

    Raises ``SemanticDecisionValidationError`` with a short,
    machine-readable reason on any structural failure.

    ``known_target_ids`` is an OPTIONAL cross-check hook: when
    supplied and non-empty, the validator ALSO refuses decisions
    whose non-``none`` ``target.id`` is not in the set. In
    production this cross-check is normally deferred to the policy
    layer, which owns the snapshot; tests may pass it to exercise
    the check here.
    """
    if not isinstance(payload, dict):
        raise SemanticDecisionValidationError("payload_not_object")

    unknown = set(payload.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise SemanticDecisionValidationError(
            f"unknown_top_level_keys:{sorted(unknown)!r}"
        )

    sv = payload.get("schema_version")
    if sv != SEMANTIC_DECISION_V2_SCHEMA_VERSION:
        raise SemanticDecisionValidationError(
            f"unsupported_schema_version:{sv!r}"
        )

    intent = payload.get("intent")
    if not isinstance(intent, str) or intent not in INTENTS:
        raise SemanticDecisionValidationError(f"unknown_intent:{intent!r}")

    target_raw = payload.get("target")
    if not isinstance(target_raw, dict):
        raise SemanticDecisionValidationError("target_not_object")
    unknown_target = set(target_raw.keys()) - {"kind", "id"}
    if unknown_target:
        raise SemanticDecisionValidationError(
            f"unknown_target_keys:{sorted(unknown_target)!r}"
        )
    try:
        target = TargetRef(kind=str(target_raw.get("kind")),
                            id=target_raw.get("id"))
    except ValueError as exc:
        raise SemanticDecisionValidationError(f"target:{exc}") from exc

    if known_target_ids and target.kind != TARGET_KIND_NONE:
        if target.id not in known_target_ids:
            raise SemanticDecisionValidationError(
                f"unknown_target_id"
            )

    field_patch = _validate_field_patch(
        payload.get("field_patch"), intent=intent,
    )
    requested_ops = _validate_requested_operations(
        payload.get("requested_operations"), intent=intent,
    )
    authorization = _validate_authorization(
        payload.get("authorization"),
        intent=intent,
        target=target,
    )

    confidence = payload.get("confidence")
    if not is_valid_confidence(confidence):
        raise SemanticDecisionValidationError(
            f"invalid_confidence:{confidence!r}"
        )

    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        raise SemanticDecisionValidationError("reason_not_string")

    return SemanticDecisionV2(
        schema_version=SEMANTIC_DECISION_V2_SCHEMA_VERSION,
        intent=intent,
        target=target,
        field_patch=MappingProxyType(field_patch),
        requested_operations=tuple(requested_ops),
        authorization=authorization,
        confidence=float(confidence),
        reason=reason,
    )


def _validate_field_patch(raw: Any, *, intent: str) -> dict[str, FieldPatchItem]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise SemanticDecisionValidationError("field_patch_not_object")

    if raw and intent not in _INTENTS_ALLOWING_FIELD_PATCH:
        raise SemanticDecisionValidationError(
            f"field_patch_not_allowed_for_intent:{intent!r}"
        )

    out: dict[str, FieldPatchItem] = {}
    for name, item in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise SemanticDecisionValidationError("field_patch_bad_field_name")
        if not isinstance(item, dict):
            raise SemanticDecisionValidationError(
                f"field_patch_item_not_object:{name!r}"
            )
        item_keys = set(item.keys()) - {"op", "value"}
        if item_keys:
            raise SemanticDecisionValidationError(
                f"field_patch_item_unknown_keys:{name!r}:{sorted(item_keys)!r}"
            )
        op = item.get("op")
        if not isinstance(op, str) or op not in PATCH_OPS:
            raise SemanticDecisionValidationError(
                f"field_patch_item_unknown_op:{name!r}:{op!r}"
            )
        if "value" in item:
            try:
                out[name] = FieldPatchItem(op=op, value=item["value"])
            except ValueError as exc:
                raise SemanticDecisionValidationError(
                    f"field_patch_item:{name!r}:{exc}"
                ) from exc
        else:
            try:
                out[name] = FieldPatchItem(op=op)
            except ValueError as exc:
                raise SemanticDecisionValidationError(
                    f"field_patch_item:{name!r}:{exc}"
                ) from exc
    return out


def _validate_requested_operations(
    raw: Any, *, intent: str,
) -> list[RequestedOperation]:
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise SemanticDecisionValidationError("requested_operations_not_array")
    if raw and intent not in _INTENTS_ALLOWING_REQUESTED_OPS:
        raise SemanticDecisionValidationError(
            f"requested_operations_not_allowed_for_intent:{intent!r}"
        )
    out: list[RequestedOperation] = []
    seen_op_field: set[tuple[str, str]] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SemanticDecisionValidationError(
                f"requested_operations[{i}]_not_object"
            )
        unknown_keys = set(item.keys()) - {"operation", "field", "policy_hint"}
        if unknown_keys:
            raise SemanticDecisionValidationError(
                f"requested_operations[{i}]_unknown_keys:{sorted(unknown_keys)!r}"
            )
        op = item.get("operation")
        field_name = item.get("field")
        policy_hint = item.get("policy_hint")
        if not isinstance(op, str) or op not in REQUESTED_OPERATIONS:
            raise SemanticDecisionValidationError(
                f"requested_operations[{i}]_unknown_operation:{op!r}"
            )
        if not isinstance(field_name, str) or not field_name:
            raise SemanticDecisionValidationError(
                f"requested_operations[{i}]_missing_field"
            )
        try:
            entry = RequestedOperation(
                operation=op, field=field_name, policy_hint=policy_hint,
            )
        except (ValueError, TypeError) as exc:
            raise SemanticDecisionValidationError(
                f"requested_operations[{i}]:{exc}"
            ) from exc
        key = (op, field_name)
        if key in seen_op_field:
            raise SemanticDecisionValidationError(
                f"requested_operations[{i}]_duplicate:{key!r}"
            )
        seen_op_field.add(key)
        out.append(entry)
    return out


def _validate_authorization(
    raw: Any, *, intent: str, target: TargetRef,
) -> Authorization:
    if raw is None:
        return Authorization(granted=False, scope=None)
    if not isinstance(raw, dict):
        raise SemanticDecisionValidationError("authorization_not_object")
    unknown = set(raw.keys()) - {"granted", "scope"}
    if unknown:
        raise SemanticDecisionValidationError(
            f"authorization_unknown_keys:{sorted(unknown)!r}"
        )
    granted = raw.get("granted", False)
    if not isinstance(granted, bool):
        raise SemanticDecisionValidationError("authorization_granted_not_bool")

    scope_raw = raw.get("scope")
    if scope_raw is None:
        scope: Optional[AuthorizationScope] = None
    else:
        if not isinstance(scope_raw, dict):
            raise SemanticDecisionValidationError("authorization_scope_not_object")
        unknown_s = set(scope_raw.keys()) - {"target_id", "action"}
        if unknown_s:
            raise SemanticDecisionValidationError(
                f"authorization_scope_unknown_keys:{sorted(unknown_s)!r}"
            )
        try:
            scope = AuthorizationScope(
                target_id=str(scope_raw.get("target_id") or ""),
                action=scope_raw.get("action"),
            )
        except ValueError as exc:
            raise SemanticDecisionValidationError(f"authorization_scope:{exc}") from exc

    if granted:
        if intent not in _INTENTS_ALLOWING_AUTH_GRANT:
            raise SemanticDecisionValidationError(
                f"authorization_grant_not_allowed_for_intent:{intent!r}"
            )
        if scope is None:
            raise SemanticDecisionValidationError("authorization_grant_missing_scope")
        if scope.target_id != target.id:
            raise SemanticDecisionValidationError(
                "authorization_scope_target_id_mismatch"
            )
        if scope.action is None:
            raise SemanticDecisionValidationError(
                "authorization_scope_missing_action"
            )
        compatible_kinds = _ACTION_COMPATIBLE_TARGET_KINDS.get(
            scope.action, frozenset(),
        )
        if target.kind not in compatible_kinds:
            raise SemanticDecisionValidationError(
                f"authorization_action_incompatible_with_target_kind"
            )

    return Authorization(granted=granted, scope=scope)


# -------------------------------------------------------------------
# Parser (never raises)
# -------------------------------------------------------------------

def parse_semantic_decision_v2(
    text: str,
    *,
    known_target_ids: Optional[frozenset[str]] = None,
) -> SemanticDecisionV2:
    """Parse a model's raw response into a validated
    ``SemanticDecisionV2``.

    On any failure — empty content, non-JSON text, non-object
    JSON, structural violation — returns a canonical fallthrough
    decision whose ``error`` field carries a short machine-
    readable reason. Never raises.
    """
    if not isinstance(text, str) or not text.strip():
        return make_fallthrough(error="empty_content")

    parsed = _extract_json_object(text)
    if parsed is None:
        return make_fallthrough(error="json_parse_failed")

    try:
        return validate_semantic_decision_v2(
            parsed, known_target_ids=known_target_ids,
        )
    except SemanticDecisionValidationError as exc:
        return make_fallthrough(error=str(exc))


def _extract_json_object(text: str) -> Optional[dict]:
    """Salvage the first balanced JSON object from ``text``.
    Handles the common cases where a model wraps output in a
    fenced code block or leading/trailing prose. Returns None if
    no dict-shaped JSON is present.

    Copied in spirit from v1's ``_extract_json_object`` — v2
    keeps the same tolerance so a well-behaved model that emits
    slightly noisy output does not silently fall through.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        nl = stripped.find("\n")
        if nl != -1:
            stripped = stripped[nl + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    # Brace-scan fallback.
    start = stripped.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    chunk = stripped[start:i + 1]
                    try:
                        parsed = json.loads(chunk)
                        return parsed if isinstance(parsed, dict) else None
                    except Exception:
                        break
        start = stripped.find("{", start + 1)
    return None


__all__ = [
    # schema version
    "SEMANTIC_DECISION_V2_SCHEMA_VERSION",
    # intents
    "INTENT_EDIT_DRAFT", "INTENT_CREATE_DRAFT",
    "INTENT_CONFIRM_DRAFT", "INTENT_CANCEL_DRAFT",
    "INTENT_CONFIRM_PENDING_ACTION", "INTENT_CANCEL_PENDING_ACTION",
    "INTENT_ANSWER_QUESTION", "INTENT_ASK_CLARIFICATION",
    "INTENT_CHAT", "INTENT_FALLTHROUGH",
    "INTENTS",
    # target kinds
    "TARGET_KIND_DRAFT", "TARGET_KIND_PENDING_ACTION",
    "TARGET_KIND_ACTIVE_ENTITY", "TARGET_KIND_NONE",
    "TARGET_KINDS",
    # ops
    "OP_REPLACE", "OP_CLEAR", "OP_REGENERATE", "OP_UNCHANGED",
    "PATCH_OPS",
    # requested operations
    "OPERATION_GENERATE_PASSWORD", "REQUESTED_OPERATIONS",
    # actions
    "ACTION_SAVE", "ACTION_DELETE", "ACTION_SAVE_ATTACHMENT",
    "ACTIONS",
    # sentinels
    "NO_VALUE",
    # dataclasses
    "TargetRef", "FieldPatchItem", "RequestedOperation",
    "AuthorizationScope", "Authorization", "SemanticDecisionV2",
    # errors + factories
    "SemanticDecisionValidationError",
    "make_fallthrough",
    # validator + parser
    "validate_semantic_decision_v2",
    "parse_semantic_decision_v2",
]
