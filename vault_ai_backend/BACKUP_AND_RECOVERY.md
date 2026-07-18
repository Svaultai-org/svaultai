# VaultAI — Backup and Recovery Plan

Companion to `DEPLOYMENT_RUNBOOK.md`. This document defines the production backup cadence, restore procedure, and the closed-set policy boundaries that govern what an operator can and cannot do for a user who lost access.

The single most important rule, stated up front: **no operator, no administrator, no support staff can read decrypted vault contents.** Every recovery procedure below preserves that boundary. There is no admin decrypt; there is no master key; there is no PIN bypass.

---

## 1. Backup cadence

### 1.1 Postgres — daily full + 15-minute WAL archive

```
Schedule
  daily 02:00 UTC      pg_dump --format=custom  → s3://vaultai-backups/db/YYYY-MM-DD.dump
  every 15 min          WAL ship to S3 archive (point-in-time recovery)
Retention
  daily snapshots       35 days
  WAL                   8 days
Encryption
  S3 SSE-KMS, key alias vaultai/backups
  IAM: write-only role for the dump cron; restore role is human-only with MFA
```

Recommended command for the daily dump cron:

```bash
pg_dump \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file="/tmp/vaultai-$(date +%Y-%m-%d).dump" \
  "$DATABASE_URL"

aws s3 cp "/tmp/vaultai-$(date +%Y-%m-%d).dump" \
  s3://vaultai-backups/db/$(date +%Y-%m-%d).dump \
  --sse aws:kms --sse-kms-key-id alias/vaultai/backups

rm -f "/tmp/vaultai-$(date +%Y-%m-%d).dump"
```

### 1.2 Object storage — daily mirror

If a separate object store (S3 / GCS) ever holds VaultAI encrypted file blobs (the current build keeps them in Postgres as `bytea`, so this section is conditional):

```
Schedule
  daily 02:30 UTC      aws s3 sync src-bucket → backup-bucket (--delete OFF)
Retention
  versioning ON on the backup bucket; lifecycle = expire noncurrent after 35 days
```

### 1.3 Pre-deploy snapshot — every release

`DEPLOYMENT_RUNBOOK.md §3.2` mandates an extra ad-hoc `pg_dump` immediately before `alembic upgrade head`. Tag the file `pre-deploy-<UTC timestamp>.dump` and upload to the same bucket under `db/pre-deploy/`.

### 1.4 Backup verification — weekly

Operators MUST restore the most recent daily snapshot into a throwaway database every Monday morning UTC and run the restore-test below. A backup that has never been restored is not a backup.

```bash
createdb vaultai_restore_test
pg_restore --no-owner --no-privileges --dbname=vaultai_restore_test \
  /tmp/vaultai-<latest>.dump

psql vaultai_restore_test <<'SQL'
  SELECT count(*) AS accounts FROM accounts;
  SELECT count(*) AS vaults   FROM vault_names;
  SELECT count(*) AS items    FROM vault_items;
  SELECT count(*) AS files    FROM uploaded_files;
  SELECT max(created_at) AS last_write FROM vault_items;
SQL
```

Counts and `last_write` must match the live cluster within tolerance for the time of day. Drop the test DB after verification:

```bash
dropdb vaultai_restore_test
```

---

## 2. Stripe / customer reconciliation

Stripe events are durable upstream — Stripe retries failed webhooks for up to 3 days. Our `provider_event_log` table dedup is keyed on `(source, source_event_id)` so re-delivery is idempotent.

### 2.1 If the database is restored from a snapshot

After a DB restore that loses some `provider_event_log` rows, **replay missing events from Stripe**, not from local logs:

```
1. Identify the timestamp T of the restored snapshot.
2. In the Stripe dashboard → Developers → Events, list events with
   created >= T.
3. For each missing event, click "Resend" to fire the webhook again.
   The handler is idempotent — a duplicate replay is a no-op.
4. Verify provider_event_log row counts match Stripe's event count
   for the recovered window.
```

### 2.2 If a customer reports a missing entitlement

```
1. Look up the account in accounts WHERE email = ?.
2. Look up provider_event_log for that customer (join via stripe_customer_id).
3. Compare with Stripe dashboard → Customers → search.
4. If a checkout.session.completed is in Stripe but NOT in our log,
   replay the event from §2.1 step 3.
```

---

## 3. Restore procedure

Only run from a maintenance window. The backend service must be stopped to prevent split-brain.

### 3.1 Stop the backend cleanly

```bash
sudo systemctl stop vaultai-backend
# or whatever stop-command the platform uses; confirm the process exited
```

### 3.2 Snapshot the current (broken) state before restore

Even when restoring, snapshot what you have first. If the restore goes sideways you still have the broken state to forensics.

```bash
pg_dump --format=custom --no-owner --no-privileges \
  --file="/tmp/vaultai-pre-restore-$(date +%Y%m%dT%H%M%S).dump" \
  "$DATABASE_URL"
```

### 3.3 Restore the target dump

```bash
# Wipe and recreate the target database.
psql postgres -c "DROP DATABASE vaultai_prod;"
psql postgres -c "CREATE DATABASE vaultai_prod;"

# Restore.
pg_restore --no-owner --no-privileges \
  --dbname=vaultai_prod \
  /backups/db/<chosen-dump>.dump

# Apply WAL replay to point-in-time if needed.
# (Wired through pgBackRest or barman; consult the cluster-specific docs.)
```

### 3.4 Verify

```bash
psql "$DATABASE_URL" <<'SQL'
  SELECT count(*) FROM accounts;
  SELECT count(*) FROM vault_names;
  SELECT count(*) FROM vault_items;
  SELECT count(*) FROM uploaded_files;
  SELECT max(created_at) FROM vault_items;
SQL

curl https://api.vaultai.com/health      # expects 503 — backend still down
```

### 3.5 Re-apply migrations if the dump was older than the deployed code

```bash
cd vault_ai_backend
alembic current        # what the dump claims
alembic upgrade head   # bring forward
```

### 3.6 Restart the backend

```bash
sudo systemctl start vaultai-backend
curl https://api.vaultai.com/health      # expects 200 ok
```

### 3.7 Replay missing Stripe events

Per §2.1.

---

## 4. Migration rollback

### 4.1 Additive migrations (most common)

Most VaultAI migrations are additive — new column, new table, new index. The previous app version can continue running against the new schema because it ignores the new columns. No rollback required; just revert the application image.

### 4.2 Destructive migrations

Only migrations `0001`–`0004` and `0017` carry destructive operations (`DROP COLUMN`, `DROP TABLE`, each guarded by `IF EXISTS`). Future destructive migrations must follow the same pattern.

Rollback procedure for a destructive migration:

```
1. Restore the pre-deploy snapshot (DEPLOYMENT_RUNBOOK §3.2).
2. Re-run the rollback path of the migration:
     alembic downgrade -1
   Verify the dropped column/table is back and matches the dump.
3. Re-deploy the previous app version.
4. Investigate why the destructive change was wrong before re-attempting.
```

### 4.3 Schema-inside-encrypted-blob

Crypto Vault records (`crypto_wallet_profile_v1`, `crypto_sensitive_backup_v1`, `crypto_note_v1`) carry a `schema` string inside the encrypted JSON blob. Adding new fields to a schema is non-breaking — older readers ignore unknown fields. Renaming or deleting fields requires a per-record reader fallback in `crypto_schemas.py`. There is NO migration step for a blob-schema change — the schema string in each row is authoritative.

---

## 5. Emergency account recovery — policy

This section governs what an operator can do for a user who has lost their PIN. It is intentionally short.

### 5.1 What an operator CAN do

- Reset the email address on the account row (after identity verification through the support channel).
- Delete the account row entirely (the user loses everything — the encrypted blobs become unreadable but storage is freed).
- Verify the account is still receiving paid-tier entitlements through Stripe.
- Trigger a fresh device-trust pairing from the user's primary email address.

### 5.2 What an operator CANNOT do

- **Decrypt vault contents.** Not even with full DB + filesystem access.
- **Recover a forgotten PIN.** The PIN-derived key is the only path to the AES blob. PBKDF2 makes brute force economically infeasible at the 100k-iteration count used.
- **Reset a PIN on behalf of a user.** The PIN is the only thing that proves the user, not VaultAI, holds the key.
- **View the contents of a secure item, note, file, or sensitive backup.** All `decrypt_message` calls require a key derived from the live PIN; the key is never persisted server-side.

### 5.3 If the user has forgotten the PIN

The only recourse is account deletion + restart. State this plainly:

> "We cannot recover a forgotten PIN. The PIN you set is the only key
> that can decrypt your vault. If you have lost it, the encrypted
> contents cannot be read by anyone — including VaultAI. We can
> delete the account so you can create a fresh one, but the existing
> contents will be permanently unreadable."

---

## 6. Disaster recovery — RTO / RPO targets

| Scenario                                   | RTO    | RPO    | Procedure                                  |
|--------------------------------------------|--------|--------|--------------------------------------------|
| Backend host failure                       | 5 min  | 0      | Restart on a spare host; no data loss.     |
| Database hardware failure                  | 30 min | 15 min | Restore latest daily + WAL replay.         |
| Region outage                              | 2 h    | 1 h    | Restore latest daily into a fresh region.  |
| Accidental destructive migration           | 1 h    | 15 min | Pre-deploy snapshot + WAL replay.          |
| Operator deletes a single account by mistake | 1 h | <24 h | Restore latest daily into a scratch DB; re-export the single account; load into prod. |

If RTO/RPO does not meet a particular customer's contract, escalate per the incident-response runbook.

---

## 7. What we never back up

- **PINs.** They are not stored. No backup needed.
- **Vault keys.** They are derived from PINs at request time. No persistent storage means nothing to back up.
- **Session tokens.** Short-lived; rolling forward through a new sign-in is the recovery path.
- **In-memory rate-limit buckets.** Process-local; restart resets them.

---

Last reviewed: 2026-06-30. See git for revision history.
