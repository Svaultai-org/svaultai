# VaultAI Android OPAQUE Client

This crate builds `libvaultai_opaque_client.so` for Flutter Android.
It is a small C-ABI wrapper over `opaque-ke 4.x` using the same
Ristretto255/SHA512/Argon2id suite as the backend OPAQUE server.

The library returns base64url JSON envelopes to Dart FFI. It does not
log PINs, keys, OPAQUE messages, tokens, or credentials.

Build from `vault_ai_frontend`:

```powershell
.\native\opaque_client\build-android.ps1
```

On macOS, with the installed Rust Android targets and Android NDK r28c
(`28.2.13676358`):

```sh
bash native/opaque_client/build-android-macos.sh
```

The macOS script uses the existing `Cargo.lock` and cached crates with
`--locked --offline`. It rebuilds all four existing Android ABIs with 16KB
maximum/common page sizes, then checks actual ELF LOAD and GNU_RELRO
boundaries and all seven public C-ABI exports using the pinned NDK's
`llvm-readelf` and an independent binary-header verifier. No current library
is replaced until every staged library passes. Original libraries and JSON /
readelf evidence are retained in a dedicated `/private/tmp` directory printed
by the script; it does not automatically erase backups.

It does not run Flutter or Gradle, access signing keys, upload to stores, or
change the OPAQUE/PBKDF2 implementation. ELF checks are not proof of full app
compatibility: verify every dependency and final APK/AAB zip alignment, then
test the installed app on a 16KB Android environment before release.

Run the build-verifier regressions without Flutter:

```sh
python3 -m unittest discover -s native/opaque_client/tests -v
```
