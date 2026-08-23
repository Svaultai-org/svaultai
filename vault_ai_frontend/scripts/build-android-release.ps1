$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $versionLine = Select-String -Path 'pubspec.yaml' -Pattern '^version:\s*[^+]+\+(\d+)\s*$'
    if (-not $versionLine) {
        throw '[android-release] pubspec versionCode is missing.'
    }
    $versionCode = [int]$versionLine.Matches[0].Groups[1].Value
    if ($versionCode -le 19) {
        throw "[android-release] versionCode $versionCode must exceed uploaded Play versionCode 19."
    }

    $releaseSha = (git rev-parse HEAD).Trim()
    if ($releaseSha -notmatch '^[a-f0-9]{40}$') {
        throw '[android-release] a full commit SHA is required.'
    }

    python scripts/verify-release-contract.py --backend-url https://api.svaultai.com/release-contract
    if ($LASTEXITCODE -ne 0) {
        throw '[android-release] live backend feature contract is incompatible.'
    }

    flutter build appbundle --release `
        --dart-define="APP_RELEASE=$releaseSha" `
        --dart-define-from-file=config/release-contract.production.json `
        --dart-define=CRYPTO_WALLET_DEFAULT_NETWORK=ethereum_mainnet `
        --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_RECEIVE_ENABLED=true `
        --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_ERC20_RECEIVE_ENABLED=true `
        --dart-define=CRYPTO_WALLET_ENGINE_MAINNET_SEND_ENABLED=true `
        @args
    if ($LASTEXITCODE -ne 0) {
        throw '[android-release] Flutter app bundle build failed.'
    }

    $bundle = 'build\app\outputs\bundle\release\app-release.aab'
    if (-not (Test-Path -LiteralPath $bundle)) {
        throw '[android-release] expected AAB was not produced.'
    }
    $hash = (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "ANDROID_VERSION_CODE=$versionCode"
    Write-Host "ANDROID_AAB=$((Resolve-Path -LiteralPath $bundle).Path)"
    Write-Host "ANDROID_AAB_SHA256=$hash"
    Write-Host 'ANDROID_STORE_UPLOAD_PERFORMED=false'
} finally {
    Pop-Location
}
