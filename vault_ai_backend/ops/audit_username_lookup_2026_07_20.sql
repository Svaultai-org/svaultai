-- Non-destructive audit queries for the 2026-07-20 username lookup
-- migration. Every query is read-only; none of them delete, update,
-- or merge production rows. Run under a read-only role if available.
--
-- Usage:
--     psql -f audit_username_lookup_2026_07_20.sql "$VAULTAI_DB_URL"
--
-- Or paste an individual block into a psql session for closer look.

\echo '== 1. Vault row counts by lookup / handle status =='
SELECT
    count(*)                                           AS total_rows,
    count(*) FILTER (WHERE vault_handle IS NOT NULL)   AS zk_rows,
    count(*) FILTER (WHERE vault_handle IS NULL)       AS legacy_only_rows,
    count(*) FILTER (WHERE username_lookup_v1 IS NULL) AS null_lookup_rows,
    count(*) FILTER (WHERE username_lookup_v1 IS NOT NULL)
        AS populated_lookup_rows
FROM vaults;

\echo ''
\echo '== 2. Legacy random-handle rows (potential duplicate-registration risk) =='
-- ZK rows with a handle but no lookup identifier: these are the
-- accounts that a fresh registration for the same canonical
-- username can still slip past. Registration prevention only
-- kicks in for these once their owner logs in with the fixed
-- client (opportunistic backfill in zk_login_init).
SELECT
    v.vault_id,
    v.created_at,
    -- 8-hex fingerprint only, never the raw handle bytes.
    encode(digest(v.vault_handle, 'sha256'), 'hex')::text
        AS handle_sha256_fpr,
    v.last_login_at,
    v.last_any_activity_at,
    v.legacy_vault_name_cleared_at IS NULL AS looks_legacy_only
FROM vaults v
WHERE v.vault_handle IS NOT NULL
  AND v.username_lookup_v1 IS NULL
ORDER BY v.created_at ASC
LIMIT 200;

\echo ''
\echo '== 3. Duplicate populated lookup_v1 (violates uniqueness) =='
-- Should be EMPTY after the partial UNIQUE landed. Any row that
-- appears here indicates the index is missing or was violated
-- somehow — investigate before running the operator remediation
-- steps.
SELECT username_lookup_v1_fpr, vault_ids
FROM (
    SELECT
        encode(digest(username_lookup_v1, 'sha256'), 'hex')::text
            AS username_lookup_v1_fpr,
        array_agg(vault_id ORDER BY created_at)
            AS vault_ids,
        count(*) AS n
    FROM vaults
    WHERE username_lookup_v1 IS NOT NULL
    GROUP BY username_lookup_v1
) s
WHERE n > 1
ORDER BY n DESC;

\echo ''
\echo '== 4. Legacy backfill conflict events awaiting operator review =='
-- Written by zk_login_init when a legacy row would have collided
-- during opportunistic backfill. The conflict fingerprint links to
-- the shared lookup_v1 value; login_vault_id is the row that TRIED
-- to backfill; other_vault_id is the row that already carries the
-- value. Never silently merged. Resolve by choosing which vault
-- should keep the username, then either operator-force-backfill or
-- delete the losing row with an operator SQL runbook.
SELECT
    e.id,
    e.observed_at,
    e.login_vault_id,
    e.other_vault_id,
    e.username_lookup_v1_fpr,
    e.resolved_at,
    e.resolution_note
FROM username_lookup_conflict_events e
WHERE e.resolved_at IS NULL
ORDER BY e.observed_at DESC
LIMIT 200;

\echo ''
\echo '== 5. Incomplete OPAQUE registrations (records missing bits) =='
-- A vault row with a vault_handle but no opaque_registration_record
-- is stuck mid-registration and would fail every login attempt.
-- Consider deletion after operator review.
SELECT
    vault_id,
    created_at,
    encode(digest(vault_handle, 'sha256'), 'hex')::text AS handle_sha256_fpr
FROM vaults
WHERE vault_handle IS NOT NULL
  AND opaque_registration_record IS NULL
ORDER BY created_at ASC
LIMIT 200;

\echo ''
\echo '== 6. Dormant legacy accounts (candidates for later cleanup) =='
-- Legacy rows that have not seen any activity for > 12 months AND
-- have no lookup identifier. Report only — never delete without
-- operator sign-off and a fresh backup.
SELECT
    vault_id,
    created_at,
    last_login_at,
    last_any_activity_at
FROM vaults
WHERE username_lookup_v1 IS NULL
  AND coalesce(last_any_activity_at, created_at) < NOW() - INTERVAL '12 months'
ORDER BY coalesce(last_any_activity_at, created_at) ASC
LIMIT 200;
