

from typing import Sequence, Union

from alembic import op


revision: str = "0011_archive_signals"
down_revision: Union[str, None] = "0010_archive_and_video_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vault_file_understanding
        ADD COLUMN IF NOT EXISTS archive_signals_jsonb JSONB
        NOT NULL DEFAULT '{}'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE vault_file_understanding "
        "DROP COLUMN IF EXISTS archive_signals_jsonb"
    )
