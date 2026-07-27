

from __future__ import annotations

import logging
import re
from typing import Any, Optional


logger = logging.getLogger(__name__)


CATEGORY_LOGIN:         str = "login"
CATEGORY_CREDENTIAL:    str = "credential"
CATEGORY_DEVICE:        str = "device"
CATEGORY_DEVICE_INFO:   str = "device_info"
CATEGORY_IMEI:          str = "imei"
CATEGORY_SERIAL_NUMBER: str = "serial_number"
CATEGORY_DOCUMENT_NOTE: str = "document_note"
CATEGORY_RECOVERY_CODE: str = "recovery_code"
CATEGORY_BACKUP_CODE:   str = "backup_code"
CATEGORY_PRIVATE_NOTE:  str = "private_note"
CATEGORY_ACCOUNT_NOTE:  str = "account_note"
CATEGORY_BANK:          str = "bank"
CATEGORY_CARD:          str = "card"
CATEGORY_OTHER:         str = "other"
CATEGORY_OTHER_SECRET:  str = "other_secret"

                                                 
CATEGORY_LICENSE_KEY:    str = "license_key"
CATEGORY_PRODUCT_KEY:    str = "product_key"
CATEGORY_ACTIVATION_KEY: str = "activation_key"
CATEGORY_PRIVATE_KEY:    str = "private_key"
CATEGORY_RECOVERY_PHRASE: str = "recovery_phrase"

                                                            
CATEGORY_CRYPTO_WALLET_ADDRESS:      str = "crypto_wallet_address"
CATEGORY_CRYPTO_SEED_PHRASE:         str = "crypto_seed_phrase"
CATEGORY_CRYPTO_PRIVATE_KEY:         str = "crypto_private_key"
CATEGORY_CRYPTO_RECOVERY_PHRASE:     str = "crypto_recovery_phrase"
CATEGORY_CRYPTO_NOTE:                str = "crypto_note"
CATEGORY_CRYPTO_TRANSACTION_NOTE:    str = "crypto_transaction_note"
CATEGORY_CRYPTO_EXCHANGE_NOTE:       str = "crypto_exchange_note"
CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE: str = "crypto_hardware_wallet_note"


CRYPTO_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_CRYPTO_WALLET_ADDRESS,
    CATEGORY_CRYPTO_SEED_PHRASE,
    CATEGORY_CRYPTO_PRIVATE_KEY,
    CATEGORY_CRYPTO_RECOVERY_PHRASE,
    CATEGORY_CRYPTO_NOTE,
    CATEGORY_CRYPTO_TRANSACTION_NOTE,
    CATEGORY_CRYPTO_EXCHANGE_NOTE,
    CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE,
})


CRYPTO_HIDDEN_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_CRYPTO_SEED_PHRASE,
    CATEGORY_CRYPTO_PRIVATE_KEY,
    CATEGORY_CRYPTO_RECOVERY_PHRASE,
    CATEGORY_CRYPTO_TRANSACTION_NOTE,
    CATEGORY_CRYPTO_EXCHANGE_NOTE,
})


CRYPTO_WARN_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_CRYPTO_SEED_PHRASE,
    CATEGORY_CRYPTO_PRIVATE_KEY,
    CATEGORY_CRYPTO_RECOVERY_PHRASE,
})


NETWORK_BTC:        str = "BTC"
NETWORK_ETH:        str = "ETH"
NETWORK_USDT_TRC20: str = "USDT TRC20"
NETWORK_USDT_ERC20: str = "USDT ERC20"
NETWORK_USDC_ERC20: str = "USDC ERC20"
NETWORK_USDC_TRC20: str = "USDC TRC20"
NETWORK_SOL:        str = "SOL"
NETWORK_BNB:        str = "BNB"
NETWORK_TRX:        str = "TRX"
NETWORK_MATIC:      str = "MATIC"
NETWORK_DOGE:       str = "DOGE"
NETWORK_LTC:        str = "LTC"
NETWORK_ADA:        str = "ADA"
NETWORK_XRP:        str = "XRP"
                                                                  
                                                                
NETWORK_XMR:        str = "XMR"


ALL_NETWORK_LABELS: tuple[str, ...] = (
    NETWORK_USDT_TRC20, NETWORK_USDT_ERC20,
    NETWORK_USDC_ERC20, NETWORK_USDC_TRC20,
    NETWORK_BTC, NETWORK_ETH, NETWORK_SOL, NETWORK_BNB,
    NETWORK_TRX, NETWORK_MATIC, NETWORK_DOGE,
    NETWORK_LTC, NETWORK_ADA, NETWORK_XRP,
    NETWORK_XMR,
)


KEY_FAMILY_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_LICENSE_KEY,
    CATEGORY_PRODUCT_KEY,
    CATEGORY_ACTIVATION_KEY,
    CATEGORY_PRIVATE_KEY,
    CATEGORY_RECOVERY_PHRASE,
})


ALL_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_LOGIN, CATEGORY_CREDENTIAL,
    CATEGORY_DEVICE, CATEGORY_DEVICE_INFO,
    CATEGORY_IMEI, CATEGORY_SERIAL_NUMBER,
    CATEGORY_DOCUMENT_NOTE, CATEGORY_RECOVERY_CODE,
    CATEGORY_BACKUP_CODE, CATEGORY_PRIVATE_NOTE,
    CATEGORY_ACCOUNT_NOTE,
    CATEGORY_BANK, CATEGORY_CARD,
    CATEGORY_OTHER, CATEGORY_OTHER_SECRET,
}) | CRYPTO_CATEGORIES | KEY_FAMILY_CATEGORIES


NON_LOGIN_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_DEVICE, CATEGORY_DEVICE_INFO,
    CATEGORY_IMEI, CATEGORY_SERIAL_NUMBER,
    CATEGORY_DOCUMENT_NOTE, CATEGORY_RECOVERY_CODE,
    CATEGORY_BACKUP_CODE, CATEGORY_PRIVATE_NOTE,
    CATEGORY_ACCOUNT_NOTE,
    CATEGORY_OTHER, CATEGORY_OTHER_SECRET,
}) | CRYPTO_CATEGORIES | KEY_FAMILY_CATEGORIES


LOGIN_LIKE_CATEGORIES: frozenset[str] = frozenset({
    CATEGORY_LOGIN, CATEGORY_CREDENTIAL,
})


_CATEGORY_NOUNS: dict[str, str] = {
    CATEGORY_LOGIN:         "login",
    CATEGORY_CREDENTIAL:    "credential",
    CATEGORY_DEVICE:        "device record",
    CATEGORY_DEVICE_INFO:   "device record",
    CATEGORY_IMEI:          "Phone IMEI",
    CATEGORY_SERIAL_NUMBER: "serial number",
    CATEGORY_DOCUMENT_NOTE: "note",
    CATEGORY_RECOVERY_CODE: "recovery code",
    CATEGORY_BACKUP_CODE:   "backup code",
    CATEGORY_PRIVATE_NOTE:  "private note",
    CATEGORY_ACCOUNT_NOTE:  "account note",
    CATEGORY_BANK:          "bank record",
    CATEGORY_CARD:          "card record",
    CATEGORY_OTHER:         "saved item",
    CATEGORY_OTHER_SECRET:  "saved secret",
    CATEGORY_CRYPTO_WALLET_ADDRESS:       "crypto wallet address",
    CATEGORY_CRYPTO_SEED_PHRASE:          "crypto seed phrase",
    CATEGORY_CRYPTO_PRIVATE_KEY:          "crypto private key",
    CATEGORY_CRYPTO_RECOVERY_PHRASE:      "crypto recovery phrase",
    CATEGORY_CRYPTO_NOTE:                 "crypto note",
    CATEGORY_CRYPTO_TRANSACTION_NOTE:     "transaction note",
    CATEGORY_CRYPTO_EXCHANGE_NOTE:        "exchange account note",
    CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE: "hardware wallet note",
                                    
    CATEGORY_LICENSE_KEY:    "license key",
    CATEGORY_PRODUCT_KEY:    "product key",
    CATEGORY_ACTIVATION_KEY: "activation key",
    CATEGORY_PRIVATE_KEY:    "private key",
    CATEGORY_RECOVERY_PHRASE: "recovery phrase",
}


def noun_for_category(category: Optional[str]) -> str:


    if not isinstance(category, str):
        return "saved item"
    return _CATEGORY_NOUNS.get(category.strip().lower(), "saved item")


_CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_LOGIN:         "Login",
    CATEGORY_CREDENTIAL:    "Credential",
    CATEGORY_DEVICE:        "Device",
    CATEGORY_DEVICE_INFO:   "Device",
    CATEGORY_IMEI:          "Phone IMEI",
    CATEGORY_SERIAL_NUMBER: "Serial number",
    CATEGORY_DOCUMENT_NOTE: "Note",
    CATEGORY_RECOVERY_CODE: "Recovery code",
    CATEGORY_BACKUP_CODE:   "Backup code",
    CATEGORY_PRIVATE_NOTE:  "Private note",
    CATEGORY_ACCOUNT_NOTE:  "Account note",
    CATEGORY_BANK:          "Bank record",
    CATEGORY_CARD:          "Card record",
    CATEGORY_OTHER:         "Saved item",
    CATEGORY_OTHER_SECRET:  "Saved secret",
    CATEGORY_CRYPTO_WALLET_ADDRESS:       "Crypto wallet",
    CATEGORY_CRYPTO_SEED_PHRASE:          "Seed phrase",
    CATEGORY_CRYPTO_PRIVATE_KEY:          "Private key",
    CATEGORY_CRYPTO_RECOVERY_PHRASE:      "Recovery phrase",
    CATEGORY_CRYPTO_NOTE:                 "Crypto note",
    CATEGORY_CRYPTO_TRANSACTION_NOTE:     "Transaction note",
    CATEGORY_CRYPTO_EXCHANGE_NOTE:        "Exchange note",
    CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE: "Hardware wallet note",
                                           
    CATEGORY_LICENSE_KEY:    "License key",
    CATEGORY_PRODUCT_KEY:    "Product key",
    CATEGORY_ACTIVATION_KEY: "Activation key",
    CATEGORY_PRIVATE_KEY:    "Private key",
    CATEGORY_RECOVERY_PHRASE: "Recovery phrase",
}


_CATEGORY_ICONS: dict[str, str] = {
    CATEGORY_LOGIN:         "login",
    CATEGORY_CREDENTIAL:    "credential",
    CATEGORY_DEVICE:        "device",
    CATEGORY_DEVICE_INFO:   "device",
    CATEGORY_IMEI:          "phone",
    CATEGORY_SERIAL_NUMBER: "serial",
    CATEGORY_DOCUMENT_NOTE: "note",
    CATEGORY_RECOVERY_CODE: "key",
    CATEGORY_BACKUP_CODE:   "key",
    CATEGORY_PRIVATE_NOTE:  "note",
    CATEGORY_ACCOUNT_NOTE:  "note",
    CATEGORY_BANK:          "bank",
    CATEGORY_CARD:          "card",
    CATEGORY_OTHER:         "item",
    CATEGORY_OTHER_SECRET:  "secret",
    CATEGORY_CRYPTO_WALLET_ADDRESS:       "wallet",
    CATEGORY_CRYPTO_SEED_PHRASE:          "seed",
    CATEGORY_CRYPTO_PRIVATE_KEY:          "key",
    CATEGORY_CRYPTO_RECOVERY_PHRASE:      "key",
    CATEGORY_CRYPTO_NOTE:                 "note",
    CATEGORY_CRYPTO_TRANSACTION_NOTE:     "note",
    CATEGORY_CRYPTO_EXCHANGE_NOTE:        "note",
    CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE: "wallet",
                             
    CATEGORY_LICENSE_KEY:    "key",
    CATEGORY_PRODUCT_KEY:    "key",
    CATEGORY_ACTIVATION_KEY: "key",
    CATEGORY_PRIVATE_KEY:    "key",
    CATEGORY_RECOVERY_PHRASE: "key",
}


def category_label(category: Optional[str]) -> str:


    if not isinstance(category, str):
        return "Saved item"
    return _CATEGORY_LABELS.get(category.strip().lower(), "Saved item")


def category_icon(category: Optional[str]) -> str:


    if not isinstance(category, str):
        return "item"
    return _CATEGORY_ICONS.get(category.strip().lower(), "item")


SENSITIVE_FIELDS: frozenset[str] = frozenset({
    "password",
    "imei", "imei_1", "imei_2",
    "serial", "serial_number",
    "mac", "mac_address",
    "phone", "phone_number",
    "notes", "lock_screen_note",
    "recovery_code", "recovery_key",
    "bitlocker_recovery_reference",
    "backup_codes", "two_factor_codes",
    "account_notes", "private_notes",
                                      
    "private_value", "private_word", "secret_value",
                                
    "wallet_address",
    "seed_phrase", "private_key", "recovery_phrase",
    "crypto_note", "transaction_note", "exchange_note",
    "hardware_wallet_note",
                                                 
    "license_key", "product_key", "activation_key",
})


_FIELD_TO_CATEGORY: dict[str, str] = {
                   
    "imei":             CATEGORY_DEVICE,
    "imei_1":           CATEGORY_DEVICE,
    "imei_2":           CATEGORY_DEVICE,
    "serial":           CATEGORY_DEVICE,
    "serial_number":    CATEGORY_DEVICE,
    "mac":              CATEGORY_DEVICE,
    "mac_address":      CATEGORY_DEVICE,
    "phone_number":     CATEGORY_DEVICE,
    "sim_provider":     CATEGORY_DEVICE,
    "lock_screen_note": CATEGORY_DEVICE,
    "find_my_status":   CATEGORY_DEVICE,
    "device_name":      CATEGORY_DEVICE,
    "device_kind":      CATEGORY_DEVICE,
    "bitlocker_recovery_reference": CATEGORY_DEVICE,
    "operating_system": CATEGORY_DEVICE,
                     
    "recovery_code":   CATEGORY_RECOVERY_CODE,
    "recovery_key":    CATEGORY_RECOVERY_CODE,
    "backup_codes":    CATEGORY_RECOVERY_CODE,
    "two_factor_codes": CATEGORY_RECOVERY_CODE,
                 
    "iban":           CATEGORY_BANK,
    "swift":          CATEGORY_BANK,
    "routing_number": CATEGORY_BANK,
    "account_number": CATEGORY_BANK,
    "card_number":    CATEGORY_CARD,
    "cvv":            CATEGORY_CARD,
    "expiration":     CATEGORY_CARD,
}


def infer_category_from_fields(
    fields: Optional[dict],
) -> Optional[str]:


    if not isinstance(fields, dict):
        return None
    for key in fields.keys():
        if not isinstance(key, str):
            continue
        cat = _FIELD_TO_CATEGORY.get(key.strip().lower())
        if cat is not None:
            return cat
    return None


_TOKEN_TO_CATEGORY: dict[str, str] = {
                   
    "imei":           CATEGORY_DEVICE,
    "imeis":          CATEGORY_DEVICE,
    "serial":         CATEGORY_DEVICE,
    "serials":        CATEGORY_DEVICE,
    "mac":            CATEGORY_DEVICE,
    "phone":          CATEGORY_DEVICE,
    "iphone":         CATEGORY_DEVICE,
    "android":        CATEGORY_DEVICE,
    "laptop":         CATEGORY_DEVICE,
    "macbook":        CATEGORY_DEVICE,
    "pc":             CATEGORY_DEVICE,
    "tablet":         CATEGORY_DEVICE,
    "ipad":           CATEGORY_DEVICE,
    "device":         CATEGORY_DEVICE,
    "devices":        CATEGORY_DEVICE,
              
    "recovery":       CATEGORY_RECOVERY_CODE,
    "backup":         CATEGORY_RECOVERY_CODE,
    "bitlocker":      CATEGORY_RECOVERY_CODE,
    "filevault":      CATEGORY_RECOVERY_CODE,
                 
    "iban":           CATEGORY_BANK,
    "routing":        CATEGORY_BANK,
    "swift":          CATEGORY_BANK,
    "card":           CATEGORY_CARD,
    "cvv":            CATEGORY_CARD,
                                                                   
    "login":          CATEGORY_LOGIN,
    "logins":         CATEGORY_LOGIN,
    "password":       CATEGORY_LOGIN,
    "username":       CATEGORY_LOGIN,
    "credential":     CATEGORY_LOGIN,
    "credentials":    CATEGORY_LOGIN,
           
    "note":           CATEGORY_DOCUMENT_NOTE,
    "notes":          CATEGORY_DOCUMENT_NOTE,
}


_WORD_RE = re.compile(r"[A-Za-z]+")


def infer_category_from_message(
    user_message: Optional[str],
) -> Optional[str]:


    if not isinstance(user_message, str) or not user_message:
        return None
    for m in _WORD_RE.finditer(user_message.lower()):
        cat = _TOKEN_TO_CATEGORY.get(m.group(0))
        if cat is not None:
            return cat
    return None


def classify_secure_item_payload(
    args: Optional[dict],
) -> Optional[str]:


    if not isinstance(args, dict):
        return "missing_args"
    secret_type = (
        str(args.get("secret_type") or args.get("category") or "")
        .strip().lower()
    )
    if not secret_type:
        return "missing_kind"
    title = (
        str(args.get("service") or args.get("title") or "")
        .strip()
    )
    if not title:
        return "missing_title"
    fields = args.get("fields") or {}
    if not isinstance(fields, dict):
        return "fields_not_dict"
    if secret_type in LOGIN_LIKE_CATEGORIES:
        if not (fields.get("username") or fields.get("password")):
            return "empty_login_fields"
        return None
                                                            
    if not fields and not args.get("notes"):
        return "empty_fields"
    return None


def mask_tail(value: Any, *, keep: int = 4) -> str:
    if value is None or value == "":
        return ""
    raw = re.sub(r"[^A-Za-z0-9]", "", str(value))
    if len(raw) <= keep:
        return f"{len(raw)}-char value"
    return f"ending {raw[-keep:]}"


def mask_mac(value: Any) -> str:
    if value is None or value == "":
        return ""
    raw = re.sub(r"[^A-Fa-f0-9]", "", str(value))
    if len(raw) < 4:
        return f"{len(raw)}-char value"
    tail = raw[-4:].upper()
    return f"ending {tail[:2]}:{tail[2:]}"


def mask_wallet_address(value: Any) -> str:
    if value is None or value == "":
        return ""
    raw = re.sub(r"\s+", "", str(value))
    if len(raw) < 12:
        return mask_tail(raw)
    head = raw[:6]
    tail = raw[-4:]
    return f"{head}…{tail}"


_DISPLAY_LABELS: dict[str, str] = {
    "username": "Username",
    "password": "Password",
    "website": "Website",
    "url": "Website or URL",
    "notes": "Note",
    "note": "Note",
}


def _ordered_field_entries(fields: Optional[dict]) -> list[dict[str, str]]:
    if not isinstance(fields, dict):
        return []
    out: list[dict[str, str]] = []
    for raw_label, raw_value in fields.items():
        label = str(raw_label or "").strip()
        if not label or raw_value is None:
            continue
        value = str(raw_value)
        out.append({
            "label": _DISPLAY_LABELS.get(label, label),
            "value": value,
        })
    return out


def masked_preview(
    *, category: Optional[str],
    title: str,
    fields: Optional[dict] = None,
    notes: Optional[str] = None,
) -> dict:


    cat = (category or "").strip().lower() or CATEGORY_OTHER
    fields = fields or {}
    out: dict = {
        "category":  cat if cat in ALL_CATEGORIES else CATEGORY_OTHER,
        "noun":      noun_for_category(cat),
        "title":     str(title or "").strip(),
        "has_notes": bool(notes),
    }
    if "username" in fields and fields["username"]:
                                                            
        out["username"] = str(fields["username"]).strip()
    if "password" in fields and fields["password"]:
        out["has_password"] = True
    for fname in (
        "imei_1", "imei_2", "serial_number", "serial",
        "recovery_code", "backup_codes",
    ):
        if fname in fields and fields[fname]:
            out[f"{fname}_mask"] = mask_tail(fields[fname])
                                                            
                                                               
    for fname in ("private_value", "private_word", "secret_value"):
        if fname in fields and fields[fname]:
            out[f"{fname}_mask"] = "•••••• hidden"
            out[f"has_{fname}"] = True
    if "account_notes" in fields and fields["account_notes"]:
        out["account_notes_mask"] = "•••••• hidden"
        out["has_account_notes"] = True
    if "mac_address" in fields and fields["mac_address"]:
        out["mac_address_mask"] = mask_mac(fields["mac_address"])
    elif "mac" in fields and fields["mac"]:
        out["mac_address_mask"] = mask_mac(fields["mac"])
    if "phone_number" in fields and fields["phone_number"]:
        out["phone_number_mask"] = mask_tail(fields["phone_number"])
    elif "phone" in fields and fields["phone"]:
        out["phone_number_mask"] = mask_tail(fields["phone"])

                                     
    if "wallet_address" in fields and fields["wallet_address"]:
        out["wallet_address_mask"] = mask_wallet_address(
            fields["wallet_address"],
        )
        out["has_wallet_address"] = True
                                                             
    if "network" in fields and fields["network"]:
        out["network"] = str(fields["network"]).strip()
                                                               
                                                          
    for fname in (
        "seed_phrase", "private_key", "recovery_phrase",
        "transaction_note", "exchange_note",
        "hardware_wallet_note",
    ):
        if fname in fields and fields[fname]:
            out[f"{fname}_mask"] = "•••••• hidden"
            out[f"has_{fname}"] = True
                                                              
                      
    if "crypto_note" in fields and fields["crypto_note"]:
        out["crypto_note_mask"] = "•••••• hidden"
        out["has_crypto_note"] = True
                                                               
                                                             
    for fname in ("license_key", "product_key", "activation_key"):
        if fname in fields and fields[fname]:
            out[f"{fname}_mask"] = "•••••• hidden"
            out[f"has_{fname}"] = True
    return out


def revealed_preview(
    *, category: Optional[str],
    title: str,
    fields: Optional[dict] = None,
    notes: Optional[str] = None,
) -> dict:


    cat = (category or "").strip().lower() or CATEGORY_OTHER
    fields = fields or {}
    out: dict = {
        "category":  cat if cat in ALL_CATEGORIES else CATEGORY_OTHER,
        "noun":      noun_for_category(cat),
        "title":     str(title or "").strip(),
        "revealed":  True,
    }
    if "username" in fields and fields["username"]:
        out["username"] = str(fields["username"]).strip()
    if "password" in fields and fields["password"]:
        out["password"] = str(fields["password"])
        out["has_password"] = True
    for fname in (
        "imei_1", "imei_2", "serial_number", "serial",
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
    ):
        if fname in fields and fields[fname]:
            out[fname] = str(fields[fname])
    if notes:
        out["notes"] = str(notes)
        out["has_notes"] = True
    ordered_fields = _ordered_field_entries(fields)
    if ordered_fields:
        out["fields"] = ordered_fields
    return out


def saved_confirmation_message(
    *, category: Optional[str], title: str,
) -> str:


    noun = noun_for_category(category)
    safe_title = str(title or "").strip() or "this"
    return f"Saved your {safe_title} {noun}."


__all__ = [
    "CATEGORY_LOGIN", "CATEGORY_CREDENTIAL",
    "CATEGORY_DEVICE", "CATEGORY_DEVICE_INFO",
    "CATEGORY_IMEI", "CATEGORY_SERIAL_NUMBER",
    "CATEGORY_DOCUMENT_NOTE",
    "CATEGORY_RECOVERY_CODE", "CATEGORY_BACKUP_CODE",
    "CATEGORY_PRIVATE_NOTE", "CATEGORY_ACCOUNT_NOTE",
    "CATEGORY_BANK", "CATEGORY_CARD",
    "CATEGORY_OTHER", "CATEGORY_OTHER_SECRET",
                                   
    "CATEGORY_CRYPTO_WALLET_ADDRESS",
    "CATEGORY_CRYPTO_SEED_PHRASE",
    "CATEGORY_CRYPTO_PRIVATE_KEY",
    "CATEGORY_CRYPTO_RECOVERY_PHRASE",
    "CATEGORY_CRYPTO_NOTE",
    "CATEGORY_CRYPTO_TRANSACTION_NOTE",
    "CATEGORY_CRYPTO_EXCHANGE_NOTE",
    "CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE",
    "CRYPTO_CATEGORIES", "CRYPTO_HIDDEN_CATEGORIES",
    "CRYPTO_WARN_CATEGORIES",
                                               
    "CATEGORY_LICENSE_KEY", "CATEGORY_PRODUCT_KEY",
    "CATEGORY_ACTIVATION_KEY", "CATEGORY_PRIVATE_KEY",
    "CATEGORY_RECOVERY_PHRASE",
    "KEY_FAMILY_CATEGORIES",
                      
    "NETWORK_BTC", "NETWORK_ETH",
    "NETWORK_USDT_TRC20", "NETWORK_USDT_ERC20",
    "NETWORK_USDC_TRC20", "NETWORK_USDC_ERC20",
    "NETWORK_SOL", "NETWORK_BNB", "NETWORK_TRX",
    "NETWORK_MATIC", "NETWORK_DOGE",
    "NETWORK_LTC", "NETWORK_ADA", "NETWORK_XRP",
    "NETWORK_XMR",
    "ALL_NETWORK_LABELS",
    "ALL_CATEGORIES", "NON_LOGIN_CATEGORIES",
    "LOGIN_LIKE_CATEGORIES",
    "SENSITIVE_FIELDS",
    "noun_for_category",
    "category_label",
    "category_icon",
    "infer_category_from_fields",
    "infer_category_from_message",
    "classify_secure_item_payload",
    "mask_tail", "mask_mac", "mask_wallet_address",
    "masked_preview",
    "revealed_preview",
    "saved_confirmation_message",
]
