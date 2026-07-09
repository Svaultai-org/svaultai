

from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Optional

from locales import (
    SUPPORTED_LOCALES, detect_document_locale, detect_script,
)


logger = logging.getLogger(__name__)


def detect_language(
    text: Optional[str], user_preferred: Optional[str] = "en",
) -> str:


    fb = (user_preferred or "en").lower()
    if fb not in SUPPORTED_LOCALES:
        fb = "en"
    return detect_document_locale(text, user_locale=fb)


_SCRIPT_RANGES: tuple = (
    ("latin",   (0x0041, 0x024F)),
    ("arabic",  (0x0600, 0x06FF)),
    ("arabic",  (0x0750, 0x077F)),
    ("arabic",  (0xFB50, 0xFDFF)),
    ("arabic",  (0xFE70, 0xFEFF)),
    ("hangul",  (0xAC00, 0xD7AF)),
    ("hangul",  (0x1100, 0x11FF)),
    ("hangul",  (0x3130, 0x318F)),
    ("cjk",     (0x3040, 0x309F)),             
    ("cjk",     (0x30A0, 0x30FF)),             
    ("cjk",     (0x4E00, 0x9FFF)),                
    ("cjk",     (0x3400, 0x4DBF)),              
    ("cyrillic",(0x0400, 0x04FF)),
)


def _scripts_in_text(text: str) -> set[str]:

    seen: set[str] = set()
    for ch in text:
        if not ch.isalpha():
            continue
        cp = ord(ch)
        for tag, (lo, hi) in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                seen.add(tag)
                break
    return seen


def detect_mixed_language(text: Optional[str]) -> bool:


    try:
        if not text:
            return False
        scripts = _scripts_in_text(text)
                                                                      
                                                                    
        return len(scripts) >= 2
    except Exception:
        return False


_QUERY_NOISE: frozenset[str] = frozenset({
             
    "the","a","an","my","your","please","show","find",
            
    "le","la","les","mon","ma","mes","montre","afficher","cherche",
             
    "el","la","los","las","mi","mis","mostrar","muestra","buscar",
                          
    "の","を","は","が","に","で","へ","と",
                        
    "은","는","이","가","을","를","에","의",
             
    "的","和","在","是",
})


def normalize_query(
    text: Optional[str], lang: Optional[str] = None,
) -> str:


    try:
        if not text:
            return ""
                                                                      
                                                                    
        decomp = unicodedata.normalize("NFKD", text)
        stripped = "".join(
            ch for ch in decomp
            if not unicodedata.combining(ch)
        )
        lowered = stripped.casefold().strip()
                                                                      
        tokens = re.findall(r"\w+", lowered, flags=re.UNICODE)
        kept = [t for t in tokens if t not in _QUERY_NOISE and len(t) >= 2]
        return " ".join(kept)
    except Exception:
        return ""


def choose_reply_language(
    user_pref: Optional[str],
    detected_query_lang: Optional[str] = None,
    document_lang: Optional[str] = None,
    chat_language_override: Optional[str] = None,
) -> str:


    candidates = (
        chat_language_override, user_pref, detected_query_lang,
        document_lang, "en",
    )
    for c in candidates:
        if c and isinstance(c, str):
            cc = c.strip().lower()
            if cc in SUPPORTED_LOCALES:
                return cc
    return "en"


def _db_lookup_enabled() -> bool:


    return os.getenv(
        "VAULTAI_USER_LOCALE_DB_LOOKUP", "true",
    ).lower() == "true"


def build_language_context(vault_id: str) -> dict:


    ctx = {
        "preferred_locale": "en",
        "chat_language":    None,
        "ui_language":      None,
        "memory_language":  None,
    }
    if not _db_lookup_enabled():
        return ctx
    try:
        from vault_core import get_db                        
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT preferred_locale, chat_language,
                              ui_language, memory_language
                       FROM vault_preferences
                       WHERE vault_id = %s""",
                    (vault_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return ctx
        pref, chat, ui, mem = row
        if pref and pref in SUPPORTED_LOCALES:
            ctx["preferred_locale"] = pref
        if chat and chat in SUPPORTED_LOCALES:
            ctx["chat_language"] = chat
        if ui and ui in SUPPORTED_LOCALES:
            ctx["ui_language"] = ui
        if mem and mem in SUPPORTED_LOCALES:
            ctx["memory_language"] = mem
    except Exception as e:
        logger.warning("build_language_context failed vault=%s: %s", vault_id, e)
    return ctx


def preserve_user_language(text: Optional[str]) -> str:


    if not text:
        return ""
    try:
        s = " ".join(text.split())
        return s
    except Exception:
        return text or ""


def normalize_for_cluster(text: Optional[str]) -> str:


    if not text:
        return ""
    try:
        decomp = unicodedata.normalize("NFKD", text)
        no_marks = "".join(
            ch for ch in decomp
            if not unicodedata.combining(ch)
        )
        folded = no_marks.casefold().strip()
                                                                 
                                      
        slug = re.sub(r"[\s\-]+", "_", folded)
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug[:200]
    except Exception:
        return ""


__all__ = [
    "detect_language",
    "detect_mixed_language",
    "detect_script",
    "normalize_query",
    "normalize_for_cluster",
    "choose_reply_language",
    "build_language_context",
    "preserve_user_language",
]
