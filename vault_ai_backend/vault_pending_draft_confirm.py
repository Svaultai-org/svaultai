

from __future__ import annotations

import re
from typing import Optional


# -------------------------------------------------------------------
# 2026-07-24 chat-brain rebuild — narrowed confirm regex.
#
# Prior to this change, ``_CONFIRM_PATTERNS`` included bare "yes",
# "ok save", "confirm", and so on — a growing list of exact
# phrasings. The regex-based cascade would run BEFORE the secure-
# item delete-confirmation check, and any orphan
# ``uploaded_files.needs_naming = TRUE`` row could hijack a bare
# "yes" reply from a user who was actually confirming a delete.
# See the 2026-07-24 root-cause report.
#
# Semantic confirmation understanding now lives in the chat brain
# (``vault_chat_semantic_decider`` + ``vault_chat_policy``). The
# regex list here has been reduced to phrasings that are so
# explicit about "save" that they cannot be misread as
# confirmations of a pending delete. Bare "yes", "yeah", "ok",
# "sure", "do it", "confirm" — all removed. Every one of these
# still works semantically through the brain; they just no
# longer short-circuit the cascade at the regex layer.
#
# This regex list continues to exist as a defense-in-depth
# fallback the chat handler consults ONLY when the semantic
# brain falls through AND a pending save action exists AND no
# destructive action is pending. That combination is enforced by
# the caller in ``main.py``.
_CONFIRM_PATTERNS: tuple[str, ...] = (
    r"^\s*save\s+it(?:\s+now)?\s*[.!?]*\s*$",
    r"^\s*save\s+this\s*[.!?]*\s*$",
    r"^\s*save\s+that(?:\s+now)?\s*[.!?]*\s*$",
    r"^\s*save\s+now\s*[.!?]*\s*$",
    r"^\s*save\s*[.!?]*\s*$",
    r"^\s*please[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*yes[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*(?:yea|yeah|yep|yup)\s*[.!?]*\s*$",
    r"^\s*(?:yea|yeah|yep|yup)[\s,.!]+save(?:\s+(?:it|this|that|now))?"
    r"\s*[.!?]*\s*$",
    r"^\s*confirm\s+save\s*[.!?]*\s*$",
    r"^\s*go\s+ahead\s+and\s+save(?:\s+(?:it|this|that))?\s*[.!?]*\s*$",
    r"^\s*store\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*keep\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*add\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*ok(?:ay)?[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*sure[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    # "put this in my vault" / "add to vault" / "store in vault"
    # variants that name "vault" explicitly and cannot be mistaken
    # for delete confirmation.
    r"^\s*put\s+(?:it|this|that)\s+in(?:to)?\s+"
    r"(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*(?:add|drop|toss|throw)\s+(?:it|this|that)\s+"
    r"(?:in(?:to)?|to)\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*save\s+(?:it|this|that)\s+"
    r"(?:in(?:to)?|to)\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*save\s+to\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*store\s+(?:it|this|that)\s+"
    r"(?:in(?:to)?|to)\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*keep\s+(?:it|this|that)\s+"
    r"(?:in(?:to)?|to)\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*remember\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*save\s+(?:it|this|that)[,\s]+please\s*[.!?]*\s*$",
    r"^\s*save\s+(?:it|this|that)\s+for\s+me\s*[.!?]*\s*$",
)


_COMPILED_CONFIRM: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _CONFIRM_PATTERNS
)


_SAVE_THEMED_PATTERNS: tuple[str, ...] = (
    r"^\s*save\s+it(?:\s+now)?\s*[.!?]*\s*$",
    r"^\s*save\s+this\s*[.!?]*\s*$",
    r"^\s*save\s+that(?:\s+now)?\s*[.!?]*\s*$",
    r"^\s*save\s+now\s*[.!?]*\s*$",
    r"^\s*save\s*[.!?]*\s*$",
    r"^\s*please[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*yes[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*(?:yea|yeah|yep|yup)[\s,.!]+save(?:\s+(?:it|this|that|now))?"
    r"\s*[.!?]*\s*$",
    r"^\s*confirm\s+save\s*[.!?]*\s*$",
    r"^\s*go\s+ahead\s+and\s+save(?:\s+(?:it|this|that))?\s*[.!?]*\s*$",
    r"^\s*store\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*keep\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*add\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*ok(?:ay)?[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    r"^\s*sure[\s,.!]+save(?:\s+(?:it|this|that|now))?\s*[.!?]*\s*$",
    # 2026-07-22 additions mirroring the CONFIRM list.
    r"^\s*put\s+(?:it|this|that)\s+in(?:to)?\s+"
    r"(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*(?:add|drop|toss|throw)\s+(?:it|this|that)\s+"
    r"(?:in(?:to)?|to)\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*save\s+(?:it|this|that)\s+"
    r"(?:in(?:to)?|to)\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*save\s+to\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*store\s+(?:it|this|that)\s+"
    r"(?:in(?:to)?|to)\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*keep\s+(?:it|this|that)\s+"
    r"(?:in(?:to)?|to)\s+(?:my\s+|the\s+)?vault\s*[.!?]*\s*$",
    r"^\s*remember\s+(?:it|this|that)\s*[.!?]*\s*$",
    r"^\s*save\s+(?:it|this|that)[,\s]+please\s*[.!?]*\s*$",
    r"^\s*save\s+(?:it|this|that)\s+for\s+me\s*[.!?]*\s*$",
)


_COMPILED_SAVE_THEMED: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _SAVE_THEMED_PATTERNS
)


_SERVICE_SCOPED_CONFIRM_RE = re.compile(
    r"^\s*(?:save|store|remember)\s+(?:my\s+|the\s+)?"
    r"(?P<service>.+?)\s+(?:login|credential|account)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


NO_DRAFT_FRIENDLY_REPLY: str = (
    "I don't have a pending save right now. Tell me what you'd "
    "like to save first."
)


def is_pending_draft_confirm_phrase(user_message: Optional[str]) -> bool:


    if not isinstance(user_message, str):
        return False
    msg = user_message.strip()
    if not msg:
        return False
    for pat in _COMPILED_CONFIRM:
        if pat.match(msg):
            return True
    return False


def is_save_themed_confirm_phrase(user_message: Optional[str]) -> bool:


    if not isinstance(user_message, str):
        return False
    msg = user_message.strip()
    if not msg:
        return False
    for pat in _COMPILED_SAVE_THEMED:
        if pat.match(msg):
            return True
    return False


def pending_draft_confirm_service(
    user_message: Optional[str],
) -> Optional[str]:
    """Return the named service for an unambiguous pending-draft save.

    The caller must still prove a live draft exists for this exact service.
    Keeping that check outside the text classifier prevents a stale draft for
    one service from being saved by a request naming another service.
    """
    if not isinstance(user_message, str):
        return None
    match = _SERVICE_SCOPED_CONFIRM_RE.fullmatch(user_message.strip())
    if match is None:
        return None
    service = str(match.group("service") or "").strip(" ,.;:!?")
    return service or None


__all__ = [
    "is_pending_draft_confirm_phrase",
    "is_save_themed_confirm_phrase",
    "pending_draft_confirm_service",
    "NO_DRAFT_FRIENDLY_REPLY",
]
