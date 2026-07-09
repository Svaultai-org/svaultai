"""VaultAI FAQ / Help Center router.

Closed-set deterministic matcher over vault_faq_content.py. Used by
the umbrella vault_chat_router to answer help / how-do-I / what-is
type questions from chat.

Safety invariants:

  1. NEVER surfaces or asks for a seed, mnemonic, private key,
     spend/view key, encrypted wallet secret, auth token, API key,
     PIN, password, or raw ID number. Safety-refusal precedence in
     the umbrella router runs BEFORE this module.
  2. Every answer is drawn from vault_faq_content.FAQ_ENTRIES —
     no generation, no LLM. What ships is what the tests approve.
  3. Every FAQ ID and category is closed-set (validated at import
     time by vault_faq_content._validate_entries).
  4. The router NEVER claims a feature that does not exist. The
     entries are the SOLE source of behavioural claims.
  5. Unmatched help-y questions return None — the caller falls
     through to the next dispatch layer (file search or LLM).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from vault_faq_content import (
    FAQ_ACTION_OPEN_HELP_CENTER,
    FAQ_BY_ID,
    FAQ_CATEGORIES,
    FAQ_CATEGORY_LABELS,
    FAQ_ENTRIES,
    FAQ_SCHEMA_V1,
    all_ids,
)


VAULT_FAQ_CARD_TYPE: str = "vault_faq_card"


VAULT_FAQ_INTENT: str = "vault_faq"


_PATTERNS_BY_ID: dict[str, tuple[re.Pattern, ...]] = {


    "what-is-vaultai": tuple(re.compile(p, re.IGNORECASE) for p in (
        r"\bwhat\s+is\s+vault\s*ai\b",
        r"\bwhat\s+does\s+vault\s*ai\s+do\b",
        r"\bwhat\s+can\s+vault\s*ai\s+do\b",
        r"\bhow\s+does\s+vault\s*ai\s+work\b",
        r"\bwhat['’]?s\s+vault\s*ai\b",
    )),
    "what-can-i-save": tuple(re.compile(p, re.IGNORECASE) for p in (
        r"\bwhat\s+can\s+i\s+save\b",
        r"\bwhat\s+can\s+i\s+store\b",
        r"\bwhat\s+can\s+i\s+put\s+in\s+my\s+vault\b",
    )),
    "how-do-i-create-my-vault": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+create\s+(?:my\s+|a\s+)?vault\b",
            r"\bhow\s+to\s+create\s+(?:my\s+)?vault\b",
            r"\bhow\s+do\s+i\s+sign\s+up\b",
        )
    ),
    "how-do-i-unlock-my-vault": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+unlock(?:\s+my\s+vault)?\b",
            r"\bhow\s+to\s+unlock\s+(?:the\s+)?vault\b",
        )
    ),
    "trusted-device": tuple(re.compile(p, re.IGNORECASE) for p in (
        r"\bwhat\s+is\s+a\s+trusted\s+device\b",
        r"\btrusted\s+device\s+meaning\b",
        r"\bwhat\s+does\s+trusted\s+device\s+mean\b",
    )),
    "files-vs-secure-items": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bdifference\s+between\s+files?\s+and\s+secure\s+items?\b",
            r"\bfiles?\s+vs\s+secure\s+items?\b",
            r"\bfiles?\s+or\s+secure\s+items?\b",
        )
    ),


    "is-my-vault-encrypted": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bis\s+my\s+vault\s+encrypted\b",
            r"\bdoes\s+vault\s*ai\s+encrypt\b",
            r"\bis\s+vault\s*ai\s+encrypted\b",
        )
    ),
    "can-vaultai-read-secrets": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+vault\s*ai\s+read\s+my\s+"
            r"(?:\w+\s+)?"
            r"(?:secrets?|seed|private\s+keys?|passwords?)\b",
            r"\bdoes\s+vault\s*ai\s+know\s+my\s+"
            r"(?:seed|passwords?|private\s+keys?)\b",
            r"\bcan\s+the\s+ai\s+see\s+my\s+"
            r"(?:seed|passwords?|private\s+keys?)\b",
        )
    ),
    "if-i-forget-my-pin": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhat\s+happens\s+if\s+i\s+forget\s+(?:my\s+)?pin\b",
            r"\bwhat\s+if\s+i\s+forget\s+(?:my\s+)?pin\b",
            r"\bforgot\s+(?:my\s+)?pin\b",
            r"\bi\s+lost\s+my\s+pin\b",
            r"\bcan\s+i\s+recover\s+my\s+pin\b",
        )
    ),
    "can-someone-else-access": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+someone\s+else\s+access\s+my\s+vault\b",
            r"\bcan\s+anyone\s+else\s+get\s+in\s+my\s+vault\b",
            r"\bis\s+my\s+vault\s+safe\b",
        )
    ),
    "lost-my-device": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\b(?:lost|stolen|missing)\s+(?:my\s+)?device\b",
            r"\bwhat\s+(?:do\s+i\s+do\s+|should\s+i\s+do\s+)?"
            r"if\s+i\s+lose\s+my\s+device\b",
            r"\bmy\s+phone\s+was\s+(?:lost|stolen)\b",
        )
    ),
    "how-local-signing-works": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+does\s+local\s+signing\s+work\b",
            r"\bwhat\s+is\s+local\s+signing\b",
        )
    ),
    "never-share-seed": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+(?:should|shouldn['’]?t)\s+i\s+"
            r"(?:not\s+)?share\s+my\s+"
            r"(?:seed(?:\s+phrase)?|private\s+key|mnemonic)\b",
            r"\bcan\s+i\s+share\s+my\s+seed\s+phrase\b",
        )
    ),
    "what-happens-when-i-delete-my-vault": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhat\s+happens\s+"
            r"(?:when|if)\s+i\s+delete\s+my\s+"
            r"(?:vault|profile|account)\b",
            r"\bwhat\s+will\s+happen\s+"
            r"(?:when|if)\s+i\s+delete\s+my\s+"
            r"(?:vault|profile|account)\b",
        )
    ),
    "can-i-recover-deleted-vault": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+i\s+recover\s+(?:a\s+|my\s+)?"
            r"deleted\s+(?:vault|profile|account)\b",
            r"\bcan\s+i\s+restore\s+(?:a\s+|my\s+)?"
            r"deleted\s+(?:vault|profile|account)\b",
            r"\bis\s+(?:my\s+)?deleted\s+"
            r"(?:vault|profile|account)\s+recoverable\b",
            r"\bwhy\s+was\s+my\s+"
            r"(?:vault|profile|account)\s+deleted\b",
        )
    ),
    "delete-my-vault": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+delete\s+my\s+"
            r"(?:vault|profile|account)\b",
            r"\bhow\s+to\s+delete\s+(?:my\s+)?"
            r"(?:vault|profile|account)\b",
            r"^\s*delete\s+my\s+(?:vault|profile|account)\s*[\.\?!]*\s*$",
            r"\bi\s+want\s+to\s+delete\s+my\s+"
            r"(?:vault|profile|account)\b",
            r"\bclose\s+my\s+(?:vault|account)\b",
        )
    ),


    "how-do-i-upload-files": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+upload\s+(?:a\s+)?files?\b",
            r"\bhow\s+to\s+upload\s+files?\b",
        )
    ),
    "what-file-types": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhat\s+file\s+types\s+can\s+i\s+store\b",
            r"\bwhat\s+kinds?\s+of\s+files?\s+can\s+i\s+upload\b",
            r"\bwhich\s+file\s+types\b",
        )
    ),
    "search-inside-documents": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+i\s+search\s+inside\s+(?:my\s+)?documents?\b",
            r"\bfull\s+text\s+search\b",
        )
    ),
    "summarize-pdf": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+vault\s*ai\s+summari[sz]e\s+(?:my\s+)?pdf\b",
            r"\bhow\s+does\s+pdf\s+summari[sz]ation\s+work\b",
        )
    ),
    "why-cant-find-file": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+can['’]?t\s+vault\s*ai\s+find\s+my\s+file\b",
            r"\bwhy\s+is\s+my\s+file\s+missing\b",
        )
    ),
    "how-do-i-delete-a-file": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+delete\s+(?:a\s+)?file\b",
        )
    ),


    "how-do-i-save-a-password": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+save\s+(?:a\s+)?(?:new\s+)?password\b",
            r"\bhow\s+to\s+save\s+(?:a\s+)?login\b",
        )
    ),
    "how-do-i-view-a-password": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+view\s+(?:a\s+)?(?:saved\s+)?password\b",
            r"\bhow\s+can\s+i\s+see\s+(?:my\s+)?password\b",
        )
    ),
    "why-are-passwords-masked": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+are\s+(?:my\s+)?passwords?\s+"
            r"(?:masked|hidden)\b",
            r"\bwhy\s+can['’]?t\s+i\s+see\s+the\s+password\s+directly\b",
        )
    ),
    "generated-login": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+create\s+a\s+generated\s+login\b",
            r"\bhow\s+to\s+generate\s+a\s+login\b",
        )
    ),
    "edit-delete-secure-item": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+edit\s+(?:or\s+delete\s+)?"
            r"(?:a\s+)?secure\s+item\b",
            r"\bhow\s+do\s+i\s+delete\s+(?:a\s+)?secure\s+item\b",
        )
    ),
    "duplicate-logins": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+vault\s*ai\s+find\s+duplicate\s+logins?\b",
            r"\bhow\s+do\s+i\s+find\s+duplicate\s+passwords?\b",
        )
    ),


    "save-passport-license": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+i\s+save\s+my\s+"
            r"(?:passport|driver\s+license|driver['’]?s\s+license)\b",
            r"\bhow\s+do\s+i\s+save\s+an?\s+id\b",
        )
    ),
    "ids-masked-by-default": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bare\s+id\s+numbers?\s+hidden\b",
            r"\bare\s+id\s+numbers?\s+masked\b",
        )
    ),
    "id-expiry-reminders": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+vault\s*ai\s+remind\s+me\s+about\s+"
            r"(?:expir(?:y|ation)|id\s+expiry)\b",
        )
    ),
    "how-do-i-search-ids": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+search\s+(?:my\s+)?id\s+documents?\b",
            r"\bhow\s+to\s+search\s+ids?\b",
        )
    ),


    "what-is-crypto-vault": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhat\s+is\s+crypto\s+vault\b",
            r"\bhow\s+do\s+crypto\s+wallets?\s+work\b",
        )
    ),
    "supported-assets": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhich\s+(?:crypto\s+)?assets?\s+(?:are\s+)?supported\b",
            r"\bwhat\s+coins?\s+can\s+i\s+store\b",
            r"\bwhat\s+cryptos?\s+are\s+supported\b",
        )
    ),
    "is-crypto-custodial": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bis\s+crypto\s+vault\s+custodial\b",
            r"\bis\s+vault\s*ai\s+custodial\b",
            r"\bcustodial\s+or\s+non[-\s]?custodial\b",
        )
    ),
    "can-vaultai-move-crypto": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+vault\s*ai\s+(?:move|send|broadcast)\s+"
            r"(?:my\s+)?crypto\b",
        )
    ),
    "pin-before-sending": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+(?:do\s+i\s+need\s+|does\s+it\s+need\s+)?"
            r"(?:a\s+)?pin\s+(?:before|to)\s+send(?:ing)?\b",
        )
    ),
    "usdt-erc20-vs-trc20": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+does\s+usdt\s+have\s+erc20\s+and\s+trc20\b",
            r"\bwhy\s+is\s+(?:my\s+)?usdt\s+asking\s+"
            r"erc20\s+or\s+trc20\b",
            r"\bwhy\s+do\s+i\s+choose\s+(?:a\s+)?usdt\s+network\b",
            r"\bwhat['’]?s\s+the\s+difference\s+between\s+usdt\s+"
            r"erc20\s+and\s+trc20\b",
        )
    ),
    "usdc-uses-eth-address": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+does\s+usdc\s+use\s+my\s+"
            r"(?:ethereum|eth)\s+address\b",
            r"\bwhy\s+do\s+usdc\s+and\s+usdt\s+erc20\s+use\s+"
            r"my\s+(?:ethereum|eth)\s+address\b",
            r"\bcan\s+usdc\s+use\s+my\s+eth\s+address\b",
        )
    ),
    "erc20-needs-eth-gas": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+do\s+token\s+transfers?\s+need\s+eth\s+for\s+gas\b",
            r"\bwhy\s+do\s+i\s+need\s+eth\s+for\s+gas\b",
            r"\bwhy\s+does\s+usdt\s+need\s+eth\b",
        )
    ),
    "why-monero-different": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+is\s+monero\s+different\b",
            r"\bwhy\s+is\s+xmr\s+different\b",
            r"\bhow\s+does\s+monero\s+privacy\s+work\b",
        )
    ),
    "monero-balance-in-browser": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+can['’]?t\s+i\s+see\s+(?:my\s+)?monero\s+"
            r"balance(?:\s+in\s+the\s+browser)?\b",
            r"\bwhy\s+can['’]?t\s+i\s+see\s+(?:my\s+)?xmr\s+balance\b",
            r"\bwhy\s+is\s+(?:my\s+)?monero\s+balance\s+"
            r"(?:unavailable|hidden|not\s+showing)\b",
        )
    ),
    "monero-send-disabled": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+is\s+(?:monero|xmr)\s+send\s+disabled\b",
            r"\bcan\s+i\s+send\s+monero\b",
            r"\bcan\s+i\s+send\s+xmr\b",
        )
    ),
    "buy-sell-swap": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+i\s+"
            r"(?:buy|sell|swap|trade|stake|bridge|exchange|convert)"
            r"(?:[\s,]+(?:or\s+)?"
            r"(?:buy|sell|swap|trade|stake|bridge|exchange|convert)"
            r")*"
            r"\s+crypto\b",
            r"\bdoes\s+vault\s*ai\s+"
            r"(?:buy|sell|swap|trade|stake|bridge|exchange|convert)\b",
        )
    ),
    "provider-unavailable": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhat\s+happens\s+if\s+(?:a\s+)?provider\s+is\s+unavailable\b",
            r"\bprovider\s+unavailable(?:\s+reason)?\b",
        )
    ),
    "why-balance-zero": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+does\s+my\s+balance\s+say\s+0\b",
            r"\bwhy\s+is\s+my\s+balance\s+zero\b",
        )
    ),
    "receive-when-balance-zero": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bcan\s+i\s+receive\s+crypto\s+(?:if|when|even\s+if)\s+"
            r"(?:my\s+)?balance\s+is\s+(?:0|zero)\b",
        )
    ),
    "crypto-when-vault-deleted": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhat\s+happens\s+to\s+(?:my\s+)?crypto\s+"
            r"(?:if|when)\s+i\s+delete\s+my\s+"
            r"(?:vault|profile|account)\b",
            r"\bwill\s+(?:my\s+)?crypto\s+be\s+deleted\b",
            r"\bwill\s+deleting\s+my\s+"
            r"(?:vault|profile|account)\s+"
            r"(?:move|delete|affect)\s+(?:my\s+)?crypto\b",
        )
    ),


    "what-plan-am-i-on": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+check\s+(?:my\s+)?plan\b",
            r"\bhow\s+do\s+i\s+see\s+my\s+plan\b",
        )
    ),
    "storage-limits": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+much\s+storage\s+do\s+i\s+have\b",
            r"\bwhat\s+is\s+my\s+storage\s+limit\b",
        )
    ),
    "storage-exceeded": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhat\s+happens\s+if\s+i\s+exceed\s+storage\b",
            r"\bwhat\s+happens\s+when\s+storage\s+is\s+full\b",
        )
    ),
    "how-do-i-upgrade": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+upgrade\s+storage\b",
            r"\bhow\s+do\s+i\s+upgrade\s+my\s+plan\b",
        )
    ),
    "how-do-i-cancel": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+cancel\b",
            r"\bhow\s+do\s+i\s+manage\s+(?:my\s+)?subscription\b",
        )
    ),
    "why-checkout-opens": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+does\s+checkout\s+open\b",
            r"\bwhy\s+does\s+it\s+redirect\s+to\s+checkout\b",
        )
    ),
    "how-storage-calculated": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+is\s+storage\s+calculated\b",
            r"\bhow\s+does\s+storage\s+count\b",
        )
    ),
    "why-inactive-unpaid-deleted": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+are\s+(?:unpaid\s+)?inactive\s+"
            r"(?:vaults?|accounts?)\s+deleted\b",
            r"\bwhy\s+are\s+inactive\s+"
            r"(?:vaults?|accounts?)\s+"
            r"(?:removed|purged|deleted)\b",
            r"\bwhen\s+are\s+inactive\s+"
            r"(?:vaults?|accounts?)\s+deleted\b",
            r"\bdoes\s+vault\s*ai\s+delete\s+"
            r"(?:unpaid|inactive)\s+"
            r"(?:vaults?|accounts?)\b",
        )
    ),
    "how-to-prevent-auto-deletion": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+"
            r"(?:prevent|stop|avoid)\s+"
            r"(?:automatic\s+|auto[-\s]?)?deletion\b",
            r"\bhow\s+do\s+i\s+"
            r"(?:keep|stop)\s+"
            r"(?:my\s+)?(?:vault|account)\s+"
            r"(?:active|from\s+being\s+deleted)\b",
            r"\bhow\s+to\s+"
            r"(?:stop|prevent|avoid)\s+"
            r"(?:automatic\s+|auto[-\s]?)?deletion\b",
        )
    ),


    "why-balance-unavailable": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+is\s+my\s+balance\s+unavailable\b",
            r"\bwhy\s+does\s+it\s+say\s+balance\s+unavailable\b",
        )
    ),
    "why-file-not-showing": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+is\s+my\s+file\s+not\s+showing\b",
            r"\bwhy\s+can['’]?t\s+i\s+see\s+my\s+file\b",
        )
    ),
    "why-chat-searches-files": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+is\s+chat\s+searching\s+files\b",
            r"\bwhy\s+does\s+chat\s+treat\s+everything\s+as\s+files\b",
            r"\bwhy\s+does\s+it\s+search\s+files\s+when\s+i\s+"
            r"ask(?:ed)?\s+about\b",
        )
    ),
    "monero-desktop-required": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+does\s+monero\s+say\s+desktop(?:\s+app)?\s+required\b",
            r"\bwhy\s+do\s+i\s+need\s+the\s+desktop\s+app\s+for\s+monero\b",
        )
    ),
    "tron-provider-unavailable": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+does\s+tron\s+say\s+provider\s+unavailable\b",
            r"\bwhy\s+is\s+tron\s+unavailable\b",
        )
    ),
    "why-subscription-checking": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bwhy\s+is\s+subscription\s+status\s+checking\b",
            r"\bwhy\s+does\s+it\s+say\s+checking\s+subscription\b",
        )
    ),
    "how-do-i-refresh": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+refresh\s+my\s+vault\b",
            r"\bhow\s+do\s+i\s+refresh\s+the\s+list\b",
        )
    ),
    "how-do-i-report-bug": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+report\s+a\s+bug\b",
            r"\bhow\s+do\s+i\s+file\s+(?:a\s+)?bug\s+report\b",
        )
    ),
    "how-do-i-get-support": tuple(
        re.compile(p, re.IGNORECASE) for p in (
            r"\bhow\s+do\s+i\s+(?:get|contact)\s+support\b",
            r"\bwhere\s+is\s+(?:customer\s+)?support\b",
            r"\bhow\s+do\s+i\s+talk\s+to\s+(?:a\s+)?human\b",
        )
    ),
}


for _id in _PATTERNS_BY_ID:
    if _id not in FAQ_BY_ID:
        raise RuntimeError(
            f"vault_faq_router pattern references unknown FAQ id "
            f"{_id!r} — vault_faq_content.FAQ_ENTRIES out of sync",
        )


_GENERIC_HELP_HINT_RE = re.compile(
    r"\b(?:how\s+do\s+i|how\s+to|how\s+does|how\s+is|"
    r"what\s+is|what[’']?s|what\s+happens|what\s+will\s+happen|"
    r"what\s+can|"
    r"what\s+should|what\s+file\s+types|"
    r"why\s+is|why\s+does|why\s+can['’]?t|why\s+do|"
    r"why\s+are|why\s+was|why\s+should|why\s+shouldn['’]?t|"
    r"when\s+are|"
    r"is\s+my|is\s+crypto|"
    r"can\s+i|can\s+vault\s*ai|can\s+someone|can\s+anyone|"
    r"will\s+(?:my|deleting|vault\s*ai)|"
    r"are\s+(?:my|id|passwords?)|which\s+"
    r"(?:assets?|coins?|file\s+types)|"
    r"does\s+vault\s*ai|does\s+the\s+ai|"
    r"forgot\s+(?:my\s+)?pin|"
    r"delete\s+my\s+(?:vault|profile|account)|"
    r"close\s+my\s+(?:vault|account)|"
    r"i\s+want\s+to\s+delete\s+my)\b",
    re.IGNORECASE,
)


def looks_like_faq_message(message: str) -> bool:
    """Cheap upstream check: does the message look like a
    help/how/why question? Used by the umbrella router to decide
    whether to run the FAQ matcher at all."""
    if not isinstance(message, str) or not message.strip():
        return False
    return bool(_GENERIC_HELP_HINT_RE.search(message))


def _match_faq_id(message: str) -> Optional[str]:
    for faq_id, patterns in _PATTERNS_BY_ID.items():
        for p in patterns:
            if p.search(message):
                return faq_id
    return None


def _build_faq_card(faq_id: str) -> dict[str, Any]:
    entry = FAQ_BY_ID[faq_id]
    return {
        "schema":           FAQ_SCHEMA_V1,
        "cardType":         VAULT_FAQ_CARD_TYPE,
        "faqId":            entry["id"],
        "category":         entry["category"],
        "categoryLabel":    FAQ_CATEGORY_LABELS[entry["category"]],
        "question":         entry["question"],
        "answer":           entry["answer"],
        "relatedIds":       list(entry.get("related_ids", ())),
        "relatedQuestions": [
            {
                "id":       FAQ_BY_ID[rid]["id"],
                "question": FAQ_BY_ID[rid]["question"],
            }
            for rid in entry.get("related_ids", ())
            if rid in FAQ_BY_ID
        ],
        "relatedActions":   list(entry.get("related_actions", ())),
    }


def build_faq_envelope(message: str) -> Optional[dict[str, Any]]:
    """Return the FAQ envelope for `message`, or None if no FAQ
    entry matched. Router callers should treat None as "fall
    through to the next dispatch layer"."""
    if not isinstance(message, str):
        return None
    text = message.strip()
    if not text:
        return None
    faq_id = _match_faq_id(text)
    if faq_id is None:
        return None
    return {
        "schema":  FAQ_SCHEMA_V1,
        "intent":  VAULT_FAQ_INTENT,
        "card":    _build_faq_card(faq_id),
        "message": FAQ_BY_ID[faq_id]["answer"],
    }


def all_faq_categories() -> tuple[str, ...]:
    return FAQ_CATEGORIES


def all_faq_ids() -> tuple[str, ...]:
    return all_ids()


def entry_by_id(faq_id: str) -> Optional[dict[str, Any]]:
    return FAQ_BY_ID.get(faq_id)
