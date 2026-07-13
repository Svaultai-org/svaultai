#!/usr/bin/env bash
# 2026-07-14 (Round 10 — stale-cache fix): canonical VaultAI web
# release-build script. POSIX sibling of build-web-release.ps1.
#
# See build-web-release.ps1 for the full contract. In short:
#
#   * runs `flutter build web --release --pwa-strategy=none
#     --dart-define=APP_RELEASE=<sha>` (+ passed extras)
#   * writes `build/web/release.json` with commit + builtAt
#   * does NOT deploy, touch prod env, run migrations, or unpause
#     ETH/SOL/TRON.
#
# Usage:
#
#   ./scripts/build-web-release.sh
#   ./scripts/build-web-release.sh --dart-define=BACKEND_BASE_URL=https://api.svaultai.com

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
cd "$project_root"

sha_full="$(git rev-parse HEAD 2>/dev/null || echo dev)"
sha_short="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
built_at="$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")"

echo "[vault-release] APP_RELEASE=$sha_full"
echo "[vault-release] (display-only short: $sha_short)"

# 2026-07-14 (Round 11 — release-ID canonicalization): pass the
# full 40-char SHA. Comparison at runtime is full-vs-full.
flutter build web --release \
    --pwa-strategy=none \
    --dart-define=APP_RELEASE="$sha_full" \
    "$@"

# Post-build: overwrite the empty stub with a migration SW that
# retires the offline-first Flutter SW on existing installed
# clients. See scripts/migration-service-worker.js for details.
sw_source="$script_dir/migration-service-worker.js"
sw_dest="$project_root/build/web/flutter_service_worker.js"
if [ -f "$sw_source" ]; then
    cp -f "$sw_source" "$sw_dest"
    echo "[vault-release] wrote migration SW to $sw_dest"
else
    echo "[vault-release] WARNING: migration-service-worker.js missing; SW stays empty."
fi

# Write build/web/release.json using printf so we don't depend on jq.
release_path="$project_root/build/web/release.json"
printf '{"commit":"%s","commitShort":"%s","builtAt":"%s"}\n' \
    "$sha_full" "$sha_short" "$built_at" > "$release_path"

echo "[vault-release] wrote $release_path"
echo "[vault-release] built bundle: $project_root/build/web"
