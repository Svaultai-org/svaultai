

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Optional


GUARDED_TOOL_NAMES: frozenset[str] = frozenset({
    "find_in_vault",
                                                        
                                                     
    "list_saved_credentials",
    "get_credential_metadata",
    "list_secrets",
    "retrieve_secret",
})


CREDENTIAL_TOOL_NAMES: frozenset[str] = frozenset({
    "list_saved_credentials",
    "get_credential_metadata",
    "list_secrets",
    "retrieve_secret",
})


_DOCUMENT_INTENT_RE = re.compile(
    r"\b(?:passports?|id\s+(?:photos?|cards?|documents?)|"
    r"identity\s+cards?|identification\s+(?:cards?|documents?)|"
    r"driver(?:'?s)?\s+licen[cs]es?|driving\s+licen[cs]es?|"
    r"national\s+ID|state\s+ID|"
    r"birth\s+certificates?|"
    r"social\s+security\s+cards?|ssn\s+cards?|"
    r"green\s+cards?|residence\s+permits?|"
    r"DL\s+number)\b",
    re.IGNORECASE,
)


def _query_asks_for_document(query: str) -> bool:
    if not query:
        return False
    return bool(_DOCUMENT_INTENT_RE.search(query))


_KNOWN_EXTENSIONS: tuple[str, ...] = (
    "txt", "pdf",
    "jpg", "jpeg", "png", "gif", "heic", "webp", "tif", "tiff", "bmp",
    "doc", "docx", "xls", "xlsx", "csv", "md", "json", "html", "htm",
    "rtf",
    "mp3", "mp4", "wav", "mov", "m4a", "m4v", "ogg", "webm",
    "zip", "tar", "gz", "7z", "rar",
)


_FILENAME_RE: re.Pattern[str] = re.compile(
    r"(?<![\w/.])([A-Za-z0-9][\w\-.]{0,200}\.(?:"
    + "|".join(_KNOWN_EXTENSIONS) + r"))\b",
    re.IGNORECASE,
)


def extract_filenames_from_reply(reply_text: str) -> list[str]:


    if not reply_text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in _FILENAME_RE.finditer(reply_text):
        fn = m.group(1)
        low = fn.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(fn)
    return out


_REQUESTED_PASSPORT_RE = re.compile(
    r"\bpassports?\b", re.IGNORECASE,
)
_REQUESTED_DRIVER_LICENSE_RE = re.compile(
    r"\bdriver(?:'?s)?\s+licen[cs]es?\b"
    r"|\bdriving\s+licen[cs]es?\b"
    r"|\bdriver\s+id\b"
    r"|\bDL(?:\s+number)?\b",
    re.IGNORECASE,
)
_REQUESTED_ID_PHOTO_RE = re.compile(
    r"\b(?:ID\s+(?:photos?|cards?|documents?)|"
    r"identity\s+cards?|"
    r"identification\s+(?:cards?|documents?)|"
    r"state\s+ID|national\s+ID)\b",
    re.IGNORECASE,
)


def requested_document_type(query: str) -> Optional[str]:


    if not query:
        return None
    if _REQUESTED_PASSPORT_RE.search(query):
        return "passport"
    if _REQUESTED_DRIVER_LICENSE_RE.search(query):
        return "driver_license"
    if _REQUESTED_ID_PHOTO_RE.search(query):
        return "id_photo"
    return None


_NOT_FOUND_PHRASES: tuple[str, ...] = (
    "couldn't find",
    "could not find",
    "can't find",
    "cannot find",
    "didn't find",
    "did not find",
    "no matching files",
    "no files matching",
    "no documents matching",
    "no images matching",
    "no results",
    "nothing matching",
    "no match",
    "not found",
    "no record",
    "no relevant",
    "i checked your vault",
)


def says_not_found(reply_text: str) -> bool:
    if not reply_text:
        return False
    tlow = reply_text.lower()
    return any(p in tlow for p in _NOT_FOUND_PHRASES)


_CLAIMS_PASSPORT_FOUND_PHRASES: tuple[str, ...] = (
    "found your passport",
    "found a passport",
    "found the passport",
    "your passport is",
    "passport: ",
    "passport found",
    "i have your passport",
    "here is your passport",
)


def claims_passport_found(reply_text: str) -> bool:
    if not reply_text:
        return False
    tlow = reply_text.lower()
    return any(p in tlow for p in _CLAIMS_PASSPORT_FOUND_PHRASES)


_CREDENTIAL_LANGUAGE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bsaved\s+(?:your\s+)?(?:union\s+bank|chase|gmail|"
        r"amazon|netflix|apple|paypal|bank\s+of\s+america|"
        r"wells\s+fargo)\b",
        r"\bone\s+password\s+in\s+your\s+vault\b",
        r"\bfound\s+one\s+password\b",
        r"\bsaved\s+credentials?\b",
        r"\bsaved\s+logins?\b",
        r"\bsaved\s+passwords?\b",
        r"\byour\s+(?:saved\s+)?login\s+for\b",
        r"\b(?:show|reveal|see)\s+(?:the\s+)?(?:saved\s+)?(?:login\s+)?details\?",
        r"\bcredentials?\s+for\s+(?:union\s+bank|chase|gmail|"
        r"amazon|netflix|apple|paypal|bank\s+of\s+america|"
        r"wells\s+fargo)\b",
    )
)


def has_credential_language(reply_text: str) -> bool:
    if not reply_text:
        return False
    return any(
        r.search(reply_text) for r in _CREDENTIAL_LANGUAGE_PATTERNS
    )


def reply_mentions_password_not_passport(reply_text: str) -> bool:


    if not reply_text:
        return False
    tlow = reply_text.lower()
    if "passport" in tlow:
        return False
    return any(
        t in tlow for t in (
            "password", "saved login", "credentials for",
            "your login", "one password", "saved credential",
        )
    )


CORRECTION_NOT_FOUND: str = (
    "I checked your vault and couldn't find files matching that request."
)

CORRECTION_NOT_FOUND_SEARCH_LIMITED: str = (
    "Search incomplete. I checked what I could, but the search "
    "hit its limit before reviewing every file."
)


def correction_passport_got_driver_license(hits: list[dict]) -> str:


    first_dl: Optional[dict] = None
    for h in hits:
        if not isinstance(h, dict):
            continue
        if h.get("document_type") == "driver_license":
            first_dl = h
            break
    if first_dl is None:
                                                           
                        
        for h in hits:
            if isinstance(h, dict):
                first_dl = h
                break
    if first_dl is None:
        return CORRECTION_NOT_FOUND

    name = str(first_dl.get("file_name") or "the file")
    matched = str(first_dl.get("matched_name") or "")
    if matched:
        return (
            f"I didn't find a passport. I did find a driver's "
            f"license that may be related: {name}. The name on "
            f"it reads {matched}."
        )
    return (
        f"I didn't find a passport. I did find a driver's "
        f"license that may be related: {name}."
    )


def correction_grounded_from_hits(
    hits: list[dict], requested_type: Optional[str],
) -> str:


    if not hits:
        return CORRECTION_NOT_FOUND
    lines: list[str] = ["I found these files in your vault:"]
    for h in hits[:5]:
        if not isinstance(h, dict):
            continue
        name = str(h.get("file_name") or "(unnamed file)")
        doc_type = str(h.get("document_type") or "")
        if doc_type and doc_type != "unknown":
            human = doc_type.replace("_", " ")
            lines.append(f"- {name} ({human})")
        else:
            lines.append(f"- {name}")
    return "\n".join(lines)


def _parse_tool_result(tool_result: Any) -> Optional[dict]:
    if tool_result is None:
        return None
    payload: Any = tool_result
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8", errors="replace")
        except Exception:
            return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return None
    if isinstance(payload, dict):
        return payload
    return None


def _hit_file_names_lower(hits: list[dict]) -> set[str]:
    out: set[str] = set()
    for h in hits:
        if isinstance(h, dict):
            n = str(h.get("file_name") or "").strip().lower()
            if n:
                out.add(n)
    return out


def _hit_doc_types(hits: list[dict]) -> set[str]:
    out: set[str] = set()
    for h in hits:
        if isinstance(h, dict):
            t = str(h.get("document_type") or "unknown").strip().lower()
            if t:
                out.add(t)
    return out


def truth_guard(
    *,
    query: str,
    reply_text: str,
    tool_name: Optional[str],
    tool_result: Any,
) -> tuple[str, Optional[str]]:


    if not reply_text:
        return reply_text, None
    if tool_name not in GUARDED_TOOL_NAMES:
        return reply_text, None

                                                        
    if tool_name in CREDENTIAL_TOOL_NAMES:
        if _query_asks_for_document(query):
            return CORRECTION_NOT_FOUND, "document_query_credential_tool"
                                                         
                                                        
        return reply_text, None

    parsed = _parse_tool_result(tool_result)
    if parsed is None:
        return reply_text, None
    if "error" in parsed:
                                                    
        return reply_text, None

    raw_hits = parsed.get("hits")
    hits = raw_hits if isinstance(raw_hits, list) else []
    complete = bool(parsed.get("complete"))
    hit_names_lc = _hit_file_names_lower(hits)
    hit_types = _hit_doc_types(hits)
    requested = requested_document_type(query)

    reply_filenames = extract_filenames_from_reply(reply_text)

                                                
    if reply_filenames:
        invented = [
            f for f in reply_filenames
            if f.lower() not in hit_names_lc
        ]
        if invented:
            if not hits:
                return (
                    correction_grounded_from_hits(hits, requested),
                    "empty_hits_invented_names",
                )
            return (
                correction_grounded_from_hits(hits, requested),
                "invented_filenames",
            )

                                                                      
    if (
        requested == "passport"
        and hits
        and "passport" not in hit_types
        and "driver_license" in hit_types
        and claims_passport_found(reply_text)
    ):
        return (
            correction_passport_got_driver_license(hits),
            "passport_mismatch_driver_license",
        )

                                                     
    query_lc = (query or "").lower()
    if (
        "passport" in query_lc
        and reply_mentions_password_not_passport(reply_text)
    ):
        if hits:
            return (
                correction_passport_got_driver_license(hits),
                "password_passport_confusion",
            )
        return CORRECTION_NOT_FOUND, "password_passport_confusion"

                                                                
    if has_credential_language(reply_text):
        return (
            correction_grounded_from_hits(hits, requested),
            "credential_language_in_doc_search",
        )

                                                                    
    if complete and not hits and not says_not_found(reply_text):
        return CORRECTION_NOT_FOUND, "empty_hits_no_not_found"

                                                                 
    if not complete and not hits and not _says_search_limited(reply_text):
        return (
            CORRECTION_NOT_FOUND_SEARCH_LIMITED,
            "search_limit_unannounced",
        )

    return reply_text, None


_SEARCH_LIMIT_PHRASES: tuple[str, ...] = (
    "search hit", "ran past the budget", "budget for this turn",
    "search ran past", "did not finish", "didn't finish",
    "hit the limit", "ran out of time", "took too long",
    "ask again",
)


def _says_search_limited(reply_text: str) -> bool:
    if not reply_text:
        return False
    tlow = reply_text.lower()
    return any(p in tlow for p in _SEARCH_LIMIT_PHRASES)


__all__ = [
    "GUARDED_TOOL_NAMES",
    "CREDENTIAL_TOOL_NAMES",
    "CORRECTION_NOT_FOUND",
    "CORRECTION_NOT_FOUND_SEARCH_LIMITED",
    "extract_filenames_from_reply",
    "requested_document_type",
    "says_not_found",
    "claims_passport_found",
    "has_credential_language",
    "reply_mentions_password_not_passport",
    "correction_passport_got_driver_license",
    "correction_grounded_from_hits",
    "truth_guard",
]
