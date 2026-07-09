

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import vault_analysis as va


logger = logging.getLogger(__name__)


DEFAULT_MAX_JOBS_PER_DRAIN = 1


_HANDLED_STAGE = va.STAGE_RELATIONSHIP_BUILDING


def drain_relationship_building(
    *,
    vault_id: str,
    key: Optional[bytes] = None,
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
                "[relgraph-drain] claim failed vault=%s", vault_id,
            )
            break
        if job is None:
            break
        if job.get("stage") != _HANDLED_STAGE:
            _release_unhandled_job(job)
            continue
        ok = _process_one_relationship_job(
            job=job, vault_id=vault_id,
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


def enqueue_relationship_building(*, vault_id: str) -> Optional[str]:


    return va.enqueue_analysis_job(
        vault_id=vault_id,
        file_id=vault_id,
        stage=_HANDLED_STAGE,
    )


def _process_one_relationship_job(
    *, job: dict, vault_id: str,
) -> bool:


    job_id = job["job_id"]
    try:
        import vault_relationship_graph as rg
        rg.build_relationships_for_vault(vault_id)
    except Exception as exc:
                                                           
                                                                 
        va.fail_analysis_job(
            job_id, error=f"relationship rebuild failed: {exc}",
            retry=False,
        )
        return False
    va.complete_analysis_job(job_id)
    return True


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
            "[relgraph-drain] release unhandled job failed job=%s "
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
