import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor


logger = logging.getLogger(__name__)

from auth_local import verify_session_token
from device_gate import verify_trusted_device
from subscription_entitlement import require_content_write
from vault_core import (
    get_db,
    encrypt_message,
    decrypt_message,
    verify_vault_pin,
    normalize_service,
    is_real_name,
)


router = APIRouter()


class ListLoginNamesRequest(BaseModel):
    vault_name: str
    pin: str


class ListFullLoginsRequest(BaseModel):
    vault_name: str
    pin: str


class LoginUpdateRequest(BaseModel):
    vault_name: str
    pin: str
    old_service: str
    new_service: str
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    pin_value: Optional[str] = None
    note: Optional[str] = None


class LoginDeleteRequest(BaseModel):
    vault_name: str
    service: str
    pin: str


class FileRenameRequest(BaseModel):
    vault_name: str
    file_id: str
    saved_name: str
    pin: str


class FileDeleteRequest(BaseModel):
    vault_name: str
    file_id: str
    pin: str


def _normalize(value: str) -> str:
    return normalize_service(value)


@router.post("/list-login-names")
async def list_login_names(
    payload: ListLoginNamesRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT service, MAX(created_at) AS created_at
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'login'
            GROUP BY service
            ORDER BY service ASC
            """,
            (vault_id,),
        )
        rows = cur.fetchall() or []
        return {"logins": rows}
    finally:
        conn.close()


@router.post("/list-secure-items")
async def list_secure_items(
    payload: ListLoginNamesRequest,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    from vault_item_visibility import SYSTEM_ITEM_TYPE_SQL_TUPLE

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT
              service,
              item_type,
              MAX(created_at) AS created_at
            FROM vault_items
            WHERE vault_id = %s
              AND item_type NOT IN %s
            GROUP BY service, item_type
            ORDER BY MAX(created_at) DESC
            """,
            (vault_id, SYSTEM_ITEM_TYPE_SQL_TUPLE),
        )
        rows = cur.fetchall() or []
        return {
            "items": [
                {
                    "service":    r.get("service") or "",
                    "item_type":  r.get("item_type") or "other",
                    "created_at": (
                        r["created_at"].isoformat()
                        if r.get("created_at") else None
                    ),
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@router.post("/logins-full")
async def list_full_logins(
    payload: ListFullLoginsRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    key = verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT service, encrypted_data, created_at
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'login'
            ORDER BY service ASC
            """,
            (vault_id,),
        )

        rows = cur.fetchall() or []
        logins = []

        for row in rows:
            try:
                fields = json.loads(decrypt_message(row["encrypted_data"], key))
            except Exception:
                fields = {}

            logins.append({
                "service": row["service"],
                "username": fields.get("username"),
                "email": fields.get("email"),
                "password": fields.get("password"),
                "pin": fields.get("pin"),
                "note": fields.get("note"),
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            })

        return {"logins": logins}
    finally:
        conn.close()


@router.patch("/login")
async def update_login(
    payload: LoginUpdateRequest,
    principal=Depends(verify_trusted_device),
):
    require_content_write(principal)
    vault_id = principal["vault_id"]

    old_service = _normalize(payload.old_service)
    new_service = _normalize(payload.new_service)

    if not is_real_name(old_service) or not is_real_name(new_service):
        raise HTTPException(status_code=400, detail="Missing service name")

    key = verify_vault_pin(vault_id, payload.pin)

    new_fields = {}
    if payload.username is not None:
        new_fields["username"] = payload.username
    if payload.email is not None:
        new_fields["email"] = payload.email
    if payload.password is not None:
        new_fields["password"] = payload.password
    if payload.pin_value is not None:
        new_fields["pin"] = payload.pin_value
    if payload.note is not None:
        new_fields["note"] = payload.note

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, encrypted_data
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'login'
              AND LOWER(service) = LOWER(%s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (vault_id, old_service),
        )
        row = cur.fetchone()

        old_fields = {}
        if row:
            old_fields = json.loads(decrypt_message(row["encrypted_data"], key))

        merged_fields = {**old_fields, **new_fields}
        encrypted = encrypt_message(json.dumps(merged_fields), key)

        if row:
            cur.execute(
                """
                UPDATE vault_items
                SET service = %s,
                    encrypted_data = %s,
                    created_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (new_service, encrypted, row["id"]),
            )
            _login_item_id = row["id"]
        else:
            cur.execute(
                """
                INSERT INTO vault_items (vault_id, item_type, service, encrypted_data)
                VALUES (%s, 'login', %s, %s)
                RETURNING id
                """,
                (vault_id, new_service, encrypted),
            )
            _new_row = cur.fetchone()
            _new_item_id = (
                _new_row["id"] if isinstance(_new_row, dict)
                else (_new_row[0] if _new_row else None)
            )
            _login_item_id = _new_item_id
                                                                                
            if _new_item_id is not None:
                try:
                    from main import client as _openai_client
                    from semantic_embedder import enqueue_vault_item_embedding
                    enqueue_vault_item_embedding(_openai_client, vault_id, _new_item_id, "item_service", new_service)
                    enqueue_vault_item_embedding(_openai_client, vault_id, _new_item_id, "item_type", "login")
                except Exception:
                    pass
                                                                                             
                try:
                    from asset_tagger import tag_vault_item_safe
                    tag_vault_item_safe(vault_id, _new_item_id,
                                        service=new_service, item_type="login")
                except Exception:
                    pass

        conn.commit()

                                                           
        try:
            from vault_tool_result_cache import invalidate_for_event
            invalidate_for_event(
                vault_id=vault_id, event="credential_edited",
            )
        except Exception:
            pass

                                                                   
        try:
            _pw = merged_fields.get("password")
            if _pw and _login_item_id is not None:
                from password_audit import upsert_password_audit_safe
                upsert_password_audit_safe(
                    vault_id, int(_login_item_id), _pw, generated=False,
                )
        except Exception:
            pass
        return {"status": "updated", "service": new_service}
    finally:
        conn.close()


def _delete_login_impl(payload: LoginDeleteRequest, vault_id: str):


    service = _normalize(payload.service)

    if not is_real_name(service):
        raise HTTPException(status_code=400, detail="Missing service name")

    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            DELETE FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'login'
              AND LOWER(service) = LOWER(%s)
            RETURNING service, encrypted_data
            """,
            (vault_id, service),
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Login not found")

                                                               
        try:
            from vault_tool_result_cache import invalidate_for_event
            invalidate_for_event(
                vault_id=vault_id, event="credential_deleted",
            )
        except Exception:
            pass

                                                            
        try:
            blob = row.get("encrypted_data")
            freed = 0
            if isinstance(blob, (bytes, bytearray, memoryview)):
                freed = len(bytes(blob))
            elif isinstance(blob, str):
                freed = len(blob.encode("utf-8"))
            if freed > 0:
                from main import bump_vault_total_bytes
                bump_vault_total_bytes(vault_id, -int(freed))
        except Exception:
            pass

        return {"status": "deleted", "service": service}
    finally:
        conn.close()


@router.delete("/login")
async def delete_login(
    payload: LoginDeleteRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    return _delete_login_impl(payload, vault_id)


@router.post("/login/delete")
async def delete_login_post(
    payload: LoginDeleteRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    return _delete_login_impl(payload, vault_id)


@router.patch("/file")
async def rename_file(
    payload: FileRenameRequest,
    principal=Depends(verify_trusted_device),
):
    require_content_write(principal)
    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            UPDATE uploaded_files
            SET saved_name = %s,
                needs_naming = FALSE
            WHERE id = %s
              AND vault_id = %s
            RETURNING id, file_name, saved_name
            """,
            (_normalize(payload.saved_name), payload.file_id, vault_id),
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            raise HTTPException(status_code=404, detail="File not found")

                                                           
        try:
            from vault_tool_result_cache import invalidate_for_event
            invalidate_for_event(
                vault_id=vault_id, event="file_renamed",
            )
        except Exception:
            pass

        return {"status": "renamed", "file": row}
    finally:
        conn.close()


def _delete_file_impl(payload: FileDeleteRequest, vault_id: str):


    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            DELETE FROM uploaded_files
            WHERE id = %s
              AND vault_id = %s
            RETURNING id, file_name, file_size
            """,
            (payload.file_id, vault_id),
        )
        row = cur.fetchone()

        if not row:
            conn.commit()
            raise HTTPException(status_code=404, detail="File not found")

        cur.execute(
            """
            UPDATE vaults
            SET total_bytes = GREATEST(total_bytes - %s, 0)
            WHERE vault_id = %s
            """,
            (int(row["file_size"] or 0), vault_id),
        )

        conn.commit()


        try:
            from vault_tool_result_cache import invalidate_for_event
            invalidate_for_event(
                vault_id=vault_id, event="file_deleted",
            )
        except Exception:
            pass

        # 2026-07-31 active-entity lifecycle (blocker 3, second delete
        # path). The primary /delete-file endpoint clears the pin on
        # delete; this vault-manage route is the OTHER authoritative
        # deletion path. Without this hook, deleting a pinned file
        # via /vault-manage/file (or POST /file/delete) leaves the
        # active-entity pin stale for the full 900 s TTL. Independent
        # review of d184d22 flagged this as the one remaining gap in
        # blocker 3's coverage.
        try:
            from vault_chat_active_entity import (
                clear_active_entity_if_matches_file,
            )
            clear_active_entity_if_matches_file(
                vault_id, payload.file_id,
            )
        except Exception:
            logger.exception(
                "[vault-manage/file] active-entity cleanup failed "
                "vault=%s file=%s", vault_id, payload.file_id,
            )

        return {"status": "deleted", "file": row}
    finally:
        conn.close()


@router.delete("/file")
async def delete_file(
    payload: FileDeleteRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    return _delete_file_impl(payload, vault_id)


@router.post("/file/delete")
async def delete_file_post(
    payload: FileDeleteRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    return _delete_file_impl(payload, vault_id)
