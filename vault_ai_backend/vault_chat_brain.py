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
from typing import Any, Optional

import vault_chat_semantic_decider as _decider_mod
from vault_chat_decision_router import RouterResult, dispatch
from vault_chat_policy import authorize, _log_policy
from vault_chat_semantic_decider import Decision
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
        return FALLTHROUGH
    _log_policy(snapshot, decision, policy_result)

    if not policy_result.approved:
        _log_brain_outcome(
            snapshot, decision, handled=False,
            elapsed=time.time() - started,
            note=f"policy_reject:{policy_result.reason}",
        )
        return BrainResult(
            handled=False,
            fallthrough_reason=f"policy:{policy_result.reason}",
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
        return FALLTHROUGH

    if not router_result.handled:
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
