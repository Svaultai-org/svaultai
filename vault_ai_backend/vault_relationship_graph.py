

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional


logger = logging.getLogger(__name__)


REL_SAME_PERSON               = "same_person"
REL_SAME_COMPANY              = "same_company"
REL_SAME_TRIP                 = "same_trip"
REL_SAME_FINANCIAL_ACCOUNT    = "same_financial_account"
REL_SAME_DOCUMENT_FAMILY      = "same_document_family"
REL_FRONT_BACK_PAIR           = "front_back_pair"
REL_DUPLICATE                 = "duplicate"
REL_NEAR_DUPLICATE            = "near_duplicate"
REL_SAME_IMPORT_BATCH         = "same_import_batch"
REL_SAME_FOLDER               = "same_folder"
REL_SEMANTIC_RELATED          = "semantic_related"
REL_ARCHIVE_CONTAINS_SIGNAL   = "archive_contains_signal"
REL_SUPPORTING_DOCUMENT       = "supporting_document"


RELATIONSHIP_TYPES: tuple[str, ...] = (
    REL_SAME_PERSON,
    REL_SAME_COMPANY,
    REL_SAME_TRIP,
    REL_SAME_FINANCIAL_ACCOUNT,
    REL_SAME_DOCUMENT_FAMILY,
    REL_FRONT_BACK_PAIR,
    REL_DUPLICATE,
    REL_NEAR_DUPLICATE,
    REL_SAME_IMPORT_BATCH,
    REL_SAME_FOLDER,
    REL_SEMANTIC_RELATED,
    REL_ARCHIVE_CONTAINS_SIGNAL,
    REL_SUPPORTING_DOCUMENT,
)


CONFIDENCE_MIN_PERSIST = 0.25


SEMANTIC_NEAR_DUPLICATE_THRESHOLD = 0.85
SEMANTIC_RELATED_THRESHOLD        = 0.55


_MAX_REASONS_PER_ROW = 4
_MAX_EVIDENCE_NAMES  = 8


_FRONT_BACK_SEGMENT_TOKENS: frozenset[str] = frozenset({
    "front", "back",
    "sidea", "sideb",                                       
    "page1", "page2",
})
_FRONT_BACK_FILLER_TOKENS: frozenset[str] = frozenset({
    "side", "page",
})
_FRONT_BACK_SEPARATOR_RE = re.compile(r"[\s_\-.]+")


def _make_decision(
    *,
    relationship_type: str,
    confidence: float,
    reasons: list[str],
    evidence: dict,
) -> Optional[dict]:


    if relationship_type not in RELATIONSHIP_TYPES:
        return None
    c = float(confidence)
    if c < CONFIDENCE_MIN_PERSIST:
        return None
    if c > 1.0:
        c = 1.0
    cleaned_reasons = []
    for r in reasons[:_MAX_REASONS_PER_ROW]:
        if not isinstance(r, str):
            continue
        s = r.strip()
        if s:
            cleaned_reasons.append(s)
    if not cleaned_reasons:
        return None
    return {
        "relationship_type": relationship_type,
        "confidence":        c,
        "reasons":           cleaned_reasons,
        "evidence":          _safe_evidence(evidence),
    }


def _safe_evidence(evidence: dict) -> dict:


    if not isinstance(evidence, dict):
        return {}
    allowed = {
        "shared_entity_names",
        "shared_topics",
        "shared_categories",
        "shared_doc_types",
        "embedding_cosine",
        "filename_pattern",
        "content_sha256_match",
        "import_id",
        "folder_path",
        "shared_email_domains",
        "archive_file_id",
        "inner_file_count",
    }
    out: dict[str, Any] = {}
    for k, v in evidence.items():
        if k not in allowed:
            continue
                                                               
                                                              
        if isinstance(v, list):
            out[k] = list(v)[:_MAX_EVIDENCE_NAMES]
        else:
            out[k] = v
    return out


def _shared_list_items(a, b) -> list[str]:


    if not isinstance(a, list) or not isinstance(b, list):
        return []
    b_lower = {str(x).lower() for x in b if isinstance(x, str)}
    seen: set[str] = set()
    out: list[str] = []
    for x in a:
        if not isinstance(x, str):
            continue
        lx = x.lower()
        if lx in b_lower and lx not in seen:
            seen.add(lx)
            out.append(x)
    return out


def _entities_names(facts: dict) -> list:
    e = facts.get("entities")
    if not isinstance(e, dict):
        return []
    names = e.get("names")
    return names if isinstance(names, list) else []


def _entities_email_domains(facts: dict) -> list:
    e = facts.get("entities")
    if not isinstance(e, dict):
        return []
    doms = e.get("email_domains")
    return doms if isinstance(doms, list) else []


def _signal_bag(facts: dict, key: str) -> dict:
    v = facts.get(key)
    return v if isinstance(v, dict) else {}


def _doc_types(facts: dict, signal_key: str) -> list:


    bag = _signal_bag(facts, signal_key)
    doc_types = bag.get("doc_types")
    return doc_types if isinstance(doc_types, list) else []


def _has_topic(facts: dict, topic: str) -> bool:
    topics = facts.get("topics")
    if not isinstance(topics, list):
        return False
    return topic.lower() in {str(t).lower() for t in topics}


def _split_filename_segments(file_name: Optional[str]) -> list[str]:


    if not file_name:
        return []
    stem = str(file_name).rsplit(".", 1)[0]
    return [s for s in _FRONT_BACK_SEPARATOR_RE.split(stem.lower()) if s]


def _filename_front_back_kind(file_name: Optional[str]) -> Optional[str]:


    segments = _split_filename_segments(file_name)
    if not segments:
        return None
                                                         
    for s in segments:
        if s in _FRONT_BACK_SEGMENT_TOKENS:
            return s
                                                   
                                    
    for i in range(len(segments) - 1):
        joined = segments[i] + segments[i + 1]
        if joined in _FRONT_BACK_SEGMENT_TOKENS:
            return joined
    return None


def _filename_stem_minus_frontback(file_name: Optional[str]) -> str:


    segments = _split_filename_segments(file_name)
    if not segments:
        return ""
    keep: list[str] = []
    skip_next = False
    for i, s in enumerate(segments):
        if skip_next:
            skip_next = False
            continue
        if s in _FRONT_BACK_SEGMENT_TOKENS:
            continue
                                                                   
        if (
            s in _FRONT_BACK_FILLER_TOKENS
            and i + 1 < len(segments)
            and (s + segments[i + 1]) in _FRONT_BACK_SEGMENT_TOKENS
        ):
            skip_next = True
            continue
        keep.append(s)
    return " ".join(keep)


def _detect_duplicate(a: dict, b: dict) -> Optional[dict]:

    ha = a.get("content_sha256")
    hb = b.get("content_sha256")
    if not ha or not hb:
        return None
    if str(ha).strip().lower() != str(hb).strip().lower():
        return None
    return _make_decision(
        relationship_type=REL_DUPLICATE,
        confidence=1.0,
        reasons=["identical file content (matching sha256)"],
        evidence={"content_sha256_match": True},
    )


def _detect_near_duplicate(a: dict, b: dict) -> Optional[dict]:


    va = a.get("embedding_vector")
    vb = b.get("embedding_vector")
    if not isinstance(va, list) or not isinstance(vb, list):
        return None
    if not va or not vb:
        return None
    try:
        from vault_embedding import cosine_similarity
        sim = cosine_similarity(va, vb)
    except Exception:
        return None
    if sim < SEMANTIC_NEAR_DUPLICATE_THRESHOLD:
        return None
    return _make_decision(
        relationship_type=REL_NEAR_DUPLICATE,
        confidence=min(1.0, 0.5 + sim / 2.0),
        reasons=[
            f"high semantic similarity ({round(sim, 2)})",
            "files appear to discuss the same topic almost identically",
        ],
        evidence={"embedding_cosine": round(float(sim), 4)},
    )


def _detect_semantic_related(a: dict, b: dict) -> Optional[dict]:
    va = a.get("embedding_vector")
    vb = b.get("embedding_vector")
    if not isinstance(va, list) or not isinstance(vb, list):
        return None
    if not va or not vb:
        return None
    try:
        from vault_embedding import cosine_similarity
        sim = cosine_similarity(va, vb)
    except Exception:
        return None
    if sim >= SEMANTIC_NEAR_DUPLICATE_THRESHOLD:
                                    
        return None
    if sim < SEMANTIC_RELATED_THRESHOLD:
        return None
    return _make_decision(
        relationship_type=REL_SEMANTIC_RELATED,
        confidence=min(0.7, 0.3 + sim / 2.0),
        reasons=[
            f"semantic similarity ({round(sim, 2)})",
            "files appear to discuss related topics",
        ],
        evidence={"embedding_cosine": round(float(sim), 4)},
    )


def _detect_same_person(a: dict, b: dict) -> Optional[dict]:
    shared = _shared_list_items(
        _entities_names(a), _entities_names(b),
    )
    if not shared:
        return None
                                                               
                                                                  
    a_id = _signal_bag(a, "identity_signals").get("any_present")
    b_id = _signal_bag(b, "identity_signals").get("any_present")
    identity_boost = bool(a_id or b_id)

    n = len(shared)
                                            
    base = 0.60 if n == 1 else 0.78
    if identity_boost:
        base = min(0.92, base + 0.10)

    return _make_decision(
        relationship_type=REL_SAME_PERSON,
        confidence=base,
        reasons=[f"same person name: {shared[0]}"] + (
            [f"and {n - 1} other shared name"
             f"{'s' if n - 1 != 1 else ''}"]
            if n > 1 else []
        ),
        evidence={"shared_entity_names": shared},
    )


def _detect_same_company(a: dict, b: dict) -> Optional[dict]:
                                                              
                                                                
    shared_domains = _shared_list_items(
        _entities_email_domains(a),
        _entities_email_domains(b),
    )
    if not shared_domains:
        return None
    return _make_decision(
        relationship_type=REL_SAME_COMPANY,
        confidence=0.65,
        reasons=[
            f"shared organisation domain: {shared_domains[0]}",
        ],
        evidence={"shared_email_domains": shared_domains},
    )


def _detect_same_trip(a: dict, b: dict) -> Optional[dict]:
    a_travel = _doc_types(a, "travel_signals")
    b_travel = _doc_types(b, "travel_signals")
    if not (a_travel and b_travel):
        return None
                                                              
                                                                
    shared_names = _shared_list_items(
        _entities_names(a), _entities_names(b),
    )
    union_types = sorted(set(a_travel) | set(b_travel))
    n_names = len(shared_names)
    base = 0.55 if not shared_names else 0.78
    return _make_decision(
        relationship_type=REL_SAME_TRIP,
        confidence=base,
        reasons=(
            [
                f"shared travel documents: {', '.join(union_types[:3])}",
            ]
            + (
                [f"shared destination / name: {shared_names[0]}"]
                if shared_names else []
            )
        ),
        evidence={
            "shared_doc_types": union_types,
            **(
                {"shared_entity_names": shared_names}
                if shared_names else {}
            ),
        },
    )


def _detect_same_financial_account(a: dict, b: dict) -> Optional[dict]:
    a_fin = _doc_types(a, "financial_signals")
    b_fin = _doc_types(b, "financial_signals")
    if not (a_fin and b_fin):
        return None
    shared_names = _shared_list_items(
        _entities_names(a), _entities_names(b),
    )
    if not shared_names:
                                                                
                                                  
        return None
    union_types = sorted(set(a_fin) | set(b_fin))
    return _make_decision(
        relationship_type=REL_SAME_FINANCIAL_ACCOUNT,
        confidence=0.72,
        reasons=[
            f"shared financial entity: {shared_names[0]}",
            f"both files include financial documents "
            f"({', '.join(union_types[:3])})",
        ],
        evidence={
            "shared_entity_names": shared_names,
            "shared_doc_types":    union_types,
        },
    )


def _detect_same_document_family(a: dict, b: dict) -> Optional[dict]:
    cats_a = a.get("detected_categories") or []
    cats_b = b.get("detected_categories") or []
    shared_cats = _shared_list_items(cats_a, cats_b)
    if not shared_cats:
        return None
                                        
    shared_topics = _shared_list_items(
        a.get("topics") or [], b.get("topics") or [],
    )
    if not shared_topics:
        return None
    base = 0.55
    return _make_decision(
        relationship_type=REL_SAME_DOCUMENT_FAMILY,
        confidence=base,
        reasons=[
            f"shared document category: {shared_cats[0]}",
            f"shared topic: {shared_topics[0]}",
        ],
        evidence={
            "shared_categories": shared_cats,
            "shared_topics":     shared_topics,
        },
    )


def _detect_front_back_pair(a: dict, b: dict) -> Optional[dict]:


    kind_a = _filename_front_back_kind(a.get("file_name"))
    kind_b = _filename_front_back_kind(b.get("file_name"))
    if not (kind_a and kind_b):
        return None
                                                           
                     
    if kind_a == kind_b:
        return None
    stem_a = _filename_stem_minus_frontback(a.get("file_name"))
    stem_b = _filename_stem_minus_frontback(b.get("file_name"))
    if not stem_a or stem_a != stem_b:
        return None
                                               
    a_id = _signal_bag(a, "identity_signals").get("any_present")
    b_id = _signal_bag(b, "identity_signals").get("any_present")
    identity_boost = bool(a_id or b_id)
    base = 0.82 if identity_boost else 0.70
    return _make_decision(
        relationship_type=REL_FRONT_BACK_PAIR,
        confidence=base,
        reasons=[
            "filename pattern suggests front/back pair of an ID",
        ] + (
            ["identity-document signals detected on at least one side"]
            if identity_boost else []
        ),
        evidence={
            "filename_pattern": f"{kind_a}/{kind_b}",
        },
    )


def _detect_same_import_batch(a: dict, b: dict) -> Optional[dict]:
    ia = a.get("import_id")
    ib = b.get("import_id")
    if not ia or not ib:
        return None
    if str(ia) != str(ib):
        return None
    return _make_decision(
        relationship_type=REL_SAME_IMPORT_BATCH,
        confidence=0.30,
        reasons=["both files arrived in the same import batch"],
        evidence={"import_id": str(ia)},
    )


def _detect_same_folder(a: dict, b: dict) -> Optional[dict]:
    fa = a.get("folder_path")
    fb = b.get("folder_path")
    if not fa or not fb:
        return None
    if str(fa) != str(fb):
        return None
    return _make_decision(
        relationship_type=REL_SAME_FOLDER,
        confidence=0.35,
        reasons=[f"same folder: {fa}"],
        evidence={"folder_path": str(fa)},
    )


def _detect_archive_contains_signal(
    a: dict, b: dict,
) -> Optional[dict]:


    for archive, other in ((a, b), (b, a)):
        sig = archive.get("archive_signals")
        if not isinstance(sig, dict):
            continue
        inner = sig.get("inner_files")
        if not isinstance(inner, list) or not inner:
            continue
                                                           
        inner_names: set[str] = set()
        inner_topics: set[str] = set()
        for f in inner:
            if not isinstance(f, dict):
                continue
            for n in (f.get("entity_names") or []):
                if isinstance(n, str):
                    inner_names.add(n)
            for t in (f.get("topics") or []):
                if isinstance(t, str):
                    inner_topics.add(t.lower())
        other_names = {
            str(x) for x in _entities_names(other) if isinstance(x, str)
        }
        other_topics = {
            str(t).lower() for t in (other.get("topics") or [])
            if isinstance(t, str)
        }
        shared_names = sorted(inner_names & other_names)
        shared_topics = sorted(inner_topics & other_topics)
        if not (shared_names or shared_topics):
            continue
        archive_id = archive.get("file_id")
        reasons: list[str] = []
        if shared_names:
            reasons.append(
                f"archive contains a file mentioning "
                f"{shared_names[0]}"
            )
        if shared_topics:
            reasons.append(
                f"archive contains a file about {shared_topics[0]}"
            )
        return _make_decision(
            relationship_type=REL_ARCHIVE_CONTAINS_SIGNAL,
            confidence=0.55,
            reasons=reasons,
            evidence={
                "archive_file_id":     str(archive_id or ""),
                "shared_entity_names": shared_names,
                "shared_topics":       shared_topics,
                "inner_file_count":    int(
                    sig.get("inner_file_count") or 0
                ),
            },
        )
    return None


def _detect_supporting_document(a: dict, b: dict) -> Optional[dict]:


    form_purposes = {
        "application_form",
        "insurance_form",
        "government_legal_financial",
    }
    a_purpose = (a.get("document_purpose") or "").lower()
    b_purpose = (b.get("document_purpose") or "").lower()
    a_is_form = a_purpose in form_purposes
    b_is_form = b_purpose in form_purposes
    if not (a_is_form ^ b_is_form):
                                                          
                                  
        return None
    form, other = (a, b) if a_is_form else (b, a)
    other_id_signals = _signal_bag(other, "identity_signals")
    if not other_id_signals.get("any_present"):
        return None
                                                              
    shared_names = _shared_list_items(
        _entities_names(form), _entities_names(other),
    )
    confidence = 0.55 if shared_names else 0.40
    reasons = [
        "supporting identity document for an application / "
        "insurance form",
    ]
    if shared_names:
        reasons.append(f"shared name: {shared_names[0]}")
    evidence: dict[str, Any] = {
        "shared_doc_types": (
            other_id_signals.get("doc_types") or []
        ),
    }
    if shared_names:
        evidence["shared_entity_names"] = shared_names
    return _make_decision(
        relationship_type=REL_SUPPORTING_DOCUMENT,
        confidence=confidence,
        reasons=reasons,
        evidence=evidence,
    )


DETECTORS: tuple = (
    _detect_duplicate,
    _detect_near_duplicate,
    _detect_semantic_related,
    _detect_same_person,
    _detect_same_company,
    _detect_same_trip,
    _detect_same_financial_account,
    _detect_same_document_family,
    _detect_front_back_pair,
    _detect_archive_contains_signal,
    _detect_supporting_document,
    _detect_same_import_batch,
    _detect_same_folder,
)


def find_relationships_in_files(files: list[dict]) -> list[dict]:


    out: list[dict] = []
    n = len(files)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = files[i], files[j]
            ida = str(a.get("file_id") or "")
            idb = str(b.get("file_id") or "")
            if not ida or not idb or ida == idb:
                continue
            if ida > idb:
                a, b = b, a
                ida, idb = idb, ida
            for detector in DETECTORS:
                try:
                    decision = detector(a, b)
                except Exception:
                                                              
                                 
                    logger.exception(
                        "[relgraph] detector failed file_a=%s file_b=%s",
                        ida, idb,
                    )
                    continue
                if not decision:
                    continue
                decision = dict(decision)
                decision["file_a_id"] = ida
                decision["file_b_id"] = idb
                out.append(decision)
    return out


RELATIONSHIP_ANALYSIS_VERSION: int = 1


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _json_dump(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


def upsert_relationship(
    *,
    vault_id: str,
    decision: dict,
    analysis_version: int = 1,
) -> None:


    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vault_file_relationships (
                vault_id, file_a_id, file_b_id,
                relationship_type, confidence,
                reasons_jsonb, evidence_jsonb,
                analysis_version,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s,
                %s, %s,
                %s::jsonb, %s::jsonb,
                %s,
                %s, %s
            )
            ON CONFLICT (
                vault_id, file_a_id, file_b_id, relationship_type
            ) DO UPDATE SET
                confidence       = EXCLUDED.confidence,
                reasons_jsonb    = EXCLUDED.reasons_jsonb,
                evidence_jsonb   = EXCLUDED.evidence_jsonb,
                analysis_version = EXCLUDED.analysis_version,
                updated_at       = EXCLUDED.updated_at
            """,
            (
                vault_id,
                decision["file_a_id"], decision["file_b_id"],
                decision["relationship_type"],
                float(decision["confidence"]),
                _json_dump(decision.get("reasons") or []),
                _json_dump(decision.get("evidence") or {}),
                int(analysis_version),
                now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_relationships_for_file(
    vault_id: str, file_id: str, *, limit: int = 50,
) -> list[dict]:


    from psycopg2.extras import RealDictCursor
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT relationship_id, vault_id,
                   file_a_id, file_b_id,
                   relationship_type, confidence,
                   reasons_jsonb, evidence_jsonb,
                   created_at, updated_at
            FROM vault_file_relationships
            WHERE vault_id = %s
              AND (file_a_id = %s OR file_b_id = %s)
            ORDER BY confidence DESC, updated_at DESC
            LIMIT %s
            """,
            (vault_id, file_id, file_id, int(limit)),
        )
        return list(cur.fetchall() or [])
    finally:
        conn.close()


def load_file_facts_for_vault(vault_id: str) -> list[dict]:


    from psycopg2.extras import RealDictCursor
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
                u.id              AS file_id,
                u.file_name,
                u.relative_path   AS folder_path,
                u.import_id,
                u.content_sha256,
                v.document_purpose,
                v.purpose_label,
                v.topics_jsonb            AS topics,
                v.entities_jsonb          AS entities,
                v.detected_categories_jsonb AS detected_categories,
                v.travel_signals_jsonb    AS travel_signals,
                v.financial_signals_jsonb AS financial_signals,
                v.legal_signals_jsonb     AS legal_signals,
                v.identity_signals_jsonb  AS identity_signals,
                v.archive_signals_jsonb   AS archive_signals,
                e.embedding_vector::text  AS embedding_vector_text
            FROM uploaded_files u
            LEFT JOIN vault_file_understanding v
              ON v.vault_id = u.vault_id AND v.file_id = u.id::text
            LEFT JOIN vault_file_embeddings e
              ON e.vault_id = u.vault_id AND e.file_id = u.id::text
             AND e.status = 'ready'
            WHERE u.vault_id = %s
              AND u.upload_status = 'complete'
            """,
            (vault_id,),
        )
        rows = list(cur.fetchall() or [])
    finally:
        conn.close()

                                                             
    try:
        from vault_understanding_search import _decode_pgvector
    except Exception:
        _decode_pgvector = lambda x: None              
    for row in rows:
        text_form = row.pop("embedding_vector_text", None)
        row["embedding_vector"] = _decode_pgvector(text_form)
        row["file_id"] = str(row["file_id"]) if row.get("file_id") else ""
    return rows


def build_relationships_for_vault(vault_id: str) -> dict:


    files = load_file_facts_for_vault(vault_id)
    decisions = find_relationships_in_files(files)
    written = 0
    for d in decisions:
        try:
            upsert_relationship(
                vault_id=vault_id, decision=d,
                analysis_version=RELATIONSHIP_ANALYSIS_VERSION,
            )
            written += 1
        except Exception:
            logger.exception(
                "[relgraph] upsert failed pair=%s,%s type=%s",
                d.get("file_a_id"), d.get("file_b_id"),
                d.get("relationship_type"),
            )
    return {
        "vault_id":          vault_id,
        "file_count":        len(files),
        "pairs_considered":  max(0, len(files) * (len(files) - 1) // 2),
        "decisions_found":   len(decisions),
        "rows_written":      written,
    }


def cleanup_relationships_for_file(
    vault_id: str, file_id: str,
) -> dict:


    if not vault_id or not file_id:
        return {"vault_id": vault_id, "file_id": file_id, "deleted": 0}
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM vault_file_relationships
            WHERE vault_id = %s
              AND (file_a_id = %s OR file_b_id = %s)
            """,
            (vault_id, file_id, file_id),
        )
        deleted = cur.rowcount or 0
        conn.commit()
    finally:
        conn.close()
    return {
        "vault_id":  vault_id,
        "file_id":   file_id,
        "deleted":   int(deleted),
    }


def cleanup_stale_relationships_for_vault(
    vault_id: str,
) -> dict:


    if not vault_id:
        return {
            "vault_id":           vault_id,
            "deleted_orphans":    0,
            "stale_version_rows": 0,
        }
    conn = _get_db()
    try:
        cur = conn.cursor()
                                                          
                                                      
        cur.execute(
            """
            DELETE FROM vault_file_relationships AS r
            WHERE r.vault_id = %s
              AND (
                NOT EXISTS (
                    SELECT 1 FROM uploaded_files AS f
                    WHERE f.id::text = r.file_a_id
                      AND f.vault_id = %s
                )
                OR
                NOT EXISTS (
                    SELECT 1 FROM uploaded_files AS f
                    WHERE f.id::text = r.file_b_id
                      AND f.vault_id = %s
                )
              )
            """,
            (vault_id, vault_id, vault_id),
        )
        deleted_orphans = cur.rowcount or 0

                                                           
        cur.execute(
            """
            SELECT COUNT(*) FROM vault_file_relationships
            WHERE vault_id = %s
              AND COALESCE(analysis_version, 0) < %s
            """,
            (vault_id, int(RELATIONSHIP_ANALYSIS_VERSION)),
        )
        row = cur.fetchone()
        stale_version_rows = int(row[0] or 0) if row else 0

        conn.commit()
    finally:
        conn.close()
    return {
        "vault_id":            vault_id,
        "deleted_orphans":     int(deleted_orphans),
        "stale_version_rows":  stale_version_rows,
    }
