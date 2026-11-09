"""Bounded, PIN-free metadata inventory for trusted zero-knowledge sessions.

The response never includes an encrypted value, inline file bytes, plaintext
filename, or plaintext file type. Legacy item type/service are exposed only
when no encrypted metadata counterpart exists; those preexisting columns are
a legacy privacy limit until client-side migration retires them. An optional
folder cutover returns older server-known relative paths to the owner; new
V2 folder paths remain encrypted in their file manifests.
"""

from __future__ import annotations

import base64
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from vault_core import get_db, is_vault_zk_adopted


router = APIRouter()
MAX_PAGE_SIZE = 100
MAX_LABEL_BYTES = 4096


def _require_inventory(vault_id: str, principal: SessionPrincipal) -> None:
    from auth_local import PIN_FREE_SAVED_ITEM_MUTATION_OFFER
    signed_item_mutation = (
        principal.get("pin_free_read_offers", 0) &
        PIN_FREE_SAVED_ITEM_MUTATION_OFFER
    )
    if os.getenv(
        "VAULTAI_ZK_METADATA_INVENTORY_ENABLED", "false",
    ).strip().lower() != "true" and not signed_item_mutation:
        raise HTTPException(status_code=404, detail="not_found")
    if not is_vault_zk_adopted(vault_id):
        raise HTTPException(status_code=409, detail="zk_vault_required")


def _label(value: object) -> str | None:
    if value is None:
        return None
    raw = bytes(value)
    if len(raw) > MAX_LABEL_BYTES:
        raise HTTPException(status_code=413, detail="encrypted_metadata_too_large")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _legacy_label(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) > 256:
        raise HTTPException(status_code=413, detail="legacy_metadata_too_large")
    return text


@router.get("/vault/items/metadata")
def item_metadata_inventory(
    after_item_id: int = Query(default=0, ge=0),
    limit: int = Query(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_inventory(principal["vault_id"], principal)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, item_type, service, item_type_ciphertext,
                   service_ciphertext, encrypted_data IS NOT NULL AS is_legacy,
                   payload_ciphertext IS NOT NULL AS has_v2_payload,
                   created_at
              FROM vault_items
             WHERE vault_id = %s AND id > %s
             ORDER BY id LIMIT %s
            """,
            (principal["vault_id"], after_item_id, limit + 1),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    records = []
    for row in rows[:limit]:
        type_ct = _label(row["item_type_ciphertext"])
        service_ct = _label(row["service_ciphertext"])
        records.append({
            "item_id": int(row["id"]),
            "item_type_ciphertext": type_ct,
            "service_ciphertext": service_ct,
            "item_type": _legacy_label(row["item_type"]) if type_ct is None else None,
            "service": _legacy_label(row["service"]) if service_ct is None else None,
            "is_legacy": bool(row["is_legacy"]),
            "has_v2_payload": bool(row["has_v2_payload"]),
            "created_at": row["created_at"],
        })
    return {
        "records": records,
        "has_more": len(rows) > limit,
        "next_after_item_id": records[-1]["item_id"] if records else None,
    }


@router.get("/vault/files/metadata")
def file_metadata_inventory(
    after_file_id: str = Query(default="", max_length=128),
    limit: int = Query(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    require_legacy_complete: bool = False,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_inventory(principal["vault_id"], principal)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if require_legacy_complete:
            # A second device can write an older row after this bearer was
            # offered the PIN-free list. Recheck under one stable snapshot so
            # an incomplete list cannot silently omit its newest file.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            from routes.auth_zk_routes import _pin_free_legacy_file_list_ready
            if not _pin_free_legacy_file_list_ready(conn, principal["vault_id"]):
                raise HTTPException(
                    status_code=409, detail="legacy_file_list_changed",
                )
        cur.execute(
            """
            SELECT u.id, u.file_size, u.storage_mode, u.chunk_size,
                   u.chunk_count, u.upload_status,
                   u.needs_naming, u.autosaved_secret,
                   u.file_name_ciphertext,
                   COALESCE(r.saved_name_override_ciphertext,
                            u.saved_name_ciphertext) AS saved_name_ciphertext,
                   u.content_type_ciphertext, u.detected_type_ciphertext,
                   u.detected_service_ciphertext, u.asset_type_ciphertext,
                   u.encrypted_file_data IS NOT NULL AS has_inline_ciphertext,
                   u.relative_path,
                   u.created_at, r.lifecycle_state, r.verification_state,
                   r.name_version
              FROM uploaded_files u
              LEFT JOIN file_v2_records r
                ON r.file_id = u.id AND r.vault_id = u.vault_id::text
             WHERE u.vault_id = %s AND u.upload_status = 'complete'
               AND u.id > %s
             ORDER BY u.id LIMIT %s
            """,
            (principal["vault_id"], after_file_id, limit + 1),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    records = []
    for row in rows[:limit]:
        record = {
            "file_id": row["id"],
            "file_size": int(row["file_size"]),
            "storage_mode": row["storage_mode"],
            "chunk_size": (
                int(row["chunk_size"])
                if row.get("chunk_size") is not None else None
            ),
            "chunk_count": (
                int(row["chunk_count"])
                if row.get("chunk_count") is not None else None
            ),
            "upload_status": row["upload_status"],
            "needs_naming": bool(row.get("needs_naming")),
            "autosaved_secret": bool(row.get("autosaved_secret")),
            "has_inline_ciphertext": bool(row["has_inline_ciphertext"]),
            "created_at": row["created_at"],
            "lifecycle_state": row["lifecycle_state"],
            "verification_state": row["verification_state"],
            "name_version": (
                int(row["name_version"])
                if row.get("name_version") is not None else None
            ),
            # Old folder paths are already server-known. Expose them only to
            # this trusted owner inventory when the coordinated local-folder
            # cutover is enabled; new V2 paths stay encrypted in the manifest.
            "relative_path": (
                row["relative_path"]
                if os.getenv("VAULTAI_ZK_SIGNED_FOLDER_METADATA_ENABLED", "false")
                .strip().lower() == "true" else None
            ),
        }
        for field in (
            "file_name_ciphertext", "saved_name_ciphertext",
            "content_type_ciphertext", "detected_type_ciphertext",
            "detected_service_ciphertext", "asset_type_ciphertext",
        ):
            record[field] = _label(row[field])
        records.append(record)
    return {
        "records": records,
        "has_more": len(rows) > limit,
        "next_after_file_id": records[-1]["file_id"] if records else None,
    }
