

from __future__ import annotations

import inspect
import time
import unittest

from vault_result_context import (
    LastAssistantResult,
    RESULT_TYPES,
    EVIDENCE_SOURCES,
    RESULT_TYPE_CREDENTIAL_FILES,
    EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
    EVIDENCE_SOURCE_EXTRACTED_TEXT,
    set_last_assistant_result,
    get_last_assistant_result,
    clear_last_assistant_result,
    make_credential_search_result,
)


def _reset_chat_memory():
                                                                  
    from vault_chat_memory import CHAT_MEMORY
    CHAT_MEMORY._data.clear()


class StructuredShapeTests(unittest.TestCase):
    def test_has_every_field_the_spec_requires(self):
        r = LastAssistantResult(
            result_type=RESULT_TYPE_CREDENTIAL_FILES,
            query="find credential files",
            intent="search_files_for_credentials",
            file_ids_returned=("f1", "f2"),
            file_ids_excluded=("f3",),
            total_matches_known=2,
            coverage_at_time={"total": 100, "analyzed": 50, "pending": 50},
            is_partial=True,
            evidence_source=EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
            timestamp_unix=1234567890.0,
            job_id="job-abc",
        )
                                                 
        for field in (
            "result_type", "query", "intent",
            "file_ids_returned", "file_ids_excluded",
            "total_matches_known", "coverage_at_time",
            "is_partial", "evidence_source",
            "timestamp_unix", "job_id",
        ):
            self.assertTrue(
                hasattr(r, field),
                f"LastAssistantResult missing required field: {field}",
            )

    def test_is_frozen(self):
        r = LastAssistantResult(
            result_type=RESULT_TYPE_CREDENTIAL_FILES,
            query="q", intent="i",
            file_ids_returned=(), file_ids_excluded=(),
            total_matches_known=0,
            coverage_at_time={},
            is_partial=False,
            evidence_source=EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
            timestamp_unix=0.0,
        )
        with self.assertRaises(Exception):
            r.result_type = "tampered"                

    def test_result_type_is_closed_set(self):
                                                                    
                                                                 
        _reset_chat_memory()
        with self.assertRaises(ValueError):
            set_last_assistant_result(
                "v1",
                LastAssistantResult(
                    result_type="not_in_closed_set",
                    query="q", intent="i",
                    file_ids_returned=(), file_ids_excluded=(),
                    total_matches_known=0, coverage_at_time={},
                    is_partial=False,
                    evidence_source=EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
                    timestamp_unix=0.0,
                ),
            )

    def test_evidence_source_is_closed_set(self):
        _reset_chat_memory()
        with self.assertRaises(ValueError):
            set_last_assistant_result(
                "v1",
                LastAssistantResult(
                    result_type=RESULT_TYPE_CREDENTIAL_FILES,
                    query="q", intent="i",
                    file_ids_returned=(), file_ids_excluded=(),
                    total_matches_known=0, coverage_at_time={},
                    is_partial=False,
                    evidence_source="speculation",
                    timestamp_unix=0.0,
                ),
            )

    def test_closed_set_constants_are_non_empty(self):
                                                  
        self.assertGreater(len(RESULT_TYPES), 0)
        self.assertGreater(len(EVIDENCE_SOURCES), 0)


class StorageRoundtripTests(unittest.TestCase):
    def setUp(self):
        _reset_chat_memory()

    def test_set_then_get_returns_equal_object(self):
        r = LastAssistantResult(
            result_type=RESULT_TYPE_CREDENTIAL_FILES,
            query="show me credential files",
            intent="search_files_for_credentials",
            file_ids_returned=("file-a", "file-b"),
            file_ids_excluded=("file-c",),
            total_matches_known=2,
            coverage_at_time={"total": 425, "analyzed": 194, "pending": 122,
                              "unsupported": 109, "scan_complete": False},
            is_partial=True,
            evidence_source=EVIDENCE_SOURCE_EXTRACTED_TEXT,
            timestamp_unix=1700000000.0,
            job_id="job-xyz",
        )
        set_last_assistant_result("v1", r)
        loaded = get_last_assistant_result("v1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.result_type, r.result_type)
        self.assertEqual(loaded.query, r.query)
        self.assertEqual(loaded.intent, r.intent)
        self.assertEqual(loaded.file_ids_returned, r.file_ids_returned)
        self.assertEqual(loaded.file_ids_excluded, r.file_ids_excluded)
        self.assertEqual(loaded.total_matches_known, r.total_matches_known)
        self.assertEqual(loaded.coverage_at_time, r.coverage_at_time)
        self.assertEqual(loaded.is_partial, r.is_partial)
        self.assertEqual(loaded.evidence_source, r.evidence_source)
        self.assertEqual(loaded.timestamp_unix, r.timestamp_unix)
        self.assertEqual(loaded.job_id, r.job_id)

    def test_get_returns_none_when_nothing_stored(self):
        self.assertIsNone(get_last_assistant_result("v-empty"))

    def test_get_returns_none_for_empty_vault_id(self):
        self.assertIsNone(get_last_assistant_result(""))

    def test_clear_drops_the_entry(self):
        r = make_credential_search_result(
            query="q", file_ids_returned=["a"], file_ids_excluded=[],
            total_matches_known=1, coverage={}, is_partial=False,
        )
        set_last_assistant_result("v1", r)
        self.assertIsNotNone(get_last_assistant_result("v1"))
        clear_last_assistant_result("v1")
        self.assertIsNone(get_last_assistant_result("v1"))

    def test_malformed_storage_dict_returns_none_does_not_raise(self):
                                                                  
                                                         
        result = LastAssistantResult.from_storage_dict({"result_type": 12345})                
                                                                    
                                    
        bad = LastAssistantResult.from_storage_dict({
            "total_matches_known": "not-a-number",
        })
        self.assertIsNone(bad)

    def test_two_vaults_have_independent_entries(self):
        r1 = make_credential_search_result(
            query="q1", file_ids_returned=["a"], file_ids_excluded=[],
            total_matches_known=1, coverage={}, is_partial=False,
        )
        r2 = make_credential_search_result(
            query="q2", file_ids_returned=["b"], file_ids_excluded=[],
            total_matches_known=1, coverage={}, is_partial=False,
        )
        set_last_assistant_result("vA", r1)
        set_last_assistant_result("vB", r2)
        a = get_last_assistant_result("vA")
        b = get_last_assistant_result("vB")
        self.assertEqual(a.file_ids_returned, ("a",))
        self.assertEqual(b.file_ids_returned, ("b",))


class PersistenceAcrossTurnsTests(unittest.TestCase):
    def setUp(self):
        _reset_chat_memory()

    def test_context_survives_unrelated_turn_until_a_new_card_replaces_it(self):
                                            
        r = make_credential_search_result(
            query="find credentials", file_ids_returned=["f1", "f2"],
            file_ids_excluded=[], total_matches_known=2,
            coverage={"total": 100, "analyzed": 100, "scan_complete": True},
            is_partial=False,
        )
        set_last_assistant_result("v1", r)
                                                                 
                                                  
        ctx = get_last_assistant_result("v1")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.result_type, RESULT_TYPE_CREDENTIAL_FILES)
        self.assertEqual(ctx.file_ids_returned, ("f1", "f2"))


class AgeHelperTests(unittest.TestCase):
    def test_age_seconds_reports_age(self):
        r = LastAssistantResult(
            result_type=RESULT_TYPE_CREDENTIAL_FILES,
            query="q", intent="i",
            file_ids_returned=(), file_ids_excluded=(),
            total_matches_known=0, coverage_at_time={},
            is_partial=False,
            evidence_source=EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
            timestamp_unix=1000.0,
        )
        self.assertEqual(r.age_seconds(now_unix=1010.0), 10.0)

    def test_age_seconds_clamps_negative_to_zero(self):
        r = LastAssistantResult(
            result_type=RESULT_TYPE_CREDENTIAL_FILES,
            query="q", intent="i",
            file_ids_returned=(), file_ids_excluded=(),
            total_matches_known=0, coverage_at_time={},
            is_partial=False,
            evidence_source=EVIDENCE_SOURCE_FILENAME_AND_CONTENT,
            timestamp_unix=2000.0,
        )
                                                               
        self.assertEqual(r.age_seconds(now_unix=1000.0), 0.0)


class NeverStoresDecryptedContentTests(unittest.TestCase):
    def test_module_source_has_no_decrypt_or_extracted_text_select(self):
                                                                 
                                                         
        import vault_result_context as vrc
        src = inspect.getsource(vrc)
        self.assertNotIn("decrypt_message", src)
        self.assertNotIn("decrypt_bytes", src)
        self.assertNotIn("SELECT extracted_text", src)

    def test_storage_dict_contains_no_known_credential_sentinels(self):
        r = make_credential_search_result(
            query="anything", file_ids_returned=["f1"],
            file_ids_excluded=[], total_matches_known=1,
            coverage={}, is_partial=False,
        )
        flat = repr(r.to_storage_dict())
        for sentinel in (
            "password=", "hunter2", "BEGIN PRIVATE KEY",
            "api_key=", "secret=",
        ):
            self.assertNotIn(sentinel, flat)


class ConvenienceConstructorTests(unittest.TestCase):
    def test_make_credential_search_result_uses_canonical_constants(self):
        r = make_credential_search_result(
            query="q", file_ids_returned=["a"], file_ids_excluded=[],
            total_matches_known=1, coverage={"total": 1, "analyzed": 1},
            is_partial=False,
        )
        self.assertEqual(r.result_type, RESULT_TYPE_CREDENTIAL_FILES)
        self.assertEqual(r.intent, "search_files_for_credentials")
        self.assertIn(r.evidence_source, EVIDENCE_SOURCES)


if __name__ == "__main__":
    unittest.main()
