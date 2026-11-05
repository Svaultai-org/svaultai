"""Store an MVK-encrypted saved-name override for ready V2 files.

Revision ID: 0051
Revises: 0050
"""

from alembic import op


revision = "0051_file_v2_encrypted_rename"
down_revision = "0050_file_v2_client_capability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE file_v2_records ADD COLUMN "
        "saved_name_override_ciphertext BYTEA"
    )
    op.execute(
        "ALTER TABLE file_v2_records ADD COLUMN "
        "name_version BIGINT NOT NULL DEFAULT 0 "
        "CHECK (name_version >= 0)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE file_v2_records DROP COLUMN IF EXISTS name_version"
    )
    op.execute(
        "ALTER TABLE file_v2_records DROP COLUMN IF EXISTS "
        "saved_name_override_ciphertext"
    )
