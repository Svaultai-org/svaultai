

from typing import Sequence, Union

from alembic import op


revision: str = "0004_uploaded_files_content_hash"
down_revision: Union[str, None] = "0003_import_batches"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
                                                                   
                                                                 
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS content_sha256 TEXT"
    )
                                                
                                                                 
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_content_sha256_format_chk "
        "CHECK (content_sha256 IS NULL OR length(content_sha256) = 64)"
    )

                                                               
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS duplicate_of_file_id TEXT "
        "REFERENCES uploaded_files(id) ON DELETE SET NULL"
    )

                                                                  
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS version_number INTEGER NOT NULL DEFAULT 1 "
        "CHECK (version_number >= 1)"
    )

                                                                   
    op.execute(
        "CREATE INDEX uploaded_files_content_hash_idx "
        "ON uploaded_files (vault_id, content_sha256, file_size) "
        "WHERE content_sha256 IS NOT NULL"
    )

                                                                  
    op.execute(
        "CREATE INDEX uploaded_files_duplicate_of_idx "
        "ON uploaded_files (vault_id, duplicate_of_file_id) "
        "WHERE duplicate_of_file_id IS NOT NULL"
    )

                                                                    
    op.execute(
        "CREATE INDEX uploaded_files_name_conflict_idx "
        "ON uploaded_files (vault_id, relative_path, saved_name) "
        "WHERE saved_name IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uploaded_files_name_conflict_idx")
    op.execute("DROP INDEX IF EXISTS uploaded_files_duplicate_of_idx")
    op.execute("DROP INDEX IF EXISTS uploaded_files_content_hash_idx")
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS version_number"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS duplicate_of_file_id"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS uploaded_files_content_sha256_format_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files DROP COLUMN IF EXISTS content_sha256"
    )
