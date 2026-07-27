import json
from typing import Any, Optional

from psycopg2.extras import RealDictCursor
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_local import verify_session_token
from device_gate import verify_trusted_device
from vault_core import (
    decrypt_message, encrypt_message, get_db,
    normalize_service, verify_vault_pin,
)

router = APIRouter(tags=["login-routes"])


def _normalize_service_name(service: Optional[str]) -> str:
    return normalize_service(service)


def _display_service_name(service: Optional[str]) -> str:
    value = " ".join(str(service or "").strip().split())
    return value


class ListLoginNamesRequest(BaseModel):
    pin: str


class GetLoginRequest(BaseModel):
    service: str
    pin: str


class DeleteLoginRequest(BaseModel):
    service: str
    pin: str


class LoginCountRequest(BaseModel):
    pin: str


class DeleteSecureItemRequest(BaseModel):
    service:   str
    item_type: str
    pin:       str


class GetSecureItemRequest(BaseModel):
    service:   str
    item_type: str
    pin:       str


class UpdateSecureItemRequest(BaseModel):
    old_service: str
    item_type:   str
    pin:         str
    new_service: Optional[str] = None
    fields:      Optional[dict[str, Any]] = None


@router.post("/list-login-names")
def list_login_names(
    payload: ListLoginNamesRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT service, MAX(created_at) AS last_created_at
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'login'
            GROUP BY service
            ORDER BY last_created_at DESC
            """,
            (vault_id,),
        )
        rows = cursor.fetchall() or []

        return {
            "logins": [
                {"service": row["service"]}
                for row in rows
            ]
        }
    finally:
        conn.close()


@router.post("/get-login")
def get_login(
    payload: GetLoginRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    normalized_service = _normalize_service_name(payload.service)

    if normalized_service == "general":
        raise HTTPException(status_code=400, detail="Missing service name")

    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT service, encrypted_data, created_at
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'login'
              AND LOWER(service) = LOWER(%s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (vault_id, normalized_service),
        )
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Login not found")

        return {
            "service": row["service"],
            "encrypted_data": row["encrypted_data"],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        }
    finally:
        conn.close()


@router.post("/delete-login")
def delete_login(
    payload: DeleteLoginRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    normalized_service = _normalize_service_name(payload.service)

    if normalized_service == "general":
        raise HTTPException(status_code=400, detail="Missing service name")

    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            DELETE FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'login'
              AND LOWER(service) = LOWER(%s)
            RETURNING service
            """,
            (vault_id, normalized_service),
        )
        deleted = cursor.fetchall() or []
        conn.commit()

        if not deleted:
            raise HTTPException(status_code=404, detail="Login not found")

                                                                  
        try:
            from vault_tool_result_cache import invalidate_for_event
            invalidate_for_event(
                vault_id=vault_id, event="credential_deleted",
            )
        except Exception:
            pass

        return {
            "deleted": True,
            "count": len(deleted),
            "service": normalized_service,
        }
    finally:
        conn.close()


@router.post("/login-count")
def login_count(
    payload: LoginCountRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT COUNT(DISTINCT service) AS login_count
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'login'
            """,
            (vault_id,),
        )
        row = cursor.fetchone() or {}

        return {"login_count": int(row.get("login_count") or 0)}
    finally:
        conn.close()


@router.post("/update-secure-item")
def update_secure_item(
    payload: UpdateSecureItemRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id        = principal["vault_id"]
    old_service_raw = _display_service_name(payload.old_service)
    old_service     = _normalize_service_name(payload.old_service)
    item_type       = (payload.item_type or "").strip()
    new_service_in  = _display_service_name(payload.new_service)

    if not item_type:
        raise HTTPException(
            status_code=400, detail="Missing item type",
        )
    if old_service == "general":
        raise HTTPException(
            status_code=400, detail="Missing service name",
        )

    key = verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, service, encrypted_data
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = %s
              AND LOWER(service) = LOWER(%s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (vault_id, item_type, old_service),
        )
        row = cur.fetchone()

                                                              
        existing_blob = row["encrypted_data"] if row else None
        if isinstance(existing_blob, (bytes, bytearray, memoryview)):
            existing_blob_size = len(bytes(existing_blob))
        elif isinstance(existing_blob, str):
            existing_blob_size = len(existing_blob.encode("utf-8"))
        else:
            existing_blob_size = 0

        try:
            existing = (
                json.loads(decrypt_message(row["encrypted_data"], key))
                if row else {}
            )
        except Exception:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}

                                                             
        _SCHEMA_B_MARKERS = {"category", "title", "fields", "item_id"}
        if any(k in existing for k in _SCHEMA_B_MARKERS):
            existing_fields = existing.get("fields") or {}
            if not isinstance(existing_fields, dict):
                existing_fields = {}
            existing_notes = existing.get("notes")
        else:
                                                                 
            existing_fields = existing
            existing_notes  = None
        incoming_fields = payload.fields or {}
        merged_fields = {**existing_fields, **incoming_fields}

        new_service = (
            new_service_in
            if new_service_in
            else ((row["service"] if row else None) or old_service_raw or old_service)
        )
        if _normalize_service_name(new_service) == "general":
            new_service = (
                (row["service"] if row else None)
                or old_service_raw
                or old_service
            )

                                                                
        merged_record = {
            "category": (
                existing.get("category") if isinstance(existing.get("category"), str)
                else None
            ) or item_type,
            "title":    new_service,
            "fields":   merged_fields,
            "notes":    existing_notes,
            "item_id":  existing.get("item_id") or (row["id"] if row else None),
        }
                                                                   
         
        for preserved_key in ("schema", "warningConfirmed"):
            if preserved_key in existing:
                merged_record[preserved_key] = existing[preserved_key]
                                                                  
                                                                
        try:
            from crypto_schemas import (
                annotate_crypto_record,
                requires_warning_confirmation_for_category,
            )
            cat = merged_record.get("category")
            warning_confirmed = (
                True
                if requires_warning_confirmation_for_category(cat)
                else None
            )
            annotate_crypto_record(
                merged_record,
                category=cat,
                warning_confirmed=warning_confirmed,
            )
        except Exception:
                                                                
                                                      
            pass

        created = row is None
        if row:
            encrypted = encrypt_message(json.dumps(merged_record), key)
            cur.execute(
                """
                UPDATE vault_items
                SET service        = %s,
                    encrypted_data = %s,
                    created_at     = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (new_service, encrypted, row["id"]),
            )
            item_id = row["id"]

            conn.commit()


            new_blob_size = (
                len(bytes(encrypted))
                if isinstance(encrypted, (bytes, bytearray, memoryview))
                else (len(encrypted.encode("utf-8"))
                      if isinstance(encrypted, str) else 0)
            )
            delta = int(new_blob_size) - int(existing_blob_size)
            if delta != 0:
                try:
                    from main import bump_vault_total_bytes
                    bump_vault_total_bytes(vault_id, delta)
                except Exception:
                    pass
        else:
            from vault_secure_item_save import _encrypt_and_write
            write_result = _encrypt_and_write(
                vault_id=vault_id,
                key=key,
                args={
                    "secret_type": item_type,
                    "service":     new_service,
                    "fields":      merged_fields,
                    "notes":       existing_notes,
                },
                field=None,
                value=None,
                notes=existing_notes,
                db_executor=None,
            )
            if write_result.get("band") != "saved":
                raise HTTPException(
                    status_code=500,
                    detail="Could not create saved item",
                )
            item_id = write_result.get("item_id")

                                                            
        try:
            from vault_tool_result_cache import invalidate_for_event
            event = (
                "credential_edited" if item_type in ("login", "credential")
                else "secure_item_edited"
            )
            invalidate_for_event(vault_id=vault_id, event=event)
        except Exception:
            pass

        return {
            "updated":   True,
            "created":   created,
            "id":        item_id,
            "service":   new_service,
            "item_type": item_type,
        }
    finally:
        conn.close()


@router.post("/get-secure-item")
def get_secure_item(
    payload: GetSecureItemRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id           = principal["vault_id"]
    normalized_service = _normalize_service_name(payload.service)
    item_type          = (payload.item_type or "").strip()

    if not item_type:
        raise HTTPException(
            status_code=400, detail="Missing item type",
        )
    if normalized_service == "general":
        raise HTTPException(
            status_code=400, detail="Missing service name",
        )

    key = verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, service, item_type, encrypted_data, created_at
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = %s
              AND LOWER(service) = LOWER(%s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (vault_id, item_type, normalized_service),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=404, detail="Saved item not found",
            )

        try:
            record = json.loads(decrypt_message(row["encrypted_data"], key))
        except Exception:
            record = {}
        if not isinstance(record, dict):
            record = {}

                                                               
        _SCHEMA_B_MARKERS = {"category", "title", "fields", "item_id"}
        if any(k in record for k in _SCHEMA_B_MARKERS):
            inner = record.get("fields")
            fields_out = inner if isinstance(inner, dict) else {}
            title_out  = (
                record.get("title") if isinstance(record.get("title"), str)
                else (row["service"] or normalized_service)
            )
            notes_out  = record.get("notes")
        else:
                                                        
            fields_out = record
            title_out  = row["service"] or normalized_service
            notes_out  = None

        return {
            "service":    title_out,
            "item_type":  row["item_type"] or item_type,
            "fields":     fields_out,
            "notes":      notes_out,
            "created_at": (
                row["created_at"].isoformat()
                if row.get("created_at") else None
            ),
        }
    finally:
        conn.close()


@router.post("/delete-secure-item")
def delete_secure_item(
    payload: DeleteSecureItemRequest,
    principal=Depends(verify_trusted_device),
):
    vault_id           = principal["vault_id"]
    normalized_service = _normalize_service_name(payload.service)
    item_type          = (payload.item_type or "").strip()

    if not item_type:
        raise HTTPException(
            status_code=400,
            detail="Missing item type",
        )
    if normalized_service == "general":
        raise HTTPException(
            status_code=400,
            detail="Missing service name",
        )

    verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            DELETE FROM vault_items
            WHERE vault_id  = %s
              AND item_type = %s
              AND LOWER(service) = LOWER(%s)
            RETURNING service, encrypted_data
            """,
            (vault_id, item_type, normalized_service),
        )
        deleted = cursor.fetchall() or []
        conn.commit()

        if not deleted:
                                                                 
                                                            
            raise HTTPException(
                status_code=404, detail="Saved item not found",
            )

                                                             
        freed = 0
        for row in deleted:
            blob = row.get("encrypted_data")
            if blob is None:
                continue
            if isinstance(blob, (bytes, bytearray, memoryview)):
                freed += len(bytes(blob))
            elif isinstance(blob, str):
                freed += len(blob.encode("utf-8"))
        if freed > 0:
            try:
                from main import bump_vault_total_bytes
                bump_vault_total_bytes(vault_id, -int(freed))
            except Exception:
                pass

                                                             
        try:
            from vault_tool_result_cache import invalidate_for_event
            event = (
                "credential_deleted" if item_type in ("login", "credential")
                else "secure_item_deleted"
            )
            invalidate_for_event(vault_id=vault_id, event=event)
        except Exception:
            pass

        return {
            "deleted":   True,
            "count":     len(deleted),
            "service":   normalized_service,
            "item_type": item_type,
        }
    finally:
        conn.close()


@router.post("/list-secure-items")
def list_secure_items(
    payload: ListLoginNamesRequest,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    verify_vault_pin(vault_id, payload.pin)

    from vault_item_visibility import SYSTEM_ITEM_TYPE_SQL_TUPLE

    conn = get_db()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
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
        rows = cursor.fetchall() or []
        return {
            "items": [
                {
                    "service":    row.get("service") or "",
                    "item_type":  row.get("item_type") or "other",
                    "created_at": (
                        row["created_at"].isoformat()
                        if row.get("created_at") else None
                    ),
                }
                for row in rows
            ],
        }
    finally:
        conn.close()


class SaveCryptoWalletProfileRequest(BaseModel):


    pin:           str
    asset:         str
    network:       Optional[str] = None
    walletLabel:   str
    publicAddress: str
    note:          Optional[str] = None
                                                         
                                                       
    title:         Optional[str] = None


class SaveCryptoSensitiveBackupRequest(BaseModel):


    pin:              str
    asset:            Optional[str] = None
    network:          Optional[str] = None
    walletLabel:      str
    secretType:       str                                                            
    secretValue:      str
    note:             Optional[str] = None
    warningConfirmed: bool = False
    title:            Optional[str] = None


def _default_wallet_profile_title(label: str, network: str) -> str:
    label = (label or "").strip() or "Crypto"
    network = (network or "").strip()
    if not network:
        return f"{label} wallet"
    return f"{label} {network} wallet"


def _default_sensitive_backup_title(
    label: str, secret_type: str,
) -> str:
    label = (label or "").strip() or "Crypto"
    pretty = (secret_type or "").replace("_", " ").strip() or "backup"
    return f"{label} {pretty}"


@router.post("/crypto/save-wallet-profile")
def save_crypto_wallet_profile(
    payload: SaveCryptoWalletProfileRequest,
    principal=Depends(verify_trusted_device),
):


    from vault_saved_item_taxonomy import CATEGORY_CRYPTO_WALLET_ADDRESS
    from vault_secure_item_save import _encrypt_and_write
    from crypto_schemas import (
        build_wallet_profile_record,
        CryptoSchemaError,
        SCHEMA_CRYPTO_WALLET_PROFILE_V1,
    )

    vault_id = principal["vault_id"]
    try:
                                                               
                                                            
        record = build_wallet_profile_record(
            asset=payload.asset,
            network=payload.network,
            wallet_label=payload.walletLabel,
            public_address=payload.publicAddress,
            note=payload.note,
        )
    except CryptoSchemaError as exc:
                                                            
                                                              
        raise HTTPException(
            status_code=400,
            detail={"schema_error": str(exc)},
        )

    key = verify_vault_pin(vault_id, payload.pin)

    title = (payload.title or "").strip() or (
        _default_wallet_profile_title(
            record["walletLabel"], record["network"],
        )
    )
    args = {
        "secret_type": CATEGORY_CRYPTO_WALLET_ADDRESS,
        "service":     title,
        "fields": {
                                                               
                                                                  
            "wallet_address": record["publicAddress"],
            "network":        record["network"],
            "wallet_label":   record["walletLabel"],
            "asset":          record["asset"],
            "balance_status": record["balanceStatus"],
        },
        "notes": record["note"] or None,
    }
    result = _encrypt_and_write(
        vault_id=vault_id, key=key,
        args=args,
        field="wallet_address",
        value=record["publicAddress"],
        notes=args["notes"],
        db_executor=None,
    )
    if result.get("band") != "saved":
                                                          
                                                             
        raise HTTPException(
            status_code=500,
            detail={
                "save_error": result.get("band", "unknown"),
            },
        )
    return {
        "status":   "saved",
        "schema":   SCHEMA_CRYPTO_WALLET_PROFILE_V1,
        "item_id":  result.get("item_id"),
        "category": CATEGORY_CRYPTO_WALLET_ADDRESS,
    }


@router.post("/crypto/save-sensitive-backup")
def save_crypto_sensitive_backup(
    payload: SaveCryptoSensitiveBackupRequest,
    principal=Depends(verify_trusted_device),
):


    from vault_secure_item_save import _encrypt_and_write
    from crypto_schemas import (
        build_sensitive_backup_record,
        category_for_secret_type,
        CryptoSchemaError,
        SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
    )

    vault_id = principal["vault_id"]

                                                            
    if payload.warningConfirmed is not True:
        raise HTTPException(
            status_code=403,
            detail={"warning_required": True},
        )

    try:
        record = build_sensitive_backup_record(
            asset=payload.asset,
            network=payload.network,
            wallet_label=payload.walletLabel,
            secret_type=payload.secretType,
            secret_value=payload.secretValue,
            note=payload.note,
            warning_confirmed=True,
        )
    except CryptoSchemaError as exc:
        raise HTTPException(
            status_code=400,
            detail={"schema_error": str(exc)},
        )

    key = verify_vault_pin(vault_id, payload.pin)

    category = category_for_secret_type(record["secretType"])
    if category is None:
                                                                
                                             
        raise HTTPException(
            status_code=400,
            detail={"schema_error": "unknown secretType"},
        )
    title = (payload.title or "").strip() or (
        _default_sensitive_backup_title(
            record["walletLabel"], record["secretType"],
        )
    )
                                                                 
                                            
    field_for_secret = {
        "seed_phrase":     "seed_phrase",
        "private_key":     "private_key",
        "recovery_phrase": "recovery_phrase",
    }[record["secretType"]]
    args = {
        "secret_type": category,
        "service":     title,
        "fields": {
            field_for_secret:  record["secretValue"],
            "network":         record["network"] or "",
            "wallet_label":    record["walletLabel"],
            "asset":           record["asset"] or "",
            "secret_type":     record["secretType"],
        },
        "notes": record["note"] or None,
    }
    result = _encrypt_and_write(
        vault_id=vault_id, key=key,
        args=args,
        field=field_for_secret,
        value=record["secretValue"],
        notes=args["notes"],
        db_executor=None,
    )
    if result.get("band") != "saved":
        raise HTTPException(
            status_code=500,
            detail={"save_error": result.get("band", "unknown")},
        )
    return {
        "status":   "saved",
        "schema":   SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
        "item_id":  result.get("item_id"),
        "category": category,
    }


class RevealSensitiveBackupRequest(BaseModel):


    pin:       str
    service:   str
    item_type: str


@router.post("/crypto/reveal-sensitive-backup")
def reveal_sensitive_backup(
    payload: RevealSensitiveBackupRequest,
    principal=Depends(verify_trusted_device),
):


    from crypto_schemas import (
        SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
        is_sensitive_backup_schema,
        requires_warning_confirmation_for_category,
    )
    import logging
    _logger = logging.getLogger("crypto_reveal_route")

    vault_id  = principal["vault_id"]
    service   = _normalize_service_name(payload.service)
    item_type = (payload.item_type or "").strip()

    if not item_type:
        raise HTTPException(
            status_code=400, detail="Missing item type",
        )
    if service == "general":
        raise HTTPException(
            status_code=400, detail="Missing service name",
        )

                                                             
    if not requires_warning_confirmation_for_category(item_type):
                                                               
                                            
        _logger.info(
            "[CRYPTO-REVEAL] refused vault=%s item_type=%s "
            "reason=item_type_not_sensitive_backup",
            (vault_id or "")[:8] + "…", item_type,
        )
        raise HTTPException(
            status_code=403,
            detail={"reveal_error": "not_sensitive_backup"},
        )

                                                                 
    from rate_limit_crypto_reveal import enforce_crypto_reveal_rate_limit
    enforce_crypto_reveal_rate_limit(vault_id)

    key = verify_vault_pin(vault_id, payload.pin)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
                                                            
                                     
        cur.execute(
            """
            SELECT id, encrypted_data
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = %s
              AND LOWER(service) = LOWER(%s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (vault_id, item_type, service),
        )
        row = cur.fetchone()
        if not row:
            _logger.info(
                "[CRYPTO-REVEAL] not_found vault=%s item_type=%s",
                (vault_id or "")[:8] + "…", item_type,
            )
            raise HTTPException(
                status_code=404,
                detail={"reveal_error": "not_found"},
            )

        try:
            record = json.loads(
                decrypt_message(row["encrypted_data"], key),
            )
        except Exception:
            _logger.exception(
                "[CRYPTO-REVEAL] decrypt_failed vault=%s item_type=%s",
                (vault_id or "")[:8] + "…", item_type,
            )
                                                              
                                                             
            raise HTTPException(
                status_code=500,
                detail={"reveal_error": "decrypt_failed"},
            )
        if not isinstance(record, dict):
            raise HTTPException(
                status_code=500,
                detail={"reveal_error": "decrypt_failed"},
            )

                                                              
        blob_schema = record.get("schema")
        if blob_schema is not None and not is_sensitive_backup_schema(
            blob_schema,
        ):
            _logger.info(
                "[CRYPTO-REVEAL] refused vault=%s item_type=%s "
                "reason=schema_mismatch",
                (vault_id or "")[:8] + "…", item_type,
            )
            raise HTTPException(
                status_code=403,
                detail={"reveal_error": "schema_mismatch"},
            )

        fields = record.get("fields")
        if not isinstance(fields, dict):
            raise HTTPException(
                status_code=500,
                detail={"reveal_error": "decrypt_failed"},
            )

                                                               
        secret_type   = None
        secret_value  = None
        for stype in ("recovery_phrase", "seed_phrase", "private_key"):
            if isinstance(fields.get(stype), str) and fields[stype]:
                secret_type  = stype
                secret_value = fields[stype]
                break
                                                                  
                                             
        explicit_type = fields.get("secret_type")
        if isinstance(explicit_type, str) and explicit_type in (
            "seed_phrase", "private_key", "recovery_phrase",
        ):
            secret_type = explicit_type
            val = fields.get(explicit_type)
            if isinstance(val, str) and val:
                secret_value = val

        if not secret_type or not secret_value:
            _logger.info(
                "[CRYPTO-REVEAL] no_secret_field vault=%s "
                "item_type=%s",
                (vault_id or "")[:8] + "…", item_type,
            )
            raise HTTPException(
                status_code=500,
                detail={"reveal_error": "no_secret_field"},
            )

                                                                
        _logger.info(
            "[CRYPTO-REVEAL] ok vault=%s item_type=%s "
            "secret_type=%s",
            (vault_id or "")[:8] + "…", item_type, secret_type,
        )
        return {
            "status":      "ok",
            "schema":      SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
            "secretType":  secret_type,
            "secretValue": secret_value,
        }
    finally:
        conn.close()


class SaveCryptoNoteRequest(BaseModel):


    pin:         str
    title:       str
    note:        str
    noteType:    str = "general"                                          
    asset:       Optional[str] = None
    network:     Optional[str] = None
    walletLabel: Optional[str] = None
    txHash:      Optional[str] = None
    amountText:  Optional[str] = None
    dateText:    Optional[str] = None


def _crypto_note_log_label(record: dict) -> str:


    parts = [record.get("noteType", "general")]
    asset = record.get("asset") or ""
    if isinstance(asset, str) and asset:
        parts.append(asset)
    return "/".join(parts)


@router.post("/crypto/save-note")
def save_crypto_note(
    payload: SaveCryptoNoteRequest,
    principal=Depends(verify_trusted_device),
):


    from vault_secure_item_save import _encrypt_and_write
    from crypto_schemas import (
        build_crypto_note_record,
        category_for_note_type,
        CryptoSchemaError,
        SCHEMA_CRYPTO_NOTE_V1,
    )

    vault_id = principal["vault_id"]
    try:
                                                                  
                                
        record = build_crypto_note_record(
            asset=payload.asset,
            network=payload.network,
            title=payload.title,
            note=payload.note,
            note_type=payload.noteType,
            wallet_label=payload.walletLabel,
            tx_hash=payload.txHash,
            amount_text=payload.amountText,
            date_text=payload.dateText,
        )
    except CryptoSchemaError as exc:
                                                               
                                                  
        raise HTTPException(
            status_code=400,
            detail={"schema_error": str(exc)},
        )

    category = category_for_note_type(record["noteType"])
    if category is None:
        raise HTTPException(
            status_code=400,
            detail={"schema_error": "unknown noteType"},
        )

    key = verify_vault_pin(vault_id, payload.pin)

                                                            
    body_field = (
        "crypto_note"
        if record["noteType"] == "general"
        else "transaction_note"
    )
    args = {
        "secret_type": category,
        "service":     record["title"],
        "fields": {
            body_field:    record["note"],
            "note_type":   record["noteType"],
            "asset":       record["asset"],
            "network":     record["network"],
            "wallet_label": record["walletLabel"],
            "tx_hash":     record["txHash"],
            "amount_text": record["amountText"],
            "date_text":   record["dateText"],
        },
        "notes": None,
    }
    result = _encrypt_and_write(
        vault_id=vault_id, key=key,
        args=args,
        field=body_field,
        value=record["note"],
        notes=None,
        db_executor=None,
    )
    if result.get("band") != "saved":
        raise HTTPException(
            status_code=500,
            detail={"save_error": result.get("band", "unknown")},
        )
    return {
        "status":   "saved",
        "schema":   SCHEMA_CRYPTO_NOTE_V1,
        "item_id":  result.get("item_id"),
        "category": category,
        "noteType": record["noteType"],
    }
