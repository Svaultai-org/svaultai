

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device
from taxonomy import RELATION_TYPES
from vault_core import get_db


logger = logging.getLogger(__name__)
router = APIRouter()


RATE_PER_MIN = int(os.getenv("VAULTAI_RELATIONSHIP_DASHBOARD_RATE_PER_MIN", "30"))
_rate: "OrderedDict[str, list[float]]" = OrderedDict()


def _is_enabled() -> bool:

    return os.getenv(
        "VAULTAI_RELATIONSHIP_DASHBOARD_ENABLED", "true",
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


class RelationshipListRequest(BaseModel):
    relation_type: Optional[str] = Field(None, max_length=40)
    limit: Optional[int] = Field(500, ge=1, le=2000)


_ICON_HINTS = {
    "passport":       "passport",
    "visa":           "visa",
    "id_card":        "id_card",
    "driver_license": "driver_license",
    "invoice":        "invoice",
    "receipt":        "receipt",
    "contract":       "contract",
    "agreement":      "agreement",
    "insurance":      "insurance",
    "tax_document":   "tax",
    "medical_record": "medical",
    "certificate":    "business",
    "degree":         "business",
    "boarding_pass":  "travel",
    "hotel_itinerary":"travel",
    "ticket":         "travel",
    "login":          "memory",
    "card":           "finance",
    "id":             "id_card",
    "bank":           "finance",
}


def _icon_for(doc_type: Optional[str], item_type: Optional[str]) -> str:
    if doc_type:
        h = _ICON_HINTS.get(doc_type)
        if h:
            return h
    if item_type:
        h = _ICON_HINTS.get(item_type)
        if h:
            return h
    return "memory"                    


@router.post("/relationships/list")
async def relationships_list(
    payload: RelationshipListRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    print(
        f"[VAULT-DEBUG] /relationships/list ENTRY vault=...{str(vault_id)[-6:]}",
        flush=True,
    )
    logger.info(
        "[VAULT-DEBUG] /relationships/list ENTRY vault_id=%s "
        "relation_type=%s limit=%s",
        vault_id, payload.relation_type, payload.limit,
    )
    try:
        if not _is_enabled():
                                                                    
                                                                   
            return {"items": [], "counts": _empty_counts(), "engine": "off"}
        _rate_limit(vault_id)

        rel_filter = (payload.relation_type or "").strip().lower() or None
        if rel_filter and rel_filter not in RELATION_TYPES:
            rel_filter = None

        conn = get_db()
        try:
            cur = conn.cursor()

                                                      
            if rel_filter:
                cur.execute(
                    """SELECT id, source_kind, source_file_id, source_item_id,
                              target_kind, target_file_id, target_item_id,
                              relation_type, confidence, created_at, updated_at
                       FROM vault_relationships
                       WHERE vault_id=%s
                         AND relation_type=%s
                       ORDER BY relation_type ASC,
                                confidence DESC,
                                updated_at DESC
                       LIMIT %s""",
                    (vault_id, rel_filter, payload.limit or 500),
                )
            else:
                cur.execute(
                    """SELECT id, source_kind, source_file_id, source_item_id,
                              target_kind, target_file_id, target_item_id,
                              relation_type, confidence, created_at, updated_at
                       FROM vault_relationships
                       WHERE vault_id=%s
                       ORDER BY relation_type ASC,
                                confidence DESC,
                                updated_at DESC
                       LIMIT %s""",
                    (vault_id, payload.limit or 500),
                )
            rows = cur.fetchall() or []
            if not rows:
                return {
                    "items":  [],
                    "counts": _empty_counts(),
                    "engine": "on",
                }

                                                                    
            file_ids: set[str] = set()
            item_ids: set[int] = set()
            for r in rows:
                (_id, sk, sfid, siid, tk, tfid, tiid, *_rest) = r
                if sfid:
                    file_ids.add(sfid)
                if siid is not None:
                    item_ids.add(int(siid))
                if tfid:
                    file_ids.add(tfid)
                if tiid is not None:
                    item_ids.add(int(tiid))

            file_labels: dict[str, tuple[str, Optional[str]]] = {}
            if file_ids:
                cur.execute(
                    """SELECT u.id, u.saved_name, u.file_name, d.doc_type
                       FROM uploaded_files u
                       LEFT JOIN vault_document_metadata d
                              ON d.uploaded_file_id = u.id
                       WHERE u.id = ANY(%s)
                         AND u.vault_id = %s""",
                    (list(file_ids), vault_id),
                )
                for (fid, saved, fname, dtype) in cur.fetchall() or []:
                    label = (saved or fname or "file").strip() or "file"
                    file_labels[fid] = (label, dtype)

            item_labels: dict[int, tuple[str, Optional[str]]] = {}
            if item_ids:
                cur.execute(
                    """SELECT id, service, item_type FROM vault_items
                       WHERE id = ANY(%s)
                         AND vault_id = %s""",
                    (list(item_ids), vault_id),
                )
                for (iid, svc, itype) in cur.fetchall() or []:
                    svc_label = (svc or "untitled").strip().title() or "untitled"
                    item_labels[int(iid)] = (svc_label, itype)

            out: list[dict] = []
            counts: dict[str, int] = {}
            for r in rows:
                (rid, sk, sfid, siid, tk, tfid, tiid,
                 rel, conf, created_at, updated_at) = r
                src = _endpoint_dict(sk, sfid, siid, file_labels, item_labels)
                tgt = _endpoint_dict(tk, tfid, tiid, file_labels, item_labels)
                out.append({
                    "id":            rid,
                    "source":        src,
                    "target":        tgt,
                    "relation_type": rel,
                    "confidence":    float(conf or 1.0),
                    "created_at":    created_at.isoformat() if created_at else None,
                    "updated_at":    updated_at.isoformat() if updated_at else None,
                })
                counts[rel] = counts.get(rel, 0) + 1

            return {"items": out, "counts": counts, "engine": "on"}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as exc:
                                                                   
                                                                    
        print(
            f"[VAULT-DEBUG] /relationships/list DEGRADED "
            f"error_type={type(exc).__name__} repr={exc!r}",
            flush=True,
        )
        from routes.expiry_routes import _safe_dashboard_response
        return _safe_dashboard_response("/relationships/list", exc)


def _endpoint_dict(
    kind: str,
    file_id: Optional[str], item_id: Optional[int],
    file_labels: dict, item_labels: dict,
) -> dict:
    if kind == "uploaded_file" and file_id:
        label, dtype = file_labels.get(file_id, ("file", None))
        return {
            "kind":      "uploaded_file",
            "file_id":   file_id,
            "item_id":   None,
            "label":     label,
            "icon":      _icon_for(dtype, None),
            "sub_type":  dtype,
        }
    if kind == "vault_item" and item_id is not None:
        label, itype = item_labels.get(int(item_id), ("untitled", None))
        return {
            "kind":      "vault_item",
            "file_id":   None,
            "item_id":   int(item_id),
            "label":     label,
            "icon":      _icon_for(None, itype),
            "sub_type":  itype,
        }
    return {
        "kind":      kind,
        "file_id":   file_id,
        "item_id":   item_id,
        "label":     "asset",
        "icon":      "memory",
        "sub_type":  None,
    }


def _empty_counts() -> dict:
    return {}
