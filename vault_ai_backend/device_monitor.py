

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from vault_core import get_db


logger = logging.getLogger(__name__)


MONITOR_CACHE_TTL_SECONDS = 5 * 60
MONITOR_CACHE_MAX_ENTRIES = 4096

_monitor_cache: "OrderedDict[tuple[str, Optional[str]], float]" = OrderedDict()
_monitor_lock = threading.Lock()


def _cache_should_skip(key: tuple[str, Optional[str]]) -> bool:


    now = time.time()
    with _monitor_lock:
        prev = _monitor_cache.get(key)
        if prev is not None and (now - prev) < MONITOR_CACHE_TTL_SECONDS:
            _monitor_cache.move_to_end(key)
            return True
        _monitor_cache[key] = now
        _monitor_cache.move_to_end(key)
        while len(_monitor_cache) > MONITOR_CACHE_MAX_ENTRIES:
            _monitor_cache.popitem(last=False)
    return False


def ip_prefix_from(request) -> Optional[str]:


    try:
        raw = request.headers.get("x-forwarded-for") or ""
        ip = raw.split(",", 1)[0].strip() if raw else ""
        if not ip and getattr(request, "client", None) is not None:
            ip = (request.client.host or "").strip()
        if not ip:
            return None
        if ":" in ip:
            parts = ip.split(":")
            head = ":".join(p for p in parts[:3] if p) or "::"
            return f"{head}::/48"
        parts = ip.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        return None
    except Exception:
        return None


def apply_login_device_takeover(
    cursor,
    *,
    vault_id: str,
    device_id: str,
    label: Optional[str] = None,
    user_agent_brand: Optional[str] = None,
    ip_prefix: Optional[str] = None,
) -> dict:
    """Apply takeover inside the authenticated issuer's vault-lock transaction.

    This helper deliberately cannot open or commit a transaction. The caller
    must already hold the vault row lock and either have just verified login
    credentials or revalidated the current session under that same lock.
    Device labels and identifiers are metadata, not authentication proof.
    """
    cursor.execute(
        "SELECT status FROM trusted_devices WHERE vault_id = %s AND device_id = %s",
        (vault_id, device_id),
    )
    prior = cursor.fetchone()
    newly_trusted = not prior or prior.get("status") != "trusted"
    cursor.execute(
        """
        INSERT INTO trusted_devices (
            vault_id, device_id, label, user_agent_brand, last_ip_prefix,
            status, approved_at, last_seen_at, revoked_at, cooldown_until
        ) VALUES (
            %s, %s, %s, %s, %s,
            'trusted', NOW(), NOW(), NULL, NULL
        )
        ON CONFLICT (vault_id, device_id) DO UPDATE
            SET status           = 'trusted',
                approved_at      = NOW(),
                last_seen_at     = NOW(),
                revoked_at       = NULL,
                cooldown_until   = NULL,
                last_ip_prefix   = COALESCE(
                    EXCLUDED.last_ip_prefix,
                    trusted_devices.last_ip_prefix),
                user_agent_brand = COALESCE(
                    EXCLUDED.user_agent_brand,
                    trusted_devices.user_agent_brand),
                label            = COALESCE(
                    NULLIF(EXCLUDED.label, ''),
                    trusted_devices.label)
        """,
        (vault_id, device_id, label, user_agent_brand, ip_prefix),
    )
    cursor.execute(
        """
        UPDATE trusted_devices
           SET status         = 'revoked',
               revoked_at     = NOW(),
               cooldown_until = NULL
         WHERE vault_id = %s
           AND device_id <> %s
           AND status <> 'revoked'
        RETURNING device_id
        """,
        (vault_id, device_id),
    )
    revoked_rows = cursor.fetchall() or []
    revoked_ids = [r["device_id"] for r in revoked_rows]
    return {
        "status":                    "trusted",
        "device_id":                 device_id,
        "new_device_trusted":        newly_trusted,
        "created":                   prior is None,
        "revoked_other_count":       len(revoked_ids),
        "revoked_other_device_ids":  revoked_ids,
    }


def lock_and_validate_current_session(cursor, *, vault_id: str, session_token_id: str) -> dict:
    """Revalidate a previously authenticated session inside the vault lock.

    Reuse the issuer's lock order before device mutations. An entry-time
    principal alone is not proof that a request still owns the current login.
    The caller owns this transaction and must roll it back on any failure.
    """
    if not session_token_id:
        raise HTTPException(status_code=401, detail={"code": "invalid_session"})
    cursor.execute(
        "SELECT vault_id FROM vaults WHERE vault_id = %s FOR UPDATE",
        (vault_id,),
    )
    if cursor.fetchone() is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_session"})
    cursor.execute(
        """
        SELECT device_id, revoked_at, revoked_reason,
               expires_at > NOW() AS unexpired
          FROM auth_sessions
         WHERE token_id = %s AND vault_id = %s
         FOR UPDATE
        """,
        (session_token_id, vault_id),
    )
    session = cursor.fetchone()
    if session is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_session"})
    if session["revoked_at"] is not None:
        code = ("session_superseded" if session["revoked_reason"] ==
                "superseded-by-new-login" else "session_revoked")
        raise HTTPException(status_code=401, detail={"code": code})
    if not session["unexpired"]:
        raise HTTPException(status_code=401, detail={"code": "session_expired"})
    return session


def register_or_refresh(
    *,
    vault_id: str,
    device_id: str,
    label: Optional[str],
    user_agent_brand: Optional[str],
    ip_prefix: Optional[str],
    session_token_id: str,
) -> dict:
    """Refresh only the still-current session's device, never pivot a bearer.

    A pre-existing session without a device binding may bind once. Subsequent
    requests must match that binding. Revalidation under the issuer's vault
    lock prevents an old request from undoing a newer login's takeover.
    """
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        session = lock_and_validate_current_session(
            cur, vault_id=vault_id, session_token_id=session_token_id,
        )
        if session["device_id"] and session["device_id"] != device_id:
            raise HTTPException(status_code=403, detail={"code": "device_session_mismatch"})
        if session["device_id"]:
            cur.execute(
                "SELECT status FROM trusted_devices WHERE vault_id = %s AND device_id = %s FOR UPDATE",
                (vault_id, device_id),
            )
            device = cur.fetchone()
            if device and device["status"] == "revoked":
                # Explicit revocation requires a fresh credential-verified
                # login; possession of the old bearer cannot undo it.
                raise HTTPException(status_code=403, detail={"code": "device_revoked"})
        if not session["device_id"]:
            cur.execute(
                "UPDATE auth_sessions SET device_id = %s WHERE token_id = %s",
                (device_id, session_token_id),
            )
        outcome = apply_login_device_takeover(
            cur, vault_id=vault_id, device_id=device_id, label=label,
            user_agent_brand=user_agent_brand, ip_prefix=ip_prefix,
        )
        conn.commit()
        return {
            "status": "trusted",
            "is_first_device": outcome["revoked_other_count"] == 0 and outcome["created"],
            "created": outcome["created"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def monitor_best_effort(request, principal: dict) -> None:
    """Record presence only; never grant trust or revoke another device."""
    try:
        vault_id = principal["vault_id"]
        device_id = (request.headers.get("x-device-id") or "").strip()
        if not device_id or device_id != principal.get("device_id"):
            return
        cache_key = (vault_id, device_id)
        if _cache_should_skip(cache_key):
            return

        ip_prefix = ip_prefix_from(request)
        conn = get_db()
        try:
            cur = conn.cursor()
            # Recheck the token in this statement: an earlier authentication
            # success may have been superseded while this request was paused.
            cur.execute(
                """
                UPDATE trusted_devices d
                   SET last_seen_at = NOW(),
                       last_ip_prefix = COALESCE(%s, d.last_ip_prefix)
                  FROM auth_sessions s
                 WHERE d.vault_id = %s AND d.device_id = %s
                   AND d.status = 'trusted'
                   AND s.token_id = %s AND s.vault_id = d.vault_id
                   AND s.device_id = d.device_id
                   AND s.revoked_at IS NULL AND s.expires_at > NOW()
                """,
                (ip_prefix, vault_id, device_id, principal["token_id"]),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception:
        logger.exception("[DEVICE-MONITOR] monitor failed (swallowed)")


def _reset_monitor_cache_for_tests() -> None:
    with _monitor_lock:
        _monitor_cache.clear()


def list_devices_for_vault(vault_id: str) -> list[dict[str, Any]]:


    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT device_id, label, user_agent_brand, last_ip_prefix,
                   status, created_at, approved_at, revoked_at, last_seen_at
            FROM trusted_devices
            WHERE vault_id = %s
            ORDER BY (status = 'trusted') DESC, last_seen_at DESC NULLS LAST
            """,
            (vault_id,),
        )
        return cur.fetchall() or []
    finally:
        conn.close()
