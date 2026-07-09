

from __future__ import annotations

import inspect
import json
import time
import unittest

import vault_chat_memory as cm
import vault_chat_followup as fu


def _strong_credential_results() -> list[dict]:
    return [
        {
            "file_id":      "f1",
            "file_name":    "passed words 7425.docx.pdf",
            "saved_name":   "",
            "relative_path": "",
            "mime_type":    "application/pdf",
            "asset_type":   "file",
            "confidence":   "strong",
            "reasons": [
                "content contains repeated service/email/password-like "
                "credential records",
            ],
        },
        {
            "file_id":      "f2",
            "file_name":    "passedwordtex.pdf",
            "saved_name":   "",
            "relative_path": "",
            "mime_type":    "application/pdf",
            "asset_type":   "file",
            "confidence":   "strong",
            "reasons": [
                "content contains repeated service/email/password-like "
                "credential records",
            ],
        },
    ]


class EnvelopeWireShapeTests(unittest.TestCase):
    def test_basic_shape(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=_strong_credential_results(),
            title="Which strong credential-file match do you mean?",
            message="I found 2 strong credential-file matches.",
            context_kind="credential_files",
        ))
        self.assertEqual(env["type"], "file_disambiguation")
        self.assertEqual(
            env["title"],
            "Which strong credential-file match do you mean?",
        )
        self.assertEqual(env["context_kind"], "credential_files")
        self.assertEqual(env["count"], 2)
        self.assertEqual(len(env["files"]), 2)

    def test_files_carry_metadata_fields(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=_strong_credential_results(),
            title="x",
            message="x",
            context_kind="credential_files",
        ))
        row = env["files"][0]
        self.assertEqual(row["file_id"], "f1")
        self.assertEqual(row["file_name"], "passed words 7425.docx.pdf")
        self.assertEqual(row["mime_type"], "application/pdf")
        self.assertEqual(row["asset_type"], "file")
        self.assertEqual(row["confidence"], "strong")
        self.assertEqual(len(row["reasons"]), 1)

    def test_message_field_carries_text_fallback(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=_strong_credential_results(),
            title="x",
            message="I found 2 strong credential-file matches.\n"
                    "1. passed words 7425.docx.pdf [strong]\n"
                    "2. passedwordtex.pdf [strong]",
            context_kind="credential_files",
        ))
                                                              
        self.assertIn("1. passed words 7425.docx.pdf", env["message"])
        self.assertIn("2. passedwordtex.pdf", env["message"])

    def test_title_default_when_blank(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=_strong_credential_results(),
            title="",
            message="",
            context_kind="credential_files",
        ))
        self.assertEqual(env["title"], "Which file do you mean?")


class EnvelopeSafetyTests(unittest.TestCase):
    def test_envelope_strips_hostile_fields(self):
        import main
        hostile_rows = [{
            "file_id":      "f1",
            "file_name":    "x.pdf",
            "saved_name":   "",
            "relative_path": "",
            "mime_type":    "application/pdf",
            "asset_type":   "file",
            "confidence":   "strong",
            "reasons":      ["content contains repeated records"],
                                                   
            "extracted_text":   "AOL\nhunter2\nSUPERSECRET-XYZ-123",
            "password":         "hunter2",
            "encrypted_file_data": "ciphertext-blob",
            "value":            "raw-token-99",
        }]
        env = json.loads(main._build_file_disambiguation_envelope(
            files=hostile_rows,
            title="x", message="x", context_kind="credential_files",
        ))
        wire = json.dumps(env)
        for sentinel in (
            "hunter2", "SUPERSECRET-XYZ-123", "raw-token-99",
            "ciphertext-blob",
            "extracted_text", '"password"',
            "encrypted_file_data",
        ):
            self.assertNotIn(
                sentinel, wire,
                f"envelope MUST NOT contain {sentinel!r}",
            )

    def test_envelope_drops_non_string_reasons(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=[{
                "file_id":   "f1",
                "file_name": "x.pdf",
                "mime_type": "application/pdf",
                "confidence": "strong",
                                                        
                "reasons": [
                    "legit reason",
                    {"password": "hunter2"},                 
                    ["nested", "list"],                       
                    "another legit reason",
                    "",                                                 
                    None,
                ],
            }],
            title="x", message="x", context_kind="credential_files",
        ))
        row = env["files"][0]
        self.assertEqual(
            row["reasons"],
            ["legit reason", "another legit reason"],
        )
        wire = json.dumps(env)
        self.assertNotIn("hunter2", wire)

    def test_non_dict_rows_are_dropped(self):
        import main
        env = json.loads(main._build_file_disambiguation_envelope(
            files=[
                {"file_id": "f1", "file_name": "x.pdf",
                 "confidence": "strong"},
                "not a dict",
                None,
                42,
            ],
            title="x", message="x", context_kind="credential_files",
        ))
        self.assertEqual(env["count"], 1)
        self.assertEqual(env["files"][0]["file_id"], "f1")


class ChatHandlerEnvelopeWiringTests(unittest.TestCase):
    def test_chat_handler_ships_envelope_on_disambiguate(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        self.assertIn("_build_file_disambiguation_envelope", src,
            "the disambiguate branch must ship the structured "
            "envelope (not plain text) so the frontend can render "
            "tappable choices")
                                                            
                                                               
        self.assertIn("format_followup_disambiguation", src)

    def test_envelope_wiring_comes_before_intent_dispatch(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        env_idx = src.find("_build_file_disambiguation_envelope")
        intent_idx = src.find('intent == "list_logins"')
        self.assertGreater(env_idx, -1)
        self.assertGreater(intent_idx, -1)
        self.assertLess(
            env_idx, intent_idx,
            "disambiguation envelope MUST ship before the intent "
            "dispatcher so 'the one' doesn't fall into list_logins",
        )


class OpenOneStillVaultFileTests(unittest.TestCase):
    def test_open_one_action_uses_structured_asset_reply(self):
                                                        
                                                            
        import main
        src = inspect.getsource(main.chat_endpoint)
        open_one_idx = src.find('followup.get("action") == "open_one"')
                                                                  
                                                       
        builder_idx = src.find(
            "_build_structured_asset_reply", open_one_idx,
        )
        disambig_idx = src.find(
            '_build_file_disambiguation_envelope', open_one_idx,
        )
        self.assertGreater(open_one_idx, -1)
        self.assertGreater(builder_idx, -1)
                                                                   
                                                          
        self.assertLess(builder_idx, disambig_idx)


class ExplicitSavedLoginsBypassTests(unittest.TestCase):
    def test_resolver_returns_none_for_saved_logins_phrase(self):
        results = _strong_credential_results()
        action = fu.resolve_followup(
            "show me my saved logins",
            {"kind": "credential_files", "results": results},
        )
        self.assertEqual(action["action"], "none",
            "explicit saved-login phrasing must bypass the resolver "
            "so the normal intent classifier runs")


class SnapshotCarriesReasonsTests(unittest.TestCase):
    def setUp(self):
        self.vault_id = f"vault-{time.time_ns()}"

    def tearDown(self):
        cm.clear_last_file_search_results(self.vault_id)

    def test_snapshot_carries_reasons(self):
        cm.set_last_file_search_results(
            self.vault_id,
            kind="credential_files",
            results=_strong_credential_results(),
        )
        out = cm.get_last_file_search_results(self.vault_id)
        self.assertIsNotNone(out)
        first = out["results"][0]
        self.assertIn("reasons", first)
        self.assertEqual(
            first["reasons"],
            [
                "content contains repeated service/email/password-like "
                "credential records",
            ],
        )

    def test_snapshot_strips_hostile_reasons(self):
        cm.set_last_file_search_results(
            self.vault_id,
            kind="credential_files",
            results=[{
                "file_id":   "f1",
                "file_name": "x.pdf",
                "saved_name": "",
                "relative_path": "",
                "mime_type": "application/pdf",
                "confidence": "strong",
                "reasons": [
                    "legit reason",
                    {"password": "hunter2"},
                    "another legit reason",
                ],
            }],
        )
        out = cm.get_last_file_search_results(self.vault_id)
        wire = json.dumps(out)
        self.assertNotIn("hunter2", wire)
                                     
        self.assertEqual(
            out["results"][0]["reasons"],
            ["legit reason", "another legit reason"],
        )


class EncryptedReplyDefinitionOrderTests(unittest.TestCase):
    def _chat_endpoint_source(self) -> str:
        import main
        return inspect.getsource(main.chat_endpoint)

    def test_encrypted_reply_defined_before_followup_resolver(self):
        src = self._chat_endpoint_source()
        def_idx = src.find("def encrypted_reply")
        open_one_branch_idx = src.find(
            'followup.get("action") == "open_one"',
        )
        disambig_branch_idx = src.find(
            'followup.get("action") == "disambiguate"',
        )
        self.assertGreater(
            def_idx, -1,
            "chat_endpoint must define encrypted_reply locally",
        )
        self.assertGreater(open_one_branch_idx, -1)
        self.assertGreater(disambig_branch_idx, -1)
        self.assertLess(
            def_idx, open_one_branch_idx,
            "encrypted_reply must be defined BEFORE the open_one "
            "branch — otherwise calling it raises UnboundLocalError.",
        )
        self.assertLess(
            def_idx, disambig_branch_idx,
            "encrypted_reply must be defined BEFORE the disambiguate "
            "branch — this was the exact crash site reported in the "
            "field for the follow-up 'the one with everything'.",
        )

    def test_encrypted_reply_defined_before_intent_dispatch(self):
        src = self._chat_endpoint_source()
        def_idx = src.find("def encrypted_reply")
        intent_idx = src.find('intent == "list_logins"')
        self.assertGreater(def_idx, -1)
        self.assertGreater(intent_idx, -1)
        self.assertLess(
            def_idx, intent_idx,
            "encrypted_reply must also be defined before the intent "
            "dispatcher — the dispatcher and every saved-logins / "
            "search / billing branch downstream all call it.",
        )

    def test_encrypted_reply_defined_exactly_once_in_chat_endpoint(self):
                                                                
                                                                  
        src = self._chat_endpoint_source()
        self.assertEqual(
            src.count("def encrypted_reply"), 1,
            "chat_endpoint must define encrypted_reply exactly once. "
            "Two definitions caused the original UnboundLocalError "
            "regression — keep it singular.",
        )

    def test_encrypted_reply_defined_after_key_is_bound(self):
                                                                       
                                                                       
        src = self._chat_endpoint_source()
        key_idx = src.find("key = get_verified_vault_key")
        def_idx = src.find("def encrypted_reply")
        self.assertGreater(key_idx, -1)
        self.assertGreater(def_idx, -1)
        self.assertLess(
            key_idx, def_idx,
            "encrypted_reply closes over ``key`` — its definition "
            "must come AFTER the PIN-verify step that binds ``key``.",
        )


class FollowupBranchEnvelopeRoutingTests(unittest.TestCase):


    def test_followup_open_one_branch_calls_encrypted_reply(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        open_one_idx = src.find(
            'followup.get("action") == "open_one"',
        )
        disambig_idx = src.find(
            'followup.get("action") == "disambiguate"',
        )
        self.assertGreater(open_one_idx, -1)
        self.assertGreater(disambig_idx, -1)
                                                                 
                                                                  
        branch_body = src[open_one_idx:disambig_idx]
        self.assertIn(
            "return encrypted_reply", branch_body,
            "open_one branch must return via encrypted_reply — "
            "this is the path that ships the vault_file envelope.",
        )
        self.assertIn(
            "_build_structured_asset_reply", branch_body,
            "open_one branch must hand the asset to "
            "_build_structured_asset_reply (the vault_file envelope "
            "builder), not the disambiguation builder.",
        )

    def test_followup_disambiguate_branch_calls_encrypted_reply(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        disambig_idx = src.find(
            'followup.get("action") == "disambiguate"',
        )
                                                                   
                                                                    
        next_phase_idx = src.find("lower_msg = decrypted_message", disambig_idx)
        self.assertGreater(disambig_idx, -1)
        self.assertGreater(next_phase_idx, disambig_idx)
        branch_body = src[disambig_idx:next_phase_idx]
        self.assertIn(
            "_build_file_disambiguation_envelope", branch_body,
            "disambiguate branch must build the structured envelope.",
        )
        self.assertIn(
            "return encrypted_reply", branch_body,
            "disambiguate branch must return via encrypted_reply.",
        )

    def test_followup_resolver_does_not_route_to_list_logins(self):


        import main
        src = inspect.getsource(main.chat_endpoint)
        resolver_idx = src.find("resolve_followup(decrypted_message")
        list_logins_idx = src.find('intent == "list_logins"')
        self.assertGreater(resolver_idx, -1)
        self.assertGreater(list_logins_idx, -1)
        self.assertLess(
            resolver_idx, list_logins_idx,
            "resolver MUST run before the list_logins intent branch — "
            "otherwise 'the one with credentials' falls through and "
            "the user gets saved logins instead of the file picker.",
        )


class FollowupResolverBugReportPhraseTests(unittest.TestCase):


    def test_resolver_returns_actionable_decision_for_bug_phrase(self):
        results = _strong_credential_results()
        last_search = {"kind": "credential_files", "results": results}
        action = fu.resolve_followup(
            "give me the one with in it only credentials logins",
            last_search,
        )
                                                              
                                                                    
        self.assertIn(
            action.get("action"),
            ("disambiguate", "open_one"),
            "bug-report phrase must resolve to a file-surface action, "
            "never fall through to action='none' (which routes to "
            "list_logins / general chat).",
        )

    def test_resolver_with_single_strong_match_returns_open_one(self):
        single = [_strong_credential_results()[0]]
        action = fu.resolve_followup(
            "give me the one",
            {"kind": "credential_files", "results": single},
        )
                                                                  
                                                                     
        self.assertEqual(action.get("action"), "open_one")

    def test_resolver_with_two_strong_matches_returns_disambiguate(self):
        action = fu.resolve_followup(
            "give me the one",
            {
                "kind":    "credential_files",
                "results": _strong_credential_results(),
            },
        )
        self.assertEqual(action.get("action"), "disambiguate")
        self.assertEqual(len(action["files"]), 2)


if __name__ == "__main__":
    unittest.main()
