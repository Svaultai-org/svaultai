

from __future__ import annotations

import logging
import math
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from auth_local import verify_session_token
from device_gate import verify_trusted_device
from chunked_aead import CHUNK_NONCE_BYTES, CHUNK_TAG_BYTES
from chunked_tokens import issue_chunk_token, load_ttl_seconds, verify_chunk_token
from vault_core import MAX_VAULT_BYTES, get_db, verify_vault_pin
from zk_migration_flags import ZkMigrationFlags


logger = logging.getLogger(__name__)

router = APIRouter()


CHUNK_UPLOAD_MIN_CHUNK_BYTES   = 1   * 1024 * 1024         
CHUNK_UPLOAD_MAX_CHUNK_BYTES   = 16  * 1024 * 1024          
CHUNK_UPLOAD_MAX_CHUNKS        = 4096                                                   
CHUNK_UPLOAD_MAX_FILE_BYTES    = CHUNK_UPLOAD_MAX_CHUNK_BYTES * CHUNK_UPLOAD_MAX_CHUNKS
CHUNK_UPLOAD_TOKEN_TTL_SECONDS = load_ttl_seconds(
    "VAULTAI_CHUNK_UPLOAD_TOKEN_TTL_SECONDS"
)
CHUNK_UPLOAD_STALE_SECONDS     = 24 * 60 * 60              
CHUNK_FRAME_OVERHEAD           = CHUNK_NONCE_BYTES + CHUNK_TAG_BYTES      


class ChunkInitRequest(BaseModel):
    vault_name: str
    pin: str
    filename: Optional[str] = None
    content_type: Optional[str] = None
    total_bytes: int
    chunk_size: int
    content_sha256: Optional[str] = None


    is_batch_upload: bool = False


    relative_path: Optional[str] = None


    import_id: Optional[str] = None
    # ZK ciphertext-first mode. When present, uploaded_files row is
    # created with the ciphertext columns populated and the legacy
    # plaintext columns as NULL from the outset. `filename` above
    # remains transiently in request memory only (needed by
    # sanitize/normalize helpers) and is not written to the DB.
    filename_ciphertext: Optional[str] = None
    content_type_ciphertext: Optional[str] = None


class ChunkFinalizeRequest(BaseModel):
    vault_name: str
    pin: str
    file_id: str


class ChunkAbortRequest(BaseModel):
    vault_name: str
    pin: str
    file_id: str


def _sweep_stale_uploads_for(cursor, vault_id: str) -> None:


    cursor.execute(
        """
        WITH stale AS (
            DELETE FROM uploaded_files
            WHERE vault_id = %s
              AND upload_status = 'uploading'
              AND created_at < NOW() - INTERVAL '%s seconds'
            RETURNING file_size
        )
        SELECT COALESCE(SUM(file_size), 0)::BIGINT AS bytes_freed
        FROM stale
        """,
        (vault_id, CHUNK_UPLOAD_STALE_SECONDS),
    )
    row = cursor.fetchone()
    bytes_freed = int((row or {}).get("bytes_freed") or 0)
    if bytes_freed > 0:
        cursor.execute(
            """
            UPDATE vaults
            SET total_bytes = GREATEST(total_bytes - %s, 0)
            WHERE vault_id = %s
            """,
            (bytes_freed, vault_id),
        )


def sweep_all_stale_uploads() -> dict:


    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

                                                                        
        cur.execute(
            """
            WITH stale AS (
                DELETE FROM uploaded_files
                WHERE upload_status = 'uploading'
                  AND created_at < NOW() - INTERVAL '%s seconds'
                RETURNING vault_id, file_size
            )
            SELECT vault_id,
                   COUNT(*)::BIGINT       AS files_swept,
                   COALESCE(SUM(file_size), 0)::BIGINT AS bytes_freed
            FROM stale
            GROUP BY vault_id
            """,
            (CHUNK_UPLOAD_STALE_SECONDS,),
        )
        groups = cur.fetchall() or []

        total_files = 0
        total_bytes = 0
        for g in groups:
            cur.execute(
                """
                UPDATE vaults
                SET total_bytes = GREATEST(total_bytes - %s, 0)
                WHERE vault_id = %s
                """,
                (int(g["bytes_freed"] or 0), g["vault_id"]),
            )
            total_files += int(g["files_swept"] or 0)
            total_bytes += int(g["bytes_freed"] or 0)

        conn.commit()
        return {
            "files_swept": total_files,
            "vaults_touched": len(groups),
            "bytes_freed": total_bytes,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _expected_chunk_frame_len(chunk_index: int, chunk_size: int,
                              chunk_count: int, total_bytes: int) -> int:

    if chunk_index < chunk_count - 1:
        plain = chunk_size
    else:
        plain = total_bytes - (chunk_count - 1) * chunk_size
    return plain + CHUNK_FRAME_OVERHEAD


@router.post("/upload-file/init")
async def upload_file_init(
    payload: ChunkInitRequest,
    principal=Depends(verify_trusted_device),
):
    # FILE_V2 is fail-closed: callers must use ciphertext metadata and the
    # client-owned upload path. Legacy plaintext uploads remain available
    # while the flag is disabled.
    file_flags = ZkMigrationFlags.from_environment(os.environ)
    file_flags.validate_dependencies()
    if file_flags.file_write_enabled and not payload.filename_ciphertext:
        raise HTTPException(
            status_code=400,
            detail="file_v2_requires_ciphertext_metadata",
        )
    if not file_flags.file_write_enabled and not payload.filename:
        raise HTTPException(status_code=400, detail="filename_required")
    vault_id = principal["vault_id"]

                                                    
    verify_vault_pin(vault_id, payload.pin)

    if payload.total_bytes <= 0:
        raise HTTPException(status_code=400, detail="total_bytes must be > 0")
    if payload.total_bytes > CHUNK_UPLOAD_MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds chunked-upload size limit")
    if not (CHUNK_UPLOAD_MIN_CHUNK_BYTES <= payload.chunk_size <= CHUNK_UPLOAD_MAX_CHUNK_BYTES):
        raise HTTPException(
            status_code=400,
            detail=(
                f"chunk_size must be in "
                f"[{CHUNK_UPLOAD_MIN_CHUNK_BYTES}, {CHUNK_UPLOAD_MAX_CHUNK_BYTES}]"
            ),
        )

    chunk_count = math.ceil(payload.total_bytes / payload.chunk_size)
    if chunk_count > CHUNK_UPLOAD_MAX_CHUNKS:
        raise HTTPException(status_code=400, detail="chunk_count exceeds backend cap")

    file_id = str(uuid.uuid4())

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

                                                          
        _sweep_stale_uploads_for(cur, vault_id)

                                                                    
        cur.execute(
            """
            SELECT total_bytes
            FROM vaults
            WHERE vault_id = %s
            FOR UPDATE
            """,
            (vault_id,),
        )
        vn = cur.fetchone()
        if not vn:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Vault not found")

                                                                     
        from billing import get_account_id_for_vault, get_entitlement
        _billing_account_id = get_account_id_for_vault(vault_id)
        if _billing_account_id is None:
            _billing_limit = int(MAX_VAULT_BYTES)
            _billing_used = int(vn["total_bytes"] or 0)
        else:
            _ent = get_entitlement(_billing_account_id)
            _billing_limit = _ent.effective_limit_bytes
            _billing_used = _ent.used_bytes

        projected = _billing_used + payload.total_bytes
        if projected > _billing_limit:
            conn.rollback()
            used_mb = _billing_used / (1024 * 1024)
            limit_mb = _billing_limit / (1024 * 1024)
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "vault_storage_limit_exceeded",
                    "message": (
                        f"Vault storage limit reached. "
                        f"Used {used_mb:.0f} MB of {limit_mb:.0f} MB. "
                        f"Delete data before uploading more."
                    ),
                    "used_bytes": _billing_used,
                    "projected_bytes": projected,
                    "limit_bytes": _billing_limit,
                    "requested_bytes": payload.total_bytes,
                },
            )

                                                                   
        default_saved_name: Optional[str] = None
        needs_naming_default = True
        if payload.is_batch_upload:
            try:
                from main import _normalize_asset_name as _normalize
                normalized_default = _normalize(payload.filename or "")
            except Exception:
                normalized_default = ""
            if normalized_default and normalized_default != "general":
                default_saved_name = normalized_default
                needs_naming_default = False

                                                                     
        try:
            from main import _sanitize_relative_path
            safe_relative_path = _sanitize_relative_path(payload.relative_path)
        except Exception:
                                                                     
                                                                     
            safe_relative_path = None

                                                                     
        try:
            from main import _validate_import_id_for_upload
            _validate_import_id_for_upload(vault_id, payload.import_id)
        except HTTPException:
            conn.rollback()
            raise

        # ZK ciphertext-first insert. When the client supplies
        # ciphertext for the readable metadata fields, the row is
        # created with the *_ciphertext columns populated and the
        # legacy plaintext columns NULL. Server never persists the
        # plaintext even transiently. The `payload.filename` (and
        # `payload.content_type`) are still available in request
        # memory for name-sanitization / audit only; they never
        # reach the DB when ZK ciphertext is present.
        import base64 as _b64
        import binascii as _binascii
        def _b64u_decode(val: Optional[str]) -> Optional[bytes]:
            if not val:
                return None
            try:
                return _b64.urlsafe_b64decode(val + "=" * (-len(val) % 4))
            except (_binascii.Error, ValueError):
                raise HTTPException(
                    status_code=400,
                    detail="ciphertext must be base64url",
                )

        filename_ct = _b64u_decode(payload.filename_ciphertext)
        content_type_ct = _b64u_decode(payload.content_type_ciphertext)
        is_zk_upload = filename_ct is not None

        if is_zk_upload:
            cur.execute(
                """
                INSERT INTO uploaded_files (
                    id, vault_id, file_name, content_type, file_size,
                    encrypted_file_data, extracted_text,
                    extracted_text_encrypted,
                    detected_type, detected_service, autosaved_secret,
                    saved_name, asset_type, needs_naming,
                    storage_mode, chunk_size, chunk_count, upload_status,
                    relative_path, import_id,
                    file_name_ciphertext, content_type_ciphertext
                ) VALUES (
                    %s, %s, NULL, NULL, %s,
                    NULL, NULL, FALSE,
                    NULL, NULL, FALSE,
                    NULL, NULL, %s,
                    'chunks', %s, %s, 'uploading',
                    %s, %s,
                    %s, %s
                )
                """,
                (
                    file_id, vault_id, payload.total_bytes,
                    needs_naming_default,
                    payload.chunk_size, chunk_count,
                    safe_relative_path,
                    payload.import_id,
                    filename_ct, content_type_ct,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO uploaded_files (
                    id, vault_id, file_name, content_type, file_size,
                    encrypted_file_data, extracted_text, extracted_text_encrypted,
                    detected_type, detected_service, autosaved_secret,
                    saved_name, asset_type, needs_naming,
                    storage_mode, chunk_size, chunk_count, upload_status,
                    relative_path, import_id
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    NULL, NULL, FALSE,
                    %s, %s, FALSE,
                    %s, %s, %s,
                    'chunks', %s, %s, 'uploading',
                    %s, %s
                )
                """,
                (
                    file_id, vault_id, payload.filename,
                    payload.content_type, payload.total_bytes,
                    "file", "general",
                    default_saved_name,
                    "file",
                    needs_naming_default,
                    payload.chunk_size, chunk_count,
                    safe_relative_path,
                    payload.import_id,
                ),
            )

                                                                            
        if not is_zk_upload:
            try:
                from main import client as _openai_client
                from semantic_embedder import enqueue_uploaded_file_embedding
                enqueue_uploaded_file_embedding(_openai_client, vault_id, file_id, "file_name", payload.filename)
                enqueue_uploaded_file_embedding(_openai_client, vault_id, file_id, "asset_type", "file")
                enqueue_uploaded_file_embedding(_openai_client, vault_id, file_id, "detected_service", "general")
            except Exception:
                pass
        if not is_zk_upload:
            try:
                from asset_tagger import tag_uploaded_file_safe
                tag_uploaded_file_safe(
                    vault_id, file_id,
                    file_name=payload.filename, asset_type="file",
                    content_type=payload.content_type, detected_service="general",
                )
            except Exception:
                pass

        cur.execute(
            """
            UPDATE vaults
            SET total_bytes = total_bytes + %s
            WHERE vault_id = %s
            """,
            (payload.total_bytes, vault_id),
        )

        conn.commit()
    finally:
        conn.close()

    upload_token, exp = issue_chunk_token(
        kind="upload",
        vault_id=vault_id,
        file_id=file_id,
        ttl_seconds=CHUNK_UPLOAD_TOKEN_TTL_SECONDS,
    )
    return {
        "status": "initialized",
        "file_id": file_id,
        "chunk_size": payload.chunk_size,
        "chunk_count": chunk_count,
        "total_bytes": payload.total_bytes,
        "upload_token": upload_token,
        "upload_token_expires_at": exp,
        "max_chunk_frame_bytes": CHUNK_UPLOAD_MAX_CHUNK_BYTES + CHUNK_FRAME_OVERHEAD,
    }


@router.post("/upload-file/chunk")
async def upload_file_chunk(
    file_id: str = Form(...),
    chunk_index: int = Form(...),
    upload_token: str = Form(...),
    chunk: UploadFile = File(...),
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    verify_chunk_token(upload_token, kind="upload", vault_id=vault_id, file_id=file_id)

    chunk_bytes = await chunk.read()
    if len(chunk_bytes) < CHUNK_FRAME_OVERHEAD:
        raise HTTPException(status_code=400, detail="Chunk frame too short")
    if len(chunk_bytes) > CHUNK_UPLOAD_MAX_CHUNK_BYTES + CHUNK_FRAME_OVERHEAD:
        raise HTTPException(status_code=413, detail="Chunk frame exceeds max size")

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT vault_id, chunk_size, chunk_count, file_size,
                   upload_status, storage_mode
            FROM uploaded_files
            WHERE id = %s
            FOR UPDATE
            """,
            (file_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Upload not found")
        if str(row["vault_id"]) != str(vault_id):
            conn.rollback()
            raise HTTPException(status_code=403, detail="Upload not yours")
        if row["storage_mode"] != "chunks" or row["upload_status"] != "uploading":
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="Upload is not in an active chunked-uploading state",
            )

        chunk_count = int(row["chunk_count"] or 0)
        if not (0 <= chunk_index < chunk_count):
            conn.rollback()
            raise HTTPException(status_code=400, detail="chunk_index out of range")

        expected_len = _expected_chunk_frame_len(
            chunk_index,
            int(row["chunk_size"]),
            chunk_count,
            int(row["file_size"]),
        )
        if len(chunk_bytes) != expected_len:
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Chunk frame length mismatch "
                    f"(got {len(chunk_bytes)}, expected {expected_len})"
                ),
            )

        cur.execute(
            """
            INSERT INTO uploaded_file_chunks (file_id, chunk_index, chunk_bytes)
            VALUES (%s, %s, %s)
            ON CONFLICT (file_id, chunk_index)
            DO UPDATE SET chunk_bytes = EXCLUDED.chunk_bytes,
                          created_at  = CURRENT_TIMESTAMP
            """,
            (file_id, chunk_index, psycopg2_bytea(chunk_bytes)),
        )

        cur.execute(
            "SELECT COUNT(*) AS n FROM uploaded_file_chunks WHERE file_id = %s",
            (file_id,),
        )
        received_count = int((cur.fetchone() or {}).get("n") or 0)

        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "file_id": file_id,
        "chunk_index": chunk_index,
        "received_count": received_count,
        "chunk_count": chunk_count,
    }


@router.post("/upload-file/finalize")
async def upload_file_finalize(
    payload: ChunkFinalizeRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT chunk_count, file_size, upload_status, storage_mode,
                   file_name, saved_name, asset_type, content_type,
                   detected_service, import_id
            FROM uploaded_files
            WHERE id = %s AND vault_id = %s
            FOR UPDATE
            """,
            (payload.file_id, vault_id),
        )
        row = cur.fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Upload not found")
        if row["storage_mode"] != "chunks":
            conn.rollback()
            raise HTTPException(status_code=409, detail="Not a chunked upload")
        if row["upload_status"] == "complete":
            conn.rollback()
            return {
                "status": "already_finalized",
                "file_id": payload.file_id,
                "chunk_count": int(row["chunk_count"] or 0),
                "file_size": int(row["file_size"] or 0),
            }
        if row["upload_status"] != "uploading":
            conn.rollback()
            raise HTTPException(status_code=409, detail="Upload is not in 'uploading' state")

        chunk_count = int(row["chunk_count"] or 0)

        cur.execute(
            """
            SELECT chunk_index FROM uploaded_file_chunks WHERE file_id = %s
            """,
            (payload.file_id,),
        )
        present = {int(r["chunk_index"]) for r in (cur.fetchall() or [])}
        expected = set(range(chunk_count))
        missing = sorted(expected - present)
        if missing:
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "missing_chunks",
                    "message": f"Cannot finalize: {len(missing)} chunk(s) missing.",
                    "missing_chunks": missing[:32],
                    "missing_count": len(missing),
                },
            )

        cur.execute(
            """
            UPDATE uploaded_files
            SET upload_status = 'complete'
            WHERE id = %s AND vault_id = %s AND upload_status = 'uploading'
            """,
            (payload.file_id, vault_id),
        )
        conn.commit()
    finally:
        conn.close()

                                                                    
    try:
        from main import kickoff_analysis_for_uploaded_file
        kickoff_analysis_for_uploaded_file(
            vault_id=vault_id,
            file_id=payload.file_id,
            file_name=row.get("file_name"),
            content_type=row.get("content_type"),
        )
    except Exception:
        pass

                                                                        
    try:
        from document_understanding import extract_and_store_document_safe
        extract_and_store_document_safe(
            vault_id, payload.file_id,
            file_name=row["file_name"],
            saved_name=row["saved_name"],
            asset_type=row["asset_type"],
            content_type=row["content_type"],
            detected_service=row["detected_service"],
            extracted_text=None,
            extracted_text_encrypted=True,
        )
    except Exception:
        pass

                                                                
    try:
        from main import _bump_import_batch_on_upload_success
        _bump_import_batch_on_upload_success(
            vault_id=vault_id,
            import_id=row.get("import_id") if isinstance(row, dict) else row["import_id"],
            file_size=int(row["file_size"] or 0),
        )
    except Exception:
        pass

    return {
        "status": "complete",
        "file_id": payload.file_id,
        "chunk_count": chunk_count,
        "file_size": int(row["file_size"] or 0),
    }


@router.post("/upload-file/abort")
async def upload_file_abort(
    payload: ChunkAbortRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            DELETE FROM uploaded_files
            WHERE id = %s
              AND vault_id = %s
              AND upload_status = 'uploading'
            RETURNING file_size, import_id
            """,
            (payload.file_id, vault_id),
        )
        deleted = cur.fetchone()

        if not deleted:
            conn.commit()
            return {"status": "already_aborted_or_finalized", "file_id": payload.file_id}

        cur.execute(
            """
            UPDATE vaults
            SET total_bytes = GREATEST(total_bytes - %s, 0)
            WHERE vault_id = %s
            """,
            (int(deleted["file_size"] or 0), vault_id),
        )
        conn.commit()
    finally:
        conn.close()

                                                                      
    try:
        from main import _bump_import_batch_on_failure
        _bump_import_batch_on_failure(
            vault_id=vault_id,
            import_id=deleted.get("import_id") if isinstance(deleted, dict) else deleted["import_id"],
        )
    except Exception:
        pass

    return {
        "status": "aborted",
        "file_id": payload.file_id,
        "released_bytes": int(deleted["file_size"] or 0),
    }


def psycopg2_bytea(b: bytes) -> bytes:
    return b
