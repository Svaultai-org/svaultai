"""Bounded encrypted legacy export for client-side MVK migration.

This route never accepts a PIN or decrypts vault content. A recent OPAQUE
proof is consumed once to create a short-lived, session-bound read grant.
Every page is serialized under a database row lock, has a monotonic sequence,
and consumes strict page and byte budgets. The grant is stored in the existing
short-lived ZK slot table; an ``e1.`` prefix keeps it out of login finalization.

The legacy database already stores item type/service and file size/content
type in plaintext. Those structural fields are returned only to this vault's
trusted session so the client can deterministically re-encrypt each record.
Secret values, file bytes, PINs, keys, and extracted text are never returned
in plaintext or logged by this module.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal, _get_secret
from legacy_source_snapshot import (
    FILE_SOURCE_FIELDS, ITEM_DELETE_FIELDS, MAX_SOURCE_CIPHERTEXT_CHARS,
    item_delete_snapshot,
    source_snapshot as legacy_source_snapshot,
)
from device_gate import verify_trusted_device
from routes.auth_zk_routes import consume_recent_zk_proof
from vault_core import get_db


router = APIRouter()

GRANT_VERSION = "e1"
GRANT_DOMAIN = b"legacy-ciphertext-export-grant/v1\x00"
GRANT_TTL_SECONDS = 5 * 60
GRANT_MAX_PAGES = 16
GRANT_MAX_BYTES = 32 * 1024 * 1024
PAGE_MAX_BYTES = 4 * 1024 * 1024 + 64 * 1024
CHUNK_MAX_CHARS = 4 * 1024 * 1024
LIST_MAX_RECORDS = 50
# Extra legacy fields can contain document text. Export them in a separate,
# proof-bound page so they are never repeated with every ciphertext chunk.
MAX_FILE_EXTRA_BYTES = 64 * 1024
MAX_FILE_EXTRA_V3_BYTES = 256 * 1024
FILE_EXTRA_V3_FLAG = "VAULTAI_ZK_LEGACY_FILE_EXTRA_V3_ENABLED"


def _enabled() -> bool:
    return os.getenv(
        "VAULTAI_ZK_LEGACY_EXPORT_ENABLED", "false",
    ).strip().lower() == "true"


def _require_enabled(principal: SessionPrincipal) -> None:
    from auth_local import PIN_FREE_SAVED_ITEM_MUTATION_OFFER
    signed_item_mutation = (
        principal.get("pin_free_read_offers", 0) &
        PIN_FREE_SAVED_ITEM_MUTATION_OFFER
    )
    if not _enabled() and not signed_item_mutation:
        raise HTTPException(status_code=404, detail="not_found")


def _require_file_extra_stage_enabled() -> None:
    if os.getenv(
        "VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED", "false",
    ).strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _require_file_extra_v3_enabled() -> None:
    _require_file_extra_stage_enabled()
    if os.getenv(FILE_EXTRA_V3_FLAG, "false").strip().lower() != "true":
        raise HTTPException(status_code=404, detail="not_found")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error):
        return b""


def _grant_tag(
    nonce: bytes, expiry: int, principal: SessionPrincipal,
) -> bytes:
    binding = (
        GRANT_DOMAIN
        + uuid.UUID(str(principal["vault_id"])).bytes
        + uuid.UUID(str(principal["token_id"])).bytes
        + expiry.to_bytes(8, "big")
        + nonce
    )
    return hmac.new(_get_secret(), binding, hashlib.sha256).digest()


def _new_grant_token(
    principal: SessionPrincipal,
) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=GRANT_TTL_SECONDS,
    )
    expiry = int(expires_at.timestamp())
    nonce = secrets.token_bytes(24)
    tag = _grant_tag(nonce, expiry, principal)
    return (
        f"{GRANT_VERSION}.{expiry}.{_b64(nonce)}.{_b64(tag)}",
        expires_at,
    )


def _grant_belongs_to_session(
    token: str, principal: SessionPrincipal, *, now_ts: Optional[int] = None,
) -> bool:
    try:
        version, expiry_text, nonce_text, tag_text = token.split(".")
        if version != GRANT_VERSION:
            return False
        expiry = int(expiry_text)
        now = int(time.time()) if now_ts is None else now_ts
        if expiry <= now or expiry > now + GRANT_TTL_SECONDS:
            return False
        nonce, tag = _unb64(nonce_text), _unb64(tag_text)
        if len(nonce) != 24 or len(tag) != 32:
            return False
        return hmac.compare_digest(tag, _grant_tag(nonce, expiry, principal))
    except (ValueError, OverflowError, KeyError):
        return False


class LegacyExportStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    zk_proof_token: str = Field(..., min_length=1, max_length=128)


class LegacyExportPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    export_token: str = Field(..., min_length=1, max_length=128)
    sequence: int = Field(..., ge=0)
    mode: Literal[
        "list_items", "list_files", "read_item", "read_file",
        "read_file_extra", "read_file_extra_v3",
    ]
    limit: int = Field(default=20, ge=1, le=LIST_MAX_RECORDS)
    after_item_id: int = Field(default=0, ge=0)
    after_file_id: str = Field(default="", max_length=128)
    item_id: Optional[int] = Field(default=None, gt=0)
    file_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    offset: int = Field(default=0, ge=0)
    max_chars: int = Field(default=CHUNK_MAX_CHARS, ge=1, le=CHUNK_MAX_CHARS)


def _assert_zk_vault(conn, vault_id: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT vault_handle IS NOT NULL FROM vaults "
        "WHERE vault_id = %s LIMIT 1",
        (vault_id,),
    )
    row = cur.fetchone()
    if row is None or not bool(row[0]):
        raise HTTPException(status_code=403, detail="private_vault_required")


@router.post("/vault/legacy-ciphertext/export/start")
def legacy_export_start(
    payload: LegacyExportStartRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
    http_response: Response = None,
) -> dict:
    _require_enabled(principal)
    # Do not burn the one-time proof if the account is ineligible.
    conn = get_db()
    try:
        _assert_zk_vault(conn, principal["vault_id"])
    finally:
        conn.close()
    consume_recent_zk_proof(payload.zk_proof_token, principal)

    token, expires_at = _new_grant_token(principal)
    state = {"sequence": 0, "pages_left": GRANT_MAX_PAGES,
             "bytes_left": GRANT_MAX_BYTES}
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vault_zk_login_slots
              (slot_id, vault_id, server_state, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (token, principal["vault_id"],
             json.dumps(state, separators=(",", ":")).encode("ascii"),
             expires_at),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if http_response is not None:
        http_response.headers["Cache-Control"] = "no-store"
    return {
        "export_token": token,
        "expires_at": expires_at,
        "next_sequence": 0,
        "pages_remaining": GRANT_MAX_PAGES,
        "bytes_remaining": GRANT_MAX_BYTES,
    }


def _metadata_b64(value: object) -> Optional[str]:
    if value is None:
        return None
    return _b64(bytes(value))


def _list_items(cur, vault_id: str, payload: LegacyExportPageRequest) -> dict:
    cur.execute(
        """
        SELECT id, LEFT(item_type, 257) AS item_type,
               LEFT(service, 257) AS service,
               item_type_ciphertext, service_ciphertext,
               LENGTH(encrypted_data) AS ciphertext_chars
          FROM vault_items
         WHERE vault_id = %s AND encrypted_data IS NOT NULL AND id > %s
         ORDER BY id LIMIT %s
        """,
        (vault_id, payload.after_item_id, payload.limit + 1),
    )
    rows = cur.fetchall() or []
    selected = rows[:payload.limit]
    records = []
    for row in selected:
        item_type = row["item_type"]
        service = row["service"]
        if len(item_type or "") > 256 or len(service or "") > 256:
            raise HTTPException(status_code=413, detail="legacy_metadata_too_large")
        records.append({
            "item_id": int(row["id"]),
            "item_type": item_type,
            "service": service,
            "item_type_ciphertext": _metadata_b64(
                row.get("item_type_ciphertext"),
            ),
            "service_ciphertext": _metadata_b64(
                row.get("service_ciphertext"),
            ),
            "ciphertext_chars": int(row["ciphertext_chars"]),
        })
    return {
        "records": records,
        "has_more": len(rows) > payload.limit,
        "next_after_item_id": records[-1]["item_id"] if records else None,
    }


def _list_files(cur, vault_id: str, payload: LegacyExportPageRequest) -> dict:
    cur.execute(
        """
        SELECT id, file_size, LEFT(content_type, 257) AS content_type,
               file_name_ciphertext, saved_name_ciphertext,
               content_type_ciphertext, detected_type_ciphertext,
               detected_service_ciphertext, asset_type_ciphertext,
               LENGTH(encrypted_file_data) AS ciphertext_chars,
               OCTET_LENGTH(extracted_text) AS extra_text_bytes,
               OCTET_LENGTH(relative_path) AS extra_path_bytes
          FROM uploaded_files
         WHERE vault_id = %s AND storage_mode = 'inline'
           AND upload_status = 'complete'
           AND encrypted_file_data IS NOT NULL AND id > %s
         ORDER BY id LIMIT %s
        """,
        (vault_id, payload.after_file_id, payload.limit + 1),
    )
    rows = cur.fetchall() or []
    selected = rows[:payload.limit]
    records = []
    for row in selected:
        content_type = row["content_type"] or ""
        file_id = str(row["id"])
        if len(content_type) > 256 or len(file_id) > 128:
            raise HTTPException(status_code=413, detail="legacy_metadata_too_large")
        records.append({
            "file_id": file_id,
            "file_size": int(row["file_size"]),
            "content_type": content_type,
            "ciphertext_chars": int(row["ciphertext_chars"]),
            "extra_text_bytes": int(row["extra_text_bytes"] or 0),
            "extra_path_bytes": int(row["extra_path_bytes"] or 0),
            **{
                field: _metadata_b64(row[field])
                for field in (
                    "file_name_ciphertext", "saved_name_ciphertext",
                    "content_type_ciphertext", "detected_type_ciphertext",
                    "detected_service_ciphertext", "asset_type_ciphertext",
                )
            },
        })
    return {
        "records": records,
        "has_more": len(rows) > payload.limit,
        "next_after_file_id": records[-1]["file_id"] if records else None,
    }


def _read_chunk(cur, vault_id: str, payload: LegacyExportPageRequest) -> dict:
    if payload.mode == "read_item":
        if payload.item_id is None:
            raise HTTPException(status_code=400, detail="item_id_required")
        table, id_column, data_column, record_id = (
            "vault_items", "id", "encrypted_data", payload.item_id,
        )
        id_key = "item_id"
        storage_clause = ""
        source_fields = ITEM_DELETE_FIELDS
        kind = "item"
    else:
        if payload.file_id is None:
            raise HTTPException(status_code=400, detail="file_id_required")
        table, id_column, data_column, record_id = (
            "uploaded_files", "id", "encrypted_file_data", payload.file_id,
        )
        id_key = "file_id"
        storage_clause = "AND storage_mode = 'inline' AND upload_status = 'complete'"
        source_fields = FILE_SOURCE_FIELDS
        kind = "file"
    # Table/column names are fixed code constants, never request parameters.
    cur.execute(
        f"SELECT LENGTH({data_column}) AS total_chars "
        f"FROM {table} WHERE vault_id = %s AND {id_column} = %s "
        f"AND {data_column} IS NOT NULL {storage_clause} FOR SHARE",
        (vault_id, record_id),
    )
    length_row = cur.fetchone()
    if length_row is None:
        raise HTTPException(status_code=404, detail="legacy_record_not_found")
    total = int(length_row["total_chars"])
    if total > MAX_SOURCE_CIPHERTEXT_CHARS:
        raise HTTPException(status_code=413, detail="legacy_streaming_required")
    if payload.offset > total:
        raise HTTPException(status_code=416, detail="offset_out_of_range")
    cur.execute(
        f"SELECT {', '.join(source_fields)} FROM {table} "
        f"WHERE vault_id = %s AND {id_column} = %s",
        (vault_id, record_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="legacy_record_not_found")
    ciphertext = row[data_column]
    if len(ciphertext) != total:
        raise HTTPException(status_code=409, detail="legacy_source_changed")
    chunk = ciphertext[payload.offset:payload.offset + payload.max_chars]
    next_offset = payload.offset + len(chunk)
    if kind == "item":
        metadata = {
            "item_type": row["item_type"],
            "service": row["service"],
            "item_type_ciphertext": _metadata_b64(row["item_type_ciphertext"]),
            "service_ciphertext": _metadata_b64(row["service_ciphertext"]),
            # The owner device compares a complete staged V2 copy with the
            # still-active legacy source before an edit may invalidate it.
            "payload_ciphertext": _metadata_b64(row["payload_ciphertext"]),
        }
    else:
        # Older clients can rename using plaintext columns. The owner needs
        # those latest labels to re-encrypt them before retiring the old row.
        metadata = {
            "file_size": int(row["file_size"]),
            "has_legacy_extra_data": (
                row["relative_path"] is not None or
                row["extracted_text"] is not None
            ),
            **{field: row[field] for field in (
                "file_name", "saved_name", "content_type",
                "detected_type", "detected_service", "asset_type",
            )},
            **{field: _metadata_b64(row[field]) for field in (
                "file_name_ciphertext", "saved_name_ciphertext",
                "content_type_ciphertext", "detected_type_ciphertext",
                "detected_service_ciphertext", "asset_type_ciphertext",
            )},
        }
    plain_fields = (
        ("item_type", "service") if kind == "item" else
        ("file_name", "saved_name", "content_type", "detected_type",
         "detected_service", "asset_type")
    )
    if any(len(metadata[field]) > 256 for field in plain_fields
           if isinstance(metadata[field], str)):
        # Source labels are structural metadata, not file content. Keep the
        # export response bounded even for malformed old rows.
        raise HTTPException(status_code=413, detail="legacy_metadata_too_large")
    return {
        id_key: record_id,
        "offset": payload.offset,
        "ciphertext_chunk": chunk,
        "total_chars": total,
        "next_offset": next_offset,
        "done": next_offset >= total,
        "source_snapshot": legacy_source_snapshot(
            kind, row, vault_id=vault_id, record_id=record_id,
        ),
        **({"delete_snapshot": item_delete_snapshot(
            row, vault_id=vault_id, record_id=record_id,
        )} if kind == "item" else {}),
        "source_metadata": metadata,
    }


def _read_file_extra(cur, vault_id: str, payload: LegacyExportPageRequest) -> dict:
    if payload.file_id is None:
        raise HTTPException(status_code=400, detail="file_id_required")
    max_text_bytes = (MAX_FILE_EXTRA_V3_BYTES
                      if payload.mode == "read_file_extra_v3"
                      else MAX_FILE_EXTRA_BYTES)
    cur.execute(
        "SELECT LENGTH(encrypted_file_data) AS legacy_chars, "
        "OCTET_LENGTH(relative_path) AS path_bytes, "
        "OCTET_LENGTH(extracted_text) AS text_bytes "
        "FROM uploaded_files WHERE vault_id=%s AND id=%s "
        "AND storage_mode='inline' AND upload_status='complete' "
        "AND encrypted_file_data IS NOT NULL",
        (vault_id, payload.file_id),
    )
    lengths = cur.fetchone()
    if lengths is None:
        raise HTTPException(status_code=404, detail="legacy_record_not_found")
    if int(lengths["legacy_chars"]) > MAX_SOURCE_CIPHERTEXT_CHARS:
        raise HTTPException(status_code=413, detail="legacy_streaming_required")
    if (payload.mode == "read_file_extra_v3" and
            int(lengths["text_bytes"] or 0) <= MAX_FILE_EXTRA_BYTES):
        raise HTTPException(status_code=413, detail="legacy_file_extra_v3_size_required")
    if (int(lengths["path_bytes"] or 0) > 4096 or
            int(lengths["text_bytes"] or 0) > max_text_bytes):
        raise HTTPException(status_code=413, detail="legacy_file_extra_streaming_required")
    cur.execute(
        f"SELECT {', '.join(FILE_SOURCE_FIELDS)} FROM uploaded_files "
        "WHERE vault_id=%s AND id=%s AND storage_mode='inline' "
        "AND upload_status='complete' AND encrypted_file_data IS NOT NULL",
        (vault_id, payload.file_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="legacy_record_not_found")
    # A concurrent mutation can occur between the size check and full read.
    path = row["relative_path"]
    text = row["extracted_text"]
    path_bytes = len(path.encode("utf-8")) if path is not None else 0
    text_bytes = len(text.encode("utf-8")) if text is not None else 0
    if (payload.mode == "read_file_extra_v3" and
            text_bytes <= MAX_FILE_EXTRA_BYTES):
        raise HTTPException(status_code=413, detail="legacy_file_extra_v3_size_required")
    if path_bytes > 4096 or text_bytes > max_text_bytes:
        raise HTTPException(status_code=413, detail="legacy_file_extra_streaming_required")
    data = {
        "file_id": payload.file_id,
        "source_snapshot": legacy_source_snapshot(
            "file", row, vault_id=vault_id, record_id=payload.file_id,
        ),
        "legacy_extra": {
            "relative_path": path,
            "extracted_text": text,
        },
    }
    if payload.mode == "read_file_extra_v3":
        data["legacy_extra_version"] = 3
    return data


@router.post("/vault/legacy-ciphertext/export/page")
def legacy_export_page(
    payload: LegacyExportPageRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
    http_response: Response = None,
) -> dict:
    _require_enabled(principal)
    if payload.mode == "read_file_extra":
        _require_file_extra_stage_enabled()
    elif payload.mode == "read_file_extra_v3":
        _require_file_extra_v3_enabled()
    if not _grant_belongs_to_session(payload.export_token, principal):
        raise HTTPException(status_code=401, detail="invalid_export_grant")

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT server_state FROM vault_zk_login_slots
             WHERE slot_id = %s AND vault_id = %s AND expires_at > NOW()
             FOR UPDATE
            """,
            (payload.export_token, principal["vault_id"]),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="invalid_export_grant")
        try:
            state = json.loads(bytes(row["server_state"]).decode("ascii"))
            sequence = int(state["sequence"])
            pages_left = int(state["pages_left"])
            bytes_left = int(state["bytes_left"])
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise HTTPException(status_code=401, detail="invalid_export_grant")
        if not (
            0 <= sequence <= GRANT_MAX_PAGES
            and 0 <= pages_left <= GRANT_MAX_PAGES
            and 0 <= bytes_left <= GRANT_MAX_BYTES
        ):
            raise HTTPException(status_code=401, detail="invalid_export_grant")
        if payload.sequence != sequence or pages_left <= 0 or bytes_left <= 0:
            raise HTTPException(status_code=409, detail="export_page_replayed_or_exhausted")

        if payload.mode == "list_items":
            data = _list_items(cur, principal["vault_id"], payload)
        elif payload.mode == "list_files":
            data = _list_files(cur, principal["vault_id"], payload)
        elif payload.mode in ("read_file_extra", "read_file_extra_v3"):
            data = _read_file_extra(cur, principal["vault_id"], payload)
        else:
            data = _read_chunk(cur, principal["vault_id"], payload)
        response = {
            "mode": payload.mode,
            **data,
            "next_sequence": sequence + 1,
            "pages_remaining": pages_left - 1,
            "bytes_remaining": 0,
        }
        # Account conservatively for the dynamic remaining-budget field and
        # JSON escaping. It may charge slightly more than transmitted bytes,
        # never less. Every response remains under a strict per-page cap.
        charge = len(json.dumps(response, ensure_ascii=True).encode()) + 256
        if charge > PAGE_MAX_BYTES or charge > bytes_left:
            raise HTTPException(status_code=413, detail="export_page_limit")
        state = {
            "sequence": sequence + 1,
            "pages_left": pages_left - 1,
            "bytes_left": bytes_left - charge,
        }
        cur.execute(
            """
            UPDATE vault_zk_login_slots SET server_state = %s
             WHERE slot_id = %s AND vault_id = %s
            """,
            (json.dumps(state, separators=(",", ":")).encode("ascii"),
             payload.export_token, principal["vault_id"]),
        )
        conn.commit()
        response["bytes_remaining"] = state["bytes_left"]
        if http_response is not None:
            http_response.headers["Cache-Control"] = "no-store"
        return response
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
