"""Add encrypted Mainnet draft sender lookup hash.

Ciphertext-first Mainnet drafts already receive a vault-scoped
sender lookup hash from the client. The column was missing on the
draft table, so duplicate-draft checks could only fall back to
vault/network scope. This migration stores that opaque 32-byte value
on draft rows without adding plaintext wallet addresses.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0035_mainnet_draft_lookup_hash"
down_revision: Union[str, None] = "0034_inheritance_reencryption_state"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE crypto_mainnet_drafts
          ADD COLUMN IF NOT EXISTS sender_address_lookup_hash BYTEA
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conname = 'crypto_mainnet_drafts_lookup_hash_len_check'
          ) THEN
            ALTER TABLE crypto_mainnet_drafts
              ADD CONSTRAINT crypto_mainnet_drafts_lookup_hash_len_check
                CHECK (sender_address_lookup_hash IS NULL
                       OR octet_length(sender_address_lookup_hash) = 32);
          END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crypto_mainnet_drafts_lookup_active
          ON crypto_mainnet_drafts
             (network_id, vault_id, sender_address_lookup_hash,
              consumed_at, expires_at)
          WHERE sender_address_lookup_hash IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS ix_crypto_mainnet_drafts_lookup_active
        """
    )
    op.execute(
        """
        ALTER TABLE crypto_mainnet_drafts
          DROP CONSTRAINT IF EXISTS
            crypto_mainnet_drafts_lookup_hash_len_check
        """
    )
    op.execute(
        """
        ALTER TABLE crypto_mainnet_drafts
          DROP COLUMN IF EXISTS sender_address_lookup_hash
        """
    )
