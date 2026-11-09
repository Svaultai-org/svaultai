"""Track source-bound, default-off old-link V2 Memory copies.

This is additive. Owner Memory rows and old inheritance records stay intact.
The destination row outlives link removal; only its mapping is cascaded.
"""

from alembic import op


revision = "0074_linked_inheritance_memory_copies"
down_revision = "0073_memory_mixed_title_fence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE linked_inheritance_v2_memory_copies (
          old_link_id BIGINT NOT NULL
            REFERENCES beneficiary_links(id) ON DELETE CASCADE,
          source_memory_id BIGINT NOT NULL CHECK (source_memory_id > 0),
          beneficiary_vault_id UUID NOT NULL
            REFERENCES vaults(vault_id) ON DELETE CASCADE,
          beneficiary_memory_id BIGINT NOT NULL
            REFERENCES vault_ai_memory(id) ON DELETE CASCADE,
          stage_revision INTEGER NOT NULL CHECK (stage_revision > 0),
          source_inventory_sha256 VARCHAR(43) NOT NULL
            CHECK (source_inventory_sha256 ~ '^[A-Za-z0-9_-]{43}$'),
          source_row_sha256 BYTEA NOT NULL
            CHECK (OCTET_LENGTH(source_row_sha256) = 32),
          destination_ciphertext_sha256 BYTEA NOT NULL
            CHECK (OCTET_LENGTH(destination_ciphertext_sha256) = 32),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (old_link_id, source_memory_id),
          UNIQUE (beneficiary_memory_id)
        )
    """)
    op.execute("""
        CREATE INDEX linked_inheritance_v2_memory_copies_beneficiary_idx
          ON linked_inheritance_v2_memory_copies
             (beneficiary_vault_id, old_link_id)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM linked_inheritance_v2_memory_copies) THEN
            RAISE EXCEPTION 'linked_inheritance_memory_copies_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("DROP TABLE linked_inheritance_v2_memory_copies")
