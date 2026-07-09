

from typing import Sequence, Union

from alembic import op


revision: str = "0008_vault_file_embeddings"
down_revision: Union[str, None] = "0007_vault_file_understanding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_STATUSES = (
    "pending",
    "processing",
    "ready",
    "failed",
    "stale",
    "unsupported",
)


_SOURCES = (
    "combined",
    "summary",
    "safe_preview",
    "extracted_text",
    "ocr",
    "transcript",
)


_EMBEDDING_DIM = 1536


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


_NEW_STAGES = (
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


def _replace_stage_check_constraint() -> None:


    op.execute(
        "ALTER TABLE vault_analysis_jobs "
        "DROP CONSTRAINT IF EXISTS vault_analysis_jobs_stage_chk"
    )
    op.execute(
        "ALTER TABLE vault_analysis_jobs "
        "ADD CONSTRAINT vault_analysis_jobs_stage_chk "
        f"CHECK ({_enum_check('stage', _NEW_STAGES)})"
    )


def upgrade() -> None:
    _replace_stage_check_constraint()

                                                                
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_file_embeddings (
            embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id UUID NOT NULL,
            file_id  UUID NOT NULL,

            -- Optional pointer back to the understanding row that
            -- sourced this embedding. NULL when the worker decided
            -- to build straight from extracted_text (no
            -- understanding row yet).
            understanding_id UUID,

            -- Versioning. Mirrors uploaded_files.extracted_text_version
            -- (and vault_file_understanding.source_text_version) at
            -- write time so the stale-detection housekeeping pass
            -- can spot embeddings whose source text has moved on.
            source_text_version INTEGER NOT NULL DEFAULT 0,

            -- ``analysis_version`` lets a future ranker / model
            -- rotation invalidate older rows globally.
            analysis_version INTEGER NOT NULL DEFAULT 1,

            -- Provider + model identifier. Rotating either bumps
            -- stale.
            embedding_model TEXT NOT NULL DEFAULT 'openai:text-embedding-3-small',

            -- Dimensionality. Pinned per row so a search reading
            -- mismatched vectors can refuse politely instead of
            -- crashing.
            embedding_dim INTEGER NOT NULL DEFAULT {dim},

            -- Which safe surface the embedding was built from.
            -- ``combined`` is the slice-2C default — the
            -- understanding summary + safe_preview + purpose label
            -- + topic / entity bag, all redacted.
            embedding_source TEXT NOT NULL DEFAULT 'combined',

            -- The vector itself. NULL while the row is pending /
            -- processing; populated when the row is ready.
            embedding_vector vector({dim}),

            -- Lifecycle status.
            status TEXT NOT NULL DEFAULT 'pending',

            -- Last error message (scrubbed for secret values via
            -- the same _truncate_error helper used by the
            -- analysis_status surface).
            last_error TEXT,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT vault_file_embeddings_status_chk
                CHECK ({status_check}),

            CONSTRAINT vault_file_embeddings_source_chk
                CHECK ({source_check}),

            -- A ``ready`` row MUST have a populated vector. (Failed
            -- / stale / pending rows may have NULL.)
            CONSTRAINT vault_file_embeddings_ready_has_vector_chk
                CHECK (
                    status <> 'ready' OR embedding_vector IS NOT NULL
                ),

            -- The vector dimensionality must equal the dim column.
            -- This is a soft invariant for now — pgvector enforces
            -- the column-level dim, and the writer pins
            -- embedding_dim to match.
            CONSTRAINT vault_file_embeddings_dim_positive_chk
                CHECK (embedding_dim > 0)
        )
        """.format(
            dim=_EMBEDDING_DIM,
            status_check=_enum_check("status", _STATUSES),
            source_check=_enum_check("embedding_source", _SOURCES),
        )
    )

                                                               
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "vault_file_embeddings_file_idx "
        "ON vault_file_embeddings (vault_id, file_id)"
    )

                                                                   
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_embeddings_vault_status_idx "
        "ON vault_file_embeddings (vault_id, status)"
    )

                                                                
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_embeddings_source_text_version_idx "
        "ON vault_file_embeddings (vault_id, source_text_version)"
    )

                                                            
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_embeddings_vector_idx "
        "ON vault_file_embeddings USING ivfflat "
        "(embedding_vector vector_cosine_ops) WITH (lists = 100)"
    )


_OLD_STAGES = (
    "text_extraction",
    "ocr",
    "audio_transcription",
    "video_transcription",
    "document_understanding",
    "file_understanding",
    "entity_extraction",
    "embedding",
    "relationship_building",
    "expiry_detection",
    "credential_file_detection",
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
        "DROP INDEX IF EXISTS vault_file_embeddings_vector_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS "
        "vault_file_embeddings_source_text_version_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_file_embeddings_vault_status_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_file_embeddings_file_idx"
    )
    op.execute("DROP TABLE IF EXISTS vault_file_embeddings")
