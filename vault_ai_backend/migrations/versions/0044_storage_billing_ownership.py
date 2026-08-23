"""Add one-owner storage billing and provider-migration foundation.

Ownership is derived from both the provider-neutral entitlement ledger and the
legacy Stripe ``account_subscriptions`` record.  Existing conflicts are
preserved and marked for reconciliation; no purchase is canceled, refunded,
deleted, resized, repriced, or renewed by this migration.

Legacy Stripe statuses that still grant storage are deliberately identical to
``billing._STATUSES_THAT_GRANT_STORAGE`` and
``stripe_service._ACTIVE_SUBSCRIPTION_STATUSES``: ``active``, ``in_grace``,
and ``canceled_pending``.  All other legacy states are non-granting and are not
backfilled as incumbent owners.
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
            legacy_subscription_account_id UUID
                REFERENCES account_subscriptions(account_id)
                ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
            legacy_source_subscription_id TEXT,
            legacy_provider TEXT
                CHECK (
                    legacy_provider IS NULL
                    OR legacy_provider = 'stripe_legacy'
                ),
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
            ),
            CHECK (
                current_entitlement_id IS NULL
                OR legacy_subscription_account_id IS NULL
            ),
            CHECK (
                (legacy_subscription_account_id IS NULL)
                = (legacy_provider IS NULL)
            ),
            CHECK (
                legacy_subscription_account_id IS NULL
                OR current_provider = 'web_card'
            )
        )
        """
    )
    op.execute(
        """
        WITH ownership_candidates AS (
            SELECT e.account_id, e.entitlement_family, e.entitlement_id,
                   NULL::UUID AS legacy_subscription_account_id,
                   NULL::TEXT AS legacy_source_subscription_id,
                   NULL::TEXT AS legacy_provider,
                   CASE
                     WHEN e.provider = 'stripe_legacy' THEN 'web_card'
                     ELSE e.provider
                   END AS public_provider,
                   e.created_at AS candidate_created_at,
                   1 AS candidate_source_rank,
                   e.external_purchase_id AS stable_identity
              FROM billing_entitlements e
             WHERE e.entitlement_family = 'storage'
               AND e.verification_state = 'verified'
               AND e.status IN ('active', 'reactivated', 'grace_period')
               AND (
                   e.current_period_end IS NULL
                   OR e.current_period_end > NOW()
               )

            UNION ALL

            SELECT s.account_id, 'storage'::TEXT, NULL::UUID,
                   s.account_id, s.source_subscription_id,
                   'stripe_legacy'::TEXT, 'web_card'::TEXT,
                   s.created_at, 0,
                   COALESCE(s.source_subscription_id, s.account_id::TEXT)
              FROM account_subscriptions s
             WHERE s.source = 'stripe'
               AND s.status IN ('active', 'in_grace', 'canceled_pending')
               AND s.purchased_bytes > 0
        ), ranked AS (
            SELECT c.*,
                   COUNT(*) OVER (
                       PARTITION BY c.account_id, c.entitlement_family
                   ) AS granting_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY c.account_id, c.entitlement_family
                       ORDER BY c.candidate_source_rank ASC,
                                c.candidate_created_at ASC,
                                c.public_provider ASC,
                                c.stable_identity ASC
                   ) AS owner_rank
              FROM ownership_candidates c
        )
        INSERT INTO billing_provider_ownership (
            account_id, entitlement_family, current_provider,
            current_entitlement_id, legacy_subscription_account_id,
            legacy_source_subscription_id, legacy_provider,
            migration_status, reason_code
        )
        SELECT account_id, entitlement_family, public_provider,
               entitlement_id, legacy_subscription_account_id,
               legacy_source_subscription_id, legacy_provider,
               CASE WHEN granting_count > 1 THEN 'conflict' ELSE 'none' END,
               CASE WHEN granting_count > 1
                    THEN 'multiple_active_storage_entitlements'
                    ELSE NULL END
          FROM ranked
         WHERE owner_rank = 1
        ON CONFLICT (account_id, entitlement_family) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_storage_billing_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            requested_provider TEXT;
            owner billing_provider_ownership%ROWTYPE;
            legacy_owner_active BOOLEAN := FALSE;
            ledger_owner_active BOOLEAN := FALSE;
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

            IF FOUND THEN
                legacy_owner_active :=
                    owner.legacy_subscription_account_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1
                          FROM account_subscriptions legacy_owner
                         WHERE legacy_owner.account_id =
                               owner.legacy_subscription_account_id
                           AND legacy_owner.account_id = NEW.account_id
                           AND legacy_owner.source = 'stripe'
                           AND legacy_owner.status IN (
                               'active', 'in_grace', 'canceled_pending'
                           )
                           AND legacy_owner.purchased_bytes > 0
                           AND legacy_owner.source_subscription_id
                               IS NOT DISTINCT FROM
                               owner.legacy_source_subscription_id
                    );
                ledger_owner_active := EXISTS (
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
                );

                -- A legacy incumbent blocks every new ledger grant, including
                -- another web-card row, until an explicit migration proves
                -- that the new row is the same subscription.
                IF legacy_owner_active
                   OR (
                       owner.current_provider <> 'free'
                       AND owner.current_provider <> requested_provider
                       AND (
                           owner.migration_status IN ('pending', 'conflict')
                           OR ledger_owner_active
                       )
                   )
                THEN
                    RAISE EXCEPTION
                        'explicit provider migration required; active storage billing owner is %',
                        owner.current_provider
                        USING ERRCODE = '23505',
                              CONSTRAINT =
                                  'one_active_storage_billing_owner';
                END IF;

                IF owner.current_provider <> 'free'
                   AND owner.current_provider <> requested_provider
                THEN
                    UPDATE billing_provider_ownership
                       SET current_provider = 'free',
                           current_entitlement_id = NULL,
                           legacy_subscription_account_id = NULL,
                           legacy_source_subscription_id = NULL,
                           legacy_provider = NULL,
                           target_provider = NULL,
                           target_entitlement_id = NULL,
                           migration_status = 'none', reason_code = NULL,
                           updated_at = NOW()
                     WHERE account_id = NEW.account_id
                       AND entitlement_family = NEW.entitlement_family;
                END IF;
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
                   legacy_subscription_account_id = NULL,
                   legacy_source_subscription_id = NULL,
                   legacy_provider = NULL,
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
        CREATE OR REPLACE FUNCTION enforce_legacy_storage_billing_owner()
        RETURNS TRIGGER AS $$
        DECLARE
            owner billing_provider_ownership%ROWTYPE;
            new_grants_storage BOOLEAN;
            same_legacy_subscription BOOLEAN;
        BEGIN
            new_grants_storage :=
                NEW.source = 'stripe'
                AND NEW.status IN ('active', 'in_grace', 'canceled_pending')
                AND NEW.purchased_bytes > 0;

            SELECT * INTO owner
              FROM billing_provider_ownership
             WHERE account_id = NEW.account_id
               AND entitlement_family = 'storage'
             FOR UPDATE;

            IF NOT new_grants_storage THEN
                IF TG_OP = 'UPDATE'
                   AND FOUND
                   AND owner.legacy_subscription_account_id = NEW.account_id
                   AND owner.legacy_source_subscription_id
                       IS NOT DISTINCT FROM OLD.source_subscription_id
                THEN
                    UPDATE billing_provider_ownership
                       SET current_provider = 'free',
                           current_entitlement_id = NULL,
                           legacy_subscription_account_id = NULL,
                           legacy_source_subscription_id = NULL,
                           legacy_provider = NULL,
                           target_provider = NULL,
                           target_entitlement_id = NULL,
                           migration_status = 'none', reason_code = NULL,
                           updated_at = NOW()
                     WHERE account_id = NEW.account_id
                       AND entitlement_family = 'storage';
                END IF;
                RETURN NEW;
            END IF;

            same_legacy_subscription :=
                FOUND
                AND owner.current_provider = 'web_card'
                AND owner.legacy_subscription_account_id = NEW.account_id
                AND owner.legacy_source_subscription_id
                    IS NOT DISTINCT FROM NEW.source_subscription_id;

            IF FOUND
               AND owner.current_provider <> 'free'
               AND NOT same_legacy_subscription
            THEN
                RAISE EXCEPTION
                    'explicit provider migration required; active storage billing owner is %',
                    owner.current_provider
                    USING ERRCODE = '23505',
                          CONSTRAINT = 'one_active_storage_billing_owner';
            END IF;

            INSERT INTO billing_provider_ownership (
                account_id, entitlement_family, current_provider,
                current_entitlement_id, legacy_subscription_account_id,
                legacy_source_subscription_id, legacy_provider,
                migration_status, reason_code, updated_at
            ) VALUES (
                NEW.account_id, 'storage', 'web_card', NULL,
                NEW.account_id, NEW.source_subscription_id, 'stripe_legacy',
                'none', NULL, NOW()
            )
            ON CONFLICT (account_id, entitlement_family) DO UPDATE
               SET current_provider = 'web_card',
                   current_entitlement_id = NULL,
                   legacy_subscription_account_id = NEW.account_id,
                   legacy_source_subscription_id = NEW.source_subscription_id,
                   legacy_provider = 'stripe_legacy',
                   migration_status = 'none', target_provider = NULL,
                   target_entitlement_id = NULL, reason_code = NULL,
                   updated_at = NOW()
             WHERE billing_provider_ownership.current_provider = 'free'
                OR (
                    billing_provider_ownership.current_provider = 'web_card'
                    AND billing_provider_ownership.legacy_subscription_account_id
                        = NEW.account_id
                    AND billing_provider_ownership.legacy_source_subscription_id
                        IS NOT DISTINCT FROM NEW.source_subscription_id
                );

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
    op.execute(
        """
        CREATE TRIGGER account_subscriptions_one_storage_owner
        BEFORE INSERT OR UPDATE OF account_id, source, source_subscription_id,
            status, purchased_bytes
        ON account_subscriptions
        FOR EACH ROW EXECUTE FUNCTION enforce_legacy_storage_billing_owner()
        """
    )


def downgrade() -> None:
    # Ownership and migration evidence is deliberately data-preserving.
    pass
