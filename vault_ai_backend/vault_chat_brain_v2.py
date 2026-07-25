"""Top-level v2 orchestrator + feature flag reader.

Called by ``vault_chat_brain.run_chat_brain`` when
``VAULTAI_CHAT_BRAIN_MODE ∈ {"shadow", "on"}``. Owns:

    * feature-flag reading + validation (fails closed to "off");
    * snapshot construction from live Redis + memory state
      (redacted per design memo rev 8);
    * pipeline invocation: decider_v2 → policy_v2 → router_v2 →
      integration_v2;
    * reply rendering from ``RouterResultV2`` +
      ``IntegrationResultV2`` (deferred templates from router_v2).

Never modifies ``main.py``, ``vault_chat_decision_router.py`` (v1),
or ``vault_chat_policy.py`` (v1). Never invokes v1 within a v2
request — mixed execution is forbidden.

Failure invariant
-----------------
If any component (decider / policy / router / integration) raises
unexpectedly in ``mode == on``:

    * if ``VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK == "on"`` (rollout
      override): return a fallthrough BrainResult so main.py's
      legacy pipeline handles the whole request from scratch;
    * otherwise: return a controlled error BrainResult (single-turn
      user-facing message; legacy pipeline NOT invoked).

In shadow mode any exception is caught, logged, and squashed —
the v1 result stands.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
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
# Reply rendering
# =====================================================================

CONTROLLED_ERROR_REPLY: str = (
    "Sorry — I ran into a problem handling that. Please try again."
)


def _render_reply(
    router_result: RouterResultV2,
    integration_result: Optional[IntegrationResultV2],
) -> str:
    """Turn a (router, integration) pair into the final user-facing
    text. Deterministic, template-driven. Never inspects diagnostic
    or telemetry.
    """
    if router_result.reply_kind == REPLY_KIND_NONE:
        return ""
    if router_result.reply_kind == REPLY_KIND_CLARIFICATION:
        return router_result.reply_text
    if router_result.reply_kind == REPLY_KIND_REJECTION:
        return router_result.reply_text
    if router_result.reply_kind == REPLY_KIND_EXECUTION_REQUIRED:
        if integration_result is None:
            # Should not happen — every execution-required router
            # result must be paired with an integration attempt.
            return CONTROLLED_ERROR_REPLY
        key = integration_result.reply_key or ""
        if integration_result.execution_status == STATUS_SUCCESS:
            text = get_success_reply(key)
            return text or CONTROLLED_ERROR_REPLY
        # Any non-success execution status → failure template.
        text = get_failure_reply(key)
        return text or CONTROLLED_ERROR_REPLY
    # Chat / etc. — phase 1 shouldn't reach here (chat falls through
    # via router), but be defensive.
    return router_result.reply_text or CONTROLLED_ERROR_REPLY


# =====================================================================
# Snapshot construction (redacted per design memo rev 8)
# =====================================================================

@dataclass(frozen=True)
class _V2Snapshot:
    """Combined snapshot for decider context + policy input.

    Split so callers can build once and re-use — decider needs
    prompt-facing views (redacted), policy needs the full
    ``PolicySnapshotV2`` with typed dataclasses.
    """
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

    Never puts these in the snapshot: passwords, decrypted vault
    content, tokens, PIN, encryption keys, attachment ciphertext,
    or raw sensitive credential fields. The Draft / PendingAction /
    Focus classes already return safe views via their
    ``to_prompt_dict`` methods; this function just aggregates.
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

    # Decider context uses redacted views only.
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

    decider_context = SemanticDecisionV2Context(
        vault_id=vault_id,
        session_id=session_id,
        user_message=user_message,
        active_drafts=active_draft_views,
        pending_actions=pending_views,
        focus=focus_view,
        recent_turns=(),      # phase-1: not wired
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
# BrainResult-like return type (kept structurally compatible with
# vault_chat_brain.BrainResult — brain.py just re-wraps this).
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

    Every exception is caught here — never propagates to the
    caller. Mode-on failure semantics:

        * V1_FALLBACK env == "on"  → return fallthrough so main.py
                                     runs the legacy pipeline fresh.
        * otherwise                → controlled error BrainV2Result.
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
        logger.exception("[BRAIN_V2] snapshot_build_failed_on")
        return _handle_on_exception("snapshot_build_failed")

    ai = ai_provider or _default_ai_provider()

    try:
        decision = await decide_v2(
            snap.decider_context, ai_provider=ai,
        )
    except Exception:
        logger.exception("[BRAIN_V2] decider_v2_failed_on")
        return _handle_on_exception("decider_failed")

    try:
        policy_result = authorize_v2(
            snapshot=snap.policy_snapshot, decision=decision,
        )
    except Exception:
        logger.exception("[BRAIN_V2] policy_v2_failed_on")
        return _handle_on_exception("policy_failed")

    try:
        router_result = route_v2(
            policy_result=policy_result, decision=decision,
        )
    except Exception:
        logger.exception("[BRAIN_V2] router_v2_failed_on")
        return _handle_on_exception("router_failed")

    if not router_result.handled:
        return BrainV2Result(
            handled=False,
            fallthrough_reason=(
                router_result.reason_code or "v2_fallthrough"
            ),
        )

    # Apply router intent via integration.
    try:
        integration_result = apply_router_result_v2(
            router_result=router_result,
            snapshot=snap.policy_snapshot,
            executor_registry=executor_registry,
            key=key,
            memory=memory,
            assistant_turn_id=assistant_turn_id or turn_id,
            created_target_id=None,   # populated by executor for create
        )
    except Exception:
        logger.exception("[BRAIN_V2] integration_v2_failed_on")
        return _handle_on_exception("integration_failed")

    reply = _render_reply(router_result, integration_result)
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


def _handle_on_exception(reason: str) -> BrainV2Result:
    """Failure handling per the design-memo rev-8 invariant."""
    if v1_fallback_enabled():
        return BrainV2Result(
            handled=False,
            fallthrough_reason=f"v2_error_v1_fallback:{reason}",
        )
    return BrainV2Result(
        handled=True,
        reply_text=CONTROLLED_ERROR_REPLY,
        tool="",
        fallthrough_reason=f"v2_controlled_error:{reason}",
    )


# =====================================================================
# Shadow run (read-only)
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
    """Read-only v2 evaluation for shadow mode. Never writes.
    Never mints. Never applies focus. Only builds the snapshot,
    runs decider + policy + router, and emits a shadow diff
    record via ``vault_chat_shadow_recorder_v2.build_and_log_diff``.

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

    # We DELIBERATELY do not call route_v2 for shadow — the diff
    # only needs the decision + policy verdict. Not calling
    # route_v2 also guarantees no chance of an ExecutionPlanV2
    # leaking into a caller that might act on it by mistake.

    try:
        build_and_log_diff(
            vault_id=vault_id, session_id=session_id, turn_id=turn_id,
            v1_tool=v1_tool, v1_handled=v1_handled,
            v2_decision=decision, v2_policy=policy_result,
        )
    except Exception:
        logger.exception("[BRAIN_V2] shadow_log_failed")


__all__ = [
    "MODE_OFF", "MODE_SHADOW", "MODE_ON", "MODES",
    "read_brain_mode", "v1_fallback_enabled",
    "CONTROLLED_ERROR_REPLY", "CONTROLLED_ERROR_RESULT",
    "BrainV2Result",
    "run_v2_authoritative",
    "run_v2_shadow",
]
