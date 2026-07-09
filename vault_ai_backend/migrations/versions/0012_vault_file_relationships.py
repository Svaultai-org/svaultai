

from typing import Sequence, Union

from alembic import op


revision: str = "0012_vault_file_relationships"
down_revision: Union[str, None] = "0011_archive_signals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RELATIONSHIP_TYPES = (
    "same_person",
    "same_company",
    "same_trip",
    "same_financial_account",
    "same_document_family",
    "front_back_pair",
    "duplicate",
    "near_duplicate",
    "same_import_batch",
    "same_folder",
    "semantic_related",
    "archive_contains_signal",
    "supporting_document",
)


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ",".join("'" + v + "'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_file_relationships (
            relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vault_id UUID NOT NULL,
            -- Ordered pair: file_a_id < file_b_id is enforced by
            -- the CHECK below so a symmetric pair has exactly
            -- ONE row per relationship_type.
            file_a_id UUID NOT NULL,
            file_b_id UUID NOT NULL,

            relationship_type TEXT NOT NULL,

            -- 0.0 .. 1.0. Builder convention:
            --   strong >= 0.75 (duplicate, front/back, shared
            --                   entity with multiple names, etc.)
            --   medium >= 0.50 (same company, same trip, semantic
            --                   near match, document-family)
            --   weak   >= 0.25 (same folder, same import batch)
            -- Below 0.25 the row is dropped — we never persist
            -- a "barely related" claim.
            confidence REAL NOT NULL,

            -- Human-readable closed-set phrasing the chat layer
            -- renders verbatim. Builder caps at 4 reasons per
            -- row so the JSONB column doesn't bloat.
            reasons_jsonb JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- Small closed-set bag of LABELS / counters / hashes
            -- the builder relied on. NEVER raw text.
            evidence_jsonb JSONB NOT NULL DEFAULT '{{}}'::jsonb,

            analysis_version INTEGER NOT NULL DEFAULT 1,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT vault_file_relationships_type_chk
                CHECK ({type_check}),

            CONSTRAINT vault_file_relationships_confidence_chk
                CHECK (confidence >= 0.0 AND confidence <= 1.0),

            -- Distinct files. file_a != file_b enforced
            -- redundantly via the order CHECK below.
            CONSTRAINT vault_file_relationships_distinct_chk
                CHECK (file_a_id <> file_b_id),

            -- Ordering invariant — file_a_id < file_b_id so a
            -- symmetric pair (A, B) and (B, A) hash to the SAME
            -- row. The Python builder swaps before INSERT.
            CONSTRAINT vault_file_relationships_ordered_chk
                CHECK (file_a_id < file_b_id)
        )
        """.format(
            type_check=_enum_check(
                "relationship_type", _RELATIONSHIP_TYPES,
            ),
        )
    )

                                                           
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "vault_file_relationships_uniq_idx "
        "ON vault_file_relationships "
        "(vault_id, file_a_id, file_b_id, relationship_type)"
    )

                                                               
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_relationships_vault_a_idx "
        "ON vault_file_relationships (vault_id, file_a_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_relationships_vault_b_idx "
        "ON vault_file_relationships (vault_id, file_b_id)"
    )

                                                           
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        "vault_file_relationships_vault_type_idx "
        "ON vault_file_relationships "
        "(vault_id, relationship_type)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS vault_file_relationships_vault_type_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_file_relationships_vault_b_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_file_relationships_vault_a_idx"
    )
    op.execute(
        "DROP INDEX IF EXISTS vault_file_relationships_uniq_idx"
    )
    op.execute("DROP TABLE IF EXISTS vault_file_relationships")
