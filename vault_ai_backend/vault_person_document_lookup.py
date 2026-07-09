

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional


logger = logging.getLogger(__name__)


DOC_KIND_ID_CARD     = "id_card"
DOC_KIND_PASSPORT    = "passport"
DOC_KIND_VISA        = "visa"
DOC_KIND_DRIVERS     = "drivers_license"
DOC_KIND_GENERIC     = "any"

_DOC_KIND_PATTERNS = (
    (DOC_KIND_PASSPORT,
     r"\bpassport(?:s)?\b"),
    (DOC_KIND_VISA,
     r"\bvisa(?:s)?\b"),
    (DOC_KIND_DRIVERS,
     r"\bdriver'?s?\s+licen[cs]e\b|\bdl\b"),
    (DOC_KIND_ID_CARD,
     r"\bid\s*card\b|\bid\s+document\b|\bidentification\b|\bnational\s+id\b"),
    (DOC_KIND_GENERIC,
     r"\bdocument(?:s)?\b|\bfiles?\b|\bpapers?\b"),
)


_DOC_KIND_TO_PURPOSES: dict[str, tuple[str, ...]] = {
    DOC_KIND_ID_CARD:  ("id_document", "passport", "visa"),
    DOC_KIND_PASSPORT: ("passport", "id_document"),
    DOC_KIND_VISA:     ("visa", "id_document"),
    DOC_KIND_DRIVERS:  ("id_document",),
    DOC_KIND_GENERIC:  (
        "id_document", "passport", "visa",
        "financial_document", "tax_document",
        "legal_document", "contract", "insurance_form",
        "medical_document", "government_legal_financial",
    ),
}


_TRIGGER_PATTERNS = (
                                   
    r"\bshow\s+me\s+.*\b(id|passport|visa|driver'?s?\s+licen[cs]e|"
    r"document|file|paper)s?\b.*\b(?:with\s+name|for|named|of)\b",
                              
    r"\b(find|search\s+for|look\s+for)\b\s+.*\b(id|passport|visa|"
    r"driver'?s?\s+licen[cs]e|document|file|paper)s?\b\s+(?:for|of|"
    r"with\s+name|named|belonging\s+to)\b",
                           
    r"\bshow\b\s+.*\b(passport|visa|id|driver'?s?\s+licen[cs]e|"
    r"document|file|paper)s?\b\s+(?:for|of|named|with\s+name|"
    r"belonging\s+to)\b",
                              
    r"\b(?:do\s+i\s+have|is\s+there)\b\s+.*\b(passport|visa|id|"
    r"driver'?s?\s+licen[cs]e|document|file)s?\b",
                            
    r"\bfind\b\s+(?:any\s+)?documents?\s+(?:for|of|belonging\s+to|"
    r"about)\s+",
                                              
                                                        
    r"\b(find|show|get)\b(?:\s+me)?\s+.*\b(photo\s+)?(id|passport|"
    r"visa|driver'?s?\s+licen[cs]e|document|file|paper)s?\b.*"
    r"\b(?:the\s+)?owner\b",
                                                          
                                                             
    r"\b(id|passport|visa|driver'?s?\s+licen[cs]e|document|file|"
    r"paper|photo\s+id)\b[\w\s]{0,30}?\bbelonging\s+to\s+",
                                                                 
                                                         
    r"\b\w{2,}(?:\s+\w{2,})*'s\s+(passport|visa|id|driver'?s?\s+"
    r"licen[cs]e|document|file|paper)s?\b",
                                  
    r"\bfind\b\s+(?:any\s+)?(?:document|file|paper)s?\s+containing\s+",
                          
    r"\b(photo\s+id|photo\s+identification|photo\s+identity)\b\s+"
    r"(?:for|of|with\s+name|belonging\s+to|where|whose|the\s+owner)",
)


_NAME_EXTRACTION_PATTERNS = (
                                  
                                
    r"\bthe\s+owner\s+(?:of\s+(?:the\s+)?\w+\s+)?is\s+"
    r"([A-Za-z][A-Za-z\.\-' ]{1,60}?)(?:\s*\?|$|\.|,)",
    r"\bowner\s+(?:of\s+(?:the\s+)?\w+\s+)?is\s+"
    r"([A-Za-z][A-Za-z\.\-' ]{1,60}?)(?:\s*\?|$|\.|,)",
    r"\b(?:whose|where\s+the)\s+owner\s+is\s+"
    r"([A-Za-z][A-Za-z\.\-' ]{1,60}?)(?:\s*\?|$|\.|,)",
    r"\bwith\s+name\s+([A-Za-z][A-Za-z\.\-' ]{1,60}?)(?:\s*\?|$|\.)",
    r"\bnamed\s+([A-Za-z][A-Za-z\.\-' ]{1,60}?)(?:\s*\?|$|\.)",
    r"\bcontaining\s+([A-Za-z][A-Za-z\.\-' ]{1,60}?)(?:\s*\?|$|\.|,)",
    r"\bbelonging\s+to\s+([A-Za-z][A-Za-z\.\-' ]{1,60}?)(?:\s*\?|$|\.)",
    r"\bfor\s+([A-Z][A-Za-z\.\-']*(?:\s+[A-Za-z][A-Za-z\.\-']*){0,4}?)(?:\s*\?|$|\.|'s\b)",
    r"\bof\s+([A-Z][A-Za-z\.\-']*(?:\s+[A-Za-z][A-Za-z\.\-']*){0,4}?)(?:\s*\?|$|\.|'s\b)",
                               
    r"\b([A-Z][A-Za-z\.\-']*(?:\s+[A-Z][A-Za-z\.\-']*){0,3})'s\b",
)


@dataclass(frozen=True)
class PersonDocumentQuery:

    person_name:   str
    doc_kind_hint: str


def _norm_name(raw: str) -> str:


    if not raw:
        return ""
    s = re.sub(r"\s+", " ", raw).strip(" ?.,!\"'")
                                                        
    s = re.sub(
        r"\s+(in|on|from|please|now|today|asap)$",
        "", s, flags=re.IGNORECASE,
    )
    return s


def detect_person_document_query(
    message: str,
) -> Optional[PersonDocumentQuery]:


    if not isinstance(message, str) or not message.strip():
        return None
    text = message.strip()
    text_l = text.lower()

    trigger_hit = False
    for pat in _TRIGGER_PATTERNS:
        if re.search(pat, text_l):
            trigger_hit = True
            break
    if not trigger_hit:
        return None

                                                        
    doc_kind = DOC_KIND_GENERIC
    for kind, pat in _DOC_KIND_PATTERNS:
        if re.search(pat, text_l):
            doc_kind = kind
            break

                              
    name = ""
    for pat in _NAME_EXTRACTION_PATTERNS:
        m = re.search(pat, text)
        if m:
            candidate = _norm_name(m.group(1))
            if candidate:
                name = candidate
                break

    if not name:
        return None
                                               
    if name.lower() in {"the", "a", "an", "any", "some", "this", "that"}:
        return None
    if len(name) < 2 or len(name) > 80:
        return None

    return PersonDocumentQuery(
        person_name=name,
        doc_kind_hint=doc_kind,
    )


def _coverage_for_vault(vault_id: str) -> dict:
    try:
        from vault_analysis import analysis_coverage_for_vault
        cov = analysis_coverage_for_vault(vault_id) or {}
        total = int(cov.get("total") or 0)
        analyzed = int(cov.get("analyzed") or 0)
        pending = int(cov.get("pending") or 0)
        processing = int(cov.get("processing") or 0)
        return {
            "total":     total,
            "analyzed":  analyzed,
            "pending":   pending,
            "processing": processing,
            "is_complete": (
                total > 0 and pending == 0 and processing == 0
            ),
        }
    except Exception:
        return {"total": 0, "analyzed": 0, "is_complete": False}


def _name_tokens(name: str) -> list[str]:
    return [
        t for t in re.split(r"\s+", (name or "").strip().lower())
        if t and len(t) >= 2
    ]


def _query_matching_files(
    vault_id: str, purposes: tuple[str, ...],
) -> list[dict]:
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT u.file_id,
                       u.document_purpose,
                       u.purpose_label,
                       u.entities_jsonb,
                       f.file_name,
                       f.saved_name,
                       f.relative_path
                FROM vault_file_understanding u
                JOIN uploaded_files f ON f.id = u.file_id
                WHERE u.vault_id = %s
                  AND u.status = 'ready'
                  AND u.document_purpose = ANY(%s)
                ORDER BY u.purpose_confidence DESC NULLS LAST,
                         f.created_at DESC
                LIMIT 200
                """,
                (vault_id, list(purposes)),
            )
            return cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "[PERSON-LOOKUP] query failed vault=%s",
            (vault_id or "")[:8] + "...",
        )
        return []


def _file_matches_name(row: dict, name_tokens: list[str]) -> bool:


    if not name_tokens:
        return False
    haystack: list[str] = []
    haystack.append(str(row.get("file_name") or "").lower())
    haystack.append(str(row.get("saved_name") or "").lower())
    haystack.append(str(row.get("relative_path") or "").lower())
    ents = row.get("entities_jsonb") or {}
    if isinstance(ents, dict):
        for cat in ("people", "organizations"):
            for t in (ents.get(cat) or []):
                if isinstance(t, str):
                    haystack.append(t.lower())
    blob = " | ".join(haystack)
    return all(tok in blob for tok in name_tokens)


def _search_identity_columns(
    vault_id: str, name_tokens: list[str],
) -> list[dict]:
    if not name_tokens:
        return []
    try:
        from main import list_uploaded_files
        rows = list_uploaded_files(vault_id) or []
    except Exception:
        return []
    out: list[dict] = []
    for r in rows:
        name = str(r.get("saved_name") or r.get("file_name") or "")
        folder = str(r.get("relative_path") or "")
        blob = f"{name} {folder}".lower()
        if all(tok in blob for tok in name_tokens):
            out.append({
                "file_id":       str(r.get("id") or ""),
                "file_name":     name,
                "saved_name":    str(r.get("saved_name") or ""),
                "relative_path": folder,
                "match_source":  "identity",
            })
            if len(out) >= 50:
                break
    return out


def _search_extracted_text(
    vault_id: str, key: bytes, name_tokens: list[str],
) -> list[dict]:
    if not name_tokens:
        return []
    try:
        from main import _list_uploaded_files_for_credential_search
        rows = (
            _list_uploaded_files_for_credential_search(vault_id, key)
            or []
        )
    except Exception:
        return []
    out: list[dict] = []
    for r in rows:
        text = r.get("extracted_text")
        if not isinstance(text, str) or not text:
            continue
        blob = text.lower()
        if all(tok in blob for tok in name_tokens):
            out.append({
                "file_id":       str(r.get("id") or ""),
                "file_name":     str(r.get("file_name") or ""),
                "saved_name":    str(r.get("saved_name") or ""),
                "relative_path": str(r.get("relative_path") or ""),
                "match_source":  "extracted_text",
            })
            if len(out) >= 50:
                break
    return out


def _search_content_chunks(
    vault_id: str, key: bytes, name_tokens: list[str],
) -> list[dict]:
    if not name_tokens or not (
        isinstance(key, (bytes, bytearray)) and len(key) == 32
    ):
        return []
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        from vault_core import decrypt_message as _decrypt
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT c.file_id, c.encrypted_chunk_text,
                       f.file_name, f.saved_name, f.relative_path
                FROM vault_content_chunks c
                JOIN uploaded_files f ON f.id = c.file_id
                WHERE c.vault_id = %s
                  AND c.chunk_text_encrypted = TRUE
                ORDER BY f.created_at DESC
                LIMIT 400
                """,
                (vault_id,),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return []
    seen_files: set[str] = set()
    out: list[dict] = []
    for r in rows:
        fid = str(r.get("file_id") or "")
        if fid in seen_files:
            continue
        enc = r.get("encrypted_chunk_text")
        if not enc:
            continue
        try:
            plain = _decrypt(enc, key)
        except Exception:
            continue
        if not plain:
            continue
        blob = plain.lower()
        if all(tok in blob for tok in name_tokens):
            seen_files.add(fid)
            out.append({
                "file_id":       fid,
                "file_name":     str(r.get("file_name") or ""),
                "saved_name":    str(r.get("saved_name") or ""),
                "relative_path": str(r.get("relative_path") or ""),
                "match_source":  "content_chunk",
            })
            if len(out) >= 50:
                break
    return out


def _search_any_understanding(
    vault_id: str, name_tokens: list[str],
) -> list[dict]:
    if not name_tokens:
        return []
    try:
        from psycopg2.extras import RealDictCursor
        from main import get_db
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT u.file_id,
                       u.document_purpose,
                       u.purpose_label,
                       u.entities_jsonb,
                       f.file_name,
                       f.saved_name,
                       f.relative_path
                FROM vault_file_understanding u
                JOIN uploaded_files f ON f.id = u.file_id
                WHERE u.vault_id = %s
                  AND u.status   = 'ready'
                ORDER BY f.created_at DESC
                LIMIT 400
                """,
                (vault_id,),
            )
            rows = cur.fetchall() or []
        finally:
            conn.close()
    except Exception:
        return []
    out: list[dict] = []
    for r in rows:
        if _file_matches_name(r, name_tokens):
            out.append({
                "file_id":       str(r.get("file_id") or ""),
                "file_name":     str(r.get("file_name") or ""),
                "saved_name":    str(r.get("saved_name") or ""),
                "relative_path": str(r.get("relative_path") or ""),
                "match_source":  "understanding_entities",
            })
            if len(out) >= 50:
                break
    return out


def _gather_broad_matches(
    vault_id: str, key: bytes, name_tokens: list[str],
) -> list[dict]:


    seen: set[str] = set()
    combined: list[dict] = []
    for searcher in (
        _search_identity_columns,
        _search_extracted_text,
        _search_content_chunks,
        _search_any_understanding,
    ):
        try:
            if searcher in (
                _search_extracted_text, _search_content_chunks,
            ):
                hits = searcher(vault_id, key, name_tokens)
            else:
                hits = searcher(vault_id, name_tokens)
        except Exception:
            logger.exception(
                "[PERSON-LOOKUP] broad source %s failed vault=%s",
                searcher.__name__,
                (vault_id or "")[:8] + "...",
            )
            hits = []
        for h in hits:
            fid = str(h.get("file_id") or "")
            if not fid or fid in seen:
                continue
            seen.add(fid)
            combined.append(h)
    return combined


def _format_doc_kind_label(doc_kind: str) -> str:
    return {
        DOC_KIND_PASSPORT: "passport",
        DOC_KIND_VISA:     "visa",
        DOC_KIND_DRIVERS:  "driver's license",
        DOC_KIND_ID_CARD:  "ID document",
        DOC_KIND_GENERIC:  "document",
    }.get(doc_kind, "document")


def _coverage_sentence(coverage: dict) -> str:
    total = int(coverage.get("total") or 0)
    analyzed = int(coverage.get("analyzed") or 0)
    is_complete = bool(coverage.get("is_complete"))
    if total <= 0 or is_complete:
        return ""
    return (
        f" I've reviewed {analyzed} of {total} files so far, "
        "so this may be incomplete."
    )


def handle_person_document_query(
    *,
    vault_id: str,
    key: Optional[bytes],
    person_name: str,
    doc_kind_hint: str,
) -> str:


    from vault_chat_safety_sanitizer import (
        SENTENCE_VAULT_UNAVAILABLE,
        SENTENCE_VAULT_LOCKED,
    )

    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return SENTENCE_VAULT_LOCKED

    purposes = _DOC_KIND_TO_PURPOSES.get(
        doc_kind_hint, _DOC_KIND_TO_PURPOSES[DOC_KIND_GENERIC],
    )

    coverage = _coverage_for_vault(vault_id)

    try:
        candidates = _query_matching_files(vault_id, purposes)
    except Exception:
        candidates = []

    name_tokens = _name_tokens(person_name)
    matches: list[dict] = []
    if candidates:
        for row in candidates:
            if _file_matches_name(row, name_tokens):
                matches.append(row)

                                                                  
    if not matches:
        broad = _gather_broad_matches(vault_id, key, name_tokens)
        if broad:
            matches = broad

    kind_label = _format_doc_kind_label(doc_kind_hint)
    cov_line = _coverage_sentence(coverage)

    if matches:
        if len(matches) == 1:
            m = matches[0]
            display = str(
                m.get("saved_name")
                or m.get("file_name")
                or "this file"
            )
            return (
                f"I found {kind_label_with_article(kind_label)} "
                f"that appears to match {person_name}: "
                f"{display}. I can open it for you."
            )
                           
        names = [
            str(m.get("saved_name") or m.get("file_name") or "")
            for m in matches[:3]
        ]
        names = [n for n in names if n]
        joined = ", ".join(names) if names else "several files"
        return (
            f"I found {len(matches)} files that appear to match "
            f"{person_name}: {joined}. Tell me which one you "
            "want me to open."
        )

                                                                  
    if coverage.get("is_complete"):
        return (
            f"I couldn't find {kind_label_with_article(kind_label)} "
            f"for {person_name} in your vault."
        )
    total = int(coverage.get("total") or 0)
    analyzed = int(coverage.get("analyzed") or 0)
    if total > 0 and analyzed < total:
        return (
            f"I'm checking the vault for "
            f"{kind_label_with_article(kind_label)} for "
            f"{person_name}. I've searched {analyzed} of "
            f"{total} files so far and I'm continuing through "
            "the remaining files. I'll update you as soon as the "
            "scan completes."
        )
    return (
        f"I couldn't find {kind_label_with_article(kind_label)} "
        f"for {person_name} in the files I can currently read."
        f"{cov_line}"
    )


def kind_label_with_article(kind_label: str) -> str:

    if not kind_label:
        return "a document"
    return ("an " if kind_label[0].lower() in "aeiou" else "a ") + kind_label


__all__ = [
    "DOC_KIND_ID_CARD",
    "DOC_KIND_PASSPORT",
    "DOC_KIND_VISA",
    "DOC_KIND_DRIVERS",
    "DOC_KIND_GENERIC",
    "PersonDocumentQuery",
    "detect_person_document_query",
    "handle_person_document_query",
]
