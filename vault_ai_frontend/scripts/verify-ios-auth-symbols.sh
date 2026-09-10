#!/bin/sh
set -eu

binary="${1:-build/ios/iphoneos/Runner.app/Runner}"
if [ ! -f "$binary" ]; then
  echo "iOS app binary not found: $binary" >&2
  exit 1
fi

for symbol in \
  vaultai_opaque_client_start_registration \
  vaultai_opaque_client_finish_registration \
  vaultai_opaque_client_start_login \
  vaultai_opaque_client_finish_login \
  vaultai_opaque_client_free_string \
  vaultai_pbkdf2_hmac_sha256
do
  if ! nm -gU "$binary" | grep -q " T _$symbol$"; then
    echo "Missing required iOS auth symbol: $symbol" >&2
    exit 1
  fi
done

echo "Verified all required iOS auth FFI symbols in $binary"
