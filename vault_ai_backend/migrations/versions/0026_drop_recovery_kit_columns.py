"""Drop the Recovery Kit columns.

Removes the two ``vaults`` columns that existed exclusively for the
Recovery Kit feature (opt-in seed-based PIN recovery):

  * ``wrapped_mvk_by_recovery`` — set only by
    ``/vault/ciphertext/recovery-kit`` (now removed).
  * ``opaque_recovery_record`` — set only by the Recovery Kit
    registration path (now removed).

The Inheritance feature (``beneficiary_links`` table + the
``inherited_from_label`` / ``frozen_until`` / ``must_reset`` columns
on ``vaults``) is intentionally NOT touched here — that feature
remains in place.

A downgrade is provided in case a rollback drill is needed. The
columns come back nullable; any pre-migration content is gone.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0026_drop_recovery_kit_columns"
down_revision: Union[str, None] = "0025_auth_session_hardening"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vaults
          DROP COLUMN IF EXISTS wrapped_mvk_by_recovery,
          DROP COLUMN IF EXISTS opaque_recovery_record
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE vaults
          ADD COLUMN IF NOT EXISTS wrapped_mvk_by_recovery BYTEA,
          ADD COLUMN IF NOT EXISTS opaque_recovery_record  BYTEA
        """
    )
