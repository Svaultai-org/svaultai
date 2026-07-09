#!/usr/bin/env bash
#
# Canonical Flutter web launch for VaultAI local dev (bash counterpart
# of run-web.ps1). See that file for the full rationale; the short
# version:
#
#   Flutter web stores its device_id in localStorage, which the browser
#   scopes per origin (scheme + host + port). Every fresh `flutter run`
#   port = fresh origin = fresh device_id. Pinning --web-port and
#   --web-hostname makes the origin stable so the device_id persists
#   across rebuilds and the trusted_devices table stops accumulating
#   stale rows.
#
# Usage:
#   ./scripts/run-web.sh
#   ./scripts/run-web.sh --release            # extra flutter flags pass through
#
# Production behaviour is unchanged — this script only governs the
# local dev origin.

set -euo pipefail

# Resolve to the Flutter project root regardless of where the caller
# invoked the script from. ${BASH_SOURCE[0]} is this file, dirname
# gives scripts/, parent is the project root.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
flutter_project_root="$(dirname "${script_dir}")"

cd "${flutter_project_root}"

echo "[vault-dev] flutter run -d chrome --web-port=5173 --web-hostname=localhost $*"
exec flutter run -d chrome --web-port=5173 --web-hostname=localhost "$@"
