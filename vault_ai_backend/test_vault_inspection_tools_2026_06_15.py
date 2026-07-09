

from __future__ import annotations

import json
import unittest
from unittest import mock

import vault_inspection_tools as vit


_KEY = b"\x77" * 32


def _row(
    file_id="f1", vault_id="v1",
    file_name="report.pdf", saved_name="report.pdf",
    relative_path="/Files/",
    content_type="application/pdf",
    asset_type="document", file_size=1024,
    extracted_text="ENC", extracted_text_encrypted=True,
    encrypted_file_data=None,
    analysis_status="ready",
):
    return {
        "id":                       file_id,
        "vault_id":                 vault_id,
        "file_name":                file_name,
        "saved_name":               saved_name,
        "relative_path":            relative_path,
        "content_type":             content_type,
        "asset_type":               asset_type,
        "file_size":                file_size,
        "created_at":               None,
        "detected_type":            None,
        "detected_service":         None,
        "upload_status":            "complete",
        "analysis_status":          analysis_status,
        "encrypted_file_data":      encrypted_file_data,
        "extracted_text":           extracted_text,
        "extracted_text_encrypted": extracted_text_encrypted,
    }


class KeyGateTests(unittest.TestCase):
    def test_read_file_text_refuses_short_key(self):
        out = vit.read_file_text(
            vault_id="v1", key=b"short", file_id="f1",
        )
        self.assertEqual(json.loads(out).get("error"), "vault_locked")

    def test_read_image_with_vision_refuses_short_key(self):
        out = vit.read_image_with_vision(
            vault_id="v1", key=b"short",
            file_id="f1", question="anything",
        )
        self.assertEqual(json.loads(out).get("error"), "vault_locked")

    def test_search_extracted_text_refuses_short_key(self):
        out = vit.search_extracted_text(
            vault_id="v1", key=b"short", query="anything",
        )
        self.assertEqual(json.loads(out).get("error"), "vault_locked")

    def test_save_requires_unlocked_vault(self):
        out = vit.save_generated_credential_after_confirmation(
            vault_id="v1", key=b"short",
            service="chase",
            fields={"username": "x", "password": "y"},
            user_confirmed=True,
        )
        self.assertEqual(json.loads(out).get("error"), "vault_locked")


class CrossVaultIsolation(unittest.TestCase):
    def test_read_file_text_returns_not_found_for_wrong_vault(self):
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=None,
        ):
            out = vit.read_file_text(
                vault_id="v-OTHER", key=_KEY, file_id="f-belongs-to-v1",
            )
        self.assertEqual(json.loads(out).get("error"), "not_found")

    def test_inspect_uploaded_file_not_found(self):
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=None,
        ):
            out = vit.inspect_uploaded_file(
                vault_id="v-OTHER", key=_KEY, file_id="f1",
            )
        self.assertEqual(json.loads(out).get("error"), "not_found")

    def test_get_file_metadata_not_found(self):
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=None,
        ):
            out = vit.get_file_metadata(
                vault_id="v-OTHER", key=_KEY, file_id="f1",
            )
        self.assertEqual(json.loads(out).get("error"), "not_found")

    def test_fetch_file_row_query_includes_vault_scope(self):
                                                        
        import inspect, vault_inspection_tools as mod
        src = inspect.getsource(mod._fetch_file_row)
        self.assertIn("vault_id = %s", src)
        self.assertIn("(file_id, vault_id)", src)


class ReadFileTextTests(unittest.TestCase):
    def test_returns_decrypted_redacted_text(self):
        row = _row(extracted_text="ENC_BLOB")
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_message",
            return_value="Hello world. password: hunter2",
        ):
            out = vit.read_file_text(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload["file_id"], "f1")
        self.assertEqual(payload["file_name"], "report.pdf")
                                                           
        self.assertNotIn("hunter2", payload["text"])

    def test_no_text_branch_when_extracted_empty(self):
                                                               
                                                             
        row = _row(
            asset_type="image",
            content_type="image/png",
            extracted_text=None, extracted_text_encrypted=False,
        )
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ):
            out = vit.read_file_text(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "no_text")
                                      
        self.assertIn("vision", payload.get("hint", "").lower())

    def test_decrypt_failure_treated_as_no_text(self):
        row = _row(extracted_text="ENC")
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_message",
            side_effect=RuntimeError("bad key"),
        ):
            out = vit.read_file_text(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "no_text")

    def test_truncates_oversized_text(self):
        long_text = "A" * (vit.MAX_TEXT_CHARS_RETURNED + 500)
        row = _row(extracted_text="ENC")
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_message", return_value=long_text,
        ):
            out = vit.read_file_text(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
        self.assertTrue(payload["truncated"])
        self.assertLessEqual(
            len(payload["text"]), vit.MAX_TEXT_CHARS_RETURNED,
        )


class ReadImageWithVisionTests(unittest.TestCase):
    def test_rejects_non_image_file(self):
        row = _row(asset_type="document",
                   content_type="application/pdf")
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ):
            out = vit.read_image_with_vision(
                vault_id="v1", key=_KEY,
                file_id="f1", question="who is in it?",
            )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "not_an_image")
                                               
        self.assertIn("read_file_text", payload.get("hint", ""))

    def test_rejects_decrypt_failure(self):
        row = _row(asset_type="image", content_type="image/png",
                   encrypted_file_data="ENC")
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_bytes",
            side_effect=RuntimeError("bad key"),
        ):
            out = vit.read_image_with_vision(
                vault_id="v1", key=_KEY,
                file_id="f1", question="who is it?",
            )
        self.assertEqual(
            json.loads(out).get("error"), "decrypt_failed",
        )

    def test_rejects_oversized_image(self):
        row = _row(asset_type="image", content_type="image/png",
                   encrypted_file_data="ENC")
        big = b"\x00" * (vit.MAX_IMAGE_BYTES + 10)
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_bytes", return_value=big,
        ):
            out = vit.read_image_with_vision(
                vault_id="v1", key=_KEY,
                file_id="f1", question="?",
            )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "image_too_large")

    def test_rejects_missing_api_key(self):
        row = _row(asset_type="image", content_type="image/png",
                   encrypted_file_data="ENC")
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_bytes", return_value=b"\x89PNG\r\n",
        ), mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            out = vit.read_image_with_vision(
                vault_id="v1", key=_KEY,
                file_id="f1", question="?",
            )
        self.assertEqual(json.loads(out).get("error"), "unavailable")

    def test_empty_question_rejected(self):
        out = vit.read_image_with_vision(
            vault_id="v1", key=_KEY, file_id="f1", question="   ",
        )
        self.assertEqual(
            json.loads(out).get("error"), "empty_question",
        )

    def test_successful_vision_call_returns_redacted_analysis(self):
        row = _row(asset_type="image", content_type="image/png",
                   encrypted_file_data="ENC")
        fake_resp = mock.MagicMock()
        fake_resp.choices = [mock.MagicMock()]
        fake_resp.choices[0].message.content = (
            "This appears to be an ID card for Louis Iodato."
        )
        fake_client = mock.MagicMock()
        fake_client.chat.completions.create.return_value = fake_resp
        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch(
            "vault_core.decrypt_bytes", return_value=b"\x89PNG\r\n",
        ), mock.patch.dict(
            "os.environ", {"OPENAI_API_KEY": "test"},
        ), mock.patch(
            "openai.OpenAI", return_value=fake_client,
        ):
            out = vit.read_image_with_vision(
                vault_id="v1", key=_KEY,
                file_id="f1",
                question="Is this Louis Iodato's ID?",
            )
        payload = json.loads(out)
        self.assertIn("Louis Iodato", payload["analysis"])
        self.assertEqual(payload["file_id"], "f1")
                                                                 
        call = fake_client.chat.completions.create.call_args
        msgs = call.kwargs["messages"]
        self.assertEqual(msgs[0]["role"], "user")
                                                            
        content = msgs[0]["content"]
        types = [c["type"] for c in content]
        self.assertIn("image_url", types)
        self.assertIn("text", types)


class SearchExtractedTextTests(unittest.TestCase):
    def test_empty_query_rejected(self):
        out = vit.search_extracted_text(
            vault_id="v1", key=_KEY, query="   ",
        )
        self.assertEqual(
            json.loads(out).get("error"), "empty_query",
        )

    def test_finds_match_in_decrypted_text(self):
        rows = [
            {
                "id": "f1", "file_name": "doc.txt",
                "saved_name": "doc.txt", "relative_path": "",
                "asset_type": "document", "content_type": "text/plain",
                "extracted_text":
                    "Louis Iodato is the owner of the ID document.",
            },
            {
                "id": "f2", "file_name": "noise.txt",
                "saved_name": "noise.txt", "relative_path": "",
                "asset_type": "document", "content_type": "text/plain",
                "extracted_text": "Lorem ipsum.",
            },
        ]
        with mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 2, "analyzed": 2, "pending": 0,
                "processing": 0,
            },
        ):
            out = vit.search_extracted_text(
                vault_id="v1", key=_KEY, query="Louis Iodato",
            )
        payload = json.loads(out)
        self.assertEqual(payload["returned"], 1)
        self.assertEqual(payload["hits"][0]["file_id"], "f1")
        self.assertIn("Louis", payload["hits"][0]["snippet"])

    def test_kind_filter_applied(self):
        rows = [{
            "id": "f1", "file_name": "doc.txt",
            "saved_name": "doc.txt", "relative_path": "",
            "asset_type": "document", "content_type": "text/plain",
            "extracted_text": "matches",
        }]
        with mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=rows,
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={"total": 1, "analyzed": 1},
        ):
            out = vit.search_extracted_text(
                vault_id="v1", key=_KEY,
                query="matches", file_kind="image",
            )
                              
        self.assertEqual(json.loads(out)["returned"], 0)


class InspectUploadedFileTests(unittest.TestCase):
    def test_returns_closed_set_fields_only(self):
        row = _row()
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.side_effect = [
            {
                "document_purpose": "id_document",
                "purpose_label":    "ID document",
                "purpose_confidence": 0.92,
                "status":           "ready",
                "entities_jsonb": {
                    "people":        ["Louis Iodato"],
                    "organizations": [],
                    "places":        [],
                },
                "summary_short":    "Government ID card.",
            },
        ]
        fake_cur.fetchall.return_value = []
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur

        with mock.patch.object(
            vit, "_fetch_file_row", return_value=row,
        ), mock.patch("main.get_db", return_value=fake_conn):
            out = vit.inspect_uploaded_file(
                vault_id="v1", key=_KEY, file_id="f1",
            )
        payload = json.loads(out)
                                          
        self.assertNotIn("extracted_text", payload)
        self.assertEqual(payload["document_purpose"], "id_document")
        self.assertIn("Louis Iodato", payload["entities"]["people"])


class SaveConfirmationGateTests(unittest.TestCase):
    def test_refuses_without_user_confirmed(self):
        out = vit.save_generated_credential_after_confirmation(
            vault_id="v1", key=_KEY,
            service="chase",
            fields={"username": "x", "password": "y"},
            user_confirmed=False,
        )
        payload = json.loads(out)
        self.assertEqual(payload.get("error"), "confirmation_required")
                                                             
        self.assertIn("save it", payload.get("hint", "").lower())

    def test_refuses_without_user_confirmed_param(self):
        out = vit.save_generated_credential_after_confirmation(
            vault_id="v1", key=_KEY,
            service="chase",
            fields={"username": "x", "password": "y"},
        )
        self.assertEqual(
            json.loads(out).get("error"), "confirmation_required",
        )

    def test_refuses_without_password(self):
        out = vit.save_generated_credential_after_confirmation(
            vault_id="v1", key=_KEY,
            service="chase",
            fields={"username": "x"},
            user_confirmed=True,
        )
        self.assertEqual(
            json.loads(out).get("error"), "missing_password",
        )

    def test_refuses_without_identity(self):
        out = vit.save_generated_credential_after_confirmation(
            vault_id="v1", key=_KEY,
            service="chase",
            fields={"password": "y"},
            user_confirmed=True,
        )
        self.assertEqual(
            json.loads(out).get("error"), "missing_identity",
        )

    def test_calls_save_secret_tool_when_confirmed(self):
        with mock.patch(
            "main.save_secret_tool", return_value="Saved.",
        ) as save_mock:
            out = vit.save_generated_credential_after_confirmation(
                vault_id="v1", key=_KEY,
                service="chase",
                fields={
                    "username": "riverfox472",
                    "password": "Strong!!Pass99",
                },
                user_confirmed=True,
            )
        save_mock.assert_called_once()
        payload = json.loads(out)
        self.assertTrue(payload["saved"])
        self.assertEqual(payload["service"], "chase")


class DispatchWiringTests(unittest.TestCase):
    _EXPECTED = (
        "read_file_text",
        "read_image_with_vision",
        "search_extracted_text",
        "inspect_uploaded_file",
        "get_file_metadata",
        "list_saved_credentials",
        "get_credential_metadata",
        "save_generated_credential_after_confirmation",
    )

    def test_inspection_dispatch_contains_every_tool(self):
        from vault_inspection_tools import INSPECTION_DISPATCH
        for name in self._EXPECTED:
            self.assertIn(name, INSPECTION_DISPATCH)

    def test_inspection_functions_schema_contains_every_tool(self):
        from vault_inspection_tools import INSPECTION_FUNCTIONS
        names = [f["function"]["name"] for f in INSPECTION_FUNCTIONS]
        for n in self._EXPECTED:
            self.assertIn(n, names)

    def test_vault_knowledge_dispatch_merges_inspection(self):
                                                             
        from vault_knowledge_tools import VAULT_KNOWLEDGE_DISPATCH
        for n in self._EXPECTED:
            self.assertIn(n, VAULT_KNOWLEDGE_DISPATCH)

    def test_vault_knowledge_functions_includes_inspection_schemas(self):
        from vault_knowledge_tools import VAULT_KNOWLEDGE_FUNCTIONS
        names = [
            f["function"]["name"] for f in VAULT_KNOWLEDGE_FUNCTIONS
        ]
        for n in self._EXPECTED:
            self.assertIn(n, names)


class SystemPromptDirectsToolUseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("tools.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_prompt_lists_inspection_tools(self):
                                                               
                                                                
        for name in (
            "read_file_text",
            "read_image_with_vision",
            "search_extracted_text",
            "inspect_uploaded_file",
            "save_generated_credential_after_confirmation",
        ):
            with self.subTest(name=name):
                self.assertIn(name, self._src)

    def test_prompt_includes_step_by_step_recipe(self):
                                                               
        self.assertIn(
            "find me a photo ID card", self._src,
        )
        self.assertIn("STEP-BY-STEP", self._src)

    def test_prompt_forbids_faking_a_read(self):
        self.assertIn("NEVER FAKE A READ", self._src)

    def test_prompt_documents_confirmation_phrases_for_save(self):
                                                               
                                                                  
        self.assertIn("save it now", self._src)
        self.assertIn("generate and save", self._src)


class DirectAIToolsFlagWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_flag_is_read_in_chat_endpoint(self):
        self.assertIn("VAULTAI_DIRECT_AI_TOOLS_ENABLED", self._src)

    def test_flag_default_is_true(self):
                                                                 
                                                             
        self.assertIn(
            'os.getenv(\n            "VAULTAI_DIRECT_AI_TOOLS_ENABLED", '
            '"true",',
            self._src,
        )

    def test_legacy_router_runs_only_when_flag_off(self):
                                                                 
                                                              
        idx = self._src.find("detect_person_document_query")
        self.assertGreater(idx, -1)
        before = self._src[max(0, idx - 400): idx]
        self.assertIn("if not _direct_ai_tools_enabled", before)


if __name__ == "__main__":
    unittest.main()
