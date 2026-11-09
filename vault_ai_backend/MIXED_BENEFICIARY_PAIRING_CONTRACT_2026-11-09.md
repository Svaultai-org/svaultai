# Mixed beneficiary pairing, staged

This default-off path reduces raw-PIN use for **new** invitations when an
OPAQUE vault still has older inheritance links. It does not upgrade or claim
those older links.

For a coordinated test, enable the existing client
`VAULTAI_ENABLE_ZK_BENEFICIARY_PROOF` and
`VAULTAI_ENABLE_ZK_BENEFICIARY_V2_PAIRING` flags, plus the server
`VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED` and
`VAULTAI_ZK_BENEFICIARY_V2_PAIRING_ENABLED` flags. Then separately enable
`VAULTAI_ENABLE_ZK_MIXED_BENEFICIARY_CREATE` and/or
`VAULTAI_ENABLE_ZK_MIXED_BENEFICIARY_LINK` in the client. Linking also needs
the server `VAULTAI_ZK_MIXED_BENEFICIARY_LINK_LOOKUP_ENABLED` flag. All new
flags default to false. Keep the full signed beneficiary offer off while old
links still need their existing actions.

- **Create:** An unlocked OPAQUE vault encrypts the new label on its device
  and sends a fresh OPAQUE proof to `/beneficiary/zk-create`. No old row is
  touched.
- **Link:** An authenticated, rate-limited lookup returns only
  `private`, `legacy`, or `unknown` for an unused code. `private` uses the
  fresh-proof V2 linker. `legacy` retains the existing older linker so its
  invitation remains usable. `unknown` stops before any PIN request. Both
  link endpoints recheck the row before writing.
- **Claim:** The older whole-vault claim still needs a PIN-derived server key.
  A proof token cannot decrypt its old key or copy all content. This path
  leaves that claim unchanged until a complete client-side transfer exists.

The code-kind lookup does not accept a PIN or return a vault identity, label,
or package. Beneficiary responses receive no-store headers. Client actions
check the current vault/key lease before and after network activity.
