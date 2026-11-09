"""Refuse older Memory title writes in a vault with private V2 memories.

The server cannot compare a PIN-keyed title identity with an MVK-keyed one.
This per-vault fence is OFF by default. Once deliberately enabled for an
upgraded vault, old readers and deletes remain available, but old creates and
content edits stop when an active native V2 record exists. A conflict is safer
than silently creating a duplicate title with a different keyed identity.
"""

from alembic import op


revision = "0073_memory_mixed_title_fence"
down_revision = "0072_memory_stage_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE vaults ADD COLUMN memory_mixed_title_fence_enabled
          BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE FUNCTION reject_older_memory_title_write()
        RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
        DECLARE fence_enabled BOOLEAN;
        BEGIN
          -- Older edit/delete-by-ID routes can select a native V2 row and
          -- soft-supersede it without being able to decrypt its contents.
          -- The native V2 routes edit in place or physically delete instead.
          IF TG_OP = 'UPDATE'
             AND OLD.superseded_at IS NULL
             AND NEW.superseded_at IS NOT NULL
             AND (CASE WHEN OCTET_LENGTH(OLD.payload_ciphertext) >= 29
                      THEN GET_BYTE(OLD.payload_ciphertext, 0) = 1
                      ELSE FALSE END)
             AND OLD.memory_record_id IS NOT NULL
             AND OLD.memory_lookup_hash IS NOT NULL THEN
            SELECT memory_mixed_title_fence_enabled INTO fence_enabled
              FROM vaults WHERE vault_id = OLD.vault_id FOR UPDATE;
            IF COALESCE(fence_enabled, FALSE) THEN
              RAISE EXCEPTION USING
                ERRCODE = '23514',
                CONSTRAINT = 'memory_mixed_title_fence',
                MESSAGE = 'memory_client_update_required';
            END IF;
          END IF;
          -- A repeated save that only changes timestamps, or a soft delete,
          -- cannot introduce a new title. Keep those older-client actions.
          IF TG_OP = 'UPDATE' THEN
            IF ROW(NEW.payload_ciphertext, NEW.memory_key,
                   NEW.memory_value, NEW.memory_normalized_key,
                   NEW.memory_lookup_hash, NEW.memory_record_id,
                   NEW.memory_type)
               IS NOT DISTINCT FROM
               ROW(OLD.payload_ciphertext, OLD.memory_key,
                   OLD.memory_value, OLD.memory_normalized_key,
                   OLD.memory_lookup_hash, OLD.memory_record_id,
                   OLD.memory_type) THEN
              RETURN NEW;
            END IF;
          END IF;
          IF NEW.superseded_at IS NOT NULL THEN RETURN NEW; END IF;
          -- A native V2 writer has a separate keyed-title and generation
          -- check. Do not mistake it for a legacy encrypted payload.
          IF (CASE WHEN OCTET_LENGTH(NEW.payload_ciphertext) >= 29
                  THEN GET_BYTE(NEW.payload_ciphertext, 0) = 1
                  ELSE FALSE END)
             AND NEW.memory_record_id IS NOT NULL
             AND NEW.memory_lookup_hash IS NOT NULL THEN
            RETURN NEW;
          END IF;

          -- This lock serializes an explicit flag switch and all older
          -- content writes. The existing generation trigger takes this row
          -- lock too; keeping it before the native-row lookup closes the
          -- flag-transition race.
          SELECT memory_mixed_title_fence_enabled INTO fence_enabled
            FROM vaults WHERE vault_id = NEW.vault_id FOR UPDATE;
          IF NOT COALESCE(fence_enabled, FALSE) THEN RETURN NEW; END IF;
          PERFORM 1 FROM vault_ai_memory m
           WHERE m.vault_id = NEW.vault_id
             AND m.id IS DISTINCT FROM NEW.id
             AND m.superseded_at IS NULL
             AND (CASE WHEN OCTET_LENGTH(m.payload_ciphertext) >= 29
                      THEN GET_BYTE(m.payload_ciphertext, 0) = 1
                      ELSE FALSE END)
             AND m.memory_record_id IS NOT NULL
             AND m.memory_lookup_hash IS NOT NULL
           LIMIT 1;
          IF FOUND THEN
            RAISE EXCEPTION USING
              ERRCODE = '23514',
              CONSTRAINT = 'memory_mixed_title_fence',
              MESSAGE = 'memory_client_update_required';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER reject_older_memory_title_write
        BEFORE INSERT OR UPDATE ON vault_ai_memory
        FOR EACH ROW EXECUTE FUNCTION reject_older_memory_title_write()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM vaults
                      WHERE memory_mixed_title_fence_enabled) THEN
            RAISE EXCEPTION 'fenced_memory_vaults_cannot_be_unprotected';
          END IF;
        END $$
    """)
    op.execute("DROP TRIGGER reject_older_memory_title_write ON vault_ai_memory")
    op.execute("DROP FUNCTION reject_older_memory_title_write()")
    op.execute("ALTER TABLE vaults DROP COLUMN memory_mixed_title_fence_enabled")
