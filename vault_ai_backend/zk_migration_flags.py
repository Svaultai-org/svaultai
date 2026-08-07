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

    @classmethod
    def from_environment(cls, source: Mapping[str, str] | None = None) -> "ZkMigrationFlags":
        env = os.environ if source is None else source
        return cls(
            read_enabled=_flag(env, "ZK_V2_READ_ENABLED"),
            write_enabled=_flag(env, "ZK_V2_WRITE_ENABLED"),
            migration_enabled=_flag(env, "ZK_V2_MIGRATION_ENABLED"),
        )

    def validate_dependencies(self) -> None:
        if self.migration_enabled and not (self.read_enabled and self.write_enabled):
            raise ValueError("migration requires both v2 read and v2 write flags")
        if self.write_enabled and not self.read_enabled:
            raise ValueError("v2 write requires v2 read")
