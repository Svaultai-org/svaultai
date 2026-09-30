"""Remove readable vault login names from server storage.

The client already derives ``username_lookup_v1`` from the normalized login
name.  This migration fills that lookup for the last legacy rows while their
old value is still available, then irreversibly replaces every readable
``vault_name`` with a row-internal opaque label.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from alembic import op


revision = "0045_private_vault_identifiers"
down_revision = "0044_storage_billing_ownership"
branch_labels = None
depends_on = None

_LOOKUP_DOMAIN = b"vaultai.username_lookup.v1|"


def _lookup(raw: str) -> bytes:
    normalized = unicodedata.normalize("NFKC", raw)
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    if not normalized:
        raise RuntimeError("cannot migrate an empty legacy vault name")
    return hashlib.sha256(_LOOKUP_DOMAIN + normalized.encode("utf-8")).digest()


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.exec_driver_sql(
        """
        SELECT vault_id::text, vault_name
          FROM vaults
         WHERE username_lookup_v1 IS NULL
        """
    ).fetchall()
    for vault_id, readable_name in rows:
        if not isinstance(readable_name, str) or not readable_name.strip():
            raise RuntimeError(
                f"vault {vault_id} has no lookup and no migratable name"
            )
        bind.exec_driver_sql(
            "UPDATE vaults SET username_lookup_v1 = %s WHERE vault_id = %s",
            (_lookup(readable_name), vault_id),
        )

    op.execute(
        """
        UPDATE vaults
           SET vault_name = 'vault-' || replace(vault_id::text, '-', ''),
               display_username = NULL
        """
    )
    op.execute("ALTER TABLE vaults ALTER COLUMN vault_name SET NOT NULL")
    op.execute(
        """
        ALTER TABLE vaults
        ADD CONSTRAINT vaults_vault_name_is_opaque_ck CHECK (
            vault_name = 'vault-' || replace(vault_id::text, '-', '')
        )
        """
    )


def downgrade() -> None:
    # Readable names cannot and must not be reconstructed server-side.
    op.execute(
        "ALTER TABLE vaults DROP CONSTRAINT IF EXISTS "
        "vaults_vault_name_is_opaque_ck"
    )
