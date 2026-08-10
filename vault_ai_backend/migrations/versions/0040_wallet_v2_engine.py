"""Add opaque WalletV2 engine records."""
from alembic import op

revision = "0040_wallet_v2_engine"
down_revision = "0039_wallet_backup_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE IF NOT EXISTS wallet_v2_records (
        id BIGSERIAL PRIMARY KEY,
        vault_id TEXT NOT NULL,
        wallet_record_id TEXT NOT NULL,
        chain TEXT NOT NULL,
        network TEXT NOT NULL,
        asset TEXT NOT NULL,
        public_address TEXT NOT NULL,
        wallet_label TEXT NOT NULL,
        payload_ciphertext BYTEA NOT NULL,
        envelope_version TEXT NOT NULL CHECK (envelope_version = 'v2'),
        migration_state TEXT NOT NULL DEFAULT 'v2_verified',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (vault_id, wallet_record_id)
      );
      CREATE INDEX IF NOT EXISTS wallet_v2_vault_idx
        ON wallet_v2_records(vault_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wallet_v2_records")
