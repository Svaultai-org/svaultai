

from typing import Union

from alembic import op


revision: str = "0013_vault_content_chunks"
down_revision: Union[str, None] = "0012_vault_file_relationships"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_EMBEDDING_DIM = 1536


_EXTRACTION_SOURCES = (
    "pdf_text",
    "ocr",
    "image_ocr",
    "docx",
    "txt",
    "html",
    "json",
    "csv",
    "xlsx",
    "archive",
    "audio_transcript",
    "video_transcript",
    "video_frame",
    "plain_text",
)


_OLD_STAGES = (
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
_NEW_STAGES = _OLD_STAGES + ("content_chunking",)


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
                                                                   
                                                                
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS vault_content_chunks (
            chunk_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id              UUID NOT NULL REFERENCES vaults(vault_id)
                                       ON DELETE CASCADE,
            file_id               TEXT NOT NULL REFERENCES uploaded_files(id)
                                       ON DELETE CASCADE,
            chunk_index           INTEGER NOT NULL,

            -- Encrypted chunk plaintext. AES-GCM-256 via the per-vault
            -- key, encoded as base64 (matches the uploaded_files.
            -- extracted_text convention).
            encrypted_chunk_text  TEXT NOT NULL,
            chunk_text_encrypted  BOOLEAN NOT NULL DEFAULT TRUE,

            -- Character range within the file's normalized
            -- extracted_text. Lets a retriever cite "the chunk that
            -- starts at offset 412" if the UI ever needs it.
            char_start            INTEGER NOT NULL,
            char_end              INTEGER NOT NULL,
            char_length           INTEGER GENERATED ALWAYS AS (char_end - char_start) STORED,

            -- Where the chunk's text came from. Closed-set enum.
            extraction_source     TEXT NOT NULL,

            -- pgvector embedding (NULL until the indexer fills it).
            embedding             vector({_EMBEDDING_DIM}),
            embedding_model       TEXT,                -- e.g. 'text-embedding-3-small'
            embedding_dim         INTEGER,             -- pinned at write
            embedded_at           TIMESTAMPTZ,

            -- Per-chunk entities / signals (jsonb). Optional.
            entities_jsonb        JSONB NOT NULL DEFAULT '{{}}'::jsonb,

            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT vault_content_chunks_chunk_index_nonneg_chk
                CHECK (chunk_index >= 0),

            CONSTRAINT vault_content_chunks_char_range_ordered_chk
                CHECK (char_start >= 0 AND char_end >= char_start),

            CONSTRAINT vault_content_chunks_extraction_source_chk
                CHECK ({_enum_check("extraction_source", _EXTRACTION_SOURCES)}),

            -- Plaintext is NEVER written. A future caller that flips
            -- chunk_text_encrypted to FALSE is refused at write time.
            CONSTRAINT vault_content_chunks_no_plaintext_at_rest_chk
                CHECK (chunk_text_encrypted = TRUE)
        )
        """
    )

                                                                  
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "vault_content_chunks_file_chunk_idx "
        "ON vault_content_chunks (file_id, chunk_index)"
    )

                                                                   
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_content_chunks_vault_id_idx "
        "ON vault_content_chunks (vault_id)"
    )

                                                                 
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_content_chunks_vault_file_idx "
        "ON vault_content_chunks (vault_id, file_id)"
    )

                                             
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_content_chunks_source_idx "
        "ON vault_content_chunks (extraction_source)"
    )

                                                  
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_content_chunks_embedding_idx "
        "ON vault_content_chunks USING ivfflat "
        "(embedding vector_cosine_ops) WITH (lists = 100)"
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

    op.execute("DROP TABLE IF EXISTS vault_content_chunks")
