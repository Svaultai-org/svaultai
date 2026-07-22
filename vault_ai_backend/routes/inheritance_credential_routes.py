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
import threading
import time
from collections import OrderedDict
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


# Escrow-mutating operations are refused while the release flow is
# mid-cycle. Anything else — including a released link the owner
# wants to rotate or revoke — is permitted; the downstream row-
# existence checks still emit INH-CRED-005 (already saved) or
# INH-CRED-006 (no row to replace) for those specific cases.
_STATES_MID_ACCESS_REQUEST = frozenset({"cooldown_active"})


def _refuse_if_access_in_flight(link_row: dict) -> None:
    """State-aware credential-mutation gate.

    Reads ``beneficiary_links.pairing_state`` (the authoritative source
    of truth for the release flow — see the module docstring in
    ``inheritance_release_routes.py``).

    Historical note: the previous implementation refused whenever
    ``access_requested_at`` or ``cooldown_ends_at`` was non-null. Those
    columns are stamped by ``/inheritance/access/request`` and are only
    cleared by ``/access/cancel`` and ``/access/reject``. The forward
    path ``request → cooldown_active → approved → released`` leaves
    them populated forever, so any released link was permanently locked
    out of both ``/replace`` and ``/delete`` with INH-CRED-007 — even
    though the release flow is already complete. See
    ``test_inheritance_release_owner_mutations_2026_07_22.py`` for the
    regression test that pins this behavior.
    """
    pairing_state = (link_row.get("pairing_state") or "").strip()
    if pairing_state in _STATES_MID_ACCESS_REQUEST:
        raise inheritance_http_error(
            INHERR.CRED_ACCESS_IN_FLIGHT,
            log_details={
                "link_id": link_row["id"],
                "pairing_state": pairing_state,
            },
        )
    # Legacy transfer path signals via ``status``: refuse if the
    # link is anywhere past ``linked``. Kept for pre-Phase-2 rows
    # that never adopted a ``pairing_state`` value.
    legacy_status = (link_row.get("status") or "").strip()
    if legacy_status not in ("pairing_pending", "linked", ""):
        raise inheritance_http_error(
            INHERR.CRED_ACCESS_IN_FLIGHT,
            log_details={
                "link_id": link_row["id"],
                "pairing_state": pairing_state,
                "legacy_status": legacy_status,
            },
        )


# States from which a successful replace or delete transitions the
# link back to a fresh escrow-only lifecycle. Any of the release-
# flow timestamps left behind by /access/request would then render as
# a stale countdown in the owner UI, so we clear them along with the
# pairing_state transition. Mirrors what /access/cancel and
# /access/reject already do (see inheritance_release_routes.py).
_STATES_WITH_STALE_RELEASE_TIMESTAMPS = frozenset({
    "approved", "claimable", "released",
})


def _clear_release_timestamps_if_stale(
    cur, *, link_id: int, prior_state: str,
) -> None:
    """Best-effort cleanup of the ``access_requested_at`` /
    ``cooldown_ends_at`` / ``decision_at`` triple whenever a
    credential mutation moves the link back out of a post-request
    state. No-op for links that were already in the pre-request
    portion of the state machine."""
    if prior_state not in _STATES_WITH_STALE_RELEASE_TIMESTAMPS:
        return
    cur.execute(
        """
        UPDATE beneficiary_links
           SET access_requested_at = NULL,
               cooldown_ends_at    = NULL,
               decision_at         = NULL
         WHERE id = %s
        """,
        (link_id,),
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
        prior_state = (link.get("pairing_state") or "").strip()

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
        _clear_release_timestamps_if_stale(
            cur, link_id=payload.beneficiary_link_id,
            prior_state=prior_state,
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
        prior_state = (link.get("pairing_state") or "").strip()

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
        _clear_release_timestamps_if_stale(
            cur, link_id=payload.beneficiary_link_id,
            prior_state=prior_state,
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


# ---------------------------------------------------------------------
# Client-side diagnostic ingest
# ---------------------------------------------------------------------


# -- Dedup window ---
# One identical (vault_id, area, reference_code) triple is logged at
# most once per _DIAG_DEDUP_TTL_S. Subsequent identical reports in
# the window are silently accepted (still 200) but do NOT emit a
# ``[INH-CLIENT-DIAG]`` line. Prevents log spam if a client loops
# through the reveal path or a page auto-refreshes into the same
# failure. Values ARE NOT surfaced to the client; the response is
# identical whether the report was recorded or deduped.
_DIAG_DEDUP_TTL_S: float = 45.0
_DIAG_DEDUP_MAX_ENTRIES: int = 8192

_diag_dedup_lock = threading.Lock()
# LRU-ordered by insertion / touch time so we can bound the map
# under a keyspace attack (attacker cycling many fake references).
_diag_dedup_seen: "OrderedDict[tuple[str, str, str], float]" = OrderedDict()


def _diag_should_emit(vault_id: str, area: str, ref: str) -> bool:
    """Return True if this (vault, area, reference) triple was NOT
    logged within the last ``_DIAG_DEDUP_TTL_S`` seconds. On True,
    the caller is responsible for actually emitting the line; the
    dedup map is updated on the True path only so a would-be
    logger that decides to skip does not extend the window.

    Thread-safe. Bounded (max ``_DIAG_DEDUP_MAX_ENTRIES``); oldest
    entries are dropped LRU-style.
    """
    key = (vault_id, area, ref)
    now = time.monotonic()
    with _diag_dedup_lock:
        # Opportunistic sweep of expired entries. O(k) in the number
        # of entries scanned before we hit a fresh one.
        cutoff = now - _DIAG_DEDUP_TTL_S
        while _diag_dedup_seen:
            oldest_key = next(iter(_diag_dedup_seen))
            oldest_ts = _diag_dedup_seen[oldest_key]
            if oldest_ts < cutoff:
                _diag_dedup_seen.popitem(last=False)
            else:
                break

        existing = _diag_dedup_seen.get(key)
        if existing is not None and existing >= cutoff:
            # Within the dedup window — silently skip the emit.
            return False

        _diag_dedup_seen[key] = now
        _diag_dedup_seen.move_to_end(key)
        # LRU cap to guard against unbounded growth under a
        # unique-key attack.
        while len(_diag_dedup_seen) > _DIAG_DEDUP_MAX_ENTRIES:
            _diag_dedup_seen.popitem(last=False)
        return True


def _reset_diag_dedup_for_tests() -> None:
    """Test-only. Drops the entire dedup map so each test starts
    from a clean slate. Never call from non-test code."""
    with _diag_dedup_lock:
        _diag_dedup_seen.clear()


# Closed set of `area` tags the client can send. Any other value is
# rejected by Pydantic before this handler runs, so a caller cannot
# invent a new area name via the wire.
_DIAG_AREAS = frozenset({"reveal", "beneficiary_list"})

# Reference codes we currently classify on the client. Kept as a
# closed allow-list so a leaked value in a log line stays a well-
# known token (grep-friendly) and unknown strings get rejected.
_DIAG_REFERENCES = frozenset({
    "INH-RETRIEVE-003-AUTH",
    "INH-RETRIEVE-003-SHAPE",
    "INH-RETRIEVE-003-B64",
    "INH-RETRIEVE-003-KEYLEN",
    "INH-RETRIEVE-003-PAYLOAD",
    "INH-RETRIEVE-003-OTHER",
    "INH-LIST-MINE-ABORT",
    "INH-LIST-MINE-STALE",
})

_DIAG_CATEGORIES = frozenset({
    "auth", "shape", "b64", "keylen", "payload",
    "network_abort", "stale", "other",
})

# Closed allow-list of decrypt-pipeline stages the client can report.
# Every value MUST match a ``kRevealStage*`` constant declared in
# ``vault_ai_frontend/lib/services/inheritance_credentials.dart``.
# Added 2026-07-22: turns "INH-RETRIEVE-003-OTHER" from a black box
# into an operator-searchable stage label.
_DIAG_STAGES = frozenset({
    "eph_pub_decode",
    "beneficiary_sk_import",
    "ecdh",
    "hkdf",
    "wrapped_key_decode",
    "wrapping_nonce_decode",
    "cek_unwrap",
    "cek_len",
    "payload_decode",
    "payload_nonce_decode",
    "payload_decrypt",
    "json",
})


class ClientDiagnosticRequest(BaseModel):
    """Body schema for the client diagnostic endpoint.

    Every field is either an enum-like short string, an integer,
    or a bounded-length id. NO base64 / ciphertext / wrapped-key
    contents / nonces / tokens / PINs are accepted. A caller that
    tries to send a large opaque blob will fail Pydantic validation
    at ingest and never reach the log formatter.

    ``client_request_id`` is a client-generated UUID (base64url or
    hex, up to 64 chars). It lets an operator correlate a specific
    client-side failure against the nginx access-log entry for the
    same request.
    """

    area: str = Field(..., min_length=1, max_length=32)
    reference_code: str = Field(..., min_length=1, max_length=48)
    client_request_id: Optional[str] = Field(None, max_length=64)
    link_id: Optional[int] = Field(None, ge=1, le=2_147_483_647)
    exception_type: Optional[str] = Field(None, max_length=64)
    category: Optional[str] = Field(None, max_length=32)
    # 2026-07-22: pipeline stage at which the client-side decrypt
    # failed. Bounded + allowlist-enforced against ``_DIAG_STAGES``
    # so unknown / malformed values are rejected before logging.
    stage: Optional[str] = Field(None, max_length=32)
    crypto_version: Optional[int] = Field(None, ge=0, le=99)

    # Byte-length metadata. Upper bounds match the wire invariants
    # in the inheritance_credentials schema (see migration 0028).
    encrypted_payload_len: Optional[int] = Field(
        None, ge=0, le=1_000_000,
    )
    payload_nonce_len: Optional[int] = Field(None, ge=0, le=64)
    wrapped_key_len: Optional[int] = Field(None, ge=0, le=8_192)
    wrapping_ephemeral_pk_len: Optional[int] = Field(None, ge=0, le=256)
    wrapping_nonce_len: Optional[int] = Field(None, ge=0, le=64)
    active_sk_present: Optional[bool] = None
    active_sk_len: Optional[int] = Field(None, ge=0, le=1024)


class ClientDiagnosticResponse(BaseModel):
    ok: bool = True


def _sanitize_diag_field(value: Optional[str], *,
                          allowed: frozenset[str],
                          name: str) -> Optional[str]:
    """Reject unknown enum-like values. Turns a stray/unknown
    ``area`` or ``reference_code`` into a hard 400 so nothing
    weird ever reaches the log line."""
    if value is None:
        return None
    if value not in allowed:
        raise inheritance_http_error(
            INHERR.CRED_INVALID_PACKAGE,
            log_details={
                "reason": f"unknown_diag_{name}",
                "value_len": len(value),
            },
        )
    return value


@router.post(
    "/inheritance/client-diagnostic",
    response_model=ClientDiagnosticResponse,
)
def client_diagnostic(
    payload: ClientDiagnosticRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> ClientDiagnosticResponse:
    """Ingest a safe structured diagnostic from a beneficiary / owner
    device when an inheritance-scoped client-side operation fails.

    NO credential material, NO ciphertext, NO wrapped-key contents,
    NO nonces, NO tokens are accepted or logged. Only categorical
    enum values, integer byte lengths, an optional exception type
    name, and an optional client-generated request id.

    Emits a single ``[INH-CLIENT-DIAG]`` log line the operator can
    grep by ``reference_code`` or by ``client_request_id`` (which
    also appears in the nginx access log if the client set the
    ``X-Client-Request-Id`` header on the failed request).
    """
    area = _sanitize_diag_field(
        payload.area, allowed=_DIAG_AREAS, name="area",
    )
    ref = _sanitize_diag_field(
        payload.reference_code,
        allowed=_DIAG_REFERENCES, name="reference_code",
    )
    category = _sanitize_diag_field(
        payload.category, allowed=_DIAG_CATEGORIES, name="category",
    )
    stage = _sanitize_diag_field(
        payload.stage, allowed=_DIAG_STAGES, name="stage",
    )

    # Dedup one identical (vault_id, area, reference_code) triple per
    # 45s so a client stuck in a retry loop cannot spam production
    # logs. Response is identical whether we log or dedup — the
    # client cannot observe the difference.
    if not _diag_should_emit(
        vault_id=str(principal["vault_id"]),
        area=area or "",
        ref=ref or "",
    ):
        return ClientDiagnosticResponse()

    logger.warning(
        "[INH-CLIENT-DIAG] area=%s ref=%s stage=%s cri=%s link_id=%s "
        "vault_tail=%s exc_type=%s category=%s crypto_v=%s "
        "payload_len=%s nonce_len=%s wrapped_len=%s "
        "eph_pk_len=%s wrap_nonce_len=%s "
        "sk_present=%s sk_len=%s",
        area, ref, stage, payload.client_request_id,
        payload.link_id,
        str(principal["vault_id"])[-6:],
        payload.exception_type, category, payload.crypto_version,
        payload.encrypted_payload_len, payload.payload_nonce_len,
        payload.wrapped_key_len, payload.wrapping_ephemeral_pk_len,
        payload.wrapping_nonce_len,
        payload.active_sk_present, payload.active_sk_len,
    )
    return ClientDiagnosticResponse()
