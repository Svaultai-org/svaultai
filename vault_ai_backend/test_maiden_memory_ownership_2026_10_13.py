"""Synthetic memory routing regressions; no DB/provider or customer access."""
import json

import pytest

import durable_personal_memory as memory


def forbid(*_args, **_kwargs):
    raise AssertionError("Memory routing must not access DB/provider here")


@pytest.mark.parametrize("phrase", [
    "save my mother's maiden name",
    "save my mother's maiden name is",
    "save my mother’s maiden name.",
    "please save my mom maiden name:",
    "remember my mother's maiden name",
])
@pytest.mark.parametrize("client_owned", [False, True])
def test_missing_value_clarifies_before_any_writer(monkeypatch, phrase, client_owned):
    monkeypatch.setattr(memory, "get_db", forbid)
    monkeypatch.setattr(memory, "_client_owned_save_envelope", forbid)
    intent = memory.parse_personal_memory_intent(phrase)
    assert intent is not None and intent.needs_clarification
    assert intent.attribute == "maiden_name" and not intent.value
    reply = memory.handle_personal_memory_turn(
        vault_id="synthetic-maiden-missing", key=b"S" * 32,
        message=phrase, session_id="synthetic-maiden-session",
        client_owned_storage=client_owned,
    )
    assert "What should I save" in reply and "maiden name?" in reply
    assert "<<VAULTAI_MEMORY_PROPOSAL>>" not in reply
    assert "login" not in reply.lower()


@pytest.mark.parametrize("phrase", [
    "save my mother's maiden name SyntheticOnly",
    "save my mother's maiden name is SyntheticOnly",
    "save my mother’s maiden name SyntheticOnly",
    "save my mother's maiden name: SyntheticOnly",
    "save my mother's maiden name as SyntheticOnly",
    "save my mother's maiden name to be SyntheticOnly",
    "save my mom maiden name SyntheticOnly",
    "save my dad maiden name SyntheticOnly",
])
def test_supplied_value_returns_client_owned_memory_not_login(monkeypatch, phrase):
    monkeypatch.setattr(memory, "get_db", forbid)
    intent = memory.parse_personal_memory_intent(phrase)
    assert intent is not None and intent.action == "save"
    assert not intent.needs_clarification and intent.value == "SyntheticOnly"
    assert intent.attribute == "maiden_name"
    reply = memory.handle_personal_memory_turn(
        vault_id="synthetic-maiden-value", key=b"S" * 32,
        message=phrase, session_id="synthetic-maiden-session",
        client_owned_storage=True,
    )
    marker = "<<VAULTAI_MEMORY_PROPOSAL>>"
    assert reply.startswith(marker)
    payload = json.loads(reply[len(marker):].split("<<END>>", 1)[0])
    assert payload["record_type"] == "personal_memory"
    assert payload["category"] == "family" and payload["attribute"] == "maiden_name"
    assert payload["value"] == "SyntheticOnly"
    assert "password" not in payload and "username" not in payload


@pytest.mark.parametrize("opening", ["what's", "whats", "what’s", "what is"])
def test_recall_variants_use_the_same_canonical_memory(opening):
    intent = memory.parse_personal_memory_intent(
        f"{opening} my mother's maiden name"
    )
    assert intent is not None and intent.action == "recall"
    assert intent.subject == "mother" and intent.attribute == "maiden_name"
    assert intent.canonical_key == "mother:maiden_name"


@pytest.mark.parametrize("phrase", [
    "save my mother's login username=qa password=synthetic",
    "save my mother's password is synthetic",
    "save my mother's maiden name as a login",
    "save my mother's maiden name login username=qa password=synthetic",
    "save my mother's maiden name password: synthetic",
    "generate a login for my mother",
    "save my github password as synthetic",
])
def test_explicit_credentials_are_not_captured_by_memory(phrase):
    assert memory.parse_personal_memory_intent(phrase) is None


def test_long_maiden_value_never_finalizes_a_truncated_value(monkeypatch):
    monkeypatch.setattr(memory, "get_db", forbid)
    monkeypatch.setattr(memory, "_client_owned_save_envelope", forbid)
    reply = memory.handle_personal_memory_turn(
        vault_id="synthetic-maiden-long", key=b"S" * 32,
        message="save my mother's maiden name " + "S" * 501,
        client_owned_storage=True,
    )
    assert "Nothing was saved." in reply


def test_new_save_ownership_is_maiden_only_not_every_parent_request():
    assert memory.parse_personal_memory_intent("save my mom birthday is January 1") is None


def test_surname_is_prefix_is_not_mistaken_for_a_connector():
    intent = memory.parse_personal_memory_intent("save my mother's maiden name Isabella")
    assert intent.value == "Isabella"


@pytest.mark.parametrize("value", ["", " SyntheticOnly"])
def test_actual_encrypted_chat_turn_stops_before_login_or_ai(value):
    from test_chat_endpoint_deterministic_2026_08_01 import _ChatEndpointHarness

    harness = _ChatEndpointHarness()
    harness.setUp()
    try:
        harness._patch("vault_core.is_vault_zk_adopted", return_value=True)
        harness._patch("durable_personal_memory.get_db", side_effect=forbid)
        harness.arm_planner_sentinel()
        result = harness.post_message("save my mother's maiden name" + value)
        assert result.http_status == 200, result.summary()
        assert result.x_chat_path == "personal_memory", result.summary()
        assert not result.planner_invoked, result.summary()
        reply = result.envelope_json or ""
        assert "login" not in reply.lower()
        if value:
            assert "<<VAULTAI_MEMORY_PROPOSAL>>" in reply and "SyntheticOnly" in reply
        else:
            assert "What should I save" in reply
            assert "<<VAULTAI_MEMORY_PROPOSAL>>" not in reply
    finally:
        harness.tearDown()


def test_memory_round_trip_uses_fixture_encryption_and_all_recall_variants(monkeypatch):
    from test_durable_personal_memory_2026_08_02 import _MemoryStore, _KEY

    store = _MemoryStore()
    monkeypatch.setattr(memory, "get_db", store.get_db)
    args = dict(vault_id="synthetic-maiden-roundtrip", key=_KEY,
                session_id="synthetic-maiden-session")
    saved = memory.handle_personal_memory_turn(
        **args, message="save my mother's maiden name SyntheticOnly"
    )
    assert "Saved" in saved and "login" not in saved.lower()
    assert len(store.rows) == 1
    assert store.rows[0]["memory_key"] is None
    assert store.rows[0]["memory_value"] is None
    for opening in ["what's", "whats", "what’s", "what is"]:
        reply = memory.handle_personal_memory_turn(
            **args, message=f"{opening} my mother's maiden name"
        )
        assert reply == "Your mother's maiden name is SyntheticOnly."
    assert len(store.rows) == 1
