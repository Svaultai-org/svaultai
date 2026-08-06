"""Deterministic matcher for the curated conversational FAQ."""

from __future__ import annotations

import re
from typing import Any, Optional

from vault_faq_content import (
    FAQ_BY_ID, FAQ_CATEGORIES, FAQ_CATEGORY_LABELS, FAQ_ENTRIES,
    FAQ_SCHEMA_V1,
)

VAULT_FAQ_CARD_TYPE = "vault_faq_card"
VAULT_FAQ_INTENT = "vault_faq"


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(value, re.IGNORECASE) for value in values)


_PATTERNS_BY_ID = {
    "what-is-svaultai": _patterns(r"\bwhat\s+is\s+s?vault\s*ai\b", r"\bhow\s+does\s+s?vault\s*ai\s+work\b"),
    "what-can-i-protect": _patterns(r"\bwhat\s+can\s+i\s+(?:save|store|protect)\b"),
    "can-staff-open-vault": _patterns(r"\bcan\s+(?:s?vault\s*ai\s+)?(?:staff|employees?|developers?|support|s?vault\s*ai)\s+(?:open|see|read|browse)\s+(?:my\s+)?vault\b"),
    "no-master-key": _patterns(r"\b(?:is\s+there|do\s+you\s+have)\s+(?:a\s+)?(?:universal\s+)?master\s+key\b"),
    "no-developer-backdoor": _patterns(r"\b(?:is\s+there|do\s+developers?\s+have)\s+(?:a\s+)?(?:developer\s+)?backdoor\b"),
    "file-and-credential-privacy": _patterns(r"\bcan\s+(?:s?vault\s*ai\s+)?(?:staff|employees?|support|s?vault\s*ai)\s+(?:browse|see|read|reveal)\s+(?:my\s+)?(?:uploaded\s+)?(?:uploads?|files?|credentials?|passwords?)\b"),
    "operational-metadata": _patterns(r"\bwhat\s+(?:information|metadata|data)\s+can\s+s?vault\s*ai\s+(?:see|process|collect)\b"),
    "forgot-pin": _patterns(r"\b(?:what\s+(?:happens|if)|i)\s+(?:if\s+i\s+)?(?:forgot|forget|lost)\s+(?:my\s+)?pin\b", r"\bcan\s+s?vault\s*ai\s+reset\s+(?:my\s+)?pin\b"),
    "trusted-devices": _patterns(r"\bwhat\s+is\s+a\s+trusted\s+device\b", r"\b(?:see|remove|manage)\s+trusted\s+devices?\b"),
    "lost-device": _patterns(r"\b(?:lost|lose|stolen)\s+(?:my\s+)?(?:phone|device)\b"),
    "files-encrypted": _patterns(r"\bare\s+(?:uploaded\s+|my\s+)?(?:uploads?|files?)\s+encrypted\b"),
    "credentials-private": _patterns(r"\bare\s+(?:saved\s+|my\s+)*(?:usernames?\s+and\s+passwords?|usernames?|passwords?|credentials?)\s+(?:private|encrypted)\b"),
    "delete-file": _patterns(r"\bwhat\s+happens\s+(?:when|if)\s+i\s+delete\s+(?:a\s+)?file\b"),
    "private-ai": _patterns(r"\bdoes\s+(?:the\s+)?ai\s+have\s+(?:unrestricted\s+)?access\s+to\s+(?:my\s+)?vault\b", r"\bcan\s+(?:the\s+)?ai\s+see\s+(?:my\s+)?(?:entire|whole)\s+vault\b"),
    "ai-provider-data": _patterns(r"\bwhat\s+(?:data|content|information)\s+(?:is|gets)\s+sent\s+to\s+(?:the\s+)?ai\b", r"\bwhat\s+can\s+an\s+ai\s+provider\s+receive\b", r"\bcan\s+ai\s+providers?\s+see\b"),
    "wallet-non-custodial": _patterns(r"\bis\s+(?:the\s+)?s?vault\s*ai\s+wallet\s+(?:custodial|non[- ]custodial)\b", r"\bcustodial\s+or\s+non[- ]custodial\b"),
    "wallet-transaction-approval": _patterns(r"\bcan\s+s?vault\s*ai\s+(?:send|move|broadcast)\s+(?:my\s+)?crypto\b", r"\bdoes\s+(?:a\s+)?transaction\s+require\s+(?:my\s+)?approval\b"),
    "wallet-recovery": _patterns(r"\bcan\s+s?vault\s*ai\s+recover\s+(?:my\s+)?wallet\b"),
    "how-local-signing-works": _patterns(r"\bhow\s+does\s+local\s+signing\s+work\b"),
    "never-share-seed": _patterns(r"\bwhy\s+should(?:n'?t|\s+i\s+not)\s+share\s+(?:my\s+)?seed\s+phrase\b"),
    "inheritance": _patterns(r"\b(?:what\s+is|how\s+does)\s+(?:the\s+)?inheritance(?:\s+feature)?\s*(?:work)?\b", r"\bcan\s+(?:my\s+)?beneficiary\s+access\b"),
    "inactive-unsubscribed-vault": _patterns(r"\bwhat\s+happens\s+after\s+six\s+months\b", r"\b(?:inactive|unsubscribed|unpaid)\s+vaults?\s+(?:deleted|deletion)\b", r"\bhow\s+do\s+i\s+reset\s+(?:the\s+)?inactivity\b"),
    "subscription-expired": _patterns(r"\bwhat\s+happens\s+(?:when|if)\s+(?:my\s+)?subscription\s+expires?\b"),
    "delete-vault": _patterns(r"\bhow\s+do\s+i\s+(?:permanently\s+)?delete\s+(?:my\s+)?(?:vault|account)\b", r"^\s*(?:i\s+want\s+to\s+)?delete\s+my\s+(?:vault|account|profile)\s*[?.!]*\s*$"),
    "deletion-and-blockchain": _patterns(r"\bwhat\s+happens\s+to\s+(?:my\s+)?(?:wallet|crypto|blockchain)\s+(?:records?\s+)?(?:when|if)\s+i\s+delete\b"),
    "phishing-safety": _patterns(r"\bhow\s+(?:can|do)\s+i\s+protect\s+myself\s+from\s+phishing\b", r"\bhow\s+do\s+i\s+stay\s+safe\b"),
    "contact-support": _patterns(r"\bhow\s+do\s+i\s+(?:contact|get)\s+support\b", r"\bwhat\s+is\s+(?:the\s+)?support\s+email\b"),
}

if set(_PATTERNS_BY_ID) != set(FAQ_BY_ID):
    raise RuntimeError("FAQ router and curated content IDs are out of sync")

_GENERIC_HELP_HINT_RE = re.compile(
    r"\b(?:what|why|how|can|does|is|are|will|forgot|lost|delete|i\s+want)\b",
    re.IGNORECASE,
)


def looks_like_faq_message(message: str) -> bool:
    if not isinstance(message, str) or not _GENERIC_HELP_HINT_RE.search(message):
        return False
    from vault_chat_general_router import split_compound_message
    if len(split_compound_message(message)) > 1:
        return False
    return _semantic_faq_id(message) is not None or any(
        pattern.search(message) for patterns in _PATTERNS_BY_ID.values()
        for pattern in patterns
    )


def _semantic_faq_id(message: str) -> Optional[str]:
    """Match FAQ concepts compositionally, without sentence conditions."""
    tokens = set(re.findall(r"[a-z0-9]+", message.lower()))
    question_like = bool(re.match(
        r"\s*(?:what|why|how|can|does|is|are|which|explain)\b",
        message,
        re.IGNORECASE,
    ))
    if not question_like:
        return None
    if tokens & {"bug", "report", "support"}:
        return "contact-support"
    if "pin" in tokens and tokens & {"forgot", "forget", "lost", "reset"}:
        return "forgot-pin"
    if "signing" in tokens and "local" in tokens:
        return "how-local-signing-works"
    if tokens & {"seed", "phrase"} and tokens & {"share", "not", "never"}:
        return "never-share-seed"
    if tokens & {"seed", "phrase", "signing", "gas", "tron", "assets"}:
        if tokens & {"share", "seed", "phrase"}:
            return "wallet-recovery"
        if tokens & {"approval", "pin", "gas", "signing"}:
            return "wallet-transaction-approval"
        return "wallet-non-custodial"
    if "monero" in tokens and tokens & {"different", "disabled", "desktop", "required"}:
        return "wallet-non-custodial"
    if tokens & {"inheritance", "beneficiary"}:
        return "inheritance"
    if tokens & {"subscription", "checkout", "upgrade", "exceed"}:
        return "subscription-expired"
    if "storage" in tokens and tokens & {"calculated", "calculate"}:
        return "subscription-expired"
    if tokens & {"password", "passwords", "login", "logins", "credential", "credentials", "masked"}:
        return "credentials-private"
    if "secure" in tokens and "item" in tokens:
        return "credentials-private"
    if (
        tokens & {"types", "passport", "license", "documents", "document", "expiration", "id"}
        and tokens & {"protect", "supported", "support", "accept", "types", "expiration", "save", "hidden"}
    ):
        return "what-can-i-protect"
    if "upload" in tokens and "files" in tokens:
        return "what-can-i-protect"
    if "delete" in tokens and "file" in tokens:
        return "delete-file"
    if tokens & {"search", "searching", "find", "showing", "summarize", "pdf", "provider", "refresh"}:
        return "private-ai"
    if "vault" in tokens and tokens & {"create", "unlock"}:
        return "what-is-svaultai"
    if tokens & {"encrypted", "encryption"}:
        return "files-encrypted"
    if (
        "vault" in tokens
        and (
            tokens & {"staff", "read"}
            or {"someone", "else"}.issubset(tokens)
        )
    ):
        return "can-staff-open-vault"
    if tokens & {"svaultai", "vaultai"} and "read" in tokens and tokens & {"secret", "secrets", "saved"}:
        return "file-and-credential-privacy"
    if tokens & {"buy", "sell", "swap", "trade"} and tokens & {"crypto", "vaultai"}:
        return "wallet-non-custodial"
    if "pin" in tokens and tokens & {"sending", "send"}:
        return "wallet-transaction-approval"
    if tokens & {"files", "items"} and tokens & {"difference", "secure"}:
        return "what-can-i-protect"
    if (
        tokens & {"private", "privacy", "trust"}
        and tokens & {"information", "data", "vault", "svaultai"}
    ):
        return "files-encrypted"
    if (
        tokens & {"explain", "describe"}
        and tokens & {"app", "svaultai"}
        and tokens & {"work", "works", "working"}
    ):
        return "what-is-svaultai"
    return None


def _match_faq_id(message: str) -> Optional[str]:
    for faq_id, patterns in _PATTERNS_BY_ID.items():
        if any(pattern.search(message) for pattern in patterns):
            return faq_id
    return _semantic_faq_id(message)


def _build_faq_card(faq_id: str) -> dict[str, Any]:
    entry = FAQ_BY_ID[faq_id]
    related = [
        {"id": related_id, "question": FAQ_BY_ID[related_id]["question"]}
        for related_id in entry.get("related_ids", ())
    ]
    return {
        "schema": FAQ_SCHEMA_V1, "cardType": VAULT_FAQ_CARD_TYPE,
        "faqId": faq_id, "category": entry["category"],
        "categoryLabel": FAQ_CATEGORY_LABELS[entry["category"]],
        "question": entry["question"], "answer": entry["answer"],
        "relatedIds": list(entry.get("related_ids", ())),
        "relatedQuestions": related,
        "relatedActions": list(entry.get("related_actions", ())),
    }


def build_faq_envelope(message: str) -> Optional[dict[str, Any]]:
    if not isinstance(message, str):
        return None
    from vault_chat_general_router import split_compound_message
    if len(split_compound_message(message)) > 1:
        return None
    faq_id = _match_faq_id(message.strip())
    if faq_id is None:
        return None
    card = _build_faq_card(faq_id)
    return {"schema": FAQ_SCHEMA_V1, "intent": VAULT_FAQ_INTENT,
            "card": card, "message": card["answer"]}


def all_faq_categories() -> tuple[str, ...]:
    return FAQ_CATEGORIES


def all_faq_ids() -> tuple[str, ...]:
    return tuple(entry["id"] for entry in FAQ_ENTRIES)


def entry_by_id(faq_id: str) -> Optional[dict[str, Any]]:
    return FAQ_BY_ID.get(faq_id)
