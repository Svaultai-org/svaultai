"""Fail-closed rollout gates for Phase-1 domain migrations."""

from zk_migration_flags import ZkMigrationFlags


def test_new_domain_flags_are_off_by_default():
    flags = ZkMigrationFlags.from_environment({})
    assert flags.file_read_enabled is False
    assert flags.file_write_enabled is False
    assert flags.file_migration_enabled is False
    assert flags.memory_read_enabled is False
    assert flags.memory_write_enabled is False
    assert flags.memory_migration_enabled is False
    assert flags.private_local_routing_enabled is False


def test_domain_migration_requires_read_and_write():
    flags = ZkMigrationFlags.from_environment({"FILE_V2_MIGRATION_ENABLED": "true"})
    try:
        flags.validate_dependencies()
    except ValueError as exc:
        assert "file migration" in str(exc)
    else:
        raise AssertionError("file migration must fail closed")


def test_memory_write_requires_memory_read():
    flags = ZkMigrationFlags.from_environment({"MEMORY_V2_WRITE_ENABLED": "true"})
    try:
        flags.validate_dependencies()
    except ValueError as exc:
        assert "memory v2 write" in str(exc)
    else:
        raise AssertionError("memory v2 write must fail closed")
