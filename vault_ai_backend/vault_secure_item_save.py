

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

from vault_saved_item_chat_intent import (
    CATEGORY_FILTER_ALL,
    INTENT_CONFIRM_SAVE,
    INTENT_NONE,
    INTENT_RETRIEVE_SECURE_ITEM,
    INTENT_SAVE_SECURE_ITEM,
    SecureItemIntent,
    classify_secure_item_intent,
    looks_like_secure_item_title_update,
    normalize_secure_item_title,
)
from vault_saved_item_taxonomy import (
    ALL_CATEGORIES,
    CATEGORY_LOGIN,
    CATEGORY_OTHER,
    CRYPTO_CATEGORIES,
    CRYPTO_WARN_CATEGORIES,
    LOGIN_LIKE_CATEGORIES,
    category_icon,
    category_label,
    classify_secure_item_payload,
    mask_mac,
    mask_tail,
    mask_wallet_address,
    masked_preview,
    noun_for_category,
    revealed_preview,
    saved_confirmation_message,
)
from vault_secure_item_card_envelope import (
    build_secure_item_card,
    build_secure_item_results_envelope,
)
from vault_secure_item_draft import (
    SecureItemDraft,
    consume_secure_item_draft,
    get_latest_secure_item_draft,
    store_secure_item_draft,
    update_pending_secure_item_draft_title,
)
from vault_secure_item_delete_confirmation import (
    BAND_DELETE_CANCELLED,
    BAND_DELETE_CONFIRMATION_PENDING,
    BAND_DELETED,
    BAND_NO_PENDING_DELETE,
    SecureItemDeleteIntent,
    cancelled_reply as _delete_cancelled_reply,
    confirmation_question as _delete_confirmation_question,
    consume_pending_delete_intent,
    deleted_reply as _delete_done_reply,
    get_pending_delete_intent,
    is_cancel_delete_phrase,
    is_confirm_delete_phrase,
    is_delete_intent_sentinel,
    parse_delete_intent_sentinel,
    store_delete_intent,
)
from vault_secure_item_results_followup import (
    FOLLOWUP_CLARIFY,
    FOLLOWUP_DELETE_ONE,
    FOLLOWUP_NONE,
    FOLLOWUP_REVEAL_ONE,
    classify_results_followup,
    get_results_context,
    store_results_context,
)


logger = logging.getLogger(__name__)


BAND_SAVED:               str = "saved"
BAND_DRAFTED:             str = "drafted"
BAND_TITLE_UPDATED:       str = "title_updated"
BAND_NEEDS_CLARIFICATION: str = "needs_clarification"
BAND_VALIDATION_FAILED:   str = "validation_failed"
BAND_VAULT_LOCKED:        str = "vault_locked"
BAND_DB_ERROR:            str = "db_error"
BAND_NO_INTENT:           str = "no_intent"
BAND_NO_DRAFT:            str = "no_draft"
                          
BAND_TIER_REQUIRED:       str = "tier_required"
BAND_WARN_DRAFTED:        str = "warn_drafted"
                                                            
                                                            
BAND_FOLLOWUP_CLARIFY:    str = "followup_clarify"
                                                               
                                                              
BAND_DELETE_PROMPT:       str = "delete_prompt"


TIER_FREE:     str = "free"
TIER_BASIC:    str = "basic"
TIER_UPGRADED: str = "upgraded"


ALL_TIERS: frozenset[str] = frozenset({
    TIER_FREE, TIER_BASIC, TIER_UPGRADED,
})


_TIER_REQUIRED_MESSAGE: str = (
    "You can't save this to Crypto Vault on your current "
    "plan. Upgrade your account to unlock Crypto Vault — a "
    "real, non-custodial wallet with receive, send, and "
    "balance tracking, where your keys stay on your device."
)


_CRYPTO_WARN_TEMPLATE: str = (
    "⚠️ This is extremely sensitive. Anyone with this phrase or "
    "key can control the wallet. Store it only if you understand "
    "the risk. I can save this as {title}. Say 'save it now' to "
    "store it in your vault, or 'cancel' to drop the draft."
)


def _is_upgraded_tier(tier: Optional[str]) -> bool:


    if not isinstance(tier, str):
        return False
    return tier.strip().lower() == TIER_UPGRADED


_CLARIFY_QUESTIONS: dict[str, str] = {
    "missing_title": (
        "Which device should I save this under — phone, laptop, "
        "or something else?"
    ),
    "missing_value": (
        "What value should I save? (e.g. the IMEI itself.)"
    ),
    "missing_category": (
        "What kind of record is this — a login, a device, a "
        "recovery code, or a note?"
    ),
}


def _short_value_preview(field: str, value: Any) -> str:


    if field == "mac_address":
        return mask_mac(value)
    return mask_tail(value)


_SAVED_TO_VAULT_MESSAGE: str = "Saved to your vault 🔐"


def _render_draft_message(*, title: str) -> str:


    safe_title = (title or "").strip() or "a secure item"
    return (
        f"Sure — I can save this as {safe_title}. "
        f"Say 'save it' when you want me to store it in your vault."
    )


def build_save_args(
    *, intent: SecureItemIntent,
) -> Optional[dict]:


    if intent is None or intent.intent != INTENT_SAVE_SECURE_ITEM:
        return None
    category = (
        intent.category if intent.category in ALL_CATEGORIES
        else CATEGORY_OTHER
    )
    title = (intent.title or "").strip()
    if not title:
                                                               
                                                                
        title = noun_for_category(category).split()[0]
    fields: dict = {}
    if intent.field and intent.value is not None:
        fields[intent.field] = str(intent.value)
                                                                
                                                                
    if intent.network:
        fields["network"] = str(intent.network)
    return {
        "secret_type": category,
        "service":     title,
        "fields":      fields,
    }


def _validate_and_build_payload(
    *, intent: SecureItemIntent,
) -> tuple[Optional[dict], Optional[dict]]:


    args = build_save_args(intent=intent) or {}
    validation_slug = classify_secure_item_payload(args)
    if validation_slug is None:
        return args, None
    if validation_slug == "missing_title":
        return None, {
            "band":    BAND_NEEDS_CLARIFICATION,
            "slug":    validation_slug,
            "message": _CLARIFY_QUESTIONS["missing_title"],
        }
    if validation_slug == "missing_kind":
        return None, {
            "band":    BAND_NEEDS_CLARIFICATION,
            "slug":    validation_slug,
            "message": _CLARIFY_QUESTIONS["missing_category"],
        }
    if validation_slug == "empty_fields":
        return None, {
            "band":    BAND_NEEDS_CLARIFICATION,
            "slug":    validation_slug,
            "message": _CLARIFY_QUESTIONS["missing_value"],
        }
    return None, {
        "band":    BAND_VALIDATION_FAILED,
        "slug":    validation_slug,
        "message": "I couldn't save that. Try again with the value.",
    }


def _encrypt_and_write(
    *,
    vault_id: str,
    key: bytes,
    args: dict,
    field: Optional[str],
    value: Optional[Any],
    notes: Optional[str],
    db_executor: Optional[Any],
) -> dict:


    try:
        from vault_core import encrypt_message
    except Exception:
        logger.exception(
            "[SECURE-ITEM] encrypt_message unavailable",
        )
        return {
            "band":    BAND_DB_ERROR,
            "message": "Couldn't reach the vault right now. Try again.",
        }
    record = {
        "category": args["secret_type"],
        "title":    args["service"],
        "fields":   args["fields"],
        "notes":    notes if notes is not None else args.get("notes"),
        "item_id":  uuid.uuid4().hex,
    }
                                                             
                                                   
    try:
        from crypto_schemas import (
            annotate_crypto_record,
            requires_warning_confirmation_for_category,
        )
        warning_confirmed = (
            True
            if requires_warning_confirmation_for_category(args["secret_type"])
            else None
        )
        annotate_crypto_record(
            record,
            category=args["secret_type"],
            warning_confirmed=warning_confirmed,
        )
    except Exception:
                                                               
                                                              
        logger.exception(
            "[SECURE-ITEM] crypto schema annotation skipped "
            "vault=%s category=%s",
            (vault_id or "")[:8] + "…", args["secret_type"],
        )
    try:
        encrypted_blob = encrypt_message(
            json.dumps(record), bytes(key),
        )
    except Exception:
        logger.exception(
            "[SECURE-ITEM] encrypt failed vault=%s category=%s",
            (vault_id or "")[:8] + "…", args["secret_type"],
        )
        return {
            "band":    BAND_DB_ERROR,
            "message": "Couldn't save this securely. Try again.",
        }
    payload = {
        "vault_id":       vault_id,
        "item_type":      args["secret_type"],
        "service":        args["service"],
        "encrypted_data": encrypted_blob,
    }
    try:
        if db_executor is not None:
            db_executor("upsert", payload)
        else:
            _default_upsert(payload)
    except Exception:
        logger.exception(
            "[SECURE-ITEM] db write failed vault=%s",
            (vault_id or "")[:8] + "…",
        )
        return {
            "band":    BAND_DB_ERROR,
            "message": "Couldn't save this securely. Try again.",
        }
                                                                   
                                                              
    logger.info(
        "[SECURE-ITEM] saved vault=%s category=%s field=%s",
        (vault_id or "")[:8] + "…",
        args["secret_type"],
        field or "(none)",
    )
    return {
        "band":     BAND_SAVED,
        "message":  _SAVED_TO_VAULT_MESSAGE,
        "preview":  masked_preview(
            category=args["secret_type"],
            title=args["service"],
            fields=args["fields"],
            notes=record.get("notes"),
        ),
        "category": args["secret_type"],
        "field":    field,
        "item_id":  record["item_id"],
    }


def save_secure_item_from_intent(
    *,
    vault_id: str,
    key: bytes,
    intent: SecureItemIntent,
    db_executor: Optional[Any] = None,
) -> dict:


    if intent.intent != INTENT_SAVE_SECURE_ITEM:
        return {
            "band":      BAND_NO_INTENT,
            "message":   "",
        }
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return {
            "band":      BAND_VAULT_LOCKED,
            "message":   "Unlock your vault first, then I can save this.",
        }
    args, error = _validate_and_build_payload(intent=intent)
    if error is not None:
        return error
    assert args is not None                            
    result = _encrypt_and_write(
        vault_id=vault_id, key=key,
        args=args,
        field=intent.field, value=intent.value, notes=None,
        db_executor=db_executor,
    )
    if result.get("band") != BAND_SAVED:
        return result
                                                                
                                      
    confirmation = saved_confirmation_message(
        category=args["secret_type"], title=args["service"],
    )
    tail_hint = ""
    if intent.field and intent.value:
        tail = _short_value_preview(intent.field, intent.value)
        if tail:
            field_noun = (
                "IMEI" if intent.field in ("imei_1", "imei_2")
                else "serial" if intent.field == "serial_number"
                else "MAC" if intent.field == "mac_address"
                else "phone" if intent.field == "phone_number"
                else "recovery code"
                if intent.field in ("recovery_code", "backup_codes")
                else "value"
            )
            tail_hint = f" {field_noun} {tail}."
    result["message"] = confirmation + tail_hint
    return result


def save_secure_item_from_message(
    *,
    vault_id: str,
    key: bytes,
    user_message: str,
    db_executor: Optional[Any] = None,
) -> dict:


    intent = classify_secure_item_intent(user_message)
    if intent.intent != INTENT_SAVE_SECURE_ITEM:
        return {
            "band":    BAND_NO_INTENT,
            "message": "",
        }
    return save_secure_item_from_intent(
        vault_id=vault_id, key=key, intent=intent,
        db_executor=db_executor,
    )


def propose_secure_item_draft_from_intent(
    *,
    vault_id: str,
    key: bytes,
    intent: SecureItemIntent,
    user_tier: Optional[str] = None,
) -> dict:


    if intent.intent != INTENT_SAVE_SECURE_ITEM:
        return {"band": BAND_NO_INTENT, "message": ""}
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return {
            "band":    BAND_VAULT_LOCKED,
            "message": "Unlock your vault first, then I can save this.",
        }
    args, error = _validate_and_build_payload(intent=intent)
    if error is not None:
        return error
    assert args is not None
    category = args["secret_type"]
                                                             
                                                              
    if category in CRYPTO_CATEGORIES and not _is_upgraded_tier(user_tier):
        logger.info(
            "[SECURE-ITEM] tier_required vault=%s category=%s",
            (vault_id or "")[:8] + "…", category,
        )
        return {
            "band":    BAND_TIER_REQUIRED,
            "message": _TIER_REQUIRED_MESSAGE,
            "category": category,
        }
    draft = store_secure_item_draft(
        vault_id=vault_id,
        category=category,
        title=args["service"],
        field=intent.field,
        value=intent.value,
        notes=None,
        network=intent.network,
    )
                                                         
                                                                
    if category in CRYPTO_WARN_CATEGORIES:
        logger.info(
            "[SECURE-ITEM] warn_drafted vault=%s category=%s field=%s",
            (vault_id or "")[:8] + "…",
            category,
            intent.field or "(none)",
        )
        return {
            "band":     BAND_WARN_DRAFTED,
            "message":  _CRYPTO_WARN_TEMPLATE.format(
                title=args["service"],
            ),
            "preview":  masked_preview(
                category=category,
                title=args["service"],
                fields=args["fields"],
                notes=None,
            ),
            "category": category,
            "field":    intent.field,
            "draft_id": draft.draft_id,
        }
    logger.info(
        "[SECURE-ITEM] drafted vault=%s category=%s field=%s",
        (vault_id or "")[:8] + "…",
        category,
        intent.field or "(none)",
    )
    return {
        "band":     BAND_DRAFTED,
        "message":  _render_draft_message(title=args["service"]),
        "preview":  masked_preview(
            category=category,
            title=args["service"],
            fields=args["fields"],
            notes=None,
        ),
        "category": category,
        "field":    intent.field,
        "draft_id": draft.draft_id,
    }


def propose_secure_item_draft_from_message(
    *,
    vault_id: str,
    key: bytes,
    user_message: str,
    user_tier: Optional[str] = None,
) -> dict:


    intent = classify_secure_item_intent(user_message)
    if intent.intent != INTENT_SAVE_SECURE_ITEM:
        return {"band": BAND_NO_INTENT, "message": ""}
    return propose_secure_item_draft_from_intent(
        vault_id=vault_id, key=key, intent=intent,
        user_tier=user_tier,
    )


def update_pending_secure_item_draft_title_from_message(
    *,
    vault_id: str,
    user_message: str,
) -> dict:


    pending = get_latest_secure_item_draft(vault_id=vault_id)
    if pending is None:
        return {"band": BAND_NO_DRAFT, "message": ""}
    if not looks_like_secure_item_title_update(user_message):
        return {"band": BAND_NO_INTENT, "message": ""}
    new_title = normalize_secure_item_title(user_message)
    if not new_title:
        return {"band": BAND_NO_INTENT, "message": ""}
    updated = update_pending_secure_item_draft_title(
        vault_id=vault_id, title=new_title,
    )
    if updated is None:
        return {"band": BAND_NO_DRAFT, "message": ""}
    logger.info(
        "[SECURE-ITEM] title_updated vault=%s category=%s",
        (vault_id or "")[:8] + "…",
        updated.category,
    )
    return {
        "band":     BAND_TITLE_UPDATED,
        "message":  (
            f"Got it — I'll label it as {new_title}. "
            f"Say 'save it' when you want me to store it in your vault."
        ),
        "category": updated.category,
        "field":    updated.field,
        "draft_id": updated.draft_id,
        "title":    new_title,
    }


def confirm_pending_secure_item_save(
    *,
    vault_id: str,
    key: bytes,
    db_executor: Optional[Any] = None,
) -> dict:


    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return {
            "band":    BAND_VAULT_LOCKED,
            "message": "Unlock your vault first, then I can save this.",
        }
    draft: Optional[SecureItemDraft] = consume_secure_item_draft(
        vault_id=vault_id,
    )
    if draft is None:
        return {
            "band":    BAND_NO_DRAFT,
            "message": (
                "I don't have a pending save right now. Tell me "
                "what you'd like to save first."
            ),
        }
    fields: dict = {}
    if draft.field and draft.value is not None:
        fields[draft.field] = str(draft.value)
                                                          
                                                            
    if draft.network:
        fields["network"] = str(draft.network)
    args = {
        "secret_type": draft.category,
        "service":     draft.title,
        "fields":      fields,
    }
    return _encrypt_and_write(
        vault_id=vault_id, key=key,
        args=args,
        field=draft.field, value=draft.value, notes=draft.notes,
        db_executor=db_executor,
    )


def _default_upsert(payload: dict) -> None:


    from main import bump_vault_total_bytes, get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, encrypted_data FROM vault_items
            WHERE vault_id = %s
              AND item_type = %s
              AND LOWER(service) = LOWER(%s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (
                payload["vault_id"],
                payload["item_type"],
                payload["service"],
            ),
        )
        existing = cur.fetchone()
        new_blob_size = _blob_size(payload.get("encrypted_data"))
        old_blob_size = (
            _blob_size(existing["encrypted_data"]) if existing else 0
        )
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
                VALUES (%s, %s, %s, %s)
                """,
                (
                    payload["vault_id"],
                    payload["item_type"],
                    payload["service"],
                    payload["encrypted_data"],
                ),
            )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

                                                               
    delta = int(new_blob_size) - int(old_blob_size)
    if delta != 0:
        try:
            bump_vault_total_bytes(payload["vault_id"], delta)
        except Exception:
            logger.warning(
                "[SECURE-ITEM] storage_bump_failed vault=%s delta=%d "
                "— nightly reconciliation will catch this",
                (payload.get("vault_id") or "")[:8] + "…", delta,
            )


def _blob_size(blob: Any) -> int:


    if blob is None:
        return 0
    if isinstance(blob, (bytes, bytearray, memoryview)):
        return len(bytes(blob))
    if isinstance(blob, str):
        return len(blob.encode("utf-8"))
    return 0


BAND_RETRIEVED:    str = "retrieved"
BAND_NOT_FOUND:    str = "not_found"


def retrieve_secure_item_from_intent(
    *,
    vault_id: str,
    key: bytes,
    intent: SecureItemIntent,
    db_reader: Optional[Any] = None,
) -> dict:


    if intent.intent != INTENT_RETRIEVE_SECURE_ITEM:
        return {"band": BAND_NO_INTENT, "message": ""}
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return {
            "band": BAND_VAULT_LOCKED,
            "message": "Unlock your vault first, then I can look this up.",
        }
    category = intent.category or CATEGORY_OTHER
    title    = (intent.title or "").strip()
    rows = (
        db_reader(vault_id, category) if db_reader is not None
        else _default_read_rows(vault_id, category)
    )
    try:
        from vault_core import decrypt_message
    except Exception:
        logger.exception(
            "[SECURE-ITEM] decrypt_message unavailable",
        )
        return {"band": BAND_DB_ERROR, "message": "Vault unavailable."}

                                                       
    candidates: list[tuple[dict, dict]] = []
    for r in rows or []:
        encrypted = r.get("encrypted_data")
        if not encrypted:
            continue
        try:
            plain = decrypt_message(encrypted, bytes(key))
            record = json.loads(plain)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
                                                           
                                                             
        _, _, _cat_override_t, _title_override_t = (
            _normalise_record_to_fields(record)
        )
        effective_title = str(
            _title_override_t or r.get("service") or "",
        )
        if title and effective_title.lower() != title.lower():
            continue
        candidates.append((record, r))
    if not candidates:
        return {
            "band":    BAND_NOT_FOUND,
            "message": (
                "I don't have that on file yet. Save it first with "
                "something like \"save my phone IMEI 123\"."
            ),
        }
    record, r = candidates[0]
    fields, notes, _cat_override, _title_override = (
        _normalise_record_to_fields(record)
    )
    effective_title = str(
        _title_override or r.get("service") or "",
    )
    effective_category = (
        _cat_override or r.get("item_type") or category
    )
    preview = masked_preview(
        category=effective_category,
        title=effective_title,
        fields=fields,
        notes=notes,
    )
    return {
        "band":     BAND_RETRIEVED,
        "message":  preview.get("title") or "Saved item",
        "preview":  preview,
        "category": effective_category,
    }


def _default_read_rows(
    vault_id: str, category: str,
) -> list[dict]:
    from main import get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, item_type, service, encrypted_data, created_at
            FROM vault_items
            WHERE vault_id = %s AND item_type = %s
            ORDER BY created_at DESC
            """,
            (vault_id, category),
        )
        return [dict(r) for r in cur.fetchall() or []]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _default_read_all_secure_items(vault_id: str) -> list[dict]:


    from main import get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT id, item_type, service, encrypted_data, created_at
            FROM vault_items
            WHERE vault_id = %s
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


from vault_saved_item_taxonomy import (
    CATEGORY_DEVICE,
    CATEGORY_DEVICE_INFO,
    CATEGORY_IMEI as _T_CATEGORY_IMEI,
    CATEGORY_SERIAL_NUMBER as _T_CATEGORY_SERIAL_NUMBER,
    CATEGORY_RECOVERY_CODE as _T_CATEGORY_RECOVERY_CODE,
    CATEGORY_BACKUP_CODE as _T_CATEGORY_BACKUP_CODE,
    CATEGORY_PRIVATE_NOTE as _T_CATEGORY_PRIVATE_NOTE,
    CATEGORY_ACCOUNT_NOTE as _T_CATEGORY_ACCOUNT_NOTE,
    CATEGORY_DOCUMENT_NOTE as _T_CATEGORY_DOCUMENT_NOTE,
    CATEGORY_CREDENTIAL as _T_CATEGORY_CREDENTIAL,
    CATEGORY_OTHER_SECRET as _T_CATEGORY_OTHER_SECRET,
)


_RETRIEVE_CATEGORY_FALLBACKS: dict[str, tuple[str, ...]] = {
    CATEGORY_DEVICE: (
        CATEGORY_DEVICE, CATEGORY_DEVICE_INFO,
        _T_CATEGORY_IMEI, _T_CATEGORY_SERIAL_NUMBER,
    ),
    CATEGORY_DEVICE_INFO: (
        CATEGORY_DEVICE_INFO, CATEGORY_DEVICE,
        _T_CATEGORY_IMEI, _T_CATEGORY_SERIAL_NUMBER,
    ),
    _T_CATEGORY_IMEI: (
        _T_CATEGORY_IMEI, CATEGORY_DEVICE, CATEGORY_DEVICE_INFO,
    ),
    _T_CATEGORY_SERIAL_NUMBER: (
        _T_CATEGORY_SERIAL_NUMBER,
        CATEGORY_DEVICE, CATEGORY_DEVICE_INFO,
    ),
    _T_CATEGORY_RECOVERY_CODE: (
        _T_CATEGORY_RECOVERY_CODE, _T_CATEGORY_BACKUP_CODE,
    ),
    _T_CATEGORY_BACKUP_CODE: (
        _T_CATEGORY_BACKUP_CODE, _T_CATEGORY_RECOVERY_CODE,
    ),
    _T_CATEGORY_PRIVATE_NOTE: (
        _T_CATEGORY_PRIVATE_NOTE, _T_CATEGORY_ACCOUNT_NOTE,
        _T_CATEGORY_DOCUMENT_NOTE,
    ),
    _T_CATEGORY_ACCOUNT_NOTE: (
        _T_CATEGORY_ACCOUNT_NOTE, _T_CATEGORY_PRIVATE_NOTE,
        _T_CATEGORY_DOCUMENT_NOTE,
    ),
    CATEGORY_LOGIN: (
        CATEGORY_LOGIN, _T_CATEGORY_CREDENTIAL,
    ),
    _T_CATEGORY_CREDENTIAL: (
        _T_CATEGORY_CREDENTIAL, CATEGORY_LOGIN,
    ),
    CATEGORY_OTHER: (
        CATEGORY_OTHER, _T_CATEGORY_OTHER_SECRET,
    ),
    _T_CATEGORY_OTHER_SECRET: (
        _T_CATEGORY_OTHER_SECRET, CATEGORY_OTHER,
    ),
}


def retrieve_secure_items_from_intent(
    *,
    vault_id: str,
    key: bytes,
    intent: SecureItemIntent,
    db_reader: Optional[Any] = None,
    db_reader_all: Optional[Any] = None,
    reveal: bool = False,
) -> dict:


    if intent.intent != INTENT_RETRIEVE_SECURE_ITEM:
        return {"band": BAND_NO_INTENT, "message": ""}
    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return {
            "band":    BAND_VAULT_LOCKED,
            "message": "Unlock your vault first, then I can look this up.",
        }
    category = (intent.category or CATEGORY_OTHER).strip().lower()
    title    = (intent.title or "").strip().lower()
    network  = (intent.network or "").strip().lower()

                                                            
    if category == CATEGORY_FILTER_ALL:
        rows = (
            db_reader_all(vault_id) if db_reader_all is not None
            else _default_read_all_secure_items(vault_id)
        )
    else:
        candidate_categories = _RETRIEVE_CATEGORY_FALLBACKS.get(
            category, (category,),
        )
        rows = []
        seen_ids: set = set()
        reader = (
            db_reader if db_reader is not None else _default_read_rows
        )
        for cat in candidate_categories:
            for r in reader(vault_id, cat) or []:
                rid = r.get("id")
                if rid is not None and rid in seen_ids:
                    continue
                if rid is not None:
                    seen_ids.add(rid)
                rows.append(r)

    try:
        from vault_core import decrypt_message
    except Exception:
        logger.exception(
            "[SECURE-ITEM] decrypt_message unavailable",
        )
        return {"band": BAND_DB_ERROR, "message": "Vault unavailable."}

                                                              
    scored: list[tuple[int, dict, dict]] = []
    for r in rows or []:
        encrypted = r.get("encrypted_data")
        if not encrypted:
            continue
        try:
            plain = decrypt_message(encrypted, bytes(key))
            record = json.loads(plain)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
                                                              
                                                               
        fields, notes, _cat_override, _title_override = (
            _normalise_record_to_fields(record)
        )
        row_category = (
            str(_cat_override or r.get("item_type") or category).strip().lower()
            or CATEGORY_OTHER
        )
        row_title = str(_title_override or r.get("service") or "")
                                                                 
                                                              
        if network:
            row_network = str(fields.get("network") or "").strip().lower()
            if network not in row_network:
                continue
        rank = _rank_title_match(title, row_title)
        if title and rank == _RANK_NO_MATCH:
            continue
        scored.append((rank, r, record))

                                                              
    if title and scored:
        best_rank = max(s[0] for s in scored)
        scored = [s for s in scored if s[0] == best_rank]

                                                             
    effective_reveal = bool(reveal)
    if (
        not effective_reveal
        and title
        and len(scored) == 1
        and scored[0][0] >= _RANK_STRONG_SUBSTRING
    ):
        effective_reveal = True

    cards: list[dict] = []
    for _rank, r, record in scored:
                                                                  
        fields, notes, _cat_override, _title_override = (
            _normalise_record_to_fields(record)
        )
        row_category = (
            str(_cat_override or r.get("item_type") or category).strip().lower()
            or CATEGORY_OTHER
        )
        row_title = str(_title_override or r.get("service") or "")
        preview = (
            revealed_preview(
                category=row_category, title=row_title,
                fields=fields, notes=notes,
            )
            if effective_reveal
            else masked_preview(
                category=row_category, title=row_title,
                fields=fields, notes=notes,
            )
        )
        cards.append(build_secure_item_card(
            item_id=str(record.get("item_id") or r.get("id") or ""),
            category=row_category,
            title=row_title,
            preview=preview,
            created_at=_to_epoch(r.get("created_at")),
            reveal=effective_reveal,
        ))

    envelope = build_secure_item_results_envelope(
        items=cards,
        category_filter=(
            "" if category == CATEGORY_FILTER_ALL else category
        ),
        reveal=effective_reveal,
                                                              
                                                                  
        receive_intent=bool(getattr(intent, "receive_intent", False)),
    )
    if not cards:
        return {
            "band":     BAND_NOT_FOUND,
            "message":  envelope,
            "envelope": envelope,
            "category": category,
            "count":    0,
        }
    return {
        "band":     BAND_RETRIEVED,
        "message":  envelope,
        "envelope": envelope,
        "category": category,
        "count":    len(cards),
    }


_SCHEMA_B_MARKERS: frozenset[str] = frozenset({
    "category", "title", "fields", "item_id",
})


def _normalise_record_to_fields(
    record: dict,
) -> tuple[dict, Any, Optional[str], Optional[str]]:


    if not isinstance(record, dict):
        return {}, None, None, None
    if any(k in record for k in _SCHEMA_B_MARKERS):
                                                               
                                                                
        fields = record.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        return (
            fields,
            record.get("notes"),
            record.get("category") if isinstance(record.get("category"), str) else None,
            record.get("title")    if isinstance(record.get("title"),    str) else None,
        )
                                                              
                                                                
    return record, None, None, None


_RANK_NO_MATCH:         int = 0
_RANK_WEAK_SUBSTRING:   int = 1                                 
                                                                      
_RANK_STRONG_SUBSTRING: int = 2
_RANK_NORMALISED:       int = 3
_RANK_EXACT:            int = 4


_TITLE_FILLER_WORDS: frozenset[str] = frozenset({
    "my", "the", "a", "an", "saved", "stored",
    "login", "logins", "credential", "credentials",
    "account", "record", "records", "entry", "entries",
    "secret", "secrets", "item", "items",
})


def _normalise_title_query(value: str) -> str:


    if not isinstance(value, str):
        return ""
    tokens = [t for t in value.lower().replace("\t", " ").split(" ") if t]
    kept: list[str] = []
    for tok in tokens:
        bare = tok.strip(".,;:!?\"'`()[]{}")
        if not bare:
            continue
        if bare in _TITLE_FILLER_WORDS:
            continue
        kept.append(bare)
    return " ".join(kept)


def _rank_title_match(query: str, row_title: str) -> int:


    if not query:
                                                                
                                                               
        return _RANK_STRONG_SUBSTRING
    q = query.strip().lower()
    t = (row_title or "").strip().lower()
    if not t:
        return _RANK_NO_MATCH
    if q == t:
        return _RANK_EXACT
    q_norm = _normalise_title_query(q)
    t_norm = _normalise_title_query(t)
    if q_norm and t_norm and q_norm == t_norm:
        return _RANK_NORMALISED
                                                        
                                                            
    if q_norm and t_norm:
        if q_norm in t_norm or t_norm in q_norm:
            return _RANK_STRONG_SUBSTRING
    if q in t or t in q:
        return _RANK_STRONG_SUBSTRING
    return _RANK_NO_MATCH


def _to_epoch(value: Any) -> Optional[float]:


    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value.timestamp())
    except Exception:
        return None


def route_secure_item_message(
    *,
    vault_id: str,
    key: bytes,
    user_message: str,
    db_executor: Optional[Any] = None,
    db_reader: Optional[Any] = None,
    db_reader_all: Optional[Any] = None,
    user_tier: Optional[str] = None,
) -> dict:


    if not isinstance(user_message, str) or not user_message.strip():
        return {"band": BAND_NO_INTENT, "message": ""}

                                                                        
    sentinel = parse_delete_intent_sentinel(user_message)
    if sentinel is not None:
        item_type, service = sentinel
        return _stamp_delete_confirmation(
            vault_id=vault_id, service=service, item_type=item_type,
            item_id=None,
        )

    pending_delete = get_pending_delete_intent(vault_id=vault_id)
    if pending_delete is not None:
        if is_confirm_delete_phrase(user_message):
            return _execute_pending_delete(
                vault_id=vault_id, key=key,
                db_executor=db_executor,
            )
        if is_cancel_delete_phrase(user_message):
            return _cancel_pending_delete(vault_id=vault_id)

    # Contextual bare confirmations: destructive intent has first refusal,
    # and a real secure-item draft must exist. This preserves wallet/login
    # draft UX without reintroducing the global bare-"yes" hijack.
    if (
        pending_delete is None
        and get_latest_secure_item_draft(vault_id=vault_id) is not None
        and re.fullmatch(
            r"\s*(?:yes|go\s+ahead|confirm)\s*[.!?]*\s*",
            user_message,
            re.IGNORECASE,
        )
    ):
        return confirm_pending_secure_item_save(
            vault_id=vault_id, key=key, db_executor=db_executor,
        )
                                                            
                                                           
    intent = classify_secure_item_intent(user_message)

                              
    if intent.intent == INTENT_CONFIRM_SAVE:
        return confirm_pending_secure_item_save(
            vault_id=vault_id, key=key, db_executor=db_executor,
        )

                                                               
    if intent.intent == INTENT_SAVE_SECURE_ITEM:
        return propose_secure_item_draft_from_intent(
            vault_id=vault_id, key=key, intent=intent,
            user_tier=user_tier,
        )

                                                               
    title_update_result = update_pending_secure_item_draft_title_from_message(
        vault_id=vault_id, user_message=user_message,
    )
    if title_update_result.get("band") == BAND_TITLE_UPDATED:
        return title_update_result

                                                              
    results_ctx = get_results_context(vault_id=vault_id)
    if results_ctx is not None:
        resolution = classify_results_followup(
            user_message=user_message, context=results_ctx,
        )
        if resolution.band == FOLLOWUP_REVEAL_ONE and resolution.cards:
            return _resolve_followup_reveal(
                vault_id=vault_id, key=key,
                card=resolution.cards[0],
                reveal=resolution.reveal,
                db_reader=db_reader,
                db_reader_all=db_reader_all,
            )
        if resolution.band == FOLLOWUP_DELETE_ONE and resolution.cards:
            return _resolve_followup_delete(
                vault_id=vault_id, card=resolution.cards[0],
            )
        if resolution.band == FOLLOWUP_CLARIFY:
            return {
                "band":    BAND_FOLLOWUP_CLARIFY,
                "message": resolution.message,
            }
                                                            

    if intent.intent == INTENT_RETRIEVE_SECURE_ITEM:
        reveal = False
        try:
            from vault_device_reveal_gate import (
                is_explicit_full_reveal_request,
            )
            reveal = bool(is_explicit_full_reveal_request(user_message))
        except Exception:
            reveal = False
        result = retrieve_secure_items_from_intent(
            vault_id=vault_id, key=key, intent=intent,
            db_reader=db_reader,
            db_reader_all=db_reader_all,
            reveal=reveal,
        )
                                                                
                                         
        _stamp_results_context_from_result(
            vault_id=vault_id, result=result,
            last_query=user_message,
        )
        return result

    return {"band": BAND_NO_INTENT, "message": ""}


def _resolve_followup_reveal(
    *,
    vault_id: str,
    key: bytes,
    card: Any,                         
    reveal: bool,
    db_reader: Optional[Any],
    db_reader_all: Optional[Any],
) -> dict:


    synthetic = SecureItemIntent(
        intent=INTENT_RETRIEVE_SECURE_ITEM,
        category=(card.item_type or "").strip().lower() or None,
        field=None,
        title=card.title or "",
        value=None,
        network=None,
    )
    result = retrieve_secure_items_from_intent(
        vault_id=vault_id, key=key, intent=synthetic,
        db_reader=db_reader,
        db_reader_all=db_reader_all,
        reveal=reveal,
    )
                                                          
              
    _stamp_results_context_from_result(
        vault_id=vault_id, result=result,
        last_query=card.title or "",
    )
    return result


def _resolve_followup_delete(
    *,
    vault_id: str, card: Any,
) -> dict:


    return _stamp_delete_confirmation(
        vault_id=vault_id,
        service=card.title or "",
        item_type=card.item_type or "",
        item_id=card.item_id or None,
    )


def _stamp_delete_confirmation(
    *,
    vault_id: str,
    service: str,
    item_type: str,
    item_id: Optional[str],
) -> dict:


    safe_service   = (service or "").strip()
    safe_item_type = (item_type or "").strip()
    if not safe_service or not safe_item_type:
                                                                  
                                                                  
        return {
            "band":    BAND_NO_INTENT,
            "message": "",
        }
    intent = store_delete_intent(
        vault_id=vault_id,
        service=safe_service,
        item_type=safe_item_type,
        item_id=item_id,
    )
    question = _delete_confirmation_question(intent)
    logger.info(
        "[SECURE-ITEM-DELETE] confirmation_pending vault=%s type=%s",
        (vault_id or "")[:8] + "…", safe_item_type,
    )
    return {
        "band":      BAND_DELETE_CONFIRMATION_PENDING,
        "message":   question,
        "title":     safe_service,
        "type":      safe_item_type,
        "is_login":  intent.is_login,
        "intent_id": intent.intent_id,
    }


def _execute_pending_delete(
    *,
    vault_id: str,
    key: bytes,
    db_executor: Optional[Any],
) -> dict:


    if not isinstance(key, (bytes, bytearray)) or len(key) != 32:
        return {
            "band":    BAND_VAULT_LOCKED,
            "message": "Unlock your vault first, then I can delete this.",
        }
    intent = consume_pending_delete_intent(vault_id=vault_id)
    if intent is None:
                                                           
                                                 
        return {
            "band":    BAND_NO_PENDING_DELETE,
            "message": "",
        }
    try:
        deleted_count = _execute_delete_row(
            vault_id=vault_id,
            service=intent.service,
            item_type=intent.item_type,
            db_executor=db_executor,
        )
    except Exception:
        logger.exception(
            "[SECURE-ITEM-DELETE] db_delete_failed vault=%s type=%s",
            (vault_id or "")[:8] + "…", intent.item_type,
        )
        return {
            "band":    BAND_DB_ERROR,
            "message": "Couldn't delete that right now. Try again.",
        }
    if deleted_count <= 0:
                                                             
                                                                 
        logger.info(
            "[SECURE-ITEM-DELETE] no_row_found vault=%s type=%s",
            (vault_id or "")[:8] + "…", intent.item_type,
        )
        return {
            "band":    BAND_DELETED,
            "message": "That saved item was already gone.",
            "title":   intent.service,
            "type":    intent.item_type,
            "is_login": intent.is_login,
            "count":   0,
        }
    logger.info(
        "[SECURE-ITEM-DELETE] deleted vault=%s type=%s count=%d",
        (vault_id or "")[:8] + "…", intent.item_type, deleted_count,
    )
    return {
        "band":     BAND_DELETED,
        "message":  _delete_done_reply(intent),
        "title":    intent.service,
        "type":     intent.item_type,
        "is_login": intent.is_login,
        "count":    deleted_count,
    }


def _cancel_pending_delete(*, vault_id: str) -> dict:
    consumed = consume_pending_delete_intent(vault_id=vault_id)
    if consumed is None:
        return {
            "band":    BAND_NO_PENDING_DELETE,
            "message": "",
        }
    logger.info(
        "[SECURE-ITEM-DELETE] cancelled vault=%s type=%s",
        (vault_id or "")[:8] + "…", consumed.item_type,
    )
    return {
        "band":    BAND_DELETE_CANCELLED,
        "message": _delete_cancelled_reply(),
    }


def _execute_delete_row(
    *,
    vault_id: str,
    service: str,
    item_type: str,
    db_executor: Optional[Any],
) -> int:


    payload = {
        "vault_id":  vault_id,
        "item_type": item_type,
        "service":   service,
    }
    if db_executor is not None:
        result = db_executor("delete", payload)
        if isinstance(result, int):
            return result
        if isinstance(result, dict) and isinstance(result.get("count"), int):
            return int(result["count"])
                                                                
        return 1
    return _default_delete(payload)


def _default_delete(payload: dict) -> int:


    from main import bump_vault_total_bytes, get_db
    from psycopg2.extras import RealDictCursor

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            DELETE FROM vault_items
            WHERE vault_id  = %s
              AND item_type = %s
              AND LOWER(service) = LOWER(%s)
            RETURNING id, encrypted_data
            """,
            (
                payload["vault_id"],
                payload["item_type"],
                payload["service"],
            ),
        )
        rows = cur.fetchall() or []
        conn.commit()
                                                               
                          
        try:
            from vault_tool_result_cache import invalidate_for_event
            event = (
                "credential_deleted"
                if payload["item_type"] in ("login", "credential")
                else "secure_item_deleted"
            )
            invalidate_for_event(
                vault_id=payload["vault_id"], event=event,
            )
        except Exception:
            pass
                                                              
                             
        freed = sum(_blob_size(r.get("encrypted_data")) for r in rows)
        if freed > 0:
            try:
                bump_vault_total_bytes(
                    payload["vault_id"], -int(freed),
                )
            except Exception:
                logger.warning(
                    "[SECURE-ITEM] storage_debit_failed vault=%s "
                    "freed=%d — nightly reconciliation will catch this",
                    (payload.get("vault_id") or "")[:8] + "…", freed,
                )
        return len(rows)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _stamp_results_context_from_result(
    *, vault_id: str, result: dict, last_query: str,
) -> None:


    if not isinstance(result, dict):
        return
    envelope = result.get("envelope")
    if not isinstance(envelope, str) or not envelope:
        return
    try:
        payload = json.loads(envelope)
    except Exception:
        return
    items = payload.get("items") or []
    try:
        store_results_context(
            vault_id=vault_id,
            cards=items,
            last_query=last_query,
        )
    except Exception:
        logger.exception(
            "[SECURE-ITEM] results_ctx_store_failed vault=%s",
            (vault_id or "")[:8] + "…",
        )


__all__ = [
    "BAND_SAVED",
    "BAND_DRAFTED",
    "BAND_WARN_DRAFTED",
    "BAND_TITLE_UPDATED",
    "BAND_NEEDS_CLARIFICATION",
    "BAND_VALIDATION_FAILED",
    "BAND_VAULT_LOCKED",
    "BAND_DB_ERROR",
    "BAND_NO_INTENT",
    "BAND_NO_DRAFT",
    "BAND_TIER_REQUIRED",
    "BAND_RETRIEVED",
    "BAND_NOT_FOUND",
    "BAND_FOLLOWUP_CLARIFY",
    "BAND_DELETE_PROMPT",
                                 
    "BAND_DELETE_CONFIRMATION_PENDING",
    "BAND_DELETED",
    "BAND_DELETE_CANCELLED",
    "BAND_NO_PENDING_DELETE",
    "TIER_FREE", "TIER_BASIC", "TIER_UPGRADED",
    "ALL_TIERS",
    "build_save_args",
    "save_secure_item_from_intent",
    "save_secure_item_from_message",
    "propose_secure_item_draft_from_intent",
    "propose_secure_item_draft_from_message",
    "update_pending_secure_item_draft_title_from_message",
    "confirm_pending_secure_item_save",
    "retrieve_secure_item_from_intent",
    "retrieve_secure_items_from_intent",
    "route_secure_item_message",
]
