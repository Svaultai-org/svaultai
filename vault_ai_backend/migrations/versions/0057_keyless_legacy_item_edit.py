"""Stage PIN-free legacy item edits without changing the active ciphertext.

Candidates are inert until a proof-bound promotion. Each promotion retains the
previous encrypted source so a bad client release can be recovered without
knowing the owner's PIN. The existing vault_items shape and old-client routes
remain available.
"""

from alembic import op


revision = "0057_keyless_legacy_item_edit"
down_revision = "0056_file_v2_legacy_extra_manifest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE legacy_item_edit_candidates (
            item_id INTEGER PRIMARY KEY REFERENCES vault_items(id) ON DELETE CASCADE,
            vault_id UUID NOT NULL REFERENCES vaults(vault_id) ON DELETE CASCADE,
            candidate_id UUID NOT NULL,
            source_snapshot VARCHAR(43) NOT NULL,
            encrypted_data TEXT NOT NULL,
            base_item_digest BYTEA NOT NULL,
            candidate_sha256 BYTEA NOT NULL,
            staged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT legacy_item_edit_candidate_shape_ck CHECK (
                source_snapshot ~ '^[A-Za-z0-9_-]{43}$' AND
                length(encrypted_data) BETWEEN 40 AND 174764 AND
                length(base_item_digest) = 32 AND
                length(candidate_sha256) = 32
            )
        )
    """)
    op.execute(
        "CREATE INDEX legacy_item_edit_candidates_vault_idx "
        "ON legacy_item_edit_candidates(vault_id)"
    )
    op.execute("""
        CREATE FUNCTION bind_legacy_item_edit_candidate_owner()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM vault_items
                 WHERE id = NEW.item_id AND vault_id = NEW.vault_id
            ) THEN
                RAISE EXCEPTION 'legacy_item_edit_candidate_owner_mismatch'
                    USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER legacy_item_edit_candidate_owner_guard "
        "BEFORE INSERT OR UPDATE ON legacy_item_edit_candidates "
        "FOR EACH ROW EXECUTE FUNCTION bind_legacy_item_edit_candidate_owner()"
    )
    op.execute("""
        CREATE FUNCTION invalidate_legacy_item_edit_candidate()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM legacy_item_edit_candidates
             WHERE item_id=OLD.id AND vault_id=OLD.vault_id;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER legacy_item_edit_candidate_invalidated "
        "AFTER UPDATE OR DELETE ON vault_items FOR EACH ROW "
        "EXECUTE FUNCTION invalidate_legacy_item_edit_candidate()"
    )
    op.execute("""
        CREATE TABLE legacy_item_edit_history (
            history_id BIGSERIAL PRIMARY KEY,
            vault_id UUID NOT NULL REFERENCES vaults(vault_id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL,
            prior_source_snapshot VARCHAR(43) NOT NULL,
            prior_item_type TEXT NOT NULL,
            prior_service TEXT NOT NULL,
            prior_encrypted_data TEXT NOT NULL,
            prior_item_type_ciphertext BYTEA,
            prior_service_ciphertext BYTEA,
            prior_payload_ciphertext BYTEA,
            prior_title_lookup_hash BYTEA,
            prior_title_revision INTEGER NOT NULL,
            prior_created_at TIMESTAMPTZ NOT NULL,
            promoted_candidate_sha256 BYTEA NOT NULL,
            promoted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT legacy_item_edit_history_shape_ck CHECK (
                prior_source_snapshot ~ '^[A-Za-z0-9_-]{43}$' AND
                length(promoted_candidate_sha256) = 32
            )
        )
    """)
    op.execute(
        "CREATE INDEX legacy_item_edit_history_item_idx "
        "ON legacy_item_edit_history(vault_id,item_id,promoted_at DESC)"
    )


def downgrade() -> None:
    # A history row may be the only retained copy of a prior encrypted item.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM legacy_item_edit_history) OR
               EXISTS (SELECT 1 FROM legacy_item_edit_candidates) THEN
                RAISE EXCEPTION 'keyless_item_edit_data_not_empty'
                    USING ERRCODE='23514';
            END IF;
        END $$
    """)
    op.execute("DROP TABLE legacy_item_edit_history")
    op.execute(
        "DROP TRIGGER legacy_item_edit_candidate_invalidated ON vault_items"
    )
    op.execute("DROP FUNCTION invalidate_legacy_item_edit_candidate()")
    op.execute(
        "DROP TRIGGER legacy_item_edit_candidate_owner_guard "
        "ON legacy_item_edit_candidates"
    )
    op.execute("DROP FUNCTION bind_legacy_item_edit_candidate_owner()")
    op.execute("DROP TABLE legacy_item_edit_candidates")
