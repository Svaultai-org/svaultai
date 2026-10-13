"""Named memory commands must own the real chat turn, not credential creation."""

import json

import pytest

import durable_personal_memory as memory


PHRASE = (
    "Save a new memory with title QA-TEST-B1-memory and content: "
    "QA-TEST B1 content alpha"
)


def test_reported_named_memory_command_preserves_both_fields():
    intent = memory.parse_personal_memory_intent(PHRASE)
    assert intent is not None
    assert intent.action == "save"
    assert intent.title == "QA-TEST-B1-memory"
    assert intent.value == "QA-TEST B1 content alpha"
    assert not intent.is_correction


def test_client_owned_turn_returns_memory_finalize_not_a_login_or_write(monkeypatch):
    def no_database():
        raise AssertionError("client-owned memory must never write plaintext")

    monkeypatch.setattr(memory, "get_db", no_database)
    response = memory.handle_personal_memory_turn(
        vault_id="synthetic-named-memory-vault",
        key=b"M" * 32,
        message=PHRASE,
        source_message_id="synthetic-named-memory-turn",
        session_id="synthetic-named-memory-session",
        client_owned_storage=True,
    )
    assert response is not None
    marker = "<<VAULTAI_MEMORY_PROPOSAL>>"
    assert response.startswith(marker)
    payload = json.loads(response[len(marker):].split("<<END>>", 1)[0])
    assert payload["title"] == "QA-TEST-B1-memory"
    assert payload["value"] == "QA-TEST B1 content alpha"
    assert payload["record_type"] == "personal_memory"
    assert "password" not in payload
    assert "username" not in payload


@pytest.mark.parametrize('content', [
    'QA-TEST B1 content alpha', 'finish login', 'finish account',
    'finish credential', 'analyze this file', 'show this file',
])
def test_real_encrypted_chat_dispatch_never_calls_login_planner(content):
    from test_chat_endpoint_deterministic_2026_08_01 import _ChatEndpointHarness

    harness = _ChatEndpointHarness()
    harness.setUp()
    try:
        harness._patch("vault_core.is_vault_zk_adopted", return_value=True)
        harness.arm_planner_sentinel()
        result = harness.post_message(
            'Save a new memory with title QA-TEST-B1-memory and content: ' + content
        )
        assert result.http_status == 200, result.summary()
        assert result.x_chat_path == "personal_memory", result.summary()
        assert not result.planner_invoked, result.summary()
        assert "QA-TEST-B1-memory" in (result.envelope_json or "")
        assert content in (result.envelope_json or "")
        assert "<<VAULTAI_MEMORY_PROPOSAL>>" in (result.envelope_json or "")
        assert "login draft" not in (result.envelope_json or "").lower()
    finally:
        harness.tearDown()


@pytest.mark.parametrize("phrase", [
    "Create a memory titled Holiday list with content: Pack the blue bag.",
    "Please save memory with title 東京 and content: メモ 🔒",
    "Save a new memory with title Login checklist and content: Review the account.",
])
def test_explicit_named_memory_is_not_inferred_from_its_content(phrase):
    intent = memory.parse_personal_memory_intent(phrase)
    assert intent is not None
    assert intent.action == "save"
    assert intent.memory_type == "note"
    assert not intent.is_correction


@pytest.mark.parametrize("phrase", [
    "Create a login with title Example and content: username example",
    "What does save a new memory with title Example and content: example mean?",
    "Continue this ordinary conversation without searching the vault.\n"
    "Previous user message: " + PHRASE,
])
def test_other_commands_and_quoted_context_do_not_become_named_memory(phrase):
    intent = memory.parse_personal_memory_intent(phrase)
    assert intent is None or intent.action != "save"


@pytest.mark.parametrize('title,content,allowed', [
    ('T' * 120, 'C' * 500, True),
    ('T' * 121, 'C', False),
    ('T', 'C' * 501, False),
    ('T', 'C' * 2200, False),
    ('', 'C', False),
    ('T', '', False),
])
def test_named_bounds_reject_without_a_partial_save(title, content, allowed):
    phrase = f'Save a memory with title {title} and content: {content}'
    intent = memory.parse_personal_memory_intent(phrase)
    assert intent is not None
    assert intent.action == ('save' if allowed else 'propose')
    assert intent.needs_clarification == (not allowed)
    reply = memory.handle_personal_memory_turn(
        vault_id='synthetic-bounds', key=b'B' * 32, message=phrase,
        client_owned_storage=True,
    )
    assert reply is not None
    if allowed:
        assert '<<VAULTAI_MEMORY_PROPOSAL>>' in reply
        assert content in reply
    else:
        assert 'Nothing was saved.' in reply
        assert '<<VAULTAI_MEMORY_PROPOSAL>>' not in reply


@pytest.mark.parametrize('phrase', [
    'Save a memory with title Example',
    'Create a memory titled Example',
    'Save memory with title Example',
])
def test_incomplete_named_syntax_stays_memory_validation(phrase):
    intent = memory.parse_personal_memory_intent(phrase)
    assert intent is not None
    assert intent.action == 'propose'
    assert intent.needs_clarification
    assert 'Nothing was saved.' in memory.handle_personal_memory_turn(
        vault_id='synthetic-incomplete', key=b'I' * 32, message=phrase,
        client_owned_storage=True,
    )


def test_named_literal_payload_preserves_unicode_multiline_and_punctuation():
    title = '東京 🔒'
    content = 'Line one: A,  B!\nLine two: C?\nEND.'
    intent = memory.parse_personal_memory_intent(
        f'Save a memory with title {title} and content: {content}'
    )
    assert intent is not None
    payload = memory._payload_for_intent(intent, source_message_id='synthetic-literal')
    assert payload['title'] == title
    assert payload['value'] == payload['body'] == payload['display_value'] == content


@pytest.mark.parametrize('left,right', [
    ('東京', '大阪'),
    ('A' * 81 + 'B', 'A' * 81 + 'C'),
    ('Title-one', 'Title one'),
])
def test_named_identity_does_not_collapse_distinct_complete_titles(left, right):
    a = memory.parse_personal_memory_intent(f'Save a memory titled {left} with content: A')
    b = memory.parse_personal_memory_intent(f'Save a memory titled {right} with content: B')
    assert a is not None and b is not None
    assert a.canonical_key != b.canonical_key


def test_unicode_only_title_can_be_recalled_without_broad_fuzzy_matching():
    payload = {'title': '東京', 'value': 'literal content', 'memory_type': 'note'}
    item = {'title': '東京', 'memory_type': 'note'}
    assert memory._score_payload_match(payload, item, '東京') == 120
    assert memory._score_payload_match(payload, item, '大阪') == 0
    assert memory._score_payload_match(payload, item, '') == 0
