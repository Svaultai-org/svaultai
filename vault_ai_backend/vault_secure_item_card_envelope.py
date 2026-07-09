

from __future__ import annotations

import json
import logging
from typing import Optional

from vault_saved_item_taxonomy import (
    ALL_CATEGORIES,
    CATEGORY_LOGIN,
    CATEGORY_OTHER,
    category_icon,
    category_label,
)


logger = logging.getLogger(__name__)


TYPE_SECURE_ITEM_RESULTS: str = "secure_item_results"


SCHEMA_VERSION: str = "secure_item.v1"
COPY_VERSION:   str = "secure_item_2026_06_28"


MESSAGE_NONE_FOUND_GENERIC:  str = "You haven't saved any items like that yet."
MESSAGE_NONE_FOUND_LOGIN:    str = "You haven't saved any logins yet."
MESSAGE_NONE_FOUND_IMEI:     str = "You haven't saved an IMEI yet."
MESSAGE_NONE_FOUND_SERIAL:   str = "You haven't saved a serial number yet."
MESSAGE_NONE_FOUND_BACKUP:   str = "You haven't saved any backup codes yet."
MESSAGE_NONE_FOUND_RECOVERY: str = "You haven't saved any recovery codes yet."
MESSAGE_NONE_FOUND_NOTE:     str = "You haven't saved any private notes yet."


def _none_found_message(category: Optional[str]) -> str:

    cat = (category or "").strip().lower()
    if cat == CATEGORY_LOGIN:
        return MESSAGE_NONE_FOUND_LOGIN
    if cat == "imei":
        return MESSAGE_NONE_FOUND_IMEI
    if cat in ("serial_number",):
        return MESSAGE_NONE_FOUND_SERIAL
    if cat == "backup_code":
        return MESSAGE_NONE_FOUND_BACKUP
    if cat == "recovery_code":
        return MESSAGE_NONE_FOUND_RECOVERY
    if cat in ("private_note", "account_note"):
        return MESSAGE_NONE_FOUND_NOTE
    return MESSAGE_NONE_FOUND_GENERIC


def _found_message(count: int) -> str:

    if count <= 0:
        return MESSAGE_NONE_FOUND_GENERIC
    if count == 1:
        return "Here's the saved item I found 🔐"
    return f"I found {count} saved items 🔐"


_ALLOWED_MASKED_KEYS: frozenset[str] = frozenset({
    "category", "noun",
    "title", "username",
    "has_password", "has_notes",
    "has_private_value", "has_private_word",
    "has_secret_value", "has_account_notes",
    "imei_1_mask", "imei_2_mask",
    "serial_number_mask", "serial_mask",
    "mac_address_mask", "mac_mask",
    "phone_number_mask", "phone_mask",
    "recovery_code_mask", "backup_codes_mask",
    "private_value_mask", "private_word_mask",
    "secret_value_mask", "account_notes_mask",
                                     
    "wallet_address_mask", "has_wallet_address",
    "network",
    "seed_phrase_mask", "has_seed_phrase",
    "private_key_mask", "has_private_key",
    "recovery_phrase_mask", "has_recovery_phrase",
    "crypto_note_mask", "has_crypto_note",
    "transaction_note_mask", "has_transaction_note",
    "exchange_note_mask", "has_exchange_note",
    "hardware_wallet_note_mask", "has_hardware_wallet_note",
                                                              
    "license_key_mask", "has_license_key",
    "product_key_mask", "has_product_key",
    "activation_key_mask", "has_activation_key",
})


_ALLOWED_REVEALED_KEYS: frozenset[str] = frozenset({
    "category", "noun", "title", "revealed",
    "username", "password", "has_password",
    "has_notes", "notes",
    "imei_1", "imei_2",
    "serial_number", "serial",
    "mac_address", "mac",
    "phone_number", "phone",
    "recovery_code", "backup_codes",
    "private_value", "private_word", "secret_value",
    "account_notes",
                                            
    "wallet_address", "network",
    "seed_phrase", "private_key", "recovery_phrase",
    "crypto_note", "transaction_note", "exchange_note",
    "hardware_wallet_note",
                                                       
                                                                  
    "license_key", "product_key", "activation_key",
})


def _filter_preview(preview: dict, *, reveal: bool) -> dict:


    allow = _ALLOWED_REVEALED_KEYS if reveal else _ALLOWED_MASKED_KEYS
    out: dict = {}
    for k, v in (preview or {}).items():
        if k in allow:
            out[k] = v
    return out


def _safe_card_type(category: Optional[str]) -> str:


    cat = (category or "").strip().lower()
    if cat in ALL_CATEGORIES:
        return cat
    return CATEGORY_OTHER


def build_secure_item_card(
    *,
    item_id: str,
    category: str,
    title: str,
    preview: dict,
    created_at: Optional[float] = None,
    reveal: bool = False,
) -> dict:


    safe_cat = _safe_card_type(category)
    safe_preview = _filter_preview(preview or {}, reveal=reveal)
                                                                
                                                                  
    card: dict = {
        "item_id":        str(item_id or ""),
        "type":           safe_cat,
        "title":          str(title or "").strip(),
        "category_label": category_label(safe_cat),
        "icon":           category_icon(safe_cat),
        "preview":        safe_preview,
        "available_actions": (
            ["open", "edit", "delete"]
            if safe_cat != CATEGORY_LOGIN
            else ["open", "copy_username", "edit", "delete"]
        ),
    }
    if created_at is not None:
        try:
            card["created_at"] = float(created_at)
        except (TypeError, ValueError):
            pass
    return card


DISPLAY_MODE_DETAIL: str = "detail"
DISPLAY_MODE_LIST:   str = "list"
ALL_DISPLAY_MODES = (DISPLAY_MODE_DETAIL, DISPLAY_MODE_LIST)


def build_secure_item_results_envelope(
    *,
    items: list[dict],
    category_filter: Optional[str] = None,
    reveal: bool = False,
    message: Optional[str] = None,
    display_mode: Optional[str] = None,
    receive_intent: bool = False,
) -> str:


    safe_items: list[dict] = []
    for i in items or []:
        if not isinstance(i, dict):
            continue
        safe_items.append({
            "item_id":        str(i.get("item_id") or ""),
            "type":           _safe_card_type(i.get("type")),
            "title":          str(i.get("title") or "").strip(),
            "category_label": str(i.get("category_label") or "Saved item"),
            "icon":           str(i.get("icon") or "item"),
            "preview":        _filter_preview(
                i.get("preview") or {}, reveal=reveal,
            ),
            "available_actions": list(i.get("available_actions") or []),
            **(
                {"created_at": float(i["created_at"])}
                if isinstance(i.get("created_at"), (int, float))
                else {}
            ),
        })
    if message is None:
        if not safe_items:
                                                                
                                                               
            if receive_intent and category_filter == "crypto_wallet_address":
                message = (
                    "I couldn't find a saved receive address. "
                    "Save one first, then I can show its QR code."
                )
            else:
                message = _none_found_message(category_filter)
        else:
            message = _found_message(len(safe_items))
                                                              
                                                              
    if display_mode is None:
        if reveal and len(safe_items) == 1:
            resolved_mode = DISPLAY_MODE_DETAIL
        else:
            resolved_mode = DISPLAY_MODE_LIST
    elif display_mode in ALL_DISPLAY_MODES:
        resolved_mode = display_mode
    else:
        resolved_mode = DISPLAY_MODE_LIST
                                                                   
                                                                  
    receive_for_envelope = bool(
        receive_intent
        and reveal
        and len(safe_items) == 1
        and safe_items[0].get("type") == "crypto_wallet_address"
    )
    payload = {
        "type":            TYPE_SECURE_ITEM_RESULTS,
        "schema_version":  SCHEMA_VERSION,
        "copy_version":    COPY_VERSION,
        "count":           len(safe_items),
        "items":           safe_items,
        "message":         message,
        "reveal":          bool(reveal),
        "display_mode":    resolved_mode,
        "category_filter": category_filter or "",
        "receive_intent":  receive_for_envelope,
    }
    logger.info(
        "[SECURE-ITEM-ENV] results count=%d cat=%s reveal=%s mode=%s schema=%s",
        len(safe_items),
        category_filter or "(any)",
        "yes" if reveal else "no",
        resolved_mode,
        SCHEMA_VERSION,
    )
    return json.dumps(payload, ensure_ascii=False)


__all__ = [
    "TYPE_SECURE_ITEM_RESULTS",
    "SCHEMA_VERSION",
    "COPY_VERSION",
    "DISPLAY_MODE_DETAIL",
    "DISPLAY_MODE_LIST",
    "ALL_DISPLAY_MODES",
    "MESSAGE_NONE_FOUND_GENERIC",
    "MESSAGE_NONE_FOUND_LOGIN",
    "MESSAGE_NONE_FOUND_IMEI",
    "MESSAGE_NONE_FOUND_SERIAL",
    "MESSAGE_NONE_FOUND_BACKUP",
    "MESSAGE_NONE_FOUND_RECOVERY",
    "MESSAGE_NONE_FOUND_NOTE",
    "build_secure_item_card",
    "build_secure_item_results_envelope",
]
