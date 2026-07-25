"""Automatic deletion of unpaid vaults inactive for 6+ months.

Product rule:
  * NO pending-deletion state and NO grace period. Vaults that
    meet the (unpaid AND inactive 6mo+) predicate at run time are
    deleted immediately.
  * Paid or active vaults are NEVER deleted here.
  * A user who logs in or uses the vault before the 6mo cutoff
    updates last_any_activity_at and is no longer eligible.
  * At delete-time, the job re-checks BOTH the billing status and
    the activity timestamp to catch anything that changed since the
    candidate query.

Every eligible vault is deleted through
`vault_deletion_service.delete_vault_and_all_data` with reason
`unpaid_inactive_6_months`. That function writes a safe tombstone
and never broadcasts a crypto transaction.

Wiring: `run_once` is invoked from vault_startup at boot (best
effort), and again from a scheduled loop that re-runs daily.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from psycopg2.extras import RealDictCursor

import security_event_log as sec_log
from vault_core import get_db
from vault_deletion_service import (
    REASON_UNPAID_INACTIVE_6_MONTHS,
    VaultDeletionBlockedByStripeError,
    VaultNotFoundError,
    delete_vault_and_all_data,
)


logger = logging.getLogger(__name__)


INACTIVITY_CUTOFF_MONTHS: int = 6
_INACTIVITY_CUTOFF_DAYS: int = INACTIVITY_CUTOFF_MONTHS * 30


PAID_SUBSCRIPTION_STATUSES: frozenset[str] = frozenset({
    "active",
    "in_grace",
    "canceled_pending",
})


UNPAID_SUBSCRIPTION_STATUSES: frozenset[str] = frozenset({
    "none",
    "past_due",
    "expired",
    "paused",
    "refunded",
    "over_quota_locked",
    "over_quota_grace",
})


@dataclass(frozen=True)
class CleanupResult:
    scanned: int
    deleted: int
    skipped_now_paid: int
    skipped_now_active: int
    errors: int


def _cutoff_iso(now: datetime) -> datetime:
    return now - timedelta(days=_INACTIVITY_CUTOFF_DAYS)


def _find_candidate_vault_ids(now: datetime) -> list[str]:

    cutoff = _cutoff_iso(now)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT v.vault_id
            FROM vaults v
            LEFT JOIN account_subscriptions s
              ON s.account_id = v.account_id
            WHERE (
                s.status IS NULL
                OR s.status NOT IN (
                    'active', 'in_grace', 'canceled_pending'
                )
            )
            AND COALESCE(
                v.last_any_activity_at,
                v.updated_at,
                v.created_at
            ) < %s
            """,
            (cutoff,),
        )
        rows = cur.fetchall() or []
        return [str(r["vault_id"]) for r in rows]
    finally:
        conn.close()


def _recheck_unpaid(vault_id: str) -> tuple[bool, str]:

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT COALESCE(s.status, 'none') AS status
            FROM vaults v
            LEFT JOIN account_subscriptions s
              ON s.account_id = v.account_id
            WHERE v.vault_id = %s
            """,
            (vault_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return (False, "missing")
    status = str(row["status"])
    return (status not in PAID_SUBSCRIPTION_STATUSES, status)


def _recheck_inactive(vault_id: str, now: datetime) -> bool:

    cutoff = _cutoff_iso(now)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT COALESCE(
                last_any_activity_at,
                updated_at,
                created_at
            ) AS last_activity
            FROM vaults
            WHERE vault_id = %s
            """,
            (vault_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row is None or row["last_activity"] is None:
        return False
    return bool(row["last_activity"] < cutoff)


def run_once(now: datetime | None = None) -> CleanupResult:

    now = now or datetime.now(timezone.utc)
    scanned = 0
    deleted = 0
    skipped_now_paid = 0
    skipped_now_active = 0
    errors = 0

    # 2026-07-30 grace-state enforcer. Runs BEFORE the 180-day
    # unpaid-inactive deletion pass so any user whose in_grace or
    # over_quota_grace window has elapsed gets moved to the terminal
    # state (past_due / over_quota_locked) and receives a
    # notification. This closes the audit finding that
    # grace_period_ends_at and over_quota_grace_ends_at were set on
    # write but never enforced. The sweep is best-effort; failures
    # are logged but never block the deletion pass.
    try:
        from stripe_service import sweep_expired_grace_periods
        _sweep = sweep_expired_grace_periods()
        logger.info(
            "[INACTIVE-CLEANUP] grace-sweep in_grace=%d over_quota=%d "
            "notifications=%d errors=%d",
            _sweep.get("in_grace_expired", 0),
            _sweep.get("over_quota_grace_expired", 0),
            _sweep.get("notifications_sent", 0),
            len(_sweep.get("errors") or []),
        )
    except Exception:
        logger.exception(
            "[INACTIVE-CLEANUP] grace-sweep raised (non-fatal)",
        )

    try:
        candidates = _find_candidate_vault_ids(now)
    except Exception:
        logger.exception(
            "[INACTIVE-CLEANUP] candidate query failed",
        )
        return CleanupResult(
            scanned=0, deleted=0,
            skipped_now_paid=0, skipped_now_active=0, errors=1,
        )

    for vault_id in candidates:
        scanned += 1
        try:
            still_unpaid, _ = _recheck_unpaid(vault_id)
            if not still_unpaid:
                skipped_now_paid += 1
                continue
            if not _recheck_inactive(vault_id, now):
                skipped_now_active += 1
                continue
            delete_vault_and_all_data(
                vault_id,
                reason=REASON_UNPAID_INACTIVE_6_MONTHS,
            )
            sec_log.emit(
                reason=sec_log.REASON_INACTIVE_UNPAID_DELETED,
                route=sec_log.ROUTE_GROUP_INACTIVE_JOB,
                subject=sec_log.short_hash(vault_id),
            )
            deleted += 1
        except VaultNotFoundError:
            continue
        except VaultDeletionBlockedByStripeError as exc:
            # 2026-07-30 audit-review safety: Stripe cancellation
            # returned an error outcome (transient API failure). The
            # vault row is UNTOUCHED. We log for ops visibility and
            # skip — tomorrow's daily run will re-attempt (both
            # cancel_subscription_for_account and the vault delete
            # are idempotent, so a retry is safe even if the Stripe
            # cancel actually did succeed on the prior attempt).
            errors += 1
            logger.warning(
                "[INACTIVE-CLEANUP] deletion deferred: stripe "
                "cancel could not be confirmed hashed=%s "
                "detail=%s — will retry next daily run",
                exc.vault_id_hashed_prefix,
                exc.detail,
            )
            continue
        except Exception:
            errors += 1
            logger.exception(
                "[INACTIVE-CLEANUP] deletion failed for a "
                "candidate vault",
            )

    logger.info(
        "[INACTIVE-CLEANUP] scanned=%d deleted=%d "
        "skipped_paid=%d skipped_active=%d errors=%d",
        scanned, deleted, skipped_now_paid,
        skipped_now_active, errors,
    )
    return CleanupResult(
        scanned=scanned,
        deleted=deleted,
        skipped_now_paid=skipped_now_paid,
        skipped_now_active=skipped_now_active,
        errors=errors,
    )


_DAILY_SECS: int = 24 * 60 * 60


async def _sleep_seconds(secs: float) -> None:

    await asyncio.sleep(secs)


async def run_forever_daily(
    *, initial_delay_seconds: float = 30.0,
) -> None:

    logger.info(
        "[INACTIVE-CLEANUP] daily loop scheduled "
        "(initial_delay=%.1fs)",
        initial_delay_seconds,
    )
    try:
        await _sleep_seconds(initial_delay_seconds)
    except asyncio.CancelledError:
        return
    while True:
        try:
            await asyncio.to_thread(run_once)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception(
                "[INACTIVE-CLEANUP] run_once raised; "
                "will retry tomorrow",
            )
        try:
            await _sleep_seconds(_DAILY_SECS)
        except asyncio.CancelledError:
            return


__all__ = [
    "INACTIVITY_CUTOFF_MONTHS",
    "PAID_SUBSCRIPTION_STATUSES",
    "UNPAID_SUBSCRIPTION_STATUSES",
    "CleanupResult",
    "run_once",
    "run_forever_daily",
]
