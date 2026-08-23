"""Regression coverage for general chat becoming vault search."""

from pathlib import Path

import pytest


def test_tool_free_prompt_requires_substantive_complete_guidance():
    from pathlib import Path

    source = (Path(__file__).parent / "main.py").read_text()
    assert "never return only a list of headings" in source
    assert "semicolon-separated topic names" in source

from vault_chat_general_router import (
    INTENT_ASSISTANT_IDENTITY,
    INTENT_CAPABILITY_QUESTION,
    INTENT_GENERAL_CHAT,
    INTENT_LANGUAGE_RESPONSE_REQUEST,
    INTENT_UNKNOWN_GENERAL,
    classify_general_intent,
    analyze_compound_message,
    has_language_directive,
    route_general_chat,
)
from vault_chat_safety_sanitizer import (
    SENTENCE_GENERAL_RESPONSE_FAILED,
    SENTENCE_GENERIC_TOOL_FAILED,
    sanitize_tool_result,
)
from vault_planner import _conservative_fallback
from vault_chat_router import build_vault_chat_envelope


SCREENSHOT_CASES = (
    ("Am I travel-ready?", INTENT_GENERAL_CHAT, "en"),
    ("hey how are you", INTENT_GENERAL_CHAT, "en"),
    ("tell me about you in spanish", INTENT_LANGUAGE_RESPONSE_REQUEST, "es"),
    ("tell me about you in french", INTENT_LANGUAGE_RESPONSE_REQUEST, "fr"),
    ("tell me bout you in french", INTENT_LANGUAGE_RESPONSE_REQUEST, "fr"),
    ("what can you do?", INTENT_CAPABILITY_QUESTION, "en"),
    ("who are you?", INTENT_ASSISTANT_IDENTITY, "en"),
    ("explain SVaultAI in Arabic", INTENT_LANGUAGE_RESPONSE_REQUEST, "ar"),
    ("thanks", INTENT_GENERAL_CHAT, "en"),
    ("hello", INTENT_GENERAL_CHAT, "en"),
    ("good morning", INTENT_GENERAL_CHAT, "en"),
)


def test_ordinary_english_with_ambiguous_article_stays_english():
    from vault_multilingual import detect_language, resolve_reply_language

    message = "I am planning a trip to Lagos"
    detected = detect_language(message)
    assert detected != "pt"
    assert resolve_reply_language(
        detected_from_message=detected,
        requested_from_message=None,
        app_locale_hint="en",
    ) == "en"


@pytest.mark.parametrize("message", (
    "How can I support a grieving friend?",
    "How should I support my child at school?",
    "Can you help me support my partner through a hard week?",
))
def test_personal_support_questions_are_not_product_support_faq(message):
    from vault_faq_router import looks_like_faq_message

    assert not looks_like_faq_message(message)
    route = route_general_chat(message)
    assert route is not None
    assert route.model_response_required


@pytest.mark.parametrize("message,intent,language", SCREENSHOT_CASES)
def test_screenshot_cases_are_retrieval_free(message, intent, language):
    route = route_general_chat(message)
    assert route is not None
    assert route.intent == intent
    assert route.language == language
    if route.response:
        assert not route.model_response_required
    else:
        assert route.model_response_required
    assert "part of the search" not in route.response.lower()
    assert "didn't find" not in route.response.lower()


@pytest.mark.parametrize("message,expected_fragment", (
    ("hey", "ready to help"),
    ("hello", "ready to help"),
    ("what can you do", "encrypted vault"),
    ("what are you capable of?", "encrypted vault"),
))
def test_obvious_small_talk_uses_existing_lightweight_response(
    message, expected_fragment,
):
    route = route_general_chat(message)
    assert route is not None
    assert not route.model_response_required
    assert expected_fragment in route.response
    assert route.clauses == ()


@pytest.mark.parametrize("message", (
    "hi", "hey there", "are you working?", "how are you today?",
    "can you help me?", "what are you capable of?",
    "explain how this app works", "thank you", "bye",
    "tell me something", "help me", "I have a question", "explain more",
    "what do you mean?", "say that again", "make it simpler",
    "hello there", "hey, how’s it going", "how are you doing today",
    "are you working", "what kind of assistant are you",
    "can you explain what you do", "thanks for helping",
    "goodbye for now", "tell me more", "explain", "can you simplify that",
    "continue", "say it another way",
))
def test_human_chat_matrix_never_searches(message):
    route = route_general_chat(message)
    assert route is not None
    assert route.intent in {
        INTENT_GENERAL_CHAT, INTENT_ASSISTANT_IDENTITY,
        INTENT_CAPABILITY_QUESTION, INTENT_LANGUAGE_RESPONSE_REQUEST,
    }


@pytest.mark.parametrize("message,language", (
    ("respond in Spanish", "es"),
    ("answer me in French", "fr"),
    ("explain privacy in Arabic", "ar"),
    ("tell me what you do in Portuguese", "pt"),
    ("reply in English", "en"),
    ("translate your last answer into German", "de"),
    ("tell me what you do, but in French", "fr"),
    ("could you respond in Arabic", "ar"),
    ("explain that in Portuguese", "pt"),
    ("translate your answer into German", "de"),
    ("reply to me in English", "en"),
    ("can you say that in Spanish please", "es"),
))
def test_language_directive_preserves_non_retrieval_route(message, language):
    route = route_general_chat(message)
    assert route is not None
    assert route.intent == INTENT_LANGUAGE_RESPONSE_REQUEST
    assert route.underlying_intent in {
        INTENT_GENERAL_CHAT, INTENT_ASSISTANT_IDENTITY,
        INTENT_CAPABILITY_QUESTION,
    }
    assert route.language == language
    assert route.requested_language
    assert route.model_response_required
    assert route.response == ""


@pytest.mark.parametrize("message", (
    "tell me about yourself in Tagalog",
    "tell me about yourself in Filipino",
    "reply in Welsh",
    "write your answer in Icelandic",
    "explain privacy in Yoruba",
))
def test_open_language_requests_use_model_only_general_route(message):
    assert has_language_directive(message)
    route = route_general_chat(message)
    assert route is not None
    assert route.intent == INTENT_LANGUAGE_RESPONSE_REQUEST
    assert route.requested_language
    assert route.model_response_required
    assert route.response == ""


def test_endpoint_language_model_route_forces_empty_tool_set():
    source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "force_no_tools=True," in source
    assert "response_language=_general_route.language" in source


def test_tool_free_prompt_forbids_fake_vault_or_travel_work():
    source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "This turn is ordinary, tool-free conversation" in source
    assert "No vault files, memories, credentials, travel data" in source
    assert "Never say or imply that you" in source
    assert "Never narrate background work" in source
    assert "if force_no_tools:" in source


@pytest.mark.parametrize("message,expected_count", (
    (
        "tell me about yourself in Tagalog\n"
        "tell me about yourself in Filipino\n"
        "explain SVaultAI in French\n"
        "reply in Arabic\n"
        "what can you do in Somali",
        5,
    ),
    ("tell me about yourself in French; what can you do in Somali", 2),
    ("1. reply in Arabic\n2. explain SVaultAI in French", 2),
    ("- reply in Tagalog\n* what can you do in Somali", 2),
    ("reply in French and then tell me about yourself in Filipino", 2),
))
def test_compound_general_chat_is_model_only_and_retrieval_free(message, expected_count):
    analysis = analyze_compound_message(message)
    assert len(analysis.clauses) == expected_count
    assert len(analysis.general_clauses) == expected_count
    assert analysis.vault_clauses == ()
    route = route_general_chat(message)
    assert route is not None
    assert route.model_response_required
    assert route.response == ""
    assert route.clauses == analysis.clauses
    assert [c.clause_id for c in analysis.clause_objects] == [
        f"clause-{i}" for i in range(1, expected_count + 1)
    ]
    assert all(not c.tool_eligible for c in analysis.clause_objects)


@pytest.mark.parametrize("message,expected_vault_text", (
    (
        "tell me about yourself in French\nshow my passport in Spanish",
        "show my passport in Spanish",
    ),
    (
        "reply in Arabic; tell me my ETH balance in Arabic",
        "tell me my ETH balance in Arabic",
    ),
    (
        "what can you do in Somali\nshow my saved login in German",
        "show my saved login in German",
    ),
    (
        "explain SVaultAI in French; show my beneficiary connection",
        "show my beneficiary connection",
    ),
))
def test_mixed_compound_preserves_only_explicit_vault_clauses(message, expected_vault_text):
    analysis = analyze_compound_message(message)
    assert analysis.general_clauses
    assert analysis.vault_clauses == (expected_vault_text,)
    assert route_general_chat(message) is None
    assert [c.tool_eligible for c in analysis.clause_objects].count(True) == 1
    assert next(
        c.text for c in analysis.clause_objects if c.tool_eligible
    ) == expected_vault_text


@pytest.mark.parametrize("message", (
    "tell me about yourself in Tagalog\nexplain security in Persian",
    "1. what can you do in Somali\n2. explain inheritance in Swahili",
    "reply in Arabic; explain privacy in Hindi",
))
def test_compound_language_chat_cannot_be_consumed_by_faq(message):
    from vault_faq_router import build_faq_envelope, looks_like_faq_message
    assert not looks_like_faq_message(message)
    assert build_faq_envelope(message) is None
    route = route_general_chat(message)
    assert route is not None
    assert route.model_response_required


def test_credential_retrieval_is_not_consumed_by_privacy_faq():
    from vault_faq_router import build_faq_envelope, looks_like_faq_message
    message = "what is my facebook login"
    assert not looks_like_faq_message(message)
    assert build_faq_envelope(message) is None


def test_mixed_clause_languages_and_intents_are_independent():
    analysis = analyze_compound_message(
        "tell me about yourself in French\nshow my passport in Spanish"
    )
    first, second = analysis.clause_objects
    assert first.requested_language == "fr"
    assert first.tool_eligible is False
    assert second.requested_language == "es"
    assert second.intent == "file_search"
    assert second.tool_eligible is True


def test_endpoint_enforces_compound_boundary_before_fast_router():
    source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "len(_compound_analysis.clauses) > 1" in source
    assert 'request.state.chat_path = "compound_mixed_planner"' in source
    assert "return _route_to_ai_planner_stream(force_no_tools=False)" in source


@pytest.mark.parametrize("message", (
    "please explain this ???; and something else unclear",
    "1. hello there\n2. ???",
))
def test_malformed_compound_general_chat_never_becomes_search(message):
    analysis = analyze_compound_message(message)
    assert analysis.vault_clauses == ()
    route = route_general_chat(message)
    assert route is not None
    assert route.model_response_required


def test_non_search_stream_failure_uses_neutral_copy_source_guard():
    source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "if _search_attempted" in source
    assert "_search_attempted = tool_name in _SEARCH_TOOL_NAMES" in source
    assert "SENTENCE_GENERAL_RESPONSE_FAILED" in source
    assert "tool_routing_message=_tool_routing_message" in source


@pytest.mark.asyncio
async def test_tool_free_provider_failure_returns_neutral_not_search_copy(monkeypatch):
    import main
    import vault_ai_provider
    from vault_chat_safety_sanitizer import (
        SENTENCE_GENERAL_RESPONSE_FAILED,
        SENTENCE_GENERIC_TOOL_FAILED,
    )

    class _Completions:
        async def create(self, **kwargs):
            assert "tools" not in kwargs
            assert "tool_choice" not in kwargs
            raise RuntimeError("synthetic provider failure")

    class _Client:
        class _Chat:
            completions = _Completions()
        chat = _Chat()

    monkeypatch.setattr(vault_ai_provider, "get_chat_client", lambda: _Client())
    monkeypatch.setattr(vault_ai_provider, "active_provider_name", lambda: "test")
    chunks = []
    async for chunk in main.ai_stream(
        [{"role": "user", "content": "compound general chat"}],
        "vault-test", b"key", last_user_message="compound general chat",
        force_no_tools=True,
    ):
        chunks.append(chunk.decode("utf-8"))
    assert "".join(chunks) == SENTENCE_GENERAL_RESPONSE_FAILED
    assert SENTENCE_GENERIC_TOOL_FAILED not in "".join(chunks)


@pytest.mark.parametrize("message", (
    "show me tulip", "open my passport", "list my videos",
    "what files do I have?", "what is my name?",
    "when was my trip to USA?", "generate a Facebook login",
    "show my Instagram login", "what is my ETH balance?", "open Send ETH",
))
def test_explicit_vault_requests_are_not_swallowed(message):
    assert classify_general_intent(message) == INTENT_UNKNOWN_GENERAL
    assert route_general_chat(message) is None


@pytest.mark.parametrize("message", (
    "show my passport in Spanish",
    "find my contract and answer in French",
    "tell me my ETH balance in Arabic",
    "show my saved login in German",
    "open my video and reply in Tagalog",
))
def test_language_request_does_not_swallow_explicit_vault_route(message):
    assert route_general_chat(message) is None


def test_planner_failure_is_tool_free_and_not_search():
    decision = _conservative_fallback("api_error")
    assert decision.intent == "unknown"
    assert decision.needs_vault_search is False
    assert decision.planned_tools == ()


def test_search_error_copy_is_scoped_to_real_search_tools():
    assert sanitize_tool_result("find_in_vault", None) == SENTENCE_GENERIC_TOOL_FAILED
    assert sanitize_tool_result("conversational_reply", None) == SENTENCE_GENERAL_RESPONSE_FAILED


def test_endpoint_priority_places_general_before_retrieval_work():
    source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
    general = source.index("from vault_chat_general_router import route_general_chat")
    drains = source.index("from vault_analysis_worker import drain_text_extraction", general)
    memory = source.index("memory = get_memory(vault_id)", general)
    brain = source.index("from vault_chat_brain import run_chat_brain", general)
    assert general < drains < memory < brain


def test_all_required_intent_names_are_defined():
    import vault_chat_general_router as router
    assert {
        router.INTENT_PENDING_CONFIRMATION,
        router.INTENT_PENDING_CANCELLATION,
        router.INTENT_GENERAL_CHAT, router.INTENT_ASSISTANT_IDENTITY,
        router.INTENT_CAPABILITY_QUESTION,
        router.INTENT_LANGUAGE_RESPONSE_REQUEST, router.INTENT_FAQ_QUESTION,
        router.INTENT_FILE_SEARCH, router.INTENT_FILE_ACTION,
        router.INTENT_FILE_UPLOAD, router.INTENT_MEMORY_RECALL,
        router.INTENT_MEMORY_SAVE, router.INTENT_MEMORY_EDIT,
        router.INTENT_MEMORY_DELETE, router.INTENT_CREDENTIAL_CREATE,
        router.INTENT_CREDENTIAL_RETRIEVE, router.INTENT_CREDENTIAL_EDIT,
        router.INTENT_CREDENTIAL_DELETE, router.INTENT_WALLET_ACTION,
        router.INTENT_INHERITANCE_ACTION, router.INTENT_UNKNOWN_GENERAL,
    } == {
        "general_chat", "assistant_identity", "capability_question",
        "language_response_request", "faq_question", "file_search",
        "file_action", "memory_recall", "memory_save",
        "credential_create", "credential_retrieve", "credential_edit",
        "credential_delete", "wallet_action", "inheritance_action",
        "unknown_general", "pending_confirmation", "pending_cancellation",
        "file_upload", "memory_edit", "memory_delete",
    }


@pytest.mark.parametrize("message", (
    "why should I trust SVaultAI?", "is my information private?",
    "explain how this app works", "can SVaultAI employees see my files?",
    "is there a master key?", "what happens after six months of inactivity?",
))
def test_help_questions_win_before_general_or_search(message):
    envelope = build_vault_chat_envelope(message)
    assert envelope is not None
    assert envelope["intent"] == "vault_faq"
