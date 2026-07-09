

from typing import Sequence, Union

from alembic import op


revision: str = "0003_import_batches"
down_revision: Union[str, None] = "0002_uploaded_files_relative_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


IMPORT_BATCH_STATUSES_SQL = (
    "'pending','uploading','completed','completed_with_errors',"
    "'cancelled','failed'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE import_batches (
            import_id              UUID         PRIMARY KEY,
            vault_id               UUID         NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            root_folder_name       TEXT,
            total_files            INTEGER      NOT NULL DEFAULT 0
                CHECK (total_files >= 0),
            uploaded_count         INTEGER      NOT NULL DEFAULT 0
                CHECK (uploaded_count >= 0),
            failed_count           INTEGER      NOT NULL DEFAULT 0
                CHECK (failed_count >= 0),
            skipped_duplicate_count INTEGER     NOT NULL DEFAULT 0
                CHECK (skipped_duplicate_count >= 0),
            status                 TEXT         NOT NULL DEFAULT 'pending'
                CHECK (status IN ({IMPORT_BATCH_STATUSES_SQL})),
            total_bytes_planned    BIGINT       NOT NULL DEFAULT 0
                CHECK (total_bytes_planned >= 0),
            total_bytes_uploaded   BIGINT       NOT NULL DEFAULT 0
                CHECK (total_bytes_uploaded >= 0),
            created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            completed_at           TIMESTAMPTZ
        );
        """
    )
                                                                   
                                                                   
    op.execute(
        "CREATE INDEX import_batches_vault_status_idx "
        "ON import_batches (vault_id, status, created_at DESC);"
    )

                                                                  
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS import_id UUID "
        "REFERENCES import_batches(import_id) ON DELETE SET NULL"
    )
                                                                    
                                                                   
    op.execute(
        "CREATE INDEX uploaded_files_import_idx "
        "ON uploaded_files (import_id) "
        "WHERE import_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uploaded_files_import_idx")
    op.execute("ALTER TABLE uploaded_files DROP COLUMN IF EXISTS import_id")
    op.execute("DROP INDEX IF EXISTS import_batches_vault_status_idx")
    op.execute("DROP TABLE IF EXISTS import_batches")
