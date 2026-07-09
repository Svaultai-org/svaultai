

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS = "search_files_for_credentials"
DEEP_INTENT_SEARCH_FILES_ABOUT = "search_files_about"
DEEP_INTENT_LIST_BY_TAG = "list_by_tag"
DEEP_INTENT_TRAVEL_READINESS = "travel_readiness"
DEEP_INTENT_RELATED_FILES = "related_files"
DEEP_INTENT_VAULT_CLUSTERS = "vault_clusters"

                                                                  
DEEP_REQUIRED_INTENTS: frozenset[str] = frozenset({
    DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
    DEEP_INTENT_SEARCH_FILES_ABOUT,
    DEEP_INTENT_LIST_BY_TAG,
    DEEP_INTENT_TRAVEL_READINESS,
    DEEP_INTENT_RELATED_FILES,
    DEEP_INTENT_VAULT_CLUSTERS,
})


STAGE_LABELS: dict[str, str] = {
    "text_extraction":     "Reading files",
    "ocr":                 "Checking images",
    "archive_indexing":    "Inspecting archives",
    "audio_transcription": "Transcribing audio",
    "video_transcription": "Transcribing video",
    "file_understanding":  "Reviewing scanned content",
    "file_embedding":      "Preparing results",
}


def required_stages_for_intent(intent: str) -> tuple[str, ...]:


    if intent == DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS:
        return (
            "text_extraction", "ocr", "archive_indexing",
            "audio_transcription", "video_transcription",
        )
    if intent in (
        DEEP_INTENT_SEARCH_FILES_ABOUT,
        DEEP_INTENT_LIST_BY_TAG,
        DEEP_INTENT_TRAVEL_READINESS,
        DEEP_INTENT_RELATED_FILES,
        DEEP_INTENT_VAULT_CLUSTERS,
    ):
        return (
            "text_extraction", "ocr", "archive_indexing",
            "audio_transcription", "video_transcription",
            "file_understanding",
        )
    return (
        "text_extraction", "ocr", "archive_indexing",
        "audio_transcription", "video_transcription",
        "file_understanding",
    )


def is_deep_intent(intent: Optional[str]) -> bool:

    return (intent or "").strip() in DEEP_REQUIRED_INTENTS


DEEP_ANSWER_STATUS_SCANNING = "scanning"
DEEP_ANSWER_STATUS_READY = "ready"
DEEP_ANSWER_STATUS_FAILED = "failed"
DEEP_ANSWER_STATUSES: tuple[str, ...] = (
    DEEP_ANSWER_STATUS_SCANNING,
    DEEP_ANSWER_STATUS_READY,
    DEEP_ANSWER_STATUS_FAILED,
)


try:
    from vault_config import worker as _worker_cfg
    _w = _worker_cfg()
    DEFAULT_MAX_WALLCLOCK_SECONDS = _w.deep_answer_max_wallclock_secs
    DEFAULT_DRAIN_BUDGET_PER_REQUEST = _w.drain_budget_per_iter
except Exception:
    DEFAULT_MAX_WALLCLOCK_SECONDS = 90.0
                                                                       
                                                                    
    DEFAULT_DRAIN_BUDGET_PER_REQUEST = 6


@dataclass
class DeepAnswerJob:
    job_id: str
    vault_id: str
    intent: str
    query: str
    status: str = DEEP_ANSWER_STATUS_SCANNING
    started_at: float = field(default_factory=time.time)
    last_step_at: float = field(default_factory=time.time)
    progress: dict = field(default_factory=dict)
    results: Optional[dict] = None
    error: Optional[str] = None
                                                                   
                                                                     
    _last_scanned: int = 0
    _no_progress_polls: int = 0

    def elapsed_seconds(self) -> float:
        return max(0.0, time.time() - self.started_at)


_JOBS: dict[tuple[str, str], DeepAnswerJob] = {}

                                                                
_JOB_TTL_SECONDS = 30 * 60

                                                                   
_STALL_THRESHOLD_POLLS = 3


def _gc_jobs(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    expired: list[tuple[str, str]] = []
    for key, job in _JOBS.items():
        if now - job.last_step_at > _JOB_TTL_SECONDS:
            expired.append(key)
    for key in expired:
        _JOBS.pop(key, None)


def reset_jobs_for_tests() -> None:


    _JOBS.clear()


def _create_job(vault_id: str, intent: str, query: str) -> DeepAnswerJob:
    job = DeepAnswerJob(
        job_id=str(uuid.uuid4()),
        vault_id=str(vault_id),
        intent=str(intent or "").strip()
        or DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
        query=str(query or "").strip(),
    )
    _JOBS[(job.vault_id, job.job_id)] = job
    return job


def _normalize_query(query: Optional[str]) -> str:


    if not query:
        return ""
                                                 
    norm = " ".join(str(query).lower().split())
    return norm


def _active_job_for(
    vault_id: str, intent: str, query: str,
) -> Optional[DeepAnswerJob]:


    _gc_jobs()
    target_intent = (str(intent or "").strip()
                     or DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS)
    target_query = _normalize_query(query)
    target_vault = str(vault_id)
    for job in _JOBS.values():
        if job.vault_id != target_vault:
            continue
        if job.status != DEEP_ANSWER_STATUS_SCANNING:
            continue
        if job.intent != target_intent:
            continue
        if _normalize_query(job.query) != target_query:
            continue
        return job
    return None


def get_job(vault_id: str, job_id: str) -> Optional[DeepAnswerJob]:
    _gc_jobs()
    return _JOBS.get((str(vault_id), str(job_id)))


def build_coverage_report(coverage: dict) -> dict:


    if not isinstance(coverage, dict):
        coverage = {}
    total = int(coverage.get("total") or 0)
    scanned = int(coverage.get("analyzed") or 0)
    pending = (
        int(coverage.get("pending") or 0)
        + int(coverage.get("not_started") or 0)
        + int(coverage.get("needs_reanalysis") or 0)
    )
    processing = int(coverage.get("processing") or 0)
    unsupported = int(coverage.get("unsupported") or 0)
    failed = int(coverage.get("failed") or 0)
    skipped = int(coverage.get("skipped") or 0)

                                                                   
    accounted = scanned + unsupported + failed + skipped
    blocked = pending + processing
    scan_complete = (total > 0) and (blocked == 0) and (accounted >= total)
    if total == 0:
        scan_complete = True                                 

    return {
        "total":         int(total),
        "scanned":       int(scanned),
        "pending":       int(pending),
        "processing":    int(processing),
        "unsupported":   int(unsupported),
        "failed":        int(failed),
        "skipped":       int(skipped),
        "scan_complete": bool(scan_complete),
    }


def progress_message(
    coverage_report: dict,
    *,
    intent: str = DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS,
    elapsed_seconds: float = 0.0,
    stage_label: Optional[str] = None,
) -> str:


    total = int(coverage_report.get("total") or 0)
    scanned = int(coverage_report.get("scanned") or 0)
    pending = int(coverage_report.get("pending") or 0)
    processing = int(coverage_report.get("processing") or 0)
    headline = {
        DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS:
            "Scanning your vault for files that contain saved credentials",
        DEEP_INTENT_SEARCH_FILES_ABOUT:
            "Scanning your vault for files about this topic",
        DEEP_INTENT_LIST_BY_TAG:
            "Scanning your vault for files matching this category",
        DEEP_INTENT_TRAVEL_READINESS:
            "Scanning your vault for travel documents",
        DEEP_INTENT_RELATED_FILES:
            "Scanning your vault for related files",
        DEEP_INTENT_VAULT_CLUSTERS:
            "Scanning your vault for connected groups of files",
    }.get(intent, "Scanning your vault")

    if coverage_report.get("scan_complete"):
        return f"I scanned {scanned} files. Preparing results."

    remaining = pending + processing
                                                               
                                                              
    if scanned == 0 and remaining > 0:
        return f"{headline}… Preparing scan…"

    progress = f"{scanned} of {total} files read so far"
    if stage_label:
        stage_line = f"{stage_label}…"
    elif remaining > 0:
        stage_line = (
            f"{remaining} file{'s' if remaining != 1 else ''} left to check."
        )
    else:
        stage_line = "Preparing results…"
    return f"{headline}… {progress}. {stage_line}"


@dataclass
class StepResult:
    coverage: dict
    drained: dict                                           
    elapsed_seconds: float


def _pick_next_stage(
    coverage_report: dict, required: tuple[str, ...],
) -> Optional[str]:


    pending = int(coverage_report.get("pending") or 0)
    processing = int(coverage_report.get("processing") or 0)
    if pending + processing == 0:
        return None
                                                                  
                                                               
    for stage in required:
        return stage                                             
    return None


DrainFn = "callable"


def _is_honestly_complete(coverage: dict) -> bool:


    total = int(coverage.get("total") or 0)
    if total == 0:
        return True
    return bool(coverage.get("scan_complete"))


def step_deep_answer(
    *,
    job: DeepAnswerJob,
    vault_id: str,
    key: bytes,
    coverage_loader,
    drain_fns: dict,
    final_results_fn,
    drain_budget: int = DEFAULT_DRAIN_BUDGET_PER_REQUEST,
    max_wallclock_seconds: float = DEFAULT_MAX_WALLCLOCK_SECONDS,
    enqueue_missing_fn=None,
) -> StepResult:


    start = time.time()
    drained_per_stage: dict[str, dict] = {}

                                              
    raw_coverage_before = coverage_loader()
    coverage_before = build_coverage_report(raw_coverage_before)
    coverage = coverage_before
    required = required_stages_for_intent(job.intent)

    elapsed = job.elapsed_seconds()

                                                                     
    enqueued_this_step = 0
    enqueue_error: Optional[str] = None
    if enqueue_missing_fn is not None:
        not_started = int(raw_coverage_before.get("not_started") or 0)
        needs_reanalysis = int(
            raw_coverage_before.get("needs_reanalysis") or 0
        )
        pending_count = int(raw_coverage_before.get("pending") or 0)
        if (not_started + needs_reanalysis + pending_count) > 0:
            try:
                enq_report = enqueue_missing_fn(vault_id) or {}
                enqueued_this_step = int(enq_report.get("enqueued") or 0)
                enqueue_error = enq_report.get("error")
            except Exception:
                logger.exception(
                    "deep-answer enqueue_missing crashed vault=%s",
                    vault_id,
                )
                enqueue_error = "enqueue_missing_crashed"
                                                                 
                                                                 
            try:
                raw_coverage_after_enqueue = coverage_loader()
                coverage = build_coverage_report(raw_coverage_after_enqueue)
            except Exception:
                pass

    stage = _pick_next_stage(coverage, required)

                                                                
    elapsed = job.elapsed_seconds()
    must_finalize = (
        _is_honestly_complete(coverage)
        or elapsed >= max_wallclock_seconds
    )

                                                        
    last_stage_attempted = stage if stage and stage in drain_fns else None

                                                                  
    if not must_finalize:
        for s in required:
            if s not in drain_fns:
                continue
            try:
                result = drain_fns[s](
                    vault_id=vault_id, key=key, max_jobs=drain_budget,
                )
            except Exception:
                logger.exception(
                    "deep-answer drain crashed stage=%s vault=%s",
                    s, vault_id,
                )
                result = {"processed": 0, "succeeded": 0, "failed": 0}
            processed = int(result.get("processed") or 0)
            drained_per_stage[s] = {
                "processed": processed,
                "succeeded": int(result.get("succeeded") or 0),
                "failed":    int(result.get("failed") or 0),
            }
            if processed > 0 and last_stage_attempted is None:
                last_stage_attempted = s
                                                                  
                                                                   
            if processed > 0:
                break
                                                             
        try:
            raw_coverage_after = coverage_loader()
            coverage = build_coverage_report(raw_coverage_after)
        except Exception:
            pass
                                                               
                                     
        elapsed = job.elapsed_seconds()
        must_finalize = (
            _is_honestly_complete(coverage)
            or elapsed >= max_wallclock_seconds
        )

                                                              
    new_scanned = int(coverage.get("scanned") or 0)
    if new_scanned > job._last_scanned:
        job._last_scanned = new_scanned
        job._no_progress_polls = 0
    else:
        job._no_progress_polls += 1

                                                          
    step_processed = sum(
        int(v.get("processed") or 0) for v in drained_per_stage.values()
    )
    step_succeeded = sum(
        int(v.get("succeeded") or 0) for v in drained_per_stage.values()
    )
    step_failed = sum(
        int(v.get("failed") or 0) for v in drained_per_stage.values()
    )
    job_jobs_enqueued = int(getattr(job, "_jobs_enqueued", 0)
        or 0) + enqueued_this_step
    job_jobs_claimed = int(getattr(job, "_jobs_claimed", 0)
        or 0) + step_processed
    job_jobs_completed = int(getattr(job, "_jobs_completed", 0)
        or 0) + step_succeeded
    job_jobs_failed = int(getattr(job, "_jobs_failed", 0)
        or 0) + step_failed
    object.__setattr__(job, "_jobs_enqueued", job_jobs_enqueued)
    object.__setattr__(job, "_jobs_claimed", job_jobs_claimed)
    object.__setattr__(job, "_jobs_completed", job_jobs_completed)
    object.__setattr__(job, "_jobs_failed", job_jobs_failed)

    registered_drains = sorted(drain_fns.keys())

                                                                      
    pending_by_stage = {
        "_note": (
            "coverage is by analysis_status, not per-stage; "
            "drain order is text_extraction → ocr → archive_indexing "
            "→ audio_transcription → video_transcription → "
            "file_understanding"
        ),
        "pending":           int(coverage.get("pending") or 0),
        "processing":        int(coverage.get("processing") or 0),
        "unsupported":       int(coverage.get("unsupported") or 0),
        "failed":            int(coverage.get("failed") or 0),
        "scanned":           int(coverage.get("scanned") or 0),
    }

    blocker_reason: Optional[str] = None
    if not must_finalize:
        total = int(coverage.get("total") or 0)
        pending = int(coverage.get("pending") or 0)
        processing = int(coverage.get("processing") or 0)
        registered_for_required = [
            s for s in required if s in drain_fns
        ]
        if enqueue_error:
            blocker_reason = enqueue_error
        elif not registered_for_required:
                                                                   
                                                                
            blocker_reason = (
                "no_worker_registered:"
                + ",".join(required)
            )
        elif stage and stage not in drain_fns:
            blocker_reason = f"no_worker_registered:{stage}"
        elif stage is None and total > 0 and pending + processing == 0:
                                                                 
                                                        
            blocker_reason = "queue_empty_but_coverage_pending"
        elif (
            pending > 0
            and enqueued_this_step == 0
            and step_processed == 0
        ):
                                                              
                                                                 
            blocker_reason = "files_pending_but_drains_returned_zero"
        elif job._no_progress_polls >= _STALL_THRESHOLD_POLLS:
            if total == 0:
                blocker_reason = "empty_vault_no_files_to_scan"
            elif new_scanned == 0:
                blocker_reason = "scan_not_started_no_files_processed_yet"
            else:
                blocker_reason = "scan_stalled_no_progress"

                                  
    stage_label = STAGE_LABELS.get(stage or "") if stage else None
    job.progress = {
        "coverage":      coverage,
        "coverage_before": coverage_before,
        "coverage_after":  coverage,
        "current_stage": stage,
        "last_stage_attempted": last_stage_attempted,
        "stage_label":   stage_label,
        "elapsed_seconds": round(elapsed, 1),
        "max_wallclock_seconds": float(max_wallclock_seconds),
        "drained":       drained_per_stage,
        "no_progress_polls": int(job._no_progress_polls),
        "blocker_reason":  blocker_reason,
                                                               
        "jobs_enqueued":   int(job_jobs_enqueued),
        "jobs_claimed":    int(job_jobs_claimed),
        "jobs_completed":  int(job_jobs_completed),
        "jobs_failed":     int(job_jobs_failed),
        "registered_drain_functions": list(registered_drains),
        "pending_by_stage": pending_by_stage,
    }
    job.last_step_at = time.time()

    if must_finalize:
                                                                  
                                                                   
        total = int(coverage.get("total") or 0)
        scanned_now = int(coverage.get("scanned") or 0)
        if (
            elapsed >= max_wallclock_seconds
            and total > 0
            and scanned_now == 0
        ):
            job.status = DEEP_ANSWER_STATUS_FAILED
            job.error = "scan_timed_out_no_files_processed"
                                                                
                                          
            if not job.progress.get("blocker_reason"):
                job.progress["blocker_reason"] = (
                    "wallclock_exceeded_no_files_processed"
                )
        else:
            try:
                results = final_results_fn(
                    vault_id=vault_id,
                    key=key,
                    intent=job.intent,
                    query=job.query,
                )
                job.results = results
                job.status = DEEP_ANSWER_STATUS_READY
            except Exception:
                logger.exception(
                    "deep-answer final results failed vault=%s job=%s",
                    vault_id, job.job_id,
                )
                job.status = DEEP_ANSWER_STATUS_FAILED
                job.error = "final_results_failed"

    return StepResult(
        coverage=coverage,
        drained=drained_per_stage,
        elapsed_seconds=round(time.time() - start, 3),
    )


def debug_job_snapshot(job: DeepAnswerJob) -> dict:


    progress = dict(job.progress or {})
    return {
        "job_id":   job.job_id,
        "vault_id": job.vault_id,
        "intent":   job.intent,
        "status":   job.status,
        "error":    job.error,
        "elapsed_seconds": round(job.elapsed_seconds(), 1),
        "coverage_before":      progress.get("coverage_before") or {},
        "coverage_after":       progress.get("coverage_after") or {},
        "last_stage_attempted": progress.get("last_stage_attempted"),
        "blocker_reason":       progress.get("blocker_reason"),
        "no_progress_polls":    int(progress.get("no_progress_polls") or 0),
        "jobs_enqueued":        int(progress.get("jobs_enqueued") or 0),
        "jobs_claimed":         int(progress.get("jobs_claimed") or 0),
        "jobs_completed":       int(progress.get("jobs_completed") or 0),
        "jobs_failed":          int(progress.get("jobs_failed") or 0),
        "registered_drain_functions":
            list(progress.get("registered_drain_functions") or []),
        "pending_by_stage":     progress.get("pending_by_stage") or {},
    }


def start_or_resume_job(
    *,
    vault_id: str,
    intent: str,
    query: str,
    existing_job_id: Optional[str] = None,
) -> DeepAnswerJob:


    if existing_job_id:
        existing = get_job(vault_id, existing_job_id)
        if existing and existing.status == DEEP_ANSWER_STATUS_SCANNING:
            return existing
    duplicate = _active_job_for(vault_id, intent, query)
    if duplicate is not None:
        return duplicate
    return _create_job(vault_id, intent, query)


def safe_job_snapshot(job: DeepAnswerJob) -> dict:


    return {
        "job_id":   job.job_id,
        "vault_id": job.vault_id,
        "intent":   job.intent,
        "query":    job.query,
        "status":   job.status,
        "progress": dict(job.progress or {}),
        "results":  job.results if job.status == DEEP_ANSWER_STATUS_READY else None,
        "error":    job.error,
        "elapsed_seconds": round(job.elapsed_seconds(), 1),
    }


__all__ = [
    "DEEP_REQUIRED_INTENTS",
    "DEEP_ANSWER_STATUSES",
    "DEEP_ANSWER_STATUS_SCANNING",
    "DEEP_ANSWER_STATUS_READY",
    "DEEP_ANSWER_STATUS_FAILED",
    "DEEP_INTENT_SEARCH_FILES_FOR_CREDENTIALS",
    "DeepAnswerJob",
    "StepResult",
    "STAGE_LABELS",
    "build_coverage_report",
    "is_deep_intent",
    "progress_message",
    "required_stages_for_intent",
    "reset_jobs_for_tests",
    "get_job",
    "start_or_resume_job",
    "step_deep_answer",
    "safe_job_snapshot",
    "debug_job_snapshot",
    "_active_job_for",
    "_normalize_query",
    "_is_honestly_complete",
    "_STALL_THRESHOLD_POLLS",
]
