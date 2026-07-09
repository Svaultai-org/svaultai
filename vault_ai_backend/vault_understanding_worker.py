

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import RealDictCursor

import vault_analysis as va
import vault_understanding as vu


logger = logging.getLogger(__name__)


DEFAULT_MAX_JOBS_PER_DRAIN = 3


_HANDLED_STAGE = va.STAGE_FILE_UNDERSTANDING


def drain_file_understanding(
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
                "[understanding-drain] claim failed vault=%s",
                vault_id,
            )
            break
        if job is None:
            break
        if job.get("stage") != _HANDLED_STAGE:
            _release_unhandled_job(job)
            continue

        ok = _process_one_understanding_job(
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


def enqueue_understanding_after_text_extraction(
    *, vault_id: str, file_id: str,
    metadata: Optional[dict] = None,
) -> Optional[str]:


    return va.enqueue_analysis_job(
        vault_id=vault_id,
        file_id=file_id,
        stage=_HANDLED_STAGE,
        metadata=metadata,
    )


def _process_one_understanding_job(
    *, job: dict, vault_id: str, key: bytes,
) -> bool:
    job_id = job["job_id"]
    file_id = job["file_id"]

    try:
        row = _load_file_row_for_understanding(
            vault_id=vault_id, file_id=file_id,
        )
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
    extracted_text_status = (row.get("extracted_text_status") or "").lower()
    encrypted_text = row.get("extracted_text")
    source_text_version = int(row.get("extracted_text_version") or 0)

                                                                   
    if extracted_text_status != "available" or not encrypted_text:
        try:
            vu.upsert_understanding(
                vault_id=vault_id,
                file_id=file_id,
                record={
                    "status":             vu.UNDERSTANDING_STATUS_UNSUPPORTED,
                    "analysis_version":   vu.CURRENT_ANALYSIS_VERSION,
                    "document_purpose":   None,
                    "purpose_label":      "",
                    "purpose_confidence": 0.0,
                    "summary":             "",
                    "safe_preview":        "",
                    "topics":              [],
                    "entities":            {},
                    "dates":               [],
                    "detected_categories": [],
                    "credential_signals":  {},
                    "travel_signals":      {},
                    "financial_signals":   {},
                    "legal_signals":       {},
                    "identity_signals":    {},
                    "relationship_signals": {},
                    "searchable_terms":    [],
                    "confidence":          {"purpose": 0.0},
                },
                source_text_version=source_text_version,
                summary_encrypted=None,
                safe_preview_encrypted=None,
            )
        except Exception:
            logger.exception(
                "[understanding] upsert unsupported failed file=%s",
                file_id,
            )
        va.complete_analysis_job(job_id)
        return True

                                          
    plaintext: Optional[str] = None
    try:
        from vault_core import decrypt_message
        plaintext = decrypt_message(encrypted_text, key)
    except Exception as exc:
        vu.mark_understanding_failed(
            vault_id=vault_id, file_id=file_id,
            error=f"text decrypt failed: {exc}",
        )
        va.fail_analysis_job(
            job_id, error=f"text decrypt failed: {exc}",
            retry=False,
        )
        return False

                                                              
    archive_signals = None
    raw_meta = job.get("metadata_jsonb") if isinstance(job, dict) else None
    if isinstance(raw_meta, dict):
        candidate = raw_meta.get("archive_signals")
        if isinstance(candidate, dict):
            archive_signals = candidate
    elif isinstance(raw_meta, str):
        try:
            import json as _json
            parsed = _json.loads(raw_meta)
            if isinstance(parsed, dict):
                candidate = parsed.get("archive_signals")
                if isinstance(candidate, dict):
                    archive_signals = candidate
        except Exception:
            archive_signals = None

                                
    try:
        from vault_inventory import _compute_credential_density_metrics
        from vault_document_purpose import classify_document_purpose

        metrics = _compute_credential_density_metrics(plaintext)
        purpose_decision = classify_document_purpose(
            plaintext, metrics=metrics,
        )
        record = vu.build_understanding(
            plaintext,
            metrics=metrics,
            purpose_decision=purpose_decision,
            file_name=file_name,
            content_type=content_type,
            archive_signals=archive_signals,
        )
    except Exception as exc:
        vu.mark_understanding_failed(
            vault_id=vault_id, file_id=file_id,
            error=f"build_understanding failed: {exc}",
        )
        va.fail_analysis_job(
            job_id, error=f"build_understanding failed: {exc}",
            retry=False,
        )
        return False
    finally:
                                                                
                                          
        plaintext = None              

                                         
    summary_enc: Optional[str] = None
    preview_enc: Optional[str] = None
    try:
        from vault_core import encrypt_message
        if record.get("summary"):
            summary_enc = encrypt_message(record["summary"], key)
        if record.get("safe_preview"):
            preview_enc = encrypt_message(record["safe_preview"], key)
    except Exception as exc:
        vu.mark_understanding_failed(
            vault_id=vault_id, file_id=file_id,
            error=f"summary encrypt failed: {exc}",
        )
        va.fail_analysis_job(
            job_id, error=f"encrypt failed: {exc}", retry=False,
        )
        return False
    finally:
                                                            
                    
        if "summary" in record:
            record["summary"] = ""
        if "safe_preview" in record:
            record["safe_preview"] = ""

                       
    try:
        vu.upsert_understanding(
            vault_id=vault_id,
            file_id=file_id,
            record=record,
            source_text_version=source_text_version,
            summary_encrypted=summary_enc,
            safe_preview_encrypted=preview_enc,
        )
    except Exception as exc:
        va.fail_analysis_job(
            job_id, error=f"upsert failed: {exc}", retry=True,
        )
        return False

    va.complete_analysis_job(job_id)

                                                                  
    try:
        import vault_embedding_worker as vew
        vew.enqueue_embedding_after_understanding(
            vault_id=vault_id, file_id=file_id,
        )
    except Exception:
                                                                 
                                                              
        logger.exception(
            "[understanding] enqueue embedding failed file=%s",
            file_id,
        )

                                                           
    try:
        import vault_relationship_worker as vrw
        vrw.enqueue_relationship_building(vault_id=vault_id)
    except Exception:
        logger.exception(
            "[understanding] enqueue relationship_building failed "
            "vault=%s file=%s", vault_id, file_id,
        )

    return True


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _load_file_row_for_understanding(
    *, vault_id: str, file_id: str,
) -> Optional[dict]:
    conn = _get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, file_name, content_type, file_size,
                   extracted_text, extracted_text_status,
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
            "[understanding-drain] release unhandled job failed "
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
