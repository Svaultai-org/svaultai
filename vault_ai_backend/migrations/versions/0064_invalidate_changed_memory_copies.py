"""Invalidate an owner-prepared Memory copy when an older writer changes it.

The old row remains authoritative until a separate coordinated cutover.
An older client may continue to write it; the prepared V2 copy is removed
in the same transaction so a stale copy cannot later be promoted.
"""

from alembic import op


revision = "0064_invalidate_changed_memory_copies"
down_revision = "0063_memory_v2_prepared_copy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION invalidate_changed_memory_v2_copy()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW(
                NEW.id, NEW.vault_id, NEW.payload_ciphertext,
                NEW.memory_type, NEW.memory_record_id,
                NEW.memory_lookup_hash, NEW.superseded_at
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.vault_id, OLD.payload_ciphertext,
                OLD.memory_type, OLD.memory_record_id,
                OLD.memory_lookup_hash, OLD.superseded_at
            ) THEN
                DELETE FROM memory_v2_prepared_copies
                 WHERE legacy_memory_id = OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER invalidate_changed_memory_v2_copy
        AFTER UPDATE ON vault_ai_memory
        FOR EACH ROW EXECUTE FUNCTION invalidate_changed_memory_v2_copy()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER invalidate_changed_memory_v2_copy ON vault_ai_memory")
    op.execute("DROP FUNCTION invalidate_changed_memory_v2_copy()")
