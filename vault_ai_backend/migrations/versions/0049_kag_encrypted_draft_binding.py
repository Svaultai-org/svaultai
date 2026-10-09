"""Add exact KAG ciphertext intent binding, without altering vault contents.

Revision ID: 0049
Revises: 0048
"""
from alembic import op

revision = "0049_kag_encrypted_draft_binding"
down_revision = "0048_paxg_encrypted_draft_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE crypto_mainnet_drafts ADD COLUMN kag_intent_commitment BYTEA")
    op.execute("""
        ALTER TABLE crypto_mainnet_drafts
          ADD CONSTRAINT crypto_mainnet_drafts_kag_intent_check CHECK (
            kag_intent_commitment IS NULL OR (
                octet_length(kag_intent_commitment) = 32
                AND paxg_intent_commitment IS NULL
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
    # Ciphertext and state records survive; KAG drafts become unbound and must
    # be re-reviewed. No account, key, balance or vault item is deleted.
    op.execute("ALTER TABLE crypto_mainnet_drafts DROP CONSTRAINT crypto_mainnet_drafts_kag_intent_check")
    op.execute("ALTER TABLE crypto_mainnet_drafts DROP COLUMN kag_intent_commitment")
