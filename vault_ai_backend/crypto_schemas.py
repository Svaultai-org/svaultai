

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from vault_saved_item_taxonomy import (
    CATEGORY_CRYPTO_WALLET_ADDRESS,
    CATEGORY_CRYPTO_SEED_PHRASE,
    CATEGORY_CRYPTO_PRIVATE_KEY,
    CATEGORY_CRYPTO_RECOVERY_PHRASE,
    CATEGORY_CRYPTO_NOTE,
    CATEGORY_CRYPTO_TRANSACTION_NOTE,
    CATEGORY_CRYPTO_EXCHANGE_NOTE,
    CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE,
    CRYPTO_CATEGORIES,
    CRYPTO_WARN_CATEGORIES,
)


SCHEMA_CRYPTO_WALLET_PROFILE_V1:   str = "crypto_wallet_profile_v1"
SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1: str = "crypto_sensitive_backup_v1"
SCHEMA_CRYPTO_NOTE_V1:             str = "crypto_note_v1"

ALL_CRYPTO_SCHEMAS: tuple[str, ...] = (
    SCHEMA_CRYPTO_WALLET_PROFILE_V1,
    SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
    SCHEMA_CRYPTO_NOTE_V1,
)


SECRET_TYPE_SEED_PHRASE:     str = "seed_phrase"
SECRET_TYPE_PRIVATE_KEY:     str = "private_key"
SECRET_TYPE_RECOVERY_PHRASE: str = "recovery_phrase"

ALL_SECRET_TYPES: tuple[str, ...] = (
    SECRET_TYPE_SEED_PHRASE,
    SECRET_TYPE_PRIVATE_KEY,
    SECRET_TYPE_RECOVERY_PHRASE,
)


_SECRET_TYPE_TO_CATEGORY: dict[str, str] = {
    SECRET_TYPE_SEED_PHRASE:     CATEGORY_CRYPTO_SEED_PHRASE,
    SECRET_TYPE_PRIVATE_KEY:     CATEGORY_CRYPTO_PRIVATE_KEY,
    SECRET_TYPE_RECOVERY_PHRASE: CATEGORY_CRYPTO_RECOVERY_PHRASE,
}

_CATEGORY_TO_SECRET_TYPE: dict[str, str] = {
    v: k for k, v in _SECRET_TYPE_TO_CATEGORY.items()
}


ASSET_BTC:        str = "BTC"
ASSET_ETH:        str = "ETH"
ASSET_USDT_TRC20: str = "USDT_TRC20"
ASSET_USDT_ERC20: str = "USDT_ERC20"
ASSET_USDC_ERC20: str = "USDC_ERC20"
ASSET_SOL:        str = "SOL"
ASSET_BNB:        str = "BNB"
ASSET_XMR:        str = "XMR"

ALL_CRYPTO_ASSETS: tuple[str, ...] = (
    ASSET_BTC, ASSET_ETH,
    ASSET_USDT_TRC20, ASSET_USDT_ERC20, ASSET_USDC_ERC20,
    ASSET_SOL, ASSET_BNB, ASSET_XMR,
)


NETWORK_LABEL_FOR_ASSET: dict[str, str] = {
    ASSET_BTC:        "Bitcoin",
    ASSET_ETH:        "Ethereum",
    ASSET_USDT_TRC20: "Tron TRC20",
    ASSET_USDT_ERC20: "Ethereum ERC20",
    ASSET_USDC_ERC20: "Ethereum ERC20",
    ASSET_SOL:        "Solana",
    ASSET_BNB:        "BNB Smart Chain",
    ASSET_XMR:        "Monero",
}


PRIVACY_CHAIN_ASSETS: frozenset[str] = frozenset({ASSET_XMR})


WALLET_LABEL_METAMASK:     str = "MetaMask"
WALLET_LABEL_TRUST_WALLET: str = "Trust Wallet"
WALLET_LABEL_LEDGER:       str = "Ledger"
WALLET_LABEL_TREZOR:       str = "Trezor"
WALLET_LABEL_BINANCE:      str = "Binance"
WALLET_LABEL_COINBASE:     str = "Coinbase"
WALLET_LABEL_CUSTOM:       str = "Custom"

ALL_WALLET_LABELS: tuple[str, ...] = (
    WALLET_LABEL_METAMASK,
    WALLET_LABEL_TRUST_WALLET,
    WALLET_LABEL_LEDGER,
    WALLET_LABEL_TREZOR,
    WALLET_LABEL_BINANCE,
    WALLET_LABEL_COINBASE,
    WALLET_LABEL_CUSTOM,
)


_CATEGORY_TO_SCHEMA: dict[str, str] = {
    CATEGORY_CRYPTO_WALLET_ADDRESS:       SCHEMA_CRYPTO_WALLET_PROFILE_V1,
    CATEGORY_CRYPTO_SEED_PHRASE:          SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
    CATEGORY_CRYPTO_PRIVATE_KEY:          SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
    CATEGORY_CRYPTO_RECOVERY_PHRASE:      SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
    CATEGORY_CRYPTO_NOTE:                 SCHEMA_CRYPTO_NOTE_V1,
    CATEGORY_CRYPTO_TRANSACTION_NOTE:     SCHEMA_CRYPTO_NOTE_V1,
    CATEGORY_CRYPTO_EXCHANGE_NOTE:        SCHEMA_CRYPTO_NOTE_V1,
    CATEGORY_CRYPTO_HARDWARE_WALLET_NOTE: SCHEMA_CRYPTO_NOTE_V1,
}


def schema_for_category(category: Optional[str]) -> Optional[str]:


    if not isinstance(category, str):
        return None
    return _CATEGORY_TO_SCHEMA.get(category)


def is_wallet_profile_schema(schema: Optional[str]) -> bool:
    return schema == SCHEMA_CRYPTO_WALLET_PROFILE_V1


def is_sensitive_backup_schema(schema: Optional[str]) -> bool:
    return schema == SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1


def is_crypto_note_schema(schema: Optional[str]) -> bool:
    return schema == SCHEMA_CRYPTO_NOTE_V1


def is_crypto_schema(schema: Optional[str]) -> bool:
    return schema in ALL_CRYPTO_SCHEMAS


def category_for_secret_type(secret_type: Optional[str]) -> Optional[str]:


    if not isinstance(secret_type, str):
        return None
    return _SECRET_TYPE_TO_CATEGORY.get(secret_type)


def requires_warning_confirmation(schema: Optional[str]) -> bool:


    return is_sensitive_backup_schema(schema)


def requires_warning_confirmation_for_category(
    category: Optional[str],
) -> bool:


    return category in CRYPTO_WARN_CATEGORIES


BALANCE_STATUS_UNAVAILABLE:         str = "unavailable"
BALANCE_STATUS_UNAVAILABLE_PRIVACY: str = "unavailable_privacy"
BALANCE_STATUS_LOOKUP_NOT_CONNECTED: str = "lookup_not_connected"

ALL_BALANCE_STATUSES: tuple[str, ...] = (
    BALANCE_STATUS_UNAVAILABLE,
    BALANCE_STATUS_UNAVAILABLE_PRIVACY,
    BALANCE_STATUS_LOOKUP_NOT_CONNECTED,
)


BALANCE_MESSAGE_UNAVAILABLE: str = "Balance unavailable"
BALANCE_MESSAGE_UNAVAILABLE_PRIVACY: str = (
    "Balance unavailable for Monero privacy addresses."
)
BALANCE_MESSAGE_LOOKUP_NOT_CONNECTED: str = "Balance lookup not connected"


_BALANCE_STATUS_MESSAGES: dict[str, str] = {
    BALANCE_STATUS_UNAVAILABLE:          BALANCE_MESSAGE_UNAVAILABLE,
    BALANCE_STATUS_UNAVAILABLE_PRIVACY:  BALANCE_MESSAGE_UNAVAILABLE_PRIVACY,
    BALANCE_STATUS_LOOKUP_NOT_CONNECTED: BALANCE_MESSAGE_LOOKUP_NOT_CONNECTED,
}


def balance_status_for_asset(asset: Optional[str]) -> str:


    if asset is None:
        return BALANCE_STATUS_LOOKUP_NOT_CONNECTED
    a = asset.strip().upper().replace("-", "_").replace(" ", "_")
    if a in PRIVACY_CHAIN_ASSETS:
        return BALANCE_STATUS_UNAVAILABLE_PRIVACY
    return BALANCE_STATUS_LOOKUP_NOT_CONNECTED


def balance_status_message(status: Optional[str]) -> str:


    if status is None:
        return BALANCE_MESSAGE_UNAVAILABLE
    return _BALANCE_STATUS_MESSAGES.get(status, BALANCE_MESSAGE_UNAVAILABLE)


class CryptoSchemaError(ValueError):
    pass


def _require_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CryptoSchemaError(f"{name} is required")
    return value.strip()


def _coerce_optional_str(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CryptoSchemaError("optional field must be string or None")
    return value


def _require_asset(asset: Any) -> str:
    asset = _require_str("asset", asset)
    if asset not in ALL_CRYPTO_ASSETS:
        raise CryptoSchemaError(f"unknown asset: {asset!r}")
    return asset


def build_wallet_profile_record(
    *,
    asset: str,
    network: Optional[str] = None,
    wallet_label: str,
    public_address: str,
    note: Optional[str] = None,
    balance_status: Optional[str] = None,
) -> dict[str, Any]:


    asset_v = _require_asset(asset)
    label_v = _require_str("walletLabel", wallet_label)
    addr_v  = _require_str("publicAddress", public_address)
    net_v   = (
        network.strip() if isinstance(network, str) and network.strip()
        else NETWORK_LABEL_FOR_ASSET.get(asset_v, asset_v)
    )
    note_v   = _coerce_optional_str(note)
    status_v = balance_status or balance_status_for_asset(asset_v)
    if status_v not in ALL_BALANCE_STATUSES:
        raise CryptoSchemaError(f"unknown balanceStatus: {status_v!r}")
    return {
        "schema":        SCHEMA_CRYPTO_WALLET_PROFILE_V1,
        "asset":         asset_v,
        "network":       net_v,
        "walletLabel":   label_v,
        "publicAddress": addr_v,
        "note":          note_v,
        "balanceStatus": status_v,
    }


def build_sensitive_backup_record(
    *,
    asset: Optional[str] = None,
    network: Optional[str] = None,
    wallet_label: str,
    secret_type: str,
    secret_value: str,
    note: Optional[str] = None,
    warning_confirmed: bool,
) -> dict[str, Any]:


    if warning_confirmed is not True:
        raise CryptoSchemaError(
            "sensitive backup requires warningConfirmed=True",
        )
    if secret_type not in ALL_SECRET_TYPES:
        raise CryptoSchemaError(f"unknown secretType: {secret_type!r}")
    label_v  = _require_str("walletLabel", wallet_label)
    value_v  = _require_str("secretValue", secret_value)
    asset_v  = asset and asset.strip()
    if asset_v and asset_v not in ALL_CRYPTO_ASSETS:
        raise CryptoSchemaError(f"unknown asset: {asset!r}")
    net_v = (
        network.strip() if isinstance(network, str) and network.strip()
        else (NETWORK_LABEL_FOR_ASSET.get(asset_v, "") if asset_v else "")
    )
    note_v = _coerce_optional_str(note)
    return {
        "schema":           SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1,
        "asset":            asset_v or "",
        "network":          net_v,
        "walletLabel":      label_v,
        "secretType":       secret_type,
        "secretValue":      value_v,
        "note":             note_v,
        "warningConfirmed": True,
    }


NOTE_TYPE_GENERAL:          str = "general"
NOTE_TYPE_TRANSACTION_NOTE: str = "transaction_note"

ALL_NOTE_TYPES: tuple[str, ...] = (
    NOTE_TYPE_GENERAL,
    NOTE_TYPE_TRANSACTION_NOTE,
)


def build_crypto_note_record(
    *,
    asset: Optional[str] = None,
    network: Optional[str] = None,
    title: str,
    note: str,
    note_type: str = NOTE_TYPE_GENERAL,
    wallet_label: Optional[str] = None,
    tx_hash: Optional[str] = None,
    amount_text: Optional[str] = None,
    date_text: Optional[str] = None,
) -> dict[str, Any]:


    if note_type not in ALL_NOTE_TYPES:
        raise CryptoSchemaError(f"unknown noteType: {note_type!r}")
    title_v = _require_str("title", title)
    note_v  = _require_str("note", note)
    asset_v = asset and asset.strip()
    if asset_v and asset_v not in ALL_CRYPTO_ASSETS:
        raise CryptoSchemaError(f"unknown asset: {asset!r}")
    net_v = (
        network.strip() if isinstance(network, str) and network.strip()
        else (NETWORK_LABEL_FOR_ASSET.get(asset_v, "") if asset_v else "")
    )
    return {
        "schema":      SCHEMA_CRYPTO_NOTE_V1,
        "asset":       asset_v or "",
        "network":     net_v,
        "title":       title_v,
        "note":        note_v,
        "noteType":    note_type,
        "walletLabel": _coerce_optional_str(wallet_label),
                                                              
                                                                  
        "txHash":      _coerce_optional_str(tx_hash),
        "amountText":  _coerce_optional_str(amount_text),
        "dateText":    _coerce_optional_str(date_text),
    }


def category_for_note_type(note_type: Optional[str]) -> Optional[str]:


    if note_type == NOTE_TYPE_GENERAL:
        return CATEGORY_CRYPTO_NOTE
    if note_type == NOTE_TYPE_TRANSACTION_NOTE:
        return CATEGORY_CRYPTO_TRANSACTION_NOTE
    return None


def is_receive_qr_eligible(
    record: Optional[Mapping[str, Any]],
) -> bool:


    if not isinstance(record, Mapping):
        return False
    if not is_wallet_profile_schema(record.get("schema")):
        return False
    pa = record.get("publicAddress")
    return isinstance(pa, str) and bool(pa.strip())


def annotate_crypto_record(
    record: dict[str, Any],
    *,
    category: Optional[str],
    warning_confirmed: Optional[bool] = None,
) -> dict[str, Any]:


    if not isinstance(record, dict):
        return record
    schema = schema_for_category(category)
    if schema is None:
        return record
    record["schema"] = schema
    if is_sensitive_backup_schema(schema):
        if warning_confirmed is not True:
            raise CryptoSchemaError(
                "sensitive backup persistence requires "
                "warning_confirmed=True at the save boundary",
            )
        record["warningConfirmed"] = True
    return record


REDACTED_PLACEHOLDER: str = "***"


SECRET_FIELDS: frozenset[str] = frozenset({
    "secretValue",
    "seed_phrase",
    "private_key",
    "recovery_phrase",
                                                                 
                                                                
    "value",
})


PUBLIC_ADDRESS_FIELDS: frozenset[str] = frozenset({
    "publicAddress",
    "wallet_address",
})


ALL_REDACTED_FIELDS: frozenset[str] = (
    SECRET_FIELDS | PUBLIC_ADDRESS_FIELDS
)


def redact_crypto_payload(
    payload: Optional[Mapping[str, Any]],
    *,
    extra_keys: Optional[Iterable[str]] = None,
) -> dict[str, Any]:


    if not isinstance(payload, Mapping):
        return {}
    keys_to_redact = set(ALL_REDACTED_FIELDS)
    if extra_keys:
        keys_to_redact.update(extra_keys)
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k in keys_to_redact:
            out[k] = REDACTED_PLACEHOLDER
            continue
        if isinstance(v, Mapping):
            out[k] = redact_crypto_payload(v, extra_keys=extra_keys)
            continue
        if isinstance(v, list):
            out[k] = [
                redact_crypto_payload(item, extra_keys=extra_keys)
                if isinstance(item, Mapping)
                else item
                for item in v
            ]
            continue
        out[k] = v
    return out


__all__ = [
             
    "SCHEMA_CRYPTO_WALLET_PROFILE_V1",
    "SCHEMA_CRYPTO_SENSITIVE_BACKUP_V1",
    "SCHEMA_CRYPTO_NOTE_V1",
    "ALL_CRYPTO_SCHEMAS",
                  
    "SECRET_TYPE_SEED_PHRASE",
    "SECRET_TYPE_PRIVATE_KEY",
    "SECRET_TYPE_RECOVERY_PHRASE",
    "ALL_SECRET_TYPES",
                                
    "ASSET_BTC", "ASSET_ETH",
    "ASSET_USDT_TRC20", "ASSET_USDT_ERC20", "ASSET_USDC_ERC20",
    "ASSET_SOL", "ASSET_BNB", "ASSET_XMR",
    "ALL_CRYPTO_ASSETS", "NETWORK_LABEL_FOR_ASSET",
    "PRIVACY_CHAIN_ASSETS",
    "WALLET_LABEL_METAMASK", "WALLET_LABEL_TRUST_WALLET",
    "WALLET_LABEL_LEDGER", "WALLET_LABEL_TREZOR",
    "WALLET_LABEL_BINANCE", "WALLET_LABEL_COINBASE",
    "WALLET_LABEL_CUSTOM", "ALL_WALLET_LABELS",
             
    "schema_for_category",
    "is_wallet_profile_schema", "is_sensitive_backup_schema",
    "is_crypto_note_schema", "is_crypto_schema",
    "requires_warning_confirmation",
    "requires_warning_confirmation_for_category",
             
    "BALANCE_STATUS_UNAVAILABLE",
    "BALANCE_STATUS_UNAVAILABLE_PRIVACY",
    "BALANCE_STATUS_LOOKUP_NOT_CONNECTED",
    "ALL_BALANCE_STATUSES",
    "BALANCE_MESSAGE_UNAVAILABLE",
    "BALANCE_MESSAGE_UNAVAILABLE_PRIVACY",
    "BALANCE_MESSAGE_LOOKUP_NOT_CONNECTED",
    "balance_status_for_asset",
    "balance_status_message",
              
    "CryptoSchemaError",
    "build_wallet_profile_record",
    "build_sensitive_backup_record",
    "build_crypto_note_record",
    "category_for_note_type",
    "NOTE_TYPE_GENERAL", "NOTE_TYPE_TRANSACTION_NOTE",
    "ALL_NOTE_TYPES",
                     
    "is_receive_qr_eligible",
                     
    "annotate_crypto_record",
               
    "REDACTED_PLACEHOLDER",
    "SECRET_FIELDS", "PUBLIC_ADDRESS_FIELDS", "ALL_REDACTED_FIELDS",
    "redact_crypto_payload",
]
