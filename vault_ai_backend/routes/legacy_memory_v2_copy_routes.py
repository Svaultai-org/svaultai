"""Additive owner-device preparation of older PIN-key Memory ciphertext.

The active legacy row is never modified. A future, separately gated cutover
must verify these copies again before exposing them as active V2 Memory.
"""

from __future__ import annotations

import base64
import binascii
import os

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from legacy_source_snapshot import MEMORY_SOURCE_FIELDS, source_snapshot
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from subscription_entitlement import require_content_write
from vault_core import get_db


router = APIRouter()
MAX_MEMORY_V2_COPY_BYTES = 128 * 1024


def _require_enabled() -> None:
    if os.getenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _decode_copy(value: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_memory_copy") from exc
    if len(raw) < 29 or len(raw) > MAX_MEMORY_V2_COPY_BYTES or raw[0] != 1:
        raise HTTPException(status_code=400, detail="invalid_memory_copy")
    return raw


class LegacyMemoryCopyStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot: str = Field(..., min_length=43, max_length=43)
    payload_ciphertext: str = Field(..., min_length=39, max_length=174764)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    client_verified_source: bool = False


def _load_active_legacy_memory(cur, vault_id: str, memory_id: int) -> dict:
    cur.execute(
        "SELECT " + ",".join(MEMORY_SOURCE_FIELDS) +
        " FROM vault_ai_memory WHERE id=%s AND vault_id=%s "
        "AND superseded_at IS NULL FOR UPDATE",
        (memory_id, vault_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="legacy_memory_not_found")
    legacy = row["payload_ciphertext"]
    if legacy is None or len(legacy) == 0 or bytes(legacy)[0] == 1:
        raise HTTPException(status_code=409, detail="memory_not_legacy")
    return row


@router.post("/vault/memory/legacy-copy/{memory_id}/stage")
def stage_legacy_memory_copy(
    memory_id: int,
    payload: LegacyMemoryCopyStageRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_enabled()
    require_content_write(principal)
    if memory_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_memory_id")
    if not payload.client_verified_source:
        raise HTTPException(status_code=400, detail="client_source_verification_required")
    copy = _decode_copy(payload.payload_ciphertext)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_active_legacy_memory(cur, principal["vault_id"], memory_id)
        snapshot = source_snapshot(
            "memory", row, vault_id=principal["vault_id"], record_id=memory_id,
        )
        if snapshot != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_memory_changed")
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        cur.execute(
            """INSERT INTO memory_v2_prepared_copies
                 (legacy_memory_id,vault_id,source_snapshot,memory_record_id,
                  memory_type,payload_ciphertext)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (legacy_memory_id) DO UPDATE SET
                 source_snapshot=EXCLUDED.source_snapshot,
                 memory_type=EXCLUDED.memory_type,
                 payload_ciphertext=EXCLUDED.payload_ciphertext,
                 prepared_at=NOW()
               WHERE memory_v2_prepared_copies.vault_id=EXCLUDED.vault_id
               RETURNING legacy_memory_id""",
            (memory_id, principal["vault_id"], snapshot,
             f"memory-migrated-{memory_id}", row["memory_type"], copy),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="memory_owner_changed")
        conn.commit()
        return {"memory_id": memory_id, "prepared": True,
                "active_legacy_unchanged": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/vault/memory/legacy-copy/{memory_id}/readback")
def readback_legacy_memory_copy(
    memory_id: int,
    http_response: Response = None,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_enabled()
    if memory_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_memory_id")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_active_legacy_memory(cur, principal["vault_id"], memory_id)
        snapshot = source_snapshot(
            "memory", row, vault_id=principal["vault_id"], record_id=memory_id,
        )
        cur.execute(
            """SELECT source_snapshot,memory_record_id,memory_type,
                      payload_ciphertext
                 FROM memory_v2_prepared_copies
                WHERE vault_id=%s AND legacy_memory_id=%s""",
            (principal["vault_id"], memory_id),
        )
        copy = cur.fetchone()
        if copy is None:
            raise HTTPException(status_code=404, detail="memory_copy_not_found")
        if copy["source_snapshot"] != snapshot or copy["memory_type"] != row["memory_type"]:
            raise HTTPException(status_code=409, detail="legacy_memory_changed")
    finally:
        conn.close()
    if http_response is not None:
        http_response.headers["Cache-Control"] = "no-store"
    return {
        "memory_id": memory_id,
        "source_snapshot": snapshot,
        "memory_record_id": copy["memory_record_id"],
        "memory_type": copy["memory_type"],
        "payload_ciphertext": base64.urlsafe_b64encode(
            bytes(copy["payload_ciphertext"]),
        ).decode("ascii").rstrip("="),
    }
