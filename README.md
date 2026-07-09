\# VaultAI



VaultAI is a private digital vault for storing, organizing, and managing sensitive personal data in one secure place.



It is designed like a digital safe: users can save important files, documents, IDs, logins, secure notes, and crypto wallet records, then use VaultAI Chat to search, summarize, and manage their vault.



\## What VaultAI Does



VaultAI helps users store and manage:



\- Files, documents, photos, videos, and audio

\- Passwords and login records

\- Secure notes and sensitive codes

\- ID documents

\- Storage and billing information

\- Trusted devices

\- Crypto Vault receive/send/store flows

\- Vault activity and vault search

\- Multilingual Help \& FAQ content



\## VaultAI Chat



VaultAI Chat is the in-app vault assistant. It helps users interact with their vault using natural language.



Users can ask questions such as:



\- “How much storage am I using?”

\- “Show my saved logins.”

\- “Find my ID documents.”

\- “What plan am I on?”

\- “Open Crypto Vault.”

\- “Summarize this document.”

\- “Delete my vault.”



VaultAI Chat is designed to route requests to the correct vault area before falling back to file search.



\## Crypto Vault



VaultAI includes a non-custodial Crypto Vault experience for send, receive, and store flows.



Supported crypto-related work includes:



\- ETH mainnet

\- USDT ERC20

\- USDC ERC20

\- SOL

\- USDT TRC20

\- XMR receive/scanner-gated foundation



VaultAI does not provide buy, sell, trade, exchange, bridge, staking, or custody services.



Private keys and sensitive wallet secrets are not handled by the backend in plaintext.



\## Security Principles



VaultAI is built around several security principles:



\- PIN-protected vault access

\- Trusted-device checks

\- Session validation

\- Sensitive action gates

\- Rate limiting

\- Security headers

\- Audit-style security event logging

\- Encrypted vault records

\- No plaintext storage of sensitive wallet secrets on the backend

\- Destructive actions require confirmation



No software can guarantee perfect security, but VaultAI is designed to reduce exposure and protect sensitive vault data with layered controls.



\## Delete Vault



VaultAI includes a destructive delete-vault flow.



Deleting a vault requires:



\- Trusted device

\- Active session

\- PIN confirmation

\- Exact confirmation phrase



After successful deletion, VaultAI clears session state, vault state, frontend caches, and redirects the user out of the authenticated app.



\## Inactive Unpaid Vault Cleanup



VaultAI supports automatic cleanup of unpaid inactive vaults according to configured production policy.



Paid/subscribed users are not automatically deleted by the inactive-unpaid cleanup flow.



\## Localization



VaultAI includes multilingual support and localized Help \& FAQ content.



Fully supported languages include:



\- English

\- Arabic

\- French

\- Spanish

\- Japanese

\- Korean

\- Chinese



Additional languages may be partially supported in the app shell.



\## Tech Stack



VaultAI uses:



\- Flutter frontend

\- FastAPI backend

\- PostgreSQL/Supabase-style database

\- Stripe billing integration

\- Redis-backed rate limiting support

\- Alembic migrations

\- Python backend test suite

\- Flutter frontend test suite



\## Development Status



This repository contains the VaultAI release build with:



\- Full vault chat

\- Crypto Vault

\- Security hardening

\- Delete-vault flow

\- Storage and billing readiness

\- Localization

\- Frontend performance improvements

\- Production deployment documentation

\- Backend and frontend regression tests



Latest verified local results:



```text

Backend: 6,118 passed / 0 failed

Frontend: 2,975 passed / 0 failed

Flutter web release build: passed

