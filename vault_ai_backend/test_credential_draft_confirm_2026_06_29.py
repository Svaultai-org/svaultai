

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import vault_credential_draft as vcd
import vault_pending_draft_confirm as pdc
import vault_saved_item_chat_intent as ci


_VAULT_ID = "11111111-aaaa-bbbb-cccc-dddddddddddd"


class TestExpandedConfirmPhrases(unittest.TestCase):

    def test_new_operator_listed_phrases_match(self):
        for phrase in [
                                                          
            "yea save it", "yeah save it",
            "yep save it", "yup save it",
            "yea", "yeah", "yep", "yup",
            "please save it", "please save",
            "save",                
            "save.", "save!",
        ]:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    pdc.is_pending_draft_confirm_phrase(phrase),
                    f"expanded closed-set must match {phrase!r}",
                )

    def test_classifier_routes_new_phrases_to_confirm(self):
                                                            
                                                                
        for phrase in [
            "save", "yea", "yeah", "yep", "yup",
            "yeah save it", "yep save it",
            "please save it", "please save",
        ]:
            with self.subTest(phrase=phrase):
                out = ci.classify_secure_item_intent(phrase)
                self.assertEqual(out.intent, ci.INTENT_CONFIRM_SAVE)

    def test_negatives_still_do_not_match(self):
        for phrase in [
            "savings",                                                   
            "saved",                              
            "save and exit",                            
            "pleasure save",                 
            "I'll save it later",                            
        ]:
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    pdc.is_pending_draft_confirm_phrase(phrase),
                )


_MAIN_PY = Path("main.py")


def _read_main() -> str:
    return _MAIN_PY.read_text(encoding="utf-8")


class TestMainPyWiringCredentialStore(unittest.TestCase):

    def test_main_imports_consume_draft_from_credential_store(self):
        src = _read_main()
        self.assertIn(
            "from vault_credential_draft import consume_draft",
            src,
            msg=(
                "main.py must consume the per-vault credential "
                "draft store inside the confirm pre-check — the "
                "legacy memory dict is no longer the source of "
                "truth for the new generate_credential_draft tool."
            ),
        )

    def test_main_calls_consume_credential_draft_before_legacy_memory(self):
        # 2026-07-31 refinement: the invariant this test protects is
        # "the persistent credential-draft consume runs BEFORE the
        # LEGACY state-machine pick-up." After the deterministic
        # pre-router relocation (d184d22), a router-side pending-draft
        # PEEK (not consume) now legitimately runs earlier — it only
        # decides whether the router should skip so the state machine
        # downstream keeps ownership of pending-draft turns. That peek
        # is not the legacy consume path; matching the first
        # `memory.get("pending_login_draft")` byte-offset in the file
        # was too coarse. Anchor the search to the state-machine
        # block (identified by its `_sm_draft` local, which is the
        # variable the state machine reads) instead.
        src = _read_main()
        idx_consume = src.find("_consume_credential_draft(")
        idx_legacy  = src.find('_sm_draft = memory.get("pending_login_draft")')
        self.assertGreater(idx_consume, 0,
            "_consume_credential_draft(...) call missing from main.py",
        )
        self.assertGreater(idx_legacy, 0,
            "legacy state-machine `_sm_draft` read from memory "
            "missing — the state-machine cascade may have been "
            "deleted",
        )
        self.assertLess(
            idx_consume, idx_legacy,
            "Persistent credential-draft consume must run BEFORE "
            "the legacy state-machine memory[\"pending_login_draft\"] "
            "pick-up.",
        )

    def test_main_credential_trace_marks_persistent_store(self):
                                                             
                                                             
        src = _read_main()
        self.assertIn("store=persistent", src)

    def test_main_returns_friendly_saved_message_on_persistent_consume(self):
        src = _read_main()
        self.assertIn("Saved your", src)
        self.assertIn("login to ", src)
        self.assertIn("your vault", src)


class TestCredentialDraftEndToEnd(unittest.TestCase):


    def setUp(self):
        vcd._reset_store_for_test()

    def tearDown(self):
        vcd._reset_store_for_test()

    def test_stage_then_confirm_consumes_draft(self):
        d = vcd.store_draft(
            vault_id=_VAULT_ID,
            service_name="Instagram",
            username="user_chosen-3399",
            password="instagram-Strong-Pass-7711",
        )
        self.assertIsNotNone(d)
        self.assertFalse(d.saved)
                                      
        consumed = vcd.consume_draft(vault_id=_VAULT_ID)
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed.service_name, "Instagram")
        self.assertEqual(consumed.username,    "user_chosen-3399")
        self.assertEqual(consumed.password,    "instagram-Strong-Pass-7711")
        self.assertTrue(consumed.saved)
                                                            
        self.assertIsNone(vcd.consume_draft(vault_id=_VAULT_ID))

    def test_no_draft_consume_returns_none(self):
        self.assertIsNone(vcd.consume_draft(vault_id=_VAULT_ID))


class TestDraftPromptCopy(unittest.TestCase):

    def test_tools_prompt_says_save_it_not_save_it_now(self):
                                                           
                                                         
        src = Path("tools.py").read_text(encoding="utf-8")
                                                       
                                            
        idx = src.find("CREDENTIAL CREATION DRAFT")
        self.assertGreater(idx, 0)
        snippet = src[idx:idx + 800]
        self.assertIn('Say "save it" when you want me to store it', snippet)
        self.assertNotIn('Say "save it now"', snippet)

    def test_vault_secure_item_save_prompt_says_save_it(self):
                                                              
                                                              
        from vault_secure_item_save import _render_draft_message
        msg = _render_draft_message(title="iPhone 15 IMEI")
        self.assertIn("save it", msg.lower())
        self.assertNotIn("save it now", msg.lower())

    def test_chat_save_guard_correction_text_says_save_it(self):
        from vault_chat_save_guard import SAFE_CORRECTION_TEXT
        self.assertIn("save it", SAFE_CORRECTION_TEXT.lower())
        self.assertNotIn('"save it now"', SAFE_CORRECTION_TEXT)


class TestPrivacyFloor(unittest.TestCase):

    def test_credential_trace_line_carries_only_prefixes(self):
        src = _read_main()
                                                     
        idx = src.find("[CHAT-TRACE] pending_credential_confirmed")
        self.assertGreater(idx, 0)
                                                             
        snippet = src[idx:idx + 600]
                                                                 
        self.assertNotIn("password", snippet.lower())
        self.assertNotIn("decrypted_message", snippet)
        self.assertNotIn("_draft_password", snippet)
        self.assertNotIn("_draft_username", snippet)

    def test_credential_draft_repr_redacts_password(self):
                                                                 
                                                            
        d = vcd.CredentialDraft(
            draft_id="abc123",
            vault_id=_VAULT_ID,
            service_name="Instagram",
            username="u",
            password="instagram-secret-pw",
            created_at=0.0,
            expires_at=999999.0,
            saved=False,
            service_key="instagram",
        )
        self.assertNotIn("instagram-secret-pw", repr(d))
        self.assertIn("REDACTED", repr(d))


class TestNoDraftFallbackUnchanged(unittest.TestCase):


    def test_save_themed_subset_includes_new_phrases(self):
        for phrase in [
            "save", "please save it", "yeah save it",
            "yep save it", "yup save it",
        ]:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    pdc.is_save_themed_confirm_phrase(phrase),
                )

    def test_bare_colloquial_yes_NOT_in_save_themed(self):
                                                        
                                                            
        for phrase in ["yeah", "yep", "yup", "yea"]:
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    pdc.is_save_themed_confirm_phrase(phrase),
                    f"bare colloquial yes {phrase!r} must NOT be "
                    f"in the save-themed subset",
                )


if __name__ == "__main__":                    
    unittest.main()
