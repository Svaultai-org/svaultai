"""Tests for the Phase II conversation digest + snapshot
enrichment.

The digest is a deterministic, cheap summary derived from the
turn snapshot inputs. This test locks:

    * digest is empty when there is nothing meaningful to say
    * digest surfaces the user's first-turn topic AND the
      assistant's most recent reply
    * digest includes pending-action headline when one is live
    * digest is length-capped
    * NEVER contains vault plaintext or secrets

Also locks the new active-entity candidate list surfacing
inside the snapshot's prompt dict.
"""

from __future__ import annotations

import unittest

from vault_chat_active_entity import (
    ACTION_DELETE, ACTION_SHOW, ENTITY_LOGIN,
    clear_active_entity, set_active_entity,
)
from vault_chat_conversation_digest import (
    MAX_DIGEST_CHARS, build_digest,
)
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_chat_turn_snapshot import (
    MAX_HISTORY_TURNS, build_turn_snapshot,
)


VAULT = "vault-p2-digest"
SESS = "sess-p2"


class TestDigest(unittest.TestCase):

    def test_empty_inputs_return_empty_digest(self):
        self.assertEqual(
            build_digest(
                recent_user_turns=[],
                recent_assistant_turns=[],
            ),
            "",
        )

    def test_first_user_turn_and_last_assistant_reply_surface(self):
        digest = build_digest(
            recent_user_turns=[
                "what's my gmail login",
                "show me the second one",
                "delete it",
            ],
            recent_assistant_turns=[
                "Found 2 Gmail logins.",
                "Which one — personal or work?",
                "Are you sure you want to delete Gmail (personal)?",
            ],
        )
        self.assertIn("what's my gmail login", digest)
        self.assertIn("Are you sure", digest)

    def test_pending_action_surfaces(self):
        digest = build_digest(
            recent_user_turns=["delete my gmail"],
            recent_assistant_turns=[],
            pending_kind="delete_secure_item",
            pending_target_label="Gmail login",
        )
        self.assertIn("delete_secure_item", digest)
        self.assertIn("Gmail login", digest)

    def test_multi_match_flag_surfaces(self):
        digest = build_digest(
            recent_user_turns=["show me my gmail"],
            recent_assistant_turns=[],
            active_entity_label="Gmail",
            active_entity_is_multi=True,
        )
        self.assertIn("Gmail", digest)
        self.assertIn("multi-match", digest)

    def test_digest_is_length_capped(self):
        long_user_text = "a" * 500
        digest = build_digest(
            recent_user_turns=[long_user_text],
            recent_assistant_turns=[],
        )
        self.assertLessEqual(len(digest), MAX_DIGEST_CHARS)

    def test_digest_does_not_include_password_or_secret_by_shape(self):
        # The module is a pure function that only reflects inputs
        # back. We assert it never invents extra text.
        digest = build_digest(
            recent_user_turns=["show me my netflix login"],
            recent_assistant_turns=["Found 1 login."],
        )
        for forbidden in ("password", "pin", "seed", "private_key"):
            self.assertNotIn(forbidden, digest.lower(),
                             f"digest must not surface {forbidden!r}")


class TestSnapshotEnrichment(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        clear_active_entity(VAULT)

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_history_capacity_raised_to_12(self):
        # Phase II moved MAX_HISTORY_TURNS from 6 to 12.
        self.assertEqual(MAX_HISTORY_TURNS, 12)

    def test_active_entity_candidates_surface_in_prompt_dict(self):
        set_active_entity(
            VAULT,
            entity_type=ENTITY_LOGIN,
            entity_ref={"query": "gmail"},
            display_label="Gmail",
            allowed_actions=[ACTION_SHOW, ACTION_DELETE],
            session_id=SESS,
            is_multi=True,
            candidates=[
                {"id": "aa11", "service": "gmail-personal"},
                {"id": "bb22", "service": "gmail-work"},
            ],
        )
        snap = build_turn_snapshot(
            vault_id=VAULT, session_id=SESS,
            turn_id="t-1", vault_name="P",
            reply_language="en",
            user_message="show me the second one",
        )
        prompt = snap.to_prompt_dict()
        entity = prompt.get("active_entity")
        self.assertIsNotNone(entity)
        cands = entity.get("candidates")
        self.assertEqual(len(cands), 2)
        self.assertIn("id", cands[0])
        self.assertEqual(cands[0]["service"], "gmail-personal")

    def test_digest_appears_in_prompt_dict_when_meaningful(self):
        # No recent turns, no pending, no entity → digest empty
        # → prompt_dict omits (or has empty) conversation_digest.
        snap_empty = build_turn_snapshot(
            vault_id=VAULT, session_id=SESS, turn_id="t-1",
            vault_name="P", reply_language="en",
            user_message="hi",
        )
        prompt_empty = snap_empty.to_prompt_dict()
        self.assertIn(prompt_empty.get("conversation_digest") or "", ("", None))

        # With a pending action → digest is populated.
        from vault_secure_item_delete_confirmation import store_delete_intent
        store_delete_intent(
            vault_id=VAULT, service="Instagram", item_type="login",
        )
        snap = build_turn_snapshot(
            vault_id=VAULT, session_id=SESS, turn_id="t-2",
            vault_name="P", reply_language="en",
            user_message="yes",
        )
        prompt = snap.to_prompt_dict()
        digest = prompt.get("conversation_digest") or ""
        self.assertIn("delete_secure_item", digest)


if __name__ == "__main__":
    unittest.main()
