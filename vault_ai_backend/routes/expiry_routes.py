

from __future__ import annotations

import logging
import os
import time
import traceback
from collections import OrderedDict
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device
from vault_core import get_db


def _safe_dashboard_response(handler_name: str, exc: BaseException) -> JSONResponse:
    tb = traceback.format_exc()
    print(
        f"[VAULT-DEBUG] {handler_name} CRASH error_type="
        f"{type(exc).__name__} repr={exc!r}",
        flush=True,
    )
    print(f"[VAULT-DEBUG] {handler_name} TRACEBACK BEGIN", flush=True)
    print(tb, flush=True)
    print(f"[VAULT-DEBUG] {handler_name} TRACEBACK END", flush=True)
    return JSONResponse(
        status_code=500,
        content={
            "code": "dashboard_handler_error",
            "message": (
                f"{handler_name} failed: {type(exc).__name__}: {exc}"
            ),
            "engine": "error",
                                                                    
                                                                  
            "alerts": [],
            "items": [],
            "relationships": [],
            "counts": {},
        },
    )


logger = logging.getLogger(__name__)
router = APIRouter()


RATE_PER_MIN = int(os.getenv("VAULTAI_EXPIRY_DASHBOARD_RATE_PER_MIN", "30"))


_EXPIRY_TYPE_PRETTY = {
    "passport":         "Passport",
    "visa":             "Visa",
    "id_card":          "ID card",
    "driver_license":   "Driver license",
    "insurance":        "Insurance",
    "tax":              "Tax",
    "contract":         "Contract",
    "subscription":     "Subscription",
    "custom":           "Reminder",
}


_rate: "OrderedDict[str, list[float]]" = OrderedDict()


def _is_enabled() -> bool:

    return os.getenv(
        "VAULTAI_EXPIRY_DASHBOARD_ENABLED", "true",
    ).lower() == "true"


def _rate_limit(vault_id: str) -> None:
    now = time.monotonic()
    window = 60.0
    bucket = _rate.get(vault_id, [])
    bucket = [t for t in bucket if (now - t) < window]
    if len(bucket) >= RATE_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Slow down.",
        )
    bucket.append(now)
    _rate[vault_id] = bucket
                  
    while len(_rate) > 1024:
        _rate.popitem(last=False)


def _days_until_today(d) -> Optional[int]:
    if d is None:
        return None
    try:
                                                                
        if isinstance(d, str):
            parsed = date.fromisoformat(d)
        elif isinstance(d, date):
            parsed = d
        else:
            return None
        return (parsed - date.today()).days
    except Exception:
        return None


def _resolve_label(
    cur, vault_id: str, row: dict,
    label_cache: dict,
) -> str:


    kind = row.get("source_kind")
    pretty = _EXPIRY_TYPE_PRETTY.get(
        row.get("expiry_type") or "",
        (row.get("expiry_type") or "").replace("_", " ").title(),
    )

    if kind == "uploaded_file" and row.get("source_file_id"):
        ck = ("file", row["source_file_id"])
        if ck not in label_cache:
            try:
                cur.execute(
                    """SELECT saved_name, file_name FROM uploaded_files
                       WHERE id=%s AND vault_id=%s""",
                    (row["source_file_id"], vault_id),
                )
                r = cur.fetchone()
                if r:
                    label_cache[ck] = ((r[0] or r[1] or "").strip()
                                       or pretty)
                else:
                    label_cache[ck] = pretty
            except Exception:
                label_cache[ck] = pretty
        return label_cache[ck] or pretty

    if kind == "vault_item" and row.get("source_item_id") is not None:
        ck = ("item", row["source_item_id"])
        if ck not in label_cache:
            try:
                cur.execute(
                    """SELECT service FROM vault_items
                       WHERE id=%s AND vault_id=%s""",
                    (row["source_item_id"], vault_id),
                )
                r = cur.fetchone()
                if r and r[0]:
                    label_cache[ck] = r[0].strip().title()
                else:
                    label_cache[ck] = pretty
            except Exception:
                label_cache[ck] = pretty
        return label_cache[ck] or pretty

    if kind == "memory":
        return "Reminder"
    return pretty


class ExpiryActiveRequest(BaseModel):
    expiry_filter: Optional[str] = Field(None, max_length=40)
    limit: Optional[int] = Field(100, ge=1, le=500)


@router.post("/expiry/active")
async def expiry_active(
    payload: ExpiryActiveRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    print(
        f"[VAULT-DEBUG] /expiry/active ENTRY vault=...{str(vault_id)[-6:]}",
        flush=True,
    )
    logger.info(
        "[VAULT-DEBUG] /expiry/active ENTRY vault_id=%s "
        "expiry_filter=%s limit=%s",
        vault_id, payload.expiry_filter, payload.limit,
    )
    try:
        if not _is_enabled():
                                                                      
                                                                      
            return {"alerts": [], "counts": _empty_counts(), "engine": "off"}
        _rate_limit(vault_id)

        try:
            from expiry_engine import fetch_active_alerts, is_enabled
            if not is_enabled():
                return {"alerts": [], "counts": _empty_counts(), "engine": "off"}
        except Exception:
            return {"alerts": [], "counts": _empty_counts(), "engine": "unavailable"}

        rows = fetch_active_alerts(
            vault_id,
            expiry_type_filter=payload.expiry_filter,
            limit=payload.limit or 100,
        )
        if not rows:
            return {"alerts": [], "counts": _empty_counts(), "engine": "on"}

        label_cache: dict = {}
        conn = get_db()
        try:
            cur = conn.cursor()
            out: list[dict] = []
            counts = {"critical": 0, "warning": 0, "info": 0, "total": 0}
            for r in rows:
                sev = r.get("severity") or "info"
                label = _resolve_label(cur, vault_id, r, label_cache)
                etype = r.get("expiry_type") or ""
                pretty = _EXPIRY_TYPE_PRETTY.get(
                    etype, etype.replace("_", " ").title(),
                )
                out.append({
                    "id":              r.get("id"),
                    "doc_label":       label,
                    "expiry_type":     etype,
                    "expiry_type_label": pretty,
                    "expiry_date":     r.get("expiry_date"),
                    "days_until":      _days_until_today(r.get("expiry_date")),
                    "severity":        sev,
                    "source_kind":     r.get("source_kind"),
                    "alert_window_days": r.get("alert_window_days"),
                })
                if sev in counts:
                    counts[sev] += 1
                counts["total"] += 1
            return {"alerts": out, "counts": counts, "engine": "on"}
        finally:
            conn.close()
    except HTTPException:
                                                                  
                                                                
        raise
    except Exception as exc:
        return _safe_dashboard_response("/expiry/active", exc)


def _empty_counts() -> dict:
    return {"critical": 0, "warning": 0, "info": 0, "total": 0}
