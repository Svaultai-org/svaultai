

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device


logger = logging.getLogger(__name__)
router = APIRouter()


class _ReadTextRequest(BaseModel):
    pin: str
                                                                    
                                                              
    max_chars: Optional[int] = Field(default=None, ge=1, le=200_000)


def load_extracted_text(
    *, vault_id: str, file_id: str, key: bytes,
    max_chars: Optional[int] = None,
) -> dict:


    if not vault_id or not file_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "file_not_found", "file_id": file_id or ""},
        )
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, file_name, content_type, analysis_status,
                   extracted_text, analysis_last_error
            FROM uploaded_files
            WHERE id = %s AND vault_id = %s
            """,
            (file_id, vault_id),
        )
        row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
                                                                     
                                                                 
        raise HTTPException(
            status_code=404,
            detail={"code": "file_not_found", "file_id": file_id},
        )

    (_, file_name, content_type, analysis_status,
     encrypted_text, analysis_last_error) = row

    base = {
        "file_id":         file_id,
        "file_name":       file_name,
        "content_type":    content_type,
        "analysis_status": analysis_status,
        "analysis_last_error":  analysis_last_error,
    }
    if analysis_status != "analyzed":
        return {
            **base,
            "text":      None,
            "truncated": False,
            "note":      "file_not_yet_analyzed",
        }
    if not encrypted_text:
        return {
            **base,
            "text":      "",
            "truncated": False,
            "note":      "analyzed_but_no_text",
        }
    try:
        from vault_core import decrypt_message
        plaintext = decrypt_message(encrypted_text, key)
    except Exception:
                                                                   
                                                     
        logger.warning(
            "extracted_text decrypt failed vault=%s file_id=%s",
            _short(vault_id), _short(file_id),
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "decrypt_failed", "file_id": file_id},
        )

    truncated = False
    if max_chars and len(plaintext) > max_chars:
        plaintext = plaintext[:max_chars]
        truncated = True
    return {**base, "text": plaintext, "truncated": truncated, "note": None}


def _short(s: str) -> str:

    if not s:
        return ""
    return s[:8] + "…" if len(s) > 8 else s


@router.post("/vault/file/{file_id}/text")
async def read_file_text_route(
    file_id: str,
    payload: _ReadTextRequest,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    token_id = principal.get("token_id") or ""

    from main import get_verified_vault_key
    key = get_verified_vault_key(vault_id, payload.pin)

                                      
    try:
        from vault_key_cache import get_cache
        get_cache().store(vault_id=vault_id, token_id=token_id, key=key)
    except Exception:
                                                                
                                                                   
        logger.exception("vault_key_cache.store failed (non-fatal)")

    return load_extracted_text(
        vault_id=vault_id, file_id=file_id, key=key,
        max_chars=payload.max_chars,
    )


__all__ = ["router", "load_extracted_text"]
