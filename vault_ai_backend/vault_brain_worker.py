

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional


logger = logging.getLogger(__name__)


try:
    from vault_config import brain as _brain_cfg, worker as _worker_cfg
    DEFAULT_MAX_JOBS_PER_DRAIN  = _worker_cfg().max_jobs_per_stage
    DEFAULT_MAX_CHUNKS_PER_FILE = _brain_cfg().max_chunks_per_file
except Exception:
    DEFAULT_MAX_JOBS_PER_DRAIN = 4
                                                                      
                                                                  
    DEFAULT_MAX_CHUNKS_PER_FILE = 256


_EMBED_FN = None


def set_embedder(embed_fn) -> None:


    global _EMBED_FN
    _EMBED_FN = embed_fn


def get_embedder():
    return _EMBED_FN


def drain_content_chunking(
    *,
    vault_id: str,
    key: bytes,
    max_jobs: int = DEFAULT_MAX_JOBS_PER_DRAIN,
) -> dict:


    if max_jobs <= 0:
        return _empty_report()
    import vault_analysis as va

    succeeded = 0
    failed = 0
    for _ in range(int(max_jobs)):
        try:
            job = va.claim_next_analysis_job(vault_id=vault_id)
        except Exception:
            logger.exception(
                "[chunking-drain] claim raised vault=%s",
                _short(vault_id),
            )
            break
        if job is None:
            break
        if job.get("stage") != va.STAGE_CONTENT_CHUNKING:
            _release_unhandled_job(job)
            continue
        ok = _process_one_chunking_job(
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


def _process_one_chunking_job(
    *, job: dict, vault_id: str, key: bytes,
) -> bool:


    import vault_analysis as va
    from vault_chunker import chunk_extracted_text
    from vault_chunk_store import write_chunks
    from vault_core import get_db, decrypt_message

    job_id = job["job_id"]
    file_id = job["file_id"]
    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT extracted_text, extracted_text_status,
                       extracted_text_source, content_type, file_name
                FROM uploaded_files
                WHERE id = %s AND vault_id = %s
                """,
                (file_id, vault_id),
            )
            row = cur.fetchone()
        finally:
            conn.close()
    except Exception as exc:
        va.fail_analysis_job(
            job_id, error=f"row load failed: {type(exc).__name__}",
            retry=True,
        )
        return False

    if row is None:
        va.fail_analysis_job(
            job_id, error="file row missing", retry=False,
        )
        return False

    encrypted_text, text_status, text_source, content_type, file_name = row

                                                                  
    if not encrypted_text or text_status != "available":
                                                                     
        write_chunks(
            vault_id=vault_id, file_id=file_id, chunks=[], key=key,
        )
        va.complete_analysis_job(job_id)
        return True

    try:
        plaintext = decrypt_message(encrypted_text, key)
    except Exception:
                                                                       
        va.fail_analysis_job(
            job_id, error="extracted_text decrypt failed",
            retry=False,
        )
        return False

    source = _map_extraction_source(text_source, content_type, file_name)
    chunks = chunk_extracted_text(plaintext, extraction_source=source)
    if len(chunks) > DEFAULT_MAX_CHUNKS_PER_FILE:
        chunks = chunks[:DEFAULT_MAX_CHUNKS_PER_FILE]

    written = write_chunks(
        vault_id=vault_id, file_id=file_id, chunks=chunks, key=key,
    )
    if written != len(chunks):
        va.fail_analysis_job(
            job_id, error=f"chunk write incomplete {written}/{len(chunks)}",
            retry=True,
        )
        return False

                                                                
    embed_fn = get_embedder()
    if embed_fn is not None and chunks:
        try:
            from vault_brain_indexer import index_chunks_for_file
            asyncio.get_event_loop().run_until_complete(
                index_chunks_for_file(
                    vault_id=vault_id, file_id=file_id,
                    embed_fn=embed_fn, key=key,
                )
            )
        except RuntimeError:
                                                                  
            try:
                from vault_brain_indexer import index_chunks_for_file
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        index_chunks_for_file(
                            vault_id=vault_id, file_id=file_id,
                            embed_fn=embed_fn, key=key,
                        )
                    )
                finally:
                    loop.close()
            except Exception:
                logger.warning(
                    "[chunking-drain] inline embed failed vault=%s "
                    "file=%s — chunks landed, vectors deferred",
                    _short(vault_id), _short(file_id),
                )
        except Exception:
            logger.warning(
                "[chunking-drain] inline embed failed vault=%s "
                "file=%s — chunks landed, vectors deferred",
                _short(vault_id), _short(file_id),
            )

    va.complete_analysis_job(job_id)

    try:
        from vault_intelligence_updater import on_file_chunked
        on_file_chunked(vault_id)
    except Exception:
        pass

    return True


def _map_extraction_source(
    text_source: Optional[str],
    content_type: Optional[str],
    file_name: Optional[str],
) -> str:


    if text_source == "ocr":
        return "ocr"
    if text_source == "transcript":
        return "audio_transcript"
    if text_source == "video_transcript":
        return "video_transcript"
    if text_source == "archive_index":
        return "archive"
                                                                 
    mime = (content_type or "").lower()
    name = (file_name or "").lower()
    if mime == "application/pdf" or name.endswith(".pdf"):
        return "pdf_text"
    if name.endswith(".docx") or "wordprocessingml" in mime:
        return "docx"
    if name.endswith(".html") or name.endswith(".htm") or mime == "text/html":
        return "html"
    if name.endswith(".json") or mime == "application/json":
        return "json"
    if name.endswith(".csv") or mime == "text/csv":
        return "csv"
    if name.endswith(".xlsx") or "spreadsheetml" in mime:
        return "xlsx"
    if mime.startswith("text/"):
        return "txt"
    return "plain_text"


def _release_unhandled_job(job: dict) -> None:


    import vault_analysis as va
    try:
        va.fail_analysis_job(
            job["job_id"],
            error=f"stage {job.get('stage')!r} not handled by content_chunking drain",
            retry=True,
        )
    except Exception:
        logger.exception(
            "[chunking-drain] failed to release unhandled stage job=%s",
            job.get("job_id"),
        )


def _empty_report() -> dict:
    return {
        "processed":  0,
        "succeeded":  0,
        "failed":     0,
        "drained_at": datetime.now(timezone.utc).isoformat(),
    }


def _short(s: str) -> str:
    if not s:
        return ""
    return s[:8] + "…" if len(s) > 8 else s


__all__ = [
    "drain_content_chunking",
    "set_embedder",
    "get_embedder",
    "DEFAULT_MAX_JOBS_PER_DRAIN",
    "DEFAULT_MAX_CHUNKS_PER_FILE",
]
