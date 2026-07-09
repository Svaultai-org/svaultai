

from __future__ import annotations

import json
import unittest
from unittest import mock

from vault_knowledge_tools import (
    MAX_FILES_RETURNED,
    MAX_RECENT_FILES,
    MAX_SEARCH_HITS,
    MAX_SNIPPET_CHARS,
    VAULT_KNOWLEDGE_DISPATCH,
    VAULT_KNOWLEDGE_FUNCTIONS,
    _classify_file_kind,
    _key_ok,
    get_vault_overview,
    list_vault_files,
    search_vault_content,
)


class ToolSurfaceTests(unittest.TestCase):
    def test_knowledge_tools_exported(self):
                                                                 
                                                               
        names = {
            f["function"]["name"] for f in VAULT_KNOWLEDGE_FUNCTIONS
        }
                                           
        for required in (
            "get_vault_intelligence",
            "get_vault_overview",
            "list_vault_files",
            "search_vault_content",
        ):
            self.assertIn(required, names)
                                                                  
        for required in (
            "read_file_text",
            "read_image_with_vision",
            "search_extracted_text",
            "inspect_uploaded_file",
            "get_file_metadata",
            "list_saved_credentials",
            "get_credential_metadata",
            "save_generated_credential_after_confirmation",
        ):
            self.assertIn(required, names)

    def test_schemas_do_not_require_vault_id_or_key(self):
                                                             
                                         
        for fn in VAULT_KNOWLEDGE_FUNCTIONS:
            params = fn["function"]["parameters"]
            self.assertNotIn(
                "vault_id", params.get("properties") or {},
            )
            self.assertNotIn(
                "key", params.get("properties") or {},
            )

    def test_dispatch_map_matches_schema_names(self):
        names = {
            f["function"]["name"] for f in VAULT_KNOWLEDGE_FUNCTIONS
        }
        self.assertEqual(set(VAULT_KNOWLEDGE_DISPATCH.keys()), names)


class KeyGateTests(unittest.TestCase):
    def test_key_ok_accepts_32_bytes(self):
        self.assertTrue(_key_ok(b"\x00" * 32))

    def test_key_ok_rejects_short_key(self):
        self.assertFalse(_key_ok(b"\x00" * 16))

    def test_key_ok_rejects_string_key(self):
        self.assertFalse(_key_ok("a" * 32))

    def test_key_ok_rejects_none(self):
        self.assertFalse(_key_ok(None))

    def test_search_vault_content_refuses_bad_key(self):
                                                           
                                                               
        out = search_vault_content(
            vault_id="v1", key=b"too-short", query="anything",
        )
        self.assertEqual(json.loads(out), {"error": "vault_locked"})

    def test_search_vault_content_refuses_empty_query(self):
        out = search_vault_content(
            vault_id="v1", key=b"\x00" * 32, query="   ",
        )
        self.assertEqual(json.loads(out), {"error": "empty_query"})


class FileKindClassifierTests(unittest.TestCase):
    def test_asset_type_wins(self):
        self.assertEqual(
            _classify_file_kind({"asset_type": "image"}),
            "image",
        )

    def test_mime_image(self):
        self.assertEqual(
            _classify_file_kind({"content_type": "image/png"}),
            "image",
        )

    def test_pdf_mime(self):
        self.assertEqual(
            _classify_file_kind({"content_type": "application/pdf"}),
            "document",
        )

    def test_video_extension(self):
        self.assertEqual(
            _classify_file_kind({"file_name": "vacation.mp4"}),
            "video",
        )

    def test_archive_extension(self):
        self.assertEqual(
            _classify_file_kind({"file_name": "backup.tar.gz"}),
            "archive",
        )

    def test_unknown_falls_to_other(self):
        self.assertEqual(
            _classify_file_kind({"file_name": "weird.xyz"}),
            "other",
        )


class ListVaultFilesTests(unittest.TestCase):
    def _rows(self):
        return [
            {
                "id":             "f1",
                "file_name":      "contract.pdf",
                "saved_name":     "contract.pdf",
                "content_type":   "application/pdf",
                "asset_type":     "document",
                "file_size":      120_000,
                "relative_path":  "/Legal/",
                "created_at":     None,
            },
            {
                "id":             "f2",
                "file_name":      "vacation.mp4",
                "saved_name":     "vacation.mp4",
                "content_type":   "video/mp4",
                "asset_type":     "video",
                "file_size":      50_000_000,
                "relative_path":  "/Travel/",
                "created_at":     None,
            },
            {
                "id":             "f3",
                "file_name":      "wells_fargo_statement.pdf",
                "saved_name":     "wells_fargo_statement.pdf",
                "content_type":   "application/pdf",
                "asset_type":     "document",
                "file_size":      80_000,
                "relative_path":  "/Banking/",
                "created_at":     None,
            },
        ]

    def test_returns_all_files_when_no_filter(self):
        with mock.patch(
            "main.list_uploaded_files",
            return_value=self._rows(),
        ):
            out = json.loads(list_vault_files(
                vault_id="v1", key=b"\x00" * 32,
            ))
        self.assertEqual(out["returned"], 3)
        self.assertEqual(out["total_in_vault"], 3)
        self.assertEqual(len(out["files"]), 3)

    def test_kind_filter_restricts(self):
        with mock.patch(
            "main.list_uploaded_files",
            return_value=self._rows(),
        ):
            out = json.loads(list_vault_files(
                vault_id="v1", key=b"\x00" * 32, kind="video",
            ))
        self.assertEqual(out["returned"], 1)
        self.assertEqual(out["files"][0]["kind"], "video")

    def test_unknown_kind_filter_falls_through(self):
        with mock.patch(
            "main.list_uploaded_files",
            return_value=self._rows(),
        ):
            out = json.loads(list_vault_files(
                vault_id="v1", key=b"\x00" * 32, kind="zzzunknown",
            ))
                                                      
        self.assertEqual(out["returned"], 3)

    def test_query_matches_filename_substring(self):
        with mock.patch(
            "main.list_uploaded_files",
            return_value=self._rows(),
        ):
            out = json.loads(list_vault_files(
                vault_id="v1", key=b"\x00" * 32, query="Wells",
            ))
        self.assertEqual(out["returned"], 1)
        self.assertIn("wells_fargo", out["files"][0]["file_name"])

    def test_query_matches_folder_substring(self):
        with mock.patch(
            "main.list_uploaded_files",
            return_value=self._rows(),
        ):
            out = json.loads(list_vault_files(
                vault_id="v1", key=b"\x00" * 32, query="banking",
            ))
        self.assertEqual(out["returned"], 1)
        self.assertEqual(out["files"][0]["folder"], "/Banking/")

    def test_returned_rows_have_no_encrypted_columns(self):
        with mock.patch(
            "main.list_uploaded_files",
            return_value=self._rows(),
        ):
            out = json.loads(list_vault_files(
                vault_id="v1", key=b"\x00" * 32,
            ))
        for row in out["files"]:
            for k in row.keys():
                self.assertFalse(
                    k.startswith("encrypted_"),
                    f"row exposes encrypted column {k!r}",
                )
                                                              
            self.assertNotIn("extracted_text", row)
            self.assertNotIn("encrypted_chunk_text", row)


class GetVaultOverviewTests(unittest.TestCase):
    def _rows(self):
                                                     
        return [
            {"asset_type": "document", "content_type": "application/pdf",
             "saved_name": "a.pdf", "file_name": "a.pdf",
             "created_at": None},
            {"asset_type": "document", "content_type": "application/pdf",
             "saved_name": "b.pdf", "file_name": "b.pdf",
             "created_at": None},
            {"asset_type": "document", "content_type": "application/pdf",
             "saved_name": "c.pdf", "file_name": "c.pdf",
             "created_at": None},
            {"asset_type": "video", "content_type": "video/mp4",
             "saved_name": "v.mp4", "file_name": "v.mp4",
             "created_at": None},
            {"asset_type": "image", "content_type": "image/jpeg",
             "saved_name": "i.jpg", "file_name": "i.jpg",
             "created_at": None},
            {"asset_type": "audio", "content_type": "audio/mp3",
             "saved_name": "x.mp3", "file_name": "x.mp3",
             "created_at": None},
        ]

    def test_overview_aggregates_kinds(self):
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {"n": 4}
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        with mock.patch(
            "main.list_uploaded_files",
            return_value=self._rows(),
        ), mock.patch(
            "main.get_db", return_value=fake_conn,
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 6, "analyzed": 4, "pending": 1,
                "processing": 1, "failed": 0, "unsupported": 0,
            },
        ):
            out = json.loads(get_vault_overview(
                vault_id="v1", key=b"\x00" * 32,
            ))
        self.assertEqual(out["total_files"], 6)
        self.assertEqual(out["files_by_kind"]["document"], 3)
        self.assertEqual(out["files_by_kind"]["video"], 1)
        self.assertEqual(out["files_by_kind"]["image"], 1)
        self.assertEqual(out["files_by_kind"]["audio"], 1)
        self.assertEqual(out["saved_credential_services_count"], 4)
        self.assertEqual(out["analysis_coverage"]["analyzed"], 4)
        self.assertFalse(out["analysis_coverage"]["is_complete"])

    def test_overview_never_leaks_secret_columns(self):
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {"n": 0}
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        with mock.patch(
            "main.list_uploaded_files",
            return_value=[{
                "asset_type": "document",
                "saved_name": "x.pdf", "file_name": "x.pdf",
                                                            
                                   
                "extracted_text": "PASSWORD-DO-NOT-LEAK",
                "encrypted_chunk_text": "DO-NOT-LEAK",
                "content_sha256": "DO-NOT-LEAK-EITHER",
                "created_at": None,
            }],
        ), mock.patch(
            "main.get_db", return_value=fake_conn,
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={"total": 1, "analyzed": 1, "pending": 0,
                          "processing": 0, "failed": 0,
                          "unsupported": 0},
        ):
            out = get_vault_overview(
                vault_id="v1", key=b"\x00" * 32,
            )
        self.assertNotIn("PASSWORD-DO-NOT-LEAK", out)
        self.assertNotIn("DO-NOT-LEAK", out)
        self.assertNotIn("extracted_text", out)
        self.assertNotIn("encrypted_chunk_text", out)


class SearchVaultContentRedactionTests(unittest.TestCase):
    def test_password_label_in_snippet_is_masked(self):
                                                   
        fake_cur = mock.MagicMock()
        fake_cur.fetchall.return_value = [{
            "file_id":              "f1",
            "encrypted_chunk_text": "BLOB",
            "file_name":            "notes.txt",
            "saved_name":           "notes.txt",
            "relative_path":        "/Notes/",
        }]
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur

        with mock.patch(
            "main.get_db", return_value=fake_conn,
        ), mock.patch(
            "vault_core.decrypt_message",
            return_value=(
                "Some note about my account. "
                "password: REAL-SECRET-DO-NOT-LEAK "
                "And more text after."
            ),
        ):
            out = json.loads(search_vault_content(
                vault_id="v1", key=b"\x00" * 32, query="account",
            ))
        self.assertEqual(out["returned"], 1)
        snippet = out["hits"][0]["snippet"]
        self.assertNotIn("REAL-SECRET-DO-NOT-LEAK", snippet)
        self.assertIn("password=***", snippet)

    def test_snippet_cap_enforced(self):
        long_text = "alpha " * 1000               
        fake_cur = mock.MagicMock()
        fake_cur.fetchall.return_value = [{
            "file_id":              "f1",
            "encrypted_chunk_text": "BLOB",
            "file_name":            "essay.txt",
            "saved_name":           "essay.txt",
            "relative_path":        "/",
        }]
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur

        with mock.patch(
            "main.get_db", return_value=fake_conn,
        ), mock.patch(
            "vault_core.decrypt_message",
            return_value=long_text,
        ):
            out = json.loads(search_vault_content(
                vault_id="v1", key=b"\x00" * 32, query="alpha",
            ))
        snippet = out["hits"][0]["snippet"]
                                                   
        self.assertLessEqual(len(snippet), MAX_SNIPPET_CHARS + 1)


class ChatPathSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("main.py", "r", encoding="utf-8") as f:
            cls._main_src = f.read()
        with open("tools.py", "r", encoding="utf-8") as f:
            cls._tools_src = f.read()

    def test_tools_concatenates_knowledge_functions(self):
        self.assertIn(
            "VAULT_KNOWLEDGE_FUNCTIONS",
            self._tools_src,
        )
        self.assertIn(
            "VAULT_FUNCTIONS = _BASE_VAULT_FUNCTIONS + list(_VK_FNS)",
            self._tools_src,
        )

    def test_handle_tool_call_imports_knowledge_dispatch(self):
        self.assertIn(
            "from vault_knowledge_tools import VAULT_KNOWLEDGE_DISPATCH",
            self._main_src,
        )

    def test_handle_tool_call_strips_client_supplied_credentials(self):
        self.assertIn(
            "safe_args.pop(\"vault_id\", None)",
            self._main_src,
        )
        self.assertIn(
            "safe_args.pop(\"key\", None)",
            self._main_src,
        )

    def test_system_prompt_mentions_each_new_tool(self):
        from tools import SYSTEM_PROMPT
                                                                   
                                                                 
        self.assertIn("list_vault_files", SYSTEM_PROMPT)
        self.assertIn("search_vault_content", SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
