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
