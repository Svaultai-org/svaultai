"""Default-off, bounded saved-item copy after old-link V2 readback proof.

Only ciphertext crosses the server. Owner rows remain untouched. This is one
content category, not a complete inheritance cutover or old-PIN retirement.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import base64
import binascii
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from rate_limit_sensitive import enforce_export_rate_limit
from subscription_entitlement import require_content_write
from vault_core import get_db
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from routes.linked_inheritance_v2_upgrade_routes import (
    _b64, _decode, _feed, _load_releasable_old_link, _offer_commitment,
    _readback_proof_enabled, _verified_release_stage,
)


router = APIRouter(tags=["linked-inheritance-v2-item-import"])
FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_ITEM_IMPORT_ENABLED"
LEGACY_EXPORT_FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_LEGACY_ITEM_EXPORT_ENABLED"
LEGACY_COPY_FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_LEGACY_ITEM_COPY_ENABLED"
_MAX_ITEMS = 100
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_FIELD_BYTES = 128 * 1024
_MAX_DESTINATION_GROWTH = 4096
_ITEM_FIELDS = (
    "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
)
_RESTART_CONFIRMATION = "DELETE_UNCHANGED_INHERITED_COPIES"
_RESTART_TTL = timedelta(minutes=10)
# Every known FK to vault_items except the import's own mapping. A new FK must
# be reviewed before this deletion route is allowed to run.
_ITEM_REFERENCE_COLUMNS = {
    ("semantic_index", "vault_item_id"),
    ("vault_asset_tags", "vault_item_id"),
    ("vault_password_audit", "vault_item_id"),
    ("vault_relationships", "source_item_id"),
    ("vault_relationships", "target_item_id"),
    ("vault_expiry_alerts", "source_item_id"),
    ("legacy_item_edit_candidates", "item_id"),
    ("linked_inheritance_v2_item_copies", "beneficiary_item_id"),
}


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


class CopyLinkedV2LegacyItem(BaseModel):
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
    content_scope: Literal["legacy_saved_items_only"]


class ConfirmLinkedV2ItemRestart(BaseModel):
    """A separate, explicit destructive action after a prepared review."""

    model_config = ConfigDict(extra="forbid")
    beneficiary_link_id: int = Field(gt=0)
    restart_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    stage_revision: int = Field(gt=0)
    offer_commitment: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    old_source_inventory_sha256: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    current_source_inventory_sha256: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    copies_sha256: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    copy_count: int = Field(gt=0, le=_MAX_ITEMS)
    confirmation: Literal["DELETE_UNCHANGED_INHERITED_COPIES"]
    zk_proof_token: str = Field(min_length=1, max_length=128)


def _enabled() -> None:
    _readback_proof_enabled()
    if os.getenv(FLAG_NAME, "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _restart_enabled() -> None:
    _enabled()
    if (os.getenv("VAULTAI_ZK_LINKED_BENEFICIARY_ITEM_RESTART_ENABLED", "false")
            .strip().lower() != "true"):
        raise HTTPException(status_code=404, detail="not_found")


def _legacy_export_enabled() -> None:
    # A released link and a verified device-side readback are both required.
    # Keep this separate from private-item copying until legacy rows have a
    # complete client-side decrypt, re-encrypt, and readback implementation.
    _readback_proof_enabled()
    if os.getenv(LEGACY_EXPORT_FLAG_NAME, "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _legacy_copy_enabled() -> None:
    _legacy_export_enabled()
    if os.getenv(LEGACY_COPY_FLAG_NAME, "false").strip().lower() != "true":
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


def _legacy_item_inventory(
    cur, *, link_id: int, link: dict, stage: dict,
) -> dict:
    """Export bounded, still-encrypted old items after the release ceremony.

    The owner key is never reconstructed here. The beneficiary's released
    envelope may contain that key, but only their device can open it.
    """
    owner_id = str(link["passer_vault_id"])
    cur.execute(
        """SELECT id,item_type,service,
                  encrypted_data IS NULL AS has_private,
                  octet_length(encrypted_data) AS ciphertext_bytes,
                  CASE WHEN octet_length(encrypted_data) <= %s
                       THEN encrypted_data ELSE NULL END AS encrypted_data
             FROM vault_items
            WHERE vault_id=%s
            ORDER BY id ASC LIMIT %s FOR SHARE""",
        (_MAX_SOURCE_BYTES, owner_id, _MAX_ITEMS + 1),
    )
    source = cur.fetchall() or []
    if len(source) > _MAX_ITEMS:
        raise HTTPException(status_code=409, detail="owner_items_exceed_import_limit")
    digest = hashlib.sha256(b"linked-old-v2-legacy-item-inventory/v1\x00")
    for value in (
        link_id, owner_id, str(link["beneficiary_vault_id"]),
        int(stage["stage_revision"]),
    ):
        _feed(digest, value)
    rendered = []
    total = 0
    previous_id = 0
    for row in source:
        if row.get("has_private"):
            raise HTTPException(
                status_code=409, detail="mixed_saved_item_modes_unsupported",
            )
        item_id = row.get("id")
        item_type = row.get("item_type")
        service = row.get("service")
        ciphertext = row.get("encrypted_data")
        declared_size = row.get("ciphertext_bytes")
        if (not isinstance(item_id, int) or item_id <= previous_id or
                not isinstance(item_type, str) or
                not isinstance(service, str) or
                len(item_type.encode("utf-8")) > 256 or
                len(service.encode("utf-8")) > 256 or
                not isinstance(ciphertext, str) or
                not isinstance(declared_size, int) or
                declared_size != len(ciphertext.encode("utf-8")) or
                declared_size > _MAX_SOURCE_BYTES):
            raise HTTPException(status_code=409, detail="owner_legacy_item_invalid")
        try:
            decoded = base64.b64decode(ciphertext, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(status_code=409, detail="owner_legacy_item_invalid")
        if len(decoded) < 28:
            raise HTTPException(status_code=409, detail="owner_legacy_item_invalid")
        total += declared_size
        if total > _MAX_SOURCE_BYTES:
            raise HTTPException(status_code=409, detail="owner_items_exceed_import_limit")
        previous_id = item_id
        row_hash = hashlib.sha256(b"linked-old-v2-legacy-item-source/v1\x00")
        for value in (item_id, item_type, service, ciphertext):
            _feed(row_hash, value)
        _feed(digest, item_id)
        _feed(digest, row_hash.digest())
        rendered.append({
            "item_id": item_id,
            "item_type": item_type,
            "service": service,
            "encrypted_data": ciphertext,
            "source_row_sha256": _b64(row_hash.digest()),
        })
    return {
        "beneficiary_link_id": link_id,
        "owner_vault_id": owner_id,
        "beneficiary_vault_id": str(link["beneficiary_vault_id"]),
        "stage_revision": int(stage["stage_revision"]),
        "offer_commitment": _offer_commitment(link_id, stage),
        "content_scope": "legacy_saved_items_only",
        "owner_content_complete": False,
        "source_inventory_sha256": _b64(digest.digest()),
        "item_count": len(rendered),
        "ciphertext_bytes": total,
        "items": rendered,
    }


def _destination_fields(
    payload: CopyLinkedV2Item | CopyLinkedV2LegacyItem,
) -> dict[str, bytes]:
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


def _destination_hash(
    *, link_id: int, source_item_id: int, beneficiary_vault_id: str,
    beneficiary_item_id: int, row: dict,
) -> bytes:
    """Bind the original copied row, including its identity and mutable shape."""
    h = hashlib.sha256(b"linked-old-v2-item-destination/v1\x00")
    for value in (
        link_id, source_item_id, beneficiary_vault_id, beneficiary_item_id,
        row.get("item_type"), row.get("service"), row.get("encrypted_data"),
        row.get("title_revision"), row.get("legacy_item_rename_active"),
        row.get("title_lookup_hash"),
        *(row.get(field) for field in _ITEM_FIELDS),
    ):
        _feed(h, value)
    return h.digest()


def _lock_restart_vaults(cur, link: dict) -> None:
    # Locking the vault rows also blocks new vault_items FK inserts while the
    # owner inventory and destination set are being checked. The link was
    # already locked by _context, so concurrent copy/restart calls serialize.
    cur.execute(
        """SELECT vault_id FROM vaults
            WHERE vault_id IN (%s,%s) ORDER BY vault_id FOR UPDATE""",
        (str(link["passer_vault_id"]), str(link["beneficiary_vault_id"])),
    )
    if {str(row["vault_id"]) for row in (cur.fetchall() or [])} != {
            str(link["passer_vault_id"]), str(link["beneficiary_vault_id"])}:
        raise HTTPException(status_code=409, detail="restart_vault_changed")


def _restart_copy_state(
    cur, *, link_id: int, beneficiary_vault_id: str,
    stage_revision: int, current_inventory: str,
) -> dict:
    cur.execute(
        """SELECT c.source_item_id,c.beneficiary_item_id,
                  c.beneficiary_vault_id,c.stage_revision,
                  c.source_inventory_sha256,c.destination_ciphertext_sha256,
                  v.vault_id AS destination_vault_id,v.item_type,v.service,
                  v.encrypted_data,v.title_revision,
                  v.legacy_item_rename_active,v.title_lookup_hash,
                  v.item_type_ciphertext,v.service_ciphertext,
                  v.payload_ciphertext
             FROM linked_inheritance_v2_item_copies c
             JOIN vault_items v ON v.id=c.beneficiary_item_id
            WHERE c.old_link_id=%s ORDER BY c.source_item_id
            FOR UPDATE OF c,v""",
        (link_id,),
    )
    copies = cur.fetchall() or []
    if not 0 < len(copies) <= _MAX_ITEMS:
        raise HTTPException(status_code=409, detail="restart_copies_unavailable")
    previous_source_id = 0
    previous_inventory = None
    h = hashlib.sha256(b"linked-old-v2-item-restart-copies/v1\x00")
    for copy in copies:
        source_id = copy["source_item_id"]
        dest_id = copy["beneficiary_item_id"]
        old_inventory = copy["source_inventory_sha256"]
        original_hash = copy.get("destination_ciphertext_sha256")
        if (not isinstance(source_id, int) or source_id <= previous_source_id or
                not isinstance(dest_id, int) or dest_id <= 0 or
                str(copy["beneficiary_vault_id"]) != beneficiary_vault_id or
                str(copy["destination_vault_id"]) != beneficiary_vault_id or
                int(copy["stage_revision"]) != stage_revision or
                not isinstance(old_inventory, str) or
                (previous_inventory is not None and
                 old_inventory != previous_inventory) or
                original_hash is None or len(bytes(original_hash)) != 32 or
                copy.get("item_type") is not None or
                copy.get("service") is not None or
                copy.get("encrypted_data") is not None or
                copy.get("title_revision") != 0 or
                copy.get("legacy_item_rename_active") is not False or
                copy.get("title_lookup_hash") is None or
                len(bytes(copy["title_lookup_hash"])) != 32 or
                any(copy.get(field) is None for field in _ITEM_FIELDS)):
            raise HTTPException(status_code=409, detail="restart_copy_changed")
        if any(not 29 <= len(bytes(copy[field])) <= _MAX_FIELD_BYTES or
               bytes(copy[field])[0] != 1 for field in _ITEM_FIELDS):
            raise HTTPException(status_code=409, detail="restart_copy_changed")
        actual_hash = _destination_hash(
            link_id=link_id, source_item_id=source_id,
            beneficiary_vault_id=beneficiary_vault_id,
            beneficiary_item_id=dest_id, row=copy,
        )
        if not hmac.compare_digest(actual_hash, bytes(original_hash)):
            raise HTTPException(status_code=409, detail="restart_copy_changed")
        _feed(h, source_id)
        _feed(h, dest_id)
        _feed(h, actual_hash)
        previous_source_id = source_id
        previous_inventory = old_inventory
    if previous_inventory == current_inventory:
        raise HTTPException(status_code=409, detail="restart_not_needed")
    return {
        "old_inventory": previous_inventory,
        "copies_digest": h.digest(),
        "copies": copies,
    }


def _assert_no_restart_dependents(cur, destination_ids: list[int]) -> None:
    # A new FK or an existing tag/relationship/alert must not be silently
    # cascaded when a copied item is removed. The parent rows are FOR UPDATE,
    # which blocks concurrent FK inserts while these checks run.
    cur.execute(
        """SELECT c.conrelid::regclass::text AS table_name,
                  array_agg(a.attname ORDER BY k.ordinality) AS column_names
             FROM pg_constraint c
             CROSS JOIN LATERAL unnest(c.conkey)
                  WITH ORDINALITY AS k(attnum,ordinality)
             JOIN pg_attribute a
               ON a.attrelid=c.conrelid AND a.attnum=k.attnum
            WHERE c.contype='f' AND c.confrelid='vault_items'::regclass
            GROUP BY c.oid""",
        (),
    )
    references = cur.fetchall() or []
    observed = {
        (row["table_name"].split(".")[-1], row["column_names"][0])
        for row in references if len(row["column_names"]) == 1
    }
    if (len(references) != len(_ITEM_REFERENCE_COLUMNS) or
            observed != _ITEM_REFERENCE_COLUMNS):
        raise HTTPException(status_code=409, detail="restart_references_changed")
    cur.execute(
        """SELECT (
            EXISTS(SELECT 1 FROM semantic_index WHERE vault_item_id=ANY(%s)) OR
            EXISTS(SELECT 1 FROM vault_asset_tags WHERE vault_item_id=ANY(%s)) OR
            EXISTS(SELECT 1 FROM vault_password_audit WHERE vault_item_id=ANY(%s)) OR
            EXISTS(SELECT 1 FROM vault_relationships
                    WHERE source_item_id=ANY(%s) OR target_item_id=ANY(%s)) OR
            EXISTS(SELECT 1 FROM vault_expiry_alerts WHERE source_item_id=ANY(%s)) OR
            EXISTS(SELECT 1 FROM legacy_item_edit_candidates WHERE item_id=ANY(%s)) OR
            EXISTS(SELECT 1 FROM legacy_item_edit_history WHERE item_id=ANY(%s)) OR
            EXISTS(SELECT 1 FROM wallet_v2_records WHERE legacy_item_id=ANY(%s))
          ) AS has_dependents""",
        (destination_ids,) * 9,
    )
    result = cur.fetchone()
    if result is None or result["has_dependents"]:
        raise HTTPException(status_code=409, detail="restart_copy_has_dependents")


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


@router.get("/inheritance/old-link-v2/{link_id}/legacy-vault-items")
def export_linked_v2_legacy_items(
    link_id: int,
    response: Response,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Release-gated legacy ciphertext for a future local rewrap flow."""
    _legacy_export_enabled()
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
        result = _legacy_item_inventory(
            cur, link_id=link_id, link=link, stage=stage,
        )
        response.headers["Cache-Control"] = "no-store"
        return result
    finally:
        conn.close()


def _legacy_copies(
    cur, *, link_id: int, inventory: dict, beneficiary_vault_id: str,
    for_update: bool,
) -> list[dict]:
    lock = "UPDATE" if for_update else "SHARE"
    cur.execute(
        f"""SELECT c.source_item_id,c.beneficiary_item_id,
                   c.beneficiary_vault_id,c.stage_revision,
                   c.source_inventory_sha256,c.source_row_sha256,
                   c.destination_ciphertext_sha256,
                   v.vault_id AS destination_vault_id,
                   v.item_type,v.service,v.encrypted_data,
                   v.title_revision,v.legacy_item_rename_active,
                   v.title_lookup_hash,v.item_type_ciphertext,
                   v.service_ciphertext,v.payload_ciphertext
              FROM linked_inheritance_v2_item_copies c
              JOIN vault_items v ON v.id=c.beneficiary_item_id
             WHERE c.old_link_id=%s ORDER BY c.source_item_id
             FOR {lock} OF c,v""",
        (link_id,),
    )
    copies = cur.fetchall() or []
    sources = {row["item_id"]: row for row in inventory["items"]}
    if len(copies) > len(sources):
        raise HTTPException(status_code=409, detail="legacy_item_copy_mismatch")
    seen = set()
    destination_bytes = 0
    for copy in copies:
        source_id = copy["source_item_id"]
        source = sources.get(source_id)
        if (source is None or source_id in seen or
                str(copy["beneficiary_vault_id"]) != beneficiary_vault_id or
                str(copy["destination_vault_id"]) != beneficiary_vault_id or
                int(copy["stage_revision"]) != inventory["stage_revision"] or
                copy["source_inventory_sha256"] !=
                inventory["source_inventory_sha256"] or
                bytes(copy["source_row_sha256"]) !=
                _decode(source["source_row_sha256"], low=32, high=32) or
                copy.get("item_type") is not None or
                copy.get("service") is not None or
                copy.get("encrypted_data") is not None):
            raise HTTPException(status_code=409, detail="legacy_item_copy_mismatch")
        seen.add(source_id)
        title_hash = copy.get("title_lookup_hash")
        original_hash = copy.get("destination_ciphertext_sha256")
        if (title_hash is None or len(bytes(title_hash)) != 32 or
                original_hash is None or len(bytes(original_hash)) != 32):
            raise HTTPException(status_code=409, detail="legacy_item_copy_mismatch")
        for field in _ITEM_FIELDS:
            raw = copy.get(field)
            if (raw is None or not 29 <= len(bytes(raw)) <= _MAX_FIELD_BYTES or
                    bytes(raw)[0] != 1):
                raise HTTPException(
                    status_code=409, detail="legacy_item_copy_mismatch",
                )
            destination_bytes += len(bytes(raw))
        expected_hash = _destination_hash(
            link_id=link_id, source_item_id=source_id,
            beneficiary_vault_id=beneficiary_vault_id,
            beneficiary_item_id=copy["beneficiary_item_id"], row=copy,
        )
        if not hmac.compare_digest(bytes(original_hash), expected_hash):
            raise HTTPException(status_code=409, detail="legacy_item_copy_changed")
    source_bytes = inventory["ciphertext_bytes"] + sum(
        len(row[field].encode("utf-8"))
        for row in inventory["items"] for field in ("item_type", "service")
    )
    if destination_bytes > source_bytes + len(copies) * _MAX_DESTINATION_GROWTH:
        raise HTTPException(status_code=409, detail="item_copy_exceeds_bound")
    return copies


@router.post("/inheritance/old-link-v2/legacy-item-copy")
def copy_linked_v2_legacy_item(
    payload: CopyLinkedV2LegacyItem,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _legacy_copy_enabled()
    require_content_write(principal)
    destination = _destination_fields(payload)
    beneficiary_id = str(principal["vault_id"])
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=payload.beneficiary_link_id,
            beneficiary_vault_id=beneficiary_id,
        )
        inventory = _legacy_item_inventory(
            cur, link_id=payload.beneficiary_link_id,
            link=link, stage=stage,
        )
        if (payload.stage_revision != inventory["stage_revision"] or
                payload.offer_commitment != inventory["offer_commitment"] or
                payload.source_inventory_sha256 !=
                inventory["source_inventory_sha256"]):
            raise HTTPException(status_code=409, detail="source_inventory_changed")
        source = next(
            (row for row in inventory["items"] if
             row["item_id"] == payload.source_item_id), None,
        )
        if (source is None or payload.source_row_sha256 !=
                source["source_row_sha256"]):
            raise HTTPException(status_code=409, detail="source_item_changed")
        source_bytes = sum(len(value.encode("utf-8")) for value in (
            source["encrypted_data"], source["item_type"], source["service"],
        ))
        if sum(len(destination[field]) for field in _ITEM_FIELDS) > (
                source_bytes + _MAX_DESTINATION_GROWTH):
            raise HTTPException(status_code=409, detail="item_copy_exceeds_bound")
        prior = _legacy_copies(
            cur, link_id=payload.beneficiary_link_id,
            inventory=inventory, beneficiary_vault_id=beneficiary_id,
            for_update=True,
        )
        existing = next(
            (row for row in prior if
             row["source_item_id"] == payload.source_item_id), None,
        )
        if existing is not None:
            conn.commit()
            return {
                "beneficiary_link_id": payload.beneficiary_link_id,
                "source_item_id": payload.source_item_id,
                "beneficiary_item_id": int(existing["beneficiary_item_id"]),
                "source_inventory_sha256": inventory["source_inventory_sha256"],
                "created": False,
                "legacy_package_preserved": True,
            }
        cur.execute(
            """SELECT 1 FROM vault_items
                WHERE vault_id=%s AND encrypted_data IS NULL
                  AND item_type_ciphertext IS NOT NULL
                  AND service_ciphertext IS NOT NULL
                  AND payload_ciphertext IS NOT NULL
                  AND title_lookup_hash IS NULL LIMIT 1""",
            (beneficiary_id,),
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
                RETURNING id,title_revision,legacy_item_rename_active""",
            (beneficiary_id,
             *(destination[field] for field in _ITEM_FIELDS),
             destination["title_lookup_hash"]),
        )
        inserted = cur.fetchone()
        item_id = int(inserted["id"])
        original_hash = _destination_hash(
            link_id=payload.beneficiary_link_id,
            source_item_id=payload.source_item_id,
            beneficiary_vault_id=beneficiary_id,
            beneficiary_item_id=item_id,
            row={
                **destination,
                "item_type": None, "service": None, "encrypted_data": None,
                "title_revision": inserted["title_revision"],
                "legacy_item_rename_active":
                    inserted["legacy_item_rename_active"],
            },
        )
        cur.execute(
            """INSERT INTO linked_inheritance_v2_item_copies (
                  old_link_id,source_item_id,beneficiary_vault_id,
                  beneficiary_item_id,stage_revision,
                  source_inventory_sha256,source_row_sha256,
                  destination_ciphertext_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (payload.beneficiary_link_id, payload.source_item_id,
             beneficiary_id, item_id, payload.stage_revision,
             inventory["source_inventory_sha256"],
             _decode(source["source_row_sha256"], low=32, high=32),
             original_hash),
        )
        conn.commit()
        return {
            "beneficiary_link_id": payload.beneficiary_link_id,
            "source_item_id": payload.source_item_id,
            "beneficiary_item_id": item_id,
            "source_inventory_sha256": inventory["source_inventory_sha256"],
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


@router.get("/inheritance/old-link-v2/{link_id}/legacy-item-copies")
def readback_linked_v2_legacy_item_copies(
    link_id: int,
    response: Response,
    source_inventory_sha256: str = Query(pattern=r"^[A-Za-z0-9_-]{43}$"),
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _legacy_copy_enabled()
    if link_id <= 0:
        raise HTTPException(status_code=404, detail="not_found")
    if (not isinstance(source_inventory_sha256, str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{43}", source_inventory_sha256)):
        raise HTTPException(status_code=400, detail="invalid_source_inventory")
    beneficiary_id = str(principal["vault_id"])
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=link_id, beneficiary_vault_id=beneficiary_id,
        )
        enforce_export_rate_limit(vault_id=beneficiary_id)
        inventory = _legacy_item_inventory(
            cur, link_id=link_id, link=link, stage=stage,
        )
        if inventory["source_inventory_sha256"] != source_inventory_sha256:
            raise HTTPException(status_code=409, detail="source_inventory_changed")
        copies = _legacy_copies(
            cur, link_id=link_id, inventory=inventory,
            beneficiary_vault_id=beneficiary_id, for_update=False,
        )
        rendered = [
            {
                "source_item_id": int(row["source_item_id"]),
                "beneficiary_item_id": int(row["beneficiary_item_id"]),
                "source_row_sha256": _b64(bytes(row["source_row_sha256"])),
                "title_lookup_hash": _b64(bytes(row["title_lookup_hash"])),
                **{field: _b64(bytes(row[field])) for field in _ITEM_FIELDS},
            }
            for row in copies
        ]
        response.headers["Cache-Control"] = "no-store"
        return {
            **{key: inventory[key] for key in (
                "beneficiary_link_id", "owner_vault_id",
                "beneficiary_vault_id", "stage_revision", "offer_commitment",
                "content_scope", "owner_content_complete",
                "source_inventory_sha256", "item_count",
            )},
            "copies": rendered,
            "all_items_copied": len(rendered) == inventory["item_count"],
            "legacy_package_preserved": True,
        }
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
                RETURNING id,title_revision,legacy_item_rename_active""",
            (principal["vault_id"],
             *(destination[field] for field in _ITEM_FIELDS),
             destination["title_lookup_hash"]),
        )
        inserted = cur.fetchone()
        item_id = int(inserted["id"])
        original_hash = _destination_hash(
            link_id=payload.beneficiary_link_id,
            source_item_id=payload.source_item_id,
            beneficiary_vault_id=str(principal["vault_id"]),
            beneficiary_item_id=item_id,
            row={
                **destination,
                "item_type": None, "service": None, "encrypted_data": None,
                "title_revision": inserted["title_revision"],
                "legacy_item_rename_active":
                    inserted["legacy_item_rename_active"],
            },
        )
        cur.execute(
            """INSERT INTO linked_inheritance_v2_item_copies (
                  old_link_id,source_item_id,beneficiary_vault_id,
                  beneficiary_item_id,stage_revision,
                  source_inventory_sha256,source_row_sha256,
                  destination_ciphertext_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (payload.beneficiary_link_id, payload.source_item_id,
             principal["vault_id"], item_id, payload.stage_revision,
             digest, source["source_row_sha256"], original_hash),
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


@router.post("/inheritance/old-link-v2/{link_id}/item-copy-restart/prepare")
def prepare_linked_v2_item_restart(
    link_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Prepare a short-lived review token; no saved item is removed here."""
    _restart_enabled()
    if link_id <= 0:
        raise HTTPException(status_code=404, detail="not_found")
    enforce_export_rate_limit(vault_id=str(principal["vault_id"]))
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        _lock_restart_vaults(cur, link)
        _, current_digest, _ = _inventory(
            cur, link_id=link_id, link=link, stage=stage,
        )
        copy_state = _restart_copy_state(
            cur, link_id=link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
            stage_revision=int(stage["stage_revision"]),
            current_inventory=current_digest,
        )
        dest_ids = [int(c["beneficiary_item_id"])
                    for c in copy_state["copies"]]
        _assert_no_restart_dependents(cur, dest_ids)
        token = secrets.token_bytes(32)
        expires_at = datetime.now(timezone.utc) + _RESTART_TTL
        commitment = _offer_commitment(link_id, stage)
        cur.execute(
            """INSERT INTO linked_inheritance_v2_item_restart_previews (
                  token_hash,old_link_id,beneficiary_vault_id,
                  stage_revision,offer_commitment,
                  old_source_inventory_sha256,current_source_inventory_sha256,
                  copies_sha256,copy_count,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (hashlib.sha256(token).digest(), link_id, principal["vault_id"],
             int(stage["stage_revision"]), commitment,
             copy_state["old_inventory"], current_digest,
             copy_state["copies_digest"], len(dest_ids), expires_at),
        )
        conn.commit()
        return {
            "beneficiary_link_id": link_id,
            "stage_revision": int(stage["stage_revision"]),
            "offer_commitment": commitment,
            "old_source_inventory_sha256": copy_state["old_inventory"],
            "current_source_inventory_sha256": current_digest,
            "copies_sha256": _b64(copy_state["copies_digest"]),
            "copy_count": len(dest_ids),
            "copied_items": [
                {"source_item_id": int(c["source_item_id"]),
                 "beneficiary_item_id": int(c["beneficiary_item_id"])}
                for c in copy_state["copies"]
            ],
            "restart_token": _b64(token),
            "expires_at": expires_at.isoformat(),
            "confirmation_required": _RESTART_CONFIRMATION,
            "effect": "delete only these unchanged beneficiary copies and mappings",
            "owner_items_preserved": True,
            "legacy_package_preserved": True,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/inheritance/old-link-v2/item-copy-restart/confirm")
def confirm_linked_v2_item_restart(
    payload: ConfirmLinkedV2ItemRestart,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Explicitly remove only untouched importer copies in one transaction."""
    _restart_enabled()
    require_content_write(principal)
    token = _decode(payload.restart_token, low=32, high=32)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=payload.beneficiary_link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        _lock_restart_vaults(cur, link)
        _, current_digest, _ = _inventory(
            cur, link_id=payload.beneficiary_link_id, link=link, stage=stage,
        )
        cur.execute(
            """SELECT old_link_id,beneficiary_vault_id,stage_revision,
                      offer_commitment,old_source_inventory_sha256,
                      current_source_inventory_sha256,copies_sha256,
                      copy_count,expires_at,consumed_at
                 FROM linked_inheritance_v2_item_restart_previews
                WHERE token_hash=%s AND old_link_id=%s
                  AND beneficiary_vault_id=%s
                  AND expires_at>NOW() AND consumed_at IS NULL
                FOR UPDATE""",
            (hashlib.sha256(token).digest(), payload.beneficiary_link_id,
             principal["vault_id"]),
        )
        preview = cur.fetchone()
        commitment = _offer_commitment(payload.beneficiary_link_id, stage)
        if (preview is None or
                int(stage["stage_revision"]) != payload.stage_revision or
                int(preview["stage_revision"]) != payload.stage_revision or
                preview["offer_commitment"] != commitment or
                payload.offer_commitment != commitment or
                preview["old_source_inventory_sha256"] !=
                payload.old_source_inventory_sha256 or
                preview["current_source_inventory_sha256"] != current_digest or
                payload.current_source_inventory_sha256 != current_digest or
                int(preview["copy_count"]) != payload.copy_count or
                not hmac.compare_digest(
                    bytes(preview["copies_sha256"]),
                    _decode(payload.copies_sha256, low=32, high=32),
                )):
            raise HTTPException(status_code=409, detail="restart_preview_changed")
        copy_state = _restart_copy_state(
            cur, link_id=payload.beneficiary_link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
            stage_revision=payload.stage_revision,
            current_inventory=current_digest,
        )
        dest_ids = [int(c["beneficiary_item_id"])
                    for c in copy_state["copies"]]
        if (copy_state["old_inventory"] !=
                payload.old_source_inventory_sha256 or
                len(dest_ids) != payload.copy_count or
                not hmac.compare_digest(
                    copy_state["copies_digest"],
                    bytes(preview["copies_sha256"]),
                )):
            raise HTTPException(status_code=409, detail="restart_copies_changed")
        _assert_no_restart_dependents(cur, dest_ids)
        consume_recent_zk_proof_on_cursor(
            payload.zk_proof_token, principal, cur,
        )
        cur.execute(
            """DELETE FROM vault_items
                WHERE id=ANY(%s) AND vault_id=%s RETURNING id""",
            (dest_ids, principal["vault_id"]),
        )
        removed = {int(row["id"]) for row in (cur.fetchall() or [])}
        if removed != set(dest_ids):
            raise HTTPException(status_code=409, detail="restart_delete_mismatch")
        cur.execute(
            """UPDATE linked_inheritance_v2_item_restart_previews
                  SET consumed_at=NOW() WHERE token_hash=%s""",
            (hashlib.sha256(token).digest(),),
        )
        conn.commit()
        return {
            "beneficiary_link_id": payload.beneficiary_link_id,
            "removed_unchanged_beneficiary_items": len(dest_ids),
            "source_inventory_sha256": current_digest,
            "owner_items_preserved": True,
            "legacy_package_preserved": True,
            "ready_to_restart_saved_item_import": True,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
