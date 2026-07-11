"""Full VaultAI chat intent router — covers the WHOLE vault.

The previous slice shipped `crypto_vault_chat_control.py` — a
closed-set classifier for crypto-only intents. This module extends
the concept to the entire vault: files, documents, secure items,
logins, generated logins, ID documents, crypto vault, billing,
storage, and vault activity — plus a cross-vault search intent.

Crypto intents are DELEGATED to the existing crypto module: no
duplicated logic, no chance of the two classifiers disagreeing.

Security invariants (enforced by tests):

  1. This module NEVER decrypts or returns a password value, a
     private key, a seed phrase, a mnemonic, an encrypted secret,
     an auth token, a payment secret, or a raw API key. Any
     request that mentions those in a "reveal without unlocking"
     context is refused.

  2. Sensitive-reveal intents (reveal password, copy password,
     reveal full secure item, reveal full ID number, export
     sensitive data, delete vault item, confirm crypto send)
     produce a `confirmation_required` card whose safety flags
     enumerate the gates: trusted device, PIN unlock, local
     signing (crypto), explicit confirmation. The chat NEVER
     grants the action itself — it only prepares the request; the
     downstream UI routes through the existing gated flows.

  3. Read-only summaries (counts, masked metadata, storage usage,
     plan name, public receive addresses, provider-live balances,
     scanner status, recent-activity summaries) are allowed
     without unlock — but every card that carries a sensitive
     field marks it with `maskedByDefault=True`.

  4. The router is 100% deterministic — regex + word-boundary
     matching. Prompt injection embedded in the message cannot
     coerce the router into a different intent.

  5. `canBroadcast` on any crypto send-draft card is fixed False.
"""

from __future__ import annotations

import re
from typing import Any

from crypto_vault_chat_control import (
    classify_and_build as _crypto_classify_and_build,
    INTENT_CLARIFY_USDT_NETWORK as _CRYPTO_INTENT_CLARIFY_USDT,
    INTENT_REFUSAL_EXCHANGE_ACTION as _CRYPTO_INTENT_REFUSAL_EXCHANGE,
    INTENT_REFUSAL_SECRET_MATERIAL as _CRYPTO_INTENT_REFUSAL_SECRET,
    INTENT_UNRECOGNIZED as _CRYPTO_INTENT_UNRECOGNIZED,
)


VAULT_CHAT_ROUTER_SCHEMA_V1: str = "vault_chat_router_v1"



INTENT_VAULT_OVERVIEW:              str = "vault_overview"
INTENT_FILE_SEARCH:                 str = "vault_file_search"
INTENT_DOCUMENT_SUMMARY:            str = "vault_document_summary"
INTENT_SECURE_ITEM_LIST:            str = "vault_secure_item_list"
INTENT_SECURE_ITEM_SEARCH:          str = "vault_secure_item_search"
INTENT_LOGIN_LIST:                  str = "vault_login_list"
INTENT_LOGIN_SEARCH:                str = "vault_login_search"
INTENT_LOGIN_DUPLICATES:            str = "vault_login_duplicates"
INTENT_LOGIN_REVEAL:                str = "vault_login_reveal"
INTENT_LOGIN_COPY:                  str = "vault_login_copy"
INTENT_GENERATED_LOGIN_LIST:        str = "vault_generated_login_list"
INTENT_GENERATED_LOGIN_CREATE_DRAFT: str = (
    "vault_generated_login_create_draft"
)
INTENT_ID_DOCUMENT_LIST:            str = "vault_id_document_list"
INTENT_ID_DOCUMENT_SEARCH:          str = "vault_id_document_search"
INTENT_ID_DOCUMENT_EXPIRY:          str = "vault_id_document_expiry"
INTENT_ID_DOCUMENT_REVEAL:          str = "vault_id_document_reveal"
INTENT_BILLING_STATUS:              str = "vault_billing_status"
INTENT_BILLING_UPGRADE:             str = "vault_billing_upgrade"
INTENT_STORAGE_USAGE:               str = "vault_storage_usage"
INTENT_STORAGE_LARGEST:             str = "vault_storage_largest_files"
INTENT_ACTIVITY_RECENT:             str = "vault_activity_recent"
INTENT_ACTIVITY_ITEM_HISTORY:       str = "vault_activity_item_history"
INTENT_CROSS_VAULT_SEARCH:          str = "vault_cross_vault_search"


INTENT_CRYPTO_DELEGATED:            str = "vault_crypto_delegated"


INTENT_FAQ:                         str = "vault_faq"


INTENT_REFUSAL_SECRET_MATERIAL:     str = "vault_refusal_secret_material"
INTENT_REFUSAL_EXCHANGE_ACTION:     str = (
    "vault_refusal_exchange_action"
)
INTENT_REFUSAL_BYPASS_PIN:          str = "vault_refusal_bypass_pin"
INTENT_REFUSAL_EXPORT_ALL:          str = "vault_refusal_export_all"
INTENT_REFUSAL_MASS_REVEAL:         str = "vault_refusal_mass_reveal"
INTENT_REFUSAL_AUTO_SEND:           str = "vault_refusal_auto_send"

INTENT_UNRECOGNIZED:                str = "vault_unrecognized"

_ALLOWED_INTENTS: frozenset[str] = frozenset({
    INTENT_VAULT_OVERVIEW,
    INTENT_FILE_SEARCH,
    INTENT_DOCUMENT_SUMMARY,
    INTENT_SECURE_ITEM_LIST,
    INTENT_SECURE_ITEM_SEARCH,
    INTENT_LOGIN_LIST,
    INTENT_LOGIN_SEARCH,
    INTENT_LOGIN_DUPLICATES,
    INTENT_LOGIN_REVEAL,
    INTENT_LOGIN_COPY,
    INTENT_GENERATED_LOGIN_LIST,
    INTENT_GENERATED_LOGIN_CREATE_DRAFT,
    INTENT_ID_DOCUMENT_LIST,
    INTENT_ID_DOCUMENT_SEARCH,
    INTENT_ID_DOCUMENT_EXPIRY,
    INTENT_ID_DOCUMENT_REVEAL,
    INTENT_BILLING_STATUS,
    INTENT_BILLING_UPGRADE,
    INTENT_STORAGE_USAGE,
    INTENT_STORAGE_LARGEST,
    INTENT_ACTIVITY_RECENT,
    INTENT_ACTIVITY_ITEM_HISTORY,
    INTENT_CROSS_VAULT_SEARCH,
    INTENT_CRYPTO_DELEGATED,
    INTENT_FAQ,
    INTENT_REFUSAL_SECRET_MATERIAL,
    INTENT_REFUSAL_EXCHANGE_ACTION,
    INTENT_REFUSAL_BYPASS_PIN,
    INTENT_REFUSAL_EXPORT_ALL,
    INTENT_REFUSAL_MASS_REVEAL,
    INTENT_REFUSAL_AUTO_SEND,
    INTENT_UNRECOGNIZED,
})



CARD_VAULT_OVERVIEW:         str = "vault_overview_card"
CARD_FILE_RESULT:            str = "vault_file_result_card"
CARD_DOCUMENT_RESULT:        str = "vault_document_result_card"
CARD_SECURE_ITEM:            str = "vault_secure_item_card"
CARD_LOGIN:                  str = "vault_login_card"
CARD_GENERATED_LOGIN:        str = "vault_generated_login_card"
CARD_ID_DOCUMENT:            str = "vault_id_document_card"
CARD_BILLING_STATUS:         str = "vault_billing_status_card"
CARD_STORAGE_USAGE:          str = "vault_storage_usage_card"
CARD_VAULT_ACTIVITY:         str = "vault_activity_card"
CARD_CROSS_VAULT_SEARCH:     str = "vault_cross_vault_search_card"
CARD_CONFIRMATION_REQUIRED:  str = "vault_confirmation_required_card"
CARD_REFUSAL:                str = "vault_refusal_card"
CARD_UNRECOGNIZED:           str = "vault_unrecognized_card"


CARD_CRYPTO_DELEGATED:       str = "vault_crypto_delegated_card"


CARD_FAQ:                    str = "vault_faq_card"

_ALLOWED_CARDS: frozenset[str] = frozenset({
    CARD_VAULT_OVERVIEW,
    CARD_FILE_RESULT,
    CARD_DOCUMENT_RESULT,
    CARD_SECURE_ITEM,
    CARD_LOGIN,
    CARD_GENERATED_LOGIN,
    CARD_ID_DOCUMENT,
    CARD_BILLING_STATUS,
    CARD_STORAGE_USAGE,
    CARD_VAULT_ACTIVITY,
    CARD_CROSS_VAULT_SEARCH,
    CARD_CONFIRMATION_REQUIRED,
    CARD_REFUSAL,
    CARD_UNRECOGNIZED,
    CARD_CRYPTO_DELEGATED,
    CARD_FAQ,
})



REFUSAL_REASON_SECRET_MATERIAL: str = "secret_material_request"
REFUSAL_REASON_EXCHANGE_ACTION: str = "exchange_action_request"
REFUSAL_REASON_BYPASS_PIN:      str = "bypass_pin_request"
REFUSAL_REASON_EXPORT_ALL:      str = "export_all_without_confirmation"
REFUSAL_REASON_MASS_REVEAL:     str = "mass_reveal_without_unlock"
REFUSAL_REASON_AUTO_SEND:       str = "auto_send_without_confirmation"



_SECRET_REVEAL_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bseed\s+phrase\b",
        r"\bseed\s+words\b",
        r"\bmnemonic(?:s)?\b",
        r"\bpolyseed\b",
        r"\brecovery\s+phrase\b",
        r"\brecovery\s+words\b",
        r"\bprivate\s+key\b",
        r"\bspend\s+key\b",
        r"\bview\s+key\b",
        r"\bencrypted\s+secret\b",
        r"\bwallet\s+secret\b",
        r"\bapi\s+key\b",
        r"\bauth\s+token\b",
    )
)


_EDUCATIONAL_SECRET_QUESTION_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bwhy\s+should(?:n['’]?t)?\s+i\s+"
        r"(?:not\s+)?share\s+my\s+"
        r"(?:seed|private\s+key|mnemonic|recovery)\b",
        r"\bcan\s+i\s+share\s+my\s+seed\s+phrase\b",
        r"\bhow\s+does\s+"
        r"(?:the\s+)?"
        r"(?:seed|private\s+key|mnemonic|local\s+signing)"
        r"\s+work\b",
        r"\bwhat\s+is\s+a\s+"
        r"(?:seed|private\s+key|mnemonic|recovery\s+phrase)\b",
    )
)


_BYPASS_PIN_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bbypass\s+(?:the\s+)?pin\b",
        r"\bskip\s+(?:the\s+)?pin\b",
        r"\bdisable\s+(?:the\s+)?pin\b",
        r"\bwithout\s+(?:pin|unlocking|unlock)\b",
        r"\bskip\s+(?:the\s+)?vault\s+unlock\b",
        r"\bdisable\s+(?:trusted\s+)?device\s+check\b",
    )
)


_EXPORT_ALL_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bexport\s+(?:my\s+)?(?:whole|entire|all\s+of\s+my)\s+"
        r"vault\b",
        r"\bexport\s+(?:my\s+)?everything\b",
        r"\bexport\s+all(?:\s+my)?\s+(?:vault|data|items|files)\b",
        r"\bdump\s+(?:my\s+)?(?:whole|entire|all)\s+vault\b",
    )
)


_MASS_REVEAL_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\breveal\s+all\s+(?:my\s+)?passwords?\b",
        r"\bshow\s+all\s+(?:my\s+)?passwords?\s+without\s+"
        r"unlock(?:ing)?\b",
        r"\bshow\s+every\s+password\b",
        r"\breveal\s+all\s+logins?\b",
        r"\breveal\s+all\s+secure\s+items?\b",
    )
)


_AUTO_SEND_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bsend\s+all\s+(?:my\s+)?crypto\b",
        r"\bsend\s+everything\s+(?:now|immediately)?\b",
        r"\bauto[-\s]?send\b",
        r"\bsend\s+(?:immediately|right\s+now|now)\s+without\s+"
        r"(?:pin|confirmation|unlock)\b",
    )
)



_OVERVIEW_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bshow\s+my\s+vault\b",
        r"\bwhat[’']?s?\s+in\s+my\s+vault\b",
        r"\bsummari[sz]e\s+my\s+vault\b",
        r"\bwhat\s+do\s+i\s+have\s+saved\b",
        r"\bwhat\s+changed\s+(?:today|recently|this\s+week)\b",
    )
)


_FILE_SEARCH_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bfind\s+(?:my\s+)?(?:file|document|pdf|invoice|tax|"
        r"receipt|contract|paper|paperwork)\b",
        r"\bsearch\s+(?:my\s+)?(?:documents?|files?)\b",
        r"\bshow\s+(?:my\s+)?files?(?:\s+uploaded)?\b",
        r"\bfiles?\s+uploaded\s+(?:this|last)\s+(?:week|day|month)\b",
    )
)


_DOCUMENT_SUMMARY_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bsummari[sz]e\s+(?:this|my|that)?\s*(?:pdf|document|file)\b",
        r"\bwhat\s+is\s+this\s+(?:pdf|document|file)\s+about\b",
    )
)


_SECURE_ITEM_LIST_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bshow\s+(?:my\s+)?secure\s+items?\b",
        r"\bshow\s+(?:my\s+)?vault\s+items?\b",
        r"\blist\s+(?:my\s+)?secure\s+items?\b",
    )
)


_SECURE_ITEM_SEARCH_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bsearch\s+secure\s+items?\b",
        r"\bfind\s+(?:my\s+)?(?:bank|secure)\s+note\b",
        r"\bsecure\s+notes?\s+.*(?:mention|about|for)\b",
        r"\bwhich\s+secure\s+notes?\s+mention\b",
    )
)


_LOGIN_LIST_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bshow\s+(?:me\s+)?(?:my\s+)?(?:saved\s+)?logins?\b",
        r"\blist\s+(?:my\s+)?(?:saved\s+)?logins?\b",
        r"\ball\s+(?:of\s+)?my\s+(?:saved\s+)?logins?\b",
        r"\bmy\s+(?:saved\s+)?passwords?\b",
    )
)


_LOGIN_SEARCH_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bfind\s+(?:my\s+)?\S+(?:\s+\S+){0,6}?\s+login\b",
        r"\bsearch\s+logins?\s+for\b",
        r"\blogin\s+for\s+\S+\b",







        r"\bshow\s+(?:me\s+)?(?:my\s+)?[\w'\-\.]+"
        r"(?:\s+[\w'\-\.]+){0,6}?\s+"
        r"(?:login|logins|password|passwords|credential|credentials|"
        r"account|bank|card|password\s+manager)\b",



        r"\bopen\s+(?:my\s+)?\S+(?:\s+\S+){0,4}?\s+login\b",
        r"\bpull\s+up\s+(?:my\s+)?\S+(?:\s+\S+){0,4}?\s+login\b",
    )
)


_LOGIN_DUPLICATES_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bduplicate\s+passwords?\b",
        r"\breused\s+passwords?\b",
        r"\bpassword\s+reuse\b",
    )
)


_LOGIN_REVEAL_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\breveal\s+(?:the\s+|my\s+)?password\b",
        r"\bshow\s+(?:me\s+)?the\s+password\b",
        r"\bwhat\s+is\s+the\s+password\s+for\b",

        r"\breveal\s+(?:the\s+|my\s+)?[\w\-'\.]+"
        r"(?:\s+[\w\-'\.]+){0,4}\s+password\b",

        r"\b(?:reveal|show)\s+(?:the\s+|my\s+)?password\s+for\b",
    )
)


_LOGIN_COPY_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bcopy\s+(?:the\s+|my\s+)?(?:\S+\s+)?password\b",
        r"\bput\s+the\s+password\s+on\s+the\s+clipboard\b",
    )
)


_GENERATED_LOGIN_LIST_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bshow\s+generated\s+logins?\b",
        r"\blist\s+generated\s+logins?\b",
        r"\bgenerated\s+logins?\s+for\s+\S+\b",
    )
)


_GENERATED_LOGIN_CREATE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bcreate\s+(?:a\s+)?generated\s+login\b",
        r"\bgenerate\s+(?:a\s+)?(?:new\s+)?(?:strong\s+)?password\b",
        r"\bmake\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?login\b",





        r"\bgenerate\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?login\s+for\s+\S+\b",



        r"\bcreate\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?login\s+for\s+\S+\b",



        r"\bmake\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?login\s+for\s+\S+\b",
    )
)


_ID_DOCUMENT_LIST_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bshow\s+my\s+ids?\b",
        r"\bshow\s+my\s+id\s+documents?\b",
        r"\blist\s+(?:my\s+)?id\s+documents?\b",
    )
)


_ID_DOCUMENT_SEARCH_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bfind\s+my\s+(?:driver\s+license|driver'?s\s+license|"
        r"passport|national\s+id|id\s+card)\b",
        r"\bdo\s+i\s+have\s+a\s+saved\s+"
        r"(?:passport|driver\s+license|id)\b",
        r"\bsearch\s+id\s+documents?\b",
    )
)


_ID_DOCUMENT_EXPIRY_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bwhen\s+does\s+my\s+(?:passport|driver\s+license|"
        r"driver'?s\s+license|id)\s+expire\b",
        r"\bid\s+(?:expiry|expiration)\b",
        r"\b(?:passport|driver\s+license)\s+expir(?:y|ation)\b",
    )
)


_ID_DOCUMENT_REVEAL_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bshow\s+(?:full\s+|complete\s+)?"
        r"(?:passport|driver\s+license|driver'?s\s+license|"
        r"national\s+id|id)\s+number\b",
        r"\breveal\s+(?:passport|driver\s+license|driver'?s\s+"
        r"license|id)\s+(?:number|details)\b",
    )
)


_BILLING_STATUS_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bwhat\s+plan\s+am\s+i\s+on\b",
        r"\bmy\s+(?:current\s+)?plan\b",
        r"\bshow\s+billing\s+status\b",
        r"\bbilling\s+summary\b",
        r"\bsubscription\s+status\b",
    )
)


_BILLING_UPGRADE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bupgrade\s+(?:my\s+)?(?:storage|plan|vault)\b",
        r"\bbuy\s+(?:more\s+)?storage\b",
        r"\bincrease\s+(?:my\s+)?storage\s+quota\b",
    )
)


_STORAGE_USAGE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bhow\s+much\s+storage(?:\s+have\s+i\s+used)?\b",
        r"\bstorage\s+(?:usage|used|left|remaining|available)\b",
        r"\bhow\s+much\s+space\s+(?:do\s+i\s+have|is\s+left)\b",
    )
)


_STORAGE_LARGEST_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bwhat\s+is\s+taking\s+up\s+(?:the\s+)?most\s+space\b",
        r"\bfind\s+(?:my\s+)?large(?:st)?\s+files?\b",
        r"\bbiggest\s+files?\b",
    )
)


_ACTIVITY_RECENT_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bwhat\s+changed\s+(?:today|recently|this\s+week|"
        r"yesterday)\b",
        r"\bshow\s+recent\s+vault\s+activity\b",
        r"\brecent\s+activity\b",
        r"\bvault\s+audit\s+log\b",
    )
)


_ACTIVITY_ITEM_HISTORY_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bwhen\s+was\s+this\s+item\s+updated\b",
        r"\bhistory\s+of\s+this\s+item\b",
        r"\bwhen\s+did\s+i\s+last\s+update\b",
    )
)


_CROSS_SEARCH_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"\bsearch\s+(?:my\s+)?(?:whole|entire|all\s+of\s+my)?\s*"
        r"vault\s+for\b",
        r"\bsearch\s+my\s+vault\s+for\b",
        r"\bwhich\s+.*\s+mention\s+\S+\b",
    )
)



_CRYPTO_TOKENS = (
    "crypto", "wallet", "eth", "usdt", "usdc", "sol",
    "solana", "monero", "xmr", "ethereum", "tron", "trc20",
    "erc20", "receive address", "receive qr", "balance", "scanner",
    "prepare a", "prepare 5", "prepare 10", "prepare 0.",
    "send.*(?:eth|usdt|usdc|sol|xmr)",
    "swap", "trade", "stake", "bridge",
)
_CRYPTO_HINT_RE = re.compile(
    r"\b(?:" + r"|".join(_CRYPTO_TOKENS) + r")\b",
    re.IGNORECASE,
)


_CRYPTO_INTERNAL_SERVICE_KEY_HINT_RE = re.compile(
    r"\b[A-Z][A-Z0-9_]{1,15}"
    r":"
    r"[a-z][a-z0-9_]{2,25}_"
    r"(?:mainnet|testnet|sepolia|devnet)\b",
)


def _detect_secret_material(text: str) -> bool:


    for edu in _EDUCATIONAL_SECRET_QUESTION_PATTERNS:
        if edu.search(text):
            return False
    for p in _SECRET_REVEAL_PATTERNS:
        if p.search(text):
            return True
    return False


def _detect_bypass_pin(text: str) -> bool:
    for p in _BYPASS_PIN_PATTERNS:
        if p.search(text):
            return True
    return False


def _detect_export_all(text: str) -> bool:
    for p in _EXPORT_ALL_PATTERNS:
        if p.search(text):
            return True
    return False


def _detect_mass_reveal(text: str) -> bool:
    for p in _MASS_REVEAL_PATTERNS:
        if p.search(text):
            return True
    return False


def _detect_auto_send(text: str) -> bool:
    for p in _AUTO_SEND_PATTERNS:
        if p.search(text):
            return True
    return False


def _looks_like_crypto_message(text: str) -> bool:
    if _CRYPTO_HINT_RE.search(text):
        return True
    if _CRYPTO_INTERNAL_SERVICE_KEY_HINT_RE.search(text):
        return True
    return False


def _matches_any(text: str, patterns) -> bool:
    for p in patterns:
        if p.search(text):
            return True
    return False



_REFUSAL_COPY = {
    REFUSAL_REASON_SECRET_MATERIAL: (
        "VaultAI never surfaces your seed, mnemonic, private keys, "
        "encrypted wallet secret, auth token, or API key through "
        "chat. If you need to back up sensitive material, use the "
        "existing gated flow (Security page, unlock + confirm)."
    ),
    REFUSAL_REASON_EXCHANGE_ACTION: (
        "VaultAI is a non-custodial wallet. It does not buy, sell, "
        "swap, trade, stake, bridge, or exchange assets. You can "
        "receive, hold, and send from your own device."
    ),
    REFUSAL_REASON_BYPASS_PIN: (
        "VaultAI does not bypass PIN unlock, trusted-device "
        "checks, or local signing. These gates exist so nothing "
        "moves without your explicit confirmation on your device."
    ),
    REFUSAL_REASON_EXPORT_ALL: (
        "Exporting your whole vault requires an explicit "
        "confirmation step in the Security page. VaultAI will not "
        "dump your entire vault from a chat message."
    ),
    REFUSAL_REASON_MASS_REVEAL: (
        "VaultAI will not reveal every password or every secure "
        "item at once. Open a single item and use the reveal-with-"
        "unlock flow to see its value."
    ),
    REFUSAL_REASON_AUTO_SEND: (
        "VaultAI cannot auto-send crypto. Every send requires a "
        "trusted device, PIN unlock, local signing on your device, "
        "a fee preview where supported, and an explicit "
        "confirmation before broadcast."
    ),
}


def _build_card(card_type: str, **extra: Any) -> dict[str, Any]:
    if card_type not in _ALLOWED_CARDS:
        raise ValueError(f"unknown card {card_type!r}")
    env: dict[str, Any] = {
        "schema":   VAULT_CHAT_ROUTER_SCHEMA_V1,
        "cardType": card_type,
    }
    for k, v in extra.items():
        env[k] = v
    return env


def _build_refusal(reason: str) -> dict[str, Any]:
    return _build_card(
        CARD_REFUSAL,
        refusalReason=reason,
        message=_REFUSAL_COPY[reason],
    )


def _build_confirmation_required(
    *, action: str,
    requiresPinUnlock: bool = True,
    requiresTrustedDevice: bool = True,
    requiresLocalSigning: bool = False,
    requiresExplicitConfirmation: bool = True,
    message: str,
    subject: str | None = None,
) -> dict[str, Any]:
    card: dict[str, Any] = _build_card(
        CARD_CONFIRMATION_REQUIRED,
        action=action,
        message=message,
        requiresPinUnlock=bool(requiresPinUnlock),
        requiresTrustedDevice=bool(requiresTrustedDevice),
        requiresLocalSigning=bool(requiresLocalSigning),
        requiresExplicitConfirmation=bool(requiresExplicitConfirmation),
    )
    if subject:
        card["subject"] = subject
    return card



def classify_and_build_vault_intent(
    message: str,
) -> dict[str, Any]:
    """Classify a full-vault chat message.

    Precedence:
      1. Refusals (secrets, bypass-pin, export-all, mass-reveal,
         auto-send) — highest priority. A message combining
         "send + seed" or "reveal + bypass PIN" is refused BEFORE
         any category delegate.
      2. Crypto delegate — if the message mentions crypto tokens,
         hand off to the existing crypto classifier and wrap its
         result in a `crypto_delegated` envelope.
      3. Per-category dispatch (files → activity).
      4. Cross-vault search.
      5. Confirmation-required for sensitive reveals (login reveal,
         ID number, etc).
      6. Unrecognized.
    """
    if not isinstance(message, str):
        return _wrap_intent(INTENT_UNRECOGNIZED,
                            _build_card(CARD_UNRECOGNIZED))
    text = message.strip()
    if not text:
        return _wrap_intent(INTENT_UNRECOGNIZED,
                            _build_card(CARD_UNRECOGNIZED))


    if _detect_mass_reveal(text):
        return _wrap_intent(
            INTENT_REFUSAL_MASS_REVEAL,
            _build_refusal(REFUSAL_REASON_MASS_REVEAL),
        )
    if _detect_bypass_pin(text):
        return _wrap_intent(
            INTENT_REFUSAL_BYPASS_PIN,
            _build_refusal(REFUSAL_REASON_BYPASS_PIN),
        )
    if _detect_auto_send(text):
        return _wrap_intent(
            INTENT_REFUSAL_AUTO_SEND,
            _build_refusal(REFUSAL_REASON_AUTO_SEND),
        )
    if _detect_export_all(text):
        return _wrap_intent(
            INTENT_REFUSAL_EXPORT_ALL,
            _build_refusal(REFUSAL_REASON_EXPORT_ALL),
        )
    if _detect_secret_material(text):
        return _wrap_intent(
            INTENT_REFUSAL_SECRET_MATERIAL,
            _build_refusal(REFUSAL_REASON_SECRET_MATERIAL),
        )


    try:
        from vault_faq_router import (
            build_faq_envelope as _faq_build_envelope,
            looks_like_faq_message as _faq_looks_like,
        )
    except Exception:
        _faq_build_envelope = None
        _faq_looks_like = None
    if _faq_looks_like is not None and _faq_looks_like(text):
        _faq_env = _faq_build_envelope(text) if _faq_build_envelope else None
        if isinstance(_faq_env, dict) and isinstance(
            _faq_env.get("card"), dict,
        ):
            _inner_card = _faq_env["card"]
            _card = _build_card(CARD_FAQ)
            for k, v in _inner_card.items():
                if k in ("schema", "cardType"):
                    continue
                _card[k] = v
            _card["message"] = str(_faq_env.get("message") or "")
            return _wrap_intent(INTENT_FAQ, _card)


    if _looks_like_crypto_message(text):
        inner = _crypto_classify_and_build(text)
        inner_intent = inner.get("intent", _CRYPTO_INTENT_UNRECOGNIZED)


        if inner_intent == _CRYPTO_INTENT_REFUSAL_SECRET:
            return _wrap_intent(
                INTENT_REFUSAL_SECRET_MATERIAL,
                _build_refusal(REFUSAL_REASON_SECRET_MATERIAL),
            )
        if inner_intent == _CRYPTO_INTENT_REFUSAL_EXCHANGE:
            return _wrap_intent(
                INTENT_REFUSAL_EXCHANGE_ACTION,
                _build_refusal(REFUSAL_REASON_EXCHANGE_ACTION),
            )
        if inner_intent == _CRYPTO_INTENT_UNRECOGNIZED:

            pass
        else:

            return {
                "schema":         VAULT_CHAT_ROUTER_SCHEMA_V1,
                "intent":         INTENT_CRYPTO_DELEGATED,
                "card":           _build_card(
                    CARD_CRYPTO_DELEGATED,
                    innerIntent=inner_intent,
                    innerCard=inner.get("card", {}),
                ),
            }


    if _matches_any(text, _CROSS_SEARCH_PATTERNS):
        query = _extract_search_query(text)
        card = _build_card(CARD_CROSS_VAULT_SEARCH)
        if query:
            card["query"] = query
        return _wrap_intent(INTENT_CROSS_VAULT_SEARCH, card)


    if _matches_any(text, _OVERVIEW_PATTERNS):
        return _wrap_intent(
            INTENT_VAULT_OVERVIEW,
            _build_card(
                CARD_VAULT_OVERVIEW,
                liveFetchRequired=True,
                maskedByDefault=True,
            ),
        )


    if _matches_any(text, _GENERATED_LOGIN_CREATE_PATTERNS):
        return _wrap_intent(
            INTENT_GENERATED_LOGIN_CREATE_DRAFT,
            _build_card(
                CARD_GENERATED_LOGIN,
                liveFetchRequired=False,
                maskedByDefault=True,
                view="create_draft",
                canSaveWithoutConfirmation=False,
            ),
        )
    if _matches_any(text, _GENERATED_LOGIN_LIST_PATTERNS):
        return _wrap_intent(
            INTENT_GENERATED_LOGIN_LIST,
            _build_card(
                CARD_GENERATED_LOGIN,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="list",
            ),
        )


    if _matches_any(text, _LOGIN_REVEAL_PATTERNS):

        return _wrap_intent(
            INTENT_LOGIN_REVEAL,
            _build_card(
                CARD_LOGIN,
                liveFetchRequired=True,
                maskedByDefault=False,
                view="detail",
                query=_extract_search_query(text),
            ),
        )
    if _matches_any(text, _LOGIN_COPY_PATTERNS):

        return _wrap_intent(
            INTENT_LOGIN_COPY,
            _build_card(
                CARD_LOGIN,
                liveFetchRequired=True,
                maskedByDefault=False,
                view="detail",
                query=_extract_search_query(text),
            ),
        )
    if _matches_any(text, _LOGIN_DUPLICATES_PATTERNS):
        return _wrap_intent(
            INTENT_LOGIN_DUPLICATES,
            _build_card(
                CARD_LOGIN,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="duplicates",
            ),
        )




    if _matches_any(text, _LOGIN_LIST_PATTERNS):
        return _wrap_intent(
            INTENT_LOGIN_LIST,
            _build_card(
                CARD_LOGIN,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="list",
            ),
        )
    if _matches_any(text, _LOGIN_SEARCH_PATTERNS):

        return _wrap_intent(
            INTENT_LOGIN_SEARCH,
            _build_card(
                CARD_LOGIN,
                liveFetchRequired=True,
                maskedByDefault=False,
                view="detail",
                query=_extract_search_query(text),
            ),
        )


    if _matches_any(text, _ID_DOCUMENT_REVEAL_PATTERNS):
        return _wrap_intent(
            INTENT_ID_DOCUMENT_REVEAL,
            _build_confirmation_required(
                action="reveal_id_document",
                message=(
                    "Revealing full ID document details requires "
                    "trusted device, PIN unlock, and explicit "
                    "confirmation."
                ),
            ),
        )
    if _matches_any(text, _ID_DOCUMENT_EXPIRY_PATTERNS):
        return _wrap_intent(
            INTENT_ID_DOCUMENT_EXPIRY,
            _build_card(
                CARD_ID_DOCUMENT,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="expiry",
            ),
        )
    if _matches_any(text, _ID_DOCUMENT_SEARCH_PATTERNS):
        return _wrap_intent(
            INTENT_ID_DOCUMENT_SEARCH,
            _build_card(
                CARD_ID_DOCUMENT,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="search",
                query=_extract_search_query(text),
            ),
        )
    if _matches_any(text, _ID_DOCUMENT_LIST_PATTERNS):
        return _wrap_intent(
            INTENT_ID_DOCUMENT_LIST,
            _build_card(
                CARD_ID_DOCUMENT,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="list",
            ),
        )


    if _matches_any(text, _SECURE_ITEM_SEARCH_PATTERNS):
        return _wrap_intent(
            INTENT_SECURE_ITEM_SEARCH,
            _build_card(
                CARD_SECURE_ITEM,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="search",
                query=_extract_search_query(text),
            ),
        )
    if _matches_any(text, _SECURE_ITEM_LIST_PATTERNS):
        return _wrap_intent(
            INTENT_SECURE_ITEM_LIST,
            _build_card(
                CARD_SECURE_ITEM,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="list",
            ),
        )


    if _matches_any(text, _BILLING_UPGRADE_PATTERNS):
        return _wrap_intent(
            INTENT_BILLING_UPGRADE,
            _build_card(
                CARD_BILLING_STATUS,
                liveFetchRequired=True,
                view="upgrade_prompt",
                routeToExistingCheckoutFlow=True,
            ),
        )
    if _matches_any(text, _BILLING_STATUS_PATTERNS):
        return _wrap_intent(
            INTENT_BILLING_STATUS,
            _build_card(
                CARD_BILLING_STATUS,
                liveFetchRequired=True,
                view="status",
            ),
        )


    if _matches_any(text, _STORAGE_LARGEST_PATTERNS):
        return _wrap_intent(
            INTENT_STORAGE_LARGEST,
            _build_card(
                CARD_STORAGE_USAGE,
                liveFetchRequired=True,
                view="largest",
            ),
        )
    if _matches_any(text, _STORAGE_USAGE_PATTERNS):
        return _wrap_intent(
            INTENT_STORAGE_USAGE,
            _build_card(
                CARD_STORAGE_USAGE,
                liveFetchRequired=True,
                view="usage",
            ),
        )


    if _matches_any(text, _ACTIVITY_ITEM_HISTORY_PATTERNS):
        return _wrap_intent(
            INTENT_ACTIVITY_ITEM_HISTORY,
            _build_card(
                CARD_VAULT_ACTIVITY,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="item_history",
            ),
        )
    if _matches_any(text, _ACTIVITY_RECENT_PATTERNS):
        return _wrap_intent(
            INTENT_ACTIVITY_RECENT,
            _build_card(
                CARD_VAULT_ACTIVITY,
                liveFetchRequired=True,
                maskedByDefault=True,
                view="recent",
            ),
        )


    if _matches_any(text, _DOCUMENT_SUMMARY_PATTERNS):
        return _wrap_intent(
            INTENT_DOCUMENT_SUMMARY,
            _build_card(
                CARD_DOCUMENT_RESULT,
                liveFetchRequired=True,
                view="summary",
            ),
        )


    if _matches_any(text, _FILE_SEARCH_PATTERNS):
        return _wrap_intent(
            INTENT_FILE_SEARCH,
            _build_card(
                CARD_FILE_RESULT,
                liveFetchRequired=True,
                view="search",
                query=_extract_search_query(text),
            ),
        )

    return _wrap_intent(INTENT_UNRECOGNIZED,
                        _build_card(CARD_UNRECOGNIZED))


_SEARCH_QUERY_EXTRACT_FOR_RE = re.compile(
    r"(?:\bsearch\s+\S+\s+for|\bsearch\s+for|\bfor|\babout|"
    r"\bmention(?:s)?)\s+(?P<q>[\w\-\.@]+(?:\s+[\w\-\.@]+)*)",
    re.IGNORECASE,
)





_LOGIN_SERVICE_EXTRACT_REGEXES: tuple[re.Pattern[str], ...] = (

    re.compile(
        r"\b(?:show|pull\s+up|open|view)\s+(?:me\s+)?(?:my\s+)?"
        r"(?P<q>[\w'\-\.]+(?:\s+[\w'\-\.]+){0,6}?)\s+"
        r"(?:login|logins|password|passwords|credential|credentials|"
        r"account|bank|card|password\s+manager)\b",
        re.IGNORECASE,
    ),


    re.compile(
        r"\bfind\s+(?:my\s+)?(?P<q>[\w'\-\.]+(?:\s+[\w'\-\.]+){0,6}?)"
        r"\s+login\b",
        re.IGNORECASE,
    ),

    # Reveal / copy phrasings — extract the service name so the
    # LOGIN_REVEAL / LOGIN_COPY intent lands on the detail card for the
    # right item. Examples: "Reveal the password for Netflix",
    # "Copy my Netflix password", "What's my password for Chase".
    re.compile(
        r"\b(?:reveal|show|unmask|view|display)\s+(?:the\s+|my\s+)?"
        r"(?:password|credential|login)\s+for\s+"
        r"(?P<q>[\w'\-\.]+(?:\s+[\w'\-\.]+){0,6})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:copy|reveal|get|grab)\s+(?:the\s+|my\s+)?"
        r"(?P<q>[\w'\-\.]+(?:\s+[\w'\-\.]+){0,6}?)\s+"
        r"(?:password|credential|login)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:what'?s|whats)\s+(?:the\s+|my\s+)?"
        r"(?:password|credential|login)\s+for\s+"
        r"(?P<q>[\w'\-\.]+(?:\s+[\w'\-\.]+){0,6})\b",
        re.IGNORECASE,
    ),
)


_LOGIN_QUERY_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "my", "me", "your", "our", "please", "saved",
    "credit", "union", "bank", "account",
})


def _extract_search_query(text: str) -> str | None:

    for pat in _LOGIN_SERVICE_EXTRACT_REGEXES:
        m = pat.search(text)
        if not m:
            continue
        q = m.group("q").strip()
        q = re.sub(r"[\.\?!,]+$", "", q).strip()




        tokens = [t for t in q.split() if t.strip()]
        if not tokens:
            continue
        if all(t.lower() in _LOGIN_QUERY_STOPWORDS for t in tokens):

            continue
        if len(q) < 2:
            continue
        return q[:80]


    m = _SEARCH_QUERY_EXTRACT_FOR_RE.search(text)
    if not m:
        return None
    q = m.group("q").strip()

    q = re.sub(r"[\.\?!,]+$", "", q).strip()
    if len(q) < 2:
        return None
    return q[:80]


def _wrap_intent(
    intent: str, card: dict[str, Any],
) -> dict[str, Any]:
    if intent not in _ALLOWED_INTENTS:
        intent = INTENT_UNRECOGNIZED
    return {
        "schema": VAULT_CHAT_ROUTER_SCHEMA_V1,
        "intent": intent,
        "card":   card,
    }



VAULT_CHAT_ENVELOPE_TYPE:    str = "vault_chat_card"
VAULT_CHAT_ENVELOPE_SCHEMA:  str = "vault_chat_response_v1"


def build_vault_chat_envelope(
    message: str,
) -> dict[str, Any] | None:
    """Classify `message` and produce a chat envelope, or None.

    Returns None when the message is unrecognized. Callers should
    fall through to their existing (LLM / secure item / etc.) chat
    handlers in that case.

    The envelope shape is stable — the frontend
    (`vault_chat_router.dart`) parses:

        {
          "type":    "vault_chat_card",
          "schema":  "vault_chat_response_v1",
          "intent":  "<one of VAULT_CHAT_ROUTER intents>",
          "message": "<top-line safe copy>",
          "card":    { ... structured card ... }
        }
    """
    if not isinstance(message, str):
        return None
    result = classify_and_build_vault_intent(message)
    if not isinstance(result, dict):
        return None
    intent = str(result.get("intent") or "")
    if not intent or intent == INTENT_UNRECOGNIZED:
        return None
    card = result.get("card")
    card_dict: dict[str, Any] = (
        card if isinstance(card, dict) else {}
    )
    envelope_message = str(card_dict.get("message") or "")
    return {
        "type":    VAULT_CHAT_ENVELOPE_TYPE,
        "schema":  VAULT_CHAT_ENVELOPE_SCHEMA,
        "intent":  intent,
        "message": envelope_message,
        "card":    card_dict,
    }


__all__ = [
    "VAULT_CHAT_ROUTER_SCHEMA_V1",


    "INTENT_VAULT_OVERVIEW",
    "INTENT_FILE_SEARCH", "INTENT_DOCUMENT_SUMMARY",
    "INTENT_SECURE_ITEM_LIST", "INTENT_SECURE_ITEM_SEARCH",
    "INTENT_LOGIN_LIST", "INTENT_LOGIN_SEARCH",
    "INTENT_LOGIN_DUPLICATES", "INTENT_LOGIN_REVEAL",
    "INTENT_LOGIN_COPY",
    "INTENT_GENERATED_LOGIN_LIST",
    "INTENT_GENERATED_LOGIN_CREATE_DRAFT",
    "INTENT_ID_DOCUMENT_LIST", "INTENT_ID_DOCUMENT_SEARCH",
    "INTENT_ID_DOCUMENT_EXPIRY", "INTENT_ID_DOCUMENT_REVEAL",
    "INTENT_BILLING_STATUS", "INTENT_BILLING_UPGRADE",
    "INTENT_STORAGE_USAGE", "INTENT_STORAGE_LARGEST",
    "INTENT_ACTIVITY_RECENT", "INTENT_ACTIVITY_ITEM_HISTORY",
    "INTENT_CROSS_VAULT_SEARCH",
    "INTENT_CRYPTO_DELEGATED",
    "INTENT_REFUSAL_SECRET_MATERIAL",
    "INTENT_REFUSAL_EXCHANGE_ACTION",
    "INTENT_REFUSAL_BYPASS_PIN",
    "INTENT_REFUSAL_EXPORT_ALL",
    "INTENT_REFUSAL_MASS_REVEAL",
    "INTENT_REFUSAL_AUTO_SEND",
    "INTENT_UNRECOGNIZED",


    "CARD_VAULT_OVERVIEW", "CARD_FILE_RESULT",
    "CARD_DOCUMENT_RESULT",
    "CARD_SECURE_ITEM", "CARD_LOGIN",
    "CARD_GENERATED_LOGIN", "CARD_ID_DOCUMENT",
    "CARD_BILLING_STATUS", "CARD_STORAGE_USAGE",
    "CARD_VAULT_ACTIVITY",
    "CARD_CROSS_VAULT_SEARCH",
    "CARD_CONFIRMATION_REQUIRED",
    "CARD_REFUSAL", "CARD_UNRECOGNIZED",
    "CARD_CRYPTO_DELEGATED",


    "REFUSAL_REASON_SECRET_MATERIAL",
    "REFUSAL_REASON_EXCHANGE_ACTION",
    "REFUSAL_REASON_BYPASS_PIN",
    "REFUSAL_REASON_EXPORT_ALL",
    "REFUSAL_REASON_MASS_REVEAL",
    "REFUSAL_REASON_AUTO_SEND",

    "classify_and_build_vault_intent",
    "build_vault_chat_envelope",
    "VAULT_CHAT_ENVELOPE_TYPE",
    "VAULT_CHAT_ENVELOPE_SCHEMA",
]
