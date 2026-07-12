"""Shared-state tables for Ethereum Mainnet send safety.

Adds three Postgres tables so the mainnet send-safety invariants
(draft registry, per-wallet broadcast lock, runtime pause flag) work
across multiple Uvicorn workers and multiple backend containers,
NOT just within one Python process.

Before this migration the state lived in module-level Python dicts /
sets in `routes/crypto_wallet_routes.py`:
  * `_MAINNET_DRAFTS`
  * `_MAINNET_WALLET_INFLIGHT`
  * a filesystem flag at `/opt/vaultai/mainnet_send_paused.flag`

Those are process-local. Two worker processes each have their own
copy, so:
  * Draft issued on worker A + broadcast attempted on worker B →
    worker B reports `unknown_or_expired_draft`.
  * Two concurrent broadcasts landing on different workers both
    acquire the local lock and race at the RPC.
  * The filesystem flag is only visible if the operator remembers
    to bind-mount the flag path into every container.

Postgres is already required by the backend (accounts, wallets,
billing, etc.) so no new hard dependency is introduced.

Tables:

  crypto_mainnet_drafts
      One row per issued mainnet send-draft. Single-active-draft-
      per-sender is enforced by application code inside a Postgres
      SERIALIZABLE-safe advisory-lock section (see
      `crypto_mainnet_control_store.register_draft`). Rows are
      marked `consumed_at` on first broadcast; a background reader
      treats `expires_at <= now()` as no longer valid without a
      manual DELETE.

  crypto_mainnet_wallet_locks
      One row per (network, sender_address_lower) claim, stamped
      with an owner `lock_token`. Owner-safe release means only the
      original acquirer can release the lock. Stale rows (past
      `expires_at`) are treated as if released.

  crypto_mainnet_control
      Key/value scratch used for the runtime pause flag
      (`send_paused`). Any process can flip the pause value; any
      other process sees it on the next request.

Downgrade drops all three tables — no encrypted or sensitive data is
stored in any of them.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0020_crypto_mainnet_control"
down_revision: Union[str, None] = "0019_dev_wipe_deletion_reason"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    # 2026-07-13 pre-mainnet: `broadcast_outcome` + `outcome_recorded_at`
    # + three CHECK constraints added to the SAME migration 0020
    # because 0020 has not been deployed anywhere yet. Editing an
    # unapplied migration in place is simpler than adding a 0021 that
    # alters a brand-new table, and keeps the schema atomic across
    # environments that first come up on this codebase.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_mainnet_drafts (
            draft_id                TEXT PRIMARY KEY,
            vault_id                TEXT NOT NULL,
            network_id              TEXT NOT NULL,
            sender_address_lower    TEXT NOT NULL,
            asset                   TEXT NOT NULL,
            destination_address     TEXT NOT NULL,
            value_wei_str           TEXT NOT NULL,
            data_hex                TEXT NOT NULL,
            nonce                   BIGINT NOT NULL,
            gas_limit               BIGINT NOT NULL,
            gas_price_str           TEXT NOT NULL,
            chain_id                BIGINT NOT NULL,
            transaction_to          TEXT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at              TIMESTAMPTZ NOT NULL,
            claim_token             TEXT,
            claim_expires_at        TIMESTAMPTZ,
            consumed_at             TIMESTAMPTZ,
            local_tx_hash           TEXT,
            broadcast_outcome       TEXT,
            outcome_recorded_at     TIMESTAMPTZ,
            CONSTRAINT crypto_mainnet_drafts_claim_pair_check CHECK (
                (claim_token IS NULL AND claim_expires_at IS NULL)
             OR (claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)
            ),
            CONSTRAINT crypto_mainnet_drafts_terminal_check CHECK (
                consumed_at IS NULL OR local_tx_hash IS NOT NULL
            ),
            CONSTRAINT crypto_mainnet_drafts_outcome_value_check CHECK (
                broadcast_outcome IS NULL
                OR broadcast_outcome IN (
                    'submitted',
                    'submission_uncertain',
                    'already_known',
                    'explicitly_rejected'
                )
            ),
            CONSTRAINT crypto_mainnet_drafts_outcome_needs_consume_check CHECK (
                broadcast_outcome IS NULL OR consumed_at IS NOT NULL
            ),
            CONSTRAINT crypto_mainnet_drafts_outcome_stamp_pair_check CHECK (
                (broadcast_outcome IS NULL AND outcome_recorded_at IS NULL)
             OR (broadcast_outcome IS NOT NULL AND outcome_recorded_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crypto_mainnet_drafts_active
            ON crypto_mainnet_drafts
            (network_id, sender_address_lower, consumed_at, expires_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crypto_mainnet_drafts_vault
            ON crypto_mainnet_drafts (vault_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_mainnet_wallet_locks (
            network_id              TEXT NOT NULL,
            sender_address_lower    TEXT NOT NULL,
            lock_token              TEXT NOT NULL,
            acquired_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at              TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (network_id, sender_address_lower)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_mainnet_control (
            control_key             TEXT PRIMARY KEY,
            value_json              TEXT NOT NULL,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )










    op.execute(
        """
        INSERT INTO crypto_mainnet_control (control_key, value_json)
        VALUES ('send_paused', '{"paused": true}')
        ON CONFLICT (control_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crypto_mainnet_control")
    op.execute("DROP TABLE IF EXISTS crypto_mainnet_wallet_locks")
    op.execute("DROP TABLE IF EXISTS crypto_mainnet_drafts")
