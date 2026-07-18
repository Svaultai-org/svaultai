# VaultAI ZK Privacy Release — Deployment & Rollback Plan

Companion to `ZK_PRIVACY_RUNBOOK.md`. This document covers the
release sequencing, secret handling, verification gates, and
rollback strategy for shipping the zero-knowledge privacy
architecture to production.

## Prerequisites

1. `VAULTAI_OPAQUE_SERVER_SETUP` (deployment secret) minted and
   available in the secret manager. Mint via:

   ```
   docker run --rm --entrypoint python vaultai-backend:latest \
       -m opaque_server_module --print-new-setup
   ```

   The value is the OPAQUE OPRF master secret. If rotated, every
   already-ZK-adopted vault loses login. **Rotation is a whole-
   fleet event.** Treat as immutable.

2. Docker builder machine (Linux) available for image build. This
   is where the pyo3 opaque-ke wheel actually gets compiled. Local
   Windows dev machines cannot build the wheel (WDAC) — Docker or
   WSL is required.

3. Empirical OPAQUE interoperability test result (green) from
   `test_opaque_wire_interop.py` running inside the built Docker
   image or a Linux CI runner with Node installed.

## Deployment Sequence

1. `docker build -t vaultai-backend:<tag> vault_ai_backend/` —
   image build includes:
   - rustup install of Rust 1.97.0 (pinned).
   - maturin build of `vault_ai_backend/opaque_server_crate/` into
     the venv.
   - A smoke-test that calls `vaultai_opaque_server.server_setup_new()`
     and asserts non-empty bytes.
   - If ANY step fails, the image build fails. This is the
     deployment gate.
2. Deploy the new image with **`VAULTAI_OPAQUE_SERVER_SETUP`** set.
   If unset, `/auth/zk-*` returns HTTP 503 (fail closed).
3. `alembic upgrade head` runs migrations `0023_vault_zk_state.py`
   and `0024_vault_metadata_encryption.py`. Both are **additive-only**
   (columns nullable; no data destroyed). Safe to run against the
   currently-serving old process.
4. Deploy the new Flutter web bundle (`flutter build web --release`).
   New assets under `web/assets/opaque/`:
   - `serenity-kit-opaque.esm.js` (~424 KB — vendored @serenity-kit/opaque
     WASM built from Meta's audited opaque-ke).
   - `vaultai-opaque-init.js` (~24 lines glue).
   - `LICENSE-serenity-kit-opaque` + `README-serenity-kit-opaque.md`.
5. Cache-header for the vendored WASM: `Cache-Control: public,
   max-age=31536000, immutable`.
6. Verify a fresh signup → the new Vault Handle (`VLT-XXXX-…`) is
   shown and OPAQUE registration succeeds.

## CSP / Nginx

Current `deploy/nginx/app.svaultai.com.conf` sets **no
Content-Security-Policy header.** WebAssembly compilation will
succeed under a default CSP absence.

If a CSP is introduced later, the vendored WASM requires
`script-src ... 'wasm-unsafe-eval' 'self'`. The bundle uses
`WebAssembly.compile(...)` only — no `eval`, no `Function()`, no
`unsafe-inline` needed for scripts.

## Rollback

- **Backend image rollback**: safe. Every ZK column is nullable;
  the old image ignores them.
- **Frontend bundle rollback**: safe for un-adopted vaults. **NOT
  safe for ZK-adopted vaults** — the old bundle cannot compute
  `wrapped_mvk` and cannot log those users in. If you must roll
  the frontend back, you MUST also roll back a plaintext-emitting
  bundle for legacy vaults only, and warn the ZK-adopted user
  cohort that they must retry after the next fixed release.
- **Migration rollback**: Alembic `downgrade` on 0023/0024
  succeeds against a live DB but any ZK-adopted vault is stranded
  (its columns are dropped). **Do not downgrade past 0023 without a
  fleet-reregister plan.**
- **`VAULTAI_OPAQUE_SERVER_SETUP` rotation**: strand-strand-strand.
  Same result as downgrading past 0023. Don't.

## Product Behaviors Intentionally Reduced for ZK Vaults

Users whose vaults are ZK-adopted see the following changes vs.
un-adopted (legacy) vaults. These are correct-by-design tradeoffs
for privacy, not bugs.

1. **Semantic search over vault content**: currently unavailable
   for ZK vaults. `semantic_embedder.upsert_uploaded_file_inline`
   and `upsert_vault_item_inline` short-circuit for ZK vaults —
   no vectors are indexed, no plaintext content_hash is written,
   and no plaintext text is sent to OpenAI's embeddings API.
   Future: client-finalized semantic flow where the client
   computes `keyed_content_hash` locally and POSTs the ciphertext
   to `/vault/ciphertext/semantic-index`. Until that lands, ZK
   users get filename/service-based search only.
2. **User-text notifications**: ZK vaults get notification rows
   with `kind` populated and `title` / `body` / `metadata` = NULL.
   The UI should show the notification bell with the kind icon +
   a neutral label (e.g. "Storage reminder", "Device change") and
   NOT show blank title/body records. If a producer emits a
   user-derived notification, the readable text is dropped
   server-side; a future client-finalization flow will encrypt
   and POST via `/vault/ciphertext/notifications`.
3. **AI memory saves**: for a ZK vault, `_handle_remember_fact`
   emits a `<<VAULTAI_MEMORY_PROPOSAL>>{json}<<END>>` sentinel in
   the chat reply and does not persist server-side. Until the
   Flutter chat SSE handler wires the client-finalization path,
   ZK users see the "I'll remember that" acknowledgment but the
   memory is not actually saved. The correct privacy tradeoff:
   nothing readable ever hits the DB.
4. **Server-inferred document metadata**: for a ZK vault upload,
   `detected_type` / `detected_service` / `asset_type` are NULL
   at INSERT. Document understanding still runs transiently in
   the request; its outputs are returned to the client for
   encryption (when the client-side finalize path ships).

## Verification Gates

Every item MUST pass before promoting to production:

- [ ] `docker build vaultai-backend:latest` succeeds including the
      OPAQUE smoke test.
- [ ] `pytest -m opaque_interop` passes inside the built image.
- [ ] Full backend pytest passes (currently 6637 passed / 82
      skipped / 0 failed on the deterministic ordering).
- [ ] Flutter analyze passes with no new errors vs baseline.
- [ ] `flutter build web --release` produces a bundle whose
      vendored `serenity-kit-opaque.esm.js` is present under
      `build/web/assets/opaque/`.
- [ ] `VAULTAI_OPAQUE_SERVER_SETUP` value is available in the
      production secret store.
- [ ] alembic migration 0023 and 0024 run cleanly on a
      staging DB.
- [ ] Sanity-check ZK signup + login end-to-end on staging.
- [ ] Sanity-check adoption on a legacy vault against staging.
