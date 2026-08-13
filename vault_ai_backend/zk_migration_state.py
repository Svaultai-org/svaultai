"""Crash-safe item-level state machine for the opt-in ZK v2 migration.

The coordinator is storage-agnostic and uses compare-and-swap semantics.  A
database adapter can persist the same contract without placing secrets in the
journal.  This module does not enumerate or migrate a vault on login.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from zk_migration_contracts import (
    CryptoVersion,
    KeyDomain,
    MigrationState,
    VerificationState,
    utcnow,
)


class MigrationConflict(RuntimeError):
    code = "migration_state_conflict"


class InvalidMigrationTransition(RuntimeError):
    code = "invalid_migration_transition"


_SAFE_ERROR_CATEGORIES = {
    "client_upload_failed",
    "client_verification_failed",
    "interrupted",
    "storage_conflict",
    "unsupported_crypto_version",
    "unknown",
}


@dataclass(frozen=True)
class ItemRef:
    vault_id: UUID
    domain: KeyDomain
    record_id: str

    def __post_init__(self) -> None:
        if not self.record_id or len(self.record_id) > 512:
            raise ValueError("record_id is required and must be bounded")


@dataclass(frozen=True)
class MigrationJournalEntry:
    item: ItemRef
    operation_id: UUID
    source_version: CryptoVersion
    target_version: CryptoVersion
    state: MigrationState
    verification_state: VerificationState
    attempt: int
    legacy_retained: bool
    envelope_id: UUID | None
    error_category: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.source_version is not CryptoVersion.LEGACY_V1:
            raise ValueError("migration source must be legacy_v1")
        if self.target_version is not CryptoVersion.CLIENT_MVK_V2:
            raise ValueError("migration target must be client_mvk_v2")
        if self.attempt < 1:
            raise ValueError("attempt must be positive")
        if not self.legacy_retained:
            raise ValueError("initial migration requires the legacy item")
        if self.error_category not in _SAFE_ERROR_CATEGORIES | {None}:
            raise ValueError("error category is not journal-safe")


class MigrationJournal(Protocol):
    def get(self, item: ItemRef) -> MigrationJournalEntry | None: ...

    def compare_and_swap(
        self,
        item: ItemRef,
        expected: MigrationJournalEntry | None,
        replacement: MigrationJournalEntry,
    ) -> MigrationJournalEntry: ...


class InMemoryMigrationJournal:
    """Deterministic synthetic journal used by tests and local characterization."""

    def __init__(self) -> None:
        self._entries: dict[ItemRef, MigrationJournalEntry] = {}
        self._lock = RLock()

    def get(self, item: ItemRef) -> MigrationJournalEntry | None:
        with self._lock:
            return self._entries.get(item)

    def compare_and_swap(
        self,
        item: ItemRef,
        expected: MigrationJournalEntry | None,
        replacement: MigrationJournalEntry,
    ) -> MigrationJournalEntry:
        with self._lock:
            current = self._entries.get(item)
            if current != expected:
                raise MigrationConflict("journal changed during item transition")
            self._entries[item] = replacement
            return replacement


class MigrationCoordinator:
    """Idempotent per-item transitions; legacy content is always retained."""

    def __init__(self, journal: MigrationJournal) -> None:
        self._journal = journal

    def begin(self, item: ItemRef, *, operation_id: UUID | None = None) -> MigrationJournalEntry:
        current = self._journal.get(item)
        if current is not None:
            if operation_id is None or operation_id == current.operation_id:
                return current
            if current.state not in {MigrationState.ROLLED_BACK, MigrationState.MIGRATION_FAILED}:
                raise MigrationConflict("item already has an active migration")
            now = utcnow()
            replacement = replace(
                current,
                operation_id=operation_id,
                state=MigrationState.MIGRATION_PENDING,
                verification_state=VerificationState.NOT_VERIFIED,
                attempt=current.attempt + 1,
                envelope_id=None,
                error_category=None,
                updated_at=now,
            )
            return self._journal.compare_and_swap(item, current, replacement)

        now = utcnow()
        entry = MigrationJournalEntry(
            item=item,
            operation_id=operation_id or uuid4(),
            source_version=CryptoVersion.LEGACY_V1,
            target_version=CryptoVersion.CLIENT_MVK_V2,
            state=MigrationState.MIGRATION_PENDING,
            verification_state=VerificationState.NOT_VERIFIED,
            attempt=1,
            legacy_retained=True,
            envelope_id=None,
            error_category=None,
            created_at=now,
            updated_at=now,
        )
        return self._journal.compare_and_swap(item, None, entry)

    def record_v2_upload(self, item: ItemRef, envelope_id: UUID) -> MigrationJournalEntry:
        current = self._required(item)
        if current.state is MigrationState.V2_WRITTEN and current.envelope_id == envelope_id:
            return current
        if current.state not in {MigrationState.MIGRATION_PENDING, MigrationState.MIGRATION_FAILED}:
            raise InvalidMigrationTransition("v2 upload is not valid in the current state")
        return self._replace(
            current,
            state=MigrationState.V2_WRITTEN,
            envelope_id=envelope_id,
            error_category=None,
        )

    def record_verification(self, item: ItemRef, *, verified: bool) -> MigrationJournalEntry:
        current = self._required(item)
        target_state = MigrationState.V2_VERIFIED if verified else MigrationState.VERIFICATION_FAILED
        target_verification = (
            VerificationState.CLIENT_VERIFIED
            if verified
            else VerificationState.VERIFICATION_FAILED
        )
        if current.state is target_state:
            return current
        if current.state is not MigrationState.V2_WRITTEN:
            raise InvalidMigrationTransition("verification requires a written v2 envelope")
        return self._replace(
            current,
            state=target_state,
            verification_state=target_verification,
            error_category=None if verified else "client_verification_failed",
        )

    def finalize(self, item: ItemRef) -> MigrationJournalEntry:
        current = self._required(item)
        if current.state is MigrationState.MIGRATED:
            return current
        if current.state is not MigrationState.V2_VERIFIED:
            raise InvalidMigrationTransition("finalization requires client verification")
        return self._replace(current, state=MigrationState.MIGRATED)

    def fail(self, item: ItemRef, error_category: str) -> MigrationJournalEntry:
        if error_category not in _SAFE_ERROR_CATEGORIES:
            raise ValueError("error category is not journal-safe")
        current = self._required(item)
        if current.state in {MigrationState.ROLLED_BACK, MigrationState.ROLLBACK_PENDING}:
            raise InvalidMigrationTransition("a rollback cannot become migration_failed")
        if current.state is MigrationState.MIGRATION_FAILED and current.error_category == error_category:
            return current
        return self._replace(
            current,
            state=MigrationState.MIGRATION_FAILED,
            error_category=error_category,
        )

    def rollback(self, item: ItemRef) -> MigrationJournalEntry:
        current = self._required(item)
        if current.state is MigrationState.ROLLED_BACK:
            return current
        if not current.legacy_retained:
            raise InvalidMigrationTransition("legacy content is unavailable for rollback")
        pending = self._replace(current, state=MigrationState.ROLLBACK_PENDING)
        return self._replace(
            pending,
            state=MigrationState.ROLLED_BACK,
            verification_state=VerificationState.NOT_VERIFIED,
            error_category=None,
        )

    def _required(self, item: ItemRef) -> MigrationJournalEntry:
        entry = self._journal.get(item)
        if entry is None:
            raise InvalidMigrationTransition("migration has not started for this item")
        return entry

    def _replace(self, current: MigrationJournalEntry, **changes: object) -> MigrationJournalEntry:
        replacement = replace(current, updated_at=utcnow(), **changes)
        return self._journal.compare_and_swap(current.item, current, replacement)
