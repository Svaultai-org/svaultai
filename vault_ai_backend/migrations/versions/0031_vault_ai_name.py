"""Vault AI name — user-chosen product-facing name for the vault's AI.

Adds a nullable TEXT column so the server can inject a per-vault
AI identity into the LLM prompt WITHOUT ever placing the canonical
username, VLT handle, UUID, or lookup identifier into the identity
slot.

This value is a product-facing label the user picks (e.g. "Nova",
"Atlas"), not a credential and not sensitive in the way the
canonical username is. It is stored plaintext because:

  * The server injects it into the LLM prompt AUTHORITATIVELY on
    every chat request (see main.py::_build_chat_prompt_context).
    Encrypting it would force a client-supplied identity slot,
    which the review explicitly forbade
    ("Treat client-provided AI names as untrusted until validated
    against authenticated vault metadata").
  * The privacy contract from 98c5afd targets the canonical
    username, not the vault-AI product label. The threat model
    for vault_ai_name is public-facing product state.

Column properties:
  * nullable — every existing account starts NULL; the server
    falls back to the neutral "VaultAI" literal, never to any
    identifier / hash / handle
  * length-constrained to 1..60 chars
  * NOT unique — many vaults can name their AI "Nova"

Rollback: DROP COLUMN + DROP CONSTRAINT cleanly.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0031_vault_ai_name"
down_revision: Union[str, None] = "0030_username_blind_index"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vaults
            ADD COLUMN IF NOT EXISTS vault_ai_name TEXT
        """,
    )
    op.execute(
        """
        ALTER TABLE vaults
            ADD CONSTRAINT vaults_vault_ai_name_len_ck CHECK (
                vault_ai_name IS NULL
                OR (length(vault_ai_name) BETWEEN 1 AND 60)
            )
        """,
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE vaults DROP CONSTRAINT IF EXISTS "
        "vaults_vault_ai_name_len_ck",
    )
    op.execute(
        "ALTER TABLE vaults DROP COLUMN IF EXISTS vault_ai_name",
    )
