"""Provider-neutral billing HTTP boundaries.

Authenticated client routes bind verified store purchases to the current
SVaultAI account. Provider notification routes authenticate and re-fetch
authoritative state before changing entitlements.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device


router = APIRouter()
logger = logging.getLogger(__name__)


class GooglePlayVerifyRequest(BaseModel):
    purchase_token: str = Field(..., min_length=1, max_length=4096)
    product_id: str = Field(..., min_length=1, max_length=200)


class GooglePlayReconcileRequest(BaseModel):
    purchase_tokens: list[str] = Field(default_factory=list, max_length=20)


class AppleTransactionRequest(BaseModel):
    signed_transaction: str = Field(..., min_length=1, max_length=100_000)
    environment: Literal["production", "sandbox"] = "production"


def _account_id(principal: dict) -> str:
    from billing import ensure_account_for_vault
    return ensure_account_for_vault(str(principal["vault_id"]))


@router.get("/billing/providers")
async def billing_providers(principal=Depends(verify_trusted_device)):
    account_id = _account_id(principal)
    from apple_billing import (
        AppleBillingConfigurationError,
        apple_app_account_token,
        configured_apple_catalog,
    )
    from google_play_billing import (
        GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        GOOGLE_PLAY_BASE_PLAN_TYPE,
        GOOGLE_PLAY_BILLING_PERIOD,
        GOOGLE_PLAY_PRODUCT_50GB,
        purchase_account_token,
    )
    apple_catalog = {}
    try:
        apple_catalog = configured_apple_catalog()
    except AppleBillingConfigurationError:
        logger.error(
            "[APPLE-BILLING] provider_catalog_unavailable "
            "reason=invalid_configuration"
        )
        apple_catalog = {}
    apple_product_ids = sorted(apple_catalog)
    apple_product = (
        apple_catalog[apple_product_ids[0]]
        if len(apple_product_ids) == 1
        else None
    )
    return {
        "web_card": {
            "checkout_enabled": False,
            "message": (
                "Storage upgrades are temporarily unavailable on the web "
                "while we update our payment provider."
            ),
        },
        "google_play": {
            "product_id": GOOGLE_PLAY_PRODUCT_50GB,
            "base_plan_id": GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
            "base_plan_type": GOOGLE_PLAY_BASE_PLAN_TYPE,
            "billing_period": GOOGLE_PLAY_BILLING_PERIOD,
            "account_token": purchase_account_token(account_id),
        },
        "apple": {
            "configured": bool(apple_product_ids),
            # The current iOS controller can purchase one configured product.
            # With zero or multiple IDs, omit the singular selection so the
            # client fails closed instead of inventing a tier.
            "product_id": (
                apple_product_ids[0]
                if len(apple_product_ids) == 1
                else None
            ),
            "product_ids": apple_product_ids,
            "billing_period": (
                apple_product["billing_period"]
                if apple_product is not None
                else None
            ),
            "storage_entitlement_bytes": (
                int(apple_product["entitlement_bytes"])
                if apple_product is not None
                else None
            ),
            "quantity": (
                int(apple_product["quantity"])
                if apple_product is not None
                else None
            ),
            "app_account_token": apple_app_account_token(account_id),
        },
        "stripe_legacy": {"checkout_enabled": False, "history_preserved": True},
    }


@router.post("/billing/web/checkout-session")
async def web_checkout_disabled(principal=Depends(verify_trusted_device)):
    _account_id(principal)
    raise HTTPException(
        status_code=503,
        detail={
            "code": "web_billing_provider_unavailable",
            "message": (
                "Storage upgrades are temporarily unavailable on the web "
                "while we update our payment provider."
            ),
        },
    )


@router.post("/billing/google-play/verify")
async def verify_google_play_purchase(
    payload: GooglePlayVerifyRequest,
    principal=Depends(verify_trusted_device),
):
    from billing_entitlements import PurchaseAlreadyBoundError
    from google_play_billing import (
        GooglePlayConfigurationError,
        GooglePlayTransientError,
        GooglePlayVerificationError,
        verify_and_apply_google_subscription,
    )
    account_id = _account_id(principal)
    try:
        result = verify_and_apply_google_subscription(
            account_id=account_id,
            purchase_token=payload.purchase_token,
            expected_product_id=payload.product_id,
        )
    except PurchaseAlreadyBoundError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "purchase_already_bound",
                "message": "This verified purchase belongs to another SVaultAI account.",
            },
        ) from exc
    except GooglePlayConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "google_play_verification_unavailable",
                "message": "Google Play verification is temporarily unavailable.",
            },
        ) from exc
    except GooglePlayTransientError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "google_play_verification_retry",
                "message": "Google Play verification is temporarily unavailable.",
            },
        ) from exc
    except GooglePlayVerificationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "google_play_purchase_invalid",
                "message": "Google Play could not verify this purchase.",
            },
        ) from exc
    return {
        "verified": True,
        "provider": "google_play",
        "product_id": result.product_id,
        "status": result.normalized_status,
        "acknowledged": result.acknowledged,
        "transition": result.transition,
        "current_period_end": (
            result.current_period_end.isoformat()
            if result.current_period_end else None
        ),
    }


@router.post("/billing/google-play/reconcile")
async def reconcile_google_play_purchases(
    payload: GooglePlayReconcileRequest,
    principal=Depends(verify_trusted_device),
):
    """Re-fetch current and server-bound purchases from Google Play.

    An empty device list is meaningful: the server still checks any bound
    non-terminal purchase before reporting the account's final entitlement.
    """
    from billing_entitlements import PurchaseAlreadyBoundError
    from google_play_billing import (
        GooglePlayConfigurationError,
        GooglePlayTransientError,
        GooglePlayVerificationError,
        reconcile_google_subscriptions,
    )

    account_id = _account_id(principal)
    try:
        result = reconcile_google_subscriptions(
            account_id=account_id,
            current_purchase_tokens=payload.purchase_tokens,
        )
    except PurchaseAlreadyBoundError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "purchase_already_bound",
                "message": "This verified purchase belongs to another SVaultAI account.",
            },
        ) from exc
    except GooglePlayConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "google_play_verification_unavailable",
                "message": "Google Play verification is temporarily unavailable.",
            },
        ) from exc
    except GooglePlayTransientError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "google_play_verification_retry",
                "message": "Google Play verification is temporarily unavailable.",
            },
        ) from exc
    except GooglePlayVerificationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "google_play_purchase_invalid",
                "message": "Google Play could not verify this purchase.",
            },
        ) from exc
    return {
        "reconciled": True,
        "provider": "google_play",
        "status": result.status,
        "has_active_subscription": result.has_active_subscription,
        "current_purchase_count": result.current_purchase_count,
        "reconciled_count": result.reconciled_count,
        "cleared_pending": result.cleared_pending,
    }


def _verify_google_pubsub_request(request: Request) -> None:
    audience = os.getenv("VAULTAI_GOOGLE_PLAY_RTDN_AUDIENCE", "").strip()
    expected_email = os.getenv(
        "VAULTAI_GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL", "",
    ).strip().lower()
    if not audience or not expected_email:
        raise HTTPException(status_code=503, detail="RTDN authentication not configured")
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="RTDN bearer token required")
    token = header.split(" ", 1)[1].strip()
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token
        claims = id_token.verify_oauth2_token(token, GoogleRequest(), audience=audience)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="RTDN identity token invalid") from exc
    if str(claims.get("email") or "").lower() != expected_email:
        raise HTTPException(status_code=403, detail="RTDN service account rejected")
    if claims.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="RTDN identity is not verified")
    if str(claims.get("aud") or "") != audience:
        raise HTTPException(status_code=403, detail="RTDN audience rejected")
    if str(claims.get("iss") or "") not in {
        "accounts.google.com", "https://accounts.google.com",
    }:
        raise HTTPException(status_code=401, detail="RTDN token issuer invalid")
    if not str(claims.get("sub") or ""):
        raise HTTPException(status_code=401, detail="RTDN token subject missing")
    try:
        issued_at = float(claims["iat"])
        expires_at = float(claims["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="RTDN token time invalid") from exc
    now = time.time()
    if (
        issued_at > now + 60
        or expires_at <= now
        or expires_at <= issued_at
        or expires_at - issued_at > 3700
    ):
        raise HTTPException(status_code=401, detail="RTDN token time invalid")


def _decode_pubsub_message(payload: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), dict):
        raise HTTPException(status_code=400, detail="invalid Pub/Sub envelope")
    message = payload["message"]
    event_id = str(message.get("messageId") or message.get("message_id") or "")
    encoded = str(message.get("data") or "")
    if not event_id or not encoded:
        raise HTTPException(status_code=400, detail="incomplete Pub/Sub envelope")
    try:
        decoded = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid Pub/Sub message data") from exc
    if not isinstance(decoded, dict):
        raise HTTPException(status_code=400, detail="invalid RTDN payload")
    return event_id, decoded


def _rtdn_event_time(notification: dict[str, Any]) -> datetime:
    raw = notification.get("eventTimeMillis")
    if isinstance(raw, bool):
        raise HTTPException(status_code=400, detail="RTDN event time invalid")
    try:
        millis = int(str(raw))
        event_time = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(status_code=400, detail="RTDN event time invalid") from exc
    if millis <= 0 or event_time > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="RTDN event time invalid")
    return event_time


def _rtdn_notification_kind(
    notification: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    supported = {
        "subscription": notification.get("subscriptionNotification"),
        "voided": notification.get("voidedPurchaseNotification"),
        "test": notification.get("testNotification"),
    }
    present = [
        (kind, value) for kind, value in supported.items()
        if isinstance(value, dict)
    ]
    unsupported_present = any(
        isinstance(notification.get(key), dict)
        for key in (
            "oneTimeProductNotification",
            "pendingRefundReviewNotification",
        )
    )
    if len(present) != 1 or unsupported_present:
        raise HTTPException(status_code=400, detail="unsupported RTDN notification")
    return present[0]


def _parse_voided_subscription(
    voided: dict[str, Any],
) -> tuple[str, str, int, int]:
    purchase_token = str(voided.get("purchaseToken") or "")
    order_id = str(voided.get("orderId") or "")
    try:
        product_type = int(voided.get("productType"))
        refund_type = int(voided.get("refundType"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="invalid voided purchase notification",
        ) from exc
    # This release has one subscription product. Quantity-based partial
    # refunds apply to one-time products and must never alter this entitlement.
    if (
        not purchase_token
        or len(purchase_token) > 4096
        or not order_id
        or len(order_id) > 512
        or product_type != 1
        or refund_type != 1
    ):
        raise HTTPException(
            status_code=400, detail="invalid voided purchase notification",
        )
    return purchase_token, order_id, product_type, refund_type


@router.post("/billing/google-play/rtdn")
async def google_play_rtdn(request: Request):
    _verify_google_pubsub_request(request)
    event_id, notification = _decode_pubsub_message(await request.json())
    from billing_entitlements import (
        StaleProviderEventError,
        claim_provider_event,
        find_account_for_purchase,
        finish_provider_event,
        revoke_verified_purchase_entitlement,
    )
    from google_play_billing import (
        GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        GOOGLE_PLAY_PACKAGE_NAME,
        GOOGLE_PLAY_PRODUCT_50GB,
        GooglePlayConfigurationError,
        GooglePlayPurchaseNotFoundError,
        GooglePlayTransientError,
        GooglePlayVerificationError,
        verify_google_subscription_identity,
        verify_and_apply_google_subscription,
    )
    if str(notification.get("version") or "") != "1.0":
        raise HTTPException(status_code=400, detail="RTDN version unsupported")
    if str(notification.get("packageName") or "") != GOOGLE_PLAY_PACKAGE_NAME:
        raise HTTPException(status_code=400, detail="RTDN package mismatch")
    event_time = _rtdn_event_time(notification)
    kind, detail = _rtdn_notification_kind(notification)
    if kind == "test":
        # Test notifications prove transport/auth without changing entitlement.
        inserted = claim_provider_event(
            source="google_play", event_id=event_id,
            signature_verified=True, environment="sandbox",
            sanitized_payload={"kind": "test", "package_name_valid": True},
        )
        if inserted:
            finish_provider_event(
                source="google_play", event_id=event_id, outcome="test_verified",
            )
        return {"outcome": "test_verified" if inserted else "duplicate"}

    if kind == "voided":
        purchase_token, order_id, product_type, refund_type = (
            _parse_voided_subscription(detail)
        )
        inserted = claim_provider_event(
            source="google_play", event_id=event_id,
            signature_verified=True, environment="production",
            sanitized_payload={
                "kind": "voided_subscription",
                "product_type": product_type,
                "refund_type": refund_type,
                "package_name_valid": True,
                "purchase_token_sha256": hashlib.sha256(
                    purchase_token.encode("utf-8")
                ).hexdigest(),
                "order_id_sha256": hashlib.sha256(
                    order_id.encode("utf-8")
                ).hexdigest(),
            },
        )
        if not inserted:
            return {"outcome": "duplicate"}
        account_id = find_account_for_purchase("google_play", purchase_token)
        if not account_id:
            finish_provider_event(
                source="google_play", event_id=event_id,
                outcome="ignored_unbound",
            )
            return {"outcome": "ignored_unbound"}
        publisher_lookup = "verified"
        try:
            try:
                verify_google_subscription_identity(
                    account_id=account_id,
                    purchase_token=purchase_token,
                )
            except GooglePlayPurchaseNotFoundError:
                # A voided purchase may already have disappeared from the
                # Publisher API. The existing server-verified binding plus the
                # authenticated Google event remains sufficient to revoke it.
                publisher_lookup = "not_found_after_void"
            _entitlement_id, transition = revoke_verified_purchase_entitlement(
                provider="google_play",
                account_id=account_id,
                external_purchase_id=purchase_token,
                provider_status="VOIDED_PURCHASE_FULL_REFUND",
                provider_event_at=event_time,
                provider_event_id=event_id,
                expected_product_id=GOOGLE_PLAY_PRODUCT_50GB,
                expected_plan_id=GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
                metadata={
                    "voided_purchase": True,
                    "refund_type": "FULL_REFUND",
                    "publisher_lookup": publisher_lookup,
                    "order_id_sha256": hashlib.sha256(
                        order_id.encode("utf-8")
                    ).hexdigest(),
                },
            )
            finish_provider_event(
                source="google_play", event_id=event_id, outcome="applied",
            )
            return {
                "outcome": "applied",
                "status": "revoked",
                "transition": transition,
            }
        except StaleProviderEventError:
            finish_provider_event(
                source="google_play", event_id=event_id,
                outcome="ignored_stale",
            )
            return {"outcome": "ignored_stale"}
        except GooglePlayVerificationError as exc:
            finish_provider_event(
                source="google_play", event_id=event_id, outcome="rejected",
                error_text=type(exc).__name__,
            )
            raise HTTPException(
                status_code=400, detail="voided purchase verification failed",
            ) from exc
        except (GooglePlayConfigurationError, GooglePlayTransientError) as exc:
            finish_provider_event(
                source="google_play", event_id=event_id, outcome="error",
                error_text=type(exc).__name__,
            )
            raise HTTPException(
                status_code=503, detail="RTDN processing retry required",
            ) from exc
        except Exception as exc:
            finish_provider_event(
                source="google_play", event_id=event_id, outcome="error",
                error_text=type(exc).__name__,
            )
            raise HTTPException(
                status_code=503, detail="RTDN processing retry required",
            ) from exc

    sub = detail
    purchase_token = str(sub.get("purchaseToken") or "")
    if not purchase_token or len(purchase_token) > 4096:
        raise HTTPException(status_code=400, detail="RTDN purchase token missing")
    inserted = claim_provider_event(
        source="google_play", event_id=event_id, signature_verified=True,
        environment="production",
        sanitized_payload={
            "kind": "subscription",
            "notification_type": sub.get("notificationType"),
            "package_name_valid": True,
            "purchase_token_sha256": hashlib.sha256(
                purchase_token.encode("utf-8")
            ).hexdigest(),
        },
    )
    if not inserted:
        return {"outcome": "duplicate"}
    account_id = find_account_for_purchase("google_play", purchase_token)
    if not account_id:
        finish_provider_event(
            source="google_play", event_id=event_id, outcome="ignored_unbound",
        )
        return {"outcome": "ignored_unbound"}
    try:
        result = verify_and_apply_google_subscription(
            account_id=account_id,
            purchase_token=purchase_token,
            event_id=event_id,
            event_time=event_time,
        )
        finish_provider_event(
            source="google_play", event_id=event_id, outcome="applied",
        )
    except StaleProviderEventError:
        finish_provider_event(
            source="google_play", event_id=event_id, outcome="ignored_stale",
        )
        return {"outcome": "ignored_stale"}
    except Exception as exc:
        finish_provider_event(
            source="google_play", event_id=event_id, outcome="error",
            error_text=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="RTDN processing retry required") from exc
    return {"outcome": "applied", "status": result.normalized_status}


@router.post("/billing/apple/verify-transaction")
async def verify_apple_transaction(
    payload: AppleTransactionRequest,
    principal=Depends(verify_trusted_device),
):
    from apple_billing import (
        AppleBillingConfigurationError,
        AppleTransactionVerificationError,
        verify_and_apply_apple_transaction,
    )
    if payload.environment == "sandbox" and os.getenv(
        "VAULTAI_APPLE_ACCEPT_SANDBOX", "false",
    ).strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=403, detail="Apple sandbox is disabled")
    try:
        return verify_and_apply_apple_transaction(
            account_id=_account_id(principal),
            signed_transaction=payload.signed_transaction,
            environment=payload.environment,
        )
    except AppleBillingConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "apple_billing_not_configured", "message": "Apple billing is not configured."},
        ) from exc
    except AppleTransactionVerificationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "apple_transaction_invalid", "message": "Apple could not verify this transaction."},
        ) from exc


@router.post("/billing/apple/notifications-v2")
async def apple_notifications_v2(request: Request):
    from apple_billing import (
        AppleBillingConfigurationError,
        AppleTransactionVerificationError,
        _attr,
        _transaction_update,
        decode_verified_apple_notification,
        enum_text,
    )
    from billing_entitlements import (
        StaleProviderEventError,
        claim_provider_event,
        find_account_for_original_transaction,
        find_account_for_purchase,
        finish_provider_event,
        upsert_verified_entitlement,
    )
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning(
            "[APPLE-BILLING] notification_rejected reason=invalid_json"
        )
        raise HTTPException(
            status_code=400, detail="Apple signed payload missing"
        ) from exc
    signed_payload = str(body.get("signedPayload") or "") if isinstance(body, dict) else ""
    if not signed_payload or len(signed_payload) > 200_000:
        logger.warning(
            "[APPLE-BILLING] notification_rejected "
            "reason=missing_or_oversize_payload"
        )
        raise HTTPException(status_code=400, detail="Apple signed payload missing")
    try:
        environment, verifier, notification = decode_verified_apple_notification(
            signed_payload,
        )
    except AppleBillingConfigurationError as exc:
        logger.error(
            "[APPLE-BILLING] notification_rejected "
            "reason=verification_not_configured"
        )
        raise HTTPException(
            status_code=503, detail="Apple notification verification unavailable"
        ) from exc
    except AppleTransactionVerificationError as exc:
        logger.warning(
            "[APPLE-BILLING] notification_rejected "
            "reason=signature_or_identity_invalid"
        )
        raise HTTPException(status_code=400, detail="Apple notification invalid") from exc
    event_id = str(_attr(notification, "notificationUUID") or "")
    event_type = enum_text(_attr(notification, "notificationType"))
    subtype = enum_text(_attr(notification, "subtype"))
    if not event_id:
        logger.warning(
            "[APPLE-BILLING] notification_rejected reason=missing_event_id"
        )
        raise HTTPException(status_code=400, detail="Apple notification identity missing")
    inserted = claim_provider_event(
        source="apple", event_id=event_id, signature_verified=True,
        environment=environment,
        sanitized_payload={"notification_type": event_type, "subtype": subtype or None},
    )
    if not inserted:
        logger.info(
            "[APPLE-BILLING] notification_processed "
            "environment=%s outcome=duplicate event_hash=%s",
            environment,
            hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:12],
        )
        return {"outcome": "duplicate"}
    data = _attr(notification, "data")
    signed_transaction = str(_attr(data, "signedTransactionInfo") or "")
    if not signed_transaction:
        finish_provider_event(source="apple", event_id=event_id, outcome="verified_no_transaction")
        logger.info(
            "[APPLE-BILLING] notification_processed "
            "environment=%s outcome=verified_no_transaction event_hash=%s",
            environment,
            hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:12],
        )
        return {"outcome": "verified_no_transaction"}
    try:
        transaction = verifier.verify_transaction(signed_transaction)
        transaction_id = str(_attr(transaction, "transactionId") or "")
        original_id = str(_attr(transaction, "originalTransactionId") or "")
        account_id = (
            find_account_for_original_transaction("apple", original_id)
            or find_account_for_purchase("apple", transaction_id)
        )
        if not account_id:
            finish_provider_event(source="apple", event_id=event_id, outcome="ignored_unbound")
            return {"outcome": "ignored_unbound"}
        update = _transaction_update(
            transaction,
            environment=environment,
            notification_type=event_type,
            subtype=subtype,
            event_id=event_id,
        )
        _entitlement_id, transition = upsert_verified_entitlement(account_id, update)
        finish_provider_event(source="apple", event_id=event_id, outcome="applied")
        return {"outcome": "applied", "status": update.status, "transition": transition}
    except StaleProviderEventError:
        finish_provider_event(
            source="apple", event_id=event_id, outcome="ignored_stale",
        )
        return {"outcome": "ignored_stale"}
    except Exception as exc:
        finish_provider_event(
            source="apple", event_id=event_id, outcome="error",
            error_text=type(exc).__name__,
        )
        raise HTTPException(status_code=503, detail="Apple notification retry required") from exc
