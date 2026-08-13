"""Make retained legacy content and the v2 envelope explicit in the journal."""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0037_zk_v2_reversible_state"
down_revision: Union[str, None] = "0036_zk_v2_migration_foundation"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vault_crypto_migration_journal
          ADD COLUMN IF NOT EXISTS envelope_id UUID
            REFERENCES vault_crypto_envelopes(id) ON DELETE RESTRICT,
          ADD COLUMN IF NOT EXISTS legacy_retained BOOLEAN NOT NULL DEFAULT TRUE
        """
    )
    op.execute(
        """
        ALTER TABLE vault_crypto_migration_journal
          ADD CONSTRAINT vault_crypto_journal_legacy_retained_ck
          CHECK (legacy_retained = TRUE)
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE vault_crypto_migration_journal
          DROP CONSTRAINT IF EXISTS vault_crypto_journal_legacy_retained_ck,
          DROP COLUMN IF EXISTS legacy_retained,
          DROP COLUMN IF EXISTS envelope_id
        """
    )
