

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

# 2026-07-21: patterns split into two tiers to fix the production
# "what are you" → "I created the login draft" misrouting.
#
# The old flat _SAVE_CLAIM_PATTERNS set treated descriptive phrases
# ("credentials are stored", "login is stored", "stored in your
# vault") the SAME as first-person save claims ("I've saved X"). On
# a capability-question turn the LLM's normal answer contains those
# descriptive phrases ("your credentials are stored securely in your
# vault"), and the guard rewrote the entire reply with the hardcoded
# login-draft correction text — inventing an action that never
# happened.
#
# Split:
#
#   * STRONG_SAVE_CLAIMS  first-person past-tense actor claims. A
#                          reply containing these is asserting the
#                          assistant DID something. Always suspect
#                          when save_tool_succeeded=False.
#
#   * DESCRIPTIVE_SAVE_CLAIMS  passive descriptions of vault state.
#                          Legitimate prose when the turn was a
#                          capability / identity / general-chat
#                          question. Only apply when the current
#                          turn's planner intent was actually
#                          to save something.
_STRONG_SAVE_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:i(?:'|’)?ve|i\s+have|i)\s+saved\b",                "i_saved"),
    (r"\bsaved\s+(?:your|the|that|this)\b",                    "saved_your"),
    (r"\bsaved\s+it\b(?!\s+yet\b)",                            "saved_it"),
)

_DESCRIPTIVE_SAVE_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bstored\s+(?:in|to|inside)\s+(?:your\s+)?vault\b",     "stored_in_vault"),
    (r"\b(?:added|put)\s+(?:it\s+)?(?:to|in|into)\s+"
     r"(?:your\s+)?vault\b",                                   "added_to_vault"),
    (r"\bsecured\s+(?:in|inside|to)\s+(?:your\s+)?vault\b",    "secured_in_vault"),
    (r"\bcredentials?\s+(?:are\s+)?(?:now\s+)?(?:saved|"
     r"stored|secured)\b",                                     "credentials_are_saved"),
    (r"\blogin\s+(?:is\s+)?(?:now\s+)?(?:saved|stored|"
     r"secured)\b",                                            "login_is_saved"),
)

# Union of both for backward compatibility (existing callers/tests
# that expect the full pattern set).
_SAVE_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    _STRONG_SAVE_CLAIM_PATTERNS + _DESCRIPTIVE_SAVE_CLAIM_PATTERNS
)


_compiled_strong: list[tuple[re.Pattern[str], str]] | None = None
_compiled_descriptive: list[tuple[re.Pattern[str], str]] | None = None
_compiled: list[tuple[re.Pattern[str], str]] | None = None


def _compiled_patterns() -> list[tuple[re.Pattern[str], str]]:
    global _compiled
    if _compiled is None:
        _compiled = [
            (re.compile(pat, re.IGNORECASE), slug)
            for pat, slug in _SAVE_CLAIM_PATTERNS
        ]
    return _compiled


def _compiled_strong_patterns() -> list[tuple[re.Pattern[str], str]]:
    global _compiled_strong
    if _compiled_strong is None:
        _compiled_strong = [
            (re.compile(pat, re.IGNORECASE), slug)
            for pat, slug in _STRONG_SAVE_CLAIM_PATTERNS
        ]
    return _compiled_strong


def _compiled_descriptive_patterns() -> list[tuple[re.Pattern[str], str]]:
    global _compiled_descriptive
    if _compiled_descriptive is None:
        _compiled_descriptive = [
            (re.compile(pat, re.IGNORECASE), slug)
            for pat, slug in _DESCRIPTIVE_SAVE_CLAIM_PATTERNS
        ]
    return _compiled_descriptive


SAFE_CORRECTION_TEXT: str = (
    "I created the login draft, but I haven't saved it yet. "
    "Say \"save it\" when you want me to store it in your vault."
)


def _is_negated_match(text: str, span: tuple[int, int]) -> bool:


    start = max(0, span[0] - 48)
    window = text[start:span[1]].lower()
    return any(tok in window for tok in _NEGATION_TOKENS)


def detect_save_claim(
    reply_text: str, *, strong_only: bool = False,
) -> Optional[str]:
    # Full-set match by default (backward-compatible with existing
    # callers). When ``strong_only=True`` we consider ONLY the
    # first-person patterns — used on turns whose planner intent
    # was NOT to save, so descriptive prose about vault storage is
    # legitimate and must not be rewritten.

    if not reply_text:
        return None
    text = str(reply_text)
    patterns = (
        _compiled_strong_patterns()
        if strong_only
        else _compiled_patterns()
    )
    for pat, slug in patterns:
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
    intent_was_save: bool = True,
) -> tuple[str, Optional[str]]:
    # 2026-07-21: added ``intent_was_save`` so the guard can
    # distinguish two very different situations:
    #
    #   1. The current turn was routed as a save intent (the user
    #      asked to save/store something). If the LLM's reply then
    #      claims a save happened but no save tool actually
    #      succeeded, that is a hallucination we MUST rewrite —
    #      whether the claim is worded strongly ("I've saved X") or
    #      descriptively ("credentials are stored"). This is the
    #      original invariant from the 2026-06-27 guard.
    #
    #   2. The current turn was routed as something else
    #      (capability_question, identity_question, casual_chat,
    #      vault_summary, credential_lookup, …). The LLM's answer
    #      may legitimately describe vault behavior in general terms
    #      ("your credentials are stored securely in your vault").
    #      Only the STRONG first-person claims about what the
    #      assistant DID indicate a hallucination in that case.
    #
    # Default value ``intent_was_save=True`` keeps the pre-2026-07-21
    # strict behavior for any caller that hasn't been updated yet —
    # never a regression toward missed hallucinations.
    if save_tool_succeeded:
        return reply_text, None
    slug = detect_save_claim(
        reply_text, strong_only=not intent_was_save,
    )
    if slug is None:
        return reply_text, None
    return SAFE_CORRECTION_TEXT, slug


def planner_intent_is_save(
    *,
    planner: object,          # PlannerDecision or None
    allowed_tool_names: set[str],
) -> bool:
    # True iff the current turn's planner intent (or, if the planner
    # was unavailable, the allowed_tools whitelist) indicates the
    # user asked us to save/store a credential. Used by the /chat
    # orchestrator to compute ``intent_was_save`` for the guard.
    save_intents = {
        "credential_creation_draft",
        "credential_save_confirmation",
    }
    if planner is not None:
        intent = getattr(planner, "intent", None)
        if isinstance(intent, str) and intent in save_intents:
            return True
        planned_tools = getattr(planner, "planned_tools", ()) or ()
        for name in planned_tools:
            if name in SAVE_TOOL_NAMES:
                return True
        return False
    # No planner decision — fall back to allowed_tools membership.
    return any(name in SAVE_TOOL_NAMES for name in allowed_tool_names)


__all__ = [
    "SAVE_TOOL_NAMES",
    "SAFE_CORRECTION_TEXT",
    "detect_save_claim",
    "tool_call_was_successful_save",
    "guard_response_text",
    "planner_intent_is_save",
]
