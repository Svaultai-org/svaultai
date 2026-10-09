"""Retire non-store storage ownership without deleting payment history.

Only verified, unexpired Apple / Google Play subscriptions can own paid
storage. Historic subscription, entitlement and event rows remain untouched;
no provider is charged, canceled or refunded by this migration.
"""

from alembic import op


revision = "0046_store_only_billing"
down_revision = "0045_private_vault_identifiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS account_subscriptions_one_storage_owner
            ON account_subscriptions;
        DROP FUNCTION IF EXISTS enforce_legacy_storage_billing_owner();
        DROP TRIGGER IF EXISTS billing_entitlements_one_storage_owner
            ON billing_entitlements;
        """
    )
    # Release retired or lapsed owners before deriving current store ownership.
    # Keep an existing valid store owner as the preferred deterministic choice
    # if old data contains multiple live store purchases. Never add their tiers.
    op.execute(
        """
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
        """
    )
    op.execute(
        """
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
        """
    )


def downgrade() -> None:
    # Deliberately data-preserving: never reactivate retired billing paths.
    pass
