from __future__ import annotations

import inspect
import unittest

import main
from attachment_command_intent import (
    ATTACHMENT_INTENT_CONTENT_ANALYSIS,
    ATTACHMENT_INTENT_CREDENTIAL_EXTRACTION,
    classify_attachment_command,
    normalize_attachment_command_language,
    references_attachment_object,
)
from vault_brain_intent import is_current_attachment_content_request
from vault_credential_command import extract_credential_command


EXTRACTION_PHRASES = (
    "analyze this and save the credentials",
    "analyze this and save yhe credentials",
    "anlyze this and save the credentials",
    "analyse this and save credentials",
    "analyze ths and find all passwords",
    "read this file and extract credntials",
    "find the logins in this",
    "what credentials are in this?",
)


class AttachmentTypoPrecedenceTests(unittest.TestCase):
    def test_all_typo_variants_route_to_current_attachment_extraction(self):
        for phrase in EXTRACTION_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    classify_attachment_command(phrase),
                    ATTACHMENT_INTENT_CREDENTIAL_EXTRACTION,
                )
                self.assertTrue(main._user_requested_login_extraction(phrase))
                self.assertTrue(is_current_attachment_content_request(
                    phrase,
                    has_uploaded_files_in_turn=True,
                ))

    def test_routing_view_normalizes_only_documented_command_language(self):
        self.assertEqual(
            normalize_attachment_command_language(
                "anlyze ths docment and extract credntials"
            ),
            "analyze this document and extract credentials",
        )
        self.assertEqual(
            normalize_attachment_command_language(
                "read teh file and find paswords"
            ),
            "read the file and find passwords",
        )

    def test_general_attachment_analysis_remains_distinct(self):
        self.assertEqual(
            classify_attachment_command("show me what's in this file"),
            ATTACHMENT_INTENT_CONTENT_ANALYSIS,
        )
        self.assertEqual(
            classify_attachment_command("analyze this"),
            ATTACHMENT_INTENT_CONTENT_ANALYSIS,
        )

    def test_no_attachment_form_requires_file_and_cannot_create_login(self):
        phrase = "analyze this and save yhe credentials"
        self.assertTrue(references_attachment_object(phrase))
        self.assertFalse(main._is_coherent_credential_creation_request(phrase))
        source = inspect.getsource(main.chat_endpoint)
        missing_index = source.index("attachment_context_required")
        supplied_index = source.index("_supplied_credential_command =")
        planner_index = source.index("site=route_to_ai_planner_stream")
        self.assertLess(missing_index, supplied_index)
        self.assertLess(missing_index, planner_index)
        self.assertFalse(references_attachment_object("show me family photo"))

    def test_supplied_values_are_never_command_normalized(self):
        message = (
            "save my instagram username anlyze "
            "password credntials"
        )
        command = extract_credential_command(message)
        self.assertEqual(command.explicit_fields["username"], "anlyze")
        self.assertEqual(command.explicit_fields["password"], "credntials")
        self.assertIsNone(classify_attachment_command(message))

    def test_preserved_credential_routes_remain_mutually_distinct(self):
        for generated in (
            "generate me an instagram login",
            "create me a new facebook login",
        ):
            with self.subTest(generated=generated):
                self.assertTrue(
                    main._is_coherent_credential_creation_request(generated)
                )
        supplied = "save my instagram username john password abc123"
        self.assertTrue(main._is_coherent_credential_creation_request(supplied))
        supplied_command = extract_credential_command(supplied)
        self.assertEqual(supplied_command.service, "instagram")
        self.assertEqual(supplied_command.explicit_fields["username"], "john")
        self.assertEqual(supplied_command.explicit_fields["password"], "abc123")
        for retrieval in (
            "what is my facebook login",
            "show my facebook login",
        ):
            with self.subTest(retrieval=retrieval):
                self.assertIsNone(classify_attachment_command(retrieval))
                self.assertFalse(
                    main._is_coherent_credential_creation_request(retrieval)
                )


if __name__ == "__main__":
    unittest.main()
