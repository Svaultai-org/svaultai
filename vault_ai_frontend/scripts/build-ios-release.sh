#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

release_sha="$(git rev-parse HEAD)"
[[ "$release_sha" =~ ^[a-f0-9]{40}$ ]] || {
  echo "[ios-release] a full commit SHA is required." >&2
  exit 2
}

python3 scripts/verify-release-contract.py \
  --backend-url https://api.svaultai.com/release-contract
flutter build ipa --release \
  --dart-define="APP_RELEASE=$release_sha" \
  --dart-define-from-file=config/release-contract.production.json \
  --dart-define=CRYPTO_WALLET_DEFAULT_NETWORK=ethereum_mainnet \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_RECEIVE_ENABLED=true \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_ERC20_RECEIVE_ENABLED=true \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=true \
  "$@"

printf 'IOS_STORE_SUBMISSION_PERFORMED=false\n'
