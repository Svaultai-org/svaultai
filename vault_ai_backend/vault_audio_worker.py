

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from psycopg2.extras import RealDictCursor

import vault_analysis as va
import vault_audio_transcription as at


logger = logging.getLogger(__name__)


DEFAULT_MAX_JOBS_PER_DRAIN = 1


_HANDLED_STAGE = va.STAGE_AUDIO_TRANSCRIPTION


def drain_audio_transcription(
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
                "[audio-drain] claim_next_analysis_job failed "
                "vault=%s", vault_id,
            )
            break
        if job is None:
            break
        if job.get("stage") != _HANDLED_STAGE:
            _release_unhandled_job(job)
            continue

        ok = _process_one_audio_job(
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


def _process_one_audio_job(
    *, job: dict, vault_id: str, key: bytes,
) -> bool:


    job_id = job["job_id"]
    file_id = job["file_id"]

    try:
        row = _load_file_row_for_audio(
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
    storage_mode = (row.get("storage_mode") or "inline").lower()
    encrypted_blob = row.get("encrypted_file_data")

    if not at.supports_audio_transcription(
        file_name=file_name, content_type=content_type,
    ):
        va.mark_file_analysis_unsupported(file_id, vault_id=vault_id)
        va.fail_analysis_job(
            job_id,
            error=f"audio transcription not supported for {file_name!r}",
            retry=False,
        )
        return False

                                       
    plaintext_bytes: Optional[bytes] = None
    if storage_mode == "inline":
        if not encrypted_blob:
            va.mark_file_analysis_failed(
                file_id, vault_id=vault_id,
                error="no encrypted bytes to transcribe",
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
                error="audio decrypt failed",
            )
            va.fail_analysis_job(
                job_id, error=f"decrypt failed: {exc}", retry=False,
            )
            return False
    else:
                                                               
                                                              
        va.mark_file_analysis_unsupported(file_id, vault_id=vault_id)
        va.fail_analysis_job(
            job_id,
            error=(
                f"audio transcription for chunked storage not "
                f"implemented yet (storage_mode={storage_mode!r})"
            ),
            retry=False,
        )
        return False

                                           
    va.mark_file_analysis_processing(file_id, vault_id=vault_id)
    try:
        text, truncated = at.transcribe_audio(
            file_name=file_name,
            file_bytes=plaintext_bytes,
            content_type=content_type,
        )
    except at.AudioTranscriptionError as exc:
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
            error="transcription returned no text",
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
            source="transcript",
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
            "[audio] enqueue understanding failed file=%s", file_id,
        )

                                                         
    try:
        va.enqueue_analysis_job(
            vault_id=vault_id, file_id=file_id,
            stage=va.STAGE_CONTENT_CHUNKING,
        )
    except Exception:
        logger.exception(
            "[audio] enqueue content_chunking failed file=%s",
            file_id,
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
            "[audio] stale housekeeping failed file=%s", file_id,
        )

    try:
        from vault_intelligence_updater import on_file_transcribed
        on_file_transcribed(vault_id)
    except Exception:
        pass

    return True


def _get_db():
    try:
        from main import get_db                
    except Exception:
        from vault_core import get_db                
    return get_db()


def _load_file_row_for_audio(
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
            SET extracted_text             = %s,
                extracted_text_encrypted   = TRUE,
                extracted_text_status      = 'available',
                extracted_text_source      = %s,
                extracted_text_updated_at  = %s,
                extracted_text_truncated   = %s,
                extracted_text_char_count  = %s,
                extracted_text_version     = COALESCE(extracted_text_version, 0) + 1
            WHERE id = %s AND vault_id = %s
            """,
            (
                encrypted_text, source, now, bool(truncated),
                int(char_count), file_id, vault_id,
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
            "[audio-drain] release unhandled job failed job=%s "
            "stage=%s",
            job.get("job_id"), job.get("stage"),
        )


def _empty_report() -> dict:
    return {
        "processed":  0,
        "succeeded":  0,
        "failed":     0,
        "drained_at": datetime.now(timezone.utc).isoformat(),
    }
