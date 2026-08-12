

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal, verify_session_token
from vault_core import get_db


logger = logging.getLogger(__name__)


ROUTES_EXEMPT_FROM_DEVICE_GATE = frozenset({
                                                                        
                                                     
    "/auth/signup",
    "/auth/login",
    "/auth/me",
    "/auth/logout",

                                                                   
    "/devices/register",
    "/devices/me",
    "/devices/diagnose-trust",
    "/devices/dev/cleanup-pending",
    "/devices/dev/reset-trust-state",

                                                                 
    "/billing/stripe/webhook",
})


DEVICE_SELF_APPROVAL_COOLDOWN_DEFAULT_SECONDS = 300              
DEVICE_SELF_APPROVAL_COOLDOWN_MAX_SECONDS     = 86400           


def load_self_approval_cooldown_seconds() -> int:


    raw = os.getenv("VAULTAI_DEVICE_SELF_APPROVAL_COOLDOWN_SECONDS", "").strip()
    if not raw:
        return DEVICE_SELF_APPROVAL_COOLDOWN_DEFAULT_SECONDS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "[DEVICE-GATE] cooldown env var=%r is not an integer; using default %d",
            raw, DEVICE_SELF_APPROVAL_COOLDOWN_DEFAULT_SECONDS,
        )
        return DEVICE_SELF_APPROVAL_COOLDOWN_DEFAULT_SECONDS
    if value <= 0:
        logger.warning(
            "[DEVICE-GATE] cooldown=%d <= 0; using default %d",
            value, DEVICE_SELF_APPROVAL_COOLDOWN_DEFAULT_SECONDS,
        )
        return DEVICE_SELF_APPROVAL_COOLDOWN_DEFAULT_SECONDS
    if value > DEVICE_SELF_APPROVAL_COOLDOWN_MAX_SECONDS:
        logger.warning(
            "[DEVICE-GATE] cooldown=%d exceeds max %d; clamping",
            value, DEVICE_SELF_APPROVAL_COOLDOWN_MAX_SECONDS,
        )
        return DEVICE_SELF_APPROVAL_COOLDOWN_MAX_SECONDS
    return value


_DEV_ENV_TOKENS = frozenset({"local", "dev", "development", "develop"})


def _is_dev_environment() -> bool:
    for var in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
        if os.getenv(var, "").strip().lower() in _DEV_ENV_TOKENS:
            return True
    return False


def _gate_enabled() -> bool:
    dev_disabled = (
        os.getenv("VAULTAI_DEVICE_GATE_DEV_DISABLE", "false").strip().lower()
        == "true"
    )
    if dev_disabled:
        return False
    return (
        os.getenv("VAULTAI_DEVICE_GATE_ENFORCE", "true").strip().lower()
        == "true"
    )


def is_dev_auto_trust_enabled() -> bool:
    raw = os.getenv(
        "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST", "false",
    ).strip().lower()
    if raw != "true":
        return False
    # Auto-trust is intentionally harder to enable than an ordinary dev
    # feature.  The isolated-QA marker and a loopback database are both
    # required, so copying the flag into production configuration cannot
    # weaken production device policy.
    isolated_qa = os.getenv(
        "VAULTAI_ISOLATED_QA", "false",
    ).strip().lower() == "true"
    database_url = os.getenv("DATABASE_URL", "").strip().lower()
    loopback_database = (
        "@127.0.0.1:" in database_url or "@localhost:" in database_url
    )
    return _is_dev_environment() and isolated_qa and loopback_database


def gate_status_for_boot() -> dict:

    dev_disabled_raw = os.getenv("VAULTAI_DEVICE_GATE_DEV_DISABLE", "").strip()
    enforce_raw = os.getenv("VAULTAI_DEVICE_GATE_ENFORCE", "").strip()
    enabled = _gate_enabled()
    if not enabled and dev_disabled_raw.lower() == "true":
        reason = "VAULTAI_DEVICE_GATE_DEV_DISABLE=true (dev override)"
    elif not enabled:
        reason = "VAULTAI_DEVICE_GATE_ENFORCE explicitly set to a non-true value"
    else:
        reason = (
            "safe default (ON)"
            if not enforce_raw
            else f"VAULTAI_DEVICE_GATE_ENFORCE={enforce_raw}"
        )
    return {
        "enabled":         enabled,
        "reason":          reason,
        "enforce_raw":     enforce_raw or "(unset, default true)",
        "dev_disable_raw": dev_disabled_raw or "(unset)",
        "dev_auto_trust":  is_dev_auto_trust_enabled(),
        "dev_environment": _is_dev_environment(),
    }


def resolve_response_status(
    db_status: Optional[str],
    row_missing: bool,
) -> tuple[str, str]:

    if row_missing:
        return (
            "missing",
            "This device has not been registered with this vault yet. "
            "Sign in again to register it.",
        )
    if db_status in ("pending", "revoked"):
        return (db_status, "This device is not trusted yet.")
    return ("unknown", "This device is not trusted yet.")


def _short(s: Optional[str], head: int = 6, tail: int = 4) -> str:
    if not s:
        return "?"
    if len(s) <= head + tail + 3:
        return s
    return f"{s[:head]}...{s[-tail:]}"


def _lookup_device_status(vault_id: str, device_id: str) -> Optional[str]:
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT status FROM trusted_devices
            WHERE vault_id = %s AND device_id = %s
            """,
            (vault_id, device_id),
        )
        row = cur.fetchone()
        return row["status"] if row else None
    finally:
        conn.close()


def _auto_trust(vault_id: str, device_id: str, current_status: Optional[str]) -> None:


    conn = get_db()
    try:
        cur = conn.cursor()
        if current_status == "pending":
            cur.execute(
                """
                UPDATE trusted_devices
                SET status='trusted', approved_at=NOW(), last_seen_at=NOW()
                WHERE vault_id=%s AND device_id=%s
                """,
                (vault_id, device_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO trusted_devices
                  (vault_id, device_id, status, approved_at, last_seen_at)
                VALUES (%s, %s, 'trusted', NOW(), NOW())
                ON CONFLICT (vault_id, device_id) DO UPDATE
                SET status='trusted', approved_at=NOW(), last_seen_at=NOW()
                """,
                (vault_id, device_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def verify_trusted_device(
    request: Request,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> SessionPrincipal:


    if not _gate_enabled():
        return principal

    if request.url.path in ROUTES_EXEMPT_FROM_DEVICE_GATE:
        return principal

    vault_id = principal["vault_id"]
    device_id = (request.headers.get("x-device-id") or "").strip()

    if not device_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code":      "missing_device_id",
                "message":   "X-Device-Id header required. Please refresh or update the app.",
                "device_id": None,
                "status":    "missing_device_id",
            },
        )

    db_status = _lookup_device_status(vault_id, device_id)
    row_missing = db_status is None

    if db_status == "trusted":
        return principal

                                                                     
    if db_status != "revoked" and is_dev_auto_trust_enabled():
        _auto_trust(vault_id, device_id, db_status)
        logger.warning(
            "[DEVICE-GATE] DEV_AUTO_TRUST device=%s vault=%s prior_status=%s",
            _short(device_id), _short(vault_id), db_status,
        )
        return principal

    response_status, response_message = resolve_response_status(db_status, row_missing)
    # Under single-active-device semantics, a 'revoked' row means
    # this device's session ended because the user (or someone with
    # their credentials) signed in on a different device. The client
    # needs to distinguish that from "no device row yet / pending"
    # so it can drop the local session, surface an unambiguous
    # message, and redirect straight to the login screen instead of
    # opening the legacy approval-waiting-period flow.
    if response_status == "revoked":
        raise HTTPException(
            status_code=403,
            detail={
                "code":      "device_revoked",
                "message":   (
                    "This device's session ended because you signed in "
                    "on another device. Sign in again to continue."
                ),
                "device_id": device_id,
                "status":    "revoked",
            },
        )
    raise HTTPException(
        status_code=403,
        detail={
            "code":      "device_not_trusted",
            "message":   response_message,
            "device_id": device_id,
            "status":    response_status,
        },
    )


async def verify_caller_is_trusted_device(
    request: Request,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> SessionPrincipal:


    vault_id = principal["vault_id"]
    device_id = (request.headers.get("x-device-id") or "").strip()

    if not device_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code":      "missing_device_id",
                "message":   "X-Device-Id header required to manage devices.",
                "device_id": None,
                "status":    "missing_device_id",
            },
        )

    db_status = _lookup_device_status(vault_id, device_id)
    if db_status != "trusted":
        raise HTTPException(
            status_code=403,
            detail={
                "code":      "device_must_be_trusted_to_approve",
                "message":   "Only a trusted device can approve or revoke devices.",
                "device_id": device_id,
                "status":    db_status or "unknown",
            },
        )
    return principal
