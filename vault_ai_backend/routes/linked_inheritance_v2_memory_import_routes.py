"""Default-off, source-bound Memory copy for released old inheritance links.

Only owner MVK ciphertext is exported. The beneficiary re-encrypts locally;
the owner row, prepared legacy copy, and old inheritance package stay intact.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from legacy_source_snapshot import source_snapshot
from rate_limit_sensitive import enforce_export_rate_limit
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from routes.linked_inheritance_v2_upgrade_routes import (
    _b64, _decode, _feed, _load_releasable_old_link, _offer_commitment,
    _readback_proof_enabled, _verified_release_stage,
)
from subscription_entitlement import require_content_write
from vault_core import get_db


router = APIRouter(tags=["linked-inheritance-v2-memory-import"])
FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_MEMORY_IMPORT_ENABLED"
_MAX_MEMORIES = 100
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_ROW_BYTES = 128 * 1024
_MAX_GROWTH = 4096
_DIGEST = re.compile(r"^[A-Za-z0-9_-]{43}$")


class CopyLinkedV2Memory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beneficiary_link_id: int = Field(gt=0)
    source_memory_id: int = Field(gt=0)
    stage_revision: int = Field(gt=0)
    offer_commitment: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    source_inventory_sha256: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    source_row_sha256: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    beneficiary_memory_record_id: str = Field(min_length=1, max_length=128)
    memory_type: str = Field(min_length=1, max_length=64)
    memory_lookup_hash: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    payload_ciphertext: str = Field(min_length=1, max_length=175000)
    content_scope: str = Field(pattern=r"^memory_only$")
    zk_proof_token: str = Field(min_length=1, max_length=128)


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


def _row_hash(row: dict) -> bytes:
    h = hashlib.sha256(b"linked-old-v2-memory-source/v1\x00")
    for value in (row["memory_id"], row["memory_type"],
                  row["memory_record_id"], row["source_snapshot"],
                  row["payload_ciphertext"]):
        _feed(h, value)
    return h.digest()


def _inventory(cur, *, link_id: int, link: dict, stage: dict) -> tuple[list[dict], str, int]:
    owner_id = str(link["passer_vault_id"])
    cur.execute(
        """SELECT id,memory_type,memory_record_id,memory_lookup_hash,
                  payload_ciphertext
             FROM vault_ai_memory
            WHERE vault_id=%s AND superseded_at IS NULL
            ORDER BY id LIMIT %s FOR SHARE""",
        (owner_id, _MAX_MEMORIES + 1),
    )
    sources = cur.fetchall() or []
    if len(sources) > _MAX_MEMORIES:
        raise HTTPException(status_code=409, detail="owner_memories_exceed_import_limit")
    digest = hashlib.sha256(b"linked-old-v2-memory-inventory/v1\x00")
    for value in (link_id, owner_id, str(link["beneficiary_vault_id"]),
                  int(stage["stage_revision"])):
        _feed(digest, value)
    rows = []
    total = 0
    for source in sources:
        memory_id = source["id"]
        raw = source.get("payload_ciphertext")
        if raw is None:
            raise HTTPException(status_code=409, detail="owner_memory_not_private_ready")
        raw = bytes(raw)
        if len(raw) >= 29 and raw[0] == 1:
            if (not source.get("memory_record_id") or
                    source.get("memory_lookup_hash") is None or
                    len(bytes(source["memory_lookup_hash"])) != 32):
                raise HTTPException(status_code=409, detail="owner_memory_not_private_ready")
            payload = raw
            record_id = str(source["memory_record_id"])
            snapshot = source_snapshot(
                "memory", source, vault_id=owner_id, record_id=memory_id,
            )
        else:
            cur.execute(
                """SELECT source_snapshot,memory_record_id,memory_type,
                          payload_ciphertext,owner_verified_stage
                     FROM memory_v2_prepared_copies
                    WHERE vault_id=%s AND legacy_memory_id=%s FOR SHARE""",
                (owner_id, memory_id),
            )
            prepared = cur.fetchone()
            snapshot = source_snapshot(
                "memory", source, vault_id=owner_id, record_id=memory_id,
            )
            if (not prepared or not prepared["owner_verified_stage"] or
                    prepared["source_snapshot"] != snapshot or
                    prepared["memory_type"] != source["memory_type"] or
                    prepared["memory_record_id"] != f"memory-migrated-{memory_id}"):
                raise HTTPException(status_code=409, detail="owner_memory_copy_unverified")
            payload = bytes(prepared["payload_ciphertext"])
            record_id = str(prepared["memory_record_id"])
        if (len(payload) < 29 or len(payload) > _MAX_ROW_BYTES or
                payload[0] != 1):
            raise HTTPException(status_code=409, detail="owner_memory_ciphertext_invalid")
        total += len(payload)
        if total > _MAX_SOURCE_BYTES:
            raise HTTPException(status_code=409, detail="owner_memories_exceed_import_limit")
        row = {
            "memory_id": memory_id,
            "memory_type": source["memory_type"],
            "memory_record_id": record_id,
            "source_snapshot": snapshot,
            "payload_ciphertext": payload,
        }
        row["source_row_sha256"] = _row_hash(row)
        _feed(digest, memory_id)
        _feed(digest, row["source_row_sha256"])
        rows.append(row)
    return rows, _b64(digest.digest()), total


def _export_body(*, link_id: int, link: dict, stage: dict,
                 rows: list[dict], digest: str, total: int) -> dict:
    return {
        "beneficiary_link_id": link_id,
        "owner_vault_id": str(link["passer_vault_id"]),
        "beneficiary_vault_id": str(link["beneficiary_vault_id"]),
        "stage_revision": int(stage["stage_revision"]),
        "offer_commitment": _offer_commitment(link_id, stage),
        "content_scope": "memory_only",
        "owner_content_complete": False,
        "source_inventory_sha256": digest,
        "memory_count": len(rows),
        "ciphertext_bytes": total,
        "memories": [{
            "memory_id": row["memory_id"],
            "memory_type": row["memory_type"],
            "memory_record_id": row["memory_record_id"],
            "source_snapshot": row["source_snapshot"],
            "source_row_sha256": _b64(row["source_row_sha256"]),
            "payload_ciphertext": _b64(row["payload_ciphertext"]),
        } for row in rows],
    }


def _destination_hash(row: dict, *, link_id: int, source_memory_id: int,
                      beneficiary_vault_id: str) -> bytes:
    h = hashlib.sha256(b"linked-old-v2-memory-destination/v1\x00")
    for value in (link_id, source_memory_id, beneficiary_vault_id,
                  row["id"], row["memory_record_id"], row["memory_type"],
                  row["memory_lookup_hash"], row["payload_ciphertext"],
                  row["memory_key"], row["memory_value"],
                  row["memory_normalized_key"], row["superseded_at"]):
        _feed(h, value)
    return h.digest()


def _memory_vault_states(cur, *, owner_id: str, beneficiary_id: str,
                         lock: bool) -> dict[str, dict]:
    # Memory triggers update the vault row after writing the Memory row. Read
    # source rows first, then take these locks in stable order; taking the
    # vault lock before _inventory could deadlock against an owner edit.
    cur.execute(
        """SELECT vault_id,memory_inventory_generation,
                  memory_mixed_title_fence_enabled
             FROM vaults WHERE vault_id IN (%s,%s)
            ORDER BY vault_id""" + (" FOR UPDATE" if lock else ""),
        (owner_id, beneficiary_id),
    )
    states = {str(row["vault_id"]): row for row in (cur.fetchall() or [])}
    if owner_id == beneficiary_id or set(states) != {owner_id, beneficiary_id}:
        raise HTTPException(status_code=409, detail="memory_vault_changed")
    return states


def _recipient_has_unmapped_memory(cur, *, link_id: int,
                                   beneficiary_id: str) -> bool:
    cur.execute(
        """SELECT 1 FROM vault_ai_memory m
            WHERE m.vault_id=%s AND m.superseded_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM linked_inheritance_v2_memory_copies c
                 WHERE c.old_link_id=%s AND
                       c.beneficiary_vault_id=%s AND
                       c.beneficiary_memory_id=m.id
              ) LIMIT 1""",
        (beneficiary_id, link_id, beneficiary_id),
    )
    return cur.fetchone() is not None


@router.get("/inheritance/old-link-v2/{link_id}/vault-memories")
def export_linked_v2_memories(
    link_id: int,
    http_response: Response,
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
        result = _export_body(
            link_id=link_id, link=link, stage=stage,
            rows=rows, digest=digest, total=total,
        )
    finally:
        conn.close()
    http_response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/inheritance/old-link-v2/memory-copy")
def copy_linked_v2_memory(
    payload: CopyLinkedV2Memory,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    require_content_write(principal)
    if payload.beneficiary_memory_record_id != (
            f"inherited-{payload.beneficiary_link_id}-{payload.source_memory_id}"):
        raise HTTPException(status_code=400, detail="invalid_memory_copy_identity")
    ciphertext = _decode(payload.payload_ciphertext, low=29, high=_MAX_ROW_BYTES)
    if ciphertext[0] != 1:
        raise HTTPException(status_code=400, detail="invalid_memory_ciphertext")
    lookup_hash = _decode(payload.memory_lookup_hash, low=32, high=32)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=payload.beneficiary_link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        owner_id = str(link["passer_vault_id"])
        beneficiary_id = str(principal["vault_id"])
        before = _memory_vault_states(
            cur, owner_id=owner_id, beneficiary_id=beneficiary_id,
            lock=False,
        )
        rows, digest, _ = _inventory(
            cur, link_id=payload.beneficiary_link_id,
            link=link, stage=stage,
        )
        # The inventory locks existing source rows, but cannot lock a new-row
        # gap. Every source/recipient Memory write advances its vault row in
        # the same transaction. Lock both vault rows only after _inventory,
        # then reject a generation change before any destination write.
        locked = _memory_vault_states(
            cur, owner_id=owner_id, beneficiary_id=beneficiary_id,
            lock=True,
        )
        if (locked[owner_id]["memory_inventory_generation"] !=
                before[owner_id]["memory_inventory_generation"]):
            raise HTTPException(status_code=409, detail="source_inventory_changed")
        if (locked[beneficiary_id]["memory_inventory_generation"] !=
                before[beneficiary_id]["memory_inventory_generation"]):
            raise HTTPException(status_code=409, detail="beneficiary_memory_changed")
        if (payload.stage_revision != stage["stage_revision"] or
                payload.offer_commitment !=
                _offer_commitment(payload.beneficiary_link_id, stage) or
                payload.source_inventory_sha256 != digest):
            raise HTTPException(status_code=409, detail="source_inventory_changed")
        source = next(
            (row for row in rows if row["memory_id"] == payload.source_memory_id),
            None,
        )
        if (source is None or payload.source_row_sha256 !=
                _b64(source["source_row_sha256"]) or
                payload.memory_type != source["memory_type"]):
            raise HTTPException(status_code=409, detail="source_memory_changed")
        if len(ciphertext) > len(source["payload_ciphertext"]) + _MAX_GROWTH:
            raise HTTPException(status_code=409, detail="memory_copy_exceeds_bound")
        cur.execute(
            """SELECT source_memory_id,beneficiary_memory_id,
                      beneficiary_vault_id,stage_revision,
                      source_inventory_sha256,source_row_sha256
                 FROM linked_inheritance_v2_memory_copies
                WHERE old_link_id=%s ORDER BY source_memory_id FOR UPDATE""",
            (payload.beneficiary_link_id,),
        )
        prior = cur.fetchall() or []
        for row in prior:
            if (str(row["beneficiary_vault_id"]) !=
                    str(principal["vault_id"]) or
                    row["stage_revision"] != payload.stage_revision or
                    row["source_inventory_sha256"] != digest):
                raise HTTPException(status_code=409, detail="prior_copy_inventory_changed")
        # The 0073 fence must already be enabled explicitly for the recipient.
        # Ciphertext prevents the server from comparing titles with a native
        # row whose client used different whitespace. Until a complete,
        # recipient-keyed title preflight exists, copy only into an otherwise
        # empty Memory set (apart from exact prior copies of this same link).
        if not locked[beneficiary_id]["memory_mixed_title_fence_enabled"]:
            raise HTTPException(status_code=409, detail="beneficiary_memory_fence_required")
        if _recipient_has_unmapped_memory(
                cur, link_id=payload.beneficiary_link_id,
                beneficiary_id=beneficiary_id):
            raise HTTPException(status_code=409, detail="beneficiary_memory_inventory_required")
        existing = next(
            (row for row in prior if row["source_memory_id"] ==
             payload.source_memory_id), None,
        )
        if existing is not None:
            if bytes(existing["source_row_sha256"]) != source["source_row_sha256"]:
                raise HTTPException(status_code=409, detail="source_memory_changed")
            conn.commit()
            return {
                "beneficiary_link_id": payload.beneficiary_link_id,
                "source_memory_id": payload.source_memory_id,
                "beneficiary_memory_id": int(existing["beneficiary_memory_id"]),
                "source_inventory_sha256": digest,
                "created": False,
                "legacy_package_preserved": True,
            }
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        cur.execute(
            """INSERT INTO vault_ai_memory (
                  vault_id,memory_record_id,memory_type,memory_key,
                  memory_value,memory_normalized_key,payload_ciphertext,
                  memory_lookup_hash)
                VALUES (%s,%s,%s,NULL,NULL,NULL,%s,%s)
                RETURNING id,memory_record_id,memory_type,memory_key,
                          memory_value,memory_normalized_key,
                          payload_ciphertext,memory_lookup_hash,superseded_at""",
            (principal["vault_id"], payload.beneficiary_memory_record_id,
             payload.memory_type, ciphertext, lookup_hash),
        )
        inserted = cur.fetchone()
        # Prior rows mapped to this link must still be private-ready. The
        # vault locks were acquired before this insertion, so no other
        # recipient Memory writer can commit until this copy finishes.
        cur.execute(
            """SELECT 1 FROM vault_ai_memory WHERE vault_id=%s
                  AND superseded_at IS NULL AND
                  (payload_ciphertext IS NULL OR
                   OCTET_LENGTH(payload_ciphertext)<29 OR
                   GET_BYTE(payload_ciphertext,0)<>1 OR
                   memory_record_id IS NULL OR memory_lookup_hash IS NULL)
                LIMIT 1""",
            (principal["vault_id"],),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="beneficiary_memory_not_private_ready")
        destination_hash = _destination_hash(
            inserted, link_id=payload.beneficiary_link_id,
            source_memory_id=payload.source_memory_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        cur.execute(
            """INSERT INTO linked_inheritance_v2_memory_copies (
                  old_link_id,source_memory_id,beneficiary_vault_id,
                  beneficiary_memory_id,stage_revision,
                  source_inventory_sha256,source_row_sha256,
                  destination_ciphertext_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (payload.beneficiary_link_id, payload.source_memory_id,
             principal["vault_id"], inserted["id"], payload.stage_revision,
             digest, source["source_row_sha256"], destination_hash),
        )
        after = _memory_vault_states(
            cur, owner_id=owner_id, beneficiary_id=beneficiary_id,
            lock=False,
        )
        if (after[owner_id]["memory_inventory_generation"] !=
                before[owner_id]["memory_inventory_generation"] or
                after[beneficiary_id]["memory_inventory_generation"] !=
                before[beneficiary_id]["memory_inventory_generation"] + 1):
            raise HTTPException(status_code=409, detail="memory_inventory_changed")
        conn.commit()
        return {
            "beneficiary_link_id": payload.beneficiary_link_id,
            "source_memory_id": payload.source_memory_id,
            "beneficiary_memory_id": int(inserted["id"]),
            "source_inventory_sha256": digest,
            "created": True,
            "legacy_package_preserved": True,
        }
    except UniqueViolation as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail="memory_copy_conflict") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/inheritance/old-link-v2/{link_id}/memory-copies")
def readback_linked_v2_memory_copies(
    link_id: int,
    http_response: Response,
    source_inventory_sha256: str = Query(pattern=r"^[A-Za-z0-9_-]{43}$"),
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    if link_id <= 0 or not _DIGEST.fullmatch(source_inventory_sha256):
        raise HTTPException(status_code=400, detail="invalid_source_inventory")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, stage = _context(
            cur, link_id=link_id,
            beneficiary_vault_id=str(principal["vault_id"]),
        )
        owner_id = str(link["passer_vault_id"])
        beneficiary_id = str(principal["vault_id"])
        before = _memory_vault_states(
            cur, owner_id=owner_id, beneficiary_id=beneficiary_id,
            lock=False,
        )
        enforce_export_rate_limit(vault_id=str(principal["vault_id"]))
        sources, digest, _ = _inventory(
            cur, link_id=link_id, link=link, stage=stage,
        )
        if digest != source_inventory_sha256:
            raise HTTPException(status_code=409, detail="source_inventory_changed")
        cur.execute(
            """SELECT c.source_memory_id,c.beneficiary_memory_id,
                      c.beneficiary_vault_id,c.stage_revision,
                      c.source_inventory_sha256,c.source_row_sha256,
                      c.destination_ciphertext_sha256,
                      m.vault_id AS destination_vault_id,
                      m.memory_record_id,m.memory_type,m.memory_key,
                      m.memory_value,m.memory_normalized_key,
                      m.payload_ciphertext,m.memory_lookup_hash,m.superseded_at,
                      m.id
                 FROM linked_inheritance_v2_memory_copies c
                 JOIN vault_ai_memory m ON m.id=c.beneficiary_memory_id
                WHERE c.old_link_id=%s ORDER BY c.source_memory_id
                FOR SHARE OF c,m""",
            (link_id,),
        )
        copies = cur.fetchall() or []
        if len(copies) > len(sources):
            raise HTTPException(status_code=409, detail="memory_copy_mismatch")
        expected = {row["memory_id"]: row for row in sources}
        rendered = []
        total = 0
        for row in copies:
            source = expected.get(row["source_memory_id"])
            if (source is None or
                    str(row["beneficiary_vault_id"]) !=
                    str(principal["vault_id"]) or
                    str(row["destination_vault_id"]) !=
                    str(principal["vault_id"]) or
                    row["stage_revision"] != stage["stage_revision"] or
                    row["source_inventory_sha256"] != digest or
                    bytes(row["source_row_sha256"]) !=
                    source["source_row_sha256"] or
                    row["memory_record_id"] !=
                    f"inherited-{link_id}-{row['source_memory_id']}" or
                    row["memory_type"] != source["memory_type"] or
                    row["memory_key"] is not None or
                    row["memory_value"] is not None or
                    row["memory_normalized_key"] is not None or
                    row["superseded_at"] is not None or
                    row["payload_ciphertext"] is None or
                    row["memory_lookup_hash"] is None or
                    not hmac.compare_digest(
                        _destination_hash(
                            row, link_id=link_id,
                            source_memory_id=row["source_memory_id"],
                            beneficiary_vault_id=str(principal["vault_id"]),
                        ), bytes(row["destination_ciphertext_sha256"]),
                    )):
                raise HTTPException(status_code=409, detail="memory_copy_mismatch")
            ciphertext = bytes(row["payload_ciphertext"])
            if (len(ciphertext) < 29 or ciphertext[0] != 1 or
                    len(ciphertext) > len(source["payload_ciphertext"]) +
                    _MAX_GROWTH):
                raise HTTPException(status_code=409, detail="memory_copy_mismatch")
            total += len(ciphertext)
            if total > _MAX_SOURCE_BYTES + len(sources) * _MAX_GROWTH:
                raise HTTPException(status_code=409, detail="memory_copy_exceeds_bound")
            rendered.append({
                "source_memory_id": row["source_memory_id"],
                "beneficiary_memory_id": row["beneficiary_memory_id"],
                "beneficiary_memory_record_id": row["memory_record_id"],
                "memory_type": row["memory_type"],
                "source_row_sha256": _b64(source["source_row_sha256"]),
                "memory_lookup_hash": _b64(bytes(row["memory_lookup_hash"])),
                "payload_ciphertext": _b64(ciphertext),
            })
        # Lock both vault generation rows after all existing source and
        # destination rows. A concurrent insert in either new-row gap is
        # detected here; locking first would deadlock with Memory triggers.
        locked = _memory_vault_states(
            cur, owner_id=owner_id, beneficiary_id=beneficiary_id,
            lock=True,
        )
        if (locked[owner_id]["memory_inventory_generation"] !=
                before[owner_id]["memory_inventory_generation"] or
                locked[beneficiary_id]["memory_inventory_generation"] !=
                before[beneficiary_id]["memory_inventory_generation"]):
            raise HTTPException(status_code=409, detail="memory_inventory_changed")
        if (not locked[beneficiary_id]["memory_mixed_title_fence_enabled"] or
                _recipient_has_unmapped_memory(
                    cur, link_id=link_id, beneficiary_id=beneficiary_id)):
            raise HTTPException(status_code=409, detail="beneficiary_memory_inventory_required")
        http_response.headers["Cache-Control"] = "no-store"
        return {
            "beneficiary_link_id": link_id,
            "owner_vault_id": str(link["passer_vault_id"]),
            "beneficiary_vault_id": str(link["beneficiary_vault_id"]),
            "stage_revision": int(stage["stage_revision"]),
            "offer_commitment": _offer_commitment(link_id, stage),
            "content_scope": "memory_only",
            "owner_content_complete": False,
            "source_inventory_sha256": digest,
            "memory_count": len(sources),
            "copies": rendered,
            "all_memories_copied": len(rendered) == len(sources),
            "legacy_package_preserved": True,
        }
    finally:
        conn.close()
