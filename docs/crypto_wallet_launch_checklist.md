# VaultAI Crypto Vault — Launch checklist

This is the pre-flight checklist an operator walks through before
turning on the Crypto Vault for real users. It complements
[crypto_wallet_runtime_setup.md](./crypto_wallet_runtime_setup.md) —
that doc explains *what* to configure, this doc explains *how* to
verify each piece end-to-end.

Non-custodial rules that never change:

- Backend never receives plaintext keys, seed, mnemonic, or wallet
  password.
- Backend never signs transactions.
- Backend never scans a Monero wallet in this build.
- Backend broadcasts only a signed transaction produced by the client
  after the user's PIN.
- Backend never invents balance, address, activity, tx hash, or fee.

## 0. Do not treat any check as passed until it renders on a real
device with real backend responses. Screenshots from tests do not
count for launch.

## 1. Backend env checklist

Run this shell audit before every deploy. Every line should print a
non-empty value **or** a documented "off by policy" note.

### 1a. Global

- `VAULTAI_ENV=production`
- `VAULT_SESSION_SECRET` — set (non-empty)
- `CORS_ALLOWED_ORIGIN_REGEX` or `CORS_ALLOWED_ORIGINS` — set
- `VAULTAI_DEBUG_ENDPOINTS_ENABLED` — must be unset or `false`
- `VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST` — must be unset or `false`
- `VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED=true`
- `VAULTAI_CRYPTO_DEFAULT_NETWORK=ethereum_mainnet`

### 1b. Ethereum Mainnet (ETH, USDT ERC20, USDC ERC20)

- `VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED=true`
- `VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED=true`
- `VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED=true`
- `ETHEREUM_MAINNET_RPC_URL` — set
- `ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7`
- `ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`
- `ETHEREUM_MAINNET_TX_INDEXER_PROVIDER=etherscan` (or blockscout)
- `ETHEREUM_MAINNET_TX_INDEXER_API_KEY` — set if Etherscan

### 1c. Solana Mainnet (SOL)

- `VAULTAI_CRYPTO_SOLANA_ENABLED=true`
- `VAULTAI_CRYPTO_SOLANA_SEND_ENABLED=true`
- `SOLANA_RPC_URL` — set

### 1d. TRON Mainnet (USDT TRC20)

- `VAULTAI_CRYPTO_TRON_ENABLED=true`
- `VAULTAI_CRYPTO_TRON_SEND_ENABLED=true`
- `TRON_API_BASE_URL` — set
- `TRON_API_KEY` — set (if provider requires)
- `TRON_USDT_CONTRACT_ADDRESS=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t`

### 1e. Monero (XMR)

- `VAULTAI_CRYPTO_XMR_ENABLED=true` — only if XMR receive is meant
  to be user-facing in this deploy
- `VAULTAI_CRYPTO_XMR_SCANNER_MODE=none` — the only permitted value
  in this build

### 1f. Stripe

- `STRIPE_SECRET_KEY` — set (starts with `sk_live_` in prod)
- `STRIPE_WEBHOOK_SECRET` — set (starts with `whsec_`)
- `STRIPE_PUBLISHABLE_KEY` — set (starts with `pk_live_`)
- `STRIPE_PRICE_ID_STORAGE_BLOCK` — set

### 1g. Admin health tokens

- `VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN` — set (production)
- `VAULTAI_BILLING_HEALTH_ADMIN_TOKEN` — set (production)

## 2. Frontend build checklist

Every production build should be produced with:

```
flutter build web \
  --dart-define=CRYPTO_WALLET_ENGINE_ENABLED=true \
  --dart-define=CRYPTO_WALLET_DEFAULT_NETWORK=ethereum_mainnet \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_RECEIVE_ENABLED=true \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_ERC20_RECEIVE_ENABLED=true \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=false
```

Keep broadcast disabled for the release candidate. Enabling mainnet send is a
separate operator action after an explicitly authorized broadcast smoke test.

Verify inside the built bundle:

- Old Lite UI is not reachable from any menu (nav guards).
- Debug controls / debug endpoints toggles are absent.
- The dark premium Crypto Vault theme renders on all screens.
- No `Debug` badge is visible anywhere in production.
- No third-party trackers or analytics scripts fire.

## 3. Operator readiness verification

Open `Crypto Vault → provider readiness` panel. It reads
`/crypto/wallet/features` and `/crypto/wallet/diagnosis` and renders a
6-row asset checklist:

| Row | Expected in "ready to ship" state |
| --- | --- |
| ETH · Ethereum Mainnet | Feature yes · RPC/API yes · Balance route ready yes · Reason `ready` |
| USDT (ERC20) · Ethereum Mainnet | Feature yes · Token contract yes · Balance route ready yes · Reason `ready` |
| USDC (ERC20) · Ethereum Mainnet | Feature yes · Token contract yes · Balance route ready yes · Reason `ready` |
| SOL · Solana Mainnet | Feature yes · RPC/API yes · Balance route ready yes · Reason `ready` |
| USDT (TRC20) · TRON Mainnet | Feature yes · RPC/API yes · Token contract yes · Balance route ready yes · Reason `ready` |
| XMR · Monero Mainnet | Feature yes · Client scanner supported no · Backend scanner enabled no · Reason `xmr_scanner_client_required` |

Anything else — RPC URL, API key, wallet address, tx hash, private
key, encrypted secret — must never be rendered. The panel prints its
own "secret-safe" attestation at the bottom.

The XMR row is intentionally not "READY" for balance: the scanner
adapter is unavailable in this build. That is honest, not a
regression.

Also open `Crypto Vault → production health` (existing admin panel).
Overall status should be `READY` (or the operator understands the
exact reason it is `DEGRADED`).

## 4. Manual end-to-end verification

Run this once on a real production build against production infra, on
a real device, with a fresh vault. Every step below has an explicit
"pass" line — if a step does not match, do not ship.

### 4a. Ethereum Mainnet

1. **Create ETH wallet**
   - Open Crypto Vault → ETH card → Receive.
   - Wallet is generated locally, PIN gate fires.
   - Backend receives ciphertext only (verify via server logs redacted
     `ciphertext_len=…` line).
   - **Pass**: Receive panel renders a `0x…` address + QR + copy button.
2. **Receive ETH**
   - Send a tiny amount of ETH from another wallet to that address.
   - Wait for one confirmation.
   - **Pass**: ETH card balance auto-refreshes to the real number.
3. **Balance shows real value or real zero**
   - **Pass**: Balance card renders `X ETH` for the exact chain value.
   - Refresh icon returns the same number after a re-fetch.
4. **Send small ETH** (operator's discretion, real funds)
   - Open ETH detail → Send.
   - Draft fires → review page → PIN prompt.
   - Sign locally (verify via network tab: backend receives signed tx
     bytes only, never a raw key).
   - **Pass**: tx hash appears in activity card after broadcast.
5. **USDT / USDC ERC20**
   - Same flow on the USDT ERC20 and USDC ERC20 cards.
   - **Pass**: Balance shows `X USDT` / `X USDC` per real chain state.
   - **Pass**: Token cards share the ETH wallet address.

### 4b. Solana Mainnet

1. **Create SOL wallet**
   - Open SOL card → Receive.
   - **Pass**: SOL Base58 address (32 or 44 char) renders + QR + copy.
2. **Receive SOL**
   - Send small SOL from another wallet.
   - **Pass**: SOL balance card auto-refreshes to real number.
3. **Balance / status / fee routes ready**
   - **Pass**: Balance shows `X SOL`, status/activity panel is
     connected, priority fee shown honestly.
4. **Send small SOL** (operator's discretion)
   - **Pass**: tx sig appears after broadcast, no fake confirmation.

### 4c. TRON Mainnet (USDT TRC20)

1. **Create TRON wallet**
   - Open USDT TRC20 card → Receive.
   - **Pass**: TRON Base58Check address (`T…`, 34 chars) renders +
     QR + copy.
2. **Receive USDT TRC20**
   - Send small USDT TRC20 from another wallet.
   - **Pass**: USDT TRC20 balance auto-refreshes to real number.
3. **TRX preflight**
   - Try to send USDT without enough TRX for bandwidth/energy.
   - **Pass**: Draft path blocks with a preflight message, never
     produces an unsignable draft.

### 4d. Monero (XMR)

1. **Create XMR wallet**
   - Open XMR card → Receive → Create Monero wallet.
   - Wallet generation runs on the device (pure-Dart Ed25519).
   - **Pass**: Receive panel renders the 95-char primary Monero
     address starting with `4`, QR renders, restore height shows.
2. **XMR balance says scanner unavailable**
   - **Pass**: Balance card says "Monero balance requires wallet
     scanning" (or similar exact reason string).
   - **Pass**: Activity card says "Monero activity requires wallet
     scanning".
   - **Pass**: Scanner card says "Monero scanning is not available in
     this build yet." No Start scan button appears.
3. **XMR send stays disabled**
   - **Pass**: Send affordance shows "Monero sending is not enabled
     yet." No signing flow reachable.

### 4e. Stripe billing

1. **Storage checkout**
   - Vault menu → Storage → Add block.
   - Redirect lands on Stripe Checkout.
   - Complete with a real card (or Stripe test card if lower env).
   - **Pass**: Redirect returns to `/storage?checkout=success` cleanly
     (no `/#/storage` hash-mode URL).
2. **Stripe webhook**
   - Trigger `checkout.session.completed` from Stripe dashboard.
   - **Pass**: Server logs show webhook accepted, signature verified,
     no plaintext body echoed.
3. **Storage quota updates**
   - **Pass**: Dashboard storage banner reflects the new block size.
4. **Failed payment banner**
   - Simulate a failed payment via Stripe.
   - **Pass**: UI shows the failed-payment banner, subscription still
     works within the grace window.
5. **Subscription portal opens**
   - Tap "Manage subscription".
   - **Pass**: Stripe billing portal loads; user can update payment
     method.

## 5. Copy audit (must all be true before launch)

Nowhere in the visible product may appear these words: `buy`, `sell`,
`swap`, `trade`, `stake`, `bridge`, `exchange`, `market`, `profit`,
`loss` — except in a **negative** attestation like "VaultAI does not
buy, sell, swap, trade, stake, or bridge" (this is intentional).

- Main crypto section is titled **Crypto Vault**.
- Balance summary is **Vault balance**.
- Asset grid is **Stored assets**.
- Activity section is **Vault activity**.
- Security section is **Vault security** / **Security**.
- Actions are **Receive** / **Send** / **Refresh**.
- Fee is **Network fee** (not "gas price" — "gas fee" is acceptable
  when explaining an Ethereum-specific concept).
- Monero scanner unavailable state is called **Scanner unavailable**
  (never "not connected").
- Ethereum Sepolia is labeled **Testnet** only when actually selected.
- The word **Portfolio** does not appear anywhere in the product.

## 6. Mobile layout audit

Every screen below must render without a RenderFlex overflow at
360×720 (small phone) and 420×800 (typical phone):

- Main Crypto Vault dashboard
- Asset grid (all six cards)
- Portfolio/Vault balance summary
- ETH receive panel
- ETH send panel
- ETH detail page (all three ERC20 tokens)
- SOL receive panel
- SOL send panel
- SOL status / fee / activity card
- USDT TRC20 receive panel
- USDT TRC20 send panel
- XMR receive panel (with real generated address)
- XMR scanner card (unavailable, not-started, syncing, synced, failed)
- Storage / subscription banners

## 7. Non-custodial guarantees to demonstrate

Before shipping, operator should be able to answer "yes" to all:

1. Can you name every env var that would carry a secret? Yes — every
   name is listed in section 1 above; **the values are never exposed
   to the client**.
2. Does the client ever ship a mnemonic / seed / spend key / view key
   / wallet password to the backend? **No.**
3. Does the backend ever sign a transaction? **No.**
4. Does the backend ever scan a Monero wallet? **No.**
5. Does the backend log any address, tx hash prefix > 12 chars, amount,
   or restoreHeight? **No.**
6. Does any UI card render a fake zero when RPC is missing? **No** —
   the reason renders as `Ethereum RPC is not configured.` / `Solana
   RPC is not configured.` / `TRON API is not configured.` / etc.
7. Are all the source guards passing in the current test run?
   Backend `test_xmr_client_side_wallet_generation_2026_07_02.py::BackendMoneroSourceGuardsTests`,
   `test_xmr_client_scanner_foundation_2026_07_02.py::BackendMoneroScannerSourceGuardTests` — **all green**.

## 8. Readiness script — one-command sanity check

Before hitting the readiness panel by hand, run the safe script:

```
python vault_ai_backend/scripts/check_crypto_wallet_readiness.py \
    --base-url https://api.your-domain.example \
    --auth-token "$SESSION_TOKEN" \
    --admin-token "$VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN"
```

Expected output when Ethereum, Solana, TRON are fully configured
and XMR scanner is intentionally left off:

```
ETH Mainnet    ready     — reason ready
USDT ERC20     ready     — reason ready
USDC ERC20    ready     — reason ready
SOL            ready     — reason ready
USDT TRC20     ready     — reason ready
XMR            not ready — reason xmr_scanner_client_required

Summary: 5 ready · 1 intentionally not ready · 0 not ready · 6 total
```

Exit codes:

- **0** — every asset is ready, or the only not-ready asset is XMR
  (whose scanner is a deferred slice).
- **1** — at least one asset is not ready because of a fixable
  provider config issue. The reason column tells you which env var
  to set:
  - `rpc_not_configured` → set the RPC/API endpoint env var.
  - `token_contract_not_configured` → set the token-contract env var.
  - `feature_disabled` → flip the receive/enable flag.
- **2** — the script could not reach the backend, or your admin
  token was rejected. Fix networking / token first.

**The script never prints RPC URLs, API keys, contract-address
values, wallet addresses, tx hashes, private keys, mnemonics,
encrypted secrets, or session tokens.** If a future envelope
somehow contains one of those, the script's `scrub` helper
substitutes `<redacted>` before printing. There is a backend test
that asserts this holds against a synthetic leaky envelope.

## 9. Frontend readiness panel — operator walkthrough

After the CLI script shows green (or intentionally-yellow for XMR),
verify the in-app readiness panel matches.

1. Open the app on a trusted device with production build.
2. Navigate to **Crypto Vault → provider readiness** panel.
3. Confirm the header reads **"Crypto Vault — provider readiness"**.
4. Confirm the summary chip reads **"5 of 6 assets ready"** when
   Ethereum, Solana, TRON are configured. If it reads fewer,
   the CLI script's reason column tells you what to fix.
5. Confirm the six asset rows appear in this exact order:
   `ETH · Ethereum Mainnet`, `USDT (ERC20) · Ethereum Mainnet`,
   `USDC (ERC20) · Ethereum Mainnet`, `SOL · Solana Mainnet`,
   `USDT (TRC20) · TRON Mainnet`, `XMR · Monero Mainnet`.
6. **XMR must render NOT READY** with reason
   `xmr_scanner_client_required`. This is correct — the scanner
   adapter is a deferred slice; the panel does not lie about it.
7. Confirm the bottom attestation reads: *"Values shown are booleans
   and enum strings only. No RPC URL, no API key, no token contract
   value, no wallet address, no tx hash, no private key or seed."*
8. Confirm no URL string, no `0x…` contract address, no `TXLAQ…`
   TRON contract, no `4…`/`8…` Monero address appears anywhere on
   the panel. If any appears, this is a shipping bug — do not launch.
9. Confirm the app-wide copy uses the launch lexicon:
   - Main crypto section is called **Crypto Vault**.
   - Balance summary heading reads **Vault balance** (not "Portfolio").
   - Asset grid heading reads **Stored assets**.
   - Activity heading reads **Vault activity**.
   - No `Buy`, `Sell`, `Swap`, `Trade`, `Stake`, `Bridge`, `Exchange`,
     `Market`, `Profit`, `Loss` verb appears anywhere.
10. Confirm the old Lite dashboard is NOT reachable from any menu.

## 10. Runtime balance validation — per asset

For each asset, after configuring providers and confirming the CLI
report, run this loop on a real device:

**Loop**

1. Open Crypto Vault → the asset's card.
2. Tap **Receive**.
3. **Confirm the wallet is created locally.** For ETH/SOL/TRON, the
   PIN gate fires and the backend receives ciphertext only. For XMR,
   the pure-Dart wallet generator runs client-side; verify the
   receive panel renders a 95-char address starting with `4`.
4. Copy the address.
5. Send a tiny amount from another wallet you control.
6. Tap **Refresh** on the balance card.
7. Expected:
   - **Real zero** (`0 ETH`, `0 SOL`, `0 USDT`, `0 USDC`) if the
     wallet is genuinely empty and the provider is reachable.
   - The **real chain value** if funds arrived.
   - **Honest reason** if the provider is misconfigured
     (`Ethereum RPC is not configured.` / `Solana RPC is not
     configured.` / `TRON API is not configured.` / `Token contract
     is not configured.` / `Balance temporarily unavailable.`).
8. **Never expect a fake zero.** If the balance card shows `0` when
   RPC is not configured, this is a shipping bug — do not launch.

**Per asset**

| Asset | Route | Balance expectation | XMR-specific |
| --- | --- | --- | --- |
| ETH | ETH card → Receive → Refresh | 0 ETH / real value / RPC reason | — |
| USDT ERC20 | USDT card → Receive → Refresh | 0 USDT / real value / RPC or contract reason | — |
| USDC ERC20 | USDC card → Receive → Refresh | 0 USDC / real value / RPC or contract reason | — |
| SOL | SOL card → Receive → Refresh | 0 SOL / real value / Solana RPC reason | — |
| USDT TRC20 | USDT TRC20 card → Receive → Refresh | 0 USDT / real value / TRON API or contract reason | — |
| XMR | XMR card → Receive → Create Monero wallet | Receive shows real 95-char address + QR | Balance shows *"Monero balance requires wallet scanning."* Scanner card shows *"Monero scanning is not available in this build yet."* Send affordance is disabled with *"Monero sending is not enabled yet."* |

## 11. Rollback plan

If any real user reports an incorrect balance or an incorrect address:

1. Flip `VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED=false` — every card
   falls back to the engine-disabled envelope. Existing wallets and
   encrypted secrets remain untouched.
2. Investigate the specific chain: check its diagnosis row's
   `lastBalanceReason` first — that pinpoints whether the fault is in
   env config (RPC not configured, contract not configured) vs. a
   real RPC provider outage.
3. Never manually edit `encryptedWalletSecret` or the wallet address
   in the database. Ciphertext is what it says on the tin.
