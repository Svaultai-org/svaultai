# Private vault-name lookup: decision needed

Source review only. No production rows, backups, or user content were read or changed. This is separate from the raw-PIN transport cutover.

## Current contract

- Users can sign in on a new device with a vault name and PIN alone. The client derives a stable 15-byte `vault_handle` and 32-byte `username_lookup_v1` from the normalized name (`vault_ai_frontend/lib/services/vault_handle.dart`). OPAQUE login sends those derived values, never the raw name (`vault_ai_frontend/lib/services/zk_auth_service.dart`).
- The server must select an OPAQUE registration record before it can complete login. It looks up the handle, then optionally the lookup value (`vault_ai_backend/routes/auth_zk_routes.py`). The OPAQUE credential identifier is bound to the stored handle. Both columns have unique indexes (`0023_vault_zk_state.py`, `0030_username_blind_index.py`), supporting name-only account lookup and globally unique names.
- The current no-recovery model does not let SVaultAI recover a forgotten PIN or client vault key (`docs/zk_v2_no_recovery_model.md`). Losing an account locator would be a separate access problem.

## Residual privacy risk

Both identifiers are unkeyed, deterministic hashes of a user-chosen name with public domain separators. A person with a database copy and source can test likely names offline. The 120-bit handle length prevents accidental hash collisions; it does not add entropy to a common name. Existing auth log fingerprints are suppressed by default in commit `6ea2a512`, but the database identifiers remain guessable. Migration `0045_private_vault_identifiers.py` replaces the readable `vaults.vault_name` column with a UUID-based label and clears `display_username`; whether production and historical backups reflect this was not checked here.

## Why a direct replacement is unsafe

- A random handle would remove the name-derived handle, but a new device could not locate the account using only name and PIN. Keeping `username_lookup_v1` as a fallback would keep the offline guessing risk. A user-held handle, trusted-device transfer, or another locator would be required.
- Changing an existing handle in the database without owner-side OPAQUE re-registration would break authentication: the server uses that handle as OPAQUE's credential identifier. Old deterministic selectors must eventually be removed, not left as permanent aliases.
- Deriving a selector from name plus PIN would make account lookup depend on the PIN and would not enforce one account per name across different PINs. A PIN change would also change the selector. The present unique-name rule needs its own private index design.

## Product and threat-model choice

1. **Keep name + PIN on every device and unique names.** A blinded lookup protocol such as VOPRF could hide the entered name on the wire and protect against a database-only leak. The service holding the VOPRF key can still evaluate guesses, so it does not hide names from a compromised or malicious service. This requires audited client/server cryptography, key rotation, mobile/web parity, owner migration, and a plan to retire both current hashes.
2. **Require a user-held random handle plus PIN.** The existing client can sign in by an explicit handle, but signup, onboarding, device transfer, and lost-handle policy would change. Global name uniqueness would need to be dropped or enforced through a separate name directory with its own privacy trade-off. This does not change the rule that a forgotten PIN cannot recover vault data.

Do not enable a new selector or delete old identifiers until the product chooses the login/recovery experience and the privacy threat model. Continue the raw-PIN cutover independently while preserving current account access.
