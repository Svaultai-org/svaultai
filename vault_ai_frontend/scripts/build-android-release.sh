#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

version_code="$(sed -nE 's/^version:[[:space:]]*[^+]+\+([0-9]+)[[:space:]]*$/\1/p' pubspec.yaml)"
if [[ -z "$version_code" || "$version_code" -le 16 ]]; then
  echo "[android-release] versionCode must exceed accepted Play versionCode 16." >&2
  exit 2
fi
release_sha="$(git rev-parse HEAD)"
[[ "$release_sha" =~ ^[a-f0-9]{40}$ ]] || {
  echo "[android-release] a full commit SHA is required." >&2
  exit 2
}

python3 scripts/verify-release-contract.py \
  --backend-url https://api.svaultai.com/release-contract
flutter build appbundle --release \
  --dart-define="APP_RELEASE=$release_sha" \
  --dart-define-from-file=config/release-contract.production.json \
  --dart-define=CRYPTO_WALLET_DEFAULT_NETWORK=ethereum_mainnet \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_RECEIVE_ENABLED=true \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_ERC20_RECEIVE_ENABLED=true \
  --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=true \
  "$@"

bundle='build/app/outputs/bundle/release/app-release.aab'
[[ -f "$bundle" ]] || {
  echo '[android-release] expected AAB was not produced.' >&2
  exit 3
}
printf 'ANDROID_VERSION_CODE=%s\n' "$version_code"
printf 'ANDROID_AAB=%s\n' "$project_root/$bundle"
printf 'ANDROID_AAB_SHA256=%s\n' "$(sha256sum "$bundle" | awk '{print $1}')"
printf 'ANDROID_STORE_UPLOAD_PERFORMED=false\n'
