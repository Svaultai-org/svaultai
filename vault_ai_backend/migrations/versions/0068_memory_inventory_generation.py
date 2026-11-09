"""Fence private Memory writes against concurrent older-client changes.

The counter advances in the same transaction as every source Memory or
prepared-copy mutation, including writes made by older clients. It contains
no vault content. Existing ciphertext and older-client routes are unchanged.
"""

from alembic import op


revision = "0068_memory_inventory_generation"
down_revision = "0067_linked_inheritance_readback_proof"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE vaults ADD COLUMN memory_inventory_generation BIGINT
          NOT NULL DEFAULT 0 CHECK (memory_inventory_generation >= 0)
    """)
    op.execute("""
        CREATE FUNCTION advance_memory_inventory_generation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE old_owner UUID;
        DECLARE new_owner UUID;
        BEGIN
          IF TG_OP <> 'INSERT' THEN old_owner := OLD.vault_id; END IF;
          IF TG_OP <> 'DELETE' THEN new_owner := NEW.vault_id; END IF;
          UPDATE vaults
             SET memory_inventory_generation = memory_inventory_generation + 1
           WHERE vault_id = old_owner OR vault_id = new_owner;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$
    """)
    for table in ("vault_ai_memory", "memory_v2_prepared_copies"):
        op.execute(f"""
            CREATE TRIGGER advance_memory_inventory_generation
            AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION advance_memory_inventory_generation()
        """)


def downgrade() -> None:
    for table in ("memory_v2_prepared_copies", "vault_ai_memory"):
        op.execute(
            f"DROP TRIGGER advance_memory_inventory_generation ON {table}"
        )
    op.execute("DROP FUNCTION advance_memory_inventory_generation()")
    op.execute("ALTER TABLE vaults DROP COLUMN memory_inventory_generation")
