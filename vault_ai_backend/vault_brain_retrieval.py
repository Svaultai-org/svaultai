

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from vault_evidence_bundle import (
    EvidenceBundle, EvidenceChunk, empty_bundle,
)


logger = logging.getLogger(__name__)


try:
    from vault_config import brain as _brain_cfg
    _b = _brain_cfg()
    DEFAULT_TOP_K                   = _b.retrieval_top_k
    DEFAULT_MIN_SIMILARITY          = _b.min_similarity
    DEFAULT_LEXICAL_FALLBACK_LIMIT  = _b.lexical_fallback_limit
    DEFAULT_NARROW_TOP_K            = _b.narrow_retrieval_top_k
    DEFAULT_BROAD_TOP_K             = _b.broad_retrieval_top_k
    DEFAULT_SUMMARY_MAX_CHUNKS      = _b.summary_max_chunks
    DEFAULT_MAX_FILES_PER_QUERY     = _b.max_files_per_query
    DEFAULT_MAX_CHUNKS_PER_FILE     = _b.max_chunks_per_file_per_query
    DEFAULT_DIVERSIFY_BY_FILE       = _b.diversify_by_file
    DEFAULT_CONTINUATION_PAGE_SIZE  = _b.deep_continuation_page_size
except Exception:
    DEFAULT_TOP_K                   = 8
    DEFAULT_MIN_SIMILARITY          = 0.20                                          
    DEFAULT_LEXICAL_FALLBACK_LIMIT  = 20
    DEFAULT_NARROW_TOP_K            = 8
    DEFAULT_BROAD_TOP_K             = 32
    DEFAULT_SUMMARY_MAX_CHUNKS      = 40
    DEFAULT_MAX_FILES_PER_QUERY     = 12
    DEFAULT_MAX_CHUNKS_PER_FILE     = 4
    DEFAULT_DIVERSIFY_BY_FILE       = True
    DEFAULT_CONTINUATION_PAGE_SIZE  = 16

                                                                         
RETRIEVAL_MODE_SEMANTIC       = "semantic"
RETRIEVAL_MODE_LEXICAL        = "lexical_fallback"
RETRIEVAL_MODE_CHUNK_LEXICAL  = "chunk_text_lexical"
RETRIEVAL_MODE_CREDENTIAL_MEMORY = "credential_memory_scan"
RETRIEVAL_MODE_EMPTY          = "no_matches"

                                                                   
RETRIEVAL_BREADTH_NARROW        = "narrow"
RETRIEVAL_BREADTH_BROAD         = "broad"
RETRIEVAL_BREADTH_SUMMARY       = "summary"
RETRIEVAL_BREADTH_CONTINUATION  = "continuation"


EmbedFn = Callable[[str], Awaitable[Optional[list[float]]]]

_SECRET_FIELD_KEYS = frozenset({
    "password",
    "pin",
    "api_key",
    "token",
    "secret",
    "private_key",
    "mnemonic",
    "recovery_code",
})


def _credential_record_has_secret(record: dict) -> bool:
    fields = record.get("fields")
    if not isinstance(fields, dict):
        return False
    return any(bool(fields.get(key)) for key in _SECRET_FIELD_KEYS)


_FILE_META_KEYS = (
    "file_name",
    "saved_name",
    "relative_path",
    "content_type",
    "asset_type",
    "content_sha256",
    "file_size",
    "created_at",
    "needs_naming",
    "detected_service",
    "detected_type",
)


def _file_meta_from_tail(values) -> dict:
    meta = {}
    for key, value in zip(_FILE_META_KEYS, values or ()):
        if value is not None:
            meta[key] = value
    return meta


def _strict_credential_file_verified(
    *,
    file_id: str,
    plaintext: str,
    extraction_source: str = "",
    file_meta: Optional[dict] = None,
) -> bool:
    try:
        from vault_inventory import verified_credential_files_report
    except Exception:
        return False
    if not plaintext or not str(plaintext).strip():
        return False
    meta = dict(file_meta or {})
    content_type = str(
        meta.get("content_type") or meta.get("mime_type") or "text/plain"
    )
    asset_type = str(meta.get("asset_type") or "file")
    source = str(extraction_source or "").lower()
    if source == "ocr":
        if not meta.get("asset_type"):
            asset_type = "image"
        if not meta.get("content_type") and not meta.get("mime_type"):
            content_type = "image/png"
    elif source == "archive":
        if not meta.get("asset_type"):
            asset_type = "archive"
        if not meta.get("content_type") and not meta.get("mime_type"):
            content_type = "application/zip"
    row = {
        "id":               str(file_id),
        "file_name":        str(
            meta.get("file_name")
            or meta.get("saved_name")
            or file_id
        ),
        "saved_name":       str(meta.get("saved_name") or ""),
        "relative_path":    str(meta.get("relative_path") or ""),
        "content_type":     content_type,
        "mime_type":        content_type,
        "asset_type":       asset_type,
        "detected_service": str(meta.get("detected_service") or ""),
        "detected_type":    str(meta.get("detected_type") or ""),
        "extracted_text":   plaintext,
        "content_sha256":   str(meta.get("content_sha256") or ""),
        "file_size":        meta.get("file_size") or len(plaintext or ""),
        "created_at":       meta.get("created_at"),
        "needs_naming":     bool(meta.get("needs_naming") or False),
    }
    report = verified_credential_files_report([row], limit=1)
    return bool(report.get("matches"))


async def retrieve_evidence(
    *,
    vault_id: str,
    query: str,
    key: bytes,
    embed_fn: EmbedFn,
    coverage: dict,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    breadth: str = RETRIEVAL_BREADTH_NARROW,
    excluded_file_ids: Optional[tuple] = None,
    excluded_chunk_ids: Optional[tuple] = None,
    diversify_by_file: Optional[bool] = None,
    max_files_per_query: Optional[int] = None,
    max_chunks_per_file: Optional[int] = None,
) -> EvidenceBundle:


    if not vault_id or not query or not query.strip():
        return empty_bundle(query=query, vault_id=vault_id,
                            coverage=coverage)

                                                                 
    effective_top_k, eff_max_files, eff_max_chunks_per_file, \
        eff_diversify = _resolve_breadth_tuning(
            breadth=breadth, top_k=top_k,
            diversify_by_file=diversify_by_file,
            max_files_per_query=max_files_per_query,
            max_chunks_per_file=max_chunks_per_file,
        )

    excluded_file_set  = frozenset(excluded_file_ids or ())
    excluded_chunk_set = frozenset(str(c) for c in (excluded_chunk_ids or ()))

                                                               
    is_continuation = (breadth == RETRIEVAL_BREADTH_CONTINUATION)

                         
    try:
        vec = await embed_fn(query.strip())
    except Exception:
                                   
        logger.warning("[BRAIN-RETRIEVE] embed call raised vault=%s",
                       _short(vault_id))
        vec = None

                                                                      
    rows: list[tuple] = []
    mode = RETRIEVAL_MODE_EMPTY
    if vec is not None:
                                                                 
                                                            
        wants_per_file_diversity = (
            eff_diversify
            and breadth in (
                RETRIEVAL_BREADTH_BROAD,
                RETRIEVAL_BREADTH_SUMMARY,
                RETRIEVAL_BREADTH_CONTINUATION,
            )
        )
        if wants_per_file_diversity:
                                                                   
                                                                 
            candidate_limit = max(
                effective_top_k * 4,
                eff_max_files * max(eff_max_chunks_per_file, 1) * 4,
                200,
            )
            rows = _semantic_search_per_file(
                vault_id=vault_id, vector=vec,
                per_file_cap=max(eff_max_chunks_per_file, 1),
                candidate_limit=candidate_limit,
                min_similarity=min_similarity,
                excluded_chunk_ids=excluded_chunk_set,
                excluded_file_ids=(
                    excluded_file_set if is_continuation else frozenset()
                ),
            )
        else:
                                                                
            oversample_target = max(
                effective_top_k * 4,
                eff_max_files * max(eff_max_chunks_per_file, 1) * 2,
            )
            rows = _semantic_search(
                vault_id=vault_id, vector=vec,
                top_k=oversample_target,
                min_similarity=min_similarity,
                excluded_chunk_ids=excluded_chunk_set,
            )
        if rows:
            mode = RETRIEVAL_MODE_SEMANTIC

                                                                
    if not rows:
        rows = _chunk_text_lexical_search(
            vault_id=vault_id, query=query.strip(),
            key=key, limit=max(effective_top_k * 4,
                               DEFAULT_LEXICAL_FALLBACK_LIMIT),
            excluded_chunk_ids=excluded_chunk_set,
        )
        if rows:
            mode = RETRIEVAL_MODE_CHUNK_LEXICAL

    if not rows:
        rows = _lexical_search(
            vault_id=vault_id, query=query.strip(),
            limit=DEFAULT_LEXICAL_FALLBACK_LIMIT,
            excluded_chunk_ids=excluded_chunk_set,
        )
        if rows:
            mode = RETRIEVAL_MODE_LEXICAL

                                                                  
    if excluded_file_set and not is_continuation:
        rows = [r for r in rows if str(r[1]) not in excluded_file_set]
                                                              
                                                               
    if excluded_chunk_set:
        rows = [r for r in rows if str(r[0]) not in excluded_chunk_set]

    if not rows:
        return EvidenceBundle(
            query=query, vault_id=vault_id,
            chunks=(), matching_file_ids=(),
            coverage_at_time=dict(coverage or {}),
            retrieval_mode=(
                RETRIEVAL_MODE_EMPTY if mode == RETRIEVAL_MODE_EMPTY
                else mode
            ),
            excluded_unsupported=int(coverage.get("unsupported", 0)),
            excluded_failed=int(coverage.get("failed", 0)),
            excluded_pending=int(coverage.get("pending", 0)),
        )

                                                                  
    from vault_core import decrypt_message
    decrypted: list[EvidenceChunk] = []
    for row in rows:
        chunk_id, file_id, chunk_index, encrypted_text, char_start, \
            char_end, extraction_source, similarity = row
                                                                   
                                                                    
        if isinstance(encrypted_text, _AlreadyPlaintext):
            plaintext = encrypted_text.text
        else:
            try:
                plaintext = decrypt_message(encrypted_text, key)
            except Exception:
                logger.warning(
                    "[BRAIN-RETRIEVE] decrypt failed vault=%s file=%s",
                    _short(vault_id), _short(str(file_id)),
                )
                continue
        decrypted.append(EvidenceChunk(
            chunk_id=str(chunk_id),
            file_id=str(file_id),
            chunk_index=int(chunk_index),
            text=plaintext,
            extraction_source=str(extraction_source),
            score=float(similarity),
            char_start=int(char_start),
            char_end=int(char_end),
        ))

                                                               
    if eff_diversify:
        diversified = _diversify_across_files(
            decrypted,
            max_files=eff_max_files,
            max_chunks_per_file=eff_max_chunks_per_file,
        )
    else:
        diversified = decrypted
    final = diversified[:effective_top_k]

    seen_files: list[str] = []
    for ch in final:
        if ch.file_id not in seen_files:
            seen_files.append(ch.file_id)

    return EvidenceBundle(
        query=query,
        vault_id=vault_id,
        chunks=tuple(final),
        matching_file_ids=tuple(seen_files),
        coverage_at_time=dict(coverage or {}),
        retrieval_mode=mode,
        excluded_unsupported=int(coverage.get("unsupported", 0)),
        excluded_failed=int(coverage.get("failed", 0)),
        excluded_pending=int(coverage.get("pending", 0)),
    )


async def retrieve_credential_evidence(
    *,
    vault_id: str,
    query: str,
    key: bytes,
    coverage: dict,
    limit: Optional[int] = None,
    **_,
) -> EvidenceBundle:


    if not vault_id:
        return empty_bundle(query=query, vault_id=vault_id,
                            coverage=coverage)
    try:
        from extractor import extract_multiple_credentials
        from vault_core import get_db, decrypt_message
    except Exception:
        logger.exception(
            "[BRAIN-RETRIEVE] credential memory imports failed vault=%s",
            _short(vault_id),
        )
        return empty_bundle(
            query=query, vault_id=vault_id, coverage=coverage,
            error="credential_memory_import_failed",
        )

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.chunk_id, c.file_id, c.chunk_index,
                   c.encrypted_chunk_text,
                   c.char_start, c.char_end, c.extraction_source,
                   uf.file_name, uf.saved_name, uf.relative_path,
                   uf.content_type, uf.asset_type, uf.content_sha256,
                   uf.file_size, uf.created_at, uf.needs_naming,
                   uf.detected_service, uf.detected_type
            FROM vault_content_chunks c
            LEFT JOIN uploaded_files uf
              ON uf.id::text = c.file_id::text
             AND uf.vault_id::text = c.vault_id::text
            WHERE c.vault_id = %s
            ORDER BY c.file_id, c.chunk_index ASC
            """,
            (vault_id,),
        )
        raw_rows = cur.fetchall() or []
    except Exception:
        logger.exception(
            "[BRAIN-RETRIEVE] credential memory select failed vault=%s",
            _short(vault_id),
        )
        return empty_bundle(
            query=query, vault_id=vault_id, coverage=coverage,
            error="credential_memory_select_failed",
        )
    finally:
        conn.close()

    chunks: list[EvidenceChunk] = []
    seen_files: list[str] = []
    seen_file_ids: set[str] = set()
    for row in raw_rows:
        chunk_id, file_id, chunk_index, encrypted_text, char_start, \
            char_end, extraction_source = row[:7]
        file_meta = _file_meta_from_tail(row[7:])
        try:
            plaintext = decrypt_message(encrypted_text, key)
        except Exception:
            continue
        if not _strict_credential_file_verified(
            file_id=str(file_id),
            plaintext=plaintext,
            extraction_source=str(extraction_source),
            file_meta=file_meta,
        ):
            continue
        fid = str(file_id)
        seen_file_ids.add(fid)
        if fid not in seen_files:
            seen_files.append(fid)
        chunks.append(EvidenceChunk(
            chunk_id=str(chunk_id),
            file_id=fid,
            chunk_index=int(chunk_index),
            text=plaintext,
            extraction_source=str(extraction_source),
            score=0.95,
            char_start=int(char_start),
            char_end=int(char_end),
        ))
        if limit is not None and len(chunks) >= int(limit):
            break

                                                                 
    if limit is None or len(chunks) < int(limit):
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, extracted_text,
                       extracted_text_encrypted,
                       COALESCE(extracted_text_source, 'extracted_text'),
                       file_name, saved_name, relative_path,
                       content_type, asset_type, content_sha256,
                       file_size, created_at, needs_naming,
                       detected_service, detected_type
                FROM uploaded_files
                WHERE vault_id::text = %s
                  AND extracted_text_status = 'available'
                  AND extracted_text IS NOT NULL
                ORDER BY id::text ASC
                """,
                (vault_id,),
            )
            extracted_rows = cur.fetchall() or []
        except Exception:
            logger.exception(
                "[BRAIN-RETRIEVE] credential extracted-text select "
                "failed vault=%s",
                _short(vault_id),
            )
            extracted_rows = []
        finally:
            conn.close()

        for row in extracted_rows:
            file_id, stored_text, encrypted, extraction_source = row[:4]
            file_meta = _file_meta_from_tail(row[4:])
            fid = str(file_id)
            if fid in seen_file_ids:
                continue
            try:
                plaintext = (
                    decrypt_message(stored_text, key)
                    if encrypted else str(stored_text or "")
                )
            except Exception:
                continue
            if not _strict_credential_file_verified(
                file_id=fid,
                plaintext=plaintext,
                extraction_source=str(extraction_source),
                file_meta=file_meta,
            ):
                continue
            seen_file_ids.add(fid)
            if fid not in seen_files:
                seen_files.append(fid)
            chunks.append(EvidenceChunk(
                chunk_id=f"extracted:{fid}",
                file_id=fid,
                chunk_index=0,
                text=plaintext,
                extraction_source=str(extraction_source or "extracted_text"),
                score=0.93,
                char_start=0,
                char_end=len(plaintext or ""),
            ))
            if limit is not None and len(chunks) >= int(limit):
                break

    if not chunks:
        return EvidenceBundle(
            query=query,
            vault_id=vault_id,
            chunks=(),
            matching_file_ids=(),
            coverage_at_time=dict(coverage or {}),
            retrieval_mode=RETRIEVAL_MODE_EMPTY,
            excluded_unsupported=int(coverage.get("unsupported", 0)),
            excluded_failed=int(coverage.get("failed", 0)),
            excluded_pending=int(coverage.get("pending", 0)),
        )

    return EvidenceBundle(
        query=query,
        vault_id=vault_id,
        chunks=tuple(chunks),
        matching_file_ids=tuple(seen_files),
        coverage_at_time=dict(coverage or {}),
        retrieval_mode=RETRIEVAL_MODE_CREDENTIAL_MEMORY,
        excluded_unsupported=int(coverage.get("unsupported", 0)),
        excluded_failed=int(coverage.get("failed", 0)),
        excluded_pending=int(coverage.get("pending", 0)),
    )


def _resolve_breadth_tuning(
    *, breadth, top_k, diversify_by_file,
    max_files_per_query, max_chunks_per_file,
):


    if breadth == RETRIEVAL_BREADTH_BROAD:
        eff_top_k = DEFAULT_BROAD_TOP_K
    elif breadth == RETRIEVAL_BREADTH_SUMMARY:
        eff_top_k = DEFAULT_SUMMARY_MAX_CHUNKS
    elif breadth == RETRIEVAL_BREADTH_CONTINUATION:
        eff_top_k = DEFAULT_CONTINUATION_PAGE_SIZE
    elif breadth == RETRIEVAL_BREADTH_NARROW:
        eff_top_k = DEFAULT_NARROW_TOP_K
    else:
        eff_top_k = DEFAULT_TOP_K
                                                               
                                                                  
    if top_k is not None and top_k != DEFAULT_TOP_K:
        eff_top_k = int(top_k)
    eff_max_files = int(
        max_files_per_query
        if max_files_per_query is not None
        else DEFAULT_MAX_FILES_PER_QUERY
    )
    eff_max_chunks_per_file = int(
        max_chunks_per_file
        if max_chunks_per_file is not None
        else DEFAULT_MAX_CHUNKS_PER_FILE
    )
                                                                  
                          
    if breadth == RETRIEVAL_BREADTH_NARROW:
        eff_diversify = False if diversify_by_file is None \
            else bool(diversify_by_file)
    else:
        eff_diversify = (
            DEFAULT_DIVERSIFY_BY_FILE
            if diversify_by_file is None
            else bool(diversify_by_file)
        )
                                                                   
                                             
    if breadth == RETRIEVAL_BREADTH_SUMMARY:
        eff_max_chunks_per_file = min(eff_max_chunks_per_file, 2)
        eff_max_files = max(eff_max_files, 16)
    return eff_top_k, eff_max_files, eff_max_chunks_per_file, eff_diversify


def _diversify_across_files(
    chunks: list,
    *,
    max_files: int,
    max_chunks_per_file: int,
) -> list:


    if not chunks:
        return []
    if max_chunks_per_file <= 0 or max_files <= 0:
        return list(chunks)

    by_file: dict[str, list] = {}
    order: list[str] = []
    for ch in chunks:
        if ch.file_id not in by_file:
            by_file[ch.file_id] = []
            order.append(ch.file_id)
        by_file[ch.file_id].append(ch)

                         
    files_in_play = order[:max_files]
    picked: list = []
    cursors = {fid: 0 for fid in files_in_play}

                                                                  
    GLOBAL_CEILING = max_files * max_chunks_per_file
    while len(picked) < GLOBAL_CEILING:
        progress = False
        for fid in files_in_play:
            if cursors[fid] >= max_chunks_per_file:
                continue
            file_chunks = by_file.get(fid, [])
            if cursors[fid] >= len(file_chunks):
                continue
            picked.append(file_chunks[cursors[fid]])
            cursors[fid] += 1
            progress = True
            if len(picked) >= GLOBAL_CEILING:
                break
        if not progress:
            break

                                                               
    return picked


class _AlreadyPlaintext:


    __slots__ = ("text",)
    def __init__(self, text: str):
        self.text = text


def _chunk_text_lexical_search(
    *,
    vault_id: str,
    query: str,
    key: bytes,
    limit: int,
    excluded_chunk_ids: Optional[frozenset] = None,
) -> list[tuple]:


    if not query or not query.strip():
        return []
    needle = query.strip().lower()
    if len(needle) < 3:
                                                                 
                              
        return []
    from vault_core import get_db, decrypt_message
    conn = get_db()
    try:
        cur = conn.cursor()
                                                                 
                                                                  
        cur.execute(
            """
            SELECT chunk_id, file_id, chunk_index,
                   encrypted_chunk_text,
                   char_start, char_end, extraction_source
            FROM vault_content_chunks
            WHERE vault_id = %s
            ORDER BY chunk_index ASC
            LIMIT 5000
            """,
            (vault_id,),
        )
        raw_rows = cur.fetchall() or []
    except Exception:
        logger.exception("[BRAIN-RETRIEVE] chunk-text lexical select "
                         "failed vault=%s", _short(vault_id))
        return []
    finally:
        conn.close()

    excl = frozenset(excluded_chunk_ids or ())
    out: list[tuple] = []
    for row in raw_rows:
        chunk_id, file_id, chunk_index, encrypted_text, char_start, \
            char_end, extraction_source = row
        if str(chunk_id) in excl:
            continue
        try:
            plaintext = decrypt_message(encrypted_text, key)
        except Exception:
                                              
            continue
        if needle not in plaintext.lower():
            continue
        out.append((
            chunk_id, file_id, chunk_index,
            _AlreadyPlaintext(plaintext),
            char_start, char_end, extraction_source,
            0.5,                                                          
        ))
        if len(out) >= int(limit):
            break
    return out


def _semantic_search(
    *,
    vault_id: str,
    vector: list[float],
    top_k: int,
    min_similarity: float,
    excluded_chunk_ids: Optional[frozenset] = None,
) -> list[tuple]:


    from vault_core import get_db
    vec_literal = "[" + ",".join(f"{x:.7f}" for x in vector) + "]"
    conn = get_db()
    try:
        cur = conn.cursor()
                                                                    
        max_distance = 1.0 - float(min_similarity)
        excl = tuple(excluded_chunk_ids or ())
        params = [vec_literal, vault_id, vec_literal,
                  max_distance, vec_literal]
        excl_sql = ""
        if excl:
            excl_sql = "  AND chunk_id::text NOT IN %s\n"
            params.append(excl)
        params.append(int(top_k))
        cur.execute(
            f"""
            SELECT chunk_id, file_id, chunk_index,
                   encrypted_chunk_text,
                   char_start, char_end, extraction_source,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM vault_content_chunks
            WHERE vault_id = %s
              AND embedding IS NOT NULL
              AND (embedding <=> %s::vector) <= %s
            {excl_sql}ORDER BY embedding <=> %s::vector ASC
            LIMIT %s
            """,
            tuple(params),
        )
        return cur.fetchall() or []
    except Exception:
                                                                  
                                                               
        logger.exception("[BRAIN-RETRIEVE] semantic search failed "
                         "vault=%s", _short(vault_id))
        return []
    finally:
        conn.close()


def _semantic_search_per_file(
    *,
    vault_id: str,
    vector: list[float],
    per_file_cap: int,
    candidate_limit: int,
    min_similarity: float,
    excluded_chunk_ids: Optional[frozenset] = None,
    excluded_file_ids: Optional[frozenset] = None,
) -> list[tuple]:


    from vault_core import get_db
    vec_literal = "[" + ",".join(f"{x:.7f}" for x in vector) + "]"
    max_distance = 1.0 - float(min_similarity)
    excl_chunks = tuple(excluded_chunk_ids or ())
    excl_files  = tuple(excluded_file_ids or ())

    where_clauses = [
        "vault_id = %s",
        "embedding IS NOT NULL",
        "(embedding <=> %s::vector) <= %s",
    ]
    params: list = [vec_literal, vault_id, vec_literal, max_distance]
    if excl_chunks:
        where_clauses.append("chunk_id::text NOT IN %s")
        params.append(excl_chunks)
    if excl_files:
        where_clauses.append("file_id::text NOT IN %s")
        params.append(excl_files)
    where_sql = " AND ".join(where_clauses)

                                                  
    params.extend([int(per_file_cap), int(candidate_limit)])

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            WITH ranked AS (
                SELECT chunk_id, file_id, chunk_index,
                       encrypted_chunk_text,
                       char_start, char_end, extraction_source,
                       embedding <=> %s::vector AS distance,
                       ROW_NUMBER() OVER (
                           PARTITION BY file_id
                           ORDER BY embedding <=> %s::vector ASC
                       ) AS rn
                FROM vault_content_chunks
                WHERE {where_sql}
            )
            SELECT chunk_id, file_id, chunk_index,
                   encrypted_chunk_text,
                   char_start, char_end, extraction_source,
                   1.0 - distance AS similarity
            FROM ranked
            WHERE rn <= %s
            ORDER BY distance ASC
            LIMIT %s
            """,
            tuple(params),
        )
        return cur.fetchall() or []
    except Exception:
                                                                    
                                                                   
        logger.exception(
            "[BRAIN-RETRIEVE] per-file semantic search failed vault=%s; "
            "falling back to flat top-N",
            _short(vault_id),
        )
        try:
            conn.rollback()
        except Exception:
            pass
        return _semantic_search(
            vault_id=vault_id, vector=vector,
            top_k=int(candidate_limit),
            min_similarity=min_similarity,
            excluded_chunk_ids=excluded_chunk_ids,
        )
    finally:
        conn.close()


def _lexical_search(
    *,
    vault_id: str,
    query: str,
    limit: int,
    excluded_chunk_ids: Optional[frozenset] = None,
) -> list[tuple]:


    from vault_core import get_db
    pattern = f"%{query.lower()}%"
    excl = tuple(excluded_chunk_ids or ())
    conn = get_db()
    try:
        cur = conn.cursor()
        params: list = [vault_id, pattern]
        excl_sql = ""
        if excl:
            excl_sql = "  AND c.chunk_id::text NOT IN %s\n"
            params.append(excl)
        params.append(int(limit))
        cur.execute(
            f"""
            SELECT c.chunk_id, c.file_id, c.chunk_index,
                   c.encrypted_chunk_text,
                   c.char_start, c.char_end, c.extraction_source,
                   0.0 AS similarity
            FROM vault_content_chunks c
            JOIN uploaded_files uf
              ON uf.id::text = c.file_id
            WHERE c.vault_id = %s
              AND LOWER(uf.file_name) LIKE %s
            {excl_sql}ORDER BY c.chunk_index ASC
            LIMIT %s
            """,
            tuple(params),
        )
        return cur.fetchall() or []
    except Exception:
        logger.exception("[BRAIN-RETRIEVE] lexical search failed "
                         "vault=%s", _short(vault_id))
        return []
    finally:
        conn.close()


def _short(s: str) -> str:
    if not s:
        return ""
    return s[:8] + "…" if len(s) > 8 else s


__all__ = [
    "retrieve_evidence",
    "retrieve_credential_evidence",
    "RETRIEVAL_MODE_SEMANTIC",
    "RETRIEVAL_MODE_LEXICAL",
    "RETRIEVAL_MODE_CHUNK_LEXICAL",
    "RETRIEVAL_MODE_CREDENTIAL_MEMORY",
    "RETRIEVAL_MODE_EMPTY",
    "RETRIEVAL_BREADTH_NARROW",
    "RETRIEVAL_BREADTH_BROAD",
    "RETRIEVAL_BREADTH_SUMMARY",
    "RETRIEVAL_BREADTH_CONTINUATION",
    "DEFAULT_TOP_K",
    "DEFAULT_MIN_SIMILARITY",
    "DEFAULT_LEXICAL_FALLBACK_LIMIT",
    "DEFAULT_NARROW_TOP_K",
    "DEFAULT_BROAD_TOP_K",
    "DEFAULT_SUMMARY_MAX_CHUNKS",
    "DEFAULT_MAX_FILES_PER_QUERY",
    "DEFAULT_MAX_CHUNKS_PER_FILE",
    "DEFAULT_DIVERSIFY_BY_FILE",
    "DEFAULT_CONTINUATION_PAGE_SIZE",
]
