

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


DEFAULT_STALE_PROCESSING_SECONDS = 5 * 60


@dataclass(frozen=True)
class ReconcilerReport:


    vault_id: str
    status_drift_repaired: int = 0
    orphan_queue_rows_deleted: int = 0
    stuck_processing_requeued: int = 0
    pending_or_not_started_enqueued: int = 0
    missing_chunks_enqueued: int = 0
    missing_embeddings_repaired: int = 0
    wrong_dim_embeddings_nulled: int = 0
    stale_chunking_jobs_reset: int = 0
    text_like_unsupported_requeued: int = 0
    error: Optional[str] = None

    def total_repairs(self) -> int:
        return (
            self.status_drift_repaired
            + self.orphan_queue_rows_deleted
            + self.stuck_processing_requeued
            + self.pending_or_not_started_enqueued
            + self.missing_chunks_enqueued
            + self.missing_embeddings_repaired
            + self.wrong_dim_embeddings_nulled
            + self.stale_chunking_jobs_reset
            + self.text_like_unsupported_requeued
        )

    def to_dict(self) -> dict:
        return {
            "vault_id":                         self.vault_id,
            "status_drift_repaired":            int(self.status_drift_repaired),
            "orphan_queue_rows_deleted":        int(self.orphan_queue_rows_deleted),
            "stuck_processing_requeued":        int(self.stuck_processing_requeued),
            "pending_or_not_started_enqueued":  int(self.pending_or_not_started_enqueued),
            "missing_chunks_enqueued":          int(self.missing_chunks_enqueued),
            "missing_embeddings_repaired":      int(self.missing_embeddings_repaired),
            "wrong_dim_embeddings_nulled":      int(self.wrong_dim_embeddings_nulled),
            "stale_chunking_jobs_reset":        int(self.stale_chunking_jobs_reset),
            "text_like_unsupported_requeued":   int(self.text_like_unsupported_requeued),
            "total_repairs":                    int(self.total_repairs()),
            "error":                            self.error,
        }


def repair_status_drift_for_vault(vault_id: str) -> int:


    if not vault_id:
        return 0
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE uploaded_files
            SET analysis_status = 'analyzed'
            WHERE vault_id = %s
              AND extracted_text IS NOT NULL
              AND analysis_status IN ('not_started', 'pending')
            """,
            (vault_id,),
        )
        affected = int(cur.rowcount or 0)
        conn.commit()
        return affected
    finally:
        conn.close()


def repair_orphan_queue_rows_for_vault(vault_id: str) -> int:


    if not vault_id:
        return 0
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM vault_analysis_jobs vaj
            USING uploaded_files uf
            WHERE vaj.file_id::text = uf.id::text
              AND uf.vault_id = %s
              AND uf.analysis_status = 'analyzed'
              AND vaj.status = 'pending'
            """,
            (vault_id,),
        )
        affected = int(cur.rowcount or 0)
        conn.commit()
        return affected
    finally:
        conn.close()


def repair_stuck_processing_for_vault(
    vault_id: str,
    *,
    stale_seconds: int = DEFAULT_STALE_PROCESSING_SECONDS,
) -> int:


    if not vault_id:
        return 0
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_analysis_jobs
            SET status = 'pending',
                locked_at = NULL,
                locked_by = NULL,
                last_error = COALESCE(last_error, '') || ' [reconciler:stale_lease]'
            WHERE vault_id = %s
              AND status = 'processing'
              AND (locked_at IS NULL
                   OR locked_at < NOW() - (%s || ' seconds')::interval)
            """,
            (vault_id, str(int(stale_seconds))),
        )
        affected = int(cur.rowcount or 0)
        conn.commit()
        return affected
    finally:
        conn.close()


def repair_pending_and_not_started_for_vault(vault_id: str) -> int:


    if not vault_id:
        return 0
    try:
        from vault_analysis import enqueue_missing_analysis_jobs
    except Exception:
        logger.exception("reconciler: enqueue helper import failed")
        return 0
    try:
        report = enqueue_missing_analysis_jobs(vault_id) or {}
                                                                   
                                                                       
        if report.get("error"):
            logger.warning(
                "reconciler: enqueue helper returned error=%s vault=%s",
                report.get("error"), vault_id,
            )
            return 0
        return int(report.get("enqueued") or 0)
    except Exception:
        logger.exception(
            "reconciler: enqueue_missing crashed vault=%s", vault_id,
        )
        return 0


def repair_text_like_unsupported_for_vault(vault_id: str) -> int:


    if not vault_id:
        return 0
    try:
        import vault_analysis_text_extraction as text_ext
        from vault_core import get_db
    except Exception:
        logger.exception(
            "reconciler: text-like unsupported imports failed vault=%s",
            vault_id,
        )
        return 0

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, file_name, content_type
            FROM uploaded_files
            WHERE vault_id::text = %s
              AND upload_status = 'complete'
              AND analysis_status = 'unsupported'
              AND extracted_text IS NULL
            """,
            (vault_id,),
        )
        rows = cur.fetchall() or []
        file_ids = [
            str(file_id)
            for file_id, file_name, content_type in rows
            if text_ext.supports_text_extraction(
                file_name=file_name, content_type=content_type,
            )
        ]
        if not file_ids:
            conn.commit()
            return 0
        cur.execute(
            """
            WITH updated AS (
                UPDATE uploaded_files
                SET analysis_status = 'pending',
                    extracted_text_status = 'not_available',
                    analysis_last_error = NULL,
                    analysis_updated_at = NOW()
                WHERE vault_id::text = %s
                  AND id::text = ANY(%s)
                  AND analysis_status = 'unsupported'
                  AND extracted_text IS NULL
                RETURNING id::text AS file_id
            ), inserted AS (
                INSERT INTO vault_analysis_jobs
                    (vault_id, file_id, stage, status,
                     attempts, max_attempts, scheduled_at, metadata_jsonb)
                SELECT %s, u.file_id, 'text_extraction', 'pending',
                       0, 3, NOW(), '{}'::jsonb
                FROM updated u
                WHERE NOT EXISTS (
                    SELECT 1 FROM vault_analysis_jobs j
                    WHERE j.file_id = u.file_id
                      AND j.stage = 'text_extraction'
                      AND j.status IN ('pending', 'processing')
                )
                RETURNING file_id
            )
            SELECT COUNT(*) FROM updated
            """,
            (vault_id, file_ids, vault_id),
        )
        row = cur.fetchone()
        repaired = int(row[0] or 0) if row else 0
        conn.commit()
        return repaired
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def repair_missing_chunks_for_vault(vault_id: str) -> int:


    if not vault_id:
        return 0
    try:
        from vault_analysis import (
            enqueue_analysis_job, STAGE_CONTENT_CHUNKING,
        )
    except Exception:
        logger.exception(
            "reconciler: chunking-stage import failed vault=%s", vault_id,
        )
        return 0
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT uf.id
            FROM uploaded_files uf
            LEFT JOIN vault_content_chunks c
              ON c.file_id = uf.id::text
            LEFT JOIN vault_analysis_jobs vaj
              ON vaj.file_id = uf.id::text
             AND vaj.stage = 'content_chunking'
             AND vaj.status IN ('pending', 'processing')
            WHERE uf.vault_id = %s
              AND uf.upload_status = 'complete'
              AND uf.analysis_status = 'analyzed'
              AND uf.extracted_text_status = 'available'
              AND c.chunk_id IS NULL
              AND vaj.job_id IS NULL
            LIMIT 500
            """,
            (vault_id,),
        )
        rows = cur.fetchall() or []
    except Exception:
                                                                  
                                                                   
        logger.warning(
            "reconciler: chunk-coverage scan failed vault=%s (table missing?)",
            vault_id,
        )
        try:
            conn.close()
        except Exception:
            pass
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass

    enqueued = 0
    for (file_id,) in rows:
        try:
            jid = enqueue_analysis_job(
                vault_id=vault_id, file_id=str(file_id),
                stage=STAGE_CONTENT_CHUNKING,
            )
        except Exception:
            logger.exception(
                "reconciler: enqueue chunking failed vault=%s file=%s",
                vault_id, str(file_id)[:8],
            )
            continue
        if jid:
            enqueued += 1
    return enqueued


def repair_chunks_missing_embeddings_for_vault(vault_id: str) -> int:


    if not vault_id:
        return 0
    try:
        from vault_analysis import (
            enqueue_analysis_job, STAGE_CONTENT_CHUNKING,
        )
    except Exception:
        logger.exception(
            "reconciler: chunking-stage import failed vault=%s",
            vault_id,
        )
        return 0
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT c.file_id
            FROM vault_content_chunks c
            LEFT JOIN vault_analysis_jobs vaj
              ON vaj.file_id = c.file_id
             AND vaj.stage = 'content_chunking'
             AND vaj.status IN ('pending', 'processing')
            WHERE c.vault_id = %s
              AND c.embedding IS NULL
              AND vaj.job_id IS NULL
            LIMIT 500
            """,
            (vault_id,),
        )
        rows = cur.fetchall() or []
    except Exception:
        logger.warning(
            "reconciler: missing-embeddings scan failed vault=%s "
            "(table missing?)",
            vault_id,
        )
        try:
            conn.close()
        except Exception:
            pass
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass

    enqueued = 0
    for (file_id,) in rows:
        try:
            jid = enqueue_analysis_job(
                vault_id=vault_id, file_id=str(file_id),
                stage=STAGE_CONTENT_CHUNKING,
            )
        except Exception:
            logger.exception(
                "reconciler: enqueue missing-embedding chunking "
                "failed vault=%s file=%s",
                vault_id, str(file_id)[:8],
            )
            continue
        if jid:
            enqueued += 1
    return enqueued


def repair_wrong_dim_or_model_embeddings_for_vault(
    vault_id: str,
) -> int:


    if not vault_id:
        return 0
    try:
        from vault_config import ai as _ai
        cfg = _ai()
        cur_model = str(cfg.embedding_model or "")
        cur_dim   = int(cfg.embedding_dim or 0)
    except Exception:
        cur_model = "text-embedding-3-small"
        cur_dim   = 1536
    if cur_dim <= 0 or not cur_model:
        return 0

    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_content_chunks
            SET embedding = NULL,
                embedding_model = NULL,
                embedding_dim = NULL,
                embedded_at = NULL,
                updated_at = NOW()
            WHERE vault_id = %s
              AND embedding IS NOT NULL
              AND (
                  embedding_dim <> %s
                  OR embedding_model <> %s
                  OR embedding_dim IS NULL
                  OR embedding_model IS NULL
              )
            """,
            (vault_id, cur_dim, cur_model),
        )
        affected = int(cur.rowcount or 0)
        conn.commit()
        return affected
    except Exception:
        logger.warning(
            "reconciler: wrong-dim/model sweep failed vault=%s "
            "(table missing?)",
            vault_id,
        )
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def repair_stale_chunking_jobs_for_vault(
    vault_id: str,
    *,
    stale_after_seconds: int = 600,
) -> int:


    if not vault_id or stale_after_seconds <= 0:
        return 0
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_analysis_jobs
            SET status = 'pending',
                locked_at = NULL,
                locked_by = NULL,
                updated_at = NOW()
            WHERE vault_id = %s
              AND stage = 'content_chunking'
              AND status = 'processing'
              AND (locked_at IS NULL
                   OR locked_at < NOW() - (%s || ' seconds')::interval)
            """,
            (vault_id, int(stale_after_seconds)),
        )
        affected = int(cur.rowcount or 0)
        conn.commit()
        return affected
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(
            "reconciler: stale-chunking-jobs sweep failed vault=%s",
            vault_id,
        )
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def reconcile_vault(
    vault_id: str,
    *,
    stale_processing_seconds: int = DEFAULT_STALE_PROCESSING_SECONDS,
) -> ReconcilerReport:


    if not vault_id:
        return ReconcilerReport(vault_id="", error="empty_vault_id")
    try:
        a = repair_status_drift_for_vault(vault_id)
    except Exception as exc:
        logger.exception("reconciler: status drift crashed vault=%s", vault_id)
        return ReconcilerReport(vault_id=vault_id, error=f"status_drift:{type(exc).__name__}")
    try:
        b = repair_orphan_queue_rows_for_vault(vault_id)
    except Exception as exc:
        logger.exception("reconciler: orphan queue crashed vault=%s", vault_id)
        return ReconcilerReport(
            vault_id=vault_id, status_drift_repaired=a,
            error=f"orphan_queue:{type(exc).__name__}",
        )
    try:
        c = repair_stuck_processing_for_vault(
            vault_id, stale_seconds=stale_processing_seconds,
        )
    except Exception as exc:
        logger.exception("reconciler: stuck processing crashed vault=%s", vault_id)
        return ReconcilerReport(
            vault_id=vault_id, status_drift_repaired=a,
            orphan_queue_rows_deleted=b,
            error=f"stuck_processing:{type(exc).__name__}",
        )
    try:
        i = repair_text_like_unsupported_for_vault(vault_id)
    except Exception:
        logger.exception(
            "reconciler: text-like unsupported repair crashed vault=%s",
            vault_id,
        )
        i = 0
    d = repair_pending_and_not_started_for_vault(vault_id)
                                                                
                                                          
    try:
        e = repair_missing_chunks_for_vault(vault_id)
    except Exception:
        logger.exception(
            "reconciler: chunking-enqueue crashed vault=%s", vault_id,
        )
        e = 0
                                                                  
                                                               
    try:
        f = repair_chunks_missing_embeddings_for_vault(vault_id)
    except Exception:
        logger.exception(
            "reconciler: missing-embedding enqueue crashed vault=%s",
            vault_id,
        )
        f = 0
                                                                 
                                                     
    try:
        g = repair_wrong_dim_or_model_embeddings_for_vault(vault_id)
    except Exception:
        logger.exception(
            "reconciler: wrong-dim/model sweep crashed vault=%s",
            vault_id,
        )
        g = 0
                                                               
                                                          
    try:
        h = repair_stale_chunking_jobs_for_vault(
            vault_id, stale_after_seconds=stale_processing_seconds,
        )
    except Exception:
        logger.exception(
            "reconciler: stale-chunking-jobs sweep crashed vault=%s",
            vault_id,
        )
        h = 0
    return ReconcilerReport(
        vault_id=vault_id,
        status_drift_repaired=a,
        orphan_queue_rows_deleted=b,
        stuck_processing_requeued=c,
        pending_or_not_started_enqueued=d,
        missing_chunks_enqueued=e,
        missing_embeddings_repaired=f,
        wrong_dim_embeddings_nulled=g,
        stale_chunking_jobs_reset=h,
        text_like_unsupported_requeued=i,
    )


def reconcile_all_vaults_at_startup() -> dict:


    from vault_core import get_db
    vault_ids: list[str] = []
    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT DISTINCT vault_id FROM uploaded_files",
            )
            vault_ids = [str(r[0]) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        logger.exception("reconcile_all: DB scan failed")
        return {"vaults_seen": 0, "total_repairs": 0, "error": "db_scan_failed"}

    total = 0
    failed = 0
    for vid in vault_ids:
        report = reconcile_vault(vid)
        total += report.total_repairs()
        if report.error:
            failed += 1
    return {
        "vaults_seen":     len(vault_ids),
        "vaults_failed":   failed,
        "total_repairs":   total,
    }


__all__ = [
    "ReconcilerReport",
    "DEFAULT_STALE_PROCESSING_SECONDS",
    "repair_status_drift_for_vault",
    "repair_orphan_queue_rows_for_vault",
    "repair_stuck_processing_for_vault",
    "repair_pending_and_not_started_for_vault",
    "repair_missing_chunks_for_vault",
    "repair_chunks_missing_embeddings_for_vault",
    "repair_wrong_dim_or_model_embeddings_for_vault",
    "repair_stale_chunking_jobs_for_vault",
    "reconcile_vault",
    "reconcile_all_vaults_at_startup",
]
