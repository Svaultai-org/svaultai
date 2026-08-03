"""Curated conversational FAQ aligned with the canonical Help Center.

The complete English Help Center lives in
``vault_ai_frontend/lib/help_center_content.dart``.  This smaller closed set
exists only so chat can answer common trust and operational questions without
exposing implementation or transient service details.
"""

from __future__ import annotations

import re
from typing import Any

FAQ_SCHEMA_V1 = "vault_faq_v1"

FAQ_CATEGORY_GETTING_STARTED = "getting_started"
FAQ_CATEGORY_PRIVACY = "privacy"
FAQ_CATEGORY_SECURITY = "security"
FAQ_CATEGORY_FILES = "files"
FAQ_CATEGORY_AI = "ai"
FAQ_CATEGORY_CRYPTO = "crypto"
FAQ_CATEGORY_INHERITANCE = "inheritance"
FAQ_CATEGORY_BILLING = "billing"
FAQ_CATEGORY_DELETION = "deletion"
FAQ_CATEGORY_SAFETY = "safety"
FAQ_CATEGORY_SUPPORT = "support"

FAQ_CATEGORIES = (
    FAQ_CATEGORY_GETTING_STARTED, FAQ_CATEGORY_PRIVACY,
    FAQ_CATEGORY_SECURITY, FAQ_CATEGORY_FILES, FAQ_CATEGORY_AI,
    FAQ_CATEGORY_CRYPTO, FAQ_CATEGORY_INHERITANCE,
    FAQ_CATEGORY_BILLING, FAQ_CATEGORY_DELETION,
    FAQ_CATEGORY_SAFETY, FAQ_CATEGORY_SUPPORT,
)

FAQ_CATEGORY_LABELS = {
    FAQ_CATEGORY_GETTING_STARTED: "Getting started",
    FAQ_CATEGORY_PRIVACY: "Privacy and encryption",
    FAQ_CATEGORY_SECURITY: "Security, PIN, and devices",
    FAQ_CATEGORY_FILES: "Files and credentials",
    FAQ_CATEGORY_AI: "AI and vault search",
    FAQ_CATEGORY_CRYPTO: "Crypto wallet",
    FAQ_CATEGORY_INHERITANCE: "Inheritance",
    FAQ_CATEGORY_BILLING: "Subscription and inactivity",
    FAQ_CATEGORY_DELETION: "Deletion",
    FAQ_CATEGORY_SAFETY: "Safety",
    FAQ_CATEGORY_SUPPORT: "Support",
}

FAQ_ACTION_OPEN_VAULT = "open_vault"
FAQ_ACTION_OPEN_LOGINS = "open_logins_page"
FAQ_ACTION_OPEN_ID_DOCS = "open_id_documents"
FAQ_ACTION_OPEN_CRYPTO_VAULT = "open_crypto_vault"
FAQ_ACTION_OPEN_BILLING = "open_billing_page"
FAQ_ACTION_OPEN_STORAGE = "open_storage_page"
FAQ_ACTION_OPEN_SECURITY = "open_security_center"
FAQ_ACTION_OPEN_HELP_CENTER = "open_help_center"
FAQ_ACTION_OPEN_UPLOAD = "open_upload_page"
FAQ_ACTION_OPEN_DELETE_VAULT = "open_delete_vault_flow"
FAQ_ALLOWED_ACTIONS = frozenset({
    FAQ_ACTION_OPEN_VAULT, FAQ_ACTION_OPEN_LOGINS,
    FAQ_ACTION_OPEN_ID_DOCS, FAQ_ACTION_OPEN_CRYPTO_VAULT,
    FAQ_ACTION_OPEN_BILLING, FAQ_ACTION_OPEN_STORAGE,
    FAQ_ACTION_OPEN_SECURITY, FAQ_ACTION_OPEN_HELP_CENTER,
    FAQ_ACTION_OPEN_UPLOAD, FAQ_ACTION_OPEN_DELETE_VAULT,
})


def _entry(faq_id: str, category: str, question: str, answer: str,
           related_ids: tuple[str, ...] = (),
           related_actions: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"id": faq_id, "category": category, "question": question,
            "answer": answer, "related_ids": related_ids,
            "related_actions": related_actions}


FAQ_ENTRIES: tuple[dict[str, Any], ...] = (
    _entry("what-is-svaultai", FAQ_CATEGORY_GETTING_STARTED,
           "What is SVaultAI?",
           "SVaultAI is a privacy-focused digital vault for documents, media, credentials, personal memories, and supported digital assets. It combines encrypted storage with tools for organizing and finding your own information."),
    _entry("what-can-i-protect", FAQ_CATEGORY_GETTING_STARTED,
           "What can I protect in SVaultAI?",
           "You can protect supported files, photos, videos, audio, saved logins, secure notes, personal memories, identity documents, and locally protected wallet secrets. Features and file limits may depend on your platform and plan."),
    _entry("can-staff-open-vault", FAQ_CATEGORY_PRIVACY,
           "Can SVaultAI staff open my vault?",
           "Your vault belongs to you. SVaultAI cannot open your vault. We do not have a master key, developer backdoor, or support tool that reveals protected vault contents."),
    _entry("no-master-key", FAQ_CATEGORY_PRIVACY,
           "Is there a universal master key?",
           "No. SVaultAI does not maintain a universal master key or customer-support backdoor that can simply unlock every vault."),
    _entry("no-developer-backdoor", FAQ_CATEGORY_PRIVACY,
           "Is there a developer backdoor?",
           "No. Developers and support do not have a backdoor or staff-facing control that reveals protected vault contents."),
    _entry("file-and-credential-privacy", FAQ_CATEGORY_PRIVACY,
           "Can staff browse my uploaded files or saved credentials?",
           "No. Staff cannot browse protected uploads or reveal saved credential values. Stored file bytes, protected file metadata, and credential values are encrypted."),
    _entry("operational-metadata", FAQ_CATEGORY_PRIVACY,
           "What information can SVaultAI process?",
           "SVaultAI processes limited operational metadata needed to run and secure the service, such as account status, subscription state, storage amount, trusted devices, security events, and deletion eligibility. It does not let staff open protected vault contents."),
    _entry("forgot-pin", FAQ_CATEGORY_SECURITY,
           "What happens if I forget my PIN?",
           "SVaultAI cannot reset your PIN or use a universal key to unlock your vault. Depending on the recovery features and key material you configured, losing the PIN may make protected data permanently inaccessible."),
    _entry("trusted-devices", FAQ_CATEGORY_SECURITY,
           "What is a trusted device?",
           "A trusted device is one you have authorized for your account. Review trusted devices regularly and remove any device you no longer control. A new or reinstalled device must complete the current authorization flow before it can access protected content."),
    _entry("lost-device", FAQ_CATEGORY_SECURITY,
           "What should I do if I lose my device?",
           "Use another authorized device to remove the lost device if possible, protect the device through its platform account, and contact support if you see suspicious activity. Do not share your PIN or recovery material."),
    _entry("files-encrypted", FAQ_CATEGORY_FILES,
           "Are uploaded files encrypted?",
           "Stored file bytes and protected file metadata are encrypted. When you request supported analysis, selected content may be processed for that request and may be sent to an AI or media-processing provider; the whole vault is not sent automatically."),
    _entry("credentials-private", FAQ_CATEGORY_FILES,
           "Are saved usernames and passwords private?",
           "Saved credential values are encrypted. They are not available to staff or support, and secret values are excluded from ordinary AI chat context and masked until you explicitly reveal them."),
    _entry("delete-file", FAQ_CATEGORY_FILES,
           "What happens when I delete a file?",
           "The file is removed from normal access and scheduled for permanent deletion under the service's deletion and backup-retention process. Do not assume support can restore it; keep an independent copy of anything you cannot replace."),
    _entry("private-ai", FAQ_CATEGORY_AI,
           "Does the AI have unrestricted access to my vault?",
           "No. The assistant receives only the information needed for the feature you request. It does not automatically receive your entire vault, and credential secrets are excluded from ordinary AI chat context."),
    _entry("ai-provider-data", FAQ_CATEGORY_AI,
           "What can an AI provider receive?",
           "When you request supported analysis, relevant text or selected content may be sent to the configured AI provider to produce an answer. The entire vault is not sent automatically. Avoid asking the assistant to process information you do not want included in that request."),
    _entry("wallet-non-custodial", FAQ_CATEGORY_CRYPTO,
           "Is the SVaultAI wallet custodial?",
           "It is non-custodial. Transactions are signed with key material protected on your device; SVaultAI does not hold funds on your behalf like an exchange."),
    _entry("wallet-transaction-approval", FAQ_CATEGORY_CRYPTO,
           "Can SVaultAI send crypto without my approval?",
           "No. A transaction requires you to review its details, authorize it with your PIN, and explicitly approve it before signing and broadcast. Blockchain transactions generally cannot be reversed after broadcast."),
    _entry("wallet-recovery", FAQ_CATEGORY_CRYPTO,
           "Can SVaultAI recover my wallet?",
           "SVaultAI cannot use a master key or support backdoor to recover or move your funds. Keep any supported recovery material securely and independently. Never share a seed phrase or private key with anyone claiming to be support."),
    _entry("inheritance", FAQ_CATEGORY_INHERITANCE,
           "How does inheritance work?",
           "Inheritance lets you designate a beneficiary through the supported authorization process. A beneficiary cannot browse your vault while you are alive merely because they are named, and support cannot bypass the inheritance controls."),
    _entry("inactive-unsubscribed-vault", FAQ_CATEGORY_BILLING,
           "What happens after six months without logging in?",
           "An unsubscribed vault that has not been logged into for six months may be automatically deleted. Logging in resets the inactivity period. Subscribed vaults are not treated as inactive unpaid vaults."),
    _entry("subscription-expired", FAQ_CATEGORY_BILLING,
           "What happens if my subscription expires?",
           "Your account may move to the available unsubscribed state and its storage limits. An unsubscribed vault not logged into for six months may be automatically deleted, so log in regularly and export important data before deletion."),
    _entry("delete-vault", FAQ_CATEGORY_DELETION,
           "How do I permanently delete my vault?",
           "Use the Delete vault flow in Settings and complete every displayed confirmation. Deletion is intended to be permanent, and protected vault content is not available through ordinary support recovery afterward.",
           related_actions=(FAQ_ACTION_OPEN_DELETE_VAULT,)),
    _entry("deletion-and-blockchain", FAQ_CATEGORY_DELETION,
           "What happens to wallet records when I delete my vault?",
           "SVaultAI removes its protected wallet records through the vault-deletion process, but public blockchain addresses and transactions remain on their networks. Deleting SVaultAI cannot reverse or erase a blockchain transaction."),
    _entry("phishing-safety", FAQ_CATEGORY_SAFETY,
           "How can I protect myself from phishing?",
           "Never share your PIN, password, seed phrase, private key, recovery material, or one-time code. Verify the app or website address, review transaction details and network names, and distrust anyone who pressures you to reveal a secret or approve a transfer."),
    _entry("contact-support", FAQ_CATEGORY_SUPPORT,
           "How do I contact support?",
           "Email vaultai@svaultai.com. Do not include your PIN, password, seed phrase, private key, recovery material, or full credential values. Support can help with service issues but cannot open your protected vault contents."),
)

FAQ_BY_ID = {entry["id"]: entry for entry in FAQ_ENTRIES}
_FAQ_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,80}$")


def _validate_entries() -> None:
    seen: set[str] = set()
    for entry in FAQ_ENTRIES:
        faq_id = entry["id"]
        if not _FAQ_ID_RE.fullmatch(faq_id) or faq_id in seen:
            raise ValueError(f"invalid or duplicate FAQ id: {faq_id!r}")
        seen.add(faq_id)
        if entry["category"] not in FAQ_CATEGORIES:
            raise ValueError(f"unknown category in {faq_id!r}")
        if not entry["question"].strip() or not entry["answer"].strip():
            raise ValueError(f"empty FAQ copy in {faq_id!r}")
        if len(entry["answer"]) > 800:
            raise ValueError(f"answer too long in {faq_id!r}")
        if any(action not in FAQ_ALLOWED_ACTIONS
               for action in entry.get("related_actions", ())):
            raise ValueError(f"invalid related action in {faq_id!r}")
    for entry in FAQ_ENTRIES:
        if any(faq_id not in seen for faq_id in entry.get("related_ids", ())):
            raise ValueError(f"unknown related FAQ in {entry['id']!r}")


_validate_entries()


def entry_by_id(faq_id: str) -> dict[str, Any] | None:
    return FAQ_BY_ID.get(faq_id)


def entries_in_category(category: str) -> tuple[dict[str, Any], ...]:
    return tuple(entry for entry in FAQ_ENTRIES
                 if entry["category"] == category)


def all_ids() -> tuple[str, ...]:
    return tuple(entry["id"] for entry in FAQ_ENTRIES)
