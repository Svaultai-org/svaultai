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
PUBLIC_PROVIDERS = frozenset({"apple", "google_play", "web_card", "free"})
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


class ConflictingActiveEntitlementError(BillingProviderError):
    """A second active tier was presented without provider replacement proof."""


class StorageBillingOwnerConflictError(BillingProviderError):
    """Another verified entitlement already owns account storage billing."""


def _raise_storage_owner_conflict(exc: Exception) -> None:
    """Translate the durable database invariant into a safe domain error."""
    diagnostic = getattr(exc, "diag", None)
    if (
        getattr(diagnostic, "constraint_name", None)
        == "one_active_storage_billing_owner"
    ):
        raise StorageBillingOwnerConflictError(
            "active_storage_billing_owner"
        ) from exc


@dataclass(frozen=True)
class ScheduledEntitlementReplacement:
    """A provider-verified future total entitlement that does not grant yet."""

    product_id: str
    plan_id: str
    entitlement_bytes: int
    effective_at: datetime

    def validate(self) -> None:
        if not self.product_id or not self.plan_id:
            raise ValueError("scheduled replacement identity is required")
        if self.entitlement_bytes < 0:
            raise ValueError("scheduled replacement entitlement is invalid")
        if self.effective_at.tzinfo is None:
            raise ValueError("scheduled replacement time must be timezone-aware")


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
    provider: str = "free"
    product_id: Optional[str] = None
    base_plan_id: Optional[str] = None
    billing_period: Optional[str] = None
    storage_bytes: int = 0
    display_tier: str = "1 GB"
    subscription_status: str = "free"
    entitlement_family: str = "storage"
    ownership_status: str = "free"
    conflict_reason_code: Optional[str] = None
    current_provider: str = "free"
    target_provider: Optional[str] = None
    migration_status: str = "none"
    web_card_purchase_allowed: bool = True


CANONICAL_STORAGE_TIER_LABELS = {
    53_687_091_200: "50 GB",
    107_374_182_400: "100 GB",
    161_061_273_600: "150 GB",
    214_748_364_800: "200 GB",
    268_435_456_000: "250 GB",
    322_122_547_200: "300 GB",
    536_870_912_000: "500 GB",
    1_073_741_824_000: "1 TB",
}


def canonical_storage_display_tier(storage_bytes: int) -> str:
    """Return product-facing capacity without treating 1 TB as 1000 GB."""
    value = max(0, int(storage_bytes or 0))
    if value == 1_073_741_824:
        return "1 GB"
    known = CANONICAL_STORAGE_TIER_LABELS.get(value)
    if known:
        return known
    gib = 1024 ** 3
    if value and value % gib == 0:
        return f"{value // gib} GB"
    return f"{value} B"


def _public_provider(provider: str) -> str:
    normalized = (provider or "").strip().lower()
    if normalized == "stripe_legacy":
        return "web_card"
    return normalized if normalized in PUBLIC_PROVIDERS else "free"


def _metadata(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("metadata_jsonb") or {}
    return value if isinstance(value, Mapping) else {}


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
    if update.provider == "google_play":
        raise ValueError(
            "Google Play storage must use atomic one-of-N reconciliation"
        )
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
    except Exception as exc:
        conn.rollback()
        _raise_storage_owner_conflict(exc)
        raise
    finally:
        conn.close()


def reconcile_google_play_storage_entitlement(
    account_id: str,
    update: VerifiedEntitlementUpdate,
    *,
    linked_purchase_id: str = "",
    scheduled_replacement: Optional[ScheduledEntitlementReplacement] = None,
) -> tuple[str, str]:
    """Atomically reconcile one authoritative Google Play storage tier.

    The account/family advisory lock and partial unique index added by the
    companion migration protect against concurrent client verification and
    RTDN workers. A second active purchase is accepted only when Google links
    it to the currently granting purchase. Scheduled replacements are stored
    on the current row but contribute no bytes until Play reports them active.
    """
    if not account_id:
        raise ValueError("account_id required")
    update.validate()
    if update.provider != "google_play":
        raise ValueError("Google Play reconciliation requires google_play")
    if scheduled_replacement is not None:
        scheduled_replacement.validate()
        if update.status not in GRANTING_STATUSES:
            raise ValueError("a non-granting purchase cannot schedule a tier")
        if scheduled_replacement.entitlement_bytes >= update.entitlement_bytes:
            raise ValueError("deferred storage replacement must be a lower tier")
    linked_purchase_id = (linked_purchase_id or "").strip()
    if linked_purchase_id == update.external_purchase_id:
        raise ValueError("a purchase cannot replace itself")

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Serialize all changes for one account/family and also serialize the
        # global purchase token so cross-account restore races fail cleanly.
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"{account_id}:google_play:storage",),
        )
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"google_play:purchase:{update.external_purchase_id}",),
        )
        cur.execute(
            """
            SELECT entitlement_id, account_id, status, last_provider_event_at,
                   superseded_by_purchase_id
              FROM billing_entitlements
             WHERE provider = 'google_play'
               AND external_purchase_id = %s
             FOR UPDATE
            """,
            (update.external_purchase_id,),
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
        if (
            existing
            and existing.get("superseded_by_purchase_id")
            and update.status in GRANTING_STATUSES
        ):
            raise StaleProviderEventError("superseded purchase cannot grant")

        linked = None
        if linked_purchase_id:
            cur.execute(
                """
                SELECT entitlement_id, account_id, external_purchase_id, status
                  FROM billing_entitlements
                 WHERE provider = 'google_play'
                   AND external_purchase_id = %s
                 FOR UPDATE
                """,
                (linked_purchase_id,),
            )
            linked = cur.fetchone()
            if linked and str(linked["account_id"]) != str(account_id):
                raise PurchaseAlreadyBoundError(
                    "linked purchase is bound to another account"
                )

        cur.execute(
            """
            SELECT entitlement_id, external_purchase_id
              FROM billing_entitlements
             WHERE account_id = %s
               AND provider = 'google_play'
               AND entitlement_family = 'storage'
               AND verification_state = 'verified'
               AND status IN ('active', 'reactivated', 'grace_period')
             FOR UPDATE
            """,
            (account_id,),
        )
        active_rows = cur.fetchall() or []
        other_active = [
            row for row in active_rows
            if str(row["external_purchase_id"]) != update.external_purchase_id
        ]
        if update.status in GRANTING_STATUSES and other_active:
            if (
                len(other_active) != 1
                or not linked_purchase_id
                or str(other_active[0]["external_purchase_id"])
                != linked_purchase_id
            ):
                raise ConflictingActiveEntitlementError(
                    "active Google Play tier requires replacement linkage"
                )

        # Only a granting replacement supersedes its predecessor. Pending or
        # canceled replacement attempts must leave the existing grant intact.
        if update.status in GRANTING_STATUSES and linked_purchase_id and linked:
            cur.execute(
                """
                UPDATE billing_entitlements
                   SET status = CASE
                           WHEN status IN ('active', 'reactivated', 'grace_period')
                           THEN 'canceled'
                           ELSE status
                       END,
                       auto_renewing = CASE
                           WHEN status IN ('active', 'reactivated', 'grace_period')
                           THEN FALSE
                           ELSE auto_renewing
                       END,
                       cancel_at_period_end = CASE
                           WHEN status IN ('active', 'reactivated', 'grace_period')
                           THEN FALSE
                           ELSE cancel_at_period_end
                       END,
                       superseded_by_purchase_id = %s,
                       updated_at = NOW()
                 WHERE entitlement_id = %s
                """,
                (update.external_purchase_id, linked["entitlement_id"]),
            )

        previous = str(existing["status"]) if existing else "none"
        metadata = json.loads(json.dumps(dict(update.metadata or {}), default=str))
        scheduled_product_id = (
            scheduled_replacement.product_id if scheduled_replacement else None
        )
        scheduled_plan_id = (
            scheduled_replacement.plan_id if scheduled_replacement else None
        )
        scheduled_bytes = (
            scheduled_replacement.entitlement_bytes
            if scheduled_replacement else None
        )
        scheduled_effective_at = (
            scheduled_replacement.effective_at if scheduled_replacement else None
        )
        if existing:
            entitlement_id = str(existing["entitlement_id"])
            cur.execute(
                """
                UPDATE billing_entitlements
                   SET entitlement_family = 'storage', product_id = %s,
                       plan_id = %s, quantity = %s, entitlement_bytes = %s,
                       status = %s, provider_status = %s,
                       verification_state = 'verified', environment = %s,
                       auto_renewing = %s, cancel_at_period_end = %s,
                       current_period_start = %s, current_period_end = %s,
                       scheduled_product_id = %s, scheduled_plan_id = %s,
                       scheduled_entitlement_bytes = %s,
                       scheduled_effective_at = %s,
                       last_verified_at = NOW(), last_provider_event_at = %s,
                       last_provider_event_id = %s, metadata_jsonb = %s,
                       updated_at = NOW()
                 WHERE entitlement_id = %s
                """,
                (
                    update.product_id, update.plan_id, update.quantity,
                    update.entitlement_bytes, update.status,
                    update.provider_status, update.environment,
                    update.auto_renewing, update.cancel_at_period_end,
                    update.current_period_start, update.current_period_end,
                    scheduled_product_id, scheduled_plan_id, scheduled_bytes,
                    scheduled_effective_at, update.provider_event_at,
                    update.provider_event_id, Json(metadata), entitlement_id,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO billing_entitlements (
                    account_id, provider, entitlement_family,
                    external_purchase_id, original_transaction_id,
                    product_id, plan_id, quantity, entitlement_bytes,
                    status, provider_status, verification_state, environment,
                    auto_renewing, cancel_at_period_end, current_period_start,
                    current_period_end, scheduled_product_id,
                    scheduled_plan_id, scheduled_entitlement_bytes,
                    scheduled_effective_at, last_verified_at,
                    last_provider_event_at, last_provider_event_id,
                    metadata_jsonb
                ) VALUES (
                    %s, 'google_play', 'storage', %s, %s, %s, %s, %s, %s,
                    %s, %s, 'verified', %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, NOW(), %s, %s, %s
                )
                RETURNING entitlement_id
                """,
                (
                    account_id, update.external_purchase_id,
                    update.original_transaction_id, update.product_id,
                    update.plan_id, update.quantity, update.entitlement_bytes,
                    update.status, update.provider_status, update.environment,
                    update.auto_renewing, update.cancel_at_period_end,
                    update.current_period_start, update.current_period_end,
                    scheduled_product_id, scheduled_plan_id, scheduled_bytes,
                    scheduled_effective_at, update.provider_event_at,
                    update.provider_event_id, Json(metadata),
                ),
            )
            entitlement_id = str(cur.fetchone()["entitlement_id"])

        transition = "reactivated" if (
            previous in {"delinquent", "canceled", "expired", "revoked", "refunded"}
            and update.status in GRANTING_STATUSES
        ) else (
            "unchanged"
            if previous == update.status
            else f"{previous}_to_{update.status}"
        )
        cur.execute(
            """
            INSERT INTO subscription_events (
                account_id, event_type, source, source_event_id, sales_channel,
                to_block_count, to_purchased_bytes, occurred_at, payload_jsonb
            ) VALUES (%s, %s, 'google_play', %s, 'self_service', %s, %s, NOW(), %s)
            """,
            (
                account_id, transition[:64], update.provider_event_id,
                update.quantity, update.entitlement_bytes,
                Json({
                    "product_id": update.product_id,
                    "status": update.status,
                    "entitlement_family": "storage",
                    "replacement": bool(linked_purchase_id),
                    "scheduled_product_id": scheduled_product_id,
                }),
            ),
        )
        conn.commit()
        return entitlement_id, transition
    except Exception as exc:
        conn.rollback()
        _raise_storage_owner_conflict(exc)
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
    """Legacy helper for non-Google providers.

    Google Play replacement must never use this separate transaction; its
    predecessor and replacement are reconciled atomically by
    reconcile_google_play_storage_entitlement.
    """
    if provider not in PROVIDERS or not linked_purchase_id:
        return
    if provider == "google_play":
        raise ValueError(
            "Google Play replacement requires atomic one-of-N reconciliation"
        )
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
    """Resolve one authoritative storage owner from the verified ledger.

    Multiple active rows are never added together.  A migration's current
    provider remains authoritative; otherwise the oldest verified granting row
    is retained deterministically and the account is surfaced as a conflict for
    operator reconciliation.
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            WITH ownership_candidates AS (
                SELECT e.entitlement_id, e.provider, e.entitlement_family,
                       e.external_purchase_id, e.product_id, e.plan_id,
                       e.status, e.quantity, e.entitlement_bytes,
                       e.current_period_end, e.cancel_at_period_end,
                       e.metadata_jsonb, e.created_at, e.updated_at,
                       o.current_provider AS ownership_current_provider,
                       o.current_entitlement_id
                           AS ownership_current_entitlement_id,
                       o.legacy_subscription_account_id
                           AS ownership_legacy_subscription_account_id,
                       o.legacy_source_subscription_id
                           AS ownership_legacy_source_subscription_id,
                       o.target_provider AS ownership_target_provider,
                       o.migration_status AS ownership_migration_status,
                       o.reason_code AS ownership_reason_code,
                       'billing_entitlements'::TEXT AS entitlement_source
                  FROM billing_entitlements e
                  LEFT JOIN billing_provider_ownership o
                    ON o.account_id = e.account_id
                   AND o.entitlement_family = e.entitlement_family
                 WHERE e.account_id = %s
                   AND e.verification_state = 'verified'
                   AND e.entitlement_family = 'storage'

                UNION ALL

                SELECT NULL::UUID, 'stripe_legacy'::TEXT, 'storage'::TEXT,
                       COALESCE(
                           s.source_subscription_id,
                           'legacy-account:' || s.account_id::TEXT
                       ),
                       NULL::TEXT, NULL::TEXT,
                       CASE
                           WHEN s.status = 'in_grace' THEN 'grace_period'
                           ELSE 'active'
                       END,
                       s.block_count, s.purchased_bytes,
                       s.current_period_end, s.cancel_at_period_end,
                       jsonb_build_object(
                           'billing_period', s.billing_period,
                           'legacy_status', s.status
                       ),
                       s.created_at, s.updated_at,
                       o.current_provider,
                       o.current_entitlement_id,
                       o.legacy_subscription_account_id,
                       o.legacy_source_subscription_id,
                       o.target_provider, o.migration_status, o.reason_code,
                       'account_subscriptions'::TEXT
                  FROM account_subscriptions s
                  LEFT JOIN billing_provider_ownership o
                    ON o.account_id = s.account_id
                   AND o.entitlement_family = 'storage'
                 WHERE s.account_id = %s
                   AND s.source = 'stripe'
                   AND s.status IN (
                       'active', 'in_grace', 'canceled_pending'
                   )
                   AND s.purchased_bytes > 0
            )
            SELECT *
              FROM ownership_candidates
             ORDER BY created_at ASC, provider ASC,
                      external_purchase_id ASC
            """,
            (account_id, account_id),
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
            str(r.get("entitlement_source") or "")
            == "account_subscriptions"
            or
            r["current_period_end"] is None
            or (
                r["current_period_end"]
                if r["current_period_end"].tzinfo
                else r["current_period_end"].replace(tzinfo=timezone.utc)
            ) > now
        )
    ]
    latest = rows[-1]
    if active:
        ownership = active[0]
        migration_current = str(
            ownership.get("ownership_current_provider") or ""
        ).strip()
        if migration_current:
            exact_ledger_owner = [
                row for row in active
                if row.get("ownership_current_entitlement_id") is not None
                and row.get("entitlement_id")
                == row.get("ownership_current_entitlement_id")
            ]
            exact_legacy_owner = [
                row for row in active
                if (
                    str(row.get("entitlement_source") or "")
                    == "account_subscriptions"
                    and row.get("ownership_legacy_subscription_account_id")
                    is not None
                )
            ]
            provider_owner = [
                row for row in active
                if _public_provider(str(row["provider"]))
                == migration_current
            ]
            if exact_ledger_owner:
                ownership = exact_ledger_owner[0]
            elif exact_legacy_owner:
                ownership = exact_legacy_owner[0]
            elif provider_owner:
                ownership = provider_owner[0]
        status = (
            "in_grace"
            if str(ownership["status"]) == "grace_period"
            else "active"
        )
        source = str(ownership["provider"])
        purchased = int(ownership["entitlement_bytes"] or 0)
        blocks = int(ownership["quantity"] or 0)
        period_end = ownership["current_period_end"]
        cancel_at_end = bool(ownership["cancel_at_period_end"])
        provider = _public_provider(source)
        current_provider = provider
        product_id = str(ownership.get("product_id") or "") or None
        base_plan_id = str(ownership.get("plan_id") or "") or None
        meta = _metadata(ownership)
        billing_period = str(meta.get("billing_period") or "") or None
        display_tier = str(meta.get("display_capacity") or "") or (
            canonical_storage_display_tier(purchased)
        )
        migration_status = str(
            ownership.get("ownership_migration_status") or "none"
        )
        target_provider = str(
            ownership.get("ownership_target_provider") or ""
        ) or None
        stored_reason_code = str(
            ownership.get("ownership_reason_code") or ""
        ) or None
        conflict = (
            len(active) > 1
            or migration_status == "conflict"
            or stored_reason_code is not None
        )
        ownership_status = "conflict" if conflict else (
            "migration_pending" if migration_status == "pending" else "owned"
        )
        reason_code = (
            "multiple_active_storage_entitlements"
            if len(active) > 1
            else stored_reason_code
        )
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
        source = "free"
        provider = "free"
        purchased = 0
        blocks = 0
        period_end = latest["current_period_end"]
        cancel_at_end = bool(latest["cancel_at_period_end"])
        product_id = None
        base_plan_id = None
        billing_period = None
        display_tier = "1 GB"
        current_provider = _public_provider(str(
            latest.get("ownership_current_provider") or "free"
        ))
        migration_status = str(
            latest.get("ownership_migration_status") or "none"
        )
        target_provider = str(
            latest.get("ownership_target_provider") or ""
        ) or None
        reason_code = str(
            latest.get("ownership_reason_code") or ""
        ) or None
        conflict = migration_status == "conflict"
        ownership_status = (
            "conflict" if conflict else
            ("migration_pending" if migration_status == "pending" else "free")
        )
    return NormalizedAccountEntitlement(
        purchased_bytes=purchased,
        block_count=blocks,
        status=status,
        source=source,
        current_period_end=period_end,
        cancel_at_period_end=cancel_at_end,
        has_active_subscription=bool(active),
        provider=provider,
        product_id=product_id,
        base_plan_id=base_plan_id,
        billing_period=billing_period,
        storage_bytes=purchased,
        display_tier=display_tier,
        subscription_status=status,
        entitlement_family="storage",
        ownership_status=ownership_status,
        conflict_reason_code=reason_code,
        current_provider=current_provider,
        target_provider=target_provider,
        migration_status=migration_status,
        web_card_purchase_allowed=(
            not active
            and not conflict
            and migration_status != "pending"
        ),
    )


def web_card_purchase_allowed_for_account(account_id: str) -> bool:
    """Durable checkout guard; store ownership or conflict always blocks."""
    try:
        normalized = get_normalized_account_entitlement(account_id)
    except Exception:
        # A checkout guard must fail closed during migrations or DB faults.
        return False
    return normalized is None or normalized.web_card_purchase_allowed
