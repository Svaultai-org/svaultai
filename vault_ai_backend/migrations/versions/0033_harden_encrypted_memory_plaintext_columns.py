"""Harden encrypted vault memory plaintext columns.

Encrypted durable memories are looked up by ``memory_lookup_hash`` and
store their user value only in ``payload_ciphertext``. This forward
migration removes any remaining plaintext duplicate columns from
encrypted rows and drops the old ``event_date`` index so sensitive dates
cannot remain indexed.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0033_harden_encrypted_memory_plaintext_columns"
down_revision: Union[str, None] = "0032_clear_durable_personal_memory_event_date"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS vault_ai_memory_event_date_idx")
    op.execute(
        """
        UPDATE vault_ai_memory
           SET memory_key = NULL,
               memory_value = NULL,
               memory_normalized_key = NULL,
               event_date = NULL
         WHERE payload_ciphertext IS NOT NULL
           AND memory_lookup_hash IS NOT NULL
           AND (
                memory_key IS NOT NULL
             OR memory_value IS NOT NULL
             OR memory_normalized_key IS NOT NULL
             OR event_date IS NOT NULL
           )
        """,
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS vault_ai_memory_event_date_idx
          ON vault_ai_memory(vault_id, event_date)
          WHERE event_date IS NOT NULL AND superseded_at IS NULL
        """,
    )
