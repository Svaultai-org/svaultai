"""Versioned, opaque record contracts for the future client-MVK migration.

This module is infrastructure only.  It does not mount routes, migrate records,
or decrypt content.  In particular, ``client_mvk_v2`` payloads are opaque to
the backend by contract.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping


class CryptoContractError(ValueError):
    """Base class for safe versioned-record contract failures."""


class UnsupportedCryptoVersion(CryptoContractError):
    code = "unsupported_crypto_version"


class CryptoDowngradeRejected(CryptoContractError):
    code = "crypto_downgrade_rejected"


class InvalidOpaqueEnvelope(CryptoContractError):
    code = "invalid_opaque_envelope"


class CryptoVersion(str, Enum):
    LEGACY_V1 = "legacy_v1"
    CLIENT_MVK_V2 = "client_mvk_v2"

    @classmethod
    def parse(cls, value: str) -> "CryptoVersion":
        try:
            return cls(value)
        except (TypeError, ValueError) as exc:
            raise UnsupportedCryptoVersion(cls._safe_value(value)) from exc

    @staticmethod
    def _safe_value(value: object) -> str:
        text = str(value)
        return text if len(text) <= 64 else text[:61] + "..."


class CipherSuite(str, Enum):
    LEGACY_SERVER_V1 = "legacy_server_v1"
    XCHACHA20_POLY1305_IETF_V1 = "xchacha20_poly1305_ietf_v1"


class KeyDomain(str, Enum):
    FILE = "file"
    CREDENTIAL = "credential"
    MEMORY = "memory"
    SECURE_NOTE = "secure_note"
    WALLET_RECORD = "wallet_record"
    INHERITANCE_RECORD = "inheritance_record"


class VerificationState(str, Enum):
    NOT_VERIFIED = "not_verified"
    CLIENT_VERIFIED = "client_verified"
    VERIFICATION_FAILED = "verification_failed"


class MigrationState(str, Enum):
    LEGACY = "legacy"
    MIGRATION_PENDING = "migration_pending"
    V2_WRITTEN = "v2_written"
    V2_VERIFIED = "v2_verified"
    MIGRATED = "migrated"
    MIGRATION_FAILED = "migration_failed"
    VERIFICATION_FAILED = "verification_failed"
    ROLLBACK_PENDING = "rollback_pending"
    ROLLED_BACK = "rolled_back"


_B64_FIELDS = ("nonce_b64", "ciphertext_b64", "authentication_tag_b64")


def _require_canonical_b64(name: str, value: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise InvalidOpaqueEnvelope(f"{name} must be non-empty base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise InvalidOpaqueEnvelope(f"{name} must be canonical base64") from exc
    if not decoded and not allow_empty:
        raise InvalidOpaqueEnvelope(f"{name} must decode to non-empty bytes")


@dataclass(frozen=True)
class OpaqueRecordEnvelope:
    """A client-produced ciphertext envelope which the backend cannot open."""

    crypto_version: CryptoVersion
    cipher_suite: CipherSuite
    key_domain: KeyDomain
    nonce_b64: str
    ciphertext_b64: str
    authentication_tag_b64: str
    migration_state: MigrationState
    verification_state: VerificationState = VerificationState.NOT_VERIFIED
    migrated_at: datetime | None = None
    blind_indexes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.crypto_version is not CryptoVersion.CLIENT_MVK_V2:
            raise InvalidOpaqueEnvelope("opaque envelopes require client_mvk_v2")
        if self.cipher_suite is not CipherSuite.XCHACHA20_POLY1305_IETF_V1:
            raise InvalidOpaqueEnvelope("cipher suite is not valid for client_mvk_v2")
        for name in _B64_FIELDS:
            _require_canonical_b64(name, getattr(self, name))
        if self.migrated_at is not None and self.migrated_at.tzinfo is None:
            raise InvalidOpaqueEnvelope("migrated_at must be timezone-aware")
        for name, value in self.blind_indexes.items():
            if not name or len(name) > 64 or not value or len(value) > 512:
                raise InvalidOpaqueEnvelope("blind index metadata is invalid")

    def opaque_storage_fields(self) -> dict[str, object]:
        """Return storage-safe fields without exposing a decrypt operation."""

        return {
            "crypto_version": self.crypto_version.value,
            "cipher_suite": self.cipher_suite.value,
            "key_domain": self.key_domain.value,
            "nonce_b64": self.nonce_b64,
            "ciphertext_b64": self.ciphertext_b64,
            "authentication_tag_b64": self.authentication_tag_b64,
            "migration_state": self.migration_state.value,
            "verification_state": self.verification_state.value,
            "migrated_at": self.migrated_at,
            "blind_indexes": dict(self.blind_indexes),
        }


def assert_no_downgrade(source: CryptoVersion, target: CryptoVersion) -> None:
    if source is CryptoVersion.CLIENT_MVK_V2 and target is CryptoVersion.LEGACY_V1:
        raise CryptoDowngradeRejected("client_mvk_v2 cannot be written as legacy_v1")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
