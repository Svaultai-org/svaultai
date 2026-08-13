"""Dual-read/new-write compatibility adapters for synthetic ZK v2 rollout.

No production routes import this module. Legacy behavior is delegated unchanged;
v2 payloads are returned to clients as opaque envelopes and never decrypted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar
from uuid import UUID, uuid4

from zk_migration_contracts import (
    CryptoDowngradeRejected,
    CryptoVersion,
    KeyDomain,
    OpaqueRecordEnvelope,
)
from zk_migration_flags import ZkMigrationFlags
from zk_migration_state import ItemRef, MigrationCoordinator, MigrationJournalEntry


LegacyT = TypeVar("LegacyT")


class ZkV2FeatureDisabled(RuntimeError):
    code = "zk_v2_feature_disabled"


class OpaqueEnvelopeNotFound(LookupError):
    code = "opaque_envelope_not_found"


class LegacyRecordPort(Protocol, Generic[LegacyT]):
    def read_legacy(self, record_id: str) -> LegacyT: ...

    def write_legacy(self, record_id: str, value: LegacyT) -> LegacyT: ...


class OpaqueEnvelopePort(Protocol):
    def get_v2(self, item: ItemRef) -> tuple[UUID, OpaqueRecordEnvelope] | None: ...

    def put_v2(self, item: ItemRef, envelope: OpaqueRecordEnvelope) -> UUID: ...


@dataclass(frozen=True)
class VersionedRead(Generic[LegacyT]):
    crypto_version: CryptoVersion
    legacy_value: LegacyT | None = None
    opaque_envelope: OpaqueRecordEnvelope | None = None


class InMemoryOpaqueEnvelopeStore:
    def __init__(self) -> None:
        self._values: dict[ItemRef, tuple[UUID, OpaqueRecordEnvelope]] = {}

    def get_v2(self, item: ItemRef) -> tuple[UUID, OpaqueRecordEnvelope] | None:
        return self._values.get(item)

    def put_v2(self, item: ItemRef, envelope: OpaqueRecordEnvelope) -> UUID:
        current = self._values.get(item)
        if current is not None:
            if current[1] != envelope:
                raise ValueError("a different v2 envelope already exists for this item")
            return current[0]
        envelope_id = uuid4()
        self._values[item] = (envelope_id, envelope)
        return envelope_id


class VersionedDomainAdapter(Generic[LegacyT]):
    """Common read/write/verify/rollback contract for one vault domain."""

    def __init__(
        self,
        *,
        vault_id: UUID,
        domain: KeyDomain,
        legacy: LegacyRecordPort[LegacyT],
        opaque_store: OpaqueEnvelopePort,
        coordinator: MigrationCoordinator,
        flags: ZkMigrationFlags,
    ) -> None:
        flags.validate_dependencies()
        self._vault_id = vault_id
        self._domain = domain
        self._legacy = legacy
        self._opaque_store = opaque_store
        self._coordinator = coordinator
        self._flags = flags

    def _item(self, record_id: str) -> ItemRef:
        return ItemRef(self._vault_id, self._domain, record_id)

    def read(self, record_id: str, crypto_version: str) -> VersionedRead[LegacyT]:
        version = CryptoVersion.parse(crypto_version)
        if version is CryptoVersion.LEGACY_V1:
            return VersionedRead(version, legacy_value=self._legacy.read_legacy(record_id))
        if not self._flags.read_enabled:
            raise ZkV2FeatureDisabled("v2 reads are disabled")
        stored = self._opaque_store.get_v2(self._item(record_id))
        if stored is None:
            raise OpaqueEnvelopeNotFound("v2 envelope does not exist")
        return VersionedRead(version, opaque_envelope=stored[1])

    def write(
        self,
        record_id: str,
        crypto_version: str,
        value: LegacyT | OpaqueRecordEnvelope,
    ) -> LegacyT | UUID:
        version = CryptoVersion.parse(crypto_version)
        item = self._item(record_id)
        if version is CryptoVersion.LEGACY_V1:
            if self._opaque_store.get_v2(item) is not None:
                raise CryptoDowngradeRejected("cannot overwrite v2 with legacy_v1")
            return self._legacy.write_legacy(record_id, value)  # type: ignore[arg-type]

        if not self._flags.write_enabled:
            raise ZkV2FeatureDisabled("v2 writes are disabled")
        if not isinstance(value, OpaqueRecordEnvelope):
            raise TypeError("client_mvk_v2 writes require an opaque envelope")
        if value.key_domain is not self._domain:
            raise ValueError("envelope key domain does not match the adapter")
        envelope_id = self._opaque_store.put_v2(item, value)
        if self._flags.migration_enabled:
            self._coordinator.begin(item)
            self._coordinator.record_v2_upload(item, envelope_id)
        return envelope_id

    def verify(self, record_id: str, *, client_verified: bool) -> MigrationJournalEntry:
        if not self._flags.migration_enabled:
            raise ZkV2FeatureDisabled("v2 migration is disabled")
        return self._coordinator.record_verification(
            self._item(record_id), verified=client_verified
        )

    def rollback(self, record_id: str) -> MigrationJournalEntry:
        if not self._flags.migration_enabled:
            raise ZkV2FeatureDisabled("v2 migration is disabled")
        return self._coordinator.rollback(self._item(record_id))


def domain_adapters() -> tuple[KeyDomain, ...]:
    """Explicit inventory; adding a domain requires a reviewed contract."""

    return (
        KeyDomain.FILE,
        KeyDomain.CREDENTIAL,
        KeyDomain.MEMORY,
        KeyDomain.SECURE_NOTE,
        KeyDomain.WALLET_RECORD,
        KeyDomain.INHERITANCE_RECORD,
    )
