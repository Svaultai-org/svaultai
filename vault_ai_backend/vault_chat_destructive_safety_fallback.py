"""Deterministic safety fallback for destructive-action confirmations.

Design constraint (2026-07-24 chat-brain rebuild, adjustment 1):

    The semantic planner is the primary way of understanding user
    intent. HOWEVER, when the planner is unavailable, times out,
    or returns invalid output AND there is a live pending
    destructive action (delete), the user must still be able to
    respond with the most obvious confirmations. This module
    provides that minimal deterministic layer. It is NOT the main
    intelligence mechanism — it is a safety fallback that
    intentionally covers only a small, unambiguous set of
    phrasings so it cannot be gamed into destructive action on
    ambiguous input.

The classifier accepts three verdicts:

    * SAFETY_CONFIRM   — bare "yes"-family word, unambiguous
    * SAFETY_CANCEL    — bare "no" / "cancel" family word
    * SAFETY_UNCLEAR   — anything else

The regexes are deliberately narrow:

    * Message must be ≤ 30 characters after strip.
    * Only bare tokens plus optional light punctuation and one
      trailing "please" / "now" / "delete" / "cancel" word are
      allowed.
    * No compound phrasings like "yeah go ahead" — those are the
      model's job. When the model is down, we prefer to ask the
      user to repeat rather than infer.

If the classifier returns SAFETY_UNCLEAR, the caller must NOT
fall through to legacy routing for a destructive turn — see
adjustment 3 in the chat-brain rebuild. The caller should ask
the user to repeat instead.
"""

from __future__ import annotations

import re
from typing import Optional


SAFETY_CONFIRM: str = "safety_confirm"
SAFETY_CANCEL:  str = "safety_cancel"
SAFETY_UNCLEAR: str = "safety_unclear"


_MAX_LEN: int = 30


# Narrow list of bare confirmation tokens the safety layer will
# accept when the model is unavailable. Order matters only for
# readability — the alternation tries each until one matches.
_CONFIRM_RE: re.Pattern[str] = re.compile(
    r"""
    ^\s*
    (?:
        yes | yeah | yep | yup | y | yea | ya
      | ok | okay
      | confirm(?:ed)?
    )
    [\s.!,]*
    (?:please|now|delete|delete\s*it|delete\s*that)?
    [\s.!,]*
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


_CANCEL_RE: re.Pattern[str] = re.compile(
    r"""
    ^\s*
    (?:
        no | nope | nah | n
      | cancel | stop
      | don'?t | do\s*not
    )
    [\s.!,]*
    (?:please|now|thanks|it|that|delete|delete\s*it|delete\s*that)?
    [\s.!,]*
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)


def classify_destructive_message(user_message: Optional[str]) -> str:
    """Return one of ``SAFETY_CONFIRM`` / ``SAFETY_CANCEL`` /
    ``SAFETY_UNCLEAR`` for the user's reply. Called ONLY when a
    live destructive pending action exists and the semantic
    planner did not confidently handle the turn."""
    if not isinstance(user_message, str):
        return SAFETY_UNCLEAR
    stripped = user_message.strip()
    if not stripped:
        return SAFETY_UNCLEAR
    if len(stripped) > _MAX_LEN:
        return SAFETY_UNCLEAR
    if _CONFIRM_RE.match(stripped):
        return SAFETY_CONFIRM
    if _CANCEL_RE.match(stripped):
        return SAFETY_CANCEL
    return SAFETY_UNCLEAR


def build_clarification_prompt(target_label: str) -> str:
    """Short, direct prompt asking the user to repeat when the
    safety fallback cannot classify their reply. Never asserts
    what will happen — only asks the yes/no question."""
    label = (target_label or "").strip() or "that saved item"
    return (
        "Sorry — I didn't catch that. Do you want me to delete "
        f"{label}? Please reply with just \"yes\" or \"no\"."
    )


__all__ = [
    "SAFETY_CONFIRM",
    "SAFETY_CANCEL",
    "SAFETY_UNCLEAR",
    "classify_destructive_message",
    "build_clarification_prompt",
]
