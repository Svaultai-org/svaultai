# Pending beneficiary invitation upgrade

This default-off flow replaces an **unpaired** older invitation with a private
V2 invitation. It is designed for links with `status=pairing_pending`, no
beneficiary vault, no inheritance package (including deleted history), and no access or transfer
request. The old row remains intact until the owner has checked the new row.

Enable only in a coordinated test build with `VAULTAI_ENABLE_SIGNED_BENEFICIARY`,
`VAULTAI_ENABLE_ZK_BENEFICIARY_PROOF`,
`VAULTAI_ENABLE_ZK_BENEFICIARY_V2_PAIRING`, and
`VAULTAI_ENABLE_ZK_PENDING_BENEFICIARY_UPGRADE`. The server additionally needs
`VAULTAI_SIGNED_BENEFICIARY_OFFER_ENABLED`,
`VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED`,
`VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED`, and
`VAULTAI_ZK_LEGACY_BENEFICIARY_UPGRADE_ENABLED`. All new flags default to off.

Owner actions:

1. Sign in with an OPAQUE-enabled vault and open Inheritance.
2. Choose **Upgrade invitation** on an unpaired older link whose label is
   readable. The site asks for two local PIN verifications: one to stage the
   private invitation, one to retire the exact older row after readback.
3. The site checks the new encrypted label, pairing-code hash, pending state,
   owner-bound source snapshot, and session-bound readback receipt. It shows
   the new code only after the old row is retired atomically.
4. Share the new code with the intended beneficiary out of band. The
   beneficiary pairs with the existing proof-only V2 flow. The owner then
   prepares the V2 MVK envelope using the beneficiary's verified key
   fingerprint. No raw PIN, vault key, or label is sent to this upgrade route.

An interrupted stage leaves the old link. A new owner action replaces an
unclaimed staged invitation, including an expired one, without touching the
old row. A claimed staged invitation cannot be reset automatically. A changed
old row, changed new row, failed readback, absent proof, or active credential
package blocks retirement.

**Strict cutover is still blocked** for linked legacy links, links with active
credential packages, or release flows in progress. Those need both vault
holders to establish and confirm a new V2 link and owner escrow. No automatic
conversion or deletion of those links is implemented by this slice.
