

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional


logger = logging.getLogger(__name__)


SENTENCE_VAULT_UNAVAILABLE = (
    "I couldn't search that part of the vault right now. "
    "The vault is unlocked, but the search service returned "
    "unavailable. I'll keep the request safe and you can try "
    "again after the backend finishes indexing."
)

SENTENCE_VAULT_LOCKED = (
    "I can see the shape of your vault, but I need it unlocked "
    "to read the file contents. Unlock with your PIN and ask "
    "again."
)

SENTENCE_EMPTY_RESULT = (
    "I checked your vault and didn't find anything matching that."
)

SENTENCE_GENERIC_TOOL_FAILED = (
    "I couldn't complete that part of the search. Try again in "
    "a moment."
)

SENTENCE_GENERAL_RESPONSE_FAILED = (
    "I couldn't complete that response. Please try again."
)

_GENERAL_RESPONSE_FAILED_BY_LANGUAGE = {
    "tl": "Hindi ko makumpleto ang tugon. Pakisubukan muli.",
    "fr": "Je n’ai pas pu terminer cette réponse. Veuillez réessayer.",
    "ar": "تعذّر عليّ إكمال الرد. يُرجى المحاولة مرة أخرى.",
    "so": "Ma dhammaystiri karin jawaabta. Fadlan mar kale isku day.",
    "es": "No pude completar la respuesta. Inténtalo de nuevo.",
    "ja": "応答を完了できませんでした。もう一度お試しください。",
    "hi": "मैं उत्तर पूरा नहीं कर सका। कृपया फिर से प्रयास करें।",
    "sw": "Sikuweza kukamilisha jibu. Tafadhali jaribu tena.",
    "fa": "نتوانستم پاسخ را کامل کنم. لطفاً دوباره تلاش کنید.",
}


def localized_general_response_failed(language: str) -> str:
    """Return a neutral generation failure in the resolved reply language."""
    normalized = str(language or "").strip().lower().replace("_", "-")
    code = normalized.split("-", 1)[0]
    return _GENERAL_RESPONSE_FAILED_BY_LANGUAGE.get(
        code, SENTENCE_GENERAL_RESPONSE_FAILED,
    )

_SEARCH_TOOL_NAMES = frozenset({
    "find_in_vault", "search_extracted_text", "search_vault_content",
    "list_vault_files", "list_files_by_category", "read_file_text",
    "read_image_with_vision", "read_media_transcript",
})


def _tool_failure_sentence(tool_name: str) -> str:
    return (
        SENTENCE_GENERIC_TOOL_FAILED
        if str(tool_name or "") in _SEARCH_TOOL_NAMES
        else SENTENCE_GENERAL_RESPONSE_FAILED
    )


_ERROR_KEYS = ("error", "errors", "exception", "fault", "failure")

_UNAVAILABLE_TOKENS = (
    "unavailable", "db_error", "decrypt_failed",
    "schema_mismatch", "no_key",
)

_VAULT_LOCKED_TOKENS = (
    "vault_locked", "locked", "needs_unlock",
)


def looks_like_raw_json(text: str) -> bool:


    if not isinstance(text, str):
        return False
    t = text.strip()
    if not t.startswith("{") or not t.endswith("}"):
        return False
    try:
        parsed = json.loads(t)
    except Exception:
        return False
    return isinstance(parsed, (dict, list))


def _payload_says_unavailable(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    for k in _ERROR_KEYS:
        v = str(payload.get(k) or "").strip().lower()
        if not v:
            continue
        for tok in _UNAVAILABLE_TOKENS:
            if tok in v:
                return True
                                                                 
    return str(payload.get("reason") or "").strip().lower() in _UNAVAILABLE_TOKENS


def _payload_says_locked(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    for k in _ERROR_KEYS + ("reason",):
        v = str(payload.get(k) or "").strip().lower()
        if not v:
            continue
        for tok in _VAULT_LOCKED_TOKENS:
            if tok in v:
                return True
    return False


def _coverage_sentence(payload: Any) -> Optional[str]:


    if not isinstance(payload, dict):
        return None
    cov = payload.get("coverage")
    if not isinstance(cov, dict):
        return None
    total = int(cov.get("total") or 0)
    analyzed = int(cov.get("analyzed") or 0)
    is_complete = bool(cov.get("is_complete"))
    if total <= 0:
        return None
    if is_complete:
        return None
    return (
        f"I've reviewed {analyzed} of {total} files so far, "
        "so this may be incomplete."
    )


def sanitize_tool_result(
    tool_name: str, raw_result: Any,
) -> str:


    if raw_result is None:
        return _tool_failure_sentence(tool_name)

                                                   
    payload: Any = None
    if isinstance(raw_result, str):
        text = raw_result.strip()
        if not text:
            return _tool_failure_sentence(tool_name)
        if not looks_like_raw_json(text):
            return text
        try:
            payload = json.loads(text)
        except Exception:
            return _tool_failure_sentence(tool_name)
    else:
        payload = raw_result

    if _payload_says_unavailable(payload):
        return SENTENCE_VAULT_UNAVAILABLE
    if _payload_says_locked(payload):
        return SENTENCE_VAULT_LOCKED

                                                                 
    if isinstance(payload, dict):
        for k in _ERROR_KEYS:
            if payload.get(k):
                return _tool_failure_sentence(tool_name)

                                                               
    if isinstance(payload, dict):
        if (
            "files" in payload and not payload.get("files")
            and not payload.get("count")
            and not payload.get("returned")
        ) or (
            "hits" in payload and not payload.get("hits")
        ):
            cov_line = _coverage_sentence(payload) or ""
            base = SENTENCE_EMPTY_RESULT
            return f"{base} {cov_line}".strip()

                                                            
    return raw_result if isinstance(raw_result, str) else json.dumps(payload)


def sanitize_user_facing_text(text: str) -> str:


    if not isinstance(text, str):
        return ""
    if not looks_like_raw_json(text):
        return text
    try:
        payload = json.loads(text)
    except Exception:
        return SENTENCE_GENERAL_RESPONSE_FAILED
    if _payload_says_unavailable(payload):
        return SENTENCE_VAULT_UNAVAILABLE
    if _payload_says_locked(payload):
        return SENTENCE_VAULT_LOCKED
    if isinstance(payload, dict):
        for k in _ERROR_KEYS:
            if payload.get(k):
                return SENTENCE_GENERAL_RESPONSE_FAILED
                                                            
                                                            
    return SENTENCE_EMPTY_RESULT


__all__ = [
    "SENTENCE_VAULT_UNAVAILABLE",
    "SENTENCE_VAULT_LOCKED",
    "SENTENCE_EMPTY_RESULT",
    "SENTENCE_GENERIC_TOOL_FAILED",
    "SENTENCE_GENERAL_RESPONSE_FAILED",
    "localized_general_response_failed",
    "looks_like_raw_json",
    "sanitize_tool_result",
    "sanitize_user_facing_text",
]
