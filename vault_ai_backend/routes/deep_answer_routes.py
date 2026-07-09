

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device


logger = logging.getLogger(__name__)


router = APIRouter()


class _DeepAnswerStartRequest(BaseModel):
    pin: str
    intent: str = Field(default="search_files_for_credentials", max_length=64)
    query: str = Field(default="", max_length=2000)
                                                                  
                                                                  
    job_id: Optional[str] = Field(default=None, max_length=64)


class _DeepAnswerPollRequest(BaseModel):
    pin: str


def _coverage_loader(vault_id: str):

    from vault_analysis import analysis_coverage_for_vault

    def _loader() -> dict:
        try:
            return analysis_coverage_for_vault(vault_id) or {}
        except Exception:
            logger.exception(
                "analysis_coverage_for_vault failed vault=%s", vault_id,
            )
            return {}

    return _loader


def _drain_fns():


    out: dict = {}
    try:
        from vault_analysis_worker import drain_text_extraction
        out["text_extraction"] = drain_text_extraction
    except Exception:
        logger.exception("import drain_text_extraction failed")
    try:
        from vault_ocr_worker import drain_ocr
        out["ocr"] = drain_ocr
    except Exception:
        logger.exception("import drain_ocr failed")
    try:
        from vault_archive_worker import drain_archive_indexing
        out["archive_indexing"] = drain_archive_indexing
    except Exception:
        logger.exception("import drain_archive_indexing failed")
    try:
        from vault_audio_worker import drain_audio_transcription
        out["audio_transcription"] = drain_audio_transcription
    except Exception:
        logger.exception("import drain_audio_transcription failed")
    try:
        from vault_understanding_worker import drain_file_understanding
        out["file_understanding"] = drain_file_understanding
    except Exception:
        logger.exception("import drain_file_understanding failed")
    return out


def _enqueue_missing_fn(vault_id: str) -> dict:


    try:
        from vault_analysis import enqueue_missing_analysis_jobs
    except Exception:
        logger.exception(
            "import enqueue_missing_analysis_jobs failed vault=%s",
            vault_id,
        )
        return {"enqueued": 0, "error": "enqueue_helper_unavailable"}
    try:
        return enqueue_missing_analysis_jobs(vault_id) or {}
    except Exception:
        logger.exception(
            "enqueue_missing_analysis_jobs raised vault=%s", vault_id,
        )
        return {"enqueued": 0, "error": "enqueue_helper_raised"}


def _final_results_fn(
    *, vault_id: str, key: bytes, intent: str, query: str,
) -> dict:


    if intent == "search_files_for_credentials":
        try:
            from main import (
                _list_uploaded_files_for_credential_search,
                _build_credential_files_envelope,
            )
            from vault_inventory import (
                verified_credential_files_report,
                format_credential_files_reply,
            )
            import json

            rows = _list_uploaded_files_for_credential_search(vault_id, key)
                                                                   
                                                                   
            try:
                from vault_analysis import analysis_coverage_for_vault
                from vault_deep_answer import build_coverage_report
                raw_cov = analysis_coverage_for_vault(vault_id) or {}
                coverage = build_coverage_report(raw_cov)
            except Exception:
                coverage = None
            report = verified_credential_files_report(
                rows, coverage=coverage,
            )
            matches = report["matches"]
            not_scanned = int(report.get("not_scanned_count") or 0)
            scanned = int(report.get("scanned_count") or 0)
            is_partial = bool(report.get("is_partial"))
            envelope_json = _build_credential_files_envelope(
                matches=matches,
                message=format_credential_files_reply(
                    matches,
                    not_scanned_count=not_scanned,
                    scanned_count=scanned,
                    is_partial=is_partial,
                ),
                scanned_count=scanned,
                not_scanned_count=not_scanned,
                is_partial=is_partial,
            )
            return {
                "envelope":         json.loads(envelope_json),
                "scanned":          scanned,
                "not_scanned":      not_scanned,
                "match_count":      len(matches),
                "intent":           intent,
            }
        except Exception:
            logger.exception(
                "final credential-search results failed vault=%s",
                vault_id,
            )
            return {
                "envelope":    None,
                "intent":      intent,
                "error":       "final_results_failed",
            }

                                                                    
    return {
        "envelope": None,
        "intent":   intent,
        "note":     "deep_answer_finalized_no_envelope_shim",
    }


@router.post("/vault-analysis/deep-answer")
async def deep_answer_start(
    payload: _DeepAnswerStartRequest,
    principal=Depends(verify_trusted_device),
):


    from main import get_verified_vault_key
    from vault_deep_answer import (
        start_or_resume_job,
        step_deep_answer,
        safe_job_snapshot,
    )

    vault_id = principal["vault_id"]
    key = get_verified_vault_key(vault_id, payload.pin)

    job = start_or_resume_job(
        vault_id=vault_id,
        intent=payload.intent,
        query=payload.query or "",
        existing_job_id=payload.job_id,
    )

                                                               
    try:
        step_deep_answer(
            job=job,
            vault_id=vault_id,
            key=key,
            coverage_loader=_coverage_loader(vault_id),
            drain_fns=_drain_fns(),
            final_results_fn=_final_results_fn,
            enqueue_missing_fn=_enqueue_missing_fn,
        )
    except Exception:
        logger.exception(
            "deep-answer initial step failed vault=%s job=%s",
            vault_id, job.job_id,
        )

    return safe_job_snapshot(job)


@router.post("/vault-analysis/deep-answer/{job_id}/poll")
async def deep_answer_poll(
    job_id: str,
    payload: _DeepAnswerPollRequest,
    principal=Depends(verify_trusted_device),
):


    from main import get_verified_vault_key
    from vault_deep_answer import (
        get_job,
        step_deep_answer,
        safe_job_snapshot,
        DEEP_ANSWER_STATUS_SCANNING,
    )

    vault_id = principal["vault_id"]
    job = get_job(vault_id, job_id)
    if job is None:
                                                                    
                                              
        raise HTTPException(status_code=404, detail="deep_answer_job_not_found")

    if job.status == DEEP_ANSWER_STATUS_SCANNING:
        key = get_verified_vault_key(vault_id, payload.pin)
        try:
            step_deep_answer(
                job=job,
                vault_id=vault_id,
                key=key,
                coverage_loader=_coverage_loader(vault_id),
                drain_fns=_drain_fns(),
                final_results_fn=_final_results_fn,
                enqueue_missing_fn=_enqueue_missing_fn,
            )
        except Exception:
            logger.exception(
                "deep-answer step crashed vault=%s job=%s",
                vault_id, job.job_id,
            )

    return safe_job_snapshot(job)


@router.post("/vault-analysis/deep-answer/{job_id}/debug")
async def deep_answer_debug(
    job_id: str,
    payload: _DeepAnswerPollRequest,
    principal=Depends(verify_trusted_device),
):


    from vault_deep_answer import (
        get_job,
        debug_job_snapshot,
    )
    from main import get_verified_vault_key

    vault_id = principal["vault_id"]
                                                               
                                                        
    get_verified_vault_key(vault_id, payload.pin)
    job = get_job(vault_id, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="deep_answer_job_not_found",
        )
    return debug_job_snapshot(job)


__all__ = ["router"]
