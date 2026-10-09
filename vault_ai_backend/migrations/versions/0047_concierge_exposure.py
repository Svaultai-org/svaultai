"""Opt-in exposure monitoring and client-encrypted Concierge state only.

No existing vault, authentication, payment or wallet rows are transformed.
"""
from alembic import op

revision = "0047_concierge_exposure"
down_revision = "0046_store_only_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE concierge_client_state (
        vault_id UUID PRIMARY KEY REFERENCES vaults(vault_id) ON DELETE CASCADE,
        ciphertext BYTEA NOT NULL CHECK(octet_length(ciphertext) BETWEEN 29 AND 204800),
        envelope_version TEXT NOT NULL DEFAULT 'v1' CHECK(envelope_version='v1'),
        revision INTEGER NOT NULL CHECK(revision>0),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
      CREATE TABLE concierge_monitors (
        id UUID PRIMARY KEY,
        vault_id UUID NOT NULL REFERENCES vaults(vault_id) ON DELETE CASCADE,
        source_item_id TEXT CHECK(source_item_id IS NULL OR length(source_item_id) BETWEEN 1 AND 128),
        key_id TEXT NOT NULL CHECK(length(key_id) BETWEEN 1 AND 40),
        email_ciphertext BYTEA NOT NULL CHECK(octet_length(email_ciphertext) BETWEEN 29 AND 1024),
        result_ciphertext BYTEA CHECK(octet_length(result_ciphertext) BETWEEN 29 AND 2097152),
        consent_version TEXT NOT NULL,
        email_disclosure_consent BOOLEAN NOT NULL CHECK(email_disclosure_consent),
        stealer_logs BOOLEAN NOT NULL DEFAULT FALSE,
        stealer_disclosure_consent BOOLEAN NOT NULL DEFAULT FALSE,
        background BOOLEAN NOT NULL DEFAULT TRUE,
        status TEXT NOT NULL DEFAULT 'not_checked'
          CHECK(status IN ('not_checked','found','no_known_findings','unavailable')),
        error_code TEXT CHECK(error_code IS NULL OR length(error_code)<=100),
        retry_after_seconds INTEGER CHECK(retry_after_seconds IS NULL OR retry_after_seconds BETWEEN 1 AND 86400),
        attempted_at TIMESTAMPTZ,
        successful_at TIMESTAMPTZ,
        next_check_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        lease_token UUID,
        lease_until TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK(NOT stealer_logs OR stealer_disclosure_consent)
      );
      CREATE INDEX concierge_monitors_vault ON concierge_monitors(vault_id,created_at);
      CREATE INDEX concierge_monitors_due ON concierge_monitors(next_check_at)
        WHERE background=TRUE;
      CREATE TABLE concierge_provider_control (
        provider TEXT PRIMARY KEY CHECK(provider='hibp'),
        next_allowed_at TIMESTAMPTZ NOT NULL DEFAULT (NOW()-INTERVAL '1 day'),
        blocked_until TIMESTAMPTZ NOT NULL DEFAULT (NOW()-INTERVAL '1 day')
      );
      CREATE TABLE concierge_request_budget (
        vault_id UUID PRIMARY KEY REFERENCES vaults(vault_id) ON DELETE CASCADE,
        window_start TIMESTAMPTZ NOT NULL,
        requests INTEGER NOT NULL CHECK(requests>0)
      );
    """)


def downgrade() -> None:
    # Explicit downgrade destroys only these feature-specific rows. Preserve a
    # reviewed backup first if monitoring history must survive feature rollback.
    op.execute("""
      DROP TABLE concierge_request_budget;
      DROP TABLE concierge_provider_control;
      DROP TABLE concierge_monitors;
      DROP TABLE concierge_client_state;
    """)
