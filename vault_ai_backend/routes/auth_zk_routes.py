"""Zero-knowledge OPAQUE (RFC 9807) auth routes.

Endpoints:

* ``POST /auth/zk-register-init``      — client sends
    (vault_handle, ke1_registration_request); server replies with
    ``ke2_registration_response``.
* ``POST /auth/zk-register-finalize``  — client sends
    (vault_handle, ke3_registration_upload, wrapped_mvk,
    wrapped_sk_vault, pk_vault_public, display_name_ciphertext,
    account_type, acknowledged_irrecoverable); server writes the
    ``vaults`` row, ``account_members`` link, and empty
    ``account_subscriptions``; issues an initial session token bound
    to the newly-minted vault_id.
* ``POST /auth/zk-login-init``         — client sends
    (vault_handle, ke1_credential_request); server looks up the
    registration record, runs OPAQUE ``server_login_start``, stores
    the resulting server_state in ``vault_zk_login_slots`` under a
    fresh ``slot_id``, returns (slot_id, ke2_credential_response).
* ``POST /auth/zk-login-finalize``     — client sends
    (slot_id, ke3_credential_finalization); server finalizes,
    consumes the slot (single-use), issues a session token, returns
    wrapped MVK / wrapped_sk_vault / display_name_ciphertext for
    the client to decrypt locally.
* ``POST /auth/zk-adopt``              — authenticated LEGACY user
    (session issued via the old ``/auth/login`` path) supplies their
    freshly-constructed ZK state (vault_handle, opaque_registration
    upload path already run, wrapped_mvk under new KEK, ...). Server
    writes the ZK columns and atomically nulls the legacy
    ``pin_salt`` / ``pin_verifier`` / ``kdf_iterations`` / vault_name.
    Idempotent: a second call for a vault that already has a
    vault_handle returns 409 Conflict.

The server sees NO plaintext PIN, NO vault master key, NO plaintext
display name in any of these paths. The plaintext vault_handle
transits the login request over TLS, is used only for row lookup, is
never logged, and is discarded end-of-request.

Nothing here contains cryptography. All OPAQUE operations are
delegated to ``opaque_server_module`` which delegates to the audited
``opaque-ke`` crate via ``vaultai_opaque_server`` pyo3 wheel.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional


def _handle_fingerprint(handle_bytes: bytes) -> str:
    """First 4 bytes of SHA-256(handle_bytes), hex-encoded.

    Non-reversible pointer to a specific vault_handle that can be
    correlated across register + login logs without exposing the
    handle itself or the username it derives from.
    """
    return hashlib.sha256(handle_bytes).hexdigest()[:8]


def _record_fingerprint(record_bytes: bytes) -> str:
    """First 4 bytes of SHA-256(opaque_registration_record), hex.

    A stable identifier for the stored OPAQUE record that lets an
    operator confirm the same record byte-for-byte was used at
    register-finish and at every subsequent login-init without
    logging the record itself (which is registration-secret material).
    """
    return hashlib.sha256(record_bytes).hexdigest()[:8]


_USERNAME_BLIND_INDEX_ENV_VAR = "VAULTAI_USERNAME_BLIND_INDEX_PEPPER"


def _username_blind_index_pepper() -> Optional[bytes]:
    """Return the per-deployment pepper for the username blind index.

    Returns None when the env var is unset — in which case the
    endpoints degrade to the pre-2026-07-20 behavior (uniqueness only
    on ``vault_handle``, no blind index written). Never logs the
    pepper's value.
    """
    raw = os.environ.get(_USERNAME_BLIND_INDEX_ENV_VAR)
    if not raw:
        return None
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        return raw.encode("utf-8")


def _compute_username_blind_index(
    normalized_username: str,
) -> Optional[bytes]:
    """HMAC-SHA256 of the normalized username under the deployment
    pepper. Returns None when no pepper is configured.
    """
    pepper = _username_blind_index_pepper()
    if pepper is None:
        return None
    return hmac.new(
        pepper,
        normalized_username.encode("utf-8"),
        hashlib.sha256,
    ).digest()


def _username_blind_index_fingerprint(bi: bytes) -> str:
    """8-hex fingerprint of the blind index for correlated logs. The
    full 32 bytes are already non-reversible without the pepper; the
    fingerprint is a further truncation so log strings never carry
    the entire lookup token.
    """
    return hashlib.sha256(bi).hexdigest()[:8]

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from psycopg2 import errors as pg_errors
from psycopg2.extras import RealDictCursor

from auth_local import (
    SessionPrincipal,
    issue_session_token,
    normalize_client_label,
    verify_session_token,
)
from opaque_server_module import (
    OpaqueError,
    OpaqueProtocolError,
    OpaqueSetupMissing,
    OpaqueWheelMissing,
    login_finish as opaque_login_finish,
    login_start as opaque_login_start,
    registration_finish as opaque_registration_finish,
    registration_start as opaque_registration_start,
)
from rate_limit_auth import (
    enforce_login_rate_limit,
    enforce_signup_rate_limit,
)
from vault_core import get_db
from vault_handle import (
    InvalidUsername,
    InvalidVaultHandle,
    VAULT_HANDLE_BYTES,
    from_display,
    normalize_username,
    to_display,
)


logger = logging.getLogger(__name__)
router = APIRouter()


LOGIN_SLOT_TTL_SECONDS = 90

MAX_OPAQUE_MESSAGE_BYTES = 8 * 1024
MAX_WRAPPED_BLOB_BYTES = 64 * 1024


GENERIC_ZK_AUTH_ERROR = "Wrong username or PIN."
DUPLICATE_USERNAME_ERROR = (
    "That username is already taken. Please choose another."
)


def _normalized_username_or_400(raw: str) -> str:
    """Server-side re-normalization guard.

    The client is expected to send an already-normalized username so
    that both sides derive the same vault_handle and the same blind
    index. We re-normalize on receive as defense-in-depth: a
    tampered/legacy client that sends the raw string would otherwise
    produce a blind index that never collides with another user's,
    silently defeating the uniqueness check.
    """
    try:
        return normalize_username(raw)
    except InvalidUsername as exc:
        raise HTTPException(
            status_code=400,
            detail="username is malformed",
        ) from exc


def _b64url_decode(value: str, *, name: str, max_bytes: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise HTTPException(
            status_code=400,
            detail=f"{name} is required",
        )
    if len(value) > max_bytes * 2:
        raise HTTPException(
            status_code=413,
            detail=f"{name} exceeds size limit",
        )
    try:
        decoded = base64.urlsafe_b64decode(
            value + "=" * (-len(value) % 4)
        )
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{name} is not valid base64url",
        ) from exc
    if len(decoded) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{name} exceeds byte limit",
        )
    return decoded


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_handle_or_400(display: str) -> bytes:
    try:
        return from_display(display)
    except InvalidVaultHandle as exc:
        raise HTTPException(
            status_code=400, detail="vault_handle is malformed",
        ) from exc


def _opaque_credential_id(handle_bytes: bytes) -> bytes:
    """Return the UTF-8 bytes of ``base64url(handle_bytes)`` — the value
    passed to opaque-ke's ``credential_identifier`` on both sides.

    The Flutter web client cannot pass raw binary through
    ``@serenity-kit/opaque``'s ``userIdentifier`` (that API accepts a
    string). Both sides therefore agree to use the base64url text form
    of the 15-byte handle as the credential id. Same information
    content, cross-language wire-compatible.
    """
    return _b64url_encode(handle_bytes).encode("ascii")


class ZkRegisterInitRequest(BaseModel):
    vault_handle: str = Field(..., min_length=1, max_length=200)
    ke1: str = Field(..., min_length=1)
    # New in 2026-07-20: the client sends the RFC-normalized username
    # so the server can compute a derivation-version-independent
    # blind index and reject duplicates that the vault_handle UNIQUE
    # alone cannot detect. Optional (a stale client still works via
    # vault_handle uniqueness only) but strongly recommended.
    normalized_username: Optional[str] = Field(
        default=None, min_length=1, max_length=200,
    )


class ZkRegisterInitResponse(BaseModel):
    ke2: str


@router.post("/auth/zk-register-init", response_model=ZkRegisterInitResponse)
async def zk_register_init(
    payload: ZkRegisterInitRequest,
    request: Request,
) -> ZkRegisterInitResponse:
    enforce_signup_rate_limit(request)
    handle_bytes = _decode_handle_or_400(payload.vault_handle)
    ke1 = _b64url_decode(payload.ke1, name="ke1",
                         max_bytes=MAX_OPAQUE_MESSAGE_BYTES)

    # Early duplicate check on the canonical-username layer. If the
    # client supplied a normalized_username AND the deployment is
    # configured with a blind-index pepper, refuse to start the OPAQUE
    # exchange when the username is already taken. This surfaces the
    # collision BEFORE any server-side OPRF state is created, so
    # nothing about the existing record leaks. If either the client
    # omits the field or no pepper is configured, we still fall
    # through to the vault_handle uniqueness gate at finalize.
    if payload.normalized_username is not None:
        normalized = _normalized_username_or_400(payload.normalized_username)
        bi = _compute_username_blind_index(normalized)
        if bi is not None:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT 1 FROM vaults
                    WHERE username_blind_index = %s
                    LIMIT 1
                    """,
                    (bi,),
                )
                if cur.fetchone() is not None:
                    logger.info(
                        "[ZK-REGISTER-INIT] duplicate username pid=%d "
                        "handle_fpr=%s bi_fpr=%s",
                        os.getpid(),
                        _handle_fingerprint(handle_bytes),
                        _username_blind_index_fingerprint(bi),
                    )
                    raise HTTPException(
                        status_code=409,
                        detail=DUPLICATE_USERNAME_ERROR,
                    )
            finally:
                conn.close()

    try:
        ke2 = opaque_registration_start(ke1, _opaque_credential_id(handle_bytes))
    except OpaqueWheelMissing:
        logger.exception("[ZK-REGISTER] opaque wheel missing")
        raise HTTPException(
            status_code=503, detail="zk auth not available in this build",
        )
    except OpaqueSetupMissing:
        logger.exception("[ZK-REGISTER] opaque setup env var not set")
        raise HTTPException(
            status_code=503, detail="zk auth not configured",
        )
    except OpaqueError:
        logger.warning("[ZK-REGISTER] init rejected")
        raise HTTPException(status_code=400, detail="registration rejected")
    return ZkRegisterInitResponse(ke2=_b64url_encode(ke2))


class ZkRegisterFinalizeRequest(BaseModel):
    vault_handle: str = Field(..., min_length=1, max_length=200)
    ke3: str = Field(..., min_length=1)
    wrapped_mvk: str = Field(..., min_length=1)
    wrapped_sk_vault: str = Field(..., min_length=1)
    pk_vault_public: str = Field(..., min_length=1)
    display_name_ciphertext: str = Field(..., min_length=1)
    acknowledged_irrecoverable: bool
    device_id: Optional[str] = Field(default=None, max_length=128)
    # Legacy PIN verifier (PBKDF2-derived, base64) supplied by the
    # client so that endpoints which still cross-check the PIN
    # (currently only /beneficiary/link) work for ZK-registered
    # accounts. Server never sees the plaintext PIN.
    pin_salt: str = Field(..., min_length=1, max_length=200)
    pin_verifier: str = Field(..., min_length=1, max_length=400)
    kdf_iterations: int = Field(..., ge=100_000, le=2_000_000)
    # Same as ZkRegisterInitRequest.normalized_username. Optional so
    # older client builds still complete registration on the plain
    # vault_handle uniqueness path.
    normalized_username: Optional[str] = Field(
        default=None, min_length=1, max_length=200,
    )

    @field_validator("acknowledged_irrecoverable")
    @classmethod
    def _must_ack(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "acknowledged_irrecoverable must be true; the vault is "
                "irrecoverable if the PIN and recovery kit are lost."
            )
        return v


class ZkRegisterFinalizeResponse(BaseModel):
    vault_id: str
    vault_handle: str
    session_token: str


@router.post("/auth/zk-register-finalize", response_model=ZkRegisterFinalizeResponse)
async def zk_register_finalize(
    payload: ZkRegisterFinalizeRequest,
    request: Request,
) -> ZkRegisterFinalizeResponse:
    enforce_signup_rate_limit(request)

    handle_bytes = _decode_handle_or_400(payload.vault_handle)
    ke3 = _b64url_decode(
        payload.ke3, name="ke3", max_bytes=MAX_OPAQUE_MESSAGE_BYTES,
    )
    wrapped_mvk = _b64url_decode(
        payload.wrapped_mvk, name="wrapped_mvk",
        max_bytes=MAX_WRAPPED_BLOB_BYTES,
    )
    wrapped_sk_vault = _b64url_decode(
        payload.wrapped_sk_vault, name="wrapped_sk_vault",
        max_bytes=MAX_WRAPPED_BLOB_BYTES,
    )
    pk_vault_public = _b64url_decode(
        payload.pk_vault_public, name="pk_vault_public",
        max_bytes=64,
    )
    if len(pk_vault_public) != 32:
        raise HTTPException(
            status_code=400,
            detail="pk_vault_public must be 32 bytes (X25519 point)",
        )
    display_name_ciphertext = _b64url_decode(
        payload.display_name_ciphertext,
        name="display_name_ciphertext",
        max_bytes=MAX_WRAPPED_BLOB_BYTES,
    )

    try:
        record = opaque_registration_finish(ke3)
    except OpaqueWheelMissing:
        raise HTTPException(
            status_code=503, detail="zk auth not available",
        )
    except OpaqueError:
        raise HTTPException(status_code=400, detail="registration rejected")

    # Safe diagnostic: the SAME (handle_fpr, record_fpr) pair should
    # appear later in the [ZK-LOGIN-INIT] log for this account. If a
    # subsequent login shows a DIFFERENT record_fpr for the same
    # handle_fpr, the record on disk was silently rewritten — a
    # storage-layer bug.
    logger.info(
        "[ZK-REGISTER-FINALIZE] pid=%d handle_fpr=%s record_fpr=%s "
        "stage=registration_finish",
        os.getpid(),
        _handle_fingerprint(handle_bytes),
        _record_fingerprint(record),
    )

    # Compute the blind index once; used by the INSERT column, the
    # diagnostic log line, and the UniqueViolation classification.
    blind_index: Optional[bytes] = None
    if payload.normalized_username is not None:
        normalized = _normalized_username_or_400(payload.normalized_username)
        blind_index = _compute_username_blind_index(normalized)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO accounts (account_id, account_type, sales_channel)
            VALUES (gen_random_uuid(), 'individual', 'self_service')
            RETURNING account_id
            """,
        )
        account_id = cur.fetchone()["account_id"]

        try:
            cur.execute(
                """
                INSERT INTO vaults (
                  vault_id, pin_salt, pin_verifier, kdf_iterations,
                  vault_handle, opaque_registration_record,
                  wrapped_mvk, wrapped_sk_vault, pk_vault_public,
                  display_name_ciphertext,
                  account_id, acknowledged_irrecoverable,
                  vault_name,
                  username_blind_index
                )
                VALUES (
                  gen_random_uuid(), %s, %s, %s,
                  %s, %s,
                  %s, %s, %s,
                  %s,
                  %s, %s,
                  encode(gen_random_bytes(16),'hex'),
                  %s
                )
                RETURNING vault_id, vault_name
                """,
                (
                    payload.pin_salt, payload.pin_verifier,
                    payload.kdf_iterations,
                    handle_bytes, record,
                    wrapped_mvk, wrapped_sk_vault, pk_vault_public,
                    display_name_ciphertext,
                    account_id, payload.acknowledged_irrecoverable,
                    blind_index,
                ),
            )
        except pg_errors.UniqueViolation as exc:
            # The vaults INSERT sits in the same implicit transaction
            # as the accounts INSERT above; rollback here undoes both,
            # so no orphan ``accounts`` row is left behind. Either the
            # vault_handle partial UNIQUE fired (same derivation as an
            # existing row) OR the username_blind_index partial UNIQUE
            # fired (same canonical username as an existing row under
            # a different derivation). Both cases surface as the same
            # 409 to the client — the difference is diagnostic only.
            conn.rollback()
            logger.warning(
                "[ZK-REGISTER] duplicate on finalize (handle_fpr=%s bi_fpr=%s)",
                _handle_fingerprint(handle_bytes),
                _username_blind_index_fingerprint(blind_index)
                if blind_index is not None else "-",
            )
            raise HTTPException(
                status_code=409,
                detail=DUPLICATE_USERNAME_ERROR,
            ) from exc
        _new_vault_row = cur.fetchone()
        vault_id = str(_new_vault_row["vault_id"])
        vault_name = _new_vault_row["vault_name"]

        cur.execute(
            """
            INSERT INTO account_members (account_id, vault_id, role, status)
            VALUES (%s, %s, 'owner', 'active')
            """,
            (account_id, vault_id),
        )
        cur.execute(
            """
            INSERT INTO account_subscriptions (account_id)
            VALUES (%s)
            ON CONFLICT (account_id) DO NOTHING
            """,
            (account_id,),
        )
        conn.commit()
    finally:
        conn.close()

    token = issue_session_token(
        vault_id=vault_id,
        vault_name=vault_name,
        device_id=payload.device_id,
        client_label=normalize_client_label(request.headers.get("user-agent")),
    )

    return ZkRegisterFinalizeResponse(
        vault_id=vault_id,
        vault_handle=to_display(handle_bytes),
        session_token=token["token"],
    )


class ZkLoginInitRequest(BaseModel):
    vault_handle: str = Field(..., min_length=1, max_length=200)
    ke1: str = Field(..., min_length=1)
    # Optional canonical username so the server can fall back to the
    # blind-index lookup if the vault_handle bytes don't match a row
    # (which happens for accounts registered before the deterministic
    # derivation was introduced). Never persisted; only used for the
    # single row lookup and then discarded end-of-request.
    normalized_username: Optional[str] = Field(
        default=None, min_length=1, max_length=200,
    )


class ZkLoginInitResponse(BaseModel):
    slot_id: str
    ke2: str


@router.post("/auth/zk-login-init", response_model=ZkLoginInitResponse)
async def zk_login_init(
    payload: ZkLoginInitRequest,
    request: Request,
) -> ZkLoginInitResponse:
    enforce_login_rate_limit(request)

    handle_bytes = _decode_handle_or_400(payload.vault_handle)
    ke1 = _b64url_decode(
        payload.ke1, name="ke1", max_bytes=MAX_OPAQUE_MESSAGE_BYTES,
    )

    lookup_bi: Optional[bytes] = None
    if payload.normalized_username is not None:
        normalized = _normalized_username_or_400(payload.normalized_username)
        lookup_bi = _compute_username_blind_index(normalized)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT vault_id, opaque_registration_record, vault_handle,
                   username_blind_index
            FROM vaults
            WHERE vault_handle = %s
            """,
            (handle_bytes,),
        )
        row = cur.fetchone()
        # Fallback: a client-supplied vault_handle that misses may
        # still name a real account if the client's derivation drifted
        # since registration (algorithm change, normalization tweak).
        # If we have a blind index for the canonical username, look
        # the row up by that instead.
        if row is None and lookup_bi is not None:
            cur.execute(
                """
                SELECT vault_id, opaque_registration_record, vault_handle,
                       username_blind_index
                FROM vaults
                WHERE username_blind_index = %s
                """,
                (lookup_bi,),
            )
            row = cur.fetchone()
        # Opportunistic backfill: any row we successfully match whose
        # blind index is NULL gets it populated now, so a subsequent
        # duplicate-registration attempt for the same canonical
        # username will collide on the partial UNIQUE index. This is
        # the migration story for accounts that predate this column.
        if (
            row is not None
            and lookup_bi is not None
            and row["username_blind_index"] is None
        ):
            cur.execute(
                """
                UPDATE vaults
                   SET username_blind_index = %s
                 WHERE vault_id = %s
                   AND username_blind_index IS NULL
                """,
                (lookup_bi, row["vault_id"]),
            )
            conn.commit()
    finally:
        conn.close()

    if row is None or row["opaque_registration_record"] is None:
        logger.info(
            "[ZK-LOGIN-INIT] no vault for handle "
            "pid=%d handle_fpr=%s bi_fpr=%s",
            os.getpid(),
            _handle_fingerprint(handle_bytes),
            _username_blind_index_fingerprint(lookup_bi)
            if lookup_bi is not None else "-",
        )
        raise HTTPException(
            status_code=401, detail=GENERIC_ZK_AUTH_ERROR,
        )

    # Use the STORED handle bytes as the OPAQUE credential_identifier.
    # This is what was passed to registration_start when the record
    # was created; passing anything else keys the OPRF with the wrong
    # secret and the AKE would fail. Almost always this equals the
    # bytes the client sent, but for a blind-index fallback the two
    # can differ — and the stored bytes are the correct ones.
    stored_handle_bytes = bytes(row["vault_handle"])
    record_bytes = bytes(row["opaque_registration_record"])
    # Safe diagnostic: correlates register-finish and every subsequent
    # login-init for the SAME account without leaking secrets.
    # Also reveals whether two workers see the same registration
    # record (they should — the record lives in Postgres, not in a
    # per-worker cache).
    logger.info(
        "[ZK-LOGIN-INIT] pid=%d handle_fpr=%s record_fpr=%s "
        "vault_id=%s stage=login_start",
        os.getpid(),
        _handle_fingerprint(handle_bytes),
        _record_fingerprint(record_bytes),
        row["vault_id"],
    )

    try:
        ke2, server_state = opaque_login_start(
            record_bytes,
            ke1,
            _opaque_credential_id(stored_handle_bytes),
        )
    except OpaqueWheelMissing:
        raise HTTPException(
            status_code=503, detail="zk auth not available",
        )
    except OpaqueError:
        raise HTTPException(
            status_code=401, detail=GENERIC_ZK_AUTH_ERROR,
        )

    slot_id = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=LOGIN_SLOT_TTL_SECONDS,
    )

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vault_zk_login_slots
              (slot_id, vault_id, server_state, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (slot_id, row["vault_id"], server_state, expires_at),
        )
        conn.commit()
    finally:
        conn.close()

    return ZkLoginInitResponse(
        slot_id=slot_id,
        ke2=_b64url_encode(ke2),
    )


class ZkLoginFinalizeRequest(BaseModel):
    slot_id: str = Field(..., min_length=1, max_length=128)
    ke3: str = Field(..., min_length=1)
    device_id: Optional[str] = Field(default=None, max_length=128)


class ZkLoginFinalizeResponse(BaseModel):
    vault_id: str
    session_token: str
    wrapped_mvk: str
    wrapped_sk_vault: str
    display_name_ciphertext: str


@router.post("/auth/zk-login-finalize", response_model=ZkLoginFinalizeResponse)
async def zk_login_finalize(
    payload: ZkLoginFinalizeRequest,
    request: Request,
) -> ZkLoginFinalizeResponse:
    ke3 = _b64url_decode(
        payload.ke3, name="ke3", max_bytes=MAX_OPAQUE_MESSAGE_BYTES,
    )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            DELETE FROM vault_zk_login_slots
            WHERE slot_id = %s
              AND expires_at > NOW()
            RETURNING vault_id, server_state
            """,
            (payload.slot_id,),
        )
        row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    if row is None:
        logger.info("[ZK-LOGIN-FINALIZE] slot missing or expired")
        raise HTTPException(
            status_code=401, detail=GENERIC_ZK_AUTH_ERROR,
        )

    try:
        _session_key = opaque_login_finish(
            bytes(row["server_state"]), ke3,
        )
    except OpaqueWheelMissing:
        raise HTTPException(
            status_code=503, detail="zk auth not available",
        )
    except OpaqueError:
        logger.info("[ZK-LOGIN-FINALIZE] opaque protocol reject")
        raise HTTPException(
            status_code=401, detail=GENERIC_ZK_AUTH_ERROR,
        )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            UPDATE vaults
              SET last_login_at        = NOW(),
                  last_vault_unlock_at = NOW(),
                  last_any_activity_at = NOW(),
                  failed_pin_attempts  = 0
              WHERE vault_id = %s
              RETURNING vault_id, vault_name, wrapped_mvk, wrapped_sk_vault,
                        display_name_ciphertext
            """,
            (row["vault_id"],),
        )
        vault_row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    if vault_row is None:
        raise HTTPException(
            status_code=401, detail=GENERIC_ZK_AUTH_ERROR,
        )

    token = issue_session_token(
        vault_id=str(vault_row["vault_id"]),
        vault_name=vault_row["vault_name"],
        device_id=payload.device_id,
        client_label=normalize_client_label(request.headers.get("user-agent")),
    )

    return ZkLoginFinalizeResponse(
        vault_id=str(vault_row["vault_id"]),
        session_token=token["token"],
        wrapped_mvk=_b64url_encode(bytes(vault_row["wrapped_mvk"])),
        wrapped_sk_vault=_b64url_encode(bytes(vault_row["wrapped_sk_vault"])),
        display_name_ciphertext=_b64url_encode(
            bytes(vault_row["display_name_ciphertext"]),
        ),
    )


class ZkAdoptRequest(BaseModel):
    vault_handle: str = Field(..., min_length=1, max_length=200)
    opaque_registration_record: str = Field(..., min_length=1)
    wrapped_mvk: str = Field(..., min_length=1)
    wrapped_sk_vault: str = Field(..., min_length=1)
    pk_vault_public: str = Field(..., min_length=1)
    display_name_ciphertext: str = Field(..., min_length=1)


class ZkAdoptResponse(BaseModel):
    adopted: bool
    vault_handle: str


@router.post("/auth/zk-adopt", response_model=ZkAdoptResponse)
async def zk_adopt(
    payload: ZkAdoptRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> ZkAdoptResponse:
    handle_bytes = _decode_handle_or_400(payload.vault_handle)
    record = _b64url_decode(
        payload.opaque_registration_record,
        name="opaque_registration_record",
        max_bytes=MAX_OPAQUE_MESSAGE_BYTES,
    )
    wrapped_mvk = _b64url_decode(
        payload.wrapped_mvk, name="wrapped_mvk",
        max_bytes=MAX_WRAPPED_BLOB_BYTES,
    )
    wrapped_sk_vault = _b64url_decode(
        payload.wrapped_sk_vault, name="wrapped_sk_vault",
        max_bytes=MAX_WRAPPED_BLOB_BYTES,
    )
    pk_vault_public = _b64url_decode(
        payload.pk_vault_public, name="pk_vault_public",
        max_bytes=64,
    )
    if len(pk_vault_public) != 32:
        raise HTTPException(
            status_code=400,
            detail="pk_vault_public must be 32 bytes",
        )
    display_name_ciphertext = _b64url_decode(
        payload.display_name_ciphertext,
        name="display_name_ciphertext",
        max_bytes=MAX_WRAPPED_BLOB_BYTES,
    )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT vault_handle IS NOT NULL AS already_zk
            FROM vaults
            WHERE vault_id = %s
            """,
            (principal["vault_id"],),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="vault not found")
        if row["already_zk"]:
            raise HTTPException(
                status_code=409, detail="vault is already zk-adopted",
            )

        try:
            # Adoption preserves the legacy pin_salt/pin_verifier: the
            # user is the same person with the same PIN, and the
            # /beneficiary/link endpoint's PIN cross-check still uses
            # that verifier. The wire representation of the PIN never
            # left the legacy signup — this row was populated at
            # legacy account creation. Wiping it here would break the
            # inheritance-link path for adopted users.
            cur.execute(
                """
                UPDATE vaults
                  SET vault_handle                  = %s,
                      opaque_registration_record    = %s,
                      wrapped_mvk                   = %s,
                      wrapped_sk_vault              = %s,
                      pk_vault_public               = %s,
                      display_name_ciphertext       = %s,
                      legacy_vault_name_cleared_at  = NOW()
                  WHERE vault_id = %s
                    AND vault_handle IS NULL
                """,
                (
                    handle_bytes, record,
                    wrapped_mvk, wrapped_sk_vault, pk_vault_public,
                    display_name_ciphertext,
                    principal["vault_id"],
                ),
            )
        except pg_errors.UniqueViolation as exc:
            conn.rollback()
            raise HTTPException(
                status_code=409, detail="vault_handle collision",
            ) from exc
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(
                status_code=409, detail="adopt failed",
            )
        conn.commit()
    finally:
        conn.close()

    return ZkAdoptResponse(
        adopted=True,
        vault_handle=to_display(handle_bytes),
    )


__all__ = ["router"]
