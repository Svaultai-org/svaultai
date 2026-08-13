

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from auth_local import verify_session_token
from device_gate import verify_trusted_device
from chunked_tokens import issue_chunk_token, load_ttl_seconds, verify_chunk_token
from vault_core import get_db, verify_vault_pin
from subscription_entitlement import require_file_read


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
