#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$repo_dir/vault_ai_backend"
python_bin="${PYTHON_BIN:-python3}"
if ! "$python_bin" -c 'import pytest' >/dev/null 2>&1; then
  echo "pytest is unavailable for $python_bin; set PYTHON_BIN to the release-test environment." >&2
  exit 127
fi
export DATABASE_URL="${DATABASE_URL:-postgresql://release_gate:release_gate@127.0.0.1:1/release_gate}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-test-only-release-gate}"
export CORS_ALLOWED_ORIGIN_REGEX="${CORS_ALLOWED_ORIGIN_REGEX:-https://app\\.example\\.test}"
"$python_bin" -m pytest -q \
  test_username_blind_index_2026_07_20.py \
  test_durable_personal_memory_2026_08_02.py \
  test_memory_v2_lookup_index_repair_2026_08_11.py \
  test_existing_credential_release_blocker_2026_08_17.py \
  test_list_secure_items_route_2026_06_28.py \
  test_file_v2_contract.py \
  test_document_extraction_field_fidelity_2026_08_19.py \
  test_general_chat_routing_regression_2026_08_04.py \
  test_provider_neutral_billing_2026_08_14.py

cd "$repo_dir/vault_ai_frontend"
flutter_bin="${FLUTTER_BIN:-flutter}"
if ! command -v "$flutter_bin" >/dev/null 2>&1; then
  configured_sdk="$(sed -n 's/^flutter.sdk=//p' android/local.properties 2>/dev/null | head -1)"
  if [[ -n "$configured_sdk" && -x "$configured_sdk/bin/flutter" ]]; then
    flutter_bin="$configured_sdk/bin/flutter"
  else
    echo "Flutter SDK not found; set FLUTTER_BIN." >&2
    exit 127
  fi
fi
frontend_tests=( \
  test/zk_auth_login_legacy_retry_2026_07_27_test.dart \
  test/vault_handle_ui_leak_2026_08_16_test.dart \
  test/memory_page_mask_and_editor_test.dart \
  test/credential_v2_end_to_end_2026_08_07_test.dart \
  test/credential_natural_language_lookup_2026_08_16_test.dart \
  test/private_inventory_arbitration_test.dart \
  test/session_rehydration_release_gate_2026_08_24_test.dart \
  test/document_extraction_field_fidelity_2026_08_19_test.dart \
  test/vault_local_file_lookup_2026_07_29_test.dart \
  test/chat_operation_queue_test.dart
)

# Apple release worktrees carry additional iOS-only regression suites. Keep
# the shared-main gate runnable while automatically including those suites
# whenever the Apple files are present.
for apple_test in \
  test/apple_storekit_billing_controller_test.dart \
  test/apple_storage_plan_selector_test.dart; do
  if [[ -f "$apple_test" ]]; then
    frontend_tests+=("$apple_test")
  fi
done

"$flutter_bin" test "${frontend_tests[@]}"
