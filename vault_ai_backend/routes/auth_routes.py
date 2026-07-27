

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from psycopg2 import errors as pg_errors
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
    generate_pin_salt,
    get_db,
)
from vault_handle import to_display as vault_handle_to_display


logger = logging.getLogger(__name__)
router = APIRouter()


VAULT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,49}$")
VAULT_NAME_MIN_LENGTH = 3
VAULT_NAME_MAX_LENGTH = 50

PIN_MAX_LENGTH = 64

GENERIC_LOGIN_ERROR = "Vault name or PIN is incorrect"


def _normalize_vault_name(raw: str) -> str:


    return (raw or "").strip().lower()


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


def _validate_vault_name(name: str) -> str:
    normalized = _normalize_vault_name(name)
    if not VAULT_NAME_PATTERN.match(normalized):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_vault_name",
                "message": (
                    f"Vault name must be {VAULT_NAME_MIN_LENGTH}-{VAULT_NAME_MAX_LENGTH} "
                    "characters, lowercase letters, digits, '_' or '-', and must "
                    "start with a letter or digit."
                ),
            },
        )
    return normalized


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


class SignupRequest(BaseModel):
    vault_name: str        = Field(..., min_length=1, max_length=64)
    pin: str               = Field(..., min_length=1, max_length=PIN_MAX_LENGTH)
    confirm_pin: str       = Field(..., min_length=1, max_length=PIN_MAX_LENGTH)
    display_username: Optional[str] = Field(default=None, max_length=200)
    acknowledged_irrecoverable: bool = Field(default=False)


class LoginRequest(BaseModel):
    vault_name: str = Field(..., min_length=1, max_length=64)
    pin: str        = Field(..., min_length=1, max_length=PIN_MAX_LENGTH)


class AuthResponse(BaseModel):
    session_token:      str
    vault_id:           str
    vault_name:         str
    display_username:   Optional[str] = None
    vault_handle:       Optional[str] = None
    zk:                 bool = False
                                                                     
                                                                    
    new_device_trusted: bool = False
    expires_at:         datetime


class MeResponse(BaseModel):
    vault_id:         str
    # vault_name is the user-chosen identity for the vault AND for
    # the AI keeper — one string, one concept. Nullable so ZK
    # accounts that haven't been backfilled since the 0031 migration
    # can exist as NULL; the frontend + prompt fall back to the
    # neutral literal "VaultAI" until the row carries a real value.
    # NEVER a hash, handle, UUID, template token, or random
    # placeholder. Set via /auth/zk-register-finalize or /auth/zk-
    # login-finalize (backfill) or PATCH /vault/name.
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
        vault_name=token_bundle["vault_name"],
        display_username=display_username,
        vault_handle=handle_display,
        zk=handle_display is not None,
        new_device_trusted=new_device_trusted,
        expires_at=token_bundle["expires_at"],
    )


@router.post("/auth/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, request: Request) -> AuthResponse:
                                                                        
                                                                 
    origin = request.headers.get("origin") or "-"
    device_id_present = bool(request.headers.get("x-device-id"))
    client_host = (request.client.host if request.client else "-") or "-"
    print(
        f"[AUTH] /auth/signup ROUTE_ENTRY "
        f"origin={origin} client={client_host} "
        f"device_id_present={device_id_present} "
        f"vault_name_len={len(payload.vault_name or '')} "
        f"pin_len={len(payload.pin or '')} "
        f"has_display_username={payload.display_username is not None} "
        f"acknowledged={payload.acknowledged_irrecoverable}",
        flush=True,
    )

    enforce_signup_rate_limit(request)

    if not payload.acknowledged_irrecoverable:
        raise HTTPException(
            status_code=400,
            detail={
                "code":    "acknowledgement_required",
                "message": (
                    "You must acknowledge that VaultAI cannot recover a "
                    "lost vault name or PIN."
                ),
            },
        )

    vault_name = _validate_vault_name(payload.vault_name)
    _validate_pin_shape(payload.pin, is_signup=True)
    if payload.pin != payload.confirm_pin:
        raise HTTPException(
            status_code=400,
            detail={"code": "pin_mismatch", "message": "PINs do not match"},
        )
    display_username = _validate_display_username(payload.display_username)

                                                                       
    pin_salt = generate_pin_salt()
    iterations = KDF_TARGET_ITERATIONS
    key = derive_key(payload.pin, pin_salt, iterations=iterations)
    pin_verifier = encrypt_message(PIN_VERIFIER_PLAINTEXT, key)

    vault_id = str(uuid.uuid4())
    account_id = str(uuid.uuid4())

                                                                    
    if display_username is None:
        display_username = _default_display_username(vault_id)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

                                                                   
        cur.execute(
            """
            INSERT INTO accounts (account_id, account_type, sales_channel)
            VALUES (%s, 'individual', 'self_service')
            """,
            (account_id,),
        )

        try:
            cur.execute(
                """
                INSERT INTO vaults
                  (vault_id, vault_name, display_username,
                   pin_salt, pin_verifier,
                   kdf_iterations, kdf_algorithm,
                   account_id, acknowledged_irrecoverable,
                   last_login_at, last_vault_unlock_at,
                   last_any_activity_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'pbkdf2_sha256', %s, TRUE,
                        NOW(), NOW(), NOW())
                """,
                (vault_id, vault_name, display_username,
                 pin_salt, pin_verifier, iterations, account_id),
            )
        except pg_errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "code":    "vault_name_taken",
                    "message": "That vault name is already taken.",
                },
            )

                                                             
        cur.execute(
            "UPDATE accounts SET billing_owner_vault_id = %s WHERE account_id = %s",
            (vault_id, account_id),
        )
        cur.execute(
            """
            INSERT INTO account_members (account_id, vault_id, role, status)
            VALUES (%s, %s, 'owner', 'active')
            """,
            (account_id, vault_id),
        )
        cur.execute(
            """
            INSERT INTO account_subscriptions (account_id, status, source)
            VALUES (%s, 'none', 'none')
            """,
            (account_id,),
        )
        cur.execute(
            "INSERT INTO account_storage_totals (account_id) VALUES (%s)",
            (account_id,),
        )

        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.exception("[AUTH] signup failed for vault_name_prefix=%s", vault_name[:3])
        raise HTTPException(status_code=500, detail="Signup failed")
    finally:
        conn.close()

    device_id = _device_id_from_request(request)
                                                                 
                                                                      
    _upsert_trusted_device(vault_id=vault_id, device_id=device_id, request=request)

    issued = issue_session_token(
        vault_id=vault_id,
        vault_name=vault_name,
        device_id=device_id,
        client_label=normalize_client_label(request.headers.get("user-agent")),
    )
    return _build_response(
        issued,
        display_username=display_username,
        new_device_trusted=False,
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
        f"vault_name_len={len(payload.vault_name or '')} "
        f"pin_len={len(payload.pin or '')}",
        flush=True,
    )

    enforce_login_rate_limit(request)
    _validate_pin_shape(payload.pin, is_signup=False)
    # 2026-07-20: preserve the user-typed casing here. Migration 0031
    # repurposed vaults.vault_name from the legacy lowercase-only
    # login identifier to the user-chosen product identity, and
    # tools.normalize_vault_name (used by ZK signup) preserves case.
    # A blind .lower() at the lookup step caused the endpoint to miss
    # every ZK-signed-up mixed-case row (e.g. "Alexa"), which surfaced
    # as the production "PIN loop" on the reload -> /pin path.
    vault_name_raw = (payload.vault_name or "").strip()
    if not vault_name_raw:


        _do_dummy_derive(payload.pin)
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Case-insensitive lookup with EXACT-case precedence, plus
        # explicit ambiguity refusal. Collision safety:
        #
        #  * Case-sensitive UNIQUE(vault_name) means at most ONE row
        #    can match exact-case equality with vault_name = %(raw)s.
        #  * If that exact-case row exists we use it — deterministic;
        #    NEVER authenticates a case-collided sibling.
        #  * If no exact-case match exists AND multiple rows share
        #    the same case-insensitive canonical form (reachable only
        #    across the legacy/ZK boundary — see the CollisionSchema
        #    audit in test_auth_login_case_insensitive_2026_07_20.py)
        #    we REFUSE with the same generic 401 as a nonexistent
        #    vault. Never pick an arbitrary row from a case-collided
        #    set: doing so would let a client who types the shared
        #    case-insensitive form authenticate as an unintended
        #    vault whose PIN happened to match.
        cur.execute(
            """
            SELECT vault_id, vault_name, pin_salt, pin_verifier, kdf_iterations,
                   failed_pin_attempts, locked_until, must_reset, display_username,
                   vault_handle,
                   (vault_name = %(raw)s) AS is_exact_match
            FROM vaults
            WHERE LOWER(vault_name) = LOWER(%(raw)s)
            """,
            {"raw": vault_name_raw},
        )
        rows = cur.fetchall()

        row = None
        if rows:
            exact_matches = [r for r in rows if r.get("is_exact_match")]
            if exact_matches:
                # UNIQUE(vault_name) case-sensitively guarantees len<=1.
                row = exact_matches[0]
            elif len(rows) == 1:
                row = rows[0]
            # else: ambiguous — leave row=None, fall through to the
            # generic 401 below.

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
        logger.exception("[AUTH] login failed for vault_name_prefix=%s", vault_name[:3])
        raise HTTPException(status_code=500, detail="Login failed")
    finally:
        conn.close()

    device_id = _device_id_from_request(request)
    newly_trusted = _upsert_trusted_device(
        vault_id=vault_id, device_id=device_id, request=request,
    )

    issued = issue_session_token(
        vault_id=vault_id,
        vault_name=row["vault_name"],
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
            SELECT vault_id, vault_name, display_username, vault_handle,
                   created_at
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
            vault_name=row.get("vault_name"),
            display_username=row.get("display_username"),
            vault_handle=_display_vault_handle(row.get("vault_handle")),
            zk=row.get("vault_handle") is not None,
            created_at=row["created_at"],
        )
    finally:
        conn.close()


class VaultNameUpdateRequest(BaseModel):
    # User-chosen identity for both the vault and the AI keeper.
    # Server normalizes (trim + whitespace-collapse + length 1..60
    # + no control chars) and stores plaintext in vaults.vault_name.
    # The server-side prompt builder always reads from
    # vaults.vault_name for the authenticated vault_id — the client
    # value here is authenticated by the session cookie but is only
    # used to WRITE the row; it is not otherwise trusted as an
    # identity source.
    vault_name: Optional[str] = Field(default=None, max_length=200)


class VaultNameResponse(BaseModel):
    vault_name: Optional[str]


@router.patch("/vault/name", response_model=VaultNameResponse)
def set_vault_name(
    payload: VaultNameUpdateRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> VaultNameResponse:
    """Set or clear the user-chosen vault name for the caller's
    authenticated vault.

    Passing ``vault_name: null`` (or a value that normalizes to
    empty) clears the column; the prompt builder then falls back
    to the neutral ``VaultAI`` literal.

    The endpoint touches ONLY the row for ``principal["vault_id"]``.
    """
    from tools import normalize_vault_name
    normalized: Optional[str] = normalize_vault_name(payload.vault_name)
    # Explicit clear semantics: the request supplied a value but it
    # normalized away (e.g. all whitespace or all control chars).
    # Treat that as "clear the column" rather than 400 — the user
    # is asking for no name, and the fallback path is what we want.
    conn = get_db()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE vaults SET vault_name = %s WHERE vault_id = %s",
                (normalized, principal["vault_id"]),
            )
        except pg_errors.UniqueViolation as exc:
            conn.rollback()
            # The vault_name column carries a UNIQUE index inherited
            # from the legacy login-lookup era. NULL doesn't collide,
            # but two accounts trying to claim the same non-NULL
            # value do. Surface a clean 409.
            raise HTTPException(
                status_code=409,
                detail="That vault name is already in use.",
            ) from exc
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="vault not found")
        conn.commit()
    finally:
        conn.close()
    return VaultNameResponse(vault_name=normalized)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(principal: SessionPrincipal = Depends(verify_session_token)) -> None:
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

    return None


__all__ = ["router"]
