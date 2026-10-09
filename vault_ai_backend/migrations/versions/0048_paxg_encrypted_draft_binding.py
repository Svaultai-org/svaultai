"""Bind new PAXG ciphertext drafts without persisting public transaction fields.

Revision ID: 0048
Revises: 0047
"""

from alembic import op

revision = "0048_paxg_encrypted_draft_binding"
down_revision = "0047_concierge_exposure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE crypto_mainnet_drafts ADD COLUMN paxg_intent_commitment BYTEA")
    op.execute("""
        ALTER TABLE crypto_mainnet_drafts
          ADD CONSTRAINT crypto_mainnet_drafts_paxg_intent_check CHECK (
            paxg_intent_commitment IS NULL OR (
                octet_length(paxg_intent_commitment) = 32
                AND draft_payload_ciphertext IS NOT NULL
                AND sender_address_lookup_hash IS NOT NULL
                AND sender_address_lower IS NULL AND asset IS NULL
                AND destination_address IS NULL AND value_wei_str IS NULL
                AND data_hex IS NULL AND transaction_to IS NULL
                AND network_id = 'ethereum_mainnet' AND chain_id = 1
            )
          )
    """)


def downgrade() -> None:
    # No encrypted draft or vault data is deleted. Bound drafts become legacy
    # unbound ciphertext drafts and must be re-reviewed, never guessed/replayed.
    op.execute("ALTER TABLE crypto_mainnet_drafts DROP CONSTRAINT crypto_mainnet_drafts_paxg_intent_check")
    op.execute("ALTER TABLE crypto_mainnet_drafts DROP COLUMN paxg_intent_commitment")
