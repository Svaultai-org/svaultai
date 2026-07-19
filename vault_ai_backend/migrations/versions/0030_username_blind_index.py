"""Client-derived stable username lookup identifier (v1).

Version note (2026-07-20): a first draft of this migration used a
server-side HMAC blind index keyed by an env pepper. That leaked the
raw username to the application server on every register/login (which
was the point of the review that produced this rewrite). The final
design is a CLIENT-derived deterministic 32-byte identifier that
never reveals the raw username to the backend, matching the same
threat surface as ``vault_handle`` today.

Wire + storage
--------------
    lookup_id_v1 = SHA-256(
        b"vaultai.username_lookup.v1|"
        || nfkc_casefolded_utf8_username
    )                                                    -- 32 bytes

* Client computes this alongside ``vault_handle`` and sends
  base64url(lookup_id_v1) as the ``username_lookup`` request field.
* Server stores the raw 32 bytes in ``vaults.username_lookup_v1``.
* Partial UNIQUE index on the non-NULL subset enforces one row per
  canonical username in a derivation-version-independent way (this
  identifier is separate from ``vault_handle``; if a future change
  to normalization requires a v2, a new column is added and both
  are populated during transition).

Threat model
------------
Backend sees only 32 opaque bytes. A DB dump alone reveals nothing
recoverable. A DB dump + source (which contains the salt string)
enables an offline dictionary attack against common usernames — the
same risk that already applies to ``vault_handle``. Rate limits on
register + login are the primary online defense. A future OPRF-
based lookup identifier is documented as the preferred long-term
mitigation.

Legacy row compatibility
------------------------
Rows created before this migration carry ``username_lookup_v1 =
NULL`` and do NOT participate in the partial UNIQUE. The gap is
cryptographically fundamental — the server never stored the raw
username, so there is no way to compute lookup_id_v1 for a legacy
row without the user's device. The fixed client backfills these
rows at login, WITH conflict detection: if the computed
lookup_id_v1 is already claimed by a different row, the found row
is NOT backfilled; a
``username_lookup_conflict_events`` audit row is written for
operator review; login still proceeds. Silent merging never
happens.

Rollback
--------
Downgrade drops the events table + partial index + column; every
other table is untouched.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0030_username_blind_index"
down_revision: Union[str, None] = "0029_inheritance_release_flow"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vaults
            ADD COLUMN IF NOT EXISTS username_lookup_v1 BYTEA
        """,
    )
    op.execute(
        """
        ALTER TABLE vaults
            ADD CONSTRAINT vaults_username_lookup_v1_len_ck CHECK (
                username_lookup_v1 IS NULL
                OR length(username_lookup_v1) = 32
            )
        """,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS vaults_username_lookup_v1_uniq
            ON vaults (username_lookup_v1)
            WHERE username_lookup_v1 IS NOT NULL
        """,
    )
    # Audit trail for legacy backfill conflicts. Written by
    # zk_login_init when the fixed client presents a lookup_id_v1
    # that would collide with an existing (different) row's
    # already-populated lookup_id_v1. The row is NOT backfilled;
    # login still succeeds; an operator reviews via the query in
    # audit_username_lookup_conflicts.sql.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS username_lookup_conflict_events (
            id                          BIGSERIAL   PRIMARY KEY,
            observed_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            login_vault_id              UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            other_vault_id              UUID        NOT NULL
                REFERENCES vaults(vault_id) ON DELETE CASCADE,
            username_lookup_v1_fpr      TEXT        NOT NULL,
            resolved_at                 TIMESTAMPTZ,
            resolution_note             TEXT
        )
        """,
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS username_lookup_conflict_events_unresolved
            ON username_lookup_conflict_events (observed_at DESC)
            WHERE resolved_at IS NULL
        """,
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS username_lookup_conflict_events_unresolved",
    )
    op.execute(
        "DROP TABLE IF EXISTS username_lookup_conflict_events",
    )
    op.execute("DROP INDEX IF EXISTS vaults_username_lookup_v1_uniq")
    op.execute(
        "ALTER TABLE vaults DROP CONSTRAINT IF EXISTS "
        "vaults_username_lookup_v1_len_ck",
    )
    op.execute(
        "ALTER TABLE vaults DROP COLUMN IF EXISTS username_lookup_v1",
    )
