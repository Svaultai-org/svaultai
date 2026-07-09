# VaultAI Crypto Wallet — production runbook

_Last updated: 2026-06-30 (slice 13)._

This runbook is the operator's checklist for shipping the
non-custodial Crypto Wallet to real users. The wallet engine is
non-custodial by construction: the backend NEVER holds plaintext
private keys, NEVER signs, NEVER decrypts wallet secrets. But it
DOES depend on external configuration — RPC URLs, indexer
endpoints, token contract addresses — and a misconfigured deployment
can silently break user balances or, worse, route real-money sends
to the wrong chain. This document is the closed-set procedure that
prevents that.

## 1. Required environment variables

| Variable | Purpose | Default | Required for |
|---|---|---|---|
| `VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED` | Master kill switch | `false` | Everything |
| `ETHEREUM_SEPOLIA_RPC_URL` | Sepolia balance + send + activity | empty | Sepolia full path |
| `ETHEREUM_MAINNET_RPC_URL` | Mainnet balance + send + activity | empty | Mainnet full path |
| `VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED` | Mainnet ETH receive surface | `false` | Mainnet receive |
| `VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED` | Mainnet USDT/USDC receive | `false` | Mainnet ERC20 receive |
| `VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED` | Mainnet send broadcast | `false` | Mainnet send |
| `VAULTAI_CRYPTO_MAINNET_SEND_PAUSED` | Emergency pause | `false` | Live pause |
| `VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN` | Admin gate for `/crypto/wallet/health` | empty | Production health |

## 2. Optional environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER` | `etherscan` / `blockscout` | empty |
| `ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY` | Etherscan key | empty |
| `ETHEREUM_SEPOLIA_TX_INDEXER_BASE_URL` | Override default | empty |
| `ETHEREUM_MAINNET_TX_INDEXER_PROVIDER` | `etherscan` / `blockscout` | empty |
| `ETHEREUM_MAINNET_TX_INDEXER_API_KEY` | Etherscan key | empty |
| `ETHEREUM_MAINNET_TX_INDEXER_BASE_URL` | Override default | empty |
| `ETH_SEPOLIA_USDT_CONTRACT_ADDRESS` | Sepolia test USDT | empty |
| `ETH_SEPOLIA_USDC_CONTRACT_ADDRESS` | Sepolia test USDC | empty |
| `ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS` | Mainnet USDT | empty |
| `ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS` | Mainnet USDC | empty |
| `VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT` | Broadcasts per vault per window | `3` |
| `VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS` | Sliding window length | `60` |

## 3. Recommended provider setup

* **Sepolia RPC** — Alchemy, Infura, or QuickNode. Free tiers
  are fine.
* **Mainnet RPC** — Alchemy, Infura, QuickNode, or a self-hosted
  archive node. Pick one that you trust to NOT log your users'
  addresses. The wallet engine forwards real-money broadcasts here.
* **Transaction indexer** — Etherscan V2 (multi-chain endpoint
  `https://api.etherscan.io/v2/api`) requires an API key. Blockscout
  works without a key.
* **Token contracts** — pin the canonical mainnet addresses for USDT
  (`0xdAC17F958D2ee523a2206206994597C13D831ec7`) and USDC
  (`0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`). Set them via env
  vars; the wallet engine refuses to hardcode them.

## 4. Chain id expectations

| Network | Expected chain id |
|---|---|
| ethereum_sepolia | `11155111` |
| ethereum_mainnet | `1` |

The health route's `chainIdObserved` field reports the value the
configured RPC returned. A mismatch surfaces as
`reason="chain_id_mismatch"` and drops the per-network status to
`not_ready`. **Fix this before any user moves funds** — a Sepolia
URL pointing at mainnet (or vice versa) would silently route an
intended-testnet broadcast onto mainnet.

## 5. Token contract checklist

For each (network, asset) tuple the wallet engine cares about:

1. Set the contract address env var.
2. Verify the health route reports `configured: true` and
   `readable: true`.
3. If `readable: false`, the most common cause is the contract
   address is correct but the RPC URL can't reach it — check
   `rpcReachable`.

`reason="invalid_contract_address"` means the env var value is not
a `0x` + 40 hex string.

## 6. Health check route

* `GET /crypto/wallet/health` — admin only. Requires the header
  `X-Crypto-Health-Admin-Token` matching
  `VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN`. Returns the closed-set
  `crypto_wallet_health_v1` envelope.
  * `overallStatus` is `ready` / `degraded` / `not_ready`.
  * Each `networks[]` entry carries `status` + `reason` + per-token
    + per-feature booleans.
  * NEVER carries the RPC URL, the API key, or any raw provider
    body.

* `GET /crypto/wallet/features` — user-safe. No auth gate beyond
  the trusted-device requirement. The frontend reads this to honor
  the live backend state regardless of compile-time `--dart-define`
  flags.

The frontend admin/dev health panel (
`CryptoWalletEngineAdminHealthPanel`) renders the envelope as a
stack of operator status cards. It refuses to render RPC URLs / API
keys even if they ever appeared in the envelope (defense in depth).

## 7. Emergency pause

To halt all mainnet sends immediately (e.g. responding to an active
incident):

```
VAULTAI_CRYPTO_MAINNET_SEND_PAUSED=true
```

Reload the backend. The mainnet `send/draft` and `send/broadcast`
routes will return the closed-set `mainnet_send_paused` envelope.
The frontend send panel surfaces "Mainnet sending is temporarily
paused." Receive, balance, and activity stay live so users can
still see their holdings.

To resume: set the var to `false` and reload.

## 8. Rate limit settings

The mainnet broadcast route enforces a per-vault rate limit:

* `VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT` — number of
  broadcasts per window (default `3`).
* `VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS` — sliding
  window length in seconds (default `60`).

When exceeded the route returns HTTP `429` with `Retry-After`. The
envelope carries a closed-set `rate_limited` body that does NOT
echo the signed transaction, destination, or amount.

## 9. What NOT to log

The wallet engine's source enforces this with tests, but operators
SHOULD audit any custom logging additions. NEVER log:

* The RPC URL or any path/query that includes it.
* The indexer base URL or its API key.
* The `signedTransaction` body.
* The full transaction hash (only a short prefix is OK).
* `publicAddress` / `destinationAddress` / `fromAddress`.
* The transaction amount.
* `encryptedWalletSecret`.
* Any plaintext key alias: `privateKey`, `seedPhrase`, `mnemonic`,
  `recoveryPhrase`, `xprv`.
* The raw RPC response body.
* The raw indexer response body.
* The idempotency key.
* The admin token.

## 10. Safe rollout order

The closed-set sequence the wallet engine was designed for. Each
step should run for at least a week against real internal testers
before moving to the next.

1. **Sepolia only.** Backend has `ETHEREUM_SEPOLIA_RPC_URL` and the
   Sepolia indexer + contracts. Frontend build flags all off.
   Health route shows Sepolia `ready`, mainnet `not_ready`. Users
   exercise testnet send/receive end to end.
2. **Mainnet receive only (ETH).** Flip
   `VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED=true` AND the
   matching `--dart-define`. Users receive real ETH; send stays
   blocked.
3. **Mainnet ERC20 receive only.** Flip
   `VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED=true` AND the
   matching `--dart-define`. Users receive real USDT/USDC at the
   same ETH wallet address. Send still blocked.
4. **Mainnet send disabled dry run.** With all receive flags on but
   `VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED` still off, run the
   admin health route in production. Confirm `overallStatus: ready`
   and `mainnetSendEnabled: false`.
5. **Mainnet send enabled for internal testers.** Flip the send
   flag on the backend AND the matching `--dart-define`. Internal
   testers exercise the full
   confirmation-phrase → PIN → local-sign → broadcast flow with
   small ETH amounts.
6. **Public launch.** Roll out to the wider user base. Keep
   `VAULTAI_CRYPTO_MAINNET_SEND_PAUSED=false`; the pause flag is
   for incident response only.

## 11. Non-custodial floor (unchanged)

These invariants are enforced by tests AND source guards. Operators
must not weaken them with custom code:

* The backend NEVER receives plaintext private keys.
* The backend NEVER receives seed phrases / mnemonics / recovery
  phrases.
* The backend NEVER decrypts the wallet secret.
* The backend NEVER signs.
* The backend ONLY broadcasts CLIENT-signed raw transactions.
* The closed-set RPC whitelist (`evm_rpc.ALLOWED_RPC_METHODS`)
  excludes every signing primitive.
* The closed-set health RPC whitelist
  (`crypto_wallet_health._ALLOWED_HEALTH_METHODS`) only allows
  `eth_chainId`, `eth_blockNumber`, and `eth_call`.
* The mainnet broadcast route refuses any extra field besides
  `signedTransaction` and the optional `idempotencyKey`.
* The mainnet broadcast route refuses any of the closed-set
  plaintext-key aliases.
