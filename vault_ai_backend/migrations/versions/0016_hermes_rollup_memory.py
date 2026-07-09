

from typing import Union

from alembic import op


revision: str = "0016_hermes_rollup_memory"
down_revision: Union[str, None] = "0015_hermes_resident_facets"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_ROLLUP_KINDS = (
    "vault_overview",
    "credential_inventory_summary",
    "sensitive_records_summary",
    "pending_failed_unsupported_summary",
    "file_kind_summary",
    "expiry_summary",
    "recently_changed_summary",
)


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD COLUMN IF NOT EXISTS rollup_kind TEXT NULL"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP CONSTRAINT IF EXISTS "
        "vault_agent_memories_rollup_kind_chk"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "ADD CONSTRAINT vault_agent_memories_rollup_kind_chk "
        f"CHECK (rollup_kind IS NULL OR "
        f"{_enum_check('rollup_kind', _ROLLUP_KINDS)})"
    )
                                                            
                                                            
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "vault_agent_memories_vault_rollup_idx "
        "ON vault_agent_memories (vault_id, rollup_kind) "
        "WHERE file_id IS NULL AND rollup_kind IS NOT NULL"
    )

                                                               
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "vault_agent_tasks_vault_level_active_idx "
        "ON vault_agent_tasks (vault_id, task_type) "
        "WHERE status IN ('pending', 'processing') "
        "AND file_id IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS "
        "vault_agent_tasks_vault_level_active_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS "
        "vault_agent_memories_vault_rollup_idx"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP CONSTRAINT IF EXISTS "
        "vault_agent_memories_rollup_kind_chk"
    )
    op.execute(
        "ALTER TABLE vault_agent_memories "
        "DROP COLUMN IF EXISTS rollup_kind"
    )
