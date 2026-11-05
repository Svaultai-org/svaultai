"""Mark unfinished V2 copies that stage an existing legacy inline file.

The marker lets a legacy client's explicit file deletion atomically remove
its still-unverified migration copy. Existing V2 rows remain unmarked because
their source cannot safely be inferred from encrypted manifests.

Revision ID: 0053
Revises: 0052
"""

from alembic import op


revision = "0053_file_v2_legacy_stage_marker"
down_revision = "0052_zk_saved_item_title_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE file_v2_records ADD COLUMN migrating_legacy "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE file_v2_records DROP COLUMN IF EXISTS migrating_legacy"
    )
