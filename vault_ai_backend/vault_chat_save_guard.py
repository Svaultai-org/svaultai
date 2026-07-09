

from __future__ import annotations

import json
import re
from typing import Optional


SAVE_TOOL_NAMES: frozenset[str] = frozenset({
    "save_secret",
    "save_generated_credential_after_confirmation",
})


_NEGATION_TOKENS: tuple[str, ...] = (
    "haven't", "have not", "haven’t",
    "hasn't", "has not", "hasn’t",
    "didn't", "did not", "didn’t",
    "won't", "will not", "won’t",
    "don't", "do not", "don’t",
    "couldn't", "could not", "couldn’t",
    "wouldn't", "would not", "wouldn’t",
    "isn't", "is not", "isn’t",
    "aren't", "are not", "aren’t",
    "wasn't", "was not", "wasn’t",
    "weren't", "were not", "weren’t",
    "not yet", "not saved", "not stored",
    "never saved", "never stored",
    "nothing", "no documents", "no files",
    "no images", "no records", "no credentials",
    "no items", "no logins", "no record",
    "no photo", "no photos", "no matching",
    "there are no", "there is no",
    "without saving", "without storing",
)

_SAVE_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:i(?:'|’)?ve|i\s+have|i)\s+saved\b",                "i_saved"),
    (r"\bsaved\s+(?:your|the|that|this)\b",                    "saved_your"),
    (r"\bsaved\s+it\b(?!\s+yet\b)",                            "saved_it"),
    (r"\bstored\s+(?:in|to|inside)\s+(?:your\s+)?vault\b",     "stored_in_vault"),
    (r"\b(?:added|put)\s+(?:it\s+)?(?:to|in|into)\s+"
     r"(?:your\s+)?vault\b",                                   "added_to_vault"),
    (r"\bsecured\s+(?:in|inside|to)\s+(?:your\s+)?vault\b",    "secured_in_vault"),
    (r"\bcredentials?\s+(?:are\s+)?(?:now\s+)?(?:saved|"
     r"stored|secured)\b",                                     "credentials_are_saved"),
    (r"\blogin\s+(?:is\s+)?(?:now\s+)?(?:saved|stored|"
     r"secured)\b",                                            "login_is_saved"),
)


_compiled: list[tuple[re.Pattern[str], str]] | None = None


def _compiled_patterns() -> list[tuple[re.Pattern[str], str]]:
    global _compiled
    if _compiled is None:
        _compiled = [
            (re.compile(pat, re.IGNORECASE), slug)
            for pat, slug in _SAVE_CLAIM_PATTERNS
        ]
    return _compiled


SAFE_CORRECTION_TEXT: str = (
    "I created the login draft, but I haven't saved it yet. "
    "Say \"save it\" when you want me to store it in your vault."
)


def _is_negated_match(text: str, span: tuple[int, int]) -> bool:


    start = max(0, span[0] - 48)
    window = text[start:span[1]].lower()
    return any(tok in window for tok in _NEGATION_TOKENS)


def detect_save_claim(reply_text: str) -> Optional[str]:


    if not reply_text:
        return None
    text = str(reply_text)
    for pat, slug in _compiled_patterns():
        for m in pat.finditer(text):
            if not _is_negated_match(text, m.span()):
                return slug
    return None


def tool_call_was_successful_save(
    tool_name: str, result_payload: object,
) -> bool:


    if tool_name not in SAVE_TOOL_NAMES:
        return False
    if result_payload is None:
        return False

                                                             
    payload: object = result_payload
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8", errors="replace")
        except Exception:
            return False
    if isinstance(payload, str):
        s = payload.strip()
        if not s:
            return False
        try:
            payload = json.loads(s)
        except Exception:
                                                          
                                         
            return "error" not in s.lower()
    if isinstance(payload, dict):
        if payload.get("error"):
            return False
                                                                   
                                                              
        return True
                                                        
                                                  
    return False


def guard_response_text(
    *,
    reply_text: str,
    save_tool_succeeded: bool,
) -> tuple[str, Optional[str]]:


    if save_tool_succeeded:
        return reply_text, None
    slug = detect_save_claim(reply_text)
    if slug is None:
        return reply_text, None
    return SAFE_CORRECTION_TEXT, slug


__all__ = [
    "SAVE_TOOL_NAMES",
    "SAFE_CORRECTION_TEXT",
    "detect_save_claim",
    "tool_call_was_successful_save",
    "guard_response_text",
]
