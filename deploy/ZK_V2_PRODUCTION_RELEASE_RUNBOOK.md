# ZK-V2 production release runbook (all V2 flags off)

This runbook prepares an initial schema/code deployment only. It does not
authorize a production deployment or any V2 migration.

## Read-only preflight

Use a SELECT-only role and stop if the duplicate-group result is nonzero:

```sh
psql "$PRODUCTION_READ_ONLY_DATABASE_URL" \
  --file deploy/zk-v2-production-preflight.sql \
  --output "zk-v2-preflight-${RELEASE_ID}.txt"
```

Record the current Alembic revision, row estimate, relation/index sizes, and
locks. `ALTER TABLE ... ADD COLUMN` takes an `ACCESS EXCLUSIVE` table lock.
Ordinary `CREATE INDEX` operations block concurrent writes while building.
Choose the maintenance window from observed production size and traffic data;
do not infer it from an empty QA database.

## Backup

Set `RELEASE_ID` to a UTC timestamp plus the immutable release commit, for
example `20260810T190000Z-cef5a5a`. Use an operator-controlled directory:

```sh
umask 077
pg_dump "$PRODUCTION_DATABASE_URL" \
  --format=custom \
  --no-owner \
  --no-acl \
  --file "${BACKUP_DIR}/svaultai-${RELEASE_ID}.dump"
sha256sum "${BACKUP_DIR}/svaultai-${RELEASE_ID}.dump" \
  > "${BACKUP_DIR}/svaultai-${RELEASE_ID}.dump.sha256"
pg_restore --list "${BACKUP_DIR}/svaultai-${RELEASE_ID}.dump" \
  > "${BACKUP_DIR}/svaultai-${RELEASE_ID}.restore-list.txt"
sha256sum --check "${BACKUP_DIR}/svaultai-${RELEASE_ID}.dump.sha256"
```

Store the backup ID, UTC timestamp, commit, database server identity, checksum,
row-count preflight output, and restore-list output together.

## Restore rehearsal and emergency restore

Rehearse against a newly created isolated database first. For an emergency
production restore, stop all application writers before replacing the database.

```sh
createdb "$RESTORE_DATABASE_NAME"
pg_restore \
  --exit-on-error \
  --clean \
  --if-exists \
  --no-owner \
  --no-acl \
  --dbname "$RESTORE_DATABASE_URL" \
  "${BACKUP_DIR}/svaultai-${RELEASE_ID}.dump"
psql "$RESTORE_DATABASE_URL" --command \
  'SELECT version_num FROM alembic_version ORDER BY version_num;'
psql "$RESTORE_DATABASE_URL" --file deploy/zk-v2-production-preflight.sql
```

Compare the restored Alembic revision and the preflight row counts with the
captured pre-backup results. Application rollback should normally restore the
previous backend/frontend artifacts while retaining the forward-compatible
schema. Do not downgrade migrations 0036-0040 after V2 data exists because the
downgrades remove V2 tables or columns.

## Abort criteria

Abort before or during migration if any of the following occurs:

- active legacy memory duplicate groups are nonzero;
- the database revision differs from the reviewed starting revision;
- the verified backup, checksum, or restore-list step fails;
- the prior backend or frontend artifact cannot be restored;
- an unexpected V2 flag is true;
- lock wait exceeds the operator-approved maintenance-window budget;
- blocked sessions, migration errors, login failures, wallet writes, signing,
  or transaction-broadcast activity are observed.
