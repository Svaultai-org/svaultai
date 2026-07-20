

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

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


def _short(s: Optional[str], head: int = 6, tail: int = 4) -> str:
    if not s:
        return "?"
    if len(s) <= head + tail + 3:
        return s
    return f"{s[:head]}...{s[-tail:]}"


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


def trust_current_and_revoke_others(
    *,
    vault_id: str,
    device_id: str,
    label: Optional[str] = None,
    user_agent_brand: Optional[str] = None,
    ip_prefix: Optional[str] = None,
) -> dict:
    # Single-active-device invariant, enforced atomically.
    #
    # The caller has just proven possession of the vault credentials
    # (ZK signup, ZK login, or a legacy adoption path calling
    # /devices/register). We record the current device as trusted
    # and, in the SAME transaction, revoke every other row for the
    # same vault_id. When the two statements share a transaction, no
    # concurrent reader (device gate, /devices/me listing) can
    # observe an intermediate state with two live devices.
    #
    # Idempotent when called with the same (vault_id, device_id):
    # the UPSERT re-affirms trusted status and the revoke-others UPDATE
    # matches zero rows.
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
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
        cur.execute(
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
        revoked_rows = cur.fetchall() or []
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    revoked_ids = [r["device_id"] for r in revoked_rows]
    if revoked_ids:
        logger.info(
            "[SINGLE-ACTIVE-DEVICE] vault=%s trusted=%s revoked_others=%d",
            _short(vault_id), _short(device_id), len(revoked_ids),
        )
    return {
        "status":                    "trusted",
        "device_id":                 device_id,
        "revoked_other_count":       len(revoked_ids),
        "revoked_other_device_ids":  revoked_ids,
    }


def register_or_refresh(
    *,
    vault_id: str,
    device_id: str,
    label: Optional[str],
    user_agent_brand: Optional[str],
    ip_prefix: Optional[str],
) -> dict:
    # Under the single-active-device model, /devices/register no
    # longer creates a 'pending' row that waits for approval from an
    # older device. The caller has an authenticated session, which
    # means they already passed OPAQUE — they hold the master key —
    # so this device is trusted and every other device is revoked in
    # one atomic step. The return shape is kept compatible with the
    # legacy `is_first_device`/`created` fields so existing callers
    # (test_device_register_idempotency, front-end retry loop)
    # continue to compile; `is_first_device` now means "there were
    # no other trusted devices before this call", i.e. no siblings
    # got revoked.
    prior_conn = get_db()
    try:
        cur = prior_conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT status FROM trusted_devices
             WHERE vault_id = %s AND device_id = %s
            """,
            (vault_id, device_id),
        )
        prior_row = cur.fetchone()
    finally:
        prior_conn.close()

    outcome = trust_current_and_revoke_others(
        vault_id=vault_id,
        device_id=device_id,
        label=label,
        user_agent_brand=user_agent_brand,
        ip_prefix=ip_prefix,
    )
    return {
        "status":          outcome["status"],
        "is_first_device": outcome["revoked_other_count"] == 0
                           and prior_row is None,
        "created":         prior_row is None,
    }


def monitor_best_effort(request, vault_id: str) -> None:


    try:
        device_id = request.headers.get("x-device-id")
        cache_key = (vault_id, device_id)
        if _cache_should_skip(cache_key):
            return

        if not device_id:
            logger.info(
                "[DEVICE-MONITOR] vault=%s no X-Device-Id header (legacy client)",
                _short(vault_id),
            )
            return

        ip_prefix = ip_prefix_from(request)
        ua_brand = (request.headers.get("user-agent") or "")[:120] or None

        result = register_or_refresh(
            vault_id=vault_id,
            device_id=device_id,
            label=None,                                                                
            user_agent_brand=ua_brand,
            ip_prefix=ip_prefix,
        )

        status = result.get("status")
        if status == "trusted":
            return
        if status == "pending":
            logger.warning(
                "[DEVICE-MONITOR] would-block (pending) vault=%s device=%s",
                _short(vault_id), _short(device_id),
            )
        elif status == "revoked":
            logger.warning(
                "[DEVICE-MONITOR] would-block (revoked) vault=%s device=%s",
                _short(vault_id), _short(device_id),
            )
        else:
            logger.warning(
                "[DEVICE-MONITOR] would-block (unknown status=%r) vault=%s device=%s",
                status, _short(vault_id), _short(device_id),
            )
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
