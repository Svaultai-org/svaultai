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
