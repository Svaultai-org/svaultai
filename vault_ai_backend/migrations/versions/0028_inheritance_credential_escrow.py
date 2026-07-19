"""Inheritance credential escrow — additive schema.

Purpose
=======

Phase 1 of the inheritance redesign. Backs the owner's ability to
store an encrypted VaultAI username + PIN for a paired beneficiary
so the beneficiary can later inherit login access to the same
account (never a copy of the vault).

This migration is **additive only** — it does not touch any existing
row and does not remove any existing column, so the current
request / approve / cooldown flow keeps working unchanged.

What this migration adds
------------------------

1. Table ``inheritance_credentials`` — one active encrypted credential
   package per beneficiary link. Enforced by a UNIQUE partial index
   (WHERE ``deleted_at IS NULL``).

2. Columns on ``beneficiary_links``:
     * ``pairing_state``      TEXT NOT NULL DEFAULT 'paired_no_credentials'
     * ``access_requested_at`` TIMESTAMPTZ  — Phase 2 will populate
     * ``cooldown_ends_at``    TIMESTAMPTZ  — Phase 2 will populate
     * ``decision_at``         TIMESTAMPTZ  — Phase 2 will populate

   ``pairing_state`` is the operator-visible state field for the new
   flow. Its default matches the wire-format contract for links that
   were pairing before this migration ran: those rows have no
   credential package saved yet, so ``paired_no_credentials`` is the
   correct baseline. The existing ``status`` column is left intact
   for Phase 2 back-compat and is not renamed.

What this migration does NOT do
-------------------------------

* Does not migrate any historical ``status`` value into the new
  ``pairing_state`` — that projection happens in application code
  in Phase 2 where the release flow lands.
* Does not add the device-enrollment authorization table — that
  lands in Phase 2 next to the release endpoints that consume it.
* Does not add plaintext columns for username or PIN. The only
  credential material the server ever sees is opaque bytes.

Rollback safety
---------------

``downgrade()`` drops the additions in reverse order. Because the
new columns are all nullable except the state column (which has a
default), the downgrade path is a straight structural undo.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0028_inheritance_credential_escrow"
down_revision: Union[str, None] = "0027_restore_inheritance_keep_recovery_removed"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_ALLOWED_PAIRING_STATES = (
    "paired_no_credentials",
    "credentials_saved",
    # Phase 2 will use these; declared now so the CHECK constraint
    # does not need to be rewritten in the next migration.
    "access_requested",
    "cooldown_active",
    "approved",
    "rejected",
    "claimable",
    "released",
    "revoked",
)


def upgrade() -> None:
    # ---- beneficiary_links: additive state columns ----------------
    op.execute(
        """
        ALTER TABLE beneficiary_links
          ADD COLUMN IF NOT EXISTS pairing_state       TEXT NOT NULL
              DEFAULT 'paired_no_credentials',
          ADD COLUMN IF NOT EXISTS access_requested_at TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS cooldown_ends_at    TIMESTAMPTZ,
          ADD COLUMN IF NOT EXISTS decision_at         TIMESTAMPTZ
        """
    )

    # CHECK constraint on the state column. Added separately so the
    # column addition above stays IF-NOT-EXISTS safe when the whole
    # migration is retried in a partial state.
    states_sql = ",".join(f"'{s}'" for s in _ALLOWED_PAIRING_STATES)
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'beneficiary_links_pairing_state_ck'
          ) THEN
            ALTER TABLE beneficiary_links
              ADD CONSTRAINT beneficiary_links_pairing_state_ck
              CHECK (pairing_state IN ({states_sql}));
          END IF;
        END$$
        """
    )

    # ---- inheritance_credentials: the encrypted escrow package ----
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inheritance_credentials (
            id                     BIGSERIAL   PRIMARY KEY,
            beneficiary_link_id    BIGINT      NOT NULL
                REFERENCES beneficiary_links(id) ON DELETE CASCADE,
            owner_vault_id         UUID        NOT NULL
                REFERENCES vaults(vault_id)    ON DELETE CASCADE,

            crypto_version         SMALLINT    NOT NULL,
            encrypted_payload      BYTEA       NOT NULL,
            payload_nonce          BYTEA       NOT NULL,
            wrapped_key            BYTEA       NOT NULL,
            wrapping_ephemeral_pk  BYTEA       NOT NULL,
            wrapping_nonce         BYTEA       NOT NULL,

            state                  TEXT        NOT NULL
                DEFAULT 'credentials_saved',

            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            released_at            TIMESTAMPTZ,
            revoked_at             TIMESTAMPTZ,
            deleted_at             TIMESTAMPTZ,

            CONSTRAINT inheritance_credentials_state_ck CHECK (
                state IN (
                    'credentials_saved',
                    'access_requested',
                    'cooldown_active',
                    'approved',
                    'rejected',
                    'claimable',
                    'released',
                    'revoked'
                )
            ),
            CONSTRAINT inheritance_credentials_lengths_ck CHECK (
                length(encrypted_payload) BETWEEN 32 AND 65536
                AND length(payload_nonce)         = 12
                AND length(wrapped_key)   BETWEEN 32 AND 4096
                AND length(wrapping_ephemeral_pk) = 32
                AND length(wrapping_nonce)        = 12
            )
        )
        """
    )

    # One live credential package per link.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            inheritance_credentials_active_link_uq
          ON inheritance_credentials(beneficiary_link_id)
          WHERE deleted_at IS NULL
        """
    )

    # Owner-scoped lookups.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
            inheritance_credentials_owner_idx
          ON inheritance_credentials(owner_vault_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS inheritance_credentials_owner_idx")
    op.execute("DROP INDEX IF EXISTS inheritance_credentials_active_link_uq")
    op.execute("DROP TABLE IF EXISTS inheritance_credentials CASCADE")
    op.execute(
        """
        ALTER TABLE beneficiary_links
          DROP CONSTRAINT IF EXISTS beneficiary_links_pairing_state_ck
        """
    )
    op.execute(
        """
        ALTER TABLE beneficiary_links
          DROP COLUMN IF EXISTS decision_at,
          DROP COLUMN IF EXISTS cooldown_ends_at,
          DROP COLUMN IF EXISTS access_requested_at,
          DROP COLUMN IF EXISTS pairing_state
        """
    )
