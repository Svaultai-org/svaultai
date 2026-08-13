"""Add opaque WalletBackupV2 records and merge the ZK-v2 migration heads."""
from alembic import op

revision = "0039_wallet_backup_v2"
down_revision = ("0038_credential_v2_endpoint", "0038_file_v2_core")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE IF NOT EXISTS wallet_backup_v2_records (
        id BIGSERIAL PRIMARY KEY,
        vault_id TEXT NOT NULL,
        backup_record_id TEXT NOT NULL,
        secret_type TEXT NOT NULL,
        payload_ciphertext BYTEA NOT NULL,
        envelope_version TEXT NOT NULL CHECK (envelope_version = 'client_mvk_v2'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (vault_id, backup_record_id)
      );
      CREATE INDEX IF NOT EXISTS wallet_backup_v2_vault_created_idx
        ON wallet_backup_v2_records(vault_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_backup_v2_records")
