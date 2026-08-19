"""Enforce one authoritative Google Play storage tier per account.

This migration is data-preserving. Existing entitlement history stays in the
ledger. Deployment fails closed if pre-existing duplicate granting Google Play
rows need operator reconciliation; it never guesses which paid tier to erase.
"""

from alembic import op


revision = "0043_google_play_storage_tiers"
down_revision = "0042_provider_neutral_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE billing_entitlements
          ADD COLUMN entitlement_family TEXT NOT NULL DEFAULT 'storage',
          ADD COLUMN superseded_by_purchase_id TEXT,
          ADD COLUMN scheduled_product_id TEXT,
          ADD COLUMN scheduled_plan_id TEXT,
          ADD COLUMN scheduled_entitlement_bytes BIGINT,
          ADD COLUMN scheduled_effective_at TIMESTAMPTZ,
          ADD CONSTRAINT billing_entitlements_family_nonempty_check
              CHECK (length(btrim(entitlement_family)) > 0),
          ADD CONSTRAINT billing_entitlements_scheduled_storage_check
              CHECK (
                  (
                      scheduled_product_id IS NULL
                      AND scheduled_plan_id IS NULL
                      AND scheduled_entitlement_bytes IS NULL
                      AND scheduled_effective_at IS NULL
                  )
                  OR
                  (
                      provider = 'google_play'
                      AND entitlement_family = 'storage'
                      AND scheduled_product_id IS NOT NULL
                      AND scheduled_plan_id IS NOT NULL
                      AND scheduled_entitlement_bytes IS NOT NULL
                      AND scheduled_entitlement_bytes >= 0
                      AND scheduled_effective_at IS NOT NULL
                  )
              )
        """
    )
    op.execute(
        """
        CREATE INDEX billing_entitlements_superseded_purchase_idx
          ON billing_entitlements(provider, superseded_by_purchase_id)
          WHERE superseded_by_purchase_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX billing_entitlements_scheduled_replacement_idx
          ON billing_entitlements(scheduled_effective_at)
          WHERE scheduled_effective_at IS NOT NULL
        """
    )
    # The index is both a durable invariant and a concurrency backstop. If a
    # legacy deployment somehow produced duplicate grants, CREATE UNIQUE INDEX
    # aborts this migration without modifying or deleting either purchase.
    op.execute(
        """
        CREATE UNIQUE INDEX billing_entitlements_one_google_storage_grant_uniq
          ON billing_entitlements(account_id, provider, entitlement_family)
          WHERE provider = 'google_play'
            AND entitlement_family = 'storage'
            AND verification_state = 'verified'
            AND status IN ('active', 'reactivated', 'grace_period')
        """
    )


def downgrade() -> None:
    # Purchase lineage and scheduled replacement evidence must survive a code
    # rollback. Older code tolerates additional columns/indexes, so rollback is
    # intentionally a data-preserving no-op.
    pass
