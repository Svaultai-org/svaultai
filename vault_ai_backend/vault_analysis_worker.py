

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import RealDictCursor

import vault_analysis as va
import vault_analysis_text_extraction as text_ext


logger = logging.getLogger(__name__)


DEFAULT_MAX_JOBS_PER_DRAIN = 4


_HANDLED_STAGE = va.STAGE_TEXT_EXTRACTION


def drain_text_extraction(
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
                "[text-drain] claim_next_analysis_job failed vault=%s",
                vault_id,
            )
            break
        if job is None:
            break
        if job.get("stage") != _HANDLED_STAGE:
                                                               
                                                                   
            _release_unhandled_job(job)
            continue

        ok = _process_one_text_extraction_job(
            job=job, vault_id=vault_id, key=key,
        )
        if ok:
            succeeded += 1
        else:
            failed += 1

    return {
        "processed": succeeded + failed,
        "succeeded": succeeded,
        "failed": failed,
        "drained_at": datetime.now(timezone.utc).isoformat(),
    }


def _process_one_text_extraction_job(
    *, job: dict, vault_id: str, key: bytes,
) -> bool:


    job_id = job["job_id"]
    file_id = job["file_id"]

    try:
        row = _load_file_row_for_extraction(vault_id=vault_id, file_id=file_id)
    except Exception as exc:
                                                                 
                                          
        va.fail_analysis_job(
            job_id, error=f"row load failed: {exc}", retry=True,
        )
        return False

    if row is None:
                                                          
                                                             
        va.fail_analysis_job(
            job_id, error="file row missing", retry=False,
        )
        return False

    file_name = (row.get("file_name") or "").strip()
    content_type = row.get("content_type")
    storage_mode = (row.get("storage_mode") or "inline").lower()
    encrypted_blob = row.get("encrypted_file_data")

                                                                
    if not text_ext.supports_text_extraction(
        file_name=file_name, content_type=content_type,
    ):
        va.mark_file_analysis_unsupported(file_id, vault_id=vault_id)
        va.fail_analysis_job(
            job_id,
            error=f"unsupported file type for text extraction: {file_name!r}",
            retry=False,
        )
        return False

                                      
    plaintext_bytes: Optional[bytes] = None
    if storage_mode == "inline":
        if not encrypted_blob:
            va.mark_file_analysis_failed(
                file_id, vault_id=vault_id,
                error="no encrypted bytes to extract from",
            )
            va.fail_analysis_job(
                job_id, error="no encrypted bytes", retry=False,
            )
            return False
        try:
            from vault_core import decrypt_bytes
            plaintext_bytes = decrypt_bytes(encrypted_blob, key)
        except Exception as exc:
                                                                
                                                     
            va.mark_file_analysis_failed(
                file_id, vault_id=vault_id,
                error="file decrypt failed",
            )
            va.fail_analysis_job(
                job_id, error=f"decrypt failed: {exc}", retry=False,
            )
            return False
    elif storage_mode in ("chunks", "chunked"):
                                                               
                                                                     
        try:
            plaintext_bytes = _decrypt_chunked_file_bytes(
                vault_id=vault_id, file_id=file_id, key=key,
            )
        except Exception as exc:
            va.mark_file_analysis_failed(
                file_id, vault_id=vault_id,
                error=f"chunked decrypt failed: {exc}",
            )
            va.fail_analysis_job(
                job_id, error=f"chunked decrypt failed: {exc}",
                retry=False,
            )
            return False
        if not plaintext_bytes:
            va.mark_file_analysis_failed(
                file_id, vault_id=vault_id,
                error="no chunked bytes to extract from",
            )
            va.fail_analysis_job(
                job_id, error="no chunked bytes", retry=False,
            )
            return False
    else:
                                                                 
                
        va.mark_file_analysis_unsupported(file_id, vault_id=vault_id)
        va.fail_analysis_job(
            job_id,
            error=f"unknown storage mode {storage_mode!r}",
            retry=False,
        )
        return False

                                        
    va.mark_file_analysis_processing(file_id, vault_id=vault_id)
    try:
        text, truncated = text_ext.extract_text(
            file_name=file_name,
            file_bytes=plaintext_bytes,
            content_type=content_type,
        )
    except text_ext.TextExtractionError as exc:
        va.mark_file_analysis_failed(
            file_id, vault_id=vault_id, error=str(exc),
        )
        va.fail_analysis_job(job_id, error=str(exc), retry=False)
        return False
    finally:
                                                                  
                                                             
        plaintext_bytes = None              

    if not text:
                                                               
                                                                 
        va.mark_file_analysis_unsupported(file_id, vault_id=vault_id)
        va.fail_analysis_job(
            job_id,
            error="extractor returned no text",
            retry=False,
        )
        return False

                                 
    try:
        from vault_core import encrypt_message
        encrypted_text = encrypt_message(text, key)
    except Exception as exc:
        va.fail_analysis_job(
            job_id, error=f"encrypt failed: {exc}", retry=False,
        )
        return False

    char_count = len(text)
    text = ""                                

    try:
        _persist_extracted_text(
            vault_id=vault_id,
            file_id=file_id,
            encrypted_text=encrypted_text,
            char_count=char_count,
            truncated=truncated,
            source="worker",
        )
    except Exception as exc:
                                                           
                              
        va.fail_analysis_job(
            job_id, error=f"persist failed: {exc}", retry=True,
        )
        return False

    va.mark_file_analysis_analyzed(file_id, vault_id=vault_id)
    va.complete_analysis_job(job_id)

                                                            
    try:
        import vault_understanding_worker as vuw
        vuw.enqueue_understanding_after_text_extraction(
            vault_id=vault_id, file_id=file_id,
        )
    except Exception:
                                                        
                                                            
        logger.exception(
            "[text-extraction] enqueue understanding failed file=%s",
            file_id,
        )

                                                              
    try:
        va.enqueue_analysis_job(
            vault_id=vault_id, file_id=file_id,
            stage=va.STAGE_CONTENT_CHUNKING,
        )
    except Exception:
        logger.exception(
            "[text-extraction] enqueue content_chunking failed "
            "file=%s", file_id,
        )

                                                                
    try:
        import vault_understanding as vu
        vu.mark_stale_understandings_for_changed_text(
            vault_id, file_id=file_id,
        )
        vu.mark_stale_embeddings_for_changed_text(
            vault_id, file_id=file_id,
        )
    except Exception:
        logger.exception(
            "[text-extraction] stale housekeeping failed file=%s",
            file_id,
        )

    try:
        from vault_intelligence_updater import on_file_extracted
        on_file_extracted(vault_id)
    except Exception:
        pass

    return True


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _load_file_row_for_extraction(
    *, vault_id: str, file_id: str,
) -> Optional[dict]:
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, file_name, content_type, file_size,
                   encrypted_file_data, storage_mode, upload_status
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


def _persist_extracted_text(
    *,
    vault_id: str,
    file_id: str,
    encrypted_text: str,
    char_count: int,
    truncated: bool,
    source: str,
) -> None:


    now = datetime.now(timezone.utc)
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE uploaded_files
            SET extracted_text = %s,
                extracted_text_encrypted = TRUE,
                extracted_text_status = 'available',
                extracted_text_source = %s,
                extracted_text_updated_at = %s,
                extracted_text_truncated = %s,
                extracted_text_char_count = %s,
                extracted_text_version = COALESCE(extracted_text_version, 0) + 1
            WHERE id = %s AND vault_id = %s
            """,
            (
                encrypted_text, source, now, truncated, char_count,
                file_id, vault_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _release_unhandled_job(job: dict) -> None:


    try:
        va.fail_analysis_job(
            job["job_id"],
            error=f"stage {job.get('stage')!r} not handled by text drain",
            retry=True,
        )
    except Exception:
        logger.exception(
            "[text-drain] failed to release unhandled stage job=%s",
            job.get("job_id"),
        )


def _empty_report() -> dict:
    return {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "drained_at": datetime.now(timezone.utc).isoformat(),
    }


def backfill_chunked_text_extraction_jobs(vault_id: str) -> dict:


    import vault_analysis_text_extraction as text_ext_mod

    candidates = _select_chunked_unsupported_for_backfill(vault_id)
    matched = len(candidates)
    if matched == 0:
        return _empty_backfill_report()

                                                                 
    extractable: list[dict] = [
        r for r in candidates
        if text_ext_mod.supports_text_extraction(
            file_name=r.get("file_name"),
            content_type=r.get("content_type"),
        )
    ]
    if not extractable:
        return {
            "matched":               matched,
            "reset_to_pending":      0,
            "jobs_enqueued":         0,
            "skipped_existing_jobs": 0,
        }

    file_ids = [r["id"] for r in extractable]
    active_job_files = _file_ids_with_active_text_extraction_jobs(file_ids)

    reset_to_pending = 0
    jobs_enqueued = 0
    skipped_existing_jobs = 0

    for row in extractable:
        file_id = row["id"]
        if file_id in active_job_files:
                                                                 
                                                                 
            skipped_existing_jobs += 1
            continue

        _reset_file_to_pending(vault_id=vault_id, file_id=file_id)
        reset_to_pending += 1

        job_id = va.enqueue_analysis_job(
            vault_id=vault_id,
            file_id=file_id,
            stage=va.STAGE_TEXT_EXTRACTION,
        )
        if job_id:
            jobs_enqueued += 1

    return {
        "matched":               matched,
        "reset_to_pending":      reset_to_pending,
        "jobs_enqueued":         jobs_enqueued,
        "skipped_existing_jobs": skipped_existing_jobs,
    }


def _empty_backfill_report() -> dict:
    return {
        "matched":               0,
        "reset_to_pending":      0,
        "jobs_enqueued":         0,
        "skipped_existing_jobs": 0,
    }


def _select_chunked_unsupported_for_backfill(vault_id: str) -> list[dict]:

    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, file_name, content_type, storage_mode
            FROM uploaded_files
            WHERE vault_id = %s
              AND upload_status = 'complete'
              AND analysis_status = 'unsupported'
              AND storage_mode IN ('chunks', 'chunked')
            ORDER BY created_at DESC
            """,
            (vault_id,),
        )
        return cur.fetchall() or []
    finally:
        conn.close()


def _file_ids_with_active_text_extraction_jobs(
    file_ids: list[str],
) -> set[str]:


    if not file_ids:
        return set()
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT DISTINCT file_id
            FROM vault_analysis_jobs
            WHERE stage = %s
              AND status IN ('pending', 'processing')
              AND file_id = ANY(%s)
            """,
            (va.STAGE_TEXT_EXTRACTION, list(file_ids)),
        )
        return {r["file_id"] for r in cur.fetchall() or []}
    finally:
        conn.close()


def _reset_file_to_pending(*, vault_id: str, file_id: str) -> None:


    now = datetime.now(timezone.utc)
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE uploaded_files
            SET analysis_status      = 'pending',
                analysis_last_error  = NULL,
                analysis_updated_at  = %s,
                analysis_completed_at = NULL
            WHERE id = %s
              AND vault_id = %s
              AND analysis_status = 'unsupported'
              AND storage_mode IN ('chunks', 'chunked')
            """,
            (now, file_id, vault_id),
        )
        conn.commit()
    finally:
        conn.close()


_CHUNKED_FILE_PLAINTEXT_CAP = 4_000_000


def _decrypt_chunked_file_bytes(
    *, vault_id: str, file_id: str, key: bytes,
) -> bytes:


    from chunked_aead import decrypt_chunk

    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
                                                                    
                                                          
        cur.execute(
            """
            SELECT chunk_count
            FROM uploaded_files
            WHERE id = %s AND vault_id = %s
            LIMIT 1
            """,
            (file_id, vault_id),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("file row missing during chunked decrypt")
        chunk_count = int(row["chunk_count"] or 0)
        if chunk_count <= 0:
            return b""

        cur.execute(
            """
            SELECT chunk_index, chunk_bytes
            FROM uploaded_file_chunks
            WHERE file_id = %s
            ORDER BY chunk_index ASC
            """,
            (file_id,),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    if len(rows) != chunk_count:
        raise RuntimeError(
            f"chunk row mismatch (expected {chunk_count}, got {len(rows)})"
        )

    parts: list[bytes] = []
    total = 0
    for r in rows:
        idx = int(r["chunk_index"])
        frame = bytes(r["chunk_bytes"])
        plain = decrypt_chunk(frame, key, idx)
        total += len(plain)
        if total > _CHUNKED_FILE_PLAINTEXT_CAP:
                                                               
                                                                
            remaining = _CHUNKED_FILE_PLAINTEXT_CAP - (total - len(plain))
            parts.append(plain[: max(0, remaining)])
            break
        parts.append(plain)
    return b"".join(parts)
