from __future__ import annotations

import unittest

from attachment_command_intent import (
    ATTACHMENT_INTENT_CREDENTIAL_EXTRACTION,
    classify_attachment_command,
    references_attachment_object,
)


class VaultContextAttachmentRoutingTests(unittest.TestCase):
    def test_real_vault_question_does_not_require_an_attachment(self):
        self.assertFalse(references_attachment_object(
            "How can I find a saved note in this test vault?"
        ))
        self.assertFalse(references_attachment_object(
            "Show me my notes in this private vault"
        ))

    def test_explicit_attachment_still_requires_current_file(self):
        self.assertTrue(references_attachment_object(
            "Find this document in this test vault"
        ))
        self.assertTrue(references_attachment_object(
            "Analyze this vault file and save the credentials"
        ))
        self.assertTrue(references_attachment_object(
            "Analyze this and save the credentials"
        ))
        self.assertEqual(
            classify_attachment_command("Analyze this and save the credentials"),
            ATTACHMENT_INTENT_CREDENTIAL_EXTRACTION,
        )


if __name__ == "__main__":
    unittest.main()
