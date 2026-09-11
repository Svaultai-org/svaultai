#!/usr/bin/env bash
set -euo pipefail

crate_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$crate_dir/ios"
header_dir="$output_dir/include"
cargo_bin="$(command -v cargo)"
cargo_root="$(cd "$(dirname "$cargo_bin")/.." && pwd)"

command -v cargo >/dev/null
command -v rustup >/dev/null
command -v xcodebuild >/dev/null

# Rust panic/source metadata can otherwise retain developer-machine paths.
# Stable virtual prefixes keep the distributed archive reproducible and avoid
# leaking local usernames or workspace locations.
export RUSTFLAGS="${RUSTFLAGS:-} --remap-path-prefix=$crate_dir=/vaultai/native/opaque_client --remap-path-prefix=$cargo_root=/cargo"

rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios

cargo build \
  --manifest-path "$crate_dir/Cargo.toml" \
  --release \
  --target aarch64-apple-ios
cargo build \
  --manifest-path "$crate_dir/Cargo.toml" \
  --release \
  --target aarch64-apple-ios-sim
cargo build \
  --manifest-path "$crate_dir/Cargo.toml" \
  --release \
  --target x86_64-apple-ios

simulator_universal_dir="$crate_dir/target/ios-simulator-universal/release"
mkdir -p "$simulator_universal_dir"
lipo -create \
  "$crate_dir/target/aarch64-apple-ios-sim/release/libvaultai_opaque_client.a" \
  "$crate_dir/target/x86_64-apple-ios/release/libvaultai_opaque_client.a" \
  -output "$simulator_universal_dir/libvaultai_opaque_client.a"

framework="$output_dir/VaultAIOpaque.xcframework"
if [[ -e "$framework" ]]; then
  rm -rf "$framework"
fi

xcodebuild -create-xcframework \
  -library "$crate_dir/target/aarch64-apple-ios/release/libvaultai_opaque_client.a" \
  -headers "$header_dir" \
  -library "$simulator_universal_dir/libvaultai_opaque_client.a" \
  -headers "$header_dir" \
  -output "$framework"

echo "Created $framework"
