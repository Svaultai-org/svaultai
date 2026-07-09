

from __future__ import annotations

import unittest

from vault_brain_intent import (
    classify_brain_intent,
    BrainIntent,
    BRAIN_INTENTS,
    SEARCH_VAULT_CONTENT,
    ANSWER_FROM_VAULT_CONTENT,
    ANSWER_FROM_FILE_CONTENT,
    SUMMARIZE_FILE_CONTENT,
    SUMMARIZE_FOLDER_CONTENT,
    CREDENTIAL_LOOKUP,
    NOT_VAULT_CONTENT,
)


class UserSpecExamplesTests(unittest.TestCase):


    def test_do_i_have_anything_about_blue_contract(self):
        result = classify_brain_intent(
            "Do I have anything about a blue contract?",
        )
        self.assertEqual(result.intent, SEARCH_VAULT_CONTENT)
        self.assertTrue(result.is_vault_content())

    def test_what_files_mention_ally_bank(self):
        result = classify_brain_intent("What files mention Ally Bank?")
        self.assertEqual(result.intent, SEARCH_VAULT_CONTENT)

    def test_what_does_this_document_say(self):
        result = classify_brain_intent("What does this document say?")
        self.assertEqual(result.intent, ANSWER_FROM_FILE_CONTENT)
        self.assertEqual(result.scope_hint, "this_file")

    def test_find_anything_about_insurance(self):
        result = classify_brain_intent("Find anything about insurance.")
        self.assertEqual(result.intent, SEARCH_VAULT_CONTENT)

    def test_what_did_i_save_about_my_card(self):
        result = classify_brain_intent("What did I save about my card?")
                                                              
                                                             
        self.assertEqual(result.intent, CREDENTIAL_LOOKUP)

    def test_summarize_this_folder(self):
        result = classify_brain_intent("Summarize this folder.")
        self.assertEqual(result.intent, SUMMARIZE_FOLDER_CONTENT)
        self.assertEqual(result.scope_hint, "this_folder")

    def test_which_files_mention_date(self):
        result = classify_brain_intent(
            "Which files mention 2027-08-19?",
        )
        self.assertEqual(result.intent, SEARCH_VAULT_CONTENT)

    def test_summarize_this_pdf(self):
        result = classify_brain_intent("Summarize this PDF.")
        self.assertEqual(result.intent, SUMMARIZE_FILE_CONTENT)

    def test_whats_my_chase_password(self):
        result = classify_brain_intent("What's my Chase password?")
        self.assertEqual(result.intent, CREDENTIAL_LOOKUP)


class ImperativeRefusedTests(unittest.TestCase):


    def test_save_my_gmail_password(self):
        result = classify_brain_intent(
            "save my Gmail password as foo",
        )
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)
        self.assertEqual(result.reason, "imperative_action_prefix")

    def test_rename_file(self):
        result = classify_brain_intent(
            "rename this to Receipt 2024.pdf",
        )
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)

    def test_delete_login(self):
        result = classify_brain_intent("delete my Chase login")
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)

    def test_update_password(self):
        result = classify_brain_intent("update my Gmail password to bar")
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)


class LegacySaversaurusRefusedTests(unittest.TestCase):


    def test_show_me_my_saved_logins(self):
        result = classify_brain_intent("show me my saved logins")
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)
        self.assertEqual(result.reason, "list_saved_logins_surface")

    def test_list_passwords(self):
        result = classify_brain_intent("list my passwords")
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)

    def test_see_my_credentials(self):
        result = classify_brain_intent("see my credentials")
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)

    def test_files_with_list_of_credentials_without_context_defers_to_strict_verifier(self):


        result = classify_brain_intent(
            "are these both the only files with list of credentials in it?"
        )
        self.assertEqual(result.intent, CREDENTIAL_LOOKUP)
        self.assertEqual(
            result.reason,
            "credential_files_strict_memory",
        )

    def test_files_with_list_of_credentials_with_context_still_strict(self):


        result = classify_brain_intent(
            "are these both the only files with list of credentials in it?",
            has_continuation_context=True,
        )
        self.assertEqual(result.intent, CREDENTIAL_LOOKUP)
        self.assertEqual(result.reason, "credential_coverage_followup")


class PendingFileNamingTests(unittest.TestCase):


    def test_bare_name_when_pending(self):
        result = classify_brain_intent(
            "vibing",
            pending_file_present=True,
        )
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)
        self.assertEqual(result.reason, "pending_file_bare_name")

    def test_question_overrides_pending(self):
                                                                     
                                                                
        result = classify_brain_intent(
            "Do I have anything about a blue contract?",
            pending_file_present=True,
        )
        self.assertEqual(result.intent, SEARCH_VAULT_CONTENT)


class ChitchatTests(unittest.TestCase):


    def test_hello(self):
        result = classify_brain_intent("hi")
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)

    def test_thanks(self):
        result = classify_brain_intent("thanks")
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)

    def test_how_are_you(self):
        result = classify_brain_intent("How are you?")
        self.assertEqual(result.intent, NOT_VAULT_CONTENT)


class UploadTurnTests(unittest.TestCase):


    def test_what_does_this_say_after_upload(self):
        result = classify_brain_intent(
            "What does this say?",
            has_uploaded_files_in_turn=True,
        )
        self.assertEqual(result.intent, ANSWER_FROM_FILE_CONTENT)

    def test_upload_turn_question(self):
        result = classify_brain_intent(
            "Why was this issued?",
            has_uploaded_files_in_turn=True,
        )
                                                                     
                                               
        self.assertEqual(result.intent, ANSWER_FROM_FILE_CONTENT)
        self.assertEqual(result.scope_hint, "this_file")


class SearchVerbTests(unittest.TestCase):


    def test_find_insurance(self):
        result = classify_brain_intent("Find insurance documents.")
        self.assertEqual(result.intent, SEARCH_VAULT_CONTENT)


class ContentNounsTests(unittest.TestCase):


    def test_when_does_my_lease_expire(self):
        result = classify_brain_intent(
            "When does my lease expire?",
        )
                                                                 
        self.assertEqual(result.intent, ANSWER_FROM_VAULT_CONTENT)


class FrozenDecisionTests(unittest.TestCase):


    def test_dict_shape(self):
        result = classify_brain_intent("Find anything about insurance.")
        d = result.to_dict()
        self.assertEqual(set(d.keys()), {"intent", "reason", "scope_hint"})
        self.assertIn(d["intent"], BRAIN_INTENTS.union({NOT_VAULT_CONTENT}))

    def test_immutable(self):
        result = BrainIntent(
            intent=SEARCH_VAULT_CONTENT,
            reason="x", scope_hint="",
        )
        with self.assertRaises(Exception):
            result.intent = NOT_VAULT_CONTENT        


class EmptyInputTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            classify_brain_intent("").intent, NOT_VAULT_CONTENT,
        )

    def test_whitespace(self):
        self.assertEqual(
            classify_brain_intent("   \n  ").intent, NOT_VAULT_CONTENT,
        )


if __name__ == "__main__":
    unittest.main()
