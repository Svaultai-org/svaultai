# VaultAI security threat model

_Last updated: 2026-07-08._

This document lists what VaultAI protects, who might try to break in,
where the trust boundaries sit, what protections are live today, and
which gaps we track separately. It is a working document — every
change to authentication, storage, crypto, billing, or webhooks
should update the relevant section here.

VaultAI is a private digital vault. No system is impossible to
attack. The goal here is to reduce likelihood, block common attack
paths, contain damage when something does go wrong, and make abuse
detectable and recoverable.

---

## 1. Assets we protect

Ranked roughly by blast radius if compromised.

| Asset | Where it lives | Why it matters |
|---|---|---|
| PIN-derived vault key | Client only; never sent to server | Unlocks every encrypted secret |
| Encrypted wallet records | `vault_items` + client-side crypto | Access to blockchain funds if user has no external backup |
| Passwords / logins | `vault_items` (AES-GCM) | Account takeover cascade risk |
| ID documents | `uploaded_files` + `vault_document_metadata` | Identity theft risk |
| Secure notes / codes / device details | `vault_items` | Sensitive user records |
| Uploaded files | `uploaded_files` + `uploaded_file_chunks` (encrypted) | User data confidentiality |
| Document text / entities | `uploaded_files.extracted_text` + `vault_document_entities` | Same sensitivity tier as source file |
| Semantic index + intelligence summary | `semantic_index`, `vault_intelligence_summary` | May leak topic/structure clues |
| Vault metadata | `vaults` row | Enumeration and account takeover surface |
| PIN verification material | `vaults.pin_salt`, `vaults.pin_verifier` | Offline PIN brute-force target |
| Session tokens | `auth_sessions` + HMAC of token_id | Session hijack risk |
| Trusted devices | `trusted_devices` | Bypass sensitive-action gates |
| Billing / subscription state | `account_subscriptions`, `stripe_customers` | Fraud + subscription bypass |
| Deletion tombstones | `vault_deletion_tombstones` (anonymized) | Audit-only; no user data |

---

## 2. Attacker profiles

| Actor | Motivation | Assumed capability |
|---|---|---|
| Unauthenticated internet attacker | Credential stuffing, mass enumeration | Can make HTTP requests, run bots, control many IPs |
| Bot / DDoS attacker | Resource exhaustion | Very high request rate; may spoof origins and headers |
| Authenticated malicious user | Escalation, data exfil | Valid signup + PIN; wants to touch other tenants |
| Compromised-session attacker | Silent takeover | Has a valid session token, may not have PIN |
| Malicious file uploader | Malware distribution, parser exploits | Can upload arbitrary bytes named "invoice.pdf" |
| Ransomware-style mass actor | Destroy or hold user data hostage | Has a session; wants to mass-upload or mass-delete |
| Webhook spoofing attacker | Grant themselves paid entitlement | Can POST arbitrary bytes to `/billing/stripe/webhook` |
| Provider abuse attacker | Exhaust upstream (RPC / OCR / LLM) quotas | Wants to run up cost or cause outage |

---

## 3. Trust boundaries

```
              ┌──────────────────────────┐
              │  Browser / native app    │  ← untrusted device
              │  (Flutter, Dart)         │
              │  Holds session token +   │
              │  vault key (in RAM)      │
              └────────────┬─────────────┘
                           │  HTTPS + CORS + CSP
                           ▼
              ┌──────────────────────────┐
              │  FastAPI backend         │  ← half-trusted
              │  main.py + routes/*      │
              │  Verifies session,       │
              │  device gate, rate limit │
              └──┬──────────┬───────┬────┘
                 │          │       │
                 ▼          ▼       ▼
        ┌──────────┐  ┌────────┐  ┌────────────┐
        │ Postgres │  │ Stripe │  │ Crypto RPC │
        │ vaults DB │ │ webhook│  │ providers  │
        └──────────┘  └────────┘  └────────────┘
```

Rules that hold across every boundary:

- **PIN never crosses "browser → backend" in plaintext long-term.**
  It is sent only to unlock, immediately used to derive a key,
  verified via AES-GCM decrypt of `pin_verifier`, and discarded.
- **Vault key never leaves the browser.** The server derives it
  per-request from the PIN it received, then discards it.
- **Crypto private material** (seed / mnemonic / spend / view key /
  raw private key) never crosses "browser → backend". Local
  signing only. Chat refuses to surface these.
- **Billing state** is authoritative only after a signature-verified
  Stripe webhook AND an idempotency check in `provider_event_log`.

---

## 4. Existing protections

### Encryption
- Per-vault AES-GCM-256, key = PBKDF2-HMAC-SHA256(PIN, salt,
  `KDF_TARGET_ITERATIONS`). Legacy vaults on 100k iterations are
  migrated on next successful unlock.
- Chunked uploads use AES-GCM-256 per chunk with a 12-byte nonce
  and per-index AAD, blocking chunk-reordering attacks.

### Authentication + session
- Session tokens: 16-byte random token_id + 32-byte HMAC-SHA256
  signature over the id, base64url-encoded. HMAC key from
  `VAULT_SESSION_SECRET`, min 32 chars, no fallback.
- Tokens are DB-backed (`auth_sessions.token_id`), can be revoked,
  and expire based on `VAULT_SESSION_TTL_HOURS` (default 7d, max 30d,
  min 1h).
- `revoke_all_sessions_for_vault(vault_id)` runs on vault deletion.

### PIN brute-force protection
- `MAX_PIN_ATTEMPTS = 5`; on the 5th failure the vault is locked
  for `PIN_LOCKOUT_HOURS = 24`.
- Failed attempts write `failed_pin_attempts` and `locked_until`
  transactionally in the same login SQL.
- `enforce_pin_verify_rate_limit` adds a per-vault + per-IP HTTP
  rate limit on `/verify-pin` on top of the account lockout.

### Trusted device gate
- `verify_trusted_device` composes with `verify_session_token`.
- Trusted-device required for: reveal password, reveal secure
  item, reveal ID number, crypto send/sign, delete vault, `/chat`.
- Bypass list is closed (`ROUTES_EXEMPT_FROM_DEVICE_GATE` in
  `device_gate.py`) and tested.

### Delete vault
- Three-step gate: (1) exact phrase `DELETE MY VAULT`, (2) HMAC-
  signed short-lived request token bound to the vault id, (3) PIN
  verification via the same PBKDF2 → AES-GCM decrypt path as login.
- Deletion cascades via ON DELETE CASCADE; a safe tombstone with
  hashed vault id is inserted for audit.
- Rate-limited via `enforce_delete_vault_rate_limit` (default 10/hr
  per IP+vault).

### Automatic inactive-unpaid cleanup
- Query candidates once per day (`inactive_unpaid_cleanup.run_once`).
- **Re-checks BOTH billing status AND activity per candidate**
  at delete-time; skips if either flipped.
- Paid statuses (`active`, `in_grace`, `canceled_pending`) are
  never eligible.

### Rate limiting
- Two-layer stack. Slowapi decorators on the main app cover
  IP-level per-route limits (~19 routes). A separate custom
  backend (`rate_limit_backend.py`) supports per-vault limits and
  a Redis backend for clustered deploys.
- Enforced buckets: `auth_signup`, `auth_login`, `pin_verify`,
  `chat`, `delete_vault`, `upload_burst`, `delete_burst`, `export`,
  `crypto_reveal`.
- 429 body: `{"code": "rate_limited", "message": "Too many requests.
  Please wait and try again.", "reset_in_seconds": N}` +
  `Retry-After` header. Body NEVER reveals whether the account
  exists, which counter tripped, or internal limits.

### Body size + upload caps
- `MAX_JSON_BODY_BYTES` (default 1 MB) for anything that isn't an
  upload.
- `MAX_UPLOAD_BYTES` (default 100 MB) for single-shot upload.
- `CHUNK_UPLOAD_MAX_FRAME_BYTES` (default 20 MB) for chunked frame.
- Chunked upload total ceiling: 4096 chunks × 16 MiB = 64 GiB per
  file (plus per-vault storage quota).

### File upload path safety
- `_sanitize_relative_path` in `main.py` rejects absolute paths,
  drive letters, `..`, `.`, NUL, CR/LF, and normalizes `\` → `/`.
- Content-Length is trusted only to short-circuit oversized bodies;
  the actual bytes are re-validated by the AEAD decrypt.

### Stripe webhook
- `Stripe-Signature` header required.
- `stripe_service.verify_webhook_signature` uses the Stripe SDK's
  HMAC construct.
- `provider_event_log` (PK on `(source, source_event_id)`) provides
  replay + idempotency protection.
- Webhook path exempt from device gate on purpose (not a user
  request).

### CORS
- Prod: `CORS_ALLOWED_ORIGIN_REGEX` required — refuses to start with
  a wildcard.
- Dev: loopback-only regex fallback.
- `allow_credentials=True` is safe because auth is bearer-based, not
  cookie-based; still gated behind a strict regex.

### Security headers
- Enabled by default via `SecurityHeadersMiddleware`:
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Content-Security-Policy` (see
  `security_headers.py CSP_STRICT`), `Permissions-Policy` (feature
  set neutered), `Cross-Origin-{Opener,Resource}-Policy: same-
  origin`.
- Production adds `Strict-Transport-Security` with a 2y max-age +
  `includeSubDomains; preload`.
- Sensitive paths (auth, PIN, delete, secure item reveal, billing,
  logins) also get `Cache-Control: no-store, no-cache,
  must-revalidate, private`.

### Crypto vault invariants (locked in by tests)
- Backend never receives seed / private key / mnemonic / spend key
  / view key. Local signing only.
- Chat classifier refuses any message asking for that material.
- Send-draft cards ship with `canBroadcast=False`.
- XMR send is disabled; XMR balance requires the native scanner.
- Provider "unavailable" is a closed-set reason — no fake zero
  balances, no fake tx rows.
- Delete vault does **not** import broadcast/sign modules (asserted
  by source scan) — deleting a vault never moves crypto.

### Logging safety
- `security_event_log.emit` accepts only closed-set reasons + route
  groups; rejects free-form text containing `pin=`, `seed`,
  `private key`, `mnemonic`, `api key`, `bearer `, `password`,
  `encrypted_data`, and other sensitive tokens.
- All identifiers passed to security event lines are pre-hashed
  (`short_hash`, 12 hex chars).
- Existing per-callsite redactors: `extractor.redact_message`,
  `crypto_schemas.redact_crypto_payload`, `stripe_service.redact_stripe_id`,
  `evm_transaction_history._redact_address` / `_redact_tx_hash`.

---

## 5. Known gaps and future work

These are things we are aware of and either accept or track for a
future pass. Nothing here weakens the invariants above.

- **Bearer token vs. HttpOnly cookie.** The Flutter app carries
  the session as `Authorization: Bearer`. This is a deliberate
  trade-off — Flutter web can't set HttpOnly cookies, and the
  native app uses secure OS storage. XSS in the web build could
  still lift the token; that is why the CSP disallows inline
  scripts and eval.
- **Redis rate-limit backend.** Implemented in
  `RedisRateLimitBackend` — atomic sliding-window Lua script,
  SHA-256-hashed keys, and per-bucket fail-closed/fail-open
  behaviour on outage. In-memory remains the default for
  single-instance dev; multi-instance deploys set
  `VAULTAI_RATE_LIMIT_REDIS_URL`. Boot emits a WARNING if
  production runs on in-memory. See
  [rate_limits.md](./rate_limits.md).
- **Global chat-input filter.** Individual routes handle sensitive
  material (chat classifier refuses seed/mnemonic questions,
  `redact_message` scrubs credentials before logging), but there's
  no single upstream filter that guarantees no sensitive substring
  reaches an LLM prompt. Every route that talks to an LLM
  currently owns this itself.
- **Archive decompression bombs.** VaultAI does not open zip or tar
  archives server-side today. If that changes, the change MUST
  add a decompression-ratio and total-size guard before landing.
- **MIME sniffing.** `content_type` on upload is trusted from the
  client. A future pass should sniff the magic bytes and reject
  mismatches. Not shipping today because the file bytes are
  encrypted at rest and never executed server-side.
- **Global request logging filter.** Every callsite currently
  redacts by convention. A single logging filter that masks
  `pin=…`, `Authorization: Bearer …`, and known sensitive JSON
  keys before they hit any handler would harden this further.
