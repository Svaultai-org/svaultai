"""Additive owner-device preparation of older PIN-key Memory ciphertext.

The active legacy row is never modified. A future, separately gated cutover
must verify these copies again before exposing them as active V2 Memory.
"""

from __future__ import annotations

import base64
import binascii
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from legacy_source_snapshot import MEMORY_SOURCE_FIELDS, source_snapshot
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from routes.vault_ciphertext_write_routes import _verify_memory_inventory_generation
from subscription_entitlement import require_content_write
from taxonomy import ALLOWED_MEMORY_TYPES
from vault_core import get_db


router = APIRouter()
MAX_MEMORY_V2_COPY_BYTES = 128 * 1024


def _require_enabled() -> None:
    if os.getenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _require_active_enabled() -> None:
    _require_enabled()
    if os.getenv("VAULTAI_ZK_LEGACY_MEMORY_ACTIVE_ENABLED", "false").strip().lower() != "true":
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


class LegacyMemoryCopyEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot: str = Field(..., min_length=43, max_length=43)
    memory_type: str = Field(..., min_length=1, max_length=64)
    legacy_payload_ciphertext: str = Field(..., min_length=40, max_length=174764)
    payload_ciphertext: str = Field(..., min_length=39, max_length=174764)
    expected_memory_generation: str = Field(
        ..., pattern=r"^(0|[1-9][0-9]{0,18})$",
    )
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    client_verified_source: bool = False


class LegacyMemoryCopyDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot: str = Field(..., min_length=43, max_length=43)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    client_confirmed_delete: bool = False


def _decode_legacy_copy(value: str) -> bytes:
    # The old writer stores an ASCII base64 AES-GCM envelope, not plaintext.
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value):
        raise HTTPException(status_code=400, detail="invalid_legacy_memory_copy")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_legacy_memory_copy") from exc
    if len(raw) < 29 or len(raw) > MAX_MEMORY_V2_COPY_BYTES:
        raise HTTPException(status_code=400, detail="invalid_legacy_memory_copy")
    return value.encode("ascii")


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


def _locked_prepared_copy(cur, vault_id: str, memory_id: int, row: dict) -> dict:
    snapshot = source_snapshot(
        "memory", row, vault_id=vault_id, record_id=memory_id,
    )
    cur.execute(
        """SELECT source_snapshot,memory_record_id,memory_type,payload_ciphertext
             FROM memory_v2_prepared_copies
            WHERE vault_id=%s AND legacy_memory_id=%s FOR UPDATE""",
        (vault_id, memory_id),
    )
    copy = cur.fetchone()
    if copy is None:
        raise HTTPException(status_code=404, detail="memory_copy_not_found")
    if copy["source_snapshot"] != snapshot or copy["memory_type"] != row["memory_type"]:
        raise HTTPException(status_code=409, detail="legacy_memory_changed")
    return copy


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


@router.get("/vault/memory/legacy-copy/list")
def list_active_legacy_memory_copies(
    http_response: Response,
    after_memory_id: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Expose only source-bound V2 ciphertext for active old Memory rows.

    The old row remains authoritative while older clients can still write.
    A missing or changed copy is reported as unavailable, never substituted
    with the PIN-key envelope or silently treated as a deleted Memory.
    """
    _require_active_enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """SELECT m.id,m.payload_ciphertext,m.memory_type,m.memory_record_id,
                      m.memory_lookup_hash,c.source_snapshot,
                      c.memory_record_id AS copy_record_id,
                      c.memory_type AS copy_type,
                      c.payload_ciphertext AS copy_ciphertext
                 FROM vault_ai_memory m
                 LEFT JOIN memory_v2_prepared_copies c
                   ON c.legacy_memory_id=m.id AND c.vault_id=m.vault_id
                WHERE m.vault_id=%s AND m.id>%s AND m.superseded_at IS NULL
                  AND CASE WHEN OCTET_LENGTH(m.payload_ciphertext)>=29
                    THEN GET_BYTE(m.payload_ciphertext,0)<>1
                    ELSE TRUE END
                ORDER BY m.id LIMIT %s""",
            (principal["vault_id"], after_memory_id, limit + 1),
        )
        rows = cur.fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_after_memory_id = rows[-1]["id"] if rows else after_memory_id
        copies = []
        unavailable = 0
        for row in rows:
            if row["copy_ciphertext"] is None:
                unavailable += 1
                continue
            snapshot = source_snapshot(
                "memory", row, vault_id=principal["vault_id"], record_id=row["id"],
            )
            if (row["source_snapshot"] != snapshot or
                    row["copy_type"] != row["memory_type"] or
                    row["copy_record_id"] != f"memory-migrated-{row['id']}"):
                unavailable += 1
                continue
            copies.append({
                "legacy_memory_id": row["id"],
                "source_snapshot": snapshot,
                "memory_record_id": row["copy_record_id"],
                "memory_type": row["copy_type"],
                "payload_ciphertext": base64.urlsafe_b64encode(
                    bytes(row["copy_ciphertext"]),
                ).decode("ascii").rstrip("="),
            })
    finally:
        conn.close()
    http_response.headers["Cache-Control"] = "no-store"
    return {"copies": copies, "unavailable_count": unavailable,
            "has_more": has_more,
            "next_after_memory_id": next_after_memory_id}


@router.get("/vault/memory/legacy-copy/generation")
def active_memory_inventory_generation(
    http_response: Response,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Return an opaque counter around a multi-request private inventory."""
    _require_active_enabled()
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT memory_inventory_generation FROM vaults WHERE vault_id=%s",
            (principal["vault_id"],),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="vault_not_found")
        generation = str(row[0])
    finally:
        conn.close()
    http_response.headers["Cache-Control"] = "no-store"
    return {"generation": generation}


@router.post("/vault/memory/legacy-copy/{memory_id}/edit")
def edit_active_legacy_memory_copy(
    memory_id: int,
    payload: LegacyMemoryCopyEditRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Atomically update old-client ciphertext and its private V2 mirror."""
    _require_active_enabled()
    require_content_write(principal)
    if memory_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_memory_id")
    if not payload.client_verified_source:
        raise HTTPException(status_code=400, detail="client_source_verification_required")
    if payload.memory_type not in ALLOWED_MEMORY_TYPES:
        raise HTTPException(status_code=400, detail="unsupported_memory_type")
    legacy_ct = _decode_legacy_copy(payload.legacy_payload_ciphertext)
    new_ct = _decode_copy(payload.payload_ciphertext)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_active_legacy_memory(cur, principal["vault_id"], memory_id)
        old_copy = _locked_prepared_copy(cur, principal["vault_id"], memory_id, row)
        if old_copy["source_snapshot"] != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_memory_changed")
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        # 0064 removes the prior prepared copy on this UPDATE. Reinsert the
        # new source-bound copy in the same transaction; a failure rolls both
        # back, including the original old-client row and its prior copy.
        cur.execute(
            """UPDATE vault_ai_memory
                  SET payload_ciphertext=%s,memory_type=%s,updated_at=NOW()
                WHERE id=%s AND vault_id=%s AND superseded_at IS NULL
                RETURNING payload_ciphertext,memory_type,memory_record_id,
                          memory_lookup_hash""",
            (legacy_ct, payload.memory_type, memory_id, principal["vault_id"]),
        )
        changed = cur.fetchone()
        if changed is None:
            raise HTTPException(status_code=409, detail="legacy_memory_changed")
        snapshot = source_snapshot(
            "memory", changed, vault_id=principal["vault_id"], record_id=memory_id,
        )
        cur.execute(
            """INSERT INTO memory_v2_prepared_copies
                 (legacy_memory_id,vault_id,source_snapshot,memory_record_id,
                  memory_type,payload_ciphertext)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (memory_id, principal["vault_id"], snapshot,
             f"memory-migrated-{memory_id}", payload.memory_type, new_ct),
        )
        # The source UPDATE, 0064 copy invalidation, and replacement copy
        # INSERT each advance generation once. A concurrent older write to
        # any other Memory makes this comparison fail and rolls back both
        # ciphertext formats plus the consumed proof.
        _verify_memory_inventory_generation(
            cur, principal["vault_id"], payload.expected_memory_generation,
            own_advances=3, signed_memory=True,
        )
        conn.commit()
        return {"memory_id": memory_id, "source_snapshot": snapshot,
                "active_legacy_updated": True, "prepared_copy_updated": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/memory/legacy-copy/{memory_id}/delete")
def delete_active_legacy_memory_copy(
    memory_id: int,
    payload: LegacyMemoryCopyDeleteRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Retain original ciphertext while hiding this Memory from old clients."""
    _require_active_enabled()
    require_content_write(principal)
    if memory_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_memory_id")
    if not payload.client_confirmed_delete:
        raise HTTPException(status_code=400, detail="client_delete_confirmation_required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_active_legacy_memory(cur, principal["vault_id"], memory_id)
        old_copy = _locked_prepared_copy(cur, principal["vault_id"], memory_id, row)
        if old_copy["source_snapshot"] != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_memory_changed")
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        cur.execute(
            """UPDATE vault_ai_memory SET superseded_at=NOW(),updated_at=NOW()
                WHERE id=%s AND vault_id=%s AND superseded_at IS NULL""",
            (memory_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="legacy_memory_changed")
        # The 0064 trigger removes the prepared copy. Check in transaction.
        cur.execute(
            "SELECT 1 FROM memory_v2_prepared_copies WHERE legacy_memory_id=%s",
            (memory_id,),
        )
        if cur.fetchone() is not None:
            raise HTTPException(status_code=500, detail="memory_copy_invalidation_failed")
        conn.commit()
        return {"memory_id": memory_id, "hidden_from_old_clients": True,
                "original_ciphertext_preserved": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
