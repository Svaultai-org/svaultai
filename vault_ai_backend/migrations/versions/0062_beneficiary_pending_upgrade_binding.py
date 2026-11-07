"""Bind an old unpaired invitation to its staged private replacement.

The old row is preserved until client readback and OPAQUE retirement. Deleting
either row clears the temporary binding without deleting the other row.
"""

from alembic import op


revision = "0062_beneficiary_pending_upgrade_binding"
down_revision = "0061_file_v3_legacy_extra_manifest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE beneficiary_pending_upgrades (
          old_link_id INTEGER PRIMARY KEY
            REFERENCES beneficiary_links(id) ON DELETE CASCADE,
          new_link_id INTEGER NOT NULL UNIQUE
            REFERENCES beneficiary_links(id) ON DELETE CASCADE,
          owner_vault_id UUID NOT NULL
            REFERENCES vaults(vault_id) ON DELETE CASCADE,
          old_source_snapshot TEXT NOT NULL
            CHECK (length(old_source_snapshot) = 43),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX beneficiary_pending_upgrades_owner_idx
          ON beneficiary_pending_upgrades(owner_vault_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM beneficiary_pending_upgrades) THEN
            RAISE EXCEPTION 'pending_beneficiary_upgrade_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("DROP TABLE beneficiary_pending_upgrades")
