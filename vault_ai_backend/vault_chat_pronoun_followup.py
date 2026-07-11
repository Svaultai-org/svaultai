"""Detect bare pronoun / "same as last" follow-up phrases.

Replaces the login-only ``vault_chat_login_followup`` module. Given
a user message, decide whether it is a short, unambiguous pronoun
follow-up like "show me", "show it", "open it", "view it", "rename
it", "delete it", "copy it", "save it", "upgrade it" — i.e. a
reference to whatever VaultAI just resolved.

Return value is either None or a small dict:

    {"verb": "show" | "open" | "view" | "rename" | "delete" |
             "copy" | "save" | "upgrade"}

Rules:

  * Message must be short (≤ 40 chars) and single-line.
  * A question shape (`?`) is not a follow-up.
  * Sensitive-reveal hints (`password`, `pin`, `reveal`, `unmask`,
    `seed`, `mnemonic`, `private key`) return None so those go
    through the confirmation-required reveal flow at
    ``vault_chat_router._LOGIN_REVEAL_PATTERNS``.
  * "yes" / "sure" / "confirm" / "cancel" return None — they belong
    to the pending-draft confirm flow.
  * A message that names a NEW entity ("show me my Gmail login",
    "delete my Chase login") returns None — those are fresh
    searches, not pronoun follow-ups.

The chat handler dispatches on the returned verb + the current
active entity's `entity_type`. A verb that is not in the entity's
`allowed_actions` list is a no-op (the handler falls through).

This module is import-safe and has zero side effects.
"""

from __future__ import annotations

import re
from typing import Optional


_MAX_FOLLOWUP_CHARS: int = 40




_VERB_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (verb, re.compile(pattern, re.IGNORECASE)) for verb, pattern in (

        ("show", r"^\s*show\s+me\s*[.!?]*\s*$"),
        ("show", r"^\s*show\s+it\s*[.!?]*\s*$"),
        ("show", r"^\s*show\s+that\s*[.!?]*\s*$"),
        ("show", r"^\s*show\s+that\s+one\s*[.!?]*\s*$"),
        ("show", r"^\s*show\s+me\s+it\s*[.!?]*\s*$"),
        ("show", r"^\s*show\s+me\s+that\s*[.!?]*\s*$"),
        ("show", r"^\s*let\s+me\s+see\s+it\s*[.!?]*\s*$"),
        ("show", r"^\s*let\s+me\s+see\s+that\s*[.!?]*\s*$"),
        ("show", r"^\s*can\s+i\s+see\s+it\s*[.!?]*\s*$"),
        ("show", r"^\s*can\s+i\s+see\s+that\s*[.!?]*\s*$"),
        ("show", r"^\s*i\s+want\s+to\s+see\s+it\s*[.!?]*\s*$"),
        ("show", r"^\s*i\s+want\s+to\s+see\s+that\s*[.!?]*\s*$"),
        ("show", r"^\s*ok(?:ay)?[\s,]*show\s+(?:it|me|that)\s*[.!?]*\s*$"),
        ("show", r"^\s*yes[\s,]*show\s+(?:it|me|that)\s*[.!?]*\s*$"),
        ("show", r"^\s*sure[\s,]*show\s+(?:it|me|that)\s*[.!?]*\s*$"),


        ("open", r"^\s*open\s+it\s*[.!?]*\s*$"),
        ("open", r"^\s*open\s+that\s*[.!?]*\s*$"),
        ("open", r"^\s*open\s+that\s+one\s*[.!?]*\s*$"),
        ("open", r"^\s*open\s+the\s+vault\s*[.!?]*\s*$"),
        ("open", r"^\s*open\s+it\s+up\s*[.!?]*\s*$"),
        ("open", r"^\s*take\s+me\s+there\s*[.!?]*\s*$"),
        ("open", r"^\s*take\s+me\s+to\s+it\s*[.!?]*\s*$"),
        ("open", r"^\s*go\s+there\s*[.!?]*\s*$"),
        ("open", r"^\s*let['’]s\s+go\s*[.!?]*\s*$"),
        ("open", r"^\s*use\s+it\s*[.!?]*\s*$"),
        ("open", r"^\s*use\s+that\s*[.!?]*\s*$"),
        ("open", r"^\s*launch\s+it\s*[.!?]*\s*$"),


        ("view", r"^\s*view\s+it\s*[.!?]*\s*$"),
        ("view", r"^\s*view\s+that\s*[.!?]*\s*$"),


        ("rename", r"^\s*rename\s+it\s*[.!?]*\s*$"),
        ("rename", r"^\s*rename\s+that\s*[.!?]*\s*$"),


        ("delete", r"^\s*delete\s+it\s*[.!?]*\s*$"),
        ("delete", r"^\s*delete\s+that\s*[.!?]*\s*$"),
        ("delete", r"^\s*remove\s+it\s*[.!?]*\s*$"),


        ("copy", r"^\s*copy\s+it\s*[.!?]*\s*$"),
        ("copy", r"^\s*copy\s+that\s*[.!?]*\s*$"),


        ("save", r"^\s*save\s+it\s*[.!?]*\s*$"),
        ("save", r"^\s*save\s+that\s*[.!?]*\s*$"),
        ("save", r"^\s*save\s+that\s+one\s*[.!?]*\s*$"),


        ("upgrade", r"^\s*upgrade\s+it\s*[.!?]*\s*$"),
        ("upgrade", r"^\s*upgrade\s+that\s*[.!?]*\s*$"),
        ("upgrade", r"^\s*upgrade\s+now\s*[.!?]*\s*$"),
    )
)




_SENSITIVE_REVEAL_HINTS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bpassword\b",
        r"\bpasscode\b",
        r"\bpin(?:code)?\b",
        r"\bsecret\b",
        r"\breveal\b",
        r"\bunmask\b",
        r"\bseed\b",
        r"\bmnemonic\b",
        r"\bprivate\s+key\b",
        r"\bspend\s+key\b",
        r"\bview\s+key\b",
        r"\bapi\s+key\b",
        r"\bshow\s+.*password\b",
        r"\bshow\s+.*pin\b",
        r"\bshow\s+.*seed\b",
        r"\bgive\s+me\s+the\s+password\b",
    )
)




_STANDALONE_CONFIRMS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"^\s*yes\s*[.!?]*\s*$",
        r"^\s*yea(?:h)?\s*[.!?]*\s*$",
        r"^\s*yep\s*[.!?]*\s*$",
        r"^\s*yup\s*[.!?]*\s*$",
        r"^\s*ok(?:ay)?\s*[.!?]*\s*$",
        r"^\s*sure\s*[.!?]*\s*$",
        r"^\s*confirm\s*[.!?]*\s*$",
        r"^\s*cancel\s*[.!?]*\s*$",
        r"^\s*nevermind\s*[.!?]*\s*$",
        r"^\s*never\s+mind\s*[.!?]*\s*$",
        r"^\s*stop\s*[.!?]*\s*$",
        r"^\s*skip\s*[.!?]*\s*$",
    )
)


def detect_pronoun_followup(user_message: Optional[str]) -> Optional[dict]:
    """Return `{"verb": ...}` if the message is a bare follow-up, else None.

    See module docstring for behavior details.
    """
    if not isinstance(user_message, str):
        return None
    msg = user_message.strip()
    if not msg:
        return None
    if "\n" in msg:
        return None
    if "?" in msg:
        return None
    if len(msg) > _MAX_FOLLOWUP_CHARS:
        return None


    for pat in _SENSITIVE_REVEAL_HINTS:
        if pat.search(msg):
            return None


    for pat in _STANDALONE_CONFIRMS:
        if pat.match(msg):
            return None


    for verb, pat in _VERB_PATTERNS:
        if pat.match(msg):
            return {"verb": verb}
    return None






def is_login_bare_followup(user_message: Optional[str]) -> bool:
    """Back-compat shim: True iff `user_message` is a `show/open/view` followup.

    Callers that used to import `is_login_bare_followup` from the
    removed ``vault_chat_login_followup`` module can continue to
    call this shim. New callers should use ``detect_pronoun_followup``
    and dispatch on the verb tag.
    """
    hit = detect_pronoun_followup(user_message)
    if hit is None:
        return False
    return hit.get("verb") in ("show", "open", "view")


__all__ = [
    "detect_pronoun_followup",
    "is_login_bare_followup",
]
