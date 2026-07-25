"""Billing-lifecycle notification hooks for VaultAI.

Emits four user-facing notifications:

  * ``billing.payment_failed`` — Stripe's first (or any) failed renewal.
  * ``billing.payment_recovered`` — a subsequent successful payment
    after a prior failure or after full cancellation.
  * ``billing.subscription_cancelled`` — Stripe cancelled the
    subscription (usually after dunning exhausts).
  * ``billing.account_over_quota`` — the 30-day over-quota grace ended
    (user is stored over the free-tier headroom and hasn't
    resubscribed or freed space).

Delivery paths — both fire per event:

  * IN-APP BANNER: one row inserted into the ``notifications`` table
    for EACH vault owned by the account. The frontend polls
    ``/notifications`` and renders unread rows. ZK vaults get a
    structural (``kind`` only) shell row per the existing
    ``_create_notification`` ZK-safe policy — the frontend fills the
    ciphertext title/body on next unlock.

  * EMAIL: a placeholder ``_dispatch_billing_email`` sink that logs
    the intent and returns success. The real email pipeline is not
    yet wired into VaultAI; this module reserves the interface so a
    future SMTP / SES / Resend integration is a one-file swap. The
    placeholder never raises and never blocks the webhook path.

Never logs the raw amount charged, the last-four of the card, or any
Stripe internal identifier without redaction. All logs use
``redact_stripe_id``.

Every public function is best-effort — it swallows every exception
and logs. The webhook path MUST NOT fail because a notification
insert or email send failed.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Notification kinds — stable enum surfaced in the notifications table.
# The frontend keys off these strings to render the correct banner.
# ---------------------------------------------------------------------------

NOTIFY_KIND_PAYMENT_FAILED         = "billing.payment_failed"
NOTIFY_KIND_PAYMENT_RECOVERED      = "billing.payment_recovered"
NOTIFY_KIND_SUBSCRIPTION_CANCELLED = "billing.subscription_cancelled"
NOTIFY_KIND_ACCOUNT_OVER_QUOTA     = "billing.account_over_quota"

ALL_BILLING_KINDS: frozenset[str] = frozenset({
    NOTIFY_KIND_PAYMENT_FAILED,
    NOTIFY_KIND_PAYMENT_RECOVERED,
    NOTIFY_KIND_SUBSCRIPTION_CANCELLED,
    NOTIFY_KIND_ACCOUNT_OVER_QUOTA,
})


# ---------------------------------------------------------------------------
# Copy — kept short + honest. No marketing wording. Same string used for
# both the in-app banner title/body and the email subject/preview so
# ops can grep production for either surface.
# ---------------------------------------------------------------------------

_COPY: dict[str, tuple[str, str]] = {
    NOTIFY_KIND_PAYMENT_FAILED: (
        "Your payment didn't go through",
        "We couldn't charge your card for this month's storage. "
        "Your vault stays fully available while Stripe retries — "
        "no data lost. Update your card in Billing whenever you can.",
    ),
    NOTIFY_KIND_PAYMENT_RECOVERED: (
        "Payment recovered — thanks!",
        "Your storage subscription is fully restored. Uploads are "
        "back to normal.",
    ),
    NOTIFY_KIND_SUBSCRIPTION_CANCELLED: (
        "Your storage subscription ended",
        "Your files stay right where they are. You can still sign "
        "in, browse, download, and delete anything you have. New "
        "uploads pause until you resubscribe.",
    ),
    NOTIFY_KIND_ACCOUNT_OVER_QUOTA: (
        "You're over the free-tier limit",
        "Your subscription ended a while ago and you're still "
        "storing more than the free 1 GB. Everything you already "
        "have stays accessible. Delete anything you don't need or "
        "resubscribe to unblock new uploads.",
    ),
}


def _copy_for(kind: str) -> tuple[str, str]:
    return _COPY.get(kind, (kind, ""))


# ---------------------------------------------------------------------------
# Vault fan-out — one banner per vault in the account.
# ---------------------------------------------------------------------------

def _vault_ids_for_account(account_id: str) -> list[str]:
    """Return every vault_id owned by ``account_id``. Best-effort:
    returns an empty list on any DB error rather than raising."""
    if not account_id:
        return []
    try:
        from vault_core import get_db
    except Exception:
        return []
    try:
        conn = get_db()
    except Exception:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT vault_id FROM vaults WHERE account_id = %s",
            (account_id,),
        )
        return [str(r[0]) for r in (cur.fetchall() or [])]
    except Exception:
        logger.exception(
            "[BILLING-NOTIFY] vault fan-out failed account=%s",
            (account_id or "")[:8],
        )
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _insert_banner(
    vault_id: str,
    kind: str,
    metadata: Optional[dict] = None,
) -> None:
    """Insert one row into the ``notifications`` table via main's
    ZK-aware helper. Best-effort — errors are already swallowed by
    ``_create_notification``."""
    if not vault_id:
        return
    title, body = _copy_for(kind)
    try:
        from main import _create_notification
        _create_notification(
            vault_id=vault_id,
            kind=kind,
            title=title,
            body=body,
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "[BILLING-NOTIFY] banner insert failed kind=%s vault=%s",
            kind, (vault_id or "")[:8],
        )


def _dispatch_billing_email(
    account_id: str,
    kind: str,
    metadata: Optional[dict] = None,
) -> None:
    """Placeholder email dispatch. Real email delivery is not yet
    wired. This function is the pinned interface so a future SMTP /
    SES / Resend integration is a single-file swap.

    Never raises. Never logs the user's real email address (the
    delivery target is looked up per-account when the real
    implementation lands — for now we only log the account fingerprint,
    the kind, and the metadata keys).
    """
    if not account_id:
        return
    title, _body = _copy_for(kind)
    try:
        logger.info(
            "[BILLING-NOTIFY-EMAIL] would-send account=%s kind=%s "
            "title=%r metadata_keys=%s (email pipeline not wired yet)",
            (account_id or "")[:8], kind, title,
            ",".join(sorted((metadata or {}).keys())),
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public API — one function per notification kind.
# ---------------------------------------------------------------------------

def _fanout(
    account_id: str,
    kind: str,
    metadata: Optional[dict] = None,
) -> None:
    if not account_id or kind not in ALL_BILLING_KINDS:
        return
    # Outer swallow — a broken _vault_ids_for_account or a broken
    # _insert_banner MUST NOT propagate to the caller (webhook
    # handler). The audit-required invariant is that a notification
    # failure never fails the billing write.
    try:
        for vid in _vault_ids_for_account(account_id):
            _insert_banner(vid, kind, metadata=metadata)
    except Exception:
        logger.exception(
            "[BILLING-NOTIFY] fanout raised (swallowed) kind=%s "
            "account=%s", kind, (account_id or "")[:8],
        )
    try:
        _dispatch_billing_email(account_id, kind, metadata=metadata)
    except Exception:
        logger.exception(
            "[BILLING-NOTIFY] email dispatch raised (swallowed) "
            "kind=%s account=%s", kind, (account_id or "")[:8],
        )


def notify_payment_failed(
    account_id: str,
    *,
    invoice_id: Optional[str] = None,
    amount_due_cents: Optional[int] = None,
    grace_period_ends_at_iso: Optional[str] = None,
) -> None:
    """Fired from ``_handle_invoice_payment_failed`` and from the
    grace-period sweep when a user transitions from ``in_grace`` to
    ``past_due`` (Stripe finally gave up).
    """
    _fanout(
        account_id,
        NOTIFY_KIND_PAYMENT_FAILED,
        metadata={
            "invoice_id_prefix": (invoice_id or "")[:14] or None,
            "amount_due_cents":  amount_due_cents,
            "grace_period_ends_at": grace_period_ends_at_iso,
        },
    )


def notify_payment_recovered(
    account_id: str,
    *,
    invoice_id: Optional[str] = None,
    restored_block_count: Optional[int] = None,
) -> None:
    """Fired from ``_handle_invoice_payment_succeeded`` when the
    handler transitions a user out of ``in_grace`` / ``expired`` /
    ``over_quota_grace`` back to ``active`` (whether by simply
    flipping status or by fully restoring block_count +
    purchased_bytes)."""
    _fanout(
        account_id,
        NOTIFY_KIND_PAYMENT_RECOVERED,
        metadata={
            "invoice_id_prefix":     (invoice_id or "")[:14] or None,
            "restored_block_count":  restored_block_count,
        },
    )


def notify_subscription_cancelled(
    account_id: str,
    *,
    over_quota: bool = False,
    over_quota_grace_ends_at_iso: Optional[str] = None,
    subscription_id: Optional[str] = None,
) -> None:
    """Fired from ``_handle_subscription_deleted``. When
    ``over_quota=True`` the user is above the free-tier headroom;
    they still have full read access, but new uploads are blocked.
    """
    _fanout(
        account_id,
        NOTIFY_KIND_SUBSCRIPTION_CANCELLED,
        metadata={
            "subscription_id_prefix": (subscription_id or "")[:14] or None,
            "over_quota":             bool(over_quota),
            "over_quota_grace_ends_at": over_quota_grace_ends_at_iso,
        },
    )


def notify_account_over_quota(
    account_id: str,
    *,
    used_bytes: Optional[int] = None,
    free_tier_bytes: Optional[int] = None,
) -> None:
    """Fired from the grace-period sweep when a user transitions
    from ``over_quota_grace`` (30-day window) to ``over_quota_locked``
    (window elapsed). Reads/downloads/deletes stay available;
    uploads have been blocked since the subscription ended.
    """
    _fanout(
        account_id,
        NOTIFY_KIND_ACCOUNT_OVER_QUOTA,
        metadata={
            "used_bytes":      used_bytes,
            "free_tier_bytes": free_tier_bytes,
        },
    )


__all__ = [
    "NOTIFY_KIND_PAYMENT_FAILED",
    "NOTIFY_KIND_PAYMENT_RECOVERED",
    "NOTIFY_KIND_SUBSCRIPTION_CANCELLED",
    "NOTIFY_KIND_ACCOUNT_OVER_QUOTA",
    "ALL_BILLING_KINDS",
    "notify_payment_failed",
    "notify_payment_recovered",
    "notify_subscription_cancelled",
    "notify_account_over_quota",
]
