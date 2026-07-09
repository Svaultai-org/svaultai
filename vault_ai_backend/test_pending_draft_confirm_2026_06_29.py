

from __future__ import annotations

import inspect
import unittest
from pathlib import Path

import vault_pending_draft_confirm as pdc
import vault_saved_item_chat_intent as ci


class TestConfirmPhraseClosedSet(unittest.TestCase):

    def test_operator_listed_phrases_all_match(self):
                                                                 
                         
        for phrase in [
            "save it", "save it now",
            "save this",
            "save that", "save that now",
            "save now",
            "yes",
            "yes save it", "yes save this",
            "confirm",
            "confirm save",
            "go ahead", "go ahead and save",
            "store it", "store this",
            "keep it",
            "add it", "add this",
            "ok save it", "okay save it", "ok, save it",
            "sure save it", "sure, save it",
            "do it",
        ]:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    pdc.is_pending_draft_confirm_phrase(phrase),
                    f"closed-set must match {phrase!r}",
                )

    def test_negatives_do_not_match(self):
                                                                
                                               
        for phrase in [
            "I'll save it later",
            "no",
            "cancel",
            "show me my logins",
            "maybe",
            "whatever",
            "yes definitely save it for me later when I'm home",
            "delete it",
            "remove it",
            "",
            "   ",
        ]:
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    pdc.is_pending_draft_confirm_phrase(phrase),
                    f"closed-set must NOT match {phrase!r}",
                )

    def test_handles_non_string_input(self):
        for v in (None, 42, [], {}, object()):
            self.assertFalse(pdc.is_pending_draft_confirm_phrase(v))


class TestSaveThemedSubset(unittest.TestCase):

    def test_save_themed_phrases_match(self):
        for phrase in [
            "save it", "save it now", "save this", "save that",
            "save now",
            "yes save it", "yes, save it",
            "confirm save",
            "go ahead and save",
            "store it", "keep it", "add it",
            "ok save it", "okay save it",
            "sure save it",
        ]:
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    pdc.is_save_themed_confirm_phrase(phrase),
                )

    def test_bare_confirm_phrases_do_NOT_fire_save_themed(self):
                                                                 
                                                                 
        for phrase in [
            "yes", "confirm", "go ahead", "do it",
        ]:
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    pdc.is_save_themed_confirm_phrase(phrase),
                    f"save-themed subset must NOT match bare {phrase!r}",
                )


class TestSecureItemClassifierConfirmCoverage(unittest.TestCase):

    def test_classifier_routes_each_phrase_to_confirm(self):
        for phrase in [
            "save it", "save it now",
            "save this", "save that", "save now",
            "yes", "yes save it",
            "confirm", "confirm save",
            "go ahead", "go ahead and save",
            "store it", "keep it", "add it",
            "ok save it", "sure save it",
            "do it",
        ]:
            with self.subTest(phrase=phrase):
                out = ci.classify_secure_item_intent(phrase)
                self.assertEqual(
                    out.intent, ci.INTENT_CONFIRM_SAVE,
                    f"classifier must map {phrase!r} to INTENT_CONFIRM_SAVE",
                )


class TestNoDraftFriendlyReply(unittest.TestCase):

    def test_no_draft_reply_is_friendly_not_generic(self):
                                                              
                                                              
        self.assertNotIn(
            "specific information",
            pdc.NO_DRAFT_FRIENDLY_REPLY.lower(),
        )
                                                             
                     
        self.assertIn("pending save", pdc.NO_DRAFT_FRIENDLY_REPLY.lower())


_MAIN_PY = Path("main.py")


def _read_main() -> str:
    return _MAIN_PY.read_text(encoding="utf-8")


class TestMainPyWiring(unittest.TestCase):


    def test_main_imports_pending_draft_helpers(self):
        src = _read_main()
        self.assertIn(
            "from vault_pending_draft_confirm import",
            src,
        )
        self.assertIn("is_pending_draft_confirm_phrase", src)
        self.assertIn("is_save_themed_confirm_phrase", src)
        self.assertIn("NO_DRAFT_FRIENDLY_REPLY", src)

    def test_main_calls_save_secret_tool_on_credential_confirm(self):
        src = _read_main()
        self.assertIn("pending_login_draft", src)
        self.assertIn("save_secret_tool(", src)

    def test_main_calls_clear_active_context_after_credential_save(self):
        src = _read_main()
                                                             
                                   
        self.assertIn("clear_active_context", src)

    def test_main_returns_friendly_reply_for_save_themed_no_draft(self):
        src = _read_main()
                                                         
        self.assertIn("NO_DRAFT_FRIENDLY_REPLY", src)
        self.assertIn("_pending_save_themed", src)


class TestPrivacyFloor(unittest.TestCase):

    def test_helper_does_not_log_or_print_user_message(self):
        src = inspect.getsource(pdc)
                                                              
        self.assertNotIn("print(", src)
        self.assertNotIn("logger", src)
        self.assertNotIn(".log(", src)
        self.assertNotIn(".info(", src)
        self.assertNotIn(".warning(", src)
        self.assertNotIn(".error(", src)

    def test_main_confirm_credential_trace_carries_only_prefix(self):
                                                                 
                                                                 
        src = _read_main()
                                            
        idx = src.find("pending_credential_confirmed")
        self.assertGreater(
            idx, 0,
            "main.py must emit the closed-set CHAT-TRACE line "
            "for credential confirm",
        )
                                               
        snippet = src[idx:idx + 400]
                                                         
        self.assertNotIn("password", snippet)
        self.assertNotIn("decrypted_message", snippet)
        self.assertNotIn("_draft_password", snippet)


if __name__ == "__main__":                    
    unittest.main()
