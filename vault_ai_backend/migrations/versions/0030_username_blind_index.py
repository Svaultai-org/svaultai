"""Username blind-index for derivation-version-independent uniqueness.

The 2026-07-19 corrective release changed the client-side vault_handle
derivation from CSPRNG to SHA-256(salt||normalized_username). Rows
written under the old algorithm carry a RANDOM 15-byte handle; rows
written under the new algorithm carry a DETERMINISTIC handle. The
partial UNIQUE on ``vaults.vault_handle`` cannot detect the two
representations of the SAME human username as a collision, and so a
user whose pre-fix registration was orphaned (they could never log in)
was able to re-register under the same username and end up with two
rows in the vaults table. See 2026-07-20 incident report.

This migration adds a derivation-version-independent lookup token.

``vaults.username_blind_index`` is the server-computed value

    HMAC-SHA256(env['VAULTAI_USERNAME_BLIND_INDEX_PEPPER'], normalized)

where ``normalized`` is the RFC-compatible NFKC+casefold+trim+collapse
form of the raw username supplied by the client on registration and
login. The server never persists the raw username. The pepper is a
per-deployment secret held only in the process env; a database dump
without the pepper does not enable offline enumeration of usernames.

Uniqueness
----------
The partial UNIQUE ``vaults_username_blind_index_uniq`` fires as soon
as a second row would carry the same blind index — irrespective of
whether the ``vault_handle`` bytes match. This is what stops the
cross-algorithm-collision duplicate documented above.

Rows written before this migration have ``username_blind_index = NULL``
and do not participate in uniqueness (the partial index excludes NULL).
Operators must run a one-time backfill / audit AFTER users log in with
the fixed client (which will supply the raw normalized_username);
duplicates surfaced by that backfill require operator adjudication —
this migration itself never deletes or merges a row.

Rollback
--------
Downgrade drops the index and column; no other schema is touched.
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
            ADD COLUMN IF NOT EXISTS username_blind_index BYTEA
        """,
    )
    op.execute(
        """
        ALTER TABLE vaults
            ADD CONSTRAINT vaults_username_blind_index_len_ck CHECK (
                username_blind_index IS NULL
                OR length(username_blind_index) = 32
            )
        """,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS vaults_username_blind_index_uniq
            ON vaults (username_blind_index)
            WHERE username_blind_index IS NOT NULL
        """,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS vaults_username_blind_index_uniq")
    op.execute(
        "ALTER TABLE vaults DROP CONSTRAINT IF EXISTS "
        "vaults_username_blind_index_len_ck",
    )
    op.execute(
        "ALTER TABLE vaults DROP COLUMN IF EXISTS username_blind_index",
    )
