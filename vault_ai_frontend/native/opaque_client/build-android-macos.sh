#!/usr/bin/env bash
set -euo pipefail

# Rebuild only the existing Android OPAQUE/PBKDF2 C ABI. This script does not
# invoke Flutter, Gradle, keytool, store services, or change Rust algorithms.
[[ "$(uname -s)" == "Darwin" ]] || { echo "macOS is required." >&2; exit 1; }
[[ $# -eq 0 ]] || { echo "Usage: bash build-android-macos.sh" >&2; exit 1; }

crate_dir="$(cd "$(dirname "$0")" && pwd)"
frontend_dir="$(cd "$crate_dir/../.." && pwd)"
android_sdk_dir="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}"
ndk_root="$android_sdk_dir/ndk/28.2.13676358"
toolchain_bin="$ndk_root/toolchains/llvm/prebuilt/darwin-x86_64/bin"
readelf_bin="$toolchain_bin/llvm-readelf"
verifier="$crate_dir/tools/verify_android_elf.py"

command -v cargo >/dev/null
command -v rustc >/dev/null
command -v python3 >/dev/null
grep -qx 'Pkg.Revision = 28.2.13676358' "$ndk_root/source.properties" || {
  echo "The pinned Android NDK r28c is required." >&2
  exit 1
}
[[ -x "$readelf_bin" && -f "$verifier" ]] || {
  echo "Native ELF verification tools are missing." >&2
  exit 1
}

triples=(aarch64-linux-android armv7-linux-androideabi x86_64-linux-android i686-linux-android)
abis=(arm64-v8a armeabi-v7a x86_64 x86)
linkers=(aarch64-linux-android24-clang armv7a-linux-androideabi24-clang x86_64-linux-android24-clang i686-linux-android24-clang)
rust_sysroot="$(rustc --print sysroot)"
for index in 0 1 2 3; do
  [[ -x "$toolchain_bin/${linkers[$index]}" && -d "$rust_sysroot/lib/rustlib/${triples[$index]}" ]] || {
    echo "An installed Android linker or Rust target is missing: ${triples[$index]}" >&2
    exit 1
  }
  [[ -f "$frontend_dir/android/app/src/main/jniLibs/${abis[$index]}/libvaultai_opaque_client.so" ]] || {
    echo "An original library is missing; refusing an unbacked replacement." >&2
    exit 1
  }
done

# Keep build output and original libraries outside the repo and never remove
# this directory automatically. A failed build/check leaves shipping files alone.
work_dir="$(mktemp -d /private/tmp/svaultai-android-native.XXXXXX)"
mkdir -p "$work_dir/staged" "$work_dir/originals"
printf 'Recoverable build/backup directory: %s\n' "$work_dir"
export CARGO_TARGET_DIR="$work_dir/cargo-target"
export CARGO_NET_OFFLINE=true
unset CARGO_ENCODED_RUSTFLAGS
cargo_registry_root="$(cd "$(dirname "$(command -v cargo)")/.." && pwd)"
# NDK r28c and both page-size flags align LOAD and GNU_RELRO boundaries. The
# verifier checks actual bytes, not the mere presence of these flags.
export RUSTFLAGS="-C link-arg=-Wl,-z,max-page-size=16384 -C link-arg=-Wl,-z,common-page-size=16384 --remap-path-prefix=$crate_dir=/vaultai/native/opaque_client --remap-path-prefix=$cargo_registry_root=/cargo --remap-path-prefix=$work_dir=/vaultai/android-build"

for index in 0 1 2 3; do
  triple="${triples[$index]}"
  abi="${abis[$index]}"
  linker_env="CARGO_TARGET_$(printf '%s' "$triple" | tr '[:lower:]-' '[:upper:]_')_LINKER"
  export "$linker_env=$toolchain_bin/${linkers[$index]}"
  cargo build --manifest-path "$crate_dir/Cargo.toml" --release --target "$triple" --locked --offline
  mkdir -p "$work_dir/staged/$abi"
  cp "$CARGO_TARGET_DIR/$triple/release/libvaultai_opaque_client.so" "$work_dir/staged/$abi/libvaultai_opaque_client.so"
done

python3 "$verifier" --readelf "$readelf_bin" --directory "$work_dir/staged" \
  --report "$work_dir/verified-build.json" --source "$crate_dir/src/lib.rs" \
  --lockfile "$crate_dir/Cargo.lock" --rustc-version "$(rustc --version)" \
  --cargo-version "$(cargo --version)"

# Back up all originals successfully before replacing any verified library.
for abi in "${abis[@]}"; do
  mkdir -p "$work_dir/originals/$abi"
  cp -p "$frontend_dir/android/app/src/main/jniLibs/$abi/libvaultai_opaque_client.so" "$work_dir/originals/$abi/libvaultai_opaque_client.so"
done
for abi in "${abis[@]}"; do
  install -m 644 "$work_dir/staged/$abi/libvaultai_opaque_client.so" "$frontend_dir/android/app/src/main/jniLibs/$abi/libvaultai_opaque_client.so"
done
python3 "$verifier" --readelf "$readelf_bin" \
  --directory "$frontend_dir/android/app/src/main/jniLibs" \
  --report "$work_dir/verified-installed.json" --source "$crate_dir/src/lib.rs" \
  --lockfile "$crate_dir/Cargo.lock" --rustc-version "$(rustc --version)" \
  --cargo-version "$(cargo --version)"
printf 'All four libraries verified. Originals and evidence retained: %s\n' "$work_dir"
printf 'Final APK/AAB packaging and a 16KB Android runtime test remain required.\n'
