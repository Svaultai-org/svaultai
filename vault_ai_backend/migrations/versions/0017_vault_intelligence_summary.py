

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0017_vault_intelligence_summary"
down_revision: Union[str, None] = "0016_hermes_rollup_memory"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_REFRESH_STATUSES = ("idle", "refreshing", "failed", "stale")


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS vault_intelligence_summary (
            vault_id              UUID PRIMARY KEY
                REFERENCES vaults(vault_id) ON DELETE CASCADE,

            schema_version        INTEGER NOT NULL DEFAULT 1,

            -- Plain metadata (no key needed; counts only).
            coverage_jsonb        JSONB,
            file_counts_jsonb     JSONB,
            saved_services_count  INTEGER NOT NULL DEFAULT 0,

            -- Encrypted snapshot payload (AES-GCM via the per-
            -- vault key; written only when the key is available).
            encrypted_snapshot    TEXT,
            snapshot_hash         TEXT,

            -- Refresh tracking.
            last_refreshed_at     TIMESTAMPTZ,
            refresh_status        TEXT NOT NULL DEFAULT 'idle',
            refresh_error_class   TEXT,
            refresh_error_reason  TEXT,

            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT vault_intelligence_refresh_status_chk
                CHECK ({_enum_check("refresh_status", _REFRESH_STATUSES)})
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS vault_intelligence_summary_refresh_idx
            ON vault_intelligence_summary (refresh_status, last_refreshed_at)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS vault_intelligence_summary_refresh_idx"
    )
    op.execute(
        "DROP TABLE IF EXISTS vault_intelligence_summary"
    )
