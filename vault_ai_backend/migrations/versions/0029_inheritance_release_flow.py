"""Inheritance release flow — Phase 2 additive schema.

Adds the one-time device-enrollment authorization table used by the
beneficiary-side reveal + inherited-login step. Everything the
release state machine itself needs already exists on
``beneficiary_links`` (pairing_state, access_requested_at,
cooldown_ends_at, decision_at) and ``inheritance_credentials``
(state, released_at, revoked_at, deleted_at) from migration 0028.

Authoritative state source
--------------------------

``beneficiary_links.pairing_state`` is the AUTHORITATIVE state for
the release flow. ``inheritance_credentials.state`` is kept in sync
by the endpoints as a denormalized mirror, but every guard read and
every transition writes ``beneficiary_links.pairing_state`` first
under ``SELECT ... FOR UPDATE`` on the link row.

Rationale: the escrow row is soft-deleted on legitimate delete /
revoke paths, so relying on it as the single source of truth would
force every read to also probe ``deleted_at``. The link row exists
for the whole life of the relationship and is the natural spine.

Rollback safety
---------------

Everything added here is a new table + new indexes, no existing
column is altered. The downgrade drops them cleanly.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0029_inheritance_release_flow"
down_revision: Union[str, None] = "0028_inheritance_credential_escrow"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    # ---- inheritance_device_authorizations ------------------------
    # One-time enrollment token that lets a beneficiary's device
    # complete trusted-device enrollment on the INHERITED owner's
    # account without waiting for a second trusted device to approve.
    #
    # Only the SHA-256 hash of the token is stored — the raw bytes
    # never touch the DB. The token is bound to a specific
    # (beneficiary_link, beneficiary_vault, inherited_owner_vault,
    # beneficiary_device_id) tuple; consuming with any mismatch fails.
    #
    # The partial unique index enforces "at most one live token per
    # link at a time" — issuing a new one soft-consumes the previous.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inheritance_device_authorizations (
            id                          BIGSERIAL   PRIMARY KEY,
            beneficiary_link_id         BIGINT      NOT NULL
                REFERENCES beneficiary_links(id) ON DELETE CASCADE,
            beneficiary_vault_id        UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            inherited_owner_vault_id    UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            beneficiary_device_id       TEXT        NOT NULL,

            challenge_hash              BYTEA       NOT NULL,

            issued_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at                  TIMESTAMPTZ NOT NULL,
            consumed_at                 TIMESTAMPTZ,
            revoked_at                  TIMESTAMPTZ,

            CONSTRAINT inheritance_device_auth_hash_ck CHECK (
                length(challenge_hash) = 32
            ),
            CONSTRAINT inheritance_device_auth_device_len_ck CHECK (
                length(beneficiary_device_id) BETWEEN 1 AND 200
            ),
            CONSTRAINT inheritance_device_auth_expiry_ck CHECK (
                expires_at > issued_at
            )
        )
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            inheritance_device_auth_active_uq
          ON inheritance_device_authorizations(beneficiary_link_id)
          WHERE consumed_at IS NULL
            AND revoked_at IS NULL
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
            inheritance_device_auth_hash_idx
          ON inheritance_device_authorizations(challenge_hash)
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
            inheritance_device_auth_beneficiary_idx
          ON inheritance_device_authorizations(beneficiary_vault_id)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS inheritance_device_auth_beneficiary_idx"
    )
    op.execute("DROP INDEX IF EXISTS inheritance_device_auth_hash_idx")
    op.execute("DROP INDEX IF EXISTS inheritance_device_auth_active_uq")
    op.execute(
        "DROP TABLE IF EXISTS inheritance_device_authorizations CASCADE"
    )
