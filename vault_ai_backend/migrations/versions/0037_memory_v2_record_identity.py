"""Add client-owned stable identity for opaque MEMORY_V2 envelopes."""
from alembic import op

revision = "0037_memory_v2_record_identity"
down_revision = "0036_zk_v2_migration_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the legacy uniqueness guarantee intact while all MemoryV2 feature
    # flags are off. A future, separately reviewed rollout that needs parallel
    # active legacy and V2 rows must use an ordering/state transition that does
    # not weaken legacy integrity during this additive schema deployment.
    op.execute("ALTER TABLE vault_ai_memory ADD COLUMN IF NOT EXISTS memory_record_id TEXT")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS vault_ai_memory_v2_record_uq ON vault_ai_memory(vault_id, memory_record_id) WHERE memory_record_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS vault_ai_memory_v2_record_uq")
    op.execute("ALTER TABLE vault_ai_memory DROP COLUMN IF EXISTS memory_record_id")
