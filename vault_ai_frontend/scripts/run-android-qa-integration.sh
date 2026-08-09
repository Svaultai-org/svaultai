#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FLUTTER_BIN="${FLUTTER_BIN:-/Users/chosenbrain/development/flutter/bin/flutter}"
TARGET="${1:?integration_test target is required}"
shift

cd "$ROOT_DIR"
exec "$FLUTTER_BIN" drive \
  --driver=test_driver/integration_test.dart \
  --target="$TARGET" \
  --android-project-arg=VAULTAI_QA_RELEASE=true \
  "$@"
