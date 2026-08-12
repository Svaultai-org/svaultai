#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FLUTTER_BIN="${FLUTTER_BIN:-/Users/chosenbrain/development/flutter/bin/flutter}"
TARGET="${1:?integration_test target is required}"
shift

ADB_BIN="${ADB_BIN:-/Users/chosenbrain/Library/Android/sdk/platform-tools/adb}"
if [[ "${QA_RESET_APP_STATE:-true}" == "true" ]]; then
  "$ADB_BIN" shell pm clear com.svaultai.app.qa >/dev/null || true
fi

cd "$ROOT_DIR"
exec "$FLUTTER_BIN" drive \
  --driver=test_driver/integration_test.dart \
  --target="$TARGET" \
  --android-project-arg=VAULTAI_QA_RELEASE=true \
  --dart-define=PRIVATE_VAULT_LOCAL_ROUTING_ENABLED=true \
  "$@"
