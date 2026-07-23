# Pending-draft continuity regression (2026-07-21).
#
# Proves that an unrelated conversational question during a pending
# credential-draft workflow does NOT:
#   * hijack the answer,
#   * discard the draft,
#   * silently save it,
#   * or make it impossible to resume the original workflow.
#
# The full 9-step scenario the deliverable requires:
#
#   1. User:    "Save my Netflix login."
#   2. VaultAI: creates/holds a pending credential draft.
#   3. User:    "Actually, what are you?"       (identity question)
#   4. VaultAI: answers the identity question normally.
#   5.          — No save tool runs.
#   6.          — No credential is written.
#   7.          — The pending draft is preserved (not deleted /
#                 not corrupted).
#   8. User:    "Save it now."                  (deterministic resume)
#   9. VaultAI: consumes and saves the original Netflix draft.
#
# Also runs the same continuity flow with "who are you?" and
# "what can you do?" per the deliverable.
#
# What this suite proves at the unit-test layer (no LLM required):
#
#   * The deterministic pending-draft confirmation regex
#     (vault_pending_draft_confirm.is_pending_draft_confirm_phrase)
#     REJECTS identity/capability questions and the initial save
#     request — none of them consume the draft.
#   * The in-process draft store (vault_credential_draft._store) is
#     unmodified across those turns; consume_draft is only entered
#     when the CURRENT message matches the confirmation regex.
#   * On the resume turn, the canonical "save it now" confirmation
#     phrase matches, consume_draft returns the original draft with
#     saved=True and the same service/username/password fields, and
#     the store is left empty.
#   * The 2026-07-21 save-guard fix (f3c3f13) does NOT touch the
#     draft store on capability-answer turns — guard_response_text
#     is pure w.r.t. the draft store.

from __future__ import annotations

from typing import Iterator

import pytest

import vault_credential_draft
from vault_chat_save_guard import guard_response_text
from vault_credential_draft import (
    CredentialDraft,
    consume_draft,
    get_draft,
    store_draft,
)
from vault_pending_draft_confirm import (
    is_pending_draft_confirm_phrase,
    is_save_themed_confirm_phrase,
)


# The shared chat-state backend persists across tests, so we reset
# it before each test to isolate the scenario. As of 2026-07-22 the
# draft store is Redis-backed in production and in-memory in tests
# (see vault_chat_state_store); the pre-fix per-process
# ``_store`` dict no longer exists.
@pytest.fixture(autouse=True)
def _reset_draft_store() -> Iterator[None]:
    vault_credential_draft._reset_store_for_test()
    yield
    vault_credential_draft._reset_store_for_test()


VAULT_ID = "00000000-0000-4000-8000-0000000000f1"


def _place_netflix_draft() -> CredentialDraft:
    # Step 1-2 modelling: the user asked to "Save my Netflix login."
    # The end-to-end code path (vault_inspection_tools.py:1430
    # + LLM tool call) writes a CredentialDraft to
    # vault_credential_draft._store. We stub that outcome directly
    # so the continuity test does not depend on an LLM.
    return store_draft(
        vault_id=VAULT_ID,
        service_name="Netflix",
        username="alexa@example.com",
        password="ZQ3-fresh-generated-pw!42",
    )


# ---------------------------------------------------------------------------
# Confirmation regex boundary — the doorway that decides whether the
# NEXT turn consumes the pending draft or leaves it alone.
# ---------------------------------------------------------------------------


class TestConfirmPhraseBoundary:
    # The heart of the continuity guarantee: the confirmation regex
    # must reject anything that isn't clearly a save-confirmation.
    # Anything false-positive here would silently save on an
    # unrelated turn.

    @pytest.mark.parametrize(
        "unrelated_question",
        [
            # From the deliverable's core scenario.
            "actually, what are you?",
            "what are you",
            # From the same-flow variants the deliverable calls out.
            "who are you?",
            "who are you",
            "what can you do?",
            "what can you do",
            # Casual / typo variants (per prior fix's requirements).
            "what are u",
            "who r u",
            # The initial save REQUEST must not be treated as its
            # own confirmation.
            "save my netflix login",
            "save my Netflix login.",
            "please save my netflix login",
        ],
    )
    def test_unrelated_or_request_does_not_match_confirmation(
        self, unrelated_question: str,
    ) -> None:
        assert is_pending_draft_confirm_phrase(unrelated_question) is False
        assert is_save_themed_confirm_phrase(unrelated_question) is False

    @pytest.mark.parametrize(
        "resume_phrase",
        [
            # 2026-07-24 chat-brain rebuild — narrowed regex
            # covers "save"-mentioning phrasings only. Bare
            # "yes", "confirm", "go ahead", "do it" now go
            # through the semantic decider.
            "save it now",
            "save it",
            "save this",
            "ok save it",
            "okay save it",
            "please save it",
        ],
    )
    def test_canonical_resume_phrases_match_confirmation(
        self, resume_phrase: str,
    ) -> None:
        assert is_pending_draft_confirm_phrase(resume_phrase) is True

    @pytest.mark.parametrize(
        "phrase_removed_from_broad_regex",
        ["yes", "confirm", "go ahead", "do it"],
    )
    def test_removed_bare_phrases_no_longer_match(
        self, phrase_removed_from_broad_regex: str,
    ) -> None:
        """Regression-lock the 2026-07-24 narrowing. These
        phrases must NOT match the broad save-confirm regex any
        more — they go through the semantic decider."""
        assert is_pending_draft_confirm_phrase(
            phrase_removed_from_broad_regex,
        ) is False


# ---------------------------------------------------------------------------
# Full 9-step continuity — unrelated turn between draft creation and
# resume must not disturb the draft.
# ---------------------------------------------------------------------------


class TestPendingDraftContinuity:
    @pytest.mark.parametrize(
        "unrelated_question",
        [
            "actually, what are you?",
            "who are you?",
            "what can you do?",
        ],
    )
    def test_full_9_step_continuity(
        self, unrelated_question: str,
    ) -> None:
        # ── Step 1-2: user asks to save; a pending draft is placed
        # in the store as the LLM would after generating one.
        original = _place_netflix_draft()
        assert get_draft(vault_id=VAULT_ID) is not None
        original_before = get_draft(vault_id=VAULT_ID)
        assert original_before is not None
        assert original_before.service_name == "Netflix"
        assert original_before.username == "alexa@example.com"
        assert original_before.password == "ZQ3-fresh-generated-pw!42"
        assert original_before.saved is False

        # ── Step 3: user asks an unrelated question. This must NOT
        # match the confirmation regex — the /chat handler's
        # _pending_confirm branch at main.py:12978 is skipped, so
        # consume_draft is never called for this turn.
        assert is_pending_draft_confirm_phrase(unrelated_question) is False

        # ── Step 4-5: simulate the guard step that runs on every
        # /chat reply. On an unrelated capability turn intent_was_save
        # is False (see f3c3f13 wiring). The guard must:
        #   * NOT rewrite a natural identity reply
        #   * NOT touch the draft store
        capability_reply = (
            "I'm VaultAI, an AI keeper for your private vault. Your "
            "credentials are stored securely and I can retrieve them "
            "on request."
        )
        guarded, slug = guard_response_text(
            reply_text=capability_reply,
            save_tool_succeeded=False,
            intent_was_save=False,
        )
        assert guarded == capability_reply, (
            "guard hijacked a capability answer during a pending-draft "
            "workflow — draft continuity would be visible to the user "
            "as a fabricated login-draft claim"
        )
        assert slug is None

        # ── Step 6-7: the pending draft is untouched.
        after_unrelated = get_draft(vault_id=VAULT_ID)
        assert after_unrelated is not None, (
            "pending draft was discarded by an unrelated turn — "
            "continuity broken"
        )
        assert after_unrelated.draft_id == original_before.draft_id, (
            "pending draft's identity changed across an unrelated turn"
        )
        assert after_unrelated.service_name == "Netflix"
        assert after_unrelated.username == "alexa@example.com"
        assert after_unrelated.password == "ZQ3-fresh-generated-pw!42"
        assert after_unrelated.saved is False

        # ── Step 8: user resumes with the canonical confirmation
        # phrase "save it now". This DOES match the confirmation
        # regex, so the /chat handler enters the _pending_confirm
        # branch and calls consume_draft.
        assert is_pending_draft_confirm_phrase("save it now") is True

        consumed = consume_draft(vault_id=VAULT_ID)

        # ── Step 9: the ORIGINAL Netflix draft (not a fresh one, not
        # a corrupted one, not an unrelated service) is what got
        # consumed.
        assert consumed is not None, (
            "resume turn could not consume the original pending draft — "
            "the draft was lost between step 2 and step 8"
        )
        assert consumed.draft_id == original.draft_id
        assert consumed.service_name == "Netflix"
        assert consumed.username == "alexa@example.com"
        assert consumed.password == "ZQ3-fresh-generated-pw!42"
        assert consumed.saved is True

        # Post-consume: the store is empty for this vault.
        assert get_draft(vault_id=VAULT_ID) is None


# ---------------------------------------------------------------------------
# Multi-turn survival — the same draft must survive N unrelated turns
# in a row, not just one. Protects against a subtle bug where the
# first unrelated turn preserves the draft but a follow-up turn
# accidentally clears it.
# ---------------------------------------------------------------------------


class TestMultipleUnrelatedTurnsPreserveDraft:
    def test_three_unrelated_turns_do_not_disturb_draft(self) -> None:
        _place_netflix_draft()
        for msg in (
            "who are you?",
            "what can you do?",
            "what are you again?",
        ):
            assert is_pending_draft_confirm_phrase(msg) is False
            _guarded, _slug = guard_response_text(
                reply_text="I'm VaultAI, your private vault assistant.",
                save_tool_succeeded=False,
                intent_was_save=False,
            )
            draft = get_draft(vault_id=VAULT_ID)
            assert draft is not None, (
                f"draft was discarded after unrelated turn: {msg!r}"
            )
            assert draft.service_name == "Netflix"
            assert draft.saved is False

        # Still resumable at the end.
        consumed = consume_draft(vault_id=VAULT_ID)
        assert consumed is not None
        assert consumed.service_name == "Netflix"


# ---------------------------------------------------------------------------
# No silent side-effect from the unrelated turn's guard pass.
# ---------------------------------------------------------------------------


class TestGuardHasNoDraftSideEffect:
    def test_guard_on_capability_answer_leaves_draft_bit_identical(
        self,
    ) -> None:
        # The guard is a post-hoc text sanitizer. It has no access to
        # the draft store. This test locks that isolation in — if a
        # future refactor makes the guard "smarter" by peeking at
        # drafts, the isolation must be preserved.
        original = _place_netflix_draft()
        before = get_draft(vault_id=VAULT_ID)
        assert before is not None

        # A pathological reply that contains BOTH strong-form save
        # language AND descriptive vault prose. On an intent_was_save
        # =False turn, the strong form still triggers a rewrite; on
        # an intent_was_save=True turn, both trigger. Neither should
        # touch the draft.
        pathological = (
            "I've saved your Netflix credentials — your credentials "
            "are stored securely in your vault now."
        )
        for intent in (False, True):
            _reply, _slug = guard_response_text(
                reply_text=pathological,
                save_tool_succeeded=False,
                intent_was_save=intent,
            )
            after = get_draft(vault_id=VAULT_ID)
            assert after is not None, (
                f"guard side-effected on intent_was_save={intent!r}"
            )
            assert after.draft_id == original.draft_id
            assert after.password == original.password
            assert after.saved is False
