

from typing import Sequence, Union

from alembic import op


revision: str = "0002_uploaded_files_relative_path"
down_revision: Union[str, None] = "0001_baseline_vaultid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
                                                                    
                                                                  
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS relative_path TEXT"
    )

                                                
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_relative_path_len_chk "
        "CHECK (relative_path IS NULL OR length(relative_path) <= 1024)"
    )

                                                                 
    op.execute(
        "CREATE INDEX uploaded_files_relative_path_idx "
        "ON uploaded_files (vault_id, relative_path text_pattern_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uploaded_files_relative_path_idx")
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS uploaded_files_relative_path_len_chk"
    )
    op.execute("ALTER TABLE uploaded_files DROP COLUMN IF EXISTS relative_path")
