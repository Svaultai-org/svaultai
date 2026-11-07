"""Track irreversible verifier retirement and reject new legacy PIN oracles.

The column does not alter existing vaults. A guarded route may set it only
after strict ingress and owner migration. Source triggers preserve the state
if an older writer is accidentally reintroduced after retirement.
"""

from alembic import op


revision = "0060_pin_verifier_retirement"
down_revision = "0059_keyless_legacy_item_rename"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE vaults
          ADD COLUMN pin_verifier_retired_at TIMESTAMPTZ,
          ADD CONSTRAINT pin_verifier_retired_shape_ck CHECK (
            pin_verifier_retired_at IS NULL OR pin_verifier = ''
          )
    """)
    op.execute("""
        CREATE FUNCTION guard_retired_pin_verifier() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.pin_verifier_retired_at IS NOT NULL AND (
            NEW.pin_verifier_retired_at IS DISTINCT FROM OLD.pin_verifier_retired_at
            OR NEW.pin_verifier <> ''
          ) THEN
            RAISE EXCEPTION 'pin_verifier_retirement_is_irreversible'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER retired_pin_verifier_guard
        BEFORE UPDATE ON vaults FOR EACH ROW
        EXECUTE FUNCTION guard_retired_pin_verifier()
    """)
    op.execute("""
        CREATE FUNCTION guard_retired_legacy_pin_oracle() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE owner_id UUID;
        BEGIN
          IF TG_TABLE_NAME = 'vault_items' THEN
            IF NEW.encrypted_data IS NULL THEN RETURN NEW; END IF;
            owner_id := NEW.vault_id;
          ELSIF TG_TABLE_NAME = 'uploaded_files' THEN
            IF NEW.encrypted_file_data IS NULL THEN RETURN NEW; END IF;
            owner_id := NEW.vault_id;
          ELSIF TG_TABLE_NAME = 'uploaded_file_chunks' THEN
            SELECT vault_id INTO owner_id FROM uploaded_files WHERE id=NEW.file_id;
          ELSIF TG_TABLE_NAME = 'legacy_item_edit_candidates'
             OR TG_TABLE_NAME = 'legacy_item_edit_history' THEN
            owner_id := NEW.vault_id;
          ELSIF TG_TABLE_NAME = 'beneficiary_links' THEN
            IF NEW.wrapped_vault_key = 'zk-beneficiary-v2:no-server-key'
            THEN RETURN NEW; END IF;
            IF EXISTS (
              SELECT 1 FROM vaults
               WHERE vault_id IN (NEW.passer_vault_id, NEW.beneficiary_vault_id)
                 AND pin_verifier_retired_at IS NOT NULL
            ) THEN
              RAISE EXCEPTION 'retired_vault_cannot_store_legacy_pin_oracle'
                USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
          ELSIF TG_TABLE_NAME = 'vault_crypto_migration_journal' THEN
            IF NOT NEW.legacy_retained THEN RETURN NEW; END IF;
            owner_id := NEW.vault_id;
          ELSE
            RAISE EXCEPTION 'unknown_legacy_pin_oracle_table'
              USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1 FROM vaults
             WHERE vault_id = owner_id AND pin_verifier_retired_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'retired_vault_cannot_store_legacy_pin_oracle'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    for table in (
        "vault_items", "uploaded_files", "uploaded_file_chunks",
        "legacy_item_edit_candidates", "legacy_item_edit_history",
        "beneficiary_links", "vault_crypto_migration_journal",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_retired_pin_oracle_guard "
            f"BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW "
            "EXECUTE FUNCTION guard_retired_legacy_pin_oracle()"
        )


def downgrade() -> None:
    # A retired verifier cannot be reconstructed. Preserve the marker and
    # source guards rather than silently reopening old PIN routes.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM vaults WHERE pin_verifier_retired_at IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'retired_pin_verifier_cannot_be_rolled_back'
              USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    for table in (
        "vault_items", "uploaded_files", "uploaded_file_chunks",
        "legacy_item_edit_candidates", "legacy_item_edit_history",
        "beneficiary_links", "vault_crypto_migration_journal",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS {table}_retired_pin_oracle_guard ON {table}"
        )
    op.execute("DROP FUNCTION guard_retired_legacy_pin_oracle()")
    op.execute("DROP TRIGGER IF EXISTS retired_pin_verifier_guard ON vaults")
    op.execute("DROP FUNCTION guard_retired_pin_verifier()")
    op.execute("""
        ALTER TABLE vaults
          DROP CONSTRAINT IF EXISTS pin_verifier_retired_shape_ck,
          DROP COLUMN IF EXISTS pin_verifier_retired_at
    """)
