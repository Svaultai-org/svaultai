"""Default-off owner indexing of a verified legacy file's blind conflict tags.

An unlocked client first stages and reads back an exact MVK-encrypted V2 copy
of its older file. This endpoint accepts only MVK-derived opaque tokens, the
unchanged source snapshot, a short-lived session-bound readback receipt, and a
fresh OPAQUE proof. It does not activate private uploads or alter file bytes.
"""

from __future__ import annotations

import base64
import binascii
import os
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from file_private_conflict_index import index_existing_file, mark_index_complete
from legacy_source_snapshot import source_snapshot as legacy_source_snapshot
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from routes import legacy_ciphertext_migration_routes as migration
from vault_core import get_db


router = APIRouter()
FLAG_NAME = "VAULTAI_PRIVATE_FILE_CONFLICT_BACKFILL_ENABLED"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class IndexLegacyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str = Field(min_length=1, max_length=128)
    source_snapshot: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    readback_receipt: str = Field(min_length=1, max_length=256)
    content_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    name_tokens: list[str] = Field(min_length=1, max_length=2)
    zk_proof_token: str = Field(min_length=1, max_length=128)
    client_verified_exact_bytes: bool


class FinishIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zk_proof_token: str = Field(min_length=1, max_length=128)


def _enabled() -> None:
    if os.getenv(FLAG_NAME, "false").strip().lower() != "true":
        raise HTTPException(404, detail="not_found")


def _token(value: str) -> bytes:
    if not _TOKEN_RE.fullmatch(value):
        raise HTTPException(400, detail="private_file_conflict_token_invalid")
    try:
        raw = base64.urlsafe_b64decode(value + "=")
    except (binascii.Error, ValueError):
        raise HTTPException(400, detail="private_file_conflict_token_invalid")
    if (len(raw) != 32 or
            base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != value):
        raise HTTPException(400, detail="private_file_conflict_token_invalid")
    return raw


def _require_live_owner(cur, principal: SessionPrincipal) -> None:
    if not principal.get("file_v2_reader_capable", False):
        raise HTTPException(426, detail="client_update_required")
    # Rechecks OPAQUE authentication, vault lock state, device ID, and current
    # bearer inside this transaction. A revoked session cannot index a file.
    migration._require_live_legacy_item_edit_session(cur, principal)
    migration._require_live_delete_trusted_device(cur, principal)


@router.post("/vault/file-conflict/index-legacy")
def index_legacy_file(
    payload: IndexLegacyFile,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    if not payload.client_verified_exact_bytes:
        raise HTTPException(400, detail="client_readback_required")
    content = _token(payload.content_token)
    names = tuple(_token(value) for value in payload.name_tokens)
    if len(set(names)) != len(names):
        raise HTTPException(400, detail="private_file_conflict_token_invalid")
    vault_id = principal["vault_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _require_live_owner(cur, principal)
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))",
            (vault_id, payload.file_id),
        )
        row = migration._load_file_pair(
            cur, vault_id, payload.file_id, locked=True,
        )
        if (row.get("encrypted_file_data") is None or
                row.get("verification_state") != "not_verified"):
            raise HTTPException(409, detail="private_file_source_unavailable")
        cur.execute(
            "SELECT migrating_legacy,lifecycle_state "
            "FROM file_v2_records WHERE file_id=%s AND vault_id=%s",
            (payload.file_id, vault_id),
        )
        stage = cur.fetchone()
        if (stage is None or stage["migrating_legacy"] is not True or
                stage["lifecycle_state"] != "file_v2_written"):
            raise HTTPException(409, detail="private_file_stage_unavailable")
        digest, _ = migration._file_digest_and_v2_hash(
            cur, payload.file_id, row, locked=True,
        )
        snapshot = legacy_source_snapshot(
            "file", row, vault_id=vault_id, record_id=payload.file_id,
        )
        if snapshot != payload.source_snapshot:
            raise HTTPException(409, detail="legacy_source_changed")
        if not migration._receipt_valid(
            payload.readback_receipt, "f", principal, payload.file_id, digest,
        ):
            raise HTTPException(409, detail="readback_required")
        consume_recent_zk_proof_on_cursor(
            payload.zk_proof_token, principal, cur,
        )
        index_existing_file(
            cur, vault_id=vault_id, file_id=payload.file_id,
            file_size=int(row["file_size"]), content_token=content,
            name_tokens=names, expected_source_snapshot=snapshot,
        )
        conn.commit()
        return {"file_id": payload.file_id, "source_snapshot": snapshot,
                "indexed": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/file-conflict/index-complete")
def complete_index(
    payload: FinishIndex,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _require_live_owner(cur, principal)
        generation = mark_index_complete(cur, vault_id=principal["vault_id"])
        consume_recent_zk_proof_on_cursor(
            payload.zk_proof_token, principal, cur,
        )
        conn.commit()
        # Deliberately does not set enforced or open the new-file gate.
        return {"indexed": True, "inventory_generation": generation,
                "private_upload_enabled": False}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
