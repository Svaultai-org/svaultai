"""Top-level entry point for the VaultAI chat brain.

Called by ``main.chat_endpoint`` as a single new band inserted
between chat-memory load and the existing pending-confirm
cascade. Wires together:

    * ``vault_chat_turn_snapshot.build_turn_snapshot``
    * ``vault_chat_semantic_decider.decide``
    * ``vault_chat_policy.authorize``
    * ``vault_chat_decision_router.dispatch``

Returns a ``BrainResult`` — either "handled" (the caller should
encrypt-and-reply with ``reply_text``) or "fallthrough" (the
caller should continue to the existing cascade unchanged).

NEVER raises. NEVER logs plaintext credentials, keys, PINs, or
decrypted vault content.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional  # noqa: F401 — Optional used by _apply_destructive_failsafe

import vault_chat_semantic_decider as _decider_mod
from vault_chat_decision_router import RouterResult, dispatch
from vault_chat_destructive_safety_fallback import (
    SAFETY_CANCEL,
    SAFETY_CONFIRM,
    SAFETY_UNCLEAR,
    build_clarification_prompt,
    classify_destructive_message,
)
from vault_chat_policy import authorize, _log_policy
from vault_chat_semantic_decider import (
    CONFIDENCE_HIGH,
    Decision,
)
from vault_chat_tool_registry import (
    TOOL_CANCEL_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_DELETE,
)
from vault_chat_turn_snapshot import (
    TurnSnapshot, append_recent_turn, build_turn_snapshot,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrainResult:
    handled:     bool
    reply_text:  str = ""
    tool:        str = ""
    fallthrough_reason: str = ""


FALLTHROUGH: BrainResult = BrainResult(handled=False)


async def run_chat_brain(
    *,
    vault_id: str,
    session_id: Optional[str],
    turn_id: str,
    vault_name: str,
    reply_language: str,
    user_message: str,
    memory: Any = None,
    key: bytes = b"",
    unlocked: bool = True,
    user_tier: str = "free",
    features: Optional[dict] = None,
) -> BrainResult:
    """Run the brain. Returns fallthrough if anything goes wrong or
    if the decider chose to yield to the existing pipeline."""
    if not vault_id or not isinstance(user_message, str):
        return FALLTHROUGH

    started = time.time()

    # 1) build the snapshot
    try:
        snapshot: TurnSnapshot = build_turn_snapshot(
            vault_id=vault_id,
            session_id=session_id,
            turn_id=turn_id,
            vault_name=vault_name,
            reply_language=reply_language,
            user_message=user_message,
            memory=memory,
            unlocked=unlocked,
            user_tier=user_tier,
            features=features,
        )
    except Exception:
        logger.exception("[BRAIN] snapshot_failed")
        return FALLTHROUGH

    # 2) decider
    try:
        decision: Decision = await _decider_mod.decide(snapshot)
    except Exception:
        logger.exception("[BRAIN] decide_crashed")
        return FALLTHROUGH

    if decision.is_fallthrough():
        safe = _apply_destructive_failsafe(
            snapshot, key=key, memory=memory, decision=decision,
        )
        if safe is not None:
            _log_brain_outcome(
                snapshot, decision, handled=True,
                elapsed=time.time() - started,
                note=(
                    "destructive_failsafe_after_decider:"
                    f"{safe.tool or 'clarify'}"
                ),
            )
            return BrainResult(
                handled=True,
                reply_text=safe.reply_text,
                tool=safe.tool,
            )
        _log_brain_outcome(
            snapshot, decision, handled=False,
            elapsed=time.time() - started,
            note="decider_fallthrough",
        )
        return BrainResult(
            handled=False,
            fallthrough_reason=decision.error or "decider_fallthrough",
        )

    # 3) policy
    try:
        policy_result = authorize(snapshot=snapshot, decision=decision)
    except Exception:
        logger.exception("[BRAIN] policy_crashed")
        policy_result = None
    if policy_result is not None:
        _log_policy(snapshot, decision, policy_result)

    if policy_result is None or not policy_result.approved:
        safe = _apply_destructive_failsafe(
            snapshot, key=key, memory=memory, decision=decision,
        )
        if safe is not None:
            _log_brain_outcome(
                snapshot, decision, handled=True,
                elapsed=time.time() - started,
                note=(
                    "destructive_failsafe_after_policy:"
                    f"{safe.tool or 'clarify'}"
                ),
            )
            return BrainResult(
                handled=True,
                reply_text=safe.reply_text,
                tool=safe.tool,
            )
        _reason = (
            "policy_crashed" if policy_result is None
            else f"policy:{policy_result.reason}"
        )
        _log_brain_outcome(
            snapshot, decision, handled=False,
            elapsed=time.time() - started,
            note=(
                "policy_crashed" if policy_result is None
                else f"policy_reject:{policy_result.reason}"
            ),
        )
        return BrainResult(
            handled=False,
            fallthrough_reason=_reason,
        )

    # 4) dispatch
    try:
        router_result: RouterResult = dispatch(
            snapshot=snapshot,
            decision=decision,
            key=key,
            memory=memory,
        )
    except Exception:
        logger.exception("[BRAIN] dispatch_crashed")
        router_result = RouterResult.fallthrough()

    if not router_result.handled:
        # Router did not handle. Before we allow the request to
        # fall through to the existing pipeline, apply the
        # destructive fail-safe: legacy routing must NEVER
        # execute a destructive action on the strength of a
        # planner failure.
        safe = _apply_destructive_failsafe(
            snapshot, key=key, memory=memory, decision=decision,
        )
        if safe is not None:
            _log_brain_outcome(
                snapshot, decision, handled=True,
                elapsed=time.time() - started,
                note=f"destructive_failsafe:{safe.tool or 'clarify'}",
            )
            return BrainResult(
                handled=True,
                reply_text=safe.reply_text,
                tool=safe.tool,
            )
        _log_brain_outcome(
            snapshot, decision, handled=False,
            elapsed=time.time() - started,
            note="router_fallthrough",
        )
        return BrainResult(
            handled=False,
            fallthrough_reason="router_fallthrough",
        )

    # 5) success — write the turn back into recent_turns so the
    # next turn has conversational context.
    try:
        append_recent_turn(memory, role="user", text=user_message)
        append_recent_turn(
            memory, role="assistant", text=router_result.reply_text,
        )
    except Exception:
        # non-fatal — the reply still stands
        logger.warning(
            "[BRAIN] recent_turn_append_failed",
        )

    _log_brain_outcome(
        snapshot, decision, handled=True,
        elapsed=time.time() - started,
        note=f"handled:{router_result.tool}",
    )
    return BrainResult(
        handled=True,
        reply_text=router_result.reply_text,
        tool=router_result.tool,
    )


def _apply_destructive_failsafe(
    snapshot: TurnSnapshot,
    *,
    key: bytes,
    memory: Any,
    decision: Optional[Decision] = None,
) -> Optional[RouterResult]:
    """Fail-safe for turns where a destructive action is pending
    and the semantic path did NOT confidently handle the turn.

    Returns:
        * ``RouterResult(handled=True, ...)`` — deterministic
          confirm/cancel dispatched OR a short clarification
          asked. In either case the caller must treat the turn
          as handled and NOT fall through to the legacy pipeline.
        * ``None`` — either no destructive pending, OR the model
          DELIBERATELY chose fallthrough (empty ``error``, i.e.
          the decider did not fail — it just yielded to the
          existing pipeline as a semantic judgment). Callers
          may then fall through to the existing pipeline as
          usual. This preserves the Phase II ability of the
          model to route a topic-switch reply (``"delete my
          chase login"`` while an Instagram delete was pending)
          into the existing pipeline that can stamp the new
          delete correctly, WITHOUT giving up the safety
          guarantees when the model actually fails.

    Note: even when the model deliberately chose fallthrough,
    the safety classifier is still tried first — a bare
    ``"yes"`` / ``"no"`` / ``"cancel"`` reply is ALWAYS handled
    by the failsafe regardless of what the model returned. That
    is the exact regression the deterministic safety fallback
    exists to prevent: a mis-behaving planner cannot let a bare
    confirmation slip through to legacy routing.
    """
    pending = snapshot.pending_action
    if not pending.is_destructive:
        return None
    verdict = classify_destructive_message(snapshot.user_message)
    if verdict == SAFETY_CONFIRM:
        synthetic = Decision(
            tool=TOOL_CONFIRM_PENDING_DELETE,
            args={"action_id": pending.action_id},
            confidence=CONFIDENCE_HIGH,
            why="deterministic safety fallback",
            error="",
        )
        try:
            result = dispatch(
                snapshot=snapshot, decision=synthetic,
                key=key, memory=memory,
            )
        except Exception:
            logger.exception("[BRAIN] failsafe_confirm_dispatch_crashed")
            return RouterResult(
                handled=True,
                reply_text=(
                    "I couldn't delete that right now. Try again "
                    "in a moment."
                ),
                tool=TOOL_CONFIRM_PENDING_DELETE,
                metadata={"error": "failsafe_dispatch_crashed"},
            )
        if not result.handled:
            return RouterResult(
                handled=True,
                reply_text=(
                    "I couldn't delete that right now. Try again "
                    "in a moment."
                ),
                tool=TOOL_CONFIRM_PENDING_DELETE,
                metadata={"error": "failsafe_dispatch_no_op"},
            )
        return result
    if verdict == SAFETY_CANCEL:
        synthetic = Decision(
            tool=TOOL_CANCEL_PENDING_DELETE,
            args={"action_id": pending.action_id},
            confidence=CONFIDENCE_HIGH,
            why="deterministic safety fallback",
            error="",
        )
        try:
            result = dispatch(
                snapshot=snapshot, decision=synthetic,
                key=key, memory=memory,
            )
        except Exception:
            logger.exception("[BRAIN] failsafe_cancel_dispatch_crashed")
            return RouterResult(
                handled=True,
                reply_text="Okay — I won't delete it.",
                tool=TOOL_CANCEL_PENDING_DELETE,
            )
        if not result.handled:
            return RouterResult(
                handled=True,
                reply_text="Okay — I won't delete it.",
                tool=TOOL_CANCEL_PENDING_DELETE,
            )
        return result
    # SAFETY_UNCLEAR path. We need one more discrimination
    # before asking the user to repeat: was this fallthrough
    # DELIBERATE (the model semantically decided "not my job")
    # or FAILURE-DRIVEN (timeout, malformed JSON, unknown tool,
    # schema mismatch)?
    #
    #   * Failure-driven → keep destructive-safety posture; ask
    #     the user to repeat (never let legacy handle a
    #     destructive turn on a planner failure — adjustment 3).
    #   * Deliberate      → the model was confident this is a
    #     topic switch or non-destructive-relevant request.
    #     Return None so the caller falls through to the
    #     existing pipeline, which can process the new request
    #     correctly (e.g. stamp a delete for a DIFFERENT target).
    #     Safety is preserved because the bare yes/no/cancel
    #     branches above already handled the confirmation
    #     hijack risk.
    from vault_chat_tool_registry import TOOL_FALLTHROUGH as _TF
    if (decision is not None
            and decision.tool == _TF
            and not decision.error
            and decision.confidence in (CONFIDENCE_HIGH, "medium")):
        # Deliberate fallthrough. The model explicitly said
        # "this is a topic switch — pipeline should handle it".
        # Let the pipeline handle it; the safety hijack risk is
        # already closed above (bare yes/no/cancel branches).
        return None
    return RouterResult(
        handled=True,
        reply_text=build_clarification_prompt(pending.target_label),
        tool="",
        metadata={"failsafe": "clarify"},
    )


def _log_brain_outcome(
    snapshot: TurnSnapshot,
    decision: Decision,
    *,
    handled: bool,
    elapsed: float,
    note: str,
) -> None:
    """Structured log — never logs user text, args, model
    reasoning, or vault plaintext."""
    logger.info(
        "[BRAIN] outcome vault=%s session=%s pending=%s "
        "tool=%s conf=%s handled=%s elapsed_ms=%d note=%s",
        (snapshot.vault_id or "")[:8] + "…",
        (snapshot.session_id or "-")[:8] + "…" if snapshot.session_id
        else "-",
        snapshot.pending_action.kind,
        decision.tool,
        decision.confidence,
        bool(handled),
        int(elapsed * 1000),
        note,
    )


__all__ = [
    "BrainResult",
    "FALLTHROUGH",
    "run_chat_brain",
]
