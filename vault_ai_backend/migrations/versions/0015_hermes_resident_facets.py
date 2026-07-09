

from typing import Union

from alembic import op


revision: str = "0015_hermes_resident_facets"
down_revision: Union[str, None] = "0014_hermes_resident_agent"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_RESIDENT_REVIEW_STATUS_VALUES = (
    "not_reviewed",
    "reviewing",
    "reviewed",
    "failed",
    "unsupported",
)


_SENSITIVITY_LEVELS = (
    "low",
    "medium",
    "high",
)


_FILE_KINDS = (
    "credential_sheet",
    "identity_document",
    "financial_record",
    "tax_document",
    "lease_or_contract",
    "insurance",
    "medical",
    "travel_document",
    "receipt_or_invoice",
    "personal_note",
    "photo_or_scan",
    "code_or_config",
    "archive",
    "unknown",
)


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
                                                               
                                                           
    op.execute("SET LOCAL statement_timeout = 0")

                                                                     
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD COLUMN IF NOT EXISTS has_credential_records "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD COLUMN IF NOT EXISTS credential_record_count "
        "INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD COLUMN IF NOT EXISTS sensitivity_level TEXT NULL"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD COLUMN IF NOT EXISTS file_kind TEXT NULL"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD COLUMN IF NOT EXISTS has_expiry_date "
        "BOOLEAN NOT NULL DEFAULT FALSE"
    )

                                                                 
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP CONSTRAINT IF EXISTS "
        "vault_agent_memories_sensitivity_level_chk"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD CONSTRAINT vault_agent_memories_sensitivity_level_chk "
        f"CHECK (sensitivity_level IS NULL OR "
        f"{_enum_check('sensitivity_level', _SENSITIVITY_LEVELS)})"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP CONSTRAINT IF EXISTS "
        "vault_agent_memories_file_kind_chk"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD CONSTRAINT vault_agent_memories_file_kind_chk "
        f"CHECK (file_kind IS NULL OR "
        f"{_enum_check('file_kind', _FILE_KINDS)})"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP CONSTRAINT IF EXISTS "
        "vault_agent_memories_credential_record_count_chk"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD CONSTRAINT vault_agent_memories_credential_record_count_chk "
        "CHECK (credential_record_count >= 0)"
    )

                                  
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_memories_credential_files_idx "
        "ON vault_agent_memories (vault_id) "
        "WHERE has_credential_records = TRUE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_agent_memories_vault_file_kind_idx "
        "ON vault_agent_memories (vault_id, file_kind) "
        "WHERE file_kind IS NOT NULL"
    )

                                                                     
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS resident_review_status TEXT"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ALTER COLUMN resident_review_status SET DEFAULT 'not_reviewed'"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS "
        "uploaded_files_resident_review_status_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD CONSTRAINT uploaded_files_resident_review_status_chk "
        f"CHECK (resident_review_status IS NULL OR "
        f"{_enum_check('resident_review_status', _RESIDENT_REVIEW_STATUS_VALUES)})"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "ADD COLUMN IF NOT EXISTS resident_reviewed_at TIMESTAMPTZ NULL"
    )

                                                              
def downgrade() -> None:
                                                          
                                                           
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP CONSTRAINT IF EXISTS "
        "uploaded_files_resident_review_status_chk"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS resident_reviewed_at"
    )
    op.execute(
        "ALTER TABLE uploaded_files "
        "DROP COLUMN IF EXISTS resident_review_status"
    )
    op.execute(
        "DROP INDEX IF EXISTS "
        "vault_agent_memories_vault_file_kind_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS "
        "vault_agent_memories_credential_files_idx"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP CONSTRAINT IF EXISTS "
        "vault_agent_memories_credential_record_count_chk"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP CONSTRAINT IF EXISTS "
        "vault_agent_memories_file_kind_chk"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP CONSTRAINT IF EXISTS "
        "vault_agent_memories_sensitivity_level_chk"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP COLUMN IF EXISTS has_expiry_date"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP COLUMN IF EXISTS file_kind"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP COLUMN IF EXISTS sensitivity_level"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP COLUMN IF EXISTS credential_record_count"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP COLUMN IF EXISTS has_credential_records"
    )
