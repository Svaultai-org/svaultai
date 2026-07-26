"""Clear plaintext event_date from encrypted durable personal memories.

Durable personal memories store their sensitive value inside
``payload_ciphertext`` and find the row with ``memory_lookup_hash``. A
previous implementation also copied birthday dates into ``event_date``,
which is plaintext and indexed. This migration removes that duplicate
plaintext from encrypted personal-memory rows while preserving the
encrypted payload, lookup hash, ownership, and supersession chain.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0032_clear_durable_personal_memory_event_date"
down_revision: Union[str, None] = "0031_vault_name_repurpose"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE vault_ai_memory
           SET event_date = NULL
         WHERE memory_type = 'date'
           AND memory_key IS NULL
           AND memory_value IS NULL
           AND payload_ciphertext IS NOT NULL
           AND memory_lookup_hash IS NOT NULL
           AND event_date IS NOT NULL
        """,
    )


def downgrade() -> None:
    # Intentionally no-op. Restoring plaintext dates would require
    # decrypting user vault payloads and would reintroduce the privacy leak.
    pass
