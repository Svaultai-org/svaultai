"""Compatibility entry points for the retired inactive-account cleanup.

Only an authenticated vault owner may delete an account. Startup does not
schedule this job, and these legacy entry points must never select accounts,
call payment providers, or delete data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

INACTIVITY_CUTOFF_MONTHS = 6
PAID_SUBSCRIPTION_STATUSES = frozenset({"active", "in_grace", "canceled_pending"})
UNPAID_SUBSCRIPTION_STATUSES = frozenset({
    "none", "past_due", "expired", "paused", "refunded",
    "over_quota_locked", "over_quota_grace",
})


@dataclass(frozen=True)
class CleanupResult:
    scanned: int
    deleted: int
    skipped_now_paid: int
    skipped_now_active: int
    errors: int


def run_once(now: datetime | None = None) -> CleanupResult:
    """Retained for old callers; automatic account deletion is disabled."""
    return CleanupResult(0, 0, 0, 0, 0)


async def run_forever_daily(*, initial_delay_seconds: float = 30.0) -> None:
    """Do not schedule work or delete user accounts."""
    return


__all__ = [
    "INACTIVITY_CUTOFF_MONTHS",
    "PAID_SUBSCRIPTION_STATUSES",
    "UNPAID_SUBSCRIPTION_STATUSES",
    "CleanupResult",
    "run_once",
    "run_forever_daily",
]
