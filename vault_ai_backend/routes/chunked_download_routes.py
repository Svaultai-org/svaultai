

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from auth_local import verify_session_token
from device_gate import verify_trusted_device
from chunked_tokens import issue_chunk_token, load_ttl_seconds, verify_chunk_token
from vault_core import get_db, is_vault_zk_adopted, verify_vault_pin
from subscription_entitlement import require_file_read
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor


logger = logging.getLogger(__name__)

router = APIRouter()


DOWNLOAD_TOKEN_TTL_SECONDS = load_ttl_seconds(
    "VAULTAI_CHUNK_DOWNLOAD_TOKEN_TTL_SECONDS"
)


class DownloadManifestRequest(BaseModel):
    vault_name: str
    pin: str
    file_id: str


class DownloadChunkRequest(BaseModel):
    file_id: str
    chunk_index: int
    download_token: str


def _pin_free_chunked_manifest_enabled() -> None:
    if os.getenv(
        "VAULTAI_ZK_LEGACY_CHUNK_MANIFEST_ENABLED", "false",
    ).strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")
    if not os.getenv("VAULTAI_UPLOAD_TOKEN_SECRET"):
        raise HTTPException(status_code=503, detail="chunk_token_unavailable")


def _pin_free_chunked_manifest_sync(
    file_id: str, proof_token: str, principal: dict,
) -> dict:
    vault_id = str(principal["vault_id"])
    if not is_vault_zk_adopted(vault_id):
        raise HTTPException(status_code=409, detail="zk_vault_required")

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, file_size, chunk_size, chunk_count,
                   storage_mode, upload_status
              FROM uploaded_files
             WHERE id = %s AND vault_id = %s::uuid
             LIMIT 1
            """,
            (file_id, vault_id),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="file_not_found")
        if row["storage_mode"] != "chunks" or row["upload_status"] != "complete":
            raise HTTPException(status_code=409, detail="chunked_file_unavailable")
        file_size = int(row["file_size"] or 0)
        chunk_size = int(row["chunk_size"] or 0)
        chunk_count = int(row["chunk_count"] or 0)
        if (file_size <= 0 or chunk_size <= 0 or chunk_count <= 0 or
                chunk_count > 4096 or
                not (chunk_size * (chunk_count - 1) < file_size <=
                     chunk_size * chunk_count)):
            raise HTTPException(status_code=409, detail="chunked_file_unavailable")
        require_file_read(principal, file_size)
        # The proof is consumed in this transaction after ownership, status,
        # and entitlement have been checked. An error cannot issue a token.
        consume_recent_zk_proof_on_cursor(proof_token, principal, cur)
        download_token, expires_at = issue_chunk_token(
            kind="download", vault_id=vault_id, file_id=file_id,
            ttl_seconds=DOWNLOAD_TOKEN_TTL_SECONDS,
        )
        conn.commit()
        return {
            "file_id": file_id,
            "storage_mode": "chunks",
            "file_size": file_size,
            "chunk_size": chunk_size,
            "chunk_count": chunk_count,
            "download_token": download_token,
            "download_token_expires_at": expires_at,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/legacy-file/chunked/manifest")
async def pin_free_chunked_download_manifest(
    request: Request,
    principal=Depends(verify_trusted_device),
):
    """Issue the existing chunk token after a recent OPAQUE proof, no PIN."""
    _pin_free_chunked_manifest_enabled()
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 1024:
            raise HTTPException(status_code=413, detail="request_too_large")
        raw.extend(chunk)
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="invalid_request")
    if not isinstance(body, dict) or set(body) != {"file_id", "zk_proof_token"}:
        raise HTTPException(status_code=400, detail="invalid_request")
    file_id, proof = body["file_id"], body["zk_proof_token"]
    if (not isinstance(file_id, str) or not 1 <= len(file_id) <= 128 or
            "\x00" in file_id or "|" in file_id or not isinstance(proof, str) or
            not 1 <= len(proof) <= 128):
        raise HTTPException(status_code=400, detail="invalid_request")
    result = await run_in_threadpool(
        _pin_free_chunked_manifest_sync, file_id, proof, principal,
    )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/download-file/manifest")
async def download_file_manifest(
    payload: DownloadManifestRequest,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, file_name, content_type, file_size, storage_mode,
                   chunk_size, chunk_count, upload_status,
                   saved_name, asset_type, needs_naming
            FROM uploaded_files
            WHERE id = %s AND vault_id = %s
            LIMIT 1
            """,
            (payload.file_id, vault_id),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    require_file_read(principal, int(row["file_size"] or 0))
    if (row["upload_status"] or "complete") != "complete":
        raise HTTPException(status_code=409, detail="File upload not finalized yet")

    storage_mode = row["storage_mode"] or "inline"

    base = {
        "file_id": row["id"],
        "file_name": row["file_name"],
        "content_type": row["content_type"],
        "file_size": int(row["file_size"] or 0),
        "storage_mode": storage_mode,
        "saved_name": row["saved_name"],
        "asset_type": row["asset_type"],
        "needs_naming": bool(row["needs_naming"]),
    }

    if storage_mode == "inline":
        return {
            **base,
            "chunk_size": None,
            "chunk_count": None,
            "download_token": None,
            "download_token_expires_at": None,
            "next": "legacy",
        }

    if storage_mode == "chunks":
        download_token, exp = issue_chunk_token(
            kind="download",
            vault_id=vault_id,
            file_id=row["id"],
            ttl_seconds=DOWNLOAD_TOKEN_TTL_SECONDS,
        )
        return {
            **base,
            "chunk_size": int(row["chunk_size"] or 0),
            "chunk_count": int(row["chunk_count"] or 0),
            "download_token": download_token,
            "download_token_expires_at": exp,
            "next": "chunked",
        }

                                                      
    raise HTTPException(
        status_code=500,
        detail=f"Unknown storage_mode: {storage_mode!r}",
    )


@router.post("/download-file/chunk")
async def download_file_chunk(
    payload: DownloadChunkRequest,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    verify_chunk_token(
        payload.download_token,
        kind="download",
        vault_id=vault_id,
        file_id=payload.file_id,
    )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

                                                                        
        cur.execute(
            """
            SELECT vault_id, chunk_count, storage_mode, upload_status
            FROM uploaded_files
            WHERE id = %s
            LIMIT 1
            """,
            (payload.file_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
        if str(row["vault_id"]) != str(vault_id):
            raise HTTPException(status_code=403, detail="File not yours")
        if (row["storage_mode"] or "inline") != "chunks":
            raise HTTPException(
                status_code=400,
                detail="Inline file - use the legacy POST /download-file endpoint",
            )
        if (row["upload_status"] or "complete") != "complete":
            raise HTTPException(status_code=409, detail="Upload not finalized yet")

        chunk_count = int(row["chunk_count"] or 0)
        if not (0 <= payload.chunk_index < chunk_count):
            raise HTTPException(status_code=400, detail="chunk_index out of range")

        cur.execute(
            """
            SELECT chunk_bytes
            FROM uploaded_file_chunks
            WHERE file_id = %s AND chunk_index = %s
            LIMIT 1
            """,
            (payload.file_id, payload.chunk_index),
        )
        crow = cur.fetchone()
        if not crow:
            raise HTTPException(status_code=404, detail="Chunk missing")

        chunk_bytes = bytes(crow["chunk_bytes"])
    finally:
        conn.close()

    return Response(
        content=chunk_bytes,
        media_type="application/octet-stream",
        headers={
            "X-Chunk-Index": str(payload.chunk_index),
            "X-Chunk-Count": str(chunk_count),
                                                     
            "Cache-Control": "no-store",
        },
    )
