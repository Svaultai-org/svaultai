# Strict raw-PIN cutover status

This isolated change adds a **default-off** server fence. It has not been
deployed or enabled. `VAULTAI_STRICT_RAW_PIN_INGRESS_ENABLED=true` rejects all
64 registered legacy PIN-capable method/path pairs, plus retired
`POST /auth/signup`, before the Python application
reads their body, including `/auth/login`, multipart forms, and the three
conditional chunked-upload paths. Rejection is global: there is no legacy-only
account exemption. The registered-route/body-model test must be updated if a
new authentication PIN field is added; it fails when that field is missing
from the explicit manifest.
The exact 64 method/path pairs are listed in
`docs/STRICT_RAW_PIN_INGRESS_AUDIT_2026-11-07.md` and executable in
`vault_ai_backend/strict_raw_pin_ingress_gate.py`.

The same flag rejects an older `POST /auth/zk-login-finalize` before reading its
body or consuming its OPAQUE login slot. A current client must send exactly one
`X-SVaultAI-Strict-Pin-Free-Client: v1` header. This is a **compatibility
signal, not cryptographic client attestation**. It cannot authorize content
access or bypass the old-route fence. The endpoint still runs OPAQUE and the
existing server-side offer/permission checks before issuing a session. An
unmodified older client cannot supersede an active session when the strict
flag is on. A modified client could assert the header, so this is not a proof
that its code has private-feature parity.

## Product parity and remaining cutover work

| Old path group | Existing private path or behavior | Cutover gap |
| --- | --- | --- |
| `/auth/login` | OPAQUE `/auth/zk-login-init` and `/auth/zk-login-finalize` | Legacy-only vaults cannot sign in once global strict mode is on. They need an owner-safe adoption/recovery path and device releases. |
| Saved items, logins, Memory | Ciphertext-first `/vault/ciphertext/vault-items`, `/vault/ciphertext/vault-ai-memory`, credential V2, and owner-only migration/export routes exist | Existing PIN-encrypted records need a complete owner-side migration and exact content verification. Old read/write aliases are unavailable in strict mode. |
| Files, uploads, rename/delete | `/vault/file-v2/*`, signed V2 create/mutation offers, metadata inventory and migration routes exist | Existing file content/metadata and pending legacy chunked uploads need verified migration. `/name-file`, related-file lookup, text extraction, and old aliases are unavailable in strict mode. |
| Chat and analysis | `/chat/zk/general` handles general questions; private vault lookup is client-local; signed private chat is staged | The old `/chat` and deep-answer paths are blocked. Full private text, photo, audio, video, and follow-up parity needs client and data readiness; the server must never receive decrypted private content merely to restore AI answers. |
| Beneficiary/inheritance | `/beneficiary/zk-create`, `/beneficiary/zk-link`, and V2 inheritance routes exist | Old mixed PIN/proof list, transfer, cancel, claim, and delete routes are blocked. A complete proof-only successor and owner-side package migration are required for older links/content. |
| Wallet/crypto | `/vault/wallet-v2` and `/vault/wallet-backup-v2` ciphertext paths exist | Old crypto-record actions are blocked; legacy records need migration. Wallet transaction behavior must not silently fall back to server-side key access. |
| Device self-approval, imports, deletion, Security Center | Some old paths already accept OPAQUE proof as an alternative to PIN; signed password-analysis offer exists | Those **same old paths** still accept a PIN, so strict mode blocks the proof form too. Each required action needs a separate proof-only route or an explicit unavailable state. |

In particular, strict mode makes these ordinary actions unavailable through
their current contracts: `/devices/request-self-approval` and
`/devices/finalize-self-approval`; `/imports/start`,
`/imports/{import_id}/cancel`, and `/imports/{import_id}/complete`;
`/vault/delete/confirm`; the old `/delete-file` and `/manage/file` aliases;
`/security-center/analyze-passwords`; and `/beneficiary/list-mine`,
`/beneficiary/list-inheritances`, `/beneficiary/request-transfer`,
`/beneficiary/cancel-transfer`, `/beneficiary/claim-transfer`, and
`/beneficiary/delete`. Some already understand proof tokens internally, but
their shared request models also accept a PIN and therefore cannot be exempted
by a path-only prebody policy. Their absence is a **release blocker** if those
actions must remain available immediately after strict cutover.

The strict fence makes the server decline these old contracts; it does not
prove that every released client avoids sending a PIN. Complete web/iOS/Android
transport tests, owner-side migration, feature parity, and release checks are
required before the flag can be turned on without broad loss of access.
The reverse proxy can receive request bytes before ASGI rejects them. The
synthetic tests prove zero application body reads, not zero network transfer.
