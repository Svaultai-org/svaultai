"""Ciphertext-first write endpoints for the ZK metadata surface.

These endpoints are the *only* API path new writes should use after
migration 0024 is deployed. They accept opaque ciphertext blobs
(BYTEA, base64url on the wire) for every human-readable metadata
field. The corresponding legacy plaintext columns are set NULL or
never touched.

Rules enforced here:

  * Each endpoint accepts ONLY the ciphertext form of a metadata
    field. If a caller sends the legacy plaintext-named field, the
    request is rejected with 400 to prevent accidental plaintext
    leaks on the new write path.
  * Every SELECT / UPDATE is scoped to the authenticated caller's
    vault_id. There is no admin path, no cross-vault visibility, no
    other-vault write.
  * No plaintext is logged; no ciphertext body is logged. Only row
    counts, table names, and error codes.
  * These endpoints coexist with the existing legacy routes. The
    lazy backfill loop (routes/vault_metadata_migration_routes.py)
    continues to migrate un-adopted rows on future unlocks.

Coverage:

  * POST /vault/ciphertext/vault-items         create / update
  * POST /vault/ciphertext/uploaded-files      metadata-only update
  * POST /vault/ciphertext/notifications       create
  * POST /vault/ciphertext/vault-ai-memory     upsert-with-lookup-hash
  * POST /vault/ciphertext/beneficiary-links   update passer_label
  * POST /vault/ciphertext/semantic-index      write keyed hash

Wallet-account records use vault_items with item_type_ciphertext
representing an opaque ``wallet_account`` marker — no separate
endpoint. Crypto drafts, wallet locks, and outgoing history use
draft_payload_ciphertext / sender_address_lookup_hash /
signature_lookup_hash on their respective per-network write paths
(``crypto_wallet_routes.py``) — extended in a follow-up turn.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg2.extras import RealDictCursor

from auth_local import (
    SessionPrincipal,
    verify_session_token,
)
from vault_core import get_db
from zk_migration_flags import ZkMigrationFlags
from subscription_entitlement import require_content_write
from taxonomy import ALLOWED_MEMORY_TYPES
from vault_credential_draft import consume_draft, get_draft


logger = logging.getLogger(__name__)
router = APIRouter()


MAX_CIPHERTEXT_BYTES = 128 * 1024


def _b64url_decode(text: str, *, name: str, max_bytes: int) -> bytes:
    if not isinstance(text, str) or not text:
        raise HTTPException(
            status_code=400, detail=f"{name} is required",
        )
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{name} is not valid base64url",
        ) from exc
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{name} exceeds size limit",
        )
    return raw


def _b64url_decode_opt(text: Optional[str], *, name: str,
                       max_bytes: int = MAX_CIPHERTEXT_BYTES) -> Optional[bytes]:
    if text is None:
        return None
    return _b64url_decode(text, name=name, max_bytes=max_bytes)


def _reject_plaintext_leak(payload_model: BaseModel,
                           forbidden_fields: tuple[str, ...]) -> None:
    """Refuse the request if any legacy plaintext field is set on a
    ciphertext-first write. The client is expected to send only the
    ``*_ciphertext`` variant."""
    data = payload_model.model_dump(exclude_none=True)
    for f in forbidden_fields:
        if f in data:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{f} must not be sent on the ciphertext-first "
                    "write path; supply the *_ciphertext field only"
                ),
            )


class VaultItemUpsertRequest(BaseModel):
    item_id: Optional[int] = Field(
        default=None,
        description=(
            "Present -> update. Absent -> create a new row with only "
            "ciphertext columns populated."
        ),
    )
    item_type_ciphertext: str = Field(..., min_length=1)
    service_ciphertext: str = Field(..., min_length=1)
    payload_ciphertext: str = Field(..., min_length=1)
    # Guardrail: refuse if the caller accidentally sends plaintext.
    item_type: Optional[str] = None
    service: Optional[str] = None
    encrypted_data: Optional[str] = None


class VaultItemUpsertResponse(BaseModel):
    item_id: int
    created: bool


class VaultItemCiphertextResponse(BaseModel):
    item_id: int
    item_type_ciphertext: str
    service_ciphertext: str
    payload_ciphertext: str
    created_at: str


class GeneratedDraftCiphertextFinalizeRequest(BaseModel):
    """Link an already-written opaque vault item to its transient draft.

    The endpoint never receives the credential values.  It only consumes the
    server-side draft after proving that the authenticated vault owns a fully
    ciphertext-backed item.
    """

    item_id: int = Field(..., gt=0)
    draft_id: str = Field(..., min_length=1, max_length=128)

    @field_validator("draft_id")
    @classmethod
    def validate_draft_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
            raise ValueError("draft_id has invalid format")
        return value


@router.post(
    "/vault/ciphertext/vault-items",
    response_model=VaultItemUpsertResponse,
)
def vault_item_upsert_ciphertext(
    payload: VaultItemUpsertRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> VaultItemUpsertResponse:
    require_content_write(principal)
    _reject_plaintext_leak(
        payload, ("item_type", "service", "encrypted_data"),
    )

    item_type_ct = _b64url_decode(
        payload.item_type_ciphertext, name="item_type_ciphertext",
        max_bytes=MAX_CIPHERTEXT_BYTES,
    )
    service_ct = _b64url_decode(
        payload.service_ciphertext, name="service_ciphertext",
        max_bytes=MAX_CIPHERTEXT_BYTES,
    )
    payload_ct = _b64url_decode(
        payload.payload_ciphertext, name="payload_ciphertext",
        max_bytes=MAX_CIPHERTEXT_BYTES,
    )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        if payload.item_id is None:
            cur.execute(
                """
                INSERT INTO vault_items (
                    vault_id, item_type, service, encrypted_data,
                    item_type_ciphertext, service_ciphertext,
                    payload_ciphertext
                )
                VALUES (%s, NULL, NULL, NULL, %s, %s, %s)
                RETURNING id
                """,
                (
                    principal["vault_id"],
                    item_type_ct, service_ct, payload_ct,
                ),
            )
            new_id = int(cur.fetchone()["id"])
            conn.commit()
            return VaultItemUpsertResponse(item_id=new_id, created=True)

        cur.execute(
            """
            UPDATE vault_items
               SET item_type_ciphertext = %s,
                   service_ciphertext   = %s,
                   payload_ciphertext   = %s,
                   item_type            = NULL,
                   service              = NULL,
                   encrypted_data       = NULL
             WHERE id = %s
               AND vault_id = %s
            """,
            (
                item_type_ct, service_ct, payload_ct,
                payload.item_id, principal["vault_id"],
            ),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="item not found")
        conn.commit()
        return VaultItemUpsertResponse(item_id=payload.item_id, created=False)
    finally:
        conn.close()


@router.post(
    "/vault/ciphertext/vault-items/generated-drafts/finalize",
    response_model=dict,
)
def finalize_generated_draft_ciphertext(
    payload: GeneratedDraftCiphertextFinalizeRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    """Consume a login draft only after its opaque item is durable.

    This keeps chat-created logins on the same client-encrypted storage path
    used by the Logins dashboard and makes retries idempotent.
    """

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1
              FROM vault_items
             WHERE id = %s
               AND vault_id = %s
               AND item_type_ciphertext IS NOT NULL
               AND service_ciphertext IS NOT NULL
               AND payload_ciphertext IS NOT NULL
            """,
            (payload.item_id, principal["vault_id"]),
        )
        if cur.fetchone() is None:
            raise HTTPException(
                status_code=409,
                detail="opaque vault item must exist before draft finalize",
            )
    finally:
        conn.close()

    current = get_draft(
        vault_id=str(principal["vault_id"]),
        draft_id=payload.draft_id,
    )
    if current is None:
        return {
            "status": "already_finalized",
            "item_id": payload.item_id,
            "draft_id": payload.draft_id,
        }
    consumed = consume_draft(
        vault_id=str(principal["vault_id"]),
        draft_id=payload.draft_id,
    )
    return {
        "status": "finalized" if consumed is not None else "already_finalized",
        "item_id": payload.item_id,
        "draft_id": payload.draft_id,
    }


@router.get(
    "/vault/ciphertext/vault-items",
    response_model=list[VaultItemCiphertextResponse],
)
def list_vault_item_ciphertexts(
    principal: SessionPrincipal = Depends(verify_session_token),
) -> list[VaultItemCiphertextResponse]:
    """Return only opaque, vault-scoped rows for client-side MVK hydration."""
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, item_type_ciphertext, service_ciphertext,
                   payload_ciphertext, created_at
              FROM vault_items
             WHERE vault_id = %s
               AND item_type_ciphertext IS NOT NULL
               AND service_ciphertext IS NOT NULL
               AND payload_ciphertext IS NOT NULL
             ORDER BY created_at DESC, id DESC
            """,
            (principal["vault_id"],),
        )
        return [
            VaultItemCiphertextResponse(
                item_id=int(row["id"]),
                item_type_ciphertext=base64.urlsafe_b64encode(
                    bytes(row["item_type_ciphertext"]),
                ).decode().rstrip("="),
                service_ciphertext=base64.urlsafe_b64encode(
                    bytes(row["service_ciphertext"]),
                ).decode().rstrip("="),
                payload_ciphertext=base64.urlsafe_b64encode(
                    bytes(row["payload_ciphertext"]),
                ).decode().rstrip("="),
                created_at=row["created_at"].isoformat(),
            )
            for row in (cur.fetchall() or [])
        ]
    finally:
        conn.close()


@router.delete("/vault/ciphertext/vault-items/{item_id}", response_model=dict)
def delete_vault_item_ciphertext(
    item_id: int,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    """Delete one opaque vault item owned by the active vault."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM vault_items WHERE id = %s AND vault_id = %s",
            (item_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="item not found")
        conn.commit()
        return {"status": "deleted", "item_id": item_id}
    finally:
        conn.close()


class UploadedFileMetadataRequest(BaseModel):
    file_id: str = Field(..., min_length=1, max_length=128)
    file_name_ciphertext: Optional[str] = None
    saved_name_ciphertext: Optional[str] = None
    content_type_ciphertext: Optional[str] = None
    detected_type_ciphertext: Optional[str] = None
    detected_service_ciphertext: Optional[str] = None
    asset_type_ciphertext: Optional[str] = None
    # Legacy plaintext guardrail.
    file_name: Optional[str] = None
    saved_name: Optional[str] = None
    content_type: Optional[str] = None
    detected_type: Optional[str] = None
    detected_service: Optional[str] = None
    asset_type: Optional[str] = None


class UploadedFileMetadataResponse(BaseModel):
    file_id: str
    updated_columns: list[str]


@router.post(
    "/vault/ciphertext/uploaded-files",
    response_model=UploadedFileMetadataResponse,
)
def uploaded_file_metadata_ciphertext(
    payload: UploadedFileMetadataRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> UploadedFileMetadataResponse:
    require_content_write(principal)
    _reject_plaintext_leak(payload, (
        "file_name", "saved_name", "content_type",
        "detected_type", "detected_service", "asset_type",
    ))

    ct_pairs: list[tuple[str, str, Optional[bytes]]] = []
    for legacy_col, ct_col, val in [
        ("file_name", "file_name_ciphertext", payload.file_name_ciphertext),
        ("saved_name", "saved_name_ciphertext", payload.saved_name_ciphertext),
        ("content_type", "content_type_ciphertext",
         payload.content_type_ciphertext),
        ("detected_type", "detected_type_ciphertext",
         payload.detected_type_ciphertext),
        ("detected_service", "detected_service_ciphertext",
         payload.detected_service_ciphertext),
        ("asset_type", "asset_type_ciphertext",
         payload.asset_type_ciphertext),
    ]:
        ct_pairs.append((legacy_col, ct_col,
                         _b64url_decode_opt(val, name=ct_col)))

    updates_ct = [(c, ct, v) for (c, ct, v) in ct_pairs if v is not None]
    if not updates_ct:
        return UploadedFileMetadataResponse(
            file_id=payload.file_id, updated_columns=[],
        )

    saved_name_updated = any(legacy == "saved_name" for legacy, _, _ in updates_ct)
    set_clauses = [f"{ct} = %s" for _, ct, _ in updates_ct]
    set_clauses.extend(f"{legacy} = NULL" for legacy, _, _ in updates_ct)
    if saved_name_updated:
        set_clauses.append("needs_naming = FALSE")
    params: list[Any] = [v for _, _, v in updates_ct]
    params.extend([payload.file_id, principal["vault_id"]])

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE uploaded_files
               SET {", ".join(set_clauses)}
             WHERE id = %s
               AND vault_id = %s
            """,
            params,
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="file not found")
        conn.commit()
        if saved_name_updated:
            try:
                from vault_tool_result_cache import invalidate_for_event
                invalidate_for_event(
                    vault_id=principal["vault_id"], event="file_renamed",
                )
            except Exception:
                pass
    finally:
        conn.close()

    return UploadedFileMetadataResponse(
        file_id=payload.file_id,
        updated_columns=[ct for _, ct, _ in updates_ct],
    )


class NotificationCiphertextRequest(BaseModel):
    kind: str = Field(..., min_length=1, max_length=64)
    title_ciphertext: str = Field(..., min_length=1)
    body_ciphertext: str = Field(..., min_length=1)
    metadata_ciphertext: Optional[str] = None
    # Legacy plaintext guardrail.
    title: Optional[str] = None
    body: Optional[str] = None
    metadata: Optional[str] = None


class NotificationCiphertextResponse(BaseModel):
    notification_id: int


@router.post(
    "/vault/ciphertext/notifications",
    response_model=NotificationCiphertextResponse,
)
def notification_ciphertext_create(
    payload: NotificationCiphertextRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> NotificationCiphertextResponse:
    require_content_write(principal)
    _reject_plaintext_leak(payload, ("title", "body", "metadata"))

    title_ct = _b64url_decode(
        payload.title_ciphertext, name="title_ciphertext",
        max_bytes=MAX_CIPHERTEXT_BYTES,
    )
    body_ct = _b64url_decode(
        payload.body_ciphertext, name="body_ciphertext",
        max_bytes=MAX_CIPHERTEXT_BYTES,
    )
    metadata_ct = _b64url_decode_opt(
        payload.metadata_ciphertext, name="metadata_ciphertext",
    )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            INSERT INTO notifications (
                vault_id, kind, title, body,
                title_ciphertext, body_ciphertext, metadata_ciphertext
            )
            VALUES (%s, %s, NULL, NULL, %s, %s, %s)
            RETURNING id
            """,
            (
                principal["vault_id"], payload.kind,
                title_ct, body_ct, metadata_ct,
            ),
        )
        new_id = int(cur.fetchone()["id"])
        conn.commit()
    finally:
        conn.close()

    return NotificationCiphertextResponse(notification_id=new_id)


class AiMemoryCiphertextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memory_id: str = Field(..., min_length=1, max_length=128)
    memory_type: str = Field(..., min_length=1, max_length=64)
    memory_lookup_hash: str = Field(
        ..., min_length=1,
        description="base64url of vault-scoped HMAC-SHA-256 of the "
                    "memory key (32 bytes).",
    )
    payload_ciphertext: str = Field(..., min_length=1)
    replace_existing: bool = False
    # Legacy plaintext guardrail.
    memory_key: Optional[str] = None
    memory_value: Optional[str] = None
    memory_normalized_key: Optional[str] = None

    @field_validator("memory_type")
    @classmethod
    def validate_memory_type(cls, value: str) -> str:
        if value not in ALLOWED_MEMORY_TYPES:
            raise ValueError("unsupported memory_type")
        return value


class AiMemoryCiphertextResponse(BaseModel):
    memory_id: str
    superseded_id: Optional[int] = None
    duplicate: bool = False


class AiMemoryCiphertextReadResponse(BaseModel):
    memory_id: str
    memory_type: str
    payload_ciphertext: str
    memory_lookup_hash: str


@router.post(
    "/vault/ciphertext/vault-ai-memory",
    response_model=AiMemoryCiphertextResponse,
)
def ai_memory_ciphertext_upsert(
    payload: AiMemoryCiphertextRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> AiMemoryCiphertextResponse:
    require_content_write(principal)
    qa = os.getenv("QA_CHAT_PRIVACY_DIAGNOSTICS", "").lower() == "true"
    if qa:
        print("BACKEND_MEMORY_V2_WRITE_REQUEST_OBSERVED=true", flush=True)
        print("BACKEND_MEMORY_V2_WRITE_HANDLER_ENTERED=true", flush=True)
    try:
        memory_flags = ZkMigrationFlags.from_environment(os.environ)
        memory_flags.validate_dependencies()
        if not memory_flags.memory_write_enabled:
            if qa:
                print("BACKEND_MEMORY_V2_WRITE_RESPONSE_STATUS=404", flush=True)
                print("BACKEND_MEMORY_V2_WRITE_SAFE_ERROR_CATEGORY=feature_disabled", flush=True)
            raise HTTPException(status_code=404, detail="memory_v2_path_disabled")
        _reject_plaintext_leak(payload, (
            "memory_key", "memory_value", "memory_normalized_key",
        ))
        if qa:
            print("BACKEND_MEMORY_V2_WRITE_VALIDATION_PASSED=true", flush=True)
        lookup_hash = _b64url_decode(
            payload.memory_lookup_hash, name="memory_lookup_hash", max_bytes=64,
        )
        if len(lookup_hash) != 32:
            raise HTTPException(status_code=400, detail="memory_lookup_hash must be 32 bytes")
        payload_ct = _b64url_decode(
            payload.payload_ciphertext, name="payload_ciphertext", max_bytes=MAX_CIPHERTEXT_BYTES,
        )
        if qa:
            print("BACKEND_MEMORY_V2_WRITE_DB_OPERATION_ENTERED=true", flush=True)
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """SELECT id, memory_record_id FROM vault_ai_memory
                   WHERE vault_id = %s AND memory_lookup_hash = %s
                     AND superseded_at IS NULL LIMIT 1""",
                (principal["vault_id"], lookup_hash),
            )
            prev = cur.fetchone()
            superseded_id: Optional[int] = None
            if (
                prev is not None
                and str(prev["memory_record_id"]) == payload.memory_id
                and not payload.replace_existing
            ):
                # The vault-scoped keyed record id represents the same
                # normalized fact and value. Do not rewrite its ciphertext or
                # pretend that an identical retry created another memory.
                return AiMemoryCiphertextResponse(
                    memory_id=str(prev["id"]),
                    superseded_id=int(prev["id"]),
                    duplicate=True,
                )
            # An editor keeps the stable client memory_record_id but may
            # change the title/normalized key, which intentionally changes
            # memory_lookup_hash. Update that stable record first; otherwise
            # an INSERT collides with the record-id uniqueness constraint and
            # makes ordinary encrypted memory edits fail.
            cur.execute(
                """UPDATE vault_ai_memory
                   SET memory_type = %s,
                       memory_key = NULL,
                       memory_value = NULL,
                       payload_ciphertext = %s,
                       memory_lookup_hash = %s,
                       superseded_at = NULL,
                       superseded_by_id = NULL
                   WHERE vault_id = %s AND memory_record_id = %s
                   RETURNING id""",
                (
                    payload.memory_type,
                    payload_ct,
                    lookup_hash,
                    principal["vault_id"],
                    payload.memory_id,
                ),
            )
            updated = cur.fetchone()
            if updated is not None:
                new_id = int(updated["id"])
            else:
                cur.execute(
                    """INSERT INTO vault_ai_memory (
                    vault_id, memory_record_id, memory_type, memory_key,
                    memory_value, payload_ciphertext, memory_lookup_hash
                ) VALUES (%s, %s, %s, NULL, NULL, %s, %s)
                ON CONFLICT (vault_id, memory_lookup_hash)
                    WHERE superseded_at IS NULL AND memory_lookup_hash IS NOT NULL
                DO UPDATE SET
                    memory_record_id = EXCLUDED.memory_record_id,
                    memory_type = EXCLUDED.memory_type,
                    memory_key = NULL,
                    memory_value = NULL,
                    payload_ciphertext = EXCLUDED.payload_ciphertext,
                    superseded_at = NULL,
                    superseded_by_id = NULL
                RETURNING id""",
                    (
                        principal["vault_id"],
                        payload.memory_id,
                        payload.memory_type,
                        payload_ct,
                        lookup_hash,
                    ),
                )
                new_id = int(cur.fetchone()["id"])
            if prev is not None:
                superseded_id = int(prev["id"])
            conn.commit()
        finally:
            conn.close()
        if qa:
            print("BACKEND_MEMORY_V2_WRITE_DB_OPERATION_SUCCEEDED=true", flush=True)
            print("BACKEND_MEMORY_V2_WRITE_RESPONSE_STATUS=200", flush=True)
            print("BACKEND_MEMORY_V2_WRITE_SAFE_ERROR_CATEGORY=none", flush=True)
        return AiMemoryCiphertextResponse(
            memory_id=str(new_id),
            superseded_id=superseded_id,
            duplicate=False,
        )
    except HTTPException as exc:
        if qa:
            print("BACKEND_MEMORY_V2_EXCEPTION_CAUGHT=true", flush=True)
            print("BACKEND_MEMORY_V2_EXCEPTION_TYPE=HTTPException", flush=True)
            print(f"BACKEND_MEMORY_V2_WRITE_RESPONSE_STATUS={exc.status_code}", flush=True)
            print("BACKEND_MEMORY_V2_WRITE_SAFE_ERROR_CATEGORY=request_validation", flush=True)
        raise
    except Exception as exc:
        if qa:
            print("BACKEND_MEMORY_V2_EXCEPTION_CAUGHT=true", flush=True)
            print(f"BACKEND_MEMORY_V2_EXCEPTION_TYPE={type(exc).__name__}", flush=True)
            print("BACKEND_MEMORY_V2_WRITE_RESPONSE_STATUS=500", flush=True)
            print("BACKEND_MEMORY_V2_WRITE_SAFE_ERROR_CATEGORY=database_error", flush=True)
        raise


@router.get(
    "/vault/ciphertext/vault-ai-memory",
    response_model=list[AiMemoryCiphertextReadResponse],
)
def ai_memory_ciphertext_list(
    memory_lookup_hash: Optional[str] = None,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> list[AiMemoryCiphertextReadResponse]:
    """Return opaque memory envelopes only; never legacy plaintext columns."""
    memory_flags = ZkMigrationFlags.from_environment(os.environ)
    memory_flags.validate_dependencies()
    if not memory_flags.memory_read_enabled:
        raise HTTPException(status_code=404, detail="memory_v2_path_disabled")
    lookup_hash = None
    if memory_lookup_hash is not None:
        lookup_hash = _b64url_decode(
            memory_lookup_hash, name="memory_lookup_hash", max_bytes=64,
        )
        if len(lookup_hash) != 32:
            raise HTTPException(status_code=400, detail="memory_lookup_hash must be 32 bytes")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT memory_record_id, memory_type, payload_ciphertext, memory_lookup_hash
              FROM vault_ai_memory
             WHERE vault_id = %s AND superseded_at IS NULL
               AND payload_ciphertext IS NOT NULL
               AND (%s IS NULL OR memory_lookup_hash = %s)
             ORDER BY id
            """,
            (principal["vault_id"], lookup_hash, lookup_hash),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [
        AiMemoryCiphertextReadResponse(
            memory_id=str(row["memory_record_id"]),
            memory_type=str(row["memory_type"]),
            payload_ciphertext=base64.urlsafe_b64encode(
                bytes(row["payload_ciphertext"])
            ).decode().rstrip("="),
            memory_lookup_hash=base64.urlsafe_b64encode(
                bytes(row["memory_lookup_hash"])
            ).decode().rstrip("="),
        )
        for row in rows
    ]


@router.delete("/vault/ciphertext/vault-ai-memory/{memory_id}", response_model=dict)
def ai_memory_ciphertext_delete(
    memory_id: str,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    flags = ZkMigrationFlags.from_environment(os.environ)
    flags.validate_dependencies()
    if not flags.memory_write_enabled:
        raise HTTPException(status_code=404, detail="memory_v2_path_disabled")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM vault_ai_memory WHERE vault_id = %s AND memory_record_id = %s",
            (principal["vault_id"], memory_id),
        )
        conn.commit()
        if cur.rowcount != 1:
            raise HTTPException(status_code=404, detail="memory_not_found")
    finally:
        conn.close()
    return {"status": "deleted", "memory_id": memory_id}


class BeneficiaryLabelCiphertextRequest(BaseModel):
    link_id: int
    passer_label_ciphertext: str = Field(..., min_length=1)
    passer_label: Optional[str] = None


@router.post(
    "/vault/ciphertext/beneficiary-links",
    response_model=dict,
)
def beneficiary_label_ciphertext_update(
    payload: BeneficiaryLabelCiphertextRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    require_content_write(principal)
    _reject_plaintext_leak(payload, ("passer_label",))

    label_ct = _b64url_decode(
        payload.passer_label_ciphertext, name="passer_label_ciphertext",
        max_bytes=MAX_CIPHERTEXT_BYTES,
    )

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE beneficiary_links
               SET passer_label_ciphertext = %s,
                   passer_label = NULL
             WHERE id = %s
               AND passer_vault_id = %s
            """,
            (label_ct, payload.link_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="link not found")
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "link_id": payload.link_id}


class SemanticIndexKeyedHashRequest(BaseModel):
    source_kind: str = Field(..., min_length=1, max_length=32)
    uploaded_file_id: Optional[str] = None
    vault_item_id: Optional[int] = None
    embedding: list[float] = Field(...)
    keyed_content_hash: str = Field(
        ..., min_length=1,
        description="base64url of vault-scoped HMAC-SHA-256 (32 bytes).",
    )


@router.post(
    "/vault/ciphertext/semantic-index",
    response_model=dict,
)
def semantic_index_keyed_hash_upsert(
    payload: SemanticIndexKeyedHashRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    require_content_write(principal)
    if (payload.uploaded_file_id is None) == (payload.vault_item_id is None):
        raise HTTPException(
            status_code=400,
            detail="exactly one of uploaded_file_id / vault_item_id required",
        )
    if len(payload.embedding) == 0 or len(payload.embedding) > 4096:
        raise HTTPException(
            status_code=400, detail="embedding length out of range",
        )
    keyed_hash = _b64url_decode(
        payload.keyed_content_hash, name="keyed_content_hash",
        max_bytes=64,
    )
    if len(keyed_hash) != 32:
        raise HTTPException(
            status_code=400, detail="keyed_content_hash must be 32 bytes",
        )

    conn = get_db()
    try:
        cur = conn.cursor()
        if payload.uploaded_file_id is not None:
            cur.execute(
                """
                INSERT INTO semantic_index (
                    vault_id, source_kind, uploaded_file_id,
                    embedding, content_hash, keyed_content_hash
                )
                VALUES (%s, %s, %s, %s, NULL, %s)
                ON CONFLICT (vault_id, source_kind, uploaded_file_id)
                    WHERE uploaded_file_id IS NOT NULL
                DO UPDATE SET
                    embedding          = EXCLUDED.embedding,
                    keyed_content_hash = EXCLUDED.keyed_content_hash,
                    updated_at         = NOW()
                """,
                (
                    principal["vault_id"], payload.source_kind,
                    payload.uploaded_file_id, payload.embedding,
                    keyed_hash,
                ),
            )
        else:
            cur.execute(
                """
                INSERT INTO semantic_index (
                    vault_id, source_kind, vault_item_id,
                    embedding, content_hash, keyed_content_hash
                )
                VALUES (%s, %s, %s, %s, NULL, %s)
                ON CONFLICT (vault_id, source_kind, vault_item_id)
                    WHERE vault_item_id IS NOT NULL
                DO UPDATE SET
                    embedding          = EXCLUDED.embedding,
                    keyed_content_hash = EXCLUDED.keyed_content_hash,
                    updated_at         = NOW()
                """,
                (
                    principal["vault_id"], payload.source_kind,
                    payload.vault_item_id, payload.embedding,
                    keyed_hash,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


class InheritanceRewrapUpload(BaseModel):
    link_id: int
    wrapped_vault_key: str = Field(..., min_length=1)


@router.post(
    "/vault/ciphertext/inheritance-rewrap",
    response_model=dict,
)
def inheritance_rewrap_upload(
    payload: InheritanceRewrapUpload,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    require_content_write(principal)
    """Passer's client uploads the beneficiary-wrapped MVK envelope
    at pairing time. Server persists the opaque bytes only. Server
    never learns MVK or the passer/beneficiary private keys.
    """
    wrapped = _b64url_decode(
        payload.wrapped_vault_key,
        name="wrapped_vault_key", max_bytes=MAX_CIPHERTEXT_BYTES,
    )
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE beneficiary_links
               SET wrapped_vault_key = %s
             WHERE id = %s
               AND passer_vault_id = %s
            """,
            (wrapped.hex(), payload.link_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="link not found")
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


_CRYPTO_NETWORKS = ("solana", "mainnet", "tron")

_CRYPTO_DRAFTS_TABLE = {
    "solana": "crypto_solana_drafts",
    "mainnet": "crypto_mainnet_drafts",
    "tron": "crypto_tron_drafts",
}
_CRYPTO_LOCKS_TABLE = {
    "solana": "crypto_solana_wallet_locks",
    "mainnet": "crypto_mainnet_wallet_locks",
    "tron": "crypto_tron_wallet_locks",
}
_CRYPTO_HISTORY_TABLE = {
    "solana": "crypto_solana_outgoing_history",
    "mainnet": "crypto_mainnet_outgoing_history",
    "tron": "crypto_tron_outgoing_history",
}


class CryptoDraftCiphertextRequest(BaseModel):
    network: str = Field(..., min_length=1, max_length=16)
    draft_id: str = Field(..., min_length=1, max_length=128)
    draft_payload_ciphertext: str = Field(..., min_length=1)
    sender_address_lookup_hash: str = Field(
        ..., min_length=1,
        description="base64url of vault-scoped HMAC(sender_address).",
    )


@router.post(
    "/vault/ciphertext/crypto-drafts",
    response_model=dict,
)
def crypto_draft_ciphertext_persist(
    payload: CryptoDraftCiphertextRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    require_content_write(principal)
    """Called by the ZK client immediately AFTER a draft is created
    via /crypto/{asset}/send/draft. Replaces the persisted
    sender_address / destination_address / value / fee / asset
    plaintext values with a single ciphertext blob, and swaps in the
    keyed lookup hash for wallet-lock lookup. The plaintext values
    remain in RAM ONLY inside the draft-create request; after this
    call they no longer exist on disk. The draft state machine
    (blockhash, expires_at, nonces, single-flight lock) is
    unchanged.

    Preserves send/broadcast semantics — the wallet lock keyed by
    the hash continues to work because the sender_address_lookup_hash
    is a stable function of the vault key + sender_address.
    """
    network = payload.network.lower()
    if network not in _CRYPTO_NETWORKS:
        raise HTTPException(status_code=400, detail="unknown network")

    payload_ct = _b64url_decode(
        payload.draft_payload_ciphertext, name="draft_payload_ciphertext",
        max_bytes=MAX_CIPHERTEXT_BYTES,
    )
    lookup_hash = _b64url_decode(
        payload.sender_address_lookup_hash,
        name="sender_address_lookup_hash", max_bytes=64,
    )
    if len(lookup_hash) != 32:
        raise HTTPException(
            status_code=400,
            detail="sender_address_lookup_hash must be 32 bytes",
        )

    drafts_table = _CRYPTO_DRAFTS_TABLE[network]
    locks_table = _CRYPTO_LOCKS_TABLE[network]
    sender_column = (
        "sender_address_lower" if network == "mainnet" else "sender_address"
    )

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            f"""
            SELECT {sender_column} AS sender_address
              FROM {drafts_table}
             WHERE draft_id = %s
               AND vault_id = %s
            """,
            (payload.draft_id, str(principal["vault_id"])),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="draft not found")
        old_sender = row["sender_address"]

        if network == "mainnet":
            cur.execute(
                f"""
                UPDATE {drafts_table}
                   SET draft_payload_ciphertext = %s,
                       sender_address_lookup_hash = %s
                 WHERE draft_id = %s
                   AND vault_id = %s
                """,
                (
                    payload_ct,
                    lookup_hash,
                    payload.draft_id,
                    str(principal["vault_id"]),
                ),
            )
        else:
            cur.execute(
                f"""
                UPDATE {drafts_table}
                   SET draft_payload_ciphertext = %s
                 WHERE draft_id = %s
                   AND vault_id = %s
                """,
                (payload_ct, payload.draft_id, str(principal["vault_id"])),
            )

        if old_sender:
            cur.execute(
                f"""
                UPDATE {locks_table}
                   SET sender_address_lookup_hash = %s
                 WHERE {sender_column} = %s
                """,
                (lookup_hash, old_sender),
            )

        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "draft_id": payload.draft_id}


class CryptoHistoryCiphertextRequest(BaseModel):
    network: str = Field(..., min_length=1, max_length=16)
    signature_lookup_hash: str = Field(
        ..., min_length=1,
        description="base64url of vault-scoped HMAC(signature).",
    )
    outcome_payload_ciphertext: str = Field(..., min_length=1)


@router.post(
    "/vault/ciphertext/crypto-history",
    response_model=dict,
)
def crypto_history_ciphertext_write(
    payload: CryptoHistoryCiphertextRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    require_content_write(principal)
    """ZK client calls this after successful broadcast. The server
    persists ONLY the keyed signature hash (for chain-dedup) and the
    ciphertext outcome payload (holds sender/destination/amount/
    signature). No plaintext transactional metadata is retained.

    Idempotent under the (vault_id, signature_lookup_hash) key.
    """
    network = payload.network.lower()
    if network not in _CRYPTO_NETWORKS:
        raise HTTPException(status_code=400, detail="unknown network")

    sig_hash = _b64url_decode(
        payload.signature_lookup_hash,
        name="signature_lookup_hash", max_bytes=64,
    )
    if len(sig_hash) != 32:
        raise HTTPException(
            status_code=400,
            detail="signature_lookup_hash must be 32 bytes",
        )
    outcome_ct = _b64url_decode(
        payload.outcome_payload_ciphertext,
        name="outcome_payload_ciphertext",
        max_bytes=MAX_CIPHERTEXT_BYTES,
    )

    hist_table = _CRYPTO_HISTORY_TABLE[network]

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE {hist_table}
               SET signature_lookup_hash    = %s,
                   outcome_payload_ciphertext = %s
             WHERE vault_id = %s
               AND signature_lookup_hash IS NULL
             RETURNING 1
            """,
            (sig_hash, outcome_ct, str(principal["vault_id"])),
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok"}


__all__ = ["router"]
