"""Add a per-vault blinded file conflict index, initially inactive.

The index is populated only by an unlocked client. Merely migrating this
schema cannot mark any vault complete or permit a private upload.
"""

from alembic import op


revision = "0075_file_private_conflict_index"
down_revision = "0074_linked_inheritance_memory_copies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE file_private_conflict_state (
          vault_id UUID PRIMARY KEY REFERENCES vaults(vault_id) ON DELETE CASCADE,
          inventory_generation BIGINT NOT NULL DEFAULT 0
            CHECK (inventory_generation >= 0),
          indexed_generation BIGINT
            CHECK (indexed_generation >= 0),
          enforced BOOLEAN NOT NULL DEFAULT FALSE,
          CHECK (indexed_generation IS NULL OR
                 indexed_generation <= inventory_generation)
        )
    """)
    op.execute("""
        CREATE TABLE file_private_conflict_index (
          vault_id UUID NOT NULL REFERENCES vaults(vault_id) ON DELETE CASCADE,
          file_id TEXT NOT NULL,
          file_size BIGINT NOT NULL CHECK (file_size >= 0),
          content_token BYTEA NOT NULL
            CHECK (OCTET_LENGTH(content_token) = 32),
          PRIMARY KEY (vault_id, file_id)
        )
    """)
    op.execute("""
        CREATE INDEX file_private_conflict_content_idx
          ON file_private_conflict_index
             (vault_id, content_token, file_size)
    """)
    op.execute("""
        CREATE TABLE file_private_conflict_names (
          vault_id UUID NOT NULL,
          file_id TEXT NOT NULL,
          name_token BYTEA NOT NULL
            CHECK (OCTET_LENGTH(name_token) = 32),
          PRIMARY KEY (vault_id, file_id, name_token),
          FOREIGN KEY (vault_id, file_id)
            REFERENCES file_private_conflict_index(vault_id, file_id)
            ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE INDEX file_private_conflict_name_idx
          ON file_private_conflict_names(vault_id, name_token, file_id)
    """)
    op.execute("""
        CREATE FUNCTION file_private_conflict_inventory_guard()
        RETURNS TRIGGER LANGUAGE plpgsql AS $fn$
        DECLARE
          target_vault UUID;
          target_file TEXT;
          active BOOLEAN;
          is_private_marker BOOLEAN;
        BEGIN
          IF TG_OP = 'UPDATE' AND OLD.vault_id IS DISTINCT FROM NEW.vault_id THEN
            RAISE EXCEPTION 'file_vault_change_forbidden' USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'DELETE' THEN
            target_vault := OLD.vault_id;
            target_file := OLD.id;
          ELSE
            target_vault := NEW.vault_id;
            target_file := NEW.id;
          END IF;

          -- Create the row even for an older writer: an in-flight writer may
          -- race the first backfill, and both must serialize on this row.
          IF TG_OP <> 'DELETE' THEN
            INSERT INTO file_private_conflict_state(vault_id)
              VALUES (target_vault) ON CONFLICT (vault_id) DO NOTHING;
          END IF;
          SELECT enforced INTO active FROM file_private_conflict_state
            WHERE vault_id = target_vault FOR UPDATE;
          IF NOT FOUND THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RAISE EXCEPTION 'private_file_conflict_state_missing';
          END IF;

          IF TG_OP = 'DELETE' THEN
            DELETE FROM file_private_conflict_index
              WHERE vault_id = target_vault AND file_id = target_file;
            IF OLD.file_name IS NOT NULL OR
               OLD.encrypted_file_data IS NOT NULL THEN
              UPDATE file_private_conflict_state
                SET inventory_generation = inventory_generation + 1,
                    indexed_generation = NULL
                WHERE vault_id = target_vault;
            END IF;
            RETURN OLD;
          END IF;

          is_private_marker := NEW.file_name IS NULL
            AND NEW.encrypted_file_data IS NULL
            AND EXISTS (
              SELECT 1 FROM file_v2_records
              WHERE file_id = NEW.id AND vault_id = target_vault::TEXT
                AND migrating_legacy = FALSE
            );
          IF active AND NOT is_private_marker THEN
            RAISE EXCEPTION 'private_file_legacy_writer_blocked'
              USING ERRCODE = '23514';
          END IF;
          IF is_private_marker AND EXISTS (
            SELECT 1 FROM file_private_conflict_index
            WHERE vault_id = target_vault AND file_id = target_file
              AND file_size = NEW.file_size
          ) THEN
            RETURN NEW;
          END IF;
          IF active THEN
            RAISE EXCEPTION 'private_file_index_missing'
              USING ERRCODE = '23514';
          END IF;
          DELETE FROM file_private_conflict_index
            WHERE vault_id = target_vault AND file_id = target_file;
          UPDATE file_private_conflict_state
            SET inventory_generation = inventory_generation + 1,
                indexed_generation = NULL
            WHERE vault_id = target_vault;
          RETURN NEW;
        END $fn$
    """)
    op.execute("""
        CREATE TRIGGER uploaded_files_private_conflict_guard
          BEFORE INSERT OR UPDATE OR DELETE ON uploaded_files
          FOR EACH ROW EXECUTE FUNCTION
            file_private_conflict_inventory_guard()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM file_private_conflict_index) OR
             EXISTS (SELECT 1 FROM file_private_conflict_state WHERE enforced) THEN
            RAISE EXCEPTION 'private_file_conflict_index_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("DROP TRIGGER IF EXISTS uploaded_files_private_conflict_guard ON uploaded_files")
    op.execute("DROP FUNCTION IF EXISTS file_private_conflict_inventory_guard()")
    op.execute("DROP TABLE IF EXISTS file_private_conflict_names")
    op.execute("DROP TABLE IF EXISTS file_private_conflict_index")
    op.execute("DROP TABLE IF EXISTS file_private_conflict_state")
