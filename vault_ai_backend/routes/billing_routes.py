

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field

from device_gate import verify_trusted_device
from vault_core import get_db


logger = logging.getLogger(__name__)
router = APIRouter()


_CONTACT_SALES_RATE: "OrderedDict[str, list[float]]" = OrderedDict()
_CONTACT_SALES_RATE_PER_MIN = 5


def _rate_limit_contact_sales(vault_id: str) -> None:
    now = time.monotonic()
    window = 60.0
    bucket = _CONTACT_SALES_RATE.get(vault_id, [])
    bucket = [t for t in bucket if (now - t) < window]
    if len(bucket) >= _CONTACT_SALES_RATE_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "contact_sales_rate_limit",
                "message": (
                    "Too many submissions in a short time. Please wait "
                    "a minute before sending another."
                ),
            },
        )
    bucket.append(now)
    _CONTACT_SALES_RATE[vault_id] = bucket
    while len(_CONTACT_SALES_RATE) > 1024:
        _CONTACT_SALES_RATE.popitem(last=False)


@router.get("/billing/me")
async def billing_me(principal=Depends(verify_trusted_device)):
    vault_id = principal["vault_id"]


    from billing import (
        ensure_account_for_vault,
        get_entitlement,
    )
    try:


        account_id = ensure_account_for_vault(vault_id)
        ent = get_entitlement(account_id)
    except Exception as exc:



        logger.warning(
            "billing_me safe_default vault=%s error=%r",
            vault_id, exc, exc_info=True,
        )
        payload = _billing_me_safe_default_payload()
        return payload


    payload = asdict(ent)


    payload["last_webhook_event"] = _read_last_webhook_event(account_id)


    payload["recent_webhook_count"] = _count_recent_global_webhooks()
    payload["billing_state"] = "ok"
    return payload




def _billing_me_safe_default_payload() -> dict:



    from billing import (
        included_bytes, block_bytes,
        block_price_cents_usd, self_service_max_blocks,
    )
    inc = included_bytes()
    return {
        "account_id":               "",
        "account_type":             "individual",
        "sales_channel":            "self_service",
        "included_bytes":           inc,
        "purchased_bytes":          0,
        "storage_bytes_grant":      0,
        "effective_limit_bytes":    inc,
        "used_bytes":               0,
        "percent_used":             0.0,
        "block_count":              0,
        "self_service_max_blocks":  self_service_max_blocks(),
        "status":                   "none",
        "source":                   "safe_default",
        "current_period_end":       None,
        "cancel_at_period_end":     False,
        "block_price_cents_usd":    block_price_cents_usd(),
        "block_bytes":              block_bytes(),
        "has_active_subscription":  False,
        "last_webhook_event":       None,
        "recent_webhook_count":     0,
        "billing_state":            "safe_default",
    }


def _count_recent_global_webhooks(window_seconds: int = 60) -> int:


    try:
        from vault_core import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*)::int
                  FROM provider_event_log
                 WHERE source = 'stripe'
                   AND received_at > NOW() - (
                         INTERVAL '1 second' * %s
                       );
                """,
                (int(window_seconds),),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "billing_me: recent_webhook_count lookup failed",
            exc_info=True,
        )
        return 0


def _read_last_webhook_event(account_id: str) -> Optional[dict]:


    if not account_id:
        return None
    try:
        from vault_core import get_db
        conn = get_db()
        try:
            cur = conn.cursor()
                                                                       
                                                                       
            cur.execute(
                """
                SELECT pel.source_event_id,
                       pel.outcome,
                       pel.received_at,
                       (
                         CASE
                           WHEN pel.received_at IS NULL THEN NULL
                           ELSE EXTRACT(EPOCH FROM NOW() - pel.received_at)::int
                         END
                       ) AS age_seconds,
                       se.event_type
                  FROM subscription_events se
                  LEFT JOIN provider_event_log pel
                         ON pel.source = 'stripe'
                        AND pel.source_event_id = se.source_event_id
                 WHERE se.account_id = %s
                 ORDER BY se.occurred_at DESC
                 LIMIT 1
                """,
                (account_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            source_event_id = str(row[0] or "")
            return {
                "event_id_prefix": source_event_id[:14],
                "event_type":      str(row[4] or ""),
                "outcome":         str(row[1] or ""),
                "age_seconds":     int(row[3] or 0),
            }
        finally:
            conn.close()
    except Exception:
                                                              
                                                         
        logger.warning(
            "billing_me: last_webhook_event lookup failed account=%s",
            (account_id or "")[:8], exc_info=True,
        )
        return None


class ContactSalesRequest(BaseModel):
    email: EmailStr
    company_name: Optional[str] = Field(None, max_length=200)
    requested_blocks: Optional[int] = Field(None, ge=1)
    message: Optional[str] = Field(None, max_length=4000)


@router.post("/billing/contact-sales")
async def contact_sales(
    payload: ContactSalesRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    _rate_limit_contact_sales(vault_id)

                                                                      
    from billing import get_account_id_for_vault
    account_id = get_account_id_for_vault(vault_id)

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO contact_sales_requests (
                account_id, vault_id, email, company_name,
                requested_blocks, message
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                account_id,
                vault_id,
                str(payload.email),
                payload.company_name,
                payload.requested_blocks,
                payload.message,
            ),
        )
        new_id_row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()

    request_id = (
        int(new_id_row[0]) if new_id_row and new_id_row[0] is not None
        else None
    )
    logger.info(
        "contact_sales recorded vault=%s account=%s request_id=%s "
        "requested_blocks=%s",
        vault_id, account_id, request_id, payload.requested_blocks,
    )
    return {
        "ok": True,
        "request_id": request_id,
        "message": (
            "Thanks — our sales team will follow up at the email you "
            "provided within one business day."
        ),
    }
