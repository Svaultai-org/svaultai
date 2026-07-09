

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


DEVICE_INTENT_LIST_ALL:       str = "list_all"
DEVICE_INTENT_FILTER_KIND:    str = "filter_kind"
DEVICE_INTENT_FILTER_BRAND:   str = "filter_brand"
DEVICE_INTENT_FILTER_MISSING_RECEIPT: str = "filter_missing_receipt"
DEVICE_INTENT_STOLEN:         str = "stolen_or_lost"
DEVICE_INTENT_REVEAL_FIELD:   str = "reveal_field"
DEVICE_INTENT_NONE:           str = "none"


ALL_DEVICE_INTENTS: tuple[str, ...] = (
    DEVICE_INTENT_LIST_ALL,
    DEVICE_INTENT_FILTER_KIND,
    DEVICE_INTENT_FILTER_BRAND,
    DEVICE_INTENT_FILTER_MISSING_RECEIPT,
    DEVICE_INTENT_STOLEN,
    DEVICE_INTENT_REVEAL_FIELD,
    DEVICE_INTENT_NONE,
)


_KIND_KEYWORDS: dict[str, str] = {
    "phone": "phone", "phones": "phone",
    "iphone": "phone", "iphones": "phone",
    "android": "phone", "androids": "phone",
    "smartphone": "phone", "smartphones": "phone",
    "mobile": "phone", "mobiles": "phone",
    "laptop": "laptop", "laptops": "laptop",
    "pc": "laptop", "pcs": "laptop",
    "macbook": "laptop", "macbooks": "laptop",
    "computer": "laptop", "computers": "laptop",
    "notebook": "laptop", "notebooks": "laptop",
    "tablet": "tablet", "tablets": "tablet",
    "ipad": "tablet", "ipads": "tablet",
}


_BRAND_KEYWORDS: frozenset[str] = frozenset({
    "apple", "samsung", "google", "pixel", "oneplus", "xiaomi",
    "huawei", "sony", "lg", "motorola", "nokia",
    "dell", "lenovo", "hp", "asus", "acer", "msi",
    "razer", "framework", "thinkpad",
    "microsoft", "surface",
})


_STOLEN_KEYWORDS: tuple[str, ...] = (
    "stolen", "got stolen", "was stolen",
    "lost", "missing", "misplaced",
    "couldn't find", "can't find",
    "someone took", "got taken",
)


_LIST_ALL_PATTERNS: tuple[str, ...] = (
    r"\bshow\s+(?:me\s+)?(?:all\s+)?(?:my\s+)?devices?\b",
    r"\blist\s+(?:my\s+)?devices?\b",
    r"\bdevice\s+info\b",
    r"\bmy\s+device\s+info\b",
)


_MISSING_RECEIPT_PATTERNS: tuple[str, ...] = (
    r"\bdevices?\s+without\s+receipts?\b",
    r"\bwithout\s+(?:a\s+)?receipt\b",
    r"\bno\s+receipt\b",
    r"\bmissing\s+receipts?\b",
)


_FIND_RECEIPT_PATTERNS: tuple[str, ...] = (
    r"\bfind\s+(?:the\s+)?receipt\s+for\b",
    r"\bshow\s+(?:the\s+)?receipt\s+for\b",
    r"\breceipt\s+for\s+my\b",
)


_LIST_ALL_RE = [re.compile(p, re.IGNORECASE) for p in _LIST_ALL_PATTERNS]
_MISSING_RECEIPT_RE = [
    re.compile(p, re.IGNORECASE) for p in _MISSING_RECEIPT_PATTERNS
]
_FIND_RECEIPT_RE = [
    re.compile(p, re.IGNORECASE) for p in _FIND_RECEIPT_PATTERNS
]


@dataclass(frozen=True)
class DeviceQuery:

    intent:      str
    kind:        Optional[str] = None
    brand:       Optional[str] = None
    reveal_field: Optional[str] = None


def _extract_kind(message_lower: str) -> Optional[str]:


    tokens = re.findall(r"[a-z]+", message_lower)
    for tok in tokens:
        if tok in _KIND_KEYWORDS:
            return _KIND_KEYWORDS[tok]
    return None


def _extract_brand(message_lower: str) -> Optional[str]:
    tokens = re.findall(r"[a-z]+", message_lower)
    for tok in tokens:
        if tok in _BRAND_KEYWORDS:
            return tok
    return None


def _is_stolen_query(message_lower: str) -> bool:
    return any(kw in message_lower for kw in _STOLEN_KEYWORDS)


def classify_device_query(user_message: Optional[str]) -> DeviceQuery:


    if not user_message or not isinstance(user_message, str):
        return DeviceQuery(intent=DEVICE_INTENT_NONE)
    msg = user_message.strip()
    msg_low = msg.lower()

    if _is_stolen_query(msg_low):
        kind = _extract_kind(msg_low)
        return DeviceQuery(
            intent=DEVICE_INTENT_STOLEN,
            kind=kind,
        )

                                              
    try:
        from vault_device_reveal_gate import reveal_target_field
        label = reveal_target_field(msg)
    except Exception:
        label = None
    if label is not None:
        return DeviceQuery(
            intent=DEVICE_INTENT_REVEAL_FIELD,
            reveal_field=label,
            kind=_extract_kind(msg_low),
            brand=_extract_brand(msg_low),
        )

    if any(p.search(msg) for p in _MISSING_RECEIPT_RE):
        return DeviceQuery(
            intent=DEVICE_INTENT_FILTER_MISSING_RECEIPT,
            kind=_extract_kind(msg_low),
        )

    if any(p.search(msg) for p in _FIND_RECEIPT_RE):
        return DeviceQuery(
            intent=DEVICE_INTENT_FILTER_KIND,
            kind=_extract_kind(msg_low) or "phone",
        )

    brand = _extract_brand(msg_low)
    kind = _extract_kind(msg_low)
    if brand is not None:
        return DeviceQuery(
            intent=DEVICE_INTENT_FILTER_BRAND,
            brand=brand, kind=kind,
        )
    if kind is not None:
        return DeviceQuery(
            intent=DEVICE_INTENT_FILTER_KIND,
            kind=kind,
        )

    if any(p.search(msg) for p in _LIST_ALL_RE):
        return DeviceQuery(intent=DEVICE_INTENT_LIST_ALL)

    return DeviceQuery(intent=DEVICE_INTENT_NONE)


def apply_device_query(
    *,
    devices: list[dict],
    query: DeviceQuery,
) -> list[dict]:


    if query.intent in (DEVICE_INTENT_NONE, DEVICE_INTENT_REVEAL_FIELD):
        return devices
    out: list[dict] = []
    for d in devices or []:
        if not isinstance(d, dict):
            continue
        preview = d.get("preview") if isinstance(
            d.get("preview"), dict,
        ) else d
        kind = str(d.get("device_kind") or preview.get("device_kind") or "").lower()
        brand = str(preview.get("brand") or "").lower()
        has_receipt = bool(preview.get("has_receipt"))

        if query.kind and kind != query.kind:
            continue
        if query.brand and brand and brand != query.brand:
            continue
                                                           
                                                            
        if query.brand and not brand:
            continue
        if query.intent == DEVICE_INTENT_FILTER_MISSING_RECEIPT:
            if has_receipt:
                continue
        out.append(d)
    return out


__all__ = [
    "DEVICE_INTENT_LIST_ALL",
    "DEVICE_INTENT_FILTER_KIND",
    "DEVICE_INTENT_FILTER_BRAND",
    "DEVICE_INTENT_FILTER_MISSING_RECEIPT",
    "DEVICE_INTENT_STOLEN",
    "DEVICE_INTENT_REVEAL_FIELD",
    "DEVICE_INTENT_NONE",
    "ALL_DEVICE_INTENTS",
    "DeviceQuery",
    "classify_device_query",
    "apply_device_query",
]
