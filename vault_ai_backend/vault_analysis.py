

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from psycopg2 import errors as pg_errors
from psycopg2.extras import RealDictCursor


logger = logging.getLogger(__name__)


ANALYSIS_STATUS_NOT_STARTED      = "not_started"
ANALYSIS_STATUS_PENDING          = "pending"
ANALYSIS_STATUS_PROCESSING       = "processing"
ANALYSIS_STATUS_ANALYZED         = "analyzed"
ANALYSIS_STATUS_FAILED           = "failed"
ANALYSIS_STATUS_NEEDS_REANALYSIS = "needs_reanalysis"
ANALYSIS_STATUS_SKIPPED          = "skipped"
ANALYSIS_STATUS_UNSUPPORTED      = "unsupported"

ANALYSIS_STATUSES: tuple[str, ...] = (
    ANALYSIS_STATUS_NOT_STARTED,
    ANALYSIS_STATUS_PENDING,
    ANALYSIS_STATUS_PROCESSING,
    ANALYSIS_STATUS_ANALYZED,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_NEEDS_REANALYSIS,
    ANALYSIS_STATUS_SKIPPED,
    ANALYSIS_STATUS_UNSUPPORTED,
)

                                                               
_TERMINAL_ANALYSIS_STATUSES: frozenset[str] = frozenset({
    ANALYSIS_STATUS_ANALYZED,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_SKIPPED,
    ANALYSIS_STATUS_UNSUPPORTED,
})


JOB_STATUS_PENDING    = "pending"
JOB_STATUS_PROCESSING = "processing"
JOB_STATUS_SUCCEEDED  = "succeeded"
JOB_STATUS_FAILED     = "failed"
JOB_STATUS_CANCELLED  = "cancelled"

JOB_STATUSES: tuple[str, ...] = (
    JOB_STATUS_PENDING,
    JOB_STATUS_PROCESSING,
    JOB_STATUS_SUCCEEDED,
    JOB_STATUS_FAILED,
    JOB_STATUS_CANCELLED,
)


STAGE_TEXT_EXTRACTION           = "text_extraction"
STAGE_OCR                       = "ocr"
STAGE_AUDIO_TRANSCRIPTION       = "audio_transcription"
STAGE_VIDEO_TRANSCRIPTION       = "video_transcription"
STAGE_DOCUMENT_UNDERSTANDING    = "document_understanding"
                                                               
                                                           
STAGE_FILE_UNDERSTANDING        = "file_understanding"
                                                                  
                                                                 
STAGE_FILE_EMBEDDING            = "file_embedding"
                                                                  
                                                                   
STAGE_ARCHIVE_INDEXING          = "archive_indexing"
STAGE_ENTITY_EXTRACTION         = "entity_extraction"
STAGE_EMBEDDING                 = "embedding"
STAGE_RELATIONSHIP_BUILDING     = "relationship_building"
STAGE_EXPIRY_DETECTION          = "expiry_detection"
STAGE_CREDENTIAL_FILE_DETECTION = "credential_file_detection"
                                                                      
                                                                  
STAGE_CONTENT_CHUNKING          = "content_chunking"

STAGES: tuple[str, ...] = (
    STAGE_TEXT_EXTRACTION,
    STAGE_OCR,
    STAGE_AUDIO_TRANSCRIPTION,
    STAGE_VIDEO_TRANSCRIPTION,
    STAGE_DOCUMENT_UNDERSTANDING,
    STAGE_FILE_UNDERSTANDING,
    STAGE_FILE_EMBEDDING,
    STAGE_ARCHIVE_INDEXING,
    STAGE_ENTITY_EXTRACTION,
    STAGE_EMBEDDING,
    STAGE_RELATIONSHIP_BUILDING,
    STAGE_EXPIRY_DETECTION,
    STAGE_CREDENTIAL_FILE_DETECTION,
    STAGE_CONTENT_CHUNKING,
)


DEFAULT_STALE_LEASE_SECONDS = 5 * 60

                                                                
DEFAULT_MAX_ATTEMPTS = 3

                                                                
_ERROR_MESSAGE_CAP = 500


def normalize_analysis_status(status: Optional[str]) -> str:


    if status is None:
        return ANALYSIS_STATUS_NOT_STARTED
    candidate = str(status).strip().lower()
    if candidate in ANALYSIS_STATUSES:
        return candidate
    return ANALYSIS_STATUS_NOT_STARTED


def is_terminal_analysis_status(status: Optional[str]) -> bool:


    return normalize_analysis_status(status) in _TERMINAL_ANALYSIS_STATUSES


def normalize_job_status(status: Optional[str]) -> str:
    if status is None:
        return JOB_STATUS_PENDING
    candidate = str(status).strip().lower()
    if candidate in JOB_STATUSES:
        return candidate
    return JOB_STATUS_PENDING


def normalize_stage(stage: Optional[str]) -> Optional[str]:


    if stage is None:
        return None
    candidate = str(stage).strip().lower()
    return candidate if candidate in STAGES else None


def _truncate_error(message: Optional[str]) -> Optional[str]:


    if not message:
        return None
    s = str(message)
                                                                  
                                                                               
    import re
    s = re.sub(
        r"(?i)(password|passwd|token|api[_\-]?key|secret|private[_\-]?key|"
        r"mnemonic)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        s,
    )
    if len(s) > _ERROR_MESSAGE_CAP:
        s = s[:_ERROR_MESSAGE_CAP - 3] + "..."
    return s


_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
               
    "pdf", "doc", "docx", "rtf", "odt", "txt", "md", "csv",
            
    "jpg", "jpeg", "png", "gif", "webp", "heic", "tiff", "bmp",
           
    "mp3", "m4a", "wav", "ogg", "flac", "aac",
           
    "mp4", "mov", "avi", "mkv", "webm", "m4v",
})


def _file_extension(file_name: Optional[str]) -> Optional[str]:
    if not file_name:
        return None
    name = file_name.strip().lower()
    dot = name.rfind(".")
    if dot <= 0 or dot >= len(name) - 1:
        return None
    return name[dot + 1:]


def should_enqueue_analysis_for_file(
    *,
    file_name: Optional[str],
    content_type: Optional[str] = None,
) -> bool:


    ext = _file_extension(file_name)
    if ext and ext in _SUPPORTED_EXTENSIONS:
        return True
    try:
        import vault_analysis_text_extraction as text_ext
        if text_ext.supports_text_extraction(
            file_name=file_name, content_type=content_type,
        ):
            return True
    except Exception:
        pass
    mime = (content_type or "").strip().lower()
    if mime.startswith("image/") or mime.startswith("audio/") \
            or mime.startswith("video/") or mime == "application/pdf" \
            or mime.startswith("text/"):
        return True
    return False


def default_stages_for_file(
    *,
    file_name: Optional[str],
    content_type: Optional[str] = None,
) -> list[str]:


    try:
        import vault_archive_indexing as archive_mod
        if archive_mod.supports_archive_indexing(
            file_name=file_name, content_type=content_type,
        ):
            return [STAGE_ARCHIVE_INDEXING]
    except Exception:
        pass

                                                               
    try:
        import vault_analysis_ocr as ocr_mod
        if ocr_mod.supports_ocr(
            file_name=file_name, content_type=content_type,
        ):
            return [STAGE_OCR]
    except Exception:
                                                                
                                                                 
        pass

                                                              
    try:
        import vault_video_transcription as video_mod
        if video_mod.supports_video_transcription(
            file_name=file_name, content_type=content_type,
        ):
            return [STAGE_VIDEO_TRANSCRIPTION]
    except Exception:
        pass

                                                               
    try:
        import vault_audio_transcription as audio_mod
        if audio_mod.supports_audio_transcription(
            file_name=file_name, content_type=content_type,
        ):
            return [STAGE_AUDIO_TRANSCRIPTION]
    except Exception:
        pass

    if not should_enqueue_analysis_for_file(
        file_name=file_name, content_type=content_type,
    ):
        return []
    return [STAGE_TEXT_EXTRACTION]


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _worker_id() -> str:


    return os.uname().nodename if hasattr(os, "uname") else os.environ.get(
        "HOSTNAME", "unknown",
    )


def mark_file_analysis_pending(
    file_id: str, *, vault_id: Optional[str] = None,
) -> bool:


    return _set_file_analysis_status(
        file_id=file_id,
        new_status=ANALYSIS_STATUS_PENDING,
        vault_id=vault_id,
        touch_started_at=False,
        touch_completed_at=False,
        last_error=None,
    )


def mark_file_analysis_processing(
    file_id: str, *, vault_id: Optional[str] = None,
) -> bool:
    return _set_file_analysis_status(
        file_id=file_id,
        new_status=ANALYSIS_STATUS_PROCESSING,
        vault_id=vault_id,
        touch_started_at=True,
        touch_completed_at=False,
        last_error=None,
    )


def mark_file_analysis_analyzed(
    file_id: str, *, vault_id: Optional[str] = None,
) -> bool:
    return _set_file_analysis_status(
        file_id=file_id,
        new_status=ANALYSIS_STATUS_ANALYZED,
        vault_id=vault_id,
        touch_started_at=False,
        touch_completed_at=True,
        last_error=None,
    )


def mark_file_analysis_failed(
    file_id: str, *, vault_id: Optional[str] = None,
    error: Optional[str] = None,
) -> bool:
    return _set_file_analysis_status(
        file_id=file_id,
        new_status=ANALYSIS_STATUS_FAILED,
        vault_id=vault_id,
        touch_started_at=False,
        touch_completed_at=True,
        last_error=_truncate_error(error),
    )


def mark_file_analysis_unsupported(
    file_id: str, *, vault_id: Optional[str] = None,
) -> bool:
    return _set_file_analysis_status(
        file_id=file_id,
        new_status=ANALYSIS_STATUS_UNSUPPORTED,
        vault_id=vault_id,
        touch_started_at=False,
        touch_completed_at=True,
        last_error=None,
    )


def _set_file_analysis_status(
    *,
    file_id: str,
    new_status: str,
    vault_id: Optional[str],
    touch_started_at: bool,
    touch_completed_at: bool,
    last_error: Optional[str],
) -> bool:
    if new_status not in ANALYSIS_STATUSES:
        raise ValueError(f"unknown analysis status: {new_status!r}")

    now = _now_utc()
    sets = [
        "analysis_status = %s",
        "analysis_updated_at = %s",
        "analysis_last_error = %s",
    ]
    params: list = [new_status, now, last_error]
    if touch_started_at:
        sets.append("analysis_started_at = COALESCE(analysis_started_at, %s)")
        params.append(now)
    if touch_completed_at:
        sets.append("analysis_completed_at = %s")
        params.append(now)

    where = "id = %s"
    params.append(file_id)
    if vault_id is not None:
        where += " AND vault_id = %s"
        params.append(vault_id)

    sql = f"UPDATE uploaded_files SET {', '.join(sets)} WHERE {where}"
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        affected = cur.rowcount
        conn.commit()
        wrote = bool(affected)
    finally:
        conn.close()

                                                                
    if wrote and vault_id:
        try:
            from vault_tool_result_cache import invalidate_for_event
            invalidate_for_event(
                vault_id=vault_id, event="file_analysis_changed",
            )
        except Exception:
                                                             
            pass
    return wrote


def enqueue_analysis_job(
    *,
    vault_id: str,
    file_id: str,
    stage: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    metadata: Optional[dict] = None,
    scheduled_at: Optional[datetime] = None,
) -> Optional[str]:


    canonical_stage = normalize_stage(stage)
    if canonical_stage is None:
        logger.warning("enqueue_analysis_job: unknown stage %r", stage)
        return None
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    sched = scheduled_at or _now_utc()
    meta_json = _json_dump(metadata or {})

    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                """
                INSERT INTO vault_analysis_jobs
                    (vault_id, file_id, stage, status,
                     attempts, max_attempts,
                     scheduled_at, metadata_jsonb)
                VALUES (%s, %s, %s, 'pending',
                        0, %s, %s, %s::jsonb)
                RETURNING job_id
                """,
                (
                    vault_id, file_id, canonical_stage,
                    max_attempts, sched, meta_json,
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return str(row["job_id"]) if row else None
        except pg_errors.UniqueViolation:
                                                                    
                                                                    
            conn.rollback()
            cur.execute(
                """
                SELECT job_id FROM vault_analysis_jobs
                WHERE file_id = %s AND stage = %s
                  AND status IN ('pending', 'processing')
                LIMIT 1
                """,
                (file_id, canonical_stage),
            )
            row = cur.fetchone()
            return str(row["job_id"]) if row else None
    finally:
        conn.close()


def enqueue_missing_analysis_jobs(
    vault_id: str,
    *,
    max_files: int = 500,
) -> dict:


    out = {
        "enqueued":            0,
        "considered":          0,
        "skipped_unsupported": 0,
        "by_stage":            {},
        "error":               None,
    }
    try:
        conn = _get_db()
    except Exception:
        logger.exception("enqueue_missing_analysis_jobs: get_db failed")
        out["error"] = "db_unavailable"
        return out
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
                                           
                                           
        cur.execute(
            f"""
            SELECT uf.id           AS file_id,
                   uf.file_name    AS file_name,
                   uf.content_type AS content_type,
                   uf.analysis_status AS analysis_status
            FROM uploaded_files uf
            LEFT JOIN vault_analysis_jobs vaj
              ON vaj.file_id = uf.id::text
             AND vaj.status IN ('pending', 'processing')
            WHERE uf.vault_id = %s
              AND uf.upload_status = 'complete'
              AND uf.analysis_status IN (
                  '{ANALYSIS_STATUS_NOT_STARTED}',
                  '{ANALYSIS_STATUS_NEEDS_REANALYSIS}',
                  '{ANALYSIS_STATUS_PENDING}'
              )
              AND vaj.job_id IS NULL
            LIMIT %s
            """,
            (vault_id, max_files),
        )
        rows = cur.fetchall() or []
    except Exception:
        logger.exception(
            "enqueue_missing_analysis_jobs: lookup failed vault=%s",
            vault_id,
        )
        try:
            conn.close()
        except Exception:
            pass
        out["error"] = "lookup_failed"
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass

    out["considered"] = len(rows)
    by_stage: dict[str, int] = {}

    for row in rows:
        file_id = str(row["file_id"])
        file_name = row.get("file_name")
        content_type = row.get("content_type")
        try:
            stages = default_stages_for_file(
                file_name=file_name,
                content_type=content_type,
            )
        except Exception:
            logger.exception(
                "enqueue_missing_analysis_jobs: stage routing failed "
                "file=%s vault=%s",
                file_id, vault_id,
            )
            stages = [STAGE_TEXT_EXTRACTION]

        if not stages:
            out["skipped_unsupported"] += 1
            try:
                mark_file_analysis_unsupported(
                    file_id, vault_id=vault_id,
                )
            except Exception:
                pass
            continue

        for stage in stages:
            try:
                job_id = enqueue_analysis_job(
                    vault_id=vault_id,
                    file_id=file_id,
                    stage=stage,
                )
            except Exception:
                logger.exception(
                    "enqueue_missing_analysis_jobs: enqueue failed "
                    "file=%s stage=%s vault=%s",
                    file_id, stage, vault_id,
                )
                continue
            if job_id:
                out["enqueued"] += 1
                by_stage[stage] = by_stage.get(stage, 0) + 1
                                                                   
                                                                    
                try:
                    mark_file_analysis_pending(
                        file_id, vault_id=vault_id,
                    )
                except Exception:
                    pass

    out["by_stage"] = by_stage
    return out


def claim_next_analysis_job(
    *,
    vault_id: Optional[str] = None,
    worker: Optional[str] = None,
    stale_lease_seconds: int = DEFAULT_STALE_LEASE_SECONDS,
) -> Optional[dict]:


    worker_id = worker or _worker_id()
    now = _now_utc()

    where_clauses = ["status = 'pending'", "scheduled_at <= %s"]
    params: list = [now]
    if vault_id is not None:
        where_clauses.insert(0, "vault_id = %s")
        params.insert(0, vault_id)

                                                       
    where_clauses_with_stale = list(where_clauses)
    where_clauses_with_stale.append(
        "(locked_at IS NULL OR locked_at < %s)"
    )
    stale_cutoff = now.timestamp() - stale_lease_seconds
    stale_cutoff_dt = datetime.fromtimestamp(stale_cutoff, tz=timezone.utc)
    params.append(stale_cutoff_dt)

    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"""
            SELECT job_id, vault_id, file_id, stage, attempts, max_attempts,
                   metadata_jsonb
            FROM vault_analysis_jobs
            WHERE {' AND '.join(where_clauses_with_stale)}
            ORDER BY scheduled_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """,
            tuple(params),
        )
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return None

        cur.execute(
            """
            UPDATE vault_analysis_jobs
            SET status = 'processing',
                attempts = attempts + 1,
                locked_at = %s,
                locked_by = %s,
                started_at = COALESCE(started_at, %s)
            WHERE job_id = %s
            RETURNING job_id, vault_id, file_id, stage, status,
                      attempts, max_attempts, locked_at, locked_by,
                      started_at, metadata_jsonb
            """,
            (now, worker_id, now, row["job_id"]),
        )
        updated = cur.fetchone()
        conn.commit()
        if updated is not None:
            updated["job_id"] = str(updated["job_id"])
            updated["vault_id"] = str(updated["vault_id"])
        return updated
    finally:
        conn.close()


def complete_analysis_job(job_id: str) -> bool:


    now = _now_utc()
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_analysis_jobs
            SET status = 'succeeded',
                locked_at = NULL,
                locked_by = NULL,
                completed_at = %s,
                last_error = NULL
            WHERE job_id = %s AND status = 'processing'
            """,
            (now, job_id),
        )
        affected = cur.rowcount
        conn.commit()
        return bool(affected)
    finally:
        conn.close()


def fail_analysis_job(
    job_id: str,
    *,
    error: Optional[str] = None,
    retry: bool = True,
) -> Optional[dict]:


    safe_error = _truncate_error(error)
    now = _now_utc()
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT job_id, attempts, max_attempts, status
            FROM vault_analysis_jobs
            WHERE job_id = %s
            LIMIT 1
            """,
            (job_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        if row["status"] != JOB_STATUS_PROCESSING:
                                                              
                                    
            return None

        attempts = int(row["attempts"])
        max_attempts = int(row["max_attempts"])
        out_of_retries = (not retry) or attempts >= max_attempts

        new_status = (
            JOB_STATUS_FAILED if out_of_retries else JOB_STATUS_PENDING
        )
        cur.execute(
            """
            UPDATE vault_analysis_jobs
            SET status = %s,
                last_error = %s,
                locked_at = NULL,
                locked_by = NULL,
                completed_at = CASE WHEN %s = 'failed' THEN %s ELSE NULL END
            WHERE job_id = %s
            RETURNING job_id, status, attempts, max_attempts, last_error
            """,
            (new_status, safe_error, new_status, now, job_id),
        )
        updated = cur.fetchone()
        conn.commit()
        if updated is not None:
            updated["job_id"] = str(updated["job_id"])
        return updated
    finally:
        conn.close()


def analysis_coverage_for_vault(vault_id: str) -> dict:


    counts: dict[str, int] = {
        ANALYSIS_STATUS_ANALYZED: 0,
        ANALYSIS_STATUS_PENDING: 0,
        ANALYSIS_STATUS_PROCESSING: 0,
        ANALYSIS_STATUS_FAILED: 0,
        ANALYSIS_STATUS_UNSUPPORTED: 0,
        ANALYSIS_STATUS_NOT_STARTED: 0,
        ANALYSIS_STATUS_NEEDS_REANALYSIS: 0,
        ANALYSIS_STATUS_SKIPPED: 0,
    }
    total = 0
    try:
        conn = _get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT analysis_status, COUNT(*)::INT AS n
                FROM uploaded_files
                WHERE vault_id = %s
                  AND upload_status = 'complete'
                GROUP BY analysis_status
                """,
                (vault_id,),
            )
            for row in cur.fetchall() or []:
                status = normalize_analysis_status(row["analysis_status"])
                counts[status] = int(row["n"])
                total += int(row["n"])
        finally:
            conn.close()
    except Exception:
        logger.exception("analysis_coverage_for_vault failed for %s", vault_id)
    return {
        "total": total,
        "analyzed":      counts[ANALYSIS_STATUS_ANALYZED],
        "pending":       counts[ANALYSIS_STATUS_PENDING],
        "processing":    counts[ANALYSIS_STATUS_PROCESSING],
        "failed":        counts[ANALYSIS_STATUS_FAILED],
        "unsupported":   counts[ANALYSIS_STATUS_UNSUPPORTED],
        "not_started":   counts[ANALYSIS_STATUS_NOT_STARTED],
        "needs_reanalysis": counts[ANALYSIS_STATUS_NEEDS_REANALYSIS],
        "skipped":       counts[ANALYSIS_STATUS_SKIPPED],
    }


def summarise_coverage_for_chat(coverage: dict) -> dict:


    analyzed = int(coverage.get("analyzed") or 0)
    pending = int(coverage.get("pending") or 0)
    processing = int(coverage.get("processing") or 0)
    failed = int(coverage.get("failed") or 0)
    unsupported = int(coverage.get("unsupported") or 0)
    not_started = int(coverage.get("not_started") or 0)
    needs_reanalysis = int(coverage.get("needs_reanalysis") or 0)
    return {
        "total": int(coverage.get("total") or 0),
        "content_scanned": analyzed,
        "still_analyzing": pending + processing + needs_reanalysis,
        "not_scanned": failed + unsupported + not_started,
    }


def chat_coverage_note(coverage: dict) -> Optional[str]:


    summary = summarise_coverage_for_chat(coverage)
    pending = summary["still_analyzing"]
    not_scanned = summary["not_scanned"]
    if pending == 0 and not_scanned == 0:
        return None

    parts: list[str] = []
    if pending > 0:
        parts.append(
            f"{pending} file{'s' if pending != 1 else ''} "
            "still being analyzed"
        )
    if not_scanned > 0:
        parts.append(
            f"{not_scanned} file{'s' if not_scanned != 1 else ''} "
            "could not be content-scanned yet"
        )
    return (
        "I found these results so far. "
        + " — ".join(parts) + "."
    )


def _json_dump(obj) -> str:
    import json
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError(f"not JSON serializable: {type(o).__name__}")
    return json.dumps(obj, default=default, separators=(",", ":"))
