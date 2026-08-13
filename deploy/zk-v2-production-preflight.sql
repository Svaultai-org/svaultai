-- Read-only ZK-V2 production preflight. Run with psql using a database role
-- that has CONNECT/SELECT privileges only. This script performs no writes.
\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;

SELECT version_num AS current_alembic_revision
FROM alembic_version
ORDER BY version_num;

SELECT COUNT(*) AS active_legacy_memory_rows
FROM vault_ai_memory
WHERE superseded_at IS NULL
  AND memory_lookup_hash IS NOT NULL;

SELECT COUNT(*) AS duplicate_active_legacy_lookup_groups
FROM (
  SELECT vault_id, memory_lookup_hash
  FROM vault_ai_memory
  WHERE superseded_at IS NULL
    AND memory_lookup_hash IS NOT NULL
  GROUP BY vault_id, memory_lookup_hash
  HAVING COUNT(*) > 1
) AS duplicates;

SELECT
  c.reltuples::bigint AS estimated_rows,
  pg_total_relation_size(c.oid) AS total_bytes,
  pg_relation_size(c.oid) AS table_bytes,
  pg_indexes_size(c.oid) AS indexes_bytes
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = current_schema()
  AND c.relname = 'vault_ai_memory';

SELECT
  indexrelname AS index_name,
  pg_relation_size(indexrelid) AS index_bytes
FROM pg_stat_user_indexes
WHERE schemaname = current_schema()
  AND relname = 'vault_ai_memory'
ORDER BY indexrelname;

SELECT *
FROM (VALUES
  ('ALTER TABLE vault_ai_memory ADD COLUMN memory_record_id',
   'ACCESS EXCLUSIVE (normally brief metadata change)'),
  ('CREATE UNIQUE INDEX vault_ai_memory_v2_record_uq',
   'table scan; ordinary CREATE INDEX blocks concurrent writes')
) AS planned_operation(operation, lock_or_write_impact);

SELECT
  pid,
  mode,
  granted,
  waitstart IS NOT NULL AS waiting
FROM pg_locks
WHERE relation = 'vault_ai_memory'::regclass
ORDER BY granted, mode, pid;

ROLLBACK;
