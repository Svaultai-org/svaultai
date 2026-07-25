"""Executor adapters for the v2 chat-brain integration layer.

Each ``EXECUTOR_REQUIRED_ACTION_KINDS`` member gets a thin adapter
that:

    * receives an ``ExecutorContextV2`` (typed context passed
      through integration);
    * re-validates the live target against the plan (TOC/TOU
      protection between policy time and execution time);
    * calls exactly one existing V1 production primitive;
    * translates the primitive's outcome into a closed-set
      ``ExecutorOutcomeV2`` (result code + optional
      ``created_target_id`` + allowlisted telemetry metadata);
    * never produces user-facing reply text (the router's
      deferred reply templates own that);
    * never swallows security errors into ``SUCCESS`` -- any
      unexpected condition becomes an explicit non-success code.

The adapter surface is intentionally small. When integration
dispatches an ``EXECUTOR_REQUIRED`` action_kind, it invokes the
adapter registered for that kind under a plain callable contract
(``def executor(**kwargs) -> None`` -- integration doesn't
require any typed return). The adapter records its
``ExecutorOutcomeV2`` on the shared ``ExecutorContextV2`` and, on
non-success, raises ``ExecutorError`` so integration returns
``EXECUTOR_FAILED``.

Held-secret lifecycle (login save)
----------------------------------
The confirm_save-login adapter resolves the phase-1 held-secret
pointer ``password_ref = "memory:pending_login_draft:password"``
by reading ``memory["pending_login_draft"]["password"]`` in the
adapter itself. The raw password is:

    * loaded from memory,
    * passed to the underlying save (``main.save_secret_tool``
      with ``generated=True``),
    * cleared from memory ONLY on save success (via
      ``memory.pop("pending_login_draft", None)``),
    * left in place on save failure so the user can retry.

The raw password is NEVER written back into a ``Draft`` (which
holds only ``password_ref``), NEVER logged, and NEVER returned
in ``telemetry_metadata``. It exists only in the adapter's
local scope for the duration of the underlying save call.

TOC/TOU protection
------------------
Between policy validation and the executor invocation, state may
change (a concurrent request may have consumed the draft, moved
the pending intent, or reassigned the upload binding). Every
adapter re-loads the live target immediately before its
underlying call and refuses to proceed with a stable failure
code (``TARGET_STALE``, ``NOT_FOUND``, ``AUTHORIZATION_CONTEXT_INVALID``,
etc.) if the target no longer matches the plan.

Do NOT wire this module from ``main.py``. Integration acquires
the registry through ``build_production_executor_registry()``
(defined here); tests inject their own registries.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional

from vault_chat_decision_router_v2 import (
    ACTION_KIND_CANCEL_PENDING,
    ACTION_KIND_CONFIRM_DELETE,
    ACTION_KIND_CONFIRM_SAVE,
    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
    ExecutionPlanV2,
)
from vault_chat_integration_v2 import (
    EXECUTOR_REQUIRED_ACTION_KINDS,
    ExecutorError,
    ExecutorRegistry,
)
from vault_chat_pending_action import (
    KIND_DELETE_SECURE_ITEM,
    KIND_SAVE_ATTACHMENT,
    KIND_SAVE_CREDENTIAL,
    KIND_SAVE_LOGIN_DRAFT,
    KIND_SAVE_SECURE_ITEM,
    PendingAction,
    SOURCE_CREDENTIAL_DRAFT,
    SOURCE_MEMORY_LOGIN_DRAFT,
    SOURCE_SECURE_DELETE_INTENT,
    SOURCE_SECURE_ITEM_DRAFT,
    SOURCE_UPLOADED_FILE,
    read_all_pending,
)
from vault_chat_policy_v2 import PolicySnapshotV2
from vault_chat_semantic_decision_v2 import (
    TARGET_KIND_DRAFT,
    TARGET_KIND_PENDING_ACTION,
)


logger = logging.getLogger(__name__)


# =====================================================================
# Result codes (closed set)
# =====================================================================

RESULT_SUCCESS:                        str = "SUCCESS"
RESULT_TARGET_STALE:                   str = "TARGET_STALE"
RESULT_VALIDATION_FAILED:              str = "VALIDATION_FAILED"
RESULT_NOT_FOUND:                      str = "NOT_FOUND"
RESULT_CONFLICT:                       str = "CONFLICT"
RESULT_AUTHORIZATION_CONTEXT_INVALID:  str = "AUTHORIZATION_CONTEXT_INVALID"
RESULT_DEPENDENCY_UNAVAILABLE:         str = "DEPENDENCY_UNAVAILABLE"
RESULT_EXECUTOR_EXCEPTION:             str = "EXECUTOR_EXCEPTION"

RESULT_CODES: frozenset[str] = frozenset({
    RESULT_SUCCESS,
    RESULT_TARGET_STALE,
    RESULT_VALIDATION_FAILED,
    RESULT_NOT_FOUND,
    RESULT_CONFLICT,
    RESULT_AUTHORIZATION_CONTEXT_INVALID,
    RESULT_DEPENDENCY_UNAVAILABLE,
    RESULT_EXECUTOR_EXCEPTION,
})

# The only user-facing reply text ever produced by an adapter is
# empty -- reply text is owned by the router's deferred templates.
_EMPTY_REPLY: str = ""


# =====================================================================
# Telemetry metadata: allowlisted, non-sensitive keys only
# =====================================================================

ALLOWED_TELEMETRY_KEYS: frozenset[str] = frozenset({
    "underlying_band",
    "underlying_count",
    "source_kind",
    "action_kind",
    "target_kind",
    "cancel_kind",
    "resolved_password_ref",
    "attachment_content_type",
    "notes",
})


class TelemetryValidationError(Exception):
    """Raised when an adapter attempts to record a telemetry
    key that is not in the allowlist. This is a construction-time
    guard against accidentally leaking sensitive keys."""


def _validate_telemetry(md: Mapping[str, str]) -> Mapping[str, str]:
    for k in md.keys():
        if k not in ALLOWED_TELEMETRY_KEYS:
            raise TelemetryValidationError(
                f"telemetry key {k!r} not in ALLOWED_TELEMETRY_KEYS"
            )
    return dict(md)


# =====================================================================
# ExecutorContextV2 -- typed context handed to adapters
# =====================================================================

@dataclass
class ExecutorContextV2:
    """Typed context passed to every adapter. The caller
    (integration) constructs one per invocation; the adapter reads
    what it needs and records its outcome via ``record_outcome``.

    Fields:
        vault_id:            live vault the request belongs to.
        session_id:          live session (may be None).
        user_turn_id:        current user turn id (for audit).
        target_kind:         plan.target_kind (draft | pending_action).
        target_id:           plan.target_id (may be None for CREATE).
        validated_patch:     plan.validated_patch (opaque to adapters).
        db_executor:         optional 2-arg (op, payload) callable
                             the underlying primitive may use. Only
                             ``_execute_pending_delete`` currently
                             consumes it; other primitives ignore.
        key:                 32-byte vault encryption key.
        memory:              SavedDict-like chat memory. The
                             confirm_save-login adapter reads
                             (and clears) ``pending_login_draft``.
        plan:                the original ExecutionPlanV2 (for
                             fields the adapter needs to
                             re-validate against, e.g.
                             action_kind).
        snapshot:            the PolicySnapshotV2 the router used.
        now:                 stable clock for TOC/TOU checks
                             (defaults to time.time() at
                             construction if not passed).

    ``outcome`` is populated by the adapter via ``record_outcome``.
    The default (``None``) means the adapter didn't produce one --
    integration treats that as an internal error.
    """
    vault_id:          str
    session_id:        Optional[str]
    user_turn_id:      str
    target_kind:       str
    target_id:         Optional[str]
    validated_patch:   Optional[Mapping]
    db_executor:       Optional[Any]
    key:               bytes
    memory:            Any
    plan:              ExecutionPlanV2
    snapshot:          PolicySnapshotV2
    now:               float = field(default_factory=time.time)

    outcome:           Optional["ExecutorOutcomeV2"] = None

    def record_outcome(self, outcome: "ExecutorOutcomeV2") -> None:
        if self.outcome is not None:
            raise RuntimeError(
                "ExecutorContextV2 outcome already recorded"
            )
        self.outcome = outcome


# =====================================================================
# ExecutorOutcomeV2 -- normalized adapter result
# =====================================================================

@dataclass(frozen=True)
class ExecutorOutcomeV2:
    """Closed-set normalized result of an adapter invocation.

    Fields:
        success:              True iff result_code == RESULT_SUCCESS.
        result_code:          one of RESULT_CODES.
        created_target_id:    for actions that mint a new entity
                              (currently unused by executor-side
                              actions; kept for symmetry).
        telemetry_metadata:   allowlist-validated at construction.
                              MUST NOT contain user secrets, ids,
                              or PII.
    """
    success:             bool
    result_code:         str
    created_target_id:   Optional[str] = None
    telemetry_metadata:  Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({}),
    )

    def __post_init__(self) -> None:
        if self.result_code not in RESULT_CODES:
            raise ValueError(f"unknown result_code {self.result_code!r}")
        if self.success and self.result_code != RESULT_SUCCESS:
            raise ValueError(
                "success=True requires result_code=SUCCESS"
            )
        if not self.success and self.result_code == RESULT_SUCCESS:
            raise ValueError(
                "result_code=SUCCESS requires success=True"
            )
        _validate_telemetry(self.telemetry_metadata)


def _ok(**telemetry: str) -> ExecutorOutcomeV2:
    return ExecutorOutcomeV2(
        success=True, result_code=RESULT_SUCCESS,
        telemetry_metadata=MappingProxyType(_validate_telemetry(telemetry)),
    )


def _fail(code: str, **telemetry: str) -> ExecutorOutcomeV2:
    return ExecutorOutcomeV2(
        success=False, result_code=code,
        telemetry_metadata=MappingProxyType(_validate_telemetry(telemetry)),
    )


# =====================================================================
# Shared TOC/TOU helpers
# =====================================================================

def _find_pending_by_id(
    ctx: ExecutorContextV2, target_id: str,
) -> Optional[PendingAction]:
    """Re-read every pending source and return the one matching
    ``target_id`` for this vault + session, or None if it is no
    longer visible.
    """
    live = read_all_pending(
        vault_id=ctx.vault_id,
        session_id=ctx.session_id,
        memory=ctx.memory,
        now=ctx.now,
    )
    for p in live:
        if p.action_id == target_id and p.vault_id == ctx.vault_id:
            return p
    return None


def _find_pending_by_kinds(
    ctx: ExecutorContextV2, kinds: frozenset[str],
) -> Optional[PendingAction]:
    """Return the highest-priority live pending action whose
    ``kind`` is in ``kinds``, for this vault + session."""
    live = read_all_pending(
        vault_id=ctx.vault_id,
        session_id=ctx.session_id,
        memory=ctx.memory,
        now=ctx.now,
    )
    for p in live:
        if p.kind in kinds and p.vault_id == ctx.vault_id:
            return p
    return None


def _require_action_kind(
    ctx: ExecutorContextV2, expected: str,
) -> Optional[ExecutorOutcomeV2]:
    if ctx.plan.action_kind != expected:
        logger.warning(
            "[ADAPTER_V2] action_kind_mismatch expected=%s got=%s",
            expected, ctx.plan.action_kind,
        )
        return _fail(RESULT_AUTHORIZATION_CONTEXT_INVALID,
                     action_kind=ctx.plan.action_kind)
    return None


def _require_target_kind(
    ctx: ExecutorContextV2, expected: str,
) -> Optional[ExecutorOutcomeV2]:
    if ctx.target_kind != expected:
        logger.warning(
            "[ADAPTER_V2] target_kind_mismatch expected=%s got=%s",
            expected, ctx.target_kind,
        )
        return _fail(RESULT_AUTHORIZATION_CONTEXT_INVALID,
                     target_kind=ctx.target_kind)
    return None


# =====================================================================
# Adapter: confirm_save (login draft)
# =====================================================================

_LOGIN_DRAFT_PENDING_KINDS: frozenset[str] = frozenset({
    KIND_SAVE_LOGIN_DRAFT,
    KIND_SAVE_CREDENTIAL,
})


def adapter_confirm_save_login(ctx: ExecutorContextV2) -> None:
    """Save a confirmed login draft.

    Contract:
        * expected action_kind == CONFIRM_SAVE
        * re-reads the live pending login/credential draft
        * resolves the held password from
          memory['pending_login_draft']['password'] (phase-1
          held-secret mechanism)
        * calls main.save_secret_tool(..., generated=True) once
        * clears memory['pending_login_draft'] ONLY after save
          success
        * on any failure, leaves memory intact so a retry (with
          fresh authorization) can succeed
    """
    err = _require_action_kind(ctx, ACTION_KIND_CONFIRM_SAVE)
    if err is not None:
        ctx.record_outcome(err)
        raise ExecutorError(err.result_code)

    err = _require_target_kind(ctx, TARGET_KIND_DRAFT)
    if err is not None:
        ctx.record_outcome(err)
        raise ExecutorError(err.result_code)

    # TOC/TOU: re-read the live pending draft. The v2 target_id is
    # the Draft.draft_id (v2's own draft store). The v1 held-secret
    # + service label live in memory['pending_login_draft']. Both
    # must be present.
    from vault_chat_draft import get_draft as get_v2_draft
    v2_draft = get_v2_draft(ctx.vault_id, ctx.target_id or "")
    if v2_draft is None:
        ctx.record_outcome(_fail(RESULT_TARGET_STALE,
                                  target_kind=ctx.target_kind))
        raise ExecutorError(RESULT_TARGET_STALE)
    if v2_draft.vault_id != ctx.vault_id:
        ctx.record_outcome(_fail(RESULT_AUTHORIZATION_CONTEXT_INVALID,
                                  target_kind=ctx.target_kind))
        raise ExecutorError(RESULT_AUTHORIZATION_CONTEXT_INVALID)

    # The v2 draft is expected to hold service + username fields
    # and an opaque password_ref. Refuse if the ref is not the
    # phase-1 shape.
    service_field = v2_draft.fields.get("service")
    username_field = v2_draft.fields.get("username")
    password_ref_field = v2_draft.fields.get("password_ref")
    if service_field is None or username_field is None or password_ref_field is None:
        ctx.record_outcome(_fail(RESULT_VALIDATION_FAILED))
        raise ExecutorError(RESULT_VALIDATION_FAILED)
    if password_ref_field.value != "memory:pending_login_draft:password":
        ctx.record_outcome(_fail(RESULT_VALIDATION_FAILED,
                                  resolved_password_ref="unexpected_ref_shape"))
        raise ExecutorError(RESULT_VALIDATION_FAILED)

    # Resolve the held password.
    memory = ctx.memory
    raw_password: Optional[str] = None
    if memory is not None:
        try:
            d = memory.get("pending_login_draft")
        except Exception:
            d = None
        if isinstance(d, dict):
            pw = d.get("password")
            if isinstance(pw, str) and pw:
                raw_password = pw
    if not raw_password:
        ctx.record_outcome(_fail(RESULT_NOT_FOUND,
                                  resolved_password_ref="held_secret_missing"))
        raise ExecutorError(RESULT_NOT_FOUND)

    # Vault key check (save_secret_tool encrypts).
    if not isinstance(ctx.key, (bytes, bytearray)) or len(ctx.key) != 32:
        ctx.record_outcome(_fail(RESULT_DEPENDENCY_UNAVAILABLE))
        raise ExecutorError(RESULT_DEPENDENCY_UNAVAILABLE)

    # Call the underlying save.
    try:
        from main import save_secret_tool
    except Exception:
        logger.exception("[ADAPTER_V2] confirm_save_import_failed")
        ctx.record_outcome(_fail(RESULT_DEPENDENCY_UNAVAILABLE))
        raise ExecutorError(RESULT_DEPENDENCY_UNAVAILABLE)

    args = {
        "service":  str(service_field.value),
        "username": str(username_field.value),
        "password": raw_password,
    }
    # Optional URL and notes if present.
    url_field = v2_draft.fields.get("url")
    if url_field is not None and url_field.value:
        args["url"] = str(url_field.value)
    notes_field = v2_draft.fields.get("notes")
    if notes_field is not None and notes_field.value:
        args["notes"] = str(notes_field.value)

    try:
        save_secret_tool(
            ctx.vault_id, args, bytes(ctx.key), generated=True,
        )
    except Exception as exc:
        logger.exception("[ADAPTER_V2] save_secret_tool_failed")
        # Held password NOT cleared -- user can retry with fresh auth.
        ctx.record_outcome(_fail(RESULT_EXECUTOR_EXCEPTION,
                                  underlying_band="exception"))
        raise ExecutorError(RESULT_EXECUTOR_EXCEPTION)

    # Success -- clear the held secret and the v2 draft.
    if memory is not None:
        try:
            memory.pop("pending_login_draft", None)
        except Exception:
            logger.warning(
                "[ADAPTER_V2] held_secret_clear_failed vault=%s",
                (ctx.vault_id or "")[:8] + "…",
            )
    try:
        from vault_chat_draft import consume_draft
        consume_draft(ctx.vault_id, ctx.target_id or "")
    except Exception:
        logger.warning(
            "[ADAPTER_V2] v2_draft_consume_failed vault=%s",
            (ctx.vault_id or "")[:8] + "…",
        )

    ctx.record_outcome(_ok(
        underlying_band="ok",
        action_kind=ACTION_KIND_CONFIRM_SAVE,
        resolved_password_ref="held_secret_consumed",
    ))


# =====================================================================
# Adapter: confirm_delete
# =====================================================================

def adapter_confirm_delete(ctx: ExecutorContextV2) -> None:
    """Execute a confirmed destructive delete of a secure item.

    Wraps ``vault_secure_item_save._execute_pending_delete``
    (the Bug-C-corrected path that requires db_executor).
    """
    err = _require_action_kind(ctx, ACTION_KIND_CONFIRM_DELETE)
    if err is not None:
        ctx.record_outcome(err)
        raise ExecutorError(err.result_code)

    err = _require_target_kind(ctx, TARGET_KIND_PENDING_ACTION)
    if err is not None:
        ctx.record_outcome(err)
        raise ExecutorError(err.result_code)

    # TOC/TOU: re-read the live pending delete intent by id.
    live = _find_pending_by_id(ctx, ctx.target_id or "")
    if live is None:
        ctx.record_outcome(_fail(RESULT_TARGET_STALE))
        raise ExecutorError(RESULT_TARGET_STALE)
    if live.kind != KIND_DELETE_SECURE_ITEM:
        ctx.record_outcome(_fail(RESULT_AUTHORIZATION_CONTEXT_INVALID,
                                  action_kind=ACTION_KIND_CONFIRM_DELETE))
        raise ExecutorError(RESULT_AUTHORIZATION_CONTEXT_INVALID)
    if live.vault_id != ctx.vault_id:
        ctx.record_outcome(_fail(RESULT_AUTHORIZATION_CONTEXT_INVALID))
        raise ExecutorError(RESULT_AUTHORIZATION_CONTEXT_INVALID)

    if not isinstance(ctx.key, (bytes, bytearray)) or len(ctx.key) != 32:
        ctx.record_outcome(_fail(RESULT_DEPENDENCY_UNAVAILABLE))
        raise ExecutorError(RESULT_DEPENDENCY_UNAVAILABLE)

    try:
        from vault_secure_item_save import _execute_pending_delete
    except Exception:
        logger.exception("[ADAPTER_V2] confirm_delete_import_failed")
        ctx.record_outcome(_fail(RESULT_DEPENDENCY_UNAVAILABLE))
        raise ExecutorError(RESULT_DEPENDENCY_UNAVAILABLE)

    try:
        result = _execute_pending_delete(
            vault_id=ctx.vault_id,
            key=bytes(ctx.key),
            db_executor=ctx.db_executor,
        )
    except Exception:
        logger.exception("[ADAPTER_V2] execute_pending_delete_failed")
        ctx.record_outcome(_fail(RESULT_EXECUTOR_EXCEPTION))
        raise ExecutorError(RESULT_EXECUTOR_EXCEPTION)

    band = str(result.get("band") or "")
    # Band-to-result mapping. See vault_secure_item_save bands.
    if band == "deleted":
        count = int(result.get("count") or 0)
        ctx.record_outcome(_ok(
            underlying_band="deleted",
            underlying_count=str(count),
            action_kind=ACTION_KIND_CONFIRM_DELETE,
        ))
        return
    if band == "no_pending_delete":
        ctx.record_outcome(_fail(RESULT_TARGET_STALE,
                                  underlying_band=band))
        raise ExecutorError(RESULT_TARGET_STALE)
    if band == "vault_locked":
        ctx.record_outcome(_fail(RESULT_AUTHORIZATION_CONTEXT_INVALID,
                                  underlying_band=band))
        raise ExecutorError(RESULT_AUTHORIZATION_CONTEXT_INVALID)
    if band == "db_error":
        ctx.record_outcome(_fail(RESULT_DEPENDENCY_UNAVAILABLE,
                                  underlying_band=band))
        raise ExecutorError(RESULT_DEPENDENCY_UNAVAILABLE)
    # Unknown band -- treat as EXECUTOR_EXCEPTION (do NOT swallow).
    ctx.record_outcome(_fail(RESULT_EXECUTOR_EXCEPTION,
                              underlying_band=band or "unknown"))
    raise ExecutorError(RESULT_EXECUTOR_EXCEPTION)


# =====================================================================
# Adapter: confirm_save_attachment
# =====================================================================

def adapter_confirm_save_attachment(ctx: ExecutorContextV2) -> None:
    """Name and save a pending attachment (unnamed uploaded file).

    Wraps ``main.save_named_uploaded_asset``. Retains the Bug-B
    strict binding semantics: the pending attachment is admitted
    only via ``vault_chat_pending_action._read_bound_attachment``
    (which requires a fresh upload binding for the current
    session).
    """
    err = _require_action_kind(ctx, ACTION_KIND_CONFIRM_SAVE_ATTACHMENT)
    if err is not None:
        ctx.record_outcome(err)
        raise ExecutorError(err.result_code)

    err = _require_target_kind(ctx, TARGET_KIND_PENDING_ACTION)
    if err is not None:
        ctx.record_outcome(err)
        raise ExecutorError(err.result_code)

    live = _find_pending_by_id(ctx, ctx.target_id or "")
    if live is None:
        ctx.record_outcome(_fail(RESULT_TARGET_STALE))
        raise ExecutorError(RESULT_TARGET_STALE)
    if live.kind != KIND_SAVE_ATTACHMENT:
        ctx.record_outcome(_fail(RESULT_AUTHORIZATION_CONTEXT_INVALID))
        raise ExecutorError(RESULT_AUTHORIZATION_CONTEXT_INVALID)
    if live.vault_id != ctx.vault_id:
        ctx.record_outcome(_fail(RESULT_AUTHORIZATION_CONTEXT_INVALID))
        raise ExecutorError(RESULT_AUTHORIZATION_CONTEXT_INVALID)

    uploaded_file_id = str(live.metadata.get("uploaded_file_id") or "")
    if not uploaded_file_id:
        ctx.record_outcome(_fail(RESULT_VALIDATION_FAILED))
        raise ExecutorError(RESULT_VALIDATION_FAILED)

    # The router's validated_patch carries the user-supplied name.
    saved_name: Optional[str] = None
    if ctx.validated_patch is not None:
        item = ctx.validated_patch.get("name")
        if item is not None and item.op == "replace" and item.value:
            saved_name = str(item.value).strip()
    if not saved_name:
        ctx.record_outcome(_fail(RESULT_VALIDATION_FAILED))
        raise ExecutorError(RESULT_VALIDATION_FAILED)

    try:
        from main import save_named_uploaded_asset
    except Exception:
        logger.exception("[ADAPTER_V2] save_attachment_import_failed")
        ctx.record_outcome(_fail(RESULT_DEPENDENCY_UNAVAILABLE))
        raise ExecutorError(RESULT_DEPENDENCY_UNAVAILABLE)

    key_arg: Optional[bytes] = None
    if isinstance(ctx.key, (bytes, bytearray)) and len(ctx.key) == 32:
        key_arg = bytes(ctx.key)

    try:
        result = save_named_uploaded_asset(
            ctx.vault_id, uploaded_file_id, saved_name, key=key_arg,
        )
    except Exception:
        logger.exception("[ADAPTER_V2] save_named_uploaded_asset_failed")
        ctx.record_outcome(_fail(RESULT_EXECUTOR_EXCEPTION))
        raise ExecutorError(RESULT_EXECUTOR_EXCEPTION)

    # Clear the binding after the save (matches the v1 flow).
    try:
        from vault_chat_upload_binding import clear_binding
        clear_binding(vault_id=ctx.vault_id,
                       uploaded_file_id=uploaded_file_id)
    except Exception:
        logger.warning("[ADAPTER_V2] clear_binding_failed after save")

    content_type = str(live.metadata.get("content_type") or "")
    ctx.record_outcome(_ok(
        underlying_band="ok",
        attachment_content_type=content_type,
        action_kind=ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
    ))


# =====================================================================
# Adapter: cancel_pending (per source_kind dispatch)
# =====================================================================

def adapter_cancel_pending(ctx: ExecutorContextV2) -> None:
    """Cancel a live pending action. Dispatches to the correct
    cancellation primitive by the pending action's source_kind.
    """
    err = _require_action_kind(ctx, ACTION_KIND_CANCEL_PENDING)
    if err is not None:
        ctx.record_outcome(err)
        raise ExecutorError(err.result_code)

    err = _require_target_kind(ctx, TARGET_KIND_PENDING_ACTION)
    if err is not None:
        ctx.record_outcome(err)
        raise ExecutorError(err.result_code)

    live = _find_pending_by_id(ctx, ctx.target_id or "")
    if live is None:
        # Idempotent: nothing to cancel.
        ctx.record_outcome(_ok(
            cancel_kind="already_gone",
            action_kind=ACTION_KIND_CANCEL_PENDING,
        ))
        return
    if live.vault_id != ctx.vault_id:
        ctx.record_outcome(_fail(RESULT_AUTHORIZATION_CONTEXT_INVALID))
        raise ExecutorError(RESULT_AUTHORIZATION_CONTEXT_INVALID)

    source = live.source_kind
    try:
        if source == SOURCE_SECURE_DELETE_INTENT:
            from vault_secure_item_save import _cancel_pending_delete
            _cancel_pending_delete(vault_id=ctx.vault_id)
        elif source == SOURCE_CREDENTIAL_DRAFT:
            from vault_credential_draft import consume_draft as cred_consume
            cred_consume(vault_id=ctx.vault_id)
        elif source == SOURCE_MEMORY_LOGIN_DRAFT:
            if ctx.memory is not None:
                try:
                    ctx.memory.pop("pending_login_draft", None)
                except Exception:
                    logger.warning(
                        "[ADAPTER_V2] memory_login_draft_cancel_failed"
                    )
        elif source == SOURCE_UPLOADED_FILE:
            from vault_chat_upload_binding import clear_binding
            uploaded_file_id = str(
                live.metadata.get("uploaded_file_id") or "",
            )
            if uploaded_file_id:
                clear_binding(
                    vault_id=ctx.vault_id,
                    uploaded_file_id=uploaded_file_id,
                )
        elif source == SOURCE_SECURE_ITEM_DRAFT:
            from vault_secure_item_draft import (
                clear_secure_item_drafts_for_vault,
            )
            clear_secure_item_drafts_for_vault(ctx.vault_id)
        else:
            ctx.record_outcome(_fail(RESULT_VALIDATION_FAILED,
                                      source_kind=source or "unknown"))
            raise ExecutorError(RESULT_VALIDATION_FAILED)
    except ExecutorError:
        raise
    except Exception:
        logger.exception(
            "[ADAPTER_V2] cancel_pending_failed source=%s", source,
        )
        ctx.record_outcome(_fail(RESULT_EXECUTOR_EXCEPTION,
                                  source_kind=source or "unknown"))
        raise ExecutorError(RESULT_EXECUTOR_EXCEPTION)

    ctx.record_outcome(_ok(
        cancel_kind="cancelled",
        source_kind=source,
        action_kind=ACTION_KIND_CANCEL_PENDING,
    ))


# =====================================================================
# Bridge: integration kwargs -> ExecutorContextV2 -> adapter call
# =====================================================================

def _make_adapter_executor(
    adapter: Callable[[ExecutorContextV2], None],
) -> Callable[..., None]:
    """Wrap an adapter callable so integration can invoke it
    with its permissive ``**kwargs`` calling convention.

    Integration passes (plan, snapshot, key, memory, vault_id,
    session_id). The wrapper builds an ``ExecutorContextV2`` and
    hands it to the adapter. Any ``ExecutorError`` raised by the
    adapter propagates up so integration returns EXECUTOR_FAILED.
    """
    def _executor(**kwargs) -> None:
        plan = kwargs.get("plan")
        snapshot = kwargs.get("snapshot")
        if plan is None or snapshot is None:
            raise ExecutorError("adapter_context_missing_plan_or_snapshot")
        ctx = ExecutorContextV2(
            vault_id=str(kwargs.get("vault_id") or ""),
            session_id=kwargs.get("session_id"),
            user_turn_id=str(getattr(
                snapshot, "current_user_turn_id", "",
            ) or ""),
            target_kind=str(plan.target_kind or ""),
            target_id=plan.target_id,
            validated_patch=plan.validated_patch,
            db_executor=kwargs.get("db_executor"),
            key=kwargs.get("key") or b"",
            memory=kwargs.get("memory"),
            plan=plan,
            snapshot=snapshot,
        )
        adapter(ctx)
        # If the adapter forgot to record an outcome, treat as
        # internal exception rather than silent success.
        if ctx.outcome is None:
            raise ExecutorError("adapter_recorded_no_outcome")
    return _executor


# =====================================================================
# Registry factory
# =====================================================================

class RegistryConstructionError(Exception):
    """Raised when build_production_executor_registry cannot
    produce a registration for a required action_kind. The
    exception carries the missing kinds so operators can see
    exactly which adapter failed to import."""


def build_production_executor_registry() -> ExecutorRegistry:
    """Return the production ``ExecutorRegistry`` with all
    ``EXECUTOR_REQUIRED_ACTION_KINDS`` wired to their adapters.

    Import failures are surfaced (via
    ``RegistryConstructionError``) rather than hidden -- an
    incomplete registry would fail the readiness guard anyway,
    but a construction error names the exact problem for
    operators.

    Adapters that reach V1 code (main.save_secret_tool,
    _execute_pending_delete, save_named_uploaded_asset) do their
    imports inside the adapter body so this factory can construct
    a full registry even when the app is not yet booted.
    """
    try:
        registry = ExecutorRegistry(
            confirm_save=_make_adapter_executor(adapter_confirm_save_login),
            confirm_delete=_make_adapter_executor(adapter_confirm_delete),
            confirm_save_attachment=_make_adapter_executor(
                adapter_confirm_save_attachment,
            ),
            cancel_pending=_make_adapter_executor(adapter_cancel_pending),
        )
    except Exception as exc:
        raise RegistryConstructionError(
            f"failed to construct production executor registry: {exc}"
        ) from exc
    # Sanity check: every EXECUTOR_REQUIRED kind maps to a callable.
    missing = []
    for kind in sorted(EXECUTOR_REQUIRED_ACTION_KINDS):
        if registry.get(kind) is None:
            missing.append(kind)
    if missing:
        raise RegistryConstructionError(
            "production registry missing adapters for: "
            f"{','.join(missing)}"
        )
    return registry


__all__ = [
    "RESULT_SUCCESS",
    "RESULT_TARGET_STALE",
    "RESULT_VALIDATION_FAILED",
    "RESULT_NOT_FOUND",
    "RESULT_CONFLICT",
    "RESULT_AUTHORIZATION_CONTEXT_INVALID",
    "RESULT_DEPENDENCY_UNAVAILABLE",
    "RESULT_EXECUTOR_EXCEPTION",
    "RESULT_CODES",
    "ALLOWED_TELEMETRY_KEYS",
    "TelemetryValidationError",
    "ExecutorContextV2",
    "ExecutorOutcomeV2",
    "adapter_confirm_save_login",
    "adapter_confirm_delete",
    "adapter_confirm_save_attachment",
    "adapter_cancel_pending",
    "build_production_executor_registry",
    "RegistryConstructionError",
]
