

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional


SCHEMA_CRYPTO_WALLET_ACCOUNT_V1:     str = "crypto_wallet_account_v1"
SCHEMA_CRYPTO_WALLET_BALANCE_V1:     str = "crypto_wallet_balance_v1"
SCHEMA_CRYPTO_WALLET_TRANSACTION_V1: str = "crypto_wallet_transaction_v1"

ALL_WALLET_ENGINE_SCHEMAS: tuple[str, ...] = (
    SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
    SCHEMA_CRYPTO_WALLET_BALANCE_V1,
    SCHEMA_CRYPTO_WALLET_TRANSACTION_V1,
)


KEY_ORIGIN_GENERATED_CLIENT_SIDE: str = "generated_client_side"
KEY_ORIGIN_IMPORTED_CLIENT_SIDE:  str = "imported_client_side"

ALL_KEY_ORIGINS: tuple[str, ...] = (
    KEY_ORIGIN_GENERATED_CLIENT_SIDE,
    KEY_ORIGIN_IMPORTED_CLIENT_SIDE,
)


SIGNING_MODE_CLIENT_SIDE: str = "client_side"

ALL_SIGNING_MODES: tuple[str, ...] = (
    SIGNING_MODE_CLIENT_SIDE,
)


BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED: str = "encrypted_backup_saved"
BACKUP_STATUS_NO_BACKUP:              str = "no_backup"

ALL_BACKUP_STATUSES: tuple[str, ...] = (
    BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
    BACKUP_STATUS_NO_BACKUP,
)


WALLET_BALANCE_STATUS_AVAILABLE:   str = "available"
WALLET_BALANCE_STATUS_UNAVAILABLE: str = "unavailable"
WALLET_BALANCE_STATUS_UNSUPPORTED: str = "unsupported"

ALL_WALLET_BALANCE_STATUSES: tuple[str, ...] = (
    WALLET_BALANCE_STATUS_AVAILABLE,
    WALLET_BALANCE_STATUS_UNAVAILABLE,
    WALLET_BALANCE_STATUS_UNSUPPORTED,
)


TRANSACTION_DIRECTION_INCOMING: str = "incoming"
TRANSACTION_DIRECTION_OUTGOING: str = "outgoing"

ALL_TRANSACTION_DIRECTIONS: tuple[str, ...] = (
    TRANSACTION_DIRECTION_INCOMING,
    TRANSACTION_DIRECTION_OUTGOING,
)


TRANSACTION_STATUS_PENDING:   str = "pending"
TRANSACTION_STATUS_CONFIRMED: str = "confirmed"
TRANSACTION_STATUS_FAILED:    str = "failed"

ALL_TRANSACTION_STATUSES: tuple[str, ...] = (
    TRANSACTION_STATUS_PENDING,
    TRANSACTION_STATUS_CONFIRMED,
    TRANSACTION_STATUS_FAILED,
)


ENGINE_STATUS_DISABLED:    str = "engine_disabled"
ENGINE_STATUS_UNSUPPORTED: str = "unsupported_asset"
ENGINE_STATUS_NOT_READY:   str = "engine_not_ready"

ENGINE_MESSAGE_DISABLED: str = (
    "The Crypto Wallet Engine is not yet enabled. "
    "Crypto Vault Lite remains available for saved public "
    "addresses, encrypted backups, and manual notes."
)
ENGINE_MESSAGE_UNSUPPORTED_ASSET: str = (
    "This asset is not yet supported by the Crypto Wallet Engine."
)
ENGINE_MESSAGE_NOT_READY: str = (
    "This operation is not yet implemented by the Crypto Wallet "
    "Engine. The skeleton route exists for forward compatibility "
    "but the underlying capability ships in a later slice."
)


def engine_disabled_envelope(
    *,
    status: str = ENGINE_STATUS_DISABLED,
    message: Optional[str] = None,
) -> dict[str, Any]:


    if status not in (
        ENGINE_STATUS_DISABLED,
        ENGINE_STATUS_UNSUPPORTED,
        ENGINE_STATUS_NOT_READY,
    ):
        status = ENGINE_STATUS_DISABLED
    if message is None:
        if status == ENGINE_STATUS_DISABLED:
            message = ENGINE_MESSAGE_DISABLED
        elif status == ENGINE_STATUS_UNSUPPORTED:
            message = ENGINE_MESSAGE_UNSUPPORTED_ASSET
        else:
            message = ENGINE_MESSAGE_NOT_READY
    return {
        "wallet_engine": status,
        "message":       message,
    }


ASSET_ROLLOUT_PHASE: dict[str, int] = {
    "ETH":        1,
    "USDT_ERC20": 3,
    "USDC_ERC20": 3,
    "BTC":        5,
    "SOL":        6,
    "BNB":        6,
    "USDT_TRC20": 6,
    "XMR":        7,
}


WALLET_ENGINE_ASSETS: tuple[str, ...] = (
    "ETH",
    "USDT_ERC20",
    "USDC_ERC20",
    "BTC",
    "SOL",
    "BNB",
    "USDT_TRC20",
    "XMR",
)


SPECIAL_DESIGN_ASSETS: frozenset[str] = frozenset({"XMR"})


def asset_is_wallet_engine_supported(asset: Optional[str]) -> bool:


    if not isinstance(asset, str):
        return False
    return asset.strip().upper() in WALLET_ENGINE_ASSETS


def asset_rollout_phase(asset: Optional[str]) -> Optional[int]:


    if not isinstance(asset, str):
        return None
    return ASSET_ROLLOUT_PHASE.get(asset.strip().upper())


PLAINTEXT_KEY_FIELD_NAMES: frozenset[str] = frozenset({
    "private_key",
    "privatekey",
    "privatekeyhex",
    "priv_key",
    "privkey",
    "seed_phrase",
    "seedphrase",
    "seed",
    "seed25",
    "polyseed",
    "monero_seed",
    "moneroseed",
    "mnemonic",
    "mnemonic_phrase",
    "mnemonicphrase",
    "recovery_phrase",
    "recoveryphrase",
    "xprv",
    "xpriv",
    "x_priv",
    "wif",
    "key_material",
    "secret_key",
    "secretkey",
    "raw_key",
    "rawkey",
    "spendable_key",
    "spendablekey",
    "spend_key",
    "spendkey",
    "private_spend_key",
    "privatespendkey",
    "xmr_spend_key",
    "xmrspendkey",
    "monero_spend_key",
    "monerospendkey",
    "view_key",
    "viewkey",
    "private_view_key",
    "privateviewkey",
    "xmr_view_key",
    "xmrviewkey",
    "monero_view_key",
    "moneroviewkey",
    "secret_spend_key",
    "secretspendkey",
    "secret_view_key",
    "secretviewkey",
    "wallet_password",
    "walletpassword",
})


def _normalize_field_name(name: Any) -> str:


    if not isinstance(name, str):
        return ""
    return "".join(c for c in name.lower() if c.isalnum())


PLAINTEXT_KEY_SUBSTRING_MARKERS: frozenset[str] = frozenset({
    "privatekey",
    "secretkey",
    "seedphrase",
    "mnemonic",
    "recoveryphrase",
    "spendablekey",
    "spendkey",
    "viewkey",
    "polyseed",
    "walletpassword",
})


def is_plaintext_key_field(name: Any) -> bool:


    norm = _normalize_field_name(name)
    if not norm:
        return False

    if norm in {_normalize_field_name(n) for n in PLAINTEXT_KEY_FIELD_NAMES}:
        return True
    for marker in PLAINTEXT_KEY_SUBSTRING_MARKERS:
        if marker in norm:
            return True
    return False


def find_plaintext_key_fields(
    payload: Optional[Mapping[str, Any]],
) -> list[str]:


    found: list[str] = []
    if not isinstance(payload, Mapping):
        return found
    for k, v in payload.items():
        if is_plaintext_key_field(k):
            found.append(str(k))
        if isinstance(v, Mapping):
            found.extend(find_plaintext_key_fields(v))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, Mapping):
                    found.extend(find_plaintext_key_fields(item))
    return found


class PlaintextKeyRejected(ValueError):


    def __init__(self, field_names: list[str]) -> None:
        self.field_names = list(field_names)
        super().__init__(
            "Wallet-engine routes refuse plaintext key fields: "
            f"{', '.join(sorted(set(field_names)))}",
        )


def rejects_plaintext_secret(payload: Optional[Mapping[str, Any]]) -> None:


    bad = find_plaintext_key_fields(payload)
    if bad:
        raise PlaintextKeyRejected(bad)


class WalletEngineSchemaError(ValueError):
    pass


def _require_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WalletEngineSchemaError(f"{name} is required")
    return value.strip()


def build_wallet_account_record(
    *,
    asset: str,
    network: str,
    wallet_label: str,
    public_address: str,
    encrypted_wallet_secret: str,
    key_origin: str = KEY_ORIGIN_GENERATED_CLIENT_SIDE,
    signing_mode: str = SIGNING_MODE_CLIENT_SIDE,
    backup_status: str = BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
) -> dict[str, Any]:


    if key_origin not in ALL_KEY_ORIGINS:
        raise WalletEngineSchemaError(
            f"unknown keyOrigin: {key_origin!r}",
        )
    if signing_mode not in ALL_SIGNING_MODES:
        raise WalletEngineSchemaError(
            f"unknown signingMode: {signing_mode!r}",
        )
    if backup_status not in ALL_BACKUP_STATUSES:
        raise WalletEngineSchemaError(
            f"unknown backupStatus: {backup_status!r}",
        )
    return {
        "schema":                SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
        "asset":                 _require_str("asset", asset),
        "network":               _require_str("network", network),
        "walletLabel":           _require_str("walletLabel", wallet_label),
        "publicAddress":         _require_str("publicAddress", public_address),
        "encryptedWalletSecret": _require_str(
            "encryptedWalletSecret", encrypted_wallet_secret,
        ),
        "keyOrigin":             key_origin,
        "signingMode":           signing_mode,
        "backupStatus":          backup_status,
    }


def build_wallet_balance_record(
    *,
    asset: str,
    network: str,
    public_address: str,
    balance_status: str,
    available_amount: Optional[str] = None,
    unit: Optional[str] = None,
    updated_at: Optional[str] = None,
) -> dict[str, Any]:


    if balance_status not in ALL_WALLET_BALANCE_STATUSES:
        raise WalletEngineSchemaError(
            f"unknown balanceStatus: {balance_status!r}",
        )
    if balance_status != WALLET_BALANCE_STATUS_AVAILABLE and (
        available_amount or unit
    ):
        raise WalletEngineSchemaError(
            "availableAmount / unit only allowed when "
            "balanceStatus is 'available'",
        )
    return {
        "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
        "asset":           _require_str("asset", asset),
        "network":         _require_str("network", network),
        "publicAddress":   _require_str("publicAddress", public_address),
        "balanceStatus":   balance_status,
        "availableAmount": available_amount,
        "unit":            unit,
        "updatedAt":       updated_at,
    }


def build_wallet_transaction_record(
    *,
    asset: str,
    network: str,
    public_address: str,
    tx_hash: str,
    direction: str,
    amount: str,
    unit: str,
    status: str,
    confirmations: int = 0,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:


    if direction not in ALL_TRANSACTION_DIRECTIONS:
        raise WalletEngineSchemaError(
            f"unknown direction: {direction!r}",
        )
    if status not in ALL_TRANSACTION_STATUSES:
        raise WalletEngineSchemaError(
            f"unknown status: {status!r}",
        )
    if not isinstance(confirmations, int) or confirmations < 0:
        raise WalletEngineSchemaError(
            "confirmations must be a non-negative integer",
        )
    return {
        "schema":        SCHEMA_CRYPTO_WALLET_TRANSACTION_V1,
        "asset":         _require_str("asset", asset),
        "network":       _require_str("network", network),
        "publicAddress": _require_str("publicAddress", public_address),
        "txHash":        _require_str("txHash", tx_hash),
        "direction":     direction,
        "amount":        _require_str("amount", amount),
        "unit":          _require_str("unit", unit),
        "status":        status,
        "confirmations": confirmations,
        "timestamp":     timestamp,
    }


__all__ = [
             
    "SCHEMA_CRYPTO_WALLET_ACCOUNT_V1",
    "SCHEMA_CRYPTO_WALLET_BALANCE_V1",
    "SCHEMA_CRYPTO_WALLET_TRANSACTION_V1",
    "ALL_WALLET_ENGINE_SCHEMAS",
                    
    "KEY_ORIGIN_GENERATED_CLIENT_SIDE",
    "KEY_ORIGIN_IMPORTED_CLIENT_SIDE",
    "ALL_KEY_ORIGINS",
    "SIGNING_MODE_CLIENT_SIDE",
    "ALL_SIGNING_MODES",
    "BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED",
    "BACKUP_STATUS_NO_BACKUP",
    "ALL_BACKUP_STATUSES",
    "WALLET_BALANCE_STATUS_AVAILABLE",
    "WALLET_BALANCE_STATUS_UNAVAILABLE",
    "WALLET_BALANCE_STATUS_UNSUPPORTED",
    "ALL_WALLET_BALANCE_STATUSES",
    "TRANSACTION_DIRECTION_INCOMING",
    "TRANSACTION_DIRECTION_OUTGOING",
    "ALL_TRANSACTION_DIRECTIONS",
    "TRANSACTION_STATUS_PENDING",
    "TRANSACTION_STATUS_CONFIRMED",
    "TRANSACTION_STATUS_FAILED",
    "ALL_TRANSACTION_STATUSES",
                            
    "ENGINE_STATUS_DISABLED",
    "ENGINE_STATUS_UNSUPPORTED",
    "ENGINE_STATUS_NOT_READY",
    "ENGINE_MESSAGE_DISABLED",
    "ENGINE_MESSAGE_UNSUPPORTED_ASSET",
    "ENGINE_MESSAGE_NOT_READY",
    "engine_disabled_envelope",
                   
    "ASSET_ROLLOUT_PHASE",
    "WALLET_ENGINE_ASSETS",
    "SPECIAL_DESIGN_ASSETS",
    "asset_is_wallet_engine_supported",
    "asset_rollout_phase",
                             
    "PLAINTEXT_KEY_FIELD_NAMES",
    "is_plaintext_key_field",
    "find_plaintext_key_fields",
    "rejects_plaintext_secret",
    "PlaintextKeyRejected",
              
    "WalletEngineSchemaError",
    "build_wallet_account_record",
    "build_wallet_balance_record",
    "build_wallet_transaction_record",
]
