# Wiping all test users/vaults (development only)

`scripts/wipe_all_test_users.py` deletes every account, vault, session,
file, secure item, ID document, encrypted crypto-wallet record, activity
row, and billing shadow row that lives inside the local development
database. It is a one-shot pre-launch tool for the phase where we have
zero real users but a long tail of half-onboarded test accounts.

The script hard-refuses to run under `VAULTAI_ENV=production` unless
the operator has explicitly opted in with a dedicated env var **and**
passed two separate command-line confirmation flags. Even then, running
this against real users would delete every one of them and cannot be
undone — do not use this outside development.

---

## When to use it

- You are in the pre-launch phase.
- You want a clean database to re-verify signup → PIN setup →
  backup → restore end-to-end.
- You want to clear the long tail of dev/test vaults, orphaned
  files, and dangling billing shadow rows.

Do **not** run this if any real user has signed up. Once we ship,
this script should stay unused; a future launch checklist should
disable it entirely.

---

## Dry-run (safe, default)

Prints only counts. Never touches the database.

```bash
python -m vault_ai_backend.scripts.wipe_all_test_users --dry-run
```

Output is aggregated `SELECT COUNT(*)` results per table, e.g.

```
[WIPE] mode=DRY-RUN env=development allow_env=False
[WIPE] plan (counts only, no PII):
  - accounts: 12
  - vaults: 14
  - sessions: 7
  - files: 823
  - secure_items_all_kinds: 41
  - notifications: 5
  - subscriptions_local: 3
  - trusted_devices: 6
  - deletion_tombstones: 2
  ...
```

**Dry-run output NEVER contains:** email addresses, display names, PINs,
file names, ID document numbers, wallet addresses, encrypted wallet
secrets, Stripe customer IDs, session tokens, API keys, or vault names.
Only aggregate counts and per-table labels.

Dry-run is the default when no destructive flags are passed — you can
even run it with no flags at all and it will refuse to delete anything.

---

## Destructive wipe

The destructive run requires **both** confirmation flags. Missing
either flag causes the script to exit with a refusal message and no
database writes.

```bash
python -m vault_ai_backend.scripts.wipe_all_test_users \
    --confirm-wipe-all-test-users \
    --i-understand-this-deletes-all-users
```

The destructive run:

1. Enumerates all vault IDs.
2. Routes each vault through the shared
   `delete_vault_and_all_data(vault_id, reason="development_full_user_wipe")`
   service. This is the same code path that user-requested vault
   deletion and unpaid-inactive auto-deletion use — so we get:
   - PostgreSQL `ON DELETE CASCADE` cleanup of every vault-owned row
     (files, chunks, secure items, semantic index, asset tags, password
     audit, document metadata/entities, AI memory, preferences,
     relationships, expiry alerts, intelligence summary, content chunks,
     file understanding/embeddings, analysis jobs, agent memories/tasks/
     audit, import batches, file relationships, sessions, trusted
     devices, notifications).
   - Best-effort Stripe subscription cancellation for the vault's
     account. Failures are swallowed and only the hashed vault-id
     prefix is logged.
   - Safe tombstone row inserted into `vault_deletion_tombstones`:
     `hashed_vault_id`, `deleted_at`, `deletion_reason=development_full_user_wipe`.
     No vault name, no account id, no encrypted material.
3. Deletes leftover rows in tables that don't cascade from `vaults`:
   `subscription_events`, `provider_event_log`,
   `contact_sales_requests`, `vault_deletion_tombstones`.
4. Deletes every remaining row from `accounts` (organization accounts
   and any lingering individual accounts).

**What the script never touches:**

- `alembic_version` — migration marker.
- `storage_skus` — pricing SKU catalogue.
- `storage_pricing` — pricing constants.
- `username_policies` — validation rules.
- `vault_service_categories` — service-category taxonomy.

---

## Production is protected

The script's env gate:

- Refuses to run at all unless one of these is true:
  - `VAULTAI_ENV` is one of `dev`, `development`, `local`, `test`,
    `ci` (or unset — which also reads as dev per `vault_config`).
  - `VAULTAI_ALLOW_TEST_USER_WIPE=true` is set as an explicit
    operator override.
- If `VAULTAI_ENV=production` (or `prod`/`live`), the script refuses
  the destructive path unless **all three** of these are present:
  1. `VAULTAI_ALLOW_TEST_USER_WIPE=true`
  2. `--confirm-wipe-all-test-users`
  3. `--i-understand-this-deletes-all-users`

Even with all three, the script prints the DESTRUCTIVE banner
identifying the env token so the operator can abort if the env is
wrong.

---

## Verifying the database is empty after a wipe

```bash

python -m vault_ai_backend.scripts.wipe_all_test_users --dry-run
```

Every count should be `0` for user-owned tables (`accounts`, `vaults`,
`sessions`, `files`, `secure_items_all_kinds`, `notifications`,
`subscriptions_local`, `trusted_devices`, `stripe_customers_local`,
etc.).

Config tables should remain intact:

```bash

psql "$VAULTAI_DATABASE_URL" -c "SELECT COUNT(*) FROM alembic_version;"
psql "$VAULTAI_DATABASE_URL" -c "SELECT COUNT(*) FROM storage_skus;"
psql "$VAULTAI_DATABASE_URL" -c "SELECT COUNT(*) FROM storage_pricing;"
psql "$VAULTAI_DATABASE_URL" -c "SELECT COUNT(*) FROM username_policies;"
psql "$VAULTAI_DATABASE_URL" -c "SELECT COUNT(*) FROM vault_service_categories;"
```

`storage_skus` should return `>0` (seeded by migration 0001);
`storage_pricing` should return `>0` (seeded by migration 0001);
`alembic_version` should return `1` (single row).

After a successful destructive wipe, the app must still boot and the
test suite must still be able to create a fresh account + vault + PIN.
If either fails, restore from your DB snapshot — this script does not
create a rollback point on its own.

---

## Rollback

The wipe is irreversible at the DB layer. If you need to recover state:

1. Restore the DB from the most recent snapshot (see
   [BACKUP_AND_RECOVERY.md](../vault_ai_backend/BACKUP_AND_RECOVERY.md)).
2. Re-run migrations up to the latest revision.
3. Re-verify the config tables (`storage_skus`, `storage_pricing`,
   `username_policies`, `vault_service_categories`).

---

## Related code

- [scripts/wipe_all_test_users.py](../vault_ai_backend/scripts/wipe_all_test_users.py)
  — the script itself.
- [vault_deletion_service.py](../vault_ai_backend/vault_deletion_service.py)
  — the shared per-vault deletion service.
- [migrations/versions/0019_dev_wipe_deletion_reason.py](../vault_ai_backend/migrations/versions/0019_dev_wipe_deletion_reason.py)
  — widens the tombstone `deletion_reason` CHECK constraint to include
  `development_full_user_wipe`.
- [test_wipe_all_test_users_2026_07_09.py](../vault_ai_backend/test_wipe_all_test_users_2026_07_09.py)
  — regression coverage.
