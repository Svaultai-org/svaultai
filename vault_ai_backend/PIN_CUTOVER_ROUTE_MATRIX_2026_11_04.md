# SVaultAI PIN cutover route matrix (2026-11-04)

Source baseline: integration commit `365d329` (web `b29bb27` and backend
`4f55a0b8`). This is an implementation inventory, not a deployment claim.

| Feature | Current web request | Existing PIN-free route | Cutover blocker |
| --- | --- | --- | --- |
| Login/unlock | OPAQUE `/auth/zk-login-*` plus plaintext `/auth/login` fallback | OPAQUE is implemented | Default web fallback must be disabled for ZK and unknown names. Keep legacy migration opt-in. |
| Fresh PIN re-entry | `/verify-pin`, delete, device approval, Security Center, wallet flows carry PIN | New `/auth/zk-verify-*` with session-bound, single-use action proof is under development | Each sensitive action must consume the proof on the server; a client-only `verified` boolean is insufficient. |
| New ZK registration | `/auth/zk-register-finalize` supplies a PBKDF2 verifier | Verifier-free mode is under development | Keep KDF salt/iterations for local legacy data migration; gate old clients explicitly. |
| Saved items and crypto records | ZK write/read/delete via `/vault/ciphertext/vault-items`; list always also POSTs raw PIN to `/list-secure-items`; legacy item reads/edits/deletes fall back to PIN routes | Ciphertext CRUD and credential-v2 APIs exist | Migrate three legacy `encrypted_data` rows client-side and remove unconditional raw-PIN list/fallback. |
| Files | Upload, list, download, import, chunk finalize, delete, stats, related-file search carry PIN; ciphertext filename metadata does not remove it | Backend `/vault/file-v2` manifest/chunk/read/delete exists behind flags | No frontend file-v2 client. Three production files are server-key inline ciphertext; migrate their content client-side. |
| Memory | Older `/memory/*` helpers carry PIN; modern vault-AI-memory CRUD is ciphertext | `/vault/ciphertext/vault-ai-memory` exists and is used | Chat save/search and extraction pipelines still use the server PIN-derived key. |
| Chat and deep answer | `/chat` requires PIN to derive server key, decrypt prompt, run tools, and encrypt SSE; deep-answer and related-file routes also carry PIN | No complete PIN-free chat route | Redesign chat protocol and tool/storage boundary; preserve Files/Memory/chat behavior under tests. |
| Beneficiary/inheritance | Create/link/list/transfer/claim/delete carry PIN and wrap a PIN-derived key | Ciphertext labels/credential packages exist for parts of the flow | Rewrite pairing key wrapping and action gates; production currently has zero links. |
| Device, Security Center, KDF rotation | PIN-bearing routes | No complete ZK counterpart | Wire OPAQUE proof for high-risk actions; derive local crypto changes on client. |

## Aggregate-only migration facts

Production has four ZK vaults, zero legacy-only vaults, and four legacy PIN
verifiers. Six saved-item rows split into three legacy server-key rows and
three ciphertext rows. Three files are inline server-key ciphertext totaling
2,477,819 nominal bytes (largest 2,285,665); all have ciphertext filenames.
One vault-AI-memory row is ciphertext. There are no chunked files,
beneficiary links, wallet-v2 records, or vault crypto envelopes. These are
counts only; no names, content, keys, or PINs were read.

## Lossless staged cutover

1. Ship server-compatible OPAQUE auth/re-entry and default-disabled raw login
   for web, preserving explicitly opt-in legacy migration and older mobile
   compatibility until platform releases are ready.
2. Add paginated, vault-scoped, bearer-authenticated export of *existing
   ciphertext bytes*. The server never decrypts or logs them. The unlocked
   client derives the old key locally, decrypts each legacy item/file locally,
   re-encrypts under the MVK, writes a v2 envelope, reads it back, verifies
   digest/content, then atomically marks the legacy row migrated. Retry by
   stable row ID and operation ID; never delete the old row before verification.
3. Wire file-v2 and credential/ciphertext v2 into web/iOS/Android; migrate all
   remaining rows and test fresh unlock, Files, Memory, chat, search, imports,
   deletion, themes, refresh, and logout on disposable vaults. Reconcile row
   counts and per-vault completion without inspecting private content.
4. Redesign server chat so the PIN and PIN-derived key never enter routine
   API requests. Preserve current feature behavior with client-controlled
   disclosure and response encryption; otherwise mark chat unavailable under
   the new privacy contract rather than silently falling back.
5. Only after every relevant route and old-client policy is settled, clear
   legacy verifiers for ZK rows and reject raw-PIN requests for those rows.
   Keep rollback compatible with data already written under v2. Run the
   failing release-gate test before any deployment claim.

Current gate: `test_zk_raw_pin_release_gate_2026_11_04.py` finds 50 direct
raw-PIN request construction sites outside opt-in legacy login on the
live-equivalent web code. The test asserts zero, not a fixed historical count.
