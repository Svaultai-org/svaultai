

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional


logger = logging.getLogger(__name__)


CONFIDENCE_STRONG = "strong"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_WEAK = "weak"
CONFIDENCE_LEVELS = (CONFIDENCE_STRONG, CONFIDENCE_MEDIUM, CONFIDENCE_WEAK)


REASON_FRONT_BACK_PAIR = "filename_front_back_pair"
REASON_SAME_PERSON_TOKEN = "shared_person_token"
REASON_SAME_FOLDER = "same_folder"
REASON_SAME_IMPORT_BATCH = "same_import_batch"
REASON_SAME_UPLOAD_SESSION = "same_upload_session"
REASON_SHARED_TOKEN = "shared_filename_token"
REASON_SAME_DOC_TYPE = "same_document_type"
REASON_SAME_CONTENT_HASH = "same_content_hash"


_REASON_WEIGHTS: dict[str, float] = {
    REASON_FRONT_BACK_PAIR:        2.0,
    REASON_SAME_CONTENT_HASH:      1.8,
    REASON_SAME_PERSON_TOKEN:      0.9,
    REASON_SAME_DOC_TYPE:          0.8,
    REASON_SAME_FOLDER:            0.6,
    REASON_SHARED_TOKEN:           0.5,
    REASON_SAME_UPLOAD_SESSION:    0.3,
    REASON_SAME_IMPORT_BATCH:      0.3,
}


_REASON_LABELS: dict[str, str] = {
    REASON_FRONT_BACK_PAIR:     "matching front/back filename pair",
    REASON_SAME_CONTENT_HASH:   "exact same content (duplicate)",
    REASON_SAME_PERSON_TOKEN:   "shared person name in filename",
    REASON_SAME_DOC_TYPE:       "same document type",
    REASON_SAME_FOLDER:         "same folder",
    REASON_SHARED_TOKEN:        "shared filename token",
    REASON_SAME_UPLOAD_SESSION: "same upload session",
    REASON_SAME_IMPORT_BATCH:   "same import batch",
}


_STRONG_THRESHOLD = 1.5
_MEDIUM_THRESHOLD = 0.7


_STOPWORD_TOKENS: frozenset[str] = frozenset({
                          
    "doc", "docs", "document", "file", "files", "image", "img", "photo",
    "photos", "pic", "pics", "picture", "scan", "scans", "screenshot",
    "screen", "shot", "copy", "copies", "page", "pages",
                            
    "the", "and", "or", "of", "for", "with", "to", "from", "in", "on",
                                                                         
    "front", "back",
                           
    "v1", "v2", "v3", "final", "draft",
                                                          
    "jpg", "jpeg", "png", "gif", "webp", "heic", "pdf", "txt",
    "doc", "docx", "xls", "xlsx", "zip", "tar", "gz",
})

                                                                
_MIN_SHARED_TOKEN_LEN = 3


_PERSON_TOKEN_RE = re.compile(
    r"^([a-z]{3,20})(?:[\s_\-]|$)", re.IGNORECASE,
)


_TOKEN_SPLIT_RE = re.compile(r"[\s_\-]+")


_FRONT_TOKENS: frozenset[str] = frozenset({"front", "fr", "f"})
_BACK_TOKENS:  frozenset[str] = frozenset({"back",  "bk", "b"})


_UPLOAD_SESSION_WINDOW_SECONDS = 5 * 60


RELATED_RENDER_HARD_CAP = 12


@dataclass(frozen=True)
class RelatedReason:


    code: str
    label: str
    weight: float


@dataclass
class RelatedResult:

    file_id: str
    file_name: str
    saved_name: Optional[str]
    relative_path: Optional[str]
    reasons: list[RelatedReason] = field(default_factory=list)

    def total_weight(self) -> float:
        return sum(r.weight for r in self.reasons)

    def confidence(self) -> str:
                                                              
                                                              
        for r in self.reasons:
            if r.code == REASON_FRONT_BACK_PAIR:
                return CONFIDENCE_STRONG
            if r.code == REASON_SAME_CONTENT_HASH:
                return CONFIDENCE_STRONG
        total = self.total_weight()
        if total >= _STRONG_THRESHOLD:
            return CONFIDENCE_STRONG
        if total >= _MEDIUM_THRESHOLD:
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_WEAK

    def display_name(self) -> str:
        sn = (self.saved_name or "").strip()
        return sn or self.file_name


def tokenise_filename(file_name: Optional[str]) -> list[str]:


    if not file_name:
        return []
    name = file_name.strip()
                                                           
                                                                  
    dot = name.rfind(".")
    if dot > 0 and (len(name) - dot) <= 6:
        name = name[:dot]
    parts = _TOKEN_SPLIT_RE.split(name.lower())
    return [p for p in parts if p]


def is_meaningful_token(token: str) -> bool:


    if not token:
        return False
    if len(token) < _MIN_SHARED_TOKEN_LEN:
        return False
    if token in _STOPWORD_TOKENS:
        return False
    if token.isdigit():
        return False
    return True


def meaningful_tokens(file_name: Optional[str]) -> set[str]:

    return {
        t for t in tokenise_filename(file_name) if is_meaningful_token(t)
    }


def detect_front_or_back(file_name: Optional[str]) -> Optional[str]:


    for t in tokenise_filename(file_name):
        if t in _FRONT_TOKENS:
            return "front"
        if t in _BACK_TOKENS:
            return "back"
    return None


def extract_person_token(file_name: Optional[str]) -> Optional[str]:


    if not file_name:
        return None
    m = _PERSON_TOKEN_RE.match(file_name.strip())
    if not m:
        return None
    token = m.group(1).lower()
    if not is_meaningful_token(token):
        return None
                                                               
                                                               
    if token in _DOC_TYPE_STEMS:
        return None
    return token


_DOC_TYPE_STEMS: frozenset[str] = frozenset({
    "passport", "license", "licence", "visa", "id", "ssn", "ein",
    "tin", "tax", "invoice", "receipt", "bill", "statement",
    "contract", "agreement", "deed", "title", "policy", "insurance",
    "report", "letter", "form", "application", "certificate",
    "transcript", "diploma", "degree", "resume", "cv",
})


def folder_of(relative_path: Optional[str]) -> Optional[str]:


    if not relative_path:
        return None
    rp = relative_path.strip().strip("/")
    if not rp:
        return None
    last_slash = rp.rfind("/")
    if last_slash <= 0:
        return None
    return rp[:last_slash]


def _matches_front_back_pair(
    anchor_tokens: set[str],
    anchor_side: Optional[str],
    cand_tokens: set[str],
    cand_side: Optional[str],
) -> bool:


    if anchor_side is None or cand_side is None:
        return False
    if anchor_side == cand_side:
        return False
    return bool(anchor_tokens & cand_tokens)


def find_related_with_reasons(
    rows: Iterable[dict],
    *,
    anchor: dict,
) -> list[RelatedResult]:


    anchor_id = anchor.get("id")
    anchor_file_name = anchor.get("file_name") or ""
    anchor_saved_name = anchor.get("saved_name") or anchor_file_name
    anchor_path = anchor.get("relative_path")
    anchor_folder = folder_of(anchor_path)
    anchor_import = anchor.get("import_id")
    anchor_hash = (anchor.get("content_sha256") or "").lower() or None
    anchor_doc_type = (anchor.get("detected_type") or "").lower() or None
    anchor_created = anchor.get("created_at")

    anchor_tokens = meaningful_tokens(anchor_file_name) | meaningful_tokens(
        anchor_saved_name
    )
    anchor_side = detect_front_or_back(anchor_file_name)
    anchor_person = (
        extract_person_token(anchor_file_name)
        or extract_person_token(anchor_saved_name)
    )

    out: list[RelatedResult] = []
    for row in rows:
        rid = row.get("id")
        if not rid or rid == anchor_id:
            continue

        cand_file_name = row.get("file_name") or ""
        cand_saved_name = row.get("saved_name") or cand_file_name
        cand_path = row.get("relative_path")
        cand_folder = folder_of(cand_path)
        cand_import = row.get("import_id")
        cand_hash = (row.get("content_sha256") or "").lower() or None
        cand_doc_type = (row.get("detected_type") or "").lower() or None
        cand_created = row.get("created_at")

        cand_tokens = meaningful_tokens(cand_file_name) | meaningful_tokens(
            cand_saved_name
        )
        cand_side = detect_front_or_back(cand_file_name)
        cand_person = (
            extract_person_token(cand_file_name)
            or extract_person_token(cand_saved_name)
        )

        reasons: list[RelatedReason] = []

                                                              
        if _matches_front_back_pair(
            anchor_tokens, anchor_side, cand_tokens, cand_side,
        ):
            reasons.append(_reason(REASON_FRONT_BACK_PAIR))

                                     
        if anchor_hash and cand_hash and anchor_hash == cand_hash:
            reasons.append(_reason(REASON_SAME_CONTENT_HASH))

                                 
        if anchor_person and cand_person and anchor_person == cand_person:
            reasons.append(_reason(REASON_SAME_PERSON_TOKEN))

                                                            
        shared = anchor_tokens & cand_tokens
        if anchor_person:
            shared.discard(anchor_person)
        if shared:
            reasons.append(_reason(REASON_SHARED_TOKEN))

                         
        if anchor_folder and cand_folder and anchor_folder == cand_folder:
            reasons.append(_reason(REASON_SAME_FOLDER))

                               
        if anchor_import and cand_import and anchor_import == cand_import:
            reasons.append(_reason(REASON_SAME_IMPORT_BATCH))

                                                                 
        if (
            anchor_created is not None
            and cand_created is not None
            and not (anchor_import and cand_import and anchor_import == cand_import)
        ):
            try:
                delta = abs(
                    (anchor_created - cand_created).total_seconds()
                )
                if delta <= _UPLOAD_SESSION_WINDOW_SECONDS:
                    reasons.append(_reason(REASON_SAME_UPLOAD_SESSION))
            except Exception:
                                                                
                                                               
                pass

                                
        if (
            anchor_doc_type
            and cand_doc_type
            and anchor_doc_type == cand_doc_type
            and anchor_doc_type not in ("file", "general", "")
        ):
            reasons.append(_reason(REASON_SAME_DOC_TYPE))

        if not reasons:
                                                                   
                                                    
            continue

        out.append(
            RelatedResult(
                file_id=str(rid),
                file_name=cand_file_name,
                saved_name=(row.get("saved_name") or None),
                relative_path=(row.get("relative_path") or None),
                reasons=reasons,
            )
        )

                                                                   
    out.sort(
        key=lambda r: (
            -r.total_weight(),
            CONFIDENCE_LEVELS.index(r.confidence()),
            (r.saved_name or r.file_name or "").lower(),
        )
    )
    return out


def _reason(code: str) -> RelatedReason:


    return RelatedReason(
        code=code,
        label=_REASON_LABELS[code],
        weight=_REASON_WEIGHTS[code],
    )


def format_related_reply(
    anchor_label: str,
    results: list[RelatedResult],
    *,
    hard_cap: int = RELATED_RENDER_HARD_CAP,
) -> str:


    if not results:
        return (
            f"I couldn't find any clearly related files for "
            f"{anchor_label}."
        )

    strong = [r for r in results if r.confidence() == CONFIDENCE_STRONG]
    medium = [r for r in results if r.confidence() == CONFIDENCE_MEDIUM]
    weak = [r for r in results if r.confidence() == CONFIDENCE_WEAK]

    lines: list[str] = []

                                    
    if not strong and not medium and weak:
        lines.append(
            f"I found files in the same upload batch as "
            f"{anchor_label}, but I'm not sure they're actually "
            f"related. Treat these as weak matches:"
        )
    else:
        lines.append(f"Related to {anchor_label}:")

    remaining = hard_cap
    for bucket_name, bucket in (
        ("Strong matches", strong),
        ("Possible matches", medium),
        ("Weak matches", weak),
    ):
        if not bucket or remaining <= 0:
            continue
                                                               
                                                              
        if bucket_name == "Weak matches" and (strong or medium):
            continue
        shown = bucket[:remaining]
        remaining -= len(shown)
        lines.append("")
        lines.append(f"{bucket_name}:")
        for r in shown:
            lines.append(
                f"- {r.display_name()} — "
                f"{_format_reasons(r.reasons)}"
            )

    total_shown = sum(
        len(b[:RELATED_RENDER_HARD_CAP])
        for b in (strong, medium)
    ) + (
        0 if (strong or medium) else len(weak[:RELATED_RENDER_HARD_CAP])
    )
    total = len(results)
    if total > total_shown:
        extra = total - total_shown
        lines.append("")
        lines.append(
            f"...and {extra} more — refine your question to narrow "
            f"the match (e.g. by folder, person, or date)."
        )

    return "\n".join(lines)


def _format_reasons(reasons: list[RelatedReason]) -> str:


    if not reasons:
        return "no clear reason"
    labels = [r.label for r in reasons]
    return " · ".join(labels)


def handle_related_items_with_reasons(
    vault_id: str,
    anchor_text: str,
) -> Optional[str]:


    if not anchor_text or not anchor_text.strip():
        return None

    try:
                                                                      
        from main import list_uploaded_files
    except Exception as e:
        logger.warning("related_items: import failed: %s", e)
        return None

    try:
        rows = list_uploaded_files(vault_id)
    except Exception as e:
        logger.warning("related_items: list_uploaded_files failed: %s", e)
        return None

    anchor = _resolve_anchor_row(rows, anchor_text.strip())
    if anchor is None:
        return None

    results = find_related_with_reasons(rows, anchor=anchor)
    anchor_label = (
        (anchor.get("saved_name") or anchor.get("file_name") or "this file")
        .strip()
    )
    return format_related_reply(anchor_label, results)


def handle_related_items_envelope_payload(
    vault_id: str,
    anchor_text: str,
) -> Optional[dict]:


    if not anchor_text or not anchor_text.strip():
        return None

    try:
        from main import list_uploaded_files               
    except Exception as e:
        logger.warning("related_items_envelope: import failed: %s", e)
        return None

    try:
        rows = list_uploaded_files(vault_id)
    except Exception as e:
        logger.warning(
            "related_items_envelope: list_uploaded_files failed: %s", e,
        )
        return None

    anchor = _resolve_anchor_row(rows, anchor_text.strip())
    if anchor is None:
        return None

    results = find_related_with_reasons(rows, anchor=anchor)
    anchor_label = (
        (anchor.get("saved_name") or anchor.get("file_name") or "this file")
        .strip()
    )
    message = format_related_reply(anchor_label, results)
    payload = build_related_files_payload(anchor, results)
    return {"message": message, "payload": payload}


def build_related_files_payload(
    anchor: dict,
    results: list[RelatedResult],
    *,
    hard_cap: int = RELATED_RENDER_HARD_CAP,
) -> dict:


    anchor_payload = {
        "file_id":       str(anchor.get("id") or ""),
        "file_name":     anchor.get("file_name") or "",
        "saved_name":    anchor.get("saved_name"),
        "relative_path": anchor.get("relative_path"),
    }

                                                                    
    capped = results[:max(0, int(hard_cap))]
    result_rows: list[dict] = []
    for r in capped:
        result_rows.append({
            "file_id":       r.file_id,
            "file_name":     r.file_name,
            "saved_name":    r.saved_name,
            "relative_path": r.relative_path,
            "confidence":    r.confidence(),
            "reasons": [
                {"code": rs.code, "label": rs.label, "weight": rs.weight}
                for rs in r.reasons
            ],
        })

    return {
        "anchor":  anchor_payload,
        "results": result_rows,
    }


def _resolve_anchor_row(
    rows: list[dict], anchor_text: str,
) -> Optional[dict]:


    needle = anchor_text.lower().strip()
    if not needle:
        return None

                     
    for row in rows:
        fn = (row.get("file_name") or "").lower()
        sn = (row.get("saved_name") or "").lower()
        if fn == needle or sn == needle:
            return row

                                                                
    for row in rows:
        fn = (row.get("file_name") or "").lower()
        sn = (row.get("saved_name") or "").lower()
        if needle in fn or needle in sn:
            return row

                         
    anchor_tokens = meaningful_tokens(anchor_text)
    if not anchor_tokens:
        return None
    for row in rows:
        cand = meaningful_tokens(row.get("file_name")) | meaningful_tokens(
            row.get("saved_name")
        )
        if anchor_tokens.issubset(cand):
            return row
    return None
