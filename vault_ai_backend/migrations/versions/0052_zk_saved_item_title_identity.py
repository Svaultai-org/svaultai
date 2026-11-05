"""Add a keyed, vault-scoped title identity and edit revision for V2 items.

Existing V2 rows remain unindexed until an unlocked MVK client claims their
identities. The server cannot derive a title hash from encrypted labels.

Revision ID: 0052
Revises: 0051
"""

from alembic import op


revision = "0052_zk_saved_item_title_identity"
down_revision = "0051_file_v2_encrypted_rename"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vault_items ADD COLUMN title_lookup_hash BYTEA"
    )
    op.execute(
        "ALTER TABLE vault_items ADD COLUMN title_revision BIGINT "
        "NOT NULL DEFAULT 0 CHECK (title_revision >= 0)"
    )
    op.execute(
        "ALTER TABLE vault_items ADD CONSTRAINT "
        "vault_items_title_lookup_hash_len_chk CHECK ("
        "title_lookup_hash IS NULL OR octet_length(title_lookup_hash) = 32)"
    )
    op.execute(
        "CREATE UNIQUE INDEX vault_items_title_lookup_uniq "
        "ON vault_items(vault_id, title_lookup_hash) "
        "WHERE title_lookup_hash IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS vault_items_title_lookup_uniq")
    op.execute(
        "ALTER TABLE vault_items DROP CONSTRAINT IF EXISTS "
        "vault_items_title_lookup_hash_len_chk"
    )
    op.execute(
        "ALTER TABLE vault_items DROP COLUMN IF EXISTS title_revision"
    )
    op.execute(
        "ALTER TABLE vault_items DROP COLUMN IF EXISTS title_lookup_hash"
    )
