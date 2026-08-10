"""Explicit fail-closed feature flags for ZK v2 infrastructure."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


def _flag(source: Mapping[str, str], name: str) -> bool:
    raw = source.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return False


@dataclass(frozen=True)
class ZkMigrationFlags:
    read_enabled: bool = False
    write_enabled: bool = False
    migration_enabled: bool = False
    file_read_enabled: bool = False
    file_write_enabled: bool = False
    file_migration_enabled: bool = False
    memory_read_enabled: bool = False
    memory_write_enabled: bool = False
    memory_migration_enabled: bool = False
    private_local_routing_enabled: bool = False
    wallet_backup_read_enabled: bool = False
    wallet_backup_write_enabled: bool = False
    wallet_backup_migration_enabled: bool = False
    wallet_read_enabled: bool = False
    wallet_write_enabled: bool = False
    wallet_migration_enabled: bool = False

    @classmethod
    def from_environment(cls, source: Mapping[str, str] | None = None) -> "ZkMigrationFlags":
        env = os.environ if source is None else source
        return cls(
            read_enabled=_flag(env, "ZK_V2_READ_ENABLED"),
            write_enabled=_flag(env, "ZK_V2_WRITE_ENABLED"),
            migration_enabled=_flag(env, "ZK_V2_MIGRATION_ENABLED"),
            file_read_enabled=_flag(env, "FILE_V2_READ_ENABLED"),
            file_write_enabled=_flag(env, "FILE_V2_WRITE_ENABLED"),
            file_migration_enabled=_flag(env, "FILE_V2_MIGRATION_ENABLED"),
            memory_read_enabled=_flag(env, "MEMORY_V2_READ_ENABLED"),
            memory_write_enabled=_flag(env, "MEMORY_V2_WRITE_ENABLED"),
            memory_migration_enabled=_flag(env, "MEMORY_V2_MIGRATION_ENABLED"),
            private_local_routing_enabled=_flag(env, "PRIVATE_VAULT_LOCAL_ROUTING_ENABLED"),
            wallet_backup_read_enabled=_flag(env, "WALLET_BACKUP_V2_READ_ENABLED"),
            wallet_backup_write_enabled=_flag(env, "WALLET_BACKUP_V2_WRITE_ENABLED"),
            wallet_backup_migration_enabled=_flag(env, "WALLET_BACKUP_V2_MIGRATION_ENABLED"),
            wallet_read_enabled=_flag(env, "WALLET_V2_READ_ENABLED"),
            wallet_write_enabled=_flag(env, "WALLET_V2_WRITE_ENABLED"),
            wallet_migration_enabled=_flag(env, "WALLET_V2_MIGRATION_ENABLED"),
        )

    def validate_dependencies(self) -> None:
        if self.migration_enabled and not (self.read_enabled and self.write_enabled):
            raise ValueError("migration requires both v2 read and v2 write flags")
        if self.write_enabled and not self.read_enabled:
            raise ValueError("v2 write requires v2 read")
        if self.file_migration_enabled and not (self.file_read_enabled and self.file_write_enabled):
            raise ValueError("file migration requires file read and file write flags")
        if self.file_write_enabled and not self.file_read_enabled:
            raise ValueError("file v2 write requires file v2 read")
        if self.memory_migration_enabled and not (self.memory_read_enabled and self.memory_write_enabled):
            raise ValueError("memory migration requires memory read and memory write flags")
        if self.memory_write_enabled and not self.memory_read_enabled:
            raise ValueError("memory v2 write requires memory v2 read")
        if self.wallet_backup_migration_enabled and not (
            self.wallet_backup_read_enabled and self.wallet_backup_write_enabled
        ):
            raise ValueError("wallet backup migration requires read and write flags")
        if self.wallet_backup_write_enabled and not self.wallet_backup_read_enabled:
            raise ValueError("wallet backup v2 write requires wallet backup v2 read")
        if self.wallet_migration_enabled and not (
            self.wallet_read_enabled and self.wallet_write_enabled
        ):
            raise ValueError("wallet v2 migration requires read and write flags")
        if self.wallet_write_enabled and not self.wallet_read_enabled:
            raise ValueError("wallet v2 write requires wallet v2 read")
