"""Shared-state tables for TRON Mainnet send safety.

2026-07-14 (Round 6 hardening): mirrors 0020 (ETH Mainnet) and 0021
(Solana Mainnet). TRON-specific fields — raw_data_hex, expiration,
fee_limit_sun, txID — instead of nonce/gas or blockhash/lamports.

Draft state machine identical to the ETH/SOL pattern:
    ACTIVE → CLAIMED → CONSUMED (outcome pending) → CONSUMED (terminal)

The `local_txid_hex` stamped at consume-time is the SHA-256 of
raw_data — TRON's canonical transaction identity (the same hex the
network returns in `tron_get_transaction_info`).

Fail-closed defaults mirror ETH/SOL:
  * Missing pause row → PAUSED
  * DB read error → PAUSED
  * Migration seeds `paused=true`
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0022_crypto_tron_control"
down_revision: Union[str, None] = "0021_crypto_solana_control"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_tron_drafts (
            draft_id                TEXT PRIMARY KEY,
            vault_id                TEXT NOT NULL,
            network_id              TEXT NOT NULL,
            sender_address          TEXT NOT NULL,
            asset                   TEXT NOT NULL,
            destination_address     TEXT NOT NULL,
            token_contract_address  TEXT NOT NULL,
            amount_base_units_str   TEXT NOT NULL,
            fee_limit_sun_str       TEXT NOT NULL,
            raw_data_hex            TEXT NOT NULL,
            expiration_ms           BIGINT NOT NULL,
            server_txid_hex         TEXT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at              TIMESTAMPTZ NOT NULL,
            claim_token             TEXT,
            claim_expires_at        TIMESTAMPTZ,
            consumed_at             TIMESTAMPTZ,
            local_txid_hex          TEXT,
            broadcast_outcome       TEXT,
            outcome_recorded_at     TIMESTAMPTZ,
            CONSTRAINT crypto_tron_drafts_claim_pair_check CHECK (
                (claim_token IS NULL AND claim_expires_at IS NULL)
             OR (claim_token IS NOT NULL AND claim_expires_at IS NOT NULL)
            ),
            CONSTRAINT crypto_tron_drafts_terminal_check CHECK (
                consumed_at IS NULL OR local_txid_hex IS NOT NULL
            ),
            CONSTRAINT crypto_tron_drafts_outcome_value_check CHECK (
                broadcast_outcome IS NULL
                OR broadcast_outcome IN (
                    'submitted',
                    'submission_uncertain',
                    'already_known',
                    'explicitly_rejected'
                )
            ),
            CONSTRAINT crypto_tron_drafts_outcome_needs_consume_check CHECK (
                broadcast_outcome IS NULL OR consumed_at IS NOT NULL
            ),
            CONSTRAINT crypto_tron_drafts_outcome_stamp_pair_check CHECK (
                (broadcast_outcome IS NULL AND outcome_recorded_at IS NULL)
             OR (broadcast_outcome IS NOT NULL AND outcome_recorded_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crypto_tron_drafts_active
            ON crypto_tron_drafts
            (network_id, sender_address, consumed_at, expires_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crypto_tron_drafts_vault
            ON crypto_tron_drafts (vault_id)
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crypto_tron_wallet_locks (
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
        CREATE TABLE IF NOT EXISTS crypto_tron_control (
            control_key             TEXT PRIMARY KEY,
            value_json              TEXT NOT NULL,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        INSERT INTO crypto_tron_control (control_key, value_json)
        VALUES ('send_paused', '{"paused": true}')
        ON CONFLICT (control_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crypto_tron_control")
    op.execute("DROP TABLE IF EXISTS crypto_tron_wallet_locks")
    op.execute("DROP TABLE IF EXISTS crypto_tron_drafts")
