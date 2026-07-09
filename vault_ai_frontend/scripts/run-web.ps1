# Canonical Flutter web launch for VaultAI local dev.
#
# Why this script exists:
#
#   On Flutter web, SharedPreferences is backed by the browser's
#   localStorage, which the browser scopes per ORIGIN = (scheme + host
#   + port). Every `flutter run` without --web-port picks a random
#   free port, which means a fresh origin, a fresh localStorage, and
#   therefore a brand-new vaultai_device_id_v1. After enough rebuilds
#   the trusted_devices table fills up with stale rows and the
#   device-trust gate strands the developer on /device-pending.
#
#   Pinning both --web-port AND --web-hostname makes the origin stable:
#       http://localhost:5173
#   localStorage persists across every rebuild, the device_id stays
#   the same, and the auto-trust hatch (VAULTAI_ENV=local +
#   VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=true) only has to fire once.
#
#   The backend's STRIPE_CHECKOUT_SUCCESS_URL / CANCEL_URL /
#   PORTAL_RETURN_URL in .env already point at port 5173, so this
#   script keeps the Stripe return flow working end-to-end.
#
# Usage:
#   .\scripts\run-web.ps1               # canonical launch
#   .\scripts\run-web.ps1 --release     # extra flutter flags pass through
#
# Production behaviour is unchanged — this script only governs the
# local dev origin.

$ErrorActionPreference = 'Stop'

# Resolve to the Flutter project root regardless of where the caller
# invoked the script from. $PSScriptRoot is scripts/, parent is the
# project root.
$flutterProjectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $flutterProjectRoot
try {
    Write-Host "[vault-dev] flutter run -d chrome --web-port=5173 --web-hostname=localhost $args" -ForegroundColor Cyan
    flutter run -d chrome --web-port=5173 --web-hostname=localhost @args
}
finally {
    Pop-Location
}
