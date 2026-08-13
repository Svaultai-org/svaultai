from __future__ import annotations

import base64
from dataclasses import dataclass
from uuid import uuid4

import pytest

from zk_migration_adapters import (
    InMemoryOpaqueEnvelopeStore,
    OpaqueEnvelopeNotFound,
    VersionedDomainAdapter,
    ZkV2FeatureDisabled,
    domain_adapters,
)
from zk_migration_contracts import (
    CipherSuite,
    CryptoDowngradeRejected,
    CryptoVersion,
    KeyDomain,
    MigrationState,
    OpaqueRecordEnvelope,
    UnsupportedCryptoVersion,
)
from zk_migration_flags import ZkMigrationFlags
from zk_migration_state import InMemoryMigrationJournal, MigrationCoordinator


@dataclass
class SyntheticLegacyPort:
    values: dict[str, str]
    reads: int = 0
    writes: int = 0

    def read_legacy(self, record_id: str) -> str:
        self.reads += 1
        return self.values[record_id]

    def write_legacy(self, record_id: str, value: str) -> str:
        self.writes += 1
        self.values[record_id] = value
        return value


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _envelope(domain: KeyDomain) -> OpaqueRecordEnvelope:
    return OpaqueRecordEnvelope(
        crypto_version=CryptoVersion.CLIENT_MVK_V2,
        cipher_suite=CipherSuite.XCHACHA20_POLY1305_IETF_V1,
        key_domain=domain,
        nonce_b64=_b64(b"synthetic nonce"),
        ciphertext_b64=_b64(b"opaque synthetic ciphertext"),
        authentication_tag_b64=_b64(b"synthetic tag"),
        migration_state=MigrationState.MIGRATION_PENDING,
    )


def _adapter(
    domain: KeyDomain,
    flags: ZkMigrationFlags,
    *,
    store: InMemoryOpaqueEnvelopeStore | None = None,
) -> tuple[VersionedDomainAdapter[str], SyntheticLegacyPort, InMemoryOpaqueEnvelopeStore]:
    legacy = SyntheticLegacyPort({"item": "unchanged legacy value"})
    opaque = store or InMemoryOpaqueEnvelopeStore()
    adapter = VersionedDomainAdapter(
        vault_id=uuid4(),
        domain=domain,
        legacy=legacy,
        opaque_store=opaque,
        coordinator=MigrationCoordinator(InMemoryMigrationJournal()),
        flags=flags,
    )
    return adapter, legacy, opaque


def test_flags_default_off_and_invalid_values_fail_closed() -> None:
    assert ZkMigrationFlags.from_environment({}) == ZkMigrationFlags()
    assert ZkMigrationFlags.from_environment({"ZK_V2_READ_ENABLED": "maybe"}) == ZkMigrationFlags()
    with pytest.raises(ValueError):
        ZkMigrationFlags(write_enabled=True).validate_dependencies()
    with pytest.raises(ValueError):
        ZkMigrationFlags(migration_enabled=True).validate_dependencies()


def test_legacy_read_and_write_are_delegated_unchanged_when_flags_off() -> None:
    adapter, legacy, _ = _adapter(KeyDomain.FILE, ZkMigrationFlags())
    assert adapter.read("item", "legacy_v1").legacy_value == "unchanged legacy value"
    assert adapter.write("item", "legacy_v1", "new legacy value") == "new legacy value"
    assert legacy.reads == 1
    assert legacy.writes == 1


def test_v2_paths_are_disabled_by_default() -> None:
    adapter, _, _ = _adapter(KeyDomain.FILE, ZkMigrationFlags())
    with pytest.raises(ZkV2FeatureDisabled):
        adapter.read("item", "client_mvk_v2")
    with pytest.raises(ZkV2FeatureDisabled):
        adapter.write("item", "client_mvk_v2", _envelope(KeyDomain.FILE))


def test_unknown_version_fails_closed_without_legacy_fallback() -> None:
    adapter, legacy, _ = _adapter(KeyDomain.FILE, ZkMigrationFlags(read_enabled=True))
    with pytest.raises(UnsupportedCryptoVersion):
        adapter.read("item", "future_v9")
    assert legacy.reads == 0


def test_missing_v2_never_falls_back_to_legacy() -> None:
    adapter, legacy, _ = _adapter(KeyDomain.FILE, ZkMigrationFlags(read_enabled=True))
    with pytest.raises(OpaqueEnvelopeNotFound):
        adapter.read("item", "client_mvk_v2")
    assert legacy.reads == 0


@pytest.mark.parametrize("domain", domain_adapters())
def test_every_domain_supports_opaque_v2_write_and_read(domain: KeyDomain) -> None:
    flags = ZkMigrationFlags(read_enabled=True, write_enabled=True)
    adapter, legacy, _ = _adapter(domain, flags)
    envelope = _envelope(domain)
    assert adapter.write("item", "client_mvk_v2", envelope)
    result = adapter.read("item", "client_mvk_v2")
    assert result.opaque_envelope == envelope
    assert result.legacy_value is None
    assert legacy.reads == 0
    assert not hasattr(adapter, "decrypt")


def test_v2_write_rejects_plaintext_and_wrong_domain() -> None:
    flags = ZkMigrationFlags(read_enabled=True, write_enabled=True)
    adapter, _, _ = _adapter(KeyDomain.FILE, flags)
    with pytest.raises(TypeError):
        adapter.write("item", "client_mvk_v2", "plaintext is forbidden")
    with pytest.raises(ValueError):
        adapter.write("item", "client_mvk_v2", _envelope(KeyDomain.CREDENTIAL))


def test_existing_v2_rejects_downgrade_write() -> None:
    flags = ZkMigrationFlags(read_enabled=True, write_enabled=True)
    adapter, legacy, _ = _adapter(KeyDomain.FILE, flags)
    adapter.write("item", "client_mvk_v2", _envelope(KeyDomain.FILE))
    with pytest.raises(CryptoDowngradeRejected):
        adapter.write("item", "legacy_v1", "downgrade")
    assert legacy.writes == 0


def test_migration_flag_connects_write_verify_and_rollback() -> None:
    flags = ZkMigrationFlags(True, True, True)
    adapter, _, _ = _adapter(KeyDomain.FILE, flags)
    adapter.write("item", "client_mvk_v2", _envelope(KeyDomain.FILE))
    assert adapter.verify("item", client_verified=True).state is MigrationState.V2_VERIFIED
    assert adapter.rollback("item").state is MigrationState.ROLLED_BACK


def test_mixed_legacy_and_v2_records_are_dispatched_independently() -> None:
    flags = ZkMigrationFlags(read_enabled=True, write_enabled=True)
    adapter, legacy, _ = _adapter(KeyDomain.MEMORY, flags)
    adapter.write("v2", "client_mvk_v2", _envelope(KeyDomain.MEMORY))
    legacy.values["legacy"] = "legacy memory"
    assert adapter.read("legacy", "legacy_v1").legacy_value == "legacy memory"
    assert adapter.read("v2", "client_mvk_v2").opaque_envelope is not None
    assert legacy.reads == 1
