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


# Length of the client-derived username lookup identifier
# (SHA-256 output). See vault_handle.dart::deriveUsernameLookupV1
# and migration 0030_username_blind_index.
USERNAME_LOOKUP_V1_BYTES = 32


def _lookup_v1_fingerprint(lookup: bytes) -> str:
    """8-hex fingerprint of a username_lookup_v1 value for correlated
    logs. The full 32 bytes are already non-reversible without a
    dictionary attack on common usernames; the fingerprint truncates
    further so no log line carries the entire lookup id.
    """
    return hashlib.sha256(lookup).hexdigest()[:8]


def _decode_lookup_v1_or_400(text: str) -> bytes:
    """base64url-decode the client-supplied username_lookup and
    verify it is 32 bytes. Rejects malformed or wrong-length values
    with HTTP 400 so a stale/hostile client can't sneak past the
    UNIQUE index by supplying a truncated identifier.
    """
    raw = _b64url_decode(
        text, name="username_lookup", max_bytes=USERNAME_LOOKUP_V1_BYTES + 4,
    )
    if len(raw) != USERNAME_LOOKUP_V1_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"username_lookup must be exactly "
                   f"{USERNAME_LOOKUP_V1_BYTES} bytes",
        )
    return raw

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
    InvalidVaultHandle,
    VAULT_HANDLE_BYTES,
    from_display,
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
    # Client-derived 32-byte username lookup identifier (base64url,
    # no padding). See vault_handle.dart::deriveUsernameLookupV1:
    #   lookup_v1 = SHA-256(b"vaultai.username_lookup.v1|"
    #                       || nfkc_casefolded_utf8_username)
    # The raw username is NEVER sent to the server. The server sees
    # 32 opaque bytes with the same visibility properties as
    # vault_handle. Optional so a stale client still completes on
    # the vault_handle uniqueness gate alone.
    username_lookup: Optional[str] = Field(
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

    # Preflight duplicate check on the derivation-version-independent
    # username_lookup_v1 layer. If the client supplied one AND a row
    # already carries it, refuse to start the OPAQUE exchange. This
    # surfaces the collision BEFORE any server-side OPRF state is
    # created, so nothing about the existing record leaks. The
    # authoritative uniqueness gate is the partial UNIQUE index on
    # vaults.username_lookup_v1 at INSERT time (atomic vs. concurrent
    # registrations — the preflight is only an early hint).
    if payload.username_lookup is not None:
        lookup_bytes = _decode_lookup_v1_or_400(payload.username_lookup)
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT 1 FROM vaults
                WHERE username_lookup_v1 = %s
                LIMIT 1
                """,
                (lookup_bytes,),
            )
            if cur.fetchone() is not None:
                logger.info(
                    "[ZK-REGISTER-INIT] duplicate username pid=%d "
                    "handle_fpr=%s lookup_fpr=%s",
                    os.getpid(),
                    _handle_fingerprint(handle_bytes),
                    _lookup_v1_fingerprint(lookup_bytes),
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
    # Same as ZkRegisterInitRequest.username_lookup — 32 opaque
    # bytes (base64url) derived client-side from the canonical
    # username. Optional so older client builds still complete
    # registration on the plain vault_handle uniqueness path.
    username_lookup: Optional[str] = Field(
        default=None, min_length=1, max_length=200,
    )
    # User-chosen vault name (product-facing identity for BOTH the
    # vault and the AI keeper). Stored plaintext in
    # vaults.vault_name after server-side normalization. Optional
    # so a stale client can still register — the row is created
    # with vault_name = NULL and the fixed client's next login
    # backfills it.
    vault_name: Optional[str] = Field(
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

    # Decode the client's username_lookup once; used by the INSERT
    # column and by the UniqueViolation diagnostic. Absence means the
    # row will be written with NULL and only participate in
    # vault_handle uniqueness — pre-migration behavior.
    lookup_bytes: Optional[bytes] = None
    if payload.username_lookup is not None:
        lookup_bytes = _decode_lookup_v1_or_400(payload.username_lookup)

    # Normalize the user-chosen vault name. Before migration 0031
    # this INSERT wrote encode(gen_random_bytes(16),'hex') to satisfy
    # the NOT NULL UNIQUE constraint on vault_name — that produced
    # the 32-hex placeholder that leaked into the typing indicator
    # as "b21e31c5b59abdc8067ff6b23643b254 is thinking...". 0031
    # dropped NOT NULL and repurposed the column as the user-chosen
    # identity for both the vault and its AI keeper. We now insert
    # the client-supplied name (normalized) or NULL.
    from tools import normalize_vault_name
    stored_vault_name: Optional[str] = normalize_vault_name(payload.vault_name)

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
                  username_lookup_v1
                )
                VALUES (
                  gen_random_uuid(), %s, %s, %s,
                  %s, %s,
                  %s, %s, %s,
                  %s,
                  %s, %s,
                  %s,
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
                    stored_vault_name,
                    lookup_bytes,
                ),
            )
        except pg_errors.UniqueViolation as exc:
            # The vaults INSERT sits in the same implicit transaction
            # as the accounts INSERT above; rollback here undoes both,
            # so no orphan ``accounts`` row is left behind. Either the
            # vault_handle partial UNIQUE fired (same derivation as an
            # existing row) OR the username_lookup_v1 partial UNIQUE
            # fired (same canonical username as an existing row under
            # any derivation). Both cases surface as the same 409 to
            # the client — the difference is diagnostic only. This is
            # the ATOMIC duplicate-registration gate: the preflight
            # check at zk-register-init is only an early hint;
            # concurrent registrations of the same username collide
            # here.
            conn.rollback()
            logger.warning(
                "[ZK-REGISTER] duplicate on finalize (handle_fpr=%s lookup_fpr=%s)",
                _handle_fingerprint(handle_bytes),
                _lookup_v1_fingerprint(lookup_bytes)
                if lookup_bytes is not None else "-",
            )
            raise HTTPException(
                status_code=409,
                detail=DUPLICATE_USERNAME_ERROR,
            ) from exc
        _new_vault_row = cur.fetchone()
        vault_id = str(_new_vault_row["vault_id"])
        # RETURNING can bring back NULL now that vault_name is
        # nullable — that is the correct outcome when the client
        # didn't supply a vault_name yet. The session token embeds
        # an empty string in that slot (honest: the vault has no
        # name until the user picks one). Every prompt and every UI
        # surface reads vault_name from the vaults row directly, so
        # the session-token slot is not the identity source.
        row_vault_name: Optional[str] = _new_vault_row["vault_name"]

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
        vault_name=row_vault_name or "",
        device_id=payload.device_id,
        client_label=normalize_client_label(request.headers.get("user-agent")),
    )

    # Single-active-device: the client that just proved knowledge of
    # the PIN gets trusted immediately, and every other device row on
    # this vault is revoked atomically. On a brand-new vault the
    # revoke-others UPDATE matches zero rows; on a signup that raced
    # against a leftover row (imports, staging seeds) any other
    # row is closed out. If no device_id was supplied we cannot
    # register anything — the /devices/register call from the client
    # will do it on next boot.
    if payload.device_id:
        try:
            from device_monitor import (
                ip_prefix_from,
                trust_current_and_revoke_others,
            )
            trust_current_and_revoke_others(
                vault_id=vault_id,
                device_id=payload.device_id,
                label=None,
                user_agent_brand=(
                    (request.headers.get("user-agent") or "")[:120] or None
                ),
                ip_prefix=ip_prefix_from(request),
            )
        except Exception:
            logger.exception(
                "[ZK-REGISTER-FINALIZE] single-active-device trust failed "
                "vault_id=%s (session issued anyway; client will retry via "
                "/devices/register)",
                vault_id,
            )

    return ZkRegisterFinalizeResponse(
        vault_id=vault_id,
        vault_handle=to_display(handle_bytes),
        session_token=token["token"],
    )


class ZkLoginInitRequest(BaseModel):
    vault_handle: str = Field(..., min_length=1, max_length=200)
    ke1: str = Field(..., min_length=1)
    # Optional client-derived 32-byte username_lookup_v1 (base64url).
    # Used as a fallback lookup when the vault_handle bytes don't
    # match a row (legacy random-handle accounts, or a future
    # normalization tweak), AND to opportunistically backfill legacy
    # NULL rows so subsequent duplicate registrations collide on the
    # partial UNIQUE index. Never persisted from the request itself.
    username_lookup: Optional[str] = Field(
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

    lookup_bytes: Optional[bytes] = None
    if payload.username_lookup is not None:
        lookup_bytes = _decode_lookup_v1_or_400(payload.username_lookup)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT vault_id, opaque_registration_record, vault_handle,
                   username_lookup_v1
            FROM vaults
            WHERE vault_handle = %s
            """,
            (handle_bytes,),
        )
        row = cur.fetchone()
        # Fallback: a client-supplied vault_handle that misses may
        # still name a real account if the client's derivation drifted
        # since registration (algorithm change, normalization tweak,
        # or a legacy random-handle account). Look it up by the
        # canonical-username lookup identifier instead.
        if row is None and lookup_bytes is not None:
            cur.execute(
                """
                SELECT vault_id, opaque_registration_record, vault_handle,
                       username_lookup_v1
                FROM vaults
                WHERE username_lookup_v1 = %s
                """,
                (lookup_bytes,),
            )
            row = cur.fetchone()
        # Conflict-detected opportunistic backfill: if the row we
        # matched carries NULL, we would like to populate it so a
        # subsequent duplicate registration for the same canonical
        # username collides on the partial UNIQUE index. But we MUST
        # first check whether the same lookup_bytes are already
        # claimed by a DIFFERENT row (two legacy accounts that would
        # both belong to the same canonical username). In that case
        # we refuse to backfill and write an audit row for operator
        # review. Login still proceeds — refusing backfill does not
        # affect the current unlock; it only defers uniqueness
        # enforcement until the operator resolves the conflict.
        if (
            row is not None
            and lookup_bytes is not None
            and row["username_lookup_v1"] is None
        ):
            cur.execute(
                """
                SELECT vault_id FROM vaults
                WHERE username_lookup_v1 = %s
                  AND vault_id <> %s
                LIMIT 1
                """,
                (lookup_bytes, row["vault_id"]),
            )
            conflict = cur.fetchone()
            if conflict is None:
                cur.execute(
                    """
                    UPDATE vaults
                       SET username_lookup_v1 = %s
                     WHERE vault_id = %s
                       AND username_lookup_v1 IS NULL
                    """,
                    (lookup_bytes, row["vault_id"]),
                )
                conn.commit()
            else:
                cur.execute(
                    """
                    INSERT INTO username_lookup_conflict_events (
                      login_vault_id, other_vault_id,
                      username_lookup_v1_fpr
                    )
                    VALUES (%s, %s, %s)
                    """,
                    (
                        row["vault_id"],
                        conflict["vault_id"],
                        _lookup_v1_fingerprint(lookup_bytes),
                    ),
                )
                conn.commit()
                logger.warning(
                    "[ZK-LOGIN-INIT] legacy backfill conflict pid=%d "
                    "login_vault_id=%s other_vault_id=%s lookup_fpr=%s",
                    os.getpid(),
                    row["vault_id"],
                    conflict["vault_id"],
                    _lookup_v1_fingerprint(lookup_bytes),
                )
    finally:
        conn.close()

    if row is None or row["opaque_registration_record"] is None:
        logger.info(
            "[ZK-LOGIN-INIT] no vault for handle "
            "pid=%d handle_fpr=%s lookup_fpr=%s",
            os.getpid(),
            _handle_fingerprint(handle_bytes),
            _lookup_v1_fingerprint(lookup_bytes)
            if lookup_bytes is not None else "-",
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
    # Opportunistic backfill of vault_name for accounts that predate
    # migration 0031_vault_name_repurpose. The user's typed name is
    # already stored client-side (that same string drives their
    # username_lookup_v1); if the vaults row still has NULL
    # vault_name — a leftover of the pre-0031 random-hex placeholder
    # having been NULLed by the backfill migration — we populate it
    # from this field on successful login, provided the value does
    # not collide with an existing vault_name. Never overwrites a
    # non-NULL value; conflicts are silently skipped and logged for
    # operator review, so the login itself still succeeds.
    vault_name: Optional[str] = Field(
        default=None, min_length=1, max_length=200,
    )


class ZkLoginFinalizeResponse(BaseModel):
    vault_id: str
    vault_handle: str
    session_token: str
    wrapped_mvk: str
    wrapped_sk_vault: str
    display_name_ciphertext: str
    # Server-authoritative user-chosen vault name (product-facing
    # identity for both vault and AI keeper). May be null on
    # accounts whose column was NULLed by migration 0031 and
    # haven't been backfilled yet — the client falls back to its
    # locally-typed value or the neutral "VaultAI" literal.
    vault_name: Optional[str] = None


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
                        display_name_ciphertext, vault_handle
            """,
            (row["vault_id"],),
        )
        vault_row = cur.fetchone()

        # Opportunistic vault_name backfill for existing accounts
        # whose column is still NULL after migration 0031. See the
        # comment on ZkLoginFinalizeRequest.vault_name. Silently
        # skipped on any conflict — login itself never fails on
        # this write.
        if (
            vault_row is not None
            and vault_row.get("vault_name") is None
            and payload.vault_name is not None
        ):
            from tools import normalize_vault_name
            candidate = normalize_vault_name(payload.vault_name)
            if candidate is not None:
                try:
                    cur.execute(
                        """
                        UPDATE vaults
                           SET vault_name = %s
                         WHERE vault_id = %s
                           AND vault_name IS NULL
                        RETURNING vault_name
                        """,
                        (candidate, row["vault_id"]),
                    )
                    updated = cur.fetchone()
                    if updated is not None:
                        vault_row["vault_name"] = updated["vault_name"]
                        logger.info(
                            "[ZK-LOGIN-FINALIZE] vault_name backfilled "
                            "vault_id=%s",
                            row["vault_id"],
                        )
                except pg_errors.UniqueViolation:
                    conn.rollback()
                    # Re-issue the successful-login UPDATE so the
                    # last_login_at bookkeeping is not lost, then
                    # log the collision. Login still succeeds.
                    cur.execute(
                        """
                        UPDATE vaults
                          SET last_login_at        = NOW(),
                              last_vault_unlock_at = NOW(),
                              last_any_activity_at = NOW(),
                              failed_pin_attempts  = 0
                          WHERE vault_id = %s
                        """,
                        (row["vault_id"],),
                    )
                    logger.warning(
                        "[ZK-LOGIN-FINALIZE] vault_name backfill conflict "
                        "vault_id=%s (name already claimed by another vault); "
                        "row keeps NULL until operator adjudicates",
                        row["vault_id"],
                    )
        conn.commit()
    finally:
        conn.close()

    if vault_row is None:
        raise HTTPException(
            status_code=401, detail=GENERIC_ZK_AUTH_ERROR,
        )

    token = issue_session_token(
        vault_id=str(vault_row["vault_id"]),
        # vault_name is nullable after migration 0031. The session
        # token embeds an empty string in that slot when the row
        # has no name yet; every prompt and every UI surface reads
        # the authoritative value from the vaults row on demand.
        vault_name=vault_row.get("vault_name") or "",
        device_id=payload.device_id,
        client_label=normalize_client_label(request.headers.get("user-agent")),
    )

    # Single-active-device: the client that just completed OPAQUE
    # login is the new sole trusted device on this vault. Trust the
    # current device_id and revoke every other row atomically. Any
    # device that was trusted before this login (including the one
    # the user just signed out of on another browser) now gets a
    # device_revoked response on its next protected request.
    if payload.device_id:
        try:
            from device_monitor import (
                ip_prefix_from,
                trust_current_and_revoke_others,
            )
            trust_current_and_revoke_others(
                vault_id=str(vault_row["vault_id"]),
                device_id=payload.device_id,
                label=None,
                user_agent_brand=(
                    (request.headers.get("user-agent") or "")[:120] or None
                ),
                ip_prefix=ip_prefix_from(request),
            )
        except Exception:
            logger.exception(
                "[ZK-LOGIN-FINALIZE] single-active-device trust failed "
                "vault_id=%s (session issued anyway; client will retry via "
                "/devices/register)",
                vault_row["vault_id"],
            )

    return ZkLoginFinalizeResponse(
        vault_id=str(vault_row["vault_id"]),
        vault_handle=to_display(bytes(vault_row["vault_handle"])),
        session_token=token["token"],
        wrapped_mvk=_b64url_encode(bytes(vault_row["wrapped_mvk"])),
        wrapped_sk_vault=_b64url_encode(bytes(vault_row["wrapped_sk_vault"])),
        display_name_ciphertext=_b64url_encode(
            bytes(vault_row["display_name_ciphertext"]),
        ),
        vault_name=vault_row.get("vault_name"),
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
