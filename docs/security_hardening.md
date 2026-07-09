# VaultAI security hardening reference

This is the operator-facing counterpart to
[`security_threat_model.md`](./security_threat_model.md). The threat
model describes *what we're defending against*. This doc describes
*where the knobs live* and how to verify each protection is
active.

## Layered defense summary

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 0 — network                                          │
│    TLS termination, WAF (external — not this repo)          │
├─────────────────────────────────────────────────────────────┤
│  Layer 1 — request front door                               │
│    CORS regex, security-header middleware, body-size cap    │
├─────────────────────────────────────────────────────────────┤
│  Layer 2 — rate limits                                      │
│    signup, login, PIN verify, delete-vault, chat, upload,   │
│    delete-burst, export, crypto-reveal                      │
├─────────────────────────────────────────────────────────────┤
│  Layer 3 — auth + trusted device                            │
│    HMAC bearer token, device gate, PIN unlock, 5-strike     │
│    lockout, per-vault activity timestamps                   │
├─────────────────────────────────────────────────────────────┤
│  Layer 4 — action gates                                     │
│    reveal → trusted-device + PIN + confirm                  │
│    crypto send → local signing + confirm                    │
│    delete vault → phrase + PIN + HMAC challenge             │
├─────────────────────────────────────────────────────────────┤
│  Layer 5 — data at rest                                     │
│    AES-GCM-256, PBKDF2-HMAC-SHA256, ON DELETE CASCADE       │
├─────────────────────────────────────────────────────────────┤
│  Layer 6 — audit                                            │
│    security_event_log (closed-set), Stripe idempotency,     │
│    deletion tombstones                                      │
└─────────────────────────────────────────────────────────────┘
```

## Enabling / configuring each layer

### Security headers (Layer 1)

- Wired by `main.py` via `SecurityHeadersMiddleware`.
- Header set defined in `security_headers.py`
  (`CSP_STRICT`, `PERMISSIONS_POLICY`, `HSTS_VALUE`).
- Enabled by default. Disable only for local browser debugging:
  ```
  VAULTAI_SECURITY_HEADERS_ENABLED=false
  ```
- HSTS is only emitted when one of `VAULTAI_ENV`, `ENVIRONMENT`,
  `FLASK_ENV`, `NODE_ENV` is `prod|production|live`.
- Sensitive paths (`/auth/*`, `/verify-pin`, `/vault/delete/*`,
  `/logins/*`, `/secure-items/*`, `/ids/*`, `/crypto/reveal*`,
  `/billing/*`, `/manage/*`, `/get-login`, `/reveal-*`) also get
  `Cache-Control: no-store, no-cache, must-revalidate, private`.
- Verify with:
  ```
  curl -s -I https://your-host/auth/me | grep -Ei \
    'Content-Security-Policy|X-Content-Type|X-Frame|Cache-Control'
  ```

### CORS (Layer 1)

- `CORS_ALLOWED_ORIGIN_REGEX` is required in production. The app
  refuses to start without it.
- Example: `CORS_ALLOWED_ORIGIN_REGEX=r'https://(app|www)\.vaultai\.example'`.
- `allow_credentials=True` is safe because auth is bearer-based,
  but do NOT relax the regex to `.*`.

### Body size caps (Layer 1)

- `MAX_JSON_BODY_BYTES` — default 1 MB, applies to all non-upload
  routes.
- `MAX_UPLOAD_BYTES` — default 100 MB, single-shot upload.
- `CHUNK_UPLOAD_MAX_FRAME_BYTES` — default 20 MB, chunked upload
  frame.
- Enforced in `main.py::limit_request_body_size` middleware, before
  the router.

### Rate limiting (Layer 2)

- Two implementations. Slowapi decorators on individual routes
  cover IP-based limits. `rate_limit_backend.py` powers per-vault
  and cross-route buckets used by `rate_limit_auth.py`,
  `rate_limit_crypto_reveal.py`, and `rate_limit_sensitive.py`.
- Backend selection:
  ```
  VAULTAI_RATE_LIMIT_BACKEND=redis   # or in_memory (default)
  VAULTAI_RATE_LIMIT_REDIS_URL=redis://...
  ```
  In-memory is safe for a single instance. Multi-instance MUST
  swap to Redis. The Redis backend runs a single Lua script for
  atomic increment+expire, hashes every key with SHA-256 before
  storage, and fails CLOSED on high-risk buckets (auth, PIN,
  delete-vault, crypto-reveal, burst guards, export) if Redis is
  unreachable. See [`rate_limits.md`](./rate_limits.md).
- Full list of tunable env vars, defaults, and buckets: see
  [`rate_limits.md`](./rate_limits.md).

### Auth + PIN (Layer 3)

- `MAX_PIN_ATTEMPTS = 5`, `PIN_LOCKOUT_HOURS = 24` in
  `vault_core.py`.
- Session token secret `VAULT_SESSION_SECRET` — required, min 32
  chars, no fallback.
- Session TTL `VAULT_SESSION_TTL_HOURS` — default 168 (7d), max
  720 (30d), min 1.
- KDF: `KDF_TARGET_ITERATIONS` — default 600000. Legacy vaults on
  100000 iterations migrate on next unlock.

### Trusted device (Layer 3)

- Enforced by `verify_trusted_device`. Bypass list is closed and
  tested (`ROUTES_EXEMPT_FROM_DEVICE_GATE`).
- Env kill-switches:
  ```
  VAULTAI_DEVICE_GATE_ENFORCE=true          # default
  VAULTAI_DEVICE_GATE_DEV_DISABLE=false     # never true in prod
  VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=false  # never true in prod
  ```

### Delete-vault gate (Layer 4)

- Three-step flow: `GET /vault/delete/status` → `POST /vault/delete/request` →
  `POST /vault/delete/confirm`.
- Confirm requires: (a) the exact phrase `DELETE MY VAULT`, (b) a
  valid HMAC challenge from `/request` bound to that vault and
  within the 10-min window, (c) correct PIN.
- Rate-limited per-vault + per-IP; 10 hits/hr by default.
- Emits `delete_vault_requested` and `delete_vault_confirmed`
  security events with the hashed vault id.
- Full sessions purged post-delete via
  `revoke_all_sessions_for_vault`.

### Automatic inactive-unpaid deletion (Layer 4)

- No pending state, no grace period.
- Query: unpaid AND (`last_any_activity_at`,
  `updated_at`, `created_at`) COALESCE'd falls before
  `NOW() - INTERVAL '6 months'`.
- Re-checks BOTH billing AND activity per candidate at delete-time.
- Paid statuses (`active`, `in_grace`, `canceled_pending`) are
  never eligible.
- Emits `inactive_unpaid_deleted` security event.

### Data at rest (Layer 5)

- Vault items and file chunks encrypted client-side under a
  PIN-derived AES-GCM-256 key.
- Everything vault-owned cascades via `ON DELETE CASCADE`. Delete
  service issues a single `DELETE FROM vaults` and lets Postgres
  do the rest.

### Audit (Layer 6)

- `security_event_log` — closed-set reasons/routes; refuses to log
  any field that contains the strings `pin=`, `seed`, `mnemonic`,
  `private key`, `api key`, `bearer `, `password`,
  `encrypted_data`, etc. Every id is pre-hashed via `short_hash`.
- Stripe webhook idempotency via `provider_event_log(source,
  source_event_id)`.
- Deletion tombstones (`vault_deletion_tombstones`) store only
  `deleted_at`, `deletion_reason`, `hashed_vault_id`. No vault
  name, no account id, no wallet address.

## Manual verification checklist

Run these before a production release:

- [ ] `CORS_ALLOWED_ORIGIN_REGEX` set to the real origin regex.
- [ ] `VAULT_SESSION_SECRET` set to a fresh 48+ char value.
- [ ] `VAULTAI_ENV=production` (or equivalent) so HSTS emits.
- [ ] `VAULTAI_DEVICE_GATE_DEV_DISABLE` unset or `false`.
- [ ] `VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST` unset or `false`.
- [ ] `STRIPE_WEBHOOK_SECRET` set; test webhook rejects unsigned.
- [ ] `VAULTAI_RATE_LIMIT_BACKEND=redis` if running >1 instance.
- [ ] `curl -I /auth/me` shows CSP, X-Frame-Options, HSTS.
- [ ] `POST /vault/delete/confirm` with wrong phrase returns 400.
- [ ] `POST /vault/delete/confirm` with wrong PIN returns 401.
- [ ] 6+ wrong PINs against `/verify-pin` triggers 24h vault lock.
- [ ] Full test suite green (see [`../vault_ai_backend/test_security_hardening_2026_07_08.py`](../vault_ai_backend/test_security_hardening_2026_07_08.py)).
