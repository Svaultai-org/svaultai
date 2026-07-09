"""Widen vault_deletion_tombstones.deletion_reason CHECK constraint
to include the development-only bulk wipe reason.

Motivation: `scripts/wipe_all_test_users.py` performs a full test-user
data reset in development. Each per-vault delete goes through
`delete_vault_and_all_data()` and inserts a tombstone. That tombstone
row is safe (hashed_vault_id + timestamp + reason) but the existing
CHECK constraint only allows `user_requested` and
`unpaid_inactive_6_months`, so we widen it here with a distinct,
easy-to-audit reason: `development_full_user_wipe`.

Absolute rules preserved:
  * Tombstone still stores no vault name, no account id, no wallet
    address, no encrypted secret.
  * The new reason cannot be used from any production code path — the
    wipe script hard-refuses to run unless the environment is
    development, or the operator sets an explicit
    VAULTAI_ALLOW_TEST_USER_WIPE env var *and* passes the confirm
    flag on the command line.
"""

from __future__ import annotations

from typing import Union

from alembic import op


revision: str = "0019_dev_wipe_deletion_reason"
down_revision: Union[str, None] = "0018_vault_activity_and_deletion"
branch_labels: Union[str, list[str], None] = None
depends_on: Union[str, list[str], None] = None


_DELETION_REASONS = (
    "user_requested",
    "unpaid_inactive_6_months",
    "development_full_user_wipe",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vault_deletion_tombstones "
        "DROP CONSTRAINT IF EXISTS "
        "vault_deletion_tombstones_deletion_reason_check"
    )
    reasons_sql = ",".join("'" + r + "'" for r in _DELETION_REASONS)
    op.execute(
        f"""
        ALTER TABLE vault_deletion_tombstones
            ADD CONSTRAINT vault_deletion_tombstones_deletion_reason_check
            CHECK (deletion_reason IN ({reasons_sql}))
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM vault_deletion_tombstones "
        "WHERE deletion_reason = 'development_full_user_wipe'"
    )
    op.execute(
        "ALTER TABLE vault_deletion_tombstones "
        "DROP CONSTRAINT IF EXISTS "
        "vault_deletion_tombstones_deletion_reason_check"
    )
    prev = ("user_requested", "unpaid_inactive_6_months")
    prev_sql = ",".join("'" + r + "'" for r in prev)
    op.execute(
        f"""
        ALTER TABLE vault_deletion_tombstones
            ADD CONSTRAINT vault_deletion_tombstones_deletion_reason_check
            CHECK (deletion_reason IN ({prev_sql}))
        """
    )
