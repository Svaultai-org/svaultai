# 2026-07-14 (Round 10 — stale-cache fix): canonical VaultAI web
# release-build script.
#
# What this script does:
#
#   1. Resolves the current git commit SHA (7-char short + full).
#   2. Runs `flutter build web --release` with:
#        --pwa-strategy=none          # empty service worker, no
#                                     # offline-first shell cache
#        --dart-define=APP_RELEASE=<sha> # embed release identifier
#      plus any additional --dart-define arguments the caller passes.
#   3. Writes a small `release.json` manifest into `build/web/`:
#        {
#          "commit":  "<full sha>",
#          "commitShort": "<short sha>",
#          "builtAt": "<iso8601 UTC>"
#        }
#   4. Emits the actual bundle path so the caller can rsync/copy
#      it into place atomically.
#
# What this script does NOT do:
#
#   * touch production env vars
#   * touch a live Nginx config
#   * run alembic migrations
#   * unpause ETH / SOL / TRON
#   * copy files onto app.svaultai.com (leave that to the deploy
#     runbook — see docs/DEPLOYMENT_RUNBOOK.md).
#
# Usage:
#
#   .\scripts\build-web-release.ps1
#   .\scripts\build-web-release.ps1 --dart-define=BACKEND_BASE_URL=https://api.svaultai.com --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=true

$ErrorActionPreference = 'Stop'

$flutterProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $flutterProjectRoot
try {
    # Resolve commit SHA. Fall back to `dev` for tree-only builds.
    $shaFull = ''
    $shaShort = ''
    try {
        $shaFull = (git rev-parse HEAD 2>$null).Trim()
        $shaShort = (git rev-parse --short HEAD 2>$null).Trim()
    } catch {}
    if (-not $shaFull -or -not $shaShort) {
        $shaFull = 'dev'
        $shaShort = 'dev'
        Write-Host "[vault-release] git SHA not resolvable; using 'dev'." -ForegroundColor Yellow
    }

    # ISO-8601 UTC. Do not use tz-local — release manifests must be
    # comparable across build hosts.
    $builtAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")

    Write-Host "[vault-release] APP_RELEASE=$shaFull" -ForegroundColor Cyan
    Write-Host "[vault-release] (display-only short: $shaShort)" -ForegroundColor Cyan

    # 2026-07-14 (Round 11 — release-ID canonicalization):
    # ALWAYS embed the full 40-character SHA. The comparison
    # in AppReleaseController is full-SHA vs `release.json.commit`
    # (also full SHA). Passing the short SHA here would guarantee
    # a permanent updateAvailable=true because
    # `<7 chars> != <40 chars>` is always true. `commitShort` in
    # release.json is display-only.
    $buildArgs = @(
        'build', 'web', '--release',
        '--pwa-strategy=none',
        "--dart-define=APP_RELEASE=$shaFull"
    ) + $args
    Write-Host "[vault-release] flutter $($buildArgs -join ' ')" -ForegroundColor Cyan
    flutter @buildArgs

    # Post-build: replace the empty --pwa-strategy=none stub with a
    # migration service worker that:
    #   - skipWaiting() on install so it activates ahead of the
    #     old offline-first SW without waiting for tabs to close;
    #   - clients.claim() on activate + delete every flutter*
    #     cache from Cache Storage;
    #   - forces each currently-controlled tab to navigate once so
    #     it fetches the new bundle (which contains
    #     AppReleaseController — that runs every subsequent
    #     update via /release.json).
    # See scripts/migration-service-worker.js for the source.
    $swSourcePath = Join-Path $PSScriptRoot 'migration-service-worker.js'
    $swDestPath = Join-Path $flutterProjectRoot 'build/web/flutter_service_worker.js'
    if (Test-Path $swSourcePath) {
        Copy-Item -Force -Path $swSourcePath -Destination $swDestPath
        Write-Host "[vault-release] wrote migration SW to $swDestPath" -ForegroundColor Green
    } else {
        Write-Host "[vault-release] WARNING: migration-service-worker.js missing; SW stays empty." -ForegroundColor Yellow
    }

    # Write release.json into build/web so Nginx can serve it as
    # /release.json with `Cache-Control: no-store`.
    $releaseJson = @{
        commit      = $shaFull
        commitShort = $shaShort
        builtAt     = $builtAt
    } | ConvertTo-Json -Compress
    $releasePath = Join-Path $flutterProjectRoot 'build/web/release.json'
    [System.IO.File]::WriteAllText(
        $releasePath, $releaseJson, [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host "[vault-release] wrote $releasePath" -ForegroundColor Green
    Write-Host "[vault-release] built bundle: $(Join-Path $flutterProjectRoot 'build/web')"
}
finally {
    Pop-Location
}
