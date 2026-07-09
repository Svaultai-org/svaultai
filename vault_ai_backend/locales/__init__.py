

from __future__ import annotations

import logging
import os
from typing import Optional

from .base import Locale, LocaleFormatter
from .en import ENGLISH_LOCALE, ENGLISH_FORMATTER
from .ar import ARABIC_LOCALE, ARABIC_FORMATTER
from .fr import FRENCH_LOCALE, FRENCH_FORMATTER
from .es import SPANISH_LOCALE, SPANISH_FORMATTER
from .ja import JAPANESE_LOCALE, JAPANESE_FORMATTER
from .ko import KOREAN_LOCALE, KOREAN_FORMATTER
from .zh import CHINESE_LOCALE, CHINESE_FORMATTER
from .detect import detect_document_locale, detect_script


logger = logging.getLogger(__name__)


SUPPORTED_LOCALES: tuple[str, ...] = ("en", "ar", "fr", "es", "ja", "ko", "zh")


_REGISTRY: dict[str, tuple[Locale, LocaleFormatter]] = {
    "en": (ENGLISH_LOCALE,  ENGLISH_FORMATTER),
    "ar": (ARABIC_LOCALE,   ARABIC_FORMATTER),
    "fr": (FRENCH_LOCALE,   FRENCH_FORMATTER),
    "es": (SPANISH_LOCALE,  SPANISH_FORMATTER),
    "ja": (JAPANESE_LOCALE, JAPANESE_FORMATTER),
    "ko": (KOREAN_LOCALE,   KOREAN_FORMATTER),
    "zh": (CHINESE_LOCALE,  CHINESE_FORMATTER),
}


def _db_lookup_enabled() -> bool:


    return os.getenv("VAULTAI_USER_LOCALE_DB_LOOKUP", "true").lower() == "true"


def get_locale(locale_id: Optional[str]) -> Locale:


    if not locale_id:
        return ENGLISH_LOCALE
    entry = _REGISTRY.get(locale_id)
    if entry is None:
        return ENGLISH_LOCALE
    return entry[0]


def get_formatter(locale_id: Optional[str]) -> LocaleFormatter:


    if not locale_id:
        return ENGLISH_FORMATTER
    entry = _REGISTRY.get(locale_id)
    if entry is None:
        return ENGLISH_FORMATTER
    return entry[1]


def get_vault_locale_id(vault_id: str) -> str:


    if not _db_lookup_enabled():
        return "en"
    try:
        from vault_core import get_db                               
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT preferred_locale FROM vault_preferences
                       WHERE vault_id = %s""",
                    (vault_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return "en"
        loc = row[0]
        if loc not in SUPPORTED_LOCALES:
            return "en"
        return loc
    except Exception as e:
        logger.warning("get_vault_locale_id failed vault=%s: %s", vault_id, e)
        return "en"


def get_vault_formatter(vault_id: str) -> LocaleFormatter:


    return get_formatter(get_vault_locale_id(vault_id))


__all__ = [
    "Locale", "LocaleFormatter",
    "ENGLISH_LOCALE", "ENGLISH_FORMATTER",
    "ARABIC_LOCALE",  "ARABIC_FORMATTER",
    "FRENCH_LOCALE",  "FRENCH_FORMATTER",
    "SPANISH_LOCALE", "SPANISH_FORMATTER",
    "JAPANESE_LOCALE","JAPANESE_FORMATTER",
    "KOREAN_LOCALE",  "KOREAN_FORMATTER",
    "CHINESE_LOCALE", "CHINESE_FORMATTER",
    "SUPPORTED_LOCALES",
    "get_locale", "get_formatter",
    "get_vault_locale_id", "get_vault_formatter",
    "detect_document_locale", "detect_script",
]
