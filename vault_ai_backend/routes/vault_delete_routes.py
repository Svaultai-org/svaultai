"""Vault delete/profile-delete endpoints.

Three endpoints, all session-authed AND behind the trusted-device
gate (via verify_trusted_device dependency in main.py's include).

  GET  /vault/delete/status   — metadata the client needs to render
                                the destructive-confirmation UI.
  POST /vault/delete/request  — records the intent to delete and
                                returns a short-lived HMAC-signed
                                challenge token (~10 min).
  POST /vault/delete/confirm  — final gate. Requires:
                                  * the challenge token from /request
                                  * the exact confirmation phrase
                                    "DELETE MY VAULT"
                                  * the correct PIN (verified via
                                    PBKDF2 → AES-GCM decrypt of the
                                    vault's pin_verifier, same path
                                    as /auth/login)
                                Then invokes vault_deletion_service.

Rules:
  * User-requested deletion requires auth (verify_session_token).
  * User-requested deletion requires trusted device (device gate is
    NOT in ROUTES_EXEMPT_FROM_DEVICE_GATE for these paths).
  * User-requested deletion requires unlock/PIN confirmation.
  * User-requested deletion requires the exact phrase.
  * Never reveals secrets. PIN is never logged; only its length.
  * Never broadcasts crypto transactions. Only the deletion
    cascade runs.
  * On success, revokes all sessions for the vault.
"""

from __future__ import annotations

import base64
import hmac
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from auth_local import (
    SessionPrincipal,
    revoke_all_sessions_for_vault,
    verify_session_token,
)
from device_gate import verify_trusted_device
from rate_limit_sensitive import enforce_delete_vault_rate_limit
import security_event_log as sec_log
from vault_core import (
    KDF_LEGACY_ITERATIONS,
    PIN_VERIFIER_PLAINTEXT,
    decrypt_message,
    derive_key,
    get_db,
)
from vault_deletion_service import (
    CONFIRMATION_PHRASE,
    REASON_USER_REQUESTED,
    VaultDeletionBlockedByStripeError,
    delete_vault_and_all_data,
)


logger = logging.getLogger(__name__)
router = APIRouter()


_CHALLENGE_TTL_SECONDS: int = 10 * 60


class DeleteStatusResponse(BaseModel):
    confirmation_phrase:      str
    requires_pin:             bool
    requires_trusted_device:  bool
    has_active_subscription:  bool
    subscription_status:      str
    is_final_vault:           bool
    deletion_allowed:         bool
    apple_subscription_state: str
    retryable:                bool = False


class DeleteRequestResponse(BaseModel):
    request_token:  str
    expires_in:     int


class DeleteConfirmRequest(BaseModel):
    request_token:        str = Field(..., min_length=1)
    pin:                  str = Field(..., min_length=1, max_length=64)
    confirmation_phrase:  str = Field(..., min_length=1, max_length=64)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def _hmac_secret() -> bytes:

    import os as _os
    raw = _os.getenv("VAULT_SESSION_SECRET", "").strip()
    if raw:
        return raw.encode("utf-8")

    from auth_local import _get_secret
    return _get_secret()


# HMAC-SHA256 produces a fixed 32-byte digest; this constant is the
# authoritative sig length used by both sign and verify.
_CHALLENGE_SIG_BYTES = 32


def _sign_challenge(vault_id: str, expires_at_ts: int) -> str:

    payload = f"{vault_id}|{expires_at_ts}".encode("utf-8")
    sig = hmac.new(_hmac_secret(), payload, "sha256").digest()
    return _b64url_encode(payload + b"." + sig)


def _verify_challenge(
    request_token: str,
    expected_vault_id: str,
    *,
    now_ts: Optional[int] = None,
) -> bool:

    if not isinstance(request_token, str) or not request_token:
        return False
    try:
        raw = _b64url_decode(request_token.strip())
    except Exception:
        return False
    # The sign layout is: payload_bytes + b"." + sig(32 bytes).
    # sig is raw HMAC-SHA256 output (arbitrary bytes) and contains
    # a b"." byte with ~12% probability; earlier versions of this
    # parser used raw.rsplit(b".", 1) and silently mis-split those
    # tokens, rejecting ~1-in-8 legitimate in-window challenges.
    # Split from the end by the known sig length instead — payload
    # and sig are unambiguously separated regardless of which bytes
    # HMAC happens to emit. The b"." byte in position -33 is still
    # asserted as a format sanity check.
    if len(raw) < _CHALLENGE_SIG_BYTES + 2:
        return False
    provided_sig = raw[-_CHALLENGE_SIG_BYTES:]
    if raw[-(_CHALLENGE_SIG_BYTES + 1):-_CHALLENGE_SIG_BYTES] != b".":
        return False
    payload = raw[:-(_CHALLENGE_SIG_BYTES + 1)]
    expected_sig = hmac.new(
        _hmac_secret(), payload, "sha256",
    ).digest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        return False
    try:
        payload_str = payload.decode("utf-8")
    except UnicodeDecodeError:
        return False
    parts = payload_str.split("|", 1)
    if len(parts) != 2:
        return False
    tok_vault_id, tok_expires_str = parts
    if tok_vault_id != expected_vault_id:
        return False
    try:
        tok_expires_ts = int(tok_expires_str)
    except ValueError:
        return False
    now = int(time.time()) if now_ts is None else int(now_ts)
    return tok_expires_ts > now


def _get_deletion_billing_state(vault_id: str) -> dict[str, object]:
    """Return the authoritative final-vault Apple deletion decision.

    No local StoreKit state and no legacy account_subscriptions row participates
    in this decision. An indeterminate authoritative state fails closed.
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT account_id FROM vaults WHERE vault_id = %s LIMIT 1
            """,
            (vault_id,),
        )
        vault = cur.fetchone()
        if not vault or not vault.get("account_id"):
            return {
                "is_final_vault": True, "deletion_allowed": False,
                "has_active_subscription": False,
                "subscription_status": "unknown",
                "apple_subscription_state": "temporarily_unavailable",
                "retryable": True,
            }
        account_id = str(vault["account_id"])
        cur.execute(
            "SELECT COUNT(*) AS count FROM vaults WHERE account_id = %s",
            (account_id,),
        )
        count_row = cur.fetchone() or {}
        is_final = int(count_row.get("count") or 0) <= 1
        if not is_final:
            return {
                "is_final_vault": False, "deletion_allowed": True,
                "has_active_subscription": False,
                "subscription_status": "not_applicable",
                "apple_subscription_state": "not_final_vault",
                "retryable": False,
            }
        cur.execute(
            """
            SELECT status, current_period_end, auto_renewing,
                   cancel_at_period_end, metadata_jsonb
              FROM billing_entitlements
             WHERE account_id = %s AND provider = 'apple'
               AND verification_state = 'verified'
             ORDER BY last_verified_at DESC NULLS LAST, updated_at DESC
            """,
            (account_id,),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    if not rows:
        return {
            "is_final_vault": True, "deletion_allowed": True,
            "has_active_subscription": False, "subscription_status": "none",
            "apple_subscription_state": "none", "retryable": False,
        }
    now = datetime.now(timezone.utc)
    granting = []
    for row in rows:
        period_end = row.get("current_period_end")
        if period_end and period_end.tzinfo is None:
            period_end = period_end.replace(tzinfo=timezone.utc)
        if str(row.get("status") or "") in {
            "active", "reactivated", "grace_period",
        } and (period_end is None or period_end > now):
            granting.append(row)
    if not granting:
        return {
            "is_final_vault": True, "deletion_allowed": True,
            "has_active_subscription": False,
            "subscription_status": str(rows[0].get("status") or "expired"),
            "apple_subscription_state": "resolved", "retryable": False,
        }
    if len(granting) != 1:
        return {
            "is_final_vault": True, "deletion_allowed": False,
            "has_active_subscription": True, "subscription_status": "conflict",
            "apple_subscription_state": "temporarily_unavailable",
            "retryable": True,
        }
    row = granting[0]
    metadata = row.get("metadata_jsonb") or {}
    renewal_state = (
        str(metadata.get("apple_auto_renew_state") or "unknown").lower()
        if isinstance(metadata, dict) else "unknown"
    )
    if renewal_state == "disabled" and bool(row.get("cancel_at_period_end")):
        return {
            "is_final_vault": True, "deletion_allowed": True,
            "has_active_subscription": True,
            "subscription_status": str(row.get("status") or "active"),
            "apple_subscription_state": "canceled_pending_expiration",
            "retryable": False,
        }
    if renewal_state == "enabled" and bool(row.get("auto_renewing")):
        return {
            "is_final_vault": True, "deletion_allowed": False,
            "has_active_subscription": True,
            "subscription_status": str(row.get("status") or "active"),
            "apple_subscription_state": "active_auto_renewing",
            "retryable": False,
        }
    return {
        "is_final_vault": True, "deletion_allowed": False,
        "has_active_subscription": True, "subscription_status": "unknown",
        "apple_subscription_state": "temporarily_unavailable",
        "retryable": True,
    }


def _require_authoritative_final_vault_deletion_allowed(vault_id: str) -> None:
    try:
        decision = _get_deletion_billing_state(vault_id)
    except Exception as exc:
        logger.warning("[VAULT-DELETE] Apple entitlement check unavailable")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "apple_subscription_status_temporarily_unavailable",
                "message": "Apple subscription status is temporarily unavailable. Please try again.",
                "retryable": True,
            },
        ) from exc
    if bool(decision["deletion_allowed"]):
        return
    if decision["apple_subscription_state"] == "active_auto_renewing":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_apple_subscription_must_be_canceled_before_final_deletion",
                "message": (
                    "Cancel the active App Store subscription before deleting "
                    "your final SVaultAI vault."
                ),
                "retryable": False,
            },
        )
    raise HTTPException(
        status_code=503,
        detail={
            "code": "apple_subscription_status_temporarily_unavailable",
            "message": "Apple subscription status is temporarily unavailable. Please try again.",
            "retryable": True,
        },
    )


def _load_pin_material(vault_id: str) -> tuple[str, str, int]:

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT pin_salt, pin_verifier, kdf_iterations
            FROM vaults
            WHERE vault_id = %s
            LIMIT 1
            """,
            (vault_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid session")
    iters = int(row.get("kdf_iterations") or KDF_LEGACY_ITERATIONS)
    return (row["pin_salt"], row["pin_verifier"], iters)


def _verify_pin(vault_id: str, pin: str) -> bool:

    if not isinstance(pin, str) or not pin:
        return False
    try:
        pin_salt, pin_verifier, iterations = _load_pin_material(vault_id)
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "[VAULT-DELETE] pin material load failed",
        )
        return False
    try:
        key = derive_key(pin, pin_salt, iterations=iterations)
        return decrypt_message(pin_verifier, key) == PIN_VERIFIER_PLAINTEXT
    except Exception:
        return False


@router.get(
    "/vault/delete/status",
    response_model=DeleteStatusResponse,
)
def get_delete_status(
    request: Request,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> DeleteStatusResponse:
    try:
        enforce_delete_vault_rate_limit(
            request, vault_id=principal["vault_id"],
        )
    except HTTPException:
        sec_log.emit(
            reason=sec_log.REASON_RATE_LIMITED_DELETE_VAULT,
            route=sec_log.ROUTE_GROUP_DELETE_VAULT,
            subject=sec_log.short_hash(principal["vault_id"]),
        )
        raise
    try:
        decision = _get_deletion_billing_state(principal["vault_id"])
    except Exception:
        decision = {
            "is_final_vault": True, "deletion_allowed": False,
            "has_active_subscription": False, "subscription_status": "unknown",
            "apple_subscription_state": "temporarily_unavailable",
            "retryable": True,
        }
    return DeleteStatusResponse(
        confirmation_phrase=CONFIRMATION_PHRASE,
        requires_pin=True,
        requires_trusted_device=True,
        has_active_subscription=bool(decision["has_active_subscription"]),
        subscription_status=str(decision["subscription_status"]),
        is_final_vault=bool(decision["is_final_vault"]),
        deletion_allowed=bool(decision["deletion_allowed"]),
        apple_subscription_state=str(decision["apple_subscription_state"]),
        retryable=bool(decision["retryable"]),
    )


@router.post(
    "/vault/delete/request",
    response_model=DeleteRequestResponse,
)
def request_delete(
    request: Request,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> DeleteRequestResponse:
    try:
        enforce_delete_vault_rate_limit(
            request, vault_id=principal["vault_id"],
        )
    except HTTPException:
        sec_log.emit(
            reason=sec_log.REASON_RATE_LIMITED_DELETE_VAULT,
            route=sec_log.ROUTE_GROUP_DELETE_VAULT,
            subject=sec_log.short_hash(principal["vault_id"]),
        )
        raise
    sec_log.emit(
        reason=sec_log.REASON_DELETE_VAULT_REQUESTED,
        route=sec_log.ROUTE_GROUP_DELETE_VAULT,
        subject=sec_log.short_hash(principal["vault_id"]),
    )
    expires_at_ts = int(time.time()) + _CHALLENGE_TTL_SECONDS
    token = _sign_challenge(principal["vault_id"], expires_at_ts)
    return DeleteRequestResponse(
        request_token=token,
        expires_in=_CHALLENGE_TTL_SECONDS,
    )


@router.post(
    "/vault/delete/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def confirm_delete(
    payload: DeleteConfirmRequest,
    request: Request,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> Response:

    vault_id = principal["vault_id"]

    try:
        enforce_delete_vault_rate_limit(request, vault_id=vault_id)
    except HTTPException:
        sec_log.emit(
            reason=sec_log.REASON_RATE_LIMITED_DELETE_VAULT,
            route=sec_log.ROUTE_GROUP_DELETE_VAULT,
            subject=sec_log.short_hash(vault_id),
        )
        raise

    if payload.confirmation_phrase != CONFIRMATION_PHRASE:
        raise HTTPException(
            status_code=400,
            detail={
                "code":    "invalid_confirmation_phrase",
                "message": (
                    f"Type the exact phrase {CONFIRMATION_PHRASE} "
                    "to confirm deletion."
                ),
            },
        )

    if not _verify_challenge(payload.request_token, vault_id):
        raise HTTPException(
            status_code=400,
            detail={
                "code":    "invalid_or_expired_request_token",
                "message": (
                    "Deletion request expired. Start the delete "
                    "flow again."
                ),
            },
        )

    if not _verify_pin(vault_id, payload.pin):
        raise HTTPException(
            status_code=401,
            detail={
                "code":    "invalid_pin",
                "message": "PIN is incorrect.",
            },
        )

    # Deliberately re-read authoritative billing state after every user gate
    # and immediately before the destructive operation. This closes the
    # request/confirmation time-of-check gap without trusting client state.
    _require_authoritative_final_vault_deletion_allowed(vault_id)

    try:
        delete_vault_and_all_data(
            vault_id, reason=REASON_USER_REQUESTED,
        )
    except VaultDeletionBlockedByStripeError as _blocked:
        # 2026-07-30 audit-review safety: the Stripe cancellation
        # attempt returned an error outcome (transient API failure).
        # The vault row is UNTOUCHED. Return 503 so the client can
        # ask the user to try again in a moment — retrying is safe
        # because both the Stripe cancel and the vault delete are
        # idempotent.
        logger.warning(
            "[VAULT-DELETE] user-requested deletion blocked: stripe "
            "cancel unavailable hashed=%s detail=%s",
            _blocked.vault_id_hashed_prefix, _blocked.detail,
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code":    "delete_deferred_stripe_unavailable",
                "message": (
                    "We couldn't confirm the payment provider "
                    "cancellation right now. Your vault has NOT "
                    "been deleted. Please try again in a few "
                    "minutes."
                ),
                "retry_after_seconds": 300,
            },
        )
    except Exception:
        logger.exception(
            "[VAULT-DELETE] user-requested deletion failed",
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code":    "delete_failed",
                "message": "Deletion could not be completed.",
            },
        )

    sec_log.emit(
        reason=sec_log.REASON_DELETE_VAULT_CONFIRMED,
        route=sec_log.ROUTE_GROUP_DELETE_VAULT,
        subject=sec_log.short_hash(vault_id),
    )

    try:
        revoke_all_sessions_for_vault(vault_id)
    except Exception:
        pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
