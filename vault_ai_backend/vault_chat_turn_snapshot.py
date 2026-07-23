"""Structured, model-safe snapshot of the current chat turn.

Consumed by ``vault_chat_semantic_decider`` to build its prompt.
Never mutates state. Never persists anything. Just gathers
already-authorized inputs into one immutable record.

Design principles:

  * Everything in the snapshot is either a stable id / short label
    / count, or plain text the user just typed. NEVER decrypted
    vault plaintext. NEVER a password, PIN, seed phrase, private
    key, or token.
  * The snapshot is composable — the decider prompt renderer
    reads exactly the fields listed here; adding a new field is
    a two-line change.
  * A turn snapshot is scoped to (vault_id, session_id, turn_id).
    Two concurrent requests with different session_ids build
    independent snapshots; the pending-action arbiter enforces
    that too.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from vault_chat_pending_action import (
    NONE_PENDING, PendingAction, read_active_pending,
)

logger = logging.getLogger(__name__)


# Phase II: larger recent-turn window so the model sees enough
# history to answer "what did I just ask you" and to resolve
# short-range references like "that one" against actual prior
# text.
MAX_HISTORY_TURNS: int = 12
MAX_MESSAGE_CHARS: int = 2000
# Maximum candidates from the active entity that we surface in
# the snapshot so the model can resolve "the second one".
MAX_ACTIVE_ENTITY_CANDIDATES: int = 10


@dataclass(frozen=True)
class HistoryTurn:
    role:   str
    text:   str
    ts:     float


@dataclass(frozen=True)
class ActiveEntitySafeView:
    entity_type:     str
    display_label:   str
    is_multi:        bool
    allowed_actions: tuple = ()
    # Phase II: safe references (ids / display labels) of the
    # candidates the last search or list rendered. Used by the
    # decider to resolve "the second one" / "that other login"
    # against real, grounded options rather than guessing.
    candidates:      tuple = ()
    query:           str   = ""


@dataclass(frozen=True)
class TurnSnapshot:
    vault_id:            str
    session_id:          Optional[str]
    turn_id:             str
    vault_name:          str
    reply_language:      str
    user_message:        str
    now:                 float

    pending_action:      PendingAction
    active_entity:       Optional[ActiveEntitySafeView]
    recent_turns:        tuple[HistoryTurn, ...]
    tool_names:          tuple[str, ...]
    unlocked:            bool = True
    user_tier:           str = "free"
    features:            dict = field(default_factory=dict)
    # Phase II: short rolling digest of the conversation so far
    # (empty when the conversation is short or the digest module
    # is unavailable). Never contains vault plaintext or secrets.
    conversation_digest: str  = ""

    def has_pending(self) -> bool:
        return self.pending_action.kind != NONE_PENDING.kind

    def to_prompt_dict(self) -> dict:
        return {
            "vault_name":     self.vault_name,
            "reply_language": self.reply_language,
            "user_message":   self.user_message,
            "unlocked":       bool(self.unlocked),
            "user_tier":      self.user_tier,
            "features":       dict(self.features or {}),
            "pending_action": (
                self.pending_action.to_prompt_dict()
                if self.has_pending() else None
            ),
            "active_entity": (
                {
                    "entity_type":     self.active_entity.entity_type,
                    "display_label":   self.active_entity.display_label,
                    "is_multi":        self.active_entity.is_multi,
                    "allowed_actions": list(
                        self.active_entity.allowed_actions
                    ),
                    "candidates":      [
                        dict(c) for c in self.active_entity.candidates
                    ],
                    "query":           self.active_entity.query,
                }
                if self.active_entity is not None else None
            ),
            "conversation_digest": (
                self.conversation_digest or None
            ),
            "recent_turns": [
                {
                    "role":       t.role,
                    "text":       t.text,
                    "age_seconds": max(0, int(self.now - t.ts)),
                }
                for t in self.recent_turns
            ],
        }


def _safe_message(text: Optional[str]) -> str:
    if not isinstance(text, str):
        return ""
    stripped = text.strip()
    if len(stripped) > MAX_MESSAGE_CHARS:
        stripped = stripped[:MAX_MESSAGE_CHARS]
    return stripped


def _recent_turns_from_memory(memory: Any, now: float) -> tuple[HistoryTurn, ...]:
    """Extract a small window of recent conversation from chat
    memory. VaultAI's chat memory doesn't hold a canonical
    per-turn log (it holds pending drafts + last-service + last
    file search); a lightweight rolling log lives under the
    ``recent_turns`` key which we own here. Best-effort — an
    absent or corrupt log yields an empty tuple, never raises.
    """
    if memory is None:
        return ()
    try:
        rt = memory.get("recent_turns")
    except Exception:
        return ()
    if not isinstance(rt, list):
        return ()
    out: list[HistoryTurn] = []
    for entry in rt[-MAX_HISTORY_TURNS:]:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "").strip()
        text = str(entry.get("text") or "").strip()
        ts = float(entry.get("ts") or 0.0)
        if role not in ("user", "assistant") or not text:
            continue
        if ts <= 0.0:
            ts = now
        # Cap per-turn text length for the prompt — the snapshot is
        # supposed to summarize, not replay full transcripts.
        if len(text) > MAX_MESSAGE_CHARS:
            text = text[:MAX_MESSAGE_CHARS]
        out.append(HistoryTurn(role=role, text=text, ts=ts))
    return tuple(out)


def append_recent_turn(memory: Any, *, role: str, text: str) -> None:
    """Called by the router after each turn to keep the rolling
    log fresh. Preserves the SavedDict semantics — every write
    flushes to the shared backend."""
    if memory is None:
        return
    if role not in ("user", "assistant") or not isinstance(text, str):
        return
    stripped = text.strip()
    if not stripped:
        return
    try:
        existing = memory.get("recent_turns")
        if not isinstance(existing, list):
            existing = []
    except Exception:
        existing = []
    existing = list(existing)
    existing.append({
        "role": role,
        "text": stripped[:MAX_MESSAGE_CHARS],
        "ts":   time.time(),
    })
    if len(existing) > MAX_HISTORY_TURNS * 2:
        existing = existing[-MAX_HISTORY_TURNS * 2:]
    try:
        memory["recent_turns"] = existing
    except Exception:
        logger.exception("[SNAPSHOT] append_recent_turn_write_failed")


def _active_entity_view(
    vault_id: str, session_id: Optional[str],
) -> Optional[ActiveEntitySafeView]:
    try:
        from vault_chat_active_entity import get_active_entity
    except Exception:
        return None
    try:
        record = get_active_entity(vault_id, session_id=session_id)
    except Exception:
        logger.exception("[SNAPSHOT] active_entity_read_failed")
        return None
    if not isinstance(record, dict):
        return None
    raw_candidates = record.get("candidates") or []
    if not isinstance(raw_candidates, list):
        raw_candidates = []
    safe_candidates: list[dict] = []
    for c in raw_candidates[:MAX_ACTIVE_ENTITY_CANDIDATES]:
        if isinstance(c, dict):
            # Copy only the always-safe keys the active-entity
            # store already validated (allowed-ref-key set). No
            # plaintext, no encrypted-column values, no tokens.
            safe = {
                k: v for k, v in c.items()
                if isinstance(k, str) and isinstance(
                    v, (str, int, float, bool),
                )
            }
            if safe:
                safe_candidates.append(safe)
    return ActiveEntitySafeView(
        entity_type=str(record.get("entity_type") or ""),
        display_label=str(record.get("display_label") or ""),
        is_multi=bool(record.get("is_multi") or False),
        allowed_actions=tuple(record.get("allowed_actions") or ()),
        candidates=tuple(safe_candidates),
        query=str(record.get("query") or "")[:80],
    )


def build_turn_snapshot(
    *,
    vault_id: str,
    session_id: Optional[str],
    turn_id: str,
    vault_name: str,
    reply_language: str,
    user_message: str,
    memory: Any = None,
    unlocked: bool = True,
    user_tier: str = "free",
    features: Optional[dict] = None,
    now: Optional[float] = None,
) -> TurnSnapshot:
    """Assemble a snapshot for the current turn.

    NEVER raises. Missing sub-inputs (no memory, no active
    entity, etc.) yield the appropriate empty defaults.
    """
    from vault_chat_tool_registry import tool_names

    when = float(now) if now is not None else time.time()
    pending = read_active_pending(
        vault_id=vault_id, session_id=session_id, memory=memory, now=when,
    )
    entity = _active_entity_view(vault_id, session_id)
    recent = _recent_turns_from_memory(memory, when)
    digest = _build_digest(recent, pending, entity)

    return TurnSnapshot(
        vault_id=str(vault_id or ""),
        session_id=(session_id or None),
        turn_id=str(turn_id or ""),
        vault_name=str(vault_name or ""),
        reply_language=str(reply_language or "en"),
        user_message=_safe_message(user_message),
        now=when,
        pending_action=pending,
        active_entity=entity,
        recent_turns=recent,
        tool_names=tuple(tool_names()),
        unlocked=bool(unlocked),
        user_tier=str(user_tier or "free"),
        features=dict(features or {}),
        conversation_digest=digest,
    )


def _build_digest(
    recent: tuple,
    pending: Any,
    entity: Optional[ActiveEntitySafeView],
) -> str:
    try:
        from vault_chat_conversation_digest import build_digest
    except Exception:
        return ""
    try:
        return build_digest(
            recent_user_turns=[
                t.text for t in recent if t.role == "user"
            ],
            recent_assistant_turns=[
                t.text for t in recent if t.role == "assistant"
            ],
            pending_kind=(
                pending.kind if pending and pending.kind != "none"
                else None
            ),
            pending_target_label=(
                pending.target_label if pending
                and pending.kind != "none" else None
            ),
            active_entity_label=(
                entity.display_label if entity else None
            ),
            active_entity_is_multi=(
                entity.is_multi if entity else False
            ),
        )
    except Exception:
        logger.exception("[SNAPSHOT] digest_failed")
        return ""


__all__ = [
    "HistoryTurn",
    "ActiveEntitySafeView",
    "TurnSnapshot",
    "MAX_HISTORY_TURNS",
    "MAX_MESSAGE_CHARS",
    "build_turn_snapshot",
    "append_recent_turn",
]
