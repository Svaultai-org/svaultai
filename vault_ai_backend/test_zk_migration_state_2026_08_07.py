from __future__ import annotations

from uuid import uuid4

import pytest

from zk_migration_contracts import KeyDomain, MigrationState, VerificationState
from zk_migration_state import (
    InMemoryMigrationJournal,
    InvalidMigrationTransition,
    ItemRef,
    MigrationConflict,
    MigrationCoordinator,
)


def _item(domain: KeyDomain = KeyDomain.FILE) -> ItemRef:
    return ItemRef(vault_id=uuid4(), domain=domain, record_id="synthetic-record")


def _coordinator() -> tuple[MigrationCoordinator, InMemoryMigrationJournal]:
    journal = InMemoryMigrationJournal()
    return MigrationCoordinator(journal), journal


def test_happy_path_retains_legacy_after_finalization() -> None:
    coordinator, _ = _coordinator()
    item = _item()
    assert coordinator.begin(item).state is MigrationState.MIGRATION_PENDING
    assert coordinator.record_v2_upload(item, uuid4()).state is MigrationState.V2_WRITTEN
    verified = coordinator.record_verification(item, verified=True)
    assert verified.state is MigrationState.V2_VERIFIED
    assert verified.verification_state is VerificationState.CLIENT_VERIFIED
    migrated = coordinator.finalize(item)
    assert migrated.state is MigrationState.MIGRATED
    assert migrated.legacy_retained is True


def test_crash_after_v2_upload_is_resumable() -> None:
    coordinator, journal = _coordinator()
    item = _item()
    operation = uuid4()
    envelope = uuid4()
    coordinator.begin(item, operation_id=operation)
    coordinator.record_v2_upload(item, envelope)

    resumed = MigrationCoordinator(journal)
    assert resumed.begin(item, operation_id=operation).state is MigrationState.V2_WRITTEN
    assert resumed.record_v2_upload(item, envelope).envelope_id == envelope
    assert resumed.record_verification(item, verified=True).state is MigrationState.V2_VERIFIED


def test_crash_after_verification_is_resumable_and_idempotent() -> None:
    coordinator, journal = _coordinator()
    item = _item()
    operation = uuid4()
    coordinator.begin(item, operation_id=operation)
    coordinator.record_v2_upload(item, uuid4())
    coordinator.record_verification(item, verified=True)

    resumed = MigrationCoordinator(journal)
    assert resumed.begin(item, operation_id=operation).state is MigrationState.V2_VERIFIED
    assert resumed.record_verification(item, verified=True).state is MigrationState.V2_VERIFIED
    assert resumed.finalize(item).state is MigrationState.MIGRATED
    assert resumed.finalize(item).state is MigrationState.MIGRATED


def test_duplicate_begin_is_safe_but_different_active_operation_conflicts() -> None:
    coordinator, _ = _coordinator()
    item = _item()
    operation = uuid4()
    first = coordinator.begin(item, operation_id=operation)
    assert coordinator.begin(item, operation_id=operation) == first
    with pytest.raises(MigrationConflict):
        coordinator.begin(item, operation_id=uuid4())


@pytest.mark.parametrize(
    "advance",
    [
        lambda c, i: None,
        lambda c, i: c.record_v2_upload(i, uuid4()),
        lambda c, i: (c.record_v2_upload(i, uuid4()), c.record_verification(i, verified=True)),
        lambda c, i: (c.record_v2_upload(i, uuid4()), c.record_verification(i, verified=True), c.finalize(i)),
    ],
)
def test_rollback_is_available_at_every_initial_phase(advance) -> None:
    coordinator, _ = _coordinator()
    item = _item()
    coordinator.begin(item)
    advance(coordinator, item)
    rolled_back = coordinator.rollback(item)
    assert rolled_back.state is MigrationState.ROLLED_BACK
    assert rolled_back.legacy_retained is True
    assert coordinator.rollback(item) == rolled_back


def test_partial_vault_rollback_does_not_change_other_items() -> None:
    coordinator, journal = _coordinator()
    vault_id = uuid4()
    first = ItemRef(vault_id, KeyDomain.FILE, "file-1")
    second = ItemRef(vault_id, KeyDomain.CREDENTIAL, "credential-1")
    coordinator.begin(first)
    coordinator.record_v2_upload(first, uuid4())
    coordinator.begin(second)
    coordinator.record_v2_upload(second, uuid4())
    coordinator.record_verification(second, verified=True)

    coordinator.rollback(first)
    assert journal.get(first).state is MigrationState.ROLLED_BACK
    assert journal.get(second).state is MigrationState.V2_VERIFIED


def test_failed_item_can_retry_with_new_operation() -> None:
    coordinator, _ = _coordinator()
    item = _item()
    first = coordinator.begin(item)
    failed = coordinator.fail(item, "interrupted")
    assert failed.state is MigrationState.MIGRATION_FAILED
    retried = coordinator.begin(item, operation_id=uuid4())
    assert retried.attempt == first.attempt + 1
    assert retried.state is MigrationState.MIGRATION_PENDING


def test_verification_failure_rolls_back_and_never_finalizes() -> None:
    coordinator, _ = _coordinator()
    item = _item()
    coordinator.begin(item)
    coordinator.record_v2_upload(item, uuid4())
    failed = coordinator.record_verification(item, verified=False)
    assert failed.state is MigrationState.VERIFICATION_FAILED
    with pytest.raises(InvalidMigrationTransition):
        coordinator.finalize(item)
    assert coordinator.rollback(item).state is MigrationState.ROLLED_BACK


def test_journal_rejects_secret_like_arbitrary_error_text() -> None:
    coordinator, _ = _coordinator()
    item = _item()
    coordinator.begin(item)
    with pytest.raises(ValueError):
        coordinator.fail(item, "PIN 1234 failed")
