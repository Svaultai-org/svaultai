

from typing import Sequence, Union

from alembic import op


revision: str = "0006_extracted_text_lifecycle"
down_revision: Union[str, None] = "0005_vault_analysis_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TEXT_STATUSES = ("not_available", "available", "failed", "stale")
_TEXT_SOURCES  = ("upload", "worker", "ocr", "transcript")


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
                                                                        
                                                                
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS extracted_text_status TEXT "
        "NOT NULL DEFAULT 'not_available'"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_extracted_text_status_chk "
        f"CHECK ({_enum_check('extracted_text_status', _TEXT_STATUSES)})"
    )

                                           
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS extracted_text_source TEXT"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_extracted_text_source_chk "
        f"CHECK (extracted_text_source IS NULL "
        f"       OR {_enum_check('extracted_text_source', _TEXT_SOURCES)})"
    )

                                                                   
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS extracted_text_updated_at TIMESTAMPTZ"
    )

                                                                 
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS extracted_text_truncated BOOLEAN "
        "NOT NULL DEFAULT FALSE"
    )

                                                                    
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS extracted_text_char_count INTEGER "
        "NOT NULL DEFAULT 0 "
        "CHECK (extracted_text_char_count >= 0)"
    )

                                                                  
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS extracted_text_version INTEGER "
        "NOT NULL DEFAULT 0 "
        "CHECK (extracted_text_version >= 0)"
    )

                                                           
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_no_plaintext_at_rest_chk "
        "CHECK (extracted_text_status <> 'available' "
        "       OR extracted_text IS NULL "
        "       OR extracted_text_encrypted = TRUE)"
    )

                                                                 
    op.execute(
        "CREATE INDEX IF NOT EXISTS uploaded_files_text_status_idx "
        "ON uploaded_files (vault_id, extracted_text_status)"
    )

                                                                   
    op.execute(
        """
        UPDATE uploaded_files
        SET extracted_text_status = 'available',
            extracted_text_source = 'upload',
            extracted_text_updated_at = COALESCE(created_at, NOW())
        WHERE extracted_text IS NOT NULL
          AND extracted_text_encrypted = TRUE
          AND extracted_text_status = 'not_available'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uploaded_files_text_status_idx")
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS uploaded_files_no_plaintext_at_rest_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS extracted_text_version"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS extracted_text_char_count"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS extracted_text_truncated"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS extracted_text_updated_at"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS uploaded_files_extracted_text_source_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS extracted_text_source"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS uploaded_files_extracted_text_status_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS extracted_text_status"
    )
