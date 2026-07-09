

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


UNDERSTANDING_NOT_STARTED       = "not_started"
UNDERSTANDING_EXTRACTED         = "extracted"
UNDERSTANDING_CHUNKED           = "chunked"
UNDERSTANDING_EMBEDDED          = "embedded"
UNDERSTANDING_FULLY_UNDERSTOOD  = "fully_understood"                      
UNDERSTANDING_PARTIAL           = "partial"
UNDERSTANDING_FAILED            = "failed"
UNDERSTANDING_UNSUPPORTED       = "unsupported"


ALL_UNDERSTANDING_STATUSES = frozenset({
    UNDERSTANDING_NOT_STARTED,
    UNDERSTANDING_EXTRACTED,
    UNDERSTANDING_CHUNKED,
    UNDERSTANDING_EMBEDDED,
    UNDERSTANDING_FULLY_UNDERSTOOD,
    UNDERSTANDING_PARTIAL,
    UNDERSTANDING_FAILED,
    UNDERSTANDING_UNSUPPORTED,
})


def is_fully_understood(status: str) -> bool:


    return status in (UNDERSTANDING_EMBEDDED, UNDERSTANDING_FULLY_UNDERSTOOD)


@dataclass(frozen=True)
class UnderstandingSummary:

    vault_id:             str
    not_started:          int = 0
    extracted:            int = 0
    chunked:              int = 0
    embedded:             int = 0
    partial:              int = 0
    failed:               int = 0
    unsupported:          int = 0
    total:                int = 0
    error:                Optional[str] = None

    @property
    def fully_understood(self) -> int:


        return self.embedded

    def to_dict(self) -> dict:
        return {
            "vault_id":          str(self.vault_id)[:8] + "…",
            "not_started":       int(self.not_started),
            "extracted":         int(self.extracted),
            "chunked":           int(self.chunked),
            "embedded":          int(self.embedded),
            "fully_understood":  int(self.fully_understood),
            "partial":           int(self.partial),
            "failed":            int(self.failed),
            "unsupported":       int(self.unsupported),
            "total":             int(self.total),
            "error":             self.error,
        }


def understanding_status_for_file(vault_id: str, file_id: str) -> str:


    if not vault_id or not file_id:
        return UNDERSTANDING_NOT_STARTED
    try:
        return _compute_understanding(vault_id, file_id)
    except Exception as exc:
        logger.warning(
            "[understanding] per-file lookup failed vault=%s cls=%s",
            _short(vault_id), type(exc).__name__,
        )
        return UNDERSTANDING_NOT_STARTED


def _compute_understanding(vault_id: str, file_id: str) -> str:

    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                analysis_status, extracted_text_status,
                analysis_pipeline_state
            FROM uploaded_files
            WHERE vault_id = %s AND id = %s
            """,
            (vault_id, file_id),
        )
        row = cur.fetchone()
        if not row:
            return UNDERSTANDING_NOT_STARTED
        analysis_status, text_status, _state = row

                                              
        if analysis_status == "failed":
            return UNDERSTANDING_FAILED
        if analysis_status == "unsupported":
            return UNDERSTANDING_UNSUPPORTED

                                                                   
        if text_status not in ("available",):
            if text_status == "failed":
                return UNDERSTANDING_FAILED
            return UNDERSTANDING_NOT_STARTED

                                                                   
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*)                          AS n_chunks,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL)
                                                      AS n_embedded
                FROM vault_content_chunks
                WHERE vault_id = %s AND file_id = %s
                """,
                (vault_id, file_id),
            )
            crow = cur.fetchone() or (0, 0)
            n_chunks   = int(crow[0] or 0)
            n_embedded = int(crow[1] or 0)
        except Exception:
            conn.rollback()
            n_chunks = n_embedded = 0
        conn.commit()
    finally:
        conn.close()

    if n_chunks == 0:
        return UNDERSTANDING_EXTRACTED
    if n_embedded == 0:
        return UNDERSTANDING_CHUNKED
    if n_embedded == n_chunks:
        return UNDERSTANDING_EMBEDDED
    return UNDERSTANDING_PARTIAL


def understanding_summary_for_vault(vault_id: str) -> UnderstandingSummary:


    if not vault_id:
        return UnderstandingSummary(vault_id="", error="empty_vault_id")
    try:
        return _aggregate_understanding(vault_id)
    except Exception as exc:
        logger.warning(
            "[understanding] vault summary failed vault=%s cls=%s",
            _short(vault_id), type(exc).__name__,
        )
        return UnderstandingSummary(
            vault_id=vault_id, error=type(exc).__name__,
        )


def _aggregate_understanding(vault_id: str) -> UnderstandingSummary:


    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                WITH chunk_counts AS (
                    SELECT
                        c.file_id,
                        COUNT(*)                                   AS n_chunks,
                        COUNT(*) FILTER (WHERE c.embedding IS NOT NULL)
                                                                   AS n_embedded
                    FROM vault_content_chunks c
                    WHERE c.vault_id = %s
                    GROUP BY c.file_id
                ),
                files AS (
                    SELECT
                        uf.id,
                        uf.analysis_status,
                        uf.extracted_text_status,
                        COALESCE(cc.n_chunks, 0)                   AS n_chunks,
                        COALESCE(cc.n_embedded, 0)                 AS n_embedded
                    FROM uploaded_files uf
                    LEFT JOIN chunk_counts cc ON cc.file_id = uf.id::text
                    WHERE uf.vault_id = %s
                      AND uf.upload_status = 'complete'
                ),
                bucketed AS (
                    SELECT
                        CASE
                            WHEN analysis_status = 'failed'         THEN 'failed'
                            WHEN analysis_status = 'unsupported'    THEN 'unsupported'
                            WHEN extracted_text_status = 'failed'   THEN 'failed'
                            WHEN extracted_text_status <> 'available' THEN 'not_started'
                            WHEN n_chunks = 0                       THEN 'extracted'
                            WHEN n_embedded = 0                     THEN 'chunked'
                            WHEN n_embedded = n_chunks              THEN 'embedded'
                            ELSE 'partial'
                        END                                         AS status
                    FROM files
                )
                SELECT
                    COUNT(*)                                  AS total,
                    COUNT(*) FILTER (WHERE status = 'not_started')  AS not_started,
                    COUNT(*) FILTER (WHERE status = 'extracted')    AS extracted,
                    COUNT(*) FILTER (WHERE status = 'chunked')      AS chunked,
                    COUNT(*) FILTER (WHERE status = 'embedded')     AS embedded,
                    COUNT(*) FILTER (WHERE status = 'partial')      AS partial,
                    COUNT(*) FILTER (WHERE status = 'failed')       AS failed,
                    COUNT(*) FILTER (WHERE status = 'unsupported')  AS unsupported
                FROM bucketed
                """,
                (vault_id, vault_id),
            )
            row = cur.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0)
        except Exception:
            conn.rollback()
                                                                     
                                                                   
            cur.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(*) FILTER (
                        WHERE extracted_text_status NOT IN ('available', 'failed')
                        AND analysis_status NOT IN ('failed', 'unsupported')
                    ),
                    COUNT(*) FILTER (
                        WHERE extracted_text_status = 'available'
                        AND analysis_status NOT IN ('failed', 'unsupported')
                    ),
                    0, 0, 0,
                    COUNT(*) FILTER (
                        WHERE analysis_status = 'failed'
                        OR extracted_text_status = 'failed'
                    ),
                    COUNT(*) FILTER (WHERE analysis_status = 'unsupported')
                FROM uploaded_files
                WHERE vault_id = %s
                  AND upload_status = 'complete'
                """,
                (vault_id,),
            )
            row = cur.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0)
        conn.commit()
    finally:
        conn.close()

    total, not_started, extracted, chunked, embedded, partial_, failed, \
        unsupported = (int(v or 0) for v in row)

    return UnderstandingSummary(
        vault_id=vault_id,
        total=total,
        not_started=not_started,
        extracted=extracted,
        chunked=chunked,
        embedded=embedded,
        partial=partial_,
        failed=failed,
        unsupported=unsupported,
    )


def _short(s: str) -> str:
    if not s:
        return ""
    return s[:8] + "…" if len(s) > 8 else s


__all__ = [
    "UNDERSTANDING_NOT_STARTED",
    "UNDERSTANDING_EXTRACTED",
    "UNDERSTANDING_CHUNKED",
    "UNDERSTANDING_EMBEDDED",
    "UNDERSTANDING_FULLY_UNDERSTOOD",
    "UNDERSTANDING_PARTIAL",
    "UNDERSTANDING_FAILED",
    "UNDERSTANDING_UNSUPPORTED",
    "ALL_UNDERSTANDING_STATUSES",
    "is_fully_understood",
    "UnderstandingSummary",
    "understanding_status_for_file",
    "understanding_summary_for_vault",
]
