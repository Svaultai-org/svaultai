"""Allow bounded V3 encrypted manifests for large legacy extracted text.

V1 and V2 file rows retain their existing meaning. V3 is created only by the
default-off, proof-bound owner migration path and remains opaque to the server.

Revision ID: 0061
Revises: 0060
"""

from alembic import op


revision = "0061_file_v3_legacy_extra_manifest"
down_revision = "0060_pin_verifier_retirement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE file_v2_records
          DROP CONSTRAINT file_v2_records_migration_metadata_version_check,
          ADD CONSTRAINT file_v2_records_migration_metadata_version_check
          CHECK (migration_metadata_version IN (1, 2, 3))
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM file_v2_records WHERE migration_metadata_version = 3
          ) THEN
            RAISE EXCEPTION 'file_v3_legacy_extra_data_exists'
              USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    op.execute("""
        ALTER TABLE file_v2_records
          DROP CONSTRAINT file_v2_records_migration_metadata_version_check,
          ADD CONSTRAINT file_v2_records_migration_metadata_version_check
          CHECK (migration_metadata_version IN (1, 2))
    """)
