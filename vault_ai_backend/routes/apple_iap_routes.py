from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device

router = APIRouter()


class AppleTransactionRequest(BaseModel):
    signed_transaction: str = Field(..., min_length=32, max_length=100_000)


class AppleNotificationRequest(BaseModel):
    signedPayload: str = Field(..., min_length=32, max_length=200_000)


@router.post("/billing/apple/transactions")
async def verify_apple_transaction(
    payload: AppleTransactionRequest,
    principal=Depends(verify_trusted_device),
):
    from apple_iap_service import (
        AppleIAPAccountConflictError,
        AppleIAPConfigurationError,
        AppleIAPVerificationError,
        apply_verified_transaction,
        verify_transaction,
    )
    from billing import ensure_account_for_vault

    account_id = ensure_account_for_vault(principal["vault_id"])
    try:
        transaction, environment = verify_transaction(payload.signed_transaction)
        return apply_verified_transaction(
            account_id=account_id,
            transaction=transaction,
            environment=environment,
        )
    except AppleIAPConfigurationError:
        raise HTTPException(
            status_code=503,
            detail={"code": "apple_iap_unconfigured", "message": "App Store purchases are temporarily unavailable."},
        )
    except AppleIAPAccountConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "billing_source_conflict", "message": str(exc)},
        )
    except AppleIAPVerificationError:
        raise HTTPException(
            status_code=400,
            detail={"code": "apple_transaction_invalid", "message": "The App Store purchase could not be verified."},
        )


@router.post("/billing/apple/notifications")
async def apple_server_notification(payload: AppleNotificationRequest):
    from apple_iap_service import (
        AppleIAPConfigurationError,
        AppleIAPVerificationError,
        apply_verified_notification,
        verify_notification,
    )

    try:
        notification, transaction, environment = verify_notification(
            payload.signedPayload
        )
        return apply_verified_notification(
            notification=notification,
            transaction=transaction,
            environment=environment,
        )
    except AppleIAPConfigurationError:
        raise HTTPException(status_code=503, detail="Apple IAP is not configured")
    except AppleIAPVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Apple notification")
