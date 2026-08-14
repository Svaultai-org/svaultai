"""Add the provider-neutral billing entitlement ledger.

Stripe-era tables are deliberately preserved for accounting, audit, and
rollback. New Apple, Google Play, and web-card purchases are written to the
normalized ledger and never need card or vault-secret data.
"""

from alembic import op


revision = "0042_provider_neutral_billing"
down_revision = "0041_restore_memory_v2_lookup_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE billing_entitlements (
            entitlement_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id              UUID NOT NULL
                REFERENCES accounts(account_id) ON DELETE CASCADE,
            provider                TEXT NOT NULL
                CHECK (provider IN (
                    'apple', 'google_play', 'web_card', 'stripe_legacy'
                )),
            external_purchase_id    TEXT NOT NULL,
            original_transaction_id TEXT,
            product_id              TEXT NOT NULL,
            plan_id                 TEXT,
            quantity                INTEGER NOT NULL DEFAULT 1
                CHECK (quantity >= 1),
            entitlement_bytes       BIGINT NOT NULL
                CHECK (entitlement_bytes >= 0),
            status                  TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'active', 'reactivated', 'grace_period', 'delinquent',
                    'canceled', 'expired', 'revoked', 'refunded'
                )),
            provider_status         TEXT,
            verification_state      TEXT NOT NULL DEFAULT 'unverified'
                CHECK (verification_state IN (
                    'unverified', 'verified', 'rejected', 'error'
                )),
            environment             TEXT NOT NULL
                CHECK (environment IN ('sandbox', 'production')),
            auto_renewing           BOOLEAN NOT NULL DEFAULT FALSE,
            cancel_at_period_end    BOOLEAN NOT NULL DEFAULT FALSE,
            current_period_start    TIMESTAMPTZ,
            current_period_end      TIMESTAMPTZ,
            last_verified_at        TIMESTAMPTZ,
            last_provider_event_at  TIMESTAMPTZ,
            last_provider_event_id  TEXT,
            metadata_jsonb          JSONB NOT NULL DEFAULT '{}'::JSONB,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (provider, external_purchase_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX billing_entitlements_account_status_idx
          ON billing_entitlements(account_id, status, verification_state)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX billing_entitlements_original_txn_uniq
          ON billing_entitlements(provider, original_transaction_id)
          WHERE original_transaction_id IS NOT NULL
        """
    )

    # Keep all historic provider events while permitting the normalized names
    # used by the new adapters. The legacy names remain valid intentionally.
    op.execute(
        """
        ALTER TABLE provider_event_log
          DROP CONSTRAINT IF EXISTS provider_event_log_source_check
        """
    )
    op.execute(
        """
        ALTER TABLE provider_event_log
          ADD CONSTRAINT provider_event_log_source_check
          CHECK (source IN (
              'apple', 'google', 'google_play', 'stripe', 'stripe_legacy',
              'paypal', 'web_card'
          ))
        """
    )


def downgrade() -> None:
    # Billing provenance and verified entitlement identity must not be erased
    # by a code rollback. Older application code tolerates the additional
    # table and broader event-source constraint, so this is intentionally a
    # data-preserving no-op.
    pass
