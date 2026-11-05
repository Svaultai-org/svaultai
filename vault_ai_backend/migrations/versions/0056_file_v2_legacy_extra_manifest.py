"""Version the opaque file manifest for owner-migrated legacy extra fields.

Existing V2 sidecars remain version 1. Only a new client that rewraps the
legacy extracted text and relative path into the MVK manifest sets version 2.

Revision ID: 0056
Revises: 0055
"""

from alembic import op


revision = "0056_file_v2_legacy_extra_manifest"
down_revision = "0055_wallet_v2_unique_account_slot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE file_v2_records ADD COLUMN migration_metadata_version "
        "SMALLINT NOT NULL DEFAULT 1 "
        "CHECK (migration_metadata_version IN (1, 2))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE file_v2_records DROP COLUMN IF EXISTS "
        "migration_metadata_version"
    )
