

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

from vault_core import get_db
                                                                      
                                                                  
from taxonomy import (
    ALLOWED_DOC_TYPES as _TAXONOMY_ALLOWED_DOC_TYPES,
    ALLOWED_KEYS_BY_DOC_TYPE as _TAXONOMY_ALLOWED_KEYS_BY_DOC_TYPE,
    DOC_TYPE_TO_ASSET_TYPE as _TAXONOMY_DOC_TYPE_TO_ASSET_TYPE,
    NAMING_TEXT_TO_DOC_TYPE as _TAXONOMY_NAMING_TEXT_TO_DOC_TYPE,
)

                                                                      
if TYPE_CHECKING:
    from locales.base import Locale as _Locale


logger = logging.getLogger(__name__)


TEXT_INSPECT_BYTES = 2048

                                                                    
METADATA_JSON_MAX_BYTES = 4096


ALLOWED_DOC_TYPES = _TAXONOMY_ALLOWED_DOC_TYPES
ALLOWED_KEYS_BY_TYPE = _TAXONOMY_ALLOWED_KEYS_BY_DOC_TYPE


DOC_TYPE_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("boarding_pass",   ("boarding pass", "boarding-pass")),
    ("hotel_itinerary", ("hotel reservation", "hotel booking",
                         "reservation confirmation",
                         "booking confirmation", "hotel itinerary")),
    ("passport",        ("passport",)),
    ("driver_license",  ("driver license", "driver's license",
                         "driving licence", "driving license")),
    ("id_card",         ("national id", "id card", "identity card")),
    ("visa",            ("visa", "schengen")),
    ("tax_document",    ("tax return", "w-2", "w2 form", "1099", "irs")),
    ("invoice",         ("invoice", "bill to")),
    ("receipt",         ("receipt",)),
    ("insurance",       ("insurance policy", "insurer", "policy number")),
    ("contract",        ("contract", "this contract")),
    ("agreement",       ("agreement", "nda", "non-disclosure")),
    ("degree",          ("degree", "diploma", "bachelor of",
                         "master of", "doctorate")),
    ("certificate",     ("certificate", "certifies that",
                         "this is to certify")),
    ("medical_record",  ("medical record", "patient", "diagnosis",
                         "prescription")),
    ("ticket",          ("event ticket", "concert ticket", "ticket")),
]


def classify_doc_type(haystack: str, locale: "Optional[_Locale]" = None) -> Optional[str]:


    h = haystack.lower()
    best: Optional[str] = None
    best_len = 0
    rules = locale.doc_type_rules if locale else DOC_TYPE_RULES
    for doc_type, phrases in rules:
        for phrase in phrases:
                                                                
                                                                     
            if phrase.lower() in h and len(phrase) > best_len:
                best, best_len = doc_type, len(phrase)
    return best


def classify_naming_text_doc_type(text: Optional[str]) -> Optional[str]:


    if not text:
        return None
    h = text.lower()
    best: Optional[str] = None
    best_len = 0
    for doc_type, phrases in _TAXONOMY_NAMING_TEXT_TO_DOC_TYPE:
        for phrase in phrases:
                                                                      
                                                                   
            pat = r"\b" + re.escape(phrase.lower()) + r"\b"
            if re.search(pat, h) and len(phrase) > best_len:
                best, best_len = doc_type, len(phrase)
    return best


_COUNTRY_NAMES: tuple[str, ...] = (
    "afghanistan", "albania", "algeria", "argentina", "armenia",
    "australia", "austria", "azerbaijan", "bahamas", "bahrain",
    "bangladesh", "belarus", "belgium", "belize", "benin", "bhutan",
    "bolivia", "bosnia", "botswana", "brazil", "brunei", "bulgaria",
    "burkina faso", "burundi", "cambodia", "cameroon", "canada",
    "chad", "chile", "china", "colombia", "congo", "costa rica",
    "croatia", "cuba", "cyprus", "czech republic", "czechia",
    "denmark", "djibouti", "dominican republic", "ecuador", "egypt",
    "el salvador", "estonia", "ethiopia", "fiji", "finland", "france",
    "gabon", "gambia", "georgia", "germany", "ghana", "greece",
    "guatemala", "guinea", "haiti", "honduras", "hong kong",
    "hungary", "iceland", "india", "indonesia", "iran", "iraq",
    "ireland", "israel", "italy", "ivory coast", "jamaica", "japan",
    "jordan", "kazakhstan", "kenya", "kuwait", "kyrgyzstan", "laos",
    "latvia", "lebanon", "lesotho", "liberia", "libya", "lithuania",
    "luxembourg", "malaysia", "maldives", "mali", "malta", "mauritius",
    "mexico", "moldova", "monaco", "mongolia", "montenegro", "morocco",
    "mozambique", "myanmar", "namibia", "nepal", "netherlands",
    "new zealand", "nicaragua", "niger", "nigeria", "north korea",
    "north macedonia", "norway", "oman", "pakistan", "palestine",
    "panama", "papua new guinea", "paraguay", "peru", "philippines",
    "poland", "portugal", "qatar", "romania", "russia", "rwanda",
    "saudi arabia", "senegal", "serbia", "seychelles", "sierra leone",
    "singapore", "slovakia", "slovenia", "somalia", "south africa",
    "south korea", "south sudan", "spain", "sri lanka", "sudan",
    "suriname", "sweden", "switzerland", "syria", "taiwan",
    "tajikistan", "tanzania", "thailand", "togo", "trinidad",
    "tunisia", "turkey", "turkmenistan", "uganda", "ukraine",
    "united arab emirates", "uae", "united kingdom", "uk",
    "united states", "usa", "uruguay", "uzbekistan", "venezuela",
    "vietnam", "yemen", "zambia", "zimbabwe",
)


def _match_country(text: str, locale: "Optional[_Locale]" = None) -> dict:


    t = text.lower()
    names = locale.country_names if locale else _COUNTRY_NAMES
    canon_map = locale.country_short_canon if locale else {
        "uk": "United Kingdom", "usa": "United States",
        "uae": "United Arab Emirates",
    }
    best: Optional[str] = None
    best_len = 0
    for name in names:
        i = t.find(name)
        while i != -1:
            before_ok = (i == 0) or not t[i - 1].isalnum()
            after_idx = i + len(name)
            after_ok = (after_idx == len(t)) or not t[after_idx].isalnum()
            if before_ok and after_ok and len(name) > best_len:
                best, best_len = name, len(name)
                break
            i = t.find(name, i + 1)
    if not best:
        return {}
    canon = canon_map.get(best) or best.title()
    return {"country": canon}


_DATE_RE_ISO = re.compile(r"\b(20\d{2}|19\d{2})-(\d{1,2})-(\d{1,2})\b")
_DATE_RE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2}|19\d{2})\b")
_DATE_RE_WORDS_DMY = re.compile(
    r"\b(\d{1,2})\s+"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+"
    r"(20\d{2}|19\d{2})\b",
    re.IGNORECASE,
)
_DATE_RE_WORDS_MDY = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+"
    r"(\d{1,2}),?\s+(20\d{2}|19\d{2})\b",
    re.IGNORECASE,
)
_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _valid_date(y: int, m: int, d: int) -> bool:
    if not (1900 <= y <= 2100):
        return False
    if not (1 <= m <= 12):
        return False
    if not (1 <= d <= 31):
        return False
    return True


def _match_any_date(text: str) -> Optional[str]:

    m = _DATE_RE_ISO.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_date(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _DATE_RE_WORDS_DMY.search(text)
    if m:
        d = int(m.group(1))
        mo = _MONTH_MAP[m.group(2).lower()[:3]]
        y = int(m.group(3))
        if _valid_date(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _DATE_RE_WORDS_MDY.search(text)
    if m:
        mo = _MONTH_MAP[m.group(1).lower()[:3]]
        d = int(m.group(2))
        y = int(m.group(3))
        if _valid_date(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _DATE_RE_SLASH.search(text)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                                                                        
                                                                
        if a > 12:
            mo, d = b, a
        elif b > 12:
            mo, d = a, b
        else:
            mo, d = b, a
        if _valid_date(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def _match_date_near(text: str, *anchors: str) -> Optional[str]:


    lower = text.lower()
    for anchor in anchors:
        pos = lower.find(anchor)
        while pos != -1:
            window = text[max(0, pos - 5):pos + 80]
            d = _match_any_date(window)
            if d:
                return d
            pos = lower.find(anchor, pos + 1)
    return None


_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
_AMOUNT_SYMBOL_RE = re.compile(r"([$€£¥])\s?(\d{1,3}(?:[,]\d{3})*(?:\.\d{1,2})?)")
_AMOUNT_CODE_RE = re.compile(
    r"\b(USD|EUR|GBP|JPY|CHF|AUD|CAD|NGN|AED|QAR|INR|CNY|HKD|SGD)"
    r"\s+(\d{1,3}(?:[,]\d{3})*(?:\.\d{1,2})?)\b"
)


def _match_amount_currency(text: str) -> Optional[tuple[str, str]]:
    m = _AMOUNT_SYMBOL_RE.search(text)
    if m:
        return m.group(2).replace(",", ""), _CURRENCY_SYMBOLS[m.group(1)]
    m = _AMOUNT_CODE_RE.search(text)
    if m:
        return m.group(2).replace(",", ""), m.group(1).upper()
    return None


_PASSPORT_NUM_RE = re.compile(
    r"(?:passport\s*(?:no\.?|number|#)\s*[:#\-]?\s*)([A-Z0-9]{6,9})",
    re.IGNORECASE,
)
_ID_NUM_RE = re.compile(
    r"(?:(?:national\s+id|id\s*(?:no\.?|number|#))\s*[:#\-]?\s*)"
    r"([A-Z0-9]{6,12})",
    re.IGNORECASE,
)
_LICENSE_NUM_RE = re.compile(
    r"(?:(?:license|licence)\s*(?:no\.?|number|#)\s*[:#\-]?\s*)"
    r"([A-Z0-9]{5,12})",
    re.IGNORECASE,
)
_POLICY_NUM_RE = re.compile(
    r"(?:policy\s*(?:no\.?|number|#)\s*[:#\-]?\s*)([A-Z0-9\-]{4,18})",
    re.IGNORECASE,
)
_FLIGHT_NUM_RE = re.compile(r"\b([A-Z]{2,3})\s?(\d{2,4})\b")
_INVOICE_NUM_RE = re.compile(
    r"(?:invoice\s*(?:no\.?|number|#)\s*[:#\-]?\s*)([A-Z0-9\-]{3,20})",
    re.IGNORECASE,
)
_TAX_YEAR_RE = re.compile(r"\b(?:tax\s*year\s*[:#\-]?\s*)?(20\d{2}|19\d{2})\b")


import functools as _functools


@_functools.lru_cache(maxsize=64)
def _label_regex(labels_tuple, min_len=4, max_len=20):


    if not labels_tuple:
        return None
    alt = "|".join(re.escape(L) for L in labels_tuple)
    return re.compile(
        rf"(?:{alt})\s*[:#\-]?\s*([A-Z0-9\-]{{{min_len},{max_len}}})",
        re.IGNORECASE,
    )


def _is_english(locale) -> bool:

    return locale is None or getattr(locale, "locale_id", "en") == "en"


def _extract_passport(text: str, locale: "Optional[_Locale]" = None) -> dict:


    out: dict = {}
    out.update(_match_country(text, locale))
    if _is_english(locale):
        pn = _PASSPORT_NUM_RE.search(text)
    else:
        rx = _label_regex(tuple(locale.passport_num_labels), 6, 9)
        pn = rx.search(text) if rx else None
    if pn:
        raw = pn.group(1).upper()
        if len(raw) >= 4:
            out["passport_number_last4"] = raw[-4:]
    expiry_anchors = locale.expiry_anchors if locale else (
        "expir", "valid until", "valid till", "date of expiry",
    )
    issue_anchors = locale.issue_anchors if locale else (
        "issue", "issued", "date of issue",
    )
    expiry = _match_date_near(text, *expiry_anchors)
    if expiry:
        out["expiry_date"] = expiry
    issue = _match_date_near(text, *issue_anchors)
    if issue:
        out["issue_date"] = issue
    return out


def _extract_visa(text: str, locale: "Optional[_Locale]" = None) -> dict:

    out: dict = {}
    out.update(_match_country(text, locale))
    expiry_anchors = locale.expiry_anchors if locale else (
        "expir", "valid until", "valid till",
    )
    expiry = _match_date_near(text, *expiry_anchors)
    if expiry:
        out["expiry_date"] = expiry
    t = text.lower()
    if "multiple entry" in t or "multiple entries" in t:
        out["entry_type"] = "multiple"
    elif "single entry" in t:
        out["entry_type"] = "single"
    return out


def _extract_boarding_pass(text: str, locale: "Optional[_Locale]" = None) -> dict:


    out: dict = {}
    fm = _FLIGHT_NUM_RE.search(text)
    if fm:
        out["airline"] = fm.group(1)
        out["flight_number"] = f"{fm.group(1)}{fm.group(2)}"
    boarding_anchors = locale.boarding_anchors if locale else (
        "departure", "depart", "boarding",
    )
    dep = _match_date_near(text, *boarding_anchors)
    if dep:
        out["departure_date"] = dep
    m = re.search(r"from\s+([A-Z]{3})\s+to\s+([A-Z]{3})", text, re.IGNORECASE)
    if m:
        out["origin"] = m.group(1).upper()
        out["destination"] = m.group(2).upper()
    return out


def _extract_ticket(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    d = _match_any_date(text)
    if d:
        out["event_date"] = d
    return out


def _extract_hotel_itinerary(text: str, locale: "Optional[_Locale]" = None) -> dict:

    out: dict = {}
    check_in_anchors = locale.check_in_anchors if locale else (
        "check-in", "check in", "checkin", "arrival",
    )
    check_out_anchors = locale.check_out_anchors if locale else (
        "check-out", "check out", "checkout", "departure",
    )
    check_in = _match_date_near(text, *check_in_anchors)
    if check_in:
        out["check_in"] = check_in
    check_out = _match_date_near(text, *check_out_anchors)
    if check_out:
        out["check_out"] = check_out
    return out


def _extract_receipt(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    amt = _match_amount_currency(text)
    if amt:
        out["amount"], out["currency"] = amt
    purchase_anchors = locale.purchase_anchors if locale else (
        "date", "purchased", "paid", "purchase",
    )
    purchased = _match_date_near(text, *purchase_anchors)
    if purchased:
        out["purchase_date"] = purchased
    elif (d := _match_any_date(text)):
        out["purchase_date"] = d
    return out


def _extract_invoice(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    amt = _match_amount_currency(text)
    if amt:
        out["amount"], out["currency"] = amt
    due_anchors = locale.due_anchors if locale else ("due", "payment due")
    due = _match_date_near(text, *due_anchors)
    if due:
        out["due_date"] = due
    if _is_english(locale):
        inv = _INVOICE_NUM_RE.search(text)
    else:
        rx = _label_regex(tuple(locale.invoice_num_labels), 3, 20)
        inv = rx.search(text) if rx else None
    if inv:
        out["invoice_number"] = inv.group(1).upper()[:20]
    return out


def _extract_contract(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    effective_anchors = locale.effective_anchors if locale else (
        "effective", "commences", "commencement", "effective date",
    )
    renewal_anchors = locale.renewal_anchors if locale else (
        "renewal", "renews", "expir", "expires",
    )
    effective = _match_date_near(text, *effective_anchors)
    if effective:
        out["effective_date"] = effective
    renewal = _match_date_near(text, *renewal_anchors)
    if renewal:
        out["renewal_date"] = renewal
    parties_match = re.search(
        r"between\s+([A-Z][^,\n]{1,60})\s+and\s+([A-Z][^,\n]{1,60})",
        text,
    )
    if parties_match:
        out["parties"] = [
            parties_match.group(1).strip(),
            parties_match.group(2).strip(),
        ][:5]
    return out


def _extract_agreement(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    effective_anchors = locale.effective_anchors if locale else (
        "effective", "dated", "commences",
    )
    effective = _match_date_near(text, *effective_anchors)
    if effective:
        out["effective_date"] = effective
    parties_match = re.search(
        r"between\s+([A-Z][^,\n]{1,60})\s+and\s+([A-Z][^,\n]{1,60})",
        text,
    )
    if parties_match:
        out["parties"] = [
            parties_match.group(1).strip(),
            parties_match.group(2).strip(),
        ][:5]
    return out


def _extract_degree(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
                                                                      
                                                                       
    y = re.search(r"(?<!\d)(20\d{2}|19\d{2})(?!\d)", text)
    if y:
        out["year"] = y.group(1)
    field_phrases = locale.education_field_phrases if locale else (
        "computer science", "engineering", "mathematics",
        "physics", "business", "law", "medicine", "biology",
        "chemistry", "economics",
    )
    text_lower = text.lower()
    for field_kw in field_phrases:
        if field_kw.lower() in text_lower:
                                                                     
                                                      
            out["field"] = field_kw.title()
            break
    return out


def _extract_certificate(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    issue_anchors = locale.issue_anchors if locale else (
        "issued", "issue", "awarded",
    )
    expiry_anchors = locale.expiry_anchors if locale else (
        "expir", "valid until", "valid till",
    )
    issued = _match_date_near(text, *issue_anchors)
    if issued:
        out["issue_date"] = issued
    expiry = _match_date_near(text, *expiry_anchors)
    if expiry:
        out["expiry_date"] = expiry
    return out


def _extract_insurance(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    if _is_english(locale):
        pn = _POLICY_NUM_RE.search(text)
    else:
        rx = _label_regex(tuple(locale.policy_num_labels), 4, 18)
        pn = rx.search(text) if rx else None
    if pn:
        raw = pn.group(1).upper()
        if len(raw) >= 4:
            out["policy_number_last4"] = raw[-4:]
                                                                 
                                                                     
    expiry_anchors = locale.expiry_anchors if locale else (
        "expir", "valid until", "valid till", "date of expiry",
    )
    renewal_anchors = locale.renewal_anchors if locale else (
        "renewal", "renews",
    )
    expiry = _match_date_near(text, *expiry_anchors, *renewal_anchors)
    if expiry:
        out["expiry_date"] = expiry
    return out


def _extract_driver_license(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    out.update(_match_country(text, locale))
    if _is_english(locale):
        ln = _LICENSE_NUM_RE.search(text)
    else:
        rx = _label_regex(tuple(locale.license_num_labels), 5, 12)
        ln = rx.search(text) if rx else None
    if ln:
        raw = ln.group(1).upper()
        if len(raw) >= 4:
            out["license_number_last4"] = raw[-4:]
    expiry_anchors = locale.expiry_anchors if locale else (
        "expir", "valid until",
    )
    expiry = _match_date_near(text, *expiry_anchors)
    if expiry:
        out["expiry_date"] = expiry
    cls = re.search(r"class\s*[:#]?\s*([A-Z0-9]{1,4})", text, re.IGNORECASE)
    if cls:
        out["license_class"] = cls.group(1).upper()
    return out


def _extract_id_card(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    out.update(_match_country(text, locale))
    if _is_english(locale):
        idn = _ID_NUM_RE.search(text)
    else:
        rx = _label_regex(tuple(locale.id_num_labels), 6, 12)
        idn = rx.search(text) if rx else None
    if idn:
        raw = idn.group(1).upper()
        if len(raw) >= 4:
            out["id_number_last4"] = raw[-4:]
    expiry_anchors = locale.expiry_anchors if locale else (
        "expir", "valid until",
    )
    expiry = _match_date_near(text, *expiry_anchors)
    if expiry:
        out["expiry_date"] = expiry
    return out


def _extract_tax_document(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    out.update(_match_country(text, locale))
    y = _TAX_YEAR_RE.search(text)
    if y:
        out["tax_year"] = y.group(1)
    text_lower = text.lower()
                                                                     
                                                                                
    keywords = locale.tax_form_keywords if locale else {
        "1099": "1099", "w-2": "W2", "w2": "W2", "tax return": "RETURN",
    }
    for kw, form_type in keywords.items():
        if kw.lower() in text_lower:
            out["form_type"] = form_type
            break
    return out


def _extract_medical_record(text: str, locale: "Optional[_Locale]" = None) -> dict:
    out: dict = {}
    d = _match_any_date(text)
    if d:
        out["record_date"] = d
    t = text.lower()
    if "prescription" in t:
        out["record_type"] = "prescription"
    elif "lab" in t or "blood test" in t:
        out["record_type"] = "lab"
    elif "diagnosis" in t:
        out["record_type"] = "diagnosis"
    return out


EXTRACTOR_BY_TYPE = {
    "passport":        _extract_passport,
    "visa":            _extract_visa,
    "boarding_pass":   _extract_boarding_pass,
    "ticket":          _extract_ticket,
    "hotel_itinerary": _extract_hotel_itinerary,
    "receipt":         _extract_receipt,
    "invoice":         _extract_invoice,
    "contract":        _extract_contract,
    "agreement":       _extract_agreement,
    "degree":          _extract_degree,
    "certificate":     _extract_certificate,
    "insurance":       _extract_insurance,
    "driver_license":  _extract_driver_license,
    "id_card":         _extract_id_card,
    "tax_document":    _extract_tax_document,
    "medical_record":  _extract_medical_record,
}


@dataclass(frozen=True)
class LocaleAdapter:


    locale_id: str
                                                                           
    doc_type_rules: tuple[tuple[str, tuple[str, ...]], ...]
    country_names: tuple[str, ...]
    month_map: dict[str, int]
                                                       
    expiry_anchors:    tuple[str, ...]
    issue_anchors:     tuple[str, ...]
    due_anchors:       tuple[str, ...]
    boarding_anchors:  tuple[str, ...]
    check_in_anchors:  tuple[str, ...]
    check_out_anchors: tuple[str, ...]
    purchase_anchors:  tuple[str, ...]
                                                                      
    passport_num_labels: tuple[str, ...]
    id_num_labels:       tuple[str, ...]
    license_num_labels:  tuple[str, ...]
    policy_num_labels:   tuple[str, ...]
                                       
    education_field_phrases: tuple[str, ...]
                                                         
    tax_form_keywords: dict[str, str]


ENGLISH_LOCALE = LocaleAdapter(
    locale_id="en",
    doc_type_rules=tuple(DOC_TYPE_RULES),
    country_names=_COUNTRY_NAMES,
    month_map=_MONTH_MAP,
    expiry_anchors=(
        "expir", "valid until", "valid till", "date of expiry",
    ),
    issue_anchors=("issue", "issued", "date of issue"),
    due_anchors=("due", "payment due"),
    boarding_anchors=("departure", "depart", "boarding"),
    check_in_anchors=("check-in", "check in", "checkin", "arrival"),
    check_out_anchors=("check-out", "check out", "checkout", "departure"),
    purchase_anchors=("date", "purchased", "paid", "purchase"),
    passport_num_labels=("passport no", "passport number"),
    id_num_labels=("national id", "id no", "id number"),
    license_num_labels=(
        "license no", "license number", "licence number", "licence no",
    ),
    policy_num_labels=("policy no", "policy number"),
    education_field_phrases=(
        "computer science", "engineering", "mathematics", "physics",
        "business", "law", "medicine", "biology", "chemistry",
        "economics",
    ),
                                                                  
                                                                       
    tax_form_keywords={
        "1099": "1099", "w-2": "W2", "w2": "W2", "tax return": "RETURN",
    },
)


_LOCALES: dict[str, LocaleAdapter] = {"en": ENGLISH_LOCALE}


def get_locale(locale_id: Optional[str] = None) -> LocaleAdapter:


    if locale_id and locale_id in _LOCALES:
        return _LOCALES[locale_id]
    return ENGLISH_LOCALE


def is_enabled() -> bool:

    return os.getenv("VAULTAI_DOCUMENT_UNDERSTANDING_ENABLED",
                     "true").lower() == "true"


def understand_document(
    *,
    file_name: Optional[str] = None,
    saved_name: Optional[str] = None,
    asset_type: Optional[str] = None,
    content_type: Optional[str] = None,
    detected_service: Optional[str] = None,
    extracted_text: Optional[str] = None,
    extracted_text_encrypted: bool = False,
    locale: "Optional[_Locale]" = None,
    user_locale: str = "en",
) -> Optional[dict]:


    text2k = ""
    if extracted_text and not extracted_text_encrypted:
        text2k = extracted_text[:TEXT_INSPECT_BYTES]
    haystack_parts = [p for p in (file_name, saved_name, detected_service,
                                  text2k) if p]
    haystack = " ".join(haystack_parts)
    if not haystack.strip():
        return None

                                                        
    if locale is None:
        try:
            from locales import get_locale, detect_document_locale
            detected_id = detect_document_locale(haystack, user_locale=user_locale)
            locale = get_locale(detected_id)
        except Exception:
            locale = None                                              

    doc_type = classify_doc_type(haystack, locale)
    if not doc_type:
        return None

    extractor = EXTRACTOR_BY_TYPE.get(doc_type)
    raw = extractor(haystack, locale) if extractor else {}

    allowed = ALLOWED_KEYS_BY_TYPE.get(doc_type, frozenset())
    metadata: dict = {}
    for k, v in raw.items():
        if k not in allowed:
            continue
        if v in (None, "", []):
            continue
        metadata[k] = v

    if not metadata:
                                                    
        return None

    expected = max(1, len(allowed))
    confidence = max(0.0, min(len(metadata) / expected, 1.0))
    return {"doc_type": doc_type, "metadata": metadata,
            "confidence": confidence}


def _refresh_asset_type_after_doc_extract(
    vault_id: str, file_id: str, *,
    doc_type: str, content_type: Optional[str],
) -> None:


    if doc_type not in _TAXONOMY_DOC_TYPE_TO_ASSET_TYPE:
        return
    if (content_type or "").lower().startswith("image/"):
        new_asset_type = "id_image"
    else:
        new_asset_type = _TAXONOMY_DOC_TYPE_TO_ASSET_TYPE[doc_type]
    try:
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE uploaded_files
                       SET asset_type = %s
                       WHERE id = %s AND vault_id = %s""",
                    (new_asset_type, file_id, vault_id),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "_refresh_asset_type_after_doc_extract failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )


def extract_and_store_document_safe(
    vault_id: str,
    file_id: str,
    *,
    file_name: Optional[str] = None,
    saved_name: Optional[str] = None,
    asset_type: Optional[str] = None,
    content_type: Optional[str] = None,
    detected_service: Optional[str] = None,
    extracted_text: Optional[str] = None,
    extracted_text_encrypted: bool = False,
    replace: bool = False,
    locale: "Optional[_Locale]" = None,
    user_locale: Optional[str] = None,
) -> None:


    try:
        if not is_enabled():
            return
                                                                   
                                                                       
        _user_locale = user_locale
        if _user_locale is None:
            try:
                from locales import get_vault_locale_id
                _user_locale = get_vault_locale_id(vault_id)
            except Exception:
                _user_locale = "en"
        result = understand_document(
            file_name=file_name,
            saved_name=saved_name,
            asset_type=asset_type,
            content_type=content_type,
            detected_service=detected_service,
            extracted_text=extracted_text,
            extracted_text_encrypted=extracted_text_encrypted,
            locale=locale,
            user_locale=_user_locale or "en",
        )
        if not result and not replace:
            return
        conn = get_db()
        try:
            with conn.cursor() as cur:
                if replace:
                    cur.execute(
                        """DELETE FROM vault_document_metadata
                           WHERE vault_id=%s AND uploaded_file_id=%s""",
                        (vault_id, file_id),
                    )
                if result:
                    payload = json.dumps(result["metadata"])
                    if len(payload.encode("utf-8")) > METADATA_JSON_MAX_BYTES:
                                                                       
                                                     
                        return
                    cur.execute(
                        """
                        INSERT INTO vault_document_metadata
                            (vault_id, uploaded_file_id,
                             doc_type, metadata_json, confidence)
                        VALUES (%s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (vault_id, uploaded_file_id) DO UPDATE SET
                            doc_type      = EXCLUDED.doc_type,
                            metadata_json = EXCLUDED.metadata_json,
                            confidence    = EXCLUDED.confidence,
                            updated_at    = NOW()
                        """,
                        (vault_id, file_id,
                         result["doc_type"], payload, result["confidence"]),
                    )
            conn.commit()
        finally:
            conn.close()

                                                                 
        if result:
            try:
                from asset_tagger import tag_uploaded_file_safe
                tag_uploaded_file_safe(
                    vault_id, file_id,
                    file_name=file_name,
                    saved_name=saved_name,
                    asset_type=asset_type,
                    content_type=content_type,
                    detected_service=detected_service,
                    doc_type=result["doc_type"],
                    doc_metadata=result["metadata"],
                    replace=True,
                )
            except Exception:
                pass

                                                                      
            _refresh_asset_type_after_doc_extract(
                vault_id, file_id,
                doc_type=result["doc_type"],
                content_type=content_type,
            )
    except Exception as e:
        logger.warning(
            "extract_and_store_document_safe failed vault=%s file=%s: %s",
            vault_id, file_id, e,
        )
