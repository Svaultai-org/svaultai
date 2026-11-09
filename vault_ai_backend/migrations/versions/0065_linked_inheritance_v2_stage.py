"""Stage a private MVK envelope beside an unchanged linked legacy link.

The staged package is owner-readable only. No legacy credential, release
state, pairing, or claim path is changed by this additive migration.
"""

from alembic import op


revision = "0065_linked_inheritance_v2_stage"
down_revision = "0064_invalidate_changed_memory_copies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE beneficiary_link_v2_upgrades (
          old_link_id BIGINT PRIMARY KEY
            REFERENCES beneficiary_links(id) ON DELETE CASCADE,
          owner_vault_id UUID NOT NULL
            REFERENCES vaults(vault_id) ON DELETE CASCADE,
          beneficiary_vault_id UUID NOT NULL
            REFERENCES vaults(vault_id) ON DELETE CASCADE,
          old_source_snapshot VARCHAR(43) NOT NULL
            CHECK (old_source_snapshot ~ '^[A-Za-z0-9_-]{43}$'),
          beneficiary_pk_sha256 BYTEA NOT NULL
            CHECK (OCTET_LENGTH(beneficiary_pk_sha256) = 32),
          encrypted_payload BYTEA NOT NULL
            CHECK (OCTET_LENGTH(encrypted_payload) BETWEEN 32 AND 65536),
          payload_nonce BYTEA NOT NULL
            CHECK (OCTET_LENGTH(payload_nonce) = 12),
          wrapped_key BYTEA NOT NULL
            CHECK (OCTET_LENGTH(wrapped_key) BETWEEN 32 AND 4096),
          wrapping_ephemeral_pk BYTEA NOT NULL
            CHECK (OCTET_LENGTH(wrapping_ephemeral_pk) = 32),
          wrapping_nonce BYTEA NOT NULL
            CHECK (OCTET_LENGTH(wrapping_nonce) = 12),
          stage_revision INTEGER NOT NULL DEFAULT 1
            CHECK (stage_revision > 0),
          state TEXT NOT NULL DEFAULT 'staged'
            CHECK (state = 'staged'),
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX beneficiary_link_v2_upgrades_owner_idx
          ON beneficiary_link_v2_upgrades(owner_vault_id, old_link_id)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM beneficiary_link_v2_upgrades) THEN
            RAISE EXCEPTION 'staged_linked_inheritance_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("DROP TABLE beneficiary_link_v2_upgrades")
