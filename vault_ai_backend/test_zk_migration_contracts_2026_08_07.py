from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest

from zk_migration_contracts import (
    CipherSuite,
    CryptoDowngradeRejected,
    CryptoVersion,
    InvalidOpaqueEnvelope,
    KeyDomain,
    MigrationState,
    OpaqueRecordEnvelope,
    UnsupportedCryptoVersion,
    assert_no_downgrade,
)


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _envelope() -> OpaqueRecordEnvelope:
    return OpaqueRecordEnvelope(
        crypto_version=CryptoVersion.CLIENT_MVK_V2,
        cipher_suite=CipherSuite.XCHACHA20_POLY1305_IETF_V1,
        key_domain=KeyDomain.FILE,
        nonce_b64=_b64(b"synthetic nonce"),
        ciphertext_b64=_b64(b"synthetic ciphertext, never plaintext data"),
        authentication_tag_b64=_b64(b"synthetic tag"),
        migration_state=MigrationState.V2_WRITTEN,
        blind_indexes={"name": "synthetic-blind-index"},
    )


def test_crypto_versions_are_explicit_and_unknown_fails_closed() -> None:
    assert CryptoVersion.parse("legacy_v1") is CryptoVersion.LEGACY_V1
    assert CryptoVersion.parse("client_mvk_v2") is CryptoVersion.CLIENT_MVK_V2
    with pytest.raises(UnsupportedCryptoVersion) as exc:
        CryptoVersion.parse("future_v99")
    assert exc.value.code == "unsupported_crypto_version"


def test_v2_envelope_is_opaque_storage_only() -> None:
    envelope = _envelope()
    stored = envelope.opaque_storage_fields()
    assert stored["ciphertext_b64"] == envelope.ciphertext_b64
    assert not hasattr(envelope, "decrypt")
    assert "pin" not in stored
    assert "mvk" not in stored
    assert "derived_key" not in stored


@pytest.mark.parametrize("field", ["nonce_b64", "ciphertext_b64", "authentication_tag_b64"])
def test_v2_envelope_rejects_non_base64_cipher_fields(field: str) -> None:
    values = _envelope().__dict__.copy()
    values[field] = "not base64!"
    with pytest.raises(InvalidOpaqueEnvelope):
        OpaqueRecordEnvelope(**values)


def test_v2_envelope_rejects_legacy_version_and_wrong_suite() -> None:
    values = _envelope().__dict__.copy()
    values["crypto_version"] = CryptoVersion.LEGACY_V1
    with pytest.raises(InvalidOpaqueEnvelope):
        OpaqueRecordEnvelope(**values)
    values = _envelope().__dict__.copy()
    values["cipher_suite"] = CipherSuite.LEGACY_SERVER_V1
    with pytest.raises(InvalidOpaqueEnvelope):
        OpaqueRecordEnvelope(**values)


def test_migration_timestamp_must_be_timezone_aware() -> None:
    values = _envelope().__dict__.copy()
    values["migrated_at"] = datetime.now()
    with pytest.raises(InvalidOpaqueEnvelope):
        OpaqueRecordEnvelope(**values)
    values["migrated_at"] = datetime.now(timezone.utc)
    assert OpaqueRecordEnvelope(**values).migrated_at is not None


def test_downgrade_is_rejected() -> None:
    with pytest.raises(CryptoDowngradeRejected):
        assert_no_downgrade(CryptoVersion.CLIENT_MVK_V2, CryptoVersion.LEGACY_V1)
    assert_no_downgrade(CryptoVersion.LEGACY_V1, CryptoVersion.CLIENT_MVK_V2)
