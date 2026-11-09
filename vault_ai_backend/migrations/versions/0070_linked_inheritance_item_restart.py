"""Track original imported ciphertext and short-lived restart preparations.

An older 0069 copy without an original destination digest cannot be reset
automatically. It remains preserved for manual review. Owner rows and old
inheritance packages are never modified by this schema change.
"""

from alembic import op


revision = "0070_linked_inheritance_item_restart"
down_revision = "0069_linked_inheritance_item_copies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE linked_inheritance_v2_item_copies
          ADD COLUMN destination_ciphertext_sha256 BYTEA,
          ADD CONSTRAINT linked_item_destination_digest_len CHECK (
            destination_ciphertext_sha256 IS NULL OR
            OCTET_LENGTH(destination_ciphertext_sha256) = 32
          )
    """)
    op.execute("""
        CREATE TABLE linked_inheritance_v2_item_restart_previews (
          token_hash BYTEA PRIMARY KEY
            CHECK (OCTET_LENGTH(token_hash) = 32),
          old_link_id BIGINT NOT NULL
            REFERENCES beneficiary_links(id) ON DELETE CASCADE,
          beneficiary_vault_id UUID NOT NULL
            REFERENCES vaults(vault_id) ON DELETE CASCADE,
          stage_revision INTEGER NOT NULL CHECK (stage_revision > 0),
          offer_commitment VARCHAR(43) NOT NULL
            CHECK (offer_commitment ~ '^[A-Za-z0-9_-]{43}$'),
          old_source_inventory_sha256 VARCHAR(43) NOT NULL
            CHECK (old_source_inventory_sha256 ~ '^[A-Za-z0-9_-]{43}$'),
          current_source_inventory_sha256 VARCHAR(43) NOT NULL
            CHECK (current_source_inventory_sha256 ~ '^[A-Za-z0-9_-]{43}$'),
          copies_sha256 BYTEA NOT NULL
            CHECK (OCTET_LENGTH(copies_sha256) = 32),
          copy_count INTEGER NOT NULL CHECK (copy_count > 0 AND copy_count <= 100),
          expires_at TIMESTAMPTZ NOT NULL,
          consumed_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX linked_item_restart_previews_link_idx
          ON linked_inheritance_v2_item_restart_previews
             (old_link_id, expires_at DESC)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM linked_inheritance_v2_item_restart_previews
          ) OR EXISTS (
            SELECT 1 FROM linked_inheritance_v2_item_copies
             WHERE destination_ciphertext_sha256 IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'linked_item_restart_state_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("DROP TABLE linked_inheritance_v2_item_restart_previews")
    op.execute("""
        ALTER TABLE linked_inheritance_v2_item_copies
          DROP CONSTRAINT linked_item_destination_digest_len,
          DROP COLUMN destination_ciphertext_sha256
    """)
