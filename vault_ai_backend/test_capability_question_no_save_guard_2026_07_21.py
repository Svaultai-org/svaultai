# Root-cause repro for the production intent-routing failure
# reported 2026-07-21:
#
#   User:  "what are you"
#   Bot:   "I created the login draft, but I haven't saved it yet.
#           Say \"save it\" when you want me to store it in your vault."
#
# The trace (see the investigation report on this branch) is:
#
#   1. planner classifies "what are you" as capability_question,
#      skips tools, no save is attempted.
#   2. The LLM answers naturally and its answer contains descriptive
#      prose like "credentials are stored securely in your vault" —
#      because tools.STATIC_VAULT_SYSTEM_PROMPT and the capability-
#      question context hint actively coach it to describe stored
#      credentials.
#   3. vault_chat_save_guard.guard_response_text sees
#      save_tool_succeeded=False, matches one of the descriptive
#      _SAVE_CLAIM_PATTERNS ("credentials_are_saved",
#      "stored_in_vault", "secured_in_vault", "login_is_saved",
#      "added_to_vault"), and REPLACES the entire reply with the
#      hardcoded SAFE_CORRECTION_TEXT.
#
# Root cause: the guard treats any surface-level save-shaped
# phrasing as a save-claim lie, regardless of whether the current
# turn even attempted to save anything. On a capability answer this
# rewrites a correct identity reply into a fabricated "I created a
# login draft" claim.
#
# The fix must:
#   * Keep firing when the LLM lies about a save it did not perform
#     (existing invariant — see test_vault_chat_save_guard_2026_06_27).
#   * NOT fire when the current turn had no save intent — descriptive
#     capability prose is legitimate then.
#
# This test suite is written FIRST so it fails against the current
# code; the fix in vault_chat_save_guard.py will make it pass.

from __future__ import annotations

import pytest

from vault_chat_save_guard import (
    SAFE_CORRECTION_TEXT,
    guard_response_text,
)


# ---------------------------------------------------------------------------
# Capability-answer prose must NOT be rewritten when intent was not to save.
# ---------------------------------------------------------------------------

# Realistic capability replies the LLM produces for "what are you",
# "who are you", "what can you do", etc. All of these contain
# descriptive phrases that today's guard misclassifies as save claims.
_CAPABILITY_REPLIES: tuple[str, ...] = (
    "I'm VaultAI, an AI assistant for your private vault. I help you "
    "find and organize what's inside — for example, your credentials "
    "are stored securely in your vault and I can retrieve them by "
    "name.",
    "I'm your VaultAI assistant. Passwords and login details you "
    "save are stored in your vault so I can help you look them up.",
    "VaultAI is a private assistant. Anything you save — notes, "
    "logins, files — is secured in your vault and only accessible to "
    "you.",
    "I help manage what you've put into your vault. Your login is "
    "stored on your device and can be recalled by asking me.",
    "I'm an AI keeper for your VaultAI vault. Items you've added to "
    "your vault (credentials, notes, files) can be searched, updated, "
    "or removed on request.",
)


@pytest.mark.parametrize("reply", _CAPABILITY_REPLIES)
def test_capability_answer_prose_is_not_rewritten_as_login_draft(
    reply: str,
) -> None:
    # Simulates the /chat pipeline at main.py:8167 for a capability
    # question: save_tool_succeeded is False (no save attempted),
    # intent_was_save is False (planner picked capability_question).
    corrected, slug = guard_response_text(
        reply_text=reply,
        save_tool_succeeded=False,
        intent_was_save=False,
    )
    assert corrected == reply, (
        f"guard rewrote a capability answer into the login-draft "
        f"correction text.\n"
        f"input:  {reply!r}\n"
        f"output: {corrected!r}\n"
        f"slug:   {slug!r}"
    )
    assert slug is None
    # And critically the exact production bug string never reaches
    # the user for a capability-question turn.
    assert "created the login draft" not in corrected


def test_capability_reply_never_returns_hardcoded_correction() -> None:
    # Direct assertion of the production failure. This is the exact
    # sentence a user saw for "what are you".
    reply = (
        "I'm VaultAI. Your credentials are stored in your vault, "
        "and I can help you retrieve them."
    )
    corrected, _slug = guard_response_text(
        reply_text=reply,
        save_tool_succeeded=False,
        intent_was_save=False,
    )
    assert corrected != SAFE_CORRECTION_TEXT, (
        "Production bug: guard rewrote a plain capability answer "
        "into the fabricated 'I created the login draft' message."
    )


# ---------------------------------------------------------------------------
# The guard MUST STILL fire on real hallucinated save claims.
# ---------------------------------------------------------------------------

# When the assistant WAS asked to save (intent_was_save=True) and it
# then claims to have saved when the tool did not succeed, the guard
# must still replace the reply — that is the original save-guard
# invariant from test_vault_chat_save_guard_2026_06_27 and must be
# preserved.

_HALLUCINATED_SAVE_CLAIMS_STRONG_FORM: tuple[str, ...] = (
    "I've saved the credentials for Union Bank.",
    "I have saved your login for netflix.com.",
    "I saved your Netflix login and it's ready.",
    "Saved your Union Bank login.",
    "Saved it — you can find it in your vault now.",
    "Saved the password for your work email.",
)


@pytest.mark.parametrize(
    "reply", _HALLUCINATED_SAVE_CLAIMS_STRONG_FORM,
)
def test_strong_first_person_save_claim_still_rewritten(
    reply: str,
) -> None:
    # First-person past-tense save claims are unambiguous
    # hallucinations when no save tool succeeded. They must be
    # rewritten regardless of intent — the LLM is asserting a false
    # fact about what IT did.
    corrected, slug = guard_response_text(
        reply_text=reply,
        save_tool_succeeded=False,
        intent_was_save=True,
    )
    assert corrected == SAFE_CORRECTION_TEXT, (
        f"guard failed to catch a first-person save-claim "
        f"hallucination.\ninput: {reply!r}"
    )
    assert slug is not None


def test_strong_first_person_claim_rewritten_even_without_intent_flag(
) -> None:
    # If the LLM lies about saving even outside a save-intent turn,
    # we still catch it — because "I saved X" is an unambiguous
    # first-person claim of an action.
    reply = "I've saved your credentials for Union Bank."
    corrected, _slug = guard_response_text(
        reply_text=reply,
        save_tool_succeeded=False,
        intent_was_save=False,
    )
    assert corrected == SAFE_CORRECTION_TEXT


# ---------------------------------------------------------------------------
# Descriptive-only prose during a save-intent turn is STILL suspicious.
# ---------------------------------------------------------------------------

def test_descriptive_prose_during_save_intent_still_rewritten() -> None:
    # If the planner routed this turn as a save intent (the user
    # asked to save something) and the reply is descriptive-only prose
    # without a successful save tool call, that IS a save-claim
    # hallucination we should catch.
    reply = "Your credentials are now stored in your vault."
    corrected, slug = guard_response_text(
        reply_text=reply,
        save_tool_succeeded=False,
        intent_was_save=True,
    )
    assert corrected == SAFE_CORRECTION_TEXT
    assert slug is not None


# ---------------------------------------------------------------------------
# When a save DID succeed, nothing gets rewritten.
# ---------------------------------------------------------------------------

def test_save_tool_success_disables_the_guard() -> None:
    reply = (
        "Saved your Union Bank login. The username and password are "
        "stored securely in your vault."
    )
    corrected, slug = guard_response_text(
        reply_text=reply,
        save_tool_succeeded=True,
        intent_was_save=True,
    )
    assert corrected == reply
    assert slug is None


# ---------------------------------------------------------------------------
# Backward compatibility.
# ---------------------------------------------------------------------------

def test_guard_still_callable_without_intent_kwarg() -> None:
    # Existing callers that don't yet pass intent_was_save must
    # continue to work. The default matches the old strict-mode
    # behavior for legacy code paths — safe direction, only affects
    # descriptive prose in obvious save-intent contexts.
    reply = "I've saved your Union Bank login."
    corrected, slug = guard_response_text(
        reply_text=reply,
        save_tool_succeeded=False,
    )
    assert corrected == SAFE_CORRECTION_TEXT
    assert slug is not None


# ---------------------------------------------------------------------------
# The `intent_was_save` derivation the /chat orchestrator computes must
# be safe: capability/identity/casual intents must produce False; the
# specific save-related intents must produce True.
# ---------------------------------------------------------------------------

def _fake_planner(
    *, intent: str, planned_tools: tuple[str, ...] = (),
    is_simple: bool = False,
):
    from vault_planner import PlannerDecision
    return PlannerDecision(
        intent=intent,
        needs_vault_search=False,
        needs_file_reading=False,
        needs_ocr_image_pdf_reading=False,
        needs_credential_action=False,
        is_simple_capability_question=is_simple,
        needs_stronger_model=False,
        planned_tools=planned_tools,
        reasoning="",
        confidence=1.0,
        source="test",
    )


def test_intent_was_save_true_for_credential_creation_and_confirmation() -> None:
    # The /chat orchestrator at main.py:8167 must compute
    # intent_was_save=True when the planner routed the current turn
    # as a save-family intent, so the guard stays as strict as before
    # for those turns.
    from vault_chat_save_guard import planner_intent_is_save
    p1 = _fake_planner(intent="credential_creation_draft")
    p2 = _fake_planner(intent="credential_save_confirmation")
    assert planner_intent_is_save(planner=p1, allowed_tool_names=set())
    assert planner_intent_is_save(planner=p2, allowed_tool_names=set())


def test_intent_was_save_false_for_capability_identity_casual() -> None:
    from vault_chat_save_guard import planner_intent_is_save
    for intent in (
        "capability_question", "identity_question", "casual_chat",
        "vault_summary", "credential_lookup", "document_search",
        "unknown",
    ):
        p = _fake_planner(intent=intent, is_simple=(intent in {
            "capability_question", "identity_question", "casual_chat",
        }))
        assert not planner_intent_is_save(
            planner=p, allowed_tool_names=set(),
        ), f"{intent!r} incorrectly marked as save intent"


def test_intent_was_save_derived_from_allowed_tools_when_planner_missing(
) -> None:
    # Fallback path: no planner decision available — derive from
    # allowed_tools. Save tools present means save intent; otherwise
    # False.
    from vault_chat_save_guard import (
        SAVE_TOOL_NAMES,
        planner_intent_is_save,
    )
    assert planner_intent_is_save(
        planner=None,
        allowed_tool_names={"save_secret", "list_secrets"},
    )
    assert planner_intent_is_save(
        planner=None,
        allowed_tool_names={"save_generated_credential_after_confirmation"},
    )
    assert not planner_intent_is_save(
        planner=None,
        allowed_tool_names={"list_secrets", "get_vault_status"},
    )
    assert not planner_intent_is_save(
        planner=None, allowed_tool_names=set(),
    )
    # Sanity: SAVE_TOOL_NAMES is what the guard file authoritatively
    # exports.
    assert "save_secret" in SAVE_TOOL_NAMES
    assert "save_generated_credential_after_confirmation" in SAVE_TOOL_NAMES
