"""Restore the active MemoryV2 blind-index uniqueness invariant.

Revision 0024 introduced this index, and the ciphertext upsert endpoint relies
on it as the conflict arbiter.  Some databases were stamped after an earlier
0024 revision that added the columns but not the index, so an idempotent repair
is required at the current head.
"""

from alembic import op

revision = "0041_restore_memory_v2_lookup_index"
down_revision = "0040_wallet_v2_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS vault_ai_memory_lookup_uniq
          ON vault_ai_memory (vault_id, memory_lookup_hash)
          WHERE superseded_at IS NULL AND memory_lookup_hash IS NOT NULL
        """
    )


def downgrade() -> None:
    # This migration repairs an invariant first introduced by 0024. Rolling
    # back 0041 must not remove an index that a healthy 0024 database already
    # had, so the corrective migration intentionally has a no-op downgrade.
    pass
