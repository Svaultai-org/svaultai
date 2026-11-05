# Legacy file text and path migration — local candidate

The current production file stage deliberately defers legacy rows with
`extracted_text` or `relative_path`. Those fields are stored in plaintext in
the legacy row and are included in the source snapshot, but the old V2
manifest did not represent them. Retiring such a row would lose data.

This candidate adds a **default-off** owner-side migration for those fields.
It has not been deployed or run against a real vault.

## Contract

1. A recent OPAQUE PIN proof authorizes a short-lived, vault/session-bound
   export grant. The normal file export reports only whether extra fields
   exist and their byte sizes. A separate `read_file_extra` page returns the
   text and path once to the authenticated owner client. It is bounded to
   64 KiB of text and 4096 bytes of path, and is bound to the same source
   snapshot as the file ciphertext. Larger records stay untouched and require
   a streaming design. The V2 manifest limit is 512 KiB for this version;
   existing V1 manifests keep their 64 KiB limit.
2. The unlocked owner client wraps those fields inside an AES-GCM encrypted
   MVK file manifest with schema `vaultai.file.migrated.v2`. The public V2
   request body carries only ciphertext and a structural
   `migration_metadata_version=2` marker. It never carries the plaintext
   text, path, PIN, or MVK. V1 manifests remain valid for files without extra
   fields. A stale V1 sidecar can be reset once under a fresh proof and source
   snapshot before a V2 sidecar is staged.
3. The client fetches the V2 manifest and chunks back, decrypts them, and
   compares file bytes plus text and path to the still-present legacy source.
   The server binds its short-lived readback receipt to the legacy fields,
   manifest version, and V2 ciphertext. The server cannot itself inspect the
   opaque manifest to prove plaintext equivalence; the client check is the
   trust boundary.
4. Existing V1 sidecars with extra legacy fields still fail readback. The
   backend's extra-field retirement path remains behind the separate
   default-off `VAULTAI_ZK_LEGACY_FILE_EXTRA_RETIRE_ENABLED` gate and demands
   an explicit `client_verified_extra_fields` assertion, exact source
   snapshot, same-session receipt, and new OPAQUE proof. The deployed file
   retirement flag is also off. No stage action deletes legacy data.

## Release gates

- Apply database migration 0056 before deploying the matching backend.
- Verify a disposable PostgreSQL end-to-end run, including stale V1 sidecar,
  source edit, content readback, quota and interruption. Current tests are
  synthetic; they do not exercise a real database transaction.
- At the 5 November count-only owner check, eight files had extracted text and
  the longest value was 556 bytes. No text or record identifiers were read.
  This is below the candidate's size cap, but does not prove migration success.
- Update and validate native large-file streaming migration, V2 readers, and
  all supported mobile releases before enabling retirement. An old native
  reader accepts only V1 manifests and cannot read a retired V2 extra file.
- Enable `VAULTAI_ENABLE_LEGACY_FILE_EXTRA_STAGE` only with the matching
  backend and 0056 schema. This flag also requires the existing stage and
  recovery flags. Keep both retirement flags off until owner readback and
  mobile compatibility are proven.
- Do not equate an eligible stage pass with full PIN secrecy. Other legacy
  records, raw-PIN content calls, and offline-testable verifiers remain.
