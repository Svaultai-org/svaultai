"""Regression coverage for general chat becoming vault search."""

from pathlib import Path

import pytest

from vault_chat_general_router import (
    INTENT_ASSISTANT_IDENTITY,
    INTENT_CAPABILITY_QUESTION,
    INTENT_GENERAL_CHAT,
    INTENT_LANGUAGE_RESPONSE_REQUEST,
    INTENT_UNKNOWN_GENERAL,
    classify_general_intent,
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


@pytest.mark.parametrize("message,intent,language", SCREENSHOT_CASES)
def test_screenshot_cases_are_retrieval_free(message, intent, language):
    route = route_general_chat(message)
    assert route is not None
    assert route.intent == intent
    assert route.language == language
    if intent == INTENT_LANGUAGE_RESPONSE_REQUEST:
        assert route.model_response_required
        assert route.response == ""
    else:
        assert route.response
    assert "part of the search" not in route.response.lower()
    assert "didn't find" not in route.response.lower()


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
    assert "_route_to_ai_planner_stream(force_no_tools=True)" in source
    assert "if force_no_tools:" in source


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
