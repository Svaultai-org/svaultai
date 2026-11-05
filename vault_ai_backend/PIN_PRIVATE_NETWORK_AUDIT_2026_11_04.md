# Private ZK network-shape audit (integration e0f83eb)

This is a synthetic, local audit only. It is not a production or store-release sign-off.

## Observed private-mode behavior

- Successful OPAQUE install clears the PIN cache and PBKDF2 crypto context. Its session-bound transport guard rejects JSON and multipart `pin` fields before HTTP. The guard remains active after MVK loss and clears on session change/logout.
- The private chat route sends general questions to `/chat/zk/general` and reads saved-item/file ciphertext for local search. It sends no raw PIN, MVK, or private index to the general AI route. File, memory, and saved-item V2 routes use the MVK on the client. Beneficiary proof actions use OPAQUE proof rather than a PIN field.
- Legacy constructors remain in source for legacy-only vaults and migration. The static release gate remains **red at 25 raw-PIN request constructors**. A private ZK session blocks these at transport, but constructor count alone does not prove every feature works.

## Release blockers and coverage limits

1. **Wallet/Assets parity:** `VaultKeyHierarchy.walletWrapKey()` exists but has no frontend consumer or wallet-v2 API adapter. The current wallet UI uses `_VaultCrypto.encrypt/decrypt` and checks `VaultCryptoRegistry.current` / `_VaultCrypto.hasKeyFor`; these are deliberately empty after private unlock. Existing `encryptedWalletSecret` records use the older crypto format, and wallet-v2 uses a separate, flag-gated store. Any remaining PIN-derived wallet ciphertext may also be an offline PIN oracle; this audit did not inspect production wallet records. Do not substitute an MVK key into the legacy ciphertext format or enable private wallet creation/send until a versioned client migration, readback, and old-ciphertext retirement are implemented and tested. Read-only wallet receive metadata is PIN-free.
2. **Private chat actions:** at this baseline `_sendOnce` enters `_sendZkPrivateChat` before legacy local memory-save, file-rename, and file-content command handlers. Private chat rejects composer attachments. These are feature gaps, not observed PIN leaks; the frontend agent is working on this region separately. Visual and spoken-content search remains unsupported by the private index.
3. **Widget-test fixtures:** two `file_v2_dashboard_ui_test.dart` cases cannot find the sidebar menu icon and fail with private-only flag both on and off. `zk_saved_item_keyless_write_ui_test.dart` passes under its normal keyless flags but its older fixture cannot find the top Create button with private-only enabled. Those failures leave the combined private UI flow unverified; they are not evidence that network requests carried PINs.

## Focused evidence

- 51/51 private-flag tests passed across unlock/session, chat transport, file cutover, memory save, saved-item private read/delete, beneficiary proof, and `zk_private_network_shape_audit_test.dart`. The added network test confirms read-only wallet metadata and ZK stats reach the synthetic server, while password analysis, KDF rotation, and related-files legacy PIN actions fail before HTTP.
- 6/6 private-chat flow tests passed under default flags; one test explicitly expects the private chat flag off in that build and therefore is not run in the private-flag group.
- Separate V2 upload/proof tests passed, while the combined flagged widget run had the three fixture failures above. These checks use synthetic data and do not exercise a live wallet, transaction, real vault, or production backend.
