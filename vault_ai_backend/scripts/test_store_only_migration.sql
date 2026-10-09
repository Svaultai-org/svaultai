-- Disposable PostgreSQL 17 staging validation for migration 0046.
-- NEVER connect this script to production.
-- Run only in a fresh container database named svaultai_store_only_staging:
--   psql -X -v ON_ERROR_STOP=1 -d svaultai_store_only_staging -f this_file.sql
-- Fixture names, identifiers and ciphertext below are synthetic.
-- All objects/data are transaction-local and are rolled back after assertions.
-- The migration SQL is captured verbatim from 0046_store_only_billing.upgrade().
-- Its downgrade() emits zero SQL and cannot restore retired billing paths.

\set ON_ERROR_STOP on
\set VERBOSITY verbose

BEGIN;
DO $$
BEGIN
    IF current_database() <> 'svaultai_store_only_staging' THEN
        RAISE EXCEPTION 'Refusing non-staging database: %', current_database();
    END IF;
END;
$$;

CREATE SCHEMA svaultai_store_only_migration_staging;
SET LOCAL search_path TO svaultai_store_only_migration_staging;

-- Minimal schemas matching the relevant 0042/0043/0044 fields and constraints.
CREATE TABLE accounts (account_id UUID PRIMARY KEY);
CREATE TABLE account_subscriptions (
    account_id UUID PRIMARY KEY REFERENCES accounts(account_id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'none',
    source_subscription_id TEXT,
    status TEXT NOT NULL DEFAULT 'none',
    purchased_bytes BIGINT NOT NULL DEFAULT 0,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE billing_entitlements (
    entitlement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    entitlement_family TEXT NOT NULL DEFAULT 'storage',
    external_purchase_id TEXT NOT NULL,
    original_transaction_id TEXT,
    product_id TEXT NOT NULL DEFAULT 'synthetic.storage.monthly',
    verification_state TEXT NOT NULL DEFAULT 'verified',
    status TEXT NOT NULL DEFAULT 'active',
    entitlement_bytes BIGINT NOT NULL DEFAULT 53687091200,
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, external_purchase_id)
);
CREATE UNIQUE INDEX billing_entitlements_one_google_storage_grant_uniq
    ON billing_entitlements (account_id, provider, entitlement_family)
    WHERE provider = 'google_play'
      AND entitlement_family = 'storage'
      AND verification_state = 'verified'
      AND status IN ('active', 'reactivated', 'grace_period');
CREATE TABLE billing_provider_ownership (
    account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    entitlement_family TEXT NOT NULL DEFAULT 'storage',
    current_provider TEXT NOT NULL DEFAULT 'free'
        CHECK (current_provider IN ('free', 'google_play', 'apple', 'web_card')),
    current_entitlement_id UUID REFERENCES billing_entitlements(entitlement_id)
        ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
    legacy_subscription_account_id UUID REFERENCES account_subscriptions(account_id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    legacy_source_subscription_id TEXT,
    legacy_provider TEXT CHECK (legacy_provider IS NULL OR legacy_provider = 'stripe_legacy'),
    target_provider TEXT CHECK (target_provider IS NULL OR target_provider IN ('google_play', 'apple', 'web_card')),
    target_entitlement_id UUID REFERENCES billing_entitlements(entitlement_id)
        ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
    migration_status TEXT NOT NULL DEFAULT 'none'
        CHECK (migration_status IN ('none', 'pending', 'conflict', 'completed', 'canceled')),
    reason_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account_id, entitlement_family),
    CHECK (migration_status <> 'pending' OR
           (target_provider IS NOT NULL AND target_provider <> current_provider)),
    CHECK (current_entitlement_id IS NULL OR legacy_subscription_account_id IS NULL),
    CHECK ((legacy_subscription_account_id IS NULL) = (legacy_provider IS NULL)),
    CHECK (legacy_subscription_account_id IS NULL OR current_provider = 'web_card')
);
CREATE TABLE synthetic_encrypted_payloads (
    account_id UUID PRIMARY KEY REFERENCES accounts(account_id),
    ciphertext BYTEA NOT NULL
);
CREATE TABLE subscription_events (
    event_id UUID PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(account_id),
    source TEXT NOT NULL,
    payload_jsonb JSONB NOT NULL
);
-- Minimal old-trigger fixtures prove migration removes legacy trigger/function
-- and replaces the store-owner trigger rather than leaving a stale hook.
CREATE FUNCTION enforce_legacy_storage_billing_owner()
RETURNS TRIGGER AS $$ BEGIN RETURN NEW; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER account_subscriptions_one_storage_owner
    BEFORE INSERT OR UPDATE ON account_subscriptions
    FOR EACH ROW EXECUTE FUNCTION enforce_legacy_storage_billing_owner();
CREATE FUNCTION enforce_storage_billing_owner()
RETURNS TRIGGER AS $$ BEGIN RETURN NEW; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER billing_entitlements_one_storage_owner
    BEFORE INSERT OR UPDATE ON billing_entitlements
    FOR EACH ROW EXECUTE FUNCTION enforce_storage_billing_owner();

INSERT INTO accounts
SELECT ('00000000-0000-0000-0000-' || lpad(n::TEXT, 12, '0'))::UUID
FROM generate_series(1, 9) n;
INSERT INTO synthetic_encrypted_payloads
SELECT account_id, decode('aabbcc0011223344', 'hex') FROM accounts;
INSERT INTO account_subscriptions (
    account_id, source, source_subscription_id, status, purchased_bytes
) VALUES (
    '00000000-0000-0000-0000-000000000001', 'stripe',
    'synthetic-legacy-subscription', 'active', 53687091200
);
INSERT INTO subscription_events VALUES (
    '30000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    'stripe', '{"synthetic":"historic payment record"}'
);

-- 1 retired; 2 live Apple; 3 live Play; 4 missing expiry; 5 lapsed Play;
-- 6 pre-existing Apple/Play conflict; 7 NULL-old recovery; 8 expired-old
-- recovery; 9 starts free for a new cross-provider conflict check.
INSERT INTO billing_entitlements (
    entitlement_id, account_id, provider, external_purchase_id,
    original_transaction_id, current_period_end
) VALUES
('20000000-0000-0000-0000-000000000011', '00000000-0000-0000-0000-000000000001', 'stripe_legacy', 'synthetic-legacy-ledger', NULL, NULL),
('20000000-0000-0000-0000-000000000012', '00000000-0000-0000-0000-000000000002', 'apple', 'apple-live-2', 'apple-original-2', NOW() + INTERVAL '30 days'),
('20000000-0000-0000-0000-000000000013', '00000000-0000-0000-0000-000000000003', 'google_play', 'play-live-3', NULL, NOW() + INTERVAL '30 days'),
('20000000-0000-0000-0000-000000000014', '00000000-0000-0000-0000-000000000004', 'apple', 'apple-null-4', 'apple-original-4', NULL),
('20000000-0000-0000-0000-000000000015', '00000000-0000-0000-0000-000000000005', 'google_play', 'play-expired-5', NULL, NOW() - INTERVAL '1 day'),
('20000000-0000-0000-0000-000000000016', '00000000-0000-0000-0000-000000000006', 'apple', 'apple-conflict-6', 'apple-original-6', NOW() + INTERVAL '30 days'),
('20000000-0000-0000-0000-000000000017', '00000000-0000-0000-0000-000000000006', 'google_play', 'play-conflict-6', NULL, NOW() + INTERVAL '30 days'),
('20000000-0000-0000-0000-000000000018', '00000000-0000-0000-0000-000000000007', 'apple', 'apple-null-7', 'apple-original-7', NULL),
('20000000-0000-0000-0000-000000000019', '00000000-0000-0000-0000-000000000007', 'google_play', 'play-live-7', NULL, NOW() + INTERVAL '30 days'),
('20000000-0000-0000-0000-000000000020', '00000000-0000-0000-0000-000000000008', 'apple', 'apple-expired-8', 'apple-original-8', NOW() - INTERVAL '1 day'),
('20000000-0000-0000-0000-000000000021', '00000000-0000-0000-0000-000000000008', 'google_play', 'play-live-8', NULL, NOW() + INTERVAL '30 days');
INSERT INTO billing_provider_ownership (
    account_id, current_provider, current_entitlement_id,
    legacy_subscription_account_id, legacy_source_subscription_id,
    legacy_provider, migration_status, reason_code
) VALUES
('00000000-0000-0000-0000-000000000001', 'web_card', NULL, '00000000-0000-0000-0000-000000000001', 'synthetic-legacy-subscription', 'stripe_legacy', 'none', NULL),
('00000000-0000-0000-0000-000000000002', 'apple', '20000000-0000-0000-0000-000000000012', NULL, NULL, NULL, 'none', NULL),
('00000000-0000-0000-0000-000000000003', 'google_play', '20000000-0000-0000-0000-000000000013', NULL, NULL, NULL, 'none', NULL),
('00000000-0000-0000-0000-000000000004', 'apple', '20000000-0000-0000-0000-000000000014', NULL, NULL, NULL, 'none', NULL),
('00000000-0000-0000-0000-000000000005', 'google_play', '20000000-0000-0000-0000-000000000015', NULL, NULL, NULL, 'none', NULL),
('00000000-0000-0000-0000-000000000006', 'apple', '20000000-0000-0000-0000-000000000016', NULL, NULL, NULL, 'conflict', 'multiple_active_storage_entitlements'),
('00000000-0000-0000-0000-000000000007', 'google_play', '20000000-0000-0000-0000-000000000019', NULL, NULL, NULL, 'none', NULL),
('00000000-0000-0000-0000-000000000008', 'google_play', '20000000-0000-0000-0000-000000000021', NULL, NULL, NULL, 'none', NULL);

CREATE TEMP TABLE expected_legacy AS SELECT to_jsonb(s) AS payload FROM account_subscriptions s;
CREATE TEMP TABLE expected_entitlements AS SELECT to_jsonb(e) AS payload FROM billing_entitlements e;
CREATE TEMP TABLE expected_events AS SELECT to_jsonb(e) AS payload FROM subscription_events e;
CREATE TEMP TABLE expected_encrypted AS SELECT to_jsonb(p) AS payload FROM synthetic_encrypted_payloads p;

-- BEGIN verbatim migration 0046 upgrade SQL (three op.execute statements).

        DROP TRIGGER IF EXISTS account_subscriptions_one_storage_owner
            ON account_subscriptions;
        DROP FUNCTION IF EXISTS enforce_legacy_storage_billing_owner();
        DROP TRIGGER IF EXISTS billing_entitlements_one_storage_owner
            ON billing_entitlements;
        


        UPDATE billing_provider_ownership o
           SET current_provider = 'free', current_entitlement_id = NULL,
               legacy_subscription_account_id = NULL,
               legacy_source_subscription_id = NULL, legacy_provider = NULL,
               target_provider = NULL, target_entitlement_id = NULL,
               migration_status = 'none', reason_code = NULL,
               updated_at = NOW()
         WHERE o.current_provider NOT IN ('apple', 'google_play')
            OR o.legacy_subscription_account_id IS NOT NULL
            OR (o.entitlement_family = 'storage' AND NOT EXISTS (
                   SELECT 1 FROM billing_entitlements e
                    WHERE e.entitlement_id = o.current_entitlement_id
                      AND e.account_id = o.account_id
                      AND e.entitlement_family = 'storage'
                      AND e.provider IN ('apple', 'google_play')
                      AND e.verification_state = 'verified'
                      AND e.status IN ('active', 'reactivated', 'grace_period')
                      AND e.current_period_end > NOW()
               ));

        UPDATE billing_provider_ownership
           SET legacy_subscription_account_id = NULL,
               legacy_source_subscription_id = NULL, legacy_provider = NULL,
               target_provider = NULL, target_entitlement_id = NULL,
               migration_status = 'none', reason_code = NULL,
               updated_at = NOW();

        WITH candidates AS (
            SELECT e.account_id, e.entitlement_family, e.entitlement_id,
                   e.provider,
                   COUNT(*) OVER (
                       PARTITION BY e.account_id, e.entitlement_family
                   ) AS granting_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY e.account_id, e.entitlement_family
                       ORDER BY (e.entitlement_id = o.current_entitlement_id)
                                    DESC NULLS LAST,
                                e.created_at, e.provider, e.external_purchase_id
                   ) AS owner_rank
              FROM billing_entitlements e
              LEFT JOIN billing_provider_ownership o
                ON o.account_id = e.account_id
               AND o.entitlement_family = e.entitlement_family
             WHERE e.entitlement_family = 'storage'
               AND e.provider IN ('apple', 'google_play')
               AND e.verification_state = 'verified'
               AND e.status IN ('active', 'reactivated', 'grace_period')
               AND e.current_period_end > NOW()
        )
        INSERT INTO billing_provider_ownership (
            account_id, entitlement_family, current_provider,
            current_entitlement_id, migration_status, reason_code, updated_at
        )
        SELECT account_id, entitlement_family, provider, entitlement_id,
               CASE WHEN granting_count > 1 THEN 'conflict' ELSE 'none' END,
               CASE WHEN granting_count > 1
                    THEN 'multiple_active_storage_entitlements' ELSE NULL END,
               NOW()
          FROM candidates WHERE owner_rank = 1
        ON CONFLICT (account_id, entitlement_family) DO UPDATE
           SET current_provider = EXCLUDED.current_provider,
               current_entitlement_id = EXCLUDED.current_entitlement_id,
               migration_status = EXCLUDED.migration_status,
               reason_code = EXCLUDED.reason_code, updated_at = NOW();

        -- Flush deferred ownership FK events before ALTER TABLE. PostgreSQL
        -- rejects DDL on a table with queued deferred trigger events (55006).
        -- Restore these originally-deferred pointers after the DDL; unrelated
        -- constraint modes and schema deferrability remain unchanged.
        SET CONSTRAINTS
            billing_provider_ownership_current_entitlement_id_fkey,
            billing_provider_ownership_legacy_subscription_account_id_fkey,
            billing_provider_ownership_target_entitlement_id_fkey
            IMMEDIATE;

        ALTER TABLE billing_provider_ownership
            ADD CONSTRAINT storage_owner_store_only_provider
                CHECK (current_provider IN ('free', 'apple', 'google_play')),
            ADD CONSTRAINT storage_owner_store_only_target
                CHECK (target_provider IS NULL
                       OR target_provider IN ('apple', 'google_play')),
            ADD CONSTRAINT storage_owner_no_legacy_connection
                CHECK (legacy_subscription_account_id IS NULL
                       AND legacy_source_subscription_id IS NULL
                       AND legacy_provider IS NULL);

        SET CONSTRAINTS
            billing_provider_ownership_current_entitlement_id_fkey,
            billing_provider_ownership_legacy_subscription_account_id_fkey,
            billing_provider_ownership_target_entitlement_id_fkey
            DEFERRED;
        


        CREATE OR REPLACE FUNCTION enforce_storage_billing_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            new_grants BOOLEAN;
            same_live_purchase BOOLEAN := FALSE;
            granting_count BIGINT;
            preferred_owner UUID;
            selected_owner UUID;
            selected_provider TEXT;
        BEGIN
            IF NEW.entitlement_family <> 'storage' THEN
                RETURN NEW;
            END IF;

            -- A single family lock also serializes Apple against Google Play.
            PERFORM pg_advisory_xact_lock(hashtextextended(
                NEW.account_id::TEXT || chr(58) || 'storage', 0
            ));
            new_grants := NEW.provider IN ('apple', 'google_play')
                AND NEW.verification_state = 'verified'
                AND NEW.status IN ('active', 'reactivated', 'grace_period')
                AND NEW.current_period_end IS NOT NULL
                AND NEW.current_period_end > NOW();

            IF TG_OP = 'UPDATE' THEN
                same_live_purchase :=
                    OLD.account_id = NEW.account_id
                    AND OLD.entitlement_id = NEW.entitlement_id
                    AND OLD.entitlement_family = NEW.entitlement_family
                    AND OLD.provider = NEW.provider
                    AND (
                        OLD.external_purchase_id = NEW.external_purchase_id
                        OR (
                            OLD.provider = 'apple'
                            AND OLD.original_transaction_id IS NOT NULL
                            AND OLD.original_transaction_id <> ''
                            AND OLD.original_transaction_id =
                                NEW.original_transaction_id
                        )
                    )
                    AND OLD.provider IN ('apple', 'google_play')
                    AND OLD.verification_state = 'verified'
                    AND OLD.status IN ('active', 'reactivated', 'grace_period')
                    AND OLD.current_period_end IS NOT NULL
                    AND OLD.current_period_end > NOW();
            END IF;

            SELECT COUNT(*) INTO granting_count
              FROM billing_entitlements e
             WHERE e.account_id = NEW.account_id
               AND e.entitlement_family = 'storage'
               AND e.provider IN ('apple', 'google_play')
               AND e.verification_state = 'verified'
               AND e.status IN ('active', 'reactivated', 'grace_period')
               AND e.current_period_end > NOW();

            -- Existing conflicts remain reconcilable by provider lifecycle
            -- updates; a new or reactivated second purchase is rejected.
            IF new_grants AND granting_count > 1 AND NOT same_live_purchase
            THEN
                RAISE EXCEPTION 'second active store storage entitlement rejected'
                    USING ERRCODE = '23505',
                          CONSTRAINT = 'one_active_storage_billing_owner';
            END IF;

            SELECT current_entitlement_id INTO preferred_owner
              FROM billing_provider_ownership
             WHERE account_id = NEW.account_id
               AND entitlement_family = 'storage'
             FOR UPDATE;

            SELECT e.entitlement_id, e.provider
              INTO selected_owner, selected_provider
              FROM billing_entitlements e
             WHERE e.account_id = NEW.account_id
               AND e.entitlement_family = 'storage'
               AND e.provider IN ('apple', 'google_play')
               AND e.verification_state = 'verified'
               AND e.status IN ('active', 'reactivated', 'grace_period')
               AND e.current_period_end > NOW()
             ORDER BY (e.entitlement_id = preferred_owner) DESC NULLS LAST,
                      e.created_at, e.provider, e.external_purchase_id
             LIMIT 1;

            INSERT INTO billing_provider_ownership (
                account_id, entitlement_family, current_provider,
                current_entitlement_id, migration_status, reason_code,
                updated_at
            ) VALUES (
                NEW.account_id, 'storage', COALESCE(selected_provider, 'free'),
                selected_owner,
                CASE WHEN granting_count > 1 THEN 'conflict' ELSE 'none' END,
                CASE WHEN granting_count > 1
                     THEN 'multiple_active_storage_entitlements' ELSE NULL END,
                NOW()
            )
            ON CONFLICT (account_id, entitlement_family) DO UPDATE
               SET current_provider = EXCLUDED.current_provider,
                   current_entitlement_id = EXCLUDED.current_entitlement_id,
                   target_provider = NULL, target_entitlement_id = NULL,
                   migration_status = EXCLUDED.migration_status,
                   reason_code = EXCLUDED.reason_code, updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER billing_entitlements_one_storage_owner
            AFTER INSERT OR UPDATE OF account_id, provider, entitlement_family,
                external_purchase_id, original_transaction_id,
                verification_state, status,
                current_period_end
            ON billing_entitlements
            FOR EACH ROW EXECUTE FUNCTION enforce_storage_billing_owner();
        

-- END verbatim migration 0046 upgrade SQL.

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM pg_constraint
        WHERE conrelid = 'billing_provider_ownership'::regclass
          AND conname IN (
              'billing_provider_ownership_current_entitlement_id_fkey',
              'billing_provider_ownership_legacy_subscription_account_id_fkey',
              'billing_provider_ownership_target_entitlement_id_fkey')
          AND condeferrable AND condeferred) <> 3 THEN
        RAISE EXCEPTION 'Migration changed originally deferred ownership FK schema';
    END IF;
    -- A temporary forward pointer must remain legal until transaction end.
    -- Restoring it proves SET CONSTRAINTS returned to DEFERRED, not merely
    -- that the pg_constraint declaration remained initially deferred.
    BEGIN
        UPDATE billing_provider_ownership
           SET current_entitlement_id = '40000000-0000-0000-0000-000000000001'
         WHERE account_id = '00000000-0000-0000-0000-000000000002';
        UPDATE billing_provider_ownership
           SET current_entitlement_id = '20000000-0000-0000-0000-000000000012'
         WHERE account_id = '00000000-0000-0000-0000-000000000002';
    EXCEPTION WHEN foreign_key_violation THEN
        RAISE EXCEPTION 'Migration did not restore ownership FK transaction mode to deferred';
    END;
    IF EXISTS ((SELECT payload FROM expected_legacy)
               EXCEPT (SELECT to_jsonb(s) FROM account_subscriptions s))
       OR EXISTS ((SELECT to_jsonb(s) FROM account_subscriptions s)
                  EXCEPT (SELECT payload FROM expected_legacy))
       OR EXISTS ((SELECT payload FROM expected_entitlements)
                  EXCEPT (SELECT to_jsonb(e) FROM billing_entitlements e))
       OR EXISTS ((SELECT to_jsonb(e) FROM billing_entitlements e)
                  EXCEPT (SELECT payload FROM expected_entitlements))
       OR EXISTS ((SELECT payload FROM expected_events)
                  EXCEPT (SELECT to_jsonb(e) FROM subscription_events e))
       OR EXISTS ((SELECT to_jsonb(e) FROM subscription_events e)
                  EXCEPT (SELECT payload FROM expected_events))
       OR EXISTS ((SELECT payload FROM expected_encrypted)
                  EXCEPT (SELECT to_jsonb(p) FROM synthetic_encrypted_payloads p))
       OR EXISTS ((SELECT to_jsonb(p) FROM synthetic_encrypted_payloads p)
                  EXCEPT (SELECT payload FROM expected_encrypted)) THEN
        RAISE EXCEPTION 'Retirement changed billing history or encrypted payloads';
    END IF;
    IF EXISTS (SELECT 1 FROM billing_provider_ownership
               WHERE current_provider NOT IN ('free', 'apple', 'google_play')
                  OR legacy_subscription_account_id IS NOT NULL
                  OR legacy_source_subscription_id IS NOT NULL
                  OR legacy_provider IS NOT NULL) THEN
        RAISE EXCEPTION 'Retired owner connection remains';
    END IF;
    IF EXISTS (SELECT 1 FROM billing_provider_ownership
               WHERE account_id IN (
                   '00000000-0000-0000-0000-000000000001',
                   '00000000-0000-0000-0000-000000000004',
                   '00000000-0000-0000-0000-000000000005')
                 AND (current_provider <> 'free' OR current_entitlement_id IS NOT NULL)) THEN
        RAISE EXCEPTION 'Legacy, NULL-expiry or expired owner did not become free';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                   WHERE account_id = '00000000-0000-0000-0000-000000000002'
                     AND current_provider = 'apple'
                     AND current_entitlement_id = '20000000-0000-0000-0000-000000000012')
       OR NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                      WHERE account_id = '00000000-0000-0000-0000-000000000003'
                        AND current_provider = 'google_play') THEN
        RAISE EXCEPTION 'Valid future Apple/Play owner was not retained';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                   WHERE account_id = '00000000-0000-0000-0000-000000000006'
                     AND current_provider = 'apple'
                     AND current_entitlement_id = '20000000-0000-0000-0000-000000000016'
                     AND migration_status = 'conflict') THEN
        RAISE EXCEPTION 'Existing live conflict was not preserved deterministically';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_trigger
               WHERE tgrelid = 'account_subscriptions'::regclass
                 AND tgname = 'account_subscriptions_one_storage_owner')
       OR to_regprocedure('enforce_legacy_storage_billing_owner()') IS NOT NULL THEN
        RAISE EXCEPTION 'Legacy ownership trigger/function is still installed';
    END IF;
END;
$$;

-- Assert a failed new store grant raises our named invariant, not some
-- unrelated uniqueness error, and leaves no partial ownership mutation.
CREATE FUNCTION pg_temp.expect_second_owner_rejected(statement TEXT)
RETURNS VOID AS $$
DECLARE rejected_constraint TEXT;
BEGIN
    BEGIN
        EXECUTE statement;
        RAISE EXCEPTION 'Expected second store grant rejection, but statement succeeded';
    EXCEPTION WHEN unique_violation THEN
        GET STACKED DIAGNOSTICS rejected_constraint = CONSTRAINT_NAME;
        IF rejected_constraint <> 'one_active_storage_billing_owner' THEN
            RAISE EXCEPTION 'Wrong uniqueness rejection: %', rejected_constraint;
        END IF;
    END;
END;
$$ LANGUAGE plpgsql;

-- New cross-provider second purchase must fail, while the first remains.
INSERT INTO billing_entitlements (
    entitlement_id, account_id, provider, external_purchase_id,
    original_transaction_id, current_period_end
) VALUES (
    '20000000-0000-0000-0000-000000000029',
    '00000000-0000-0000-0000-000000000009',
    'apple', 'apple-new-9', 'apple-original-9', NOW() + INTERVAL '30 days'
);
SELECT pg_temp.expect_second_owner_rejected($statement$
    INSERT INTO billing_entitlements (
        entitlement_id, account_id, provider, external_purchase_id, current_period_end
    ) VALUES (
        '20000000-0000-0000-0000-000000000030',
        '00000000-0000-0000-0000-000000000009',
        'google_play', 'play-rejected-9', NOW() + INTERVAL '30 days'
    )
$statement$);

-- NULL and expired OLD expiry cannot grandfather reactivation when another
-- store currently grants, even when Apple's original ID is unchanged.
SELECT pg_temp.expect_second_owner_rejected($statement$
    UPDATE billing_entitlements
       SET external_purchase_id = 'apple-null-recovery-7',
           current_period_end = NOW() + INTERVAL '30 days'
     WHERE entitlement_id = '20000000-0000-0000-0000-000000000018'
$statement$);
SELECT pg_temp.expect_second_owner_rejected($statement$
    UPDATE billing_entitlements
       SET external_purchase_id = 'apple-expired-recovery-8',
           current_period_end = NOW() + INTERVAL '30 days'
     WHERE entitlement_id = '20000000-0000-0000-0000-000000000020'
$statement$);

-- Apple renewals use a new transaction ID but the same original subscription.
-- A verified lifecycle update of an already-live conflict must still apply.
UPDATE billing_entitlements
   SET external_purchase_id = 'apple-renewal-6',
       current_period_end = NOW() + INTERVAL '60 days'
 WHERE entitlement_id = '20000000-0000-0000-0000-000000000016';
SELECT pg_temp.expect_second_owner_rejected($statement$
    UPDATE billing_entitlements
       SET external_purchase_id = 'apple-different-purchase-6',
           original_transaction_id = 'apple-different-original-6',
           current_period_end = NOW() + INTERVAL '90 days'
     WHERE entitlement_id = '20000000-0000-0000-0000-000000000016'
$statement$);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM billing_entitlements
                   WHERE entitlement_id = '20000000-0000-0000-0000-000000000016'
                     AND external_purchase_id = 'apple-renewal-6'
                     AND original_transaction_id = 'apple-original-6')
       OR NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                      WHERE account_id = '00000000-0000-0000-0000-000000000006'
                        AND current_provider = 'apple'
                        AND migration_status = 'conflict') THEN
        RAISE EXCEPTION 'Same-original Apple renewal failed or a new original bypassed conflict';
    END IF;
    IF EXISTS (SELECT 1 FROM billing_entitlements
               WHERE external_purchase_id = 'play-rejected-9')
       OR NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                      WHERE account_id = '00000000-0000-0000-0000-000000000009'
                        AND current_provider = 'apple') THEN
        RAISE EXCEPTION 'Rejected second provider left a partial grant';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM billing_entitlements
                   WHERE entitlement_id = '20000000-0000-0000-0000-000000000018'
                     AND current_period_end IS NULL)
       OR NOT EXISTS (SELECT 1 FROM billing_entitlements
                      WHERE entitlement_id = '20000000-0000-0000-0000-000000000020'
                        AND current_period_end < NOW()) THEN
        RAISE EXCEPTION 'NULL/expired recovery was not rolled back safely';
    END IF;
END;
$$;

-- Expiry/refund releases conflicts and ownership without deleting purchases.
UPDATE billing_entitlements SET status = 'revoked', current_period_end = NOW()
 WHERE entitlement_id = '20000000-0000-0000-0000-000000000017';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                   WHERE account_id = '00000000-0000-0000-0000-000000000006'
                     AND current_provider = 'apple'
                     AND migration_status = 'none' AND reason_code IS NULL) THEN
        RAISE EXCEPTION 'Conflict did not resolve after competing store revocation';
    END IF;
END;
$$;
UPDATE billing_entitlements SET current_period_end = NOW() - INTERVAL '1 minute'
 WHERE entitlement_id = '20000000-0000-0000-0000-000000000016';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                   WHERE account_id = '00000000-0000-0000-0000-000000000006'
                     AND current_provider = 'free' AND current_entitlement_id IS NULL) THEN
        RAISE EXCEPTION 'Lapsed last store owner still grants';
    END IF;
END;
$$;
-- No competing live purchase: a valid new expiry can reactivate the record.
UPDATE billing_entitlements
   SET external_purchase_id = 'apple-reactivated-6',
       current_period_end = NOW() + INTERVAL '30 days'
 WHERE entitlement_id = '20000000-0000-0000-0000-000000000016';
UPDATE billing_entitlements SET current_period_end = NOW() + INTERVAL '30 days'
 WHERE entitlement_id = '20000000-0000-0000-0000-000000000014';
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                   WHERE account_id = '00000000-0000-0000-0000-000000000006'
                     AND current_provider = 'apple' AND migration_status = 'none')
       OR NOT EXISTS (SELECT 1 FROM billing_provider_ownership
                      WHERE account_id = '00000000-0000-0000-0000-000000000004'
                        AND current_provider = 'apple') THEN
        RAISE EXCEPTION 'Safe restore after expiry/missing expiry did not reactivate';
    END IF;
    IF (SELECT COUNT(*) FROM accounts) <> 9
       OR (SELECT COUNT(*) FROM billing_entitlements) <> 12
       OR EXISTS ((SELECT payload FROM expected_legacy)
                  EXCEPT (SELECT to_jsonb(s) FROM account_subscriptions s))
       OR EXISTS ((SELECT payload FROM expected_events)
                  EXCEPT (SELECT to_jsonb(e) FROM subscription_events e))
       OR EXISTS ((SELECT payload FROM expected_encrypted)
                  EXCEPT (SELECT to_jsonb(p) FROM synthetic_encrypted_payloads p)) THEN
        RAISE EXCEPTION 'Lifecycle operations deleted or changed unrelated fixture data';
    END IF;
END;
$$;

-- No COMMIT: passing/failing this file never keeps staging fixture data.
ROLLBACK;
SELECT 'PASS: store-only migration, expiry, ownership, Apple renewal, conflict lifecycle and preserved history/encrypted data' AS result;
