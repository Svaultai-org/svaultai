

from __future__ import annotations

import unittest
from unittest import mock


class ImperativeClassifierTests(unittest.TestCase):
    def setUp(self):
        from vault_brain_intent import (
            classify_brain_intent,
            NOT_VAULT_CONTENT,
        )
        self._classify = classify_brain_intent
        self._NOT_VAULT = NOT_VAULT_CONTENT

    def _is_not_vault(self, msg):
        return self._classify(msg).intent == self._NOT_VAULT

    def test_create_username_and_password_for_chase(self):
                                                         
        self.assertTrue(self._is_not_vault(
            "create username and password for my chase bank",
        ))

    def test_create_login_for_x(self):
        self.assertTrue(self._is_not_vault(
            "create me a login for my BNB bank",
        ))

    def test_generate_password_for_x(self):
        self.assertTrue(self._is_not_vault(
            "generate a strong password for Gmail",
        ))

    def test_make_a_username_for_x(self):
        self.assertTrue(self._is_not_vault(
            "make me a username for my Wells Fargo account",
        ))

    def test_give_me_a_password(self):
        self.assertTrue(self._is_not_vault(
            "give me a 24-char password",
        ))

    def test_i_want_you_to_create(self):
        self.assertTrue(self._is_not_vault(
            "i want you to create me username, email, "
            "and password for X",
        ))

    def test_please_generate(self):
        self.assertTrue(self._is_not_vault(
            "please generate a password for me",
        ))

    def test_can_you_create_login(self):
        self.assertTrue(self._is_not_vault(
            "can you create a login for chase?",
        ))

    def test_produce_a_password(self):
        self.assertTrue(self._is_not_vault(
            "produce a fresh password for my account",
        ))

    def test_existing_mutation_verbs_still_route_to_not_vault(self):
                                                                    
                            
        for msg in (
            "save my new gmail password",
            "store this credit card",
            "add a login for Netflix",
            "update my chase password",
            "delete my old amex login",
            "rename my contract.pdf",
        ):
            with self.subTest(msg=msg):
                self.assertTrue(self._is_not_vault(msg))

    def test_actual_search_question_still_routes_to_brain(self):
                                                              
                                   
        for msg in (
            "find anything about my anniversary",
            "what files mention Wells Fargo",
            "any notes about the kids' school?",
        ):
            with self.subTest(msg=msg):
                                                                 
                                                                 
                result = self._classify(msg)
                self.assertNotEqual(
                    result.reason, "imperative_action_prefix",
                    f"{msg!r} should not be classified as an "
                    "imperative action",
                )


class BrainComposerMarkdownTests(unittest.TestCase):
    def test_system_prompt_forbids_markdown_bold(self):
        from vault_memory_answer_composer import SYSTEM_PROMPT
        lower = SYSTEM_PROMPT.lower()
        self.assertIn("no markdown bold", lower)

    def test_system_prompt_forbids_numbered_lists(self):
        from vault_memory_answer_composer import SYSTEM_PROMPT
        self.assertIn("NO numbered lists", SYSTEM_PROMPT)

    def test_system_prompt_forbids_file_id_quoting(self):
        from vault_memory_answer_composer import SYSTEM_PROMPT
        self.assertIn("file_id", SYSTEM_PROMPT)
        self.assertIn("useless to them", SYSTEM_PROMPT)

    def test_strip_helper_removes_bold(self):
        from vault_memory_answer_composer import (
            strip_markdown_for_chat_bubble,
        )
        out = strip_markdown_for_chat_bubble(
            "I found **passedwpordtex.pdf** in the vault.",
        )
        self.assertNotIn("**", out)
        self.assertIn("passedwpordtex.pdf", out)

    def test_strip_helper_removes_italics(self):
        from vault_memory_answer_composer import (
            strip_markdown_for_chat_bubble,
        )
        out = strip_markdown_for_chat_bubble(
            "I see *contract.pdf* in your vault.",
        )
        self.assertNotIn("*", out)

    def test_strip_helper_removes_headers(self):
        from vault_memory_answer_composer import (
            strip_markdown_for_chat_bubble,
        )
        out = strip_markdown_for_chat_bubble(
            "# Files found\n\nHere are the files",
        )
        self.assertNotIn("# ", out)
        self.assertIn("Files found", out)

    def test_strip_helper_removes_numbered_lists(self):
        from vault_memory_answer_composer import (
            strip_markdown_for_chat_bubble,
        )
        out = strip_markdown_for_chat_bubble(
            "1. file_a.pdf\n2. file_b.pdf\n3. file_c.pdf",
        )
                                                           
        self.assertNotIn("1. ", out)
        self.assertNotIn("2. ", out)
        self.assertIn("file_a.pdf", out)

    def test_strip_helper_removes_file_id_parens(self):
        from vault_memory_answer_composer import (
            strip_markdown_for_chat_bubble,
        )
        out = strip_markdown_for_chat_bubble(
            "I found contract.pdf (File ID: "
            "1b81d7b7-027e-4d4d-95ff-509ee765607a).",
        )
        self.assertNotIn("File ID", out)
        self.assertIn("contract.pdf", out)

    def test_strip_helper_handles_combined_markdown(self):
                                                 
        from vault_memory_answer_composer import (
            strip_markdown_for_chat_bubble,
        )
        raw = (
            "The evidence retrieved includes 5 matching files:\n\n"
            "1. **Passedwpordtex.pdf** "
            "(File ID: 1b81d7b7-027e-4d4d-95ff-509ee765607a)\n"
            "2. **Passedwpordtex.pdf** "
            "(File ID: 22e45a00-788f-4f58-bb2a-d1b923755e14)\n"
            "3. **login.js** "
            "(File ID: 42a31495-1f17-49e2-91eb-83937e46bbdb)\n"
        )
        out = strip_markdown_for_chat_bubble(raw)
        self.assertNotIn("**", out)
        self.assertNotIn("File ID", out)
        self.assertNotIn("1. ", out)
                          
        self.assertIn("Passedwpordtex.pdf", out)
        self.assertIn("login.js", out)

    def test_strip_helper_empty_input(self):
        from vault_memory_answer_composer import (
            strip_markdown_for_chat_bubble,
        )
        self.assertEqual(strip_markdown_for_chat_bubble(""), "")
        self.assertEqual(strip_markdown_for_chat_bubble(None), "")


class EvidenceRowDedupTests(unittest.TestCase):


    def _bundle_with_chunks(self, chunks):
        import vault_brain_answerer as v
                                                            
                                         
        bundle = mock.MagicMock()
        bundle.query = "test"
        bundle.chunks = chunks
        return v._build_evidence_rows(
            bundle,
            file_names={
                ch.file_id: f"file-{ch.file_id[:3]}.txt"
                for ch in chunks
            },
            max_rows=10,
            snippet_chars=120,
        )

    def _chunk(self, file_id, score=0.5, text="some snippet text",
               chunk_index=0, extraction_source="file_text"):
        m = mock.MagicMock()
        m.file_id = file_id
        m.score = score
        m.text = text
        m.chunk_index = chunk_index
        m.extraction_source = extraction_source
        return m

    def test_multiple_chunks_same_file_collapse_to_one_row(self):
        with mock.patch(
            "vault_brain_answerer._lookup_file_content_hashes",
            return_value={},
        ):
            rows = self._bundle_with_chunks([
                self._chunk("file-A", score=0.9, chunk_index=0),
                self._chunk("file-A", score=0.6, chunk_index=1),
                self._chunk("file-A", score=0.8, chunk_index=2),
            ])
        self.assertEqual(len(rows), 1)
                                     
        self.assertEqual(rows[0].score, 0.9)
        self.assertEqual(rows[0].chunk_index, 0)

    def test_same_sha_different_file_ids_collapse_to_one_row(self):
                                                            
                                                                
        with mock.patch(
            "vault_brain_answerer._lookup_file_content_hashes",
            return_value={
                "file-A": "a" * 64,
                "file-B": "a" * 64,
                "file-C": "b" * 64,
            },
        ):
            rows = self._bundle_with_chunks([
                self._chunk("file-A", score=0.9),
                self._chunk("file-B", score=0.7),
                self._chunk("file-C", score=0.5),
            ])
                                                         
                                      
        self.assertEqual(len(rows), 2)

    def test_missing_sha_does_not_collapse(self):
                                                           
                                  
        with mock.patch(
            "vault_brain_answerer._lookup_file_content_hashes",
            return_value={
                "file-A": "",
                "file-B": "",
            },
        ):
            rows = self._bundle_with_chunks([
                self._chunk("file-A", score=0.9),
                self._chunk("file-B", score=0.7),
            ])
        self.assertEqual(len(rows), 2)

    def test_max_rows_cap_enforced(self):
        with mock.patch(
            "vault_brain_answerer._lookup_file_content_hashes",
            return_value={},
        ):
            chunks = [
                self._chunk(f"file-{i}", score=0.9 - 0.01 * i)
                for i in range(20)
            ]
            import vault_brain_answerer as v
            bundle = mock.MagicMock()
            bundle.query = "test"
            bundle.chunks = chunks
            rows = v._build_evidence_rows(
                bundle,
                file_names={
                    ch.file_id: f"file-{ch.file_id[:8]}.txt"
                    for ch in chunks
                },
                max_rows=3,
                snippet_chars=120,
            )
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
