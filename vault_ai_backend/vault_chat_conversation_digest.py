"""Lightweight rolling digest of the recent chat conversation.

Surfaced in ``TurnSnapshot.conversation_digest`` so the semantic
decider has one compact signal about what has been happening,
even when the specific turn-by-turn text has aged out of the
short recent-turns window.

Design choices:

  * The digest is DETERMINISTIC and CHEAP — it is derived from
    the recent-turns list and current pending-action metadata,
    with no extra LLM call. That keeps chat latency and cost
    predictable, and prevents the digest from becoming a source
    of hallucination.

  * The digest text is a short bulleted headline (≤ 240 chars)
    the model can read at a glance:

        Recent activity: user asked for a Gmail login; assistant
        showed 2 matches; user is confirming a delete of the
        Gmail login now.

  * Vault plaintext is never included. Only structural facts
    — user vs assistant turn counts, whether a pending action
    exists and its kind + target label, whether the active
    entity is a multi-match.

  * Empty digest returns ``""`` — the snapshot renderer omits
    the key when the digest is empty.

This module has no state. It reads inputs and returns text.
"""

from __future__ import annotations

from typing import Iterable, Optional


MAX_DIGEST_CHARS: int = 240


def build_digest(
    *,
    recent_user_turns: Iterable[str],
    recent_assistant_turns: Iterable[str],
    pending_kind: Optional[str] = None,
    pending_target_label: Optional[str] = None,
    active_entity_label: Optional[str] = None,
    active_entity_is_multi: bool = False,
) -> str:
    """Return a short, safe headline of the conversation. Empty
    string when there is nothing meaningful to say."""
    u_turns = [t for t in (recent_user_turns or []) if isinstance(t, str) and t.strip()]
    a_turns = [t for t in (recent_assistant_turns or []) if isinstance(t, str) and t.strip()]

    if not (u_turns or a_turns or pending_kind or active_entity_label):
        return ""

    parts: list[str] = []
    if u_turns:
        first_user = u_turns[0].strip().replace("\n", " ")
        if len(first_user) > 90:
            first_user = first_user[:90] + "…"
        parts.append(f"user asked: {first_user}")
    if a_turns:
        latest_asst = a_turns[-1].strip().replace("\n", " ")
        if len(latest_asst) > 90:
            latest_asst = latest_asst[:90] + "…"
        parts.append(f"assistant last said: {latest_asst}")
    if active_entity_label:
        label = active_entity_label.strip()
        if active_entity_is_multi:
            parts.append(f"active context: {label} (multi-match)")
        else:
            parts.append(f"active context: {label}")
    if pending_kind and pending_target_label:
        parts.append(
            f"pending {pending_kind}: {pending_target_label}"
        )
    elif pending_kind:
        parts.append(f"pending {pending_kind}")

    text = "Recent activity: " + "; ".join(parts) + "."
    if len(text) > MAX_DIGEST_CHARS:
        text = text[:MAX_DIGEST_CHARS - 1] + "…"
    return text


__all__ = ["build_digest", "MAX_DIGEST_CHARS"]
