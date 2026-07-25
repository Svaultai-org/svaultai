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


        ("download", r"^\s*download\s+it\s*[.!?]*\s*$"),
        ("download", r"^\s*download\s+that\s*[.!?]*\s*$"),
        ("download", r"^\s*download\s+that\s+one\s*[.!?]*\s*$"),
        ("download", r"^\s*download\s+the\s+file\s*[.!?]*\s*$"),


        # Pagination follow-up for file/collection cards. "show more"
        # after a file-list card resurfaces the same list card with
        # the next page slice. See dispatcher in main.py.
        ("more", r"^\s*show\s+more\s*[.!?]*\s*$"),
        ("more", r"^\s*more\s*[.!?]*\s*$"),
        ("more", r"^\s*next\s*[.!?]*\s*$"),
        ("more", r"^\s*next\s+page\s*[.!?]*\s*$"),
        ("more", r"^\s*keep\s+going\s*[.!?]*\s*$"),
        ("more", r"^\s*load\s+more\s*[.!?]*\s*$"),
        ("more", r"^\s*more\s+files?\s*[.!?]*\s*$"),
        ("more", r"^\s*show\s+more\s+files?\s*[.!?]*\s*$"),


        ("upgrade", r"^\s*upgrade\s+it\s*[.!?]*\s*$"),
        ("upgrade", r"^\s*upgrade\s+that\s*[.!?]*\s*$"),
        ("upgrade", r"^\s*upgrade\s+now\s*[.!?]*\s*$"),


        # 2026-07-27 architectural gap fix: the follow-up verb set
        # the deterministic-router audit surfaced. Every one of these
        # must resolve against the active vault-object entity rather
        # than fall through to the LLM planner. The dispatcher in
        # main.py maps each canonical verb to the appropriate
        # pending_action on the file card.

        # "related" - fetch objects related to the active object
        ("related", r"^\s*show\s+related\s*[.!?]*\s*$"),
        ("related", r"^\s*show\s+me\s+related\s*[.!?]*\s*$"),
        ("related", r"^\s*show\s+the\s+related\s*[.!?]*\s*$"),
        ("related", r"^\s*any\s+related\s*[.!?]*\s*$"),
        ("related", r"^\s*related\s+files?\s*[.!?]*\s*$"),
        ("related", r"^\s*related\s+items?\s*[.!?]*\s*$"),

        # "describe" - summarize / tell me about the active object
        ("describe", r"^\s*tell\s+me\s+about\s+it\s*[.!?]*\s*$"),
        ("describe", r"^\s*tell\s+me\s+about\s+that\s*[.!?]*\s*$"),
        ("describe", r"^\s*tell\s+me\s+about\s+this\s*[.!?]*\s*$"),
        ("describe", r"^\s*what\s+is\s+it\s*[.!?]*\s*$"),
        ("describe", r"^\s*what['']?s\s+that\s*[.!?]*\s*$"),
        ("describe", r"^\s*what['']?s\s+it\s*[.!?]*\s*$"),
        ("describe", r"^\s*describe\s+it\s*[.!?]*\s*$"),
        ("describe", r"^\s*describe\s+that\s*[.!?]*\s*$"),
        ("describe", r"^\s*summarize\s+it\s*[.!?]*\s*$"),
        ("describe", r"^\s*summarize\s+that\s*[.!?]*\s*$"),

        # "move" - move the active object
        ("move", r"^\s*move\s+it\s*[.!?]*\s*$"),
        ("move", r"^\s*move\s+that\s*[.!?]*\s*$"),
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
