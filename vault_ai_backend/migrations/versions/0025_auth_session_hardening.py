"""Single-session hardening — Phase 1 of session revocation.

Adds columns, constraints, indexes, and a new audit-events table to
support the "one active session per vault" policy. Contains a
deterministic backfill that consolidates any pre-existing
multi-session vaults down to at-most one unrevoked row **before**
the single-session-per-vault UNIQUE index is created — the index
would otherwise fail on legacy multi-session vaults.

Additive columns on ``auth_sessions``:
  + token_id_hash          BYTEA          NULL
      HMAC-SHA256(session_secret, token_id_bytes || b"session-id/v1").
      Populated by future issuance (application code), NULL for
      pre-migration rows. Length-checked to 32 bytes when non-NULL.

  + client_label           TEXT           NULL
      Coarse, server-derived audit label such as
      "Chrome on Windows". Never contains the raw User-Agent.
      Length-capped to 1..64 chars when non-NULL.

  + client_label_source    SMALLINT       NOT NULL DEFAULT 0
      0 = absent, 1 = derived-from-UA-at-issue. Nullability change
      is safe: DEFAULT 0 backfills existing rows automatically.

  + revoked_reason         TEXT           NULL
      Free-form label: 'logout' | 'superseded-by-new-login' |
      'revoke-one' | 'vault-delete' | 'single-session-migration' |
      'cap-evicted' | ... . Intentionally CHECK-free so future
      reason codes do not force a new migration.

New indexes on ``auth_sessions``:
  + uq_auth_sessions_one_unrevoked_per_vault
      UNIQUE (vault_id) WHERE revoked_at IS NULL.
      The load-bearing single-session invariant.

  + uq_auth_sessions_token_id_hash
      UNIQUE (token_id_hash) WHERE token_id_hash IS NOT NULL.
      Guarantees the public session reference returned by
      GET /auth/sessions is globally unique.

  + idx_auth_sessions_vault_active
      (vault_id, expires_at) WHERE revoked_at IS NULL.
      Query support for the bounded active-session scan used by
      the vault-scoped hash lookup.

New table ``vault_security_events``:
  Structured audit trail. Never contains IP, User-Agent, token_id,
  token_id_hash, MVK/subkey material, or vault plaintext.

    event_id      BIGSERIAL PRIMARY KEY
    vault_id      UUID NOT NULL REFERENCES vaults(vault_id) ON DELETE CASCADE
    event_type    TEXT NOT NULL       -- 1..64 chars
    client_label  TEXT     NULL       -- 1..64 chars when non-NULL
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    event_version SMALLINT NOT NULL DEFAULT 1
    idx_vault_security_events_vault_time (vault_id, created_at DESC)

Deterministic backfill:

    For every vault with rows WHERE revoked_at IS NULL:
      Rank by (issued_at DESC, token_id DESC).
      * rn = 1 AND expires_at >  NOW()  →  KEEP
      * rn = 1 AND expires_at <= NOW()  →  REVOKE
      * rn > 1                          →  REVOKE
    Revocations set revoked_at = NOW() and
    revoked_reason = 'single-session-migration'.

One ``vault_security_events`` row is emitted per affected vault with
event_type='single-session-migration' and client_label=NULL. Affected
vaults are identified by DISTINCT on the revoked_reason we just wrote
(this migration is the first ever writer of that reason value, so
scoping is unambiguous).

Downgrade is STRUCTURAL ONLY. Revoked rows stay revoked; the data
change is intentionally irreversible. Reconstructing which historical
row was "the surviving session" from a revoked state has no defined
semantic and would corrupt audit truth.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0025_auth_session_hardening"
down_revision: Union[str, None] = "0024_vault_metadata_encryption"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------
    # 1. Additive columns on auth_sessions.
    #    IF NOT EXISTS covers the re-run-inside-a-manual-transaction
    #    case; the primary idempotency guarantee remains Alembic's
    #    version-table check.
    # -------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE auth_sessions
          ADD COLUMN IF NOT EXISTS token_id_hash        BYTEA,
          ADD COLUMN IF NOT EXISTS client_label         TEXT,
          ADD COLUMN IF NOT EXISTS client_label_source  SMALLINT NOT NULL DEFAULT 0,
          ADD COLUMN IF NOT EXISTS revoked_reason       TEXT
        """
    )

    # -------------------------------------------------------------
    # 2. Length CHECK constraints.
    #    Both NULL-safe so they never fail against existing rows.
    # -------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conname = 'auth_sessions_token_id_hash_len_chk'
          ) THEN
            ALTER TABLE auth_sessions
              ADD CONSTRAINT auth_sessions_token_id_hash_len_chk
                CHECK (token_id_hash IS NULL
                       OR octet_length(token_id_hash) = 32);
          END IF;
        END $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conname = 'auth_sessions_client_label_len_chk'
          ) THEN
            ALTER TABLE auth_sessions
              ADD CONSTRAINT auth_sessions_client_label_len_chk
                CHECK (client_label IS NULL
                       OR char_length(client_label) BETWEEN 1 AND 64);
          END IF;
        END $$
        """
    )

    # -------------------------------------------------------------
    # 3. Deterministic backfill.
    #    Must run BEFORE the single-session partial UNIQUE index
    #    (step 4). Any vault that today has more than one
    #    unrevoked session, or a lone-but-expired unrevoked row,
    #    is consolidated to at-most one live row.
    #    Deterministic tie-break: token_id DESC after issued_at DESC.
    # -------------------------------------------------------------
    op.execute(
        """
        WITH ranked AS (
            SELECT token_id, vault_id, expires_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY vault_id
                       ORDER BY issued_at DESC, token_id DESC
                   ) AS rn
              FROM auth_sessions
             WHERE revoked_at IS NULL
        )
        UPDATE auth_sessions AS s
           SET revoked_at     = NOW(),
               revoked_reason = 'single-session-migration'
          FROM ranked r
         WHERE s.token_id = r.token_id
           AND (
                 r.rn > 1
                 OR (r.rn = 1 AND r.expires_at <= NOW())
               )
        """
    )

    # -------------------------------------------------------------
    # 4. The load-bearing single-session invariant.
    #    Partial UNIQUE index enforces at-most-one unrevoked row
    #    per vault, at the DB level, under any concurrency model.
    # -------------------------------------------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
          uq_auth_sessions_one_unrevoked_per_vault
          ON auth_sessions (vault_id)
          WHERE revoked_at IS NULL
        """
    )

    # -------------------------------------------------------------
    # 5. Partial UNIQUE index on token_id_hash so the public session
    #    reference the future GET /auth/sessions returns is globally
    #    unique. NULLs are excluded (pre-migration rows lack a hash).
    # -------------------------------------------------------------
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
          uq_auth_sessions_token_id_hash
          ON auth_sessions (token_id_hash)
          WHERE token_id_hash IS NOT NULL
        """
    )

    # -------------------------------------------------------------
    # 6. Query-support index for the bounded active-session scan
    #    used by the future vault-scoped hash lookup (pre-migration
    #    rows are matched by iterating this partial index).
    # -------------------------------------------------------------
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
          idx_auth_sessions_vault_active
          ON auth_sessions (vault_id, expires_at)
          WHERE revoked_at IS NULL
        """
    )

    # -------------------------------------------------------------
    # 7. Security-events audit table.
    #    No IP, no User-Agent, no token identifier, no vault
    #    plaintext. Length caps prevent runaway blobs.
    # -------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_security_events (
            event_id      BIGSERIAL PRIMARY KEY,
            vault_id      UUID NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            event_type    TEXT NOT NULL,
            client_label  TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            event_version SMALLINT NOT NULL DEFAULT 1,
            CONSTRAINT vault_security_events_event_type_len_chk
                CHECK (char_length(event_type) BETWEEN 1 AND 64),
            CONSTRAINT vault_security_events_client_label_len_chk
                CHECK (client_label IS NULL
                       OR char_length(client_label) BETWEEN 1 AND 64)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vault_security_events_vault_time
          ON vault_security_events (vault_id, created_at DESC)
        """
    )

    # -------------------------------------------------------------
    # 8. Emit one 'single-session-migration' event per affected
    #    vault. This migration is the FIRST writer of the reason
    #    value 'single-session-migration' in DB history, so
    #    DISTINCT scoping is unambiguous.
    #
    #    Rationale: emit AFTER creating the events table so the
    #    events end up in the same schema shape the runtime code
    #    will read.
    # -------------------------------------------------------------
    op.execute(
        """
        INSERT INTO vault_security_events (vault_id, event_type, client_label)
        SELECT DISTINCT s.vault_id, 'single-session-migration', NULL
          FROM auth_sessions s
         WHERE s.revoked_reason = 'single-session-migration'
        """
    )


def downgrade() -> None:
    """Structural downgrade only — irreversible data state noted.

    This drops every object created by upgrade(). It does NOT
    un-revoke sessions that upgrade() revoked with
    ``revoked_reason='single-session-migration'`` — those rows stay
    revoked. Reconstructing which historical row was "the surviving
    session" from a revoked state has no defined semantic and would
    corrupt audit truth.

    The security-events rows this migration emitted also stay
    logically true (they record that the transition happened), but
    they are dropped because the table itself is dropped. If a
    downgrade-then-re-upgrade cycle happens, the re-upgrade re-emits
    events for whichever rows still have
    ``revoked_reason='single-session-migration'`` — safe because
    ``DROP TABLE`` also purges the prior events.
    """

    # 7 + 6 → drop events table (indexes dropped implicitly with the table,
    # but we DROP INDEX explicitly first for symmetric visibility).
    op.execute("DROP INDEX IF EXISTS idx_vault_security_events_vault_time")
    op.execute("DROP TABLE IF EXISTS vault_security_events")

    # 4, 5, 6 → drop auth_sessions indexes.
    op.execute("DROP INDEX IF EXISTS idx_auth_sessions_vault_active")
    op.execute("DROP INDEX IF EXISTS uq_auth_sessions_token_id_hash")
    op.execute("DROP INDEX IF EXISTS uq_auth_sessions_one_unrevoked_per_vault")

    # 2 → drop CHECK constraints.
    op.execute(
        """
        ALTER TABLE auth_sessions
          DROP CONSTRAINT IF EXISTS auth_sessions_client_label_len_chk,
          DROP CONSTRAINT IF EXISTS auth_sessions_token_id_hash_len_chk
        """
    )

    # 1 → drop additive columns. Reverse order for readability.
    op.execute(
        """
        ALTER TABLE auth_sessions
          DROP COLUMN IF EXISTS revoked_reason,
          DROP COLUMN IF EXISTS client_label_source,
          DROP COLUMN IF EXISTS client_label,
          DROP COLUMN IF EXISTS token_id_hash
        """
    )
    # NOTE: rows revoked by upgrade()'s backfill remain revoked.
    # This is intentional and documented in the docstring above.
