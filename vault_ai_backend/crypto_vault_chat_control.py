"""Crypto Vault chat control — safe intent classifier + response
envelope builder.

Ships as a standalone module. The route handler at
`POST /crypto/vault/chat/classify` accepts a user chat message and
returns a closed-set intent + a card envelope the frontend renders.

Security invariants — enforced by tests, not just documentation:

  1. This module NEVER returns a private key, seed, mnemonic, spend
     key, view key, encrypted secret, auth token, or API key. Any
     request that MENTIONS these words is coerced into a refusal
     card — no live data fetch happens on that branch.

  2. This module NEVER broadcasts a send. Send intents produce a
     `send_draft` card whose `canBroadcast=False` — the frontend
     must route the user through the existing PIN-locked, trusted-
     device, local-signing send flow.

  3. This module NEVER fabricates a balance or an activity row.
     Balance / activity / scanner-status cards carry only the
     closed-set state the classifier resolved; the frontend must
     fetch real data from the existing balance / transactions
     endpoints before rendering a number.

  4. This module NEVER enables buy / sell / swap / trade / stake /
     bridge / exchange / convert — any such request is refused.

  5. USDT without an ERC20 / TRC20 qualifier is AMBIGUOUS. The
     classifier returns a `clarify_usdt_network` intent so the UI
     can ask the user which network they mean.

The classifier is 100% deterministic (regex + word-boundary
matching). No LLM in this path. This makes classification
predictable, testable, and immune to prompt-injection style
attacks embedded in the message.
"""

from __future__ import annotations

import re
from typing import Any


CHAT_CONTROL_SCHEMA_V1: str = "crypto_vault_chat_control_v1"



INTENT_SHOW_VAULT:              str = "crypto_vault_show_vault"
INTENT_BALANCE:                 str = "crypto_vault_balance"
INTENT_RECEIVE_ADDRESS:         str = "crypto_vault_receive_address"
INTENT_RECEIVE_QR:              str = "crypto_vault_receive_qr"
INTENT_SCANNER_STATUS:          str = "crypto_vault_scanner_status"
INTENT_ACTIVITY:                str = "crypto_vault_activity"
INTENT_SEND_DRAFT:              str = "crypto_vault_send_draft"
INTENT_CLARIFY_USDT_NETWORK:    str = "crypto_vault_clarify_usdt_network"
INTENT_REFUSAL_SECRET_MATERIAL: str = (
    "crypto_vault_refusal_secret_material"
)
INTENT_REFUSAL_EXCHANGE_ACTION: str = (
    "crypto_vault_refusal_exchange_action"
)
INTENT_UNRECOGNIZED:            str = "crypto_vault_unrecognized"

_ALLOWED_INTENTS: frozenset[str] = frozenset({
    INTENT_SHOW_VAULT,
    INTENT_BALANCE,
    INTENT_RECEIVE_ADDRESS,
    INTENT_RECEIVE_QR,
    INTENT_SCANNER_STATUS,
    INTENT_ACTIVITY,
    INTENT_SEND_DRAFT,
    INTENT_CLARIFY_USDT_NETWORK,
    INTENT_REFUSAL_SECRET_MATERIAL,
    INTENT_REFUSAL_EXCHANGE_ACTION,
    INTENT_UNRECOGNIZED,
})



CARD_SHOW_VAULT:      str = "crypto_vault_show_vault_card"
CARD_BALANCE:         str = "crypto_vault_balance_card"
CARD_RECEIVE:         str = "crypto_vault_receive_card"
CARD_RECEIVE_QR:      str = "crypto_vault_receive_qr_card"
CARD_SCANNER_STATUS:  str = "crypto_vault_scanner_status_card"
CARD_ACTIVITY:        str = "crypto_vault_activity_card"
CARD_SEND_DRAFT:      str = "crypto_vault_send_draft_card"
CARD_REFUSAL:         str = "crypto_vault_refusal_card"
CARD_CLARIFY:         str = "crypto_vault_clarify_card"
CARD_UNRECOGNIZED:    str = "crypto_vault_unrecognized_card"

_ALLOWED_CARDS: frozenset[str] = frozenset({
    CARD_SHOW_VAULT, CARD_BALANCE, CARD_RECEIVE, CARD_RECEIVE_QR,
    CARD_SCANNER_STATUS, CARD_ACTIVITY, CARD_SEND_DRAFT,
    CARD_REFUSAL, CARD_CLARIFY, CARD_UNRECOGNIZED,
})



ASSET_ETH:        str = "ETH"
ASSET_USDT_ERC20: str = "USDT_ERC20"
ASSET_USDC_ERC20: str = "USDC_ERC20"
ASSET_SOL:        str = "SOL"
ASSET_USDT_TRC20: str = "USDT_TRC20"
ASSET_XMR:        str = "XMR"

_SUPPORTED_ASSETS: frozenset[str] = frozenset({
    ASSET_ETH, ASSET_USDT_ERC20, ASSET_USDC_ERC20,
    ASSET_SOL, ASSET_USDT_TRC20, ASSET_XMR,
})



REFUSAL_REASON_SECRET_MATERIAL: str = "secret_material_request"
REFUSAL_REASON_EXCHANGE_ACTION: str = "exchange_action_request"



_SECRET_MATERIAL_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bprivate\s+key\b",
        r"\bspend\s+key\b",
        r"\bview\s+key\b",
        r"\bseed\s+phrase\b",
        r"\bseed\s+words\b",
        r"\bmnemonic(?:s)?\b",
        r"\bpolyseed\b",
        r"\brecovery\s+phrase\b",
        r"\brecovery\s+words\b",
        r"\bencrypted\s+secret\b",
        r"\bwallet\s+secret\b",
        r"\bapi\s+key\b",
        r"\bauth\s+token\b",
    )
)


_EXCHANGE_ACTION_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bbuy\s+(?:\d+|eth|usdt|usdc|sol|xmr|crypto|monero|"
        r"solana|bitcoin|btc|coins?|some|more|any)\b",
        r"\bsell\s+(?:\d+|eth|usdt|usdc|sol|xmr|crypto|monero|"
        r"solana|bitcoin|btc|coins?|some|more|any)\b",
        r"\bswap\b",
        r"\btrade\s+(?:eth|usdt|usdc|sol|xmr|crypto|monero|"
        r"solana|bitcoin|btc|coins?|for|to)\b",
        r"\bstake\b",
        r"\bbridge\s+(?:eth|usdt|usdc|sol|xmr|crypto|monero|"
        r"solana|to|from)\b",
        r"\bconvert\s+(?:eth|usdt|usdc|sol|xmr|to|into)\b",
        r"\bexchange\s+(?:eth|usdt|usdc|sol|xmr|crypto|monero|"
        r"solana|bitcoin|btc|coins?|for|to|into)\b",
    )
)


_ETH_ADDRESS_RE  = re.compile(r"\b0x[0-9a-fA-F]{40}\b")

_SOL_ADDRESS_RE  = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")

_TRON_ADDRESS_RE = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")


_NUM_ASSET_RE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?)\s*"
    r"(?P<asset>eth|usdt(?:\s*(?:erc20|trc20))?|usdc(?:\s*erc20)?"
    r"|sol|solana|xmr|monero|ethereum|ether)",
    re.IGNORECASE,
)


_SEND_VERB_RE = re.compile(
    r"\b(?:send|transfer|prepare|draft|move|pay)\b",
    re.IGNORECASE,
)


class ClassifiedIntent:
    __slots__ = ("intent", "params")

    def __init__(self, intent: str, params: dict[str, Any] | None = None):
        if intent not in _ALLOWED_INTENTS:
            raise ValueError(f"unknown intent {intent!r}")
        self.intent = intent
        self.params: dict[str, Any] = dict(params or {})

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "params": dict(self.params)}


def _resolve_asset_from_token(token: str) -> str | None:
    token = token.strip().lower()
    token = re.sub(r"\s+", "_", token)
    mapping = {
        "eth":         ASSET_ETH,
        "ether":       ASSET_ETH,
        "ethereum":    ASSET_ETH,
        "usdt_erc20":  ASSET_USDT_ERC20,
        "usdt_trc20":  ASSET_USDT_TRC20,
        "usdc":        ASSET_USDC_ERC20,
        "usdc_erc20":  ASSET_USDC_ERC20,
        "sol":         ASSET_SOL,
        "solana":      ASSET_SOL,
        "xmr":         ASSET_XMR,
        "monero":      ASSET_XMR,
    }
    return mapping.get(token)


def _detect_secret_material(text: str) -> bool:
    for p in _SECRET_MATERIAL_PATTERNS:
        if p.search(text):
            return True
    return False


def _detect_exchange_action(text: str) -> bool:
    for p in _EXCHANGE_ACTION_PATTERNS:
        if p.search(text):
            return True
    return False


def _detect_send_intent(text: str) -> tuple[str | None, str | None,
                                             str | None] | None:
    """Returns (asset, amount, recipient) if a send-shaped intent is
    detected, else None. Recipient may be None if we saw an amount+asset
    but no address — the UI will prompt for the address.
    """
    if not _SEND_VERB_RE.search(text):
        return None
    match = _NUM_ASSET_RE.search(text)
    if not match:

        return None
    amount = match.group("amount")
    raw_asset = match.group("asset").lower().strip()

    recipient = None
    m_addr = (
        _ETH_ADDRESS_RE.search(text)
        or _TRON_ADDRESS_RE.search(text)
        or _SOL_ADDRESS_RE.search(text)
    )
    if m_addr:
        recipient = m_addr.group(0)


    if re.match(r"^usdt\s*erc20$", raw_asset):
        asset = ASSET_USDT_ERC20
    elif re.match(r"^usdt\s*trc20$", raw_asset):
        asset = ASSET_USDT_TRC20
    elif raw_asset == "usdt":

        return ("USDT_AMBIGUOUS", amount, recipient)
    else:
        asset = _resolve_asset_from_token(raw_asset)
    if not asset:
        return None
    return (asset, amount, recipient)


_BALANCE_RE = re.compile(
    r"\b(?:balance|how\s+much|what\s+is\s+my|what[’']s\s+my)\b",
    re.IGNORECASE,
)


_ADDRESS_RE = re.compile(
    r"\b(?:receive\s+address|my\s+\S+\s+address|my\s+address|"
    r"show\s+.*address|where\s+.*receive|receive\s+.*into|"
    r"what\s+is\s+my\s+\S+\s+address)\b",
    re.IGNORECASE,
)


_QR_RE = re.compile(
    r"\b(?:qr(?:\s*code)?|scan(?:\s+code)?)\b",
    re.IGNORECASE,
)


_SCANNER_STATUS_RE = re.compile(
    r"\b(?:scanner|monero\s+scanner|scanner\s+status|"
    r"why\s+.*monero\s+(?:scanner|scanning|sync|indexer|"
    r"balance|activity|not\s+syncing)|"
    r"why\s+can['’]?t\s+.*(?:monero|xmr)\s+balance)\b",
    re.IGNORECASE,
)


_ACTIVITY_RE = re.compile(
    r"\b(?:recent\s+.*(?:activity|transactions|txs|txns|history)|"
    r"my\s+(?:activity|transactions|txs|txns|history)|"
    r"crypto\s+activity|transaction\s+history|"
    r"activity)\b",
    re.IGNORECASE,
)


_SHOW_VAULT_RE = re.compile(
    r"\b(?:show\s+(?:my\s+)?(?:crypto\s+)?vault|"
    r"open\s+(?:my\s+)?(?:crypto\s+)?vault|"
    r"my\s+wallets|crypto\s+vault|show\s+wallets)\b",
    re.IGNORECASE,
)


_INTERNAL_SERVICE_KEY_RE = re.compile(
    r"\b([A-Z][A-Z0-9_]{1,15})"
    r":"
    r"([a-z][a-z0-9_]{2,25}_"
    r"(?:mainnet|testnet|sepolia|devnet))\b",
)


_SHOW_ASSET_WALLET_RE = re.compile(
    r"\bshow\s+(?:me\s+)?(?:my\s+|the\s+)?"
    r"(?:eth(?:ereum)?|monero|xmr|sol(?:ana)?|"
    r"usdt(?:\s*[-_]?(?:erc20|trc20))?|"
    r"usdc(?:\s*[-_]?erc20)?)"
    r"(?:\s+wallet(?:s)?|\s+account(?:s)?)?\b",
    re.IGNORECASE,
)


def _detect_asset_from_service_key(text: str) -> str | None:
    """Extract asset from an internal service key like
    "ETH:ethereum_mainnet". Returns None if no service key found or
    the asset is unknown."""
    m = _INTERNAL_SERVICE_KEY_RE.search(text)
    if not m:
        return None
    raw_asset = m.group(1).upper()
    if raw_asset == "ETH":
        return ASSET_ETH
    if raw_asset in ("XMR", "MONERO"):
        return ASSET_XMR
    if raw_asset in ("SOL", "SOLANA"):
        return ASSET_SOL
    if raw_asset == "USDT_ERC20":
        return ASSET_USDT_ERC20
    if raw_asset == "USDT_TRC20":
        return ASSET_USDT_TRC20
    if raw_asset in ("USDC", "USDC_ERC20"):
        return ASSET_USDC_ERC20
    return None


def _detect_asset_hint(text: str) -> str | None:
    """Find an asset mentioned in the message. Returns None if none
    or if the mention is ambiguous (bare 'usdt')."""
    text_lower = text.lower()
    if "usdt erc20" in text_lower or "usdt-erc20" in text_lower:
        return ASSET_USDT_ERC20
    if "usdt trc20" in text_lower or "usdt-trc20" in text_lower:
        return ASSET_USDT_TRC20
    if "usdc" in text_lower:
        return ASSET_USDC_ERC20
    if "monero" in text_lower or re.search(r"\bxmr\b",
                                            text_lower):
        return ASSET_XMR
    if "solana" in text_lower or re.search(r"\bsol\b", text_lower):
        return ASSET_SOL
    if re.search(r"\beth(?:ereum|er)?\b", text_lower):
        return ASSET_ETH
    if re.search(r"\busdt\b", text_lower):
        return "USDT_AMBIGUOUS"
    return None


def classify_crypto_vault_intent(
    message: str,
) -> ClassifiedIntent:
    """Deterministic closed-set classifier.

    Precedence order matters: secret refusals come first so a
    message mixing "send" and "seed phrase" cannot slip through as
    a send draft.
    """
    if not isinstance(message, str):
        return ClassifiedIntent(INTENT_UNRECOGNIZED)
    text = message.strip()
    if not text:
        return ClassifiedIntent(INTENT_UNRECOGNIZED)


    if _detect_secret_material(text):
        return ClassifiedIntent(
            INTENT_REFUSAL_SECRET_MATERIAL,
            {"reason": REFUSAL_REASON_SECRET_MATERIAL},
        )


    if _detect_exchange_action(text):
        return ClassifiedIntent(
            INTENT_REFUSAL_EXCHANGE_ACTION,
            {"reason": REFUSAL_REASON_EXCHANGE_ACTION},
        )


    send = _detect_send_intent(text)
    if send is not None:
        asset, amount, recipient = send
        if asset == "USDT_AMBIGUOUS":
            return ClassifiedIntent(
                INTENT_CLARIFY_USDT_NETWORK,
                {"amount": amount, "recipient": recipient},
            )
        params: dict[str, Any] = {
            "asset":     asset,
            "amount":    amount,
        }
        if recipient:
            params["recipient"] = recipient
        return ClassifiedIntent(INTENT_SEND_DRAFT, params)


    if _QR_RE.search(text):
        asset = _detect_asset_hint(text) or ASSET_XMR
        if asset == "USDT_AMBIGUOUS":
            return ClassifiedIntent(INTENT_CLARIFY_USDT_NETWORK)
        return ClassifiedIntent(
            INTENT_RECEIVE_QR, {"asset": asset},
        )


    if _SCANNER_STATUS_RE.search(text):
        return ClassifiedIntent(
            INTENT_SCANNER_STATUS, {"asset": ASSET_XMR},
        )



    if _ADDRESS_RE.search(text):
        asset = _detect_asset_hint(text)
        if asset == "USDT_AMBIGUOUS":
            return ClassifiedIntent(INTENT_CLARIFY_USDT_NETWORK)
        if asset is None:
            asset = ASSET_ETH
        return ClassifiedIntent(
            INTENT_RECEIVE_ADDRESS, {"asset": asset},
        )


    if _ACTIVITY_RE.search(text):
        asset = _detect_asset_hint(text)
        if asset == "USDT_AMBIGUOUS":
            return ClassifiedIntent(INTENT_CLARIFY_USDT_NETWORK)
        params = {}
        if asset:
            params["asset"] = asset
        return ClassifiedIntent(INTENT_ACTIVITY, params)


    _svc_asset = _detect_asset_from_service_key(text)
    if _svc_asset is not None:
        if _svc_asset == ASSET_XMR:
            return ClassifiedIntent(
                INTENT_SCANNER_STATUS, {"asset": ASSET_XMR},
            )
        return ClassifiedIntent(
            INTENT_BALANCE, {"asset": _svc_asset},
        )


    if _SHOW_ASSET_WALLET_RE.search(text):
        asset = _detect_asset_hint(text)
        if asset == "USDT_AMBIGUOUS":
            return ClassifiedIntent(INTENT_CLARIFY_USDT_NETWORK)
        if asset is not None:
            if asset == ASSET_XMR:
                return ClassifiedIntent(
                    INTENT_SCANNER_STATUS, {"asset": ASSET_XMR},
                )
            return ClassifiedIntent(
                INTENT_BALANCE, {"asset": asset},
            )


    if _BALANCE_RE.search(text):
        asset = _detect_asset_hint(text)
        if asset == "USDT_AMBIGUOUS":
            return ClassifiedIntent(INTENT_CLARIFY_USDT_NETWORK)
        if asset is None:

            return ClassifiedIntent(INTENT_SHOW_VAULT)
        return ClassifiedIntent(
            INTENT_BALANCE, {"asset": asset},
        )


    if _SHOW_VAULT_RE.search(text):
        return ClassifiedIntent(INTENT_SHOW_VAULT)


    if _detect_asset_hint(text) == "USDT_AMBIGUOUS":
        return ClassifiedIntent(INTENT_CLARIFY_USDT_NETWORK)

    return ClassifiedIntent(INTENT_UNRECOGNIZED)



_REFUSAL_COPY_SECRET_MATERIAL: str = (
    "VaultAI never surfaces your seed, mnemonic, private spend "
    "key, private view key, or encrypted wallet secret through "
    "chat. If you need to back up, use the Security page in the "
    "Crypto Vault."
)


_REFUSAL_COPY_EXCHANGE_ACTION: str = (
    "VaultAI is a non-custodial wallet. It does not buy, sell, "
    "swap, trade, stake, bridge, or exchange assets. You can "
    "receive, hold, and send from your own device."
)


_CLARIFY_USDT_NETWORK_COPY: str = (
    "USDT can mean USDT ERC20 (on Ethereum) or USDT TRC20 (on "
    "TRON). Which one do you mean?"
)


_UNRECOGNIZED_COPY: str = (
    "That question is not something Crypto Vault chat can answer "
    "yet. Try asking for a balance, a receive address, the "
    "Monero scanner status, or to prepare a send."
)


def _build_card(
    card_type: str, **extra: Any,
) -> dict[str, Any]:
    if card_type not in _ALLOWED_CARDS:
        raise ValueError(f"unknown card {card_type!r}")
    envelope: dict[str, Any] = {
        "schema":   CHAT_CONTROL_SCHEMA_V1,
        "cardType": card_type,
    }
    for k, v in extra.items():
        envelope[k] = v
    return envelope


def build_response_envelope(
    classified: ClassifiedIntent,
) -> dict[str, Any]:
    """Produce a card envelope for the given classification.

    This function makes NO network calls and NO database calls.
    Balance / activity / scanner-status cards carry the closed-set
    intent + asset hint; the frontend fetches live data through
    the existing balance / transactions / scanner-status endpoints
    before rendering a number or a real transaction row.
    """
    intent = classified.intent
    params = classified.params

    if intent == INTENT_REFUSAL_SECRET_MATERIAL:
        return _build_card(
            CARD_REFUSAL,
            refusalReason=REFUSAL_REASON_SECRET_MATERIAL,
            message=_REFUSAL_COPY_SECRET_MATERIAL,
        )

    if intent == INTENT_REFUSAL_EXCHANGE_ACTION:
        return _build_card(
            CARD_REFUSAL,
            refusalReason=REFUSAL_REASON_EXCHANGE_ACTION,
            message=_REFUSAL_COPY_EXCHANGE_ACTION,
        )

    if intent == INTENT_CLARIFY_USDT_NETWORK:
        return _build_card(
            CARD_CLARIFY,
            message=_CLARIFY_USDT_NETWORK_COPY,
            options=[ASSET_USDT_ERC20, ASSET_USDT_TRC20],
        )

    if intent == INTENT_SEND_DRAFT:
        return _build_card(
            CARD_SEND_DRAFT,
            asset=params.get("asset"),
            amount=params.get("amount"),
            recipient=params.get("recipient"),

            canBroadcast=False,
            requiresPinUnlock=True,
            requiresTrustedDevice=True,
            requiresLocalSigning=True,
            requiresExplicitConfirmation=True,
        )

    if intent == INTENT_BALANCE:
        return _build_card(
            CARD_BALANCE,
            asset=params.get("asset"),

            liveFetchRequired=True,
        )

    if intent == INTENT_RECEIVE_ADDRESS:
        return _build_card(
            CARD_RECEIVE,
            asset=params.get("asset"),
            liveFetchRequired=True,
        )

    if intent == INTENT_RECEIVE_QR:
        return _build_card(
            CARD_RECEIVE_QR,
            asset=params.get("asset"),
            liveFetchRequired=True,
        )

    if intent == INTENT_SCANNER_STATUS:
        return _build_card(
            CARD_SCANNER_STATUS,
            asset=params.get("asset", ASSET_XMR),
            liveFetchRequired=True,
        )

    if intent == INTENT_ACTIVITY:
        card = _build_card(
            CARD_ACTIVITY,
            liveFetchRequired=True,
        )
        if params.get("asset"):
            card["asset"] = params["asset"]
        return card

    if intent == INTENT_SHOW_VAULT:
        return _build_card(CARD_SHOW_VAULT)

    return _build_card(
        CARD_UNRECOGNIZED,
        message=_UNRECOGNIZED_COPY,
    )


def classify_and_build(message: str) -> dict[str, Any]:
    """Convenience: single call returning `{intent, card}`."""
    classified = classify_crypto_vault_intent(message)
    card = build_response_envelope(classified)
    return {
        "schema": CHAT_CONTROL_SCHEMA_V1,
        "intent": classified.intent,
        "card":   card,
    }


__all__ = [
    "CHAT_CONTROL_SCHEMA_V1",

    "INTENT_SHOW_VAULT",
    "INTENT_BALANCE",
    "INTENT_RECEIVE_ADDRESS",
    "INTENT_RECEIVE_QR",
    "INTENT_SCANNER_STATUS",
    "INTENT_ACTIVITY",
    "INTENT_SEND_DRAFT",
    "INTENT_CLARIFY_USDT_NETWORK",
    "INTENT_REFUSAL_SECRET_MATERIAL",
    "INTENT_REFUSAL_EXCHANGE_ACTION",
    "INTENT_UNRECOGNIZED",

    "CARD_SHOW_VAULT",
    "CARD_BALANCE",
    "CARD_RECEIVE",
    "CARD_RECEIVE_QR",
    "CARD_SCANNER_STATUS",
    "CARD_ACTIVITY",
    "CARD_SEND_DRAFT",
    "CARD_REFUSAL",
    "CARD_CLARIFY",
    "CARD_UNRECOGNIZED",

    "ASSET_ETH", "ASSET_USDT_ERC20", "ASSET_USDC_ERC20",
    "ASSET_SOL", "ASSET_USDT_TRC20", "ASSET_XMR",

    "REFUSAL_REASON_SECRET_MATERIAL",
    "REFUSAL_REASON_EXCHANGE_ACTION",

    "ClassifiedIntent",
    "classify_crypto_vault_intent",
    "build_response_envelope",
    "classify_and_build",
]
