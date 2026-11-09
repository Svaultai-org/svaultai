"""Track bounded old-link V2 saved-item copies without touching owner rows.

Each source item maps to at most one beneficiary item for one exact source
inventory and readback stage. The encrypted destination survives link removal;
only its copy mapping is cascaded. No old inheritance path is retired here.
"""

from alembic import op


revision = "0069_linked_inheritance_item_copies"
down_revision = "0068_memory_inventory_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE linked_inheritance_v2_item_copies (
          old_link_id BIGINT NOT NULL
            REFERENCES beneficiary_links(id) ON DELETE CASCADE,
          source_item_id INTEGER NOT NULL CHECK (source_item_id > 0),
          beneficiary_vault_id UUID NOT NULL
            REFERENCES vaults(vault_id) ON DELETE CASCADE,
          beneficiary_item_id INTEGER NOT NULL
            REFERENCES vault_items(id) ON DELETE CASCADE,
          stage_revision INTEGER NOT NULL CHECK (stage_revision > 0),
          source_inventory_sha256 VARCHAR(43) NOT NULL
            CHECK (source_inventory_sha256 ~ '^[A-Za-z0-9_-]{43}$'),
          source_row_sha256 BYTEA NOT NULL
            CHECK (OCTET_LENGTH(source_row_sha256) = 32),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          PRIMARY KEY (old_link_id, source_item_id),
          UNIQUE (beneficiary_item_id)
        )
    """)
    op.execute("""
        CREATE INDEX linked_inheritance_v2_item_copies_beneficiary_idx
          ON linked_inheritance_v2_item_copies
             (beneficiary_vault_id, old_link_id)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM linked_inheritance_v2_item_copies) THEN
            RAISE EXCEPTION 'linked_inheritance_item_copies_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("DROP TABLE linked_inheritance_v2_item_copies")
