

from __future__ import annotations

import logging
import re
from typing import Optional


logger = logging.getLogger(__name__)


INTENT_CRYPTO_SAVE_QUESTION:    str = "crypto_save_question"
INTENT_CRYPTO_SEND_QUESTION:    str = "crypto_send_question"
INTENT_CRYPTO_RECEIVE_QUESTION: str = "crypto_receive_question"
INTENT_CRYPTO_BUY_QUESTION:     str = "crypto_buy_question"
INTENT_CRYPTO_GENERIC_QUESTION: str = "crypto_generic_question"
INTENT_NONE:                    str = "none"


ALL_CRYPTO_INTENTS: tuple[str, ...] = (
    INTENT_CRYPTO_SAVE_QUESTION,
    INTENT_CRYPTO_SEND_QUESTION,
    INTENT_CRYPTO_RECEIVE_QUESTION,
    INTENT_CRYPTO_BUY_QUESTION,
    INTENT_CRYPTO_GENERIC_QUESTION,
    INTENT_NONE,
)


BAND_DEFLECTED: str = "deflected"
BAND_NO_INTENT: str = "no_intent"










MESSAGE_CRYPTO_SAVE: str = (
    "You can't access Crypto Vault on your current plan. "
    "Upgrade your account to unlock it — Crypto Vault is a "
    "real, non-custodial wallet with receive, send, and "
    "balance tracking on supported networks."
)

MESSAGE_CRYPTO_SAVE_UPGRADED: str = (
    "Yes. Crypto Vault is a real non-custodial wallet on "
    "your account. Open Crypto Vault, pick a supported "
    "asset, and use Receive to see the address and QR "
    "code, or Send to enter a recipient and amount. Your "
    "keys stay on your device."
)

MESSAGE_CRYPTO_SEND: str = (
    "You can't access Crypto Vault on your current plan. "
    "Upgrade your account to unlock the wallet — from "
    "there, open Crypto Vault, pick a supported asset, and "
    "use Send to enter the recipient and amount. Every send "
    "requires your PIN unlock and local signing on your device."
)

MESSAGE_CRYPTO_SEND_UPGRADED: str = (
    "Yes. Open Crypto Vault, pick a supported asset, then "
    "use Send to enter the recipient and amount. Every send "
    "requires your PIN unlock and local signing on your "
    "device — VaultAI never moves funds on its own."
)

MESSAGE_CRYPTO_RECEIVE: str = (
    "You can't access Crypto Vault on your current plan. "
    "Upgrade your account to unlock the wallet, then open "
    "Crypto Vault, pick a supported asset, and use Receive "
    "to see the address and QR code."
)

MESSAGE_CRYPTO_RECEIVE_UPGRADED: str = (
    "Yes. Open Crypto Vault, pick a supported asset, and "
    "use Receive to see the wallet address and QR code. "
    "You control the funds — the wallet is non-custodial."
)

MESSAGE_CRYPTO_BUY: str = (
    "VaultAI doesn't buy, sell, or trade crypto — it's a "
    "non-custodial wallet, not an exchange. To use the "
    "wallet at all you'll need to upgrade your account; "
    "after that the wallet supports receive, hold, and "
    "send from your own device."
)

MESSAGE_CRYPTO_BUY_UPGRADED: str = (
    "VaultAI doesn't buy, sell, or trade crypto — it's a "
    "non-custodial wallet, not an exchange. Your Crypto "
    "Vault is active: open it to receive, hold, and send "
    "assets from your own device."
)

MESSAGE_CRYPTO_GENERIC: str = (
    "You can't access Crypto Vault on your current plan. "
    "Upgrade your account to unlock it. Crypto Vault is a "
    "real, non-custodial wallet — once upgraded, open it "
    "to pick a supported asset, use Receive for an address "
    "and QR code, use Send to enter a recipient and amount, "
    "and view balance and transaction history where supported."
)

MESSAGE_CRYPTO_GENERIC_UPGRADED: str = (
    "Yes. Crypto Vault is a real, non-custodial wallet on "
    "your account. Open Crypto Vault, pick a supported "
    "asset, use Receive for the wallet address and QR "
    "code, use Send to enter a recipient and amount, and "
    "view balance and transaction history where supported. "
    "Network and asset availability may vary."
)


MESSAGE_CRYPTO_CHECKING_ACCESS: str = (
    "I'm checking your Crypto Vault access. Try again in a "
    "moment."
)


TIER_FREE_LABEL:     str = "free"
TIER_BASIC_LABEL:    str = "basic"
TIER_UPGRADED_LABEL: str = "upgraded"
TIER_UNKNOWN_LABEL:  str = "unknown"
_NON_UPGRADED_TIERS: frozenset[str] = frozenset({
    TIER_FREE_LABEL, TIER_BASIC_LABEL,
})


def _is_upgraded(user_tier: Optional[str]) -> bool:


    if not isinstance(user_tier, str):
        return False
    return user_tier.strip().lower() == TIER_UPGRADED_LABEL


def _is_tier_unknown(user_tier: Optional[str]) -> bool:


    if not isinstance(user_tier, str):
        return False
    return user_tier.strip().lower() == TIER_UNKNOWN_LABEL


_CRYPTO_TOKEN_RE = re.compile(
    r"\b(?:crypto|cryptocurrency|cryptocurrencies|"
    r"bitcoin|btc|"
    r"ethereum|eth|ether|"
    r"solana|sol|"
    r"usdt|usdc|tether|"
    r"dogecoin|doge|"
    r"litecoin|ltc|"
    r"polygon|matic|"
    r"cardano|ada|"
    r"ripple|xrp|"
    r"binance|bnb|"
    r"wallet|wallets|"
    r"seed\s+phrase|seed\s+phrases|"
    r"private\s+key|private\s+keys|"
    r"blockchain|on[-\s]chain|"
    r"web3|defi|"
    r"nft|nfts|"
    r"airdrop|airdrops|"
    r"staking|stake\s+crypto|"
    r"metamask|coinbase|trust\s+wallet|"
    r"ledger|trezor|hardware\s+wallet)\b",
    re.IGNORECASE,
)


_SEND_RE = re.compile(
    r"\b(?:send|transfer|withdraw|payout|pay|outgoing)\b",
    re.IGNORECASE,
)


_RECEIVE_RE = re.compile(
    r"\b(?:receive|deposit|incoming|fund|top\s*up|"
    r"get\s+paid|cash\s+in)\b",
    re.IGNORECASE,
)


_BUY_RE = re.compile(
    r"\b(?:buy|purchase|sell|trade|trading|exchange|"
    r"swap|convert)\b",
    re.IGNORECASE,
)


_SAVE_RE = re.compile(
    r"\b(?:save|store|keep|put|add|hold|secure|stash|"
    r"remember|backup|back\s+up)\b",
    re.IGNORECASE,
)


_QUESTION_RE = re.compile(
    r"\b(?:can\s+(?:i|you|we|vaultai|this|it)|"
    r"how\s+(?:do\s+i|can\s+i|do\s+you|does)|"
    r"do\s+you|does\s+(?:vaultai|this|it)|"
    r"is\s+(?:vaultai|this|it)|are\s+you|"
    r"will\s+(?:i|you|vaultai|this|it)|"
    r"when\s+can|when\s+will)\b",
    re.IGNORECASE,
)


_EXCHANGE_RE = re.compile(
    r"\b(?:exchange|broker|brokerage|trading\s+platform|"
    r"crypto\s+exchange|marketplace)\b",
    re.IGNORECASE,
)


def _has_crypto_token(msg: str) -> bool:
    return bool(_CRYPTO_TOKEN_RE.search(msg))


def classify_crypto_question(
    user_message: Optional[str],
) -> str:


    if not isinstance(user_message, str) or not user_message.strip():
        return INTENT_NONE
    msg = user_message.strip()
    has_crypto = _has_crypto_token(msg)
    has_exchange = bool(_EXCHANGE_RE.search(msg))
                                                              
                                                              
    if has_exchange and _QUESTION_RE.search(msg):
        return INTENT_CRYPTO_BUY_QUESTION
    if not has_crypto:
        return INTENT_NONE
    if _BUY_RE.search(msg):
        return INTENT_CRYPTO_BUY_QUESTION
    if _SEND_RE.search(msg):
        return INTENT_CRYPTO_SEND_QUESTION
    if _RECEIVE_RE.search(msg):
        return INTENT_CRYPTO_RECEIVE_QUESTION
    if _SAVE_RE.search(msg):
        return INTENT_CRYPTO_SAVE_QUESTION
    if _QUESTION_RE.search(msg):
        return INTENT_CRYPTO_GENERIC_QUESTION
    return INTENT_NONE


def _message_for_intent(
    intent: str, user_tier: Optional[str] = None,
) -> str:


    if _is_tier_unknown(user_tier):
        return MESSAGE_CRYPTO_CHECKING_ACCESS
    upgraded = _is_upgraded(user_tier)
    if intent == INTENT_CRYPTO_SAVE_QUESTION:
        return MESSAGE_CRYPTO_SAVE_UPGRADED if upgraded else MESSAGE_CRYPTO_SAVE
    if intent == INTENT_CRYPTO_SEND_QUESTION:
        return MESSAGE_CRYPTO_SEND_UPGRADED if upgraded else MESSAGE_CRYPTO_SEND
    if intent == INTENT_CRYPTO_RECEIVE_QUESTION:
        return MESSAGE_CRYPTO_RECEIVE_UPGRADED if upgraded else MESSAGE_CRYPTO_RECEIVE
    if intent == INTENT_CRYPTO_BUY_QUESTION:
        return MESSAGE_CRYPTO_BUY_UPGRADED if upgraded else MESSAGE_CRYPTO_BUY
    if intent == INTENT_CRYPTO_GENERIC_QUESTION:
        return MESSAGE_CRYPTO_GENERIC_UPGRADED if upgraded else MESSAGE_CRYPTO_GENERIC
    return ""


def route_crypto_question(
    *,
    user_message: Optional[str],
    user_tier: Optional[str] = None,
) -> dict:


    intent = classify_crypto_question(user_message)
    if intent == INTENT_NONE:
        return {
            "band":    BAND_NO_INTENT,
            "intent":  INTENT_NONE,
            "message": "",
        }
    message = _message_for_intent(intent, user_tier)
                                                                   
                                                                   
    if _is_tier_unknown(user_tier):
        safe_tier = TIER_UNKNOWN_LABEL
    elif _is_upgraded(user_tier):
        safe_tier = TIER_UPGRADED_LABEL
    else:
        safe_tier = TIER_FREE_LABEL
    logger.info(
        "[CRYPTO-LOCKED] deflected intent=%s tier=%s",
        intent, safe_tier,
    )
    return {
        "band":    BAND_DEFLECTED,
        "intent":  intent,
        "message": message,
    }


__all__ = [
    "INTENT_CRYPTO_SAVE_QUESTION",
    "INTENT_CRYPTO_SEND_QUESTION",
    "INTENT_CRYPTO_RECEIVE_QUESTION",
    "INTENT_CRYPTO_BUY_QUESTION",
    "INTENT_CRYPTO_GENERIC_QUESTION",
    "INTENT_NONE",
    "ALL_CRYPTO_INTENTS",
    "BAND_DEFLECTED",
    "BAND_NO_INTENT",
    "MESSAGE_CRYPTO_SAVE",
    "MESSAGE_CRYPTO_SAVE_UPGRADED",
    "MESSAGE_CRYPTO_SEND",
    "MESSAGE_CRYPTO_SEND_UPGRADED",
    "MESSAGE_CRYPTO_RECEIVE",
    "MESSAGE_CRYPTO_RECEIVE_UPGRADED",
    "MESSAGE_CRYPTO_BUY",
    "MESSAGE_CRYPTO_BUY_UPGRADED",
    "MESSAGE_CRYPTO_GENERIC",
    "MESSAGE_CRYPTO_GENERIC_UPGRADED",
    "MESSAGE_CRYPTO_CHECKING_ACCESS",
    "TIER_FREE_LABEL",
    "TIER_BASIC_LABEL",
    "TIER_UPGRADED_LABEL",
    "TIER_UNKNOWN_LABEL",
    "classify_crypto_question",
    "route_crypto_question",
]
