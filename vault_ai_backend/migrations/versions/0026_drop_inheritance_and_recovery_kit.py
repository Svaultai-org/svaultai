"""Drop the Recovery Kit + Inheritance-Pairing feature schema.

Removes every table and column that existed exclusively for the two
features:

  * Drops table ``beneficiary_links`` (and its three indexes).
  * Drops the four ``vaults`` columns that only had meaning while
    those features existed:
      - ``inherited_from_label``   (populated only by claim endpoint)
      - ``frozen_until``           (set only by claim endpoint)
      - ``must_reset``             (set only by claim endpoint)
      - ``wrapped_mvk_by_recovery`` (set only by /vault/ciphertext/recovery-kit)
      - ``opaque_recovery_record``  (set only by the Recovery Kit flow)

No data is preserved: the features are removed in full, and any
existing rows referenced only unreachable functionality.

The ``vault_deletion_service`` no longer walks ``beneficiary_links``
(see the same-turn source change), so its downgrade path does not
need to be preserved either.

If a downgrade is ever needed for a rollback drill, the columns can
be re-added as nullable and the table re-created from
``0001_baseline_vaultid.py`` / ``0024_vault_metadata_encryption.py``;
that reversibility is intentional but non-lossless (any legacy row
that was pending in production is gone).
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0026_drop_inheritance_and_recovery_kit"
down_revision: Union[str, None] = "0025_auth_session_hardening"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS beneficiary_links_passer_idx")
    op.execute("DROP INDEX IF EXISTS beneficiary_links_beneficiary_idx")
    op.execute("DROP INDEX IF EXISTS beneficiary_links_pairing_code_idx")
    op.execute("DROP TABLE IF EXISTS beneficiary_links CASCADE")

    op.execute(
        """
        ALTER TABLE vaults
          DROP COLUMN IF EXISTS inherited_from_label,
          DROP COLUMN IF EXISTS frozen_until,
          DROP COLUMN IF EXISTS must_reset,
          DROP COLUMN IF EXISTS wrapped_mvk_by_recovery,
          DROP COLUMN IF EXISTS opaque_recovery_record
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE vaults
          ADD COLUMN IF NOT EXISTS inherited_from_label   TEXT,
          ADD COLUMN IF NOT EXISTS frozen_until           TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS must_reset             BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS wrapped_mvk_by_recovery BYTEA,
          ADD COLUMN IF NOT EXISTS opaque_recovery_record  BYTEA
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS beneficiary_links (
          id                      SERIAL      PRIMARY KEY,
          passer_vault_id         UUID        NOT NULL,
          passer_label            TEXT,
          passer_label_ciphertext BYTEA,
          beneficiary_vault_id    UUID,
          beneficiary_email       TEXT,
          pairing_code_hash       TEXT,
          pairing_expires_at      TIMESTAMPTZ,
          wrapped_vault_key       TEXT,
          status                  TEXT        NOT NULL DEFAULT 'pairing_pending',
          transfer_requested_at   TIMESTAMPTZ,
          transfer_executes_at    TIMESTAMPTZ,
          created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS beneficiary_links_passer_idx "
        "ON beneficiary_links (passer_vault_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS beneficiary_links_beneficiary_idx "
        "ON beneficiary_links (beneficiary_vault_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS beneficiary_links_pairing_code_idx "
        "ON beneficiary_links (pairing_code_hash)"
    )
