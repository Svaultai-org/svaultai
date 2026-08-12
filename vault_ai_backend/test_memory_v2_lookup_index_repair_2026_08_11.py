from pathlib import Path


def test_memory_v2_lookup_index_repair_is_idempotent_and_non_destructive() -> None:
    migration = (
        Path(__file__).parent
        / "migrations"
        / "versions"
        / "0041_restore_memory_v2_lookup_index.py"
    ).read_text()

    assert 'down_revision = "0040_wallet_v2_engine"' in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS vault_ai_memory_lookup_uniq" in migration
    assert "ON vault_ai_memory (vault_id, memory_lookup_hash)" in migration
    assert "superseded_at IS NULL AND memory_lookup_hash IS NOT NULL" in migration
    assert "DROP INDEX" not in migration
