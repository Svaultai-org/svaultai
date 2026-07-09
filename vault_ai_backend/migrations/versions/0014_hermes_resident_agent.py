

from typing import Union

from alembic import op


revision: str = "0014_hermes_resident_agent"
down_revision: Union[str, None] = "0013_vault_content_chunks"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_EMBEDDING_DIM = 1536


_MEMORY_TYPES = (
    "file_summary",
    "credential_record",
    "file_relationship",
    "entity_extraction",
    "unsupported_file",
    "failed_analysis",
    "vault_observation",
    "task_proposal",
    "credential_followup_context",
)


_SOURCE_STAGES = (
    "text_extraction",
    "ocr",
    "archive_indexing",
    "audio_transcription",
    "video_transcription",
    "content_chunking",
    "file_embedding",
    "document_understanding",
    "credential_file_detection",
    "relationship_building",
    "expiry_detection",
    "entity_extraction",
    "file_understanding",
    "file_upload_complete",
    "user_question",
    "resident_review",
)


_TASK_TYPES = (
    "review_new_file",
    "review_changed_file",
    "update_credential_inventory",
    "update_file_relationships",
    "update_vault_summary",
    "mark_unsupported_understood",
    "mark_failed_understood",
    "followup_credential_question",
    "backfill_memory_on_demand",
)


_TASK_STATUSES = (
    "pending",
    "processing",
    "succeeded",
    "failed",
    "cancelled",
)


_AUDIT_ACTIONS = (
    "tool_call",
    "memory_write",
    "memory_update",
    "memory_delete",
    "task_claim",
    "task_complete",
    "task_fail",
    "task_cancel",
    "file_reviewed",
    "credential_revealed",
)


_TOOL_NAMES = (
    "list_vault_files",
    "read_file_text",
    "read_file_chunks",
    "search_vault",
    "list_credentials",
    "read_credential_record_metadata",
    "get_vault_coverage",
    "get_pending_failed_unsupported",
    "write_vault_memory_note",
    "update_file_tags",
    "link_related_files",
    "mark_file_reviewed",
    "create_user_task_or_reminder",
    "reveal_credential",
)


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
                                                                     
                                                                    
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS vault_agent_memories (
            memory_id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id                        UUID NOT NULL REFERENCES vaults(vault_id)
                                                 ON DELETE CASCADE,
            -- file_id is nullable: vault-level observations
            -- (e.g. "vault has 3 credential files") have no
            -- single owning file.
            file_id                         TEXT NULL REFERENCES uploaded_files(id)
                                                 ON DELETE CASCADE,

            memory_type                     TEXT NOT NULL,
            source_stage                    TEXT NOT NULL,

            -- Confidence in the memory's accuracy [0.0, 1.0]. The
            -- writer sets this; the planner reads it.
            confidence                      REAL NOT NULL DEFAULT 0.5,

            -- AES-GCM-256-encrypted payload. The plaintext NEVER hits
            -- the schema. The writer encrypts with the per-vault key
            -- (same key used by vault_content_chunks /
            -- uploaded_files.encrypted_file_data).
            encrypted_title                 TEXT NOT NULL,
            encrypted_summary               TEXT NOT NULL,
            encrypted_entities              TEXT NOT NULL,
            encrypted_sensitive_record_refs TEXT NOT NULL,
            encrypted_relationship_refs     TEXT NOT NULL,
            payload_encrypted               BOOLEAN NOT NULL DEFAULT TRUE,

            -- Redacted, secrets-stripped searchable summary. Safe
            -- to read at rest and safe to embed. The Python writer
            -- enforces redaction (no passwords / tokens / PINs);
            -- this column is intentionally NOT marked encrypted so
            -- retrieval can substring-match on it without unlocking.
            redacted_searchable_summary     TEXT NULL,

            -- pgvector embedding over the redacted summary. NULL
            -- until the writer fills it. NEVER embedded over the
            -- raw payload.
            embedding                       vector({_EMBEDDING_DIM}),
            embedding_model                 TEXT,
            embedding_dim                   INTEGER,
            embedded_at                     TIMESTAMPTZ,

            created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_verified_at                TIMESTAMPTZ,

            -- Closed-set CHECK constraints. A future invalid value
            -- is refused at INSERT time — no silent typo'd rows.
            CONSTRAINT vault_agent_memories_memory_type_chk
                CHECK ({_enum_check("memory_type", _MEMORY_TYPES)}),
            CONSTRAINT vault_agent_memories_source_stage_chk
                CHECK ({_enum_check("source_stage", _SOURCE_STAGES)}),

            CONSTRAINT vault_agent_memories_confidence_range_chk
                CHECK (confidence >= 0.0 AND confidence <= 1.0),

            -- Refuse any future caller that tries to flip
            -- payload_encrypted to FALSE. This is the wall against
            -- accidental plaintext-at-rest.
            CONSTRAINT vault_agent_memories_payload_encrypted_chk
                CHECK (payload_encrypted = TRUE)
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_memories_vault_idx "
        "ON vault_agent_memories (vault_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_memories_vault_file_idx "
        "ON vault_agent_memories (vault_id, file_id) "
        "WHERE file_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_memories_vault_type_idx "
        "ON vault_agent_memories (vault_id, memory_type)"
    )
                                                                 
                                                               
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "vault_agent_memories_idempotent_idx "
        "ON vault_agent_memories (vault_id, file_id, memory_type) "
        "WHERE file_id IS NOT NULL"
    )

                                                                     
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS vault_agent_tasks (
            task_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id           UUID NOT NULL REFERENCES vaults(vault_id)
                                    ON DELETE CASCADE,
            file_id            TEXT NULL REFERENCES uploaded_files(id)
                                    ON DELETE CASCADE,

            task_type          TEXT NOT NULL,
            status             TEXT NOT NULL DEFAULT 'pending',

            -- Lower = higher priority. Lets a future urgent
            -- "user just asked, review this file now" enqueue ahead
            -- of routine background reviews.
            priority           INTEGER NOT NULL DEFAULT 100,

            attempts           INTEGER NOT NULL DEFAULT 0,
            max_attempts       INTEGER NOT NULL DEFAULT 3,

            -- Free-text failure reason (closed-set will be added in a
            -- later slice once the failure taxonomy stabilises).
            failure_reason     TEXT,

            -- Last error metadata: classname + safe message only. The
            -- daemon MUST NOT write raw payload here.
            last_error         TEXT,

            -- Lease columns (same shape as vault_analysis_jobs).
            locked_at          TIMESTAMPTZ,
            locked_by          TEXT,
            scheduled_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at         TIMESTAMPTZ,
            completed_at       TIMESTAMPTZ,

            -- Safe-only metadata (no secrets). Caller redacts before
            -- write.
            metadata_jsonb     JSONB NOT NULL DEFAULT '{{}}'::jsonb,

            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT vault_agent_tasks_task_type_chk
                CHECK ({_enum_check("task_type", _TASK_TYPES)}),
            CONSTRAINT vault_agent_tasks_status_chk
                CHECK ({_enum_check("status", _TASK_STATUSES)}),
            CONSTRAINT vault_agent_tasks_attempts_nonneg_chk
                CHECK (attempts >= 0 AND attempts <= max_attempts),
            CONSTRAINT vault_agent_tasks_priority_nonneg_chk
                CHECK (priority >= 0)
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_tasks_vault_idx "
        "ON vault_agent_tasks (vault_id)"
    )
                                                               
                                     
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_tasks_claim_idx "
        "ON vault_agent_tasks (status, priority, scheduled_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_tasks_vault_file_idx "
        "ON vault_agent_tasks (vault_id, file_id) "
        "WHERE file_id IS NOT NULL"
    )
                                                                
                                                                   
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "vault_agent_tasks_active_idempotent_idx "
        "ON vault_agent_tasks (vault_id, file_id, task_type) "
        "WHERE status IN ('pending', 'processing') "
        "AND file_id IS NOT NULL"
    )

                                                                     
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS vault_agent_audit (
            audit_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id            UUID NOT NULL REFERENCES vaults(vault_id)
                                     ON DELETE CASCADE,
            file_id             TEXT NULL REFERENCES uploaded_files(id)
                                     ON DELETE CASCADE,

            action              TEXT NOT NULL,
            tool_name           TEXT NULL,

            -- Safe-only metadata. The audit helper redacts at write
            -- time. NEVER includes raw passwords / tokens / PINs /
            -- decrypted summaries / vault keys.
            safe_metadata_jsonb JSONB NOT NULL DEFAULT '{{}}'::jsonb,

            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT vault_agent_audit_action_chk
                CHECK ({_enum_check("action", _AUDIT_ACTIONS)}),
            -- tool_name is closed-set when present; NULL allowed.
            CONSTRAINT vault_agent_audit_tool_name_chk
                CHECK (
                    tool_name IS NULL
                    OR {_enum_check("tool_name", _TOOL_NAMES)}
                ),
            -- A tool_call action MUST name a tool. A non-tool_call
            -- action MUST NOT name one. Refuses caller drift.
            CONSTRAINT vault_agent_audit_tool_name_action_match_chk
                CHECK (
                    (action = 'tool_call' AND tool_name IS NOT NULL)
                    OR (action <> 'tool_call' AND tool_name IS NULL)
                )
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_audit_vault_created_idx "
        "ON vault_agent_audit (vault_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_audit_vault_file_idx "
        "ON vault_agent_audit (vault_id, file_id) "
        "WHERE file_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_audit_action_idx "
        "ON vault_agent_audit (action)"
    )


def downgrade() -> None:
                                                                     
                         
    op.execute("DROP TABLE IF EXISTS vault_agent_audit")
    op.execute("DROP TABLE IF EXISTS vault_agent_tasks")
    op.execute("DROP TABLE IF EXISTS vault_agent_memories")
