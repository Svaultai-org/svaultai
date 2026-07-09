

from __future__ import annotations

import unittest

from vault_brain_intent import (
    classify_brain_intent,
    NOT_VAULT_CONTENT,
    CREDENTIAL_LOOKUP,
    SEARCH_VAULT_CONTENT,
)


_CREDENTIAL_FILES_QUERY_CORPUS = (
                                         
    "is there any files in my vault that has list of credentials "
    "or login details in them?",
                  
    "are there any files in my vault with saved credentials",
    "is there any file in my vault that contains login details",
    "do i have any files that contain passwords",
    "do I have any files with my logins saved in them",
    "which files contain passwords",
    "which files have my login details",
    "what files contain saved credentials",
    "find files with passwords",
    "find files that contain passwords",
    "search my vault for files with credentials",
    "search for files containing login details",
    "look for files holding credentials",
    "list of credentials in files",
    "list of credentials in any file in my vault",
    "list files that have passwords",
    "show me files with login details",
    "show me files containing credentials",
    "show me files that have credentials saved in it",
    "any files with credentials",
    "any file that has my passwords",
    "scan my files for passwords",
    "find files with usernames and passwords",
)


_CREDENTIAL_SINGLE_LOOKUP_CORPUS = (
    "what's my Chase password",
    "what is my Gmail password",
    "what did I save about my card",
    "my Ally Bank routing number",
    "what's my apple id password",
    "what did i save about my netflix login",
    "what's my recovery code",
    "what's my paypal password",
)


class CredentialFilesQueriesRouteToStrictMemory(unittest.TestCase):


    def test_user_literal_screenshot_phrasing_defers_to_strict_verifier(
        self,
    ):
        msg = (
            "is there any files in my vault that has list of "
            "credentials or login details in them?"
        )
        result = classify_brain_intent(msg)
        self.assertEqual(
            result.intent, CREDENTIAL_LOOKUP,
            f"User's literal screenshot phrasing routed to "
            f"{result.intent!r} (reason={result.reason!r}) — should "
            f"defer to legacy strict verifier.",
        )
        self.assertEqual(
            result.reason,
            "credential_files_strict_memory",
        )

    def test_every_credential_files_phrasing_defers_to_strict_verifier(
        self,
    ):
        for msg in _CREDENTIAL_FILES_QUERY_CORPUS:
            with self.subTest(msg=msg):
                result = classify_brain_intent(msg)
                self.assertEqual(
                    result.intent, CREDENTIAL_LOOKUP,
                    f"{msg!r} routed to {result.intent!r} (reason="
                    f"{result.reason!r}) — should defer to legacy "
                    f"strict verifier.",
                )


class SingleCredentialLookupsStayOnBrain(unittest.TestCase):


    def test_every_single_credential_lookup_stays_on_brain(self):
        for msg in _CREDENTIAL_SINGLE_LOOKUP_CORPUS:
            with self.subTest(msg=msg):
                result = classify_brain_intent(msg)
                self.assertEqual(
                    result.intent, CREDENTIAL_LOOKUP,
                    f"{msg!r} should stay on CREDENTIAL_LOOKUP; "
                    f"got {result.intent!r} (reason={result.reason!r})",
                )


class FollowupContextStillRoutesToBrain(unittest.TestCase):


    def test_follow_up_with_context_routes_to_credential_lookup(self):
        result = classify_brain_intent(
            "are these both the only files with list of credentials in it?",
            has_continuation_context=True,
        )
        self.assertEqual(result.intent, CREDENTIAL_LOOKUP)
        self.assertEqual(
            result.reason, "credential_coverage_followup",
        )

    def test_follow_up_paraphrase_with_context_routes_to_credential_lookup(
        self,
    ):
        result = classify_brain_intent(
            "are these all the files that have my passwords",
            has_continuation_context=True,
        )
        self.assertEqual(result.intent, CREDENTIAL_LOOKUP)


class NonCredentialFileSearchesStillRouteToBrain(unittest.TestCase):


    def test_files_about_taxes_stays_on_brain(self):
        result = classify_brain_intent(
            "do I have any files about taxes",
        )
        self.assertEqual(result.intent, SEARCH_VAULT_CONTENT)

    def test_files_with_contracts_stays_on_brain(self):
        result = classify_brain_intent(
            "find files with my apartment contract",
        )
                                                               
                                                                  
        self.assertEqual(result.intent, SEARCH_VAULT_CONTENT)

    def test_summarise_file_stays_on_brain(self):
        result = classify_brain_intent("summarize this file")
                                 
        self.assertNotEqual(result.intent, NOT_VAULT_CONTENT)


class ChatHandlerWiresCredentialFilesIntentToStrictVerifier(
    unittest.TestCase,
):


    def _main_src(self) -> str:
        import os
        candidates = [
            os.path.join(os.path.dirname(__file__), "main.py"),
            r"c:\Users\user\Desktop\Vaultai\vault_ai_backend\main.py",
        ]
        for p in candidates:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
        self.skipTest("main.py not reachable from this test runner.")

    def test_credential_intent_branch_calls_strict_verifier(self):
        src = self._main_src()
                                             
                                                       
        branch_start = src.find(
            'if intent == "search_files_for_credentials":',
        )
        self.assertGreater(
            branch_start, -1,
            "credential branch missing in main.py",
        )
                                                                  
        branch_end = src.find(
            'if intent == "extract_logins_from_file"', branch_start,
        )
        body = src[branch_start:branch_end]
        self.assertIn(
            "verified_credential_files_report", body,
            "credential branch must use the strict verifier (no "
            "loose ranker / no brain semantic fallback).",
        )
                                                                  
                 
        self.assertIn(
            "make_credential_search_result", body,
        )
        self.assertIn(
            "set_last_assistant_result", body,
        )


if __name__ == "__main__":
    unittest.main()
