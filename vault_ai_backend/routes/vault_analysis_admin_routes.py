

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from device_gate import verify_trusted_device


logger = logging.getLogger(__name__)


router = APIRouter()


class _PinRequest(BaseModel):
    pin: str


class _DrainRequest(BaseModel):
    pin: str
    max_jobs: Optional[int] = None


@router.post("/vault-analysis/coverage")
async def vault_analysis_coverage(
    payload: _PinRequest,
    principal=Depends(verify_trusted_device),
):


    from vault_analysis import analysis_coverage_for_vault
    from main import get_verified_vault_key

    vault_id = principal["vault_id"]
                                                               
                                         
    get_verified_vault_key(vault_id, payload.pin)

    coverage = analysis_coverage_for_vault(vault_id)
    text_coverage = _extracted_text_coverage(vault_id)
    sample = _list_recent_files_with_analysis_state(vault_id, limit=25)

    return {
        "coverage":      coverage,
        "text_coverage": text_coverage,
        "sample":        sample,
    }


@router.post("/vault-analysis/drain-text-extraction")
async def vault_analysis_drain_text_extraction(
    payload: _DrainRequest,
    principal=Depends(verify_trusted_device),
):


    from vault_analysis_worker import drain_text_extraction
    from main import get_verified_vault_key

    vault_id = principal["vault_id"]
    key = get_verified_vault_key(vault_id, payload.pin)

    max_jobs = int(payload.max_jobs) if payload.max_jobs is not None else 200
    if max_jobs < 1:
        max_jobs = 1
    if max_jobs > 1000:
        max_jobs = 1000

    report = drain_text_extraction(
        vault_id=vault_id, key=key, max_jobs=max_jobs,
    )
    return report


@router.post("/vault-analysis/backfill-chunked-text-extraction")
async def vault_analysis_backfill_chunked_text_extraction(
    payload: _PinRequest,
    principal=Depends(verify_trusted_device),
):


    from vault_analysis_worker import backfill_chunked_text_extraction_jobs
    from main import get_verified_vault_key

    vault_id = principal["vault_id"]
                                                                    
                                                                    
    get_verified_vault_key(vault_id, payload.pin)

    return backfill_chunked_text_extraction_jobs(vault_id)


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _extracted_text_coverage(vault_id: str) -> dict:


    counts = {
        "not_available": 0,
        "available":     0,
        "failed":        0,
        "stale":         0,
    }
    total = 0
    try:
        conn = _get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT extracted_text_status, COUNT(*)::INT AS n
                FROM uploaded_files
                WHERE vault_id = %s
                  AND upload_status = 'complete'
                GROUP BY extracted_text_status
                """,
                (vault_id,),
            )
            for row in cur.fetchall() or []:
                status = (row["extracted_text_status"] or "not_available").lower()
                counts[status] = counts.get(status, 0) + int(row["n"])
                total += int(row["n"])
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "_extracted_text_coverage failed for vault=%s", vault_id,
        )
    return {"total": total, **counts}


def _list_recent_files_with_analysis_state(
    vault_id: str, *, limit: int = 25,
) -> list[dict]:


    rows: list[dict] = []
    try:
        conn = _get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, file_name, relative_path, storage_mode,
                       upload_status, analysis_status,
                       analysis_last_error, analysis_updated_at,
                       extracted_text_status, extracted_text_source,
                       extracted_text_truncated,
                       extracted_text_char_count,
                       extracted_text_updated_at
                FROM uploaded_files
                WHERE vault_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (vault_id, max(1, int(limit))),
            )
            for r in cur.fetchall() or []:
                rows.append({
                    "file_id":              r["id"],
                    "file_name":            r["file_name"],
                    "relative_path":        r["relative_path"],
                    "storage_mode":         r["storage_mode"],
                    "upload_status":        r["upload_status"],
                    "analysis_status":      r["analysis_status"],
                    "analysis_last_error":  r["analysis_last_error"],
                    "analysis_updated_at":  _isoformat(r["analysis_updated_at"]),
                    "extracted_text_status":      r["extracted_text_status"],
                    "extracted_text_source":      r["extracted_text_source"],
                    "extracted_text_truncated":   r["extracted_text_truncated"],
                    "extracted_text_char_count":  r["extracted_text_char_count"],
                    "extracted_text_updated_at":  _isoformat(r["extracted_text_updated_at"]),
                })
        finally:
            conn.close()
    except Exception:
        logger.exception(
            "_list_recent_files_with_analysis_state failed for vault=%s",
            vault_id,
        )
    return rows


def _isoformat(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)
