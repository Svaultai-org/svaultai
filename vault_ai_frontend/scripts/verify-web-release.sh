#!/usr/bin/env bash
# 2026-07-20: pre-deploy gate that refuses to ship a web bundle that
# was built with `flutter build web` directly instead of via
# `scripts/build-web-release.{sh,ps1}`.
#
# WHAT WENT WRONG THAT MADE THIS SCRIPT NECESSARY
# ================================================
#
# A production deploy shipped a `build/web` that:
#   * kept Flutter's default offline-first `flutter_service_worker.js`
#     instead of the migration SW body
#   * contained `vaultai-sw-bootstrap.template.js` but no resolved
#     `vaultai-sw-bootstrap.js`
#   * had no `release.json`
#   * baked `APP_RELEASE=dev` into `main.dart.js`
#
# Every one of these is what `flutter build web` produces WITHOUT the
# release wrapper. Users whose browsers had an older Flutter SW
# installed kept fetching the OLD `main.dart.js` from that SW's cache,
# and no migration ever kicked in. That's the "PIN loop" symptom in
# production — the browser is still running pre-00ac5c5 code, hits
# the crypto cache-key mismatch, and the route guard redirects back
# to /pin.
#
# WHAT THIS SCRIPT CHECKS
# =======================
#
# Run this AFTER a release build and BEFORE scp'ing to prod. Exits
# non-zero (and prints a specific remediation) if any check fails.
#
# 1. `build/web/vaultai-sw-bootstrap.js` exists AND the literal
#    `__VAULTAI_APP_RELEASE__` token is gone AND a 40-char hex SHA
#    is present.
# 2. `build/web/release.json` exists, is valid JSON, and its `commit`
#    field is a 40-char hex SHA.
# 3. `build/web/flutter_service_worker.js` is the MIGRATION SW body
#    (contains `[vaultai-sw]`), NOT Flutter's default offline-first
#    SW (contains `flutter-app-manifest`).
# 4. `build/web/main.dart.js` contains the same 40-char SHA — proof
#    that `--dart-define=APP_RELEASE=<sha>` reached the compiler and
#    the running bundle knows its own release ID.
# 5. `build/web/vaultai-sw-bootstrap.template.js` is not present
#    (Flutter copies it through by default; the wrapper script does
#    NOT delete it — but leaving it public is confusing. Warn only.)
#
# EXIT CODES
# ==========
#
#   0 = clean, safe to deploy
#   2 = missing or malformed artifact — DO NOT DEPLOY
#   3 = internal error (script bug or missing bundle)

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
bundle_dir="$project_root/build/web"

echo "[verify-web-release] checking bundle at $bundle_dir"

if [ ! -d "$bundle_dir" ]; then
    echo "[verify-web-release] ERROR: $bundle_dir does not exist." >&2
    echo "[verify-web-release]   Run scripts/build-web-release.{sh,ps1} first." >&2
    exit 3
fi

fail=0
warn=0

remediation() {
    cat >&2 <<REMEDIATE

[verify-web-release] TO FIX:
[verify-web-release]   Rebuild via the release wrapper, which produces
[verify-web-release]   the migration SW, the SW bootstrap, release.json,
[verify-web-release]   and bakes APP_RELEASE into main.dart.js:
[verify-web-release]
[verify-web-release]       cd vault_ai_frontend
[verify-web-release]       ./scripts/build-web-release.sh          # bash / macOS
[verify-web-release]       .\\scripts\\build-web-release.ps1       # Windows
[verify-web-release]
[verify-web-release]   Then re-run this verifier before deploying.

REMEDIATE
}

# ---- 1) bootstrap.js exists, resolved, contains a 40-hex SHA ----------
bootstrap="$bundle_dir/vaultai-sw-bootstrap.js"
if [ ! -f "$bootstrap" ]; then
    echo "[verify-web-release] FAIL: $bootstrap missing." >&2
    echo "[verify-web-release]   The build ran without the release wrapper." >&2
    fail=$((fail+1))
else
    if grep -q "__VAULTAI_APP_RELEASE__" "$bootstrap"; then
        echo "[verify-web-release] FAIL: bootstrap.js still contains the" >&2
        echo "[verify-web-release]        unresolved __VAULTAI_APP_RELEASE__ token." >&2
        fail=$((fail+1))
    fi
    if ! grep -qE "[a-f0-9]{40}" "$bootstrap"; then
        echo "[verify-web-release] FAIL: no 40-char hex SHA found in bootstrap.js." >&2
        fail=$((fail+1))
    fi
fi

# ---- 2) release.json exists + valid + commit is 40-hex ----------------
release_json="$bundle_dir/release.json"
if [ ! -f "$release_json" ]; then
    echo "[verify-web-release] FAIL: $release_json missing." >&2
    echo "[verify-web-release]   AppReleaseController polls this file; without" >&2
    echo "[verify-web-release]   it, the auto-update loop never fires." >&2
    fail=$((fail+1))
else
    commit_line="$(grep -oE '"commit"[[:space:]]*:[[:space:]]*"[a-f0-9]{40}"' "$release_json" || true)"
    if [ -z "$commit_line" ]; then
        echo "[verify-web-release] FAIL: release.json missing/invalid \"commit\" field." >&2
        echo "[verify-web-release]   contents: $(cat "$release_json")" >&2
        fail=$((fail+1))
    fi
    if ! grep -q '"apiContract":"svaultai-core-v2-2026-08-16"' "$release_json"; then
        echo "[verify-web-release] FAIL: release.json API contract is missing or unexpected." >&2
        fail=$((fail+1))
    fi
    for expected_feature in \
        '"credentialV2Read":true' \
        '"credentialV2Write":false' \
        '"credentialV2Migration":false' \
        '"memoryV2Read":true' \
        '"memoryV2Write":true' \
        '"memoryV2Migration":false' \
        '"fileV2Read":true' \
        '"fileV2Write":true' \
        '"fileV2Migration":false' \
        '"walletBackupV2Read":false' \
        '"walletBackupV2Write":false' \
        '"walletBackupV2Migration":false' \
        '"walletV2Read":false' \
        '"walletV2Write":false' \
        '"walletV2Migration":false' \
        '"privateVaultLocalRouting":false'; do
        if ! grep -q "$expected_feature" "$release_json"; then
            echo "[verify-web-release] FAIL: release.json feature contract mismatch: $expected_feature" >&2
            fail=$((fail+1))
        fi
    done
fi

# ---- 3) flutter_service_worker.js is the migration SW -----------------
sw="$bundle_dir/flutter_service_worker.js"
if [ ! -f "$sw" ]; then
    echo "[verify-web-release] FAIL: $sw missing." >&2
    fail=$((fail+1))
else
    if grep -q "flutter-app-manifest" "$sw"; then
        echo "[verify-web-release] FAIL: flutter_service_worker.js is Flutter's" >&2
        echo "[verify-web-release]        DEFAULT offline-first SW (contains" >&2
        echo "[verify-web-release]        'flutter-app-manifest'). Users with an" >&2
        echo "[verify-web-release]        older SW will KEEP fetching stale" >&2
        echo "[verify-web-release]        main.dart.js from Cache Storage." >&2
        fail=$((fail+1))
    fi
    if ! grep -q "\\[vaultai-sw\\]" "$sw"; then
        echo "[verify-web-release] FAIL: flutter_service_worker.js does not" >&2
        echo "[verify-web-release]        contain the migration-SW signature" >&2
        echo "[verify-web-release]        '[vaultai-sw]'. Body was not replaced." >&2
        fail=$((fail+1))
    fi
fi

# ---- 4) main.dart.js contains the same SHA (APP_RELEASE baked in) ----
main_js="$bundle_dir/main.dart.js"
if [ ! -f "$main_js" ]; then
    echo "[verify-web-release] FAIL: $main_js missing." >&2
    fail=$((fail+1))
else
    if [ -f "$release_json" ]; then
        expected_sha="$(sed -nE 's/.*"commit"[[:space:]]*:[[:space:]]*"([a-f0-9]{40})".*/\1/p' "$release_json" || true)"
        if [ -n "$expected_sha" ]; then
            if ! grep -q "$expected_sha" "$main_js"; then
                echo "[verify-web-release] FAIL: main.dart.js does NOT contain the" >&2
                echo "[verify-web-release]        SHA from release.json ($expected_sha)." >&2
                echo "[verify-web-release]        --dart-define=APP_RELEASE=<sha> was not passed;" >&2
                echo "[verify-web-release]        the running bundle self-reports APP_RELEASE=dev" >&2
                echo "[verify-web-release]        and the update controller silently refuses to" >&2
                echo "[verify-web-release]        fire." >&2
                fail=$((fail+1))
            fi
        fi
    fi
fi

# ---- 5) template file leftover (warn only, not blocking) --------------
template_leftover="$bundle_dir/vaultai-sw-bootstrap.template.js"
if [ -f "$template_leftover" ]; then
    echo "[verify-web-release] WARN: $template_leftover is present in the bundle." >&2
    echo "[verify-web-release]        This file is harmless (its content" >&2
    echo "[verify-web-release]        short-circuits on the unresolved token)" >&2
    echo "[verify-web-release]        but it's dead weight in the deployed" >&2
    echo "[verify-web-release]        bundle. Consider deleting it after build." >&2
    warn=$((warn+1))
fi

if [ "$fail" -gt 0 ]; then
    echo "[verify-web-release] $fail check(s) failed. DO NOT DEPLOY." >&2
    remediation
    exit 2
fi

if [ "$warn" -gt 0 ]; then
    echo "[verify-web-release] $warn warning(s) — bundle is deployable but review advisories above."
fi

echo "[verify-web-release] OK: bundle looks clean."
exit 0
