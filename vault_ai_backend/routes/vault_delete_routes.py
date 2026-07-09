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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
    if b"." not in raw:
        return False
    payload, provided_sig = raw.rsplit(b".", 1)
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


def _get_subscription_state(vault_id: str) -> tuple[bool, str]:

    try:
        from billing import (
            _STATUSES_THAT_GRANT_STORAGE,
            get_account_id_for_vault,
        )
        account_id = get_account_id_for_vault(vault_id)
    except Exception:
        return (False, "unknown")
    if not account_id:
        return (False, "none")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT COALESCE(status, 'none') AS status
            FROM account_subscriptions
            WHERE account_id = %s
            """,
            (account_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    subscription_status = str(row["status"]) if row else "none"
    has_active = subscription_status in _STATUSES_THAT_GRANT_STORAGE
    return (has_active, subscription_status)


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
    has_active, sub_status = _get_subscription_state(
        principal["vault_id"],
    )
    return DeleteStatusResponse(
        confirmation_phrase=CONFIRMATION_PHRASE,
        requires_pin=True,
        requires_trusted_device=True,
        has_active_subscription=bool(has_active),
        subscription_status=sub_status,
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
)
def confirm_delete(
    payload: DeleteConfirmRequest,
    request: Request,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> None:

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

    try:
        delete_vault_and_all_data(
            vault_id, reason=REASON_USER_REQUESTED,
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

    return None


__all__ = ["router"]
