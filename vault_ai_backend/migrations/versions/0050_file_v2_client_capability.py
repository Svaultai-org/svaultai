"""Bind client-only V2 file reader support to an authenticated session.

Revision ID: 0050
Revises: 0049
"""

from alembic import op


revision = "0050_file_v2_client_capability"
down_revision = "0049_kag_encrypted_draft_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auth_sessions ADD COLUMN file_v2_reader_capable "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX file_v2_ready_vault_idx ON file_v2_records (vault_id) "
        "WHERE lifecycle_state='client_v2_ready' "
        "AND verification_state='client_verified'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS file_v2_ready_vault_idx")
    op.execute(
        "ALTER TABLE auth_sessions DROP COLUMN IF EXISTS "
        "file_v2_reader_capable"
    )
