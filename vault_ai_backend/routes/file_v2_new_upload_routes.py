"""Publish and delete fully encrypted, client-MVK V2 files.

The existing manifest/chunk routes stage ciphertext. This module never sees a
filename, PIN, MVK, file key or plaintext content. New files become visible and
count against quota only after the client confirms its own GET/decrypt readback
and this route verifies a complete, bounded ciphertext set.
"""

from __future__ import annotations

import os
import base64
import binascii
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from routes.file_v2_routes import (
    _enabled,
    MAX_FILE_BYTES as STAGING_MAX_FILE_BYTES,
    MAX_CHUNK_BYTES as STAGING_MAX_CHUNK_BYTES,
    MAX_CHUNKS as STAGING_MAX_CHUNKS,
    MAX_MANIFEST_CIPHERTEXT_BYTES as STAGING_MAX_MANIFEST_BYTES,
    GCM_FRAMING_BYTES as STAGING_GCM_OVERHEAD,
)
from subscription_entitlement import require_content_write
from vault_core import MAX_VAULT_BYTES, get_db, is_vault_zk_adopted
from file_private_conflict_index import inspect_and_reserve_new_file
from routes.auth_zk_routes import (
    consume_recent_zk_proof_on_cursor,
)
from routes import inheritance_v2_file_export_routes as inheritance_files


router = APIRouter()
MAX_NEW_FILE_BYTES = STAGING_MAX_FILE_BYTES  # Also FileV2Reader's bound.
MAX_CHUNK_BYTES = STAGING_MAX_CHUNK_BYTES
MAX_CHUNKS = STAGING_MAX_CHUNKS
MAX_MANIFEST_CIPHERTEXT = STAGING_MAX_MANIFEST_BYTES
AES_GCM_FRAME_OVERHEAD = STAGING_GCM_OVERHEAD


class PublishNewFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    inheritance_link_id: int | None = Field(default=None, ge=1)
    inheritance_source_file_id: str | None = Field(
        default=None, min_length=1, max_length=128,
    )
    inheritance_source_revision: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$",
    )
    zk_proof_token: str | None = Field(default=None, min_length=1, max_length=128)
    # MVK-keyed tags bind the whole-file digest and effective name(s), scoped
    # to the encrypted folder path. Optional fields preserve the default-off
    # gate's 409 response for clients that do not yet supply them.
    content_token: str | None = Field(default=None, max_length=64)
    name_tokens: list[str] | None = Field(default=None, max_length=2)
    duplicate_action: str = Field(default="prompt", max_length=16)


class DeleteNewFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    zk_proof_token: str = Field(min_length=1, max_length=128)


def _new_upload_enabled() -> None:
    _enabled(True)
    if os.getenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", "false").strip().lower() != "true":
        raise HTTPException(404, detail="new_file_v2_disabled")


def _file_id(value: str) -> str:
    if re.fullmatch(r"v2-[A-Za-z0-9_-]{27}", value):
        encoded = value[3:]
        try:
            raw = base64.urlsafe_b64decode(encoded + "=")
            if (len(raw) == 20 and
                    base64.urlsafe_b64encode(raw).decode().rstrip("=") == encoded):
                return value
        except (ValueError, binascii.Error):
            pass
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, detail="new_file_id_invalid") from None
    if str(parsed) != value.lower():
        raise HTTPException(400, detail="new_file_id_invalid")
    return value


def _blind_token(value: str | None) -> bytes:
    if value is None or re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is None:
        raise HTTPException(400, detail="private_file_conflict_token_invalid")
    try:
        token = base64.urlsafe_b64decode(value + "=")
    except (ValueError, binascii.Error):
        raise HTTPException(400, detail="private_file_conflict_token_invalid") from None
    if (len(token) != 32 or
            base64.urlsafe_b64encode(token).decode("ascii").rstrip("=") != value):
        raise HTTPException(400, detail="private_file_conflict_token_invalid")
    return token


def _publish_conflict_tags(payload: PublishNewFile) -> tuple[bytes, tuple[bytes, ...]]:
    if payload.duplicate_action not in ("prompt", "skip", "keep_both"):
        raise HTTPException(400, detail="private_file_duplicate_action_invalid")
    if payload.name_tokens is None or not 1 <= len(payload.name_tokens) <= 2:
        raise HTTPException(400, detail="private_file_conflict_token_invalid")
    content = _blind_token(payload.content_token)
    names = tuple(_blind_token(token) for token in payload.name_tokens)
    if len(set(names)) != len(names):
        raise HTTPException(400, detail="private_file_conflict_token_invalid")
    return content, names


def _validate_framing(record: dict, chunks: list) -> None:
    total = int(record["total_bytes"])
    size = int(record["chunk_size"])
    count = int(record["chunk_count"])
    ciphertext = bytes(record["manifest_ciphertext"])
    if (total < 0 or total > MAX_NEW_FILE_BYTES or size <= 0 or
            size > MAX_CHUNK_BYTES or count < 0 or count > MAX_CHUNKS or
            count != (total + size - 1) // size or
            len(ciphertext) < AES_GCM_FRAME_OVERHEAD or
            len(ciphertext) > MAX_MANIFEST_CIPHERTEXT):
        raise HTTPException(409, detail="file_v2_invalid_framing")
    if len(chunks) != count:
        raise HTTPException(409, detail="file_v2_chunks_incomplete")
    for index, row in enumerate(chunks):
        if int(row["chunk_index"]) != index:
            raise HTTPException(409, detail="file_v2_chunks_incomplete")
        plain_size = min(size, total - index * size)
        if int(row["ciphertext_bytes"]) != plain_size + AES_GCM_FRAME_OVERHEAD:
            raise HTTPException(409, detail="file_v2_invalid_chunk_size")


def _account_quota(cur, account_id: str | None, vault_used: int) -> tuple[int, int]:
    if account_id is None:
        return int(MAX_VAULT_BYTES), vault_used
    from billing import get_entitlement

    # Serialize this new-file route per account, then check both the billing
    # counter and the authoritative vault rows. Existing upload paths may have
    # different lock orders; this cannot replace their own quota gates.
    cur.execute("SELECT account_id FROM accounts WHERE account_id=%s FOR UPDATE",
                (account_id,))
    if cur.fetchone() is None:
        raise HTTPException(503, detail="account_quota_unavailable")
    entitlement = get_entitlement(account_id)
    cur.execute("SELECT COALESCE(SUM(total_bytes), 0) AS used "
                "FROM vaults WHERE account_id=%s", (account_id,))
    aggregate = cur.fetchone()
    aggregate_used = int(aggregate["used"] if aggregate else 0)
    used = max(int(entitlement.used_bytes), aggregate_used, vault_used)
    return int(entitlement.effective_limit_bytes), used


def _require_inheritance_release_for_publish(
    cur, *, payload: PublishNewFile, beneficiary_vault_id: str,
) -> None:
    if payload.inheritance_link_id is None:
        return
    # This SELECT holds a share lock until the publish transaction commits.
    # Owner revocation cannot slip between the final release check and making
    # the beneficiary's encrypted copy visible.
    inheritance_files._enabled()
    if payload.inheritance_source_file_id is None:
        raise HTTPException(400, detail="inheritance_source_required")
    source_id = inheritance_files._file_id(
        payload.inheritance_source_file_id,
    )
    owner = inheritance_files._released_owner(
        cur,
        link_id=payload.inheritance_link_id,
        beneficiary_vault_id=beneficiary_vault_id,
    )
    inheritance_files._require_all_owner_files_ready(cur, owner)
    source = inheritance_files._ready_file(
        cur, owner_vault_id=owner, file_id=source_id,
        lock_source=True,
    )
    if (payload.inheritance_source_revision is None or
            inheritance_files._source_revision(source) !=
            payload.inheritance_source_revision):
        raise HTTPException(409, detail="inherited_source_changed")


@router.post("/vault/file-v2/{file_id}/publish-new")
def publish_new_file(
    file_id: str,
    payload: PublishNewFile,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _new_upload_enabled()
    # No new V2 mode may publish before duplicate and name-conflict decisions
    # can be made atomically over blinded indexes for old and V2 files.
    from file_create_conflict_gate import require_new_file_conflict_parity
    require_new_file_conflict_parity()
    if not principal.get("file_v2_reader_capable", False):
        raise HTTPException(status_code=426, detail={
            "code": "client_update_required",
            "message": "Update SVaultAI before creating client-only files.",
        })
    require_content_write(principal)
    _file_id(file_id)
    if not payload.confirm:
        raise HTTPException(400, detail="file_v2_readback_confirmation_required")
    if ((payload.inheritance_link_id is None) !=
            (payload.inheritance_source_file_id is None)):
        raise HTTPException(400, detail="inheritance_source_required")
    if payload.inheritance_link_id is not None:
        inheritance_files._enabled()
        if payload.zk_proof_token is None:
            raise HTTPException(400, detail="inheritance_beneficiary_proof_required")
        if payload.inheritance_source_revision is None:
            raise HTTPException(400, detail="inherited_source_revision_required")
    elif (payload.zk_proof_token is not None or
          payload.inheritance_source_revision is not None):
        raise HTTPException(400, detail="unexpected_beneficiary_proof")
    vault_id = principal["vault_id"]
    if not is_vault_zk_adopted(vault_id):
        raise HTTPException(409, detail="zk_vault_required")
    content_token, name_tokens = _publish_conflict_tags(payload)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (vault_id, file_id))
        _require_inheritance_release_for_publish(
            cur, payload=payload, beneficiary_vault_id=vault_id,
        )
        # Login takes the vault row lock before it revokes the current
        # session. Take that same lock before making a file visible, then
        # recheck the session: a login may have superseded it since the
        # request dependency first authenticated this request.
        cur.execute(
            "SELECT total_bytes, account_id FROM vaults "
            "WHERE vault_id=%s FOR UPDATE", (vault_id,),
        )
        vault = cur.fetchone()
        if vault is None:
            raise HTTPException(404, detail="vault_not_found")
        cur.execute(
            "SELECT 1 FROM auth_sessions WHERE token_id=%s AND vault_id=%s "
            "AND file_v2_reader_capable=TRUE AND revoked_at IS NULL "
            "AND expires_at>NOW() LIMIT 1",
            (principal["token_id"], vault_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(401, detail="session_expired")
        cur.execute(
            "SELECT file_id, manifest_ciphertext, total_bytes, chunk_size, "
            "chunk_count, lifecycle_state, verification_state "
            "FROM file_v2_records WHERE file_id=%s AND vault_id=%s FOR UPDATE",
            (file_id, vault_id),
        )
        record = cur.fetchone()
        if record is None:
            raise HTTPException(404, detail="file_v2_not_found")
        cur.execute(
            "SELECT file_size, encrypted_file_data IS NOT NULL AS has_legacy, "
            "file_name, content_type, storage_mode, upload_status FROM uploaded_files "
            "WHERE id=%s AND vault_id=%s FOR UPDATE",
            (file_id, vault_id),
        )
        marker = cur.fetchone()
        if (record["lifecycle_state"] == "client_v2_ready" and
                record["verification_state"] == "client_verified"):
            if (marker is None or marker["has_legacy"] or
                    marker["file_name"] is not None or
                    marker["content_type"] is not None or
                    marker["storage_mode"] != "inline" or
                    marker["upload_status"] != "complete" or
                    int(marker["file_size"]) != int(record["total_bytes"])):
                raise HTTPException(409, detail="file_v2_published_state_inconsistent")
            conn.commit()
            return {"file_id": file_id, "status": "already_published"}
        if (record["lifecycle_state"] != "file_v2_written" or
                record["verification_state"] != "not_verified" or
                marker is not None):
            raise HTTPException(409, detail="file_v2_not_new")

        cur.execute(
            "SELECT chunk_index, OCTET_LENGTH(ciphertext) AS ciphertext_bytes "
            "FROM file_v2_chunks WHERE file_id=%s ORDER BY chunk_index "
            "LIMIT %s",
            (file_id, MAX_CHUNKS + 1),
        )
        _validate_framing(record, cur.fetchall() or [])
        total = int(record["total_bytes"])
        account_id = str(vault["account_id"]) if vault["account_id"] else None
        limit, used = _account_quota(cur, account_id, int(vault["total_bytes"]))
        if used + total > limit:
            raise HTTPException(413, detail={
                "code": "vault_storage_limit_exceeded",
                "used_bytes": used,
                "requested_bytes": total,
                "limit_bytes": limit,
            })

        conflict = inspect_and_reserve_new_file(
            cur, vault_id=vault_id, file_id=file_id, file_size=total,
            content_token=content_token, name_tokens=name_tokens,
            keep_content_duplicate=payload.duplicate_action == "keep_both",
        )
        if conflict.kind == "duplicate":
            if payload.duplicate_action == "skip":
                # An unverified stage has no visible file or quota charge.
                # Drop it with its ciphertext chunks inside this transaction
                # rather than leaving duplicate uploads to accumulate.
                cur.execute(
                    "DELETE FROM file_v2_records WHERE file_id=%s AND vault_id=%s "
                    "AND lifecycle_state='file_v2_written' "
                    "AND verification_state='not_verified'",
                    (file_id, vault_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(409, detail="file_v2_stage_changed")
                conn.commit()
                return {"file_id": file_id, "status": "skipped_duplicate",
                        "duplicate_of_file_id": conflict.existing_file_id}
            raise HTTPException(409, detail={
                "code": "duplicate_found",
                "existing_file_id": conflict.existing_file_id,
            })
        if conflict.kind == "name_conflict":
            # A client can decrypt its inventory, choose a versioned name,
            # prepare a fresh encrypted manifest and retry. The stage stays
            # unverified; no server-generated plaintext name is possible.
            raise HTTPException(409, detail={
                "code": "name_conflict",
                "existing_file_id": conflict.existing_file_id,
            })
        if conflict.kind != "available":
            raise HTTPException(409, detail="private_file_conflict_unknown")

        # The release state authorizes the beneficiary to copy the source;
        # publishing a new destination file also requires a fresh proof of
        # control of this beneficiary vault. Consume it only after quota and
        # conflict checks, in the same transaction as the marker insert.
        if payload.inheritance_link_id is not None:
            consume_recent_zk_proof_on_cursor(
                payload.zk_proof_token, principal, cur,
            )

        # NULL filename/content type are intentional: the only human-readable
        # metadata is inside the MVK-encrypted manifest already staged.
        cur.execute(
            "INSERT INTO uploaded_files "
            "(id,vault_id,file_name,content_type,file_size,encrypted_file_data,"
            "storage_mode,upload_status,duplicate_of_file_id) "
            "VALUES (%s,%s,NULL,NULL,%s,NULL,'inline','complete',%s)",
            (file_id, vault_id, total, conflict.existing_file_id),
        )
        cur.execute(
            "UPDATE file_v2_records SET lifecycle_state='client_v2_ready', "
            "verification_state='client_verified' "
            "WHERE file_id=%s AND vault_id=%s AND "
            "lifecycle_state='file_v2_written' AND verification_state='not_verified'",
            (file_id, vault_id),
        )
        if cur.rowcount != 1:
            raise HTTPException(409, detail="file_v2_publish_conflict")
        cur.execute("UPDATE vaults SET total_bytes=total_bytes+%s "
                    "WHERE vault_id=%s", (total, vault_id))
        if cur.rowcount != 1:
            raise HTTPException(409, detail="vault_quota_update_conflict")
        if account_id is not None:
            cur.execute(
                "SELECT COALESCE(SUM(total_bytes), 0) AS used "
                "FROM vaults WHERE account_id=%s", (account_id,),
            )
            account_used = int(cur.fetchone()["used"])
            cur.execute(
                "INSERT INTO account_storage_totals "
                "(account_id, encrypted_bytes) VALUES (%s, %s) "
                "ON CONFLICT (account_id) DO UPDATE SET "
                "encrypted_bytes=EXCLUDED.encrypted_bytes, "
                "last_recomputed=NOW()",
                (account_id, account_used),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    try:
        from vault_tool_result_cache import invalidate_for_event
        invalidate_for_event(vault_id=vault_id, event="file_uploaded")
    except Exception:
        pass
    return {"file_id": file_id, "status": "published"}


@router.post("/vault/file-v2/{file_id}/delete-new")
def delete_new_file(
    file_id: str,
    payload: DeleteNewFile,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled(True)
    require_content_write(principal)
    _file_id(file_id)
    if not payload.confirm:
        raise HTTPException(400, detail="file_delete_confirmation_required")
    vault_id = principal["vault_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (vault_id, file_id))
        cur.execute(
            "SELECT total_bytes, lifecycle_state, verification_state "
            "FROM file_v2_records WHERE file_id=%s AND vault_id=%s FOR UPDATE",
            (file_id, vault_id),
        )
        record = cur.fetchone()
        if record is None:
            raise HTTPException(404, detail="file_v2_not_found")
        if (record["lifecycle_state"] != "client_v2_ready" or
                record["verification_state"] != "client_verified"):
            raise HTTPException(409, detail="file_v2_not_new_ready")
        cur.execute(
            "SELECT file_size, encrypted_file_data IS NOT NULL AS has_legacy, "
            "file_name, content_type, storage_mode FROM uploaded_files "
            "WHERE id=%s AND vault_id=%s "
            "FOR UPDATE", (file_id, vault_id),
        )
        marker = cur.fetchone()
        total = int(record["total_bytes"])
        if (marker is None or marker["has_legacy"] or
                marker["file_name"] is not None or
                marker["content_type"] is not None or
                marker["storage_mode"] != "inline" or
                int(marker["file_size"]) != total):
            raise HTTPException(409, detail="file_v2_marker_inconsistent")
        cur.execute("SELECT account_id FROM vaults WHERE vault_id=%s FOR UPDATE",
                    (vault_id,))
        vault = cur.fetchone()
        if vault is None:
            raise HTTPException(404, detail="vault_not_found")
        # A newer login can revoke this session after the request dependency
        # authenticates it. The vault row lock serializes this check with login.
        cur.execute(
            "SELECT 1 FROM auth_sessions WHERE token_id=%s AND vault_id=%s "
            "AND file_v2_reader_capable=TRUE AND revoked_at IS NULL "
            "AND expires_at>NOW() LIMIT 1",
            (principal["token_id"], vault_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(401, detail="session_expired")
        account_id = str(vault["account_id"]) if vault["account_id"] else None
        if account_id is not None:
            cur.execute("SELECT account_id FROM accounts WHERE account_id=%s "
                        "FOR UPDATE", (account_id,))
            if cur.fetchone() is None:
                raise HTTPException(503, detail="account_quota_unavailable")
        # Consume the one-use proof in this transaction so any failed delete
        # leaves both the file and its proof intact for a safe retry.
        consume_recent_zk_proof_on_cursor(
            payload.zk_proof_token, principal, cur,
        )
        cur.execute("DELETE FROM file_v2_records WHERE file_id=%s AND vault_id=%s",
                    (file_id, vault_id))
        if cur.rowcount != 1:
            raise HTTPException(409, detail="file_v2_delete_conflict")
        cur.execute(
            "DELETE FROM uploaded_files WHERE id=%s AND vault_id=%s "
            "AND encrypted_file_data IS NULL AND file_name IS NULL",
            (file_id, vault_id),
        )
        if cur.rowcount != 1:
            raise HTTPException(409, detail="file_v2_marker_changed")
        cur.execute("UPDATE vaults SET total_bytes=GREATEST(total_bytes-%s,0) "
                    "WHERE vault_id=%s", (total, vault_id))
        if cur.rowcount != 1:
            raise HTTPException(409, detail="vault_quota_update_conflict")
        if account_id is not None:
            cur.execute(
                "SELECT COALESCE(SUM(total_bytes), 0) AS used "
                "FROM vaults WHERE account_id=%s", (account_id,),
            )
            account_used = int(cur.fetchone()["used"])
            cur.execute(
                "INSERT INTO account_storage_totals "
                "(account_id, encrypted_bytes) VALUES (%s, %s) "
                "ON CONFLICT (account_id) DO UPDATE SET "
                "encrypted_bytes=EXCLUDED.encrypted_bytes, "
                "last_recomputed=NOW()",
                (account_id, account_used),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for module, function, args, kwargs in (
        ("vault_relationship_graph", "cleanup_relationships_for_file",
         (vault_id, file_id), {}),
        ("vault_chat_active_entity", "clear_active_entity_if_matches_file",
         (vault_id, file_id), {}),
        ("vault_tool_result_cache", "invalidate_for_event", (),
         {"vault_id": vault_id, "event": "file_deleted"}),
    ):
        try:
            imported = __import__(module)
            getattr(imported, function)(*args, **kwargs)
        except Exception:
            pass
    return {"file_id": file_id, "deleted": True}
