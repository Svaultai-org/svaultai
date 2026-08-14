"""Provider-neutral billing HTTP boundaries.

Authenticated client routes bind verified store purchases to the current
SVaultAI account. Provider notification routes authenticate and re-fetch
authoritative state before changing entitlements.
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device


router = APIRouter()


class GooglePlayVerifyRequest(BaseModel):
    purchase_token: str = Field(..., min_length=1, max_length=4096)
    product_id: str = Field(..., min_length=1, max_length=200)


class AppleTransactionRequest(BaseModel):
    signed_transaction: str = Field(..., min_length=1, max_length=100_000)
    environment: Literal["production", "sandbox"] = "production"


def _account_id(principal: dict) -> str:
    from billing import ensure_account_for_vault
    return ensure_account_for_vault(str(principal["vault_id"]))


@router.get("/billing/providers")
async def billing_providers(principal=Depends(verify_trusted_device)):
    account_id = _account_id(principal)
    from apple_billing import apple_app_account_token, configured_apple_catalog
    from google_play_billing import (
        GOOGLE_PLAY_BASE_PLAN_MONTHLY,
        GOOGLE_PLAY_PRODUCT_50GB,
        purchase_account_token,
    )
    apple_configured = False
    try:
        apple_configured = bool(configured_apple_catalog())
    except Exception:
        apple_configured = False
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
            "base_plan_id": GOOGLE_PLAY_BASE_PLAN_MONTHLY,
            "account_token": purchase_account_token(account_id),
        },
        "apple": {
            "configured": apple_configured,
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


@router.post("/billing/google-play/rtdn")
async def google_play_rtdn(request: Request):
    _verify_google_pubsub_request(request)
    event_id, notification = _decode_pubsub_message(await request.json())
    from billing_entitlements import (
        StaleProviderEventError,
        claim_provider_event,
        find_account_for_purchase,
        finish_provider_event,
    )
    from google_play_billing import (
        GOOGLE_PLAY_PACKAGE_NAME,
        verify_and_apply_google_subscription,
    )
    if str(notification.get("packageName") or "") != GOOGLE_PLAY_PACKAGE_NAME:
        raise HTTPException(status_code=400, detail="RTDN package mismatch")
    sub = notification.get("subscriptionNotification")
    if not isinstance(sub, dict):
        # Test notifications prove transport/auth without changing entitlement.
        if isinstance(notification.get("testNotification"), dict):
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
        raise HTTPException(status_code=400, detail="unsupported RTDN notification")
    purchase_token = str(sub.get("purchaseToken") or "")
    if not purchase_token:
        raise HTTPException(status_code=400, detail="RTDN purchase token missing")
    inserted = claim_provider_event(
        source="google_play", event_id=event_id, signature_verified=True,
        environment="production",
        sanitized_payload={
            "kind": "subscription",
            "notification_type": sub.get("notificationType"),
            "package_name_valid": True,
            "purchase_token_sha256": __import__("hashlib").sha256(
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
    millis = notification.get("eventTimeMillis")
    try:
        event_time = datetime.fromtimestamp(float(millis) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        event_time = datetime.now(timezone.utc)
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
    body = await request.json()
    signed_payload = str(body.get("signedPayload") or "") if isinstance(body, dict) else ""
    if not signed_payload or len(signed_payload) > 200_000:
        raise HTTPException(status_code=400, detail="Apple signed payload missing")
    try:
        environment, verifier, notification = decode_verified_apple_notification(
            signed_payload,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Apple notification invalid") from exc
    event_id = str(_attr(notification, "notificationUUID") or "")
    event_type = enum_text(_attr(notification, "notificationType"))
    subtype = enum_text(_attr(notification, "subtype"))
    if not event_id:
        raise HTTPException(status_code=400, detail="Apple notification identity missing")
    inserted = claim_provider_event(
        source="apple", event_id=event_id, signature_verified=True,
        environment=environment,
        sanitized_payload={"notification_type": event_type, "subtype": subtype or None},
    )
    if not inserted:
        return {"outcome": "duplicate"}
    data = _attr(notification, "data")
    signed_transaction = str(_attr(data, "signedTransactionInfo") or "")
    if not signed_transaction:
        finish_provider_event(source="apple", event_id=event_id, outcome="verified_no_transaction")
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
