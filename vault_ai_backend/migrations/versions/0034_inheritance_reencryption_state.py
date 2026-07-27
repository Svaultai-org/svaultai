"""Allow inheritance packages to require owner re-encryption.

When a beneficiary vault must rotate its ZK X25519 key because the old
local key is unrecoverable, existing inheritance credential packages are
still preserved but can no longer be decrypted. This migration adds a
state for that recoverable relationship / stale package condition.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0034_inheritance_reencryption_state"
down_revision: Union[str, None] = "0033_harden_encrypted_memory_plaintext_columns"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_PAIRING_STATES = (
    "paired_no_credentials",
    "credentials_saved",
    "access_requested",
    "cooldown_active",
    "approved",
    "rejected",
    "claimable",
    "released",
    "revoked",
    "needs_reencryption",
)

_CREDENTIAL_STATES = (
    "credentials_saved",
    "access_requested",
    "cooldown_active",
    "approved",
    "rejected",
    "claimable",
    "released",
    "revoked",
    "needs_reencryption",
)


def _quoted(states: tuple[str, ...]) -> str:
    return ",".join(f"'{state}'" for state in states)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE beneficiary_links
          DROP CONSTRAINT IF EXISTS beneficiary_links_pairing_state_ck
        """
    )
    op.execute(
        f"""
        ALTER TABLE beneficiary_links
          ADD CONSTRAINT beneficiary_links_pairing_state_ck
          CHECK (pairing_state IN ({_quoted(_PAIRING_STATES)}))
        """
    )
    op.execute(
        """
        ALTER TABLE inheritance_credentials
          DROP CONSTRAINT IF EXISTS inheritance_credentials_state_ck
        """
    )
    op.execute(
        f"""
        ALTER TABLE inheritance_credentials
          ADD CONSTRAINT inheritance_credentials_state_ck
          CHECK (state IN ({_quoted(_CREDENTIAL_STATES)}))
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE beneficiary_links bl
           SET pairing_state = CASE
                 WHEN EXISTS (
                   SELECT 1
                     FROM inheritance_credentials ic
                    WHERE ic.beneficiary_link_id = bl.id
                      AND ic.deleted_at IS NULL
                 ) THEN 'credentials_saved'
                 ELSE 'paired_no_credentials'
               END
         WHERE pairing_state = 'needs_reencryption'
        """
    )
    op.execute(
        """
        UPDATE inheritance_credentials
           SET state = 'credentials_saved'
         WHERE state = 'needs_reencryption'
        """
    )
    op.execute(
        """
        ALTER TABLE beneficiary_links
          DROP CONSTRAINT IF EXISTS beneficiary_links_pairing_state_ck
        """
    )
    op.execute(
        f"""
        ALTER TABLE beneficiary_links
          ADD CONSTRAINT beneficiary_links_pairing_state_ck
          CHECK (pairing_state IN ({_quoted(_PAIRING_STATES[:-1])}))
        """
    )
    op.execute(
        """
        ALTER TABLE inheritance_credentials
          DROP CONSTRAINT IF EXISTS inheritance_credentials_state_ck
        """
    )
    op.execute(
        f"""
        ALTER TABLE inheritance_credentials
          ADD CONSTRAINT inheritance_credentials_state_ck
          CHECK (state IN ({_quoted(_CREDENTIAL_STATES[:-1])}))
        """
    )
