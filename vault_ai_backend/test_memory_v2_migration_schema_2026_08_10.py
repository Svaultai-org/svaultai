from pathlib import Path


def test_memory_v2_identity_migration_preserves_legacy_uniqueness() -> None:
    migration = (
        Path(__file__).parent
        / "migrations"
        / "versions"
        / "0037_memory_v2_record_identity.py"
    ).read_text(encoding="utf-8")

    upgrade = migration.split("def upgrade() -> None:", 1)[1].split(
        "def downgrade() -> None:", 1
    )[0]
    assert "DROP INDEX IF EXISTS vault_ai_memory_lookup_uniq" not in upgrade
    assert "ADD COLUMN IF NOT EXISTS memory_record_id" in upgrade
    assert "vault_ai_memory_v2_record_uq" in upgrade
