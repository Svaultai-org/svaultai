

from __future__ import annotations

import re
import unittest

from vault_brain_intent import (
    is_credential_files_query,
    looks_like_vault_files_question,
)


SCREENSHOT_QUERY = (
    "is there any files in my vault that has list of credentials "
    "or login details in them?"
)


class TestIsCredentialFilesQuery(unittest.TestCase):


    def test_screenshot_query_matches(self):
        self.assertTrue(is_credential_files_query(SCREENSHOT_QUERY))

    def test_paraphrases_match(self):
        for phrasing in (
            "any files with credentials",
            "do I have any files with my logins saved in them",
            "files with passwords",
            "files that contain saved credentials",
            "files holding credentials",
            "list of credentials in any file in my vault",
            "is there a file with my login details",
        ):
            with self.subTest(phrasing=phrasing):
                self.assertTrue(
                    is_credential_files_query(phrasing),
                    f"expected credential-files match: {phrasing!r}",
                )

    def test_non_credential_files_questions_do_not_match(self):
        for phrasing in (
            "do I have any files about my house",
            "find my tax return file",
            "what's my Chase password",
            "show my saved logins",
            "list my passwords",
            "summarize the lease",
        ):
            with self.subTest(phrasing=phrasing):
                self.assertFalse(
                    is_credential_files_query(phrasing),
                    f"unexpected credential-files match: {phrasing!r}",
                )

    def test_empty_and_falsy_inputs(self):
        self.assertFalse(is_credential_files_query(""))
        self.assertFalse(is_credential_files_query(None))


class TestLooksLikeVaultFilesQuestion(unittest.TestCase):


    def test_file_nouns_match(self):
        for phrasing in (
            "do I have any files about my house",
            "show me my documents",
            "find my last upload",
            "what does this pdf say",
            "are there any pictures of receipts",
        ):
            with self.subTest(phrasing=phrasing):
                self.assertTrue(looks_like_vault_files_question(phrasing))

    def test_no_file_noun_no_match(self):
        for phrasing in (
            "hello",
            "what's my Chase password",
            "good morning",
            "show my saved logins",
        ):
            with self.subTest(phrasing=phrasing):
                self.assertFalse(looks_like_vault_files_question(phrasing))


class TestVaultFunctionsFilter(unittest.TestCase):


    def setUp(self):
                                                              
                                                                  
        from main import _vault_functions_for_message, VAULT_FUNCTIONS
        self._filter = _vault_functions_for_message
        self._all = VAULT_FUNCTIONS

    def _names(self, tools):
        return {fn.get("function", {}).get("name") for fn in tools}

    def test_screenshot_query_strips_list_secrets(self):
        tools = self._filter(SCREENSHOT_QUERY)
        names = self._names(tools)
        self.assertNotIn(
            "list_secrets",
            names,
            "list_secrets must be blocked for the screenshot query",
        )
                                                                 
                                   
        self.assertIn("save_secret", names)
        self.assertIn("retrieve_secret", names)

    def test_file_shaped_question_strips_list_secrets(self):
        for phrasing in (
            "do I have any files about my house",
            "show me my documents",
            "what does this pdf say",
        ):
            with self.subTest(phrasing=phrasing):
                names = self._names(self._filter(phrasing))
                self.assertNotIn("list_secrets", names)

    def test_non_file_question_keeps_full_tool_list(self):
                                                               
                                                             
        for phrasing in (
            "what's my Chase password",
        ):
            with self.subTest(phrasing=phrasing):
                names = self._names(self._filter(phrasing))
                self.assertIn("list_secrets", names)
                self.assertIn("save_secret", names)
                self.assertIn("retrieve_secret", names)

    def test_identity_shape_strips_list_secrets(self):
                                                         
                                                           
        for phrasing in ("hello", "good morning", "who are you"):
            with self.subTest(phrasing=phrasing):
                names = self._names(self._filter(phrasing))
                self.assertNotIn("list_secrets", names)
                self.assertIn("save_secret", names)
                self.assertIn("retrieve_secret", names)

    def test_empty_message_keeps_full_tool_list(self):
        names = self._names(self._filter(""))
        self.assertIn("list_secrets", names)


class TestChatEndpointSourceGuards(unittest.TestCase):


    def setUp(self):
        with open("main.py", "r", encoding="utf-8") as f:
            self._src = f.read()

    def test_credential_files_override_block_present(self):
                                                               
                                                             
        self.assertIn(
            "is_credential_files_query",
            self._src,
            "credential-files override import missing from main.py",
        )
                                                                  
                                                           
        self.assertRegex(
            self._src,
            r"intent\s*=\s*[\"']search_files_for_credentials[\"']",
        )

    def test_ai_stream_uses_filtered_tools(self):
                                                                 
                                       
        import inspect, main
        try:
            body = inspect.getsource(main.ai_stream)
        except (OSError, TypeError) as e:                    
            self.fail(
                f"could not read ai_stream source via inspect: {e}"
            )
                                              
        self.assertTrue(
            body.lstrip().startswith("async def ai_stream("),
            "ai_stream signature changed",
        )
                                             
                                                         
        self.assertIn(
            "_vault_functions_for_message", body,
            "ai_stream must derive its tool list via "
            "_vault_functions_for_message",
        )
                                                                
                                                             
        self.assertRegex(
            body,
            r'(tools\s*=\s*allowed_tools'
            r'|_create_kwargs\["tools"\]\s*=\s*allowed_tools)',
            "ai_stream must pass the filtered allowed_tools list "
            "to OpenAI, not VAULT_FUNCTIONS",
        )
                                                              
        self.assertNotRegex(
            body,
            r'tools\s*=\s*VAULT_FUNCTIONS',
            "ai_stream must NEVER bind tools=VAULT_FUNCTIONS — "
            "that re-introduces the credential-search leak",
        )

    def test_route_trace_log_present(self):
                                                              
                                             
        self.assertIn(
            "route_name=search_files_for_credentials",
            self._src,
            "route-trace log missing from strict verifier path",
        )
        self.assertIn(
            "strict_verifier_used=",
            self._src,
        )
        self.assertIn(
            "evidence_bundle_present=",
            self._src,
        )

    def test_no_fabricated_indexed_phrasing_present(self):
                                                           
                                                           
        self.assertNotIn(
            "anything indexed that way",
            self._src,
        )
        self.assertNotIn(
            "no file-content search",
            self._src,
        )


if __name__ == "__main__":
    unittest.main()
