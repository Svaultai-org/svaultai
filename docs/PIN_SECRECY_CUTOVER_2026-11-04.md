# PIN secrecy cutover gate — 4 November 2026

## Release invariant

For a ZK vault, no browser or native client request may carry the raw PIN or a reusable PIN-derived decryption key. The server must not persist a verifier or legacy ciphertext that permits offline PIN guessing from a copied database. OPAQUE remains the authentication mechanism; the client holds the MVK and domain subkeys. A release must preserve existing vault content and active features.

## Current live shape (aggregate only)

- Web: `b29bb27a`; backend: `4f55a0b`; both descend from `origin/main=6fecfb3` and diverge. Integration merge `365d329` has the exact live web tree and exact live backend tree.
- Vaults: 4 total, all 4 ZK, 0 legacy-only, all 4 with a nonempty legacy PIN verifier.
- `vault_items`: 6 rows; 3 have legacy `encrypted_data`, 3 have V2 `payload_ciphertext`.
- `uploaded_files`: 3 inline rows with `encrypted_file_data` and ciphertext names; 0 chunked/V2 files. Aggregate file size 2,477,819 bytes, largest 2,285,665 bytes.
- `vault_ai_memory`: 1 ciphertext row. Beneficiary links and wallet V2 rows: 0.

These counts were read without names, PINs, content, ciphertext, or row identifiers. They can change; recheck before cutover.

## Required stages

1. Ship client/controller cleanup and OPAQUE re-verification with a short-lived session-bound proof. Existing `/auth/login` fallback must be absent for ZK and unknown-name sign-in. Keep the legacy route for a separately verified migration path only.
2. Add a recent-OPAQUE-protected export of *encrypted* legacy items/files, scoped to the authenticated vault. The unlocked client decrypts with its existing local PIN-derived key, re-encrypts under MVK-derived domain keys, writes through V2 endpoints, and verifies round-trip. Never send the raw PIN or legacy decryption key to the server. Migration must be resumable and idempotent; preserve old rows until verified.
3. Migrate chat, file AI, secure-item list/read, beneficiary, device, import/delete, deep-answer, and other active PIN-dependent operations to session/proof authorization and client-held content keys. A route census finds at least 47 PIN-dependent backend paths and 49 PIN-bearing client request constructors. A feature-by-feature network test must show no raw PIN or reusable PIN-derived key after unlock.
4. Release updated web, iOS, and Android clients with a minimum-version gate for ZK flows. Before rejecting old clients, verify approved store versions are available to users. An old client's verifier-bearing ZK signup must return update-required; it must not create a vault that the old client cannot use.
5. Enable verifier-free ZK registration only after stage 3 and client availability. Then, for each existing ZK vault, require migration verification for every legacy item/file before clearing `pin_verifier`. Merely blanking the verifier while PIN-derived AES-GCM ciphertext remains still permits offline guesses using the ciphertext authentication tag.
6. After all records and clients pass, block raw-PIN ZK routes at the backend; confirm no production request carries a PIN, no ZK row has a testable verifier or PIN-derived ciphertext, and legacy-only accounts have an explicit supported migration path. Keep backups and a tested rollback of code/configuration; never restore a cleared verifier as a shortcut.

## Go/no-go evidence

- Synthetic full-stack tests cover new ZK signup, valid/wrong PIN, refresh unlock, chat, files, memory, beneficiary, wallet-sensitive actions, logout, and old-client rejection. They inspect network request shapes and backend DB state without printing secrets.
- The current real vault data remains accessible on a separate device during migration; client round-trip checks pass before old rows are retired.
- A read-only production aggregate confirms zero remaining ZK verifiers and zero legacy PIN-derived ciphertext, with no user content examined.
- Web build and both native builds use the same reviewed shared-source commit, and backend build matches its reviewed contract. Existing billing, session, and release-update gates pass.

The original integration baseline merge was not a deployable cutover. Rollout flags must remain off until the gates above pass.

## 5 November progress (UTC)

This is a security work log, not a declaration that the cutover passed.

- Live web `1fd7e5b` skips the legacy raw-PIN KDF-rotation call after an OPAQUE unlock. Its default build also blocks the ambiguous legacy-login fallback for ZK/unknown names, clears submitted PIN form controllers, and redacts release diagnostics.
- Live backend image `vaultai-backend:trust-inheritance-4e432e7` binds trusted-device checks to the session and requires them on V2 content, inheritance, and ZK adoption routes. Its runtime has `VAULTAI_ZK_LEGACY_LOGIN_DISABLED=true`, which rejects plaintext legacy login for ZK rows. Public health and web release requests returned HTTP 200 after both live changes.
- The local integration branch contains opt-in OPAQUE proof routes, encrypted legacy export and stage/readback, private V2 chat/file/saved-item paths, verifier-free registration, and an old-mobile reader gate. No new client, V2, migration, or verifier-free flag is enabled in production.
- Read-only live aggregates: 4 ZK vaults still have a PIN verifier; 3 legacy item blobs and 3 legacy inline file blobs remain. The one AI memory row is a client-MVK V2 envelope. Other inspected PIN-key content tables have no live rows. These are aggregate checks, not inspection of private content.
- Local web release build, iOS simulator build, and Android debug APK compiled. Xcode 27 requires the iOS project to target iOS 15 or newer; the integration branch has that packaging change. Neither mobile store has received this branch.
- **Cutover remains blocked** by PIN-bearing chat/file/deep-answer/beneficiary paths, production owner-side re-encryption and readback, old mobile versions, and current store availability. Do not clear verifier or legacy ciphertext, turn on verifier-free signup, or claim PIN secrecy from the live partial hotfixes.
