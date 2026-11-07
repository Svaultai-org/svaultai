# Older inheritance claim: private-mode gap

Status: **No PIN-free replacement is enabled or deployed.** This note describes
the old claim contract and the boundary added to the default-off private
beneficiary build. It does not change an existing link or its encrypted data.

## Why the current claim cannot be reused

The original `/beneficiary/link` decrypts the owner's key on the server and
stores `beneficiary_links.wrapped_vault_key` encrypted under the beneficiary's
legacy PIN-derived vault key. `/beneficiary/claim-transfer` accepts that raw PIN,
derives the beneficiary key on the server, unwraps the owner's key, decrypts
and re-encrypts old saved items and files on the server, and creates another
legacy PIN vault. It also marks the source vault frozen and the link transferred.
Calling it under a different UI would still expose the PIN and content keys.

The OPAQUE adoption path adopts the beneficiary's existing legacy key as its
MVK, so a client-side unwrap of an *existing* link may be cryptographically
possible for that subset of vaults. That alone does not provide a transfer:

- `/vault/legacy-ciphertext/export/*` grants ciphertext for the **signed-in
  vault only**, using that vault's own recent OPAQUE proof. A beneficiary
  session cannot use it to read the owner's vault.
- `/inheritance/v2/{link_id}/vault-items` accepts only a released V2 link and
  exports migrated saved items only. An old link has neither its V2 marker nor
  its released V2 key envelope; the V2 import cannot consume it.
- The old clone copies legacy `vault_items` and `uploaded_files`. It has no
  complete, versioned export/import contract for V2 files, memories, wallet
  data, chat state, or mixed legacy/V2 content. Treating a partial copy as
  “all inherited data” would silently lose content.
- The old wrapped key may predate an owner's key rotation. A replacement must
  verify which key generation can read each ciphertext before changing link
  state or freezing the source vault.

## Boundary in the optional private build

For a signed beneficiary offer, `/beneficiary/request-transfer` is rejected
before the API reads its body, just like old create/link/claim. The client also
prevents starting an old countdown and explains that a new private link can
share only supported saved items. Existing ciphertext and the old link remain
untouched. The ordinary release retains its current behavior until a complete
private replacement is built and separately enabled.

## Complete replacement needed

1. Define a beneficiary-scoped release grant bound to the correct link,
   beneficiary session, trusted device, cooldown/approval state, and owner key
   generation. Reject replay, link revocation, stale snapshots, and partial
   exports. Never accept a raw PIN or a reusable PIN-derived key over HTTP.
2. Export a bounded, consistent inventory of **all** source ciphertext and
   required public structure. Include both legacy and V2 records, file chunks,
   memories, and every other inheritable content type, or explicitly exclude
   each type in the product contract before activation. Keep source data intact.
3. Unwrap the owner key and decrypt only on the beneficiary device. Authenticate
   every record, then encrypt under the beneficiary's client-held key. Use a
   resumable, idempotent import with source IDs and readback checks; do not
   transition the link or freeze the owner vault until completeness is proved.
4. For an existing link whose old key cannot decrypt the owner's current data,
   require owner-side migration and a new private pairing while the owner can
   still unlock the vault. If the owner cannot do that, show an unavailable
   state and preserve the original encrypted data rather than falling back to
   server-side decryption.

Synthetic tests must cover old and mixed records, chunked files, rotated keys,
replay, revoked links, interrupted imports, and no PIN/key in requests. This
release does **not** satisfy those requirements yet.
