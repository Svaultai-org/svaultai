# ZK v2 vault ownership and no-recovery model

This is a security invariant, not a temporary product limitation.

SVaultAI cannot recover a forgotten vault PIN or restore access to the
existing encrypted vault. There is no company-held recovery secret, universal
KEK, administrator unlock, support override, PIN escrow, or server-held MVK.
Account control and hosted-service control do not imply vault-key possession.

## PIN change

A user who knows the current PIN may authenticate through OPAQUE, unwrap the
existing MVK on the client, establish a new authentication secret, and re-wrap
client key material. The backend must never receive the MVK or plaintext vault
content during that operation.

A user who has lost the current PIN cannot recover the existing vault through
email, SMS, support, an administrator, billing changes, database edits, forged
sessions, trusted-device changes, or account-profile changes. Starting a new
vault after explicitly deleting inaccessible ciphertext is not recovery.

## Separation of authority

Operators may control hosting, availability, releases, patches, configuration,
subscriptions, rate limits, and entitlement to hosted functionality. Those
controls must never yield an MVK, domain subkey, wallet signing key,
inheritance private key, or plaintext vault record.

OPAQUE server setup material authenticates protocol exchanges; it does not
decrypt the client MVK or vault records. User-stored recovery phrases and
recovery codes are ordinary encrypted vault content. Inheritance transfers use
the explicitly configured beneficiary cryptographic path and are not an owner
PIN-reset mechanism.

## Data-integrity obligation

No forgotten-PIN recovery does not excuse data loss for a user who knows the
PIN. Updates, logout/login, supported device migration, v2 migration, and
interrupted migration must preserve legitimate access and fail closed without
destroying the retained legacy record.
