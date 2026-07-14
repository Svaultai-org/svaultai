# VaultAI Zero-Knowledge Privacy — Deployment Runbook

Authoritative deployment reference for the OPAQUE-based zero-knowledge
auth model. Complements `DEPLOYMENT_RUNBOOK.md` (existing ops) and
`BACKUP_AND_RECOVERY.md` (which is being updated separately to drop
stale `accounts.email` / `vault_names` references).

## 1. What ships in the ZK model

**Backend**
- Rust crate `vault_ai_backend/opaque_server_crate/` — pyo3 wrapper
  over Meta's audited RFC 9807 `opaque-ke` (Ristretto255-SHA512-
  Argon2id + TripleDH).
- Python wrapper `vault_ai_backend/opaque_server_module.py` — loads
  the wheel with a graceful-fallback diagnostic and reads the
  long-term server setup from an env var.
- Vault Handle model `vault_ai_backend/vault_handle.py` — 15-byte
  Crockford base32 opaque login identifier.
- ZK auth routes `vault_ai_backend/routes/auth_zk_routes.py`.
- Metadata migration routes
  `vault_ai_backend/routes/vault_metadata_migration_routes.py` (per-
  vault lazy backfill; no admin path).
- Migrations `0023_vault_zk_state.py` (auth) and
  `0024_vault_metadata_encryption.py` (content ciphertext columns).

**Frontend (Web only)**
- Vendored `@serenity-kit/opaque@1.1.0` under
  `vault_ai_frontend/web/assets/opaque/`. Same upstream Rust crate
  as the backend; wire-compat guaranteed.
- `vault_ai_frontend/lib/services/vault_handle.dart` — Dart mirror of
  the Python handle format.
- `vault_ai_frontend/lib/services/opaque_client.dart` — Dart
  `dart:js_interop` wrapper around the WASM bundle.
- `vault_ai_frontend/lib/services/zk_auth_service.dart` — signup /
  login / adopt orchestration.
- `vault_ai_frontend/lib/services/vault_key_hierarchy.dart` — HKDF
  subkey derivations + AES-GCM wrap/unwrap helpers.
- `vault_ai_frontend/lib/services/legacy_adoption.dart` — transparent
  post-login adoption helper.

## 2. Required environment variables

**New — mandatory before turning ZK auth on**

- `VAULTAI_OPAQUE_SERVER_SETUP`
  Base64url-encoded ServerSetup bytes (the OPAQUE OPRF master
  secret). Handle as a deployment-tier secret. If unset, every
  `/auth/zk-*` route returns HTTP 503. If ever rotated, every
  existing ZK-adopted vault becomes unable to log in — so rotation
  is a whole-fleet-reregister event. Treat as immutable.

  Mint once from inside the built image:
  ```
  docker run --rm --entrypoint python vaultai-backend:latest \
      -m opaque_server_module --print-new-setup
  ```
  Store the emitted string in your secret manager and inject via
  the same channel as `VAULT_SESSION_SECRET`.

**Optional**
- `VAULTAI_INTEROP_NODE_MODULES` — points the wire-interop test at a
  directory containing `node_modules/@serenity-kit/opaque`. Only
  relevant when running `pytest -m opaque_interop`.

**Unchanged**
- `VAULT_SESSION_SECRET`, `DATABASE_URL`, `OPENAI_API_KEY`,
  `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `CORS_ALLOWED_ORIGIN_REGEX`,
  `VAULTAI_RATE_LIMIT_BACKEND`, `VAULTAI_RATE_LIMIT_REDIS_URL`,
  `VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN`, `VAULTAI_BILLING_HEALTH_ADMIN_TOKEN`.

## 3. Backend redeploy requirements

1. `docker build` picks up the updated Dockerfile, which now:
   - Installs Rust 1.97.0 in the builder stage via rustup (minimal
     profile).
   - Installs `maturin>=1.14` into the venv.
   - Compiles the `opaque_server_crate` and pip-installs the
     resulting wheel.
   - Runs a smoke test that calls
     `vaultai_opaque_server.server_setup_new()` and asserts
     non-empty output.
   Any failure at any of these steps fails the image build.
2. Image build time increases by ~5–10 minutes (Rust dep compile).
3. Runtime layer gains one native `.so` under `/opt/venv`.
4. `alembic upgrade head` must run **after** the image with the new
   migrations is deployed. Migrations 0023 and 0024 are additive-
   only. They can be applied while the old process is still
   serving; the new process picks up the columns on next start.
5. After first deploy, mint and inject `VAULTAI_OPAQUE_SERVER_SETUP`
   (see §2) before enabling ZK auth in the frontend bundle.

## 4. Frontend redeploy requirements

1. `vault_ai_frontend/scripts/build-web-release.ps1` (or `.sh`) is
   unchanged. `flutter build web` copies the new
   `web/assets/opaque/**` into `build/web/assets/opaque/**` verbatim.
2. **CSP:** the vendored bundle instantiates WebAssembly via
   `WebAssembly.compile(...)` with no `eval` and no `Function()`. If
   the site is served under a Content-Security-Policy header, add
   `wasm-unsafe-eval` to the `script-src` directive. No other CSP
   changes are needed. The base64-embedded WASM does not require
   `unsafe-inline` for scripts.
3. **Nginx:** serve `/assets/opaque/*.js` with
   `Content-Type: application/javascript` and
   `Cache-Control: public, max-age=31536000, immutable`. The
   vendored bundle's URL is version-pinned by content addressing.
4. Bundle size: `serenity-kit-opaque.esm.js` is ~424 KB
   uncompressed, ~150 KB gzipped. Not on the first-paint critical
   path (module script is deferred by default).
5. First-visit users on cold caches will download ~150 KB extra;
   subsequent visits are cache-hit.

## 5. Migrations 0023 and 0024

Both are **additive-only** and safe to run on production while the
old process is still serving traffic.

- `0023_vault_zk_state.py`
  - Adds nullable columns on `vaults`: `vault_handle`,
    `opaque_registration_record`, `wrapped_mvk`, `wrapped_sk_vault`,
    `pk_vault_public`, `display_name_ciphertext`,
    `legacy_vault_name_cleared_at`, `wrapped_mvk_by_recovery`,
    `opaque_recovery_record`.
  - Adds partial unique index on `vault_handle`.
  - Adds a consistency check across the ZK column trio.
  - Creates `vault_zk_login_slots` (transient login state, 90-second
    TTL, single-use).

- `0024_vault_metadata_encryption.py`
  - Adds nullable ciphertext / keyed-lookup-hash columns on
    `uploaded_files`, `vault_items`, `vault_document_metadata`,
    `vault_ai_memory` (with unique index on non-superseded
    `memory_lookup_hash`), `semantic_index`, `notifications`,
    `beneficiary_links`, `crypto_*_drafts`, `crypto_*_wallet_locks`.
  - Best-effort adds columns to `crypto_*_outgoing_history` where
    the table exists.
  - Creates `vault_metadata_migration_state` (per-vault cursor
    table).

Downgrades exist and restore the schema. **Downgrade does NOT
recover any dropped plaintext** (a follow-up Phase 4 migration will
drop legacy plaintext columns once fleet adoption confirms 100%
coverage; this turn does not include Phase 4).

## 6. Rollback constraints

- **Rolling back the backend image** to a pre-ZK build is safe:
  the ZK columns are nullable, and the old code paths ignore them.
- **Rolling back the frontend** to a pre-ZK build is safe: the
  frontend serves the legacy `/auth/login` and `/auth/signup`
  routes which remain functional. Users who have not adopted
  continue to use them. Users who HAVE adopted see the ZK routes
  fail because the legacy client cannot compute wrapped_mvk — they
  cannot log in from the old bundle. This is a one-way ratchet;
  once a vault is ZK, it must use the ZK-capable bundle.
- **Rolling back a migration** (0023 or 0024) via alembic downgrade
  drops the ZK columns; any adopted vault is now unable to log in
  via either path. **Do not downgrade past 0023 without a full
  fleet reregister plan.**

## 7. Legacy vault adoption

- Existing users' vaults are **untouched** at migration time. Their
  data remains encrypted with the same PBKDF2-derived vault key.
- On next successful legacy unlock, the frontend calls
  `tryAdoptLegacyVault` which:
  1. Checks `/auth/me` for existing ZK state (no-op if adopted).
  2. Generates a fresh Vault Handle.
  3. Runs OPAQUE registration with the user's existing PIN.
  4. **Adopts the legacy PBKDF2-derived key as MVK** — zero data
     re-encryption, zero user-visible data movement.
  5. Wraps MVK under the new KEK (from OPAQUE export_key).
  6. Uploads via `/auth/zk-adopt`.
  7. The server atomically writes the ZK columns and clears
     `pin_salt` / `pin_verifier` (i.e. blanks them; the columns
     themselves are dropped in Phase 4).
  8. The frontend caches the new Vault Handle in
     `shared_preferences` for trusted-device autofill.
- If any step fails, the user's session remains valid via legacy;
  the adoption retries on the next unlock.
- **No user data is deleted** by adoption. Zero file loss, zero
  wallet loss, zero subscription disturbance.
- Users who never unlock during the migration window remain on the
  legacy path until either (a) they unlock and adopt, or (b) the
  auto-deletion rule removes them after 6 months of inactivity on
  the free tier.

## 8. What the server observes after adoption

Per adopted vault:
- Opaque `vault_id` (random UUID) — unchanged from today.
- `vault_handle` — 15 random bytes. Not derived from any user
  input. Not enumerable via DB dump.
- `opaque_registration_record` — RFC 9807 opaque bytes.
- `wrapped_mvk`, `wrapped_sk_vault` — AES-GCM ciphertext under a
  key the server does not possess.
- `pk_vault_public` — X25519 public point (public by design).
- `display_name_ciphertext` — AES-GCM ciphertext.
- Account link, subscription state, storage bytes, activity
  timestamps — unchanged operational state.

Per session:
- `token_id`, `vault_id`, `device_id`, timestamps — unchanged.

Per active OPAQUE login handshake:
- `vault_zk_login_slots.server_state` — transient, 90-second TTL,
  deleted on finalize. No lasting exposure.

Post-Phase-3 (client-side write-path encryption not yet fully
wired), the following remain visible as plaintext until each row is
lazily backfilled on next unlock:
- `uploaded_files`: `file_name`, `saved_name`, `content_type`,
  `detected_type`, `detected_service`, `asset_type`.
- `vault_items`: `item_type`, `service`, JSON body inside
  `encrypted_data`.
- `vault_document_metadata.metadata_json`.
- `vault_ai_memory.memory_key`, `memory_value`,
  `memory_normalized_key`.
- `notifications.title`, `body`, `metadata`.
- Wallet public addresses and destination addresses (drafts +
  history).

These evaporate on a per-vault, per-table basis as the client hits
`/vault/metadata-migration/next-batch` after unlock.

## 9. Admin surfaces — enumerated and gated

There is **no** admin route that:
- Lists users, searches users, or returns a single user's row.
- Suspends, deletes, revokes, or resets any user.
- Inspects any vault's metadata or content.
- Decrypts any vault's data.
- Returns any user's session tokens.

Existing admin surfaces are limited to infra health probes:
- `/billing/admin/health` (Stripe RPC health, token-gated).
- `/crypto/wallet/health`, `/crypto/{mainnet,solana,tron}/admin/health`
  (crypto RPC health probes, token-gated).

Enforced by test `test_no_admin_endpoint_scan.py`.

## 10. Emergency: what to do if OPAQUE breaks

If a bug is found in the ZK path:
1. **Do NOT roll back migration 0023** — that would strand ZK-adopted
   users. Roll forward with a fix.
2. **Do NOT unset `VAULTAI_OPAQUE_SERVER_SETUP`** — 503 storm for
   every ZK-adopted user's login.
3. Feature-flag: revert the frontend to send legacy `/auth/login`
   only. Users who have not yet adopted remain on legacy; users
   who have adopted are unable to log in until the fix ships. The
   underlying MVK is unchanged in wrapped_mvk; a fixed bundle
   restores access.
4. Contact route: no support endpoint exists to recover a user's
   vault — that is architectural, not a bug.

## 11. AI processing under ZK

Unchanged: OCR, document understanding, semantic embeddings, chat,
and AI memory operations remain permitted when the authenticated
user is unlocked and explicitly asks for them. The backend receives
plaintext content only for the lifetime of that user-authorized
request, never persists that plaintext, never logs it, and never
exposes it to any admin surface. The server holds no persistent
capability to decrypt any stored content; it only sees decrypted
bytes during a live request the user initiated.

`VAULTAI_AI_PROCESSING_ENABLED=false` in env disables OCR/AI proxies
entirely; the app degrades gracefully to a cache-only mode.

## 12. Wire-interop test

`vault_ai_backend/test_opaque_wire_interop.py` runs a full OPAQUE
round-trip between our pyo3 wrapper (server role) and Node's
`@serenity-kit/opaque` (client role) and asserts identical
`session_key` and `export_key`.

Preconditions to run:
1. `vaultai_opaque_server` wheel installed (present in the Docker
   image; NOT present on Windows dev boxes where WDAC blocks Rust
   build-script execution).
2. Node on PATH.
3. `VAULTAI_INTEROP_NODE_MODULES` pointing at a dir with
   `node_modules/@serenity-kit/opaque`.

In the current Windows dev environment the test auto-skips with a
clear diagnostic. In the Docker builder stage (or any Linux CI with
Rust + Node) it runs empirically.

## 13. Files ledger for the ZK redesign

New files (Phase 1 + Phase 2 + Phase 3 groundwork + this turn):

Backend (Python):
- `opaque_server_crate/Cargo.toml`, `pyproject.toml`, `src/lib.rs`
- `opaque_server_module.py`
- `vault_handle.py`
- `migrations/versions/0023_vault_zk_state.py`
- `migrations/versions/0024_vault_metadata_encryption.py`
- `routes/auth_zk_routes.py`
- `routes/vault_metadata_migration_routes.py`
- `test_vault_handle_zk.py`
- `test_no_admin_endpoint_scan.py`
- `test_opaque_wire_interop.py`
- `ZK_PRIVACY_RUNBOOK.md` (this file)

Frontend (Dart/JS):
- `web/assets/opaque/serenity-kit-opaque.esm.js` (vendored)
- `web/assets/opaque/serenity-kit-opaque.d.ts` (vendored typings)
- `web/assets/opaque/LICENSE-serenity-kit-opaque`
- `web/assets/opaque/README-serenity-kit-opaque.md`
- `web/assets/opaque/vaultai-opaque-init.js` (24-line loader)
- `lib/services/vault_handle.dart`
- `lib/services/opaque_client.dart`
- `lib/services/opaque_client_stub.dart`
- `lib/services/zk_auth_service.dart`
- `lib/services/vault_key_hierarchy.dart`
- `lib/services/legacy_adoption.dart`
- `test/vault_handle_zk_test.dart`
- `test/x25519_seed_determinism_test.dart`

Modified files:
- `vault_ai_backend/Dockerfile` — added Rust + maturin + wheel build.
- `vault_ai_backend/main.py` — wired `auth_zk_router` +
  `vault_metadata_migration_router`.
- `vault_ai_backend/conftest.py` — registered `opaque_interop`
  marker.
- `vault_ai_frontend/web/index.html` — added the OPAQUE init loader
  module script.
