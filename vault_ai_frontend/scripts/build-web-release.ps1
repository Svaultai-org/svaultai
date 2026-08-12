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
#   5. Writes `build/web/release.json`.
#
# Usage:
#
#   .\scripts\build-web-release.ps1
#   $env:RELEASE_SHA = '<full-sha>'; .\scripts\build-web-release.ps1
#   .\scripts\build-web-release.ps1 --allow-dev-release   # LOCAL only

$ErrorActionPreference = 'Stop'

$flutterProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $flutterProjectRoot
try {
    # ---- Resolve RELEASE SHA (fail-closed) ----
    $allowDev = $false
    $flutterExtraArgs = @()
    foreach ($arg in $args) {
        if ($arg -eq '--allow-dev-release') {
            $allowDev = $true
        } elseif ($arg -match '^--dart-define=(MEMORY_V2_|FILE_V2_|WALLET_BACKUP_V2_|WALLET_V2_|PRIVATE_VAULT_LOCAL_ROUTING_ENABLED=)') {
            Write-Error '[vault-release] production V2 flags are pinned false by this script.'
            exit 2
        } else {
            $flutterExtraArgs += $arg
        }
    }

    $shaFull = ''
    if ($env:RELEASE_SHA) {
        $shaFull = $env:RELEASE_SHA.Trim()
        Write-Host "[vault-release] using RELEASE_SHA env var" -ForegroundColor Cyan
    } else {
        try {
            $probe = (git rev-parse HEAD 2>$null)
            if ($LASTEXITCODE -eq 0 -and $probe) {
                $shaFull = $probe.Trim()
            }
        } catch {}
    }

    if ($shaFull -notmatch '^[a-f0-9]{40}$') {
        if ($allowDev) {
            $shaFull = 'dev0000000000000000000000000000000000000dev'
            Write-Host "[vault-release] WARNING: --allow-dev-release set; using synthetic 'dev' SHA." -ForegroundColor Yellow
        } else {
            Write-Error @"
[vault-release] ERROR: cannot resolve a real 40-char commit SHA.
  set `$env:RELEASE_SHA = '<full-sha>' (archive host)
  or pass --allow-dev-release for a local-only build.
This guard prevents shipping a production release with APP_RELEASE=dev
(which would permanently show the update banner and never converge).
"@
            exit 2
        }
    }

    $shaShort = $shaFull.Substring(0, 7)
    $builtAt = (Get-Date).ToUniversalTime().ToString(
        "yyyy-MM-ddTHH:mm:ss.fffZ"
    )

    Write-Host "[vault-release] APP_RELEASE=$shaFull" -ForegroundColor Cyan
    Write-Host "[vault-release] (display-only short: $shaShort)" -ForegroundColor Cyan

    # ---- Build ----
    $buildArgs = @(
        'build', 'web', '--release',
        '--pwa-strategy=none',
        "--dart-define=APP_RELEASE=$shaFull",
        '--dart-define=MEMORY_V2_READ_ENABLED=false',
        '--dart-define=MEMORY_V2_WRITE_ENABLED=false',
        '--dart-define=MEMORY_V2_MIGRATION_ENABLED=false',
        '--dart-define=FILE_V2_READ_ENABLED=false',
        '--dart-define=FILE_V2_WRITE_ENABLED=false',
        '--dart-define=FILE_V2_MIGRATION_ENABLED=false',
        '--dart-define=WALLET_BACKUP_V2_READ_ENABLED=false',
        '--dart-define=WALLET_BACKUP_V2_WRITE_ENABLED=false',
        '--dart-define=WALLET_BACKUP_V2_MIGRATION_ENABLED=false',
        '--dart-define=WALLET_V2_READ_ENABLED=false',
        '--dart-define=WALLET_V2_WRITE_ENABLED=false',
        '--dart-define=WALLET_V2_MIGRATION_ENABLED=false',
        '--dart-define=PRIVATE_VAULT_LOCAL_ROUTING_ENABLED=false'
        '--dart-define=CRYPTO_WALLET_DEFAULT_NETWORK=ethereum_mainnet'
        '--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_RECEIVE_ENABLED=true'
        '--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_ERC20_RECEIVE_ENABLED=true'
        '--dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=false'
    ) + $flutterExtraArgs
    Write-Host "[vault-release] flutter $($buildArgs -join ' ')" -ForegroundColor Cyan
    flutter @buildArgs

    # ---- Migration SW ----
    $swSource = Join-Path $PSScriptRoot 'migration-service-worker.js'
    $swDest = Join-Path $flutterProjectRoot 'build/web/flutter_service_worker.js'
    if (-not (Test-Path $swSource)) {
        Write-Error "[vault-release] ERROR: migration-service-worker.js missing at $swSource"
        exit 3
    }
    Copy-Item -Force -Path $swSource -Destination $swDest
    Write-Host "[vault-release] wrote migration SW to $swDest" -ForegroundColor Green

    # ---- SW-registration bootstrap ----
    $tplSource = Join-Path $flutterProjectRoot 'web/vaultai-sw-bootstrap.template.js'
    $tplDest = Join-Path $flutterProjectRoot 'build/web/vaultai-sw-bootstrap.js'
    if (-not (Test-Path $tplSource)) {
        Write-Error "[vault-release] ERROR: vaultai-sw-bootstrap.template.js missing at $tplSource"
        exit 4
    }
    $tplContent = Get-Content -Raw -Path $tplSource
    $tplContent = $tplContent.Replace('__VAULTAI_APP_RELEASE__', $shaFull)
    [System.IO.File]::WriteAllText(
        $tplDest, $tplContent, [System.Text.UTF8Encoding]::new($false)
    )
    if ((Get-Content -Raw -Path $tplDest) -like "*__VAULTAI_APP_RELEASE__*") {
        Write-Error "[vault-release] ERROR: token substitution failed for $tplDest"
        exit 5
    }
    if ((Get-Content -Raw -Path $tplDest) -notlike "*$shaFull*") {
        Write-Error "[vault-release] ERROR: full SHA missing from $tplDest"
        exit 6
    }
    Write-Host "[vault-release] wrote SW-registration bootstrap to $tplDest" -ForegroundColor Green

    $tplLeftover = Join-Path $flutterProjectRoot 'build/web/vaultai-sw-bootstrap.template.js'
    if (Test-Path $tplLeftover) {
        Remove-Item -Force -Path $tplLeftover
        Write-Host "[vault-release] removed template leftover $tplLeftover" -ForegroundColor Green
    }

    # ---- release.json ----
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
