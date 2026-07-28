$ErrorActionPreference = "Stop"

$crateDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Split-Path -Parent (Split-Path -Parent $crateDir)
$sdkRoot = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { $env:ANDROID_HOME }
if (-not $sdkRoot) {
  $sdkRoot = Join-Path $env:LOCALAPPDATA "Android\Sdk"
}

$ndkRoot = $env:ANDROID_NDK_HOME
if (-not $ndkRoot) {
  $ndkRoot = Get-ChildItem -Path (Join-Path $sdkRoot "ndk") -Directory |
    Sort-Object Name -Descending |
    Select-Object -First 1 -ExpandProperty FullName
}
if (-not $ndkRoot -or -not (Test-Path $ndkRoot)) {
  throw "Android NDK not found. Set ANDROID_NDK_HOME or install an NDK under $sdkRoot\ndk."
}

$toolchainBin = Join-Path $ndkRoot "toolchains\llvm\prebuilt\windows-x86_64\bin"
$targets = @(
  @{ Triple = "aarch64-linux-android"; Abi = "arm64-v8a"; Linker = "aarch64-linux-android24-clang.cmd" },
  @{ Triple = "armv7-linux-androideabi"; Abi = "armeabi-v7a"; Linker = "armv7a-linux-androideabi24-clang.cmd" },
  @{ Triple = "x86_64-linux-android"; Abi = "x86_64"; Linker = "x86_64-linux-android24-clang.cmd" },
  @{ Triple = "i686-linux-android"; Abi = "x86"; Linker = "i686-linux-android24-clang.cmd" }
)

Push-Location $crateDir
try {
  foreach ($target in $targets) {
    $linkerPath = Join-Path $toolchainBin $target.Linker
    if (-not (Test-Path $linkerPath)) {
      throw "Android linker not found: $linkerPath"
    }
    $envName = "CARGO_TARGET_" + ($target.Triple.ToUpperInvariant() -replace "-", "_") + "_LINKER"
    Set-Item -Path "Env:$envName" -Value $linkerPath

    cargo build --target $target.Triple --release
    if ($LASTEXITCODE -ne 0) {
      throw "Cargo build failed for $($target.Triple)"
    }

    $source = Join-Path $crateDir "target\$($target.Triple)\release\libvaultai_opaque_client.so"
    $destDir = Join-Path $frontendDir "android\app\src\main\jniLibs\$($target.Abi)"
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    Copy-Item -LiteralPath $source -Destination (Join-Path $destDir "libvaultai_opaque_client.so") -Force
  }
} finally {
  Pop-Location
}
