"""Restore the Inheritance-Pairing schema; leave Recovery Kit removed.

Context
=======

Migration ``0026_drop_inheritance_and_recovery_kit`` was applied to
production and removed two separate feature footprints together:

  1. Recovery Kit — the ``vaults.wrapped_mvk_by_recovery`` and
     ``vaults.opaque_recovery_record`` columns.
  2. Inheritance-Pairing — the ``beneficiary_links`` table (with
     its three indexes) and the ``vaults.inherited_from_label``,
     ``vaults.frozen_until``, ``vaults.must_reset`` columns.

The Recovery Kit removal is intended and stays. The Inheritance-
Pairing removal was NOT intended — this migration recreates every
inheritance table, column, index, and foreign key that the old 0026
dropped, in the exact shape they had immediately before it ran
(``0001_baseline_vaultid`` baseline as amended by
``0024_vault_metadata_encryption``).

Data loss
---------

The old 0026 executed ``DROP TABLE IF EXISTS beneficiary_links
CASCADE`` and ``ALTER TABLE vaults DROP COLUMN ...``, both of which
are destructive. Any row previously stored in ``beneficiary_links``
is gone (pairings, pending transfers, wrapped keys, cooldown
timestamps). Any per-vault value previously stored in
``inherited_from_label`` / ``frozen_until`` / ``must_reset`` is also
gone. This migration recreates the SCHEMA only; it does not — and
cannot — recover the data. Existing vaults come back with
``must_reset = FALSE`` (the baseline default) and NULL for the two
nullable columns. Existing beneficiary pairings, if any, must be
re-established through the app.

What this migration recreates
-----------------------------

* ``beneficiary_links`` table, columns identical to the state after
  ``0024_vault_metadata_encryption`` — that means:
    - ``passer_label`` is nullable (0024 relaxed the NOT NULL).
    - ``passer_label_ciphertext BYTEA`` is present (0024 added it).
* Foreign keys back onto ``vaults(vault_id)``:
    - ``passer_vault_id      ON DELETE CASCADE``
    - ``beneficiary_vault_id ON DELETE SET NULL``
* Indexes ``beneficiary_links_passer_idx``,
  ``beneficiary_links_beneficiary_idx``,
  ``beneficiary_links_pairing_code_idx`` (partial indexes on the
  nullable FK / hash columns, matching the original).
* ``vaults.must_reset          BOOLEAN NOT NULL DEFAULT FALSE``
* ``vaults.frozen_until        TIMESTAMPTZ``
* ``vaults.inherited_from_label TEXT``

What this migration does NOT recreate
-------------------------------------

* ``vaults.wrapped_mvk_by_recovery`` — Recovery Kit, stays dropped.
* ``vaults.opaque_recovery_record``  — Recovery Kit, stays dropped.

Idempotence
-----------

Every statement uses ``IF NOT EXISTS`` guards so a partial prior
run is safe to replay. Rerunning against a fully-applied database
is a no-op.

Rollback
--------

``downgrade()`` re-drops the schema this migration adds. It is a
straight structural undo — no attempt is made to preserve rows that
existed in the re-created ``beneficiary_links`` between apply and
rollback.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0027_restore_inheritance_keep_recovery_removed"
down_revision: Union[str, None] = "0026_drop_inheritance_and_recovery_kit"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    # ---- vaults columns ---------------------------------------------
    op.execute(
        """
        ALTER TABLE vaults
          ADD COLUMN IF NOT EXISTS must_reset            BOOLEAN     NOT NULL DEFAULT FALSE,
          ADD COLUMN IF NOT EXISTS frozen_until          TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS inherited_from_label  TEXT
        """
    )

    # ---- beneficiary_links table ------------------------------------
    # Shape matches the post-0024 schema: passer_label is NULL-able,
    # passer_label_ciphertext BYTEA is present, both foreign keys
    # back onto vaults(vault_id).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS beneficiary_links (
            id                      SERIAL      PRIMARY KEY,
            passer_vault_id         UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            passer_label            TEXT,
            passer_label_ciphertext BYTEA,
            beneficiary_vault_id    UUID
                REFERENCES vaults(vault_id) ON DELETE SET NULL,
            pairing_code_hash       TEXT,
            pairing_expires_at      TIMESTAMPTZ,
            wrapped_vault_key       TEXT        NOT NULL,
            status                  TEXT        NOT NULL DEFAULT 'pairing_pending',
            transfer_requested_at   TIMESTAMPTZ,
            transfer_executes_at    TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS beneficiary_links_passer_idx
          ON beneficiary_links(passer_vault_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS beneficiary_links_beneficiary_idx
          ON beneficiary_links(beneficiary_vault_id)
          WHERE beneficiary_vault_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS beneficiary_links_pairing_code_idx
          ON beneficiary_links(pairing_code_hash)
          WHERE pairing_code_hash IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS beneficiary_links_pairing_code_idx")
    op.execute("DROP INDEX IF EXISTS beneficiary_links_beneficiary_idx")
    op.execute("DROP INDEX IF EXISTS beneficiary_links_passer_idx")
    op.execute("DROP TABLE IF EXISTS beneficiary_links CASCADE")
    op.execute(
        """
        ALTER TABLE vaults
          DROP COLUMN IF EXISTS inherited_from_label,
          DROP COLUMN IF EXISTS frozen_until,
          DROP COLUMN IF EXISTS must_reset
        """
    )
