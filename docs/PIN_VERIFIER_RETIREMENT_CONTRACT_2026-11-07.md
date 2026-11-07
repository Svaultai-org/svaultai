# Per-vault PIN-verifier retirement contract

This is isolated release code only. No production flag, vault, or data has
been changed. Migration `0060_pin_verifier_retirement` adds an irreversible
timestamp to each vault. It preserves the OPAQUE registration record, wrapped
MVK and private key, PIN salt, and all existing ciphertext.

`POST /auth/zk-pin-verifier-retire` is disabled unless
`VAULTAI_ZK_PIN_VERIFIER_RETIRE_ENABLED=true`. It also requires global
`VAULTAI_STRICT_RAW_PIN_INGRESS_ENABLED=true`, one
`X-SVaultAI-Strict-Pin-Free-Client: v1` header, a trusted OPAQUE session with
all current server-signed private offer bits, and a recent session-bound
OPAQUE proof. Request body:

```json
{
  "zk_proof_token": "<short-lived one-use proof from /auth/zk-verify-finalize>",
  "client_verified_exact_readback": true
}
```

The client must complete the existing legacy item/file stage, readback,
exact local plaintext comparison, and proof-gated retire flows first. This
request contains no PIN, key, vault name, or content. The boolean is an owner
assertion; the server cannot inspect or verify the plaintext comparison. It
checks structural database state and never accepts the boolean alone.

The server locks the known legacy-source tables, verifies the recent owner
proof within the transaction, reads only existence flags, and blocks
retirement if any legacy item ciphertext, item-edit candidate or
history, inline file ciphertext, old uploaded chunk, older beneficiary key
wrap, retained migration journal, incomplete item/file/V2 wallet, or active
legacy session remains. It consumes the one-use OPAQUE proof and blanks
`pin_verifier` in the same transaction, then records
`pin_verifier_retired_at`. On success the response is
`{"retired":true,"already_retired":false}`. A blocked vault receives HTTP
409 with `detail.code=verifier_retirement_not_ready` and a list of structural
blocker codes, without record identifiers or content. A blocked transaction
rolls back, leaving the proof reusable; an invalid proof cannot read blocker
categories. The route is idempotent for an already retired vault.

Migration 0060 prevents a retired verifier from being restored and rejects
new known legacy PIN-derived sources. The table locks serialize the retirement
check with concurrent old writes; source triggers then reject old material
after the timestamp commits. V2-only item writes remain allowed. Each
retirement briefly blocks writes to those source tables across vaults. The
route acquires its table locks without waiting and returns
`verifier_retirement_busy` for a later retry if another writer already holds
one. A future rollout must use bounded scheduling and monitor retries.

## Release blockers

- Current client readiness does not advertise the strict capability while
  wallet and private-media parity is incomplete. The server and retirement
  flags stay off.
- `legacy_item_edit_history.prior_encrypted_data` and
  `legacy_item_edit_candidates.encrypted_data` remain offline PIN oracles even
  after an active item is migrated. There is no owner-approved, exact-readback
  cleanup path for retained edit history. A vault with these rows stays
  blocked rather than losing the rollback copy silently.
- The migration journal has a `legacy_retained=TRUE` invariant. Existing
  journal rows block retirement until a separately reviewed retirement
  protocol resolves their retained-source status.
- Old chunked file bytes and old beneficiary key wraps block retirement.
  Existing file retirement is bounded and does not cover every large or
  chunked source. The count-only production preflight must identify whether
  a streaming migration is needed; no content inspection is required.
- This code only covers the known live-database PIN oracles. Historical
  backups can still contain old verifiers and ciphertext; their retention and
  access must be handled separately. The server cannot cryptographically
  attest a client binary from the capability header.

## Count-only file preflight, 7 November 2026

A read-only production aggregate found 35 legacy inline completed file rows.
Three encoded ciphertext records exceed the current client's 8 MiB automatic
migration cap, affecting one vault; none exceed the backend's 64 MiB source
limit. Fifteen rows have extra text or path fields, and one extracted-text
field exceeds the current 64 KiB extra-field limit. There are zero pending
uploads, zero chunked file rows, and zero uploaded legacy chunk rows. The
oversized text field's `OCTET_LENGTH` rounds up to 201 KiB. The current
client/backend limits block **four distinct file records**: the three large
records and the oversized extra-text record do not overlap.
These counts contain no IDs, filenames, ciphertext, or contents and may change.

## Bounded V3 migration for the oversized extracted text

Migration 0061 permits `migration_metadata_version=3` in the opaque file V2
table. The new `VAULTAI_ZK_LEGACY_FILE_EXTRA_V3_ENABLED` flag is off by
default and also requires the existing extra-stage flag. A recent OPAQUE
proof creates the same short-lived, session-bound export grant as V2. With
that grant, the owner can request `read_file_extra_v3` on the existing page
endpoint. Only this mode admits `extracted_text` above 64 KiB and at most
256 KiB UTF-8; `relative_path` remains capped at 4 KiB UTF-8. The response
includes `legacy_extra_version: 3` and the same full-source snapshot. The
older `read_file_extra` remains capped at 64 KiB. Neither request contains a
PIN. The existing page and grant byte budgets still apply.

The owner rewraps the **complete** extra text and path locally into an MVK
encrypted manifest with schema `vaultai.file.migrated.v3`, then stages it
through the existing file V2 manifest route using
`migration_metadata_version=3`. Only a legacy source with text strictly
above 64 KiB and at most 256 KiB can use V3. The encrypted manifest is
bounded to 2 MiB; the server checks the source snapshot and both size bounds
before inserting a stage. V2 remains capped at 512 KiB manifest ciphertext.

The existing readback route returns the staged ciphertext, version 3, and a
short-lived receipt bound to the current full legacy source and V2 bytes.
The client must decrypt and compare exact file bytes, text, path, and metadata
before sending `client_verified_exact_bytes=true` and
`client_verified_extra_fields=true`. The server checks the receipt and a
fresh one-use OPAQUE proof under the file lock before it removes the legacy
copy. V3 retirement additionally requires its flag and the existing
extra-retirement flag. Failed checks before proof consumption preserve the
legacy row and the owner proof. A later database failure preserves the row,
but the proof may need to be refreshed. The server cannot inspect the
encrypted manifest to verify the client's plaintext assertion.

This addresses the one count-only 201 KiB text field once a matching client
has passed exact readback. It does not address the three distinct legacy file
ciphertexts above the client's 8 MiB automatic migration cap. All production
flags stay off until full client parity and those larger files are resolved.

The 0060 migration was upgraded, downgraded, and upgraded again on an
isolated local PostgreSQL/pgvector database. Its synthetic test confirmed
that a retired verifier and legacy item/file/beneficiary writes are rejected
while a V2-only item remains writable. That test does not establish readiness
of any production vault.
