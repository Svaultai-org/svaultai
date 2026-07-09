

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrainCoverage:


    vault_id:                       str
    total_files:                    int = 0
    files_with_extracted_text:      int = 0
    files_with_chunks:              int = 0
    files_with_any_chunks:          int = 0
    files_with_embedded_chunks:     int = 0
    files_with_all_chunks_embedded: int = 0
    files_with_partial_embeddings:  int = 0
    files_missing_chunks:           int = 0
    files_missing_embeddings:       int = 0
    chunks_total:                   int = 0
    chunks_embedded:                int = 0
    chunks_unembedded:              int = 0
    pending_chunking_jobs:          int = 0
    pending_embedding_jobs:         int = 0
    failed_chunking_jobs:           int = 0
    failed_embedding_jobs:          int = 0
    unsupported_files:              int = 0
    error:                          Optional[str] = None

    @property
    def coverage_percentage(self) -> float:


        denom = self.total_files - self.unsupported_files
        if denom <= 0:
            return 1.0
        ratio = float(self.files_with_all_chunks_embedded) / float(denom)
        if ratio < 0.0:
            return 0.0
        if ratio > 1.0:
            return 1.0
        return ratio

    @property
    def chunk_coverage_percentage(self) -> float:


        if self.chunks_total <= 0:
            return 1.0
        ratio = float(self.chunks_embedded) / float(self.chunks_total)
        if ratio < 0.0:
            return 0.0
        if ratio > 1.0:
            return 1.0
        return ratio

    @property
    def is_complete(self) -> bool:


        try:
            from vault_config import brain as _b
            threshold = float(_b().coverage_complete_threshold)
        except Exception:
            threshold = 0.95
        return (
            self.coverage_percentage >= threshold
            and self.pending_chunking_jobs == 0
            and self.pending_embedding_jobs == 0
            and self.files_missing_chunks == 0
            and self.files_missing_embeddings == 0
            and self.files_with_partial_embeddings == 0
            and self.chunks_unembedded == 0
        )

    @property
    def has_failures(self) -> bool:
        return (
            self.failed_chunking_jobs > 0
            or self.failed_embedding_jobs > 0
        )

    def to_dict(self) -> dict:
        return {
            "vault_id":                       str(self.vault_id)[:8] + "…",
            "total_files":                    int(self.total_files),
            "files_with_extracted_text":      int(self.files_with_extracted_text),
            "files_with_chunks":              int(self.files_with_chunks),
            "files_with_any_chunks":          int(self.files_with_any_chunks),
            "files_with_embedded_chunks":     int(self.files_with_embedded_chunks),
            "files_with_all_chunks_embedded": int(self.files_with_all_chunks_embedded),
            "files_with_partial_embeddings":  int(self.files_with_partial_embeddings),
            "files_missing_chunks":           int(self.files_missing_chunks),
            "files_missing_embeddings":       int(self.files_missing_embeddings),
            "chunks_total":                   int(self.chunks_total),
            "chunks_embedded":                int(self.chunks_embedded),
            "chunks_unembedded":              int(self.chunks_unembedded),
            "pending_chunking_jobs":          int(self.pending_chunking_jobs),
            "pending_embedding_jobs":         int(self.pending_embedding_jobs),
            "failed_chunking_jobs":           int(self.failed_chunking_jobs),
            "failed_embedding_jobs":          int(self.failed_embedding_jobs),
            "unsupported_files":              int(self.unsupported_files),
            "coverage_percentage":            round(self.coverage_percentage, 4),
            "chunk_coverage_percentage":      round(
                self.chunk_coverage_percentage, 4,
            ),
            "is_complete":                    bool(self.is_complete),
            "has_failures":                   bool(self.has_failures),
            "error":                          self.error,
        }


def brain_coverage_for_vault(vault_id: str) -> BrainCoverage:


    if not vault_id:
        return BrainCoverage(vault_id="", error="empty_vault_id")

    try:
        return _query_brain_coverage(vault_id)
    except Exception as exc:
                                                             
        logger.warning(
            "[brain-coverage] aggregate failed vault=%s cls=%s",
            _short(vault_id), type(exc).__name__,
        )
        return BrainCoverage(
            vault_id=vault_id, error=type(exc).__name__,
        )


def _query_brain_coverage(vault_id: str) -> BrainCoverage:


    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()

                                                                     
        cur.execute(
            """
            SELECT
                COUNT(*)                                          AS total_files,
                COUNT(*) FILTER (
                    WHERE extracted_text_status = 'available'
                )                                                 AS with_text,
                COUNT(*) FILTER (
                    WHERE analysis_status = 'unsupported'
                )                                                 AS unsupported
            FROM uploaded_files
            WHERE vault_id = %s
              AND upload_status = 'complete'
            """,
            (vault_id,),
        )
        row = cur.fetchone() or (0, 0, 0)
        total_files, with_text, unsupported = (
            int(row[0] or 0), int(row[1] or 0), int(row[2] or 0),
        )

                                                                     
        try:
            cur.execute(
                """
                WITH per_file AS (
                    SELECT
                        c.file_id,
                        COUNT(*)                                  AS total_chunks,
                        COUNT(*) FILTER (
                            WHERE c.embedding IS NOT NULL
                        )                                         AS embedded_chunks
                    FROM vault_content_chunks c
                    WHERE c.vault_id = %s
                    GROUP BY c.file_id
                )
                SELECT
                    COALESCE(SUM(total_chunks), 0)                AS chunks_total,
                    COALESCE(SUM(embedded_chunks), 0)             AS chunks_embedded,
                    COUNT(*)                                      AS files_with_any_chunks,
                    COUNT(*) FILTER (
                        WHERE embedded_chunks > 0
                    )                                             AS files_with_any_emb,
                    COUNT(*) FILTER (
                        WHERE embedded_chunks = total_chunks
                          AND total_chunks > 0
                    )                                             AS files_fully_embedded,
                    COUNT(*) FILTER (
                        WHERE embedded_chunks > 0
                          AND embedded_chunks < total_chunks
                    )                                             AS files_partial_emb,
                    COUNT(*) FILTER (
                        WHERE embedded_chunks < total_chunks
                    )                                             AS files_with_unembedded
                FROM per_file
                """,
                (vault_id,),
            )
            row = cur.fetchone() or (0, 0, 0, 0, 0, 0, 0)
            chunks_total          = int(row[0] or 0)
            chunks_embedded       = int(row[1] or 0)
            files_with_any_chunks = int(row[2] or 0)
            files_with_any_emb    = int(row[3] or 0)
            files_fully_embedded  = int(row[4] or 0)
            files_partial_emb     = int(row[5] or 0)
            files_unembedded      = int(row[6] or 0)
        except Exception:
                                                             
            conn.rollback()
            chunks_total = chunks_embedded = 0
            files_with_any_chunks = files_with_any_emb = 0
            files_fully_embedded = files_partial_emb = 0
            files_unembedded = 0
        chunks_unembedded = max(0, chunks_total - chunks_embedded)
        files_chunked = files_with_any_chunks

                                                                  
        try:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE stage = 'content_chunking'
                        AND status IN ('pending', 'processing')
                    )                                             AS pend_chunking,
                    COUNT(*) FILTER (
                        WHERE stage = 'content_chunking'
                        AND status = 'failed'
                    )                                             AS fail_chunking,
                    COUNT(*) FILTER (
                        WHERE stage = 'file_embedding'
                        AND status IN ('pending', 'processing')
                    )                                             AS pend_embedding,
                    COUNT(*) FILTER (
                        WHERE stage = 'file_embedding'
                        AND status = 'failed'
                    )                                             AS fail_embedding
                FROM vault_analysis_jobs
                WHERE vault_id = %s
                """,
                (vault_id,),
            )
            row = cur.fetchone() or (0, 0, 0, 0)
            pend_chunking   = int(row[0] or 0)
            fail_chunking   = int(row[1] or 0)
            pend_embedding  = int(row[2] or 0)
            fail_embedding  = int(row[3] or 0)
        except Exception:
            conn.rollback()
            pend_chunking = fail_chunking = 0
            pend_embedding = fail_embedding = 0

        conn.commit()
    finally:
        conn.close()

                                                                   
    files_missing_chunks = max(0, with_text - files_chunked)
                                                                  
                                                                
    files_missing_embeddings = files_unembedded

    return BrainCoverage(
        vault_id=vault_id,
        total_files=total_files,
        files_with_extracted_text=with_text,
        files_with_chunks=files_chunked,
        files_with_any_chunks=files_with_any_chunks,
                                                         
                                                                 
        files_with_embedded_chunks=files_with_any_emb,
        files_with_all_chunks_embedded=files_fully_embedded,
        files_with_partial_embeddings=files_partial_emb,
        files_missing_chunks=files_missing_chunks,
        files_missing_embeddings=files_missing_embeddings,
        chunks_total=chunks_total,
        chunks_embedded=chunks_embedded,
        chunks_unembedded=chunks_unembedded,
        pending_chunking_jobs=pend_chunking,
        pending_embedding_jobs=pend_embedding,
        failed_chunking_jobs=fail_chunking,
        failed_embedding_jobs=fail_embedding,
        unsupported_files=unsupported,
    )


def _short(s: str) -> str:
    if not s:
        return ""
    return s[:8] + "…" if len(s) > 8 else s


__all__ = [
    "BrainCoverage",
    "brain_coverage_for_vault",
]
