"""Integration layer for the chat-brain v2 semantic reasoning path.

Given a router-produced ``RouterResultV2`` + a
``PolicySnapshotV2``, this module:

    1. Applies the router's IMMEDIATE ``focus_update`` (usually
       PRESERVE — router owns the intent; integration only
       persists).
    2. If the router produced an ``execution_plan``:
         a. Mints an ``AuthorizationRecord`` (when the plan
            requires one).
         b. Atomically CAS-consumes the record.
         c. Dispatches to an executor via the injected
            ``ExecutorRegistry``.
         d. On success: applies the plan's ``success_focus_update``.
         e. On failure: applies the plan's ``failure_focus_update``.
    3. Returns a stable ``IntegrationResultV2`` naming the
       outcome. Executor exceptions never propagate out — they
       are captured and translated into typed statuses.

Integration NEVER:

    * decides target kind/id/assistant_act for focus (router does);
    * chooses reply text (router does — deferred templates);
    * branches on ``telemetry_reason`` (observational only);
    * mixes v1 and v2 in the same request (all steps here are v2
      code paths; v1 legacy path is not invoked from within a
      running v2 integration).

Executor injection
------------------
``ExecutorRegistry`` maps each ``ACTION_KIND_*`` to a callable.
Tests inject fakes; production wiring in ``vault_chat_brain_v2``
provides real callables (typically lazy-imported wrappers around
existing v1 primitives like ``main.save_secret_tool`` or
``vault_secure_item_save._execute_pending_delete``).

An unmapped action kind produces
``IntegrationResultV2(execution_status=INTERNAL_ERROR)`` —
integration refuses to guess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from vault_chat_authorization_record import (
    AUTH_ACTION_DELETE,
    AUTH_ACTION_SAVE,
    AUTH_ACTION_SAVE_ATTACHMENT,
    ConsumeResult,
    REASON_CONSUMED,
    atomic_consume_authorization,
    mint_authorization,
)
from vault_chat_decision_router_v2 import (
    ACTION_KIND_APPLY_CREATE,
    ACTION_KIND_APPLY_EDIT,
    ACTION_KIND_CANCEL_DRAFT,
    ACTION_KIND_CANCEL_PENDING,
    ACTION_KIND_CONFIRM_DELETE,
    ACTION_KIND_CONFIRM_SAVE,
    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
    ACTION_KINDS,
    ExecutionPlanV2,
    FOCUS_ACTION_CLEAR,
    FOCUS_ACTION_CLEAR_IF_MATCHES,
    FOCUS_ACTION_PRESERVE,
    FOCUS_ACTION_SET,
    FOCUS_ACTION_SET_ON_CREATE,
    FocusUpdate,
    RouterResultV2,
)
from vault_chat_focus import (
    clear_focus,
    clear_focus_if_matches,
    stamp_focus,
)
from vault_chat_policy_v2 import PolicySnapshotV2


logger = logging.getLogger(__name__)


# =====================================================================
# Execution status (closed set)
# =====================================================================

STATUS_SUCCESS:                str = "SUCCESS"
STATUS_EXECUTOR_FAILED:        str = "EXECUTOR_FAILED"
STATUS_AUTHORIZATION_FAILED:   str = "AUTHORIZATION_FAILED"
STATUS_CONSUME_FAILED:         str = "CONSUME_FAILED"
STATUS_INTERNAL_ERROR:         str = "INTERNAL_ERROR"
STATUS_NO_EXECUTION:           str = "NO_EXECUTION"

EXECUTION_STATUSES: frozenset[str] = frozenset({
    STATUS_SUCCESS,
    STATUS_EXECUTOR_FAILED,
    STATUS_AUTHORIZATION_FAILED,
    STATUS_CONSUME_FAILED,
    STATUS_INTERNAL_ERROR,
    STATUS_NO_EXECUTION,
})


# =====================================================================
# IntegrationResultV2
# =====================================================================

@dataclass(frozen=True)
class IntegrationResultV2:
    """Stable boundary between execution machinery and the reply
    renderer. Downstream code branches only on ``execution_status``
    + ``reply_key``. ``telemetry_reason`` is observational and MUST
    NOT be used for control flow.
    """
    execution_status:       str
    executed_action_kind:   Optional[str] = None
    applied_focus_update:   Optional[FocusUpdate] = None
    reply_key:              Optional[str] = None
    telemetry_reason:       str = ""

    def __post_init__(self) -> None:
        if self.execution_status not in EXECUTION_STATUSES:
            raise ValueError(
                f"unknown execution_status {self.execution_status!r}"
            )


# =====================================================================
# ExecutorRegistry
# =====================================================================

Executor = Callable[..., None]
"""Executor callable. Signature is intentionally permissive — the
integration passes context as kwargs and the executor consumes
what it needs. Executors MUST NOT raise; they should log and
return, or raise ``ExecutorError`` for a controlled failure."""


class ExecutorError(Exception):
    """A controlled executor failure. Integration catches this and
    returns ``execution_status=EXECUTOR_FAILED``."""


@dataclass(frozen=True)
class ExecutorRegistry:
    """Injectable map of action_kind → executor.

    A missing action kind maps to ``None`` — integration returns
    ``INTERNAL_ERROR`` rather than guessing.
    """
    confirm_save:             Optional[Executor] = None
    confirm_delete:           Optional[Executor] = None
    confirm_save_attachment:  Optional[Executor] = None
    cancel_draft:             Optional[Executor] = None
    cancel_pending:           Optional[Executor] = None
    apply_edit:               Optional[Executor] = None
    apply_create:             Optional[Executor] = None

    def get(self, action_kind: str) -> Optional[Executor]:
        m = {
            ACTION_KIND_CONFIRM_SAVE:            self.confirm_save,
            ACTION_KIND_CONFIRM_DELETE:          self.confirm_delete,
            ACTION_KIND_CONFIRM_SAVE_ATTACHMENT: self.confirm_save_attachment,
            ACTION_KIND_CANCEL_DRAFT:            self.cancel_draft,
            ACTION_KIND_CANCEL_PENDING:          self.cancel_pending,
            ACTION_KIND_APPLY_EDIT:              self.apply_edit,
            ACTION_KIND_APPLY_CREATE:            self.apply_create,
        }
        return m.get(action_kind)


# =====================================================================
# Action-kind classification (commit 5b)
#
# Every action_kind the router can emit belongs to exactly ONE of
# these closed sets. The classification governs whether the
# runtime-readiness guard demands an executor for that kind, and
# whether integration dispatches through the ExecutorRegistry or
# through its native handlers.
#
# EXECUTOR_REQUIRED_ACTION_KINDS
#     Actions that cross out of v2 into external side effects --
#     database writes, cancellation of DB-backed pending intents,
#     etc. These are wrapped by adapters in a later commit. The
#     readiness guard REFUSES on-mode when any of these is
#     unmapped.
#
# NON_EXECUTOR_ACTION_KINDS
#     Actions that are purely v2-native state transformations on
#     the Redis-backed Draft store. Integration handles them
#     directly via ``vault_chat_draft`` primitives; the executor
#     registry is not consulted for them. The readiness guard does
#     NOT demand an executor for these.
#
# Partition invariants (asserted at import time):
#     * the two sets are disjoint;
#     * their union equals ACTION_KINDS;
#     * no unknown string appears in either.
# =====================================================================

EXECUTOR_REQUIRED_ACTION_KINDS: frozenset[str] = frozenset({
    ACTION_KIND_CONFIRM_SAVE,
    ACTION_KIND_CONFIRM_DELETE,
    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
    ACTION_KIND_CANCEL_PENDING,
})

NON_EXECUTOR_ACTION_KINDS: frozenset[str] = frozenset({
    ACTION_KIND_APPLY_EDIT,
    ACTION_KIND_APPLY_CREATE,
    ACTION_KIND_CANCEL_DRAFT,
})

ACTION_KIND_CLASSIFICATION: Mapping[str, str] = MappingProxyType({
    ACTION_KIND_CONFIRM_SAVE:            "executor_required",
    ACTION_KIND_CONFIRM_DELETE:          "executor_required",
    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT: "executor_required",
    ACTION_KIND_CANCEL_PENDING:          "executor_required",
    ACTION_KIND_APPLY_EDIT:              "non_executor",
    ACTION_KIND_APPLY_CREATE:            "non_executor",
    ACTION_KIND_CANCEL_DRAFT:            "non_executor",
})


def _assert_action_kind_partition() -> None:
    overlap = EXECUTOR_REQUIRED_ACTION_KINDS & NON_EXECUTOR_ACTION_KINDS
    if overlap:
        raise AssertionError(
            f"action-kind partition overlaps: {sorted(overlap)}"
        )
    union = EXECUTOR_REQUIRED_ACTION_KINDS | NON_EXECUTOR_ACTION_KINDS
    if union != ACTION_KINDS:
        missing_from_partition = ACTION_KINDS - union
        extra_in_partition = union - ACTION_KINDS
        raise AssertionError(
            f"action-kind partition does not cover ACTION_KINDS: "
            f"missing={sorted(missing_from_partition)} "
            f"extra={sorted(extra_in_partition)}"
        )
    unclassified = ACTION_KINDS - set(ACTION_KIND_CLASSIFICATION.keys())
    if unclassified:
        raise AssertionError(
            f"ACTION_KIND_CLASSIFICATION missing: {sorted(unclassified)}"
        )


_assert_action_kind_partition()


# =====================================================================
# Runtime-readiness guard for mode==on
# =====================================================================

def validate_v2_runtime_readiness(
    registry: ExecutorRegistry,
) -> tuple[bool, list[str]]:
    """Return ``(is_ready, missing_action_kinds_sorted)``.

    The caller should refuse to enter mode==on unless
    ``is_ready`` is True. The registry is considered ready only
    when every ``EXECUTOR_REQUIRED_ACTION_KINDS`` member maps to
    a non-None executor. ``NON_EXECUTOR_ACTION_KINDS`` members
    are handled natively by integration and do NOT need an entry
    in the registry.

    Off and shadow modes do NOT need this check -- shadow never
    dispatches an executor, and off never invokes v2 at all.
    """
    missing: list[str] = []
    for action_kind in sorted(EXECUTOR_REQUIRED_ACTION_KINDS):
        if registry.get(action_kind) is None:
            missing.append(action_kind)
    return (len(missing) == 0, missing)


# =====================================================================
# Focus application
# =====================================================================

def _apply_focus(
    focus:                       FocusUpdate,
    *,
    vault_id:                    str,
    session_id:                  Optional[str],
    assistant_turn_id:           str,
    target_id_override:          Optional[str] = None,
) -> None:
    """Persist / clear focus in the state store per the update.

    ``target_id_override`` is used for ``SET_ON_CREATE`` — the
    caller (integration) passes the newly-minted entity id after
    the executor creates it.
    """
    if focus.action == FOCUS_ACTION_PRESERVE:
        return
    if focus.action == FOCUS_ACTION_CLEAR:
        clear_focus(vault_id=vault_id, session_id=session_id)
        return
    if focus.action == FOCUS_ACTION_CLEAR_IF_MATCHES:
        clear_focus_if_matches(
            vault_id=vault_id, session_id=session_id,
            kind=focus.kind, id=focus.id,
        )
        return
    if focus.action == FOCUS_ACTION_SET:
        stamp_focus(
            vault_id=vault_id, session_id=session_id,
            kind=focus.kind, id=focus.id,
            assistant_act=focus.assistant_act,
            assistant_turn_id=assistant_turn_id,
        )
        return
    if focus.action == FOCUS_ACTION_SET_ON_CREATE:
        # Router provided kind + assistant_act; integration
        # supplies the freshly-minted target_id.
        if not target_id_override:
            logger.warning(
                "[INTEGRATION_V2] set_on_create without target id"
            )
            return
        stamp_focus(
            vault_id=vault_id, session_id=session_id,
            kind=focus.kind, id=target_id_override,
            assistant_act=focus.assistant_act,
            assistant_turn_id=assistant_turn_id,
        )
        return
    logger.warning(
        "[INTEGRATION_V2] unknown focus action %r", focus.action,
    )


# =====================================================================
# Native handlers for NON_EXECUTOR_ACTION_KINDS (commit 5b)
#
# These are pure v2 draft operations -- they touch only the
# Redis-backed Draft store via ``vault_chat_draft`` primitives.
# No executor lookup, no v1 code path, no external DB call.
# Integration owns them so the readiness guard does not have to
# demand an artificial executor for pure state transformation.
# =====================================================================

def _run_native_handler(
    *,
    plan,
    snapshot:            "PolicySnapshotV2",
    vault_id:            str,
    session_id:          Optional[str],
    assistant_turn_id:   str,
    created_target_id:   Optional[str],
) -> tuple[bool, str, Optional[str]]:
    """Dispatch a NON_EXECUTOR action_kind to its native handler.

    Returns ``(ok, telemetry_reason, created_target_id)``. The
    third element is only meaningful for APPLY_CREATE, which may
    mint a new draft_id that the caller then feeds to
    SET_ON_CREATE focus.

    Native handlers never raise; every failure resolves into
    ``ok=False`` with a stable reason string.
    """
    from vault_chat_decision_router_v2 import (
        ACTION_KIND_APPLY_CREATE,
        ACTION_KIND_APPLY_EDIT,
        ACTION_KIND_CANCEL_DRAFT,
    )
    kind = plan.action_kind
    try:
        if kind == ACTION_KIND_CANCEL_DRAFT:
            return _native_cancel_draft(plan, vault_id)
        if kind == ACTION_KIND_APPLY_EDIT:
            return _native_apply_edit(
                plan, snapshot, vault_id, assistant_turn_id,
            )
        if kind == ACTION_KIND_APPLY_CREATE:
            return _native_apply_create(
                plan, snapshot, vault_id, session_id,
                assistant_turn_id,
            )
    except Exception as exc:
        logger.exception(
            "[INTEGRATION_V2] native_handler_uncontrolled_failure "
            "action=%s", kind,
        )
        return (False, f"native_exception:{type(exc).__name__}",
                created_target_id)
    # Should not happen: partition asserts every action_kind is
    # classified. Defensive branch keeps returns typed.
    return (False, f"native_unknown_kind:{kind}", created_target_id)


def _native_cancel_draft(
    plan, vault_id: str,
) -> tuple[bool, str, Optional[str]]:
    from vault_chat_draft import cancel_draft
    target_id = plan.target_id or ""
    if not target_id:
        return (False, "native_cancel_draft:missing_target_id", None)
    removed = cancel_draft(vault_id=vault_id, draft_id=target_id)
    if not removed:
        # Idempotent from the user's perspective -- the draft is
        # already gone. Report ok so the router's success focus
        # (which typically clears any lingering matching focus)
        # still applies. Telemetry marks the no-op explicitly.
        return (True, "native_cancel_draft:already_gone", None)
    return (True, "native_cancel_draft:ok", None)


def _native_apply_edit(
    plan, snapshot, vault_id: str, assistant_turn_id: str,
) -> tuple[bool, str, Optional[str]]:
    from vault_chat_draft import get_draft, store_draft
    from vault_chat_draft_merge import merge, PatchError
    target_id = plan.target_id or ""
    if not target_id:
        return (False, "native_apply_edit:missing_target_id", None)
    draft = get_draft(vault_id, target_id)
    if draft is None:
        return (False, "native_apply_edit:draft_not_found", None)
    if plan.validated_patch is None:
        return (False, "native_apply_edit:missing_patch", None)
    # Rebuild the patch as merge() expects a
    # ``{field_name -> {op, value?}}`` mapping. The plan carries
    # FieldPatchItem instances; convert without leaking values.
    patch_dict: dict = {}
    for field_name, item in plan.validated_patch.items():
        entry: dict = {"op": item.op}
        if item.value is not None:
            entry["value"] = item.value
        patch_dict[field_name] = entry
    try:
        new_draft = merge(
            existing=draft,
            patch=patch_dict,
            patch_source="user_explicit",
            patch_turn_id=assistant_turn_id or "u-native",
        )
    except PatchError as exc:
        return (False, f"native_apply_edit:patch_error:{exc}", None)
    try:
        store_draft(new_draft)
    except Exception:
        logger.exception("[INTEGRATION_V2] native_apply_edit_store_failed")
        return (False, "native_apply_edit:store_failed", None)
    return (True, "native_apply_edit:ok", None)


def _native_apply_create(
    plan, snapshot, vault_id: str, session_id: Optional[str],
    assistant_turn_id: str,
) -> tuple[bool, str, Optional[str]]:
    # APPLY_CREATE requires the router to have supplied a full
    # initial-field patch. draft_kind must be derivable; today the
    # router only creates login drafts, so DRAFT_LOGIN is the
    # default. If a future router emits create for other kinds we
    # must plumb draft_kind through the plan explicitly. Refuse
    # rather than guess.
    from vault_chat_draft import (
        DRAFT_LOGIN, DraftField, SOURCE_USER_EXPLICIT,
        new_draft, store_draft,
    )
    if plan.validated_patch is None:
        return (False, "native_apply_create:missing_patch", None)
    fields: dict = {}
    for field_name, item in plan.validated_patch.items():
        if item.op != "replace" or item.value is None:
            # Create only accepts a replace-with-value patch; any
            # other op has no create semantics.
            continue
        fields[field_name] = DraftField(
            value=item.value,
            source=SOURCE_USER_EXPLICIT,
            turn_id=assistant_turn_id or "u-native",
            at=snapshot.now,
        )
    if not fields:
        return (False, "native_apply_create:empty_patch", None)
    try:
        draft = new_draft(
            vault_id=vault_id, session_id=session_id,
            draft_kind=DRAFT_LOGIN,
            initial_fields=fields,
            origin_turn_id=assistant_turn_id or "u-native",
            now=snapshot.now,
        )
    except Exception as exc:
        logger.exception("[INTEGRATION_V2] native_apply_create_build_failed")
        return (False, f"native_apply_create:build:{type(exc).__name__}",
                None)
    try:
        store_draft(draft)
    except Exception:
        logger.exception("[INTEGRATION_V2] native_apply_create_store_failed")
        return (False, "native_apply_create:store_failed", None)
    return (True, "native_apply_create:ok", draft.draft_id)


# =====================================================================
# apply_router_result_v2 — the public entry point
# =====================================================================

def apply_router_result_v2(
    *,
    router_result:       RouterResultV2,
    snapshot:            PolicySnapshotV2,
    executor_registry:   ExecutorRegistry,
    key:                 bytes = b"",
    memory:              Any = None,
    assistant_turn_id:   str = "",
    created_target_id:   Optional[str] = None,
    db_executor:         Optional[Any] = None,
) -> IntegrationResultV2:
    """Apply the router's declared intent. Owns focus persistence,
    authorization minting + CAS-consumption, and executor
    dispatch. Never raises — every failure resolves into a stable
    ``IntegrationResultV2``.

    Parameters:
        router_result: the RouterResultV2 to apply.
        snapshot: the PolicySnapshotV2 the router was based on;
                  used for vault_id, session_id, and
                  authorizing-turn context.
        executor_registry: action_kind → executor callable.
        key: encryption key (bytes) forwarded to executors that
             need it (e.g. save_secret_tool).
        memory: the SavedDict / chat memory forwarded to
                executors that need it.
        assistant_turn_id: the id of the assistant turn this
                           router result represents. Used when
                           persisting focus.
        created_target_id: the freshly-minted target id for
                           SET_ON_CREATE focus. Callers that
                           wrap apply_router_result_v2 around
                           an apply_create path supply this;
                           None otherwise.
    """
    vault_id = snapshot.vault_id
    session_id = snapshot.session_id

    # -----------------------------------------------------------------
    # Step 1: apply immediate focus (router-declared).
    # -----------------------------------------------------------------
    try:
        _apply_focus(
            router_result.focus_update,
            vault_id=vault_id, session_id=session_id,
            assistant_turn_id=assistant_turn_id,
            target_id_override=None,
        )
    except Exception:
        logger.exception("[INTEGRATION_V2] immediate_focus_apply_failed")
        # A focus-write failure is non-fatal to the pipeline; log and
        # continue. No mixed v1/v2 concern — this is still v2.
    immediate_focus = router_result.focus_update

    # -----------------------------------------------------------------
    # Step 2: no execution required → return.
    # -----------------------------------------------------------------
    plan = router_result.execution_plan
    if plan is None:
        return IntegrationResultV2(
            execution_status=STATUS_NO_EXECUTION,
            executed_action_kind=None,
            applied_focus_update=immediate_focus,
            reply_key=None,
            telemetry_reason="no_plan",
        )

    if plan.action_kind not in ACTION_KINDS:
        return IntegrationResultV2(
            execution_status=STATUS_INTERNAL_ERROR,
            executed_action_kind=None,
            applied_focus_update=immediate_focus,
            reply_key=plan.failure_reply_key,
            telemetry_reason=f"unknown_action_kind:{plan.action_kind!r}",
        )

    # -----------------------------------------------------------------
    # Step 3: mint + CAS-consume authorization if the plan carries one.
    # -----------------------------------------------------------------
    if plan.authorization_intent is not None:
        try:
            record = mint_authorization(
                vault_id=vault_id,
                session_id=session_id,
                target_kind=plan.authorization_intent.target_kind,
                target_id=plan.authorization_intent.target_id,
                action=plan.authorization_intent.action,
                authorizing_user_turn_id=(
                    plan.authorization_intent.authorizing_user_turn_id
                ),
                preceding_assistant_turn_id=(
                    plan.authorization_intent.preceding_assistant_turn_id
                ),
                confidence=plan.authorization_intent.confidence,
            )
        except Exception:
            logger.exception("[INTEGRATION_V2] auth_mint_failed")
            return IntegrationResultV2(
                execution_status=STATUS_AUTHORIZATION_FAILED,
                executed_action_kind=plan.action_kind,
                applied_focus_update=immediate_focus,
                reply_key=plan.failure_reply_key,
                telemetry_reason="mint_exception",
            )

        try:
            consume = atomic_consume_authorization(
                auth_id=record.auth_id,
                expected_vault_id=vault_id,
                expected_session_id=session_id,
                expected_target_kind=(
                    plan.authorization_intent.target_kind
                ),
                expected_target_id=plan.authorization_intent.target_id,
                expected_action=plan.authorization_intent.action,
                expected_authorizing_user_turn_id=(
                    plan.authorization_intent.authorizing_user_turn_id
                ),
            )
        except Exception:
            logger.exception("[INTEGRATION_V2] auth_consume_exception")
            return IntegrationResultV2(
                execution_status=STATUS_CONSUME_FAILED,
                executed_action_kind=plan.action_kind,
                applied_focus_update=immediate_focus,
                reply_key=plan.failure_reply_key,
                telemetry_reason="consume_exception",
            )
        if not consume.consumed:
            return IntegrationResultV2(
                execution_status=STATUS_CONSUME_FAILED,
                executed_action_kind=plan.action_kind,
                applied_focus_update=immediate_focus,
                reply_key=plan.failure_reply_key,
                telemetry_reason=f"consume:{consume.reason}",
            )

    # -----------------------------------------------------------------
    # Step 4: dispatch -- executor for EXECUTOR_REQUIRED kinds, or
    # native handler for NON_EXECUTOR kinds. The partition is
    # verified at import time; any action_kind reaching this point
    # is in exactly one set.
    # -----------------------------------------------------------------
    if plan.action_kind in NON_EXECUTOR_ACTION_KINDS:
        executor_ok, executor_reason, created_target_id = _run_native_handler(
            plan=plan, snapshot=snapshot,
            vault_id=vault_id, session_id=session_id,
            assistant_turn_id=assistant_turn_id,
            created_target_id=created_target_id,
        )
    else:
        executor = executor_registry.get(plan.action_kind)
        if executor is None:
            return IntegrationResultV2(
                execution_status=STATUS_INTERNAL_ERROR,
                executed_action_kind=plan.action_kind,
                applied_focus_update=immediate_focus,
                reply_key=plan.failure_reply_key,
                telemetry_reason=f"no_executor:{plan.action_kind}",
            )

        exec_kwargs = {
            "plan":              plan,
            "snapshot":          snapshot,
            "key":               key,
            "memory":            memory,
            "vault_id":          vault_id,
            "session_id":        session_id,
            "db_executor":       db_executor,
        }

        executor_ok = True
        executor_reason = ""
        try:
            executor(**exec_kwargs)
        except ExecutorError as exc:
            executor_ok = False
            executor_reason = f"executor:{exc}"
            logger.warning(
                "[INTEGRATION_V2] executor_controlled_failure action=%s "
                "reason=%s",
                plan.action_kind, executor_reason,
            )
        except Exception as exc:
            executor_ok = False
            executor_reason = f"executor_exception:{type(exc).__name__}"
            logger.exception("[INTEGRATION_V2] executor_uncontrolled_failure")

    # -----------------------------------------------------------------
    # Step 5: apply success or failure focus + return.
    # -----------------------------------------------------------------
    focus_to_apply = (
        plan.success_focus_update if executor_ok
        else plan.failure_focus_update
    )
    try:
        _apply_focus(
            focus_to_apply,
            vault_id=vault_id, session_id=session_id,
            assistant_turn_id=assistant_turn_id,
            target_id_override=(
                created_target_id if executor_ok else None
            ),
        )
    except Exception:
        logger.exception(
            "[INTEGRATION_V2] %s_focus_apply_failed",
            "success" if executor_ok else "failure",
        )

    return IntegrationResultV2(
        execution_status=(
            STATUS_SUCCESS if executor_ok else STATUS_EXECUTOR_FAILED
        ),
        executed_action_kind=plan.action_kind,
        applied_focus_update=focus_to_apply,
        reply_key=(
            plan.success_reply_key if executor_ok
            else plan.failure_reply_key
        ),
        telemetry_reason=executor_reason,
    )


__all__ = [
    "STATUS_SUCCESS",
    "STATUS_EXECUTOR_FAILED",
    "STATUS_AUTHORIZATION_FAILED",
    "STATUS_CONSUME_FAILED",
    "STATUS_INTERNAL_ERROR",
    "STATUS_NO_EXECUTION",
    "EXECUTION_STATUSES",
    "EXECUTOR_REQUIRED_ACTION_KINDS",
    "NON_EXECUTOR_ACTION_KINDS",
    "ACTION_KIND_CLASSIFICATION",
    "IntegrationResultV2",
    "ExecutorError",
    "ExecutorRegistry",
    "apply_router_result_v2",
    "validate_v2_runtime_readiness",
]
