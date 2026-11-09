"""Keep an owner-edited V2 Memory copy intact after it commits.

An older client can still read the dual-written legacy row. Once an owner
successfully edits both ciphertext formats, an older source-only mutation
must fail rather than let 0064 silently delete the verified V2 copy.
"""

from alembic import op


revision = "0071_memory_verified_edit_fence"
down_revision = "0070_linked_inheritance_item_restart"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memory_v2_prepared_copies
          ADD COLUMN owner_verified_edit BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE FUNCTION reject_older_write_to_verified_memory()
        RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF ROW(
                NEW.id, NEW.vault_id, NEW.payload_ciphertext,
                NEW.memory_type, NEW.memory_record_id,
                NEW.memory_lookup_hash, NEW.superseded_at
            ) IS NOT DISTINCT FROM ROW(
                OLD.id, OLD.vault_id, OLD.payload_ciphertext,
                OLD.memory_type, OLD.memory_record_id,
                OLD.memory_lookup_hash, OLD.superseded_at
            ) THEN
              RETURN NEW;
            END IF;
          END IF;
          -- A vault-wide deletion removes the parent first, then cascades
          -- through Memory. It must remain possible to delete the vault.
          IF TG_OP = 'DELETE' THEN
            PERFORM 1 FROM vaults WHERE vault_id = OLD.vault_id;
            IF NOT FOUND THEN RETURN OLD; END IF;
          END IF;
          -- This VOLATILE lookup takes a fresh snapshot after the source-row
          -- lock, including an owner's just-committed replacement copy.
          PERFORM 1 FROM memory_v2_prepared_copies
           WHERE legacy_memory_id = OLD.id
             AND vault_id = OLD.vault_id
             AND owner_verified_edit;
          IF FOUND THEN
            RAISE EXCEPTION USING
              ERRCODE = '23514',
              CONSTRAINT = 'memory_v2_verified_edit_fence',
              MESSAGE = 'memory_v2_owner_edit_conflict';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER reject_older_write_to_verified_memory
        BEFORE UPDATE OR DELETE ON vault_ai_memory
        FOR EACH ROW EXECUTE FUNCTION reject_older_write_to_verified_memory()
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM memory_v2_prepared_copies
                      WHERE owner_verified_edit) THEN
            RAISE EXCEPTION 'verified_memory_copies_cannot_be_unprotected';
          END IF;
        END $$
    """)
    op.execute("DROP TRIGGER reject_older_write_to_verified_memory ON vault_ai_memory")
    op.execute("DROP FUNCTION reject_older_write_to_verified_memory()")
    op.execute("ALTER TABLE memory_v2_prepared_copies DROP COLUMN owner_verified_edit")
