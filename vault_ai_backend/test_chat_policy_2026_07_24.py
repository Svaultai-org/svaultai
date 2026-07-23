"""Regression tests for ``vault_chat_policy``.

Locks the deterministic authorization rules that keep the LLM
honest — no destructive execution on low confidence, no confirm
on the wrong action_id, no attachment save without the narrow
defense-in-depth gate, no conversational hijack of a pending
destructive action.
"""

from __future__ import annotations

import unittest

from vault_chat_pending_action import (
    KIND_DELETE_SECURE_ITEM,
    KIND_NONE,
    KIND_SAVE_ATTACHMENT,
    KIND_SAVE_CREDENTIAL,
    NONE_PENDING,
    PendingAction,
)
from vault_chat_policy import authorize
from vault_chat_semantic_decider import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    Decision,
)
from vault_chat_tool_registry import (
    TOOL_CANCEL_PENDING_DELETE,
    TOOL_CANCEL_PENDING_SAVE,
    TOOL_CONFIRM_PENDING_DELETE,
    TOOL_CONFIRM_PENDING_SAVE,
    TOOL_CONVERSATIONAL_REPLY,
    TOOL_FALLTHROUGH,
    TOOL_REQUEST_CLARIFICATION,
)
from vault_chat_turn_snapshot import TurnSnapshot


VAULT = "vault-policy-test"


def _snap(user_message: str, pending: PendingAction = NONE_PENDING) -> TurnSnapshot:
    return TurnSnapshot(
        vault_id=VAULT,
        session_id="s-1",
        turn_id="t-1",
        vault_name="Personal",
        reply_language="en",
        user_message=user_message,
        now=1_700_000_000.0,
        pending_action=pending,
        active_entity=None,
        recent_turns=(),
        tool_names=(),
    )


def _pending_delete(action_id="del-1") -> PendingAction:
    return PendingAction(
        kind=KIND_DELETE_SECURE_ITEM, action_id=action_id,
        source_kind="secure_delete_intent",
        target_label="Instagram login",
        created_at=1.0, expires_at=1_000_000.0,
        vault_id=VAULT, is_destructive=True,
        metadata={"item_type": "login"},
    )


def _pending_save_attachment(action_id="file-1") -> PendingAction:
    return PendingAction(
        kind=KIND_SAVE_ATTACHMENT, action_id=action_id,
        source_kind="uploaded_file",
        target_label="video: v.webm",
        created_at=1.0, expires_at=1_000_000.0,
        vault_id=VAULT, session_id="s-1",
        is_destructive=False,
        metadata={"uploaded_file_id": action_id,
                  "content_type": "video/webm",
                  "filename": "v.webm"},
    )


def _decision(tool, args=None, confidence=CONFIDENCE_HIGH) -> Decision:
    return Decision(
        tool=tool, args=dict(args or {}),
        confidence=confidence, why="test",
    )


class TestFallthroughAndClarification(unittest.TestCase):

    def test_fallthrough_always_approved(self):
        r = authorize(
            snapshot=_snap("hi"),
            decision=_decision(TOOL_FALLTHROUGH, confidence=CONFIDENCE_LOW),
        )
        self.assertTrue(r.approved)

    def test_clarification_needs_nonempty_question(self):
        r = authorize(
            snapshot=_snap("delete something"),
            decision=_decision(
                TOOL_REQUEST_CLARIFICATION, args={"question": ""},
            ),
        )
        self.assertFalse(r.approved)

    def test_clarification_ok_with_question(self):
        r = authorize(
            snapshot=_snap("delete something"),
            decision=_decision(
                TOOL_REQUEST_CLARIFICATION,
                args={"question": "Which one did you mean?"},
            ),
        )
        self.assertTrue(r.approved)


class TestConversationalReply(unittest.TestCase):

    def test_low_confidence_conversational_refused(self):
        r = authorize(
            snapshot=_snap("what is a vault"),
            decision=_decision(
                TOOL_CONVERSATIONAL_REPLY,
                args={"reply": "guess"},
                confidence=CONFIDENCE_LOW,
            ),
        )
        self.assertFalse(r.approved)

    def test_conversational_refused_when_destructive_pending(self):
        r = authorize(
            snapshot=_snap("what time is it",
                           pending=_pending_delete()),
            decision=_decision(
                TOOL_CONVERSATIONAL_REPLY,
                args={"reply": "hello!"},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertFalse(r.approved)


class TestDestructiveConfirm(unittest.TestCase):

    def test_confirm_delete_requires_pending(self):
        r = authorize(
            snapshot=_snap("yes"),
            decision=_decision(
                TOOL_CONFIRM_PENDING_DELETE,
                args={"action_id": "anything"},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertFalse(r.approved)
        self.assertIn("no_pending_delete", r.reason)

    def test_confirm_delete_requires_matching_action_id(self):
        r = authorize(
            snapshot=_snap("yes", pending=_pending_delete("del-1")),
            decision=_decision(
                TOOL_CONFIRM_PENDING_DELETE,
                args={"action_id": "del-DIFFERENT"},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertFalse(r.approved)

    def test_confirm_delete_requires_high_confidence(self):
        r = authorize(
            snapshot=_snap("yes", pending=_pending_delete()),
            decision=_decision(
                TOOL_CONFIRM_PENDING_DELETE,
                args={"action_id": "del-1"},
                confidence=CONFIDENCE_MEDIUM,
            ),
        )
        self.assertFalse(r.approved)

    def test_confirm_delete_denies_unrelated_long_reply(self):
        long_reply = (
            "so anyway what were we talking about I forget can you "
            "just remind me thanks a lot!"
        )
        r = authorize(
            snapshot=_snap(long_reply, pending=_pending_delete()),
            decision=_decision(
                TOOL_CONFIRM_PENDING_DELETE,
                args={"action_id": "del-1"},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertFalse(r.approved)
        self.assertIn("destructive_safety_gate", r.reason)

    def test_confirm_delete_ok_high_conf_yes(self):
        r = authorize(
            snapshot=_snap("yes", pending=_pending_delete()),
            decision=_decision(
                TOOL_CONFIRM_PENDING_DELETE,
                args={"action_id": "del-1"},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertTrue(r.approved)

    def test_confirm_delete_ok_natural_variations(self):
        # These are user paraphrases the model would recognize as
        # confirmations. The narrow defense-in-depth gate must
        # accept these too.
        for phrase in [
            "yes",
            "Yes.",
            "yep",
            "yeah do it",
            "ok delete it",
            "sure",
            "confirm",
            "go ahead",
            "delete it",
            "proceed",
        ]:
            r = authorize(
                snapshot=_snap(phrase, pending=_pending_delete()),
                decision=_decision(
                    TOOL_CONFIRM_PENDING_DELETE,
                    args={"action_id": "del-1"},
                    confidence=CONFIDENCE_HIGH,
                ),
            )
            self.assertTrue(
                r.approved,
                msg=f"phrase={phrase!r} rejected: {r.reason}",
            )


class TestSaveAttachment(unittest.TestCase):

    def test_attachment_save_denied_on_long_unrelated_reply(self):
        long_reply = (
            "wait actually I think I was gonna ask you about "
            "something else can we come back to this"
        )
        r = authorize(
            snapshot=_snap(long_reply,
                           pending=_pending_save_attachment()),
            decision=_decision(
                TOOL_CONFIRM_PENDING_SAVE,
                args={"action_id": "file-1",
                      "pending_kind": KIND_SAVE_ATTACHMENT},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertFalse(r.approved)
        self.assertIn("attachment_save_narrow_gate", r.reason)

    def test_attachment_save_ok_short_yes(self):
        r = authorize(
            snapshot=_snap("yes",
                           pending=_pending_save_attachment()),
            decision=_decision(
                TOOL_CONFIRM_PENDING_SAVE,
                args={"action_id": "file-1",
                      "pending_kind": KIND_SAVE_ATTACHMENT},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertTrue(r.approved)


class TestCancelPaths(unittest.TestCase):

    def test_cancel_delete_ok_natural(self):
        r = authorize(
            snapshot=_snap("no", pending=_pending_delete()),
            decision=_decision(
                TOOL_CANCEL_PENDING_DELETE,
                args={"action_id": "del-1"},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertTrue(r.approved)

    def test_cancel_delete_wrong_action_id_denied(self):
        r = authorize(
            snapshot=_snap("no", pending=_pending_delete()),
            decision=_decision(
                TOOL_CANCEL_PENDING_DELETE,
                args={"action_id": "wrong"},
                confidence=CONFIDENCE_HIGH,
            ),
        )
        self.assertFalse(r.approved)


if __name__ == "__main__":
    unittest.main()
