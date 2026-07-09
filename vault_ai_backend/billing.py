

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from psycopg2.extras import RealDictCursor

from vault_core import get_db


logger = logging.getLogger(__name__)


try:
    from vault_config import billing as _billing_cfg
    _bcfg = _billing_cfg()
    DEFAULT_INCLUDED_BYTES = _bcfg.free_included_bytes
    DEFAULT_BLOCK_BYTES = _bcfg.storage_block_bytes
    DEFAULT_BLOCK_PRICE_CENTS_USD = _bcfg.monthly_block_price_cents_usd
    DEFAULT_SELF_SERVICE_MAX_BLOCKS = _bcfg.self_service_max_blocks
except Exception:
    DEFAULT_INCLUDED_BYTES = 1_073_741_824                 
    DEFAULT_BLOCK_BYTES = 53_687_091_200                    
    DEFAULT_BLOCK_PRICE_CENTS_USD = 2500                  
    DEFAULT_SELF_SERVICE_MAX_BLOCKS = 100                  


DEFAULT_FREE_STORAGE_BYTES = DEFAULT_INCLUDED_BYTES


_STATUSES_THAT_GRANT_STORAGE = frozenset(
    {"active", "in_grace", "canceled_pending"}
)


@dataclass(frozen=True)
class StorageEntitlement:


    account_id: str
    account_type: str                                                         
    sales_channel: str                                                        
    included_bytes: int
    purchased_bytes: int
    storage_bytes_grant: int
    effective_limit_bytes: int
    used_bytes: int
    percent_used: float
    block_count: int
    self_service_max_blocks: int
    status: str
    source: str
    current_period_end: Optional[str]                            
    cancel_at_period_end: bool
    block_price_cents_usd: int
    block_bytes: int
                                                                   
                                                           
    has_active_subscription: bool


_PRICING_CACHE: dict[str, int] = {}


def reset_pricing_cache() -> None:


    _PRICING_CACHE.clear()


def _load_pricing() -> None:


    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT key, value FROM storage_pricing;")
            rows = cur.fetchall() or []
            _PRICING_CACHE.clear()
            for row in rows:
                _PRICING_CACHE[row["key"]] = int(row["value"])
        finally:
            conn.close()
    except Exception:
        logger.warning("storage_pricing load failed; using defaults",
                       exc_info=True)


def get_pricing(key: str, default: int) -> int:


    if not _PRICING_CACHE:
        _load_pricing()
    return _PRICING_CACHE.get(key, default)


def included_bytes() -> int:
    return get_pricing("included_bytes", DEFAULT_INCLUDED_BYTES)


def block_bytes() -> int:
    return get_pricing("block_bytes", DEFAULT_BLOCK_BYTES)


def block_price_cents_usd() -> int:
    return get_pricing("block_price_cents_usd",
                       DEFAULT_BLOCK_PRICE_CENTS_USD)


def self_service_max_blocks() -> int:
    return get_pricing("self_service_max_blocks",
                       DEFAULT_SELF_SERVICE_MAX_BLOCKS)


def blocks_to_bytes(blocks: int) -> int:


    if blocks < 0:
        raise ValueError("blocks must be >= 0")
    return blocks * block_bytes()


def block_count_to_price_cents(blocks: int) -> int:


    if blocks < 0:
        raise ValueError("blocks must be >= 0")
    return blocks * block_price_cents_usd()


def is_within_self_service_ceiling(blocks: int) -> bool:


    return blocks <= self_service_max_blocks()


def compute_percent_used(used: int, limit: int) -> float:


    if limit <= 0:
        return 100.0 if used > 0 else 0.0
    raw = (float(used) / float(limit)) * 100.0
    if raw < 0.0:
        return 0.0
    if raw > 100.0:
        return 100.0
    return round(raw, 1)


def get_account_id_for_vault(vault_id: str) -> Optional[str]:


    if not vault_id:
        return None
    try:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT account_id FROM vaults WHERE vault_id = %s LIMIT 1",
                (vault_id,),
            )
            row = cur.fetchone()
            return str(row[0]) if row and row[0] is not None else None
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "get_account_id_for_vault failed vault_id=%s", vault_id, exc_info=True,
        )
        return None


def reconcile_account_storage_from_vaults(account_id: str) -> int:


    if not account_id:
        return 0
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE account_storage_totals t
               SET encrypted_bytes = COALESCE((
                     SELECT SUM(total_bytes)
                       FROM vaults
                      WHERE account_id = %s
                   ), 0),
                   last_recomputed = NOW()
             WHERE t.account_id = %s
            RETURNING encrypted_bytes;
            """,
            (account_id, account_id),
        )
        row = cur.fetchone()
        conn.commit()
        return int(row[0]) if row else 0
    except Exception:
        conn.rollback()
        logger.warning(
            "reconcile_account_storage_from_vaults failed account=%s",
            account_id, exc_info=True,
        )
        return 0
    finally:
        conn.close()


def ensure_account_for_vault(vault_id: str) -> str:


    if not vault_id:
        raise ValueError("vault_id required")
    existing = get_account_id_for_vault(vault_id)
    if existing is not None:
        try:
            reconcile_account_storage_from_vaults(existing)
        except Exception:
            logger.warning(
                "reconcile (existing account) failed vault=%s account=%s",
                vault_id, existing, exc_info=True,
            )
        return existing

    new_id = str(uuid.uuid4())
    conn = get_db()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO accounts (
                    account_id, account_type, sales_channel,
                    billing_owner_vault_id
                ) VALUES (%s, 'individual', 'self_service', %s);
                """,
                (new_id, vault_id),
            )
            cur.execute(
                """
                INSERT INTO account_members (
                    account_id, vault_id, role, status
                ) VALUES (%s, %s, 'owner', 'active');
                """,
                (new_id, vault_id),
            )
            cur.execute(
                """
                INSERT INTO account_subscriptions (account_id)
                VALUES (%s)
                ON CONFLICT (account_id) DO NOTHING;
                """,
                (new_id,),
            )
            cur.execute(
                """
                INSERT INTO account_storage_totals (account_id, encrypted_bytes)
                VALUES (%s, 0)
                ON CONFLICT (account_id) DO NOTHING;
                """,
                (new_id,),
            )
            cur.execute(
                "UPDATE vaults SET account_id = %s WHERE vault_id = %s",
                (new_id, vault_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
                                           
            again = get_account_id_for_vault(vault_id)
            if again is not None:
                try:
                    reconcile_account_storage_from_vaults(again)
                except Exception:
                    pass
                return again
            raise
    finally:
        conn.close()

    try:
        reconcile_account_storage_from_vaults(new_id)
    except Exception:
        logger.warning(
            "reconcile (new account) failed vault=%s account=%s",
            vault_id, new_id, exc_info=True,
        )
    return new_id


def _purchased_bytes_active(status: str, purchased: int) -> int:


    return purchased if status in _STATUSES_THAT_GRANT_STORAGE else 0


def _grant_is_live(expires_at, now_iso: Optional[str]) -> bool:


    if expires_at is None:
        return True
                                                                   
                                                                
    return True


def get_entitlement(account_id: str) -> StorageEntitlement:


    if not account_id:
        raise ValueError("account_id required")

    inc = included_bytes()
    bb = block_bytes()
    price = block_price_cents_usd()
    ceiling = self_service_max_blocks()

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
              a.account_id,
              a.account_type,
              a.sales_channel,
              COALESCE(s.status, 'none')          AS status,
              COALESCE(s.source, 'none')          AS source,
              COALESCE(s.block_count, 0)          AS block_count,
              COALESCE(s.purchased_bytes, 0)      AS purchased_bytes,
              COALESCE(s.storage_bytes_grant, 0)  AS storage_bytes_grant,
              s.storage_bytes_grant_expires_at,
              s.current_period_end,
              COALESCE(s.cancel_at_period_end, FALSE) AS cancel_at_period_end,
              COALESCE(t.encrypted_bytes, 0)      AS used_bytes
            FROM accounts a
            LEFT JOIN account_subscriptions s ON s.account_id = a.account_id
            LEFT JOIN account_storage_totals t ON t.account_id = a.account_id
            WHERE a.account_id = %s;
            """,
            (account_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
                                                                       
                                                                    
        logger.warning("get_entitlement: missing account_id=%s", account_id)
        return StorageEntitlement(
            account_id=account_id,
            account_type="individual",
            sales_channel="self_service",
            included_bytes=inc,
            purchased_bytes=0,
            storage_bytes_grant=0,
            effective_limit_bytes=inc,
            used_bytes=0,
            percent_used=0.0,
            block_count=0,
            self_service_max_blocks=ceiling,
            status="none",
            source="none",
            current_period_end=None,
            cancel_at_period_end=False,
            block_price_cents_usd=price,
            block_bytes=bb,
            has_active_subscription=False,
        )

    status = str(row["status"])
    purchased = int(row["purchased_bytes"])
    grant = int(row["storage_bytes_grant"])

                                                                    
    grant_expires = row["storage_bytes_grant_expires_at"]
    if grant_expires is not None:
                                                                   
                                                                  
        conn2 = get_db()
        try:
            cur2 = conn2.cursor()
            cur2.execute("SELECT (NOW() > %s)::bool;", (grant_expires,))
            expired = bool(cur2.fetchone()[0])
        finally:
            conn2.close()
        if expired:
            grant = 0

    purchased_active = _purchased_bytes_active(status, purchased)
    block_count_val = int(row["block_count"])

                                                                           
    if block_count_val > 0 and purchased_active > 0:
        effective = purchased_active
    else:
        effective = inc + grant

    used = int(row["used_bytes"])
    pct = compute_percent_used(used, effective)

    period_end = row["current_period_end"]
    period_end_iso = (
        period_end.isoformat() if period_end is not None else None
    )

                                                                  
    has_active_subscription = (
        str(row["source"]).lower() == "stripe"
        and status in _STATUSES_THAT_GRANT_STORAGE
    )

    return StorageEntitlement(
        account_id=str(row["account_id"]),
        account_type=str(row["account_type"]),
        sales_channel=str(row["sales_channel"]),
        included_bytes=inc,
        purchased_bytes=purchased_active,
        storage_bytes_grant=grant,
        effective_limit_bytes=effective,
        used_bytes=used,
        percent_used=pct,
        block_count=int(row["block_count"]),
        self_service_max_blocks=ceiling,
        status=status,
        source=str(row["source"]),
        current_period_end=period_end_iso,
        cancel_at_period_end=bool(row["cancel_at_period_end"]),
        block_price_cents_usd=price,
        block_bytes=bb,
        has_active_subscription=has_active_subscription,
    )


def get_effective_limit_for_vault(vault_id: str) -> int:


    inc = included_bytes()
    account_id = get_account_id_for_vault(vault_id)
    if account_id is None:
        return inc
    try:
        ent = get_entitlement(account_id)
        return ent.effective_limit_bytes
    except Exception:
        logger.warning(
            "get_effective_limit_for_vault failed vault=%s account=%s",
            vault_id, account_id, exc_info=True,
        )
        return inc


def get_effective_storage_limit(account_id: Optional[str]) -> int:


    floor = included_bytes()
    if not account_id:
        return floor
    try:
        ent = get_entitlement(account_id)
        limit = int(ent.effective_limit_bytes)
                                                                 
                                                                 
        return limit if limit > 0 else floor
    except Exception:
        logger.warning(
            "get_effective_storage_limit failed account=%s",
            (account_id or "")[:8], exc_info=True,
        )
        return floor


def get_storage_used_bytes(account_id: Optional[str]) -> int:


    if not account_id:
        return 0
    try:
        ent = get_entitlement(account_id)
        used = int(ent.used_bytes)
        return max(0, used)
    except Exception:
        logger.warning(
            "get_storage_used_bytes failed account=%s",
            (account_id or "")[:8], exc_info=True,
        )
        return 0


def bump_account_total_bytes(account_id: str, delta_bytes: int) -> None:


    if not account_id or delta_bytes == 0:
        return
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO account_storage_totals (account_id, encrypted_bytes)
            VALUES (%s, GREATEST(%s, 0))
            ON CONFLICT (account_id) DO UPDATE
              SET encrypted_bytes = GREATEST(
                    account_storage_totals.encrypted_bytes + EXCLUDED.encrypted_bytes,
                    0
                  ),
                  last_recomputed = NOW();
            """,
            (account_id, int(delta_bytes)),
        )
        conn.commit()
    finally:
        conn.close()
