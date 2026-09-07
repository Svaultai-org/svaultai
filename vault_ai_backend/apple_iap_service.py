"""Server-side verification and entitlement updates for Apple storage IAP.

The device supplies a StoreKit 2 signed transaction. Nothing from the device
is trusted until Apple's certificate chain and the SVaultAI app identifiers
have been verified by Apple's official server library.
"""
from __future__ import annotations

import json
import os
from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.signed_data_verifier import (
    SignedDataVerifier,
    VerificationException,
)

BUNDLE_ID = "com.svaultai.app"
APP_APPLE_ID = 6800601455
BLOCK_BYTES = 53_687_091_200
PRODUCT_BLOCKS = {
    "com.svaultai.app.storage.50gb.monthly.v2": 1,
    "com.svaultai.app.storage.100gb.monthly.v2": 2,
    "com.svaultai.app.storage.150gb.monthly.v2": 3,
    "com.svaultai.app.storage.200gb.monthly.v2": 4,
    "com.svaultai.app.storage.250gb.monthly.v2": 5,
    "com.svaultai.app.storage.500gb.monthly.v2": 10,
    "com.svaultai.app.storage.1tb.monthly.v2": 20,
    "com.svaultai.app.storage.2tb.monthly.v2": 40,
    "com.svaultai.app.storage.5tb.monthly.v2": 100,
}
ACTIVE_STATUSES = {"active", "in_grace", "canceled_pending"}

# Apple Root CA G2/G3 DER certificates published by Apple PKI. Embedding the
# public trust anchors keeps transaction verification available in immutable
# containers while APPLE_ROOT_CERTIFICATE_PATHS remains an operator override.
_APPLE_ROOT_CERTIFICATES_B64 = (
    "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",
)


class AppleIAPConfigurationError(RuntimeError):
    pass


class AppleIAPVerificationError(ValueError):
    pass


class AppleIAPAccountConflictError(ValueError):
    pass


def _field(value: Any, *names: str) -> Any:
    for name in names:
        candidate = getattr(value, name, None)
        if candidate is not None:
            return candidate
    return None


def _load_roots() -> list[bytes]:
    paths = [
        item.strip()
        for item in os.getenv("APPLE_ROOT_CERTIFICATE_PATHS", "").split(",")
        if item.strip()
    ]
    if not paths:
        return [b64decode(value, validate=True) for value in _APPLE_ROOT_CERTIFICATES_B64]
    try:
        return [open(path, "rb").read() for path in paths]
    except OSError as exc:
        raise AppleIAPConfigurationError(
            "An Apple root certificate could not be loaded"
        ) from exc


def _verifier(environment: Environment) -> SignedDataVerifier:
    return SignedDataVerifier(
        _load_roots(),
        True,
        environment,
        BUNDLE_ID,
        APP_APPLE_ID if environment == Environment.PRODUCTION else None,
    )


def verify_transaction(signed_transaction: str) -> tuple[Any, str]:
    if not signed_transaction or len(signed_transaction) > 100_000:
        raise AppleIAPVerificationError("Invalid signed transaction")
    last_error: Optional[Exception] = None
    for environment, label in (
        (Environment.PRODUCTION, "production"),
        (Environment.SANDBOX, "sandbox"),
    ):
        try:
            return (
                _verifier(environment).verify_and_decode_signed_transaction(
                    signed_transaction
                ),
                label,
            )
        except VerificationException as exc:
            last_error = exc
    raise AppleIAPVerificationError("Apple transaction verification failed") from last_error


def verify_notification(signed_payload: str) -> tuple[Any, Any, str]:
    if not signed_payload or len(signed_payload) > 200_000:
        raise AppleIAPVerificationError("Invalid signed notification")
    last_error: Optional[Exception] = None
    for environment, label in (
        (Environment.PRODUCTION, "production"),
        (Environment.SANDBOX, "sandbox"),
    ):
        verifier = _verifier(environment)
        try:
            notification = verifier.verify_and_decode_notification(signed_payload)
            signed_transaction = _field(
                _field(notification, "data"), "signedTransactionInfo"
            )
            if not signed_transaction:
                raise AppleIAPVerificationError(
                    "Notification has no signed transaction"
                )
            transaction = verifier.verify_and_decode_signed_transaction(
                signed_transaction
            )
            return notification, transaction, label
        except VerificationException as exc:
            last_error = exc
    raise AppleIAPVerificationError("Apple notification verification failed") from last_error


def _ms_to_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


def apply_verified_transaction(*, account_id: str, transaction: Any, environment: str) -> dict:
    product_id = str(_field(transaction, "productId", "product_id") or "")
    blocks = PRODUCT_BLOCKS.get(product_id)
    if blocks is None:
        raise AppleIAPVerificationError("Transaction is not an SVaultAI storage product")

    transaction_id = str(_field(transaction, "transactionId", "transaction_id") or "")
    original_id = str(
        _field(transaction, "originalTransactionId", "original_transaction_id") or ""
    )
    app_account_token = str(
        _field(transaction, "appAccountToken", "app_account_token") or ""
    ).lower()
    if not transaction_id or not original_id:
        raise AppleIAPVerificationError("Apple transaction identifiers are missing")
    if app_account_token != str(account_id).lower():
        raise AppleIAPVerificationError("Purchase belongs to a different SVaultAI account")

    expires_at = _ms_to_datetime(_field(transaction, "expiresDate", "expires_date"))
    revoked_at = _ms_to_datetime(_field(transaction, "revocationDate", "revocation_date"))
    now = datetime.now(timezone.utc)
    if revoked_at is not None or expires_at is None or expires_at <= now:
        raise AppleIAPVerificationError("Apple subscription is not active")

    from vault_core import get_db

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT source, status, block_count
              FROM account_subscriptions
             WHERE account_id = %s
             FOR UPDATE
            """,
            (account_id,),
        )
        existing = cur.fetchone()
        if existing and str(existing[0]) not in {"none", "apple"} and str(existing[1]) in ACTIVE_STATUSES:
            raise AppleIAPAccountConflictError(
                "An active non-Apple storage subscription already exists"
            )
        previous_blocks = int(existing[2] or 0) if existing else 0

        cur.execute(
            """
            INSERT INTO provider_event_log (
                source, source_event_id, signature_verified, environment,
                processed_at, outcome, raw_payload_jsonb
            ) VALUES ('apple', %s, TRUE, %s, NOW(), 'processed', %s::jsonb)
            ON CONFLICT (source, source_event_id) DO NOTHING
            RETURNING source_event_id
            """,
            (transaction_id, environment, json.dumps({"product_id": product_id})),
        )
        first_processing = cur.fetchone() is not None
        if not first_processing:
            conn.rollback()
            return {"verified": True, "duplicate": True, "block_count": blocks}

        cur.execute(
            """
            INSERT INTO account_subscriptions (
                account_id, status, source, source_subscription_id,
                billing_period, block_count, purchased_bytes,
                current_period_end, cancel_at_period_end, metadata_jsonb
            ) VALUES (%s, 'active', 'apple', %s, 'monthly', %s, %s, %s, FALSE, %s::jsonb)
            ON CONFLICT (account_id) DO UPDATE SET
                status = 'active', source = 'apple',
                source_subscription_id = EXCLUDED.source_subscription_id,
                stripe_subscription_item_id = NULL,
                billing_period = 'monthly', block_count = EXCLUDED.block_count,
                purchased_bytes = EXCLUDED.purchased_bytes,
                current_period_end = EXCLUDED.current_period_end,
                cancel_at_period_end = FALSE, canceled_at = NULL,
                metadata_jsonb = EXCLUDED.metadata_jsonb, updated_at = NOW()
            """,
            (
                account_id,
                original_id,
                blocks,
                blocks * BLOCK_BYTES,
                expires_at,
                json.dumps({"product_id": product_id, "environment": environment}),
            ),
        )
        cur.execute(
            """
            INSERT INTO subscription_events (
                account_id, event_type, source, source_event_id, sales_channel,
                from_block_count, to_block_count,
                from_purchased_bytes, to_purchased_bytes, occurred_at,
                payload_jsonb
            ) VALUES (%s, 'apple_transaction', 'apple', %s, 'self_service',
                      %s, %s, %s, %s, NOW(), %s::jsonb)
            """,
            (
                account_id,
                transaction_id,
                previous_blocks,
                blocks,
                previous_blocks * BLOCK_BYTES,
                blocks * BLOCK_BYTES,
                json.dumps({"product_id": product_id, "environment": environment}),
            ),
        )
        conn.commit()
        return {"verified": True, "duplicate": False, "block_count": blocks}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_verified_notification(
    *, notification: Any, transaction: Any, environment: str
) -> dict:
    """Apply renewal/expiry notifications without trusting unsigned fields."""
    from vault_core import get_db

    original_id = str(
        _field(transaction, "originalTransactionId", "original_transaction_id") or ""
    )
    notification_id = str(_field(notification, "notificationUUID") or "")
    notification_type = str(
        _field(notification, "rawNotificationType")
        or _field(_field(notification, "notificationType"), "value")
        or "UNKNOWN"
    ).upper()
    if not original_id or not notification_id:
        raise AppleIAPVerificationError("Apple notification identifiers are missing")

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT account_id FROM account_subscriptions "
            "WHERE source = 'apple' AND source_subscription_id = %s FOR UPDATE",
            (original_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            return {"accepted": True, "outcome": "subscription_not_found"}
        account_id = str(row[0])
    finally:
        conn.close()

    inactive_types = {"EXPIRED", "REFUND", "REVOKE"}
    if notification_type not in inactive_types:
        return apply_verified_transaction(
            account_id=account_id,
            transaction=transaction,
            environment=environment,
        )

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO provider_event_log (
                source, source_event_id, signature_verified, environment,
                processed_at, outcome, raw_payload_jsonb
            ) VALUES ('apple', %s, TRUE, %s, NOW(), 'processed', %s::jsonb)
            ON CONFLICT (source, source_event_id) DO NOTHING
            RETURNING source_event_id
            """,
            (
                notification_id,
                environment,
                json.dumps({"notification_type": notification_type}),
            ),
        )
        if cur.fetchone() is None:
            conn.rollback()
            return {"accepted": True, "outcome": "duplicate"}
        cur.execute(
            """
            UPDATE account_subscriptions
               SET status = 'expired', cancel_at_period_end = FALSE,
                   canceled_at = NOW(), updated_at = NOW()
             WHERE account_id = %s AND source = 'apple'
            """,
            (account_id,),
        )
        cur.execute(
            """
            INSERT INTO subscription_events (
                account_id, event_type, source, source_event_id, sales_channel,
                occurred_at, payload_jsonb
            ) VALUES (%s, %s, 'apple', %s, 'self_service', NOW(), %s::jsonb)
            """,
            (
                account_id,
                notification_type.lower(),
                notification_id,
                json.dumps({"environment": environment}),
            ),
        )
        conn.commit()
        return {"accepted": True, "outcome": "processed"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
