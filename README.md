# SVaultAI

**Your private digital vault with an assistant that speaks your language.**

SVaultAI is an end-to-end-encrypted personal vault for the things that
usually live scattered across your inbox, notes app, camera roll, and
password manager: passports and IDs, logins, secure notes, files and
photos, and crypto wallet records. A vault-native chat assistant sits
on top so you can retrieve, summarise, and manage all of it in plain
language.

The vault is opened by a **PIN you never send to the backend in
plaintext**. The vault contents are decrypted **on-device**, with a
key that only exists in memory while you are unlocked. SVaultAI Chat
runs against **masked, safe projections** of your vault — the AI
never sees your raw records.

---

## Contents

- [What you can put in it](#what-you-can-put-in-it)
- [SVaultAI Chat](#svaultai-chat)
- [Crypto Vault](#crypto-vault) — non-custodial, receive-first
- [Trust model](#trust-model) — what we guarantee, what we don't
- [Cryptography summary](#cryptography-summary)
- [Inheritance](#inheritance)
- [Deleting your vault](#deleting-your-vault)
- [Languages](#languages)
- [Architecture](#architecture)
- [Getting started (development)](#getting-started-development)
- [Testing](#testing)
- [Production deployment](#production-deployment)
- [What SVaultAI is not](#what-svaultai-is-not)
- [Status](#status)

---

## What you can put in it

| Category | Examples |
|---|---|
| **Logins** | Web and app credentials with per-item username/password/notes |
| **ID documents** | Passport, driver's licence, national ID, membership cards |
| **Secure notes** | Free-form text and codes |
| **Files** | PDFs, images, video, audio, folders — each stored as encrypted chunks |
| **Crypto wallet records** | Addresses, labels, receive-side transaction history |
| **Preferences and memory** | The assistant's per-vault long-term memory index |

Every item is encrypted per-vault with a key derived from your PIN.
The backend stores ciphertext + metadata needed to route requests —
never the plaintext.

---

## SVaultAI Chat

SVaultAI Chat is the in-app assistant. It's built around one rule:
**deterministic routing wins, AI is a fallback.**

- **Deterministic router first.** Common intents ("show my saved
  logins", "how much storage am I using", "open Crypto Vault",
  "delete my vault", "what files do I have") are recognised by a
  language-aware pattern router before any LLM call. That router
  serves a *card* (a structured UI response), not free-form text.
- **AI answers only when the router doesn't fire.** When a message
  is genuinely open-ended, the assistant answers from a safe
  projection of the vault — filenames, categories, non-secret
  attributes — never raw secrets. The assistant refuses to reveal
  seed phrases, private keys, PINs, spend keys, view keys, or
  encrypted material, in every supported language.
- **Language auto-detects per message.** If you write "hola" while
  the shell is English, you get Spanish back. If you write a short
  message ("ok"), the assistant follows the app-shell language.
- **FAQ answers in your language.** The multilingual FAQ ships with
  full translations in the seven fully-localised languages and
  falls back to English elsewhere.

---

## Crypto Vault

The Crypto Vault is a **non-custodial receive-first wallet
experience**. It exists so a user can save a crypto record next to
their passport, view the receive-side balance, and never lose the
context. It is not a trading platform.

**Supported networks:**

| Network | Receive | Send | Notes |
|---|---|---|---|
| Ethereum mainnet (ETH) | Yes | Yes, behind safety gates | Alchemy RPC by default |
| ERC20 USDT / USDC | Yes | Yes, behind safety gates | Standard mainnet contracts |
| Solana mainnet (SOL) | Yes | Yes, behind safety gates | Helius RPC by default |
| TRON (TRX) + USDT-TRC20 | Yes | Yes, behind safety gates | TronGrid |
| Monero (XMR) | Foundation only | Off at launch | Scanner mode `none` until a resident scanner ships |

**What the backend never touches:**

- Your seed phrase or mnemonic.
- Your private spend key or view key.
- Your wallet password.
- Any plaintext private key.

All plaintext-secret aliases (`privateKey`, `seedPhrase`, `mnemonic`,
`recoveryPhrase`, `wif`, `xprv`, `spendKey`, `viewKey`, `polyseed`,
`walletPassword`, …) are **rejected at the request schema layer**
before the request handler ever sees the payload.

The Crypto Vault also never surfaces buy / sell / swap / trade /
stake / bridge / exchange language — the FAQ and the chat classifier
both refuse those framings.

---

## Trust model

**We think you should read this before you trust the vault with
anything.**

- **Your PIN is the root.** It never leaves the device in plaintext.
  Every vault operation that touches encrypted material requires
  the PIN.
- **Encryption is on your device.** Vault items are decrypted after
  you unlock, using a key derived from your PIN + a per-vault salt.
  The backend stores only ciphertext + routing metadata.
- **The assistant runs against masked data.** SVaultAI Chat sees
  file names, categories, sizes, and structured "safe projections" —
  never the encrypted content.
- **Sessions are short and revocable.** Every session is signed with
  an HMAC secret; sessions can be revoked per-vault and per-device.
  Vault deletion cascades to session revocation.
- **Destructive actions have gates.** Deleting a vault requires a
  trusted device, an active session, your PIN, and the exact
  confirmation phrase `DELETE MY VAULT`.
- **We rate-limit sensitive surfaces.** PIN verify, delete-vault,
  chat, upload burst, delete burst, and export all have quotas —
  in-memory in dev, Redis-clustered in production.

**What SVaultAI does not promise:**

- Perfect security. No software can promise that. If your device is
  compromised, your unlocked vault is compromised.
- Recovery of a lost PIN. Losing the PIN means losing the vault.
  There is no server-side backdoor; there is no reset link.
- Custody of your crypto. SVaultAI does not hold your funds. If your
  private key is compromised, SVaultAI cannot stop the loss.

More detail:
[docs/security_threat_model.md](docs/security_threat_model.md),
[docs/security_hardening.md](docs/security_hardening.md),
[docs/incident_response.md](docs/incident_response.md).

---

## Cryptography summary

| Layer | Choice |
|---|---|
| Key derivation | PBKDF2-HMAC-SHA256, 100,000 iterations, per-vault salt |
| Symmetric | AES-GCM-256 |
| Session tokens | HMAC-SHA256 with `VAULT_SESSION_SECRET` |
| Delete-vault challenge | HMAC-signed, 10-minute TTL, vault-bound |
| At-rest chunks | Chunked AEAD; each chunk has its own nonce |
| Pairing codes (inheritance) | PBKDF2 + AES-GCM wrap of the recovery envelope |

The KDF iteration count is enforced at the schema layer
(`kdf_iterations >= 100000`). Sessions carry no vault plaintext;
their only claim is "this token id maps to this vault id". The
delete-vault challenge is short-lived and bound to the specific
vault so a captured challenge can't be replayed against another
account.

---

## Inheritance

SVaultAI supports **beneficiary pairing** so a vault can be passed
to a named person on a defined schedule.

1. The vault owner shares a **pairing code** with a beneficiary.
2. The beneficiary redeems the code; the two vaults become
   **linked**, with a **30-day cooldown** before a claim can be
   made.
3. If the owner does not disclaim during the cooldown, the
   beneficiary can **claim**. The claim creates a **fresh vault on
   the beneficiary's account**, with the recovery envelope
   unwrapped using their PIN — the beneficiary chooses their own
   PIN; they do not learn the passer's PIN.
4. The passer's vault is soft-frozen for 90 days after a successful
   claim.

The recovery envelope carries no plaintext material and the
backend never learns either PIN.

---

## Deleting your vault

Deletion is destructive and irreversible. To reach the delete flow
you must:

1. Be on a **trusted device**.
2. Have an **active session**.
3. Enter your **PIN**.
4. Type the exact phrase **`DELETE MY VAULT`**.

The confirmation phrase is fixed and never localised. On success:

- The vault row is deleted; a PostgreSQL `ON DELETE CASCADE`
  cleans every vault-owned row (files, chunks, secure items,
  semantic index, agent memories, embeddings, sessions, trusted
  devices, notifications, …).
- A safe **tombstone** is written with only the hashed vault id,
  timestamp, and reason. No vault name, no account id, no
  addresses, no encrypted material.
- All open sessions for that vault are revoked.
- The frontend clears session, in-memory caches
  (`_VaultCrypto`, `CryptoChatLiveCache`, `FrontendCache`) and
  persistent preferences (`session_token`, `last_vault_name`),
  navigates to `/auth`, and shows "Your vault has been deleted."

Automatic cleanup of unpaid inactive vaults follows the same
service path (`delete_vault_and_all_data`) after a re-check of
billing and activity. Paid subscribers are never auto-deleted.

---

## Languages

SVaultAI ships **seven fully-localised languages** across the app
shell, help/FAQ content, and chat replies:

- English
- Arabic (RTL)
- French
- Spanish
- Japanese
- Korean
- Chinese (Simplified)

A broader language registry supports natural chat replies across major
languages and writing systems, including Portuguese, German, Italian,
Dutch, Polish, Romanian, Russian, Ukrainian, Turkish, Greek, Hebrew,
Persian, Urdu, Hindi, Bengali, Punjabi, Tamil, Telugu, Marathi, Gujarati,
Nepali, Sinhala, Vietnamese, Thai, Indonesian, Malay, Tagalog/Filipino,
Swahili, Hausa, Yoruba, Igbo, Somali, Amharic, Zulu, and Afrikaans. The
app shell falls back to English with an honest "translation in progress"
notice when its full interface translation is not yet available.

Chat response-language order:

1. A language explicitly requested in the current message.
2. The confidently detected language of the current message.
3. Manual selection in Settings.
4. Device/browser locale.
5. English.

Language selection is per-message and does not change the account or vault
locale. It is independent of intent routing: general conversation uses no
vault tools, while explicit vault requests retain their required tools.
Common aliases such as Filipino/Tagalog, Mandarin/Chinese, Farsi/Persian,
Castilian/Spanish, and Brazilian Portuguese/Portuguese are normalized.

---

## Architecture

```
┌────────────────────────────┐        ┌────────────────────────────┐
│  Flutter frontend          │        │  FastAPI backend           │
│  (Web / iOS / Android /    │  HTTPS │  (Uvicorn, Alembic,        │
│   Windows / macOS / Linux) │◀──────▶│   PostgreSQL / Supabase)   │
│                            │        │                            │
│  • PIN entry               │        │  • Session HMAC            │
│  • On-device AES-GCM       │        │  • Trusted-device gate     │
│  • SVaultAI Chat UI        │        │  • Rate limiting           │
│  • Crypto Vault UI         │        │  • Security headers        │
│  • Multi-locale shell      │        │  • Vault deletion service  │
│                            │        │  • Chat orchestrator       │
└────────────────────────────┘        └────────────────────────────┘
                                              │
                                              ▼
                                       ┌────────────────┐
                                       │  PostgreSQL    │
                                       │  (encrypted    │
                                       │   vault rows)  │
                                       └────────────────┘
```

- **Frontend** — Flutter, single codebase across Web + iOS +
  Android + desktop. State lives in a `ChangeNotifier`-based
  `AppState`. Crypto lives in `_VaultCrypto`, cached per-vault
  and cleared aggressively on logout / delete / vault switch.
- **Backend** — FastAPI with 20+ route modules split by domain
  (auth, chat, files, crypto wallet, billing, delete, expiry,
  devices, memory, relationships, security-centre, …). Alembic
  migrations, psycopg2 raw SQL for hot paths.
- **Database** — PostgreSQL. Every vault-owned table has an
  `ON DELETE CASCADE` FK to `vaults(vault_id)`, so vault
  deletion is a single row-delete under the hood.
- **Storage layer** — file chunks are encrypted client-side and
  reassembled server-side into an authenticated chunk stream.
- **Third-party** — Stripe (billing), OpenAI (chat completions,
  behind masked projections only), Alchemy / Helius / TronGrid
  (public RPC for crypto receive), Redis (rate-limit backend in
  prod).

---

## Getting started (development)

### Backend

```bash
cd vault_ai_backend
python -m venv .venv
.venv\Scripts\activate     # Windows
# or: source .venv/bin/activate

pip install -r requirements.txt

# Copy the example env, fill in local values.
cp .env.example .env
# Set at minimum:
#   VAULTAI_ENV=development
#   DATABASE_URL=postgres://...
#   VAULT_SESSION_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
#   OPENAI_API_KEY=sk-...   (optional in dev)

# Run migrations.
alembic upgrade head

# Start.
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The backend refuses to boot in `VAULTAI_ENV=production` without a
full production config; in `development` mode it accepts sensible
defaults and unions `http://localhost:5173` into the CORS origin
regex automatically.

### Frontend

```bash
cd vault_ai_frontend
flutter pub get

# Web (default dev port is 5173).
flutter run -d chrome --web-port 5173

# Or build for release.
flutter build web --release
```

The frontend defaults to `http://localhost:8000` for the backend.
Override with `--dart-define=BACKEND_BASE_URL=https://…`.

---

## Testing

Both suites are run on every slice.

**Backend (Python + pytest):**

```bash
cd vault_ai_backend
python -m pytest -q
# 6,118 passed / 0 failed / 65 skipped / 8,511 subtests (last full run)
```

**Frontend (Flutter):**

```bash
cd vault_ai_frontend
flutter test
# 2,975 passed / 0 failed (last full run)
```

**Web release build** — verifies the whole Dart+JS pipeline
compiles cleanly:

```bash
cd vault_ai_frontend
flutter build web --release
```

Coverage highlights:

- **Router determinism** — every high-traffic intent (saved
  logins, files, passport, storage quota, plan, delete-vault,
  Crypto Vault open, …) has an anchored regex test that catches
  drift.
- **Secret leakage guards** — repeated tests plant fake
  `sk_live_LEAKY-KEY-XXX` / `whsec_LEAKY-SECRET-YYY` in env and
  assert that health envelopes, logs, and error paths do not
  echo them back.
- **Encryption invariants** — the frontend has tests that assert
  no plaintext `seed`, `mnemonic`, `privateKey`, `spendKey`,
  `viewKey`, or `walletPassword` alias ever appears in a network
  payload.
- **Delete-vault** — 20 frontend + 16 backend regression tests
  covering session revocation, cache clearing, route
  replacement, and status-code separation between success and
  failure.
- **Localisation** — every representative key is asserted non-
  empty across all seven fully-localised locales, with cross-
  locale differ-from-English checks so a missed translation
  fails the suite.

---

## Production deployment

Follow the runbook rather than these bullets:
[vault_ai_backend/DEPLOYMENT_RUNBOOK.md](vault_ai_backend/DEPLOYMENT_RUNBOOK.md).

Short version of what must be true before boot:

- `VAULTAI_ENV=production`
- `VAULT_SESSION_SECRET` (≥ 32 chars, high-entropy)
- `DATABASE_URL` with SSL
- `OPENAI_API_KEY`
- `DESCOPE_PROJECT_ID`
- `CORS_ALLOWED_ORIGIN_REGEX=^https://(app|www)\.…$` (anchored)
- `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`
- `VAULTAI_RATE_LIMIT_BACKEND=redis`
+ `VAULTAI_RATE_LIMIT_REDIS_URL=…`
- `VAULTAI_DEBUG_ENDPOINTS_ENABLED=false`
- `VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=false`

Anything missing causes the boot handler to refuse rather than
downgrade quietly. The full example lives at
[vault_ai_backend/.env.production.example](vault_ai_backend/.env.production.example).

Related runbooks:

- [docs/rate_limits.md](docs/rate_limits.md)
- [docs/security_hardening.md](docs/security_hardening.md)
- [docs/security_threat_model.md](docs/security_threat_model.md)
- [docs/incident_response.md](docs/incident_response.md)
- [docs/crypto_wallet_production_runbook.md](docs/crypto_wallet_production_runbook.md)
- [docs/crypto_wallet_launch_checklist.md](docs/crypto_wallet_launch_checklist.md)
- [vault_ai_backend/BACKUP_AND_RECOVERY.md](vault_ai_backend/BACKUP_AND_RECOVERY.md)

---

## What SVaultAI is not

- **Not an exchange or brokerage.** No buy, sell, trade, swap,
  bridge, staking, or fiat on-ramp. The Crypto Vault is a
  receive-first, storage-and-context product.
- **Not a custodian.** SVaultAI does not hold your funds. It stores
  encrypted labels and receive-side addresses next to your other
  vault data.
- **Not a password sync service.** Logins live in your vault. They
  are not synced across a login provider or shared through a
  browser extension.
- **Not a search index vendor.** The AI answers about your own
  vault, from safe projections. It is not a general web-search
  assistant.
- **Not an unrecoverable-by-design "seed phrase" wallet in the
  crypto sense.** The vault is unrecoverable if you forget your
  PIN; if you also lose beneficiary pairing, there is no reset.
  This is intentional. There is no server-side backdoor.

---

## Status

Pre-launch. Zero real users at time of writing. The repository
carries a full backend + frontend suite, a production runbook, a
threat model, and the incident-response guide. The delete-vault
flow, session/state clearing, CORS handshake, localisation
default (device-detected, English fallback), and Crypto Vault
receive-side surfaces are all covered by regression tests.

Recent regression coverage also verifies that web media dialogs close their
own dialog route without navigating away from the active vault, and that
per-message multilingual requests produce the requested response language
without interfering with vault routing.

If you file an issue, please **do not paste real PINs, real seed
phrases, real wallet addresses, real Stripe keys, real session
tokens, or any real encrypted material**. Redact aggressively.
The threat model and the incident-response doc explain what a
useful report looks like.
