from __future__ import annotations

import logging
from typing import Any, Optional

import pytest

import durable_personal_memory as dpm
from vault_core import derive_key, KDF_TARGET_ITERATIONS


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
            vault_id, memory_type, event_date, payload_ct, lookup_hash = params
            row = self.store.insert(
                vault_id=vault_id,
                memory_type=memory_type,
                event_date=event_date,
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
            row["event_date"],
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
    assert b"January" not in row["payload_ciphertext"]
    assert b"mom" not in row["payload_ciphertext"].lower()

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
    reply = _handle(memory_store, "my mom's birthday is actually January 31, 1965")
    assert "Updated" in reply
    assert len(memory_store.active_rows("vault-a")) == 1
    recall = _handle(memory_store, "when is my mom's birthday")
    assert "January 31, 1965" in recall
    assert "January 30, 1965" not in recall


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


def test_vault_isolation(memory_store):
    _handle(
        memory_store,
        "remember my mom birthday is January 30, 1965",
        vault_id="vault-a",
    )
    recall = _handle(memory_store, "when is my mom's birthday", vault_id="vault-b")
    assert "don't have" in recall


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


def test_exact_memory_route_handles_chat_endpoint_before_ai_planner(monkeypatch):
    from test_chat_endpoint_deterministic_2026_08_01 import _ChatEndpointHarness

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

        recall = harness.post_message("when is my mom's birthday")
        assert recall.http_status == 200, recall.summary()
        assert recall.x_chat_path == "personal_memory", recall.summary()
        assert not recall.planner_invoked, recall.summary()
        assert "January 30, 1965" in (recall.envelope_json or "")
    finally:
        harness.tearDown()
