"""Two-phase, client-verified migration from PIN ciphertext to MVK v2.

Stage never removes the legacy copy. Readback returns only client-supplied V2
ciphertext and a short-lived receipt bound to the current legacy and V2 bytes.
Retirement is a separate, default-disabled, one-time OPAQUE proof-gated step.
The client must decrypt readback and compare exact content before requesting
retirement; the server cannot verify plaintext without breaking ZK.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal, _get_secret
from device_gate import verify_trusted_device
from legacy_source_snapshot import source_snapshot as legacy_source_snapshot
from routes.auth_zk_routes import consume_recent_zk_proof
from subscription_entitlement import require_content_write
from vault_core import get_db


router = APIRouter()

RECEIPT_TTL_SECONDS = 10 * 60
MAX_ITEM_CIPHERTEXT_BYTES = 128 * 1024
MAX_FILE_MIGRATION_CIPHERTEXT_BYTES = 64 * 1024 * 1024
MAX_FILE_MIGRATION_CHUNKS = 4096


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _require_flag(name: str) -> None:
    if not _flag(name):
        raise HTTPException(status_code=404, detail="not_found")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str, *, field: str, max_bytes: int) -> bytes:
    if len(value) > max_bytes * 2:
        raise HTTPException(status_code=413, detail=f"{field}_too_large")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail=f"{field}_invalid")
    if not raw or len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail=f"{field}_invalid")
    return raw


def _feed_digest(hasher, value: object) -> None:
    if value is None:
        raw = b""
    elif isinstance(value, (str, int)):
        raw = str(value).encode("utf-8")
    else:
        raw = bytes(value)
    hasher.update(len(raw).to_bytes(8, "big"))
    hasher.update(raw)


def _item_digest(row: dict) -> bytes:
    hasher = hashlib.sha256(b"legacy-item-migration/v1\x00")
    for field in (
        "encrypted_data", "item_type", "service",
        "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
    ):
        _feed_digest(hasher, row.get(field))
    return hasher.digest()


def _receipt_tag(
    domain: bytes,
    principal: SessionPrincipal,
    record_id: str,
    digest: bytes,
    expiry: int,
) -> bytes:
    message = (
        domain
        + uuid.UUID(str(principal["vault_id"])).bytes
        + uuid.UUID(str(principal["token_id"])).bytes
        + expiry.to_bytes(8, "big")
        + len(record_id).to_bytes(2, "big")
        + record_id.encode("utf-8")
        + digest
    )
    return hmac.new(_get_secret(), message, hashlib.sha256).digest()


def _new_receipt(
    kind: str, principal: SessionPrincipal,
    record_id: str, digest: bytes,
) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=RECEIPT_TTL_SECONDS,
    )
    expiry = int(expires_at.timestamp())
    domain = f"legacy-{kind}-readback/v1\x00".encode("ascii")
    tag = _receipt_tag(domain, principal, record_id, digest, expiry)
    return (f"{kind}r1.{expiry}.{_b64(digest)}.{_b64(tag)}", expires_at)


def _receipt_valid(
    receipt: str, kind: str, principal: SessionPrincipal,
    record_id: str, digest: bytes, *, now_ts: Optional[int] = None,
) -> bool:
    try:
        version, expiry_text, digest_text, tag_text = receipt.split(".")
        if version != f"{kind}r1":
            return False
        expiry = int(expiry_text)
        now = int(time.time()) if now_ts is None else now_ts
        if expiry <= now or expiry > now + RECEIPT_TTL_SECONDS:
            return False
        encoded_digest = base64.urlsafe_b64decode(
            digest_text + "=" * (-len(digest_text) % 4),
        )
        tag = base64.urlsafe_b64decode(
            tag_text + "=" * (-len(tag_text) % 4),
        )
        if len(encoded_digest) != 32 or len(tag) != 32:
            return False
        if not hmac.compare_digest(encoded_digest, digest):
            return False
        domain = f"legacy-{kind}-readback/v1\x00".encode("ascii")
        expected = _receipt_tag(domain, principal, record_id, digest, expiry)
        return hmac.compare_digest(tag, expected)
    except (ValueError, OverflowError, KeyError, binascii.Error):
        return False


class ItemStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(..., gt=0)
    item_type_ciphertext: str = Field(..., min_length=1)
    service_ciphertext: str = Field(..., min_length=1)
    payload_ciphertext: str = Field(..., min_length=1)
    source_snapshot: str = Field(..., min_length=43, max_length=43)


class ItemRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(..., gt=0)
    readback_receipt: str = Field(..., min_length=1, max_length=256)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    source_snapshot: str = Field(..., min_length=43, max_length=43)


class FileRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str = Field(..., min_length=1, max_length=128)
    readback_receipt: str = Field(..., min_length=1, max_length=256)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    client_verified_exact_bytes: bool
    source_snapshot: str = Field(..., min_length=43, max_length=43)


_ITEM_COLUMNS = (
    "encrypted_data, item_type, service, item_type_ciphertext, "
    "service_ciphertext, payload_ciphertext"
)


def _load_item_locked(cur, vault_id: str, item_id: int) -> dict:
    cur.execute(
        f"SELECT {_ITEM_COLUMNS} FROM vault_items "
        "WHERE vault_id = %s AND id = %s FOR UPDATE",
        (vault_id, item_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="legacy_item_not_found")
    return row


def _item_v2_complete(row: dict) -> bool:
    return all(row.get(field) is not None for field in (
        "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
    ))


@router.post("/vault/legacy-ciphertext/migrate/item-stage")
def stage_legacy_item(
    payload: ItemStageRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED")
    require_content_write(principal)
    ciphertexts = (
        _decode(payload.item_type_ciphertext, field="item_type_ciphertext",
                max_bytes=MAX_ITEM_CIPHERTEXT_BYTES),
        _decode(payload.service_ciphertext, field="service_ciphertext",
                max_bytes=MAX_ITEM_CIPHERTEXT_BYTES),
        _decode(payload.payload_ciphertext, field="payload_ciphertext",
                max_bytes=MAX_ITEM_CIPHERTEXT_BYTES),
    )
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_item_locked(cur, principal["vault_id"], payload.item_id)
        if row.get("encrypted_data") is None:
            raise HTTPException(status_code=409, detail="item_not_legacy")
        if legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"],
            record_id=payload.item_id,
        ) != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        existing = tuple(row.get(field) for field in (
            "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
        ))
        if row.get("payload_ciphertext") is not None:
            if not _item_v2_complete(row) or tuple(
                bytes(value) for value in existing
            ) != ciphertexts:
                raise HTTPException(status_code=409, detail="staged_item_conflict")
            conn.commit()
            return {"item_id": payload.item_id, "staged": True,
                    "created": False,
                    "source_snapshot": payload.source_snapshot}
        cur.execute(
            """
            UPDATE vault_items
               SET item_type_ciphertext = %s,
                   service_ciphertext = %s,
                   payload_ciphertext = %s
             WHERE id = %s AND vault_id = %s AND encrypted_data IS NOT NULL
            """,
            (*ciphertexts, payload.item_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="item_changed_during_stage")
        row.update(zip(("item_type_ciphertext", "service_ciphertext",
                        "payload_ciphertext"), ciphertexts))
        post_stage_snapshot = legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"],
            record_id=payload.item_id,
        )
        conn.commit()
        return {"item_id": payload.item_id, "staged": True, "created": True,
                "source_snapshot": post_stage_snapshot}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/vault/legacy-ciphertext/migrate/item-staged/{item_id}")
def readback_staged_item(
    item_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED")
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_item_id")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"SELECT {_ITEM_COLUMNS} FROM vault_items "
            "WHERE vault_id = %s AND id = %s",
            (principal["vault_id"], item_id),
        )
        row = cur.fetchone()
        if row is None or row.get("encrypted_data") is None:
            raise HTTPException(status_code=404, detail="legacy_item_not_found")
        if not _item_v2_complete(row):
            raise HTTPException(status_code=409, detail="item_not_staged")
        receipt, expires_at = _new_receipt(
            "i", principal, str(item_id), _item_digest(row),
        )
        return {
            "item_id": item_id,
            "source_snapshot": legacy_source_snapshot(
                "item", row, vault_id=principal["vault_id"],
                record_id=item_id,
            ),
            "item_type_ciphertext": _b64(bytes(row["item_type_ciphertext"])),
            "service_ciphertext": _b64(bytes(row["service_ciphertext"])),
            "payload_ciphertext": _b64(bytes(row["payload_ciphertext"])),
            "readback_receipt": receipt,
            "receipt_expires_at": expires_at,
        }
    finally:
        conn.close()


@router.post("/vault/legacy-ciphertext/migrate/item-retire")
def retire_legacy_item(
    payload: ItemRetireRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_ITEM_RETIRE_ENABLED")
    require_content_write(principal)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_item_locked(cur, principal["vault_id"], payload.item_id)
        if row.get("encrypted_data") is None and _item_v2_complete(row):
            conn.commit()
            return {"item_id": payload.item_id, "retired": True,
                    "already_retired": True}
        if row.get("encrypted_data") is None or not _item_v2_complete(row):
            raise HTTPException(status_code=409, detail="item_not_ready")
        digest = _item_digest(row)
        if legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"],
            record_id=payload.item_id,
        ) != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        if not _receipt_valid(
            payload.readback_receipt, "i", principal, str(payload.item_id), digest,
        ):
            raise HTTPException(status_code=409, detail="readback_required")
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            """
            UPDATE vault_items
               SET encrypted_data = NULL, item_type = NULL, service = NULL
             WHERE id = %s AND vault_id = %s
               AND encrypted_data IS NOT NULL
               AND item_type_ciphertext IS NOT NULL
               AND service_ciphertext IS NOT NULL
               AND payload_ciphertext IS NOT NULL
            """,
            (payload.item_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="item_changed_during_retire")
        conn.commit()
        return {"item_id": payload.item_id, "retired": True,
                "already_retired": False}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_FILE_COLUMNS = """
    u.id, u.file_size, u.file_name, u.saved_name, u.content_type,
    u.detected_type, u.detected_service, u.asset_type,
    u.extracted_text, u.relative_path, u.encrypted_file_data,
    u.file_name_ciphertext, u.saved_name_ciphertext,
    u.content_type_ciphertext, u.detected_type_ciphertext,
    u.detected_service_ciphertext, u.asset_type_ciphertext,
    r.manifest_ciphertext, r.total_bytes, r.chunk_size, r.chunk_count,
    r.crypto_version, r.verification_state
"""


def _load_file_pair(cur, vault_id: str, file_id: str, *, locked: bool) -> dict:
    # Bound the legacy inline blob before reading it into the process. Future
    # larger files need a streamed migration path; never silently skip them.
    cur.execute(
        """
        SELECT LENGTH(encrypted_file_data) AS legacy_chars
          FROM uploaded_files
         WHERE id = %s AND vault_id = %s AND storage_mode = 'inline'
        """,
        (file_id, vault_id),
    )
    legacy = cur.fetchone()
    if legacy is None:
        raise HTTPException(status_code=404, detail="legacy_file_not_found")
    if (legacy.get("legacy_chars") or 0) > MAX_FILE_MIGRATION_CIPHERTEXT_BYTES:
        raise HTTPException(status_code=413, detail="file_migration_streaming_required")

    cur.execute(
        "SELECT OCTET_LENGTH(manifest_ciphertext) AS manifest_bytes "
        "FROM file_v2_records WHERE file_id = %s AND vault_id = %s",
        (file_id, vault_id),
    )
    manifest_size = cur.fetchone()
    if manifest_size is None:
        raise HTTPException(status_code=409, detail="file_v2_not_staged")
    if int(manifest_size["manifest_bytes"]) > MAX_ITEM_CIPHERTEXT_BYTES:
        raise HTTPException(status_code=413, detail="file_manifest_too_large")

    cur.execute(
        f"SELECT {_FILE_COLUMNS} FROM uploaded_files u "
        "JOIN file_v2_records r ON r.file_id = u.id AND r.vault_id = %s "
        "WHERE u.id = %s AND u.vault_id = %s AND u.storage_mode = 'inline' "
        + ("FOR UPDATE OF u, r" if locked else ""),
        (vault_id, file_id, vault_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail="file_v2_not_staged")
    if row["crypto_version"] != "client_mvk_v2":
        raise HTTPException(status_code=409, detail="file_v2_crypto_version_mismatch")
    if int(row["total_bytes"]) != int(row["file_size"]):
        raise HTTPException(status_code=409, detail="file_v2_size_mismatch")
    return row


def _file_digest_and_v2_hash(
    cur, file_id: str, row: dict, *, locked: bool,
) -> tuple[bytes, str]:
    if row.get("extracted_text") is not None or row.get("relative_path") is not None:
        raise HTTPException(status_code=409, detail="file_extra_legacy_data_requires_migration")
    legacy_ciphertext = row.get("encrypted_file_data")
    if legacy_ciphertext is None:
        raise HTTPException(status_code=409, detail="file_already_retired")

    if int(row["chunk_count"]) > MAX_FILE_MIGRATION_CHUNKS:
        raise HTTPException(status_code=413, detail="file_migration_streaming_required")
    cur.execute(
        "SELECT COUNT(*) AS chunk_count, "
        "COALESCE(SUM(OCTET_LENGTH(ciphertext)), 0) AS ciphertext_bytes "
        "FROM file_v2_chunks WHERE file_id = %s",
        (file_id,),
    )
    aggregate = cur.fetchone() or {}
    if int(aggregate.get("chunk_count") or 0) != int(row["chunk_count"]):
        raise HTTPException(status_code=409, detail="file_v2_chunks_incomplete")
    if int(aggregate.get("ciphertext_bytes") or 0) > MAX_FILE_MIGRATION_CIPHERTEXT_BYTES:
        raise HTTPException(status_code=413, detail="file_migration_streaming_required")
    cur.execute(
        "SELECT chunk_index, ciphertext FROM file_v2_chunks "
        "WHERE file_id = %s ORDER BY chunk_index "
        + ("FOR UPDATE" if locked else ""),
        (file_id,),
    )
    chunks = cur.fetchall() or []
    expected_count = int(row["chunk_count"])
    if len(chunks) != expected_count:
        raise HTTPException(status_code=409, detail="file_v2_chunks_incomplete")
    if any(int(chunk["chunk_index"]) != index or not chunk["ciphertext"]
           for index, chunk in enumerate(chunks)):
        raise HTTPException(status_code=409, detail="file_v2_chunks_incomplete")
    v2_bytes = len(bytes(row["manifest_ciphertext"])) + sum(
        len(bytes(chunk["ciphertext"])) for chunk in chunks
    )
    if v2_bytes > MAX_FILE_MIGRATION_CIPHERTEXT_BYTES:
        raise HTTPException(status_code=413, detail="file_migration_streaming_required")

    v2_hasher = hashlib.sha256(b"file-v2-readback/v1\x00")
    _feed_digest(v2_hasher, row["manifest_ciphertext"])
    for index, chunk in enumerate(chunks):
        _feed_digest(v2_hasher, index.to_bytes(8, "big"))
        _feed_digest(v2_hasher, chunk["ciphertext"])

    hasher = hashlib.sha256(b"legacy-file-migration/v1\x00")
    for field in (
        "encrypted_file_data", "file_name", "saved_name", "content_type",
        "detected_type", "detected_service", "asset_type", "file_size",
        "file_name_ciphertext", "saved_name_ciphertext",
        "content_type_ciphertext", "detected_type_ciphertext",
        "detected_service_ciphertext", "asset_type_ciphertext",
    ):
        _feed_digest(hasher, row.get(field))
    _feed_digest(hasher, v2_hasher.digest())
    return hasher.digest(), v2_hasher.hexdigest()


@router.get("/vault/legacy-ciphertext/migrate/file-staged/{file_id}")
def readback_staged_file(
    file_id: str,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED")
    if not file_id or len(file_id) > 128:
        raise HTTPException(status_code=400, detail="invalid_file_id")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_file_pair(cur, principal["vault_id"], file_id, locked=False)
        digest, v2_hash = _file_digest_and_v2_hash(
            cur, file_id, row, locked=False,
        )
        receipt, expires_at = _new_receipt(
            "f", principal, file_id, digest,
        )
        return {
            "file_id": file_id,
            "source_snapshot": legacy_source_snapshot(
                "file", row, vault_id=principal["vault_id"],
                record_id=file_id,
            ),
            "manifest_ciphertext": _b64(bytes(row["manifest_ciphertext"])),
            "chunk_count": int(row["chunk_count"]),
            "total_bytes": int(row["total_bytes"]),
            "v2_ciphertext_sha256": v2_hash,
            "readback_receipt": receipt,
            "receipt_expires_at": expires_at,
        }
    finally:
        conn.close()


@router.post("/vault/legacy-ciphertext/migrate/file-retire")
def retire_legacy_file(
    payload: FileRetireRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_FILE_RETIRE_ENABLED")
    require_content_write(principal)
    if not payload.client_verified_exact_bytes:
        raise HTTPException(status_code=400, detail="client_readback_required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            (principal["vault_id"], payload.file_id),
        )
        row = _load_file_pair(cur, principal["vault_id"], payload.file_id,
                              locked=True)
        if row.get("encrypted_file_data") is None:
            if row.get("verification_state") == "client_verified":
                conn.commit()
                return {"file_id": payload.file_id, "retired": True,
                        "already_retired": True}
            raise HTTPException(status_code=409, detail="file_retire_state_conflict")
        digest, _ = _file_digest_and_v2_hash(
            cur, payload.file_id, row, locked=True,
        )
        if legacy_source_snapshot(
            "file", row, vault_id=principal["vault_id"],
            record_id=payload.file_id,
        ) != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        if not _receipt_valid(
            payload.readback_receipt, "f", principal, payload.file_id, digest,
        ):
            raise HTTPException(status_code=409, detail="readback_required")
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            """
            UPDATE uploaded_files
               SET encrypted_file_data = NULL,
                   file_name = NULL, saved_name = NULL,
                   content_type = NULL, detected_type = NULL,
                   detected_service = NULL, asset_type = NULL
             WHERE id = %s AND vault_id = %s
               AND storage_mode = 'inline' AND encrypted_file_data IS NOT NULL
            """,
            (payload.file_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="file_changed_during_retire")
        cur.execute(
            """
            UPDATE file_v2_records
               SET verification_state = 'client_verified',
                   lifecycle_state = 'legacy_migration_retired'
             WHERE file_id = %s AND vault_id = %s
            """,
            (payload.file_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="file_v2_changed_during_retire")
        conn.commit()
        return {"file_id": payload.file_id, "retired": True,
                "already_retired": False}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
