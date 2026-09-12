# 2026-07-20: pre-deploy gate that refuses to ship a web bundle
# built with `flutter build web` directly instead of via
# `scripts/build-web-release.{sh,ps1}`.
#
# See the shell twin at scripts/verify-web-release.sh for the full
# problem statement.
#
# Exit codes:
#   0 = clean, safe to deploy
#   2 = missing or malformed artifact - DO NOT DEPLOY
#   3 = internal error (script bug or missing bundle)

$ErrorActionPreference = 'Stop'

$flutterProjectRoot = Split-Path -Parent $PSScriptRoot
$bundleDir = Join-Path $flutterProjectRoot 'build/web'

Write-Host "[verify-web-release] checking bundle at $bundleDir"

if (-not (Test-Path $bundleDir -PathType Container)) {
    Write-Error "[verify-web-release] ERROR: $bundleDir does not exist. Run scripts/build-web-release.ps1 first."
    exit 3
}

$fail = 0
$warn = 0

function Show-Remediation {
    Write-Host ''
    Write-Host '[verify-web-release] TO FIX:'
    Write-Host '[verify-web-release]   Rebuild via the release wrapper, which produces'
    Write-Host '[verify-web-release]   the migration SW, the SW bootstrap, release.json,'
    Write-Host '[verify-web-release]   and bakes APP_RELEASE into main.dart.js:'
    Write-Host ''
    Write-Host '[verify-web-release]       cd vault_ai_frontend'
    Write-Host '[verify-web-release]       .\scripts\build-web-release.ps1     # Windows'
    Write-Host '[verify-web-release]       ./scripts/build-web-release.sh      # bash / macOS'
    Write-Host ''
    Write-Host '[verify-web-release]   Then re-run this verifier before deploying.'
    Write-Host ''
}

# ---- 1) bootstrap.js exists, resolved, contains a 40-hex SHA ----------
$bootstrap = Join-Path $bundleDir 'vaultai-sw-bootstrap.js'
if (-not (Test-Path $bootstrap -PathType Leaf)) {
    Write-Error "[verify-web-release] FAIL: $bootstrap missing. The build ran without the release wrapper."
    $fail++
} else {
    $bootstrapText = Get-Content -Raw -Path $bootstrap
    if ($bootstrapText -like '*__VAULTAI_APP_RELEASE__*') {
        Write-Error '[verify-web-release] FAIL: bootstrap.js still contains the unresolved __VAULTAI_APP_RELEASE__ token.'
        $fail++
    }
    if ($bootstrapText -notmatch '[a-f0-9]{40}') {
        Write-Error '[verify-web-release] FAIL: no 40-char hex SHA found in bootstrap.js.'
        $fail++
    }
}

# ---- 2) release.json exists + valid + commit is 40-hex ----------------
$releaseJsonPath = Join-Path $bundleDir 'release.json'
$expectedSha = $null
if (-not (Test-Path $releaseJsonPath -PathType Leaf)) {
    Write-Error "[verify-web-release] FAIL: $releaseJsonPath missing. AppReleaseController polls this file; without it, the auto-update loop never fires."
    $fail++
} else {
    try {
        $releaseJson = Get-Content -Raw -Path $releaseJsonPath | ConvertFrom-Json -ErrorAction Stop
        if ($releaseJson.commit -match '^[a-f0-9]{40}$') {
            $expectedSha = $releaseJson.commit
        } else {
            Write-Error "[verify-web-release] FAIL: release.json commit field is not a 40-char hex SHA. Got: $($releaseJson.commit)"
            $fail++
        }
        if ($releaseJson.apiContract -ne 'svaultai-core-v2-2026-08-16') {
            Write-Error "[verify-web-release] FAIL: release.json API contract is missing or unexpected. Got: $($releaseJson.apiContract)"
            $fail++
        }
        $expectedFeatures = [ordered]@{
            credentialV2Read  = $true
            credentialV2Write = $false
            credentialV2Migration = $false
            memoryV2Read      = $true
            memoryV2Write     = $true
            memoryV2Migration = $false
            fileV2Read        = $true
            fileV2Write       = $true
            fileV2Migration   = $false
            walletBackupV2Read = $false
            walletBackupV2Write = $false
            walletBackupV2Migration = $false
            walletV2Read = $false
            walletV2Write = $false
            walletV2Migration = $false
            privateVaultLocalRouting = $false
        }
        foreach ($featureName in $expectedFeatures.Keys) {
            $property = $releaseJson.features.PSObject.Properties[$featureName]
            if ($null -eq $property -or [bool]$property.Value -ne $expectedFeatures[$featureName]) {
                Write-Error "[verify-web-release] FAIL: release.json feature '$featureName' is missing or does not match the production contract."
                $fail++
            }
        }
    } catch {
        Write-Error "[verify-web-release] FAIL: release.json is not valid JSON: $_"
        $fail++
    }
}

# ---- 3) flutter_service_worker.js is the migration SW -----------------
$sw = Join-Path $bundleDir 'flutter_service_worker.js'
if (-not (Test-Path $sw -PathType Leaf)) {
    Write-Error "[verify-web-release] FAIL: $sw missing."
    $fail++
} else {
    $swText = Get-Content -Raw -Path $sw
    if ($swText -like '*flutter-app-manifest*') {
        Write-Error @'
[verify-web-release] FAIL: flutter_service_worker.js is Flutter's DEFAULT
[verify-web-release]        offline-first SW (contains 'flutter-app-manifest').
[verify-web-release]        Users with an older SW will KEEP fetching stale
[verify-web-release]        main.dart.js from Cache Storage.
'@
        $fail++
    }
    if ($swText -notlike '*[vaultai-sw]*') {
        Write-Error '[verify-web-release] FAIL: flutter_service_worker.js does not contain the migration-SW signature ''[vaultai-sw]''. Body was not replaced.'
        $fail++
    }
}

# ---- 4) main.dart.js contains the same SHA (APP_RELEASE baked in) ----
$mainJs = Join-Path $bundleDir 'main.dart.js'
if (-not (Test-Path $mainJs -PathType Leaf)) {
    Write-Error "[verify-web-release] FAIL: $mainJs missing."
    $fail++
} elseif ($expectedSha) {
    # Streaming search - main.dart.js can be tens of MB.
    $found = $false
    $sr = [System.IO.StreamReader]::new($mainJs)
    try {
        while (-not $sr.EndOfStream) {
            $line = $sr.ReadLine()
            if ($line -and $line.Contains($expectedSha)) {
                $found = $true
                break
            }
        }
    } finally {
        $sr.Close()
    }
    if (-not $found) {
        Write-Error @"
[verify-web-release] FAIL: main.dart.js does NOT contain the SHA from
[verify-web-release]        release.json ($expectedSha).
[verify-web-release]        --dart-define=APP_RELEASE=<sha> was not passed;
[verify-web-release]        the running bundle self-reports APP_RELEASE=dev
[verify-web-release]        and the update controller silently refuses to fire.
"@
        $fail++
    }
}

# ---- 5) template file leftover (warn only, not blocking) --------------
$templateLeftover = Join-Path $bundleDir 'vaultai-sw-bootstrap.template.js'
if (Test-Path $templateLeftover -PathType Leaf) {
    Write-Warning @'
[verify-web-release] WARN: vaultai-sw-bootstrap.template.js is present in
[verify-web-release]        the bundle. Harmless (its content short-circuits
[verify-web-release]        on the unresolved token) but dead weight in the
[verify-web-release]        deployed bundle. Consider deleting after build.
'@
    $warn++
}

if ($fail -gt 0) {
    Write-Error "[verify-web-release] $fail check(s) failed. DO NOT DEPLOY."
    Show-Remediation
    exit 2
}

if ($warn -gt 0) {
    Write-Host "[verify-web-release] $warn warning(s) - bundle is deployable but review advisories above."
}

Write-Host '[verify-web-release] OK: bundle looks clean.' -ForegroundColor Green
exit 0
