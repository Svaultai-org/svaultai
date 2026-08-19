"""Provider-neutral, server-verified storage entitlement ledger.

This module handles billing metadata only. It never reads vault ciphertext and
has no dependency on authentication keys, PINs, wallet keys, or card data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from psycopg2.extras import Json, RealDictCursor

from vault_core import get_db


PROVIDERS = frozenset({"apple", "google_play", "web_card", "stripe_legacy"})
VERIFICATION_STATES = frozenset({"unverified", "verified", "rejected", "error"})
NORMALIZED_STATUSES = frozenset({
    "pending", "active", "reactivated", "grace_period", "delinquent",
    "canceled", "expired", "revoked", "refunded",
})
GRANTING_STATUSES = frozenset({"active", "reactivated", "grace_period"})


class BillingProviderError(RuntimeError):
    """Base class for provider-neutral billing failures."""


class PurchaseAlreadyBoundError(BillingProviderError):
    """A verified provider purchase belongs to a different SVaultAI account."""


class StaleProviderEventError(BillingProviderError):
    """An older provider event attempted to overwrite newer state."""


@dataclass(frozen=True)
class VerifiedEntitlementUpdate:
    provider: str
    external_purchase_id: str
    product_id: str
    quantity: int
    entitlement_bytes: int
    status: str
    provider_status: str
    environment: str
    original_transaction_id: Optional[str] = None
    plan_id: Optional[str] = None
    auto_renewing: bool = False
    cancel_at_period_end: bool = False
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    provider_event_at: Optional[datetime] = None
    provider_event_id: Optional[str] = None
    metadata: Optional[Mapping[str, Any]] = None

    def validate(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError("unsupported billing provider")
        if self.status not in NORMALIZED_STATUSES:
            raise ValueError("unsupported normalized billing status")
        if self.environment not in {"sandbox", "production"}:
            raise ValueError("unsupported billing environment")
        if not self.external_purchase_id or not self.product_id:
            raise ValueError("purchase and product identity are required")
        if self.quantity < 1 or self.entitlement_bytes < 0:
            raise ValueError("invalid entitlement quantity")


@dataclass(frozen=True)
class NormalizedAccountEntitlement:
    purchased_bytes: int
    block_count: int
    status: str
    source: str
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    has_active_subscription: bool


def utc_from_rfc3339(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_google_subscription_state(
    provider_state: str,
    *,
    expiry_time: Optional[datetime],
    now: Optional[datetime] = None,
) -> str:
    """Map SubscriptionsV2 state to SVaultAI state without client trust."""
    state = (provider_state or "").strip().upper()
    now = now or datetime.now(timezone.utc)
    if expiry_time is not None and expiry_time <= now:
        return "expired"
    return {
        "SUBSCRIPTION_STATE_PENDING": "pending",
        "SUBSCRIPTION_STATE_ACTIVE": "active",
        "SUBSCRIPTION_STATE_PAUSED": "delinquent",
        "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace_period",
        "SUBSCRIPTION_STATE_ON_HOLD": "delinquent",
        # Canceled subscriptions remain entitled until expiry. The separate
        # cancel_at_period_end flag communicates that renewal is off.
        "SUBSCRIPTION_STATE_CANCELED": "active",
        "SUBSCRIPTION_STATE_EXPIRED": "expired",
        "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED": "canceled",
        # Defensive aliases used by lifecycle fixtures and older integrations.
        "SUBSCRIPTION_STATE_PENDING_PURCHASE_EXPIRED": "canceled",
        "SUBSCRIPTION_STATE_REVOKED": "revoked",
    }.get(state, "pending")


def normalize_apple_transaction_state(
    *,
    notification_type: str,
    subtype: str = "",
    expires_at: Optional[datetime],
    revoked: bool,
    now: Optional[datetime] = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    event = (notification_type or "").upper()
    sub = (subtype or "").upper()
    if revoked or event in {"REFUND", "REVOKE"}:
        return "revoked" if event == "REVOKE" else "refunded"
    if event in {"EXPIRED", "GRACE_PERIOD_EXPIRED"}:
        return "expired"
    if sub == "GRACE_PERIOD" or event == "DID_FAIL_TO_RENEW":
        return "grace_period" if expires_at is None or expires_at > now else "expired"
    if expires_at is not None and expires_at <= now:
        return "expired"
    return "active"


def claim_provider_event(
    *,
    source: str,
    event_id: str,
    signature_verified: bool,
    environment: str,
    sanitized_payload: Mapping[str, Any],
) -> bool:
    """Insert an audit event once. False means the event is a safe replay."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO provider_event_log (
                source, source_event_id, signature_verified, environment,
                raw_payload_jsonb, outcome
            ) VALUES (%s, %s, %s, %s, %s, 'processing')
            ON CONFLICT (source, source_event_id) DO UPDATE
               SET outcome = 'processing', error_text = NULL
             WHERE provider_event_log.outcome = 'error'
            RETURNING source_event_id
            """,
            (
                source, event_id, bool(signature_verified), environment,
                Json(dict(sanitized_payload)),
            ),
        )
        inserted = cur.fetchone() is not None
        conn.commit()
        return inserted
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_provider_event(
    *, source: str, event_id: str, outcome: str, error_text: Optional[str] = None,
) -> None:
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE provider_event_log
               SET processed_at = NOW(), outcome = %s, error_text = %s
             WHERE source = %s AND source_event_id = %s
            """,
            (outcome[:64], (error_text or "")[:500] or None, source, event_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_verified_entitlement(
    account_id: str,
    update: VerifiedEntitlementUpdate,
) -> tuple[str, str]:
    """Bind/update one verified purchase and return (entitlement_id, transition).

    Provider identifiers are immutable across SVaultAI accounts. This is the
    restore-purchase boundary that prevents duplicate cross-account grants.
    """
    if not account_id:
        raise ValueError("account_id required")
    update.validate()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT entitlement_id, account_id, status, last_provider_event_at
              FROM billing_entitlements
             WHERE provider = %s
               AND (
                    external_purchase_id = %s
                    OR (%s IS NOT NULL AND original_transaction_id = %s)
               )
             FOR UPDATE
            """,
            (
                update.provider,
                update.external_purchase_id,
                update.original_transaction_id,
                update.original_transaction_id,
            ),
        )
        existing = cur.fetchone()
        if existing and str(existing["account_id"]) != str(account_id):
            raise PurchaseAlreadyBoundError(
                "verified purchase is already bound to another account"
            )
        if (
            existing
            and update.provider_event_at
            and existing.get("last_provider_event_at")
            and update.provider_event_at < existing["last_provider_event_at"]
        ):
            raise StaleProviderEventError("older provider event ignored")

        previous = str(existing["status"]) if existing else "none"
        metadata = json.loads(json.dumps(dict(update.metadata or {}), default=str))
        if existing:
            entitlement_id = str(existing["entitlement_id"])
            cur.execute(
                """
                UPDATE billing_entitlements
                   SET external_purchase_id = %s,
                       original_transaction_id = COALESCE(%s, original_transaction_id),
                       product_id = %s, plan_id = %s, quantity = %s,
                       entitlement_bytes = %s, status = %s,
                       provider_status = %s, verification_state = 'verified',
                       environment = %s, auto_renewing = %s,
                       cancel_at_period_end = %s,
                       current_period_start = %s, current_period_end = %s,
                       last_verified_at = NOW(), last_provider_event_at = %s,
                       last_provider_event_id = %s, metadata_jsonb = %s,
                       updated_at = NOW()
                 WHERE entitlement_id = %s
                """,
                (
                    update.external_purchase_id, update.original_transaction_id,
                    update.product_id, update.plan_id, update.quantity,
                    update.entitlement_bytes, update.status, update.provider_status,
                    update.environment, update.auto_renewing,
                    update.cancel_at_period_end, update.current_period_start,
                    update.current_period_end, update.provider_event_at,
                    update.provider_event_id, Json(metadata), entitlement_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO billing_entitlements (
                    account_id, provider, external_purchase_id,
                    original_transaction_id, product_id, plan_id, quantity,
                    entitlement_bytes, status, provider_status,
                    verification_state, environment, auto_renewing,
                    cancel_at_period_end, current_period_start,
                    current_period_end, last_verified_at,
                    last_provider_event_at, last_provider_event_id,
                    metadata_jsonb
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'verified', %s, %s, %s, %s, %s, NOW(), %s, %s, %s
                )
                RETURNING entitlement_id
                """,
                (
                    account_id, update.provider, update.external_purchase_id,
                    update.original_transaction_id, update.product_id,
                    update.plan_id, update.quantity, update.entitlement_bytes,
                    update.status, update.provider_status, update.environment,
                    update.auto_renewing, update.cancel_at_period_end,
                    update.current_period_start, update.current_period_end,
                    update.provider_event_at, update.provider_event_id,
                    Json(metadata),
                ),
            )
            entitlement_id = str(cur.fetchone()["entitlement_id"])

        transition = "reactivated" if (
            previous in {"delinquent", "canceled", "expired", "revoked", "refunded"}
            and update.status in GRANTING_STATUSES
        ) else ("unchanged" if previous == update.status else f"{previous}_to_{update.status}")
        cur.execute(
            """
            INSERT INTO subscription_events (
                account_id, event_type, source, source_event_id, sales_channel,
                to_block_count, to_purchased_bytes, occurred_at, payload_jsonb
            ) VALUES (%s, %s, %s, %s, 'self_service', %s, %s, NOW(), %s)
            """,
            (
                account_id, transition[:64], update.provider,
                update.provider_event_id, update.quantity,
                update.entitlement_bytes,
                Json({"product_id": update.product_id, "status": update.status}),
            ),
        )
        conn.commit()
        return entitlement_id, transition
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def revoke_verified_purchase_entitlement(
    *,
    provider: str,
    account_id: str,
    external_purchase_id: str,
    provider_status: str,
    provider_event_at: datetime,
    provider_event_id: str,
    expected_product_id: Optional[str] = None,
    expected_plan_id: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> tuple[str, str]:
    """Revoke exactly one bound entitlement without deleting user data.

    This is intentionally a revoke-only operation. It cannot create a ledger
    row, transfer a purchase between accounts, or modify vault/account data.
    """
    if provider not in PROVIDERS:
        raise ValueError("unsupported billing provider")
    if not account_id or not external_purchase_id or not provider_event_id:
        raise ValueError("bound purchase and provider event identity required")
    event_at = (
        provider_event_at
        if provider_event_at.tzinfo
        else provider_event_at.replace(tzinfo=timezone.utc)
    )
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT entitlement_id, account_id, product_id, plan_id, status,
                   current_period_end, last_provider_event_at, metadata_jsonb
              FROM billing_entitlements
             WHERE provider = %s AND external_purchase_id = %s
             FOR UPDATE
            """,
            (provider, external_purchase_id),
        )
        existing = cur.fetchone()
        if not existing:
            raise BillingProviderError("verified entitlement is not bound")
        if str(existing["account_id"]) != str(account_id):
            raise PurchaseAlreadyBoundError(
                "verified purchase is already bound to another account"
            )
        if expected_product_id and str(existing["product_id"]) != expected_product_id:
            raise BillingProviderError("bound entitlement product mismatch")
        if expected_plan_id and str(existing.get("plan_id") or "") != expected_plan_id:
            raise BillingProviderError("bound entitlement plan mismatch")
        last_event_at = existing.get("last_provider_event_at")
        if last_event_at and event_at < last_event_at:
            raise StaleProviderEventError("older provider event ignored")

        previous = str(existing["status"])
        transition = (
            "unchanged" if previous == "revoked" else f"{previous}_to_revoked"
        )
        existing_metadata = existing.get("metadata_jsonb")
        merged_metadata = (
            dict(existing_metadata) if isinstance(existing_metadata, Mapping) else {}
        )
        merged_metadata.update(
            json.loads(json.dumps(dict(metadata or {}), default=str))
        )
        period_end = existing.get("current_period_end")
        if period_end is None or period_end > event_at:
            period_end = event_at

        entitlement_id = str(existing["entitlement_id"])
        cur.execute(
            """
            UPDATE billing_entitlements
               SET status = 'revoked', provider_status = %s,
                   auto_renewing = FALSE, cancel_at_period_end = FALSE,
                   current_period_end = %s, last_verified_at = NOW(),
                   last_provider_event_at = %s,
                   last_provider_event_id = %s, metadata_jsonb = %s,
                   updated_at = NOW()
             WHERE entitlement_id = %s
            """,
            (
                provider_status, period_end, event_at, provider_event_id,
                Json(merged_metadata), entitlement_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO subscription_events (
                account_id, event_type, source, source_event_id, sales_channel,
                to_block_count, to_purchased_bytes, occurred_at, payload_jsonb
            ) VALUES (%s, %s, %s, %s, 'self_service', 0, 0, NOW(), %s)
            """,
            (
                account_id, transition[:64], provider, provider_event_id,
                Json({
                    "product_id": str(existing["product_id"]),
                    "status": "revoked",
                }),
            ),
        )
        conn.commit()
        return entitlement_id, transition
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_bound_provider_entitlements(
    *, provider: str, account_id: str,
) -> list[dict[str, Any]]:
    """Return server-bound purchase identities for authoritative refresh.

    This is an internal billing operation. Purchase identifiers must never be
    returned by an HTTP response or written to logs.
    """
    if provider not in PROVIDERS:
        raise ValueError("unsupported billing provider")
    if not account_id:
        raise ValueError("account_id required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT external_purchase_id, status, product_id, plan_id
              FROM billing_entitlements
             WHERE provider = %s AND account_id = %s
             ORDER BY updated_at DESC
            """,
            (provider, account_id),
        )
        return [dict(row) for row in (cur.fetchall() or [])]
    finally:
        conn.close()


def terminalize_missing_provider_purchase(
    *,
    provider: str,
    account_id: str,
    external_purchase_id: str,
    provider_status: str,
    provider_event_at: datetime,
    provider_event_id: str,
) -> tuple[str, str, str]:
    """Fail closed when an already-bound purchase is authoritatively gone.

    A never-completed pending purchase becomes ``canceled``. A previously
    verified non-terminal purchase becomes ``expired``. Existing terminal
    states remain terminal. The operation cannot create or transfer a grant.
    """
    if provider not in PROVIDERS:
        raise ValueError("unsupported billing provider")
    if not account_id or not external_purchase_id or not provider_event_id:
        raise ValueError("bound purchase and provider event identity required")
    event_at = (
        provider_event_at
        if provider_event_at.tzinfo
        else provider_event_at.replace(tzinfo=timezone.utc)
    )
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT entitlement_id, account_id, product_id, status,
                   current_period_end, last_provider_event_at
              FROM billing_entitlements
             WHERE provider = %s AND external_purchase_id = %s
             FOR UPDATE
            """,
            (provider, external_purchase_id),
        )
        existing = cur.fetchone()
        if not existing:
            raise BillingProviderError("verified entitlement is not bound")
        if str(existing["account_id"]) != str(account_id):
            raise PurchaseAlreadyBoundError(
                "verified purchase is already bound to another account"
            )
        last_event_at = existing.get("last_provider_event_at")
        if last_event_at and event_at < last_event_at:
            raise StaleProviderEventError("older provider event ignored")

        previous = str(existing["status"])
        if previous in {"canceled", "expired", "revoked", "refunded"}:
            terminal_status = previous
        elif previous == "pending":
            terminal_status = "canceled"
        else:
            terminal_status = "expired"
        transition = (
            "unchanged"
            if previous == terminal_status
            else f"{previous}_to_{terminal_status}"
        )
        period_end = existing.get("current_period_end")
        if period_end is None or period_end > event_at:
            period_end = event_at

        entitlement_id = str(existing["entitlement_id"])
        cur.execute(
            """
            UPDATE billing_entitlements
               SET status = %s, provider_status = %s,
                   auto_renewing = FALSE, cancel_at_period_end = FALSE,
                   current_period_end = %s, last_verified_at = NOW(),
                   last_provider_event_at = %s,
                   last_provider_event_id = %s, updated_at = NOW()
             WHERE entitlement_id = %s
            """,
            (
                terminal_status, provider_status, period_end, event_at,
                provider_event_id, entitlement_id,
            ),
        )
        cur.execute(
            """
            INSERT INTO subscription_events (
                account_id, event_type, source, source_event_id, sales_channel,
                to_block_count, to_purchased_bytes, occurred_at, payload_jsonb
            ) VALUES (%s, %s, %s, %s, 'self_service', 0, 0, NOW(), %s)
            """,
            (
                account_id, transition[:64], provider, provider_event_id,
                Json({
                    "product_id": str(existing["product_id"]),
                    "status": terminal_status,
                    "reason": "authoritative_purchase_not_found",
                }),
            ),
        )
        conn.commit()
        return entitlement_id, transition, terminal_status
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def find_account_for_purchase(provider: str, external_purchase_id: str) -> Optional[str]:
    if provider not in PROVIDERS or not external_purchase_id:
        return None
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT account_id
              FROM billing_entitlements
             WHERE provider = %s AND external_purchase_id = %s
             LIMIT 1
            """,
            (provider, external_purchase_id),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def find_account_for_original_transaction(
    provider: str, original_transaction_id: str,
) -> Optional[str]:
    if provider not in PROVIDERS or not original_transaction_id:
        return None
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT account_id
              FROM billing_entitlements
             WHERE provider = %s AND original_transaction_id = %s
             LIMIT 1
            """,
            (provider, original_transaction_id),
        )
        row = cur.fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def supersede_linked_purchase(
    *, provider: str, account_id: str,
    linked_purchase_id: str, replacement_purchase_id: str,
) -> None:
    """Remove a provider-declared predecessor grant without rebinding it."""
    if provider not in PROVIDERS or not linked_purchase_id:
        return
    if linked_purchase_id == replacement_purchase_id:
        return
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE billing_entitlements
               SET status = 'canceled', auto_renewing = FALSE,
                   cancel_at_period_end = FALSE, updated_at = NOW()
             WHERE provider = %s AND account_id = %s
               AND external_purchase_id = %s
            """,
            (provider, account_id, linked_purchase_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_normalized_account_entitlement(
    account_id: str,
) -> Optional[NormalizedAccountEntitlement]:
    """Aggregate verified provider grants; return None when ledger is empty."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT provider, status, quantity, entitlement_bytes,
                   current_period_end, cancel_at_period_end
              FROM billing_entitlements
             WHERE account_id = %s
               AND verification_state = 'verified'
             ORDER BY updated_at DESC
            """,
            (account_id,),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    if not rows:
        return None

    now = datetime.now(timezone.utc)
    active = [
        r for r in rows
        if str(r["status"]) in GRANTING_STATUSES
        and (
            r["current_period_end"] is None
            or (
                r["current_period_end"]
                if r["current_period_end"].tzinfo
                else r["current_period_end"].replace(tzinfo=timezone.utc)
            ) > now
        )
    ]
    purchased = sum(int(r["entitlement_bytes"] or 0) for r in active)
    blocks = sum(int(r["quantity"] or 0) for r in active)
    sources = sorted({str(r["provider"]) for r in active})
    latest = rows[0]
    if active:
        status = "in_grace" if all(
            str(r["status"]) == "grace_period" for r in active
        ) else "active"
        source = sources[0] if len(sources) == 1 else "multiple"
        period_values = [r["current_period_end"] for r in active if r["current_period_end"]]
        period_end = max(period_values) if period_values else None
        cancel_at_end = bool(active) and all(bool(r["cancel_at_period_end"]) for r in active)
    else:
        mapped = str(latest["status"])
        latest_period_end = latest["current_period_end"]
        if (
            mapped in GRANTING_STATUSES
            and latest_period_end is not None
            and (
                latest_period_end
                if latest_period_end.tzinfo
                else latest_period_end.replace(tzinfo=timezone.utc)
            ) <= now
        ):
            mapped = "expired"
        status = (
            "past_due"
            if mapped in {"delinquent", "canceled", "expired", "revoked", "refunded"}
            else mapped
        )
        source = str(latest["provider"])
        period_end = latest["current_period_end"]
        cancel_at_end = bool(latest["cancel_at_period_end"])
    return NormalizedAccountEntitlement(
        purchased_bytes=purchased,
        block_count=blocks,
        status=status,
        source=source,
        current_period_end=period_end,
        cancel_at_period_end=cancel_at_end,
        has_active_subscription=bool(active),
    )
