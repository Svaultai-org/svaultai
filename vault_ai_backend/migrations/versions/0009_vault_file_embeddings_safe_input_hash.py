

from typing import Sequence, Union

from alembic import op


revision: str = "0009_vault_file_embeddings_safe_input_hash"
down_revision: Union[str, None] = "0008_vault_file_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vault_file_embeddings
        ADD COLUMN IF NOT EXISTS safe_input_hash TEXT
        """
    )

                                                                 
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_embeddings_input_hash_idx "
        "ON vault_file_embeddings "
        "(vault_id, file_id, embedding_model, safe_input_hash)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS vault_file_embeddings_input_hash_idx"
    )
    op.execute(
        "ALTER TABLE vault_file_embeddings "
        "DROP COLUMN IF EXISTS safe_input_hash"
    )
