

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device
from taxonomy import ALLOWED_MEMORY_TYPES


logger = logging.getLogger(__name__)
router = APIRouter()


RATE_PER_MIN = int(os.getenv("VAULTAI_MEMORY_DASHBOARD_RATE_PER_MIN", "30"))
_rate: "OrderedDict[str, list[float]]" = OrderedDict()


def _is_enabled() -> bool:

    return os.getenv(
        "VAULTAI_MEMORY_DASHBOARD_ENABLED", "true",
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


class MemoryTimelineRequest(BaseModel):
    memory_type: Optional[str] = Field(None, max_length=40)
    limit: Optional[int] = Field(200, ge=1, le=500)


def _serialize_row(r: dict) -> dict:

    out = {
        "id":          r.get("id"),
        "memory_type": r.get("memory_type"),
        "memory_key":  r.get("memory_key"),
                                                                      
                                                                     
        "memory_value": r.get("memory_value"),
        "event_date":  r.get("event_date"),
        "confidence":  float(r.get("confidence") or 1.0),
        "created_at":  (r.get("created_at").isoformat()
                        if r.get("created_at") else None),
        "updated_at":  (r.get("updated_at").isoformat()
                        if r.get("updated_at") else None),
    }
    return out


@router.post("/memory/timeline")
async def memory_timeline_endpoint(
    payload: MemoryTimelineRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    print(
        f"[VAULT-DEBUG] /memory/timeline ENTRY vault=...{str(vault_id)[-6:]}",
        flush=True,
    )
    logger.info(
        "[VAULT-DEBUG] /memory/timeline ENTRY vault_id=%s "
        "memory_type=%s limit=%s",
        vault_id, payload.memory_type, payload.limit,
    )
    try:
        if not _is_enabled():
                                                                    
                                                                     
            return {"items": [], "counts": {}, "engine": "off"}
        _rate_limit(vault_id)

        filt = (payload.memory_type or "").strip().lower() or None
        if filt and filt not in ALLOWED_MEMORY_TYPES:
            filt = None                                 

        try:
            from memory_recall import memory_timeline
        except Exception:
            return {"items": [], "counts": {}, "engine": "unavailable"}

        try:
            rows = memory_timeline(
                vault_id,
                memory_type=filt, limit=payload.limit or 200,
            )
        except Exception as exc:
                                                                      
                                                                       
            print(
                f"[VAULT-DEBUG] /memory/timeline DEGRADED "
                f"error_type={type(exc).__name__} repr={exc!r}",
                flush=True,
            )
            return {"items": [], "counts": {}, "engine": "unavailable"}

        serialized = [_serialize_row(r) for r in rows]
        counts: dict[str, int] = {}
        for it in serialized:
            t = it.get("memory_type") or "unknown"
            counts[t] = counts.get(t, 0) + 1

        return {
            "items":  serialized,
            "counts": counts,
            "engine": "on",
        }
    except HTTPException:
        raise
    except Exception as exc:
        from routes.expiry_routes import _safe_dashboard_response
        return _safe_dashboard_response("/memory/timeline", exc)
