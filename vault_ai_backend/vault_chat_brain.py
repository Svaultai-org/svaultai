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
    build_clarification_prompt,
    classify_destructive_message,
)
from vault_chat_policy import authorize, _log_policy
from vault_chat_semantic_decider import (
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
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
    """Dispatch on ``VAULTAI_CHAT_BRAIN_MODE``:

        * ``off``    (default): legacy v1 brain runs; behavior
                                identical to pre-commit-5.
        * ``shadow`` : legacy v1 brain is authoritative; v2 runs
                       read-only alongside and emits a diff record.
                       Any v2 exception is caught + logged;
                       user-facing result is unaffected.
        * ``on``     : v2 is authoritative. Legacy v1 brain does
                       NOT run. On uncaught v2 exception the
                       behavior follows the design memo rev 8
                       failure invariant (V1_FALLBACK env override
                       vs controlled error). No mixed v1/v2
                       execution within one request.

    Returns ``BrainResult`` in every mode. Never raises.
    """
    if not vault_id or not isinstance(user_message, str):
        return FALLTHROUGH

    # Feature-flag dispatch — read once, fail closed to "off".
    try:
        from vault_chat_brain_v2 import (
            MODE_OFF, MODE_SHADOW, MODE_ON,
            read_brain_mode,
        )
        mode = read_brain_mode()
    except Exception:
        logger.exception("[BRAIN] mode_read_failed")
        return await _run_legacy_brain(
            vault_id=vault_id, session_id=session_id, turn_id=turn_id,
            vault_name=vault_name, reply_language=reply_language,
            user_message=user_message, memory=memory, key=key,
            unlocked=unlocked, user_tier=user_tier, features=features,
        )

    if mode == MODE_OFF:
        return await _run_legacy_brain(
            vault_id=vault_id, session_id=session_id, turn_id=turn_id,
            vault_name=vault_name, reply_language=reply_language,
            user_message=user_message, memory=memory, key=key,
            unlocked=unlocked, user_tier=user_tier, features=features,
        )

    if mode == MODE_SHADOW:
        # v1 authoritative; v2 observes read-only.
        legacy_result = await _run_legacy_brain(
            vault_id=vault_id, session_id=session_id, turn_id=turn_id,
            vault_name=vault_name, reply_language=reply_language,
            user_message=user_message, memory=memory, key=key,
            unlocked=unlocked, user_tier=user_tier, features=features,
        )
        try:
            from vault_chat_brain_v2 import run_v2_shadow
            await run_v2_shadow(
                vault_id=vault_id, session_id=session_id,
                turn_id=turn_id, user_message=user_message,
                memory=memory,
                v1_tool=legacy_result.tool,
                v1_handled=legacy_result.handled,
            )
        except Exception:
            logger.exception("[BRAIN] shadow_v2_wrapper_failed")
        return legacy_result

    if mode == MODE_ON:
        # Readiness guard: mode==on requires a complete executor
        # registry. If any action_kind is unmapped we refuse to
        # enter on mode (which would produce INTERNAL_ERROR for
        # ordinary saves/deletes) and return a controlled
        # unavailable response instead. The brain does NOT fall
        # through to v1 here -- an operator turning on the flag
        # against an unwired build must see this as a real
        # deployment error, not a silent v1 handling.
        try:
            from vault_chat_brain_v2 import (
                CONTROLLED_ERROR_RESULT,
                CONTROLLED_UNAVAILABLE_RESULT,
                run_v2_authoritative,
            )
            from vault_chat_integration_v2 import (
                validate_v2_runtime_readiness,
            )
            registry = _default_v2_executor_registry()
            ready, missing = validate_v2_runtime_readiness(registry)
            if not ready:
                logger.error(
                    "[BRAIN] on_mode_refused executors_missing=%s",
                    ",".join(missing),
                )
                return BrainResult(
                    handled=CONTROLLED_UNAVAILABLE_RESULT.handled,
                    reply_text=CONTROLLED_UNAVAILABLE_RESULT.reply_text,
                    tool=CONTROLLED_UNAVAILABLE_RESULT.tool,
                    fallthrough_reason=(
                        CONTROLLED_UNAVAILABLE_RESULT.fallthrough_reason
                    ),
                )
            v2_result = await run_v2_authoritative(
                vault_id=vault_id, session_id=session_id,
                turn_id=turn_id, user_message=user_message,
                key=key, memory=memory,
                executor_registry=registry,
                assistant_turn_id=turn_id,
            )
        except Exception:
            # Any exception escaping run_v2_authoritative is a bug
            # (that function catches everything internally). Treat
            # like a READ_ONLY-phase failure so V1_FALLBACK env
            # (if set) still applies -- the ambiguity resolves in
            # favor of "state may already have mutated". Since
            # run_v2_authoritative's own catch has phase context
            # and this branch does not, we conservatively refuse
            # fallback here regardless of env.
            logger.exception("[BRAIN] on_v2_top_level_crashed")
            v2_result = CONTROLLED_ERROR_RESULT
        return BrainResult(
            handled=v2_result.handled,
            reply_text=v2_result.reply_text,
            tool=v2_result.tool,
            fallthrough_reason=v2_result.fallthrough_reason,
        )

    # Defensive — should be unreachable after read_brain_mode
    # normalization.
    logger.warning("[BRAIN] unexpected mode %r; falling back to off", mode)
    return await _run_legacy_brain(
        vault_id=vault_id, session_id=session_id, turn_id=turn_id,
        vault_name=vault_name, reply_language=reply_language,
        user_message=user_message, memory=memory, key=key,
        unlocked=unlocked, user_tier=user_tier, features=features,
    )


def _default_v2_executor_registry():
    """Phase-1 empty registry — no action_kind is wired to a real
    executor. This is deliberate: mode==on will produce
    ``INTERNAL_ERROR`` for any confirm/cancel/edit/create until a
    later commit wires the real executors. The framework is in
    place for that commit; no user is exposed to it because the
    flag is off in production.

    Tests inject their own registries to exercise the SUCCESS /
    EXECUTOR_FAILED / AUTHORIZATION_FAILED / CONSUME_FAILED
    branches.
    """
    from vault_chat_integration_v2 import ExecutorRegistry
    return ExecutorRegistry()


async def _run_legacy_brain(
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
    """The v1 brain body, unchanged. Called when
    ``VAULTAI_CHAT_BRAIN_MODE == "off"`` or ``"shadow"``. Kept
    byte-identical to the pre-commit-5 body so the legacy
    regression suite remains green."""

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
            and decision.confidence in (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM)):
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
