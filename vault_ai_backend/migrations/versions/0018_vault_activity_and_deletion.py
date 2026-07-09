"""Add activity-tracking timestamps to vaults + deletion tombstones.

- vaults.last_login_at, vaults.last_vault_unlock_at,
  vaults.last_any_activity_at (all nullable TIMESTAMPTZ)
- Backfill last_any_activity_at = COALESCE(updated_at, created_at)
  so existing vaults have a baseline for the 6-month inactivity check.
- vault_deletion_tombstones: safe audit record for auto-deletions
  and user-requested deletions. Stores only:
    * deleted_at
    * deletion_reason (closed-set)
    * hashed_vault_id (SHA-256 hex — anonymized)
  No vault name, no account id, no file/item names, no wallet
  addresses, no encrypted secrets.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0018_vault_activity_and_deletion"
down_revision: Union[str, None] = "0017_vault_intelligence_summary"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_DELETION_REASONS = (
    "user_requested",
    "unpaid_inactive_6_months",
)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vaults
            ADD COLUMN IF NOT EXISTS last_login_at         TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_vault_unlock_at  TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS last_any_activity_at  TIMESTAMPTZ
        """
    )

    op.execute(
        """
        UPDATE vaults
        SET last_any_activity_at =
            COALESCE(last_any_activity_at, updated_at, created_at)
        WHERE last_any_activity_at IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS vaults_last_any_activity_at_idx
            ON vaults (last_any_activity_at)
        """
    )

    reasons_sql = ",".join("'" + r + "'" for r in _DELETION_REASONS)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS vault_deletion_tombstones (
            id                BIGSERIAL   PRIMARY KEY,
            deleted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deletion_reason   TEXT        NOT NULL
                CHECK (deletion_reason IN ({reasons_sql})),
            hashed_vault_id   TEXT        NOT NULL
                CHECK (length(hashed_vault_id) BETWEEN 32 AND 128)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS vault_deletion_tombstones_reason_idx
            ON vault_deletion_tombstones (deletion_reason, deleted_at DESC)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS vault_deletion_tombstones_reason_idx"
    )
    op.execute("DROP TABLE IF EXISTS vault_deletion_tombstones")

    op.execute(
        "DROP INDEX IF EXISTS vaults_last_any_activity_at_idx"
    )
    op.execute(
        """
        ALTER TABLE vaults
            DROP COLUMN IF EXISTS last_any_activity_at,
            DROP COLUMN IF EXISTS last_vault_unlock_at,
            DROP COLUMN IF EXISTS last_login_at
        """
    )
