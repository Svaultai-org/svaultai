"""Carry an encrypted title through proof-bound legacy item replacement.

The old plaintext service remains for older clients. The new title is stored
only as MVK ciphertext and a keyed lookup hash. Candidates remain inert until
the owner's exact readback and one-use proof promote them.
"""

from alembic import op


revision = "0059_keyless_legacy_item_rename"
down_revision = "0058_keyless_legacy_item_edit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE vault_items
        ADD COLUMN legacy_item_rename_active BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE vault_items
        ADD CONSTRAINT legacy_item_rename_active_shape_ck CHECK (
            NOT legacy_item_rename_active OR (
                encrypted_data IS NOT NULL AND
                service_ciphertext IS NOT NULL AND
                title_lookup_hash IS NOT NULL AND
                item_type_ciphertext IS NULL AND
                payload_ciphertext IS NULL
            )
        )
    """)
    op.execute("""
        ALTER TABLE legacy_item_edit_candidates
        ADD COLUMN new_service_ciphertext BYTEA,
        ADD COLUMN new_title_lookup_hash BYTEA
    """)
    op.execute("""
        ALTER TABLE legacy_item_edit_candidates
        ADD CONSTRAINT legacy_item_edit_rename_shape_ck CHECK (
            (new_service_ciphertext IS NULL AND new_title_lookup_hash IS NULL)
            OR (new_service_ciphertext IS NOT NULL AND
                octet_length(new_service_ciphertext) BETWEEN 30 AND 4096 AND
                new_title_lookup_hash IS NOT NULL AND
                octet_length(new_title_lookup_hash) = 32)
        )
    """)
    op.execute("""
        ALTER TABLE legacy_item_edit_history
        ADD COLUMN encrypted_rename BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM legacy_item_edit_candidates
                WHERE new_service_ciphertext IS NOT NULL OR
                      new_title_lookup_hash IS NOT NULL
            ) OR EXISTS (
                SELECT 1 FROM legacy_item_edit_history
                WHERE encrypted_rename
            ) OR EXISTS (
                SELECT 1 FROM vault_items
                WHERE legacy_item_rename_active
            ) THEN
                RAISE EXCEPTION 'keyless_item_rename_data_exists'
                    USING ERRCODE='23514';
            END IF;
        END $$
    """)
    op.execute("ALTER TABLE legacy_item_edit_history DROP COLUMN encrypted_rename")
    op.execute("""
        ALTER TABLE vault_items
        DROP CONSTRAINT legacy_item_rename_active_shape_ck,
        DROP COLUMN legacy_item_rename_active
    """)
    op.execute("""
        ALTER TABLE legacy_item_edit_candidates
        DROP CONSTRAINT legacy_item_edit_rename_shape_ck,
        DROP COLUMN new_service_ciphertext,
        DROP COLUMN new_title_lookup_hash
    """)
