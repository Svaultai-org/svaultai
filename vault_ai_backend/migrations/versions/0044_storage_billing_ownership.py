"""Add one-owner storage billing and provider-migration foundation.

Existing conflicting rows are preserved.  The oldest granting row is recorded
as the incumbent owner and the account is marked conflict for reconciliation;
no provider purchase is canceled, refunded, or deleted by this migration.
"""

from alembic import op


revision = "0044_storage_billing_ownership"
down_revision = "0043_google_play_storage_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE billing_provider_ownership (
            account_id UUID NOT NULL
                REFERENCES accounts(account_id) ON DELETE CASCADE,
            entitlement_family TEXT NOT NULL DEFAULT 'storage',
            current_provider TEXT NOT NULL DEFAULT 'free'
                CHECK (current_provider IN (
                    'free', 'google_play', 'apple', 'web_card'
                )),
            current_entitlement_id UUID
                REFERENCES billing_entitlements(entitlement_id)
                ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
            target_provider TEXT
                CHECK (target_provider IS NULL OR target_provider IN (
                    'google_play', 'apple', 'web_card'
                )),
            target_entitlement_id UUID
                REFERENCES billing_entitlements(entitlement_id)
                ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED,
            migration_status TEXT NOT NULL DEFAULT 'none'
                CHECK (migration_status IN (
                    'none', 'pending', 'conflict', 'completed', 'canceled'
                )),
            reason_code TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (account_id, entitlement_family),
            CHECK (
                migration_status <> 'pending'
                OR (
                    target_provider IS NOT NULL
                    AND target_provider <> current_provider
                )
            )
        )
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT e.account_id, e.entitlement_family, e.entitlement_id,
                   CASE
                     WHEN e.provider = 'stripe_legacy' THEN 'web_card'
                     ELSE e.provider
                   END AS public_provider,
                   COUNT(*) OVER (
                       PARTITION BY e.account_id, e.entitlement_family
                   ) AS granting_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY e.account_id, e.entitlement_family
                       ORDER BY e.created_at ASC, e.provider ASC,
                                e.external_purchase_id ASC
                   ) AS owner_rank
              FROM billing_entitlements e
             WHERE e.entitlement_family = 'storage'
               AND e.verification_state = 'verified'
               AND e.status IN ('active', 'reactivated', 'grace_period')
               AND (
                   e.current_period_end IS NULL
                   OR e.current_period_end > NOW()
               )
        )
        INSERT INTO billing_provider_ownership (
            account_id, entitlement_family, current_provider,
            current_entitlement_id, migration_status, reason_code
        )
        SELECT account_id, entitlement_family, public_provider,
               entitlement_id,
               CASE WHEN granting_count > 1 THEN 'conflict' ELSE 'none' END,
               CASE WHEN granting_count > 1
                    THEN 'multiple_active_storage_entitlements'
                    ELSE NULL END
          FROM ranked
         WHERE owner_rank = 1
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_storage_billing_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            requested_provider TEXT;
            owner billing_provider_ownership%ROWTYPE;
        BEGIN
            IF NEW.entitlement_family <> 'storage'
               OR NEW.verification_state <> 'verified'
               OR NEW.status NOT IN ('active', 'reactivated', 'grace_period')
            THEN
                RETURN NEW;
            END IF;

            IF TG_OP = 'UPDATE'
               AND OLD.entitlement_family = NEW.entitlement_family
               AND OLD.account_id = NEW.account_id
               AND OLD.provider = NEW.provider
               AND OLD.verification_state = 'verified'
               AND OLD.status IN ('active', 'reactivated', 'grace_period')
            THEN
                RETURN NEW;
            END IF;

            requested_provider := CASE
                WHEN NEW.provider = 'stripe_legacy' THEN 'web_card'
                ELSE NEW.provider
            END;

            SELECT * INTO owner
              FROM billing_provider_ownership
             WHERE account_id = NEW.account_id
               AND entitlement_family = NEW.entitlement_family
             FOR UPDATE;

            IF FOUND
               AND owner.current_provider <> 'free'
               AND owner.current_provider <> requested_provider
            THEN
                IF owner.migration_status = 'pending'
                   OR EXISTS (
                       SELECT 1
                         FROM billing_entitlements current_owner
                        WHERE current_owner.entitlement_id =
                              owner.current_entitlement_id
                          AND current_owner.verification_state = 'verified'
                          AND current_owner.status IN (
                              'active', 'reactivated', 'grace_period'
                          )
                          AND (
                              current_owner.current_period_end IS NULL
                              OR current_owner.current_period_end > NOW()
                          )
                   )
                THEN
                    RAISE EXCEPTION
                        'active storage billing owner is %',
                        owner.current_provider
                        USING ERRCODE = '23505',
                              CONSTRAINT =
                                  'one_active_storage_billing_owner';
                END IF;

                UPDATE billing_provider_ownership
                   SET current_provider = 'free',
                       current_entitlement_id = NULL,
                       target_provider = NULL,
                       target_entitlement_id = NULL,
                       migration_status = 'none', reason_code = NULL,
                       updated_at = NOW()
                 WHERE account_id = NEW.account_id
                   AND entitlement_family = NEW.entitlement_family;
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM billing_entitlements e
                 WHERE e.account_id = NEW.account_id
                   AND e.entitlement_family = NEW.entitlement_family
                   AND e.entitlement_id <> NEW.entitlement_id
                   AND e.verification_state = 'verified'
                   AND e.status IN ('active', 'reactivated', 'grace_period')
                   AND (
                       e.current_period_end IS NULL
                       OR e.current_period_end > NOW()
                   )
            ) THEN
                RAISE EXCEPTION 'second active storage entitlement rejected'
                    USING ERRCODE = '23505',
                          CONSTRAINT = 'one_active_storage_billing_owner';
            END IF;

            INSERT INTO billing_provider_ownership (
                account_id, entitlement_family, current_provider,
                current_entitlement_id, migration_status, reason_code,
                updated_at
            ) VALUES (
                NEW.account_id, NEW.entitlement_family, requested_provider,
                NEW.entitlement_id, 'none', NULL, NOW()
            )
            ON CONFLICT (account_id, entitlement_family) DO UPDATE
               SET current_provider = EXCLUDED.current_provider,
                   current_entitlement_id = EXCLUDED.current_entitlement_id,
                   migration_status = 'none', target_provider = NULL,
                   target_entitlement_id = NULL, reason_code = NULL,
                   updated_at = NOW()
             WHERE billing_provider_ownership.current_provider = 'free'
                OR billing_provider_ownership.current_provider =
                   EXCLUDED.current_provider;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER billing_entitlements_one_storage_owner
        BEFORE INSERT OR UPDATE OF account_id, provider, entitlement_family,
            verification_state, status
        ON billing_entitlements
        FOR EACH ROW EXECUTE FUNCTION enforce_storage_billing_owner()
        """
    )


def downgrade() -> None:
    # Ownership and migration evidence is deliberately data-preserving.
    pass
