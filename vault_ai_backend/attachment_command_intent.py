"""Deterministic intent-only parsing for current-message attachments.

The normalized text produced here is a disposable routing view.  It must
never be passed to credential field extraction or persistence: usernames,
passwords, PINs, account numbers, URLs, and identifiers always remain exactly
as supplied by the user or source document.
"""

from __future__ import annotations

import re
from typing import Optional


ATTACHMENT_INTENT_CREDENTIAL_EXTRACTION = "credential_extraction"
ATTACHMENT_INTENT_CONTENT_ANALYSIS = "content_analysis"


_COMMAND_ALIASES = {
    "analyse": "analyze",
    "analysed": "analyzed",
    "analysing": "analyzing",
    "anlyze": "analyze",
    "ths": "this",
    "teh": "the",
    "yhe": "the",
    "credntial": "credential",
    "credntials": "credentials",
    "pasword": "password",
    "paswords": "passwords",
    "docment": "document",
}

_COMMAND_LEXICON = frozenset({
    "analyze", "analyzed", "analyzing", "inspect", "review", "read",
    "scan", "extract", "identify", "classify", "explain", "compare",
    "summarize", "transcribe", "describe", "understand", "find", "get",
    "show", "save", "what", "which", "who", "where", "when", "why",
    "how", "this", "that", "the", "file", "document", "attachment",
    "attached", "pdf", "image", "photo", "credential", "credentials",
    "password", "passwords", "login", "logins", "username", "usernames",
    "account", "accounts", "pin", "pins", "secret", "secrets", "secure",
    "record", "records", "code", "codes", "identifier", "identifiers",
})

_ANALYSIS_ACTION_RE = re.compile(
    r"\b(?:analyz(?:e|ed|ing)|inspect|review|read|scan|extract|identify|"
    r"classify|explain|compare|summarize|transcribe|describe|understand|"
    r"find|get|show)\b",
)
_CREDENTIAL_NOUN_RE = re.compile(
    r"\b(?:credentials?|passwords?|logins?|usernames?|accounts?|pins?|"
    r"secrets?|secure\s+records?|access\s+codes?|identifiers?)\b",
)
_ATTACHMENT_REFERENT_RE = re.compile(
    r"\b(?:this|that|attached|attachment|file|document|pdf|image|photo)\b",
)
_MISSING_ATTACHMENT_REFERENT_RE = re.compile(
    r"\b(?:this|that)(?:\s+(?:file|document|pdf|image|photo|attachment))?\b|"
    r"\b(?:attached|attachment|newly\s+uploaded|just\s+uploaded|"
    r"current\s+(?:file|document|attachment))\b",
)
_QUESTION_RE = re.compile(
    r"^\s*(?:what|which|who|where|when|why|how|is|are|does|do|can)\b",
)
_SAVE_REVIEW_SET_RE = re.compile(
    r"\bsave\s+(?:(?:the|all|any)\s+)?"
    r"(?:credentials?|passwords?|logins?|secure\s+records?)\b",
)
_EXPLICIT_EXISTING_VAULT_SCOPE_RE = re.compile(
    r"\b(?:search|look\s+through|scan|check)\s+(?:in\s+)?(?:my|the)\s+vault\b|"
    r"\b(?:existing|previously|already)\s+(?:saved|uploaded)\b|"
    r"\b(?:what\s+is|show|get|retrieve|find)\s+(?:me\s+)?my\s+"
    r"[^?]{1,80}\b(?:login|credential|password)\b",
)
_COHERENT_SUPPLIED_ASSERTION_RE = re.compile(
    r"\b(?:username|user)\s+(?:is\s+)?\S+.*"
    r"\b(?:password|pass|pwd)\s+(?:is\s+)?\S+",
    re.IGNORECASE,
)


def _one_edit_apart(left: str, right: str) -> bool:
    """Return True for one insertion/deletion/substitution/transposition."""
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = [i for i, pair in enumerate(zip(left, right)) if pair[0] != pair[1]]
        if len(differences) == 1:
            return True
        return (
            len(differences) == 2
            and differences[1] == differences[0] + 1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]]
        )
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    short_index = 0
    long_index = 0
    skipped = False
    while short_index < len(shorter) and long_index < len(longer):
        if shorter[short_index] == longer[long_index]:
            short_index += 1
            long_index += 1
            continue
        if skipped:
            return False
        skipped = True
        long_index += 1
    return True


def _normalize_command_token(token: str) -> str:
    lowered = token.lower()
    if lowered in _COMMAND_ALIASES:
        return _COMMAND_ALIASES[lowered]
    if lowered in _COMMAND_LEXICON or len(lowered) < 4:
        return lowered
    candidates = [
        known for known in _COMMAND_LEXICON
        if abs(len(known) - len(lowered)) <= 1
        and _one_edit_apart(lowered, known)
    ]
    return candidates[0] if len(candidates) == 1 else lowered


def normalize_attachment_command_language(text: str) -> str:
    """Build a lowercase command-only matching view; never a data payload."""
    if not isinstance(text, str):
        return ""
    return re.sub(
        r"[A-Za-z]+",
        lambda match: _normalize_command_token(match.group(0)),
        text,
    ).lower()


def classify_attachment_command(text: str) -> Optional[str]:
    """Classify an instruction assuming a current attachment is available."""
    if not isinstance(text, str) or not text.strip():
        return None
    if _EXPLICIT_EXISTING_VAULT_SCOPE_RE.search(text):
        return None
    # A coherent supplied credential assertion remains a credential command,
    # even if a value happens to resemble a misspelled command word.
    if _COHERENT_SUPPLIED_ASSERTION_RE.search(text):
        return None

    command_view = normalize_attachment_command_language(text)
    has_action = bool(_ANALYSIS_ACTION_RE.search(command_view))
    has_credentials = bool(_CREDENTIAL_NOUN_RE.search(command_view))
    has_referent = bool(_ATTACHMENT_REFERENT_RE.search(command_view))
    is_question = bool(_QUESTION_RE.search(command_view))

    if has_credentials and (
        has_action
        or (has_referent and is_question)
        or (has_referent and _SAVE_REVIEW_SET_RE.search(command_view))
    ):
        return ATTACHMENT_INTENT_CREDENTIAL_EXTRACTION
    if has_action or (has_referent and is_question):
        return ATTACHMENT_INTENT_CONTENT_ANALYSIS
    return None


def references_attachment_object(text: str) -> bool:
    """Return whether language deictically requires a current attachment."""
    return bool(
        isinstance(text, str)
        and _MISSING_ATTACHMENT_REFERENT_RE.search(
            normalize_attachment_command_language(text)
        )
    )


__all__ = [
    "ATTACHMENT_INTENT_CREDENTIAL_EXTRACTION",
    "ATTACHMENT_INTENT_CONTENT_ANALYSIS",
    "classify_attachment_command",
    "normalize_attachment_command_language",
    "references_attachment_object",
]
