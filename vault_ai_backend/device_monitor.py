

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


def register_or_refresh(
    *,
    vault_id: str,
    device_id: str,
    label: Optional[str],
    user_agent_brand: Optional[str],
    ip_prefix: Optional[str],
) -> dict:


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
        existing = cur.fetchone()

        if existing:
            cur.execute(
                """
                UPDATE trusted_devices
                SET last_seen_at     = NOW(),
                    last_ip_prefix   = COALESCE(%s, last_ip_prefix),
                    user_agent_brand = COALESCE(%s, user_agent_brand),
                    label            = COALESCE(NULLIF(%s, ''), label)
                WHERE vault_id = %s AND device_id = %s
                """,
                (ip_prefix, user_agent_brand, label, vault_id, device_id),
            )
            conn.commit()
            return {
                "status": existing["status"],
                "is_first_device": False,
                "created": False,
            }

                                                                              
        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM trusted_devices
            WHERE vault_id = %s AND status = 'trusted'
            """,
            (vault_id,),
        )
        trusted_count = int((cur.fetchone() or {}).get("n") or 0)
        is_first = trusted_count == 0
        new_status = "trusted" if is_first else "pending"

        cur.execute(
            """
            INSERT INTO trusted_devices (
                vault_id, device_id, label, user_agent_brand, last_ip_prefix,
                status, approved_at, last_seen_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s,
                CASE WHEN %s = 'trusted' THEN NOW() ELSE NULL END,
                NOW()
            )
            ON CONFLICT (vault_id, device_id) DO NOTHING
            """,
            (
                vault_id, device_id, label, user_agent_brand, ip_prefix,
                new_status, new_status,
            ),
        )
        cur.execute(
            """
            SELECT status FROM trusted_devices
            WHERE vault_id = %s AND device_id = %s
            """,
            (vault_id, device_id),
        )
        final = cur.fetchone() or {"status": new_status}
        conn.commit()
        return {
            "status": final["status"],
            "is_first_device": is_first and final["status"] == "trusted",
            "created": True,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
