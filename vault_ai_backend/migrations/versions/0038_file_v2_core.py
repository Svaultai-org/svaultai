"""FILE_V2 opaque manifests and encrypted chunks."""
from alembic import op

revision = "0038_file_v2_core"
down_revision = "0037_memory_v2_record_identity"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("""
      CREATE TABLE IF NOT EXISTS file_v2_records (
        file_id TEXT PRIMARY KEY,
        vault_id TEXT NOT NULL,
        crypto_version TEXT NOT NULL CHECK (crypto_version = 'client_mvk_v2'),
        manifest_ciphertext BYTEA NOT NULL,
        total_bytes BIGINT NOT NULL CHECK (total_bytes >= 0),
        chunk_size INTEGER NOT NULL CHECK (chunk_size > 0),
        chunk_count INTEGER NOT NULL CHECK (chunk_count >= 0),
        lifecycle_state TEXT NOT NULL DEFAULT 'file_v2_written',
        verification_state TEXT NOT NULL DEFAULT 'not_verified',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
      CREATE INDEX IF NOT EXISTS file_v2_records_vault_idx
        ON file_v2_records(vault_id, created_at DESC);
      CREATE TABLE IF NOT EXISTS file_v2_chunks (
        file_id TEXT NOT NULL REFERENCES file_v2_records(file_id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
        ciphertext BYTEA NOT NULL,
        PRIMARY KEY (file_id, chunk_index)
      );
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS file_v2_chunks")
    op.execute("DROP TABLE IF EXISTS file_v2_records")
