

from __future__ import annotations

import re
from typing import Any, Optional

from crypto_wallet_schemas import (
    ENGINE_MESSAGE_DISABLED,
    ENGINE_MESSAGE_NOT_READY,
    ENGINE_MESSAGE_UNSUPPORTED_ASSET,
    ENGINE_STATUS_DISABLED,
    ENGINE_STATUS_NOT_READY,
    ENGINE_STATUS_UNSUPPORTED,
    SPECIAL_DESIGN_ASSETS,
    WALLET_ENGINE_ASSETS,
    asset_is_wallet_engine_supported,
)


INTENT_WALLET_ENGINE_SHOW_WALLET:        str = "wallet_engine_show_wallet"
INTENT_WALLET_ENGINE_SHOW_BALANCE:       str = "wallet_engine_show_balance"
INTENT_WALLET_ENGINE_SHOW_RECEIVE:       str = "wallet_engine_show_receive"
INTENT_WALLET_ENGINE_SHOW_QR:            str = "wallet_engine_show_qr"
INTENT_WALLET_ENGINE_SHOW_TRANSACTIONS:  str = "wallet_engine_show_transactions"
INTENT_WALLET_ENGINE_CREATE_WALLET:      str = "wallet_engine_create_wallet"
INTENT_WALLET_ENGINE_BACKUP_WALLET:      str = "wallet_engine_backup_wallet"
INTENT_WALLET_ENGINE_HIDE_BALANCE:       str = "wallet_engine_hide_balance"
INTENT_WALLET_ENGINE_SEND_DRAFT:         str = "wallet_engine_send_draft"

ALL_WALLET_ENGINE_INTENTS: tuple[str, ...] = (
    INTENT_WALLET_ENGINE_SHOW_WALLET,
    INTENT_WALLET_ENGINE_SHOW_BALANCE,
    INTENT_WALLET_ENGINE_SHOW_RECEIVE,
    INTENT_WALLET_ENGINE_SHOW_QR,
    INTENT_WALLET_ENGINE_SHOW_TRANSACTIONS,
    INTENT_WALLET_ENGINE_CREATE_WALLET,
    INTENT_WALLET_ENGINE_BACKUP_WALLET,
    INTENT_WALLET_ENGINE_HIDE_BALANCE,
    INTENT_WALLET_ENGINE_SEND_DRAFT,
)


_ASSET_ALIASES: dict[str, str] = {
    "bitcoin":     "BTC",
    "btc":         "BTC",
    "ethereum":    "ETH",
    "eth":         "ETH",
    "ether":       "ETH",
    "usdt":        "USDT_ERC20",
    "usdt erc20":  "USDT_ERC20",
    "usdt-erc20":  "USDT_ERC20",
    "usdt-trc20":  "USDT_TRC20",
    "usdt trc20":  "USDT_TRC20",
    "tron usdt":   "USDT_TRC20",
    "usdc":        "USDC_ERC20",
    "usdc erc20":  "USDC_ERC20",
    "usdc-erc20":  "USDC_ERC20",
    "solana":      "SOL",
    "sol":         "SOL",
    "bnb":         "BNB",
    "binance smart chain": "BNB",
    "binance-smart-chain": "BNB",
    "bsc":         "BNB",
    "monero":      "XMR",
    "xmr":         "XMR",
}


def _detect_asset(message: str) -> Optional[str]:


    if not isinstance(message, str):
        return None
    low = message.lower()
                                                                       
    aliases_sorted = sorted(_ASSET_ALIASES.keys(), key=len, reverse=True)
    for alias in aliases_sorted:
                                                                      
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, low):
            return _ASSET_ALIASES[alias]
    return None


_INTENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
                                         
    (re.compile(r"\bsend\b.*\bto\s+0x[a-f0-9]{2,}", re.I),
     INTENT_WALLET_ENGINE_SEND_DRAFT),
    (re.compile(r"\bsend\b\s+\d", re.I),
     INTENT_WALLET_ENGINE_SEND_DRAFT),
    (re.compile(r"\bi\s+want\s+to\s+send\b", re.I),
     INTENT_WALLET_ENGINE_SEND_DRAFT),
              
    (re.compile(r"\b(show|check|whats?|view)\b.{0,15}\bbalance\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_BALANCE),
    (re.compile(r"\bhow\s+much\b.{0,20}\b(do\s+i\s+have|i\s+got)\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_BALANCE),
           
    (re.compile(r"\bhide\b.{0,15}\bbalance\b", re.I),
     INTENT_WALLET_ENGINE_HIDE_BALANCE),
                             
    (re.compile(r"\b(qr\s*code|qr)\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_QR),
    (re.compile(r"\b(receive|deposit)\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_RECEIVE),
    (re.compile(r"\b(receive|wallet)\s+address\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_RECEIVE),
    (re.compile(r"\b(show|give)\b.{0,20}\b(receive|wallet)\s+address\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_RECEIVE),
    (re.compile(r"\b(show|give|get)\b.{0,15}\baddress\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_RECEIVE),
                   
    (re.compile(r"\b(show|view|list)\b.{0,15}\btransactions?\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_TRANSACTIONS),
    (re.compile(r"\b(my|recent)\b.{0,15}\btransactions?\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_TRANSACTIONS),
                      
    (re.compile(r"\bcreate\b.{0,15}\bwallet\b", re.I),
     INTENT_WALLET_ENGINE_CREATE_WALLET),
    (re.compile(r"\bbackup\b.{0,15}\bwallet\b", re.I),
     INTENT_WALLET_ENGINE_BACKUP_WALLET),
                                         
    (re.compile(r"\b(show|open)\b.{0,15}\b(crypto\s+)?wallet\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_WALLET),
    (re.compile(r"\bmy\s+(crypto\s+)?wallet\b", re.I),
     INTENT_WALLET_ENGINE_SHOW_WALLET),
)


def detect_wallet_engine_intent(message: Optional[str]) -> Optional[dict[str, Any]]:


    if not isinstance(message, str) or not message.strip():
        return None
    for pattern, intent in _INTENT_PATTERNS:
        if pattern.search(message):
            return {
                "intent": intent,
                "asset":  _detect_asset(message),
            }
    return None


CHAT_MESSAGE_ENGINE_DISABLED: str = (
    "The Crypto Wallet Engine is not enabled for this network or "
    "account yet. Open Crypto Vault to see which assets and networks "
    "are currently supported, and try again once availability changes."
)
CHAT_MESSAGE_SEND_NOT_READY: str = (
    "Send is not yet available. When the wallet engine ships send, the "
    "flow will: build an unsigned draft, show a review screen with the "
    "amount and destination, require your PIN, sign locally on this "
    "device, then broadcast the signed transaction. VaultAI never sends "
    "from one message."
)
CHAT_MESSAGE_RECEIVE_NOT_READY: str = (
    "Receive is not yet wired through the wallet engine. The Receive "
    "panel will show your wallet address and QR code once the asset "
    "ships — only send the matching asset on the matching network."
)
CHAT_MESSAGE_BALANCE_NOT_READY: str = (
    "Balance lookup is not yet connected for this asset. The wallet "
    "engine shows the real on-chain balance once the asset is wired; "
    "until then there is no balance to display."
)
CHAT_MESSAGE_TRANSACTIONS_NOT_READY: str = (
    "Transaction history is not yet wired through the wallet engine. "
    "The list will populate once the asset is wired to its RPC / "
    "indexer endpoint."
)
CHAT_MESSAGE_MONERO_SPECIAL: str = (
    "Monero needs a special wallet-scanning design — its balance and "
    "transactions cannot be read from a public address alone. The "
    "wallet engine will support Monero in a later phase."
)
CHAT_MESSAGE_UNSUPPORTED_ASSET: str = (
    "This asset is not yet supported by the wallet engine."
)


def compose_chat_response(
    *,
    intent: str,
    asset: Optional[str],
    engine_enabled: bool,
) -> dict[str, Any]:


    if not engine_enabled:
        return {
            "ok":            True,
            "status":        ENGINE_STATUS_DISABLED,
            "intent":        intent,
            "asset":         asset,
            "message":       CHAT_MESSAGE_ENGINE_DISABLED,
            "engineMessage": ENGINE_MESSAGE_DISABLED,
        }
    norm_asset = (asset or "").strip().upper()
    if norm_asset and norm_asset in SPECIAL_DESIGN_ASSETS:
        return {
            "ok":            True,
            "status":        ENGINE_STATUS_UNSUPPORTED,
            "intent":        intent,
            "asset":         norm_asset,
            "message":       CHAT_MESSAGE_MONERO_SPECIAL,
            "engineMessage": ENGINE_MESSAGE_UNSUPPORTED_ASSET,
        }
    if norm_asset and not asset_is_wallet_engine_supported(norm_asset):
        return {
            "ok":            True,
            "status":        ENGINE_STATUS_UNSUPPORTED,
            "intent":        intent,
            "asset":         norm_asset,
            "message":       CHAT_MESSAGE_UNSUPPORTED_ASSET,
            "engineMessage": ENGINE_MESSAGE_UNSUPPORTED_ASSET,
        }
    if intent == INTENT_WALLET_ENGINE_SEND_DRAFT:
        msg = CHAT_MESSAGE_SEND_NOT_READY
    elif intent in {
        INTENT_WALLET_ENGINE_SHOW_RECEIVE,
        INTENT_WALLET_ENGINE_SHOW_QR,
    }:
        msg = CHAT_MESSAGE_RECEIVE_NOT_READY
    elif intent == INTENT_WALLET_ENGINE_SHOW_BALANCE:
        msg = CHAT_MESSAGE_BALANCE_NOT_READY
    elif intent == INTENT_WALLET_ENGINE_SHOW_TRANSACTIONS:
        msg = CHAT_MESSAGE_TRANSACTIONS_NOT_READY
    else:
        msg = ENGINE_MESSAGE_NOT_READY
    return {
        "ok":            True,
        "status":        ENGINE_STATUS_NOT_READY,
        "intent":        intent,
        "asset":         norm_asset or None,
        "message":       msg,
        "engineMessage": ENGINE_MESSAGE_NOT_READY,
    }


WALLET_CHAT_INTENT_OPEN_CRYPTO_WALLET:    str = "open_crypto_wallet"
WALLET_CHAT_INTENT_SHOW_WALLET:           str = "show_wallet"
WALLET_CHAT_INTENT_SHOW_BALANCE:          str = "show_balance"
WALLET_CHAT_INTENT_RECEIVE_ADDRESS:       str = "receive_address"
WALLET_CHAT_INTENT_RECEIVE_QR:            str = "receive_qr"
WALLET_CHAT_INTENT_SEND_DRAFT:            str = "send_draft"
WALLET_CHAT_INTENT_SHOW_TRANSACTIONS:     str = "show_transactions"
WALLET_CHAT_INTENT_UNSUPPORTED_ASSET:     str = "unsupported_asset"
WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK:   str = "unsupported_network"
WALLET_CHAT_INTENT_MONERO_SPECIAL:        str = "monero_special"
WALLET_CHAT_INTENT_CLARIFY_NETWORK:       str = "clarify_network"

ALL_WALLET_CHAT_INTENTS: tuple[str, ...] = (
    WALLET_CHAT_INTENT_OPEN_CRYPTO_WALLET,
    WALLET_CHAT_INTENT_SHOW_WALLET,
    WALLET_CHAT_INTENT_SHOW_BALANCE,
    WALLET_CHAT_INTENT_RECEIVE_ADDRESS,
    WALLET_CHAT_INTENT_RECEIVE_QR,
    WALLET_CHAT_INTENT_SEND_DRAFT,
    WALLET_CHAT_INTENT_SHOW_TRANSACTIONS,
    WALLET_CHAT_INTENT_UNSUPPORTED_ASSET,
    WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
    WALLET_CHAT_INTENT_MONERO_SPECIAL,
    WALLET_CHAT_INTENT_CLARIFY_NETWORK,
)


WALLET_CHAT_NETWORK_SEPOLIA:  str = "ethereum_sepolia"
WALLET_CHAT_NETWORK_MAINNET:  str = "ethereum_mainnet"
WALLET_CHAT_NETWORK_SOLANA_MAINNET: str = "solana_mainnet"
WALLET_CHAT_NETWORK_TRON_MAINNET:   str = "tron_mainnet"
WALLET_CHAT_NETWORK_MONERO_MAINNET: str = "monero_mainnet"


_NETWORK_ALIASES: tuple[tuple[str, str], ...] = (
    ("monero mainnet",        WALLET_CHAT_NETWORK_MONERO_MAINNET),
    ("monero",                WALLET_CHAT_NETWORK_MONERO_MAINNET),
    ("xmr",                   WALLET_CHAT_NETWORK_MONERO_MAINNET),
    ("tron mainnet",          WALLET_CHAT_NETWORK_TRON_MAINNET),
    ("trc20",                 WALLET_CHAT_NETWORK_TRON_MAINNET),
    ("trc 20",                WALLET_CHAT_NETWORK_TRON_MAINNET),
    ("tron",                  WALLET_CHAT_NETWORK_TRON_MAINNET),
    ("solana mainnet",        WALLET_CHAT_NETWORK_SOLANA_MAINNET),
    ("solana",                WALLET_CHAT_NETWORK_SOLANA_MAINNET),
    ("ethereum mainnet",      WALLET_CHAT_NETWORK_MAINNET),
    ("eth mainnet",           WALLET_CHAT_NETWORK_MAINNET),
    ("mainnet",               WALLET_CHAT_NETWORK_MAINNET),
    ("ethereum sepolia",      WALLET_CHAT_NETWORK_SEPOLIA),
    ("eth sepolia",           WALLET_CHAT_NETWORK_SEPOLIA),
    ("sepolia testnet",       WALLET_CHAT_NETWORK_SEPOLIA),
    ("ethereum testnet",      WALLET_CHAT_NETWORK_SEPOLIA),
    ("eth testnet",           WALLET_CHAT_NETWORK_SEPOLIA),
    ("sepolia",               WALLET_CHAT_NETWORK_SEPOLIA),
    ("testnet",               WALLET_CHAT_NETWORK_SEPOLIA),
)


WALLET_CHAT_LIVE_ASSETS: frozenset[str] = frozenset({
    "ETH", "USDT_ERC20", "USDC_ERC20",
})


_AMOUNT_BEFORE_ASSET_RE = re.compile(
    r"\bsend\b\s+(\d+(?:\.\d+)?)\s+("
    r"eth|ether|ethereum|"
    r"usdt[-_\s]?trc20|"
    r"usdt(?:[-_\s]?erc20)?|tether|"
    r"usdc(?:[-_\s]?erc20)?|usd\s+coin|"
    r"sol|solana"
    r")\b",
    re.IGNORECASE,
)
_DESTINATION_RE = re.compile(
    r"\bto\s+(0x[a-fA-F0-9]{40})\b",
    re.IGNORECASE,
)
_SOLANA_DESTINATION_RE = re.compile(
    r"\bto\s+([1-9A-HJ-NP-Za-km-z]{32,44})\b",
)
_TRON_DESTINATION_RE = re.compile(
    r"\bto\s+(T[1-9A-HJ-NP-Za-km-z]{33})\b",
)


def _detect_network(message: str) -> Optional[str]:


    if not isinstance(message, str):
        return None
    low = message.lower()
    for alias, network_id in _NETWORK_ALIASES:
                                                                     
                                                                   
        pattern = r"\b" + re.escape(alias) + r"\b"
        if re.search(pattern, low):
            return network_id
    return None


def _extract_send_fields(
    message: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:


    if not isinstance(message, str):
        return None, None, None
    amount: Optional[str] = None
    asset_alias: Optional[str] = None
    m = _AMOUNT_BEFORE_ASSET_RE.search(message)
    if m:
        amount = m.group(1)
        asset_alias = m.group(2).lower()
    dest_m = _DESTINATION_RE.search(message)
    destination = dest_m.group(1) if dest_m else None
    if destination is None:
        tron_m = _TRON_DESTINATION_RE.search(message)
        if tron_m:
            destination = tron_m.group(1)
    if destination is None:
        sol_m = _SOLANA_DESTINATION_RE.search(message)
        if sol_m:
            candidate = sol_m.group(1)
            if candidate.lower() not in {
                "mainnet", "sepolia", "testnet", "solana", "ethereum",
                "tron",
            }:
                destination = candidate
    return amount, asset_alias, destination


def _asset_alias_to_canonical(alias: Optional[str]) -> Optional[str]:

    if not alias:
        return None
    a = alias.lower().replace("-", " ").replace("_", " ")
    a = re.sub(r"\s+", " ", a).strip()
    if a in {"eth", "ether", "ethereum"}:
        return "ETH"
    if a.startswith("usdt trc20") or a.startswith("usdt tron"):
        return "USDT_TRC20"
    if a in {"usdt", "tether"} or a.startswith("usdt erc20"):
        return "USDT_ERC20"
    if a in {"usdc", "usd coin"} or a.startswith("usdc erc20"):
        return "USDC_ERC20"
    return None


WALLET_CHAT_MSG_SHOW_WALLET: str = (
    "Opening your Crypto Vault — your non-custodial wallet engine. "
    "VaultAI never holds your keys."
)
WALLET_CHAT_MSG_SHOW_BALANCE: str = (
    "Opening your {asset_label} balance on {network_label}. The "
    "live balance loads from the network — VaultAI never displays "
    "a fake balance."
)
WALLET_CHAT_MSG_RECEIVE: str = (
    "Opening your {asset_label} receive panel on {network_label}. "
    "The QR shows your real wallet address — only send "
    "{asset_label} on {network_label} to it."
)
WALLET_CHAT_MSG_MAINNET_RECEIVE_REAL_FUNDS: str = (
    "Opening your Ethereum Mainnet receive panel. Mainnet uses REAL "
    "funds — only send ETH on Ethereum Mainnet to this address. "
    "Mainnet transactions cannot be reversed."
)
WALLET_CHAT_MSG_MAINNET_TOKEN_RECEIVE_REAL_FUNDS: str = (
    "Opening your Ethereum Mainnet {token_label} receive panel. "
    "Mainnet uses REAL funds — only send {token_label} on Ethereum "
    "Mainnet to this address. Mainnet transactions cannot be "
    "reversed. Sending this token later will require ETH for gas."
)
WALLET_CHAT_MSG_MAINNET_TOKEN_SEND_DISABLED: str = (
    "Ethereum Mainnet token sending is not enabled yet. The "
    "non-custodial wallet engine ships mainnet token send after a "
    "security review — until then I can only prepare Sepolia "
    "testnet flows."
)
WALLET_CHAT_MSG_MAINNET_TOKEN_RECEIVE_DISABLED: str = (
    "Ethereum Mainnet token receive is not enabled yet. Open the "
    "wallet page to use Ethereum Sepolia testnet receive."
)
WALLET_CHAT_MSG_SEND_DRAFT: str = (
    "I prepared a send review. Please review the address, amount, "
    "and fee before confirming. Your PIN is required to sign and "
    "broadcast — VaultAI never sends from one message."
)
WALLET_CHAT_MSG_MAINNET_SEND_REAL_FUNDS: str = (
    "I prepared an Ethereum Mainnet send review. Mainnet uses REAL "
    "funds — please confirm the destination address, amount, and "
    "gas fee on the review screen. Your PIN is required to sign "
    "locally and broadcast. Mainnet transactions cannot be reversed."
)
WALLET_CHAT_MSG_SEND_DRAFT_MISSING_FIELDS: str = (
    "I need both the amount and the destination address to prepare "
    "a send review. Try: \"send 0.01 ETH on Sepolia to 0x... \"."
)
WALLET_CHAT_MSG_TRANSACTIONS_NOT_CONNECTED: str = (
    "Transaction history not connected yet. Sent transactions will "
    "show their hash and status after broadcast."
)
WALLET_CHAT_MSG_MAINNET_DISABLED: str = (
    "Ethereum Mainnet sending is not enabled yet. The non-custodial "
    "wallet engine ships mainnet support after a security review — "
    "until then I can only prepare Sepolia testnet flows."
)
WALLET_CHAT_MSG_MAINNET_RECEIVE_DISABLED: str = (
    "Ethereum Mainnet receive is not enabled yet. Open the wallet "
    "page to use Ethereum Sepolia testnet receive."
)
WALLET_CHAT_MSG_MONERO_SPECIAL: str = (
    "Monero requires a separate privacy-wallet design and is not "
    "connected to the live wallet engine yet. A public address "
    "alone cannot expose Monero balance or transactions."
)
WALLET_CHAT_MSG_UNSUPPORTED_ASSET: str = (
    "{asset_label} is not connected to the wallet engine yet. "
    "It ships in a later phase — until then there is no balance, "
    "address, or send action available."
)
WALLET_CHAT_MSG_CLARIFY_NETWORK: str = (
    "Which network do you mean? Ethereum Sepolia testnet is the "
    "only network the wallet engine supports right now."
)
WALLET_CHAT_MSG_ENGINE_DISABLED_LITE: str = CHAT_MESSAGE_ENGINE_DISABLED
WALLET_CHAT_MSG_CREATE_WALLET_FIRST: str = (
    "You need to create your Ethereum Sepolia wallet first. Open the "
    "Crypto Vault, tap the ETH card, and tap Receive — VaultAI "
    "generates the wallet on this device, encrypts it with your PIN, "
    "and never sends the plaintext key to the backend."
)


_DISPLAY_LABELS: dict[str, str] = {
    "ETH":        "Ethereum",
    "USDT_ERC20": "USDT (ERC20)",
    "USDC_ERC20": "USDC (ERC20)",
    "BTC":        "Bitcoin",
    "SOL":        "Solana",
    "BNB":        "BNB Smart Chain",
    "USDT_TRC20": "USDT (TRC20)",
    "XMR":        "Monero",
}


WALLET_CHAT_ENVELOPE_TYPE: str = "crypto_wallet_action"


def parse_wallet_engine_chat_message(
    message: Optional[str],
    *,
    default_network: str = WALLET_CHAT_NETWORK_SEPOLIA,
) -> Optional[dict[str, Any]]:


    if not isinstance(message, str) or not message.strip():
        return None

                                                                    
    base = detect_wallet_engine_intent(message)
    if base is None:
        return None
    raw_intent = base["intent"]
    asset = base.get("asset")

                                 
    detected_network = _detect_network(message)
    network = detected_network or default_network
    network_explicit = detected_network is not None

                                                             
    amount: Optional[str] = None
    destination: Optional[str] = None
    if raw_intent == INTENT_WALLET_ENGINE_SEND_DRAFT:
        amt, asset_alias, dest = _extract_send_fields(message)
        amount = amt
        destination = dest
                                                                      
                                                                     
        if asset_alias is not None:
            canonical = _asset_alias_to_canonical(asset_alias)
            if canonical:
                asset = canonical

                                                                     
    intent: str
    if raw_intent == INTENT_WALLET_ENGINE_SHOW_WALLET:
                                                                  
                                                              
        intent = (
            WALLET_CHAT_INTENT_OPEN_CRYPTO_WALLET
            if re.search(r"\bopen\b", message, re.IGNORECASE)
            else WALLET_CHAT_INTENT_SHOW_WALLET
        )
    elif raw_intent == INTENT_WALLET_ENGINE_SHOW_BALANCE:
        intent = WALLET_CHAT_INTENT_SHOW_BALANCE
    elif raw_intent == INTENT_WALLET_ENGINE_SHOW_RECEIVE:
        intent = WALLET_CHAT_INTENT_RECEIVE_ADDRESS
    elif raw_intent == INTENT_WALLET_ENGINE_SHOW_QR:
        intent = WALLET_CHAT_INTENT_RECEIVE_QR
    elif raw_intent == INTENT_WALLET_ENGINE_SHOW_TRANSACTIONS:
        intent = WALLET_CHAT_INTENT_SHOW_TRANSACTIONS
    elif raw_intent == INTENT_WALLET_ENGINE_SEND_DRAFT:
        intent = WALLET_CHAT_INTENT_SEND_DRAFT
    elif raw_intent == INTENT_WALLET_ENGINE_CREATE_WALLET:
        intent = WALLET_CHAT_INTENT_OPEN_CRYPTO_WALLET
    elif raw_intent == INTENT_WALLET_ENGINE_BACKUP_WALLET:
        intent = WALLET_CHAT_INTENT_OPEN_CRYPTO_WALLET
    elif raw_intent == INTENT_WALLET_ENGINE_HIDE_BALANCE:
        intent = WALLET_CHAT_INTENT_SHOW_WALLET
    else:
        intent = WALLET_CHAT_INTENT_SHOW_WALLET

    norm_asset = (asset or "").strip().upper() or None
    if norm_asset == "XMR":
        try:
            from vault_config import monero_enabled as _xmr_on
            xmr_on = bool(_xmr_on())
        except Exception:
            xmr_on = False
        try:
            from vault_config import (
                monero_send_enabled as _xmr_send_on,
            )
            xmr_send_on = bool(_xmr_send_on())
        except Exception:
            xmr_send_on = False
        if not xmr_on:
            intent = WALLET_CHAT_INTENT_MONERO_SPECIAL
        else:
            if not network_explicit or network not in (
                WALLET_CHAT_NETWORK_MONERO_MAINNET,
            ):
                network = WALLET_CHAT_NETWORK_MONERO_MAINNET
                network_explicit = True
            if raw_intent == INTENT_WALLET_ENGINE_SEND_DRAFT \
                    and not xmr_send_on:
                intent = WALLET_CHAT_INTENT_UNSUPPORTED_ASSET
    elif norm_asset == "USDT_TRC20":
        try:
            from vault_config import tron_enabled as _tron_on
            tron_on = bool(_tron_on())
        except Exception:
            tron_on = False
        try:
            from vault_config import (
                tron_send_enabled as _tron_send_on,
            )
            tron_send_on = bool(_tron_send_on())
        except Exception:
            tron_send_on = False
        if not tron_on:
            intent = WALLET_CHAT_INTENT_UNSUPPORTED_ASSET
        else:
            if not network_explicit or network not in (
                WALLET_CHAT_NETWORK_TRON_MAINNET,
            ):
                network = WALLET_CHAT_NETWORK_TRON_MAINNET
                network_explicit = True
            if raw_intent == INTENT_WALLET_ENGINE_SEND_DRAFT \
                    and not tron_send_on:
                intent = WALLET_CHAT_INTENT_UNSUPPORTED_ASSET
    elif norm_asset == "SOL":
        try:
            from vault_config import solana_enabled as _solana_on
            sol_on = bool(_solana_on())
        except Exception:
            sol_on = False
        try:
            from vault_config import solana_send_enabled as _sol_send
            sol_send_on = bool(_sol_send())
        except Exception:
            sol_send_on = False
        if not sol_on:
            intent = WALLET_CHAT_INTENT_UNSUPPORTED_ASSET
        else:
            if not network_explicit or network not in (
                WALLET_CHAT_NETWORK_SOLANA_MAINNET,
            ):
                network = WALLET_CHAT_NETWORK_SOLANA_MAINNET
                network_explicit = True
            if raw_intent == INTENT_WALLET_ENGINE_SEND_DRAFT \
                    and not sol_send_on:
                intent = WALLET_CHAT_INTENT_UNSUPPORTED_ASSET
    elif norm_asset and norm_asset not in WALLET_CHAT_LIVE_ASSETS and \
            norm_asset != "XMR":

        intent = WALLET_CHAT_INTENT_UNSUPPORTED_ASSET


    return {
        "intent":             intent,
        "asset":              norm_asset,
        "network":            network,
        "networkExplicit":    network_explicit,
        "amount":             amount,
        "destinationAddress": destination,
    }


def _asset_display_label(asset: Optional[str]) -> str:
    if not asset:
        return "your wallet"
    return _DISPLAY_LABELS.get(asset.upper(), asset)


def compose_wallet_engine_chat_envelope(
    parsed: dict[str, Any],
    *,
    engine_enabled: bool,
    mainnet_receive_enabled: bool = False,
    mainnet_send_enabled: bool = False,
    mainnet_erc20_receive_enabled: bool = False,
) -> dict[str, Any]:


    intent = parsed.get("intent", WALLET_CHAT_INTENT_SHOW_WALLET)
    asset = parsed.get("asset")
    network = parsed.get("network", WALLET_CHAT_NETWORK_SEPOLIA)
    amount = parsed.get("amount")
    destination = parsed.get("destinationAddress")

                                                                  
    asset_is_erc20 = (asset or "").strip().upper() in {
        "USDT_ERC20", "USDC_ERC20",
    }
    if network == WALLET_CHAT_NETWORK_MAINNET:
        if intent == WALLET_CHAT_INTENT_SEND_DRAFT:
            if not mainnet_send_enabled:
                                                
                intent = WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK
                                                                   
                                                                    
        elif asset_is_erc20:
            if not mainnet_erc20_receive_enabled:
                intent = WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK
        elif not mainnet_receive_enabled:
                                                                       
            intent = WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK

                                                                  
    if not engine_enabled:
        return {
            "type":               WALLET_CHAT_ENVELOPE_TYPE,
            "message":            WALLET_CHAT_MSG_ENGINE_DISABLED_LITE,
            "intent":             intent,
            "asset":              asset,
            "network":            network,
            "engineEnabled":      False,
            "blockedReason":      "engine_disabled",
            "amount":             None,
            "amountUnit":         None,
            "destinationAddress": None,
            "needsCreateWalletFirst": False,
        }

    asset_label = _asset_display_label(asset)

    if intent == WALLET_CHAT_INTENT_MONERO_SPECIAL:
        return _envelope(
            intent=intent, asset=asset, network=network,
            message=WALLET_CHAT_MSG_MONERO_SPECIAL,
            blocked="monero_special",
        )

    if intent == WALLET_CHAT_INTENT_UNSUPPORTED_ASSET:
        return _envelope(
            intent=intent, asset=asset, network=network,
            message=WALLET_CHAT_MSG_UNSUPPORTED_ASSET.format(
                asset_label=asset_label,
            ),
            blocked="unsupported_asset",
        )

    if intent == WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK:
                                                                 
                                                                
        send_words = bool(amount or destination)
        if asset_is_erc20:
            msg = (
                WALLET_CHAT_MSG_MAINNET_TOKEN_SEND_DISABLED
                if send_words
                else WALLET_CHAT_MSG_MAINNET_TOKEN_RECEIVE_DISABLED
            )
        else:
            msg = (
                WALLET_CHAT_MSG_MAINNET_DISABLED
                if send_words
                else WALLET_CHAT_MSG_MAINNET_RECEIVE_DISABLED
            )
        return _envelope(
            intent=intent, asset=asset, network=network,
            message=msg,
            blocked="mainnet_disabled",
        )

    if intent == WALLET_CHAT_INTENT_CLARIFY_NETWORK:
        return _envelope(
            intent=intent, asset=asset, network=network,
            message=WALLET_CHAT_MSG_CLARIFY_NETWORK,
            blocked="clarify_network",
        )

    if intent == WALLET_CHAT_INTENT_SEND_DRAFT:
        if not amount or not destination:
            return _envelope(
                intent=intent, asset=asset, network=network,
                message=WALLET_CHAT_MSG_SEND_DRAFT_MISSING_FIELDS,
                blocked="missing_send_fields",
            )
                                                                   
                                                              
        chosen_asset = asset or "ETH"
        send_message = (
            WALLET_CHAT_MSG_MAINNET_SEND_REAL_FUNDS
            if network == WALLET_CHAT_NETWORK_MAINNET
            else WALLET_CHAT_MSG_SEND_DRAFT
        )
        return {
            "type":               WALLET_CHAT_ENVELOPE_TYPE,
            "message":            send_message,
            "intent":             intent,
            "asset":              chosen_asset,
            "network":            network,
            "engineEnabled":      True,
            "blockedReason":      None,
            "amount":             amount,
            "amountUnit":         chosen_asset,
            "destinationAddress": destination,
            "needsCreateWalletFirst": False,
        }

    if intent == WALLET_CHAT_INTENT_SHOW_TRANSACTIONS:
        return _envelope(
            intent=intent, asset=asset or "ETH", network=network,
            message=WALLET_CHAT_MSG_TRANSACTIONS_NOT_CONNECTED,
            blocked=None,
        )

    if network == WALLET_CHAT_NETWORK_MAINNET:
        network_label = "Ethereum Mainnet"
    elif network == WALLET_CHAT_NETWORK_SOLANA_MAINNET:
        network_label = "Solana"
    elif network == WALLET_CHAT_NETWORK_TRON_MAINNET:
        network_label = "TRON"
    elif network == WALLET_CHAT_NETWORK_MONERO_MAINNET:
        network_label = "Monero"
    else:
        network_label = "Ethereum Sepolia"

    if intent in {
        WALLET_CHAT_INTENT_RECEIVE_ADDRESS,
        WALLET_CHAT_INTENT_RECEIVE_QR,
    }:
        if network == WALLET_CHAT_NETWORK_MAINNET:
            if asset_is_erc20:
                token_label = (
                    "USDT" if (asset or "").upper() == "USDT_ERC20"
                    else "USDC"
                )
                msg = WALLET_CHAT_MSG_MAINNET_TOKEN_RECEIVE_REAL_FUNDS.format(
                    token_label=token_label,
                )
            else:
                msg = WALLET_CHAT_MSG_MAINNET_RECEIVE_REAL_FUNDS
        else:
            msg = WALLET_CHAT_MSG_RECEIVE.format(
                asset_label=_asset_display_label(asset or "ETH"),
                network_label=network_label,
            )
        return _envelope(
            intent=intent, asset=asset or "ETH", network=network,
            message=msg,
            blocked=None,
        )

    if intent == WALLET_CHAT_INTENT_SHOW_BALANCE:
        return _envelope(
            intent=intent, asset=asset or "ETH", network=network,
            message=WALLET_CHAT_MSG_SHOW_BALANCE.format(
                asset_label=_asset_display_label(asset or "ETH"),
                network_label=network_label,
            ),
            blocked=None,
        )

                                                                    
    return _envelope(
        intent=intent, asset=asset, network=network,
        message=WALLET_CHAT_MSG_SHOW_WALLET,
        blocked=None,
    )


def _envelope(
    *,
    intent: str,
    asset: Optional[str],
    network: str,
    message: str,
    blocked: Optional[str],
) -> dict[str, Any]:
    return {
        "type":               WALLET_CHAT_ENVELOPE_TYPE,
        "message":            message,
        "intent":             intent,
        "asset":              asset,
        "network":            network,
        "engineEnabled":      True,
        "blockedReason":      blocked,
        "amount":             None,
        "amountUnit":         None,
        "destinationAddress": None,
        "needsCreateWalletFirst": False,
    }


def safe_telemetry_label(parsed: dict[str, Any]) -> str:


    intent = str(parsed.get("intent") or "")
    asset = str(parsed.get("asset") or "")
    network = str(parsed.get("network") or "")
                                                                 
                                                               
    if intent and intent not in ALL_WALLET_CHAT_INTENTS:
        intent = "unknown"
    if asset and asset not in {
        "ETH", "USDT_ERC20", "USDC_ERC20",
        "BTC", "SOL", "BNB", "USDT_TRC20", "XMR",
    }:
        asset = "unknown"
    if network and network not in {
        WALLET_CHAT_NETWORK_SEPOLIA, WALLET_CHAT_NETWORK_MAINNET,
        WALLET_CHAT_NETWORK_SOLANA_MAINNET,
        WALLET_CHAT_NETWORK_TRON_MAINNET,
        WALLET_CHAT_NETWORK_MONERO_MAINNET,
    }:
        network = "unknown"
    return f"intent={intent}|asset={asset}|network={network}"


__all__ = [
                                                                 
    "INTENT_WALLET_ENGINE_SHOW_WALLET",
    "INTENT_WALLET_ENGINE_SHOW_BALANCE",
    "INTENT_WALLET_ENGINE_SHOW_RECEIVE",
    "INTENT_WALLET_ENGINE_SHOW_QR",
    "INTENT_WALLET_ENGINE_SHOW_TRANSACTIONS",
    "INTENT_WALLET_ENGINE_CREATE_WALLET",
    "INTENT_WALLET_ENGINE_BACKUP_WALLET",
    "INTENT_WALLET_ENGINE_HIDE_BALANCE",
    "INTENT_WALLET_ENGINE_SEND_DRAFT",
    "ALL_WALLET_ENGINE_INTENTS",
                          
    "WALLET_CHAT_INTENT_OPEN_CRYPTO_WALLET",
    "WALLET_CHAT_INTENT_SHOW_WALLET",
    "WALLET_CHAT_INTENT_SHOW_BALANCE",
    "WALLET_CHAT_INTENT_RECEIVE_ADDRESS",
    "WALLET_CHAT_INTENT_RECEIVE_QR",
    "WALLET_CHAT_INTENT_SEND_DRAFT",
    "WALLET_CHAT_INTENT_SHOW_TRANSACTIONS",
    "WALLET_CHAT_INTENT_UNSUPPORTED_ASSET",
    "WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK",
    "WALLET_CHAT_INTENT_MONERO_SPECIAL",
    "WALLET_CHAT_INTENT_CLARIFY_NETWORK",
    "ALL_WALLET_CHAT_INTENTS",
                      
    "WALLET_CHAT_NETWORK_SEPOLIA",
    "WALLET_CHAT_NETWORK_MAINNET",
    "WALLET_CHAT_NETWORK_SOLANA_MAINNET",
    "WALLET_CHAT_NETWORK_TRON_MAINNET",
    "WALLET_CHAT_NETWORK_MONERO_MAINNET",
    "WALLET_CHAT_LIVE_ASSETS",
                                     
    "detect_wallet_engine_intent",
    "compose_chat_response",
    "parse_wallet_engine_chat_message",
    "compose_wallet_engine_chat_envelope",
    "safe_telemetry_label",
                       
    "WALLET_CHAT_ENVELOPE_TYPE",
                                         
    "CHAT_MESSAGE_ENGINE_DISABLED",
    "CHAT_MESSAGE_SEND_NOT_READY",
    "CHAT_MESSAGE_RECEIVE_NOT_READY",
    "CHAT_MESSAGE_BALANCE_NOT_READY",
    "CHAT_MESSAGE_TRANSACTIONS_NOT_READY",
    "CHAT_MESSAGE_MONERO_SPECIAL",
    "CHAT_MESSAGE_UNSUPPORTED_ASSET",
                                         
    "WALLET_CHAT_MSG_SHOW_WALLET",
    "WALLET_CHAT_MSG_SHOW_BALANCE",
    "WALLET_CHAT_MSG_RECEIVE",
    "WALLET_CHAT_MSG_SEND_DRAFT",
    "WALLET_CHAT_MSG_SEND_DRAFT_MISSING_FIELDS",
    "WALLET_CHAT_MSG_TRANSACTIONS_NOT_CONNECTED",
    "WALLET_CHAT_MSG_MAINNET_DISABLED",
    "WALLET_CHAT_MSG_MAINNET_RECEIVE_DISABLED",
    "WALLET_CHAT_MSG_MAINNET_RECEIVE_REAL_FUNDS",
    "WALLET_CHAT_MSG_MAINNET_SEND_REAL_FUNDS",
    "WALLET_CHAT_MSG_MAINNET_TOKEN_RECEIVE_REAL_FUNDS",
    "WALLET_CHAT_MSG_MAINNET_TOKEN_SEND_DISABLED",
    "WALLET_CHAT_MSG_MAINNET_TOKEN_RECEIVE_DISABLED",
    "WALLET_CHAT_MSG_MONERO_SPECIAL",
    "WALLET_CHAT_MSG_UNSUPPORTED_ASSET",
    "WALLET_CHAT_MSG_CLARIFY_NETWORK",
    "WALLET_CHAT_MSG_CREATE_WALLET_FIRST",
]
