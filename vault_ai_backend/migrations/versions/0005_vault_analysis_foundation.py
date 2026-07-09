

from typing import Sequence, Union

from alembic import op


revision: str = "0005_vault_analysis_foundation"
down_revision: Union[str, None] = "0004_uploaded_files_content_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ANALYSIS_STATUSES = (
    "not_started",
    "pending",
    "processing",
    "analyzed",
    "failed",
    "needs_reanalysis",
    "skipped",
    "unsupported",
)

_JOB_STATUSES = (
    "pending",
    "processing",
    "succeeded",
    "failed",
    "cancelled",
)

_STAGES = (
    "text_extraction",
    "ocr",
    "audio_transcription",
    "video_transcription",
    "document_understanding",
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
        "ADD COLUMN IF NOT EXISTS analysis_status TEXT "
        "NOT NULL DEFAULT 'not_started'"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_analysis_status_chk "
        f"CHECK ({_enum_check('analysis_status', _ANALYSIS_STATUSES)})"
    )

                                                                    
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS analysis_pipeline_state JSONB "
        "NOT NULL DEFAULT '{}'::jsonb"
    )

                                                                             
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS analysis_last_error TEXT"
    )

                                                                    
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS analysis_started_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS analysis_completed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS analysis_updated_at TIMESTAMPTZ"
    )

                                                                 
    op.execute(
        "CREATE INDEX IF NOT EXISTS uploaded_files_analysis_status_idx "
        "ON uploaded_files (vault_id, analysis_status)"
    )

                                                                        
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_analysis_jobs (
            job_id        UUID         PRIMARY KEY
                                       DEFAULT gen_random_uuid(),
            vault_id      UUID         NOT NULL
                                       REFERENCES vaults(vault_id)
                                       ON DELETE CASCADE,
            file_id       TEXT         NOT NULL
                                       REFERENCES uploaded_files(id)
                                       ON DELETE CASCADE,
            stage         TEXT         NOT NULL,
            status        TEXT         NOT NULL DEFAULT 'pending',
            attempts      INTEGER      NOT NULL DEFAULT 0
                                       CHECK (attempts >= 0),
            max_attempts  INTEGER      NOT NULL DEFAULT 3
                                       CHECK (max_attempts >= 1),
            last_error    TEXT,
            locked_at     TIMESTAMPTZ,
            locked_by     TEXT,
            scheduled_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            started_at    TIMESTAMPTZ,
            completed_at  TIMESTAMPTZ,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            metadata_jsonb JSONB       NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )

                                                                  
    op.execute(
        "ALTER TABLE vault_analysis_jobs "
        "ADD CONSTRAINT vault_analysis_jobs_stage_chk "
        f"CHECK ({_enum_check('stage', _STAGES)})"
    )
    op.execute(
        "ALTER TABLE vault_analysis_jobs "
        "ADD CONSTRAINT vault_analysis_jobs_status_chk "
        f"CHECK ({_enum_check('status', _JOB_STATUSES)})"
    )

                                                            
    op.execute(
        "CREATE INDEX IF NOT EXISTS vault_analysis_jobs_ready_idx "
        "ON vault_analysis_jobs (vault_id, status, scheduled_at) "
        "WHERE status IN ('pending', 'processing')"
    )

                                                                  
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS vault_analysis_jobs_file_stage_idx "
        "ON vault_analysis_jobs (file_id, stage) "
        "WHERE status IN ('pending', 'processing')"
    )

                                                                 
    op.execute(
        """
        CREATE OR REPLACE FUNCTION vault_analysis_jobs_touch_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER vault_analysis_jobs_touch_updated_at_trg
            BEFORE UPDATE ON vault_analysis_jobs
            FOR EACH ROW
            EXECUTE FUNCTION vault_analysis_jobs_touch_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS vault_analysis_jobs_touch_updated_at_trg "
        "ON vault_analysis_jobs"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS vault_analysis_jobs_touch_updated_at()"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_analysis_jobs_file_stage_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_analysis_jobs_ready_idx"
    )
    op.execute("DROP TABLE IF EXISTS vault_analysis_jobs")
    op.execute("DROP INDEX IF EXISTS uploaded_files_analysis_status_idx")
    op.execute(
        "ALTER TABLE uploaded_files DROP COLUMN IF EXISTS analysis_updated_at"
    )
    op.execute(
        "ALTER TABLE uploaded_files DROP COLUMN IF EXISTS analysis_completed_at"
    )
    op.execute(
        "ALTER TABLE uploaded_files DROP COLUMN IF EXISTS analysis_started_at"
    )
    op.execute(
        "ALTER TABLE uploaded_files DROP COLUMN IF EXISTS analysis_last_error"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS analysis_pipeline_state"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS uploaded_files_analysis_status_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files DROP COLUMN IF EXISTS analysis_status"
    )
