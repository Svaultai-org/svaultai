from __future__ import annotations

import importlib
import logging
from typing import Any, Optional

import pytest

import durable_personal_memory as dpm
from vault_core import derive_key, decrypt_message, KDF_TARGET_ITERATIONS


_KEY = derive_key(
    "1234",
    "dmF1bHRhaS1tZW1vcnktdGVzdA==",
    iterations=KDF_TARGET_ITERATIONS,
)


class _MemoryCursor:
    def __init__(self, store: "_MemoryStore"):
        self.store = store
        self.last: Any = None
        self.rowcount = 0

    def execute(self, sql: str, params: tuple = ()):
        if self.store.fail_writes and sql.lstrip().lower().startswith("insert"):
            raise RuntimeError("write failed")
        low = " ".join(sql.lower().split())
        if low.startswith("select id, payload_ciphertext"):
            vault_id, digest = params
            self.last = self.store.find_active(vault_id, digest)
            return
        if low.startswith("insert into vault_ai_memory"):
            vault_id, memory_type, payload_ct, lookup_hash = params
            row = self.store.insert(
                vault_id=vault_id,
                memory_type=memory_type,
                event_date=None,
                payload_ciphertext=payload_ct,
                memory_lookup_hash=lookup_hash,
            )
            self.last = (row["id"],)
            self.rowcount = 1
            return
        if low.startswith("update vault_ai_memory"):
            self.rowcount = self.store.update(low, params)
            self.last = None
            return
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self.last


class _MemoryConn:
    def __init__(self, store: "_MemoryStore"):
        self.store = store

    def cursor(self, cursor_factory=None):
        return _MemoryCursor(self.store)

    def commit(self):
        self.store.commits += 1

    def rollback(self):
        self.store.rollbacks += 1

    def close(self):
        pass


class _MemoryStore:
    def __init__(self):
        self.rows: list[dict] = []
        self.next_id = 1
        self.commits = 0
        self.rollbacks = 0
        self.fail_writes = False

    def get_db(self):
        return _MemoryConn(self)

    def find_active(self, vault_id: str, digest: bytes) -> Optional[tuple]:
        matches = [
            r for r in self.rows
            if r["vault_id"] == vault_id
            and r["memory_lookup_hash"] == digest
            and r.get("superseded_at") is None
        ]
        if not matches:
            return None
        row = matches[-1]
        return (
            row["id"],
            row["payload_ciphertext"],
            None,
            None,
        )

    def insert(self, **kwargs):
        row = {
            "id": self.next_id,
            "memory_key": None,
            "memory_value": None,
            "superseded_at": None,
            "superseded_by_id": None,
            **kwargs,
        }
        self.next_id += 1
        self.rows.append(row)
        return row

    def update(self, sql: str, params: tuple) -> int:
        if "set updated_at=now()" in sql:
            return 1
        if len(params) == 2:
            row_id, vault_id = params
            for row in self.rows:
                if row["id"] == row_id and row["vault_id"] == vault_id:
                    row["superseded_at"] = "now"
                    return 1
            return 0
        if len(params) == 3:
            new_id, prior_id, vault_id = params
            for row in self.rows:
                if row["id"] == prior_id and row["vault_id"] == vault_id:
                    row["superseded_at"] = "now"
                    row["superseded_by_id"] = new_id
                    return 1
            return 0
        return 0

    def active_rows(self, vault_id: str) -> list[dict]:
        return [
            row for row in self.rows
            if row["vault_id"] == vault_id and row.get("superseded_at") is None
        ]


@pytest.fixture()
def memory_store(monkeypatch):
    store = _MemoryStore()
    monkeypatch.setattr(dpm, "get_db", store.get_db)
    return store


def _handle(store: _MemoryStore, message: str, *, vault_id: str = "vault-a") -> str:
    reply = dpm.handle_personal_memory_turn(
        vault_id=vault_id,
        key=_KEY,
        message=message,
        source_message_id="test-msg",
    )
    assert reply is not None
    return reply


def _payload(row: dict) -> dict:
    blob = row["payload_ciphertext"]
    text = (blob.tobytes() if isinstance(blob, memoryview) else blob).decode("utf-8")
    decoded = dpm.json.loads(decrypt_message(text, _KEY))
    assert isinstance(decoded, dict)
    return decoded


def _assert_no_plaintext_birthday_storage(store: _MemoryStore) -> None:
    forbidden_text = (
        "January 30, 1965",
        "January 31, 1965",
        "1965-01-30",
        "1965-01-31",
    )
    forbidden_bytes = tuple(v.encode("utf-8") for v in forbidden_text)
    for row in store.rows:
        assert row["memory_key"] is None
        assert row["memory_value"] is None
        assert row["event_date"] is None
        assert row.get("memory_normalized_key") is None
        for value in forbidden_text:
            assert value not in str(row.get("memory_key"))
            assert value not in str(row.get("memory_value"))
            assert value not in str(row.get("event_date"))
        for value in forbidden_bytes:
            assert value not in row["payload_ciphertext"]


def test_save_and_immediate_recall_exact_reproduction(memory_store):
    reply = _handle(
        memory_store,
        "remember my mom birthday is 30th january 1965",
    )
    assert "Saved" in reply
    assert "January 30, 1965" in reply

    active = memory_store.active_rows("vault-a")
    assert len(active) == 1
    row = active[0]
    assert row["memory_key"] is None
    assert row["memory_value"] is None
    assert row["event_date"] is None
    assert b"January" not in row["payload_ciphertext"]
    assert b"mom" not in row["payload_ciphertext"].lower()
    _assert_no_plaintext_birthday_storage(memory_store)

    recall = _handle(memory_store, "when is my mom's birthday")
    assert "January 30, 1965" in recall


def test_aliases_recall_the_same_structured_fact(memory_store):
    _handle(memory_store, "remember my mom birthday is January 30, 1965")
    assert "January 30, 1965" in _handle(
        memory_store, "when is my mother date of birth"
    )
    assert "January 30, 1965" in _handle(
        memory_store, "what is my mum dob"
    )


def test_save_this_about_me_with_colon(memory_store):
    reply = _handle(
        memory_store,
        "save this about me: my mother date of birth is 30 January 1965",
    )
    assert "Saved" in reply
    assert "January 30, 1965" in _handle(
        memory_store, "when is my mom's birthday"
    )


def test_duplicate_save_does_not_create_duplicate_active_records(memory_store):
    _handle(memory_store, "remember my mom birthday is January 30, 1965")
    reply = _handle(memory_store, "remember my mother's birthday is 1965-01-30")
    assert "already have" in reply.lower()
    assert len(memory_store.active_rows("vault-a")) == 1


def test_clear_correction_replaces_the_canonical_fact(memory_store):
    _handle(memory_store, "remember my mom birthday is January 30, 1965")
    reply = _handle(memory_store, "my mom's birthday is actually January 31 1965")
    assert "Updated" in reply
    assert len(memory_store.active_rows("vault-a")) == 1
    assert all(row["event_date"] is None for row in memory_store.rows)
    _assert_no_plaintext_birthday_storage(memory_store)
    recall = _handle(memory_store, "when is my mom's birthday")
    assert "January 31, 1965" in recall
    assert "January 30, 1965" not in recall
    assert _payload(memory_store.active_rows("vault-a")[0])["normalized_value"] == "1965-01-31"


def test_conflicting_non_correction_does_not_overwrite(memory_store):
    _handle(memory_store, "remember my mom birthday is January 30, 1965")
    reply = _handle(memory_store, "remember my mom birthday is January 31, 1965")
    assert "I already have" in reply
    assert len(memory_store.active_rows("vault-a")) == 1
    recall = _handle(memory_store, "when is my mom's birthday")
    assert "January 30, 1965" in recall


def test_forget_tombstones_fact(memory_store):
    _handle(memory_store, "remember my mom birthday is January 30, 1965")
    reply = _handle(memory_store, "forget my mom's birthday")
    assert "Forgot" in reply
    recall = _handle(memory_store, "when is my mom's birthday")
    assert "don't have" in recall
    _assert_no_plaintext_birthday_storage(memory_store)


def test_vault_isolation(memory_store):
    _handle(
        memory_store,
        "remember my mom birthday is January 30, 1965",
        vault_id="vault-a",
    )
    recall = _handle(memory_store, "when is my mom's birthday", vault_id="vault-b")
    assert "don't have" in recall


def test_recall_survives_backend_restart_without_event_date_or_index(memory_store):
    _handle(memory_store, "remember my mom birthday is January 30, 1965")
    memory_store.commits = 0
    memory_store.rollbacks = 0

    recall = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="when is my mom's birthday",
        source_message_id="after-restart",
    )

    assert recall == "Your mom's birthday is January 30, 1965."
    assert memory_store.commits == 0
    assert memory_store.rollbacks == 0
    _assert_no_plaintext_birthday_storage(memory_store)


def test_failed_write_does_not_claim_saved_or_log_plaintext(memory_store, caplog):
    memory_store.fail_writes = True
    caplog.set_level(logging.WARNING)
    reply = _handle(memory_store, "remember my mom birthday is January 30, 1965")
    assert "couldn't save" in reply.lower()
    assert memory_store.rows == []
    assert memory_store.rollbacks == 1
    logs = caplog.text.lower()
    assert "january" not in logs
    assert "mom" not in logs


def test_db_connection_failure_returns_memory_error(monkeypatch, caplog):
    def fail_get_db():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(dpm, "get_db", fail_get_db)
    caplog.set_level(logging.WARNING)
    reply = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="remember my mom birthday is January 30, 1965",
        source_message_id="test-msg",
    )
    assert reply == "I couldn't save that memory. Please try again."
    assert "january" not in caplog.text.lower()
    assert "mom" not in caplog.text.lower()


def test_forward_migration_clears_only_plaintext_event_date(monkeypatch):
    migration = importlib.import_module(
        "migrations.versions.0032_clear_durable_personal_memory_event_date"
    )
    executed: list[str] = []
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()
    migration.downgrade()

    assert len(executed) == 1
    sql = " ".join(executed[0].lower().split())
    assert sql.startswith("update vault_ai_memory set event_date = null")
    assert "memory_type = 'date'" in sql
    assert "memory_key is null" in sql
    assert "memory_value is null" in sql
    assert "payload_ciphertext is not null" in sql
    assert "memory_lookup_hash is not null" in sql
    assert "event_date is not null" in sql
    assert "payload_ciphertext =" not in sql
    assert "memory_lookup_hash =" not in sql
    assert "vault_id =" not in sql


def test_exact_memory_route_handles_chat_endpoint_before_ai_planner(monkeypatch):
    from test_chat_endpoint_deterministic_2026_08_01 import (
        _ChatEndpointHarness,
        _TEST_VAULT_ID,
    )

    store = _MemoryStore()
    harness = _ChatEndpointHarness()
    harness.setUp()
    try:
        harness._patch("durable_personal_memory.get_db", side_effect=store.get_db)
        harness.arm_planner_sentinel()

        save = harness.post_message(
            "remember my mom birthday is 30th january 1965"
        )
        assert save.http_status == 200, save.summary()
        assert save.x_chat_path == "personal_memory", save.summary()
        assert not save.planner_invoked, save.summary()
        assert "January 30, 1965" in (save.envelope_json or "")
        assert len(store.active_rows(_TEST_VAULT_ID)) == 1
        assert store.active_rows(_TEST_VAULT_ID)[0]["event_date"] is None

        recall = harness.post_message("when is my mom's birthday")
        assert recall.http_status == 200, recall.summary()
        assert recall.x_chat_path == "personal_memory", recall.summary()
        assert not recall.planner_invoked, recall.summary()
        assert "January 30, 1965" in (recall.envelope_json or "")

        corrected = harness.post_message(
            "my mom's birthday is actually January 31 1965"
        )
        assert corrected.http_status == 200, corrected.summary()
        assert corrected.x_chat_path == "personal_memory", corrected.summary()
        assert not corrected.planner_invoked, corrected.summary()
        assert "January 31, 1965" in (corrected.envelope_json or "")
        assert len(store.active_rows(_TEST_VAULT_ID)) == 1
        assert all(row["event_date"] is None for row in store.rows)

        recall_after_restart = harness.post_message(
            "when is my mother's date of birth"
        )
        assert recall_after_restart.http_status == 200, recall_after_restart.summary()
        assert recall_after_restart.x_chat_path == "personal_memory"
        assert "January 31, 1965" in (recall_after_restart.envelope_json or "")

        isolated = dpm.handle_personal_memory_turn(
            vault_id="vault-b",
            key=_KEY,
            message="when is my mom's birthday",
            source_message_id="vault-b",
        )
        assert isolated is not None
        assert "don't have" in isolated

        forgot = harness.post_message("forget my mom's birthday")
        assert forgot.http_status == 200, forgot.summary()
        assert forgot.x_chat_path == "personal_memory", forgot.summary()
        assert not forgot.planner_invoked, forgot.summary()
        assert "Forgot" in (forgot.envelope_json or "")

        after_forget = harness.post_message("when is my mom's birthday")
        assert after_forget.http_status == 200, after_forget.summary()
        assert after_forget.x_chat_path == "personal_memory"
        assert "don't have" in (after_forget.envelope_json or "")
        _assert_no_plaintext_birthday_storage(store)
    finally:
        harness.tearDown()
