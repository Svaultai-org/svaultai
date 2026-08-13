# VaultAI Crypto Wallet — Runtime Setup Checklist

This document explains what the operator has to configure in order to make
the wallet engine's *balances* actually load in the app.

The wallet code (key generation, signing) is client-side. The backend still
needs an RPC / API endpoint per chain to observe on-chain state (balance,
gas price, activity). When those endpoints aren't configured, the app is
required to say so **honestly** — never a fake zero, never a fake
"not connected."

Non-custodial rules that never change:

- Backend never receives a plaintext private key, spend key, view key,
  seed, mnemonic, polyseed, or wallet password.
- Backend never decrypts `encryptedWalletSecret`.
- Backend never signs a transaction.
- Backend broadcasts only a signed transaction produced by the client
  after the user's PIN.
- Backend never invents balance, address, activity, tx hash, or fee.
- No buy / sell / swap / trade / stake / bridge UI.

## 1. Env checklist

Only what the wallet engine reads. Everything else in this repo has its own
config docs.

### Global engine flags

```env
VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED=true
VAULTAI_CRYPTO_DEFAULT_NETWORK=ethereum_mainnet
```

`VAULTAI_CRYPTO_DEFAULT_NETWORK` must be one of `ethereum_mainnet` or
`ethereum_sepolia`. If unset in production, the backend refuses to boot.

### Ethereum Mainnet (ETH, USDT ERC20, USDC ERC20)

```env
VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED=true
VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED=true
VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED=true

ETHEREUM_MAINNET_RPC_URL=
ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=0xdAC17F958D2ee523a2206206994597C13D831ec7
ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
```

The USDT/USDC contract addresses above are the canonical Ethereum Mainnet
addresses.

Optional transaction-history indexer (for the activity card):

```env
ETHEREUM_MAINNET_TX_INDEXER_PROVIDER=etherscan
ETHEREUM_MAINNET_TX_INDEXER_API_KEY=
```

### Solana Mainnet (SOL)

```env
VAULTAI_CRYPTO_SOLANA_ENABLED=true
VAULTAI_CRYPTO_SOLANA_SEND_ENABLED=true

SOLANA_RPC_URL=
```

### TRON Mainnet (USDT TRC20)

```env
VAULTAI_CRYPTO_TRON_ENABLED=true
VAULTAI_CRYPTO_TRON_SEND_ENABLED=true

TRON_API_BASE_URL=
TRON_API_KEY=
TRON_USDT_CONTRACT_ADDRESS=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
```

### Monero (XMR)

```env
VAULTAI_CRYPTO_XMR_ENABLED=false
VAULTAI_CRYPTO_XMR_SCANNER_MODE=none
```

Leave XMR off unless you are testing the receive foundation. XMR balance
and activity require the client-side wallet scanner, which is not in this
slice. The only permitted scanner mode value in this slice is `none`.

### Frontend build flags (Flutter)

Compile-time hard rails. If any of these is `false` at build time, the
frontend keeps the receive / send flow disabled regardless of what the
backend features endpoint reports.

```
--dart-define=CRYPTO_WALLET_ENGINE_ENABLED=true
--dart-define=CRYPTO_WALLET_DEFAULT_NETWORK=ethereum_mainnet
--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_RECEIVE_ENABLED=true
--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_ERC20_RECEIVE_ENABLED=true
--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=false
```

## 2. What each balance reason means

The balance endpoint returns `balanceStatus: unavailable` with a `reason`
when it can't produce a real number. The Flutter client maps each reason
to its own honest copy:

| Reason from backend                | Frontend copy                                                     |
| ---------------------------------- | ----------------------------------------------------------------- |
| `no_wallet_yet`                    | "Create wallet to view balance."                                  |
| `rpc_not_configured` (Ethereum)    | "Ethereum RPC is not configured."                                 |
| `rpc_not_configured` (Solana)      | "Solana RPC is not configured."                                   |
| `rpc_not_configured` (TRON)        | "TRON API is not configured."                                     |
| `rpc_not_configured` (Monero)      | "Monero balance requires wallet scanning. Scanning is not enabled yet." |
| `token_contract_not_configured`    | "Token contract is not configured."                               |
| `rpc_unreachable` / RPC error code | "Balance temporarily unavailable."                                |
| `feature_disabled` / network off   | "This asset is not enabled yet."                                  |
| `xmr_scanner_not_enabled`          | "Monero balance requires wallet scanning. Scanning is not enabled yet." |
| Real zero from chain               | "0 ETH", "0 SOL", "0 USDT" (the actual number the chain returned) |

The client never renders "not connected" as a fallback. If the reason is
unknown it falls back to "Balance temporarily unavailable" — never a fake
zero and never nothing.

## 3. Verify from a running server

After setting envs, run the server and hit these three endpoints. The
frontend uses `/features`; the operator uses `/health` and `/diagnosis`.

### `GET /crypto/wallet/features`

Everyone with a trusted device can hit it. Expected shape:

```json
{
  "status": "ok",
  "schema": "crypto_wallet_features_v1",
  "walletEngineEnabled": true,
  "mainnetReceiveEnabled": true,
  "mainnetErc20ReceiveEnabled": true,
  "mainnetSendEnabled": true,
  "solanaEnabled": true,
  "solanaBalanceEnabled": true,
  "tronEnabled": true,
  "tronBalanceEnabled": true,
  "tronUsdtContractConfigured": true,
  "supportedNetworks": ["ethereum_sepolia", "ethereum_mainnet", "solana_mainnet", "tron_mainnet"],
  ...
}
```

Only booleans and enum strings. No RPC URL, no API key, no contract
address, no seed, no mnemonic.

### `GET /crypto/wallet/health`

Requires the header `X-Crypto-Health-Admin-Token: <token>` in production,
or `VAULTAI_DEBUG_ENDPOINTS_ENABLED=true` in dev. Returns per-network RPC
reachability, chain id match, token contract readable check. No secrets
in the body — probes are done server-side and only the outcome is
returned.

`overallStatus` is `ready` only when every enabled asset's RPC is
reachable and every configured contract is readable.

### `GET /crypto/wallet/diagnosis`

Same auth as `/health`. Same non-secret guarantee. Returns per-asset
rows:

```json
{
  "schema": "crypto_wallet_diagnosis_v1",
  "walletEngineEnabled": true,
  "assetsReady": 5,
  "assetsTotal": 6,
  "assets": [
    {
      "rowId": "ethereum_mainnet_eth",
      "asset": "ETH",
      "network": "ethereum_mainnet",
      "featureEnabled": true,
      "featureFlagEnvVar": "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
      "rpcConfigured": true,
      "rpcEnvVar": "ETHEREUM_MAINNET_RPC_URL",
      "tokenContractRequired": false,
      "tokenContractConfigured": true,
      "tokenContractEnvVar": "",
      "balanceRouteReady": true,
      "lastBalanceReason": "ready"
    },
    {
      "rowId": "ethereum_mainnet_usdt_erc20",
      "asset": "USDT_ERC20",
      "featureFlagEnvVar": "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
      "rpcConfigured": true,
      "tokenContractRequired": true,
      "tokenContractConfigured": true,
      "tokenContractEnvVar": "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
      "balanceRouteReady": true,
      "lastBalanceReason": "ready"
    },
    ...
  ]
}
```

The envelope never contains the actual RPC URL, the actual API key, or
the actual token contract address — only whether the env var is populated
(`rpcConfigured` / `tokenContractConfigured`).

Reading a diagnosis row top-down:

1. `featureEnabled == false` → set the flag env var and restart.
2. `rpcConfigured == false` → set the RPC/API env var (name in
   `rpcEnvVar`) and restart.
3. `tokenContractRequired && !tokenContractConfigured` → set the token
   contract env var (name in `tokenContractEnvVar`) and restart.
4. `balanceRouteReady == true` → the backend will now emit real balances
   as soon as the user creates a wallet.

## 4. Frontend refresh behavior

`CryptoWalletEnginePage`:

- fetches `/crypto/wallet/features` when it mounts;
- fetches it again after the receive panel closes (so a freshly created
  wallet's card unlocks immediately);
- fetches it again after the user returns from the asset detail page;
- keeps compile-time `--dart-define` flags as hard rails — no runtime
  flip enables a receive path that was disabled at build.

`CryptoWalletEngineAssetDetailPage`:

- loads the address then the balance on mount;
- exposes a refresh icon next to the "Balance" heading — tapping it
  re-runs the balance load;
- when the receive panel closes, reloads both address and balance
  (covers the case where the user just created the wallet);
- displays the exact reason string returned by the backend — never a
  generic "not connected."

## 5. Common failure modes and what the app will show

| Scenario                                              | Frontend copy on the balance card                        |
| ----------------------------------------------------- | -------------------------------------------------------- |
| Freshly logged-in user, no wallet yet                 | "Create wallet to view balance."                         |
| `ETHEREUM_MAINNET_RPC_URL` blank                      | "Ethereum RPC is not configured."                        |
| `SOLANA_RPC_URL` blank, `VAULTAI_CRYPTO_SOLANA_ENABLED=true` | "Solana RPC is not configured."                    |
| `TRON_API_BASE_URL` blank, `VAULTAI_CRYPTO_TRON_ENABLED=true` | "TRON API is not configured."                     |
| `ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS` blank        | "Token contract is not configured."                      |
| Mainnet feature flag off                              | "This asset is not enabled yet."                         |
| RPC configured but 500 / timeout                      | "Balance temporarily unavailable."                       |
| Wallet exists on empty chain address                  | "0 ETH" / "0 SOL" / "0 USDT" — the real number           |
| XMR on, no wallet scanner shipped yet                 | "Monero balance requires wallet scanning. Scanning is not enabled yet." |

## 6. Security guarantees this checklist preserves

- Every env var above is read from the process environment. None of them
  are persisted in the vault or exposed to the client.
- `/features` returns booleans and enum strings only.
- `/health` and `/diagnosis` require the admin token in production.
- Logs never contain the RPC URL, the API key, the contract address, a
  wallet address, a seed, a mnemonic, or an amount.
- Encrypted wallet secrets remain ciphertext under the vault key. Setting
  an RPC / API env var does not give the backend any new decryption power.
