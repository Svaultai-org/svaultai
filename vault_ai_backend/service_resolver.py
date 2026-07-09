

from __future__ import annotations

import logging
import os
from typing import Optional

from vault_core import get_db
from taxonomy import SERVICE_CATEGORIES


logger = logging.getLogger(__name__)


UNKNOWN_CATEGORY = "unknown"


_ALLOWED_OUTPUTS: frozenset[str] = frozenset(SERVICE_CATEGORIES) | {UNKNOWN_CATEGORY}


_INPROC_CACHE: dict[tuple[str, str], str] = {}
_INPROC_CACHE_MAX = 1024


_SYSTEM_PROMPT = (
    "Classify the given service name into exactly one of these "
    "categories: bank, wallet, exchange, social, travel, commerce, "
    "media, government, business. "
    "If none fit, reply 'unknown'. "
    "Reply with one lowercase word only - no punctuation, no quotes, "
    "no explanation."
)


def _resolver_model() -> str:


    raw = os.getenv("VAULTAI_RESOLVER_MODEL", "").strip()
    if raw:
        return raw
    try:
        from vault_config import ai as _ai_cfg
        return _ai_cfg().intent_model
    except Exception:
        return "gpt-4o-mini"


def is_enabled() -> bool:


    return os.getenv(
        "VAULTAI_LLM_SERVICE_RESOLVER_ENABLED", "false",
    ).lower() == "true"


def _normalize(service_name: str) -> str:


    return (service_name or "").strip().lower()


def _normalize_locale(locale: Optional[str]) -> str:
    return (locale or "en").strip().lower() or "en"


def _cache_get(service_name: str, locale: str) -> Optional[str]:


    key = (service_name, locale)
    if key in _INPROC_CACHE:
        return _INPROC_CACHE[key]
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT category FROM vault_service_categories
                       WHERE service_name=%s AND locale=%s""",
                    (service_name, locale),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return None
        cat = row[0]
        if cat not in _ALLOWED_OUTPUTS:
                                                             
            return None
        if len(_INPROC_CACHE) < _INPROC_CACHE_MAX:
            _INPROC_CACHE[key] = cat
        return cat
    except Exception as e:
        logger.warning(
            "service_resolver._cache_get failed service=%s locale=%s: %s",
            service_name, locale, e,
        )
        return None


def _cache_put(
    service_name: str, locale: str, category: str,
    *, confidence: float, source: str,
) -> None:


    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO vault_service_categories
                            (service_name, locale, category, confidence,
                             source, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                       ON CONFLICT (service_name, locale) DO UPDATE SET
                            category   = EXCLUDED.category,
                            confidence = EXCLUDED.confidence,
                            source     = EXCLUDED.source,
                            updated_at = NOW()""",
                    (service_name, locale, category, confidence, source),
                )
            conn.commit()
        finally:
            conn.close()
        if len(_INPROC_CACHE) < _INPROC_CACHE_MAX:
            _INPROC_CACHE[(service_name, locale)] = category
    except Exception as e:
        logger.warning(
            "service_resolver._cache_put failed service=%s locale=%s: %s",
            service_name, locale, e,
        )


def _parse_llm_output(raw: Optional[str]) -> Optional[str]:


    if not raw:
        return None
    cleaned = raw.strip().strip(' .,"\'\n\t').lower()
    if " " in cleaned:
        cleaned = cleaned.split()[0]
    if cleaned in _ALLOWED_OUTPUTS:
        return cleaned
    return None


def _llm_classify(service_name: str, locale: str) -> Optional[str]:


    try:
                                                          
                                                              
        from vault_ai_provider import get_chat_client_sync
        client = get_chat_client_sync()
        resp = client.chat.completions.create(
            model=_resolver_model(),
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",
                 "content": f"Service: {service_name}\nLocale: {locale}"},
            ],
            temperature=0,
            max_tokens=6,
        )
        raw = resp.choices[0].message.content if resp.choices else None
        return _parse_llm_output(raw)
    except Exception as e:
        logger.warning(
            "service_resolver._llm_classify failed service=%s: %s",
            service_name, e,
        )
        return None


def resolve_service_category(
    service_name: Optional[str],
    user_locale: Optional[str] = "en",
) -> Optional[str]:


    try:
        norm = _normalize(service_name or "")
        if not norm:
            return None
        loc = _normalize_locale(user_locale)

                                             
        cached = _cache_get(norm, loc)
        if cached is not None:
            return cached if cached != UNKNOWN_CATEGORY else None

                                                                       
        if not is_enabled():
            return None

                               
        result = _llm_classify(norm, loc)
        if result is None:
            return None

                                                                
        _cache_put(norm, loc, result, confidence=1.0, source="llm")

        if result == UNKNOWN_CATEGORY:
            return None
        return result
    except Exception as e:
        logger.warning("resolve_service_category failed: %s", e)
        return None


def clear_inproc_cache() -> None:


    _INPROC_CACHE.clear()
