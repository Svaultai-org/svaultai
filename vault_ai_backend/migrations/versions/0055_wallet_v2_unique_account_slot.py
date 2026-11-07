"""Prevent a second active or pending wallet for the same account slot."""

from alembic import op

revision = "0055_wallet_v2_unique_account_slot"
down_revision = "0054_wallet_v2_legacy_source_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE UNIQUE INDEX IF NOT EXISTS wallet_v2_unique_account_slot_idx
      ON wallet_v2_records (vault_id, chain, network, UPPER(asset));
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS wallet_v2_unique_account_slot_idx")
