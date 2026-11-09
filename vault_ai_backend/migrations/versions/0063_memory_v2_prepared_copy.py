"""Keep owner-verified V2 Memory copies beside active legacy records.

Preparation is additive. Older clients continue reading the original row;
this table is not an active Memory source until a separately gated cutover.
"""

from alembic import op


revision = "0063_memory_v2_prepared_copy"
down_revision = "0062_beneficiary_pending_upgrade_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE memory_v2_prepared_copies (
          legacy_memory_id BIGINT PRIMARY KEY
            REFERENCES vault_ai_memory(id) ON DELETE CASCADE,
          vault_id UUID NOT NULL REFERENCES vaults(vault_id) ON DELETE CASCADE,
          source_snapshot VARCHAR(43) NOT NULL
            CHECK (source_snapshot ~ '^[A-Za-z0-9_-]{43}$'),
          memory_record_id TEXT NOT NULL,
          memory_type TEXT NOT NULL,
          payload_ciphertext BYTEA NOT NULL
            CHECK (OCTET_LENGTH(payload_ciphertext) BETWEEN 29 AND 131072
                   AND GET_BYTE(payload_ciphertext,0) = 1),
          prepared_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          UNIQUE (vault_id, memory_record_id)
        )
    """)
    op.execute("""
        CREATE INDEX memory_v2_prepared_copies_vault_idx
          ON memory_v2_prepared_copies(vault_id, prepared_at DESC)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM memory_v2_prepared_copies) THEN
            RAISE EXCEPTION 'prepared_memory_copies_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("DROP TABLE memory_v2_prepared_copies")
