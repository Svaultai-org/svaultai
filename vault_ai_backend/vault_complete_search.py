

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Iterable, Optional


logger = logging.getLogger(__name__)


MAX_VISION_INSPECTIONS: int = int(
    os.getenv("VAULTAI_VISION_BUDGET", "6"),
)
                                                            
                                                              
ID_CLASS_VISION_BUDGET: int = int(
    os.getenv("VAULTAI_ID_CLASS_VISION_BUDGET", "50"),
)
MAX_TEXT_FILES_SCANNED: int = int(
    os.getenv("VAULTAI_TEXT_SCAN_BUDGET", "50"),
)
DEFAULT_FUZZY_DISTANCE: int = 2

                                                             
try:
    from vault_pdf_page_vision import (
        MAX_PDF_PAGES_PER_DOC,              
    )
except Exception:                                        
    MAX_PDF_PAGES_PER_DOC = 3

                                                            
EVIDENCE_EXTRACTED_TEXT:  str = "extracted_text"
EVIDENCE_IMAGE_VISION:    str = "image_vision"
EVIDENCE_PDF_PAGE_VISION: str = "pdf_page_vision"
EVIDENCE_OCR_TEXT:        str = "ocr_text"

                                                               
MATCH_EXACT_TEXT: str = "exact_text"
MATCH_FUZZY_TEXT: str = "fuzzy_text"
MATCH_VISION:     str = "vision"

                                           
DOC_TYPE_ID_PHOTO:          str = "id_photo"
DOC_TYPE_PASSPORT:          str = "passport"
DOC_TYPE_DRIVER_LICENSE:    str = "driver_license"
DOC_TYPE_NATIONAL_ID:       str = "national_id"
DOC_TYPE_RESIDENCE_PERMIT:  str = "residence_permit"
DOC_TYPE_VISA:              str = "visa"
DOC_TYPE_BIRTH_CERTIFICATE: str = "birth_certificate"
DOC_TYPE_BANK_CARD:         str = "bank_card"
DOC_TYPE_OTHER_DOCUMENT:    str = "other_document"
DOC_TYPE_UNKNOWN:           str = "unknown"

ID_CLASS_DOC_TYPES: frozenset[str] = frozenset({
    DOC_TYPE_ID_PHOTO,
    DOC_TYPE_PASSPORT,
    DOC_TYPE_DRIVER_LICENSE,
    DOC_TYPE_NATIONAL_ID,
    DOC_TYPE_RESIDENCE_PERMIT,
    DOC_TYPE_VISA,
})

                                                               
DOC_TYPE_NOUN: dict[str, str] = {
    DOC_TYPE_ID_PHOTO:          "ID document",
    DOC_TYPE_PASSPORT:          "passport",
    DOC_TYPE_DRIVER_LICENSE:    "driver license",
    DOC_TYPE_NATIONAL_ID:       "national ID",
    DOC_TYPE_RESIDENCE_PERMIT:  "residence permit",
    DOC_TYPE_VISA:              "visa",
    DOC_TYPE_BIRTH_CERTIFICATE: "birth certificate",
    DOC_TYPE_BANK_CARD:         "bank card",
    DOC_TYPE_OTHER_DOCUMENT:    "document",
    DOC_TYPE_UNKNOWN:           "document",
}

                                                                 
STRENGTH_VISUAL_CONFIRMED:    str = "visual_confirmed"
STRENGTH_STRONG_OCR_DOCUMENT: str = "strong_ocr_document"
STRENGTH_WEAK_TEXT_REFERENCE: str = "weak_text_reference"

STRICT_ID_PHOTO_STRENGTHS: frozenset[str] = frozenset({
    STRENGTH_VISUAL_CONFIRMED,
    STRENGTH_STRONG_OCR_DOCUMENT,
})

                                                              
QUERY_KIND_ID_PHOTO_VISUAL:   str = "id_photo_visual"
QUERY_KIND_ID_REFERENCE_TEXT: str = "id_reference_text"
QUERY_KIND_GENERIC:           str = "generic"

                                                              
MATCH_STATUS_EXACT_NAME_MATCH: str = "exact_name_match"
MATCH_STATUS_FUZZY_NAME_MATCH: str = "fuzzy_name_match"
MATCH_STATUS_NO_NAME_MATCH:    str = "no_name_match"
MATCH_STATUS_NAME_MISMATCH:    str = "name_mismatch"

PERSON_MATCH_ACCEPT: frozenset[str] = frozenset({
    MATCH_STATUS_EXACT_NAME_MATCH,
    MATCH_STATUS_FUZZY_NAME_MATCH,
})

                                                       
ID_CLASS_DOC_KINDS: frozenset[str] = frozenset({
    "id", "id_photo", "passport", "driver_license",
    "identity_card", "license",
})

                                                           
_ID_CLASS_KEYWORDS: frozenset[str] = frozenset({
    "id", "ids", "photo", "photos", "card", "cards",
    "passport", "passports", "license", "licenses",
    "licence", "licences", "identity", "identification",
    "drivers", "driver", "driving", "dl", "permit", "passports",
    "national", "state",
})

                                                            
_QUERY_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "of", "for", "with", "to", "from",
    "in", "on", "at", "by", "as", "vs",
    "my", "your", "our", "their", "his", "her", "its",
    "all", "any", "every", "some", "each",
    "find", "show", "me", "get", "list", "give", "please",
    "look", "search", "search?", "tell", "do",
    "can", "could", "would", "should", "will", "shall",
    "have", "has", "had", "contain", "contains", "containing",
    "is", "are", "was", "were", "be", "been", "being",
    "who", "what", "where", "when", "which", "that", "this",
    "those", "these",
    "named", "name", "person", "people", "owner", "holder",
    "you", "they", "we", "i", "me",
    "now", "yet", "again",
                                                          
                                                             
    "vault", "vaults", "vaultai",
                                                                    
                                                             
    "ok", "okay", "yeah", "yep", "yes", "sure", "so", "well",
    "alright", "hey", "thanks", "thank",
                                                                   
    "just", "actually", "really", "kinda", "sorta",
})


_KIND_EXPANSIONS: dict[str, tuple[str, ...]] = {
                                                       
                            
    "id":              ("image", "pdf"),
    "id_photo":        ("image", "pdf"),
    "passport":        ("image", "pdf"),
    "driver_license":  ("image", "pdf"),
    "identity_card":   ("image", "pdf"),
    "license":         ("image", "pdf"),
                             
    "photo":           ("image",),
    "image":           ("image",),
    "pdf":             ("pdf",),
                    
    "document":        ("image", "pdf", "text"),
    "any":             ("image", "pdf", "text"),
}


_DOC_TYPE_MARKERS: dict[str, tuple[str, ...]] = {
    DOC_TYPE_DRIVER_LICENSE: (
        "driver license", "driver's license", "drivers license",
        "license class", "license number", "lic no",
        "dmv", "department of motor vehicles",
        "motor vehicle administration",
        "endorsements", "restrictions",
        "donor", "real id",
    ),
    DOC_TYPE_PASSPORT: (
        "passport number", "passport no", "passport book",
        "place of birth", "country code", "type code",
        "machine readable zone", "passeport",
        "department of state",
    ),
    DOC_TYPE_ID_PHOTO: (
        "identity card", "id card", "id number", "id no",
        "national id", "state id", "resident card",
        "permanent resident card", "social security card",
    ),
}


_ID_FORM_NEGATIVE_MARKERS: tuple[str, ...] = (
                                                         
    "please attach", "please provide", "please submit",
    "please upload", "please send", "please email", "please fax",
    "please include a copy", "must provide", "we require",
    "copy of your driver", "copy of your license",
    "copy of your passport", "copy of your id",
    "copy of driver licen", "copy of license",
    "scan of your", "scan of driver", "scan of license",
    "photo of your driver", "photo of your license",
    "photo of your id", "upload a copy", "upload your",
    "submit a copy", "attach a copy",
    "for verification purposes",
    "as proof of identity", "proof of identification",
    "valid form of identification", "valid form of id",
    "government-issued id", "government issued id",
                                   
    "insurance policy", "insurance company", "insurance carrier",
    "policy number", "premium", "deductible", "coverage period",
    "policyholder", "policy holder", "named insured",
    "underwritten by", "claim number", "auto insurance",
    "homeowners insurance", "home insurance", "renters insurance",
    "renewal notice", "renewal premium", "policy renewal",
    "billing statement", "invoice number", "amount due",
    "payment due",
                                      
    "form 4506", "form 1040", "form w-2", "form w-9",
    "form ssa", "form i-9", "form i-94", "tax return",
    "tax form", "tax year", "internal revenue service",
    "request for transcript", "transcript of",
                                                              
                                                  
    "dear customer", "dear member", "dear sir or madam",
    "regards,", "sincerely,", "best regards",
                                   
    "human resources", "onboarding", "i-9 verification",
    "employment authorization", "background check",
    "application form", "registration form",
)

                                                            
_ID_HEADER_MARKERS: dict[str, tuple[str, ...]] = {
    DOC_TYPE_DRIVER_LICENSE: (
        "driver license", "driver's license", "drivers license",
        "commercial driver license", "commercial driver's license",
        "operator's license", "operator license",
    ),
    DOC_TYPE_PASSPORT: (
        "passport", "passeport", "u.s. passport", "us passport",
        "united states of america passport",
    ),
    DOC_TYPE_ID_PHOTO: (
        "identification card", "identity card", "national id",
        "national identity", "state identification card",
        "state id card", "real id", "permanent resident card",
        "resident card", "id card",
    ),
}

                                                               
_ID_FIELD_MARKERS: dict[str, tuple[str, ...]] = {
    DOC_TYPE_DRIVER_LICENSE: (
        "dob", "date of birth", "exp", "expires", "expiration",
        "class", "endorsements", "restrictions", "donor",
        "dl #", "dl no", "dl number", "license number",
        "lic #", "lic no", "iss", "issued",
        "department of motor vehicles", "motor vehicle administration",
        "dmv", "department of public safety",
        "sex:", "sex m", "sex f", "height", "weight",
        "hair", "eyes",
    ),
    DOC_TYPE_PASSPORT: (
        "passport number", "passport no", "passport book",
        "type code", "country code", "nationality",
        "place of birth", "machine readable zone",
        "department of state", "date of issue", "date of expiration",
        "authority", "given names", "surname",
    ),
    DOC_TYPE_ID_PHOTO: (
        "id number", "id no", "id #", "card number",
        "issued by", "date of birth", "dob",
        "expires", "expiration", "issued",
        "uscis", "alien number", "a#",
    ),
}


def _text_looks_like_id_form(text: str) -> bool:


    if not text:
        return False
    tlow = text.lower()
    return any(marker in tlow for marker in _ID_FORM_NEGATIVE_MARKERS)


def _strong_ocr_document_for_type(text: str, doc_type: str) -> bool:


    if not text or doc_type not in ID_CLASS_DOC_TYPES:
        return False
    if _text_looks_like_id_form(text):
        return False
    tlow = text.lower()
    headers = _ID_HEADER_MARKERS.get(doc_type, ())
    fields = _ID_FIELD_MARKERS.get(doc_type, ())
    has_header = any(h in tlow for h in headers)
    has_field = any(f in tlow for f in fields)
    return has_header and has_field


_ID_REFERENCE_QUERY_MARKERS: tuple[str, ...] = (
    "mentions", "mentioning", "mention",
    "references", "referencing", "reference",
    "contains", "containing", "contain",
    "anything about", "documents about",
    "discusses", "discussing",
    "talks about",
)


_REQUESTED_DOC_TYPE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
                                                                 
                                                              
    (
        re.compile(
            r"\b(?:driver(?:'?s)?|drivers)\s+licen[sc]es?\b",
            re.IGNORECASE,
        ),
        DOC_TYPE_DRIVER_LICENSE,
    ),
    (
        re.compile(r"\bdriving\s+licen[sc]es?\b", re.IGNORECASE),
        DOC_TYPE_DRIVER_LICENSE,
    ),
                                                         
    (
        re.compile(
            r"\bresiden(?:ce|cy|t)\s+permits?\b", re.IGNORECASE,
        ),
        DOC_TYPE_RESIDENCE_PERMIT,
    ),
                        
    (
        re.compile(
            r"\bbirth\s+certificates?\b", re.IGNORECASE,
        ),
        DOC_TYPE_BIRTH_CERTIFICATE,
    ),
    (
        re.compile(r"\bbirth\s+certs?\b", re.IGNORECASE),
        DOC_TYPE_BIRTH_CERTIFICATE,
    ),
                                                            
                                                            
    (
        re.compile(
            r"\bnational\s+(?:id|identification|identity)\b",
            re.IGNORECASE,
        ),
        DOC_TYPE_NATIONAL_ID,
    ),
    (
        re.compile(r"\bnat\s+id\b", re.IGNORECASE),
        DOC_TYPE_NATIONAL_ID,
    ),
                
    (
        re.compile(r"\bbank\s+cards?\b", re.IGNORECASE),
        DOC_TYPE_BANK_CARD,
    ),
    (
        re.compile(r"\b(?:debit|credit)\s+cards?\b", re.IGNORECASE),
        DOC_TYPE_BANK_CARD,
    ),
               
    (
        re.compile(r"\bpassports?\b", re.IGNORECASE),
        DOC_TYPE_PASSPORT,
    ),
                                                                
                                                         
    (
        re.compile(
            r"\b(?:immigration\s+|entry\s+)?visas?\b", re.IGNORECASE,
        ),
        DOC_TYPE_VISA,
    ),
                                                                 
                                                                
    (
        re.compile(r"\blicen[sc]es?\b", re.IGNORECASE),
        DOC_TYPE_DRIVER_LICENSE,
    ),
)


_BROAD_ID_QUERY_MARKERS: tuple[str, ...] = (
    "documents", "document", "files",
    "id documents", "id document",
    "identification documents", "identification document",
    "id papers", "identity papers",
    "any id", "all ids", "all id photos",
)


def extract_requested_doc_type(query: Optional[str]) -> Optional[str]:


    if not isinstance(query, str) or not query.strip():
        return None
    q = query.strip().lower()
    for pattern, doc_type in _REQUESTED_DOC_TYPE_PATTERNS:
        if pattern.search(q):
            return doc_type
    return None


def _classify_query_kind(*, query: str, is_id_class: bool) -> str:


    if not is_id_class:
        return QUERY_KIND_GENERIC
    qlow = (query or "").lower()
    if any(marker in qlow for marker in _ID_REFERENCE_QUERY_MARKERS):
        return QUERY_KIND_ID_REFERENCE_TEXT
    return QUERY_KIND_ID_PHOTO_VISUAL


def _compute_match_status(
    *,
    requested_name: str,
    visible_name: Optional[str],
    fuzzy_distance: int,
) -> str:


    requested = (requested_name or "").strip()
    visible = (visible_name or "").strip()
    if not requested:
                                                                  
                                                                    
        return (
            MATCH_STATUS_EXACT_NAME_MATCH
            if visible
            else MATCH_STATUS_NO_NAME_MATCH
        )
    if not visible:
        return MATCH_STATUS_NO_NAME_MATCH
    if requested.lower() == visible.lower():
        return MATCH_STATUS_EXACT_NAME_MATCH
    if fuzzy_token_match(
        requested, visible, max_distance=fuzzy_distance,
    ):
        return MATCH_STATUS_FUZZY_NAME_MATCH
    return MATCH_STATUS_NAME_MISMATCH


def _classification_strength(
    *,
    evidence_type: str,
    doc_type: str,
    text_for_strength_check: Optional[str] = None,
) -> str:


    if evidence_type in (EVIDENCE_IMAGE_VISION, EVIDENCE_PDF_PAGE_VISION):
        if doc_type in ID_CLASS_DOC_TYPES:
            return STRENGTH_VISUAL_CONFIRMED
        return STRENGTH_WEAK_TEXT_REFERENCE
    if evidence_type in (EVIDENCE_EXTRACTED_TEXT, EVIDENCE_OCR_TEXT):
        if _strong_ocr_document_for_type(
            text_for_strength_check or "", doc_type,
        ):
            return STRENGTH_STRONG_OCR_DOCUMENT
        return STRENGTH_WEAK_TEXT_REFERENCE
    return STRENGTH_WEAK_TEXT_REFERENCE


_NAME_CHAR = r"[^\W\d_]"
_NAME_TOKEN = rf"{_NAME_CHAR}[\w'\-]+"
_NAME_RUN = rf"{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,3}}"

_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        rf"\b(?:Holder|Card\s*Holder)\s*[:\-]?\s+({_NAME_RUN})",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        rf"\b(?:Name|Full\s*Name|Given\s*Name)\s*[:\-]\s*({_NAME_RUN})",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        rf"\bIssued\s+to\s*[:\-]?\s+({_NAME_RUN})",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        rf"\b(?:Surname|Last\s*Name)\s*[:\-]\s*({_NAME_TOKEN})",
        re.IGNORECASE | re.UNICODE,
    ),
)


_VISION_NEGATIONS: tuple[str, ...] = (
    "no document", "no id", "no card", "no name", "no match",
    "does not show", "doesn't show",
                                                             
                                                            
    "does not belong to", "doesn't belong to",
    "is not named", "isn't named",
    "name is not", "name does not match",
    "different person", "different name",
    "wrong person", "wrong name",
    "i don't see", "i do not see",
    "cannot tell", "can't tell", "unable to determine",
    "not visible", "isn't shown", "is not shown",
    "appears to be unrelated", "not an id",
    "not a driver license", "not a passport",
    "no — ", "no, ", "no.",
)


_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")]


def _levenshtein(a: str, b: str, *, max_d: int) -> int:


    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_d:
        return max_d + 1
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cb = b[j - 1]
            v = min(
                cur[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            )
            cur[j] = v
            if v < row_min:
                row_min = v
        if row_min > max_d:
            return max_d + 1
        prev = cur
    return prev[lb] if prev[lb] <= max_d else max_d + 1


def fuzzy_token_match(
    query: str, haystack: str, *,
    max_distance: int = DEFAULT_FUZZY_DISTANCE,
) -> bool:


    q_tokens = [t for t in _tokenize(query) if len(t) >= 3]
    if not q_tokens:
        return False
    h_tokens = _tokenize(haystack)
    if not h_tokens:
        return False
    h_set = set(h_tokens)
    for qt in q_tokens:
        if qt in h_set:
            continue
        ok = False
        for ht in h_tokens:
            if abs(len(ht) - len(qt)) > max_distance:
                continue
            if _levenshtein(qt, ht, max_d=max_distance) <= max_distance:
                ok = True
                break
        if not ok:
            return False
    return True


def exact_substring_match(query: str, haystack: str) -> bool:
    q = (query or "").strip().lower()
    h = (haystack or "").lower()
    return bool(q) and q in h


_ID_KEYWORD_TYPO_DISTANCE: int = 1
_ID_KEYWORD_TYPO_MIN_LEN:  int = 5
                                                               
                                                                 
_ID_CLASS_KEYWORDS_FUZZY: tuple[str, ...] = tuple(
    sorted(k for k in _ID_CLASS_KEYWORDS if len(k) >= _ID_KEYWORD_TYPO_MIN_LEN)
)


def _adjacent_transpose_equal(a: str, b: str) -> bool:


    if len(a) != len(b):
        return False
    diffs = [i for i in range(len(a)) if a[i] != b[i]]
    if len(diffs) != 2:
        return False
    i, j = diffs
    if j != i + 1:
        return False
    return a[i] == b[j] and a[j] == b[i]


def _is_id_class_keyword(token: str) -> bool:


    if not token:
        return False
    t = token.lower()
    if t in _ID_CLASS_KEYWORDS:
        return True
    if len(t) < _ID_KEYWORD_TYPO_MIN_LEN:
        return False
    for kw in _ID_CLASS_KEYWORDS_FUZZY:
                                                               
                                                                
        if abs(len(kw) - len(t)) <= _ID_KEYWORD_TYPO_DISTANCE:
            if _levenshtein(t, kw, max_d=_ID_KEYWORD_TYPO_DISTANCE) <= (
                _ID_KEYWORD_TYPO_DISTANCE
            ):
                return True
        if _adjacent_transpose_equal(t, kw):
            return True
    return False


def _infer_doc_kind_from_query(query: str) -> Optional[str]:


    for t in _tokenize(query):
        if _is_id_class_keyword(t):
            return "id_photo"
    return None


def _normalize_kind_hint(doc_kind: Optional[str]) -> tuple[str, ...]:
    if not doc_kind:
        return _KIND_EXPANSIONS["any"]
    key = doc_kind.strip().lower()
    if key in _KIND_EXPANSIONS:
        return _KIND_EXPANSIONS[key]
    return _KIND_EXPANSIONS["any"]


def _is_id_class_doc_kind(doc_kind: Optional[str]) -> bool:
    if not doc_kind:
        return False
    return doc_kind.strip().lower() in ID_CLASS_DOC_KINDS


def _extract_entity_from_query(
    query: str, *, is_id_class_search: bool,
) -> str:


    if not is_id_class_search:
        return (query or "").strip()
    tokens = _tokenize(query)
    keep: list[str] = []
    for t in tokens:
                                                                   
                                                                   
        if _is_id_class_keyword(t):
            continue
        if t in _QUERY_STOPWORDS:
            continue
        if len(t) < 2:
            continue
        keep.append(t)
    return " ".join(keep)


def _row_subkind(row: dict) -> str:


    ctype = (row.get("content_type") or "").strip().lower()
    asset = (row.get("asset_type") or "").strip().lower()
    name = (row.get("saved_name") or row.get("file_name") or "").lower()
                                                                       
                                                               
    try:
        from vault_image_formats import is_image_row
        if is_image_row(
            mime=ctype, file_name=name, asset_type=asset,
        ):
            return "image"
    except Exception:
        if asset == "image" or ctype.startswith("image/"):
            return "image"
    if asset == "video" or ctype.startswith("video/"):
        return "video"
    if asset == "audio" or ctype.startswith("audio/"):
        return "audio"
    if "pdf" in ctype or name.endswith(".pdf"):
        return "pdf"
    if (
        ctype.startswith("text/")
        or ctype in ("application/json", "application/xml")
        or name.endswith((".txt", ".md", ".json", ".csv", ".html"))
    ):
        return "text"
                                                           
                                                             
    if row.get("extracted_text"):
        return "text"
    return "other"


def _row_label(row: dict) -> str:
    return str(row.get("saved_name") or row.get("file_name") or "")


def _row_id(row: dict) -> str:
    return str(row.get("id") or "")


def _decrypt_pdf_bytes(row: dict, key: bytes) -> Optional[bytes]:


    enc = row.get("encrypted_file_data")
    fid = _row_id(row)

                                                        
    if not enc and fid:
        try:
            from main import get_db
            from psycopg2.extras import RealDictCursor
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    "SELECT encrypted_file_data, storage_mode "
                    "FROM uploaded_files WHERE id = %s",
                    (fid,),
                )
                drow = cur.fetchone()
                if drow:
                    enc = drow.get("encrypted_file_data")
            finally:
                conn.close()
        except Exception:
            logger.exception(
                "[FIND] pdf lazy-fetch failed file_id=%s",
                (fid or "")[:8],
            )
            return None

    if not enc or not isinstance(enc, str):
        return None
    try:
        from vault_core import decrypt_bytes
        return decrypt_bytes(enc, key)
    except Exception:
        logger.exception(
            "[FIND] pdf decrypt failed file_id=%s",
            (fid or "")[:8],
        )
        return None


def classify_document_type_from_text(text: Optional[str]) -> str:


    if not text:
        return DOC_TYPE_UNKNOWN
    t = text.lower()
    scores: dict[str, int] = {k: 0 for k in _DOC_TYPE_MARKERS}
    for kind, markers in _DOC_TYPE_MARKERS.items():
        for m in markers:
            if m in t:
                scores[kind] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] >= 1 else DOC_TYPE_UNKNOWN


def classify_document_type_from_vision(text: Optional[str]) -> str:


    if not text:
        return DOC_TYPE_UNKNOWN
    t = text.lower()
    if any(n in t for n in _VISION_NEGATIONS):
                                                              
                                          
        return DOC_TYPE_UNKNOWN
    if "passport" in t:
        return DOC_TYPE_PASSPORT
    if (
        "driver license" in t
        or "driver's license" in t
        or "drivers license" in t
    ):
        return DOC_TYPE_DRIVER_LICENSE
    if (
        "id card" in t
        or "identity card" in t
        or "national id" in t
        or "state id" in t
        or "real id" in t
        or "identification card" in t
    ):
        return DOC_TYPE_ID_PHOTO
    return DOC_TYPE_UNKNOWN


def extract_name_from_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    for pat in _NAME_PATTERNS:
        m = pat.search(text)
        if m:
            raw = m.group(1).strip()
                                                            
            return _smart_titlecase(raw)
    return None


_NAME_STOPWORDS: frozenset[str] = frozenset({
                                                                 
                                          
    "the", "a", "an", "of", "to", "for", "and", "with", "on",
    "in", "at", "by", "from", "into", "as", "is", "it", "this",
    "that", "these", "those", "be", "been", "are", "was", "were",
                                                             
                                                   
    "reads", "shown", "appears", "visible", "see", "say",
    "states", "stating", "show",
                                                            
    "name", "names", "holder", "owner", "driver", "passport",
    "license", "licence", "id", "document", "card", "photo",
    "image", "issued", "registered", "belongs", "full", "given",
    "surname", "country", "state", "no",
})


def _is_valid_name_capture(captured: str) -> bool:


    if not captured:
        return False
    tokens = captured.split()
    if not tokens:
        return False
    for t in tokens:
        if t.lower() in _NAME_STOPWORDS:
            return False
    return True


_VISION_NAME_RUN = (
    r"[A-Z][A-Za-z'\-]+(?:[ \t]+[A-Z][A-Za-z'\-]+){1,3}"
)


_NAME_VISION_PATTERNS: tuple[re.Pattern[str], ...] = (
                                                            
                                                           
    re.compile(
        rf"(?i:\bfull\s+name)\s*[:\-]\s*({_VISION_NAME_RUN})",
    ),
    re.compile(
                                                                  
                                                                
        rf"(?i:\b(?:holder|card\s*holder))\b\s*[:\-]?\s+"
        rf"({_VISION_NAME_RUN})",
    ),
    re.compile(
        rf"(?i:\b(?:given\s+name|surname|last\s+name))\s*[:\-]\s*"
        rf"({_VISION_NAME_RUN})",
    ),
    re.compile(
        rf"(?i:\bname)\s*[:\-]\s*({_VISION_NAME_RUN})",
    ),
    re.compile(
        rf"(?i:\bdriver)\s*[:\-]\s*({_VISION_NAME_RUN})",
    ),
                                                                
                                                                
    re.compile(
        rf"(?i:\bname\b.{{0,40}}?\b(?:is|reads|shown|appears))"
        rf"\s+({_VISION_NAME_RUN})",
    ),
                                                               
                                                            
    re.compile(
        rf"(?i:\bissued\s+to)\s+({_VISION_NAME_RUN})",
    ),
    re.compile(
        rf"(?i:\b(?:belongs?|registered)\s+to)\s+({_VISION_NAME_RUN})",
    ),
                                                                
                                                   
    re.compile(
        rf"(?i:\b(?:passport|licen[cs]e|id|card|document)"
        rf"\s+(?:for|of))\s+({_VISION_NAME_RUN})",
    ),
)

                                                            
_NAME_PRE_CLAUSE_NEGATIONS: tuple[str, ...] = (
    "not ", "n't ", " no ",
    "does not", "doesn't",
    "do not", "don't",
    "did not", "didn't",
    "is not", "isn't",
    "are not", "aren't",
    "was not", "wasn't",
    "were not", "weren't",
    "cannot", "can't",
    "no match", "no name",
    "different person", "different name",
    "wrong person", "wrong name",
    "name is not", "name does not",
    "does not belong to", "doesn't belong to",
    "not named", "is not named",
)


def _pre_match_is_negated(text: str, match_start: int) -> bool:


    if match_start <= 0:
        return False
    window_start = max(0, match_start - 200)
    pre = text[window_start:match_start]
    last_boundary = max(pre.rfind("."), pre.rfind("!"), pre.rfind("?"))
    if last_boundary >= 0:
        pre = pre[last_boundary + 1:]
    pre_low = pre.lower()
    return any(neg in pre_low for neg in _NAME_PRE_CLAUSE_NEGATIONS)


_NAME_INPUT_NORMALIZE_TABLE = str.maketrans({
    "“": " ",                     
    "”": " ",                      
    "‘": " ",                     
    "’": "'",                                                      
    "«": " ",
    "»": " ",
    "*": " ",                                            
    "\"": " ",
    "_": " ",
})


def extract_name_from_vision(text: Optional[str]) -> Optional[str]:


    if not text:
        return None
    normalized = text.translate(_NAME_INPUT_NORMALIZE_TABLE)
    for pat in _NAME_VISION_PATTERNS:
        for m in pat.finditer(normalized):
                                                               
                                                            
            if _pre_match_is_negated(normalized, m.start()):
                continue
            raw = m.group(1).strip()
                                                                         
                                                                      
            raw = raw.rstrip(".,;:!?")
            if _is_valid_name_capture(raw):
                return _smart_titlecase(raw)
    return None


def _smart_titlecase(s: str) -> str:
    parts = re.split(r"(\s+)", s)
    out: list[str] = []
    for p in parts:
        if p.isspace():
            out.append(p)
        elif p:
            out.append(p[0].upper() + p[1:].lower())
    return "".join(out)


def _vision_hit_phrase_matched(text: str, query: str) -> bool:
    if not text or not query:
        return False
    tlow = text.lower()
    if any(n in tlow for n in _VISION_NEGATIONS):
        return False
    if exact_substring_match(query, text):
        idx = tlow.find(query.lower())
        window = tlow[max(0, idx - 48):idx]
        if any(n in window for n in _VISION_NEGATIONS):
            return False
        return True
    return fuzzy_token_match(query, text)


def _err(name: str, **extra: Any) -> str:
    payload: dict[str, Any] = {"error": name}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def _short(s: str, cap: int) -> str:
    s = (s or "").strip()
    if len(s) <= cap:
        return s
    cut = s[:cap]
    ws = cut.rfind(" ")
    if ws > cap * 0.7:
        cut = cut[:ws]
    return cut + "…"


def _evidence_snippet_for_text(text: str, query: str) -> str:
    try:
        from extractor import redact_message
        text = redact_message(text or "")
    except Exception:
        pass
    if not text:
        return ""
    qlow = (query or "").lower()
    tlow = text.lower()
    idx = tlow.find(qlow) if qlow else -1
    if idx < 0 and query:
        for qt in _tokenize(query):
            if len(qt) < 3:
                continue
            i = tlow.find(qt)
            if i >= 0:
                idx = i
                break
    if idx < 0:
        return _short(text, 240)
    start = max(0, idx - 80)
    end = min(len(text), idx + 160)
    return _short(text[start:end], 240)


def _build_vision_question(
    *, is_id_class_search: bool, entity_query: str,
) -> str:
    if is_id_class_search:
        if entity_query:
            return (
                "Is this image an ID document, passport, "
                "driver's license, or identity card belonging "
                f"to '{entity_query}'? Answer plainly. State "
                "the document type and the name visible on it. "
                "If the image is unrelated, say 'no'."
            )
        return (
            "Is this image an ID document, passport, driver's "
            "license, or identity card? Answer plainly. State "
            "the document type and the name visible on it. If "
            "it is unrelated, say 'no'."
        )
    return (
        f"Does this image show or contain '{entity_query}'? "
        "Answer plainly. If the image shows an ID document "
        "with a name, state the name verbatim."
    )


def _normalize_lookup_key(name: Optional[str]) -> str:
    """2026-07-26 named-object resolution normalization. Mirror
    ``main._normalize_asset_lookup_key``: lowercase, collapse
    whitespace, drop punctuation the user might vary on, fold
    hyphens/underscores to space. Used ONLY for comparison; stored
    display labels are preserved verbatim by the writer.
    """
    if not name or not isinstance(name, str):
        return ""
    s = name.strip().lower()
    s = re.sub(r"[^\w\-\.\s]", "", s)
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Drop a trailing file extension so "naim id" matches
    # "naim_id.jpg" — the LLM's query rarely includes the extension.
    s = re.sub(r"\.[a-z0-9]{1,6}$", "", s).strip()
    return s


# Category words that are broad-family queries, NOT specific named
# items. The named-object resolver bows out when the whole normalized
# query is one of these so ``list_by_tag`` / broad ID search stays
# in charge.
_NAMED_OBJECT_CATEGORY_STOP: frozenset[str] = frozenset({
    "id", "ids", "identity", "identities",
    "photo", "photos", "image", "images",
    "document", "documents", "file", "files",
    "receipt", "receipts", "note", "notes",
    "passport", "passports", "license", "licenses",
    "driver license", "driver licenses",
    "tax", "taxes", "medical", "finance", "financial",
    "travel", "legal", "personal", "business",
})


# Very short labels are unsafe to substring-match against arbitrary
# messages ("id" would match every message containing the word).
_NAMED_OBJECT_MIN_KEY_LEN = 3


def _resolve_named_object(
    vault_id: str,
    query: str,
    rows: list[dict],
) -> Optional[dict]:
    """2026-07-26 named-object resolution. Before running the
    extracted-text + vision search, check whether the user's message
    literally names a specific uploaded file — by ``saved_name`` (the
    UI label the user gave the file) or by ``file_name`` (the
    original upload filename).

    Returns the matching row when a unique-longest match is found.
    Returns ``None`` when:
      * the vault has no rows, or
      * the normalized query is a broad category label, or
      * no row's saved_name / file_name appears as a substring of
        the normalized query, or
      * multiple equally-long candidates match (ambiguous — better
        to let the LLM ask, or to fall through to the broader search).

    ZK-adopted vault caveat: for rows where saved_name is NULL and
    only saved_name_ciphertext exists, this resolver cannot see the
    label — the backend has no plaintext to compare against. Those
    rows fall through to the existing extracted-text/vision search,
    which is the same behavior as pre-2026-07-26. A follow-up commit
    will thread client-side plaintext labels through the chat
    request for ZK vaults.
    """
    if not vault_id or not query or not rows:
        return None
    normalized_query = _normalize_lookup_key(query)
    if not normalized_query:
        return None
    if normalized_query in _NAMED_OBJECT_CATEGORY_STOP:
        return None

    # (normalized_label, row, source_label) for each candidate.
    candidates: list[tuple[str, dict, str]] = []
    seen_keys: set[str] = set()

    for row in rows:
        for source_label in ("saved_name", "file_name"):
            raw = row.get(source_label)
            if not raw or not isinstance(raw, str):
                continue
            key = _normalize_lookup_key(raw)
            if not key or len(key) < _NAMED_OBJECT_MIN_KEY_LEN:
                continue
            if key in seen_keys:
                continue
            if key in _NAMED_OBJECT_CATEGORY_STOP:
                continue
            # Whole-query exact match wins immediately.
            if key == normalized_query:
                return row
            # Word-boundary substring: label appears as a token
            # inside the query.
            pat = re.compile(
                r"(?:^|(?<=\s))" + re.escape(key)
                + r"(?=$|\s|[.,;:!?])",
                re.IGNORECASE,
            )
            if pat.search(normalized_query):
                candidates.append((key, row, source_label))
                seen_keys.add(key)

    if not candidates:
        return None

    # Prefer the LONGEST matched label — more specific wins.
    candidates.sort(key=lambda t: len(t[0]), reverse=True)
    top_len = len(candidates[0][0])
    top = [c for c in candidates if len(c[0]) == top_len]
    if len(top) != 1:
        # Ambiguous — let the LLM disambiguate via the broader
        # search rather than picking arbitrarily.
        return None
    return top[0][1]


def find_in_vault(
    *, vault_id: str, key: bytes,
    query: str,
    doc_kind: Optional[str] = None,
    fuzzy_distance: Optional[int] = None,
) -> str:


    print(
        f"[FIND-CALL] vault={(vault_id or '')[:8]}... "
        f"query_len={len(query or '')} "
        f"doc_kind={doc_kind or 'auto'} "
        f"fuzzy_distance={fuzzy_distance}",
        flush=True,
    )
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return _err("vault_locked")
    q = (query or "").strip()

                                                         
    effective_kind = doc_kind or _infer_doc_kind_from_query(q)
    is_id_class = _is_id_class_doc_kind(effective_kind)
    kinds_we_want = _normalize_kind_hint(effective_kind)

                                                             
    query_kind = _classify_query_kind(query=q, is_id_class=is_id_class)

    entity_query = _extract_entity_from_query(
        q, is_id_class_search=is_id_class,
    )

                                                           
    if query_kind == QUERY_KIND_ID_REFERENCE_TEXT:
        entity_query = ""

                                                             
    if not q:
        return _err("empty_query")

    fuzzy = int(
        fuzzy_distance if fuzzy_distance is not None
        else DEFAULT_FUZZY_DISTANCE
    )
    fuzzy = max(0, min(4, fuzzy))

                                                     
    try:
        from main import _list_uploaded_files_for_credential_search
        rows = (
            _list_uploaded_files_for_credential_search(vault_id, key)
            or []
        )
    except Exception:
        logger.exception("[FIND] file list failed")
        return _err("unavailable")

    # 2026-07-26 named-object resolution — CRITICAL BUG 1 FIX.
    # Before running the extracted-text + vision search (which only
    # matches strings appearing INSIDE the file content), check
    # whether the user's message literally names a specific uploaded
    # file by its ``saved_name`` (UI label the user gave) or by its
    # ``file_name`` (original upload). Prior to this fix, "show me
    # naim id" required "naim" to appear in the OCR text of an
    # ID-classified image — so a file the user labelled "Naim ID"
    # was invisible unless its content happened to also spell out
    # the name.
    #
    # On a unique-longest match we return immediately with a
    # synthesized envelope shaped like the normal find_in_vault
    # result. Category-label queries ("show my id documents") are
    # filtered out by the resolver so ``list_by_tag`` /
    # broad-family search stays in charge for those.
    _named_hit = _resolve_named_object(vault_id, q, rows)
    if _named_hit is not None:
        _named_subkind = (
            _named_hit.get("_subkind") or _row_subkind(_named_hit)
        )
        _named_doc_type = (
            (_named_hit.get("detected_type") or "").strip()
            or DOC_TYPE_UNKNOWN
        )
        _named_label = _row_label(_named_hit)
        _named_hit_dict = {
            "file_id":       _row_id(_named_hit),
            "file_name":     _named_label,
            "file_kind":     _named_subkind,
            "evidence_type": EVIDENCE_EXTRACTED_TEXT,
            "match_type":    MATCH_EXACT_TEXT,
            "document_type": _named_doc_type,
            "matched_name":  _named_label,
            "confidence":    0.99,
            "evidence":      f"named-object match on '{_named_label}'",
            "classification_strength": "strong",
            "match_status":  MATCH_STATUS_EXACT_NAME_MATCH,
        }
        print(
            f"[FIND-CALL] named_object_hit vault={(vault_id or '')[:8]}... "
            f"file_id={(_row_id(_named_hit) or '')[:8]}... "
            f"file_kind={_named_subkind}",
            flush=True,
        )
        return json.dumps({
            "query":                    q,
            "doc_kind":                 effective_kind,
            "query_kind":               query_kind,
            "is_id_class_search":       is_id_class,
            "complete":                 True,
            "partial_inspection":       False,
            "hits":                     [_named_hit_dict],
            "files_inspected":          1,
            "files_via_text":           1,
            "files_via_vision":         0,
            "candidate_id_docs_count":  1 if _named_doc_type in ID_CLASS_DOC_TYPES else 0,
            "name_mismatch_count":      0,
            "requested_person_name":    None,
            "requested_doc_type":       None,
            "requested_doc_type_label": None,
            "other_id_docs_count":      0,
            "other_id_doc_types":       [],
            "coverage":                 {
                "vision_budget_remaining": None,
                "vision_used":              0,
                "text_scanned":             1,
                "relevant_rows":            1,
                "named_object_resolution":  True,
            },
        }, ensure_ascii=False)

    seen_ids: set[str] = set()
    relevant_rows: list[dict] = []
    skipped_unrelated = 0
    for r in rows:
        fid = _row_id(r)
        if not fid or fid in seen_ids:
            continue
        seen_ids.add(fid)
        subkind = _row_subkind(r)
        if subkind not in kinds_we_want:
            skipped_unrelated += 1
            continue
        relevant_rows.append({**r, "_subkind": subkind})

    hits: list[dict] = []
    hit_ids: set[str] = set()
    files_via_text = 0
    files_via_vision = 0
    text_scanned = 0
                                             
     
    candidate_id_docs_count = 0
    name_mismatch_count = 0
    counted_candidate_ids: set[str] = set()

                            
    for r in relevant_rows:
        if text_scanned >= MAX_TEXT_FILES_SCANNED:
            break
        text = r.get("extracted_text")
        if not isinstance(text, str) or not text:
            continue
        text_scanned += 1
        fid = _row_id(r)
        if fid in hit_ids:
            continue

        doc_type = classify_document_type_from_text(text)
        name_in_text = extract_name_from_text(text)

        exact_hit = (
            bool(entity_query)
            and exact_substring_match(entity_query, text)
        )
        fuzzy_hit = False
        if entity_query and not exact_hit:
            fuzzy_hit = fuzzy_token_match(
                entity_query, text, max_distance=fuzzy,
            )

        if is_id_class:
                                                           
                                                     
            if doc_type not in ID_CLASS_DOC_TYPES:
                continue
                                                              
                                                              
            if (
                fid not in counted_candidate_ids
                and _strong_ocr_document_for_type(text, doc_type)
            ):
                counted_candidate_ids.add(fid)
                candidate_id_docs_count += 1
                                                            
                                                           
            text_match_status = _compute_match_status(
                requested_name=entity_query,
                visible_name=name_in_text,
                fuzzy_distance=fuzzy,
            )
            if entity_query:
                if not (exact_hit or fuzzy_hit):
                    continue
                if text_match_status not in PERSON_MATCH_ACCEPT:
                    if text_match_status == MATCH_STATUS_NAME_MISMATCH:
                        name_mismatch_count += 1
                                                                 
                                                           
                    continue
                confidence = (
                    0.95
                    if (exact_hit
                        and text_match_status
                        == MATCH_STATUS_EXACT_NAME_MATCH)
                    else 0.80
                )
                match_type = (
                    MATCH_EXACT_TEXT if exact_hit else MATCH_FUZZY_TEXT
                )
                hits.append(_make_hit(
                    row=r, evidence_type=EVIDENCE_EXTRACTED_TEXT,
                    match_type=match_type, document_type=doc_type,
                    matched_name=name_in_text,
                    confidence=confidence,
                    evidence=_evidence_snippet_for_text(text, entity_query),
                    text_for_strength_check=text,
                    match_status=text_match_status,
                ))
                hit_ids.add(fid)
                files_via_text += 1
            else:
                                                              
                                                            
                hits.append(_make_hit(
                    row=r, evidence_type=EVIDENCE_EXTRACTED_TEXT,
                    match_type=MATCH_EXACT_TEXT,
                    document_type=doc_type,
                    matched_name=name_in_text,
                    confidence=0.85,
                    evidence=_short(text, 200),
                    text_for_strength_check=text,
                    match_status=text_match_status,
                ))
                hit_ids.add(fid)
                files_via_text += 1
        else:
            if not entity_query:
                continue
            non_id_match_status = _compute_match_status(
                requested_name=entity_query,
                visible_name=name_in_text,
                fuzzy_distance=fuzzy,
            )
            if exact_hit:
                hits.append(_make_hit(
                    row=r, evidence_type=EVIDENCE_EXTRACTED_TEXT,
                    match_type=MATCH_EXACT_TEXT,
                    document_type=doc_type,
                    matched_name=name_in_text,
                    confidence=0.90,
                    evidence=_evidence_snippet_for_text(text, entity_query),
                    text_for_strength_check=text,
                    match_status=non_id_match_status,
                ))
                hit_ids.add(fid)
                files_via_text += 1
            elif fuzzy_hit:
                hits.append(_make_hit(
                    row=r, evidence_type=EVIDENCE_EXTRACTED_TEXT,
                    match_type=MATCH_FUZZY_TEXT,
                    document_type=doc_type,
                    matched_name=name_in_text,
                    confidence=0.70,
                    evidence=_evidence_snippet_for_text(text, entity_query),
                    text_for_strength_check=text,
                    match_status=non_id_match_status,
                ))
                hit_ids.add(fid)
                files_via_text += 1

                                                              
    vision_candidates = [
        r for r in relevant_rows
        if r["_subkind"] == "image" and _row_id(r) not in hit_ids
    ]
    vision_used = 0
    vision_question = _build_vision_question(
        is_id_class_search=is_id_class,
        entity_query=entity_query,
    )
                                                                
                                                              
    effective_vision_budget = (
        ID_CLASS_VISION_BUDGET if is_id_class
        else MAX_VISION_INSPECTIONS
    )

    for r in vision_candidates:
        if vision_used >= effective_vision_budget:
            break
        fid = _row_id(r)
        try:
            from vault_inspection_tools import read_image_with_vision
            raw = read_image_with_vision(
                vault_id=vault_id, key=bytes(key),
                file_id=fid, question=vision_question,
            )
        except Exception:
            logger.exception(
                "[FIND] vision call raised file_id=%s", fid[:8],
            )
            vision_used += 1
            continue
        vision_used += 1
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
        if "error" in parsed:
            continue
        analysis = str(parsed.get("analysis") or "")
        if not analysis:
            continue

        v_doc_type = classify_document_type_from_vision(analysis)
        v_name = extract_name_from_vision(analysis)

        if is_id_class:
            if v_doc_type not in ID_CLASS_DOC_TYPES:
                continue
                                                                
                                                               
            if fid not in counted_candidate_ids:
                counted_candidate_ids.add(fid)
                candidate_id_docs_count += 1
                                                               
                                                            
            match_status = _compute_match_status(
                requested_name=entity_query,
                visible_name=v_name,
                fuzzy_distance=fuzzy,
            )
            if entity_query:
                if match_status not in PERSON_MATCH_ACCEPT:
                    if match_status == MATCH_STATUS_NAME_MISMATCH:
                        name_mismatch_count += 1
                    continue
                confidence = (
                    0.92
                    if match_status == MATCH_STATUS_EXACT_NAME_MATCH
                    else 0.88
                )
                hits.append(_make_hit(
                    row=r, evidence_type=EVIDENCE_IMAGE_VISION,
                    match_type=MATCH_VISION,
                    document_type=v_doc_type,
                    matched_name=v_name,
                    confidence=confidence,
                    evidence=_short(analysis, 240),
                    match_status=match_status,
                ))
                hit_ids.add(fid)
                files_via_vision += 1
            else:
                hits.append(_make_hit(
                    row=r, evidence_type=EVIDENCE_IMAGE_VISION,
                    match_type=MATCH_VISION,
                    document_type=v_doc_type,
                    matched_name=v_name,
                    confidence=0.88,
                    evidence=_short(analysis, 240),
                    match_status=match_status,
                ))
                hit_ids.add(fid)
                files_via_vision += 1
        else:
            if entity_query and _vision_hit_phrase_matched(
                analysis, entity_query,
            ):
                ms = _compute_match_status(
                    requested_name=entity_query,
                    visible_name=v_name,
                    fuzzy_distance=fuzzy,
                )
                hits.append(_make_hit(
                    row=r, evidence_type=EVIDENCE_IMAGE_VISION,
                    match_type=MATCH_VISION,
                    document_type=v_doc_type,
                    matched_name=v_name,
                    confidence=0.85,
                    evidence=_short(analysis, 240),
                    match_status=ms,
                ))
                hit_ids.add(fid)
                files_via_vision += 1

                                                               
    pdf_pages_used = 0
    pdf_docs_inspected = 0
    pdf_overflow = False
    if is_id_class:
        pdf_candidates = [
            r for r in relevant_rows
            if r["_subkind"] == "pdf" and _row_id(r) not in hit_ids
        ]
        for r in pdf_candidates:
            if vision_used >= effective_vision_budget:
                                                              
                                                       
                pdf_overflow = True
                break
            fid = _row_id(r)
            pdf_bytes = _decrypt_pdf_bytes(r, key)
            if not pdf_bytes:
                continue
            remaining_budget = effective_vision_budget - vision_used
            per_doc_cap = min(
                MAX_PDF_PAGES_PER_DOC,
                max(1, remaining_budget),
            )
            try:
                from vault_pdf_page_vision import (
                    inspect_pdf_pages_with_vision,
                )
                pdf_result = inspect_pdf_pages_with_vision(
                    file_id=fid,
                    pdf_bytes=pdf_bytes,
                    question=vision_question,
                    max_pages=per_doc_cap,
                )
            except Exception:
                logger.exception(
                    "[FIND] pdf_page_vision call raised "
                    "file_id=%s", fid[:8],
                )
                continue

            pages_inspected = int(
                pdf_result.get("pages_inspected") or 0
            )
            pdf_pages_used += pages_inspected
            vision_used += pages_inspected
            pdf_docs_inspected += 1
            if pdf_result.get("budget_exceeded"):
                                                              
                                                             
                pdf_overflow = True

            best_hit_for_doc: Optional[dict] = None
            page_saw_id_class = False
            page_saw_mismatch = False
            for page_result in pdf_result.get("page_results") or []:
                analysis = str(page_result.get("analysis") or "")
                if not analysis:
                    continue
                v_doc_type = classify_document_type_from_vision(analysis)
                if v_doc_type not in ID_CLASS_DOC_TYPES:
                    continue
                page_saw_id_class = True
                v_name = extract_name_from_vision(analysis)
                                                        
                                                                
                page_match_status = _compute_match_status(
                    requested_name=entity_query,
                    visible_name=v_name,
                    fuzzy_distance=fuzzy,
                )
                if entity_query:
                    if page_match_status not in PERSON_MATCH_ACCEPT:
                        if (
                            page_match_status
                            == MATCH_STATUS_NAME_MISMATCH
                        ):
                            page_saw_mismatch = True
                        continue
                    confidence = (
                        0.90
                        if page_match_status
                        == MATCH_STATUS_EXACT_NAME_MATCH
                        else 0.86
                    )
                else:
                    confidence = 0.86

                candidate = _make_hit(
                    row=r,
                    evidence_type=EVIDENCE_PDF_PAGE_VISION,
                    match_type=MATCH_VISION,
                    document_type=v_doc_type,
                    matched_name=v_name,
                    confidence=confidence,
                    evidence=_short(analysis, 240),
                    match_status=page_match_status,
                )
                                                           
                                                            
                if best_hit_for_doc is None or (
                    candidate["confidence"]
                    > best_hit_for_doc["confidence"]
                ):
                    best_hit_for_doc = candidate

            if best_hit_for_doc is not None:
                hits.append(best_hit_for_doc)
                hit_ids.add(fid)
                files_via_vision += 1

                                                            
            if page_saw_id_class and fid not in counted_candidate_ids:
                counted_candidate_ids.add(fid)
                candidate_id_docs_count += 1
            if page_saw_mismatch and best_hit_for_doc is None:
                name_mismatch_count += 1

                                                       
    if is_id_class:
        hits = [
            h for h in hits
            if not (
                h.get("document_type") == DOC_TYPE_UNKNOWN
                and h.get("evidence_type") == EVIDENCE_EXTRACTED_TEXT
            )
        ]

                                                          
    weak_hits_dropped = 0
    if query_kind == QUERY_KIND_ID_PHOTO_VISUAL:
        before = len(hits)
        hits = [
            h for h in hits
            if h.get("classification_strength")
            in STRICT_ID_PHOTO_STRENGTHS
        ]
        weak_hits_dropped = before - len(hits)

                                                          
    requested_doc_type = extract_requested_doc_type(q) if is_id_class else None
    other_id_docs_count = 0
    other_id_doc_types: list[str] = []
    if requested_doc_type:
        before = len(hits)
        kept: list[dict] = []
        other_seen: set[str] = set()
        for h in hits:
            h_type = (h.get("document_type") or "").lower()
            if h_type == requested_doc_type:
                kept.append(h)
                continue
            if h_type in ID_CLASS_DOC_TYPES:
                                                             
                                                              
                other_id_docs_count += 1
                if h_type and h_type not in other_seen:
                    other_seen.add(h_type)
                    other_id_doc_types.append(h_type)
        hits = kept
                                                                 
                                                              
        wrong_type_dropped = before - len(hits)
    else:
        wrong_type_dropped = 0

    inspected = text_scanned + vision_used
    vision_overflow = (
        len(vision_candidates) > vision_used
    )
                                                     
     
    is_complete = True
    partial_inspection = vision_overflow or pdf_overflow

    coverage = {
        "total_relevant_files": len(relevant_rows),
        "inspected":            inspected,
        "skipped_unrelated":    skipped_unrelated,
        "vision_budget_used":   vision_used,
        "vision_budget_max":    effective_vision_budget,
        "pdf_pages_used":       pdf_pages_used,
        "pdf_docs_inspected":   pdf_docs_inspected,
        "pdf_overflow":         pdf_overflow,
        "vision_overflow":      vision_overflow,
                                                            
                                                       
        "partial_inspection":   partial_inspection,
        "is_complete":          is_complete,
                                           
        "query_kind":           query_kind,
        "weak_hits_dropped":    weak_hits_dropped,
                                                          
                                                     
        "candidate_id_docs_count": candidate_id_docs_count,
        "name_mismatch_count":     name_mismatch_count,
                                                              
        "requested_doc_type":     requested_doc_type,
        "other_id_docs_count":    other_id_docs_count,
        "wrong_type_dropped":     wrong_type_dropped,
    }

    logger.info(
        "[FIND] vault=%s kinds=%s id_class=%s files=%d "
        "text_scanned=%d vision_used=%d hits=%d complete=%s "
        "partial=%s vision_budget=%d "
        "query_kind=%s weak_dropped=%d",
        (vault_id or "")[:8] + "...",
        ",".join(kinds_we_want),
        is_id_class,
        len(relevant_rows),
        text_scanned,
        vision_used,
        len(hits),
        is_complete,
        partial_inspection,
        effective_vision_budget,
        query_kind,
        weak_hits_dropped,
    )

    return json.dumps({
        "query":              q,
        "doc_kind":           effective_kind,
        "query_kind":         query_kind,
        "is_id_class_search": is_id_class,
        "complete":           is_complete,
                                                             
                                                         
        "partial_inspection": partial_inspection,
        "hits":               hits,
        "files_inspected":    inspected,
        "files_via_text":     files_via_text,
        "files_via_vision":   files_via_vision,
                                                              
                                                                
        "candidate_id_docs_count": candidate_id_docs_count,
        "name_mismatch_count":     name_mismatch_count,
        "requested_person_name":   (
            _smart_titlecase(entity_query) if entity_query else None
        ),
                                                               
                                                                 
        "requested_doc_type":      requested_doc_type,
        "requested_doc_type_label": (
            DOC_TYPE_NOUN.get(requested_doc_type, "document")
            if requested_doc_type else None
        ),
        "other_id_docs_count":     other_id_docs_count,
        "other_id_doc_types":      other_id_doc_types,
        "coverage":           coverage,
    }, ensure_ascii=False)


def _make_hit(
    *, row: dict, evidence_type: str, match_type: str,
    document_type: str, matched_name: Optional[str],
    confidence: float, evidence: str,
    classification_strength: Optional[str] = None,
    text_for_strength_check: Optional[str] = None,
    match_status: str = MATCH_STATUS_NO_NAME_MATCH,
) -> dict:
                                                               
                                                                
    strength = classification_strength or _classification_strength(
        evidence_type=evidence_type,
        doc_type=document_type,
        text_for_strength_check=text_for_strength_check,
    )
    return {
        "file_id":       _row_id(row),
        "file_name":     _row_label(row),
        "file_kind":     row.get("_subkind") or _row_subkind(row),
        "evidence_type": evidence_type,
        "match_type":    match_type,
        "document_type": document_type,
        "matched_name":  matched_name,
        "confidence":    round(float(confidence), 2),
        "evidence":      evidence,
                                                             
                                                                      
        "classification_strength": strength,
                                                                  
                                              
        "match_status": match_status,
    }


__all__ = [
    "find_in_vault",
    "fuzzy_token_match",
    "exact_substring_match",
    "classify_document_type_from_text",
    "classify_document_type_from_vision",
    "extract_name_from_text",
    "extract_name_from_vision",
    "MAX_VISION_INSPECTIONS",
    "MAX_TEXT_FILES_SCANNED",
    "DEFAULT_FUZZY_DISTANCE",
    "MATCH_EXACT_TEXT",
    "MATCH_FUZZY_TEXT",
    "MATCH_VISION",
    "EVIDENCE_EXTRACTED_TEXT",
    "EVIDENCE_IMAGE_VISION",
    "EVIDENCE_PDF_PAGE_VISION",
    "EVIDENCE_OCR_TEXT",
    "DOC_TYPE_ID_PHOTO",
    "DOC_TYPE_PASSPORT",
    "DOC_TYPE_DRIVER_LICENSE",
    "DOC_TYPE_UNKNOWN",
    "ID_CLASS_DOC_TYPES",
    "ID_CLASS_DOC_KINDS",
]
