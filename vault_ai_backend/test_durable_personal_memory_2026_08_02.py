from __future__ import annotations

import importlib
import logging
from typing import Any, Optional

import pytest

import durable_personal_memory as dpm


def test_general_conversation_context_never_becomes_memory_intent():
    envelope = (
        "Continue this ordinary conversation without searching the vault.\n"
        "Previous user message: I am choosing between two job offers.\n"
        "Previous assistant response: Save money, but consider balance.\n"
        "Current user follow-up: Now give me the strongest counterargument."
    )

    assert dpm.parse_personal_memory_intent(envelope) is None
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
        self.rows: list[Any] = []
        self.rowcount = 0

    def execute(self, sql: str, params: tuple = ()):
        if self.store.fail_writes and sql.lstrip().lower().startswith("insert"):
            raise RuntimeError("write failed")
        low = " ".join(sql.lower().split())
        if low.startswith("select id, payload_ciphertext"):
            vault_id, digest = params
            self.last = self.store.find_active(vault_id, digest)
            return
        if low.startswith("select id, memory_type, payload_ciphertext"):
            if "where id=%s" in low:
                row_id, vault_id = params
                self.last = self.store.find_active_by_id(vault_id, row_id)
            else:
                vault_id = params[0]
                limit = params[1] if len(params) > 1 else 500
                self.rows = self.store.fetch_active_rows(vault_id, limit=limit)
                self.last = None
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

    def fetchall(self):
        return self.rows


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

    def find_active_by_id(self, vault_id: str, row_id: int) -> Optional[tuple]:
        for row in self.rows:
            if (
                row["vault_id"] == vault_id
                and row["id"] == row_id
                and row.get("superseded_at") is None
            ):
                return (
                    row["id"],
                    row["memory_type"],
                    row["payload_ciphertext"],
                    None,
                    None,
                )
        return None

    def fetch_active_rows(self, vault_id: str, *, limit: int = 500) -> list[tuple]:
        out = []
        for row in self.active_rows(vault_id)[: int(limit)]:
            out.append((
                row["id"],
                row["memory_type"],
                row["payload_ciphertext"],
                None,
                None,
            ))
        return out


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


def _assert_plaintext_absent_from_persistent_columns(
    store: _MemoryStore,
    forbidden: list[str],
) -> None:
    forbidden_bytes = [v.encode("utf-8") for v in forbidden]
    for row in store.rows:
        assert row["memory_key"] is None
        assert row["memory_value"] is None
        assert row["event_date"] is None
        assert row.get("memory_normalized_key") is None
        for value in forbidden:
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


def test_birthday_without_year_is_complete_useful_memory(memory_store):
    proposal = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my mother's birthday is Feb 6",
        source_message_id="proposal-msg",
        session_id="session-a",
    )
    assert proposal is not None
    decoded = dpm.json.loads(proposal)
    data = decoded["card"]["data"]
    assert data["title"] == "Mother's birthday"
    assert data["value"] == "February 6"
    assert data["event_date"] == "--02-06"

    saved = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="save-msg",
        session_id="session-a",
    )
    assert saved is not None
    assert "February 6" in saved
    recall = _handle(memory_store, "when is my mother's birthday")
    assert "February 6" in recall
    assert "missing details" not in saved.lower()
    assert all(row["event_date"] is None for row in memory_store.rows)


def test_missing_detail_followup_uses_active_memory_context(memory_store):
    reply = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my mom birthday is blursday",
        source_message_id="proposal-msg",
        session_id="session-a",
    )
    assert reply == "What month and day should I save for your mom's birthday?"
    followup = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="what is the missing details",
        source_message_id="followup-msg",
        session_id="session-a",
    )
    assert followup == reply


def test_save_this_about_me_with_colon(memory_store):
    reply = _handle(
        memory_store,
        "save this about me: my mother date of birth is 30 January 1965",
    )
    assert "Saved" in reply
    assert "January 30, 1965" in _handle(
        memory_store, "when is my mom's birthday"
    )


def test_travel_recall_variants_do_not_route_to_files(memory_store):
    saved = _handle(memory_store, "remember I traveled to the USA on April 7, 2026")
    assert "Saved" in saved
    for question in (
        "when was my travel to the USA",
        "when was my trip to USA",
        "what date was my USA trip",
        "when did I travel to the USA",
    ):
        reply = _handle(memory_store, question)
        assert "April 7, 2026" in reply
        assert "file" not in reply.lower()


def test_name_address_variants_recall_same_identity(memory_store):
    _handle(memory_store, "remember my name is Earl")
    assert _handle(memory_store, "what is my name") == "Your name is Earl."
    assert _handle(memory_store, "how do you address me") == (
        "I'll address you as Earl."
    )
    assert _handle(memory_store, "what should you call me") == (
        "I'll address you as Earl."
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


def test_bare_memory_statement_returns_structured_proposal_not_plain_save(memory_store):
    proposal = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my dad birthday is 12/12/1975",
        source_message_id="proposal-msg",
        session_id="session-a",
    )
    assert proposal is not None
    decoded = dpm.json.loads(proposal)
    assert decoded["type"] == "vault_chat_card"
    assert decoded["intent"] == "vault_memory_save_proposal"
    assert decoded["card"]["cardType"] == "vault_memory_proposal_card"
    data = decoded["card"]["data"]
    assert data["title"] == "Dad's birthday"
    assert data["value"] == "December 12, 1975"
    assert data["event_date"] == "1975-12-12"
    assert data["actions"] == ["save", "edit", "cancel"]
    assert memory_store.active_rows("vault-a") == []


def test_save_it_persists_current_memory_proposal(memory_store):
    dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my dad birthday is 12/12/1975",
        source_message_id="proposal-msg",
        session_id="session-a",
    )
    saved = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="save-msg",
        session_id="session-a",
    )
    assert saved is not None
    assert "Saved" in saved
    assert "December 12, 1975" in saved
    assert len(memory_store.active_rows("vault-a")) == 1
    recall = _handle(memory_store, "when is my dad's birthday")
    assert "December 12, 1975" in recall
    _assert_plaintext_absent_from_persistent_columns(
        memory_store,
        ["December 12, 1975", "1975-12-12"],
    )


def test_pending_memory_proposal_helper_tracks_current_session(memory_store):
    assert not dpm.has_pending_memory_proposal("vault-a", "session-a")
    dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my name is Kola",
        source_message_id="proposal-msg",
        session_id="session-a",
    )

    assert dpm.has_pending_memory_proposal("vault-a", "session-a")
    assert not dpm.has_pending_memory_proposal("vault-a", "session-b")

    saved = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="save-msg",
        session_id="session-a",
    )
    assert saved is not None
    assert not dpm.has_pending_memory_proposal("vault-a", "session-a")


def test_bare_save_it_without_memory_proposal_does_not_steal_other_flows(memory_store):
    for text in (
        "save it",
        "Save it.",
        "SAVE IT!",
        "save that?",
        "save this",
        "save the memory",
        "remember it.",
        "save memory",
    ):
        reply = dpm.handle_personal_memory_turn(
            vault_id="vault-a",
            key=_KEY,
            message=text,
            source_message_id="no-proposal",
            session_id="session-a",
        )
        assert reply == "There isn't a memory waiting to be saved."
    assert memory_store.active_rows("vault-a") == []


def test_generic_forget_does_not_steal_active_object_pronouns(memory_store):
    for text in ("delete it", "remove this", "forget that"):
        assert dpm.handle_personal_memory_turn(
            vault_id="vault-a",
            key=_KEY,
            message=text,
            source_message_id="active-object",
            session_id="session-a",
        ) is None


def test_maiden_name_proposal_save_recall_update_and_forget(memory_store):
    proposal = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my mother maiden name is Lodato",
        source_message_id="maiden-proposal",
        session_id="session-a",
    )
    assert proposal is not None
    assert "vault_memory_proposal_card" in proposal
    saved = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="maiden-save",
        session_id="session-a",
    )
    assert "Saved" in (saved or "")
    assert "Lodato" in _handle(memory_store, "what is my mother's maiden name")
    updated = _handle(memory_store, "my mother's maiden name is actually Rossi")
    assert "Updated" in updated
    assert "Rossi" in _handle(memory_store, "what is my mother maiden name")
    forgot = _handle(memory_store, "forget my mother's maiden name")
    assert "Forgot" in forgot
    assert "don't have" in _handle(memory_store, "what is my mother maiden name")
    _assert_plaintext_absent_from_persistent_columns(
        memory_store,
        ["Lodato", "Rossi"],
    )


def test_self_name_proposal_save_recall_restart_and_forget(memory_store):
    proposal = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my name is Kola",
        source_message_id="name-proposal",
        session_id="session-a",
    )
    assert proposal is not None
    decoded = dpm.json.loads(proposal)
    assert decoded["type"] == "vault_chat_card"
    assert decoded["intent"] == "vault_memory_save_proposal"
    data = decoded["card"]["data"]
    assert data["title"] == "Your name"
    assert data["value"] == "Kola"
    assert data["attribute"] == "display_name"
    assert memory_store.active_rows("vault-a") == []

    saved = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="name-save",
        session_id="session-a",
    )
    assert "Saved" in (saved or "")
    assert "Kola" in _handle(memory_store, "what is my name")

    restarted = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="what is my name?",
        source_message_id="name-after-restart",
    )
    assert restarted == "Your name is Kola."

    forgot = _handle(memory_store, "forget my name")
    assert "Forgot" in forgot
    assert "don't have" in _handle(memory_store, "what is my name")
    _assert_plaintext_absent_from_persistent_columns(
        memory_store,
        ["Kola", "display_name"],
    )


def test_self_name_proposal_save_replaces_existing_display_name(memory_store):
    dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my name is Earl",
        source_message_id="old-name-proposal",
        session_id="session-a",
    )
    saved_old = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="old-name-save",
        session_id="session-a",
    )
    assert "Saved" in (saved_old or "")
    assert "Earl" in _handle(memory_store, "what is my name")

    dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="my name is Kola",
        source_message_id="new-name-proposal",
        session_id="session-a",
    )
    saved_new = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="new-name-save",
        session_id="session-a",
    )
    assert "Updated" in (saved_new or "")
    assert _handle(memory_store, "what is my name") == "Your name is Kola."
    assert len(memory_store.active_rows("vault-a")) == 1


def test_self_name_replacement_preserves_unrelated_and_other_vault(memory_store):
    _handle(memory_store, "remember my favorite place is Los Angeles")
    _handle(memory_store, "remember my name is Earl")
    _handle(memory_store, "remember my name is Kola.")
    _handle(memory_store, "remember my name is Kay")
    _handle(memory_store, "remember my name is Other", vault_id="vault-b")

    active = memory_store.active_rows("vault-a")
    payloads = [_payload(row) for row in active]
    display_names = [
        payload for payload in payloads
        if payload["attribute"] == "display_name"
    ]
    favorite_places = [
        payload for payload in payloads
        if payload["attribute"] == "favorite_place"
    ]

    assert len(display_names) == 1
    assert display_names[0]["display_value"] == "Kay"
    assert len(favorite_places) == 1
    assert favorite_places[0]["display_value"] == "Los Angeles"
    assert _handle(memory_store, "what is my name") == "Your name is Kay."
    assert _handle(memory_store, "what is my favorite place") == (
        "Your favorite place is Los Angeles."
    )
    assert _handle(memory_store, "what is my name", vault_id="vault-b") == (
        "Your name is Other."
    )


def test_call_me_replaces_preferred_name_and_forget_removes_current(memory_store):
    _handle(memory_store, "remember my name is Earl")
    proposal = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="Call me Kay.",
        source_message_id="call-me-kay-proposal",
        session_id="session-a",
    )
    assert proposal is not None
    data = dpm.json.loads(proposal)["card"]["data"]
    assert data["attribute"] == "display_name"
    assert data["value"] == "Kay"

    saved = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="call-me-kay-save",
        session_id="session-a",
    )
    assert "Updated" in (saved or "")
    assert _handle(memory_store, "what is my name?") == "Your name is Kay."
    assert _handle(memory_store, "what should you call me?") == (
        "I'll address you as Kay."
    )
    assert _handle(memory_store, "how should you address me?") == (
        "I'll address you as Kay."
    )
    assert len(memory_store.active_rows("vault-a")) == 1

    forgot = _handle(memory_store, "forget my name")
    assert "Forgot" in forgot
    assert "don't have" in _handle(memory_store, "what is my name")
    assert memory_store.active_rows("vault-a") == []


def test_travel_memory_immediate_after_save_and_encrypted_list(memory_store):
    proposal = dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="I traveled to Italy on January 3, 2020",
        source_message_id="travel-proposal",
        session_id="session-a",
    )
    assert proposal is not None
    decoded = dpm.json.loads(proposal)
    assert decoded["card"]["data"]["title"] == "Trip to Italy"
    assert decoded["card"]["data"]["memory_type"] == "travel"
    dpm.handle_personal_memory_turn(
        vault_id="vault-a",
        key=_KEY,
        message="save it",
        source_message_id="travel-save",
        session_id="session-a",
    )
    recall = _handle(memory_store, "when did I travel to Italy")
    assert recall == "You traveled to Italy on January 3, 2020."
    listed = dpm.list_memory_items(vault_id="vault-a", key=_KEY, query="Italy")
    assert listed["items"][0]["title"] == "Trip to Italy"
    assert listed["items"][0]["value"] == "January 3, 2020"
    _assert_plaintext_absent_from_persistent_columns(
        memory_store,
        ["Italy", "January 3, 2020", "2020-01-03"],
    )


def test_forget_birthday_accepts_normal_punctuation(memory_store):
    _handle(memory_store, "remember my mom birthday is January 30, 1965")
    for suffix in ("", ".", "!", "?"):
        _handle(memory_store, "remember my mom birthday is January 30, 1965")
        reply = _handle(memory_store, f"Please forget my mom's birthday{suffix}")
        assert "Forgot" in reply
        assert "don't have" in _handle(memory_store, "when is my mom's birthday")
    _assert_no_plaintext_birthday_storage(memory_store)


def test_generic_encrypted_memory_recall_and_custom_fields(memory_store):
    saved = dpm.save_memory_payload(
        vault_id="vault-a",
        key=_KEY,
        payload=dpm.build_payload_from_request({
            "title": "OpenAI API key",
            "value": "Structured memory",
            "body": "OpenAI project access",
            "memory_type": "note",
            "category": "project",
            "tags": ["api", "openai"],
            "custom_fields": [
                {"label": "API key", "value": "sk-memory-marker-123"},
                {"label": "Server IP", "value": "10.50.60.70"},
            ],
        }),
        source_message_id="manual-memory",
        is_correction=True,
    )
    assert saved["ok"] is True

    assert "sk-memory-marker-123" in _handle(
        memory_store,
        "What API key did I save?",
    )
    assert "10.50.60.70" in _handle(
        memory_store,
        "What was the server IP I saved?",
    )
    listed = dpm.list_memory_items(
        vault_id="vault-a",
        key=_KEY,
        query="server ip",
    )
    assert listed["items"][0]["title"] == "OpenAI API key"
    assert listed["items"][0]["custom_fields"][1] == {
        "label": "Server IP",
        "value": "10.50.60.70",
    }
    _assert_plaintext_absent_from_persistent_columns(
        memory_store,
        ["sk-memory-marker-123", "10.50.60.70"],
    )


def test_generic_memory_update_uses_existing_row(memory_store):
    dpm.save_memory_payload(
        vault_id="vault-a",
        key=_KEY,
        payload=dpm.build_payload_from_request({
            "title": "Home Wi-Fi",
            "value": "old-wifi-secret",
            "body": "Home Wi-Fi password",
            "memory_type": "note",
            "tags": ["wifi"],
        }),
        source_message_id="manual-memory",
        is_correction=True,
    )
    reply = _handle(memory_store, "update home Wi-Fi to new-wifi-secret")
    assert "Updated" in reply
    assert len(memory_store.active_rows("vault-a")) == 1
    assert "new-wifi-secret" in _handle(
        memory_store,
        "What is the Wi-Fi password for my home network?",
    )
    _assert_plaintext_absent_from_persistent_columns(
        memory_store,
        ["old-wifi-secret", "new-wifi-secret"],
    )


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


def test_legacy_remember_fact_branch_uses_encrypted_durable_store(
    memory_store,
    monkeypatch,
):
    import ai_memory
    import main

    plaintext_writer_called = False

    def fail_plaintext_writer(*args, **kwargs):
        nonlocal plaintext_writer_called
        plaintext_writer_called = True
        raise AssertionError("plaintext ai_memory writer must not be used")

    monkeypatch.setattr(dpm, "get_db", memory_store.get_db)
    monkeypatch.setattr(ai_memory, "update_memory_safe", fail_plaintext_writer)

    reply = main._handle_remember_fact(
        "vault-a",
        "date",
        "mom birthday",
        "January 30, 1965",
        "1965-01-30",
        vault_key=_KEY,
    )

    assert plaintext_writer_called is False
    assert reply == "Saved: mom birthday."
    rows = memory_store.active_rows("vault-a")
    assert len(rows) == 1
    row = rows[0]
    assert row["memory_key"] is None
    assert row["memory_value"] is None
    assert row["event_date"] is None
    _assert_plaintext_absent_from_persistent_columns(
        memory_store,
        ["mom birthday", "January 30, 1965", "1965-01-30"],
    )
    recalled = main._handle_recall_memory(
        "vault-a",
        "date",
        memory_query="mom birthday",
        vault_key=_KEY,
    )
    assert recalled is not None
    assert "mom birthday: January 30, 1965" in recalled


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


def test_forward_migration_drops_event_date_index_and_clears_encrypted_columns(
    monkeypatch,
):
    migration = importlib.import_module(
        "migrations.versions.0033_harden_encrypted_memory_plaintext_columns"
    )
    executed: list[str] = []

    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    assert len(executed) == 2
    assert executed[0] == "DROP INDEX IF EXISTS vault_ai_memory_event_date_idx"
    sql = " ".join(executed[1].lower().split())
    assert sql.startswith("update vault_ai_memory set memory_key = null")
    assert "memory_value = null" in sql
    assert "memory_normalized_key = null" in sql
    assert "event_date = null" in sql
    assert "payload_ciphertext is not null" in sql
    assert "memory_lookup_hash is not null" in sql
    assert "vault_id =" not in sql
    assert "payload_ciphertext =" not in sql
    assert "memory_lookup_hash =" not in sql


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

        proposal = harness.post_message("my dad birthday is 12/12/1975")
        assert proposal.http_status == 200, proposal.summary()
        assert proposal.x_chat_path == "personal_memory", proposal.summary()
        assert not proposal.planner_invoked, proposal.summary()
        assert "vault_memory_save_proposal" in (proposal.envelope_json or "")
        assert "vault_memory_proposal_card" in (proposal.envelope_json or "")

        saved_proposal = harness.post_message("save it")
        assert saved_proposal.http_status == 200, saved_proposal.summary()
        assert saved_proposal.x_chat_path == "personal_memory"
        assert not saved_proposal.planner_invoked, saved_proposal.summary()
        assert "December 12, 1975" in (saved_proposal.envelope_json or "")

        _assert_no_plaintext_birthday_storage(store)
        _assert_plaintext_absent_from_persistent_columns(
            store,
            ["December 12, 1975", "1975-12-12"],
        )
    finally:
        harness.tearDown()


def test_encrypted_memory_crud_routes_create_search_update_delete(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    import routes.memory_routes as memory_routes

    store = _MemoryStore()

    async def fake_verify(request=None):
        return {"vault_id": "vault-a", "token_id": "memory-route-session"}

    monkeypatch.setattr(dpm, "get_db", store.get_db)
    monkeypatch.setattr(memory_routes, "verify_vault_pin", lambda vault_id, pin: _KEY)
    main.app.dependency_overrides[memory_routes.verify_trusted_device] = fake_verify
    main.app.dependency_overrides[main.verify_trusted_device] = fake_verify
    client = TestClient(main.app)
    try:
        created = client.post("/memory/create", json={
            "vault_name": "Vault",
            "pin": "1234",
            "title": "Mother's maiden name",
            "value": "Lodato",
            "memory_type": "identity",
            "category": "family",
            "subject": "mother",
            "subject_display": "mother",
            "relationship": "mother",
            "attribute": "maiden_name",
        })
        assert created.status_code == 200, created.text
        item = created.json()["item"]
        assert item["title"] == "Mother's maiden name"
        assert item["value"] == "Lodato"

        listed = client.post("/memory/list", json={
            "vault_name": "Vault",
            "pin": "1234",
            "query": "Lodato",
        })
        assert listed.status_code == 200, listed.text
        assert [it["title"] for it in listed.json()["items"]] == [
            "Mother's maiden name"
        ]

        updated = client.post("/memory/update", json={
            "id": int(item["id"]),
            "vault_name": "Vault",
            "pin": "1234",
            "title": "Mother's maiden name",
            "value": "Rossi",
            "memory_type": "identity",
            "category": "family",
            "subject": "mother",
            "subject_display": "mother",
            "relationship": "mother",
            "attribute": "maiden_name",
        })
        assert updated.status_code == 200, updated.text
        new_item = updated.json()["item"]
        assert new_item["value"] == "Rossi"

        old_search = client.post("/memory/list", json={
            "vault_name": "Vault",
            "pin": "1234",
            "query": "Lodato",
        })
        assert old_search.status_code == 200, old_search.text
        assert old_search.json()["items"] == []

        new_search = client.post("/memory/list", json={
            "vault_name": "Vault",
            "pin": "1234",
            "query": "Rossi",
        })
        assert new_search.status_code == 200, new_search.text
        assert len(new_search.json()["items"]) == 1

        deleted = client.post("/memory/delete", json={
            "vault_name": "Vault",
            "pin": "1234",
            "id": int(new_item["id"]),
        })
        assert deleted.status_code == 200, deleted.text

        empty = client.post("/memory/list", json={
            "vault_name": "Vault",
            "pin": "1234",
            "query": "Rossi",
        })
        assert empty.status_code == 200, empty.text
        assert empty.json()["items"] == []
        _assert_plaintext_absent_from_persistent_columns(
            store,
            ["Lodato", "Rossi"],
        )
    finally:
        main.app.dependency_overrides.pop(memory_routes.verify_trusted_device, None)
        main.app.dependency_overrides.pop(main.verify_trusted_device, None)
