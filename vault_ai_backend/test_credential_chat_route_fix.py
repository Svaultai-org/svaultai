

from __future__ import annotations

import asyncio
import inspect
import re
import unittest


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class CredentialBranchDoesNotCallDeepAnswerGuard(unittest.TestCase):


    def _credential_block_source(self) -> str:
        path = "main.py"
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except FileNotFoundError:
            import os
            path = os.path.join(
                os.path.dirname(__file__), "main.py",
            )
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
                                                                    
                                                      
        m = re.search(
            r'if intent == "search_files_for_credentials":'
            r'(?P<block>.*?)'
            r'(?=\n        if intent == "|\n        elif intent == "|\Z)',
            src, re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            "Could not locate the 'search_files_for_credentials' "
            "intent branch in main.py — has it been renamed?",
        )
        return m.group("block")

    def test_credential_branch_does_not_call_deep_answer_envelope(
        self,
    ):
        block = self._credential_block_source()
        self.assertNotIn(
            "_maybe_build_deep_answer_envelope", block,
            "The credential branch must not call "
            "_maybe_build_deep_answer_envelope — that helper emits "
            "the 'Scanning your vault... N of M files read so far' "
            "bubble the user spec forbids in normal chat mode.",
        )

    def test_credential_branch_still_stores_last_assistant_result(
        self,
    ):


        block = self._credential_block_source()
        self.assertIn(
            "set_last_assistant_result", block,
            "The credential branch must store the "
            "LastAssistantResult after answering — otherwise a "
            "follow-up 'are these the only files?' falls through "
            "to the legacy LLM with 'I can't check content...'.",
        )
        self.assertIn(
            "make_credential_search_result", block,
            "The credential branch must build the "
            "credential_search shape via make_credential_search_result "
            "so the planner branches correctly.",
        )

    def test_credential_branch_uses_strict_verifier_only(self):


        block = self._credential_block_source()
        self.assertIn(
            "verified_credential_files_report", block,
            "Credential branch must use the strict verifier; the "
            "loose ranker MUST NOT be the user-facing surface.",
        )


class CredentialReplyFormatterCopyGuard(unittest.TestCase):


    def test_reply_does_not_emit_legacy_scan_wording(self):
        from vault_inventory import format_credential_files_reply
                                         
        reply = format_credential_files_reply(
            matches=[
                {"file_id": "f1", "file_name": "logins.txt",
                 "saved_name": None, "relative_path": "/",
                 "mime_type": "text/plain", "confidence": "strong"},
            ],
            scanned_count=425, not_scanned_count=0, is_partial=False,
        )
        self.assertNotRegex(
            reply, r"\d+ of \d+ files read so far",
            "Strict-verifier reply leaked the deep-answer progress "
            "wording.",
        )
        self.assertNotIn(
            "Scanning your vault", reply,
            "Strict-verifier reply leaked the deep-answer card lead.",
        )

    def test_partial_reply_states_honest_coverage(self):


        from vault_inventory import format_credential_files_reply
        reply = format_credential_files_reply(
            matches=[
                {"file_id": "f1", "file_name": "logins.txt",
                 "saved_name": None, "relative_path": "/",
                 "mime_type": "text/plain", "confidence": "strong"},
            ],
            scanned_count=194, not_scanned_count=231, is_partial=True,
        )
        self.assertIn("I checked 194 of 425 files", reply)
        self.assertIn("231", reply)
        self.assertIn("extraction/OCR", reply)
        self.assertIn("These results are incomplete", reply)

    def test_complete_reply_states_count_checked(self):
        from vault_inventory import format_credential_files_reply
        reply = format_credential_files_reply(
            matches=[
                {"file_id": "f1", "file_name": "logins.txt",
                 "saved_name": None, "relative_path": "/",
                 "mime_type": "text/plain", "confidence": "strong"},
                {"file_id": "f2", "file_name": "creds.csv",
                 "saved_name": None, "relative_path": "/",
                 "mime_type": "text/csv", "confidence": "strong"},
            ],
            scanned_count=425, not_scanned_count=0, is_partial=False,
        )
        self.assertIn(
            "I checked 425 files and found 2 files",
            reply,
            "Complete reply must state the exact count + match count.",
        )


class FollowupClassifierRecognisesUserScreenshotPhrasings(
    unittest.TestCase,
):


    def test_user_screenshot_phrasing_matches_coverage_intent(self):


        from vault_followup_classifier import (
            _COVERAGE_SCOPE_TOKENS, _COVERAGE_RESULT_TOKENS,
        )
                                                 
        msg = ("are these both the only files with list of "
               "credentials in it").lower()
        scope_hits = sum(
            1 for t in _COVERAGE_SCOPE_TOKENS if t in msg
        )
        result_hits = sum(
            1 for t in _COVERAGE_RESULT_TOKENS if t in msg
        )
        self.assertGreaterEqual(
            scope_hits, 1,
            "User's 'are these both the only files…' phrasing must "
            "contain ≥1 coverage-scope token (only/both/all/etc.).",
        )
        self.assertGreaterEqual(
            result_hits, 1,
            "User's 'are these both the only files…' phrasing must "
            "contain ≥1 result token (file/files/credentials/etc.).",
        )

    def test_anchor_set_carries_screenshot_phrasing_or_close_paraphrase(
        self,
    ):


        from vault_followup_classifier import (
            _ANCHORS, INTENT_COVERAGE_COMPLETE_CHECK,
        )
        anchors = _ANCHORS[INTENT_COVERAGE_COMPLETE_CHECK]
                                                                    
        good = [
            a for a in anchors
            if "only" in a and (
                "file" in a or "matches" in a or "results" in a
            )
        ]
        self.assertGreaterEqual(
            len(good), 1,
            "Coverage-complete-check anchors must include at least "
            "one 'only'+file/matches/results paraphrase.",
        )


class CredentialResultRoundTripsThroughStorage(unittest.TestCase):


    def test_round_trip_preserves_planner_fields(self):
        from vault_chat_memory import CHAT_MEMORY, memory_key
        from vault_result_context import (
            make_credential_search_result,
            set_last_assistant_result,
            get_last_assistant_result,
            RESULT_TYPE_CREDENTIAL_FILES,
        )
        vault_id = "v-round-trip-1"
        CHAT_MEMORY.pop(memory_key(vault_id), None)
        result = make_credential_search_result(
            query="is their any files with credentials",
            file_ids_returned=["f1", "f2"],
            file_ids_excluded=[],
            total_matches_known=2,
            coverage={"total": 425, "scanned": 194,
                      "pending": 231, "processing": 0},
            is_partial=True,
        )
        set_last_assistant_result(vault_id, result)
        loaded = get_last_assistant_result(vault_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.result_type, RESULT_TYPE_CREDENTIAL_FILES)
        self.assertEqual(loaded.file_ids_returned, ("f1", "f2"))
        self.assertEqual(loaded.total_matches_known, 2)
        self.assertTrue(loaded.is_partial)
                                                          
        self.assertEqual(loaded.coverage_at_time.get("total"), 425)
        self.assertEqual(loaded.coverage_at_time.get("scanned"), 194)


class SafeTraceLogShapeGuard(unittest.TestCase):


    def test_chat_trace_lines_do_not_emit_raw_message_field(self):
        path = "main.py"
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except FileNotFoundError:
            import os
            path = os.path.join(
                os.path.dirname(__file__), "main.py",
            )
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
                                                                    
                                                                  
        blocks = re.findall(
            r'logger\.info\(\s*"\[CHAT-TRACE\].*?\)\s*$',
            src, re.DOTALL | re.MULTILINE,
        )
        self.assertGreater(
            len(blocks), 0,
            "Expected at least one logger.info '[CHAT-TRACE]' "
            "block in main.py.",
        )
        for block in blocks:
                                                                
                                                                 
            self.assertNotRegex(
                block, r'decrypted_message(?!\s*or\s*"")[^,)]*[,)]',
            )
                                                                
                                        
            self.assertNotRegex(
                block,
                r'%s[^)]*,\s*decrypted_message\s*(?:,|\))',
                "[CHAT-TRACE] block is passing decrypted_message as "
                "a %s arg — must only emit length / closed-set fields.",
            )
                                             
            self.assertNotRegex(
                block,
                r'%s[^)]*,\s*req\.encrypted_message',
            )


class FlutterUnlockBannerDoesNotInterpolateVaultName(unittest.TestCase):


    def _read_main_dart(self) -> str:
        import os
        here = os.path.dirname(__file__)
        candidates = [
            os.path.join(
                here, "..", "vault_ai_frontend", "lib", "main.dart",
            ),
            os.path.join(
                here, "vault_ai_frontend", "lib", "main.dart",
            ),
            r"c:\Users\user\Desktop\Vaultai\vault_ai_frontend\lib\main.dart",
        ]
        for p in candidates:
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
        self.skipTest("main.dart not reachable from this test runner.")

    def test_unlock_banner_does_not_interpolate_vault_name(self):
        src = self._read_main_dart()
                                                             
        self.assertNotIn(
            'Your vault "$name" is unlocked.', src,
            'main.dart still emits the vault-name-leaking unlock '
            'banner.',
        )
                                                  
                                                             
        self.assertIn(
            'Your vault is unlocked 🔓', src,
            'main.dart should emit the neutral, friendly unlock '
            'banner with the open-lock emoji.',
        )


if __name__ == "__main__":
    unittest.main()
