"""Inheritance credential escrow — Phase 1 backend surface.

Endpoints the owner uses to save, replace, or delete an encrypted
copy of the VaultAI credentials that a paired beneficiary will
inherit access to. **No decryption ever happens on the server.**
Every byte of credential material stays wrapped end-to-end: the
owner's client generates the CEK, encrypts the JSON payload, and
wraps the CEK for the beneficiary's ``pk_vault_public`` via
X25519-ECDH → HKDF-SHA256 → AES-GCM-256. The server only records
opaque byte strings and their state.

Phase 1 does NOT contain the request / approve / cooldown / release
endpoints — those land in Phase 2 alongside the beneficiary-side
read path. Until then the existing ``/beneficiary/request-transfer``
family keeps working unchanged (see main.py).

Surface
-------

* ``POST /inheritance/credentials/save``
* ``POST /inheritance/credentials/replace``
* ``POST /inheritance/credentials/delete``
* ``GET  /inheritance/credentials/status?link_id=…``
* ``GET  /inheritance/beneficiary/{link_id}/pubkey``

Every endpoint verifies (a) the session token is valid, (b) the
authenticated vault owns the ``beneficiary_links`` row, (c) the
row is in a state that permits the transition, and (d) that no
active access request is in flight (Phase 2 gate — read-only for
now).

Wire format
-----------

All byte-valued request/response fields are base64url with no
padding. Fixed lengths at rest:

    payload_nonce            = 12 bytes
    wrapping_ephemeral_pk    = 32 bytes  (X25519 public key)
    wrapping_nonce           = 12 bytes
    wrapped_key              32..4096 bytes
    encrypted_payload        32..65536 bytes

Length invariants are echoed at the SQL layer (see migration 0028
``inheritance_credentials_lengths_ck``) so a caller cannot bypass
them by talking to the DB.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal, verify_session_token
from inheritance_error_codes import INHERR, inheritance_http_error
from vault_core import get_db


logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------
# Byte-length invariants
# ---------------------------------------------------------------------

_NONCE_BYTES = 12
_X25519_PUB_BYTES = 32
_ENCRYPTED_PAYLOAD_MIN = 32
_ENCRYPTED_PAYLOAD_MAX = 64 * 1024
_WRAPPED_KEY_MIN = 32
_WRAPPED_KEY_MAX = 4 * 1024

_SUPPORTED_CRYPTO_VERSION = 1


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _b64url_decode_bytes(
    text: str,
    *,
    exact: Optional[int] = None,
    lo: Optional[int] = None,
    hi: Optional[int] = None,
) -> bytes:
    """Decode a base64url string, then check length. On malformed
    input or length-mismatch the operator-safe INH-CRED-004 code is
    surfaced to the caller — never the underlying parser exception.
    """
    if not isinstance(text, str) or not text:
        raise inheritance_http_error(INHERR.CRED_INVALID_PACKAGE)
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise inheritance_http_error(INHERR.CRED_INVALID_PACKAGE)
    if exact is not None and len(raw) != exact:
        raise inheritance_http_error(INHERR.CRED_INVALID_PACKAGE)
    if lo is not None and len(raw) < lo:
        raise inheritance_http_error(INHERR.CRED_INVALID_PACKAGE)
    if hi is not None and len(raw) > hi:
        raise inheritance_http_error(INHERR.CRED_INVALID_PACKAGE)
    return raw


def _b64url_encode_bytes(raw: bytes) -> str:
    """base64url without padding — matches the frontend contract."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------


class _CredentialPackageBase(BaseModel):
    beneficiary_link_id: int = Field(..., ge=1)
    crypto_version: int = Field(..., ge=1, le=1)
    encrypted_payload: str = Field(..., min_length=1)
    payload_nonce: str = Field(..., min_length=1)
    wrapped_key: str = Field(..., min_length=1)
    wrapping_ephemeral_pk: str = Field(..., min_length=1)
    wrapping_nonce: str = Field(..., min_length=1)

    def __repr__(self) -> str:
        # Never render the ciphertext in a log line.
        return (
            f"<CredentialPackage link={self.beneficiary_link_id} "
            f"crypto_version={self.crypto_version}>"
        )


class SaveCredentialPackageRequest(_CredentialPackageBase):
    pass


class ReplaceCredentialPackageRequest(_CredentialPackageBase):
    pass


class DeleteCredentialPackageRequest(BaseModel):
    beneficiary_link_id: int = Field(..., ge=1)


class CredentialStatusResponse(BaseModel):
    beneficiary_link_id: int
    credentials_saved: bool
    crypto_version: Optional[int] = None
    updated_at: Optional[str] = None
    # The compact state exposed to the client. In Phase 1 the only
    # observable states are 'paired_no_credentials' and
    # 'credentials_saved'; Phase 2 introduces the release states.
    pairing_state: str


class BeneficiaryPubKeyResponse(BaseModel):
    beneficiary_link_id: int
    pk_vault_public_b64url: str
    crypto_version_hint: int = _SUPPORTED_CRYPTO_VERSION


# ---------------------------------------------------------------------
# Shared query helpers
# ---------------------------------------------------------------------


def _fetch_owned_link(
    cur, *, link_id: int, owner_vault_id: str, for_update: bool
) -> dict:
    """Return the beneficiary_links row (owner-scoped) or raise the
    operator-safe ``INH-CRED-001`` if it does not belong to the
    caller. The lookup uses SELECT ... FOR UPDATE when the caller is
    about to mutate the row so the state-machine transition is
    serialized."""
    suffix = "FOR UPDATE" if for_update else ""
    cur.execute(
        f"""
        SELECT id, passer_vault_id, beneficiary_vault_id, status,
               pairing_state, access_requested_at, cooldown_ends_at
          FROM beneficiary_links
         WHERE id = %s
           AND passer_vault_id = %s
        {suffix}
        """,
        (link_id, owner_vault_id),
    )
    row = cur.fetchone()
    if not row:
        raise inheritance_http_error(
            INHERR.CRED_LINK_NOT_FOUND,
            log_details={
                "link_id": link_id,
                "owner_tail": str(owner_vault_id)[-6:],
            },
        )
    return row


def _fetch_beneficiary_pk(cur, *, beneficiary_vault_id) -> bytes:
    cur.execute(
        "SELECT pk_vault_public FROM vaults WHERE vault_id = %s",
        (beneficiary_vault_id,),
    )
    row = cur.fetchone()
    if not row or not row.get("pk_vault_public"):
        raise inheritance_http_error(
            INHERR.CRED_BENEFICIARY_NO_ZK_PUBLIC_KEY,
            log_details={
                "beneficiary_tail": str(beneficiary_vault_id)[-6:],
            },
        )
    pk = bytes(row["pk_vault_public"])
    if len(pk) != _X25519_PUB_BYTES:
        # A stored key of the wrong length is a data-integrity bug,
        # not a client mistake — surface as INH-CRED-003 to avoid
        # leaking internals.
        raise inheritance_http_error(
            INHERR.CRED_BENEFICIARY_NO_ZK_PUBLIC_KEY,
            log_details={"pk_len": len(pk)},
        )
    return pk


def _refuse_if_access_in_flight(link_row: dict) -> None:
    """Phase 1 conservative gate: if the row is anywhere in the
    request/approve/cooldown pipeline, credentials must not be
    mutated. Phase 2 will refine this."""
    active = link_row.get("access_requested_at") is not None or (
        link_row.get("cooldown_ends_at") is not None
    )
    if active:
        raise inheritance_http_error(
            INHERR.CRED_ACCESS_IN_FLIGHT,
            log_details={"link_id": link_row["id"]},
        )
    # Legacy transfer path signals via ``status``: refuse if the
    # link is anywhere past ``linked``.
    legacy_status = (link_row.get("status") or "").strip()
    if legacy_status not in ("pairing_pending", "linked", ""):
        raise inheritance_http_error(
            INHERR.CRED_ACCESS_IN_FLIGHT,
            log_details={
                "link_id": link_row["id"],
                "legacy_status": legacy_status,
            },
        )


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------


@router.get(
    "/inheritance/beneficiary/{link_id}/pubkey",
    response_model=BeneficiaryPubKeyResponse,
)
def get_beneficiary_public_key(
    link_id: int,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> BeneficiaryPubKeyResponse:
    """Owner-side lookup returning the beneficiary's stored X25519
    public key so the owner's client can wrap the CEK before saving.

    The beneficiary must already have completed pairing on their
    side (``beneficiary_vault_id`` populated on the link) AND their
    vault must be ZK-adopted (``pk_vault_public`` populated).
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_owned_link(
            cur, link_id=link_id,
            owner_vault_id=principal["vault_id"],
            for_update=False,
        )
        if not link.get("beneficiary_vault_id"):
            raise inheritance_http_error(
                INHERR.CRED_BENEFICIARY_NOT_LINKED,
                log_details={"link_id": link_id},
            )
        pk = _fetch_beneficiary_pk(
            cur, beneficiary_vault_id=link["beneficiary_vault_id"],
        )
    finally:
        conn.close()
    return BeneficiaryPubKeyResponse(
        beneficiary_link_id=link_id,
        pk_vault_public_b64url=_b64url_encode_bytes(pk),
    )


def _insert_credential_row(
    cur, *, link_id: int, owner_vault_id: str,
    crypto_version: int,
    encrypted_payload: bytes, payload_nonce: bytes,
    wrapped_key: bytes, wrapping_ephemeral_pk: bytes,
    wrapping_nonce: bytes,
) -> None:
    cur.execute(
        """
        INSERT INTO inheritance_credentials (
            beneficiary_link_id, owner_vault_id,
            crypto_version,
            encrypted_payload, payload_nonce,
            wrapped_key, wrapping_ephemeral_pk, wrapping_nonce,
            state, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                'credentials_saved', NOW(), NOW())
        """,
        (
            link_id, owner_vault_id, crypto_version,
            encrypted_payload, payload_nonce,
            wrapped_key, wrapping_ephemeral_pk, wrapping_nonce,
        ),
    )
    cur.execute(
        """
        UPDATE beneficiary_links
           SET pairing_state = 'credentials_saved'
         WHERE id = %s
        """,
        (link_id,),
    )


@router.post(
    "/inheritance/credentials/save",
    response_model=CredentialStatusResponse,
)
def save_credentials(
    payload: SaveCredentialPackageRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> CredentialStatusResponse:
    """Owner-side save. Refuses if credentials are already saved for
    this link (use /replace) or if an access request is in flight."""
    if payload.crypto_version != _SUPPORTED_CRYPTO_VERSION:
        raise inheritance_http_error(
            INHERR.CRED_INVALID_PACKAGE,
            log_details={
                "reason": "unsupported_crypto_version",
                "sent": payload.crypto_version,
            },
        )
    encrypted = _b64url_decode_bytes(
        payload.encrypted_payload,
        lo=_ENCRYPTED_PAYLOAD_MIN, hi=_ENCRYPTED_PAYLOAD_MAX,
    )
    payload_nonce = _b64url_decode_bytes(
        payload.payload_nonce, exact=_NONCE_BYTES,
    )
    wrapped_key = _b64url_decode_bytes(
        payload.wrapped_key,
        lo=_WRAPPED_KEY_MIN, hi=_WRAPPED_KEY_MAX,
    )
    eph_pk = _b64url_decode_bytes(
        payload.wrapping_ephemeral_pk, exact=_X25519_PUB_BYTES,
    )
    wrap_nonce = _b64url_decode_bytes(
        payload.wrapping_nonce, exact=_NONCE_BYTES,
    )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_owned_link(
            cur, link_id=payload.beneficiary_link_id,
            owner_vault_id=principal["vault_id"], for_update=True,
        )
        if not link.get("beneficiary_vault_id"):
            raise inheritance_http_error(
                INHERR.CRED_BENEFICIARY_NOT_LINKED,
                log_details={"link_id": payload.beneficiary_link_id},
            )
        _refuse_if_access_in_flight(link)

        cur.execute(
            """
            SELECT 1 FROM inheritance_credentials
             WHERE beneficiary_link_id = %s
               AND deleted_at IS NULL
             LIMIT 1
            """,
            (payload.beneficiary_link_id,),
        )
        if cur.fetchone():
            raise inheritance_http_error(
                INHERR.CRED_ALREADY_SAVED,
                log_details={"link_id": payload.beneficiary_link_id},
            )

        _insert_credential_row(
            cur, link_id=payload.beneficiary_link_id,
            owner_vault_id=principal["vault_id"],
            crypto_version=payload.crypto_version,
            encrypted_payload=encrypted,
            payload_nonce=payload_nonce,
            wrapped_key=wrapped_key,
            wrapping_ephemeral_pk=eph_pk,
            wrapping_nonce=wrap_nonce,
        )
        conn.commit()
    finally:
        conn.close()

    return CredentialStatusResponse(
        beneficiary_link_id=payload.beneficiary_link_id,
        credentials_saved=True,
        crypto_version=payload.crypto_version,
        updated_at=None,  # returned by /status
        pairing_state="credentials_saved",
    )


@router.post(
    "/inheritance/credentials/replace",
    response_model=CredentialStatusResponse,
)
def replace_credentials(
    payload: ReplaceCredentialPackageRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> CredentialStatusResponse:
    """Owner-side replace. Refuses if no credentials are saved or if
    an access request is in flight. Soft-deletes the previous row so
    audit history is preserved."""
    if payload.crypto_version != _SUPPORTED_CRYPTO_VERSION:
        raise inheritance_http_error(
            INHERR.CRED_INVALID_PACKAGE,
            log_details={
                "reason": "unsupported_crypto_version",
                "sent": payload.crypto_version,
            },
        )
    encrypted = _b64url_decode_bytes(
        payload.encrypted_payload,
        lo=_ENCRYPTED_PAYLOAD_MIN, hi=_ENCRYPTED_PAYLOAD_MAX,
    )
    payload_nonce = _b64url_decode_bytes(
        payload.payload_nonce, exact=_NONCE_BYTES,
    )
    wrapped_key = _b64url_decode_bytes(
        payload.wrapped_key,
        lo=_WRAPPED_KEY_MIN, hi=_WRAPPED_KEY_MAX,
    )
    eph_pk = _b64url_decode_bytes(
        payload.wrapping_ephemeral_pk, exact=_X25519_PUB_BYTES,
    )
    wrap_nonce = _b64url_decode_bytes(
        payload.wrapping_nonce, exact=_NONCE_BYTES,
    )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_owned_link(
            cur, link_id=payload.beneficiary_link_id,
            owner_vault_id=principal["vault_id"], for_update=True,
        )
        if not link.get("beneficiary_vault_id"):
            raise inheritance_http_error(
                INHERR.CRED_BENEFICIARY_NOT_LINKED,
                log_details={"link_id": payload.beneficiary_link_id},
            )
        _refuse_if_access_in_flight(link)

        cur.execute(
            """
            UPDATE inheritance_credentials
               SET deleted_at = NOW()
             WHERE beneficiary_link_id = %s
               AND deleted_at IS NULL
            """,
            (payload.beneficiary_link_id,),
        )
        if cur.rowcount != 1:
            # Nothing to replace — direct the user to save instead.
            raise inheritance_http_error(
                INHERR.CRED_NOT_SAVED,
                log_details={"link_id": payload.beneficiary_link_id},
            )
        _insert_credential_row(
            cur, link_id=payload.beneficiary_link_id,
            owner_vault_id=principal["vault_id"],
            crypto_version=payload.crypto_version,
            encrypted_payload=encrypted,
            payload_nonce=payload_nonce,
            wrapped_key=wrapped_key,
            wrapping_ephemeral_pk=eph_pk,
            wrapping_nonce=wrap_nonce,
        )
        conn.commit()
    finally:
        conn.close()

    return CredentialStatusResponse(
        beneficiary_link_id=payload.beneficiary_link_id,
        credentials_saved=True,
        crypto_version=payload.crypto_version,
        updated_at=None,
        pairing_state="credentials_saved",
    )


@router.post(
    "/inheritance/credentials/delete",
    response_model=CredentialStatusResponse,
)
def delete_credentials(
    payload: DeleteCredentialPackageRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> CredentialStatusResponse:
    """Owner-side delete. Soft-deletes the credential row and moves
    the link back to ``paired_no_credentials``."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_owned_link(
            cur, link_id=payload.beneficiary_link_id,
            owner_vault_id=principal["vault_id"], for_update=True,
        )
        _refuse_if_access_in_flight(link)

        cur.execute(
            """
            UPDATE inheritance_credentials
               SET deleted_at = NOW()
             WHERE beneficiary_link_id = %s
               AND deleted_at IS NULL
            """,
            (payload.beneficiary_link_id,),
        )
        cur.execute(
            """
            UPDATE beneficiary_links
               SET pairing_state = 'paired_no_credentials'
             WHERE id = %s
            """,
            (payload.beneficiary_link_id,),
        )
        conn.commit()
    finally:
        conn.close()

    return CredentialStatusResponse(
        beneficiary_link_id=payload.beneficiary_link_id,
        credentials_saved=False,
        crypto_version=None,
        updated_at=None,
        pairing_state="paired_no_credentials",
    )


@router.get(
    "/inheritance/credentials/status",
    response_model=CredentialStatusResponse,
)
def credential_status(
    link_id: int = Query(..., ge=1),
    principal: SessionPrincipal = Depends(verify_session_token),
) -> CredentialStatusResponse:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_owned_link(
            cur, link_id=link_id,
            owner_vault_id=principal["vault_id"], for_update=False,
        )
        cur.execute(
            """
            SELECT crypto_version, updated_at
              FROM inheritance_credentials
             WHERE beneficiary_link_id = %s
               AND deleted_at IS NULL
             LIMIT 1
            """,
            (link_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row:
        return CredentialStatusResponse(
            beneficiary_link_id=link_id,
            credentials_saved=True,
            crypto_version=int(row["crypto_version"]),
            updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
            pairing_state=link.get("pairing_state") or "credentials_saved",
        )
    return CredentialStatusResponse(
        beneficiary_link_id=link_id,
        credentials_saved=False,
        pairing_state=link.get("pairing_state") or "paired_no_credentials",
    )
