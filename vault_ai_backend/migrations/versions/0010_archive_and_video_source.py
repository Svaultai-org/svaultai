

from typing import Sequence, Union

from alembic import op


revision: str = "0010_archive_and_video_source"
down_revision: Union[str, None] = (
    "0009_vault_file_embeddings_safe_input_hash"
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_TEXT_SOURCES = (
    "upload",
    "worker",
    "ocr",
    "transcript",
    "video_transcript",                  
    "archive_index",               
)


_OLD_TEXT_SOURCES = (
    "upload",
    "worker",
    "ocr",
    "transcript",
)


_NEW_STAGES = (
    "text_extraction",
    "ocr",
    "audio_transcription",
    "video_transcription",
    "document_understanding",
    "file_understanding",
    "file_embedding",
    "archive_indexing",                     
    "entity_extraction",
    "embedding",
    "relationship_building",
    "expiry_detection",
    "credential_file_detection",
)


_OLD_STAGES = (
    "text_extraction",
    "ocr",
    "audio_transcription",
    "video_transcription",
    "document_understanding",
    "file_understanding",
    "file_embedding",
    "entity_extraction",
    "embedding",
    "relationship_building",
    "expiry_detection",
    "credential_file_detection",
)


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
                                            
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS uploaded_files_extracted_text_source_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_extracted_text_source_chk "
        f"CHECK (extracted_text_source IS NULL "
        f"       OR {_enum_check('extracted_text_source', _NEW_TEXT_SOURCES)})"
    )

                                                
    op.execute(
        "ALTER TABLE vault_analysis_jobs "
        "DROP CONSTRAINT IF EXISTS vault_analysis_jobs_stage_chk"
    )
    op.execute(
        "ALTER TABLE vault_analysis_jobs "
        "ADD CONSTRAINT vault_analysis_jobs_stage_chk "
        f"CHECK ({_enum_check('stage', _NEW_STAGES)})"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE vault_analysis_jobs "
        "DROP CONSTRAINT IF EXISTS vault_analysis_jobs_stage_chk"
    )
    op.execute(
        "ALTER TABLE vault_analysis_jobs "
        "ADD CONSTRAINT vault_analysis_jobs_stage_chk "
        f"CHECK ({_enum_check('stage', _OLD_STAGES)})"
    )

    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS uploaded_files_extracted_text_source_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_extracted_text_source_chk "
        f"CHECK (extracted_text_source IS NULL "
        f"       OR {_enum_check('extracted_text_source', _OLD_TEXT_SOURCES)})"
    )
