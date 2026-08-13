"""Backend FAQ localization policy.

Privacy-sensitive translations are intentionally disabled until reviewed.
Every locale therefore receives the canonical English conversational FAQ.
"""

from __future__ import annotations

from typing import Any, Optional

from vault_faq_content import FAQ_BY_ID, FAQ_CATEGORY_LABELS

SUPPORTED_FAQ_LOCALES = ("en", "ar", "fr", "es", "ja", "ko", "zh")
FAQ_TRANSLATIONS: dict[str, dict[str, dict[str, str]]] = {}
FAQ_CATEGORY_LABELS_I18N = {"en": dict(FAQ_CATEGORY_LABELS)}


def get_localized_faq(
    faq_id: str, locale: Optional[str],
) -> Optional[dict[str, str]]:
    """Return canonical English until translated privacy copy is reviewed."""
    del locale
    entry = FAQ_BY_ID.get(faq_id)
    if entry is None:
        return None
    return {"question": entry["question"], "answer": entry["answer"]}


def get_localized_category_label(
    category_id: str, locale: Optional[str],
) -> str:
    del locale
    return FAQ_CATEGORY_LABELS.get(category_id, category_id)


def apply_locale_to_faq_envelope(
    envelope: Optional[dict[str, Any]], locale: Optional[str],
) -> Optional[dict[str, Any]]:
    if not isinstance(envelope, dict):
        return envelope
    card = envelope.get("card")
    if not isinstance(card, dict):
        return envelope
    if card.pop("preserveDynamicCopy", False) is True:
        envelope["message"] = str(card.get("answer") or envelope.get("message") or "")
        envelope["locale"] = "en"
        return envelope
    localized = get_localized_faq(card.get("faqId", ""), locale)
    if localized is None:
        return envelope
    card.update(localized)
    envelope["message"] = localized["answer"]
    category = card.get("category", "")
    card["categoryLabel"] = get_localized_category_label(category, locale)
    # Report the language actually served rather than implying a translation.
    envelope["locale"] = "en"
    return envelope


__all__ = [
    "SUPPORTED_FAQ_LOCALES", "FAQ_CATEGORY_LABELS_I18N",
    "FAQ_TRANSLATIONS", "get_localized_faq",
    "get_localized_category_label", "apply_locale_to_faq_envelope",
]
