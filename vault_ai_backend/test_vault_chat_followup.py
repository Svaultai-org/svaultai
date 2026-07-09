

from __future__ import annotations

import inspect
import json
import time
import unittest

import vault_chat_followup as fu
import vault_chat_memory as cm


def _fixture_credential_results() -> list[dict]:


    return [
        {
            "file_id":      "f1",
            "file_name":    "passed words 7425.docx.pdf",
            "saved_name":   "",
            "relative_path": "",
            "mime_type":    "application/pdf",
            "confidence":   "strong",
        },
        {
            "file_id":      "f2",
            "file_name":    "passedwordtex.pdf",
            "saved_name":   "",
            "relative_path": "",
            "mime_type":    "application/pdf",
            "confidence":   "strong",
        },
    ]


def _fixture_mixed_results() -> list[dict]:
    return [
        {
            "file_id":      "strong1",
            "file_name":    "harmless-name.pdf",
            "saved_name":   "",
            "relative_path": "",
            "mime_type":    "application/pdf",
            "confidence":   "strong",
        },
        {
            "file_id":      "medium1",
            "file_name":    "config_dump.txt",
            "saved_name":   "",
            "relative_path": "",
            "mime_type":    "text/plain",
            "confidence":   "medium",
        },
        {
            "file_id":      "weak1",
            "file_name":    "loginatt.html",
            "saved_name":   "",
            "relative_path": "",
            "mime_type":    "text/html",
            "confidence":   "weak",
        },
    ]


def _wrap_search(results: list[dict]) -> dict:
    return {"kind": "credential_files", "results": results}


class DetectFollowupReferenceTests(unittest.TestCase):
    def test_the_one_with_everything_matches(self):
        ref = fu.detect_followup_reference(
            "show me the one with everything in it is logins credentials"
        )
        self.assertEqual(ref, {"selector": "everything"})

    def test_the_one_matches(self):
        ref = fu.detect_followup_reference("show me the one")
        self.assertEqual(ref, {"selector": "pure"})

    def test_that_one_matches(self):
        ref = fu.detect_followup_reference("can you open that one")
        self.assertEqual(ref, {"selector": "pure"})

    def test_first_one_matches(self):
        for phrase in (
            "show me the first one",
            "open the first result",
            "the top one",
            "#1",
        ):
            with self.subTest(phrase=phrase):
                ref = fu.detect_followup_reference(phrase)
                self.assertIsNotNone(ref, f"phrase {phrase!r} must match")
                if "1" in phrase:
                    self.assertEqual(ref["selector"], "ordinal")
                    self.assertEqual(ref["n"], 1)
                else:
                    self.assertIn(ref["selector"], ("first", "ordinal"))

    def test_numeric_ordinal_matches(self):
        for phrase, expected in (
            ("show me #2", 2),
            ("open #3", 3),
            ("the 2nd one", 2),
            ("third one", 3),
            ("the second one", 2),
        ):
            with self.subTest(phrase=phrase):
                ref = fu.detect_followup_reference(phrase)
                self.assertEqual(ref["selector"], "ordinal")
                self.assertEqual(ref["n"], expected)

    def test_last_one_matches(self):
        ref = fu.detect_followup_reference("show me the last one")
        self.assertEqual(ref["selector"], "last")

    def test_strong_one_matches(self):
        ref = fu.detect_followup_reference("show me the strong one")
        self.assertEqual(ref["selector"], "strong")

    def test_strongest_matches(self):
        ref = fu.detect_followup_reference("open the strongest match")
        self.assertEqual(ref["selector"], "strong")

    def test_unrelated_message_returns_none(self):
        for phrase in (
            "what should I cook tonight",
            "how big is my vault",
            "list my files",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(fu.detect_followup_reference(phrase))

    def test_explicit_saved_logins_does_NOT_trigger_followup(self):
                                                                  
                                                               
        for phrase in (
            "show me my saved logins",
            "list my vault items",
            "open my password manager",
            "the one in my saved logins",                        
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(
                    fu.detect_followup_reference(phrase),
                    f"{phrase!r} explicitly names the saved-login "
                    "surface — resolver must not steal the turn",
                )

    def test_empty_input_returns_none(self):
        self.assertIsNone(fu.detect_followup_reference(""))
        self.assertIsNone(fu.detect_followup_reference(None))


class ResolveFollowupTests(unittest.TestCase):
    def test_the_one_with_one_strong_match_opens_it(self):
        results = [_fixture_mixed_results()[0]]
        action = fu.resolve_followup(
            "show me the one", _wrap_search(results),
        )
        self.assertEqual(action["action"], "open_one")
        self.assertEqual(action["file"]["file_id"], "strong1")

    def test_the_one_with_multiple_strong_asks_disambiguation(self):
                                         
        results = _fixture_credential_results()
        action = fu.resolve_followup(
            "show me the one with everything in it is logins credentials",
            _wrap_search(results),
        )
        self.assertEqual(action["action"], "disambiguate")
        self.assertEqual(len(action["files"]), 2)

    def test_first_one_opens_first(self):
        results = _fixture_credential_results()
        action = fu.resolve_followup(
            "show me the first one", _wrap_search(results),
        )
        self.assertEqual(action["action"], "open_one")
        self.assertEqual(action["file"]["file_id"], "f1")

    def test_second_one_opens_second(self):
        results = _fixture_credential_results()
        action = fu.resolve_followup(
            "show me #2", _wrap_search(results),
        )
        self.assertEqual(action["action"], "open_one")
        self.assertEqual(action["file"]["file_id"], "f2")

    def test_last_one_opens_last(self):
        results = _fixture_credential_results()
        action = fu.resolve_followup(
            "the last one", _wrap_search(results),
        )
        self.assertEqual(action["action"], "open_one")
        self.assertEqual(action["file"]["file_id"], "f2")

    def test_strong_one_with_one_strong_opens_it(self):
        results = _fixture_mixed_results()                              
        action = fu.resolve_followup(
            "show me the strong one", _wrap_search(results),
        )
        self.assertEqual(action["action"], "open_one")
        self.assertEqual(action["file"]["confidence"], "strong")

    def test_strong_ones_plural_with_multiple_disambiguates(self):
        results = _fixture_credential_results()            
        action = fu.resolve_followup(
            "show me the strong ones", _wrap_search(results),
        )
        self.assertEqual(action["action"], "disambiguate")
        self.assertEqual(len(action["files"]), 2)

    def test_strong_with_no_strong_results_falls_through(self):
                                                                 
                                                                 
        results = [r for r in _fixture_mixed_results()
                   if r["confidence"] != "strong"]
        action = fu.resolve_followup(
            "the strong one", _wrap_search(results),
        )
        self.assertEqual(action["action"], "none")

    def test_no_stored_results_falls_through(self):
        action = fu.resolve_followup("the one", None)
        self.assertEqual(action["action"], "none")

    def test_empty_stored_results_falls_through(self):
        action = fu.resolve_followup(
            "the one", {"kind": "credential_files", "results": []},
        )
        self.assertEqual(action["action"], "none")

    def test_explicit_saved_logins_falls_through(self):
                                                            
                        
        results = _fixture_credential_results()
        action = fu.resolve_followup(
            "show me my saved logins", _wrap_search(results),
        )
        self.assertEqual(action["action"], "none")

    def test_disambiguate_capped_at_five(self):
        many = [
            {
                "file_id":    f"f{i}",
                "file_name":  f"file{i}.pdf",
                "saved_name": "",
                "relative_path": "",
                "mime_type":  "application/pdf",
                "confidence": "strong",
            }
            for i in range(10)
        ]
        action = fu.resolve_followup(
            "show me the strong ones", _wrap_search(many),
        )
        self.assertEqual(action["action"], "disambiguate")
        self.assertEqual(len(action["files"]), 5)

    def test_ordinal_out_of_range_falls_to_disambiguation(self):
        results = _fixture_credential_results()
        action = fu.resolve_followup(
            "show me #99", _wrap_search(results),
        )
        self.assertEqual(action["action"], "disambiguate")


class FormatDisambiguationTests(unittest.TestCase):
    def test_two_strong_matches_uses_spec_headline(self):
        files = _fixture_credential_results()
        text = fu.format_followup_disambiguation(files)
        self.assertIn(
            "I found 2 strong credential-file matches. Which one do "
            "you mean?",
            text,
        )
                                    
        self.assertIn("1. passed words 7425.docx.pdf", text)
        self.assertIn("2. passedwordtex.pdf", text)

    def test_mixed_confidence_uses_generic_headline(self):
        files = _fixture_mixed_results()
        text = fu.format_followup_disambiguation(files)
        self.assertIn(
            "I found 3 matches from the previous file search.",
            text,
        )

    def test_disambiguation_carries_confidence_chip(self):
        files = _fixture_mixed_results()
        text = fu.format_followup_disambiguation(files)
        self.assertIn("[strong]", text)
        self.assertIn("[medium]", text)
        self.assertIn("[weak]", text)

    def test_disambiguation_does_not_echo_extracted_text(self):
                                                          
                                                                 
        hostile = [{
            "file_id":     "f1",
            "file_name":   "x.pdf",
            "saved_name":  "",
            "relative_path": "",
            "mime_type":   "application/pdf",
            "confidence":  "strong",
                                                                       
            "extracted_text":  "hunter2 sunshine6856 Patrick62109",
            "password":        "hunter2",
        }]
        text = fu.format_followup_disambiguation(hostile)
        for sentinel in (
            "hunter2", "sunshine6856", "Patrick62109",
            "extracted_text", "password=",
        ):
            self.assertNotIn(
                sentinel, text,
                f"disambiguation MUST NOT echo {sentinel!r}",
            )


class ChatMemorySnapshotTests(unittest.TestCase):
    def setUp(self):
                                                              
                                   
        self.vault_id = f"vault-{time.time_ns()}"

    def tearDown(self):
        cm.clear_last_file_search_results(self.vault_id)

    def test_set_then_get_roundtrip(self):
        cm.set_last_file_search_results(
            self.vault_id,
            kind="credential_files",
            results=_fixture_credential_results(),
        )
        out = cm.get_last_file_search_results(self.vault_id)
        self.assertIsNotNone(out)
        self.assertEqual(out["kind"], "credential_files")
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(out["results"][0]["file_id"], "f1")
        self.assertEqual(out["results"][0]["confidence"], "strong")

    def test_snapshot_strips_hostile_fields(self):
                                                             
                                                                 
        cm.set_last_file_search_results(
            self.vault_id,
            kind="credential_files",
            results=[{
                "file_id":     "f1",
                "file_name":   "x.pdf",
                "saved_name":  "",
                "relative_path": "",
                "mime_type":   "application/pdf",
                "confidence":  "strong",
                "extracted_text": "hunter2 SUPERSECRET",
                "password":       "hunter2",
            }],
        )
        out = cm.get_last_file_search_results(self.vault_id)
        wire = json.dumps(out)
        for sentinel in ("hunter2", "SUPERSECRET",
                         "extracted_text", '"password"'):
            self.assertNotIn(
                sentinel, wire,
                f"chat memory snapshot must NOT contain {sentinel!r}",
            )

    def test_clear_drops_the_entry(self):
        cm.set_last_file_search_results(
            self.vault_id,
            kind="credential_files",
            results=_fixture_credential_results(),
        )
        cm.clear_last_file_search_results(self.vault_id)
        self.assertIsNone(cm.get_last_file_search_results(self.vault_id))

    def test_get_returns_none_for_empty_results(self):
        cm.set_last_file_search_results(
            self.vault_id, kind="credential_files", results=[],
        )
        self.assertIsNone(cm.get_last_file_search_results(self.vault_id))

    def test_snapshot_capped_at_max_items(self):
        many = [
            {
                "file_id":    f"f{i}",
                "file_name":  f"file{i}.pdf",
                "saved_name": "",
                "relative_path": "",
                "mime_type":  "application/pdf",
                "confidence": "weak",
            }
            for i in range(1000)
        ]
        cm.set_last_file_search_results(
            self.vault_id, kind="credential_files", results=many,
        )
        out = cm.get_last_file_search_results(self.vault_id)
        self.assertLessEqual(
            len(out["results"]), cm.LAST_FILE_SEARCH_MAX_ITEMS,
        )


class ChatHandlerWiringTests(unittest.TestCase):


    def test_handler_invokes_resolver(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn("resolve_followup", src)
        self.assertIn("get_last_file_search_results", src)

    def test_resolver_runs_before_intent_dispatch(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
                                                                     
                                                               
        resolver_idx = src.find("resolve_followup(decrypted_message")
        intent_idx = src.find('intent == "list_logins"')
        self.assertGreater(resolver_idx, -1)
        self.assertGreater(intent_idx, -1)
        self.assertLess(
            resolver_idx, intent_idx,
            "follow-up resolver MUST run BEFORE the intent dispatcher "
            "so 'the one' doesn't get routed to list_logins (the "
            "exact bug this slice fixes)",
        )

    def test_handler_persists_credential_results(self):
                                                                    
                                                                   
        import main
        src = inspect.getsource(main.chat_endpoint)
                                                                        
                                                
        branch_idx = src.find('intent == "search_files_for_credentials"')
        setter_idx = src.find("set_last_file_search_results(", branch_idx)
        self.assertGreater(branch_idx, -1)
        self.assertGreater(setter_idx, -1)
                                                                  
                                                                
        self.assertLess(
            setter_idx - branch_idx, 16000,
            "set_last_file_search_results MUST be inside the "
            "search_files_for_credentials branch",
        )

    def test_handler_clears_followup_after_open_one(self):
                                                                 
                                                                
        import main
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn("clear_last_file_search_results(vault_id)", src)


class EndToEndBugReportTests(unittest.TestCase):
    def test_bug_report_resolves_to_disambiguation_not_list_logins(self):


        action = fu.resolve_followup(
            "show me the one with everything in it is logins credentials",
            _wrap_search(_fixture_credential_results()),
        )
        self.assertEqual(action["action"], "disambiguate")
        files = action["files"]
        self.assertEqual(len(files), 2)
        self.assertEqual(
            {f["file_id"] for f in files},
            {"f1", "f2"},
        )

        prompt = fu.format_followup_disambiguation(files)
                                         
        self.assertIn("1. passed words 7425.docx.pdf", prompt)
        self.assertIn("2. passedwordtex.pdf", prompt)

                                                                     
        self.assertNotIn("saved logins", prompt.lower())
        self.assertNotIn("vault items", prompt.lower())

    def test_followup_for_unrelated_message_falls_through(self):
                                                               
                                                                 
        for phrase in (
            "show me my saved Gmail login",
            "list my saved logins",
            "do I have a Twitter login saved",
        ):
            with self.subTest(phrase=phrase):
                action = fu.resolve_followup(
                    phrase,
                    _wrap_search(_fixture_credential_results()),
                )
                self.assertEqual(action["action"], "none",
                    f"resolver must NOT hijack {phrase!r}")


if __name__ == "__main__":
    unittest.main()
