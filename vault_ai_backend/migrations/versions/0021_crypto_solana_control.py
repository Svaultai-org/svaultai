"""Shared-state tables for Solana Mainnet send safety.

2026-07-14 (Round 6 hardening): mirrors the ETH Mainnet pattern
established in migration 0020 (`crypto_mainnet_control`) but with
Solana-specific fields — recent blockhash + last_valid_block_height +
fee lamports — that are meaningless for EVM chains.

Three primitives per network so the safety invariants (draft
registry, per-wallet broadcast lock, runtime pause flag) work
across multi-worker + multi-container deployments and NOT just
inside one Python process:

  crypto_solana_drafts
      One row per issued Solana send-draft. Single-active-draft-per-
      sender is enforced by application code inside a Postgres
      SERIALIZABLE-safe advisory-lock section (see
      `crypto_solana_control_store.register_draft`). Rows are
      marked `consumed_at` on first broadcast; a background reader
      treats `expires_at <= now()` as no longer valid without a
      manual DELETE.

      `local_signature` is stamped at consume-time. Solana
      transaction identity is the first 64 bytes of the signed
      wire form (the primary Ed25519 signature) — the client
      derives it before broadcast so an ambiguous RPC timeout does
      not lose track of what was submitted.

  crypto_solana_wallet_locks
      One row per (network, sender_address) claim, owner-token-
      gated release. Stale rows past `expires_at` are treated as if
      released.

  crypto_solana_control
      Key/value scratch used for the runtime pause flag
      (`send_paused`). Any process can flip the pause value; any
      other process sees it on the next request.

Fail-closed defaults:
  * Missing `send_paused` row → treated as PAUSED by the store's
    is_solana_send_paused().
  * Migration seeds `paused=true` — an operator must explicitly
    call the ops CLI's set_solana_send_paused(False) after canary
    tests before any live Solana send can proceed.

Downgrade drops all three tables — no encrypted or sensitive data
is stored in any of them.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0021_crypto_solana_control"
down_revision: Union[str, None] = "0020_crypto_mainnet_control"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_solana_drafts (
            draft_id                TEXT PRIMARY KEY,
            vault_id                TEXT NOT NULL,
            network_id              TEXT NOT NULL,
            sender_address          TEXT NOT NULL,
            asset                   TEXT NOT NULL,
            destination_address     TEXT NOT NULL,
            value_lamports_str      TEXT NOT NULL,
            fee_lamports_str        TEXT NOT NULL,
            recent_blockhash        TEXT NOT NULL,
            last_valid_block_height BIGINT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at              TIMESTAMPTZ NOT NULL,
            claim_token             TEXT,
            claim_expires_at        TIMESTAMPTZ,
            consumed_at             TIMESTAMPTZ,
            local_signature         TEXT,
            broadcast_outcome       TEXT,
            outcome_recorded_at     TIMESTAMPTZ,
            CONSTRAINT crypto_solana_drafts_claim_pair_check CHECK (
                (claim_token IS NULL AND claim_expires_at IS NULL)
             OR (claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)
            ),
            CONSTRAINT crypto_solana_drafts_terminal_check CHECK (
                consumed_at IS NULL OR local_signature IS NOT NULL
            ),
            CONSTRAINT crypto_solana_drafts_outcome_value_check CHECK (
                broadcast_outcome IS NULL
                OR broadcast_outcome IN (
                    'submitted',
                    'submission_uncertain',
                    'already_known',
                    'explicitly_rejected'
                )
            ),
            CONSTRAINT crypto_solana_drafts_outcome_needs_consume_check CHECK (
                broadcast_outcome IS NULL OR consumed_at IS NOT NULL
            ),
            CONSTRAINT crypto_solana_drafts_outcome_stamp_pair_check CHECK (
                (broadcast_outcome IS NULL AND outcome_recorded_at IS NULL)
             OR (broadcast_outcome IS NOT NULL AND outcome_recorded_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crypto_solana_drafts_active
            ON crypto_solana_drafts
            (network_id, sender_address, consumed_at, expires_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crypto_solana_drafts_vault
            ON crypto_solana_drafts (vault_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_solana_wallet_locks (
            network_id              TEXT NOT NULL,
            sender_address          TEXT NOT NULL,
            lock_token              TEXT NOT NULL,
            acquired_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at              TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (network_id, sender_address)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_solana_control (
            control_key             TEXT PRIMARY KEY,
            value_json              TEXT NOT NULL,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # Seed the pause flag as TRUE (defense-in-depth: any freshly
    # migrated environment starts with Solana send disabled until
    # the operator explicitly unpauses via the ops CLI).
    op.execute(
        """
        INSERT INTO crypto_solana_control (control_key, value_json)
        VALUES ('send_paused', '{"paused": true}')
        ON CONFLICT (control_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crypto_solana_control")
    op.execute("DROP TABLE IF EXISTS crypto_solana_wallet_locks")
    op.execute("DROP TABLE IF EXISTS crypto_solana_drafts")
