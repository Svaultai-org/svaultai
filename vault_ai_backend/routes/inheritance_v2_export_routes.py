"""Released private-inheritance ciphertext export for saved items only.

The beneficiary receives owner MVK ciphertext after the release state machine
has released a V2 key envelope. The server never decrypts an item or MVK.
This bounded route is part of a staged, default-off import flow.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from inheritance_protocol import (
    ZK_BENEFICIARY_V2_MARKER,
    ZK_BENEFICIARY_V2_CRYPTO_VERSION,
    zk_beneficiary_v2_enabled,
)
from vault_core import get_db
from rate_limit_sensitive import enforce_export_rate_limit

router = APIRouter()
_MAX_ITEMS = 500
_MAX_CIPHERTEXT_BYTES = 4 * 1024 * 1024


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(bytes(value)).rstrip(b"=").decode("ascii")


@router.get("/inheritance/v2/{link_id}/vault-items")
def export_released_vault_items(
    link_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    if not zk_beneficiary_v2_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if link_id <= 0:
        raise HTTPException(status_code=404, detail="Not found")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT bl.passer_vault_id, bl.wrapped_vault_key,
                      bl.pairing_state, ic.crypto_version
                 FROM beneficiary_links bl
                 JOIN inheritance_credentials ic
                   ON ic.beneficiary_link_id = bl.id
                  AND ic.deleted_at IS NULL
                WHERE bl.id = %s AND bl.beneficiary_vault_id = %s""",
            (link_id, principal["vault_id"]),
        )
        link = cur.fetchone()
        if (not link or link["wrapped_vault_key"] != ZK_BENEFICIARY_V2_MARKER or
                link["pairing_state"] != "released" or
                int(link["crypto_version"]) != ZK_BENEFICIARY_V2_CRYPTO_VERSION):
            raise HTTPException(status_code=404, detail="Inheritance export unavailable")
        enforce_export_rate_limit(vault_id=str(principal["vault_id"]))
        owner_vault_id = link["passer_vault_id"]
        cur.execute(
            """SELECT 1 FROM vault_items
                WHERE vault_id = %s
                  AND (encrypted_data IS NOT NULL OR
                       item_type_ciphertext IS NULL OR
                       service_ciphertext IS NULL OR
                       payload_ciphertext IS NULL)
                LIMIT 1""",
            (owner_vault_id,),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="owner_items_need_private_migration")
        cur.execute(
            """SELECT COUNT(*) AS item_count,
                      COALESCE(SUM(OCTET_LENGTH(item_type_ciphertext) +
                                   OCTET_LENGTH(service_ciphertext) +
                                   OCTET_LENGTH(payload_ciphertext)), 0)
                        AS ciphertext_bytes
                 FROM vault_items WHERE vault_id = %s""",
            (owner_vault_id,),
        )
        budget = cur.fetchone() or {}
        if (int(budget.get("item_count") or 0) > _MAX_ITEMS or
                int(budget.get("ciphertext_bytes") or 0) > _MAX_CIPHERTEXT_BYTES):
            raise HTTPException(status_code=409, detail="owner_items_exceed_import_limit")
        cur.execute(
            """SELECT id, item_type_ciphertext, service_ciphertext,
                      payload_ciphertext
                 FROM vault_items
                WHERE vault_id = %s
                ORDER BY id ASC LIMIT %s""",
            (owner_vault_id, _MAX_ITEMS + 1),
        )
        rows = cur.fetchall() or []
        if (len(rows) > _MAX_ITEMS or
                sum(len(bytes(row[field])) for row in rows for field in (
                    "item_type_ciphertext", "service_ciphertext", "payload_ciphertext"
                )) > _MAX_CIPHERTEXT_BYTES):
            raise HTTPException(status_code=409, detail="owner_items_exceed_import_limit")
        return {
            "owner_vault_id": str(owner_vault_id),
            "beneficiary_link_id": link_id,
            "items": [
                {
                    "item_id": int(row["id"]),
                    "item_type_ciphertext": _b64(row["item_type_ciphertext"]),
                    "service_ciphertext": _b64(row["service_ciphertext"]),
                    "payload_ciphertext": _b64(row["payload_ciphertext"]),
                }
                for row in rows
            ],
        }
    finally:
        conn.close()
