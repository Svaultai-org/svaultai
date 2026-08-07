# ZK v2 record schema map

This is an additive compatibility design. It does not alter existing domain
tables or migrate records.

| Domain adapter | Existing representation | Shared v2 representation | Key domain |
|---|---|---|---|
| Files | Existing uploaded-file rows and object ciphertext | `vault_crypto_envelopes`, keyed by file record ID | `file` |
| Credentials | Existing secure-item/login rows | Shared envelope keyed by credential record ID | `credential` |
| Memories | Existing memory rows | Shared envelope keyed by memory record ID | `memory` |
| Secure notes | Existing secure-item/note rows | Shared envelope keyed by note record ID | `secure_note` |
| Wallet records | Existing network-specific records | Shared envelope keyed by wallet record ID | `wallet_record` |
| Inheritance | Existing version-1 inheritance package remains unchanged | Shared envelope only where an inheritance record later adopts the general content contract | `inheritance_record` |

Every v2 envelope explicitly stores `crypto_version`, `cipher_suite`,
`key_domain`, nonce, ciphertext, authentication tag, migration and verification
states, optional migration time, and non-sensitive blind indexes. The backend
stores these fields but has no v2 decrypt or key-derivation API.

The journal contains only identifiers, versions, state, timestamps, safe error
category, verification state, operation ID, and attempt number. Plaintext,
PINs, MVKs, derived keys, wallet private keys, and seed phrases are prohibited.

Legacy rows remain authoritative until a client has written and verified a v2
envelope. Initial migration work never deletes legacy representations.

## Dispatch and feature gates

- `legacy_v1` dispatches only to the existing legacy adapter.
- `client_mvk_v2` dispatches only to the opaque client-decrypt envelope path.
- Unknown versions fail closed with `unsupported_crypto_version`.
- V2 never silently falls back to legacy, and an existing v2 envelope cannot
  be overwritten through a v1 write.
- `ZK_V2_READ_ENABLED`, `ZK_V2_WRITE_ENABLED`, and
  `ZK_V2_MIGRATION_ENABLED` are explicit and default to `false`, including in
  the production example. Migration requires both read and write to be on.

The stale `APP_RELEASE` value in the ignored production client configuration is
operationally significant: it is sent as `X-App-Release` and participates in
web service-worker release/cache convergence. It is not a secret, but a stale
value can misidentify the running client and interfere with release refresh
behavior. The ignored local configuration was not changed.

## Credential v2 cryptographic contract

Credential v2 reuses the active client MVK and the existing HKDF-SHA256 key
hierarchy. No second root key exists.

1. `K_credential = HKDF-SHA256(MVK, salt="", info="vaultai.credential.encryption.v2", L=32)`
2. `K_record = HKDF-SHA256(K_credential, salt=UTF8(record_id), info="vaultai.credential.record.v2", L=32)`
3. `AAD = UTF8("svaultai|client_mvk_v2|credential|" + record_id)`
4. `AES-256-GCM(K_record, random 96-bit nonce, AAD, canonical credential JSON)`

Every write uses a fresh secure nonce. The record ID is bound into both key
derivation and authenticated AAD. Username, password, URL, notes, custom fields,
and TOTP secret are encrypted. The server sees only the record ID, framing,
state, and approved opaque lookup tokens.

`K_lookup = HKDF-SHA256(MVK, salt="", info="vaultai.credential.lookup.v2", L=32)`

An exact token is `HMAC-SHA256(K_lookup, UTF8(field + NUL + normalized_value))`.
Normalization trims, lowercases, and collapses whitespace; URL lookup uses the
lowercase parsed hostname. Only `service`, `username`, and `url_host` are
indexed. Passwords, notes, custom fields, and TOTP secrets are never indexed.
Collisions return opaque candidates which the client decrypts and matches
locally. The backend performs no semantic plaintext search.
