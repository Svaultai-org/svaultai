"""Add client-owned stable identity for opaque MEMORY_V2 envelopes."""
from alembic import op

revision = "0037_memory_v2_record_identity"
down_revision = "0036_zk_v2_migration_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The legacy lookup uniqueness constraint prevents v2 supersession: the
    # new envelope must be inserted before the prior active row is retired.
    # Preserve the lookup column and all unrelated constraints/indexes.
    op.execute("DROP INDEX IF EXISTS vault_ai_memory_lookup_uniq")
    op.execute("ALTER TABLE vault_ai_memory ADD COLUMN IF NOT EXISTS memory_record_id TEXT")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS vault_ai_memory_v2_record_uq ON vault_ai_memory(vault_id, memory_record_id) WHERE memory_record_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS vault_ai_memory_v2_record_uq")
    op.execute("ALTER TABLE vault_ai_memory DROP COLUMN IF EXISTS memory_record_id")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS vault_ai_memory_lookup_uniq
          ON vault_ai_memory (vault_id, memory_lookup_hash)
         WHERE superseded_at IS NULL AND memory_lookup_hash IS NOT NULL
        """
    )
