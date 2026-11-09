"""Protect an owner-confirmed staged Memory copy from older source writes.

Confirmation is separately gated and off by default. Unconfirmed copies keep
their original older-client behavior, including invalidation on source edits.
"""

from alembic import op


revision = "0072_memory_stage_confirmation"
down_revision = "0071_memory_verified_edit_fence"
branch_labels = None
depends_on = None


def _guard_sql(*, include_stage: bool) -> str:
    protected = (
        "(owner_verified_edit OR owner_verified_stage)"
        if include_stage else "owner_verified_edit"
    )
    return f"""
        CREATE OR REPLACE FUNCTION reject_older_write_to_verified_memory()
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
          IF TG_OP = 'DELETE' THEN
            PERFORM 1 FROM vaults WHERE vault_id = OLD.vault_id;
            IF NOT FOUND THEN RETURN OLD; END IF;
          END IF;
          PERFORM 1 FROM memory_v2_prepared_copies
           WHERE legacy_memory_id = OLD.id
             AND vault_id = OLD.vault_id
             AND {protected};
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
    """


def upgrade() -> None:
    op.execute("""
        ALTER TABLE memory_v2_prepared_copies
          ADD COLUMN owner_verified_stage BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute(_guard_sql(include_stage=True))


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM memory_v2_prepared_copies
                      WHERE owner_verified_stage) THEN
            RAISE EXCEPTION 'confirmed_memory_copies_cannot_be_unprotected';
          END IF;
        END $$
    """)
    op.execute(_guard_sql(include_stage=False))
    op.execute("ALTER TABLE memory_v2_prepared_copies DROP COLUMN owner_verified_stage")
