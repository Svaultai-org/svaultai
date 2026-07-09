

from __future__ import annotations

import re
from typing import Optional

from vault_active_context import (
    CONTEXT_CREDENTIAL_DRAFT,
    CONTEXT_FILE_SEARCH_RESULTS,
    CONTEXT_GENERAL_CHAT,
    CONTEXT_VAULT_QUESTION,
)


EXPLICIT_CREDENTIAL_SAVE_PATTERNS: tuple[str, ...] = (
    r"\bsave\s+(?:the\s+)?(?:login\s+)?draft\b",
    r"\bsave\s+(?:the\s+|that\s+)?credential\b",
    r"\bsave\s+(?:the\s+|that\s+)?login\b",
    r"\bsave\s+the\s+pending\s+(?:login|draft|credential)\b",
    r"\bsave\s+the\s+[a-z][a-z\- ]+\s+login\b",                                
    r"\bgo\s+back\s+to\s+(?:the\s+)?(?:login\s+)?draft\b",
    r"\bgo\s+back\s+to\s+(?:the\s+)?credential\b",
    r"\bsave\s+(?:the\s+|that\s+|my\s+)?(?:username|password)\b",
)


EXPLICIT_FILE_SAVE_PATTERNS: tuple[str, ...] = (
    r"\bsave\s+(?:this|that|the|one\s+of\s+the)\s+(?:file|files|"
    r"photo|photos|picture|pictures|image|images|document|"
    r"documents|card|cards|result|results|id|ids|passport|"
    r"passports)\b",
    r"\bbookmark\s+(?:this|that|the|it)\b",
    r"\bopen\s+(?:this|that|the\s+first|the\s+second|the\s+third|"
    r"\s*\d+(?:st|nd|rd|th))\b",
)


AMBIGUOUS_SAVE_PATTERNS: tuple[str, ...] = (
    r"\bsave\s+it(?:\s+now)?\b",
    r"\bsave\s+that\b",
    r"\bsave\s+this\b",
)


_EXPLICIT_CREDENTIAL_RE = [
    re.compile(p, re.IGNORECASE) for p in EXPLICIT_CREDENTIAL_SAVE_PATTERNS
]
_EXPLICIT_FILE_RE = [
    re.compile(p, re.IGNORECASE) for p in EXPLICIT_FILE_SAVE_PATTERNS
]
_AMBIGUOUS_SAVE_RE = [
    re.compile(p, re.IGNORECASE) for p in AMBIGUOUS_SAVE_PATTERNS
]


def is_explicit_credential_save_phrase(user_message: str) -> bool:


    if not isinstance(user_message, str) or not user_message:
        return False
    return any(p.search(user_message) for p in _EXPLICIT_CREDENTIAL_RE)


def is_explicit_file_save_phrase(user_message: str) -> bool:


    if not isinstance(user_message, str) or not user_message:
        return False
    return any(p.search(user_message) for p in _EXPLICIT_FILE_RE)


def is_ambiguous_save_phrase(user_message: str) -> bool:


    if not isinstance(user_message, str) or not user_message:
        return False
    if is_explicit_credential_save_phrase(user_message):
        return False
    if is_explicit_file_save_phrase(user_message):
        return False
    return any(p.search(user_message) for p in _AMBIGUOUS_SAVE_RE)


def should_suppress_pending_draft_save_shortcut(
    *,
    active_context: Optional[str],
    user_message: str,
    has_pending_draft: bool,
) -> bool:


    if not has_pending_draft:
        return True
    if is_explicit_credential_save_phrase(user_message):
        return False
    if is_explicit_file_save_phrase(user_message):
        return True
    ambiguous = is_ambiguous_save_phrase(user_message)
    if active_context == CONTEXT_CREDENTIAL_DRAFT and ambiguous:
                                                            
                               
        return False
    if active_context == CONTEXT_FILE_SEARCH_RESULTS:
                                                                
                                                               
        return True
                                                             
                                                                     
    return not is_explicit_credential_save_phrase(user_message)


def should_request_save_ambiguity_clarification(
    *,
    active_context: Optional[str],
    user_message: str,
    has_pending_draft: bool,
) -> bool:


    if not has_pending_draft:
        return False
    if active_context != CONTEXT_FILE_SEARCH_RESULTS:
        return False
    return is_ambiguous_save_phrase(user_message)


AMBIGUITY_CLARIFICATION_TEXT: str = (
    "Do you mean save the pending login draft, or "
    "save/bookmark one of these files?"
)


_STYLE_PREAMBLE: str = (
    "STYLE: Reply like a calm, helpful vault — short, warm, plain "
    "text. Do NOT use markdown asterisks (**bold** renders literally "
    "in this chat). Do NOT use numbered corporate lists. Do NOT say "
    "\"I'm designed to\", \"As an AI\", \"As your assistant\", or any "
    "similar stiff preamble. Light emoji use is fine — at most 1-3 "
    "of: 🔎 search, 🔐 credentials/security, 📄 documents, 🪪 IDs, "
    "🧾 receipts/forms, 🗂️ organising. Skip emojis if the topic is "
    "sensitive or serious. Lead with a warm opener like \"Nice — \" "
    "or \"Sure — \" when the user is exploring."
)


_CONTEXT_HINT_FILE_SEARCH_RESULTS: str = (
    "ACTIVE CONTEXT: the user just saw a file_search_results card. "
    "Follow-up questions about what to do next refer to those file "
    "results, not to any earlier credential draft. Offer file "
    "actions like: open one of the files, compare names across "
    "results, find more files for the same person, extract dates "
    "or document details, or help organize them. DO NOT mention a "
    "pending login draft unless the user explicitly says so (e.g. "
    "\"save the login draft\", \"save the Union Bank login\", or "
    "\"go back to the credential draft\").\n\n"
    + _STYLE_PREAMBLE + "\n\n"
    "EXAMPLE follow-up for \"what more can you do?\" after ID photos:\n"
    "Nice — I can help you do more with these ID photos 🪪\n\n"
    "I can open one, compare the names across them, find other "
    "files for the same person, pull out details like name or "
    "dates, or help organize them into cleaner groups.\n\n"
    "You can also ask things like:\n"
    "'open the HEIC one'\n"
    "'find all IDs for Louis'\n"
    "'show documents with expiry dates'\n"
    "'compare these names'"
)


_CONTEXT_HINT_CREDENTIAL_DRAFT: str = (
    "ACTIVE CONTEXT: the user has a pending credential draft. "
    "Short ambiguous phrasings like \"save it now\" / \"save that\" "
    "address the credential draft and route to the save flow.\n\n"
    + _STYLE_PREAMBLE
)


_CONTEXT_HINT_VAULT_QUESTION: str = (
    "ACTIVE CONTEXT: the user just asked a vault overview / "
    "metadata question. Follow-ups should stay grounded in that "
    "overview unless the user pivots explicitly.\n\n"
    + _STYLE_PREAMBLE
)


_CONTEXT_HINT_CAPABILITY_QUESTION: str = (
    "ACTIVE CONTEXT: the user just asked a general capability "
    "question (\"what can you do?\"). Reply in the calm, friendly "
    "vault voice — short, warm, plain text. Mention the user's "
    "vault explicitly so the reply feels grounded.\n\n"
    + _STYLE_PREAMBLE + "\n\n"
    "EXAMPLE reply for \"what can you do?\":\n"
    "I can help you find, understand, and organize what's inside "
    "your vault 🔐\n\n"
    "I can search your files, find IDs or passports, read PDFs "
    "and images, help with saved logins, check expiry dates, and "
    "pull together related documents.\n\n"
    "Ask me something simple like:\n"
    "'show me all ID photos'\n"
    "'find my Wells Fargo files'\n"
    "'create a login for Union Bank'\n"
    "'what documents are expiring?'"
)


def context_hint_system_message(
    *,
    active_context: Optional[str],
    has_pending_draft: bool,
    planner_intent: Optional[str] = None,
) -> Optional[str]:


    if active_context == CONTEXT_FILE_SEARCH_RESULTS:
        return _CONTEXT_HINT_FILE_SEARCH_RESULTS
    if active_context == CONTEXT_CREDENTIAL_DRAFT:
        return _CONTEXT_HINT_CREDENTIAL_DRAFT
    if active_context == CONTEXT_VAULT_QUESTION:
        return _CONTEXT_HINT_VAULT_QUESTION
                                                                      
    if planner_intent in ("capability_question", "identity_question"):
        return _CONTEXT_HINT_CAPABILITY_QUESTION
    return None


__all__ = [
    "EXPLICIT_CREDENTIAL_SAVE_PATTERNS",
    "EXPLICIT_FILE_SAVE_PATTERNS",
    "AMBIGUOUS_SAVE_PATTERNS",
    "AMBIGUITY_CLARIFICATION_TEXT",
    "is_explicit_credential_save_phrase",
    "is_explicit_file_save_phrase",
    "is_ambiguous_save_phrase",
    "should_suppress_pending_draft_save_shortcut",
    "should_request_save_ambiguity_clarification",
    "context_hint_system_message",
]
