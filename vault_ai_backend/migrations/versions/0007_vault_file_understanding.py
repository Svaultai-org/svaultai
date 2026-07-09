

from typing import Sequence, Union

from alembic import op


revision: str = "0007_vault_file_understanding"
down_revision: Union[str, None] = "0006_extracted_text_lifecycle"
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
        CREATE TABLE IF NOT EXISTS vault_file_understanding (
            understanding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id UUID NOT NULL,
            file_id UUID NOT NULL,

            -- Versioning. ``source_text_version`` mirrors the
            -- uploaded_files.extracted_text_version at write time
            -- so a stale-detection query can spot files whose
            -- source text has been re-extracted since the
            -- understanding was built. ``analysis_version`` is
            -- model-version-bumped per codebase change.
            source_text_version INTEGER NOT NULL DEFAULT 0,
            analysis_version    INTEGER NOT NULL DEFAULT 1,

            -- Lifecycle status.
            status TEXT NOT NULL DEFAULT 'pending',

            -- Document-purpose verdict from
            -- ``vault_document_purpose.classify_document_purpose``.
            -- ``document_purpose`` is the closed-set machine tag
            -- (saved_login_list / credential_export / config_secrets
            -- / application_form / insurance_form /
            -- government_legal_financial / generic_text / unknown).
            -- ``purpose_label`` is the short human phrase shown in
            -- the picker reason line.
            document_purpose   TEXT,
            purpose_label      TEXT,
            purpose_confidence REAL,

            -- ENCRYPTED user content (ciphertext only).
            summary_encrypted       TEXT,
            safe_preview_encrypted  TEXT,

            -- Belt-and-braces flags for the CHECK below. True iff
            -- the matching ``_encrypted`` column holds AES-GCM
            -- ciphertext written with the per-vault key.
            summary_is_encrypted      BOOLEAN NOT NULL DEFAULT FALSE,
            safe_preview_is_encrypted BOOLEAN NOT NULL DEFAULT FALSE,

            -- Closed-set signal bags. JSONB so each family stays
            -- evolvable, but the WRITER's vocabulary is a closed
            -- set the understanding worker enforces.
            topics_jsonb              JSONB NOT NULL DEFAULT '[]'::jsonb,
            entities_jsonb            JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            dates_jsonb               JSONB NOT NULL DEFAULT '[]'::jsonb,
            detected_categories_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- Family-specific signal bags. Each is a small JSONB
            -- dict the chat / search layer reads to answer focused
            -- questions ("am I travel ready?", "find files with
            -- saved logins"). Counts + booleans + label arrays only
            -- — NEVER captured values.
            credential_signals_jsonb   JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            travel_signals_jsonb       JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            financial_signals_jsonb    JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            legal_signals_jsonb        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            identity_signals_jsonb     JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            relationship_signals_jsonb JSONB NOT NULL DEFAULT '{{}}'::jsonb,

            -- Searchable term bag — closed-set keyword tokens the
            -- ranker scores against the user query. NOT a free-form
            -- text dump; the worker filters out password-like
            -- tokens before write.
            searchable_terms_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- Per-field confidence map. Lets chat surface "high
            -- confidence on purpose, low on dates" honestly when
            -- the user asks why a file was classified a certain way.
            confidence_jsonb JSONB NOT NULL DEFAULT '{{}}'::jsonb,

            -- Last error message (scrubbed for secret values via
            -- the same _truncate_error helper used by the existing
            -- analysis_status surface).
            last_error TEXT,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT vault_file_understanding_status_chk
                CHECK ({status_check}),

            -- No plaintext at rest. If summary_encrypted is
            -- non-null, summary_is_encrypted MUST be true. Same for
            -- safe_preview_encrypted. A regression that tries to
            -- write a raw summary fails the constraint LOUDLY.
            CONSTRAINT vault_file_understanding_no_plaintext_summary_chk
                CHECK (
                    summary_encrypted IS NULL
                    OR summary_is_encrypted = TRUE
                ),
            CONSTRAINT vault_file_understanding_no_plaintext_preview_chk
                CHECK (
                    safe_preview_encrypted IS NULL
                    OR safe_preview_is_encrypted = TRUE
                ),

            -- A ``ready`` row must carry a purpose verdict. (Failed
            -- / stale / pending rows may have NULL.)
            CONSTRAINT vault_file_understanding_ready_has_purpose_chk
                CHECK (
                    status <> 'ready' OR document_purpose IS NOT NULL
                )
        )
        """.format(status_check=_enum_check("status", _STATUSES))
    )

                                                                   
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "vault_file_understanding_file_idx "
        "ON vault_file_understanding (vault_id, file_id)"
    )

                                                                 
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_understanding_vault_status_idx "
        "ON vault_file_understanding (vault_id, status)"
    )

                                                                       
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_understanding_vault_purpose_idx "
        "ON vault_file_understanding (vault_id, document_purpose)"
    )

                                          
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_understanding_source_text_version_idx "
        "ON vault_file_understanding (vault_id, source_text_version)"
    )


_OLD_STAGES = (
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
        "DROP INDEX IF EXISTS "
        "vault_file_understanding_source_text_version_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_file_understanding_vault_purpose_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_file_understanding_vault_status_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_file_understanding_file_idx"
    )
    op.execute("DROP TABLE IF EXISTS vault_file_understanding")
