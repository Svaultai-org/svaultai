"""Add a public owner-MVK readback verifier and beneficiary proof receipt.

The verifier is an Ed25519 public key derived only on client devices from the
owner MVK and exact staged offer. Neither a private signing seed nor the MVK
is stored here. This is additive; it does not retire the old linked protocol.
"""

from alembic import op


revision = "0067_linked_inheritance_readback_proof"
down_revision = "0066_linked_inheritance_beneficiary_keycheck"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE beneficiary_link_v2_upgrades
          ADD COLUMN owner_readback_public_key BYTEA,
          ADD COLUMN owner_readback_revision INTEGER,
          ADD COLUMN owner_readback_commitment VARCHAR(43),
          ADD COLUMN owner_readback_at TIMESTAMPTZ,
          ADD COLUMN beneficiary_readback_challenge_hash BYTEA,
          ADD COLUMN beneficiary_readback_challenge_revision INTEGER,
          ADD COLUMN beneficiary_readback_challenge_expires_at TIMESTAMPTZ,
          ADD COLUMN beneficiary_readback_revision INTEGER,
          ADD COLUMN beneficiary_readback_at TIMESTAMPTZ,
          ADD CONSTRAINT owner_readback_verifier_complete CHECK (
            (owner_readback_public_key IS NULL AND
             owner_readback_revision IS NULL AND
             owner_readback_commitment IS NULL AND
             owner_readback_at IS NULL) OR
            (owner_readback_public_key IS NOT NULL AND
             OCTET_LENGTH(owner_readback_public_key) = 32 AND
             owner_readback_revision IS NOT NULL AND
             owner_readback_revision > 0 AND
             owner_readback_commitment IS NOT NULL AND
             owner_readback_commitment ~ '^[A-Za-z0-9_-]{43}$' AND
             owner_readback_at IS NOT NULL)
          ),
          ADD CONSTRAINT beneficiary_readback_challenge_complete CHECK (
            (beneficiary_readback_challenge_hash IS NULL AND
             beneficiary_readback_challenge_revision IS NULL AND
             beneficiary_readback_challenge_expires_at IS NULL) OR
            (beneficiary_readback_challenge_hash IS NOT NULL AND
             OCTET_LENGTH(beneficiary_readback_challenge_hash) = 32 AND
             beneficiary_readback_challenge_revision IS NOT NULL AND
             beneficiary_readback_challenge_revision > 0 AND
             beneficiary_readback_challenge_expires_at IS NOT NULL)
          ),
          ADD CONSTRAINT beneficiary_readback_receipt_complete CHECK (
            (beneficiary_readback_revision IS NULL AND
             beneficiary_readback_at IS NULL) OR
            (beneficiary_readback_revision IS NOT NULL AND
             beneficiary_readback_revision > 0 AND
             beneficiary_readback_at IS NOT NULL)
          )
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM beneficiary_link_v2_upgrades
             WHERE owner_readback_public_key IS NOT NULL
                OR beneficiary_readback_challenge_hash IS NOT NULL
                OR beneficiary_readback_revision IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'linked_inheritance_readback_proof_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("""
        ALTER TABLE beneficiary_link_v2_upgrades
          DROP CONSTRAINT beneficiary_readback_receipt_complete,
          DROP CONSTRAINT beneficiary_readback_challenge_complete,
          DROP CONSTRAINT owner_readback_verifier_complete,
          DROP COLUMN beneficiary_readback_at,
          DROP COLUMN beneficiary_readback_revision,
          DROP COLUMN beneficiary_readback_challenge_expires_at,
          DROP COLUMN beneficiary_readback_challenge_revision,
          DROP COLUMN beneficiary_readback_challenge_hash,
          DROP COLUMN owner_readback_at,
          DROP COLUMN owner_readback_commitment,
          DROP COLUMN owner_readback_revision,
          DROP COLUMN owner_readback_public_key
    """)
