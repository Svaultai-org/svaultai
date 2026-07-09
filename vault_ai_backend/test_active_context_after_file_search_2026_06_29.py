

from __future__ import annotations

import json
import time
import unittest
from typing import Optional
from unittest.mock import patch

import vault_active_context as vac
import vault_chat_context_gate as vccg
import vault_credential_draft as vcd
import vault_chat_save_guard as vsg


def _reset() -> None:
    vac._reset_store_for_test()
    vcd._reset_store_for_test()


class TestActiveContextStore(unittest.TestCase):
    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_set_and_get(self):
        vac.set_active_context(
            "vault-A", vac.CONTEXT_FILE_SEARCH_RESULTS,
        )
        self.assertEqual(
            vac.get_active_context("vault-A"),
            vac.CONTEXT_FILE_SEARCH_RESULTS,
        )

    def test_unknown_label_rejected(self):
        vac.set_active_context("vault-A", "not_a_real_label")
        self.assertIsNone(vac.get_active_context("vault-A"))

    def test_per_vault_isolation(self):
        vac.set_active_context(
            "vault-A", vac.CONTEXT_FILE_SEARCH_RESULTS,
        )
        vac.set_active_context(
            "vault-B", vac.CONTEXT_CREDENTIAL_DRAFT,
        )
        self.assertEqual(
            vac.get_active_context("vault-A"),
            vac.CONTEXT_FILE_SEARCH_RESULTS,
        )
        self.assertEqual(
            vac.get_active_context("vault-B"),
            vac.CONTEXT_CREDENTIAL_DRAFT,
        )

    def test_ttl_expiry(self):
        vac.set_active_context(
            "vault-A", vac.CONTEXT_FILE_SEARCH_RESULTS,
            ttl_seconds=1,
        )
        with patch(
            "vault_active_context._now",
            return_value=time.time() + 10,
        ):
            self.assertIsNone(vac.get_active_context("vault-A"))

    def test_clear(self):
        vac.set_active_context(
            "vault-A", vac.CONTEXT_FILE_SEARCH_RESULTS,
        )
        self.assertTrue(vac.clear_active_context("vault-A"))
        self.assertIsNone(vac.get_active_context("vault-A"))

    def test_empty_vault_id_silent_noop(self):
        vac.set_active_context("", vac.CONTEXT_FILE_SEARCH_RESULTS)
        vac.set_active_context(None, vac.CONTEXT_FILE_SEARCH_RESULTS)
        self.assertIsNone(vac.get_active_context(""))
        self.assertIsNone(vac.get_active_context(None))


class TestExplicitCredentialSavePhrase(unittest.TestCase):
    def test_recognised_phrases(self):
        for phrase in (
            "save the login draft",
            "save the credential",
            "save that credential",
            "save the pending login",
            "save the union bank login",
            "save the Union Bank login",
            "go back to the login draft",
            "go back to the draft",
            "save the username",
            "save the password",
            "save my password",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    vccg.is_explicit_credential_save_phrase(phrase),
                )

    def test_ambiguous_not_classified_as_explicit(self):
        for phrase in ("save it", "save it now", "save that", "save this"):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    vccg.is_explicit_credential_save_phrase(phrase),
                )

    def test_unrelated_phrase_not_classified(self):
        for phrase in (
            "great, what more can you do for me",
            "show me all ID photos",
            "open the first file",
            "tell me more",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    vccg.is_explicit_credential_save_phrase(phrase),
                )


class TestExplicitFileSavePhrase(unittest.TestCase):
    def test_file_phrasings_recognised(self):
        for phrase in (
            "save this file",
            "save that photo",
            "save the document",
            "save one of the files",
            "bookmark this",
            "bookmark that",
            "open the first",
            "open the second",
            "open the third",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    vccg.is_explicit_file_save_phrase(phrase),
                )

    def test_credential_phrasings_not_classified_as_file(self):
        for phrase in (
            "save the login draft",
            "save the union bank login",
            "save that credential",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    vccg.is_explicit_file_save_phrase(phrase),
                )


class TestAmbiguousSavePhrase(unittest.TestCase):
    def test_ambiguous_phrasings(self):
        for phrase in (
            "save it",
            "save it now",
            "save that",
            "save this",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(vccg.is_ambiguous_save_phrase(phrase))

    def test_explicit_credential_save_not_ambiguous(self):
        self.assertFalse(
            vccg.is_ambiguous_save_phrase("save the login draft"),
        )

    def test_explicit_file_save_not_ambiguous(self):
        self.assertFalse(
            vccg.is_ambiguous_save_phrase("save this file"),
        )

    def test_no_save_word_not_ambiguous(self):
        self.assertFalse(
            vccg.is_ambiguous_save_phrase(
                "great, what more can you do for me",
            )
        )


class TestSuppressionGate(unittest.TestCase):
    def test_no_pending_draft_always_suppresses(self):
                                                                     
                             
        for active in (
            None,
            vac.CONTEXT_FILE_SEARCH_RESULTS,
            vac.CONTEXT_CREDENTIAL_DRAFT,
            vac.CONTEXT_GENERAL_CHAT,
        ):
            with self.subTest(active=active):
                self.assertTrue(
                    vccg.should_suppress_pending_draft_save_shortcut(
                        active_context=active,
                        user_message="save it now",
                        has_pending_draft=False,
                    )
                )

    def test_credential_context_ambiguous_save_not_suppressed(self):
                                                             
                                                
        self.assertFalse(
            vccg.should_suppress_pending_draft_save_shortcut(
                active_context=vac.CONTEXT_CREDENTIAL_DRAFT,
                user_message="save it now",
                has_pending_draft=True,
            )
        )

    def test_file_search_results_context_unrelated_msg_suppressed(self):
                                                            
                                                                   
        self.assertTrue(
            vccg.should_suppress_pending_draft_save_shortcut(
                active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
                user_message="great, what more can you do for me",
                has_pending_draft=True,
            )
        )

    def test_file_search_results_context_ambiguous_save_suppressed(self):
                                                                  
                                                                 
        self.assertTrue(
            vccg.should_suppress_pending_draft_save_shortcut(
                active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
                user_message="save it now",
                has_pending_draft=True,
            )
        )

    def test_explicit_credential_save_unblocks_any_context(self):
                                                                    
                                                                     
        for active in (
            vac.CONTEXT_FILE_SEARCH_RESULTS,
            vac.CONTEXT_GENERAL_CHAT,
            vac.CONTEXT_VAULT_QUESTION,
            None,
        ):
            with self.subTest(active=active):
                self.assertFalse(
                    vccg.should_suppress_pending_draft_save_shortcut(
                        active_context=active,
                        user_message="save the login draft",
                        has_pending_draft=True,
                    )
                )

    def test_explicit_file_save_blocks_credential_branch(self):
                                                                    
                                                              
        self.assertTrue(
            vccg.should_suppress_pending_draft_save_shortcut(
                active_context=vac.CONTEXT_CREDENTIAL_DRAFT,
                user_message="save this file",
                has_pending_draft=True,
            )
        )


class TestAmbiguityClarification(unittest.TestCase):
    def test_clarification_fires_when_all_three_conditions_hold(self):
                                                                    
                                               
        self.assertTrue(
            vccg.should_request_save_ambiguity_clarification(
                active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
                user_message="save it now",
                has_pending_draft=True,
            )
        )

    def test_clarification_does_not_fire_without_pending_draft(self):
        self.assertFalse(
            vccg.should_request_save_ambiguity_clarification(
                active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
                user_message="save it now",
                has_pending_draft=False,
            )
        )

    def test_clarification_does_not_fire_when_active_is_credential(self):
                                                                     
                                                       
        self.assertFalse(
            vccg.should_request_save_ambiguity_clarification(
                active_context=vac.CONTEXT_CREDENTIAL_DRAFT,
                user_message="save it now",
                has_pending_draft=True,
            )
        )

    def test_clarification_does_not_fire_for_explicit_phrases(self):
                                                                     
        self.assertFalse(
            vccg.should_request_save_ambiguity_clarification(
                active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
                user_message="save the login draft",
                has_pending_draft=True,
            )
        )

    def test_clarification_does_not_fire_for_unrelated_message(self):
                                                                  
                        
        self.assertFalse(
            vccg.should_request_save_ambiguity_clarification(
                active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
                user_message="great, what more can you do for me",
                has_pending_draft=True,
            )
        )

    def test_clarification_text_is_operator_pinned(self):
                                                                   
                   
        self.assertEqual(
            vccg.AMBIGUITY_CLARIFICATION_TEXT,
            "Do you mean save the pending login draft, or "
            "save/bookmark one of these files?",
        )


class TestContextHintInjection(unittest.TestCase):
    def test_file_search_results_hint_mentions_file_actions(self):
                                                                    
                                                               
        hint = vccg.context_hint_system_message(
            active_context=vac.CONTEXT_FILE_SEARCH_RESULTS,
            has_pending_draft=False,
        )
        self.assertIsNotNone(hint)
                                                                  
        for action in (
            "open one of the files",
            "compare names",
            "find more files",
            "extract dates",
            "organize",
        ):
            with self.subTest(action=action):
                self.assertIn(action, hint or "")
                                                                 
                      
        self.assertIn("pending login draft", hint or "")

    def test_credential_draft_hint_recognises_save_phrases(self):
        hint = vccg.context_hint_system_message(
            active_context=vac.CONTEXT_CREDENTIAL_DRAFT,
            has_pending_draft=True,
        )
        self.assertIsNotNone(hint)
        self.assertIn("credential draft", hint or "")
        self.assertIn("save it now", hint or "")

    def test_general_chat_no_hint(self):
                                                                  
                      
        hint = vccg.context_hint_system_message(
            active_context=vac.CONTEXT_GENERAL_CHAT,
            has_pending_draft=False,
        )
        self.assertIsNone(hint)

    def test_none_context_no_hint(self):
        hint = vccg.context_hint_system_message(
            active_context=None, has_pending_draft=False,
        )
        self.assertIsNone(hint)


class TestPrivacyFloor(unittest.TestCase):
    def test_active_context_log_carries_no_user_text(self):
        import logging
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        log = logging.getLogger("vault_active_context")
        log.addHandler(sink)
        prior_level = log.level
        log.setLevel(logging.DEBUG)
        try:
            vac.set_active_context(
                "vault_secret_xyz_user_password_12345",
                vac.CONTEXT_FILE_SEARCH_RESULTS,
            )
            vac.get_active_context(
                "vault_secret_xyz_user_password_12345",
            )
        finally:
            log.removeHandler(sink)
            log.setLevel(prior_level)
        joined = "\n".join(r.getMessage() for r in records)
                                                    
        self.assertNotIn("vault_secret_xyz_user_password_12345", joined)
                                      
        self.assertIn(vac.CONTEXT_FILE_SEARCH_RESULTS, joined)

    def test_no_password_in_clarification_text(self):
                                 
        msg = vccg.AMBIGUITY_CLARIFICATION_TEXT.lower()
        for forbidden in ("password", "username", "secret"):
            self.assertNotIn(forbidden, msg)


class TestPendingDraftExpiry(unittest.TestCase):


    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_draft_expires_independently_of_active_context(self):
                                         
        draft = vcd.store_draft(
            vault_id="v1", service_name="Union Bank",
            username="ub_user", password="X" * 16,
            ttl_seconds=1,
        )
                                                          
        vac.set_active_context(
            "v1", vac.CONTEXT_FILE_SEARCH_RESULTS,
        )
                                          
        with patch(
            "vault_credential_draft._now",
            return_value=time.time() + 60,
        ):
            self.assertIsNone(
                vcd.get_draft(vault_id="v1"),
            )
                                                              
        self.assertEqual(
            vac.get_active_context("v1"),
            vac.CONTEXT_FILE_SEARCH_RESULTS,
        )


class TestEndToEndOperatorCases(unittest.TestCase):


    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_case1_draft_then_search_then_what_more_can_you_do(self):
                                    
                                      
        vac.set_active_context(
            "v1", vac.CONTEXT_FILE_SEARCH_RESULTS,
        )
        self.assertTrue(
            vccg.should_suppress_pending_draft_save_shortcut(
                active_context=vac.get_active_context("v1"),
                user_message="great, what more can you do for me",
                has_pending_draft=True,
            )
        )
        self.assertFalse(
            vccg.should_request_save_ambiguity_clarification(
                active_context=vac.get_active_context("v1"),
                user_message="great, what more can you do for me",
                has_pending_draft=True,
            )
        )

    def test_case2_draft_then_search_then_save_it_now_asks_clarification(self):
                                    
                                      
        vac.set_active_context(
            "v1", vac.CONTEXT_FILE_SEARCH_RESULTS,
        )
        self.assertTrue(
            vccg.should_request_save_ambiguity_clarification(
                active_context=vac.get_active_context("v1"),
                user_message="save it now",
                has_pending_draft=True,
            )
        )

    def test_case3_draft_then_save_it_now_saves(self):
                                    
                                              
        vac.set_active_context(
            "v1", vac.CONTEXT_CREDENTIAL_DRAFT,
        )
        self.assertFalse(
            vccg.should_suppress_pending_draft_save_shortcut(
                active_context=vac.get_active_context("v1"),
                user_message="save it now",
                has_pending_draft=True,
            )
        )
        self.assertFalse(
            vccg.should_request_save_ambiguity_clarification(
                active_context=vac.get_active_context("v1"),
                user_message="save it now",
                has_pending_draft=True,
            )
        )

    def test_case4_id_photo_then_what_can_you_do_with_this_offers_file_actions(
        self,
    ):
                                                                   
                                                                
        vac.set_active_context(
            "v1", vac.CONTEXT_FILE_SEARCH_RESULTS,
        )
        hint = vccg.context_hint_system_message(
            active_context=vac.get_active_context("v1"),
            has_pending_draft=False,
        )
        self.assertIsNotNone(hint)
                                                                 
        for fragment in ("open one of the files", "compare names"):
            self.assertIn(fragment, hint or "")


class TestSaveGuardStillCatchesHallucinations(unittest.TestCase):


    def test_save_guard_fires_on_hallucinated_claim(self):
        reply, slug = vsg.guard_response_text(
            reply_text="I've saved your Union Bank login.",
            save_tool_succeeded=False,
        )
        self.assertIsNotNone(slug)
        self.assertIn("I created the login draft", reply)
                                                            
                                                                
if __name__ == "__main__":                    
    unittest.main()
