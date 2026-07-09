

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from main import (
    _classify_secret_from_text,
    _is_high_confidence_login,
    _user_requested_login_extraction,
    save_uploaded_file,
)


class UserRequestedLoginExtractionTests(unittest.TestCase):


    def test_find_logins_in_this_file(self):
        self.assertTrue(
            _user_requested_login_extraction("Find logins in this file")
        )

    def test_extract_passwords_from_this_pdf(self):
        self.assertTrue(
            _user_requested_login_extraction("Extract passwords from this PDF")
        )

    def test_scan_folder_for_saved_accounts(self):
        self.assertTrue(
            _user_requested_login_extraction(
                "Scan this folder for saved accounts"
            )
        )

    def test_check_documents_for_login_details(self):
        self.assertTrue(
            _user_requested_login_extraction(
                "Check these documents for login details"
            )
        )

    def test_save_any_login_credentials(self):
        self.assertTrue(
            _user_requested_login_extraction(
                "Save any login credentials you find in this file"
            )
        )

    def test_extract_credentials_from_this_zip(self):
        self.assertTrue(
            _user_requested_login_extraction(
                "Extract credentials from this zip"
            )
        )

    def test_case_insensitive_match(self):
        self.assertTrue(
            _user_requested_login_extraction("EXTRACT PASSWORDS PLEASE")
        )

    def test_pull_passwords(self):
        self.assertTrue(
            _user_requested_login_extraction("Pull passwords out of this")
        )

    def test_search_for_logins(self):
        self.assertTrue(
            _user_requested_login_extraction(
                "Search for logins inside the attached"
            )
        )

    def test_save_the_passwords(self):
        self.assertTrue(
            _user_requested_login_extraction(
                "Save the passwords from this dump"
            )
        )

                                  
    def test_none_is_false(self):
        self.assertFalse(_user_requested_login_extraction(None))

    def test_empty_is_false(self):
        self.assertFalse(_user_requested_login_extraction(""))
        self.assertFalse(_user_requested_login_extraction("   "))

    def test_save_these_files_does_not_trigger(self):
                                                                         
                                                  
        self.assertFalse(_user_requested_login_extraction("save these files"))

    def test_show_my_files_does_not_trigger(self):
        self.assertFalse(_user_requested_login_extraction("show my files"))

    def test_bank_statement_caption_does_not_trigger(self):
                                                              
                                                                    
        self.assertFalse(
            _user_requested_login_extraction(
                "this is my chase credit card statement for april"
            )
        )

    def test_naming_intent_does_not_trigger(self):
                                                                   
                                                                  
        self.assertFalse(
            _user_requested_login_extraction("save my passport")
        )

    def test_save_my_gmail_login_chat_path_does_not_trigger_upload_extractor(self):
                                                                
                                                                
        self.assertFalse(
            _user_requested_login_extraction(
                "save my gmail login: user alice@x.com password hunter2"
            )
        )

    def test_arbitrary_prose_does_not_trigger(self):
        self.assertFalse(
            _user_requested_login_extraction(
                "here are some receipts from last week"
            )
        )

    def test_due_to_rounding_does_not_trigger(self):
                                                                  
                                                                  
        self.assertFalse(
            _user_requested_login_extraction(
                "the statement says due to rounding or minimum "
                "interest charge"
            )
        )

    def test_login_mentioned_without_a_verb_does_not_trigger(self):
                                                                 
        self.assertFalse(
            _user_requested_login_extraction(
                "my netflix login is the same as my hbo login"
            )
        )


class _FakeBackgroundTasks:


    def __init__(self):
        self.added: list = []

    def add_task(self, func, *args, **kwargs):
        self.added.append((func, args, kwargs))


def _fake_ensure_vault_exists(_vault_id):
    return None


def _fake_get_db():
    class _Cur:
        def execute(self, *_a, **_k):
            return None

        def fetchone(self):
            return {"id": "fake-row"}

        def fetchall(self):
                                                      
                                                                 
            return []

        def close(self):
            return None

    class _Conn:
        def cursor(self, **_k):
            return _Cur()

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    return _Conn()


class SaveUploadedFileLoginGateTests(unittest.TestCase):


    def _run(self, *, accompanying_login_payloads, auto_save):


        save_secret_calls: list = []

        def _fake_save_secret_tool(vault_id, payload, key):
            save_secret_calls.append((vault_id, payload, key))
            return {"status": "ok", "id": f"secret-{len(save_secret_calls)}"}

        classification = {
            "detected_type": "login" if accompanying_login_payloads else "file",
            "detected_service": "gmail" if accompanying_login_payloads else "general",
            "payloads": accompanying_login_payloads,
        }

                                                                              
        with patch("main._classify_secret_from_text", return_value=classification), \
             patch("main._extract_text_from_bytes", return_value="ignored"), \
             patch("main._should_analyze_upload", return_value=True), \
             patch("main.encrypt_bytes", return_value="ENC"), \
             patch("main.encrypt_message", return_value="ENC_TXT"), \
             patch("main.save_secret_tool", side_effect=_fake_save_secret_tool), \
             patch("billing.get_account_id_for_vault", return_value=None), \
             patch("main.get_vault_total_bytes", return_value=0), \
             patch("main.ensure_vault_exists", side_effect=_fake_ensure_vault_exists), \
             patch("main.get_db", side_effect=_fake_get_db), \
             patch("main._default_asset_type_for_upload", return_value="file"), \
             patch("main._run_post_upload_processing"):
            try:
                save_uploaded_file(
                    vault_id="vault-1",
                    file_name="statement-april.pdf",
                    content_type="application/pdf",
                    file_bytes=b"ignored",
                    key=b"k" * 32,
                    background_tasks=_FakeBackgroundTasks(),
                    is_batch_upload=False,
                    auto_save_login_credentials=auto_save,
                )
            except Exception:
                                                                     
                                                                          
                pass

        return save_secret_calls

    @staticmethod
    def _login_payload():
        return {
            "secret_type": "login",
            "service": "gmail",
            "fields": {
                "username": "alice@example.com",
                "password": "hunter2",
            },
        }

    def test_default_upload_with_login_payloads_creates_zero_login_items(self):
                                                                         
        calls = self._run(
            accompanying_login_payloads=[self._login_payload()],
            auto_save=False,
        )
        self.assertEqual(
            calls,
            [],
            "default upload must never forward login payloads to save_secret_tool",
        )

    def test_explicit_extract_with_high_confidence_login_creates_one_item(self):
                                                                     
                                                
        calls = self._run(
            accompanying_login_payloads=[self._login_payload()],
            auto_save=True,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["service"], "gmail")
        self.assertEqual(
            calls[0][1]["fields"]["username"], "alice@example.com"
        )

    def test_default_upload_with_no_payloads_is_a_no_op(self):
        calls = self._run(
            accompanying_login_payloads=[],
            auto_save=False,
        )
        self.assertEqual(calls, [])

    def test_default_upload_with_multiple_login_payloads_skips_all(self):
                                                                 
                                                                 
        payloads = [
            self._login_payload(),
            {
                "secret_type": "login",
                "service": "github",
                "fields": {"username": "alice", "token": "ghp_xxx"},
            },
            {
                "secret_type": "login",
                "service": "aws",
                "fields": {"username": "alice", "api_key": "AKIAXXX"},
            },
        ]
        calls = self._run(
            accompanying_login_payloads=payloads,
            auto_save=False,
        )
        self.assertEqual(calls, [])

    def test_default_upload_signature_has_safe_default(self):
                                                                      
                                                                 
        sig = inspect.signature(save_uploaded_file)
        param = sig.parameters.get("auto_save_login_credentials")
        self.assertIsNotNone(
            param,
            "save_uploaded_file must accept auto_save_login_credentials",
        )
        self.assertIs(
            param.default,
            False,
            "default must be False — explicit-only is the product rule",
        )


class CanonicalFalsePositiveTests(unittest.TestCase):


    def test_due_to_rounding_text_does_not_classify_as_high_confidence(self):
        text = (
            "Due to rounding or minimum interest charge, the balance "
            "may differ slightly from the statement total."
        )
        result = _classify_secret_from_text(text, "statement-april.pdf")
        for p in result.get("payloads") or []:
            self.assertFalse(
                _is_high_confidence_login(p),
                f"statement prose must not produce a high-confidence "
                f"login payload, got: {p}",
            )

    def test_bank_statement_text_with_amount_and_date_does_not_save(self):
                                                                   
                                                                    
        text = (
            "Your account ending in 1234 was charged $84.20 on April 3. "
            "Due to rounding or minimum interest charge, the next "
            "statement may show a residual balance."
        )
        result = _classify_secret_from_text(text, "statement-april.pdf")
                                                                     
                                                                    
        for p in result.get("payloads") or []:
            self.assertFalse(
                _is_high_confidence_login(p),
                f"bank statement prose must never produce a high-"
                f"confidence login, got: {p}",
            )


class LogRedactionTests(unittest.TestCase):


    def test_login_autosave_skipped_log_line_does_not_emit_payload(self):
        src = inspect.getsource(save_uploaded_file)
                                                                       
                                     
        forbidden = ['payload="', 'payload={', 'payloads=', 'fields=']
                                                                  
                                                                     
        marker = '"upload.login_autosave_skipped"'
        idx = src.find(marker)
        self.assertGreater(
            idx,
            -1,
            "the skipped-login log marker must exist for this guard "
            "to be meaningful",
        )
        log_slice = src[idx: idx + 400]
        for token in forbidden:
            self.assertNotIn(
                token,
                log_slice,
                f"skipped-login log must not include payload contents; "
                f"found {token!r}",
            )


if __name__ == "__main__":
    unittest.main()
