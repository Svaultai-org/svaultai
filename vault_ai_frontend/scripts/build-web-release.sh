#!/usr/bin/env bash
# 2026-07-14 (Round 12): canonical VaultAI web release-build script.
#
# What this script does:
#
#   1. Resolves the RELEASE SHA:
#        - If env var `RELEASE_SHA` is set → use it verbatim (must
#          match ^[a-f0-9]{40}$).
#        - Else `git rev-parse HEAD` (must succeed with 40 chars).
#        - Else fail closed UNLESS `--allow-dev-release` is passed.
#          Never silently produce a production release with
#          `APP_RELEASE=dev`.
#   2. Runs `flutter build web --release --pwa-strategy=none
#      --dart-define=APP_RELEASE=<full-sha>` (+ passed extras).
#   3. Overwrites `build/web/flutter_service_worker.js` with the
#      migration SW body (`scripts/migration-service-worker.js`).
#   4. Substitutes `__VAULTAI_APP_RELEASE__` in the SW bootstrap
#      template with the FULL SHA and writes to
#      `build/web/vaultai-sw-bootstrap.js`.
#   5. Writes `build/web/release.json` with `{commit, commitShort,
#      builtAt}`.
#
# What this script does NOT do:
#
#   * touch production env vars
#   * touch a live Nginx config
#   * run alembic migrations
#   * unpause ETH / SOL / TRON
#   * copy files onto app.svaultai.com.
#
# Usage:
#
#   ./scripts/build-web-release.sh
#   RELEASE_SHA=<full-sha> ./scripts/build-web-release.sh   # archive-host build
#   ./scripts/build-web-release.sh --allow-dev-release      # ONLY for local dev
#
# Any extra args are passed straight through to `flutter build`.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
cd "$project_root"

allow_dev=0
declare -a flutter_extra_args=()
for arg in "$@"; do
    case "$arg" in
        --allow-dev-release)
            allow_dev=1
            ;;
        --dart-define=MEMORY_V2_*|--dart-define=FILE_V2_*|--dart-define=WALLET_BACKUP_V2_*|--dart-define=WALLET_V2_*|--dart-define=PRIVATE_VAULT_LOCAL_ROUTING_ENABLED=*)
            echo "[vault-release] ERROR: production V2 flags are pinned false by this script." >&2
            exit 2
            ;;
        *)
            flutter_extra_args+=("$arg")
            ;;
    esac
done

# 1. Resolve RELEASE_SHA — fail closed if we can't obtain a real
#    40-char SHA and `--allow-dev-release` was not passed.
sha_full=""
if [ -n "${RELEASE_SHA:-}" ]; then
    sha_full="$RELEASE_SHA"
    echo "[vault-release] using RELEASE_SHA env var"
elif [ -d .git ] || git rev-parse --git-dir >/dev/null 2>&1; then
    sha_full="$(git rev-parse HEAD 2>/dev/null || true)"
fi

if ! echo "$sha_full" | grep -qE '^[a-f0-9]{40}$'; then
    if [ "$allow_dev" -eq 1 ]; then
        sha_full="dev0000000000000000000000000000000000000dev"
        echo "[vault-release] WARNING: --allow-dev-release set; using synthetic 'dev' SHA."
    else
        echo "[vault-release] ERROR: cannot resolve a real 40-char commit SHA." >&2
        echo "[vault-release]   set RELEASE_SHA=<full-sha> as an env var, or" >&2
        echo "[vault-release]   pass --allow-dev-release for a local-only build." >&2
        echo "[vault-release] This guard prevents shipping a production release" >&2
        echo "[vault-release] with APP_RELEASE=dev (which would permanently show" >&2
        echo "[vault-release] the update banner and never converge)." >&2
        exit 2
    fi
fi

sha_short="$(printf '%s' "$sha_full" | cut -c1-7)"
built_at="$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")"

echo "[vault-release] APP_RELEASE=$sha_full"
echo "[vault-release] (display-only short: $sha_short)"

# 2. Build. --pwa-strategy=none writes an empty SW stub; we
#    overwrite it in step 3 with the migration SW body.
flutter build web --release \
    --pwa-strategy=none \
    --dart-define=APP_RELEASE="$sha_full" \
    --dart-define=MEMORY_V2_READ_ENABLED=false \
    --dart-define=MEMORY_V2_WRITE_ENABLED=false \
    --dart-define=MEMORY_V2_MIGRATION_ENABLED=false \
    --dart-define=FILE_V2_READ_ENABLED=false \
    --dart-define=FILE_V2_WRITE_ENABLED=false \
    --dart-define=FILE_V2_MIGRATION_ENABLED=false \
    --dart-define=WALLET_BACKUP_V2_READ_ENABLED=false \
    --dart-define=WALLET_BACKUP_V2_WRITE_ENABLED=false \
    --dart-define=WALLET_BACKUP_V2_MIGRATION_ENABLED=false \
    --dart-define=WALLET_V2_READ_ENABLED=false \
    --dart-define=WALLET_V2_WRITE_ENABLED=false \
    --dart-define=WALLET_V2_MIGRATION_ENABLED=false \
    --dart-define=PRIVATE_VAULT_LOCAL_ROUTING_ENABLED=false \
    "${flutter_extra_args[@]}"

# 3. Migration SW.
sw_source="$script_dir/migration-service-worker.js"
sw_dest="$project_root/build/web/flutter_service_worker.js"
if [ ! -f "$sw_source" ]; then
    echo "[vault-release] ERROR: migration-service-worker.js missing at $sw_source." >&2
    exit 3
fi
cp -f "$sw_source" "$sw_dest"
echo "[vault-release] wrote migration SW to $sw_dest"

# 4. Bootstrap: substitute __VAULTAI_APP_RELEASE__ → full SHA.
tpl_source="$project_root/web/vaultai-sw-bootstrap.template.js"
tpl_dest="$project_root/build/web/vaultai-sw-bootstrap.js"
if [ ! -f "$tpl_source" ]; then
    echo "[vault-release] ERROR: vaultai-sw-bootstrap.template.js missing." >&2
    exit 4
fi
# Portable sed alternative — POSIX awk substitutes the literal
# token exactly once.
awk -v release="$sha_full" '{
    n = index($0, "__VAULTAI_APP_RELEASE__");
    while (n > 0) {
        $0 = substr($0, 1, n-1) release substr($0, n+length("__VAULTAI_APP_RELEASE__"));
        n = index($0, "__VAULTAI_APP_RELEASE__");
    }
    print $0;
}' "$tpl_source" > "$tpl_dest"

# Sanity check: the literal token MUST NOT survive substitution.
if grep -q "__VAULTAI_APP_RELEASE__" "$tpl_dest"; then
    echo "[vault-release] ERROR: token substitution failed for $tpl_dest" >&2
    exit 5
fi
# Sanity check: the full SHA MUST appear in the bootstrap.
if ! grep -q "$sha_full" "$tpl_dest"; then
    echo "[vault-release] ERROR: full SHA missing from $tpl_dest" >&2
    exit 6
fi
echo "[vault-release] wrote SW-registration bootstrap to $tpl_dest"

tpl_leftover="$project_root/build/web/vaultai-sw-bootstrap.template.js"
if [ -f "$tpl_leftover" ]; then
    rm -f "$tpl_leftover"
    echo "[vault-release] removed template leftover $tpl_leftover"
fi

# 5. release.json.
release_path="$project_root/build/web/release.json"
printf '{"commit":"%s","commitShort":"%s","builtAt":"%s"}\n' \
    "$sha_full" "$sha_short" "$built_at" > "$release_path"

echo "[vault-release] wrote $release_path"
echo "[vault-release] built bundle: $project_root/build/web"
