"""Top-level v2 orchestrator + feature flag reader.

Called by ``vault_chat_brain.run_chat_brain`` when
``VAULTAI_CHAT_BRAIN_MODE in {"shadow", "on"}``. Owns:

    * feature-flag reading + validation (fails closed to ``off``);
    * snapshot construction from live Redis + memory state
      (redacted -- see snapshot-redaction rules below);
    * pipeline invocation: decider_v2 -> policy_v2 -> router_v2 ->
      integration_v2;
    * reply rendering from ``RouterResultV2`` +
      ``IntegrationResultV2`` (deferred templates from router_v2).

Never modifies ``main.py``, ``vault_chat_decision_router.py`` (v1),
or ``vault_chat_policy.py`` (v1). Never invokes v1 within a v2
request -- mixed execution is forbidden.

Snapshot redaction rules (commit 5a)
------------------------------------
The decider prompt payload NEVER contains:

    * raw ``vault_id`` or ``session_id`` (the caller keeps them for
      side effects; the prompt payload omits them);
    * password_ref values (Draft.to_prompt_dict(redact_secrets=True)
      returns ``{present, source}`` only);
    * decrypted vault content, ciphertext, tokens, PINs, encryption
      keys, attachment ciphertext, attachment extraction text;
    * authorization record ids or Redis keys.

The decider prompt payload MAY contain (deliberate, per design):

    * usernames, email addresses, and service names embedded in
      draft fields -- required so the model can honor edits like
      "use my email as the username". These values MUST NEVER
      appear in shadow logs, fingerprints, or telemetry.
    * ``PendingAction.target_label`` -- short human-readable labels
      (e.g. "Instagram login") already curated as safe-to-show;
      they never appear in shadow logs / telemetry.

Failure invariant (commit 5a: V2ExecutionPhase)
-----------------------------------------------
``run_v2_authoritative`` tracks an execution phase:

    PHASE_READ_ONLY          -- snapshot / decider / policy / router
    PHASE_INTEGRATION_STARTED-- apply_router_result_v2 has been called
                                (any immediate focus write may have
                                landed; auth mint/consume may follow)
    PHASE_EXECUTOR_STARTED   -- integration reported the executor was
                                dispatched
    PHASE_EXECUTOR_COMPLETED -- executor returned (success or error);
                                integration produced a result

V1 fallback via ``VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK=on`` is honored
ONLY when the phase is ``PHASE_READ_ONLY`` at the moment the
exception is caught. In every later phase, an uncontrolled failure
resolves to a controlled error reply -- never a V1 fallthrough,
because at that point state mutation may already have happened and
a second V1 pass would risk a duplicate operation.

Runtime readiness guard (commit 5a)
-----------------------------------
Mode ``on`` requires that every ``ACTION_KIND_*`` the router can
emit maps to a real executor in the injected registry. The brain
calls ``validate_v2_runtime_readiness(registry)`` before entering
authoritative execution; if the registry is incomplete, mode-on
is refused with a controlled unavailable response, not silently
downgraded.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple

from vault_chat_authorization_record import AuthorizationRecord  # noqa: F401
from vault_chat_decision_router_v2 import (
    REPLY_KIND_CLARIFICATION,
    REPLY_KIND_EXECUTION_REQUIRED,
    REPLY_KIND_NONE,
    REPLY_KIND_REJECTION,
    RouterResultV2,
    get_failure_reply,
    get_success_reply,
    route_v2,
)
from vault_chat_draft import (
    Draft,
    list_live_drafts,
)
from vault_chat_focus import (
    ConversationalFocus,
    read_focus,
)
from vault_chat_integration_v2 import (
    ExecutorRegistry,
    IntegrationResultV2,
    STATUS_EXECUTOR_FAILED,
    STATUS_INTERNAL_ERROR,
    STATUS_NO_EXECUTION,
    STATUS_SUCCESS,
    apply_router_result_v2,
    validate_v2_runtime_readiness,
)
from vault_chat_pending_action import (
    PendingAction,
    read_all_pending,
)
from vault_chat_policy_v2 import (
    PolicySnapshotV2,
    authorize_v2,
    PolicyResultV2,
)
from vault_chat_semantic_decider_v2 import (
    SemanticDecisionV2Context,
    decide_v2,
)
from vault_chat_semantic_decision_v2 import (
    SemanticDecisionV2,
    make_fallthrough,
)
from vault_chat_shadow_recorder_v2 import build_and_log_diff


logger = logging.getLogger(__name__)


# =====================================================================
# Feature-flag reader
# =====================================================================

MODE_OFF:     str = "off"
MODE_SHADOW:  str = "shadow"
MODE_ON:      str = "on"

MODES: frozenset[str] = frozenset({MODE_OFF, MODE_SHADOW, MODE_ON})

_ENV_MODE:            str = "VAULTAI_CHAT_BRAIN_MODE"
_ENV_V1_FALLBACK:     str = "VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK"


def read_brain_mode() -> str:
    """Read and validate the chat-brain mode. Unknown values log
    a WARNING and fall back to ``off``."""
    raw = (os.environ.get(_ENV_MODE) or MODE_OFF).strip().lower()
    if raw in MODES:
        return raw
    logger.warning(
        "[BRAIN_V2] unknown mode %r; falling back to off", raw,
    )
    return MODE_OFF


def v1_fallback_enabled() -> bool:
    return (os.environ.get(_ENV_V1_FALLBACK) or "").strip().lower() == "on"


# =====================================================================
# Execution phase (V2ExecutionPhase) -- side-effect boundary for
# V1 fallback eligibility.
# =====================================================================

class V2ExecutionPhase(str, Enum):
    READ_ONLY            = "READ_ONLY"
    INTEGRATION_STARTED  = "INTEGRATION_STARTED"
    EXECUTOR_STARTED     = "EXECUTOR_STARTED"
    EXECUTOR_COMPLETED   = "EXECUTOR_COMPLETED"


# Only READ_ONLY is fallback-eligible. Every later phase means a
# state mutation (immediate focus write, auth mint, consume,
# executor call, etc.) may have landed; a second V1 pass could
# duplicate the operation.
_FALLBACK_ELIGIBLE_PHASES: frozenset[V2ExecutionPhase] = frozenset({
    V2ExecutionPhase.READ_ONLY,
})


# =====================================================================
# Reply rendering
# =====================================================================

CONTROLLED_ERROR_REPLY: str = (
    "Sorry - I ran into a problem handling that. Please try again."
)

CONTROLLED_UNAVAILABLE_REPLY: str = (
    "Sorry - this feature isn't ready in this environment yet. "
    "Please try again shortly."
)


def _render_reply(
    router_result: RouterResultV2,
    integration_result: Optional[IntegrationResultV2],
) -> str:
    if router_result.reply_kind == REPLY_KIND_NONE:
        return ""
    if router_result.reply_kind == REPLY_KIND_CLARIFICATION:
        return router_result.reply_text
    if router_result.reply_kind == REPLY_KIND_REJECTION:
        return router_result.reply_text
    if router_result.reply_kind == REPLY_KIND_EXECUTION_REQUIRED:
        if integration_result is None:
            return CONTROLLED_ERROR_REPLY
        key = integration_result.reply_key or ""
        if integration_result.execution_status == STATUS_SUCCESS:
            text = get_success_reply(key)
            return text or CONTROLLED_ERROR_REPLY
        text = get_failure_reply(key)
        return text or CONTROLLED_ERROR_REPLY
    return router_result.reply_text or CONTROLLED_ERROR_REPLY


# =====================================================================
# Snapshot construction (redacted)
# =====================================================================

@dataclass(frozen=True)
class _V2Snapshot:
    policy_snapshot:     PolicySnapshotV2
    decider_context:     SemanticDecisionV2Context


def _build_v2_snapshot(
    *,
    vault_id:                       str,
    session_id:                     Optional[str],
    user_message:                   str,
    current_user_turn_id:           str,
    preceding_assistant_turn_id:    str,
    memory:                         Any,
    now:                            Optional[float] = None,
) -> _V2Snapshot:
    """Build a redacted snapshot from live state.

    The decider context deliberately carries ``vault_id=""`` and
    ``session_id=None`` -- policy still holds the real values so
    side effects and correlation work, but the prompt-serialized
    payload the model sees never contains them. Any Redis key,
    authorization id, ciphertext, or token is likewise absent by
    construction (source dataclasses' ``to_prompt_dict`` methods
    do not expose them).
    """
    when = float(now) if now is not None else time.time()

    live_drafts = list_live_drafts(
        vault_id=vault_id, session_id=session_id, now=when,
    ) or []
    live_pending = read_all_pending(
        vault_id=vault_id, session_id=session_id,
        memory=memory, now=when,
    ) or []
    focus_record = read_focus(
        vault_id=vault_id, session_id=session_id, now=when,
    )

    policy_snapshot = PolicySnapshotV2(
        vault_id=vault_id,
        session_id=session_id,
        current_user_turn_id=current_user_turn_id,
        preceding_assistant_turn_id=preceding_assistant_turn_id,
        now=when,
        active_drafts=tuple(live_drafts),
        pending_actions=tuple(live_pending),
        focus=focus_record,
    )

    active_draft_views = tuple(
        d.to_prompt_dict(redact_secrets=True) for d in live_drafts
    )
    pending_views = tuple(
        p.to_prompt_dict() for p in live_pending
    )
    focus_view = _focus_to_view(focus_record)
    known_ids = frozenset(
        [d.draft_id for d in live_drafts]
        + [p.action_id for p in live_pending]
    )

    # NOTE: vault_id / session_id deliberately blanked in the
    # decider context so build_prompt_v2's payload cannot leak
    # them into the LLM prompt.
    decider_context = SemanticDecisionV2Context(
        vault_id="",
        session_id=None,
        user_message=user_message,
        active_drafts=active_draft_views,
        pending_actions=pending_views,
        focus=focus_view,
        recent_turns=(),
        conversation_digest="",
        known_target_ids=known_ids,
    )

    return _V2Snapshot(
        policy_snapshot=policy_snapshot,
        decider_context=decider_context,
    )


def _focus_to_view(focus: Optional[ConversationalFocus]) -> Optional[dict]:
    if focus is None:
        return None
    return {
        "kind":              focus.kind,
        "id":                focus.id,
        "assistant_act":     focus.assistant_act,
        "assistant_turn_id": focus.assistant_turn_id,
        "age_seconds":       max(0, int(time.time() - focus.at)),
    }


# =====================================================================
# BrainResult-like return type
# =====================================================================

@dataclass(frozen=True)
class BrainV2Result:
    handled:            bool
    reply_text:         str = ""
    tool:               str = ""
    fallthrough_reason: str = ""


CONTROLLED_ERROR_RESULT: BrainV2Result = BrainV2Result(
    handled=True,
    reply_text=CONTROLLED_ERROR_REPLY,
    tool="",
    fallthrough_reason="v2_controlled_error",
)

CONTROLLED_UNAVAILABLE_RESULT: BrainV2Result = BrainV2Result(
    handled=True,
    reply_text=CONTROLLED_UNAVAILABLE_REPLY,
    tool="",
    fallthrough_reason="v2_not_ready_on_mode",
)


# =====================================================================
# ai_provider getter (indirect so tests can inject)
# =====================================================================

def _default_ai_provider():
    from vault_ai_provider import chat_complete_with_fallback
    return chat_complete_with_fallback


# =====================================================================
# Authoritative v2 execution
# =====================================================================

async def run_v2_authoritative(
    *,
    vault_id:                       str,
    session_id:                     Optional[str],
    turn_id:                        str,
    user_message:                   str,
    key:                            bytes = b"",
    memory:                         Any = None,
    executor_registry:              ExecutorRegistry,
    ai_provider:                    Any = None,
    preceding_assistant_turn_id:    str = "",
    assistant_turn_id:              str = "",
) -> BrainV2Result:
    """Run v2 end-to-end when the mode is ``on``.

    Every exception is caught here -- never propagates to the
    caller. V1 fallback is honored ONLY when the exception was
    caught while phase == READ_ONLY. Later-phase failures always
    become a controlled error reply.
    """
    phase = V2ExecutionPhase.READ_ONLY

    try:
        snap = _build_v2_snapshot(
            vault_id=vault_id, session_id=session_id,
            user_message=user_message,
            current_user_turn_id=turn_id,
            preceding_assistant_turn_id=preceding_assistant_turn_id,
            memory=memory,
        )
    except Exception:
        logger.exception("[BRAIN_V2] snapshot_build_failed_on")
        return _handle_on_exception("snapshot_build_failed", phase)

    ai = ai_provider or _default_ai_provider()

    try:
        decision = await decide_v2(
            snap.decider_context, ai_provider=ai,
        )
    except Exception:
        logger.exception("[BRAIN_V2] decider_v2_failed_on")
        return _handle_on_exception("decider_failed", phase)

    try:
        policy_result = authorize_v2(
            snapshot=snap.policy_snapshot, decision=decision,
        )
    except Exception:
        logger.exception("[BRAIN_V2] policy_v2_failed_on")
        return _handle_on_exception("policy_failed", phase)

    try:
        router_result = route_v2(
            policy_result=policy_result, decision=decision,
        )
    except Exception:
        logger.exception("[BRAIN_V2] router_v2_failed_on")
        return _handle_on_exception("router_failed", phase)

    if not router_result.handled:
        # Router explicitly deferred to fallthrough -- still
        # READ_ONLY, so this is a legitimate hand-off. Not a V2
        # error; the caller (brain.py) treats the return as a
        # normal v2 fallthrough.
        return BrainV2Result(
            handled=False,
            fallthrough_reason=(
                router_result.reason_code or "v2_fallthrough"
            ),
        )

    # -------------------------------------------------------------
    # Cross the side-effect boundary. From here on, no fallback.
    # -------------------------------------------------------------
    phase = V2ExecutionPhase.INTEGRATION_STARTED
    try:
        integration_result = apply_router_result_v2(
            router_result=router_result,
            snapshot=snap.policy_snapshot,
            executor_registry=executor_registry,
            key=key,
            memory=memory,
            assistant_turn_id=assistant_turn_id or turn_id,
            created_target_id=None,
        )
    except Exception:
        logger.exception("[BRAIN_V2] integration_v2_failed_on")
        return _handle_on_exception("integration_failed", phase)

    # Integration always returns a stable result. Executor may or
    # may not have been called -- integration reports that via
    # execution_status. Regardless, we are no longer READ_ONLY:
    # the integration attempted its immediate focus write.
    if integration_result.execution_status in (
        STATUS_SUCCESS, STATUS_EXECUTOR_FAILED,
    ):
        phase = V2ExecutionPhase.EXECUTOR_COMPLETED

    try:
        reply = _render_reply(router_result, integration_result)
    except Exception:
        logger.exception("[BRAIN_V2] render_reply_failed_on")
        return _handle_on_exception("render_reply_failed", phase)

    tool = (
        integration_result.executed_action_kind
        or router_result.normalized_intent
        or ""
    )
    return BrainV2Result(
        handled=True,
        reply_text=reply,
        tool=tool,
        fallthrough_reason="",
    )


def _handle_on_exception(
    reason: str, phase: V2ExecutionPhase,
) -> BrainV2Result:
    """Failure handling per the phase-boundary invariant.

    V1 fallback is honored only when phase is READ_ONLY at the
    moment of the exception AND the operator explicitly enabled
    fallback via env var. In every later phase, the failure
    becomes a controlled error reply regardless of the env var
    -- state mutation may already have landed and a second V1
    pass could duplicate the operation.
    """
    fallback_eligible = phase in _FALLBACK_ELIGIBLE_PHASES
    if fallback_eligible and v1_fallback_enabled():
        return BrainV2Result(
            handled=False,
            fallthrough_reason=(
                f"v2_error_v1_fallback:{reason}:phase={phase.value}"
            ),
        )
    # Not eligible OR env not set -> controlled error.
    if not fallback_eligible and v1_fallback_enabled():
        # Log the refusal so operators can see why the fallback env
        # did not take effect for a given failure.
        logger.warning(
            "[BRAIN_V2] v1_fallback_refused reason=%s phase=%s "
            "(post-side-effect phase not fallback-eligible)",
            reason, phase.value,
        )
    return BrainV2Result(
        handled=True,
        reply_text=CONTROLLED_ERROR_REPLY,
        tool="",
        fallthrough_reason=(
            f"v2_controlled_error:{reason}:phase={phase.value}"
        ),
    )


# =====================================================================
# Shadow run (read-only, full stack)
# =====================================================================

async def run_v2_shadow(
    *,
    vault_id:                       str,
    session_id:                     Optional[str],
    turn_id:                        str,
    user_message:                   str,
    memory:                         Any = None,
    ai_provider:                    Any = None,
    v1_tool:                        str = "",
    v1_handled:                     bool = False,
    preceding_assistant_turn_id:    str = "",
) -> None:
    """Read-only v2 evaluation for shadow mode. Runs the FULL
    decision stack up to (but not including) integration:

        _build_v2_snapshot
        -> decide_v2 (LLM call)
        -> authorize_v2 (policy)
        -> route_v2 (router)

    Emits one ``[SHADOW_V2]`` log line summarizing the router's
    verdict and the disagreement category against v1.

    STRICT invariant: this function MUST NOT
        * call ``apply_router_result_v2``,
        * mint_authorization,
        * atomic_consume_authorization,
        * dispatch an executor,
        * persist focus,
        * persist a draft,
        * mutate any pending-action row.

    Any exception is caught + logged; the caller's v1 result is
    unaffected.
    """
    try:
        snap = _build_v2_snapshot(
            vault_id=vault_id, session_id=session_id,
            user_message=user_message,
            current_user_turn_id=turn_id,
            preceding_assistant_turn_id=preceding_assistant_turn_id,
            memory=memory,
        )
    except Exception:
        logger.exception("[BRAIN_V2] shadow_snapshot_failed")
        return

    ai = ai_provider or _default_ai_provider()
    decision: Optional[SemanticDecisionV2] = None
    policy_result: Optional[PolicyResultV2] = None
    router_result: Optional[RouterResultV2] = None

    try:
        decision = await decide_v2(
            snap.decider_context, ai_provider=ai,
        )
    except Exception:
        logger.exception("[BRAIN_V2] shadow_decide_failed")
        decision = make_fallthrough(error="shadow_decider_exception")

    try:
        policy_result = authorize_v2(
            snapshot=snap.policy_snapshot, decision=decision,
        )
    except Exception:
        logger.exception("[BRAIN_V2] shadow_policy_failed")
        policy_result = None

    if policy_result is not None:
        try:
            router_result = route_v2(
                policy_result=policy_result, decision=decision,
            )
        except Exception:
            logger.exception("[BRAIN_V2] shadow_router_failed")
            router_result = None

    try:
        build_and_log_diff(
            vault_id=vault_id, session_id=session_id, turn_id=turn_id,
            v1_tool=v1_tool, v1_handled=v1_handled,
            v2_decision=decision, v2_policy=policy_result,
            v2_router=router_result,
        )
    except Exception:
        logger.exception("[BRAIN_V2] shadow_log_failed")


__all__ = [
    "MODE_OFF", "MODE_SHADOW", "MODE_ON", "MODES",
    "V2ExecutionPhase",
    "read_brain_mode", "v1_fallback_enabled",
    "CONTROLLED_ERROR_REPLY", "CONTROLLED_ERROR_RESULT",
    "CONTROLLED_UNAVAILABLE_REPLY", "CONTROLLED_UNAVAILABLE_RESULT",
    "BrainV2Result",
    "run_v2_authoritative",
    "run_v2_shadow",
]
