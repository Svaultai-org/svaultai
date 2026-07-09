

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import RealDictCursor

import vault_analysis as va
import vault_embedding as ve


logger = logging.getLogger(__name__)


DEFAULT_MAX_JOBS_PER_DRAIN = 2


_HANDLED_STAGE = va.STAGE_FILE_EMBEDDING


def drain_file_embedding(
    *,
    vault_id: str,
    key: bytes,
    max_jobs: int = DEFAULT_MAX_JOBS_PER_DRAIN,
) -> dict:


    if max_jobs <= 0:
        return _empty_report()

    succeeded = 0
    failed = 0

    for _ in range(max_jobs):
        try:
            job = va.claim_next_analysis_job(vault_id=vault_id)
        except Exception:
            logger.exception(
                "[embedding-drain] claim failed vault=%s",
                vault_id,
            )
            break
        if job is None:
            break
        if job.get("stage") != _HANDLED_STAGE:
            _release_unhandled_job(job)
            continue

        ok = _process_one_embedding_job(
            job=job, vault_id=vault_id, key=key,
        )
        if ok:
            succeeded += 1
        else:
            failed += 1

    return {
        "processed":  succeeded + failed,
        "succeeded":  succeeded,
        "failed":     failed,
        "drained_at": datetime.now(timezone.utc).isoformat(),
    }


def enqueue_embedding_after_understanding(
    *, vault_id: str, file_id: str,
) -> Optional[str]:


    return va.enqueue_analysis_job(
        vault_id=vault_id,
        file_id=file_id,
        stage=_HANDLED_STAGE,
    )


def _process_one_embedding_job(
    *, job: dict, vault_id: str, key: bytes,
) -> bool:
    job_id = job["job_id"]
    file_id = job["file_id"]

    try:
        understanding = _load_understanding_for_embedding(
            vault_id=vault_id, file_id=file_id,
        )
    except Exception as exc:
        va.fail_analysis_job(
            job_id, error=f"row load failed: {exc}", retry=True,
        )
        return False

    file_row = None
    try:
        file_row = _load_file_row_for_embedding(
            vault_id=vault_id, file_id=file_id,
        )
    except Exception as exc:
        va.fail_analysis_job(
            job_id, error=f"file row load failed: {exc}", retry=True,
        )
        return False
    if file_row is None:
                                                 
        va.fail_analysis_job(
            job_id, error="file row missing", retry=False,
        )
        return False

    file_name = (file_row.get("file_name") or "").strip()
    source_text_version = int(
        file_row.get("extracted_text_version") or 0
    )

                                                                  
    if understanding is None and not file_row.get("extracted_text"):
        try:
            _upsert_embedding_status(
                vault_id=vault_id,
                file_id=file_id,
                status=ve.EMBEDDING_STATUS_UNSUPPORTED,
                source_text_version=source_text_version,
            )
        except Exception:
            logger.exception(
                "[embedding] upsert unsupported failed file=%s", file_id,
            )
        va.complete_analysis_job(job_id)
        return True

                                                      
    summary: Optional[str] = None
    safe_preview: Optional[str] = None
    raw_text: Optional[str] = None
    if understanding:
        try:
            from vault_core import decrypt_message
            if understanding.get("summary_encrypted"):
                summary = decrypt_message(
                    understanding["summary_encrypted"], key,
                )
            if understanding.get("safe_preview_encrypted"):
                safe_preview = decrypt_message(
                    understanding["safe_preview_encrypted"], key,
                )
        except Exception as exc:
            _mark_embedding_failed(
                vault_id=vault_id, file_id=file_id,
                error=f"decrypt failed: {exc}",
                source_text_version=source_text_version,
            )
            va.fail_analysis_job(
                job_id, error=f"decrypt failed: {exc}", retry=False,
            )
            return False
    elif file_row.get("extracted_text") and file_row.get(
        "extracted_text_encrypted"
    ):
                                                              
                                                                
        try:
            from vault_core import decrypt_message
            raw_text = decrypt_message(
                file_row["extracted_text"], key,
            )
        except Exception as exc:
            _mark_embedding_failed(
                vault_id=vault_id, file_id=file_id,
                error=f"text decrypt failed: {exc}",
                source_text_version=source_text_version,
            )
            va.fail_analysis_job(
                job_id, error=f"text decrypt failed: {exc}",
                retry=False,
            )
            return False

                                              
    try:
                                                                 
                                                               
        embed_record = _row_to_record(understanding) if understanding else None
        input_text = ve.build_embedding_input(
            embed_record,
            file_name=file_name,
            summary=summary,
            safe_preview=safe_preview,
            raw_text=raw_text,
        )
    except Exception as exc:
        _mark_embedding_failed(
            vault_id=vault_id, file_id=file_id,
            error=f"build_input failed: {exc}",
            source_text_version=source_text_version,
        )
        va.fail_analysis_job(
            job_id, error=f"build_input failed: {exc}", retry=False,
        )
        return False
    finally:
                                                                 
                                                             
        summary = None              
        safe_preview = None              
        raw_text = None              

    if not input_text or not input_text.strip():
                                                                 
                                                                  
        try:
            _upsert_embedding_status(
                vault_id=vault_id,
                file_id=file_id,
                status=ve.EMBEDDING_STATUS_UNSUPPORTED,
                source_text_version=source_text_version,
            )
        except Exception:
            logger.exception(
                "[embedding] upsert unsupported failed file=%s",
                file_id,
            )
        va.complete_analysis_job(job_id)
        return True

                                                     
    safe_input_hash = ve.hash_safe_input(input_text)
    understanding_id = (
        understanding.get("understanding_id")
        if understanding else None
    )

    try:
        cached = _lookup_cached_embedding(
            vault_id=vault_id,
            file_id=file_id,
            embedding_model=ve.EMBEDDING_MODEL_DEFAULT,
            safe_input_hash=safe_input_hash,
        )
    except Exception:
                                                             
                               
        logger.exception(
            "[embedding] cache lookup failed file=%s", file_id,
        )
        cached = None

    if cached and cached.get("has_vector"):
                                                            
                                                                
        try:
            _refresh_embedding_metadata(
                vault_id=vault_id,
                file_id=file_id,
                understanding_id=understanding_id,
                source_text_version=source_text_version,
            )
                                                                
                                               
            input_text = ""              
            va.complete_analysis_job(job_id)
                                                                
                                                       
            try:
                import vault_relationship_worker as vrw
                vrw.enqueue_relationship_building(vault_id=vault_id)
            except Exception:
                logger.exception(
                    "[embedding] enqueue relationship_building "
                    "(cache-hit) failed vault=%s file=%s",
                    vault_id, file_id,
                )
            return True
        except Exception as exc:
                                                               
                                                
            logger.exception(
                "[embedding] cache refresh failed file=%s", file_id,
            )

                                              
    try:
        vector = ve.generate_embedding(input_text)
    except ve.EmbeddingError as exc:
        _mark_embedding_failed(
            vault_id=vault_id, file_id=file_id,
            error=str(exc),
            source_text_version=source_text_version,
        )
        va.fail_analysis_job(job_id, error=str(exc), retry=True)
        return False
    finally:
                                                                 
                                              
        input_text = ""              

    if not vector:
        _mark_embedding_failed(
            vault_id=vault_id, file_id=file_id,
            error="empty vector",
            source_text_version=source_text_version,
        )
        va.fail_analysis_job(
            job_id, error="empty vector", retry=False,
        )
        return False

                                         
    try:
        _upsert_embedding_vector(
            vault_id=vault_id,
            file_id=file_id,
            understanding_id=understanding_id,
            vector=vector,
            source_text_version=source_text_version,
            safe_input_hash=safe_input_hash,
        )
    except Exception as exc:
        va.fail_analysis_job(
            job_id, error=f"upsert failed: {exc}", retry=True,
        )
        return False

    va.complete_analysis_job(job_id)

                                                                
    try:
        import vault_relationship_worker as vrw
        vrw.enqueue_relationship_building(vault_id=vault_id)
    except Exception:
        logger.exception(
            "[embedding] enqueue relationship_building failed "
            "vault=%s file=%s", vault_id, file_id,
        )

    return True


def _row_to_record(row: Optional[dict]) -> Optional[dict]:
    if not row:
        return None
    return {
        "document_purpose":    row.get("document_purpose"),
        "purpose_label":       row.get("purpose_label"),
        "topics":              row.get("topics_jsonb") or [],
        "entities":            row.get("entities_jsonb") or {},
        "detected_categories": row.get("detected_categories_jsonb") or [],
    }


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _load_file_row_for_embedding(
    *, vault_id: str, file_id: str,
) -> Optional[dict]:
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, file_name, content_type, extracted_text,
                   extracted_text_encrypted,
                   extracted_text_version, upload_status
            FROM uploaded_files
            WHERE id = %s AND vault_id = %s
            LIMIT 1
            """,
            (file_id, vault_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        if (row.get("upload_status") or "complete") != "complete":
            return None
        return row
    finally:
        conn.close()


def _load_understanding_for_embedding(
    *, vault_id: str, file_id: str,
) -> Optional[dict]:


    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT understanding_id, vault_id, file_id,
                   source_text_version, analysis_version, status,
                   document_purpose, purpose_label,
                   summary_encrypted, safe_preview_encrypted,
                   topics_jsonb, entities_jsonb,
                   detected_categories_jsonb
            FROM vault_file_understanding
            WHERE vault_id = %s AND file_id = %s
              AND status IN ('ready', 'stale')
            LIMIT 1
            """,
            (vault_id, file_id),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _upsert_embedding_vector(
    *,
    vault_id: str,
    file_id: str,
    understanding_id: Optional[str],
    vector: list[float],
    source_text_version: int,
    safe_input_hash: str,
) -> None:


    now = datetime.now(timezone.utc)
    conn = _get_db()
    try:
        cur = conn.cursor()
        vec_str = "[" + ",".join(
            f"{float(x):.6f}" for x in vector
        ) + "]"
        cur.execute(
            """
            INSERT INTO vault_file_embeddings (
                vault_id, file_id, understanding_id,
                source_text_version, analysis_version,
                embedding_model, embedding_dim,
                embedding_source, embedding_vector,
                safe_input_hash,
                status, last_error,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s::vector, %s, 'ready', NULL, %s, %s
            )
            ON CONFLICT (vault_id, file_id) DO UPDATE SET
                understanding_id     = EXCLUDED.understanding_id,
                source_text_version  = EXCLUDED.source_text_version,
                analysis_version     = EXCLUDED.analysis_version,
                embedding_model      = EXCLUDED.embedding_model,
                embedding_dim        = EXCLUDED.embedding_dim,
                embedding_source     = EXCLUDED.embedding_source,
                embedding_vector     = EXCLUDED.embedding_vector,
                safe_input_hash      = EXCLUDED.safe_input_hash,
                status               = 'ready',
                last_error           = NULL,
                updated_at           = EXCLUDED.updated_at
            """,
            (
                vault_id, file_id, understanding_id,
                int(source_text_version),
                int(ve.CURRENT_EMBEDDING_ANALYSIS_VERSION),
                ve.EMBEDDING_MODEL_DEFAULT,
                int(len(vector)),
                ve.EMBEDDING_SOURCE_COMBINED,
                vec_str,
                str(safe_input_hash or ""),
                now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _lookup_cached_embedding(
    *,
    vault_id: str,
    file_id: str,
    embedding_model: str,
    safe_input_hash: str,
) -> Optional[dict]:


    if not safe_input_hash:
        return None
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
                status,
                source_text_version,
                analysis_version,
                (embedding_vector IS NOT NULL) AS has_vector
            FROM vault_file_embeddings
            WHERE vault_id        = %s
              AND file_id         = %s
              AND embedding_model = %s
              AND safe_input_hash = %s
            LIMIT 1
            """,
            (vault_id, file_id, embedding_model, safe_input_hash),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _refresh_embedding_metadata(
    *,
    vault_id: str,
    file_id: str,
    understanding_id: Optional[str],
    source_text_version: int,
) -> None:


    now = datetime.now(timezone.utc)
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_file_embeddings
            SET    understanding_id    = %s,
                   source_text_version = %s,
                   analysis_version    = %s,
                   status              = 'ready',
                   last_error          = NULL,
                   updated_at          = %s
            WHERE vault_id = %s AND file_id = %s
            """,
            (
                understanding_id,
                int(source_text_version),
                int(ve.CURRENT_EMBEDDING_ANALYSIS_VERSION),
                now,
                vault_id, file_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _upsert_embedding_status(
    *,
    vault_id: str,
    file_id: str,
    status: str,
    source_text_version: int,
) -> None:


    now = datetime.now(timezone.utc)
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vault_file_embeddings (
                vault_id, file_id,
                source_text_version, analysis_version,
                embedding_model, embedding_dim,
                embedding_source,
                status, last_error,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, NULL, %s, %s
            )
            ON CONFLICT (vault_id, file_id) DO UPDATE SET
                source_text_version = EXCLUDED.source_text_version,
                analysis_version    = EXCLUDED.analysis_version,
                embedding_model     = EXCLUDED.embedding_model,
                embedding_dim       = EXCLUDED.embedding_dim,
                embedding_source    = EXCLUDED.embedding_source,
                status              = EXCLUDED.status,
                last_error          = NULL,
                updated_at          = EXCLUDED.updated_at
            """,
            (
                vault_id, file_id,
                int(source_text_version),
                int(ve.CURRENT_EMBEDDING_ANALYSIS_VERSION),
                ve.EMBEDDING_MODEL_DEFAULT,
                int(ve.EMBEDDING_DIM),
                ve.EMBEDDING_SOURCE_COMBINED,
                status,
                now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_embedding_failed(
    *,
    vault_id: str,
    file_id: str,
    error: str,
    source_text_version: int,
) -> None:


    try:
        scrubbed = va._truncate_error(error)
    except Exception:
        scrubbed = (error or "")[:500]
    now = datetime.now(timezone.utc)
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vault_file_embeddings (
                vault_id, file_id, source_text_version,
                analysis_version, embedding_model, embedding_dim,
                embedding_source, status, last_error,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                'failed', %s, %s, %s
            )
            ON CONFLICT (vault_id, file_id) DO UPDATE SET
                status     = 'failed',
                last_error = EXCLUDED.last_error,
                updated_at = EXCLUDED.updated_at
            """,
            (
                vault_id, file_id,
                int(source_text_version),
                int(ve.CURRENT_EMBEDDING_ANALYSIS_VERSION),
                ve.EMBEDDING_MODEL_DEFAULT,
                int(ve.EMBEDDING_DIM),
                ve.EMBEDDING_SOURCE_COMBINED,
                scrubbed,
                now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _release_unhandled_job(job: dict) -> None:


    try:
        va.fail_analysis_job(
            job["job_id"],
            error=(
                "stage handled by a different worker; releasing "
                "lease"
            ),
            retry=True,
        )
    except Exception:
        logger.exception(
            "[embedding-drain] release unhandled job failed "
            "job=%s stage=%s",
            job.get("job_id"), job.get("stage"),
        )


def _empty_report() -> dict:
    return {
        "processed":  0,
        "succeeded":  0,
        "failed":     0,
        "drained_at": datetime.now(timezone.utc).isoformat(),
    }
