"""Default-off, bounded saved-item copy after old-link V2 readback proof.

Only ciphertext crosses the server. Owner rows remain untouched. This is one
content category, not a complete inheritance cutover or old-PIN retirement.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from rate_limit_sensitive import enforce_export_rate_limit
from subscription_entitlement import require_content_write
from vault_core import get_db
from routes.linked_inheritance_v2_upgrade_routes import (
    _b64, _decode, _feed, _load_releasable_old_link, _offer_commitment,
    _readback_proof_enabled, _verified_release_stage,
)


router = APIRouter(tags=["linked-inheritance-v2-item-import"])
FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_ITEM_IMPORT_ENABLED"
_MAX_ITEMS = 100
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_FIELD_BYTES = 128 * 1024
_MAX_DESTINATION_GROWTH = 4096
_ITEM_FIELDS = (
    "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
)


class CopyLinkedV2Item(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beneficiary_link_id: int = Field(gt=0)
    source_item_id: int = Field(gt=0)
    stage_revision: int = Field(gt=0)
    offer_commitment: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    source_inventory_sha256: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    source_row_sha256: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    item_type_ciphertext: str = Field(min_length=1, max_length=175000)
    service_ciphertext: str = Field(min_length=1, max_length=175000)
    payload_ciphertext: str = Field(min_length=1, max_length=175000)
    title_lookup_hash: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    content_scope: Literal["saved_items_only"]


def _enabled() -> None:
    _readback_proof_enabled()
    if os.getenv(FLAG_NAME, "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _context(cur, *, link_id: int, beneficiary_vault_id: str) -> tuple[dict, dict]:
    link, credential, state = _load_releasable_old_link(
        cur, link_id=link_id, beneficiary_vault_id=beneficiary_vault_id,
    )
    if state != "released":
        raise HTTPException(status_code=409, detail="release_not_complete")
    stage = _verified_release_stage(cur, link=link, credential=credential)
    revision = int(stage["stage_revision"])
    if (stage.get("owner_readback_public_key") is None or
            stage.get("owner_readback_revision") != revision or
            stage.get("owner_readback_commitment") !=
            _offer_commitment(link_id, stage) or
            stage.get("beneficiary_readback_revision") != revision or
            stage.get("beneficiary_readback_at") is None):
        raise HTTPException(status_code=409, detail="readback_receipt_required")
    return link, stage


def _item_hash(item: dict) -> bytes:
    h = hashlib.sha256(b"linked-old-v2-item-source/v1\x00")
    _feed(h, item["item_id"])
    for field in _ITEM_FIELDS:
        _feed(h, item[field])
    return h.digest()


def _inventory(
    cur, *, link_id: int, link: dict, stage: dict,
) -> tuple[list[dict], str, int]:
    owner_id = str(link["passer_vault_id"])
    cur.execute(
        """SELECT id,encrypted_data IS NOT NULL AS has_legacy,
                  item_type_ciphertext,service_ciphertext,payload_ciphertext
             FROM vault_items WHERE vault_id=%s
             ORDER BY id ASC LIMIT %s FOR SHARE""",
        (owner_id, _MAX_ITEMS + 1),
    )
    source = cur.fetchall() or []
    if len(source) > _MAX_ITEMS:
        raise HTTPException(status_code=409, detail="owner_items_exceed_import_limit")
    h = hashlib.sha256(b"linked-old-v2-item-inventory/v1\x00")
    for value in (
        link_id, owner_id, str(link["beneficiary_vault_id"]),
        int(stage["stage_revision"]),
    ):
        _feed(h, value)
    rows = []
    total = 0
    previous_id = 0
    for raw in source:
        item_id = raw["id"]
        if (not isinstance(item_id, int) or item_id <= previous_id or
                raw["has_legacy"]):
            raise HTTPException(status_code=409, detail="owner_items_not_private_ready")
        item = {"item_id": item_id}
        previous_id = item_id
        for field in _ITEM_FIELDS:
            value = raw.get(field)
            if value is None:
                raise HTTPException(
                    status_code=409, detail="owner_items_not_private_ready",
                )
            encoded = bytes(value)
            if (len(encoded) < 29 or len(encoded) > _MAX_FIELD_BYTES or
                    encoded[0] != 1):
                raise HTTPException(
                    status_code=409, detail="owner_item_ciphertext_invalid",
                )
            total += len(encoded)
            if total > _MAX_SOURCE_BYTES:
                raise HTTPException(
                    status_code=409, detail="owner_items_exceed_import_limit",
                )
            item[field] = encoded
        _feed(h, item_id)
        for field in _ITEM_FIELDS:
            _feed(h, item[field])
        item["source_row_sha256"] = _item_hash(item)
        rows.append(item)
    return rows, _b64(h.digest()), total


def _export_body(
    *, link_id: int, link: dict, stage: dict,
    rows: list[dict], digest: str, total: int,
) -> dict:
    return {
        "beneficiary_link_id": link_id,
        "owner_vault_id": str(link["passer_vault_id"]),
        "beneficiary_vault_id": str(link["beneficiary_vault_id"]),
        "stage_revision": int(stage["stage_revision"]),
        "offer_commitment": _offer_commitment(link_id, stage),
        "content_scope": "saved_items_only",
        "owner_content_complete": False,
        "source_inventory_sha256": digest,
        "item_count": len(rows),
        "ciphertext_bytes": total,
        "items": [
            {
                "item_id": row["item_id"],
                "source_row_sha256": _b64(row["source_row_sha256"]),
                **{field: _b64(row[field]) for field in _ITEM_FIELDS},
            }
            for row in rows
        ],
    }


def _destination_fields(payload: CopyLinkedV2Item) -> dict[str, bytes]:
    fields = {}
    for field in _ITEM_FIELDS:
        raw = _decode(getattr(payload, field), low=29, high=_MAX_FIELD_BYTES)
        if raw[0] != 1:
            raise HTTPException(status_code=400, detail="invalid_item_ciphertext")
        fields[field] = raw
    fields["title_lookup_hash"] = _decode(
        payload.title_lookup_hash, low=32, high=32,
    )
    return fields


@router.get("/inheritance/old-link-v2/{link_id}/vault-items")
def export_linked_v2_items(
    link_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    if link_id <= 0:
        raise HTTPException(status_code=404, detail="not_found")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        enforce_export_rate_limit(vault_id=str(principal["vault_id"]))
        rows, digest, total = _inventory(
            cur, link_id=link_id, link=link, stage=stage,
        )
        return _export_body(
            link_id=link_id, link=link, stage=stage,
            rows=rows, digest=digest, total=total,
        )
    finally:
        conn.close()


@router.post("/inheritance/old-link-v2/item-copy")
def copy_linked_v2_item(
    payload: CopyLinkedV2Item,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    require_content_write(principal)
    destination = _destination_fields(payload)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=payload.beneficiary_link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        rows, digest, _ = _inventory(
            cur, link_id=payload.beneficiary_link_id,
            link=link, stage=stage,
        )
        if (payload.stage_revision != stage["stage_revision"] or
                payload.offer_commitment !=
                _offer_commitment(payload.beneficiary_link_id, stage) or
                payload.source_inventory_sha256 != digest):
            raise HTTPException(status_code=409, detail="source_inventory_changed")
        source = next(
            (row for row in rows if row["item_id"] == payload.source_item_id),
            None,
        )
        if (source is None or payload.source_row_sha256 !=
                _b64(source["source_row_sha256"])):
            raise HTTPException(status_code=409, detail="source_item_changed")
        if sum(len(destination[field]) for field in _ITEM_FIELDS) > (
                sum(len(source[field]) for field in _ITEM_FIELDS) +
                _MAX_DESTINATION_GROWTH):
            raise HTTPException(status_code=409, detail="item_copy_exceeds_bound")
        cur.execute(
            """SELECT source_item_id,beneficiary_item_id,
                      beneficiary_vault_id,stage_revision,
                      source_inventory_sha256,source_row_sha256
                 FROM linked_inheritance_v2_item_copies
                WHERE old_link_id=%s ORDER BY source_item_id FOR UPDATE""",
            (payload.beneficiary_link_id,),
        )
        prior = cur.fetchall() or []
        for row in prior:
            if (str(row["beneficiary_vault_id"]) !=
                    str(principal["vault_id"]) or
                    int(row["stage_revision"]) !=
                    payload.stage_revision or
                    row["source_inventory_sha256"] != digest):
                raise HTTPException(
                    status_code=409, detail="prior_copy_inventory_changed",
                )
        existing = next(
            (row for row in prior if row["source_item_id"] ==
             payload.source_item_id), None,
        )
        if existing is not None:
            if bytes(existing["source_row_sha256"]) != source["source_row_sha256"]:
                raise HTTPException(status_code=409, detail="source_item_changed")
            conn.commit()
            return {
                "beneficiary_link_id": payload.beneficiary_link_id,
                "source_item_id": payload.source_item_id,
                "beneficiary_item_id": int(existing["beneficiary_item_id"]),
                "source_inventory_sha256": digest,
                "created": False,
                "legacy_package_preserved": True,
            }
        # An unindexed V2 destination row could already use this private
        # title, while the server cannot derive its hash from ciphertext.
        # Require the same private-index readiness as strict item creates.
        cur.execute(
            """SELECT 1 FROM vault_items
                WHERE vault_id=%s AND encrypted_data IS NULL
                  AND item_type_ciphertext IS NOT NULL
                  AND service_ciphertext IS NOT NULL
                  AND payload_ciphertext IS NOT NULL
                  AND title_lookup_hash IS NULL LIMIT 1""",
            (principal["vault_id"],),
        )
        if cur.fetchone():
            raise HTTPException(
                status_code=409, detail="beneficiary_item_index_required",
            )
        cur.execute(
            """INSERT INTO vault_items (
                  vault_id,item_type,service,encrypted_data,
                  item_type_ciphertext,service_ciphertext,
                  payload_ciphertext,title_lookup_hash)
                VALUES (%s,NULL,NULL,NULL,%s,%s,%s,%s)
                RETURNING id""",
            (principal["vault_id"],
             *(destination[field] for field in _ITEM_FIELDS),
             destination["title_lookup_hash"]),
        )
        item_id = int(cur.fetchone()["id"])
        cur.execute(
            """INSERT INTO linked_inheritance_v2_item_copies (
                  old_link_id,source_item_id,beneficiary_vault_id,
                  beneficiary_item_id,stage_revision,
                  source_inventory_sha256,source_row_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (payload.beneficiary_link_id, payload.source_item_id,
             principal["vault_id"], item_id, payload.stage_revision,
             digest, source["source_row_sha256"]),
        )
        conn.commit()
        return {
            "beneficiary_link_id": payload.beneficiary_link_id,
            "source_item_id": payload.source_item_id,
            "beneficiary_item_id": item_id,
            "source_inventory_sha256": digest,
            "created": True,
            "legacy_package_preserved": True,
        }
    except UniqueViolation as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail="item_copy_conflict") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/inheritance/old-link-v2/{link_id}/item-copies")
def readback_linked_v2_item_copies(
    link_id: int,
    source_inventory_sha256: str = Query(pattern=r"^[A-Za-z0-9_-]{43}$"),
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    if link_id <= 0:
        raise HTTPException(status_code=404, detail="not_found")
    if (not isinstance(source_inventory_sha256, str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{43}", source_inventory_sha256)):
        raise HTTPException(status_code=400, detail="invalid_source_inventory")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        enforce_export_rate_limit(vault_id=str(principal["vault_id"]))
        rows, digest, _ = _inventory(
            cur, link_id=link_id, link=link, stage=stage,
        )
        if digest != source_inventory_sha256:
            raise HTTPException(status_code=409, detail="source_inventory_changed")
        cur.execute(
            """SELECT c.source_item_id,c.beneficiary_item_id,
                      c.beneficiary_vault_id,c.stage_revision,
                      c.source_inventory_sha256,c.source_row_sha256,
                      v.vault_id AS destination_vault_id,
                      v.item_type_ciphertext,v.service_ciphertext,
                      v.payload_ciphertext,v.title_lookup_hash
                 FROM linked_inheritance_v2_item_copies c
                 JOIN vault_items v ON v.id=c.beneficiary_item_id
                WHERE c.old_link_id=%s ORDER BY c.source_item_id
                FOR SHARE OF c,v""",
            (link_id,),
        )
        copies = cur.fetchall() or []
        source_by_id = {row["item_id"]: row for row in rows}
        if len(copies) > len(rows):
            raise HTTPException(status_code=409, detail="item_copy_mismatch")
        rendered = []
        total = 0
        for row in copies:
            source = source_by_id.get(row["source_item_id"])
            if (source is None or
                    str(row["beneficiary_vault_id"]) !=
                    str(principal["vault_id"]) or
                    str(row["destination_vault_id"]) !=
                    str(principal["vault_id"]) or
                    int(row["stage_revision"]) != int(stage["stage_revision"]) or
                    row["source_inventory_sha256"] != digest or
                    bytes(row["source_row_sha256"]) !=
                    source["source_row_sha256"]):
                raise HTTPException(status_code=409, detail="item_copy_mismatch")
            destination = {}
            for field in _ITEM_FIELDS:
                raw = row.get(field)
                if raw is None:
                    raise HTTPException(status_code=409, detail="item_copy_mismatch")
                encoded = bytes(raw)
                if len(encoded) < 29 or encoded[0] != 1:
                    raise HTTPException(status_code=409, detail="item_copy_mismatch")
                total += len(encoded)
                if total > _MAX_SOURCE_BYTES + len(rows) * _MAX_DESTINATION_GROWTH:
                    raise HTTPException(status_code=409, detail="item_copy_exceeds_bound")
                destination[field] = _b64(encoded)
            title_hash = row.get("title_lookup_hash")
            if title_hash is None or len(bytes(title_hash)) != 32:
                raise HTTPException(status_code=409, detail="item_copy_mismatch")
            rendered.append({
                "source_item_id": int(row["source_item_id"]),
                "beneficiary_item_id": int(row["beneficiary_item_id"]),
                "source_row_sha256": _b64(source["source_row_sha256"]),
                "title_lookup_hash": _b64(bytes(title_hash)),
                **destination,
            })
        return {
            "beneficiary_link_id": link_id,
            "owner_vault_id": str(link["passer_vault_id"]),
            "beneficiary_vault_id": str(link["beneficiary_vault_id"]),
            "stage_revision": int(stage["stage_revision"]),
            "offer_commitment": _offer_commitment(link_id, stage),
            "content_scope": "saved_items_only",
            "owner_content_complete": False,
            "source_inventory_sha256": digest,
            "item_count": len(rows),
            "copies": rendered,
            "all_items_copied": len(rendered) == len(rows),
            "legacy_package_preserved": True,
        }
    finally:
        conn.close()
