"""Add shared opaque-envelope and item migration journal tables.

This is additive infrastructure.  It does not backfill or mutate any existing
vault-domain table, and the application feature flags default to off.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0036_zk_v2_migration_foundation"
down_revision: Union[str, None] = "0035_mainnet_draft_lookup_hash"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_crypto_envelopes (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id                 UUID NOT NULL REFERENCES vaults(vault_id)
                                      ON DELETE CASCADE,
            record_domain            TEXT NOT NULL,
            record_id                TEXT NOT NULL,
            crypto_version           TEXT NOT NULL,
            cipher_suite             TEXT NOT NULL,
            key_domain               TEXT NOT NULL,
            nonce_b64                TEXT NOT NULL,
            ciphertext_b64           TEXT NOT NULL,
            authentication_tag_b64   TEXT NOT NULL,
            blind_indexes            JSONB NOT NULL DEFAULT '{}'::jsonb,
            migration_state          TEXT NOT NULL,
            verification_state       TEXT NOT NULL,
            migrated_at              TIMESTAMPTZ,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT vault_crypto_envelopes_version_ck
              CHECK (crypto_version = 'client_mvk_v2'),
            CONSTRAINT vault_crypto_envelopes_suite_ck
              CHECK (cipher_suite = 'xchacha20_poly1305_ietf_v1'),
            CONSTRAINT vault_crypto_envelopes_domain_ck
              CHECK (record_domain IN
                ('file','credential','memory','secure_note','wallet_record',
                 'inheritance_record')),
            CONSTRAINT vault_crypto_envelopes_migration_state_ck
              CHECK (migration_state IN
                ('migration_pending','v2_written','v2_verified','migrated',
                 'migration_failed','verification_failed','rollback_pending',
                 'rolled_back')),
            CONSTRAINT vault_crypto_envelopes_verification_state_ck
              CHECK (verification_state IN
                ('not_verified','client_verified','verification_failed')),
            CONSTRAINT vault_crypto_envelopes_record_uq
              UNIQUE (vault_id, record_domain, record_id, crypto_version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_crypto_migration_journal (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            operation_id          UUID NOT NULL,
            vault_id              UUID NOT NULL REFERENCES vaults(vault_id)
                                   ON DELETE CASCADE,
            record_domain         TEXT NOT NULL,
            record_id             TEXT NOT NULL,
            source_version        TEXT NOT NULL,
            target_version        TEXT NOT NULL,
            migration_state       TEXT NOT NULL,
            verification_state    TEXT NOT NULL,
            error_category        TEXT,
            attempt               INTEGER NOT NULL DEFAULT 1,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT vault_crypto_journal_versions_ck
              CHECK (source_version = 'legacy_v1'
                     AND target_version = 'client_mvk_v2'),
            CONSTRAINT vault_crypto_journal_attempt_ck CHECK (attempt > 0),
            CONSTRAINT vault_crypto_journal_operation_uq
              UNIQUE (vault_id, record_domain, record_id, operation_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_vault_crypto_journal_resume
          ON vault_crypto_migration_journal
             (vault_id, migration_state, updated_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_vault_crypto_journal_resume")
    op.execute("DROP TABLE IF EXISTS vault_crypto_migration_journal")
    op.execute("DROP TABLE IF EXISTS vault_crypto_envelopes")
