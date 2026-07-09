"""VaultAI FAQ / Help Center — the ground-truth knowledge base.

Ships as a standalone module. Every FAQ entry has:

  * a stable closed-set ID (kebab-case)
  * a category from FAQ_CATEGORIES
  * the question (verbatim, as a user might phrase it)
  * a short answer (product-truth accurate)
  * related_ids — other FAQ entries relevant to this one
  * related_actions — safe in-app navigation intents (never a
    "reveal secret" or a "send crypto" action)

Content rules enforced by the module + tests:

  1. NEVER instruct a user to share a seed phrase, private key,
     mnemonic, spend key, view key, encrypted wallet secret, auth
     token, API key, PIN, or password.
  2. NEVER promise a feature that does not exist. The VaultAI
     product truth list from the operator brief is the SOLE source
     of behavioural claims.
  3. NEVER claim there is a live customer-support team.
  4. Every ID matches the regex `^[a-z][a-z0-9-]{2,80}$` (kebab).
  5. Every answer stays under 800 characters so cards fit on
     mobile without vertical explosion.

This module is imported by:
  * vault_faq_router.py  — the deterministic matcher
  * frontend (via the router) — for card rendering
  * tests
"""

from __future__ import annotations

import re
from typing import Any


FAQ_SCHEMA_V1: str = "vault_faq_v1"


FAQ_CATEGORY_GETTING_STARTED:  str = "getting_started"
FAQ_CATEGORY_SECURITY:         str = "security"
FAQ_CATEGORY_FILES:            str = "files"
FAQ_CATEGORY_SECURE_ITEMS:     str = "secure_items"
FAQ_CATEGORY_IDS:              str = "ids"
FAQ_CATEGORY_CRYPTO:           str = "crypto"
FAQ_CATEGORY_BILLING:          str = "billing"
FAQ_CATEGORY_TROUBLESHOOTING:  str = "troubleshooting"


FAQ_CATEGORIES: tuple[str, ...] = (
    FAQ_CATEGORY_GETTING_STARTED,
    FAQ_CATEGORY_SECURITY,
    FAQ_CATEGORY_FILES,
    FAQ_CATEGORY_SECURE_ITEMS,
    FAQ_CATEGORY_IDS,
    FAQ_CATEGORY_CRYPTO,
    FAQ_CATEGORY_BILLING,
    FAQ_CATEGORY_TROUBLESHOOTING,
)


FAQ_CATEGORY_LABELS: dict[str, str] = {
    FAQ_CATEGORY_GETTING_STARTED: "Getting started",
    FAQ_CATEGORY_SECURITY:        "Security",
    FAQ_CATEGORY_FILES:           "Files",
    FAQ_CATEGORY_SECURE_ITEMS:    "Secure items",
    FAQ_CATEGORY_IDS:             "IDs",
    FAQ_CATEGORY_CRYPTO:          "Crypto Vault",
    FAQ_CATEGORY_BILLING:         "Billing",
    FAQ_CATEGORY_TROUBLESHOOTING: "Troubleshooting",
}


FAQ_ACTION_OPEN_VAULT:          str = "open_vault"
FAQ_ACTION_OPEN_LOGINS:         str = "open_logins_page"
FAQ_ACTION_OPEN_ID_DOCS:        str = "open_id_documents"
FAQ_ACTION_OPEN_CRYPTO_VAULT:   str = "open_crypto_vault"
FAQ_ACTION_OPEN_BILLING:        str = "open_billing_page"
FAQ_ACTION_OPEN_STORAGE:        str = "open_storage_page"
FAQ_ACTION_OPEN_SECURITY:       str = "open_security_center"
FAQ_ACTION_OPEN_HELP_CENTER:    str = "open_help_center"
FAQ_ACTION_OPEN_UPLOAD:         str = "open_upload_page"
FAQ_ACTION_OPEN_DELETE_VAULT:   str = "open_delete_vault_flow"


FAQ_ALLOWED_ACTIONS: frozenset[str] = frozenset({
    FAQ_ACTION_OPEN_VAULT,
    FAQ_ACTION_OPEN_LOGINS,
    FAQ_ACTION_OPEN_ID_DOCS,
    FAQ_ACTION_OPEN_CRYPTO_VAULT,
    FAQ_ACTION_OPEN_BILLING,
    FAQ_ACTION_OPEN_STORAGE,
    FAQ_ACTION_OPEN_SECURITY,
    FAQ_ACTION_OPEN_HELP_CENTER,
    FAQ_ACTION_OPEN_UPLOAD,
    FAQ_ACTION_OPEN_DELETE_VAULT,
})


_FAQ_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,80}$")


_MAX_ANSWER_CHARS: int = 800




FAQ_ENTRIES: tuple[dict[str, Any], ...] = (


    {
        "id":       "what-is-vaultai",
        "category": FAQ_CATEGORY_GETTING_STARTED,
        "question": "What is VaultAI?",
        "answer": (
            "VaultAI is your private digital vault. Think of a "
            "bank vault or a safe at home: people use those to "
            "protect important papers, drives, cash, gold, IDs, "
            "and private records. VaultAI gives you that idea in "
            "digital form. You can keep files, documents, photos, "
            "videos, audio, passwords, secure notes, ID "
            "documents, and Crypto Vault assets in one protected "
            "place. Instead of saving passwords or private "
            "records in emails, notes, screenshots, or random "
            "folders, VaultAI helps you keep them organized and "
            "protected inside your vault. VaultAI Chat helps you "
            "search, understand, and manage what is inside your "
            "vault without treating everything as just a file."
        ),
        "related_ids": (
            "what-can-i-save",
            "is-my-vault-encrypted",
            "files-vs-secure-items",
        ),
        "related_actions": (FAQ_ACTION_OPEN_VAULT,),
    },
    {
        "id":       "what-can-i-save",
        "category": FAQ_CATEGORY_GETTING_STARTED,
        "question": "What can I save in VaultAI?",
        "answer": (
            "You can save files, documents, photos, videos, "
            "audio, passwords, generated logins, secure notes, "
            "codes, device details, ID documents, and Crypto "
            "Vault assets. Internal wallet records are managed "
            "by Crypto Vault and are not shown as normal secure "
            "items."
        ),
        "related_ids": (
            "files-vs-secure-items",
            "what-is-crypto-vault",
        ),
        "related_actions": (),
    },
    {
        "id":       "how-do-i-create-my-vault",
        "category": FAQ_CATEGORY_GETTING_STARTED,
        "question": "How do I create my vault?",
        "answer": (
            "Open the VaultAI sign-in flow, pick or confirm your "
            "vault name, and set your PIN when prompted. Your "
            "PIN helps protect your vault unlock process — keep "
            "it safe. If recovery is not available for your "
            "account, losing your PIN may mean you cannot "
            "recover access."
        ),
        "related_ids": (
            "how-do-i-unlock-my-vault",
            "if-i-forget-my-pin",
        ),
        "related_actions": (),
    },
    {
        "id":       "how-do-i-unlock-my-vault",
        "category": FAQ_CATEGORY_GETTING_STARTED,
        "question": "How do I unlock my vault?",
        "answer": (
            "Open VaultAI on a trusted device and enter your "
            "PIN. Your PIN unlocks the vault locally — the "
            "server never sees your PIN in plaintext. Some "
            "sensitive actions may ask for confirmation again."
        ),
        "related_ids": (
            "trusted-device",
            "is-my-vault-encrypted",
        ),
        "related_actions": (),
    },
    {
        "id":       "trusted-device",
        "category": FAQ_CATEGORY_GETTING_STARTED,
        "question": "What is a trusted device?",
        "answer": (
            "A trusted device is a device you have already approved "
            "for this account. Sensitive actions — revealing a "
            "password, showing a full ID number, preparing a crypto "
            "send — require the request to come from a trusted "
            "device."
        ),
        "related_ids": (
            "how-do-i-unlock-my-vault",
            "lost-my-device",
        ),
        "related_actions": (),
    },
    {
        "id":       "files-vs-secure-items",
        "category": FAQ_CATEGORY_GETTING_STARTED,
        "question": (
            "What is the difference between files and secure items?"
        ),
        "answer": (
            "Files are uploaded blobs: PDFs, images, spreadsheets, "
            "and other documents. Secure items are short encrypted "
            "text records: logins, notes, codes, device details, "
            "and crypto wallet addresses."
        ),
        "related_ids": (
            "what-can-i-save",
            "how-do-i-save-a-password",
        ),
        "related_actions": (),
    },


    {
        "id":       "is-my-vault-encrypted",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "Is my vault encrypted?",
        "answer": (
            "Yes. VaultAI stores sensitive vault data encrypted with "
            "a key derived from your PIN. Sensitive values are "
            "masked by default and protected by trusted-device, "
            "unlock/PIN, and confirmation gates where required."
        ),
        "related_ids": (
            "can-vaultai-read-secrets",
            "why-are-passwords-masked",
        ),
        "related_actions": (),
    },
    {
        "id":       "can-vaultai-read-secrets",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "Can VaultAI read my saved secrets?",
        "answer": (
            "VaultAI does not display or ask for your seed phrase, "
            "private key, mnemonic, spend key, view key, encrypted "
            "wallet secret, auth token, or API key in chat. The AI "
            "only works with masked, safe projections of your vault."
        ),
        "related_ids": (
            "never-share-seed",
            "is-my-vault-encrypted",
        ),
        "related_actions": (),
    },
    {
        "id":       "if-i-forget-my-pin",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "What happens if I forget my PIN?",
        "answer": (
            "The PIN is required to derive your encryption key. If "
            "you forget it, recovery may not be possible — keep your "
            "PIN safe and consider recording it in a physical "
            "location only you can access."
        ),
        "related_ids": (
            "how-do-i-create-my-vault",
            "lost-my-device",
        ),
        "related_actions": (),
    },
    {
        "id":       "can-someone-else-access",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "Can someone else access my vault?",
        "answer": (
            "Only from a trusted device, with your PIN. Sensitive "
            "reveals require additional confirmation. Never share "
            "your PIN, and remove trusted-device access for devices "
            "you no longer control."
        ),
        "related_ids": (
            "trusted-device",
            "lost-my-device",
        ),
        "related_actions": (FAQ_ACTION_OPEN_SECURITY,),
    },
    {
        "id":       "lost-my-device",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "What should I do if I lose my device?",
        "answer": (
            "Open the Security page from another trusted device and "
            "revoke access for the lost device. Your PIN still "
            "protects your vault, but revoking removes the trusted-"
            "device status."
        ),
        "related_ids": (
            "trusted-device",
            "can-someone-else-access",
        ),
        "related_actions": (FAQ_ACTION_OPEN_SECURITY,),
    },
    {
        "id":       "how-local-signing-works",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "How does local signing work for crypto?",
        "answer": (
            "Crypto sends are signed on your device with keys that "
            "only your device can access. The server never receives "
            "your private key. Every send requires trusted device, "
            "PIN unlock, local signing, and explicit confirmation."
        ),
        "related_ids": (
            "is-crypto-custodial",
            "never-share-seed",
        ),
        "related_actions": (),
    },
    {
        "id":       "never-share-seed",
        "category": FAQ_CATEGORY_SECURITY,
        "question": (
            "Why should I not share my seed phrase or private key?"
        ),
        "answer": (
            "Anyone with your seed phrase, private key, mnemonic, "
            "spend key, or view key can access or spend your crypto. "
            "VaultAI will never ask for these values, and no "
            "support person should either."
        ),
        "related_ids": (
            "can-vaultai-read-secrets",
            "is-crypto-custodial",
        ),
        "related_actions": (),
    },
    {
        "id":       "delete-my-vault",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "How do I delete my vault?",
        "answer": (
            "Open Settings and choose Delete vault. VaultAI shows a "
            "warning, then asks you to type the exact phrase "
            "DELETE MY VAULT, enter your PIN, and confirm from a "
            "trusted device. This is intentionally not a one-click "
            "action. Deletion is permanent. VaultAI cannot delete "
            "your vault from chat, and the flow cannot bypass PIN, "
            "trusted-device, or phrase confirmation."
        ),
        "related_ids": (
            "what-happens-when-i-delete-my-vault",
            "can-i-recover-deleted-vault",
            "crypto-when-vault-deleted",
        ),
        "related_actions": (FAQ_ACTION_OPEN_DELETE_VAULT,),
    },
    {
        "id":       "what-happens-when-i-delete-my-vault",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "What happens when I delete my vault?",
        "answer": (
            "Deleting your vault permanently deletes your VaultAI "
            "vault data, including files, secure items, logins, ID "
            "documents, Crypto Vault encrypted wallet records, and "
            "related vault metadata. Any active storage "
            "subscription is closed. Deletion does not move or "
            "delete crypto assets on the blockchain — those remain "
            "wherever the corresponding wallets exist. If you have "
            "not backed up your wallet outside VaultAI, deleting "
            "your encrypted wallet records may cause loss of "
            "access to those funds."
        ),
        "related_ids": (
            "delete-my-vault",
            "can-i-recover-deleted-vault",
            "crypto-when-vault-deleted",
        ),
        "related_actions": (),
    },
    {
        "id":       "can-i-recover-deleted-vault",
        "category": FAQ_CATEGORY_SECURITY,
        "question": "Can I recover a deleted vault?",
        "answer": (
            "No. Once you confirm deletion, VaultAI removes vault "
            "data permanently and cannot restore it. There is no "
            "hidden shadow copy and no recovery flow. If you also "
            "lose the wallet backup you kept outside VaultAI, "
            "on-chain crypto in that wallet may become "
            "unrecoverable too."
        ),
        "related_ids": (
            "delete-my-vault",
            "what-happens-when-i-delete-my-vault",
            "crypto-when-vault-deleted",
        ),
        "related_actions": (),
    },


    {
        "id":       "how-do-i-upload-files",
        "category": FAQ_CATEGORY_FILES,
        "question": "How do I upload files?",
        "answer": (
            "Open the Vault or Files view and choose Upload. You "
            "can also drop files onto the app. Uploads are "
            "encrypted before storage."
        ),
        "related_ids": (
            "what-file-types",
            "search-inside-documents",
        ),
        "related_actions": (FAQ_ACTION_OPEN_UPLOAD,),
    },
    {
        "id":       "what-file-types",
        "category": FAQ_CATEGORY_FILES,
        "question": "What file types can I store?",
        "answer": (
            "VaultAI accepts common document, image, audio, and "
            "video file types. Any file that fits within your "
            "storage quota can be uploaded."
        ),
        "related_ids": (
            "how-do-i-upload-files",
            "storage-limits",
        ),
        "related_actions": (),
    },
    {
        "id":       "search-inside-documents",
        "category": FAQ_CATEGORY_FILES,
        "question": "Can I search inside documents?",
        "answer": (
            "Yes. VaultAI extracts text from supported documents "
            "and lets you search across their contents from chat "
            "or the file list."
        ),
        "related_ids": (
            "summarize-pdf",
            "why-cant-find-file",
        ),
        "related_actions": (),
    },
    {
        "id":       "summarize-pdf",
        "category": FAQ_CATEGORY_FILES,
        "question": "Can VaultAI summarize my PDF?",
        "answer": (
            "Yes. Ask the assistant to summarize a specific PDF or "
            "document. The summary uses the extracted text; it "
            "does not modify the original file."
        ),
        "related_ids": (
            "search-inside-documents",
        ),
        "related_actions": (),
    },
    {
        "id":       "why-cant-find-file",
        "category": FAQ_CATEGORY_FILES,
        "question": "Why can't VaultAI find my file?",
        "answer": (
            "Check the file name spelling, the vault you are "
            "in, and whether the upload completed. Files that are "
            "still analyzing may not appear in searches yet."
        ),
        "related_ids": (
            "how-do-i-upload-files",
            "search-inside-documents",
        ),
        "related_actions": (),
    },
    {
        "id":       "how-do-i-delete-a-file",
        "category": FAQ_CATEGORY_FILES,
        "question": "How do I delete a file?",
        "answer": (
            "Open the file's row in the Files list and choose "
            "Delete. Deletion is permanent — VaultAI does not keep "
            "a shadow copy."
        ),
        "related_ids": (),
        "related_actions": (),
    },


    {
        "id":       "how-do-i-save-a-password",
        "category": FAQ_CATEGORY_SECURE_ITEMS,
        "question": "How do I save a password?",
        "answer": (
            "Open the Logins & Secure Items page and choose Save, "
            "or ask the assistant to save a login. VaultAI encrypts "
            "the entry before storing it."
        ),
        "related_ids": (
            "how-do-i-view-a-password",
            "generated-login",
        ),
        "related_actions": (FAQ_ACTION_OPEN_LOGINS,),
    },
    {
        "id":       "how-do-i-view-a-password",
        "category": FAQ_CATEGORY_SECURE_ITEMS,
        "question": "How do I view a saved password?",
        "answer": (
            "Open the login's row and choose View. Revealing the "
            "password requires trusted device, PIN unlock, and "
            "explicit confirmation — the chat itself never displays "
            "the password value."
        ),
        "related_ids": (
            "why-are-passwords-masked",
            "how-do-i-save-a-password",
        ),
        "related_actions": (FAQ_ACTION_OPEN_LOGINS,),
    },
    {
        "id":       "why-are-passwords-masked",
        "category": FAQ_CATEGORY_SECURE_ITEMS,
        "question": "Why are passwords masked?",
        "answer": (
            "Passwords are masked by default so nobody looking over "
            "your shoulder — including the AI transcript — sees the "
            "value. Reveal requires unlock and confirmation."
        ),
        "related_ids": (
            "how-do-i-view-a-password",
            "is-my-vault-encrypted",
        ),
        "related_actions": (),
    },
    {
        "id":       "generated-login",
        "category": FAQ_CATEGORY_SECURE_ITEMS,
        "question": "How do I create a generated login?",
        "answer": (
            "Ask the assistant to generate a new login for a "
            "service, or open the Logins page and pick Generate. "
            "You confirm the draft before it is saved."
        ),
        "related_ids": (
            "how-do-i-save-a-password",
            "duplicate-logins",
        ),
        "related_actions": (FAQ_ACTION_OPEN_LOGINS,),
    },
    {
        "id":       "edit-delete-secure-item",
        "category": FAQ_CATEGORY_SECURE_ITEMS,
        "question": "How do I edit or delete a secure item?",
        "answer": (
            "Open the item's row and choose Edit or Delete. Both "
            "actions require unlock; deletion is permanent."
        ),
        "related_ids": (),
        "related_actions": (FAQ_ACTION_OPEN_LOGINS,),
    },
    {
        "id":       "duplicate-logins",
        "category": FAQ_CATEGORY_SECURE_ITEMS,
        "question": "Can VaultAI find duplicate logins?",
        "answer": (
            "Yes. Ask the assistant to show duplicate or reused "
            "passwords. VaultAI compares saved logins locally after "
            "unlock and flags matches."
        ),
        "related_ids": (
            "generated-login",
        ),
        "related_actions": (FAQ_ACTION_OPEN_LOGINS,),
    },


    {
        "id":       "save-passport-license",
        "category": FAQ_CATEGORY_IDS,
        "question": "Can I save my passport or driver license?",
        "answer": (
            "Yes. Upload the document and mark it as an ID "
            "document. Extracted fields are stored encrypted; the "
            "ID number is masked by default."
        ),
        "related_ids": (
            "ids-masked-by-default",
            "id-expiry-reminders",
        ),
        "related_actions": (FAQ_ACTION_OPEN_ID_DOCS,),
    },
    {
        "id":       "ids-masked-by-default",
        "category": FAQ_CATEGORY_IDS,
        "question": "Are ID numbers hidden by default?",
        "answer": (
            "Yes. Only the last few characters are shown. Revealing "
            "the full number requires trusted device, PIN unlock, "
            "and explicit confirmation."
        ),
        "related_ids": (
            "save-passport-license",
        ),
        "related_actions": (),
    },
    {
        "id":       "id-expiry-reminders",
        "category": FAQ_CATEGORY_IDS,
        "question": (
            "Can VaultAI remind me about expiration dates?"
        ),
        "answer": (
            "Ask the assistant when your passport or license "
            "expires. VaultAI reads the extracted expiry date "
            "from your ID documents."
        ),
        "related_ids": (
            "save-passport-license",
            "how-do-i-search-ids",
        ),
        "related_actions": (FAQ_ACTION_OPEN_ID_DOCS,),
    },
    {
        "id":       "how-do-i-search-ids",
        "category": FAQ_CATEGORY_IDS,
        "question": "How do I search my ID documents?",
        "answer": (
            "Ask the assistant, or open the ID Documents page and "
            "use the search bar. Searches match on type, issuing "
            "country, and issuing state — not on the raw ID number."
        ),
        "related_ids": (
            "ids-masked-by-default",
        ),
        "related_actions": (FAQ_ACTION_OPEN_ID_DOCS,),
    },


    {
        "id":       "what-is-crypto-vault",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "What is Crypto Vault?",
        "answer": (
            "Crypto Vault is the non-custodial wallet feature of "
            "VaultAI. It stores your public receive addresses, "
            "shows live balances from public providers, and lets "
            "you prepare sends that you sign locally."
        ),
        "related_ids": (
            "is-crypto-custodial",
            "supported-assets",
            "buy-sell-swap",
        ),
        "related_actions": (FAQ_ACTION_OPEN_CRYPTO_VAULT,),
    },
    {
        "id":       "supported-assets",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Which assets are supported?",
        "answer": (
            "ETH, USDT ERC20, USDC ERC20 on Ethereum; SOL on "
            "Solana; USDT TRC20 on TRON; XMR on Monero (receive "
            "only in this release)."
        ),
        "related_ids": (
            "usdt-erc20-vs-trc20",
            "why-monero-different",
        ),
        "related_actions": (FAQ_ACTION_OPEN_CRYPTO_VAULT,),
    },
    {
        "id":       "is-crypto-custodial",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Is Crypto Vault custodial?",
        "answer": (
            "No. Crypto Vault is non-custodial. Your keys are on "
            "your device; VaultAI cannot move your crypto without "
            "your local signature."
        ),
        "related_ids": (
            "can-vaultai-move-crypto",
            "how-local-signing-works",
        ),
        "related_actions": (),
    },
    {
        "id":       "can-vaultai-move-crypto",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Can VaultAI move my crypto?",
        "answer": (
            "No. VaultAI cannot broadcast a transaction without "
            "your PIN unlock, trusted device, local signing, and "
            "explicit confirmation. It never auto-sends."
        ),
        "related_ids": (
            "is-crypto-custodial",
            "pin-before-sending",
        ),
        "related_actions": (),
    },
    {
        "id":       "pin-before-sending",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Why do I need a PIN before sending?",
        "answer": (
            "The PIN unlocks the local signing key. Without it "
            "your device cannot sign a transaction, and VaultAI "
            "will not accept an unsigned send request."
        ),
        "related_ids": (
            "how-local-signing-works",
            "can-vaultai-move-crypto",
        ),
        "related_actions": (),
    },
    {
        "id":       "usdt-erc20-vs-trc20",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Why does USDT have ERC20 and TRC20?",
        "answer": (
            "USDT exists on multiple networks. VaultAI supports "
            "USDT ERC20 on Ethereum and USDT TRC20 on TRON. You "
            "must pick the correct network — addresses, fees, and "
            "transfers are network-specific and not interchangeable."
        ),
        "related_ids": (
            "usdc-uses-eth-address",
            "erc20-needs-eth-gas",
        ),
        "related_actions": (FAQ_ACTION_OPEN_CRYPTO_VAULT,),
    },
    {
        "id":       "usdc-uses-eth-address",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": (
            "Why does USDC use my Ethereum address?"
        ),
        "answer": (
            "USDC and USDT ERC20 are ERC20 tokens on Ethereum. "
            "Your Ethereum wallet address can receive ETH, USDT "
            "ERC20, and USDC ERC20. Sending an ERC20 token spends "
            "ETH as gas."
        ),
        "related_ids": (
            "usdt-erc20-vs-trc20",
            "erc20-needs-eth-gas",
        ),
        "related_actions": (FAQ_ACTION_OPEN_CRYPTO_VAULT,),
    },
    {
        "id":       "erc20-needs-eth-gas",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Why do token transfers need ETH for gas?",
        "answer": (
            "Ethereum charges gas in ETH for every transaction, "
            "including ERC20 token transfers. Without a small ETH "
            "balance, USDT ERC20 and USDC ERC20 sends will fail."
        ),
        "related_ids": (
            "usdc-uses-eth-address",
            "usdt-erc20-vs-trc20",
        ),
        "related_actions": (),
    },
    {
        "id":       "why-monero-different",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Why is Monero different?",
        "answer": (
            "Monero is private. A public Monero address does not "
            "reveal its balance. To show balance or activity, the "
            "wallet must scan the Monero blockchain using wallet "
            "scanning capability."
        ),
        "related_ids": (
            "monero-balance-in-browser",
            "monero-send-disabled",
        ),
        "related_actions": (FAQ_ACTION_OPEN_CRYPTO_VAULT,),
    },
    {
        "id":       "monero-balance-in-browser",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": (
            "Why can't I see my Monero balance in the browser?"
        ),
        "answer": (
            "Real Monero scanning cannot run safely inside the web "
            "app. In web, VaultAI can show your Monero receive "
            "address, but balance and activity require the desktop "
            "or native local scanner."
        ),
        "related_ids": (
            "why-monero-different",
            "monero-send-disabled",
        ),
        "related_actions": (FAQ_ACTION_OPEN_CRYPTO_VAULT,),
    },
    {
        "id":       "monero-send-disabled",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Why is Monero send disabled?",
        "answer": (
            "XMR send is disabled until real local Monero scanning "
            "and signing are implemented. This prevents fake "
            "balances, unsafe spending, or invalid transactions."
        ),
        "related_ids": (
            "why-monero-different",
            "monero-balance-in-browser",
        ),
        "related_actions": (),
    },
    {
        "id":       "buy-sell-swap",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": (
            "Can I buy, sell, swap, or trade crypto in VaultAI?"
        ),
        "answer": (
            "No. Crypto Vault is for storing, receiving, and "
            "sending supported assets where enabled. It is not an "
            "exchange and does not support buy, sell, swap, trade, "
            "stake, bridge, or exchange features."
        ),
        "related_ids": (
            "is-crypto-custodial",
            "what-is-crypto-vault",
        ),
        "related_actions": (),
    },
    {
        "id":       "provider-unavailable",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": (
            "What happens if a provider is unavailable?"
        ),
        "answer": (
            "VaultAI shows a clear unavailable reason instead of "
            "inventing a balance. A 0 balance is shown only when "
            "the provider actually returns zero."
        ),
        "related_ids": (
            "why-balance-zero",
            "receive-when-balance-zero",
        ),
        "related_actions": (),
    },
    {
        "id":       "why-balance-zero",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Why does my balance say 0?",
        "answer": (
            "A displayed 0 balance means the provider returned a "
            "real zero. If the provider was unavailable, VaultAI "
            "shows an unavailable reason instead of a fake zero."
        ),
        "related_ids": (
            "provider-unavailable",
            "receive-when-balance-zero",
        ),
        "related_actions": (),
    },
    {
        "id":       "receive-when-balance-zero",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "Can I receive crypto even if balance is 0?",
        "answer": (
            "Yes. Receive works regardless of balance. Share your "
            "public receive address to accept funds; incoming "
            "transfers show up when your provider reports them."
        ),
        "related_ids": (
            "why-balance-zero",
            "provider-unavailable",
        ),
        "related_actions": (FAQ_ACTION_OPEN_CRYPTO_VAULT,),
    },
    {
        "id":       "crypto-when-vault-deleted",
        "category": FAQ_CATEGORY_CRYPTO,
        "question": "What happens to my crypto if I delete my vault?",
        "answer": (
            "Deleting your vault does not move or delete your "
            "crypto on the blockchain. VaultAI stores encrypted "
            "wallet records locally and on the server — but the "
            "coins themselves live on-chain. Deleting your VaultAI "
            "vault removes the encrypted wallet records. If you "
            "have not backed up your wallet outside VaultAI, "
            "losing the encrypted wallet records may mean losing "
            "access to those funds. VaultAI never broadcasts "
            "crypto transactions during deletion."
        ),
        "related_ids": (
            "delete-my-vault",
            "what-happens-when-i-delete-my-vault",
            "is-crypto-custodial",
        ),
        "related_actions": (),
    },


    {
        "id":       "what-plan-am-i-on",
        "category": FAQ_CATEGORY_BILLING,
        "question": "What plan am I on?",
        "answer": (
            "Ask the assistant \"what plan am I on\" or open the "
            "Billing page. VaultAI shows your active plan and the "
            "storage quota it grants."
        ),
        "related_ids": (
            "storage-limits",
            "how-do-i-upgrade",
        ),
        "related_actions": (FAQ_ACTION_OPEN_BILLING,),
    },
    {
        "id":       "storage-limits",
        "category": FAQ_CATEGORY_BILLING,
        "question": "How much storage do I have?",
        "answer": (
            "Ask the assistant \"how much storage am I using\" or "
            "open the Storage page. VaultAI shows used bytes, "
            "quota bytes, and percent used."
        ),
        "related_ids": (
            "how-do-i-upgrade",
            "storage-exceeded",
        ),
        "related_actions": (FAQ_ACTION_OPEN_STORAGE,),
    },
    {
        "id":       "storage-exceeded",
        "category": FAQ_CATEGORY_BILLING,
        "question": "What happens if I exceed storage?",
        "answer": (
            "Uploads are blocked until you free space or upgrade. "
            "Existing files remain accessible."
        ),
        "related_ids": (
            "how-do-i-upgrade",
            "how-storage-calculated",
        ),
        "related_actions": (FAQ_ACTION_OPEN_STORAGE,),
    },
    {
        "id":       "how-do-i-upgrade",
        "category": FAQ_CATEGORY_BILLING,
        "question": "How do I upgrade storage?",
        "answer": (
            "Open the Billing page and choose an upgrade tier. "
            "Checkout runs through a payment provider; VaultAI "
            "does not store your payment details."
        ),
        "related_ids": (
            "how-do-i-cancel",
            "why-checkout-opens",
        ),
        "related_actions": (FAQ_ACTION_OPEN_BILLING,),
    },
    {
        "id":       "how-do-i-cancel",
        "category": FAQ_CATEGORY_BILLING,
        "question": (
            "How do I cancel or manage subscription?"
        ),
        "answer": (
            "Open the Billing page and choose Manage subscription. "
            "You can cancel or change your plan through the "
            "payment provider portal."
        ),
        "related_ids": (
            "how-do-i-upgrade",
        ),
        "related_actions": (FAQ_ACTION_OPEN_BILLING,),
    },
    {
        "id":       "why-checkout-opens",
        "category": FAQ_CATEGORY_BILLING,
        "question": "Why does checkout open?",
        "answer": (
            "Payments run through a payment provider so VaultAI "
            "does not handle payment details directly. Checkout "
            "opens in the provider's UI."
        ),
        "related_ids": (
            "how-do-i-upgrade",
        ),
        "related_actions": (),
    },
    {
        "id":       "how-storage-calculated",
        "category": FAQ_CATEGORY_BILLING,
        "question": "How is storage calculated?",
        "answer": (
            "Storage counts the encrypted byte size of your "
            "uploaded files and documents. Secure items are small "
            "and typically negligible for quota."
        ),
        "related_ids": (
            "storage-limits",
        ),
        "related_actions": (),
    },
    {
        "id":       "why-inactive-unpaid-deleted",
        "category": FAQ_CATEGORY_BILLING,
        "question": "Why are unpaid inactive vaults deleted?",
        "answer": (
            "Unpaid vaults that are not used for at least 6 months "
            "may be permanently deleted. This keeps VaultAI "
            "storage focused on people who are actively using "
            "their vault. To keep your vault active, sign in and "
            "use your vault before the 6-month inactivity cutoff, "
            "or subscribe if you want continued storage "
            "protection. If you subscribe or become active before "
            "the cutoff, the vault is not deleted."
        ),
        "related_ids": (
            "how-to-prevent-auto-deletion",
            "delete-my-vault",
            "how-do-i-upgrade",
        ),
        "related_actions": (FAQ_ACTION_OPEN_BILLING,),
    },
    {
        "id":       "how-to-prevent-auto-deletion",
        "category": FAQ_CATEGORY_BILLING,
        "question": "How do I prevent automatic deletion?",
        "answer": (
            "To prevent automatic deletion, sign in and use your "
            "vault before the 6-month inactivity cutoff — a "
            "login, unlock, upload, or vault activity resets the "
            "timer. Alternatively, subscribe: paid vaults are not "
            "subject to the unpaid-inactive-6-months rule. If you "
            "were on a paid plan and later cancelled, the "
            "inactivity clock only starts after your paid "
            "entitlement ends."
        ),
        "related_ids": (
            "why-inactive-unpaid-deleted",
            "how-do-i-upgrade",
        ),
        "related_actions": (FAQ_ACTION_OPEN_BILLING,),
    },


    {
        "id":       "why-balance-unavailable",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": "Why is my balance unavailable?",
        "answer": (
            "The provider for that asset did not return a value in "
            "time. VaultAI shows an honest \"unavailable\" state "
            "instead of a fake zero. Retry usually recovers it."
        ),
        "related_ids": (
            "provider-unavailable",
            "why-balance-zero",
        ),
        "related_actions": (FAQ_ACTION_OPEN_CRYPTO_VAULT,),
    },
    {
        "id":       "why-file-not-showing",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": "Why is my file not showing?",
        "answer": (
            "Check that the upload finished, you are in the right "
            "vault, and any active filters or search terms match. "
            "Files still analyzing may not appear in searches yet."
        ),
        "related_ids": (
            "why-cant-find-file",
            "how-do-i-upload-files",
        ),
        "related_actions": (),
    },
    {
        "id":       "why-chat-searches-files",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": (
            "Why is chat searching files when I asked about "
            "something else?"
        ),
        "answer": (
            "That is a bug. Chat should route to the correct vault "
            "category — Crypto Vault, logins, IDs, billing, "
            "storage, or activity — before falling back to file "
            "search. If a specific phrase misroutes, please tell "
            "the assistant so it can be fixed."
        ),
        "related_ids": (
            "what-is-vaultai",
            "how-do-i-report-bug",
        ),
        "related_actions": (),
    },
    {
        "id":       "monero-desktop-required",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": "Why does Monero say desktop app required?",
        "answer": (
            "Monero scanning cannot run inside a browser. When the "
            "app is running in web, Monero balance and activity "
            "require the desktop or native scanner."
        ),
        "related_ids": (
            "monero-balance-in-browser",
            "why-monero-different",
        ),
        "related_actions": (),
    },
    {
        "id":       "tron-provider-unavailable",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": "Why does TRON say provider unavailable?",
        "answer": (
            "The TRON balance provider did not respond in time. "
            "VaultAI shows unavailable instead of a fake zero. "
            "Retry usually recovers, and receive addresses remain "
            "valid regardless."
        ),
        "related_ids": (
            "provider-unavailable",
            "receive-when-balance-zero",
        ),
        "related_actions": (),
    },
    {
        "id":       "why-subscription-checking",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": "Why is subscription status checking?",
        "answer": (
            "VaultAI is fetching your latest plan state from the "
            "billing provider. It usually clears within a few "
            "seconds; if it persists, try Refresh from the Billing "
            "page."
        ),
        "related_ids": (
            "what-plan-am-i-on",
        ),
        "related_actions": (FAQ_ACTION_OPEN_BILLING,),
    },
    {
        "id":       "how-do-i-refresh",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": "How do I refresh my vault?",
        "answer": (
            "Every list page has a Refresh action, and chat cards "
            "have a Retry button when data is unavailable. Pulling "
            "to refresh works on touch devices."
        ),
        "related_ids": (),
        "related_actions": (),
    },
    {
        "id":       "how-do-i-report-bug",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": "How do I report a bug?",
        "answer": (
            "There is no live customer-support team yet. Use the "
            "in-app FAQ and the AI assistant to search for a "
            "solution first. If a report-issue path is available "
            "in your build, use it; otherwise describe the problem "
            "here so the team can find and fix it."
        ),
        "related_ids": (
            "how-do-i-get-support",
        ),
        "related_actions": (FAQ_ACTION_OPEN_HELP_CENTER,),
    },
    {
        "id":       "how-do-i-get-support",
        "category": FAQ_CATEGORY_TROUBLESHOOTING,
        "question": "How do I get support?",
        "answer": (
            "Since there is no live customer-support team yet, use "
            "the in-app FAQ and the AI assistant. If a report-"
            "issue or contact-support route is available in your "
            "build, use it. Otherwise, live support contact is not "
            "available yet."
        ),
        "related_ids": (
            "how-do-i-report-bug",
        ),
        "related_actions": (FAQ_ACTION_OPEN_HELP_CENTER,),
    },
)




FAQ_BY_ID: dict[str, dict[str, Any]] = {
    e["id"]: e for e in FAQ_ENTRIES
}


def _validate_entries() -> None:
    seen: set[str] = set()
    for e in FAQ_ENTRIES:
        eid = e["id"]
        if not isinstance(eid, str) or not _FAQ_ID_RE.match(eid):
            raise ValueError(f"bad FAQ id: {eid!r}")
        if eid in seen:
            raise ValueError(f"duplicate FAQ id: {eid!r}")
        seen.add(eid)
        if e["category"] not in FAQ_CATEGORIES:
            raise ValueError(
                f"unknown category {e['category']!r} in {eid!r}",
            )
        answer = e["answer"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"empty answer for {eid!r}")
        if len(answer) > _MAX_ANSWER_CHARS:
            raise ValueError(
                f"answer too long ({len(answer)} chars) for {eid!r}",
            )
        for a in e.get("related_actions", ()):
            if a not in FAQ_ALLOWED_ACTIONS:
                raise ValueError(
                    f"disallowed related_action {a!r} in {eid!r}",
                )
    for e in FAQ_ENTRIES:
        for rid in e.get("related_ids", ()):
            if rid not in seen:
                raise ValueError(
                    f"{e['id']!r} references unknown related id {rid!r}",
                )


_validate_entries()


def entry_by_id(faq_id: str) -> dict[str, Any] | None:
    return FAQ_BY_ID.get(faq_id)


def entries_in_category(category: str) -> tuple[dict[str, Any], ...]:
    if category not in FAQ_CATEGORIES:
        return ()
    return tuple(e for e in FAQ_ENTRIES if e["category"] == category)


def all_ids() -> tuple[str, ...]:
    return tuple(e["id"] for e in FAQ_ENTRIES)
