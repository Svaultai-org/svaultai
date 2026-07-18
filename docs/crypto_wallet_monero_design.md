# Crypto Wallet Engine — Monero / XMR Architecture Design

Status: **DRAFT design slice only. No XMR runtime code ships in this slice.**
Date: 2026-07-02
Owner: VaultAI Crypto Wallet Engine

This document sets the direction for future Monero support inside VaultAI. It does **not** implement any XMR functionality. The XMR card in the product remains `privacy_wallet_later` until a later phase.

---

## 1. Product position

VaultAI is a **digital vault**, not an exchange. Crypto Vault is one protected category inside VaultAI. There is no buy, sell, swap, trade, stake, or bridge — not for ETH, not for USDT ERC20/TRC20, not for SOL, and never for XMR.

Monero (XMR) is a **privacy-wallet-later** asset. It sits in the same product surface as any other supported asset — a card in the Crypto Vault dashboard — but the Monero card is intentionally held back from the "live" experience until the design questions in this document are answered.

The Monero integration must prioritize, in this order:

1. **Non-custodial control.** VaultAI never holds spend authority. Ever.
2. **Privacy.** Monero exists to preserve on-chain privacy. A VaultAI integration that undermines that value proposition would be worse than no integration at all.
3. **Honest state.** No fake balance, no fake address, no fake activity, no fake sync progress, no fake confirmation, no fake success.
4. **Convenience.** Only after the first three are satisfied.

Every design decision below is filtered through those priorities.

---

## 2. Architecture options

This section compares three architectures. Each is evaluated against six dimensions: security model, privacy model, implementation difficulty, user experience, backend custody risk, and VaultAI fit.

### Option A — Client-side Monero wallet + scanner

The Flutter client generates all keys locally, encrypts the wallet secret under the user's vault key, and stores only ciphertext on the backend. The client is responsible for scanning the chain — either directly against a public/self-hosted Monero daemon, or via a light-wallet server (LWS) style API using the user's private view key held on-device.

- **Security model.** Spend key never leaves the device. View key never leaves the device (or, in the LWS variant, only leaves under a user-selected LWS host — never VaultAI's own backend). VaultAI backend has no ability to observe balance, addresses, or transactions.
- **Privacy model.** Strongest. Backend sees only opaque ciphertext blobs. If the client scans against a trusted daemon (self-hosted or a public node the user chose), no third party correlates VaultAI users with Monero addresses.
- **Implementation difficulty.** Highest. Flutter has no first-class Monero library. Options are (a) FFI bindings into `monero-serai` (Rust) or `wallet2` (C++ from monero-project), or (b) a pure-Dart implementation of ed25519 + BulletProofs+ + Triptych verification (out of scope), or (c) use a light-wallet-server protocol like Cake/MyMonero-style where the client sends the view key to an LWS. Sync itself is expensive: even with LWS, initial scan can be minutes to hours; on cold daemon it is much longer.
- **User experience.** Restore-height selection matters — a cold restore of a wallet with an early restore height can burn phones and batteries. Wallet-sync UX needs a genuine progress bar backed by real block heights. Balances stay `syncing` for a while, honestly.
- **Backend custody risk.** Near zero. Backend cannot observe, cannot spend, cannot even confirm the wallet is used.
- **VaultAI fit.** Highest.

### Option B — Backend view-only scanner (opt-in)

Client generates all keys, keeps the spend key on-device (encrypted, never uploaded), and *voluntarily* uploads the private view key (also encrypted at rest, decrypted only inside a hardened scanner process) so the backend can scan the chain and surface incoming transactions and balance.

- **Security model.** Spend key never leaves the device — VaultAI cannot spend. But the backend holds spend-observability: the view key allows the backend to see every incoming transaction to the wallet, its amounts, and the outputs the wallet owns.
- **Privacy model.** Weaker than A. VaultAI now has a data class it never wanted: on-chain financial observability of specific users. This is a *significant* privacy regression from what Monero users expect.
- **Implementation difficulty.** Medium. Backend can run monero-project `wallet2` in view-only mode against a Monero daemon. The FFI/binary risk shifts server-side (where we control the toolchain).
- **User experience.** Great — balance and activity load quickly, sync is opaque to the user, wallet feels "instant" after restore.
- **Backend custody risk.** Zero for spend. Non-zero for observation: a backend compromise leaks transaction history of every opt-in Monero user to whoever breaches the box.
- **VaultAI fit.** Only acceptable behind a **hard opt-in** with an explicit, plain-language privacy warning, an easy delete path, and an architecture where the view-key can be revoked and the scanning data purged. Even then, this is a real product concession.

### Option C — External wallet-connect / watch-only import

VaultAI stores only what the user pastes in: a Monero primary address (or subaddress), an optional label, and metadata. All wallet operations happen in an external Monero wallet the user already runs (Feather, Cake, monero-wallet-cli, Ledger + Feather). VaultAI at most computes a QR code from the address and remembers the label.

- **Security model.** VaultAI has no keys of any kind. No spend, no view, no reveal.
- **Privacy model.** Excellent — VaultAI cannot observe anything on-chain.
- **Implementation difficulty.** Trivial (couple hundred lines).
- **User experience.** Weak. Users must run a second app for anything beyond "here is my address." No balance, no activity, no send — VaultAI becomes a labeled address book for Monero.
- **Backend custody risk.** Zero.
- **VaultAI fit.** Fits as a *floor* — a placeholder we could ship in a week — but does not match the product bar VaultAI has set for ETH/USDT/SOL/TRON. Users would experience Monero as second-class inside the Vault.

### Comparison summary

| Dimension | A: client-side scanner | B: backend view-only | C: watch-only import |
|---|---|---|---|
| Spend authority on backend | never | never | never |
| Observation on backend | none | on opt-in | none |
| Implementation effort | high | medium | low |
| Time-to-first-balance | slow (sync) | fast | none |
| Cold-restore cost | on-device | on-server | n/a |
| Privacy regression risk | minimal | material | none |
| Matches ETH/SOL/TRON product bar | yes | yes | no |
| Recoverable if we change our minds later | yes | requires delete flow | yes |

---

## 3. Recommended path

**Recommended: Option A (client-side wallet + client-side scanner).** Option B is available as a *user-elected fallback*, not the default, and only after the client-side path is shipped in some form.

The reasoning:

- Monero users choose Monero specifically because the tool doesn't give observability to third parties. A VaultAI product that quietly makes an exception here — even for "convenience" — betrays that choice.
- ETH, USDT, SOL, and TRON support in VaultAI is fully non-custodial today. Adding an *observationally custodial* asset next to those would be a regression of the product's core claim.
- The client-side scan path is difficult, but the difficulty is one-time engineering, not a permanent product cost.

If backend view-only scanning is ever considered as a fallback, the following constraints are **non-negotiable**:

1. **Explicit user opt-in.** Not a default. Not buried. A dedicated screen explains, in one paragraph a non-technical user can understand, exactly what the backend will see (incoming amounts, wallet addresses, timing) and what it will *not* see (spend authority, outgoing spending intent).
2. **Encrypted at rest.** The view key is stored encrypted under a server-held KMS-managed key, decrypted only inside the scanner process, never logged, never returned to any other route.
3. **Never the spend key.** Under no circumstances does the backend accept a private spend key, a mnemonic/seed phrase, a wallet password, or any material from which a spend key can be derived.
4. **Delete path.** A single user action ("stop backend scanning") deletes the encrypted view key and all cached scanning data for that wallet.
5. **No raw-address / raw-tx logs.** Logs use closed-set labels and short prefixes. Never a full XMR address, never a full transaction id, never an amount.
6. **Region-selectable.** The scanner can run in the same region as the user's VaultAI data. The user is told which region the scan runs in.
7. **Kill switch.** A single feature flag (`VAULTAI_CRYPTO_XMR_BACKEND_SCAN_ENABLED=false`) disables the entire backend-scan code path for the deployment.

The initial rollout of XMR should ship without backend view-only scanning. That option is opt-in in a later phase or not at all.

### What about hybrid?

There is a workable hybrid where the client owns the view key and periodically hands it to a short-lived server-side scan job whose ciphertext + result is returned to the client and then wiped server-side. This is discussed as future work — it is not the recommendation for phase 1 or phase 2.

---

## 4. Monero phased roadmap

Each phase must land green regressions before the next begins. The phases below are named to match the phrasing used elsewhere in the codebase (`kCryptoWalletEngineFutureStateLabel['XMR']` is already `Privacy wallet later`).

### Phase 1 — Design + UI placeholder *(this slice)*

- This document exists at [docs/crypto_wallet_monero_design.md](../docs/crypto_wallet_monero_design.md).
- The XMR card in the Crypto Vault dashboard remains `privacy_wallet_later`. No balance, no address, no receive button, no send button surface real functionality.
- Copy explains why Monero takes longer. See section 8.
- No feature flag is added yet — `VAULTAI_CRYPTO_XMR_ENABLED` is not implemented; XMR is a compile-time placeholder.
- Tests remain unchanged.

### Phase 2 — XMR receive foundation

- Add `VAULTAI_CRYPTO_XMR_ENABLED=false` default. When true, XMR card becomes a receive-only "wallet exists" experience.
- Client-side wallet generation (ed25519 spend + view keypair, primary address, primary subaddress 0/0). See section 5 for the data model, section 6 for the routes.
- Client encrypts the wallet secret under the vault key. Backend receives ciphertext only.
- Backend stores `publicAddress`, `restoreHeight`, `encryptedWalletSecret`, `keyOrigin: generated_client_side`, `signingMode: client_side`, `scannerMode: none`, `backupStatus: encrypted_backup_saved`. No plaintext key material of any kind.
- Receive route returns the primary address and QR payload. No balance route yet. No activity route yet.
- Copy: "Only send Monero (XMR) to this address." + "Balance and activity are not connected yet — this wallet ships in later phases."

### Phase 3 — XMR balance/activity scanner

Two decision points for this phase:

- **Which scanner architecture?** Default is Option A (client-side sync via a user-selected daemon). Option B (opt-in backend view-only) may be added *after* phase 3 ships without it, if user demand warrants.
- **Which library on the client?** Options include FFI into monero-serai (Rust), FFI into wallet2 (C++), or a light-wallet-server proxy. Each has trade-offs; the choice is a follow-up implementation slice.

Whatever is chosen must:

- Distinguish **locked balance** from **unlocked balance**. Show both, labeled correctly.
- Show **confirmations** on incoming transactions, real numbers only.
- Show a **sync state** with an honest label: `syncing` with block height, `synced`, or `unavailable`. Never fake "up to date."
- Never render an amount, direction, or txid that did not come from a real chain read.

### Phase 4 — XMR send safety

- Local signing only. The private spend key never leaves the device.
- Fee estimation must be real (from the daemon) — presented as `estimated network fee` if the exact value is not yet known, never as an exact number when it is not.
- Support the "no payment ID needed for subaddresses" flow; only allow legacy integrated addresses with an explicit warning.
- Review + PIN + local sign + backend broadcasts signed transaction only. Same shape as the Solana and TRON send slices.
- Backend never signs, never decrypts, never reads the spend key.
- No fake tx id. No fake confirmation. The submitted screen shows the real txid returned by the daemon.

---

## 5. Data model proposal

For future implementation, extend `crypto_wallet_account_v1` for XMR with the following fields.

```json
{
  "schema": "crypto_wallet_account_v1",
  "asset": "XMR",
  "network": "monero_mainnet",
  "networkLabel": "Monero",
  "walletLabel": "VaultAI XMR wallet",
  "publicAddress": "<XMR primary address, 95 chars, base58>",
  "restoreHeight": 3220000,
  "encryptedWalletSecret": "<ciphertext, opaque to backend>",
  "keyOrigin": "generated_client_side",
  "signingMode": "client_side",
  "scannerMode": "none",
  "backupStatus": "encrypted_backup_saved"
}
```

- `scannerMode` closed set: `"none" | "client_side" | "backend_view_only_opt_in"`. Phase 2 stores only `"none"`. Phase 3 stores `"client_side"` by default; `"backend_view_only_opt_in"` never becomes the default.
- `restoreHeight` is a block height (integer). Setting it correctly at creation time is critical — a wrong (too low) restore height forces a slow full scan; a wrong (too high) restore height loses transactions. The client picks it at generation time using the current chain tip minus a small buffer (e.g., tip − 500).
- `encryptedWalletSecret` is the client-encrypted blob and MUST contain the private spend key, private view key, and any client-only metadata the wallet needs to rebuild itself. Backend never decrypts it.

**The following are NEVER stored on the backend, encrypted or otherwise:**

- Mnemonic phrase / seed
- Private spend key (plaintext)
- Private view key (plaintext) — see section 3 for the opt-in backend-scan exception
- Wallet password
- Any password derived from PIN
- Restore-height *offset* that could de-anonymize the user's wallet history (the number is fine; a full mnemonic derivation trace is not)

The client-encrypted `encryptedWalletSecret` may internally contain the private spend and view keys — that's fine, because from the backend's perspective it's an opaque ciphertext blob.

### Pydantic constraints (future)

The XMR create route must apply the existing `rejects_plaintext_secret` guard from [crypto_wallet_schemas.py](../vault_ai_backend/crypto_wallet_schemas.py), which already refuses field names like `privateKey`, `spendKey`, `viewKey`, `seedPhrase`, `mnemonic`, `recoveryPhrase`, `wif`, `xprv`. Extend the blocklist for XMR-specific aliases:

- `spend_key`, `spendKey`, `xmrSpendKey`, `moneroSpendKey`
- `view_key`, `viewKey`, `xmrViewKey`, `moneroViewKey`
- `spendable_key` (already blocked)
- `seed25`, `polyseed`, `moneroSeed`

Add these to `PLAINTEXT_KEY_FIELD_NAMES` and `PLAINTEXT_KEY_SUBSTRING_MARKERS` in phase 2.

---

## 6. Backend route proposal

For future implementation. In this slice, none of these routes exist as real handlers — any XMR path returns `xmr_not_enabled` / `xmr_privacy_wallet_later` (see section 8).

- `POST /crypto/wallet/network/monero_mainnet/XMR/create`
- `GET  /crypto/wallet/network/monero_mainnet/XMR/receive`
- `GET  /crypto/wallet/network/monero_mainnet/XMR/balance`
- `GET  /crypto/wallet/network/monero_mainnet/XMR/transactions`
- `POST /crypto/wallet/network/monero_mainnet/XMR/send/draft`
- `POST /crypto/wallet/network/monero_mainnet/XMR/send/broadcast`
- `GET  /crypto/wallet/network/monero_mainnet/XMR/transaction/{txid}`
- `GET  /crypto/wallet/network/monero_mainnet/XMR/encrypted-secret`

All will follow the same non-custodial contract as ETH / SOL / USDT-TRC20:

- Trusted device gate on every route.
- `rejects_plaintext_secret` on every route that accepts a body.
- `extra="forbid"` Pydantic models.
- Feature-flag gated: `VAULTAI_CRYPTO_XMR_ENABLED=false` default. Send additionally gated by `VAULTAI_CRYPTO_XMR_SEND_ENABLED=false` and `VAULTAI_CRYPTO_XMR_SEND_PAUSED`.
- Per-vault broadcast rate limit + idempotency, same shape as the Solana / TRON dispatchers.
- No raw address, no raw transaction, no view key, no spend key, no seed in any log line.

### Dispatch mapping to future scanner mode

- Balance route:
  - `scannerMode: "none"` → return `balanceStatus: "unavailable", reason: "scanner_not_configured"`.
  - `scannerMode: "client_side"` → the balance route is 501 or advisory only; client is the source of truth. Client-side sync writes cached balance into an opaque encrypted blob if we want persistence across app restarts, but the backend does not read it.
  - `scannerMode: "backend_view_only_opt_in"` → real balance from the server-side scanner, gated on the opt-in flag being on for this wallet.
- Transactions route: same mapping as balance.

---

## 7. Threat model

For each threat, what stops it in the recommended architecture.

- **Backend compromise.** Recommended architecture (Option A) means the backend has only ciphertext blobs, public addresses, and restore heights. Backend compromise cannot spend, cannot observe, cannot restore wallets. Under the opt-in Option B fallback, a compromise leaks view keys of opt-in users; that is why the fallback requires opt-in + delete path + kill switch.
- **Malicious RPC / daemon.** Under Option A the user picks the daemon. Under any option, we prefer over-the-wire authentication and TLS. A malicious daemon can withhold transactions (denial-of-service) but cannot steal keys, cannot forge balance (double-check via multiple daemons for high-value wallets in a later phase).
- **Metadata leakage.** Logs use closed-set labels only. No full address. No full txid (short prefix at most). No view key. No spend key. No amount. No seed. This mirrors the existing Solana and TRON log discipline.
- **Address reuse.** Encourage subaddresses. The primary receive address is 0/0; each new receive tap can request a fresh subaddress index. Never present the same subaddress twice for two visible "receive" flows unless the user explicitly wants to.
- **View-key exposure.** Under Option A, the view key never leaves the device. Under Option B, the view key is uploaded once, encrypted at rest with a KMS-managed key, and deletable. Never logged. Never returned by any GET route.
- **Spend-key exposure.** Never accepted by any backend route. Rejected by `rejects_plaintext_secret` at the Pydantic layer *before* any route body runs. The client wipes plaintext after signing.
- **Logs leaking addresses or txids.** All XMR log lines pass through the same log-line audit tests we already run for ETH / SOL / TRON (see `test_solana_engine_slice_2026_07_02.py::SolanaLoggingRestrictionsTests`). The XMR tests must extend that audit for XMR-specific fields.
- **Fake balance risk.** No balance is displayed unless a real scanner has returned a real number. The wallet is `syncing` (with real block heights) or `unavailable`, never a fake zero.
- **Restore failure.** The `restoreHeight` is stored and the encrypted wallet secret contains the seed material. As long as the user has their PIN, they can restore. The restore path is documented in the runbook alongside [BACKUP_AND_RECOVERY.md](../vault_ai_backend/BACKUP_AND_RECOVERY.md).
- **User losing PIN / vault key.** Standard VaultAI recovery flow — inheritance path, recovery codes. If the user loses the vault key with no recovery configured, the encrypted wallet secret is unrecoverable and so is the wallet. This is a feature (non-custodial has costs) but must be surfaced to the user before wallet creation.
- **Sync taking long time.** UI shows real block heights, real progress, and never fakes "up to date." A user with a wallet whose restore height is years old sees a multi-hour sync and knows why.

---

## 8. UI/UX proposal

### Current (phase 1) copy

The XMR card renders a `privacy_wallet_later` badge and displays:

- Card heading: `Monero`
- Ticker: `XMR`
- Body: `"Monero privacy wallet support is planned."`
- Sub-copy: `"XMR requires private wallet scanning, so it will be added carefully."`

Tapping the card opens the asset-detail page as it does for other placeholder assets. The detail page currently renders a Monero-specific banner (already present in [crypto_wallet_engine_asset_detail_page.dart](../vault_ai_frontend/lib/ui/crypto_wallet_engine_asset_detail_page.dart) as `kAssetDetailMoneroBanner`) explaining the special design need. No Receive button. No Send button. No balance number. No activity rows.

The card must **never** show:

- A fake balance (even zero — zero implies "we checked and it is zero", which we did not).
- A fake receive address.
- A fake or example transaction.
- A "setup successful" state before a real wallet has been generated.

### Future (phase 2+) copy

Once phase 2 lands, the card gains a live "receive-only" state and the detail page includes:

- Primary Monero address with QR.
- **Sync status card** with three states: `Syncing (block X of Y)`, `Synced at block Y`, `Sync unavailable`.
- Restore height (informational — user rarely needs to change it after generation).
- **Locked balance** and **Unlocked balance** as two separate labels once a scanner exists.
- Privacy warning banner: "Balance and activity require wallet scanning. VaultAI can sync locally on this device without revealing anything to our servers. Enabling backend scanning is a separate, opt-in feature and shows a privacy warning at that time."
- Backup reminder before the wallet is created: "This wallet is only recoverable through your VaultAI vault key. Losing your PIN with no recovery configured loses the wallet."

### What the UI will never show

- Buy, Sell, Swap, Trade, Stake, Bridge, Market, Exchange, Profit, Loss.
- A "current price" or "USD equivalent." Not part of VaultAI's product surface.
- A default-off backend-scan option masquerading as a default-on.
- A fake success screen after key generation before the client has actually generated a valid keypair and confirmed the encrypted-backup round-trip.

---

## 9. Tests to plan

The following tests must land alongside the phase they belong to. This list defines the acceptance floor for every XMR-touching slice.

### Non-custodial hard invariants (every phase)

- Backend never accepts a private spend key. `rejects_plaintext_secret` refuses the field. Test: POST create/send with a `spendKey` field returns 422 `plaintext_key_rejected`.
- Backend never accepts a mnemonic / seed / recovery phrase. Same guard.
- No backend signing helper exists. Source-guard test greps the backend source for `sign_monero_transaction`, `monero_sign`, `moneroSign`, `wallet2.sign`, etc. and asserts none are present.
- Backend never returns a spend key from any route. Response-body audit test.
- Backend never returns a view key from any route unless `scannerMode` = `backend_view_only_opt_in` AND the route is explicitly `encrypted-secret`.

### Honest-state invariants (phases 2, 3)

- No fake XMR balance. Balance route returns `balanceStatus: "unavailable"` when no scanner exists or has not synced.
- No fake XMR transactions. Transactions route returns `transactionsStatus: "unavailable"` unless a real scanner has produced rows.
- No fake address. Receive route returns `create_xmr_wallet_first` if no wallet exists; returns a real address only after a real wallet is created.
- No fake confirmation. Transaction-status route reflects real chain confirmations only.
- Sync UI never says "up to date" without a real synced-at-height signal.

### Log discipline (every phase)

- Log lines contain no full XMR address, no view key, no spend key, no seed, no full txid, no amount, no restore height leaked as a user identifier.
- Same log-audit pattern as `SolanaLoggingRestrictionsTests` and `TronBackendLoggingSafetyTests`.

### Send-safety invariants (phase 4)

- Send route disabled without `VAULTAI_CRYPTO_XMR_SEND_ENABLED=true`.
- Send route paused when `VAULTAI_CRYPTO_XMR_SEND_PAUSED=true`.
- Draft route validates from/dest addresses (95-char primary or 106-char integrated) and rejects malformed / too-many-decimals.
- Broadcast route accepts a signed-transaction blob only. `SendBroadcastPayload` uses `extra="forbid"`.
- Idempotency + per-vault rate limit, same shape as TRON.
- Frontend test: broadcast payload contains no `spendKey`, `viewKey`, `seed`, `mnemonic`, `recoveryPhrase`, `encryptedWalletSecret`, or `privateKey`.
- Frontend test: wrong PIN blocks signing.
- Frontend test: local signing on device; plaintext key wiped after sign.

### Existing-slice regressions (every phase)

- ETH / USDT ERC20 / USDC ERC20 / SOL / USDT TRC20 receive / send / balance / activity remain unchanged. No XMR change should touch those code paths.

---

## 10. Acceptance for this design slice

This slice ships when:

- `docs/crypto_wallet_monero_design.md` exists at the path above and contains the ten sections named in the spec.
- The design covers architecture options A / B / C and recommends one.
- The design defines a phased roadmap (phase 1 through phase 4).
- The design defines privacy / security tradeoffs and calls out the opt-in constraints on any backend-view-only fallback.
- XMR remains marked `privacy_wallet_later` in [crypto_wallet_engine_page.dart](../vault_ai_frontend/lib/ui/crypto_wallet_engine_page.dart) — no runtime XMR functionality is added.
- No exchange / trading language is added anywhere.
- Full backend + Flutter regressions remain green (no code changed — no test count moved).

### Backlog links (for future slices)

- Phase 2 receive foundation depends on choosing a Monero library / FFI approach on the Flutter client. Track that decision in a follow-up doc before phase 2 starts.
- Phase 3 scanner depends on the same Flutter-side library choice plus a decision about whether Option A alone is sufficient for first launch or whether Option B opt-in ships alongside it.
- Phase 4 send depends on both prior phases and on a hard security review of the local-signing FFI path.

---

*This document is a draft. It is intentionally opinionated so that engineering can push back before code is written, not after.*

---

## Appendix — 2026-07-06 slice: safe scanner-status interface (Phase 1 scaffolding)

This appendix documents the scanner architecture that ships in the 2026-07-06 slice. It does **not** add any real scanner. It adds the safe interface + honest status endpoint so future slices can plug in a real scanner without changing the UI contract or the security model.

### Current safe model (what actually ships today)

**Receive-only local wallet mode:**

- The Flutter client owns and generates the XMR wallet secret in memory. It is never uploaded in plaintext.
- The backend stores only the `encryptedWalletSecret` blob and the public wallet address (base58, mainnet-prefixed, checksum-validated).
- The backend **cannot** scan the chain because it does not hold a view key.
- The UI must display the honest state: **"Scanner not enabled"**. The scanner-status endpoint always reports `disabled` / `scanner_not_enabled` under the current defaults.

**Backend security invariants (enforced by tests):**

1. Backend never receives seed.
2. Backend never receives mnemonic.
3. Backend never receives private spend key.
4. Backend never receives private view key.
5. Backend never decrypts `encryptedWalletSecret`.
6. Backend never signs XMR transactions.
7. `canSend` remains `false` in every scanner-status response returned by any adapter in this slice.

### Scanner mode enum

`VAULTAI_CRYPTO_XMR_SCANNER_MODE` accepts three values (allowed set will only be expanded when the corresponding runtime implementation ships):

| Mode | Meaning | Scanner endpoint reports |
|------|---------|--------------------------|
| `none` | Default. No scanner. | `disabled` / `scanner_not_enabled` |
| `client_local` | Client scans locally (view key never leaves device). | `disabled` / `scanner_not_enabled` (endpoint describes the **server** scanner — the client is orthogonal) |
| `server_view_only` | Future opt-in: user chooses to let a hardened backend scan using a watch-only credential. Never implicit. | `configured` / `view_key_not_available` until the user opts in, then `syncing` → `ready` when a real HTTP adapter ships |

### Scanner-status endpoint

`GET /crypto/wallet/xmr/scanner/status` (behind `verify_trusted_device`).

Response schema:

```json
{
  "schema":          "monero_scanner_status_v1",
  "asset":           "XMR",
  "scannerStatus":   "disabled" | "not_configured" | "configured" |
                     "syncing" | "ready" | "error",
  "reason":          "scanner_not_enabled" | "scanner_not_configured" |
                     "view_key_not_available" | "scanner_unreachable" |
                     "scanner_syncing" | "scanner_ready" |
                     "scanner_error",
  "canShowBalance":  false,
  "canShowActivity": false,
  "canSend":         false
}
```

Rules:

- Default: `scannerStatus="disabled"`, `reason="scanner_not_enabled"`.
- `VAULTAI_CRYPTO_XMR_SCANNER_MODE=server_view_only` but no `VAULTAI_CRYPTO_XMR_SCANNER_URL`: `scannerStatus="not_configured"`, `reason="scanner_not_configured"`.
- Scanner URL present but user has not opted in / no watch-only credential is available: `scannerStatus="configured"`, `reason="view_key_not_available"`.
- Reserved for a future HTTP adapter: `error` / `scanner_unreachable`, `syncing` / `scanner_syncing`, `ready` / `scanner_ready`. These are wired at the adapter layer today so tests can exercise the UI copy; no real HTTP scanner probe runs in this slice.
- `canSend` is `false` for all states. Send-authorization would require signing on the device.

The response **never** carries the wallet address, scanner URL, API key, view key, encrypted secret, mnemonic, tx hash, or the raw scanner response body — asserted by tests. The safe log line emitted on each call is:

```
xmr_scanner_status_check scanner_status=<enum> reason=<enum>
    can_show_balance=<bool> can_show_activity=<bool> can_send=<bool>
```

Only closed-set enum strings and booleans. No addresses, no URLs, no key material.

### Scanner-adapter interface

`vault_ai_backend/monero_scanner.py` defines the abstract `MoneroScannerAdapter` with three methods:

- `get_status()` — returns the status envelope above.
- `get_balance(public_address)` — accepts only the **public** address string; returns a balance envelope with `balanceStatus="unavailable"` and a closed-set `reason` unless a real scanner is wired up.
- `get_activity(public_address, limit=20)` — same guarantee; never fakes activity, never fakes zero, never returns synthesized rows.

Concrete adapters shipped today:

| Adapter | Selected when | Status returned |
|---------|---------------|-----------------|
| `DisabledMoneroScannerAdapter` | `monero_enabled()` is false, or `scanner_mode == "none"`, or `client_local` | `disabled` / `scanner_not_enabled` |
| `NotConfiguredMoneroScannerAdapter` | Mode requires a URL but `monero_scanner_url()` is empty | `not_configured` / `scanner_not_configured` |
| `ViewKeyMissingMoneroScannerAdapter` | `server_view_only` mode + URL present + no watch-only credential yet | `configured` / `view_key_not_available` |
| `SyncingMoneroScannerAdapter` | Reserved for a future HTTP adapter that saw partial-height response | `syncing` / `scanner_syncing` |
| `UnreachableMoneroScannerAdapter` | Reserved for future HTTP adapter that timed out or was rejected | `error` / `scanner_unreachable` |
| `ReadyMoneroScannerAdapter` | Reserved for future HTTP adapter with a real ready response | `ready` / `scanner_ready` (balance still `unavailable` until a real scan) |

Even the `Ready` adapter refuses to invent a balance — `get_balance()` / `get_activity()` still return the closed-set unavailable envelope. Only a future HTTP-backed adapter that actually queries a real scanner is allowed to return `balanceStatus="available"` — and only when it truly saw an on-chain result.

### Frontend contract

The Flutter client:

1. Fetches `/crypto/wallet/xmr/scanner/status`, parses into `MoneroScannerStatusResponse` (see `vault_ai_frontend/lib/services/monero_scanner_status.dart`).
2. Renders the balance card and activity card copy through `moneroScannerBalanceCopyForReason()` and `moneroScannerActivityCopyForReason()` — closed-set string maps that never contain "coming soon", "buy", "sell", "swap", "trade", "stake", "bridge", "exchange", or "convert" (asserted by test).
3. Never renders `0 XMR` unless a real scanner delivered `balanceStatus == "available"`.
4. Hides the Send affordance on the XMR dashboard card until `canSend == true`, which is not possible in this slice.

### Provider-failure chip (Part E confirmation)

`kVaultBalanceSummaryAssets` in `vault_ai_frontend/lib/ui/crypto_wallet_engine_page.dart` intentionally excludes `"XMR"`. XMR's scanner-not-enabled state is therefore never counted toward the dashboard's "N balance unavailable" provider-failure chip.
