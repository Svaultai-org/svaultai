

from __future__ import annotations

import json
import re
import unittest
from unittest import mock

from vault_chat_safety_sanitizer import (
    SENTENCE_EMPTY_RESULT,
    SENTENCE_GENERIC_TOOL_FAILED,
    SENTENCE_VAULT_LOCKED,
    SENTENCE_VAULT_UNAVAILABLE,
    looks_like_raw_json,
    sanitize_tool_result,
    sanitize_user_facing_text,
)
from vault_person_document_lookup import (
    DOC_KIND_GENERIC,
    DOC_KIND_ID_CARD,
    DOC_KIND_PASSPORT,
    detect_person_document_query,
    handle_person_document_query,
)


_KEY = b"\x77" * 32


class SanitizerErrorEnvelopeTests(unittest.TestCase):
    def test_unavailable_envelope_becomes_friendly_sentence(self):
        out = sanitize_tool_result(
            "search_vault_content",
            '{"error":"unavailable"}',
        )
        self.assertEqual(out, SENTENCE_VAULT_UNAVAILABLE)
        self.assertNotIn('"error"', out)
        self.assertNotIn("{", out)

    def test_vault_locked_envelope_becomes_friendly_sentence(self):
        out = sanitize_tool_result(
            "search_vault_content",
            '{"error":"vault_locked"}',
        )
        self.assertEqual(out, SENTENCE_VAULT_LOCKED)
        self.assertNotIn("vault_locked", out)

    def test_generic_error_becomes_safe_sentence(self):
                                                              
                       
        out = sanitize_tool_result(
            "list_vault_files",
            '{"error":"some_unexpected_class"}',
        )
        self.assertEqual(out, SENTENCE_GENERIC_TOOL_FAILED)
        self.assertNotIn("some_unexpected_class", out)

    def test_empty_search_hits_become_friendly_sentence(self):
        out = sanitize_tool_result(
            "search_vault_content",
            '{"query": "x", "hits": [], "returned": 0}',
        )
        self.assertIn("didn't find anything", out)
        self.assertNotIn("hits", out)
        self.assertNotIn("[]", out)

    def test_empty_files_with_coverage_includes_coverage_line(self):
        payload = {
            "files": [],
            "returned": 0,
            "total_in_vault": 0,
            "coverage": {
                "total": 425, "analyzed": 120, "is_complete": False,
            },
        }
        out = sanitize_tool_result(
            "list_vault_files", json.dumps(payload),
        )
        self.assertIn("didn't find", out)
        self.assertIn("120", out)
        self.assertIn("425", out)

    def test_plain_prose_passes_through_unchanged(self):
        self.assertEqual(
            sanitize_tool_result(
                "any", "Here's what I found in your vault.",
            ),
            "Here's what I found in your vault.",
        )


class SanitizerJsonDetectionTests(unittest.TestCase):
    def test_looks_like_raw_json_true_for_object(self):
        self.assertTrue(
            looks_like_raw_json('{"error":"unavailable"}')
        )
        self.assertTrue(
            looks_like_raw_json('  {"a":1,"b":2}  ')
        )

    def test_looks_like_raw_json_false_for_prose(self):
        self.assertFalse(
            looks_like_raw_json("I checked your vault.")
        )
        self.assertFalse(
            looks_like_raw_json("Total {0,5} files match"),
        )
        self.assertFalse(looks_like_raw_json(""))
        self.assertFalse(looks_like_raw_json("{ broken json"))


class SanitizerUserFacingGuardTests(unittest.TestCase):
    def test_user_facing_text_catches_raw_unavailable(self):
        self.assertEqual(
            sanitize_user_facing_text('{"error":"unavailable"}'),
            SENTENCE_VAULT_UNAVAILABLE,
        )

    def test_user_facing_text_keeps_prose(self):
        self.assertEqual(
            sanitize_user_facing_text("Here's a normal answer."),
            "Here's a normal answer.",
        )

    def test_user_facing_text_handles_none(self):
        self.assertEqual(sanitize_user_facing_text(None), "")


class PersonDocumentClassifierTests(unittest.TestCase):
    def test_show_me_id_card_with_name_louis_iodato(self):
                                          
        q = detect_person_document_query(
            "show me ID card with name louis Iodato",
        )
        self.assertIsNotNone(q)
        self.assertEqual(q.doc_kind_hint, DOC_KIND_ID_CARD)
        self.assertIn("louis", q.person_name.lower())
        self.assertIn("iodato", q.person_name.lower())

    def test_find_id_document_for_x(self):
        q = detect_person_document_query(
            "find ID document for Jane Doe",
        )
        self.assertIsNotNone(q)
        self.assertEqual(q.doc_kind_hint, DOC_KIND_ID_CARD)
        self.assertEqual(q.person_name, "Jane Doe")

    def test_show_passport_for_x(self):
        q = detect_person_document_query(
            "show passport for Louis Iodato",
        )
        self.assertIsNotNone(q)
        self.assertEqual(q.doc_kind_hint, DOC_KIND_PASSPORT)
        self.assertEqual(q.person_name, "Louis Iodato")

    def test_find_documents_for_x(self):
        q = detect_person_document_query(
            "find documents for Louis Iodato",
        )
        self.assertIsNotNone(q)
        self.assertEqual(q.doc_kind_hint, DOC_KIND_GENERIC)
        self.assertEqual(q.person_name, "Louis Iodato")

    def test_do_i_have_passport_for_x(self):
        q = detect_person_document_query(
            "do I have a passport for Louis Iodato",
        )
        self.assertIsNotNone(q)
        self.assertEqual(q.doc_kind_hint, DOC_KIND_PASSPORT)
        self.assertEqual(q.person_name, "Louis Iodato")

    def test_unrelated_query_returns_none(self):
        for msg in (
            "what's in my vault",
            "create a username and password for chase",
            "hello",
            "list my files",
            "good morning",
        ):
            with self.subTest(msg=msg):
                self.assertIsNone(
                    detect_person_document_query(msg)
                )


class PersonDocumentHandlerTests(unittest.TestCase):
    def _patch_db(self, rows):
        fake_cur = mock.MagicMock()
        fake_cur.fetchall.return_value = rows
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        return mock.patch("main.get_db", return_value=fake_conn)

    def test_locked_vault_returns_locked_sentence(self):
        out = handle_person_document_query(
            vault_id="v1", key=b"short",
            person_name="Louis Iodato",
            doc_kind_hint=DOC_KIND_ID_CARD,
        )
        self.assertEqual(out, SENTENCE_VAULT_LOCKED)

    def test_found_one_returns_match_sentence(self):
        rows = [{
            "file_id":          "f1",
            "document_purpose": "id_document",
            "purpose_label":    "ID document",
            "entities_jsonb": {
                "people": ["Louis Iodato"],
                "organizations": [],
                "places": [],
            },
            "file_name":     "louis_iodato_id.pdf",
            "saved_name":    "louis_iodato_id.pdf",
            "relative_path": "/Family/",
        }]
        with self._patch_db(rows), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 5, "analyzed": 5, "pending": 0,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ):
            out = handle_person_document_query(
                vault_id="v1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
        self.assertIn("Louis Iodato", out)
        self.assertIn("louis_iodato_id.pdf", out)
        self.assertIn("ID document", out)
        self.assertNotIn("{", out)

    def test_not_found_with_partial_coverage_includes_coverage_line(self):
                                                         
                                                                 
        with self._patch_db([]), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 425, "analyzed": 120, "pending": 305,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ):
            out = handle_person_document_query(
                vault_id="v1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
        self.assertIn("Louis Iodato", out)
                                                          
                               
        self.assertIn("120", out)
        self.assertIn("425", out)
                                                           
                                                           
        self.assertTrue(
            any(needle in out.lower() for needle in (
                "continuing", "scan", "couldn't find", "incomplete",
            )),
            msg=f"Reply must be a coverage-aware safe sentence: "
                f"{out!r}",
        )
                        
        self.assertNotIn("{", out)
        self.assertNotIn("error", out.lower())

    def test_not_found_with_complete_coverage_omits_coverage_line(self):
        with self._patch_db([]), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 5, "analyzed": 5, "pending": 0,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ):
            out = handle_person_document_query(
                vault_id="v1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
        self.assertIn("couldn't find", out)
        self.assertNotIn("reviewed", out)
        self.assertNotIn("incomplete", out)

    def test_db_failure_returns_unavailable_sentence(self):
                                                                  
                                                                
        with mock.patch(
            "main.get_db", side_effect=RuntimeError("db down"),
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 5, "analyzed": 0, "pending": 5,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ):
            out = handle_person_document_query(
                vault_id="v1", key=_KEY,
                person_name="Louis Iodato",
                doc_kind_hint=DOC_KIND_ID_CARD,
            )
                                                           
                                                                
        self.assertNotIn("{", out)
        self.assertNotIn('"error"', out)
        self.assertIn("Louis Iodato", out)
                                                           
                                                           
        self.assertTrue(
            ("couldn't find" in out)
            or ("continuing" in out and "0 of 5" in out),
            msg=f"Reply must be a safe coverage-aware sentence: "
                f"{out!r}",
        )


class ChatEndpointWiringSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_ai_stream_does_not_yield_raw_tool_result(self):
                                                                        
                                                              
        self.assertNotIn(
            'yield f"\\n\\n{result}\\n\\n".encode("utf-8")',
            self._src,
        )

    def test_ai_stream_imports_sanitizer(self):
        self.assertIn(
            "from vault_chat_safety_sanitizer import (",
            self._src,
        )
        self.assertIn(
            "sanitize_user_facing_text",
            self._src,
        )

    def test_ai_stream_feeds_tool_result_back_to_model(self):
        self.assertIn(
            '"role": "tool"',
            self._src,
        )
        self.assertIn(
            "followup = await stream_client.chat.completions.create",
            self._src,
        )

    def test_chat_endpoint_invokes_person_document_lookup(self):
        self.assertIn(
            "from vault_person_document_lookup import (",
            self._src,
        )
        self.assertIn(
            "detect_person_document_query",
            self._src,
        )
        person_idx = self._src.find("detect_person_document_query")
        self.assertGreater(person_idx, -1)


class NoRawJsonInUserFacingPathTests(unittest.TestCase):
    def test_general_failure_copy_is_a_safe_sentence(self):
        from vault_chat_safety_sanitizer import (
            localized_general_response_failed,
        )

        for language in ("en", "fr", "ar", "tl"):
            with self.subTest(language=language):
                text = localized_general_response_failed(language)
                self.assertTrue(text)
                self.assertNotIn("{", text)
                self.assertNotIn("[AI Error]", text)


if __name__ == "__main__":
    unittest.main()
