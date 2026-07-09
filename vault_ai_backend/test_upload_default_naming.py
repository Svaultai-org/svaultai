

from __future__ import annotations

import unittest

from main import (
    _build_upload_message,
    _classify_secret_from_text,
    _is_high_confidence_login,
    _is_valid_secret_payload,
    decide_pending_file_intent_override,
    extract_naming_intent_from_accompanying_text,
)


class HighConfidenceLoginGateTests(unittest.TestCase):


    def _payload(self, *, service="capital one", fields=None):
        return {
            "secret_type": "login",
            "service": service,
            "fields": fields or {},
        }

    def test_full_triad_passes(self):
        p = self._payload(fields={"username": "alice", "password": "BarBaz!1"})
        self.assertTrue(_is_high_confidence_login(p))

    def test_email_counts_as_identifier(self):
        p = self._payload(fields={"email": "alice@example.com", "password": "x"})
        self.assertTrue(_is_high_confidence_login(p))

    def test_token_counts_as_secret(self):
        p = self._payload(fields={"username": "alice", "token": "tok_abc"})
        self.assertTrue(_is_high_confidence_login(p))

    def test_pin_counts_as_secret(self):
        p = self._payload(fields={"username": "alice", "pin": "4242"})
        self.assertTrue(_is_high_confidence_login(p))

    def test_api_key_counts_as_secret(self):
        p = self._payload(fields={"email": "a@b.c", "api_key": "k_xyz"})
        self.assertTrue(_is_high_confidence_login(p))

                                                                            
    def test_general_service_rejected(self):
        p = self._payload(
            service="general",
            fields={"username": "alice", "password": "Bar123"},
        )
        self.assertFalse(_is_high_confidence_login(p))

    def test_identifier_only_rejected(self):
                                                                       
                                                             
        p = self._payload(fields={"username": "12345"})
        self.assertTrue(_is_valid_secret_payload(p))
        self.assertFalse(_is_high_confidence_login(p))

    def test_secret_only_rejected(self):
        p = self._payload(fields={"password": "Bar123"})
        self.assertTrue(_is_valid_secret_payload(p))
        self.assertFalse(_is_high_confidence_login(p))

    def test_empty_payload_rejected(self):
        self.assertFalse(_is_high_confidence_login({}))
        self.assertFalse(_is_high_confidence_login(None))


class ClassifySecretFromTextTests(unittest.TestCase):


    def test_account_label_only_is_not_a_login(self):
                                                                   
                                                                    
        text = (
            "Statement Summary\n"
            "Account: 88812345\n"
            "Due to rounding or minimum interest charge, this period "
            "shows a minimum payment of $25.00.\n"
            "Payment due April 15.\n"
        )
        result = _classify_secret_from_text(text, "statement-april.pdf")
        self.assertEqual(result["detected_type"], "file")
        self.assertEqual(result["payloads"], [])

    def test_due_to_rounding_phrase_alone_is_not_a_login(self):
                                                                
                                                                  
        text = (
            "Due to rounding or minimum interest charge, this statement "
            "shows a remaining balance of $0.23.\n"
        )
        result = _classify_secret_from_text(text, "statement.pdf")
        self.assertEqual(result["detected_type"], "file")
        self.assertEqual(result["payloads"], [])

    def test_invoice_without_credit_card_keywords_is_a_file(self):
                                                                       
                                             
        text = (
            "INVOICE 003421\n"
            "Bill to: ACME Corp\n"
            "Item: Consulting services — 8 hours\n"
            "Net 30.\n"
        )
        result = _classify_secret_from_text(text, "invoice-003421.pdf")
        self.assertEqual(result["detected_type"], "file")
        self.assertEqual(result["payloads"], [])

    def test_genuine_login_paragraph_is_classified_as_login(self):
                                                                
                                                                 
        text = (
            "gmail\n"
            "username: alice@example.com\n"
            "password: hunter2!Strong\n"
        )
        result = _classify_secret_from_text(text, "creds.txt")
        self.assertEqual(result["detected_type"], "login")
        self.assertTrue(result["payloads"])
        payload = result["payloads"][0]
        self.assertEqual(payload["secret_type"], "login")
        self.assertIn(payload["service"].lower(), ("gmail",))


class AccompanyingTextVetoTests(unittest.TestCase):


    def test_use_original_names_returns_none(self):
        self.assertIsNone(
            extract_naming_intent_from_accompanying_text("use original names"),
        )

    def test_use_their_original_filenames_returns_none(self):
        self.assertIsNone(
            extract_naming_intent_from_accompanying_text(
                "use their original filenames",
            ),
        )

    def test_keep_original_filenames_returns_none(self):
        self.assertIsNone(
            extract_naming_intent_from_accompanying_text("keep original filenames"),
        )

    def test_each_original_names_returns_none(self):
                                               
        self.assertIsNone(
            extract_naming_intent_from_accompanying_text("each original names"),
        )

    def test_with_their_own_names_returns_none(self):
        self.assertIsNone(
            extract_naming_intent_from_accompanying_text(
                "with their own names",
            ),
        )

    def test_save_with_original_names_returns_none(self):
        self.assertIsNone(
            extract_naming_intent_from_accompanying_text(
                "save with original names",
            ),
        )

    def test_legitimate_name_still_passes(self):
                                                                   
                                                                  
        result = extract_naming_intent_from_accompanying_text(
            "call this passport",
        )
        self.assertIsNotNone(result)
        self.assertIn("passport", result.lower())


class UploadDefaultsTests(unittest.TestCase):


    def test_normalize_returns_human_readable(self):
        from main import _normalize_asset_name
        out = _normalize_asset_name("invoice-april-2026.pdf")
                                                                      
                                                             
        self.assertTrue(out)
        self.assertNotEqual(out, "general")

    def test_normalize_handles_audio_pdf_video_image_doc(self):
        from main import _normalize_asset_name
        for name in (
            "passport.pdf",
            "vacation.jpg",
            "voice-memo.m4a",
            "demo.mp4",
            "contract.docx",
        ):
            with self.subTest(name=name):
                out = _normalize_asset_name(name)
                self.assertTrue(out)
                self.assertNotEqual(out, "general")


class BuildUploadMessageBatchBranchTests(unittest.TestCase):


    def _result(self, *, asset_type: str = "video",
                filename: str = "clip.mp4") -> dict:
        return {
            "filename": filename,
            "asset_type": asset_type,
            "detected_type": "file",
            "detected_service": "general",
            "autosaved_secret": False,
            "saved_count": 0,
            "skipped_count": 0,
        }

    def test_single_video_upload_emits_prompt(self):
                                                                       
                                                                  
        msg = _build_upload_message(self._result(asset_type="video"))
        self.assertIn("What should I save this video as?", msg)

    def test_single_image_upload_emits_prompt(self):
        msg = _build_upload_message(self._result(asset_type="image"))
        self.assertIn("Tell me what you want to call it", msg)

    def test_single_audio_upload_emits_prompt(self):
        msg = _build_upload_message(self._result(asset_type="audio"))
        self.assertIn("What should I save this recording as?", msg)

    def test_single_file_upload_emits_prompt(self):
        msg = _build_upload_message(self._result(asset_type="file"))
        self.assertIn("Tell me what you want to call it", msg)

    def test_batch_video_upload_does_not_emit_prompt(self):
        msg = _build_upload_message(
            self._result(asset_type="video"),
            is_batch_upload=True,
        )
        self.assertNotIn("What should I save this", msg)
        self.assertNotIn("Tell me what you want to call it", msg)

    def test_batch_file_upload_does_not_emit_prompt(self):
        msg = _build_upload_message(
            self._result(asset_type="file"),
            is_batch_upload=True,
        )
        self.assertNotIn("What should I save this", msg)
        self.assertNotIn("Tell me what you want to call it", msg)


class PendingFileOverrideAfterPromptTests(unittest.TestCase):


    def test_sheinport_coerced_to_name_file(self):
                                                                       
                                                                  
        for llm_intent in ("general_chat", "identity", None, ""):
            with self.subTest(llm_intent=llm_intent):
                final, override_applied, reason = (
                    decide_pending_file_intent_override(
                        llm_intent, "sheinport", pending_file_present=True,
                    )
                )
                self.assertEqual(final, "name_file")
                self.assertTrue(override_applied)
                self.assertIsNone(reason)

    def test_no_override_when_no_pending_file(self):
                                                       
                                                                  
        final, override_applied, _ = decide_pending_file_intent_override(
            "general_chat", "sheinport", pending_file_present=False,
        )
        self.assertEqual(final, "general_chat")
        self.assertFalse(override_applied)

    def test_question_does_not_coerce_even_with_pending_file(self):
        final, override_applied, reason = (
            decide_pending_file_intent_override(
                "general_chat",
                "what should I name this?",
                pending_file_present=True,
            )
        )
        self.assertNotEqual(final, "name_file")
        self.assertFalse(override_applied)
        self.assertEqual(reason, "message_not_bare_name")

    def test_explicit_logins_intent_skips_naming_override(self):
                                                                   
                                                                     
        final, override_applied, reason = (
            decide_pending_file_intent_override(
                "general_chat",
                "show my saved logins",
                pending_file_present=True,
            )
        )
        self.assertEqual(final, "list_logins")
        self.assertFalse(override_applied)
        self.assertEqual(reason, "explicit_logins_intent_downgrade")


if __name__ == "__main__":
    unittest.main()
