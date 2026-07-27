

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
from vault_core import verify_vault_pin


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


class MemoryListRequest(BaseModel):
    vault_name: Optional[str] = Field(None, max_length=100)
    pin: str = Field(..., min_length=1, max_length=128)
    query: Optional[str] = Field(None, max_length=200)
    memory_type: Optional[str] = Field(None, max_length=40)
    limit: Optional[int] = Field(200, ge=1, le=500)


class MemoryCreateRequest(BaseModel):
    vault_name: Optional[str] = Field(None, max_length=100)
    pin: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=120)
    value: str = Field(..., min_length=1, max_length=1000)
    body: Optional[str] = Field(None, max_length=2000)
    memory_type: Optional[str] = Field("note", max_length=40)
    category: Optional[str] = Field("personal", max_length=80)
    subject: Optional[str] = Field("self", max_length=80)
    subject_display: Optional[str] = Field(None, max_length=80)
    relationship: Optional[str] = Field("self", max_length=80)
    attribute: Optional[str] = Field("note", max_length=120)
    event_date: Optional[str] = Field(None, max_length=40)
    normalized_value: Optional[str] = Field(None, max_length=500)
    display_value: Optional[str] = Field(None, max_length=500)
    place: Optional[str] = Field(None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=20)
    canonical_key: Optional[str] = Field(None, max_length=180)
    proposal_id: Optional[str] = Field(None, max_length=80)


class MemoryUpdateRequest(MemoryCreateRequest):
    id: int = Field(..., ge=1)


class MemoryDeleteRequest(BaseModel):
    vault_name: Optional[str] = Field(None, max_length=100)
    pin: str = Field(..., min_length=1, max_length=128)
    id: int = Field(..., ge=1)


def _verified_vault_key(principal, pin: str) -> tuple[str, bytes]:
    vault_id = principal["vault_id"]
    key = verify_vault_pin(vault_id, pin)
    return vault_id, key


def _model_dict(payload: BaseModel) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


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


@router.post("/memory/list")
async def memory_list_endpoint(
    payload: MemoryListRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id, key = _verified_vault_key(principal, payload.pin)
    _rate_limit(vault_id)
    if not _is_enabled():
        return {"items": [], "counts": {}, "engine": "off"}
    try:
        from durable_personal_memory import list_memory_items

        return {
            **list_memory_items(
                vault_id=vault_id,
                key=key,
                query=payload.query,
                memory_type=payload.memory_type,
                limit=payload.limit or 200,
            ),
            "engine": "encrypted",
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "encrypted memory list failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="Memory list failed")


@router.post("/memory/create")
async def memory_create_endpoint(
    payload: MemoryCreateRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id, key = _verified_vault_key(principal, payload.pin)
    _rate_limit(vault_id)
    if not _is_enabled():
        raise HTTPException(status_code=503, detail="Memory is unavailable")
    try:
        from durable_personal_memory import (
            build_payload_from_request,
            save_memory_payload,
        )

        body = _model_dict(payload)
        body.pop("pin", None)
        body.pop("vault_name", None)
        result = save_memory_payload(
            vault_id=vault_id,
            key=key,
            payload=build_payload_from_request(body),
            source_message_id=payload.proposal_id,
            is_correction=True,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=500, detail="Memory save failed")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "encrypted memory create failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="Memory save failed")


@router.post("/memory/update")
async def memory_update_endpoint(
    payload: MemoryUpdateRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id, key = _verified_vault_key(principal, payload.pin)
    _rate_limit(vault_id)
    try:
        from durable_personal_memory import (
            build_payload_from_request,
            update_memory_item,
        )

        body = _model_dict(payload)
        memory_id = int(body.pop("id"))
        body.pop("pin", None)
        body.pop("vault_name", None)
        result = update_memory_item(
            vault_id=vault_id,
            key=key,
            memory_id=memory_id,
            payload=build_payload_from_request(body),
        )
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail="Memory not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "encrypted memory update failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="Memory update failed")


@router.post("/memory/delete")
async def memory_delete_endpoint(
    payload: MemoryDeleteRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id, key = _verified_vault_key(principal, payload.pin)
    _rate_limit(vault_id)
    try:
        from durable_personal_memory import delete_memory_item

        result = delete_memory_item(
            vault_id=vault_id,
            key=key,
            memory_id=payload.id,
        )
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail="Memory not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning(
            "encrypted memory delete failed vault=%s error_type=%s",
            (vault_id or "")[:8],
            type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="Memory delete failed")
