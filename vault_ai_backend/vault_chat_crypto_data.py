"""Safe live-data projections for Crypto Vault chat cards.

The vault_chat_router delegates crypto messages to the
`crypto_vault_chat_control` module, which returns a card shell with
`liveFetchRequired=true`. This module POPULATES the inner card with
safe live data from the existing Crypto Vault services — WITHOUT
duplicating any wallet cryptography, key handling, or provider
call.

Split of responsibility:

  * FAST / LOCAL (populated here in /chat):
      - Asset metadata (network id, receive-enabled, send-enabled)
      - Receive addresses (deterministic, read from vault records)
      - XMR scanner status (platform + config check)
      - Send-draft safety flags
      - USDT ambiguity flag (already carried by classifier)

  * SLOW / NETWORK (deferred to frontend live fetch on card mount):
      - Balance numbers (EVM RPC, Solana RPC, TRON API, XMR scan)
      - Transaction history (indexer / RPC)
    These carry `balanceStatus='pending_live_fetch'` /
    `activityStatus='pending_live_fetch'` — the frontend then uses
    the existing endpoints to populate.

Safety invariants (enforced by tests):

  1. No card data payload EVER carries a private key, seed phrase,
     mnemonic, private view/spend key, encrypted wallet secret,
     auth token, or API key.
  2. `canBroadcast=false` on every send-draft card at BOTH the
     backend envelope and the frontend parser layer.
  3. No fake balance number. If we cannot obtain a real result,
     `balanceStatus='unavailable'` or `'pending_live_fetch'`. We
     NEVER emit `displayBalance='0'` unless the provider actually
     returned zero.
  4. XMR balance/activity NEVER carry a number in this module —
     they carry only scanner status. The frontend fetches the real
     balance if the scanner is ready.
  5. Every crypto data payload is versioned with a schema string.
     Frontend parsers check the schema.
  6. Refusal / clarify / unrecognized inner cards are LEFT ALONE.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)



CRYPTO_VAULT_OVERVIEW_DATA_SCHEMA:  str = "crypto_vault_overview_data_v1"
CRYPTO_BALANCE_DATA_SCHEMA:         str = "crypto_balance_data_v1"
CRYPTO_RECEIVE_DATA_SCHEMA:         str = "crypto_receive_data_v1"
CRYPTO_SCANNER_STATUS_DATA_SCHEMA:  str = "crypto_scanner_status_data_v1"
CRYPTO_ACTIVITY_DATA_SCHEMA:        str = "crypto_activity_data_v1"
CRYPTO_SEND_DRAFT_DATA_SCHEMA:      str = "crypto_send_draft_data_v1"



BALANCE_STATUS_PENDING_LIVE_FETCH: str = "pending_live_fetch"
BALANCE_STATUS_AVAILABLE:          str = "available"
BALANCE_STATUS_UNAVAILABLE:        str = "unavailable"
BALANCE_STATUS_SCANNER_GATED:      str = "scanner_gated"
BALANCE_STATUS_REQUIRES_DESKTOP:   str = "requires_desktop"


ACTIVITY_STATUS_PENDING_LIVE_FETCH: str = "pending_live_fetch"
ACTIVITY_STATUS_AVAILABLE:          str = "available"
ACTIVITY_STATUS_UNAVAILABLE:        str = "unavailable"
ACTIVITY_STATUS_SCANNER_GATED:      str = "scanner_gated"



REASON_CREATE_WALLET_FIRST:  str = "create_wallet_first"
REASON_ASSET_NOT_ENABLED:    str = "asset_not_enabled"
REASON_SCANNER_NOT_ENABLED:  str = "scanner_not_enabled"
REASON_SCANNER_REQUIRES_DESKTOP: str = "scanner_requires_desktop"
REASON_INTERNAL_ERROR:       str = "internal_error"



ASSET_ETH:        str = "ETH"
ASSET_USDT_ERC20: str = "USDT_ERC20"
ASSET_USDC_ERC20: str = "USDC_ERC20"
ASSET_SOL:        str = "SOL"
ASSET_USDT_TRC20: str = "USDT_TRC20"
ASSET_XMR:        str = "XMR"


ASSET_LABELS: dict[str, str] = {
    ASSET_ETH:        "ETH",
    ASSET_USDT_ERC20: "USDT (ERC20)",
    ASSET_USDC_ERC20: "USDC (ERC20)",
    ASSET_SOL:        "SOL",
    ASSET_USDT_TRC20: "USDT (TRC20)",
    ASSET_XMR:        "XMR",
}

ASSET_NETWORKS: dict[str, str] = {
    ASSET_ETH:        "ethereum",
    ASSET_USDT_ERC20: "ethereum",
    ASSET_USDC_ERC20: "ethereum",
    ASSET_SOL:        "solana",
    ASSET_USDT_TRC20: "tron",
    ASSET_XMR:        "monero",
}

ALL_ASSETS: tuple[str, ...] = (
    ASSET_ETH, ASSET_USDT_ERC20, ASSET_USDC_ERC20,
    ASSET_SOL, ASSET_USDT_TRC20, ASSET_XMR,
)



_FORBIDDEN_CRYPTO_KEYS: frozenset[str] = frozenset({

    "privateKey", "private_key",
    "privateViewKey", "private_view_key",
    "privateSpendKey", "private_spend_key",
    "seed", "seed_phrase", "seedPhrase",
    "mnemonic", "mnemonic_words",
    "polyseed",


    "encryptedWalletSecret", "encrypted_wallet_secret",
    "encrypted_secret", "encryptedSecret",


    "authToken", "auth_token", "apiKey", "api_key",
    "stripeSecretKey", "stripe_secret_key",


    "pin", "pinHash", "pin_hash",


    "signedTxHex", "signed_tx_hex", "signedRawTransaction",
    "privateSpendKeyHex", "spendKey", "viewKey",
})


def _strip_forbidden(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_forbidden(v)
            for k, v in obj.items()
            if k not in _FORBIDDEN_CRYPTO_KEYS
        }
    if isinstance(obj, list):
        return [_strip_forbidden(x) for x in obj]
    return obj




def _receive_address_for(
    vault_id: str, asset: str,
) -> Optional[dict[str, Any]]:

    try:
        from routes.crypto_wallet_routes import (
            _load_wallet_account_record_network,
        )
        from evm_networks import (
            NETWORK_ETHEREUM_MAINNET, NETWORK_MONERO_MAINNET,
        )

        try:
            from evm_networks import NETWORK_SOLANA_MAINNET
        except Exception:
            NETWORK_SOLANA_MAINNET = "solana_mainnet"
        try:
            from evm_networks import NETWORK_TRON_MAINNET
        except Exception:
            NETWORK_TRON_MAINNET = "tron_mainnet"
    except Exception:
        return None

    net_map = {
        ASSET_ETH:        NETWORK_ETHEREUM_MAINNET,
        ASSET_USDT_ERC20: NETWORK_ETHEREUM_MAINNET,
        ASSET_USDC_ERC20: NETWORK_ETHEREUM_MAINNET,
        ASSET_SOL:        NETWORK_SOLANA_MAINNET,
        ASSET_USDT_TRC20: NETWORK_TRON_MAINNET,
        ASSET_XMR:        NETWORK_MONERO_MAINNET,
    }
    network_id = net_map.get(asset)
    if not network_id:
        return None
    try:
        record = _load_wallet_account_record_network(
            vault_id, asset, network_id,
        )
    except Exception:
        logger.exception(
            "[vault_chat_crypto_data] receive_address lookup failed "
            "vault=%s asset=%s",
            (vault_id or "")[:8] + "...", asset,
        )
        return None
    if not record:
        return None
    return {
        "publicAddress": str(record.get("publicAddress") or ""),
        "walletLabel":   str(record.get("walletLabel") or ""),
    }




def _xmr_scanner_status(
    client_platform: Optional[str] = None,
) -> dict[str, Any]:
    try:
        from xmr_scanner import (
            get_monero_scanner_adapter,
        )
        adapter = get_monero_scanner_adapter(
            client_platform=client_platform,
        )
        envelope = adapter.get_status()

        try:

            import vault_config
            _mode_fn = getattr(
                vault_config, "monero_scanner_mode", None,
            )
            envelope["mode"] = _mode_fn() if _mode_fn else None
        except Exception:
            envelope["mode"] = None
        return envelope
    except Exception:
        logger.exception(
            "[vault_chat_crypto_data] xmr_scanner_status lookup failed",
        )
        return {
            "scannerStatus":   "unavailable",
            "reason":          REASON_INTERNAL_ERROR,
            "canShowBalance":  False,
            "canShowActivity": False,
            "canSend":         False,
        }



def build_crypto_overview_data(
    vault_id: str,
    *,
    client_platform: Optional[str] = None,
) -> dict[str, Any]:

    if not vault_id:
        return {
            "schema":            CRYPTO_VAULT_OVERVIEW_DATA_SCHEMA,
            "available":         False,
            "unavailable_reason": "missing_dependency",
        }
    try:
        assets: list[dict[str, Any]] = []
        unavailable_count = 0

        for asset in ALL_ASSETS:
            recv = _receive_address_for(vault_id, asset)
            receive_ready = bool(recv and recv.get("publicAddress"))
            send_enabled = asset != ASSET_XMR
            balance_status = BALANCE_STATUS_PENDING_LIVE_FETCH
            reason: Optional[str] = None
            if asset == ASSET_XMR:

                xmr = _xmr_scanner_status(client_platform)
                if not xmr.get("canShowBalance", False):
                    balance_status = BALANCE_STATUS_SCANNER_GATED
                    reason = xmr.get("reason") or "scanner_gated"
                    unavailable_count += 1
            if not receive_ready:

                if balance_status == BALANCE_STATUS_PENDING_LIVE_FETCH:
                    balance_status = BALANCE_STATUS_UNAVAILABLE
                    reason = reason or REASON_CREATE_WALLET_FIRST
                unavailable_count += 1
            assets.append({
                "asset":         asset,
                "label":         ASSET_LABELS.get(asset, asset),
                "network":       ASSET_NETWORKS.get(asset, ""),
                "balanceStatus": balance_status,
                "reason":        reason,
                "receiveReady":  receive_ready,
                "sendEnabled":   send_enabled,

                "publicAddress": (
                    recv.get("publicAddress") if recv else None
                ),
            })


        xmr_status = _xmr_scanner_status(client_platform)
        return {
            "schema":            CRYPTO_VAULT_OVERVIEW_DATA_SCHEMA,
            "available":         True,
            "assets":            assets,
            "unavailableCount":  unavailable_count,
            "xmrScannerStatus":  xmr_status.get("scannerStatus"),
            "xmrReason":         xmr_status.get("reason"),
            "xmrCanShowBalance": bool(
                xmr_status.get("canShowBalance"),
            ),
            "xmrMode":           xmr_status.get("mode"),
        }
    except Exception:
        logger.exception(
            "[vault_chat_crypto_data] build_crypto_overview_data failed",
        )
        return {
            "schema":             CRYPTO_VAULT_OVERVIEW_DATA_SCHEMA,
            "available":          False,
            "unavailable_reason": REASON_INTERNAL_ERROR,
        }



def build_crypto_balance_data(
    vault_id: str, asset: str,
    *,
    client_platform: Optional[str] = None,
) -> dict[str, Any]:

    if not asset:
        return {
            "schema":            CRYPTO_BALANCE_DATA_SCHEMA,
            "available":         False,
            "unavailable_reason": "missing_asset",
        }
    label = ASSET_LABELS.get(asset, asset)
    network = ASSET_NETWORKS.get(asset, "")


    if asset == ASSET_XMR:
        xmr = _xmr_scanner_status(client_platform)
        can_show = bool(xmr.get("canShowBalance"))
        if can_show:
            return {
                "schema":         CRYPTO_BALANCE_DATA_SCHEMA,
                "available":      True,
                "asset":          asset,
                "label":          label,
                "network":        network,
                "balanceStatus":  BALANCE_STATUS_PENDING_LIVE_FETCH,
                "liveFetchRequired": True,
            }

        reason = xmr.get("reason") or REASON_SCANNER_NOT_ENABLED
        return {
            "schema":        CRYPTO_BALANCE_DATA_SCHEMA,
            "available":     True,
            "asset":         asset,
            "label":         label,
            "network":       network,
            "balanceStatus": BALANCE_STATUS_SCANNER_GATED,
            "reason":        reason,
            "scannerStatus": xmr.get("scannerStatus"),
        }


    recv = _receive_address_for(vault_id, asset)
    return {
        "schema":            CRYPTO_BALANCE_DATA_SCHEMA,
        "available":         True,
        "asset":             asset,
        "label":             label,
        "network":           network,
        "balanceStatus":     BALANCE_STATUS_PENDING_LIVE_FETCH,
        "liveFetchRequired": True,

        "publicAddress":     (
            recv.get("publicAddress") if recv else None
        ),
    }



def build_crypto_receive_data(
    vault_id: str, asset: str,
    *,
    include_qr: bool = False,
) -> dict[str, Any]:

    if not asset:
        return {
            "schema":            CRYPTO_RECEIVE_DATA_SCHEMA,
            "available":         False,
            "unavailable_reason": "missing_asset",
        }
    label = ASSET_LABELS.get(asset, asset)
    network = ASSET_NETWORKS.get(asset, "")
    recv = _receive_address_for(vault_id, asset)
    if not recv or not recv.get("publicAddress"):
        return {
            "schema":       CRYPTO_RECEIVE_DATA_SCHEMA,
            "available":    True,
            "asset":        asset,
            "label":        label,
            "network":      network,
            "receiveReady": False,
            "reason":       REASON_CREATE_WALLET_FIRST,
        }
    address = recv["publicAddress"]
    result: dict[str, Any] = {
        "schema":        CRYPTO_RECEIVE_DATA_SCHEMA,
        "available":     True,
        "asset":         asset,
        "label":         label,
        "network":       network,
        "receiveReady":  True,
        "publicAddress": address,
        "walletLabel":   str(recv.get("walletLabel") or ""),
        "warning":       f"Only send {label} on {network} "
                         f"to this address.",
    }
    if include_qr:

        result["qrPayload"] = address
    return result



def build_crypto_scanner_status_data(
    *,
    client_platform: Optional[str] = None,
) -> dict[str, Any]:

    xmr = _xmr_scanner_status(client_platform)
    return {
        "schema":          CRYPTO_SCANNER_STATUS_DATA_SCHEMA,
        "available":       True,
        "asset":           ASSET_XMR,
        "scannerStatus":   xmr.get("scannerStatus"),
        "reason":          xmr.get("reason"),
        "message":         xmr.get("message"),
        "canShowBalance":  bool(xmr.get("canShowBalance")),
        "canShowActivity": bool(xmr.get("canShowActivity")),

        "canSend":         False,
        "mode":            xmr.get("mode"),
    }



def build_crypto_activity_data(
    vault_id: str, asset: Optional[str] = None,
    *,
    client_platform: Optional[str] = None,
) -> dict[str, Any]:


    if asset == ASSET_XMR:
        xmr = _xmr_scanner_status(client_platform)
        if not xmr.get("canShowActivity"):
            return {
                "schema":         CRYPTO_ACTIVITY_DATA_SCHEMA,
                "available":      True,
                "asset":          asset,
                "activityStatus": ACTIVITY_STATUS_SCANNER_GATED,
                "reason":         xmr.get("reason") or (
                    REASON_SCANNER_NOT_ENABLED
                ),
                "scannerStatus":  xmr.get("scannerStatus"),
                "entries":        [],
            }
    return {
        "schema":            CRYPTO_ACTIVITY_DATA_SCHEMA,
        "available":         True,
        "asset":             asset,
        "activityStatus":    ACTIVITY_STATUS_PENDING_LIVE_FETCH,

        "entries":           [],
        "liveFetchRequired": True,
    }



def build_crypto_send_draft_data(
    asset: Optional[str], amount: Optional[str], recipient: Optional[str],
) -> dict[str, Any]:



    if asset == ASSET_XMR:

        return {
            "schema":                       CRYPTO_SEND_DRAFT_DATA_SCHEMA,
            "available":                    True,
            "asset":                        asset,
            "network":                      ASSET_NETWORKS.get(asset, ""),
            "amount":                       amount,
            "toAddressPublic":              recipient,
            "feePreviewStatus":             "not_supported",
            "canBroadcast":                 False,
            "requiresTrustedDevice":        True,
            "requiresPinUnlock":            True,
            "requiresLocalSigning":         True,
            "requiresExplicitConfirmation": True,
            "sendDisabledReason":           "xmr_send_not_supported",
        }
    return {
        "schema":                       CRYPTO_SEND_DRAFT_DATA_SCHEMA,
        "available":                    True,
        "asset":                        asset,
        "network":                      ASSET_NETWORKS.get(asset or "", ""),
        "amount":                       amount,
        "toAddressPublic":              recipient,
        "feePreviewStatus":             BALANCE_STATUS_PENDING_LIVE_FETCH,
        "canBroadcast":                 False,
        "requiresTrustedDevice":        True,
        "requiresPinUnlock":            True,
        "requiresLocalSigning":         True,
        "requiresExplicitConfirmation": True,
    }




_CVC_INTENT_SHOW_VAULT       = "crypto_vault_show_vault"
_CVC_INTENT_BALANCE          = "crypto_vault_balance"
_CVC_INTENT_RECEIVE_ADDRESS  = "crypto_vault_receive_address"
_CVC_INTENT_RECEIVE_QR       = "crypto_vault_receive_qr"
_CVC_INTENT_SCANNER_STATUS   = "crypto_vault_scanner_status"
_CVC_INTENT_ACTIVITY         = "crypto_vault_activity"
_CVC_INTENT_SEND_DRAFT       = "crypto_vault_send_draft"


def populate_crypto_delegated_card_data(
    envelope: dict[str, Any],
    *,
    vault_id: str,
    client_platform: Optional[str] = None,
) -> dict[str, Any]:
    """Populate the crypto delegated card's inner card with safe live data.

    The vault_chat_router wraps the crypto module's result in an
    outer envelope with intent=`vault_crypto_delegated`. Its `card`
    field carries `innerIntent` + `innerCard`. This function
    populates `innerCard.data` and mutates the envelope in place.

    Idempotent. Never raises.
    """
    if not isinstance(envelope, dict):
        return envelope
    if str(envelope.get("intent") or "") != "vault_crypto_delegated":
        return envelope
    card = envelope.get("card")
    if not isinstance(card, dict):
        return envelope
    inner_intent = str(card.get("innerIntent") or "")
    inner_card = card.get("innerCard")
    if not isinstance(inner_card, dict):
        return envelope



    if inner_intent in (
        "crypto_vault_refusal_secret_material",
        "crypto_vault_refusal_exchange_action",
        "crypto_vault_clarify_usdt_network",
        "crypto_vault_unrecognized",
    ):
        return envelope

    try:
        data: Optional[dict[str, Any]] = None
        if inner_intent == _CVC_INTENT_SHOW_VAULT:
            data = build_crypto_overview_data(
                vault_id, client_platform=client_platform,
            )
        elif inner_intent == _CVC_INTENT_BALANCE:
            data = build_crypto_balance_data(
                vault_id,
                str(inner_card.get("asset") or ""),
                client_platform=client_platform,
            )
        elif inner_intent in (
            _CVC_INTENT_RECEIVE_ADDRESS, _CVC_INTENT_RECEIVE_QR,
        ):
            data = build_crypto_receive_data(
                vault_id,
                str(inner_card.get("asset") or ""),
                include_qr=inner_intent == _CVC_INTENT_RECEIVE_QR,
            )
        elif inner_intent == _CVC_INTENT_SCANNER_STATUS:
            data = build_crypto_scanner_status_data(
                client_platform=client_platform,
            )
        elif inner_intent == _CVC_INTENT_ACTIVITY:
            data = build_crypto_activity_data(
                vault_id,
                str(inner_card.get("asset") or "") or None,
                client_platform=client_platform,
            )
        elif inner_intent == _CVC_INTENT_SEND_DRAFT:
            data = build_crypto_send_draft_data(
                inner_card.get("asset"),
                inner_card.get("amount"),
                inner_card.get("recipient"),
            )
        else:

            data = None
        if data is not None:
            inner_card["data"] = _strip_forbidden(data)


        inner_card["canBroadcast"] = False
    except Exception:
        logger.exception(
            "[vault_chat_crypto_data] populate_crypto_delegated_card_data "
            "failed intent=%s", inner_intent,
        )
    return envelope



__all__ = [
    "CRYPTO_VAULT_OVERVIEW_DATA_SCHEMA",
    "CRYPTO_BALANCE_DATA_SCHEMA",
    "CRYPTO_RECEIVE_DATA_SCHEMA",
    "CRYPTO_SCANNER_STATUS_DATA_SCHEMA",
    "CRYPTO_ACTIVITY_DATA_SCHEMA",
    "CRYPTO_SEND_DRAFT_DATA_SCHEMA",

    "BALANCE_STATUS_PENDING_LIVE_FETCH",
    "BALANCE_STATUS_AVAILABLE",
    "BALANCE_STATUS_UNAVAILABLE",
    "BALANCE_STATUS_SCANNER_GATED",
    "BALANCE_STATUS_REQUIRES_DESKTOP",

    "ACTIVITY_STATUS_PENDING_LIVE_FETCH",
    "ACTIVITY_STATUS_AVAILABLE",
    "ACTIVITY_STATUS_UNAVAILABLE",
    "ACTIVITY_STATUS_SCANNER_GATED",

    "REASON_CREATE_WALLET_FIRST",
    "REASON_ASSET_NOT_ENABLED",
    "REASON_SCANNER_NOT_ENABLED",
    "REASON_SCANNER_REQUIRES_DESKTOP",
    "REASON_INTERNAL_ERROR",

    "ASSET_LABELS", "ASSET_NETWORKS", "ALL_ASSETS",

    "build_crypto_overview_data",
    "build_crypto_balance_data",
    "build_crypto_receive_data",
    "build_crypto_scanner_status_data",
    "build_crypto_activity_data",
    "build_crypto_send_draft_data",
    "populate_crypto_delegated_card_data",
]
