"""Restore vault_name to its intended product meaning.

Context
-------
Before this migration, ``vaults.vault_name`` carried two competing
meanings depending on account type:

  * Legacy accounts (pre-ZK): user-typed login identifier, plaintext,
    UNIQUE. Original product meaning from migration 0001.
  * ZK accounts (post-migration-0023): a synthetic random placeholder
    ``encode(gen_random_bytes(16), 'hex')`` written at signup only to
    satisfy the NOT NULL UNIQUE constraint after login lookup moved
    to ``vault_handle``. Zero product meaning. This is what leaked
    into the typing indicator as
    ``b21e31c5b59abdc8067ff6b23643b254 is thinking...``.

The correct product model (confirmed 2026-07-20) has always been
that ``vault_name`` is the user-chosen identity used both for
signing in AND as the Vault AI's own name. The ZK signup path had
been silently replacing that with a synthetic placeholder.

What this migration does
------------------------
1. Drops ``NOT NULL`` so ZK accounts that don't have a real
   ``vault_name`` yet can exist as NULL. UI + prompt substitute the
   neutral "VaultAI" fallback until the row is backfilled.
2. Keeps the existing UNIQUE index. NULL does not collide in a
   Postgres UNIQUE index (each NULL is treated as distinct), so
   unadopted legacy accounts' ``/auth/login`` lookups by
   ``vault_name`` continue to work, and multiple ZK rows can hold
   NULL simultaneously.
3. Adds a product-label length check (1..60 chars for non-NULL
   values).
4. Backfills the random-hex placeholders to NULL on ZK rows.

Legacy rows with genuine user-typed values are never touched — the
backfill regex matches only strict 32-lowercase-hex strings on rows
that also have a non-NULL ``vault_handle`` (i.e. ZK rows).

Existing ZK rows: their real vault_name is stored client-side (the
user typed it and it drives ``username_lookup_v1``). The fixed
client sends it at login-finalize; the backend backfills the NULL
column when there is no conflict. No user prompt or data
re-submission is required.

Rollback
--------
``downgrade()`` drops the length check and restores ``NOT NULL``
only if all rows are non-NULL. If any row is still NULL, downgrade
fails cleanly — operator must populate every ``vault_name`` before
downgrading. That is intentional: silently re-populating with a
random hex would re-introduce the very leak this migration removes.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0031_vault_name_repurpose"
down_revision: Union[str, None] = "0030_username_blind_index"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vaults ALTER COLUMN vault_name DROP NOT NULL",
    )
    op.execute(
        """
        ALTER TABLE vaults ADD CONSTRAINT vaults_vault_name_len_ck CHECK (
            vault_name IS NULL
            OR (length(vault_name) BETWEEN 1 AND 60)
        )
        """,
    )
    # Clear only the strict 32-hex placeholders on ZK rows. Legacy
    # rows (vault_handle IS NULL) never match the vault_handle
    # filter, so their user-typed values are preserved.
    op.execute(
        r"""
        UPDATE vaults
           SET vault_name = NULL
         WHERE vault_handle IS NOT NULL
           AND vault_name ~ '^[0-9a-f]{32}$'
        """,
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE vaults DROP CONSTRAINT IF EXISTS "
        "vaults_vault_name_len_ck",
    )
    # Restoring NOT NULL is only safe if every row is currently
    # non-NULL. If any row is NULL, this ALTER will fail — that is
    # the correct behavior. The operator must populate every
    # vault_name before downgrading.
    op.execute(
        "ALTER TABLE vaults ALTER COLUMN vault_name SET NOT NULL",
    )
