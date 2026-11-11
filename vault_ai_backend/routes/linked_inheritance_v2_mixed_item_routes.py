"""Default-off complete saved-item inventory for mixed old/new owner rows.

Both source formats are returned as ciphertext in one exact inventory. Copy
and readback use the same digest so either format cannot silently disappear.
No PIN or content key is accepted by these routes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from rate_limit_sensitive import enforce_export_rate_limit
from vault_core import get_db
from routes.linked_inheritance_v2_upgrade_routes import (
    _b64, _feed, _offer_commitment, _readback_proof_enabled,
)
from routes.linked_inheritance_v2_item_import_routes import (
    CopyLinkedV2LegacyItem, _context, _copy_bounded_source_item,
    _readback_bounded_source_item_copies, _ITEM_FIELDS,
    _MAX_FIELD_BYTES, _MAX_ITEMS, _MAX_SOURCE_BYTES,
)


router = APIRouter(tags=["linked-inheritance-v2-mixed-item-import"])
FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_MIXED_ITEM_COPY_ENABLED"
_SCOPE = "mixed_saved_items_only"


class CopyLinkedV2MixedItem(CopyLinkedV2LegacyItem):
    content_scope: Literal["mixed_saved_items_only"]


def _enabled() -> None:
    _readback_proof_enabled()
    if os.getenv(FLAG_NAME, "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _inventory(cur, *, link_id: int, link: dict, stage: dict) -> dict:
    owner_id = str(link["passer_vault_id"])
    # A parent row lock excludes concurrent FK inserts; the item locks exclude
    # edits and deletes until export/copy/readback finishes this transaction.
    cur.execute(
        "SELECT vault_id FROM vaults WHERE vault_id=%s FOR UPDATE",
        (owner_id,),
    )
    if not cur.fetchone():
        raise HTTPException(status_code=409, detail="owner_vault_changed")
    cur.execute(
        """SELECT id,item_type,service,
                  encrypted_data IS NOT NULL AS has_legacy,
                  octet_length(encrypted_data) AS legacy_bytes,
                  CASE WHEN octet_length(encrypted_data) <= %s
                       THEN encrypted_data ELSE NULL END AS encrypted_data,
                  CASE WHEN octet_length(item_type_ciphertext) <= %s
                       THEN item_type_ciphertext ELSE NULL END
                       AS item_type_ciphertext,
                  CASE WHEN octet_length(service_ciphertext) <= %s
                       THEN service_ciphertext ELSE NULL END
                       AS service_ciphertext,
                  CASE WHEN octet_length(payload_ciphertext) <= %s
                       THEN payload_ciphertext ELSE NULL END
                       AS payload_ciphertext
             FROM vault_items WHERE vault_id=%s
             ORDER BY id ASC LIMIT %s FOR SHARE""",
        (_MAX_SOURCE_BYTES, _MAX_FIELD_BYTES, _MAX_FIELD_BYTES,
         _MAX_FIELD_BYTES, owner_id, _MAX_ITEMS + 1),
    )
    raw_rows = cur.fetchall() or []
    if len(raw_rows) > _MAX_ITEMS:
        raise HTTPException(status_code=409, detail="owner_items_exceed_import_limit")
    digest = hashlib.sha256(b"linked-old-v2-mixed-item-inventory/v1\x00")
    for value in (
        link_id, owner_id, str(link["beneficiary_vault_id"]),
        int(stage["stage_revision"]),
    ):
        _feed(digest, value)
    rendered = []
    previous_id = 0
    total = 0
    for raw in raw_rows:
        item_id = raw.get("id")
        if not isinstance(item_id, int) or item_id <= previous_id:
            raise HTTPException(status_code=409, detail="owner_item_invalid")
        previous_id = item_id
        legacy = raw.get("has_legacy")
        if legacy is True:
            item_type = raw.get("item_type")
            service = raw.get("service")
            ciphertext = raw.get("encrypted_data")
            size = raw.get("legacy_bytes")
            if (not isinstance(item_type, str) or
                    not item_type.strip() or
                    len(item_type.encode("utf-8")) > 256 or
                    not isinstance(service, str) or
                    not service.strip() or
                    len(service.encode("utf-8")) > 256 or
                    not isinstance(ciphertext, str) or
                    not isinstance(size, int) or
                    size != len(ciphertext.encode("utf-8")) or
                    size > _MAX_SOURCE_BYTES):
                raise HTTPException(status_code=409, detail="owner_item_invalid")
            try:
                decoded = base64.b64decode(ciphertext, validate=True)
            except (ValueError, binascii.Error):
                raise HTTPException(status_code=409, detail="owner_item_invalid")
            if len(decoded) < 28:
                raise HTTPException(status_code=409, detail="owner_item_invalid")
            kind = "legacy"
            source_fields = (item_type, service, ciphertext)
            item = {
                "item_id": item_id, "source_kind": kind,
                "item_type": item_type, "service": service,
                "encrypted_data": ciphertext,
            }
            total += size
        elif legacy is False:
            kind = "private"
            item = {"item_id": item_id, "source_kind": kind}
            source_fields = []
            for field in _ITEM_FIELDS:
                value = raw.get(field)
                if value is None:
                    raise HTTPException(status_code=409, detail="owner_item_invalid")
                encoded = bytes(value)
                if (not 29 <= len(encoded) <= _MAX_FIELD_BYTES or
                        encoded[0] != 1):
                    raise HTTPException(status_code=409, detail="owner_item_invalid")
                total += len(encoded)
                source_fields.append(encoded)
                item[field] = _b64(encoded)
        else:
            raise HTTPException(status_code=409, detail="owner_item_invalid")
        if total > _MAX_SOURCE_BYTES:
            raise HTTPException(status_code=409, detail="owner_items_exceed_import_limit")
        row_hash = hashlib.sha256(b"linked-old-v2-mixed-item-source/v1\x00")
        for value in (item_id, kind, *source_fields):
            _feed(row_hash, value)
        row_digest = row_hash.digest()
        _feed(digest, item_id)
        _feed(digest, kind)
        _feed(digest, row_digest)
        item["source_row_sha256"] = _b64(row_digest)
        rendered.append(item)
    return {
        "beneficiary_link_id": link_id,
        "owner_vault_id": owner_id,
        "beneficiary_vault_id": str(link["beneficiary_vault_id"]),
        "stage_revision": int(stage["stage_revision"]),
        "offer_commitment": _offer_commitment(link_id, stage),
        "content_scope": _SCOPE,
        "owner_content_complete": False,
        "source_inventory_sha256": _b64(digest.digest()),
        "item_count": len(rendered),
        "ciphertext_bytes": total,
        "items": rendered,
    }


@router.get("/inheritance/old-link-v2/{link_id}/mixed-vault-items")
def export_mixed_items(
    link_id: int,
    response: Response,
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
        inventory = _inventory(cur, link_id=link_id, link=link, stage=stage)
        response.headers["Cache-Control"] = "no-store"
        return inventory
    finally:
        conn.close()


@router.post("/inheritance/old-link-v2/mixed-item-copy")
def copy_mixed_item(
    payload: CopyLinkedV2MixedItem,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    return _copy_bounded_source_item(payload, principal, _inventory)


@router.get("/inheritance/old-link-v2/{link_id}/mixed-item-copies")
def readback_mixed_item_copies(
    link_id: int,
    response: Response,
    source_inventory_sha256: str = Query(pattern=r"^[A-Za-z0-9_-]{43}$"),
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    return _readback_bounded_source_item_copies(
        link_id, response, source_inventory_sha256, principal, _inventory,
    )
