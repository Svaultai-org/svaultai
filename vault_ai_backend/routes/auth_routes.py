

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth_local import (
    SessionPrincipal,
    issue_session_token,
    normalize_client_label,
    revoke_session_token,
    verify_session_token,
)
from rate_limit_auth import (
    enforce_login_rate_limit,
    enforce_signup_rate_limit,
)
from vault_core import (
    KDF_LEGACY_ITERATIONS,
    KDF_TARGET_ITERATIONS,
    MAX_PIN_ATTEMPTS,
    MIN_PIN_LENGTH_NEW_VAULT,
    PIN_LOCKOUT_HOURS,
    PIN_VERIFIER_PLAINTEXT,
    decrypt_message,
    derive_key,
    encrypt_message,
    get_db,
)
from vault_handle import to_display as vault_handle_to_display


logger = logging.getLogger(__name__)
router = APIRouter()


PIN_MAX_LENGTH = 64

GENERIC_LOGIN_ERROR = "Vault name or PIN is incorrect"
USERNAME_LOOKUP_BYTES = 32


def _decode_username_lookup(value: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid username lookup") from exc
    if len(raw) != USERNAME_LOOKUP_BYTES:
        raise HTTPException(status_code=400, detail="Invalid username lookup")
    return raw


def _validate_pin_shape(pin: str, *, is_signup: bool) -> None:
                                                                     
                                                                       
    if not isinstance(pin, str) or not pin:
        raise HTTPException(status_code=400, detail="PIN is required")
    if not pin.isdigit():
        raise HTTPException(
            status_code=400, detail="PIN can only contain digits.",
        )
    if len(pin) > PIN_MAX_LENGTH:
        raise HTTPException(
            status_code=400, detail="PIN must be 64 digits or fewer.",
        )
    if len(pin) < MIN_PIN_LENGTH_NEW_VAULT:
        raise HTTPException(
            status_code=400, detail="PIN must be at least 6 digits.",
        )


def _validate_display_username(username: Optional[str]) -> Optional[str]:
    if username is None:
        return None
    stripped = username.strip()
    if not stripped:
        return None
    if len(stripped) > 200:
        raise HTTPException(status_code=400, detail="display_username is too long")
    return stripped


_DISPLAY_USERNAME_FALLBACK_PREFIX_LEN = 8


def _default_display_username(vault_id: str) -> str:


    short = vault_id.replace("-", "")[:_DISPLAY_USERNAME_FALLBACK_PREFIX_LEN]
    return f"User {short}"


class LoginRequest(BaseModel):
    username_lookup: str = Field(..., min_length=1, max_length=200)
    pin: str = Field(..., min_length=1, max_length=PIN_MAX_LENGTH)


class AuthResponse(BaseModel):
    session_token:      str
    vault_id:           str
    # Human-readable login names never come from the service.  The field is
    # retained as nullable for one release so older clients can decode the
    # response without learning an internal database label.
    vault_name:         Optional[str] = None
    display_username:   Optional[str] = None
    vault_handle:       Optional[str] = None
    zk:                 bool = False
                                                                     
                                                                    
    new_device_trusted: bool = False
    expires_at:         datetime


class MeResponse(BaseModel):
    vault_id:         str
    vault_name:       Optional[str] = None
    display_username: Optional[str]
    vault_handle:     Optional[str] = None
    zk:               bool = False
    created_at:       datetime


def _display_vault_handle(raw: object) -> Optional[str]:
    if raw is None:
        return None
    try:
        return vault_handle_to_display(bytes(raw))
    except Exception:
        logger.warning("[AUTH] invalid vault_handle bytes on auth response")
        return None


_DUMMY_PIN_SALT = "AAAAAAAAAAAAAAAAAAAAAAAA"                           


def _device_id_from_request(request: Request) -> Optional[str]:

    raw = request.headers.get("x-device-id") or ""
    raw = raw.strip()
    return raw or None


def _upsert_trusted_device(
    *, vault_id: str, device_id: Optional[str], request: Request,
) -> bool:


    if not device_id:
        return False
    user_agent = (request.headers.get("user-agent") or "")[:200]
    last_ip = (request.client.host if request.client else "") or ""
    last_ip_prefix = last_ip.split(".")[0] if "." in last_ip else last_ip[:8]
    conn = get_db()
    try:
        cur = conn.cursor()
                                                                     
                                                                   
        cur.execute(
            "SELECT status FROM trusted_devices "
            "WHERE vault_id = %s AND device_id = %s",
            (vault_id, device_id),
        )
        prior = cur.fetchone()
        was_trusted = bool(prior) and (prior[0] == "trusted")

        cur.execute(
            """
            INSERT INTO trusted_devices
              (vault_id, device_id, user_agent_brand, last_ip_prefix,
               status, approved_at, last_seen_at)
            VALUES (%s, %s, %s, %s, 'trusted', NOW(), NOW())
            ON CONFLICT (vault_id, device_id) DO UPDATE
            SET status         = 'trusted',
                approved_at    = COALESCE(trusted_devices.approved_at, NOW()),
                last_seen_at   = NOW(),
                last_ip_prefix = EXCLUDED.last_ip_prefix,
                user_agent_brand = EXCLUDED.user_agent_brand
            """,
            (vault_id, device_id, user_agent, last_ip_prefix),
        )
        conn.commit()
        return not was_trusted
    except Exception:
        conn.rollback()
        logger.exception(
            "[AUTH] trusted-device upsert failed vault_id=%s device_id_prefix=%s",
            vault_id, (device_id or "")[:8],
        )
        return False
    finally:
        conn.close()


def _build_response(
    token_bundle: dict,
    *,
    display_username: Optional[str] = None,
    vault_handle: object = None,
    new_device_trusted: bool = False,
) -> AuthResponse:
    handle_display = _display_vault_handle(vault_handle)
    return AuthResponse(
        session_token=token_bundle["token"],
        vault_id=str(token_bundle["vault_id"]),
        vault_name=None,
        display_username=None,
        vault_handle=handle_display,
        zk=handle_display is not None,
        new_device_trusted=new_device_trusted,
        expires_at=token_bundle["expires_at"],
    )


@router.post("/auth/signup", status_code=status.HTTP_410_GONE)
def signup_disabled(request: Request) -> None:
    """Reject the retired plaintext-username signup protocol.

    Current clients use the OPAQUE/ZK registration endpoints, which receive
    only client-derived opaque identifiers.
    """
    enforce_signup_rate_limit(request)
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "private_signup_required",
            "message": "Please update SVaultAI and create the vault again.",
        },
    )


def _do_dummy_derive(pin: str) -> None:


    try:
        derive_key(pin, _DUMMY_PIN_SALT, iterations=KDF_TARGET_ITERATIONS)
    except Exception:
                                                            
        pass


@router.post("/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request) -> AuthResponse:
                                                                
                                                                      
    origin = request.headers.get("origin") or "-"
    device_id_present = bool(request.headers.get("x-device-id"))
    client_host = (request.client.host if request.client else "-") or "-"
    print(
        f"[AUTH] /auth/login ROUTE_ENTRY "
        f"origin={origin} client={client_host} "
        f"device_id_present={device_id_present} "
        f"lookup_present={bool(payload.username_lookup)} "
        f"pin_len={len(payload.pin or '')}",
        flush=True,
    )

    enforce_login_rate_limit(request)
    _validate_pin_shape(payload.pin, is_signup=False)
    username_lookup = _decode_username_lookup(payload.username_lookup)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT vault_id, pin_salt, pin_verifier, kdf_iterations,
                   failed_pin_attempts, locked_until, must_reset, display_username,
                   vault_handle
            FROM vaults
            WHERE username_lookup_v1 = %s
            """,
            (username_lookup,),
        )
        row = cur.fetchone()

        if not row:


            _do_dummy_derive(payload.pin)
            raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

        vault_id = str(row["vault_id"])
        pin_salt = row["pin_salt"]
        pin_verifier = row["pin_verifier"]
        iterations = int(row.get("kdf_iterations") or KDF_LEGACY_ITERATIONS)

                                                                    
        key = derive_key(payload.pin, pin_salt, iterations=iterations)
        try:
            verifier_ok = decrypt_message(pin_verifier, key) == PIN_VERIFIER_PLAINTEXT
        except Exception:
            verifier_ok = False

        if not verifier_ok:
                                                                       
                                                                   
            cur.execute("SELECT NOW() AS now")
            now_row = cur.fetchone() or {}
            now = now_row.get("now")

            prior_locked_until = row.get("locked_until")
            prior_attempts = 0 if (
                prior_locked_until and now and prior_locked_until < now
            ) else int(row.get("failed_pin_attempts") or 0)
            new_attempts = prior_attempts + 1

            if new_attempts >= MAX_PIN_ATTEMPTS:
                cur.execute(
                    """
                    UPDATE vaults
                    SET failed_pin_attempts = 0,
                        locked_until = NOW() + (INTERVAL '1 hour' * %s)
                    WHERE vault_id = %s
                    """,
                    (PIN_LOCKOUT_HOURS, vault_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE vaults
                    SET failed_pin_attempts = %s,
                        locked_until = NULL
                    WHERE vault_id = %s
                    """,
                    (new_attempts, vault_id),
                )
            conn.commit()
            raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

                                                               
        if row.get("must_reset"):
            raise HTTPException(
                status_code=423,
                detail={
                    "code":    "vault_frozen",
                    "message": "This vault has been frozen and cannot be unlocked.",
                },
            )

        cur.execute("SELECT NOW() AS now")
        now_row = cur.fetchone() or {}
        now = now_row.get("now")
        locked_until = row.get("locked_until")
        if locked_until and now and locked_until > now:
            raise HTTPException(
                status_code=423,
                detail={
                    "code":          "pin_locked",
                    "message":       "This vault is temporarily locked. Try again later.",
                    "locked_until":  locked_until.isoformat(),
                },
            )


        cur.execute(
            """
            UPDATE vaults
            SET failed_pin_attempts = 0,
                locked_until = NULL,
                last_login_at = NOW(),
                last_vault_unlock_at = NOW(),
                last_any_activity_at = NOW()
            WHERE vault_id = %s
            """,
            (vault_id,),
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.exception("[AUTH] login failed after opaque lookup")
        raise HTTPException(status_code=500, detail="Login failed")
    finally:
        conn.close()

    device_id = _device_id_from_request(request)
    newly_trusted = _upsert_trusted_device(
        vault_id=vault_id, device_id=device_id, request=request,
    )

    issued = issue_session_token(
        vault_id=vault_id,
        vault_name="",
        device_id=device_id,
        client_label=normalize_client_label(request.headers.get("user-agent")),
    )
    return _build_response(
        issued,
        display_username=row.get("display_username"),
        vault_handle=row.get("vault_handle"),
        new_device_trusted=newly_trusted,
    )


@router.get("/auth/me", response_model=MeResponse)
def me(principal: SessionPrincipal = Depends(verify_session_token)) -> MeResponse:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT vault_id, vault_handle, created_at
            FROM vaults
            WHERE vault_id = %s
            """,
            (principal["vault_id"],),
        )
        row = cur.fetchone()
        if not row:

            raise HTTPException(status_code=401, detail="Invalid token")
        return MeResponse(
            vault_id=str(row["vault_id"]),
            vault_name=None,
            display_username=None,
            vault_handle=_display_vault_handle(row.get("vault_handle")),
            zk=row.get("vault_handle") is not None,
            created_at=row["created_at"],
        )
    finally:
        conn.close()


class VaultNameUpdateRequest(BaseModel):
    # Compatibility-only. Current clients never send this field and the
    # service never stores it.
    vault_name: Optional[str] = Field(default=None, max_length=200)


class VaultNameResponse(BaseModel):
    vault_name: Optional[str]


@router.patch("/vault/name", response_model=VaultNameResponse)
def set_vault_name(
    payload: VaultNameUpdateRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> VaultNameResponse:
    """Retired compatibility endpoint.

    The readable vault name stays on the user's device and is never written
    into the service database.  Returning success avoids breaking an older
    client during the update window while discarding the supplied value.
    """
    del payload, principal
    return VaultNameResponse(vault_name=None)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def logout(principal: SessionPrincipal = Depends(verify_session_token)) -> Response:
    revoke_session_token(principal["token_id"])
                                                                      
                                                                     
    try:
        from vault_key_cache import get_cache
        get_cache().clear_session(principal["token_id"])
    except Exception:
                                                      
        pass

                                                              
    try:
        from vault_tool_result_cache import invalidate_session
        invalidate_session(
            vault_id=principal["vault_id"],
            token_id=principal["token_id"],
        )
    except Exception:
        pass

                                                             
    try:
        from vault_credential_draft import clear_drafts_for_vault
        clear_drafts_for_vault(principal["vault_id"])
    except Exception:
        pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
