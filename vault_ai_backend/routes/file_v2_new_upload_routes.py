"""Publish and delete fully encrypted, client-MVK V2 files.

The existing manifest/chunk routes stage ciphertext. This module never sees a
filename, PIN, MVK, file key or plaintext content. New files become visible and
count against quota only after the client confirms its own GET/decrypt readback
and this route verifies a complete, bounded ciphertext set.
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from routes.file_v2_routes import _enabled
from subscription_entitlement import require_content_write
from vault_core import MAX_VAULT_BYTES, get_db, is_vault_zk_adopted
from routes.auth_zk_routes import consume_recent_zk_proof


router = APIRouter()
MAX_NEW_FILE_BYTES = 64 * 1024 * 1024  # FileV2Reader's current bound.
MAX_CHUNK_BYTES = 16 * 1024 * 1024
MAX_CHUNKS = 4096
MAX_MANIFEST_CIPHERTEXT = 64 * 1024
AES_GCM_FRAME_OVERHEAD = 28  # 12-byte nonce + 16-byte tag.


class PublishNewFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool


class DeleteNewFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    zk_proof_token: str = Field(min_length=1, max_length=128)


def _new_upload_enabled() -> None:
    _enabled(True)
    if os.getenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", "false").lower() != "true":
        raise HTTPException(404, detail="new_file_v2_disabled")


def _file_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, detail="new_file_id_must_be_uuid") from None
    if str(parsed) != value.lower():
        raise HTTPException(400, detail="new_file_id_must_be_uuid")
    return value


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


@router.post("/vault/file-v2/{file_id}/publish-new")
def publish_new_file(
    file_id: str,
    payload: PublishNewFile,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _new_upload_enabled()
    require_content_write(principal)
    _file_id(file_id)
    if not payload.confirm:
        raise HTTPException(400, detail="file_v2_readback_confirmation_required")
    vault_id = principal["vault_id"]
    if not is_vault_zk_adopted(vault_id):
        raise HTTPException(409, detail="zk_vault_required")

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (vault_id, file_id))
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
            "file_name, upload_status FROM uploaded_files "
            "WHERE id=%s AND vault_id=%s FOR UPDATE",
            (file_id, vault_id),
        )
        marker = cur.fetchone()
        if (record["lifecycle_state"] == "client_v2_ready" and
                record["verification_state"] == "client_verified"):
            if (marker is None or marker["has_legacy"] or
                    marker["file_name"] not in (None, "") or
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
        cur.execute(
            "SELECT total_bytes, account_id FROM vaults "
            "WHERE vault_id=%s FOR UPDATE", (vault_id,),
        )
        vault = cur.fetchone()
        if vault is None:
            raise HTTPException(404, detail="vault_not_found")
        account_id = str(vault["account_id"]) if vault["account_id"] else None
        limit, used = _account_quota(cur, account_id, int(vault["total_bytes"]))
        if used + total > limit:
            raise HTTPException(413, detail={
                "code": "vault_storage_limit_exceeded",
                "used_bytes": used,
                "requested_bytes": total,
                "limit_bytes": limit,
            })

        # NULL filename/content type are intentional: the only human-readable
        # metadata is inside the MVK-encrypted manifest already staged.
        cur.execute(
            "INSERT INTO uploaded_files "
            "(id,vault_id,file_name,content_type,file_size,encrypted_file_data,"
            "storage_mode,upload_status) "
            "VALUES (%s,%s,NULL,NULL,%s,NULL,'inline','complete')",
            (file_id, vault_id, total),
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
            "file_name FROM uploaded_files WHERE id=%s AND vault_id=%s "
            "FOR UPDATE", (file_id, vault_id),
        )
        marker = cur.fetchone()
        total = int(record["total_bytes"])
        if (marker is None or marker["has_legacy"] or
                marker["file_name"] not in (None, "") or
                int(marker["file_size"]) != total):
            raise HTTPException(409, detail="file_v2_marker_inconsistent")
        cur.execute("SELECT account_id FROM vaults WHERE vault_id=%s FOR UPDATE",
                    (vault_id,))
        vault = cur.fetchone()
        if vault is None:
            raise HTTPException(404, detail="vault_not_found")
        account_id = str(vault["account_id"]) if vault["account_id"] else None
        if account_id is not None:
            cur.execute("SELECT account_id FROM accounts WHERE account_id=%s "
                        "FOR UPDATE", (account_id,))
            if cur.fetchone() is None:
                raise HTTPException(503, detail="account_quota_unavailable")
        consume_recent_zk_proof(payload.zk_proof_token, principal)
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
