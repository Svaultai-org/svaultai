#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CA_PATH="${SVaultAI_QA_CA_PATH:-$HOME/Library/Application Support/SVaultAI-QA/secrets/qa-ca.crt}"
if [[ ! -r "$CA_PATH" ]]; then
  echo "qa_ca_unavailable" >&2
  exit 1
fi
CA_B64="$(base64 < "$CA_PATH" | tr -d '\n')"
cd "$ROOT_DIR"
FLUTTER_BIN="${FLUTTER_BIN:-/Users/chosenbrain/development/flutter/bin/flutter}"
"$FLUTTER_BIN" build apk --debug -PVAULTAI_QA_RELEASE=true \
  --dart-define=BACKEND_BASE_URL=https://10.0.2.2:8444 \
  --dart-define=QA_TRUST_LOCAL_CA=true \
  --dart-define=QA_AUTH_DIAGNOSTICS=true \
  --dart-define="QA_CA_B64=$CA_B64" \
  --dart-define=ZK_V2_READ_ENABLED=true \
  --dart-define=ZK_V2_WRITE_ENABLED=true \
  --dart-define=ZK_V2_MIGRATION_ENABLED=true "$@"
