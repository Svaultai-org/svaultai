

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional


logger = logging.getLogger(__name__)


DEVICE_KIND_PHONE:  str = "phone"
DEVICE_KIND_LAPTOP: str = "laptop"
DEVICE_KIND_TABLET: str = "tablet"
DEVICE_KIND_OTHER:  str = "other"

ALL_DEVICE_KINDS: frozenset[str] = frozenset({
    DEVICE_KIND_PHONE,
    DEVICE_KIND_LAPTOP,
    DEVICE_KIND_TABLET,
    DEVICE_KIND_OTHER,
})


_PHONE_FIELDS: frozenset[str] = frozenset({
    "device_name", "brand", "model",
    "imei_1", "imei_2", "serial_number",
    "phone_number", "sim_provider",
    "purchase_date", "receipt_file_id",
    "color", "lock_screen_note",
    "find_my_status",
    "emergency_contact",
    "notes",
})


_LAPTOP_FIELDS: frozenset[str] = frozenset({
    "device_name", "brand", "model",
    "serial_number", "mac_address",
    "operating_system",
    "purchase_date", "receipt_file_id",
    "bitlocker_recovery_reference",
    "notes",
})


_FIELDS_BY_KIND: dict[str, frozenset[str]] = {
    DEVICE_KIND_PHONE:  _PHONE_FIELDS,
    DEVICE_KIND_LAPTOP: _LAPTOP_FIELDS,
    DEVICE_KIND_TABLET: _LAPTOP_FIELDS,
    DEVICE_KIND_OTHER:  _LAPTOP_FIELDS,
}


SENSITIVE_FIELDS: frozenset[str] = frozenset({
    "imei_1", "imei_2", "serial_number",
    "phone_number", "mac_address",
    "bitlocker_recovery_reference",
    "lock_screen_note",
    "notes",
    "emergency_contact",
})


_HEADLINE_FALLBACK_ORDER: tuple[str, ...] = (
    "device_name", "model", "brand",
)


class DeviceSaveInvalidError(ValueError):


    def __init__(self, slug: str):
        super().__init__(slug)
        self.slug = slug


def _mask_tail(value: Optional[str], *, keep: int = 4) -> str:


    if not value:
        return ""
    raw = re.sub(r"[^A-Za-z0-9]", "", str(value))
    if len(raw) <= keep:
                                                                    
        return f"{len(raw)}-char value"
    return f"ending {raw[-keep:]}"


def _mask_mac(value: Optional[str]) -> str:


    if not value:
        return ""
    raw = re.sub(r"[^A-Fa-f0-9]", "", str(value))
    if len(raw) < 4:
        return f"{len(raw)}-char value"
    last4 = raw[-4:].upper()
    return f"ending {last4[:2]}:{last4[2:]}"


def _mask_phone(value: Optional[str]) -> str:

    return _mask_tail(value, keep=4)


def _mask_notes(value: Optional[str]) -> str:


    return "(notes available)" if value else ""


def _mask_field(field: str, value: Any) -> str:


    if field in ("imei_1", "imei_2", "serial_number"):
        return _mask_tail(value, keep=4)
    if field == "phone_number":
        return _mask_phone(value)
    if field == "mac_address":
        return _mask_mac(value)
    if field in ("notes", "lock_screen_note",
                 "emergency_contact",
                 "bitlocker_recovery_reference"):
        return _mask_notes(value)
    return str(value or "")


def _normalise_kind(raw: Any) -> str:
    if not isinstance(raw, str):
        return DEVICE_KIND_OTHER
    k = raw.strip().lower()
    if k in ALL_DEVICE_KINDS:
        return k
                     
    if k in ("phone", "iphone", "android", "smartphone", "mobile"):
        return DEVICE_KIND_PHONE
    if k in ("laptop", "computer", "pc", "macbook", "notebook"):
        return DEVICE_KIND_LAPTOP
    if k in ("tablet", "ipad"):
        return DEVICE_KIND_TABLET
    return DEVICE_KIND_OTHER


def _filter_fields_for_kind(
    fields: dict, *, device_kind: str,
) -> dict:


    allowed = _FIELDS_BY_KIND.get(device_kind, _LAPTOP_FIELDS)
    out: dict = {}
    for k, v in (fields or {}).items():
        if not isinstance(k, str):
            continue
        if k not in allowed:
            continue
        if v is None:
            continue
        if isinstance(v, str):
            v = v.strip()
            if not v:
                continue
        out[k] = v
    return out


def _classify_save_payload(args: Any) -> Optional[str]:


    if not isinstance(args, dict):
        return "missing_args"
    kind_raw = args.get("device_kind") or args.get("kind")
    if kind_raw is None:
        return "missing_device_kind"
    fields = args.get("fields") or {}
    if not isinstance(fields, dict):
        return "fields_not_dict"
                                                                 
                             
    has_signal = any(
        fields.get(k)
        for k in (
            "device_name", "model", "serial_number",
            "imei_1", "imei_2", "phone_number",
        )
    )
    if not has_signal:
        return "empty_fields"
    return None


def _new_device_id() -> str:
    return uuid.uuid4().hex


def save_device_entry(
    *,
    vault_id: str,
    key: bytes,
    args: dict,
    db_executor: Optional[Any] = None,
) -> dict:


    reason = _classify_save_payload(args)
    if reason is not None:
        raise DeviceSaveInvalidError(reason)
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        raise DeviceSaveInvalidError("vault_locked")

    kind = _normalise_kind(args.get("device_kind") or args.get("kind"))
    fields = _filter_fields_for_kind(
        args.get("fields") or {}, device_kind=kind,
    )

    device_id = (
        str(args.get("device_id") or "").strip()
        or _new_device_id()
    )
    fields["device_kind"] = kind                
    fields["device_id"]   = device_id

                       
    try:
        from vault_core import encrypt_message
    except Exception:
        logger.exception("[DEVICE-VAULT] encrypt_message unavailable")
        raise DeviceSaveInvalidError("encrypt_unavailable")
    encrypted_blob = encrypt_message(json.dumps(fields), bytes(key))

                                                                    
    headline = ""
    for k in _HEADLINE_FALLBACK_ORDER:
        v = fields.get(k)
        if isinstance(v, str) and v.strip():
            headline = v.strip()
            break
    if not headline:
        headline = kind                

    payload = {
        "vault_id":       vault_id,
        "device_id":      device_id,
        "device_kind":    kind,
        "headline":       headline,
        "encrypted_data": encrypted_blob,
    }

    if db_executor is not None:
        db_executor("upsert", payload)
    else:
        _default_upsert(payload)

                                                
    logger.info(
        "[DEVICE-VAULT] saved vault=%s device_id=%s kind=%s",
        (vault_id or "")[:8] + "…",
        device_id[:8] + "…",
        kind,
    )

    return {
        "device_id":   device_id,
        "device_kind": kind,
        "preview":     _build_preview(fields),
    }


def _default_upsert(payload: dict) -> None:

    from main import get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'device'
              AND service = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (payload["vault_id"], payload["device_id"]),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """
                UPDATE vault_items
                SET encrypted_data = %s,
                    created_at     = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (payload["encrypted_data"], existing["id"]),
            )
        else:
            cur.execute(
                """
                INSERT INTO vault_items
                  (vault_id, item_type, service, encrypted_data)
                VALUES (%s, 'device', %s, %s)
                """,
                (
                    payload["vault_id"],
                    payload["device_id"],
                    payload["encrypted_data"],
                ),
            )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_devices(
    *,
    vault_id: str,
    key: bytes,
    db_reader: Optional[Any] = None,
) -> dict:

    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return {"devices": [], "count": 0, "error": "vault_locked"}

    rows = (
        db_reader(vault_id) if db_reader is not None
        else _default_read_rows(vault_id)
    )

    previews: list[dict] = []
    for row in rows or []:
        encrypted = row.get("encrypted_data") or ""
        if not encrypted:
            continue
        try:
            from vault_core import decrypt_message
            plain = decrypt_message(encrypted, bytes(key))
            fields = json.loads(plain)
            if not isinstance(fields, dict):
                continue
        except Exception:
                                                                   
                                                            
            continue
        kind = _normalise_kind(fields.get("device_kind"))
        device_id = str(
            fields.get("device_id") or row.get("service") or ""
        )
        previews.append({
            "device_id":   device_id,
            "device_kind": kind,
            "preview":     _build_preview(fields),
        })

    logger.info(
        "[DEVICE-VAULT] listed vault=%s count=%d",
        (vault_id or "")[:8] + "…",
        len(previews),
    )
    return {"devices": previews, "count": len(previews)}


def _default_read_rows(vault_id: str) -> list[dict]:
    from main import get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, service, encrypted_data, created_at
            FROM vault_items
            WHERE vault_id = %s
              AND item_type = 'device'
            ORDER BY created_at DESC
            """,
            (vault_id,),
        )
        return [dict(r) for r in cur.fetchall() or []]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_device_entry(
    *,
    vault_id: str,
    key: bytes,
    device_id: str,
    db_reader: Optional[Any] = None,
) -> Optional[dict]:


    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return None
    if not device_id:
        return None
    rows = (
        db_reader(vault_id) if db_reader is not None
        else _default_read_rows(vault_id)
    )
    for row in rows or []:
                                                                    
                                 
        if str(row.get("service") or "") == device_id:
            encrypted = row.get("encrypted_data") or ""
            try:
                from vault_core import decrypt_message
                plain = decrypt_message(encrypted, bytes(key))
                fields = json.loads(plain)
                if isinstance(fields, dict):
                    return fields
            except Exception:
                return None
    return None


def link_receipt_to_device(
    *,
    vault_id: str,
    key: bytes,
    device_id: str,
    file_id: str,
    db_executor: Optional[Any] = None,
    db_reader: Optional[Any] = None,
) -> dict:

    record = get_device_entry(
        vault_id=vault_id, key=key, device_id=device_id,
        db_reader=db_reader,
    )
    if record is None:
        return {"error": "device_not_found"}
    record["receipt_file_id"] = file_id
                                     
    return save_device_entry(
        vault_id=vault_id, key=key,
        args={
            "device_kind": record.get("device_kind"),
            "device_id":   device_id,
            "fields":      record,
        },
        db_executor=db_executor,
    )


def _build_preview(fields: dict) -> dict:


    kind = _normalise_kind(fields.get("device_kind"))
    out: dict = {
        "device_kind":  kind,
        "device_name":  str(fields.get("device_name") or "").strip(),
        "brand":        str(fields.get("brand") or "").strip(),
        "model":        str(fields.get("model") or "").strip(),
        "purchase_date": str(fields.get("purchase_date") or "").strip(),
        "has_receipt":  bool(fields.get("receipt_file_id")),
    }
    if kind == DEVICE_KIND_PHONE:
        out["imei_1_mask"]    = _mask_field("imei_1", fields.get("imei_1"))
        out["imei_2_mask"]    = _mask_field("imei_2", fields.get("imei_2"))
        out["serial_mask"]    = _mask_field(
            "serial_number", fields.get("serial_number"),
        )
        out["phone_mask"]     = _mask_field(
            "phone_number", fields.get("phone_number"),
        )
        out["sim_provider"]   = str(
            fields.get("sim_provider") or "",
        ).strip()
        out["color"]          = str(fields.get("color") or "").strip()
        out["find_my_status"] = str(
            fields.get("find_my_status") or "",
        ).strip()
        out["has_lock_screen_note"] = bool(
            fields.get("lock_screen_note"),
        )
        out["has_emergency_contact"] = bool(
            fields.get("emergency_contact"),
        )
    else:
        out["serial_mask"] = _mask_field(
            "serial_number", fields.get("serial_number"),
        )
        out["mac_mask"]    = _mask_field(
            "mac_address", fields.get("mac_address"),
        )
        out["operating_system"] = str(
            fields.get("operating_system") or "",
        ).strip()
        out["has_recovery_reference"] = bool(
            fields.get("bitlocker_recovery_reference"),
        )
    out["has_notes"] = bool(fields.get("notes"))
    return out


__all__ = [
    "DEVICE_KIND_PHONE", "DEVICE_KIND_LAPTOP",
    "DEVICE_KIND_TABLET", "DEVICE_KIND_OTHER",
    "ALL_DEVICE_KINDS",
    "SENSITIVE_FIELDS",
    "DeviceSaveInvalidError",
    "save_device_entry",
    "list_devices",
    "get_device_entry",
    "link_receipt_to_device",
    "_mask_tail",
    "_mask_mac",
    "_mask_phone",
    "_build_preview",
    "_classify_save_payload",
    "_normalise_kind",
    "_filter_fields_for_kind",
]
