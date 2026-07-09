

from __future__ import annotations

import logging
import re
from typing import Optional

import vault_document_purpose as vp

logger = logging.getLogger(__name__)


TIER_PURPOSE          = 0
TIER_CATEGORY         = 1
TIER_ENTITY           = 2
TIER_TOPIC            = 3
TIER_TERM             = 4
TIER_DATE             = 5
TIER_SEMANTIC_STRONG  = 6             
TIER_SEMANTIC_MEDIUM  = 7             
TIER_SUMMARY          = 8
TIER_PREVIEW          = 9
TIER_CONTENT          = 10
TIER_FOLDER           = 11
TIER_FILENAME         = 12


_TIER_LABELS: dict[int, str] = {
    TIER_PURPOSE:         "purpose",
    TIER_CATEGORY:        "category",
    TIER_ENTITY:          "entity",
    TIER_TOPIC:           "topic",
    TIER_TERM:            "term",
    TIER_DATE:            "date",
    TIER_SEMANTIC_STRONG: "semantic",
    TIER_SEMANTIC_MEDIUM: "semantic",
    TIER_SUMMARY:         "summary",
    TIER_PREVIEW:         "preview",
    TIER_CONTENT:         "content",
    TIER_FOLDER:          "folder",
    TIER_FILENAME:        "filename",
}


_TIER_CONFIDENCE: dict[int, str] = {
    TIER_PURPOSE:         "strong",
    TIER_CATEGORY:        "strong",
    TIER_ENTITY:          "strong",
    TIER_TOPIC:           "medium",
    TIER_TERM:            "medium",
    TIER_DATE:            "medium",
    TIER_SEMANTIC_STRONG: "strong",
    TIER_SEMANTIC_MEDIUM: "medium",
    TIER_SUMMARY:         "medium",
    TIER_PREVIEW:         "medium",
    TIER_CONTENT:         "medium",
    TIER_FOLDER:          "weak",
    TIER_FILENAME:        "weak",
}


_PURPOSE_QUERY_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("saved login",          (vp.PURPOSE_SAVED_LOGIN_LIST,
                              vp.PURPOSE_CREDENTIAL_EXPORT)),
    ("saved logins",         (vp.PURPOSE_SAVED_LOGIN_LIST,
                              vp.PURPOSE_CREDENTIAL_EXPORT)),
    ("login list",           (vp.PURPOSE_SAVED_LOGIN_LIST,)),
    ("password list",        (vp.PURPOSE_SAVED_LOGIN_LIST,
                              vp.PURPOSE_CREDENTIAL_EXPORT)),
    ("password manager",     (vp.PURPOSE_CREDENTIAL_EXPORT,)),
    ("credential export",    (vp.PURPOSE_CREDENTIAL_EXPORT,)),
    ("credentials",          (vp.PURPOSE_SAVED_LOGIN_LIST,
                              vp.PURPOSE_CREDENTIAL_EXPORT,
                              vp.PURPOSE_CONFIG_SECRETS)),
    ("api keys",             (vp.PURPOSE_CONFIG_SECRETS,)),
    ("config",               (vp.PURPOSE_CONFIG_SECRETS,)),
    ("secrets file",         (vp.PURPOSE_CONFIG_SECRETS,)),
    ("dotenv",               (vp.PURPOSE_CONFIG_SECRETS,)),
    ("env file",             (vp.PURPOSE_CONFIG_SECRETS,)),
    ("application form",     (vp.PURPOSE_APPLICATION_FORM,)),
    ("insurance form",       (vp.PURPOSE_INSURANCE_FORM,)),
    ("tax form",             (vp.PURPOSE_GOVERNMENT_LEGAL,)),
    ("government document",  (vp.PURPOSE_GOVERNMENT_LEGAL,)),
    ("legal document",       (vp.PURPOSE_GOVERNMENT_LEGAL,)),
)


_CATEGORY_QUERY_HINTS: tuple[tuple[str, str], ...] = (
    ("travel",      "travel"),
    ("finance",     "finance"),
    ("financial",   "finance"),
    ("tax",         "tax"),
    ("taxes",       "tax"),
    ("legal",       "legal"),
    ("medical",     "medical"),
    ("health",      "medical"),
    ("education",   "education"),
    ("insurance",   "insurance"),
    ("identity",    "identity"),
    ("id document", "identity"),
    ("security",    "security"),
    ("login",       "security"),
    ("credential",  "security"),
)


_TOPIC_QUERY_HINTS: tuple[str, ...] = (
    "travel", "finance", "taxes", "identity", "legal", "medical",
    "insurance", "credentials", "education", "real_estate",
)


_DECRYPT_BYTE_CAP = 200_000


def _maybe_query_embedding(query: str) -> Optional[list[float]]:


    if not query or not query.strip():
        return None
    try:
        import vault_embedding as ve
        return ve.generate_embedding(query)
    except Exception:
                                                                   
                                                             
        return None


def search_vault_understanding(
    vault_id: str,
    query: str,
    key: Optional[bytes] = None,
    limit: int = 10,
) -> dict:


    query_str = (query or "").strip()
    if not query_str:
        return {
            "results":        [],
            "pending_count":  0,
            "total_scanned":  0,
            "query_terms":    [],
        }

    query_low = query_str.lower()
    query_tokens = _tokenize_query(query_low)
    purpose_hints = _purpose_hints_from_query(query_low)
    category_hints = _category_hints_from_query(query_low)
    topic_hints = _topic_hints_from_query(query_low)
    date_hint = _date_hint_from_query(query_str)

    rows = _fetch_search_rows(vault_id)

                                                                
    query_vector = _maybe_query_embedding(query_str) if rows else None
                                                           
                                                              
    embedded_count = sum(
        1 for r in rows
        if r.get("embedding_status") == "ready"
        and r.get("embedding_vector_decoded")
    )
    pending_embedding_count = sum(
        1 for r in rows
        if r.get("embedding_status") in ("pending", "processing",
                                          "stale")
    )

    pending_count = sum(
        1 for r in rows
        if (r.get("understanding_status") or "")
        in ("pending", "processing", "stale")
    )
                                                                 
                                                                  
    stale_count = sum(
        1 for r in rows
        if (r.get("understanding_status") or "") == "stale"
    )

    matched: dict[str, dict] = {}
    for r in rows:
        match = _score_row(
            row=r,
            query_low=query_low,
            query_tokens=query_tokens,
            purpose_hints=purpose_hints,
            category_hints=category_hints,
            topic_hints=topic_hints,
            date_hint=date_hint,
            key=key,
            query_vector=query_vector,
        )
        if match is None:
            continue
        file_id = str(r.get("file_id") or "")
        if not file_id:
            continue
                                                             
                                                                    
        understanding_status = (
            r.get("understanding_status") or ""
        ).lower()
        embedding_status = (r.get("embedding_status") or "").lower()
        is_semantic_match = match.get("tier") in (
            TIER_SEMANTIC_STRONG, TIER_SEMANTIC_MEDIUM,
        )
                                                                
                                                                   
        stale_understanding = understanding_status == "stale"
        stale_embedding = (
            embedding_status == "stale" and is_semantic_match
        )
        if stale_understanding or stale_embedding:
            tier = int(match.get("tier") or TIER_FILENAME)
            if tier <= TIER_CONTENT:
                match["confidence"] = "weak"
                match["is_stale"] = True
                base_reason = str(match.get("match_reason") or "").rstrip()
                if base_reason and "(being refreshed)" not in base_reason:
                    match["match_reason"] = (
                        f"{base_reason} (being refreshed)"
                    )
                                                             
                                                                
        try:
            archive_reason = _maybe_archive_reason(
                row=r, match=match,
                query_low=query_low, query_tokens=query_tokens,
            )
            if archive_reason:
                match["match_reason"] = archive_reason
                match["is_archive_match"] = True
        except Exception:
                                                            
                                                                 
            pass

                                                               
        if match.get("is_archive_match"):
            try:
                details = _maybe_archive_match_details(
                    row=r,
                    query_low=query_low,
                    query_tokens=query_tokens,
                )
                if details and details.get("inner_matches"):
                    match["archive_match_details"] = details
            except Exception:
                                                                
                                                                
                pass

        existing = matched.get(file_id)
        if existing is None or match["tier"] < existing["tier"]:
            matched[file_id] = match

                                                   
    confidence_order = {"strong": 0, "medium": 1, "weak": 2}
    ranked = sorted(
        matched.values(),
        key=lambda m: (
            int(m.get("tier") or TIER_FILENAME),
            confidence_order.get(m.get("confidence") or "weak", 2),
            (m.get("saved_name") or m.get("file_name") or "").lower(),
        ),
    )

    if limit and limit > 0:
        ranked = ranked[: int(limit)]

    return {
        "results":       ranked,
        "pending_count": pending_count,
        "stale_count":   stale_count,
                                                                  
                                                                 
        "embedded_count":         embedded_count,
        "pending_embedding_count": pending_embedding_count,
        "semantic_available":     query_vector is not None,
        "total_scanned":          len(rows),
        "query_terms":            query_tokens,
    }


def explain_match_reason(result: dict) -> str:


    if not isinstance(result, dict):
        return ""
    return str(result.get("match_reason") or "").strip()


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokenize_query(query_low: str) -> list[str]:


    stops = {
        "a", "an", "the", "of", "to", "in", "on", "for", "and",
        "or", "with", "about", "any", "all", "show", "find",
        "list", "files", "file", "document", "documents",
        "from", "my", "me", "i", "do", "have",
    }
    seen: set[str] = set()
    out: list[str] = []
    for tok in _TOKEN_RE.findall(query_low):
        if tok in stops:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _purpose_hints_from_query(query_low: str) -> list[str]:
                                                                
                                                               
    normalised = query_low.replace("-", " ")
    purposes: list[str] = []
    for phrase, candidates in _PURPOSE_QUERY_HINTS:
        if phrase in normalised:
            for p in candidates:
                if p not in purposes:
                    purposes.append(p)
    return purposes


def _category_hints_from_query(query_low: str) -> list[str]:
    cats: list[str] = []
    for phrase, cat in _CATEGORY_QUERY_HINTS:
        if phrase in query_low and cat not in cats:
            cats.append(cat)
    return cats


def _topic_hints_from_query(query_low: str) -> list[str]:
    topics: list[str] = []
    for t in _TOPIC_QUERY_HINTS:
        if t in query_low and t not in topics:
            topics.append(t)
    return topics


_DATE_QUERY_RE = re.compile(
    r"\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})\b"
)


def _date_hint_from_query(query: str) -> Optional[str]:
    m = _DATE_QUERY_RE.search(query)
    if m:
        return m.group(0)
    return None


def _score_row(
    *,
    row: dict,
    query_low: str,
    query_tokens: list[str],
    purpose_hints: list[str],
    category_hints: list[str],
    topic_hints: list[str],
    date_hint: Optional[str],
    key: Optional[bytes],
    query_vector: Optional[list[float]] = None,
) -> Optional[dict]:


    file_id = str(row.get("file_id") or "")
    file_name = row.get("file_name") or ""
    saved_name = row.get("saved_name") or ""
    relative_path = row.get("relative_path") or ""
    purpose = row.get("document_purpose") or ""
    purpose_label = row.get("purpose_label") or ""
    topics = _safe_list(row.get("topics_jsonb"))
    entities = _safe_dict(row.get("entities_jsonb"))
    dates = _safe_list(row.get("dates_jsonb"))
    categories = _safe_list(row.get("detected_categories_jsonb"))
    terms = _safe_list(row.get("searchable_terms_jsonb"))

    def _base(extra: dict) -> dict:
        out = {
            "file_id":       file_id,
            "file_name":     file_name,
            "saved_name":    saved_name or None,
            "relative_path": relative_path or None,
            "mime_type":     row.get("content_type"),
            "asset_type":    row.get("asset_type") or "file",
            "purpose":       purpose or None,
            "purpose_label": purpose_label or None,
        }
        out.update(extra)
        return out

                                
    if purpose_hints and purpose and purpose in purpose_hints:
        label = purpose_label or purpose
        return _base({
            "tier":         TIER_PURPOSE,
            "match_type":   _TIER_LABELS[TIER_PURPOSE],
            "match_reason": f"purpose match: {label}",
            "confidence":   _TIER_CONFIDENCE[TIER_PURPOSE],
        })

                                 
    if category_hints and categories:
        hit = next(
            (c for c in categories if c in category_hints), None,
        )
        if hit:
            return _base({
                "tier":         TIER_CATEGORY,
                "match_type":   _TIER_LABELS[TIER_CATEGORY],
                "match_reason": f"category match: {hit}",
                "confidence":   _TIER_CONFIDENCE[TIER_CATEGORY],
            })

                                                  
    names = entities.get("names") if isinstance(entities, dict) else None
    if isinstance(names, list) and names:
                                                                    
                                                               
        hit_name = _find_entity_match(names, query_low, query_tokens)
        if hit_name:
            return _base({
                "tier":         TIER_ENTITY,
                "match_type":   _TIER_LABELS[TIER_ENTITY],
                "match_reason": f"entity match: {hit_name}",
                "confidence":   _TIER_CONFIDENCE[TIER_ENTITY],
            })
    email_domains = (
        entities.get("email_domains")
        if isinstance(entities, dict) else None
    )
    if isinstance(email_domains, list):
        for d in email_domains:
            if not isinstance(d, str):
                continue
            d_low = d.lower()
            if any(tok in d_low for tok in query_tokens):
                return _base({
                    "tier":         TIER_ENTITY,
                    "match_type":   _TIER_LABELS[TIER_ENTITY],
                    "match_reason": f"email-domain match: {d}",
                    "confidence":   _TIER_CONFIDENCE[TIER_ENTITY],
                })

                         
    if topic_hints and topics:
        hit = next(
            (t for t in topics if t in topic_hints), None,
        )
        if hit:
            return _base({
                "tier":         TIER_TOPIC,
                "match_type":   _TIER_LABELS[TIER_TOPIC],
                "match_reason": f"topic match: {hit}",
                "confidence":   _TIER_CONFIDENCE[TIER_TOPIC],
            })

                                    
    if terms and query_tokens:
        for term in terms:
            if not isinstance(term, str):
                continue
            term_low = term.lower()
            if term_low in query_tokens:
                return _base({
                    "tier":         TIER_TERM,
                    "match_type":   _TIER_LABELS[TIER_TERM],
                    "match_reason": f"term match: {term}",
                    "confidence":   _TIER_CONFIDENCE[TIER_TERM],
                })

                        
    if date_hint and dates:
        if date_hint in [str(d) for d in dates]:
            return _base({
                "tier":         TIER_DATE,
                "match_type":   _TIER_LABELS[TIER_DATE],
                "match_reason": f"date match: {date_hint}",
                "confidence":   _TIER_CONFIDENCE[TIER_DATE],
            })

                                                                
    if (
        query_vector is not None
                                                              
                                                                
        and row.get("embedding_status") in ("ready", "stale")
        and row.get("embedding_vector_decoded")
    ):
        from vault_embedding import (
            cosine_similarity,
            DEFAULT_STRONG_THRESHOLD,
            DEFAULT_MEDIUM_THRESHOLD,
        )
        sim = cosine_similarity(
            query_vector,
            row["embedding_vector_decoded"],
        )
        if sim >= DEFAULT_STRONG_THRESHOLD:
            return _base({
                "tier":         TIER_SEMANTIC_STRONG,
                "match_type":   _TIER_LABELS[TIER_SEMANTIC_STRONG],
                "match_reason": _semantic_reason(row, sim, "strong"),
                "confidence":   _TIER_CONFIDENCE[TIER_SEMANTIC_STRONG],
                "similarity":   round(float(sim), 4),
            })
        if sim >= DEFAULT_MEDIUM_THRESHOLD:
            return _base({
                "tier":         TIER_SEMANTIC_MEDIUM,
                "match_type":   _TIER_LABELS[TIER_SEMANTIC_MEDIUM],
                "match_reason": _semantic_reason(row, sim, "medium"),
                "confidence":   _TIER_CONFIDENCE[TIER_SEMANTIC_MEDIUM],
                "similarity":   round(float(sim), 4),
            })
                                                               

    if key is not None:
        summary_match = _decrypted_text_hit(
            row.get("summary_encrypted"), key, query_low,
        )
        if summary_match:
            return _base({
                "tier":         TIER_SUMMARY,
                "match_type":   _TIER_LABELS[TIER_SUMMARY],
                "match_reason": (
                    f"summary mentions '{summary_match}'"
                ),
                "confidence":   _TIER_CONFIDENCE[TIER_SUMMARY],
            })
        preview_match = _decrypted_text_hit(
            row.get("safe_preview_encrypted"), key, query_low,
        )
        if preview_match:
            return _base({
                "tier":         TIER_PREVIEW,
                "match_type":   _TIER_LABELS[TIER_PREVIEW],
                "match_reason": (
                    f"preview mentions '{preview_match}'"
                ),
                "confidence":   _TIER_CONFIDENCE[TIER_PREVIEW],
            })
        if row.get("extracted_text") and (
            row.get("extracted_text_encrypted")
        ):
            content_match = _decrypted_text_hit(
                row.get("extracted_text"), key, query_low,
            )
            if content_match:
                return _base({
                    "tier":         TIER_CONTENT,
                    "match_type":   _TIER_LABELS[TIER_CONTENT],
                    "match_reason": (
                        f"file content mentions '{content_match}'"
                    ),
                    "confidence":   _TIER_CONFIDENCE[TIER_CONTENT],
                })

                                    
    if relative_path:
        rp_low = relative_path.lower()
        if query_low and (
            query_low in rp_low
            or any(tok in rp_low for tok in query_tokens)
        ):
            return _base({
                "tier":         TIER_FOLDER,
                "match_type":   _TIER_LABELS[TIER_FOLDER],
                "match_reason": f"folder match: {relative_path}",
                "confidence":   _TIER_CONFIDENCE[TIER_FOLDER],
            })

                                                 
    name_low = (saved_name or file_name or "").lower()
    if name_low and (
        query_low in name_low
        or any(tok in name_low for tok in query_tokens)
    ):
        return _base({
            "tier":         TIER_FILENAME,
            "match_type":   _TIER_LABELS[TIER_FILENAME],
            "match_reason": (
                f"filename match: {saved_name or file_name}"
            ),
            "confidence":   _TIER_CONFIDENCE[TIER_FILENAME],
        })

    return None


def _find_entity_match(
    names: list, query_low: str, query_tokens: list[str],
) -> Optional[str]:


    if not isinstance(names, list):
        return None
    for n in names:
        if not isinstance(n, str):
            continue
        n_low = n.lower()
        if not n_low:
            continue
        if query_low in n_low or n_low in query_low:
            return n
    if query_tokens:
        for n in names:
            if not isinstance(n, str):
                continue
            n_low = n.lower()
            if all(tok in n_low for tok in query_tokens):
                return n
        for n in names:
            if not isinstance(n, str):
                continue
            n_low = n.lower()
            if n_low in query_tokens:
                return n
    return None


def _decrypted_text_hit(
    ciphertext: Optional[str],
    key: bytes,
    query_low: str,
) -> Optional[str]:


    if not ciphertext or not query_low:
        return None
    try:
        from vault_core import decrypt_message
        plain = decrypt_message(ciphertext, key)
    except Exception:
        return None
    if not plain:
        return None
    snippet = plain[:_DECRYPT_BYTE_CAP].lower()
    if query_low in snippet:
                                                               
                                                                   
        return query_low
    return None


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _fetch_search_rows(vault_id: str) -> list[dict]:


    from psycopg2.extras import RealDictCursor

    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
                u.id            AS file_id,
                u.file_name,
                u.saved_name,
                u.relative_path,
                u.content_type,
                u.asset_type,
                u.extracted_text,
                u.extracted_text_encrypted,
                v.status                     AS understanding_status,
                v.document_purpose,
                v.purpose_label,
                v.summary_encrypted,
                v.safe_preview_encrypted,
                v.topics_jsonb,
                v.entities_jsonb,
                v.dates_jsonb,
                v.detected_categories_jsonb,
                v.searchable_terms_jsonb,
                v.archive_signals_jsonb,
                e.status                     AS embedding_status,
                e.embedding_model,
                e.embedding_dim,
                e.embedding_vector::text     AS embedding_vector_text
            FROM uploaded_files u
            LEFT JOIN vault_file_understanding v
                ON v.vault_id = u.vault_id
               AND v.file_id  = u.id::text
            LEFT JOIN vault_file_embeddings e
                ON e.vault_id = u.vault_id
               AND e.file_id  = u.id::text
            WHERE u.vault_id = %s
              AND u.upload_status = 'complete'
            ORDER BY u.created_at DESC
            """,
            (vault_id,),
        )
        out: list[dict] = []
        for row in cur.fetchall() or []:
            row["embedding_vector_decoded"] = _decode_pgvector(
                row.get("embedding_vector_text")
            )
            out.append(row)
        return out
    finally:
        conn.close()


def _decode_pgvector(text_form: Optional[str]) -> Optional[list[float]]:


    if not text_form:
        return None
    s = str(text_form).strip()
    if not s or not s.startswith("[") or not s.endswith("]"):
        return None
    body = s[1:-1]
    if not body.strip():
        return None
    try:
        return [float(tok) for tok in body.split(",") if tok.strip()]
    except Exception:
        return None


_ARCHIVE_REASON_TIERS = frozenset({
    TIER_PURPOSE,
    TIER_CATEGORY,
    TIER_ENTITY,
    TIER_TOPIC,
    TIER_TERM,
    TIER_SEMANTIC_STRONG,
    TIER_SEMANTIC_MEDIUM,
})


_CODE_QUERY_TOKENS = frozenset({
    "code", "script", "scripts", "source", "programs", "program",
})


_TOPIC_TO_CATEGORY: dict[str, str] = {
    "travel":      "travel",
    "finance":     "finance",
    "taxes":       "tax",
    "legal":       "legal",
    "medical":     "medical",
    "insurance":   "insurance",
    "identity":    "identity",
    "credentials": "security",
    "education":   "education",
    "real_estate": "real_estate",
}


def _maybe_archive_reason(
    *,
    row: dict,
    match: dict,
    query_low: str,
    query_tokens: list[str],
) -> Optional[str]:


    if not isinstance(match, dict):
        return None
    tier_val = match.get("tier")
    if tier_val is None:
        return None
                                                                 
                                                                
    tier = int(tier_val)

    sig = _safe_dict(row.get("archive_signals_jsonb"))
    if not sig:
        return None
    inner = sig.get("inner_files")
    if not isinstance(inner, list) or not inner:
        return None

                                                              
    if query_tokens and any(t in _CODE_QUERY_TOKENS for t in query_tokens):
        code_hits = [
            f for f in inner
            if isinstance(f, dict)
            and isinstance(f.get("language"), str)
            and f.get("language")
        ]
        if code_hits:
            return _format_archive_reason_code(code_hits)

                                                              
    if tier not in _ARCHIVE_REASON_TIERS:
        return None

                                                           
    entity_hits = _inner_files_matching_entity(
        inner, query_low=query_low, query_tokens=query_tokens,
    )
    if entity_hits:
        canonical_entity = _canonical_entity_match(
            entity_hits, query_low=query_low, query_tokens=query_tokens,
        )
        return _format_archive_reason_entity(
            entity_hits, canonical_entity or "this entity",
        )

                                                              
    cred_hits = [
        f for f in inner
        if isinstance(f, dict) and f.get("is_credential_bearing")
    ]
    if cred_hits:
        return _format_archive_reason_credentials(cred_hits)

                                                                
    topic_hits = _inner_files_matching_topic(
        inner, query_low=query_low,
    )
    if topic_hits:
        return _format_archive_reason_topic(topic_hits)

    return None


def _inner_files_matching_entity(
    inner: list, *, query_low: str, query_tokens: list[str],
) -> list[dict]:
    out: list[dict] = []
    for f in inner:
        if not isinstance(f, dict):
            continue
        names = f.get("entity_names")
        if not isinstance(names, list):
            continue
        if _find_entity_match(names, query_low, query_tokens):
            out.append(f)
    return out


def _canonical_entity_match(
    hits: list, *, query_low: str, query_tokens: list[str],
) -> Optional[str]:


    for f in hits:
        names = f.get("entity_names") if isinstance(f, dict) else None
        if not isinstance(names, list):
            continue
        m = _find_entity_match(names, query_low, query_tokens)
        if m:
            return m
    return None


def _inner_files_matching_topic(
    inner: list, *, query_low: str,
) -> list[dict]:
    if not query_low:
        return []
                                                             
    hint_topics = set(_topic_hints_from_query(query_low))
    category_hints = set(_category_hints_from_query(query_low))
    out: list[dict] = []
    for f in inner:
        if not isinstance(f, dict):
            continue
        topics = f.get("topics")
        if not isinstance(topics, list):
            continue
        for t in topics:
            tl = str(t).lower()
                                                                
                       
            if tl in hint_topics:
                out.append(f)
                break
                                                                 
                                                              
            category = _TOPIC_TO_CATEGORY.get(tl, tl)
            if category in category_hints:
                out.append(f)
                break
                                                             
                             
            if tl in query_low:
                out.append(f)
                break
    return out


def _format_archive_reason_entity(hits: list, canonical: str) -> str:
    n = len(hits)
    if n == 1:
        path = str(hits[0].get("path") or "an inner file").strip()
        return (
            f"archive content match: {path} mentions {canonical}"
        )
    return (
        f"archive content match: {n} inner files mention {canonical}"
    )


def _format_archive_reason_credentials(hits: list) -> str:
    n = len(hits)
    if n == 1:
        path = str(hits[0].get("path") or "an inner file").strip()
        return (
            f"archive content match: {path} appears to contain "
            "saved-login records"
        )
    return (
        f"archive content match: {n} inner files appear to "
        "contain saved-login records"
    )


def _format_archive_reason_topic(hits: list) -> str:
    n = len(hits)
    if n == 1:
        f = hits[0]
        path = str(f.get("path") or "an inner file").strip()
        topics = f.get("topics") or []
        topic_label = str(topics[0]).replace("_", " ") if topics else ""
        if topic_label:
            return (
                f"archive content match: {path} is about {topic_label}"
            )
        return f"archive content match: {path} matches your query"
    return (
        f"archive content match: {n} inner files match your query"
    )


def _format_archive_reason_code(hits: list) -> str:
    n = len(hits)
    if n == 1:
        f = hits[0]
        path = str(f.get("path") or "an inner file").strip()
        lang = str(f.get("language") or "code").strip() or "code"
        return (
            f"archive content match: {path} contains {lang} code"
        )
    return (
        f"archive content match: {n} inner code files in the archive"
    )


_INNER_KIND_ENTITY      = "entity"
_INNER_KIND_CREDENTIALS = "credentials"
_INNER_KIND_CODE        = "code"
_INNER_KIND_TOPIC       = "topic"


_MAX_INNER_MATCHES_SHIPPED = 10


def _maybe_archive_match_details(
    *,
    row: dict,
    query_low: str,
    query_tokens: list[str],
) -> Optional[dict]:


    sig = _safe_dict(row.get("archive_signals_jsonb"))
    if not sig:
        return None
    inner = sig.get("inner_files")
    if not isinstance(inner, list) or not inner:
        return None

    want_code = bool(
        query_tokens
        and any(t in _CODE_QUERY_TOKENS for t in query_tokens)
    )

    hint_topics    = set(_topic_hints_from_query(query_low or ""))
    category_hints = set(_category_hints_from_query(query_low or ""))

    matches: list[dict] = []

    for f in inner:
        if not isinstance(f, dict):
            continue
        path = str(f.get("path") or "").strip()
        if not path:
            continue

                                                              
        if want_code:
            lang = f.get("language")
            if isinstance(lang, str) and lang:
                matches.append({
                    "path":       path,
                    "reason":     f"contains {lang} code",
                    "kind":       _INNER_KIND_CODE,
                    "confidence": "medium",
                })
                continue

                                                                
        names = f.get("entity_names")
        if isinstance(names, list) and names:
            hit = _find_entity_match(
                names, query_low or "", query_tokens or [],
            )
            if hit:
                matches.append({
                    "path":       path,
                    "reason":     f"mentions {hit}",
                    "kind":       _INNER_KIND_ENTITY,
                    "confidence": "strong",
                })
                continue

                                                                 
        if f.get("is_credential_bearing"):
            credential_hint = (
                "security" in category_hints
                or "credentials" in hint_topics
                or bool(_purpose_hints_from_query(query_low or ""))
            )
            if credential_hint:
                matches.append({
                    "path":       path,
                    "reason":     (
                        "appears to contain saved-login records"
                    ),
                    "kind":       _INNER_KIND_CREDENTIALS,
                    "confidence": "strong",
                })
                continue

                                                              
        topics = f.get("topics")
        if isinstance(topics, list) and topics:
            topic_label = None
            for t in topics:
                tl = str(t).lower()
                if tl in hint_topics:
                    topic_label = tl
                    break
                category = _TOPIC_TO_CATEGORY.get(tl, tl)
                if category in category_hints:
                    topic_label = tl
                    break
                if query_low and tl in query_low:
                    topic_label = tl
                    break
            if topic_label:
                                                             
                                                           
                display = topic_label.replace("_", " ")
                matches.append({
                    "path":       path,
                    "reason":     f"is about {display}",
                    "kind":       _INNER_KIND_TOPIC,
                    "confidence": "medium",
                })
                continue

    if not matches:
        return None

    total = len(matches)
    shipped = matches[:_MAX_INNER_MATCHES_SHIPPED]
    return {
        "inner_matches":       shipped,
        "total_inner_matches": total,
    }


def _semantic_reason(row: dict, similarity: float, level: str) -> str:


    purpose_label = (row.get("purpose_label") or "").strip()
    categories = _safe_list(row.get("detected_categories_jsonb"))
    topics = _safe_list(row.get("topics_jsonb"))

    phrase = ""
    if purpose_label:
        phrase = purpose_label
    elif categories:
                                                                
        first = str(categories[0]).replace("_", " ").strip()
        phrase = f"{first} document"
    elif topics:
        first = str(topics[0]).replace("_", " ").strip()
        phrase = f"document about {first}"
    else:
        phrase = "similar meaning to your query"

    if level == "strong":
        return f"semantic match: this file appears to be a {phrase}"
    return f"semantic match: this file may be related ({phrase})"


def _safe_list(value) -> list:


    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            import json
            decoded = json.loads(value)
            if isinstance(decoded, list):
                return decoded
        except Exception:
            return []
    return []


def _safe_dict(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            import json
            decoded = json.loads(value)
            if isinstance(decoded, dict):
                return decoded
        except Exception:
            return {}
    return {}


def format_search_reply(
    *,
    query: str,
    results: list[dict],
    pending_count: int,
    stale_count: int = 0,
    pending_embedding_count: int = 0,
    semantic_available: bool = True,
) -> str:


    q = (query or "").strip() or "your query"
    stale_count = max(0, int(stale_count or 0))
    truly_pending = max(0, int(pending_count or 0) - stale_count)
    pending_emb = max(0, int(pending_embedding_count or 0))

    def _stale_note() -> str:
        return (
            f"{stale_count} file"
            f"{'s' if stale_count != 1 else ''} "
            "being re-analyzed (results may be slightly out of date)."
        )

    def _embedding_pending_note() -> str:
        return (
            f"{pending_emb} file"
            f"{'s' if pending_emb != 1 else ''} "
            "still being indexed for semantic search."
        )

    def _semantic_unavailable_note() -> str:
        return (
            "Semantic search is temporarily unavailable; falling "
            "back to exact / closed-set matches."
        )

    if not results:
        base = f"I didn't find any files about \"{q}\"."
        notes: list[str] = []
        if truly_pending:
                                                                
                                                                 
            notes.append(
                f"{truly_pending} file"
                f"{'s' if truly_pending != 1 else ''} "
                "are still being indexed — they may surface "
                "in this search once indexing completes."
            )
        if stale_count:
            notes.append(_stale_note())
        if pending_emb:
            notes.append(_embedding_pending_note())
        if not semantic_available:
            notes.append(_semantic_unavailable_note())
        if notes:
            base += "\n\nNote: " + " ".join(notes)
        return base

    n = len(results)
    lines = [
        f"I found {n} file{'s' if n != 1 else ''} about \"{q}\":",
    ]
    for i, r in enumerate(results, 1):
        display = (
            r.get("saved_name") or r.get("file_name") or "file"
        )
        reason = explain_match_reason(r)
        suffix = f" — {reason}" if reason else ""
        lines.append(f"{i}. {display}{suffix}")

    notes: list[str] = []
    if truly_pending:
        notes.append(
            f"{truly_pending} file"
            f"{'s' if truly_pending != 1 else ''} "
            "still being analyzed; some matches may not appear "
            "until that finishes."
        )
    if stale_count:
        notes.append(_stale_note())
    if pending_emb:
        notes.append(_embedding_pending_note())
    if not semantic_available:
        notes.append(_semantic_unavailable_note())
    if notes:
        lines.append("")
        lines.append("Note: " + " ".join(notes))

    return "\n".join(lines)
