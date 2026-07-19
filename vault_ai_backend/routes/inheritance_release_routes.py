"""Inheritance release flow — Phase 2 backend surface.

Endpoints
---------

Beneficiary-facing:
  * POST /inheritance/access/request
  * POST /inheritance/access/cancel
  * POST /inheritance/access/claim
  * GET  /inheritance/credentials/retrieve?link_id=…
  * POST /inheritance/device/authorize
  * POST /inheritance/device/consume

Owner-facing:
  * POST /inheritance/access/approve
  * POST /inheritance/access/reject

Either side:
  * GET  /inheritance/access/status?link_id=…

State machine (authoritative source: ``beneficiary_links.pairing_state``)
------------------------------------------------------------------------

    credentials_saved
        │  beneficiary /request
        ▼
    cooldown_active   ── owner /approve ──▶ approved   ── /retrieve ──▶ released
        │                                     │
        │  timer expires                      │
        ▼                                     │
    claimable         ── beneficiary /claim ──▶ released
        │
        │  owner /reject   → credentials_saved      (allow re-request)
        │  beneficiary /cancel → credentials_saved  (allow re-request)
        │  owner delete/revoke → revoked            (terminal, package gone)

Every mutation:
  * runs inside a single DB transaction,
  * takes ``SELECT ... FOR UPDATE`` on the link row so concurrent
    approve/reject/claim serialize deterministically,
  * checks caller identity and role (owner vs beneficiary),
  * writes ``pairing_state`` first, then mirrors on the escrow row.

Cooldown configuration:
    VAULTAI_INHERITANCE_COOLDOWN_DAYS   int, default 30
    VAULTAI_INHERITANCE_DEVICE_AUTH_TTL_HOURS  int, default 72

Zero-knowledge invariant
------------------------

The server never sees decrypted credential bytes. ``retrieve``
returns the same wrapped package the owner uploaded in Phase 1 —
``encrypted_payload || payload_nonce || wrapped_key ||
wrapping_ephemeral_pk || wrapping_nonce`` — plus the
``crypto_version``. Decryption happens only in the beneficiary's
client using the ZK vault's private X25519 key.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal, verify_session_token
from inheritance_error_codes import INHERR, inheritance_http_error
from vault_core import get_db


logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------


def _cooldown_days() -> int:
    """Environment override. Default is 30 days.

    Tests set this to a small value (or 0) to exercise the boundary
    without wall-clock waits. Only positive values are accepted; a
    zero/negative override is treated as an immediate-cooldown flag
    (``cooldown_ends_at = access_requested_at``) so timing tests
    can hit the exact boundary condition.
    """
    raw = os.getenv("VAULTAI_INHERITANCE_COOLDOWN_DAYS", "").strip()
    if not raw:
        return 30
    try:
        v = int(raw)
    except ValueError:
        return 30
    return max(v, 0)


def _cooldown_delta() -> timedelta:
    days = _cooldown_days()
    if days <= 0:
        # Test override: cooldown_ends_at == access_requested_at,
        # so /claim succeeds on the same request that /requested.
        return timedelta(seconds=0)
    return timedelta(days=days)


def _device_auth_ttl() -> timedelta:
    raw = os.getenv(
        "VAULTAI_INHERITANCE_DEVICE_AUTH_TTL_HOURS", "",
    ).strip()
    hours = 72
    if raw:
        try:
            hours = max(int(raw), 1)
        except ValueError:
            pass
    return timedelta(hours=hours)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


_STATES_ALLOWED_TO_REQUEST = {"credentials_saved"}
_STATES_WITH_ACTIVE_REQUEST = {"cooldown_active", "claimable"}
_STATES_RELEASE_READABLE = {"approved", "claimable", "released"}
_STATES_TERMINAL = {"released", "revoked"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if v else None


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _fetch_link_for_update(
    cur, *, link_id: int,
) -> Optional[dict]:
    """Return the link row locked for update, or None if it doesn't
    exist. Caller decides which side (owner vs beneficiary) matches
    the caller's principal and raises the right error code."""
    cur.execute(
        """
        SELECT id,
               passer_vault_id,
               beneficiary_vault_id,
               status,
               COALESCE(pairing_state, 'paired_no_credentials') AS pairing_state,
               access_requested_at,
               cooldown_ends_at,
               decision_at
          FROM beneficiary_links
         WHERE id = %s
        FOR UPDATE
        """,
        (link_id,),
    )
    return cur.fetchone()


def _write_state(cur, *, link_id: int, new_state: str,
                 timestamps: Optional[dict] = None) -> None:
    """Update pairing_state on beneficiary_links AND mirror on the
    escrow row (if one exists). Any explicit timestamp updates are
    applied inline so the whole transition is a single SQL round-trip
    per table."""
    fields = ["pairing_state = %s"]
    params: list[Any] = [new_state]
    for col, val in (timestamps or {}).items():
        fields.append(f"{col} = %s")
        params.append(val)
    params.append(link_id)
    cur.execute(
        f"UPDATE beneficiary_links SET {', '.join(fields)} WHERE id = %s",
        tuple(params),
    )
    # Mirror on the escrow row (best-effort; the link is authoritative).
    cur.execute(
        """
        UPDATE inheritance_credentials
           SET state = %s,
               updated_at = NOW()
         WHERE beneficiary_link_id = %s
           AND deleted_at IS NULL
        """,
        (new_state, link_id),
    )


def _load_escrow_package(
    cur, *, link_id: int, expect_state: Optional[set] = None,
) -> dict:
    cur.execute(
        """
        SELECT id, crypto_version,
               encrypted_payload, payload_nonce,
               wrapped_key, wrapping_ephemeral_pk, wrapping_nonce,
               released_at, state
          FROM inheritance_credentials
         WHERE beneficiary_link_id = %s
           AND deleted_at IS NULL
         LIMIT 1
        """,
        (link_id,),
    )
    row = cur.fetchone()
    if not row:
        raise inheritance_http_error(
            INHERR.RETRIEVE_MISSING_PACKAGE,
            log_details={"link_id": link_id},
        )
    if expect_state and row["state"] not in expect_state:
        raise inheritance_http_error(
            INHERR.RETRIEVE_NOT_RELEASED,
            log_details={
                "link_id": link_id,
                "state": row["state"],
            },
        )
    return row


def _require_owner(link: dict, principal: SessionPrincipal) -> None:
    if str(link["passer_vault_id"]) != str(principal["vault_id"]):
        raise inheritance_http_error(
            INHERR.ACCESS_NOT_OWNER,
            log_details={
                "link_id": link["id"],
                "caller_tail": str(principal["vault_id"])[-6:],
            },
        )


def _require_beneficiary(link: dict, principal: SessionPrincipal) -> None:
    beneficiary_vault_id = link.get("beneficiary_vault_id")
    if not beneficiary_vault_id or (
        str(beneficiary_vault_id) != str(principal["vault_id"])
    ):
        raise inheritance_http_error(
            INHERR.ACCESS_NOT_A_BENEFICIARY,
            log_details={
                "link_id": link["id"],
                "caller_tail": str(principal["vault_id"])[-6:],
            },
        )


def _escrow_state_or_no_credentials(link: dict) -> str:
    return link.get("pairing_state") or "paired_no_credentials"


# ---------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------


def _notify(vault_id: str, kind: str, *,
            title: Optional[str] = None,
            body: Optional[str] = None,
            metadata: Optional[dict] = None) -> None:
    """Best-effort in-app notification via the existing shell.

    Failure is swallowed so a transient notification error never
    blocks a state transition. Backend logs the failure without
    exposing user text.
    """
    try:
        from main import _create_notification  # local import: avoid cycle
        _create_notification(
            vault_id, kind,
            title or "", body or "",
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001
        logger.warning("[INH] notification %s failed (swallowed)", kind)


_NOTIFY_KIND_ACCESS_REQUESTED = "inheritance_access_requested"
_NOTIFY_KIND_APPROVED = "inheritance_approved"
_NOTIFY_KIND_REJECTED = "inheritance_rejected"
_NOTIFY_KIND_CANCELLED = "inheritance_cancelled"
_NOTIFY_KIND_CLAIMED = "inheritance_claimed"
_NOTIFY_KIND_RELEASED = "inheritance_released"


# ---------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------


class _LinkOnlyBody(BaseModel):
    beneficiary_link_id: int = Field(..., ge=1)


class AccessRequestBody(_LinkOnlyBody):
    pass


class AccessCancelBody(_LinkOnlyBody):
    pass


class AccessApproveBody(_LinkOnlyBody):
    pass


class AccessRejectBody(_LinkOnlyBody):
    pass


class AccessClaimBody(_LinkOnlyBody):
    pass


class AccessStatusResponse(BaseModel):
    beneficiary_link_id: int
    pairing_state: str
    role: str  # "owner" or "beneficiary" for the caller
    access_requested_at: Optional[str]
    cooldown_ends_at: Optional[str]
    decision_at: Optional[str]
    server_now: str


class DeviceAuthorizeResponse(BaseModel):
    beneficiary_link_id: int
    token: str  # one-time, base64url no padding, ~32 bytes
    expires_at: str


class DeviceConsumeBody(BaseModel):
    token: str = Field(..., min_length=1)


class DeviceConsumeResponse(BaseModel):
    consumed: bool
    inherited_owner_vault_id: str


class RetrievedCredentialPackage(BaseModel):
    beneficiary_link_id: int
    crypto_version: int
    encrypted_payload: str
    payload_nonce: str
    wrapped_key: str
    wrapping_ephemeral_pk: str
    wrapping_nonce: str
    released_at: Optional[str]
    pairing_state: str


# ---------------------------------------------------------------------
# Endpoints — access request lifecycle
# ---------------------------------------------------------------------


@router.post("/inheritance/access/request", response_model=AccessStatusResponse)
def request_access(
    body: AccessRequestBody,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> AccessStatusResponse:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_link_for_update(cur, link_id=body.beneficiary_link_id)
        if not link:
            raise inheritance_http_error(
                INHERR.ACCESS_NOT_A_BENEFICIARY,
                log_details={"link_id": body.beneficiary_link_id},
            )
        _require_beneficiary(link, principal)

        state = _escrow_state_or_no_credentials(link)
        if state in _STATES_TERMINAL and state == "revoked":
            raise inheritance_http_error(INHERR.ACCESS_REVOKED)
        if state != "credentials_saved":
            if state in _STATES_WITH_ACTIVE_REQUEST:
                raise inheritance_http_error(INHERR.ACCESS_ALREADY_REQUESTED)
            raise inheritance_http_error(INHERR.ACCESS_NO_CREDENTIALS)

        # Verify the escrow package exists and belongs to this link.
        _load_escrow_package(cur, link_id=body.beneficiary_link_id)

        now = _now_utc()
        ends = now + _cooldown_delta()
        _write_state(
            cur, link_id=body.beneficiary_link_id,
            new_state="cooldown_active",
            timestamps={
                "access_requested_at": now,
                "cooldown_ends_at": ends,
                "decision_at": None,
            },
        )
        owner_vault = link["passer_vault_id"]
        conn.commit()
    finally:
        conn.close()

    _notify(
        str(owner_vault),
        _NOTIFY_KIND_ACCESS_REQUESTED,
        title="Inheritance: access requested",
        body="A beneficiary has requested access to the credentials "
             "you saved for them.",
        metadata={"beneficiary_link_id": body.beneficiary_link_id},
    )

    return AccessStatusResponse(
        beneficiary_link_id=body.beneficiary_link_id,
        pairing_state="cooldown_active",
        role="beneficiary",
        access_requested_at=_iso(now),
        cooldown_ends_at=_iso(ends),
        decision_at=None,
        server_now=_iso(now) or "",
    )


@router.post("/inheritance/access/cancel", response_model=AccessStatusResponse)
def cancel_access(
    body: AccessCancelBody,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> AccessStatusResponse:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_link_for_update(cur, link_id=body.beneficiary_link_id)
        if not link:
            raise inheritance_http_error(
                INHERR.ACCESS_NOT_A_BENEFICIARY,
                log_details={"link_id": body.beneficiary_link_id},
            )
        _require_beneficiary(link, principal)

        state = _escrow_state_or_no_credentials(link)
        if state not in _STATES_WITH_ACTIVE_REQUEST:
            raise inheritance_http_error(INHERR.ACCESS_NO_ACTIVE_REQUEST)

        _write_state(
            cur, link_id=body.beneficiary_link_id,
            new_state="credentials_saved",
            timestamps={
                "access_requested_at": None,
                "cooldown_ends_at": None,
                "decision_at": None,
            },
        )
        _revoke_active_device_authorizations(cur, link_id=body.beneficiary_link_id)
        owner_vault = link["passer_vault_id"]
        conn.commit()
    finally:
        conn.close()

    _notify(
        str(owner_vault), _NOTIFY_KIND_CANCELLED,
        title="Inheritance: request cancelled",
        body="The beneficiary cancelled their access request.",
        metadata={"beneficiary_link_id": body.beneficiary_link_id},
    )
    now = _now_utc()
    return AccessStatusResponse(
        beneficiary_link_id=body.beneficiary_link_id,
        pairing_state="credentials_saved", role="beneficiary",
        access_requested_at=None, cooldown_ends_at=None,
        decision_at=None, server_now=_iso(now) or "",
    )


@router.post("/inheritance/access/approve", response_model=AccessStatusResponse)
def approve_access(
    body: AccessApproveBody,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> AccessStatusResponse:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_link_for_update(cur, link_id=body.beneficiary_link_id)
        if not link:
            raise inheritance_http_error(
                INHERR.ACCESS_NOT_OWNER,
                log_details={"link_id": body.beneficiary_link_id},
            )
        _require_owner(link, principal)

        state = _escrow_state_or_no_credentials(link)
        if state not in _STATES_WITH_ACTIVE_REQUEST:
            raise inheritance_http_error(INHERR.ACCESS_NO_ACTIVE_REQUEST)

        now = _now_utc()
        _write_state(
            cur, link_id=body.beneficiary_link_id,
            new_state="approved",
            timestamps={"decision_at": now},
        )
        beneficiary_vault = link["beneficiary_vault_id"]
        conn.commit()
    finally:
        conn.close()

    if beneficiary_vault:
        _notify(
            str(beneficiary_vault), _NOTIFY_KIND_APPROVED,
            title="Inheritance: approved",
            body="The owner approved your access request.",
            metadata={"beneficiary_link_id": body.beneficiary_link_id},
        )
    return AccessStatusResponse(
        beneficiary_link_id=body.beneficiary_link_id,
        pairing_state="approved", role="owner",
        access_requested_at=_iso(link.get("access_requested_at")),
        cooldown_ends_at=_iso(link.get("cooldown_ends_at")),
        decision_at=_iso(now), server_now=_iso(now) or "",
    )


@router.post("/inheritance/access/reject", response_model=AccessStatusResponse)
def reject_access(
    body: AccessRejectBody,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> AccessStatusResponse:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_link_for_update(cur, link_id=body.beneficiary_link_id)
        if not link:
            raise inheritance_http_error(
                INHERR.ACCESS_NOT_OWNER,
                log_details={"link_id": body.beneficiary_link_id},
            )
        _require_owner(link, principal)

        state = _escrow_state_or_no_credentials(link)
        if state not in _STATES_WITH_ACTIVE_REQUEST:
            raise inheritance_http_error(INHERR.ACCESS_NO_ACTIVE_REQUEST)

        now = _now_utc()
        _write_state(
            cur, link_id=body.beneficiary_link_id,
            new_state="credentials_saved",
            timestamps={
                "access_requested_at": None,
                "cooldown_ends_at": None,
                "decision_at": now,
            },
        )
        _revoke_active_device_authorizations(cur, link_id=body.beneficiary_link_id)
        beneficiary_vault = link["beneficiary_vault_id"]
        conn.commit()
    finally:
        conn.close()

    if beneficiary_vault:
        _notify(
            str(beneficiary_vault), _NOTIFY_KIND_REJECTED,
            title="Inheritance: rejected",
            body="The owner rejected your access request. You can "
                 "request again if you need to.",
            metadata={"beneficiary_link_id": body.beneficiary_link_id},
        )
    return AccessStatusResponse(
        beneficiary_link_id=body.beneficiary_link_id,
        pairing_state="credentials_saved", role="owner",
        access_requested_at=None, cooldown_ends_at=None,
        decision_at=_iso(now), server_now=_iso(now) or "",
    )


@router.post("/inheritance/access/claim", response_model=AccessStatusResponse)
def claim_access(
    body: AccessClaimBody,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> AccessStatusResponse:
    """Beneficiary-side claim after the cooldown expires. Moves the
    state to ``claimable`` (idempotent — repeated calls stay in
    ``claimable`` until /retrieve promotes it to ``released``).
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_link_for_update(cur, link_id=body.beneficiary_link_id)
        if not link:
            raise inheritance_http_error(
                INHERR.ACCESS_NOT_A_BENEFICIARY,
                log_details={"link_id": body.beneficiary_link_id},
            )
        _require_beneficiary(link, principal)

        state = _escrow_state_or_no_credentials(link)
        if state == "cooldown_active":
            cooldown_ends = link.get("cooldown_ends_at")
            if not cooldown_ends or cooldown_ends > _now_utc():
                raise inheritance_http_error(INHERR.CLAIM_TOO_EARLY)
            _write_state(
                cur, link_id=body.beneficiary_link_id,
                new_state="claimable",
            )
            state = "claimable"
        elif state == "claimable":
            pass  # idempotent
        elif state in ("approved", "released"):
            # Approval short-circuits the cooldown; nothing to do here.
            pass
        else:
            raise inheritance_http_error(INHERR.CLAIM_NOT_PERMITTED)
        now = _now_utc()
        conn.commit()
    finally:
        conn.close()

    return AccessStatusResponse(
        beneficiary_link_id=body.beneficiary_link_id,
        pairing_state=state, role="beneficiary",
        access_requested_at=_iso(link.get("access_requested_at")),
        cooldown_ends_at=_iso(link.get("cooldown_ends_at")),
        decision_at=_iso(link.get("decision_at")),
        server_now=_iso(now) or "",
    )


@router.get("/inheritance/access/status", response_model=AccessStatusResponse)
def access_status(
    link_id: int = Query(..., ge=1),
    principal: SessionPrincipal = Depends(verify_session_token),
) -> AccessStatusResponse:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, passer_vault_id, beneficiary_vault_id,
                   COALESCE(pairing_state, 'paired_no_credentials') AS pairing_state,
                   access_requested_at, cooldown_ends_at, decision_at
              FROM beneficiary_links
             WHERE id = %s
            """,
            (link_id,),
        )
        link = cur.fetchone()
    finally:
        conn.close()
    if not link:
        raise inheritance_http_error(
            INHERR.ACCESS_NOT_A_BENEFICIARY,
            log_details={"link_id": link_id},
        )
    caller = str(principal["vault_id"])
    role: Optional[str] = None
    if str(link["passer_vault_id"]) == caller:
        role = "owner"
    elif str(link.get("beneficiary_vault_id") or "") == caller:
        role = "beneficiary"
    else:
        raise inheritance_http_error(
            INHERR.ACCESS_NOT_A_BENEFICIARY,
            log_details={"link_id": link_id},
        )
    return AccessStatusResponse(
        beneficiary_link_id=link_id,
        pairing_state=link["pairing_state"],
        role=role,
        access_requested_at=_iso(link.get("access_requested_at")),
        cooldown_ends_at=_iso(link.get("cooldown_ends_at")),
        decision_at=_iso(link.get("decision_at")),
        server_now=_iso(_now_utc()) or "",
    )


# ---------------------------------------------------------------------
# Retrieve encrypted credential package (beneficiary-side)
# ---------------------------------------------------------------------


@router.get(
    "/inheritance/credentials/retrieve",
    response_model=RetrievedCredentialPackage,
)
def retrieve_credentials(
    link_id: int = Query(..., ge=1),
    principal: SessionPrincipal = Depends(verify_session_token),
) -> RetrievedCredentialPackage:
    """Returns the wrapped credential package to the beneficiary only
    when the release state permits. On the first retrieval in
    ``approved`` or ``claimable``, promotes to ``released`` and
    stamps ``released_at``. Subsequent retrievals are idempotent."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_link_for_update(cur, link_id=link_id)
        if not link:
            raise inheritance_http_error(
                INHERR.RETRIEVE_NOT_YOURS,
                log_details={"link_id": link_id},
            )
        _require_beneficiary(link, principal)

        state = _escrow_state_or_no_credentials(link)
        if state not in _STATES_RELEASE_READABLE:
            raise inheritance_http_error(
                INHERR.RETRIEVE_NOT_RELEASED,
                log_details={"link_id": link_id, "state": state},
            )
        pkg = _load_escrow_package(cur, link_id=link_id)
        if state != "released":
            now = _now_utc()
            cur.execute(
                """
                UPDATE inheritance_credentials
                   SET released_at = COALESCE(released_at, %s),
                       state = 'released',
                       updated_at = NOW()
                 WHERE id = %s
                """,
                (now, pkg["id"]),
            )
            _write_state(
                cur, link_id=link_id, new_state="released",
            )
            state = "released"
            pkg["released_at"] = now
        beneficiary_vault = link["beneficiary_vault_id"]
        conn.commit()
    finally:
        conn.close()

    if beneficiary_vault:
        _notify(
            str(beneficiary_vault), _NOTIFY_KIND_RELEASED,
            title="Inheritance: credentials released",
            body="The saved credentials are now available to reveal.",
            metadata={"beneficiary_link_id": link_id},
        )

    return RetrievedCredentialPackage(
        beneficiary_link_id=link_id,
        crypto_version=int(pkg["crypto_version"]),
        encrypted_payload=_b64u_encode(bytes(pkg["encrypted_payload"])),
        payload_nonce=_b64u_encode(bytes(pkg["payload_nonce"])),
        wrapped_key=_b64u_encode(bytes(pkg["wrapped_key"])),
        wrapping_ephemeral_pk=_b64u_encode(
            bytes(pkg["wrapping_ephemeral_pk"])),
        wrapping_nonce=_b64u_encode(bytes(pkg["wrapping_nonce"])),
        released_at=_iso(pkg.get("released_at")),
        pairing_state=state,
    )


# ---------------------------------------------------------------------
# Device authorization (one-time enrollment token)
# ---------------------------------------------------------------------


def _revoke_active_device_authorizations(cur, *, link_id: int) -> None:
    """Called on cancel / reject / revoke — invalidates any token
    that was issued for this link but has not been consumed yet."""
    cur.execute(
        """
        UPDATE inheritance_device_authorizations
           SET revoked_at = NOW()
         WHERE beneficiary_link_id = %s
           AND consumed_at IS NULL
           AND revoked_at IS NULL
        """,
        (link_id,),
    )


@router.post(
    "/inheritance/device/authorize",
    response_model=DeviceAuthorizeResponse,
)
def authorize_device(
    body: _LinkOnlyBody,
    request: Request,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> DeviceAuthorizeResponse:
    """Beneficiary asks the server to mint a one-time inheritance-
    scoped enrollment token for the current device. Only allowed
    when the state is release-readable. The raw token is returned
    exactly once; the server stores only its SHA-256 hash.

    The token later authorizes ``/inheritance/device/consume`` on
    the INHERITED owner's session — see that handler for the full
    validation chain.
    """
    device_id = (request.headers.get("x-device-id") or "").strip()
    if not device_id:
        raise inheritance_http_error(INHERR.DEV_MISSING_DEVICE_ID)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link = _fetch_link_for_update(cur, link_id=body.beneficiary_link_id)
        if not link:
            raise inheritance_http_error(
                INHERR.DEV_NOT_RELEASED,
                log_details={"link_id": body.beneficiary_link_id},
            )
        _require_beneficiary(link, principal)
        state = _escrow_state_or_no_credentials(link)
        if state not in _STATES_RELEASE_READABLE:
            raise inheritance_http_error(
                INHERR.DEV_NOT_RELEASED,
                log_details={
                    "link_id": body.beneficiary_link_id, "state": state,
                },
            )

        # Any older unconsumed token is revoked before we mint a new
        # one — this preserves the "at most one live token per link"
        # invariant (also enforced by a partial unique index).
        _revoke_active_device_authorizations(
            cur, link_id=body.beneficiary_link_id,
        )
        token_bytes = secrets.token_bytes(32)
        token_hash = hashlib.sha256(token_bytes).digest()
        now = _now_utc()
        expires = now + _device_auth_ttl()
        cur.execute(
            """
            INSERT INTO inheritance_device_authorizations (
                beneficiary_link_id,
                beneficiary_vault_id,
                inherited_owner_vault_id,
                beneficiary_device_id,
                challenge_hash,
                issued_at, expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                body.beneficiary_link_id,
                link["beneficiary_vault_id"],
                link["passer_vault_id"],
                device_id,
                token_hash,
                now, expires,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return DeviceAuthorizeResponse(
        beneficiary_link_id=body.beneficiary_link_id,
        token=_b64u_encode(token_bytes),
        expires_at=_iso(expires) or "",
    )


@router.post(
    "/inheritance/device/consume",
    response_model=DeviceConsumeResponse,
)
def consume_device_authorization(
    body: DeviceConsumeBody,
    request: Request,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> DeviceConsumeResponse:
    """Called from a session that has just authenticated as the
    INHERITED owner (i.e. using the released username + PIN). Marks
    the current device trusted on that account, but ONLY when the
    presented token matches the ``inheritance_device_authorizations``
    row that was minted by ``/authorize`` for this specific pairing.

    Validation chain (each failure surfaces a distinct code so log
    review can distinguish an operator error from a replay attempt):
      * device header present
      * token hash matches an unconsumed, unrevoked, unexpired row
      * row's ``inherited_owner_vault_id`` matches the caller's
        current session
      * row's ``beneficiary_device_id`` matches the ``X-Device-Id``
        the caller is presenting
    """
    device_id = (request.headers.get("x-device-id") or "").strip()
    if not device_id:
        raise inheritance_http_error(INHERR.DEV_MISSING_DEVICE_ID)
    token = body.token.strip()
    if not token:
        raise inheritance_http_error(INHERR.DEV_TOKEN_INVALID)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except Exception:  # noqa: BLE001
        raise inheritance_http_error(INHERR.DEV_TOKEN_INVALID)
    token_hash = hashlib.sha256(raw).digest()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id,
                   beneficiary_link_id,
                   inherited_owner_vault_id,
                   beneficiary_device_id,
                   expires_at, consumed_at, revoked_at
              FROM inheritance_device_authorizations
             WHERE challenge_hash = %s
             FOR UPDATE
            """,
            (token_hash,),
        )
        row = cur.fetchone()
        if not row:
            raise inheritance_http_error(INHERR.DEV_TOKEN_INVALID)
        if row["revoked_at"] is not None or row["consumed_at"] is not None:
            raise inheritance_http_error(INHERR.DEV_ALREADY_CONSUMED)
        if row["expires_at"] <= _now_utc():
            raise inheritance_http_error(INHERR.DEV_TOKEN_INVALID)
        if str(row["inherited_owner_vault_id"]) != str(principal["vault_id"]):
            raise inheritance_http_error(INHERR.DEV_TOKEN_WRONG_ACCOUNT)
        if row["beneficiary_device_id"] != device_id:
            raise inheritance_http_error(INHERR.DEV_TOKEN_WRONG_DEVICE)

        # Confirm the release is still valid (has not been revoked
        # between authorize and consume).
        link = _fetch_link_for_update(cur, link_id=row["beneficiary_link_id"])
        if not link:
            raise inheritance_http_error(INHERR.DEV_TOKEN_INVALID)
        if link.get("pairing_state") == "revoked":
            raise inheritance_http_error(INHERR.ACCESS_REVOKED)

        cur.execute(
            """
            UPDATE inheritance_device_authorizations
               SET consumed_at = NOW()
             WHERE id = %s
               AND consumed_at IS NULL
            """,
            (row["id"],),
        )
        if cur.rowcount != 1:
            # Someone else consumed it in the race window.
            raise inheritance_http_error(INHERR.DEV_ALREADY_CONSUMED)

        # Convert the current device from pending → trusted on the
        # INHERITED owner's account. This is the only auth-graph
        # change this endpoint makes; it never touches the
        # beneficiary's own account, and it never bypasses login
        # (the caller is already authenticated as the inherited
        # owner via their revealed username + PIN).
        cur.execute(
            """
            UPDATE trusted_devices
               SET status = 'trusted', approved_at = NOW()
             WHERE vault_id = %s
               AND device_id = %s
               AND status = 'pending'
            """,
            (row["inherited_owner_vault_id"], device_id),
        )
        conn.commit()
        inherited_vault = str(row["inherited_owner_vault_id"])
    finally:
        conn.close()
    return DeviceConsumeResponse(
        consumed=True,
        inherited_owner_vault_id=inherited_vault,
    )
