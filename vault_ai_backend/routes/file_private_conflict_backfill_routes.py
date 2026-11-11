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
from file_private_conflict_index import (
    index_existing_file, index_ready_file, mark_index_complete,
    ready_file_source_revision,
)
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


class IndexReadyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str = Field(min_length=1, max_length=128)
    source_revision: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    content_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    name_tokens: list[str] = Field(min_length=1, max_length=2)
    zk_proof_token: str = Field(min_length=1, max_length=128)
    client_verified_exact_bytes: bool


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


def _ready_file_row(cur, *, vault_id: str, file_id: str,
                    locked: bool) -> dict | None:
    cur.execute(
        "SELECT r.file_id,r.manifest_ciphertext,"
        "r.saved_name_override_ciphertext,r.name_version,r.total_bytes,"
        "r.chunk_size,r.chunk_count,r.migration_metadata_version,"
        "r.lifecycle_state,r.verification_state,r.migrating_legacy,"
        "u.file_size AS marker_size,u.upload_status,u.storage_mode,"
        "u.encrypted_file_data IS NOT NULL AS has_legacy,"
        "u.file_name,u.saved_name,u.content_type,u.relative_path "
        "FROM file_v2_records r JOIN uploaded_files u "
        "ON u.id=r.file_id AND u.vault_id::text=r.vault_id "
        "WHERE r.file_id=%s AND r.vault_id=%s "
        + ("FOR UPDATE OF r,u" if locked else ""),
        (file_id, vault_id),
    )
    return cur.fetchone()


@router.get("/vault/file-conflict/ready-source/{file_id}")
def ready_file_source(
    file_id: str,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    if not file_id or len(file_id) > 128:
        raise HTTPException(400, detail="invalid_file_id")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _require_live_owner(cur, principal)
        row = _ready_file_row(
            cur, vault_id=principal["vault_id"], file_id=file_id,
            locked=False,
        )
        if row is None:
            raise HTTPException(404, detail="file_v2_not_found")
        revision = ready_file_source_revision(
            row, vault_id=principal["vault_id"], file_id=file_id,
        )
        return {"file_id": file_id, "source_revision": revision,
                "file_size": int(row["total_bytes"]),
                "name_version": int(row["name_version"])}
    finally:
        conn.close()


@router.post("/vault/file-conflict/index-ready")
def index_ready_v2_file(
    payload: IndexReadyFile,
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
        row = _ready_file_row(
            cur, vault_id=vault_id, file_id=payload.file_id, locked=True,
        )
        if row is None:
            raise HTTPException(404, detail="file_v2_not_found")
        if ready_file_source_revision(
            row, vault_id=vault_id, file_id=payload.file_id,
        ) != payload.source_revision:
            raise HTTPException(409, detail="private_file_ready_source_changed")
        consume_recent_zk_proof_on_cursor(
            payload.zk_proof_token, principal, cur,
        )
        index_ready_file(
            cur, vault_id=vault_id, file_id=payload.file_id,
            source_row=row, expected_source_revision=payload.source_revision,
            content_token=content, name_tokens=names,
        )
        conn.commit()
        return {"file_id": payload.file_id,
                "source_revision": payload.source_revision,
                "indexed": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
