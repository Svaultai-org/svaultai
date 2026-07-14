"""Zero-knowledge auth state: opaque envelopes, wrapped MVK, encrypted display name.

Adds the columns required for VaultAI's ZK auth redesign:

  * ``vaults.vault_handle``           — opaque 15-byte client-generated
                                        login identifier (base32 display).
                                        UNIQUE index for row lookup.
  * ``vaults.opaque_registration_record`` — bytes of the OPAQUE server
                                        record produced by opaque-ke's
                                        ``ServerRegistration::finish``.
                                        Server-derivable-key-free.
  * ``vaults.wrapped_mvk``            — AES-GCM(KEK, MVK) where KEK is
                                        derived by the client from the
                                        OPAQUE export_key. Server cannot
                                        unwrap.
  * ``vaults.wrapped_sk_vault``       — AES-GCM(KEK, sk_vault_private)
                                        for inheritance (X25519 pk lives
                                        in ``pk_vault_public``).
  * ``vaults.pk_vault_public``        — X25519 public key. Plaintext by
                                        design.
  * ``vaults.display_name_ciphertext`` — AES-GCM(MVK, display_name_utf8).
                                        Replaces plaintext display_username
                                        for ZK-adopted vaults.
  * ``vaults.legacy_vault_name_cleared_at`` — timestamp marking when
                                        the legacy vault_name row was
                                        nulled after ZK adoption. Used
                                        by the drop-plaintext follow-up
                                        migration to confirm 100%
                                        adoption before removing the
                                        column.
  * ``vaults.wrapped_mvk_by_recovery`` — Optional recovery-kit-wrapped
                                        MVK (nullable; only set when
                                        the user opts in).
  * ``vaults.opaque_recovery_record``  — Optional OPAQUE registration
                                        record for the recovery seed
                                        (independent of the PIN OPAQUE).

Additive only — every added column is nullable and every existing
column is untouched. Legacy vaults continue to authenticate via
``vault_name``+``pin_verifier`` until their next successful unlock,
which drives client-side adoption via ``/auth/zk-adopt``.

The old ``vault_name``, ``pin_salt``, ``pin_verifier``, ``kdf_iterations``,
``kdf_algorithm`` columns are NOT dropped here. A follow-up migration
(``0046_vaults_drop_legacy_pin.py``) will drop them once the fleet-
adoption metric confirms zero remaining legacy rows.

No data is destroyed or transformed by this migration. Downgrade
drops the added columns but cannot recover deleted plaintext (which is
the point of the design).
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0023_vault_zk_state"
down_revision: Union[str, None] = "0022_crypto_tron_control"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vaults
          ADD COLUMN IF NOT EXISTS vault_handle                  BYTEA,
          ADD COLUMN IF NOT EXISTS opaque_registration_record    BYTEA,
          ADD COLUMN IF NOT EXISTS wrapped_mvk                   BYTEA,
          ADD COLUMN IF NOT EXISTS wrapped_sk_vault              BYTEA,
          ADD COLUMN IF NOT EXISTS pk_vault_public               BYTEA,
          ADD COLUMN IF NOT EXISTS display_name_ciphertext       BYTEA,
          ADD COLUMN IF NOT EXISTS legacy_vault_name_cleared_at  TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS wrapped_mvk_by_recovery       BYTEA,
          ADD COLUMN IF NOT EXISTS opaque_recovery_record        BYTEA
        """
    )

    op.execute(
        """
        ALTER TABLE vaults
          ADD CONSTRAINT vaults_vault_handle_len_check
            CHECK (vault_handle IS NULL OR octet_length(vault_handle) = 15)
        """
    )

    op.execute(
        """
        ALTER TABLE vaults
          ADD CONSTRAINT vaults_pk_vault_public_len_check
            CHECK (pk_vault_public IS NULL OR octet_length(pk_vault_public) = 32)
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS vaults_vault_handle_uniq
          ON vaults (vault_handle)
          WHERE vault_handle IS NOT NULL
        """
    )

    op.execute(
        """
        ALTER TABLE vaults
          ADD CONSTRAINT vaults_zk_state_consistency_check
            CHECK (
              (vault_handle IS NULL AND opaque_registration_record IS NULL
                AND wrapped_mvk IS NULL)
              OR
              (vault_handle IS NOT NULL AND opaque_registration_record IS NOT NULL
                AND wrapped_mvk IS NOT NULL)
            )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_zk_login_slots (
            slot_id       TEXT        PRIMARY KEY,
            vault_id      UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            server_state  BYTEA       NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at    TIMESTAMPTZ NOT NULL
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS vault_zk_login_slots_expiry_idx
          ON vault_zk_login_slots (expires_at)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS vault_zk_login_slots"
    )

    op.execute(
        "DROP INDEX IF EXISTS vaults_vault_handle_uniq"
    )

    op.execute(
        """
        ALTER TABLE vaults
          DROP CONSTRAINT IF EXISTS vaults_zk_state_consistency_check,
          DROP CONSTRAINT IF EXISTS vaults_pk_vault_public_len_check,
          DROP CONSTRAINT IF EXISTS vaults_vault_handle_len_check
        """
    )

    op.execute(
        """
        ALTER TABLE vaults
          DROP COLUMN IF EXISTS opaque_recovery_record,
          DROP COLUMN IF EXISTS wrapped_mvk_by_recovery,
          DROP COLUMN IF EXISTS legacy_vault_name_cleared_at,
          DROP COLUMN IF EXISTS display_name_ciphertext,
          DROP COLUMN IF EXISTS pk_vault_public,
          DROP COLUMN IF EXISTS wrapped_sk_vault,
          DROP COLUMN IF EXISTS wrapped_mvk,
          DROP COLUMN IF EXISTS opaque_registration_record,
          DROP COLUMN IF EXISTS vault_handle
        """
    )
