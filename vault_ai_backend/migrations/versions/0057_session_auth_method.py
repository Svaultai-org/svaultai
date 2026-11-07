"""Record how an authenticated session was issued.

Existing sessions are conservatively legacy until their next OPAQUE login.
The column is an authorization fact set by server-side login routes, never a
client-provided header.

Revision ID: 0057
Revises: 0056
"""

from alembic import op


revision = "0057_session_auth_method"
down_revision = "0056_file_v2_legacy_extra_manifest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auth_sessions ADD COLUMN auth_method TEXT NOT NULL "
        "DEFAULT 'legacy_pin' "
        "CHECK (auth_method IN ('legacy_pin', 'opaque'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE auth_sessions DROP COLUMN IF EXISTS auth_method")
