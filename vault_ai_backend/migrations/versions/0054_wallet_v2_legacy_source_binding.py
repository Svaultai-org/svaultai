"""Bind staged wallet V2 envelopes to one exact legacy wallet row."""
from alembic import op

revision = "0054_wallet_v2_legacy_source_binding"
down_revision = "0053_file_v2_legacy_stage_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      ALTER TABLE wallet_v2_records
        ADD COLUMN IF NOT EXISTS legacy_item_id BIGINT,
        ADD COLUMN IF NOT EXISTS legacy_source_snapshot TEXT;
      CREATE UNIQUE INDEX IF NOT EXISTS wallet_v2_legacy_source_idx
        ON wallet_v2_records(vault_id, legacy_item_id)
        WHERE legacy_item_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
      DROP INDEX IF EXISTS wallet_v2_legacy_source_idx;
      ALTER TABLE wallet_v2_records
        DROP COLUMN IF EXISTS legacy_source_snapshot,
        DROP COLUMN IF EXISTS legacy_item_id;
    """)
