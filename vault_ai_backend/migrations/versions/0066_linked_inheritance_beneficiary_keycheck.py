"""Record a beneficiary's private-key possession for an unchanged old link.

The challenge contains only random bytes, never the staged owner MVK. A
successful check is bound to one stage revision. It is not a package decrypt
receipt or permission to release or switch the legacy link.
"""

from alembic import op


revision = "0066_linked_inheritance_beneficiary_keycheck"
down_revision = "0065_linked_inheritance_v2_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE beneficiary_link_v2_upgrades
          ADD COLUMN beneficiary_challenge_hash BYTEA,
          ADD COLUMN beneficiary_challenge_revision INTEGER,
          ADD COLUMN beneficiary_challenge_expires_at TIMESTAMPTZ,
          ADD COLUMN beneficiary_keycheck_revision INTEGER,
          ADD COLUMN beneficiary_keycheck_at TIMESTAMPTZ,
          ADD CONSTRAINT beneficiary_challenge_complete CHECK (
            (beneficiary_challenge_hash IS NULL AND
             beneficiary_challenge_revision IS NULL AND
             beneficiary_challenge_expires_at IS NULL) OR
            (beneficiary_challenge_hash IS NOT NULL AND
             OCTET_LENGTH(beneficiary_challenge_hash) = 32 AND
             beneficiary_challenge_revision IS NOT NULL AND
             beneficiary_challenge_revision > 0 AND
             beneficiary_challenge_expires_at IS NOT NULL)
          ),
          ADD CONSTRAINT beneficiary_keycheck_complete CHECK (
            (beneficiary_keycheck_revision IS NULL AND
             beneficiary_keycheck_at IS NULL) OR
            (beneficiary_keycheck_revision IS NOT NULL AND
             beneficiary_keycheck_revision > 0 AND
             beneficiary_keycheck_at IS NOT NULL)
          )
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM beneficiary_link_v2_upgrades
             WHERE beneficiary_challenge_hash IS NOT NULL
                OR beneficiary_keycheck_revision IS NOT NULL
          ) THEN
            RAISE EXCEPTION 'linked_inheritance_keycheck_cannot_be_dropped';
          END IF;
        END $$
    """)
    op.execute("""
        ALTER TABLE beneficiary_link_v2_upgrades
          DROP CONSTRAINT beneficiary_keycheck_complete,
          DROP CONSTRAINT beneficiary_challenge_complete,
          DROP COLUMN beneficiary_keycheck_at,
          DROP COLUMN beneficiary_keycheck_revision,
          DROP COLUMN beneficiary_challenge_expires_at,
          DROP COLUMN beneficiary_challenge_revision,
          DROP COLUMN beneficiary_challenge_hash
    """)
