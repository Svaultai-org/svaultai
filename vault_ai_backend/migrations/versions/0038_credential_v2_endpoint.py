"""Add soft deletion and credential-v2 lookup indexes to opaque envelopes."""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0038_credential_v2_endpoint"
down_revision: Union[str, None] = "0037_zk_v2_reversible_state"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vault_crypto_envelopes
          ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        ALTER TABLE vault_crypto_envelopes
          DROP CONSTRAINT IF EXISTS vault_crypto_envelopes_suite_ck
        """
    )
    op.execute(
        """
        ALTER TABLE vault_crypto_envelopes
          ADD CONSTRAINT vault_crypto_envelopes_suite_ck
          CHECK (cipher_suite IN
            ('aes_256_gcm_v1', 'xchacha20_poly1305_ietf_v1'))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_vault_crypto_credential_active
          ON vault_crypto_envelopes (vault_id, record_id)
          WHERE record_domain = 'credential' AND deleted_at IS NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_vault_crypto_credential_blind_indexes
          ON vault_crypto_envelopes USING GIN (blind_indexes)
          WHERE record_domain = 'credential' AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_vault_crypto_credential_blind_indexes")
    op.execute("DROP INDEX IF EXISTS ix_vault_crypto_credential_active")
    op.execute(
        """
        ALTER TABLE vault_crypto_envelopes
          DROP CONSTRAINT IF EXISTS vault_crypto_envelopes_suite_ck
        """
    )
    op.execute(
        """
        ALTER TABLE vault_crypto_envelopes
          ADD CONSTRAINT vault_crypto_envelopes_suite_ck
          CHECK (cipher_suite = 'xchacha20_poly1305_ietf_v1')
        """
    )
    op.execute(
        """
        ALTER TABLE vault_crypto_envelopes DROP COLUMN IF EXISTS deleted_at
        """
    )
