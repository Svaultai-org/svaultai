

from __future__ import annotations

import inspect
import json
import re
import unittest
from unittest.mock import patch

from main import (
    _FILE_LIST_CARD_CAP,
    _build_structured_asset_reply,
    _build_vault_file_list_envelope,
    _extension_group_label,
    _extract_folder_hint,
    _extract_literal_filename,
    _file_list_title,
    _format_file_list_reply,
    _format_no_match_reply,
    _has_literal_filename,
    _is_list_or_browse_phrasing,
    _list_all_folder_names,
    _serialize_file_for_list_card,
    _try_folder_aware_file_retrieval,
    search_files_with_filters,
)


def _row(
    *,
    id: str,
    file_name: str,
    relative_path: str | None,
    saved_name: str | None = None,
    content_type: str = "application/pdf",
    asset_type: str = "file",
    file_size: int = 1024,
) -> dict:
    return {
        "id": id,
        "file_name": file_name,
        "saved_name": saved_name or file_name,
        "relative_path": relative_path,
        "content_type": content_type,
        "asset_type": asset_type,
        "file_size": file_size,
        "detected_type": "file",
        "detected_service": "general",
        "autosaved_secret": False,
        "needs_naming": False,
        "created_at": None,
    }


class ExtractFolderHintTests(unittest.TestCase):
    KNOWN = ["My Life Backup", "Bank", "Banking", "Taxes", "Code",
             "Family", "Graduation"]

    def test_inside_bank_matches_bank(self):
        self.assertEqual(
            _extract_folder_hint(
                "send me statement.pdf inside Bank",
                known_folders=self.KNOWN,
            ),
            "Bank",
        )

    def test_in_my_life_backup_matches_full_phrase(self):
                                                                 
                                                                 
        self.assertEqual(
            _extract_folder_hint(
                "show me files in My Life Backup",
                known_folders=self.KNOWN,
            ),
            "My Life Backup",
        )

    def test_from_code_matches_code(self):
        self.assertEqual(
            _extract_folder_hint(
                "open app.py from Code",
                known_folders=self.KNOWN,
            ),
            "Code",
        )

    def test_under_family_matches_family(self):
        self.assertEqual(
            _extract_folder_hint(
                "show me photos under Family",
                known_folders=self.KNOWN,
            ),
            "Family",
        )

    def test_within_family_matches_family(self):
        self.assertEqual(
            _extract_folder_hint(
                "find pictures within Family",
                known_folders=self.KNOWN,
            ),
            "Family",
        )

    def test_in_my_taxes_with_filler_matches(self):
        self.assertEqual(
            _extract_folder_hint(
                "find documents in my Taxes folder",
                known_folders=self.KNOWN,
            ),
            "Taxes",
        )

    def test_inside_the_bank_with_filler_matches(self):
        self.assertEqual(
            _extract_folder_hint(
                "show me everything inside the Bank folder",
                known_folders=self.KNOWN,
            ),
            "Bank",
        )

    def test_case_insensitive(self):
        self.assertEqual(
            _extract_folder_hint(
                "show me FILES IN bank",
                known_folders=self.KNOWN,
            ),
            "Bank",
        )

    def test_bank_does_not_match_banking_when_both_exist(self):
                                                                    
                                                                     
        result = _extract_folder_hint(
            "send me statement.pdf inside Bank",
            known_folders=self.KNOWN,
        )
        self.assertEqual(result, "Bank")
        self.assertNotEqual(result, "Banking")

    def test_inside_banking_matches_banking(self):
        result = _extract_folder_hint(
            "show me everything inside Banking",
            known_folders=self.KNOWN,
        )
        self.assertEqual(result, "Banking")

    def test_no_preposition_returns_none(self):
                                                               
                                                              
        self.assertIsNone(
            _extract_folder_hint(
                "save my Bank login",
                known_folders=self.KNOWN,
            ),
        )

    def test_unknown_folder_returns_none(self):
        self.assertIsNone(
            _extract_folder_hint(
                "find files inside Photography",
                known_folders=self.KNOWN,
            ),
        )

    def test_empty_query_returns_none(self):
        self.assertIsNone(
            _extract_folder_hint("", known_folders=self.KNOWN),
        )
        self.assertIsNone(
            _extract_folder_hint(None, known_folders=self.KNOWN),
        )

    def test_empty_known_folders_returns_none(self):
        self.assertIsNone(
            _extract_folder_hint("show files inside Bank", known_folders=[]),
        )
        self.assertIsNone(
            _extract_folder_hint("show files inside Bank", known_folders=None),
        )


class IsListOrBrowsePhrasingTests(unittest.TestCase):
    def test_plural_type_token_triggers(self):
        for q in (
            "show me my photos",
            "find all videos",
            "list documents",
            "give me my pdfs",
            "show scripts",
        ):
            self.assertTrue(
                _is_list_or_browse_phrasing(q),
                f"phrase {q!r} should flag as browse",
            )

    def test_verb_plus_all_triggers(self):
        self.assertTrue(_is_list_or_browse_phrasing("show all my files"))
        self.assertTrue(_is_list_or_browse_phrasing("list every file"))

    def test_specific_filename_does_not_trigger(self):
        for q in (
            "send me statement.pdf",
            "open app.py",
            "find passport image",
        ):
            self.assertFalse(
                _is_list_or_browse_phrasing(q),
                f"single-file query {q!r} should not flag as browse",
            )

    def test_empty_input(self):
        self.assertFalse(_is_list_or_browse_phrasing(""))
        self.assertFalse(_is_list_or_browse_phrasing(None))


class LiteralFilenameTests(unittest.TestCase):
    def test_recognises_common_filenames(self):
        for q in (
            "send me statement.pdf",
            "open app.py",
            "find my_resume.docx",
            "show me family.jpg",
            "what's in archive-2024.zip",
        ):
            self.assertTrue(
                _has_literal_filename(q),
                f"{q!r} should contain a literal filename",
            )

    def test_does_not_false_positive_on_numbers(self):
        for q in (
            "what's $1.5M",
            "the rate is 1.0",
            "version 3.14 of the spec",
        ):
            self.assertFalse(
                _has_literal_filename(q),
                f"{q!r} should not look like a filename",
            )

    def test_extracts_first_filename(self):
        self.assertEqual(
            _extract_literal_filename(
                "send me statement.pdf and family.jpg",
            ),
            "statement.pdf",
        )

    def test_extracts_none_when_no_filename(self):
        self.assertIsNone(_extract_literal_filename("just chatting"))
        self.assertIsNone(_extract_literal_filename(""))
        self.assertIsNone(_extract_literal_filename(None))


class SearchFilesWithFiltersTests(unittest.TestCase):
    ROWS = [
        _row(id="1", file_name="statement.pdf",
             relative_path="Bank/statement.pdf"),
        _row(id="2", file_name="statement.pdf",
             relative_path="Taxes/statement.pdf"),
        _row(id="3", file_name="app.py",
             relative_path="Code/app.py", saved_name="App"),
        _row(id="4", file_name="family.jpg",
             relative_path="My Life Backup/Photos/Family/family.jpg",
             content_type="image/jpeg", asset_type="image"),
        _row(id="5", file_name="archive.zip",
             relative_path="Backups/archive.zip"),
        _row(id="6", file_name="loose.pdf",
             relative_path=None),               
        _row(id="7", file_name="bank-of-america.pdf",
             relative_path="Banking/bank-of-america.pdf"),
    ]

    def _patched(self):
        return patch("main.list_uploaded_files", return_value=self.ROWS)

    def test_folder_filter_constrains_to_folder(self):
        with self._patched():
            result = search_files_with_filters(
                "vault-1", folder_filter="Bank",
            )
        self.assertEqual([r["id"] for r in result], ["1"])

    def test_folder_filter_does_not_match_sibling_prefix(self):
                                                                
                                      
        with self._patched():
            result = search_files_with_filters(
                "vault-1", folder_filter="Bank",
            )
        ids = [r["id"] for r in result]
        self.assertIn("1", ids)
        self.assertNotIn("7", ids)

    def test_extension_filter_filters_by_extension(self):
        with self._patched():
            result = search_files_with_filters(
                "vault-1", extension_filter=("py",),
            )
        self.assertEqual([r["id"] for r in result], ["3"])

    def test_extension_filter_with_folder_combines(self):
        with self._patched():
            result = search_files_with_filters(
                "vault-1",
                folder_filter="Code",
                extension_filter=("py",),
            )
        self.assertEqual([r["id"] for r in result], ["3"])

    def test_name_query_substring_match(self):
        with self._patched():
            result = search_files_with_filters(
                "vault-1", name_query="statement",
            )
                                                                
        self.assertEqual({r["id"] for r in result}, {"1", "2"})

    def test_name_query_with_folder_returns_one(self):
        with self._patched():
            result = search_files_with_filters(
                "vault-1",
                folder_filter="Bank",
                name_query="statement",
            )
        self.assertEqual([r["id"] for r in result], ["1"])

    def test_no_filters_returns_all(self):
        with self._patched():
            result = search_files_with_filters("vault-1", limit=99)
        self.assertEqual(len(result), len(self.ROWS))

    def test_limit_respected(self):
        with self._patched():
            result = search_files_with_filters("vault-1", limit=3)
        self.assertEqual(len(result), 3)


class FormatNoMatchReplyTests(unittest.TestCase):
    def test_plain_no_match(self):
        self.assertEqual(
            _format_no_match_reply(None, None),
            "I couldn't find that file in your vault.",
        )

    def test_with_folder_only(self):
        self.assertEqual(
            _format_no_match_reply("Bank", None),
            "I couldn't find that file inside Bank.",
        )

    def test_with_extension_type_query(self):
        self.assertEqual(
            _format_no_match_reply(
                None, ("zip", "tar", "gz", "tgz", "7z", "rar"),
            ),
            "I couldn't find any zip files in your vault.",
        )

    def test_with_extension_inside_folder(self):
        self.assertEqual(
            _format_no_match_reply(
                "Code", ("py",),
            ),
            "I couldn't find any Python scripts inside Code.",
        )

    def test_with_requested_name(self):
        msg = _format_no_match_reply(
            "Bank", None, requested_name="statement.pdf",
        )
        self.assertIn("statement.pdf", msg)
        self.assertIn("Bank", msg)


class FormatFileListReplyTests(unittest.TestCase):
    def test_lists_paths_for_matches(self):
        rows = [
            {"file_name": "app.py", "saved_name": "App",
             "relative_path": "Code/app.py"},
            {"file_name": "lib.py", "saved_name": "Lib",
             "relative_path": "Code/lib.py"},
        ]
        result = _format_file_list_reply(
            rows, "Code", ("py",),
        )
        self.assertIn("I found 2 Python scripts inside Code:", result)
        self.assertIn("Code/app.py", result)
        self.assertIn("Code/lib.py", result)

    def test_caps_at_25_with_summary(self):
        from main import _EXTENSION_FILTER_GROUPS
        rows = [
            {"file_name": f"f{i}.zip", "saved_name": f"F{i}",
             "relative_path": f"Backups/f{i}.zip"}
            for i in range(40)
        ]
        result = _format_file_list_reply(
            rows, None, _EXTENSION_FILTER_GROUPS["zip"],
            query="show all zip files",
        )
        self.assertIn("I found 40 zip files:", result)
        self.assertIn("…and 15 more", result)


class ExtensionGroupLabelTests(unittest.TestCase):
    def test_python_label(self):
        from main import _EXTENSION_FILTER_GROUPS
        self.assertEqual(
            _extension_group_label(_EXTENSION_FILTER_GROUPS["python"]),
            "Python scripts",
        )

    def test_image_label(self):
        from main import _EXTENSION_FILTER_GROUPS
        self.assertEqual(
            _extension_group_label(_EXTENSION_FILTER_GROUPS["image"]),
            "images",
        )

    def test_unknown_group_falls_back_to_files(self):
        self.assertEqual(
            _extension_group_label(("xyz",)),
            "files",
        )

    def test_none_falls_back_to_files(self):
        self.assertEqual(_extension_group_label(None), "files")


class TryFolderAwareFileRetrievalTests(unittest.TestCase):
    ROWS = [
        _row(id="1", file_name="statement.pdf",
             relative_path="Bank/statement.pdf"),
        _row(id="2", file_name="statement.pdf",
             relative_path="Taxes/statement.pdf"),
        _row(id="3", file_name="app.py",
             relative_path="Code/app.py", saved_name="App"),
        _row(id="4", file_name="lib.py",
             relative_path="Code/lib.py", saved_name="Lib"),
        _row(id="5", file_name="family.jpg",
             relative_path="My Life Backup/Photos/Family/family.jpg",
             content_type="image/jpeg", asset_type="image"),
        _row(id="6", file_name="loose.pdf", relative_path=None),
    ]

    def _patched(self):
        return patch("main.list_uploaded_files", return_value=self.ROWS)

    def test_defers_when_neither_filter_applies(self):
                                                                 
                                                        
        with self._patched():
            result = _try_folder_aware_file_retrieval(
                vault_id="vault-1",
                decrypted_message="find statement",
            )
        self.assertIsNone(result)

    def test_single_match_returns_vault_file_envelope(self):
                                                                          
                               
        with self._patched():
            result = _try_folder_aware_file_retrieval(
                vault_id="vault-1",
                decrypted_message="send me statement.pdf inside Bank",
            )
        self.assertIsNotNone(result)
        payload = json.loads(result)
        self.assertEqual(payload["type"], "vault_file")
        self.assertEqual(payload["file_id"], "1")
        self.assertEqual(
            payload["relative_path"], "Bank/statement.pdf",
        )

    def test_specific_name_with_multiple_matches_disambiguates(self):
                                                                     
                                                                    
        with self._patched():
            result = _try_folder_aware_file_retrieval(
                vault_id="vault-1",
                decrypted_message="send me statement.pdf",
            )
        self.assertIsNotNone(result)
        payload = json.loads(result)
        self.assertEqual(payload["type"], "vault_file_list")
        self.assertEqual(payload["requested_name"], "statement.pdf")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["total_count"], 2)
                                                                  
                                             
        paths = {f["relative_path"] for f in payload["files"]}
        self.assertEqual(
            paths, {"Bank/statement.pdf", "Taxes/statement.pdf"},
        )
                                                                  
                                                            
        self.assertIn("I found 2 files", payload["message"])
        self.assertIn("statement.pdf", payload["message"])

    def test_type_wide_query_returns_list(self):
                                                                 
                                                     
        with self._patched():
            result = _try_folder_aware_file_retrieval(
                vault_id="vault-1",
                decrypted_message="show all Python scripts",
            )
        self.assertIsNotNone(result)
        payload = json.loads(result)
        self.assertEqual(payload["type"], "vault_file_list")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["total_count"], 2)
                                                                  
        self.assertEqual(payload["title"], "Python scripts")
                                                    
        paths = {f["relative_path"] for f in payload["files"]}
        self.assertEqual(paths, {"Code/app.py", "Code/lib.py"})

    def test_folder_browse_query_returns_list(self):
                                                                       
                                              
        with self._patched():
            result = _try_folder_aware_file_retrieval(
                vault_id="vault-1",
                decrypted_message="show me files inside Code",
            )
        self.assertIsNotNone(result)
        payload = json.loads(result)
        self.assertEqual(payload["type"], "vault_file_list")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["title"], "Files inside Code")

    def test_type_wide_no_match_friendly_message(self):
                                              
        with self._patched():
            result = _try_folder_aware_file_retrieval(
                vault_id="vault-1",
                decrypted_message="show all zip files",
            )
        self.assertIsNotNone(result)
        self.assertEqual(
            result,
            "I couldn't find any zip files in your vault.",
        )

    def test_folder_specific_no_match_mentions_folder(self):
        with self._patched():
            result = _try_folder_aware_file_retrieval(
                vault_id="vault-1",
                decrypted_message="open passport.pdf inside Code",
            )
        self.assertIsNotNone(result)
        self.assertIn("Code", result)
        self.assertIn("passport.pdf", result)
        self.assertIn("couldn't find", result)

    def test_photos_inside_family_combined_filter(self):
                                                                   
                                                                    
        with self._patched():
            result = _try_folder_aware_file_retrieval(
                vault_id="vault-1",
                decrypted_message=(
                    "show all photos in Family folder"
                ),
            )
        self.assertIsNotNone(result)
        payload = json.loads(result)
                                                                  
                                                           
        self.assertEqual(payload["type"], "vault_file_list")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["title"], "Images inside Family")
        self.assertEqual(
            payload["files"][0]["file_name"], "family.jpg",
        )
        self.assertEqual(
            payload["files"][0]["asset_type"], "image",
        )


class BuildStructuredAssetReplyTests(unittest.TestCase):
    def test_includes_relative_path_when_present(self):
        result = _build_structured_asset_reply(
            {
                "id": "f1",
                "file_name": "statement.pdf",
                "saved_name": "April Statement",
                "content_type": "application/pdf",
                "asset_type": "file",
                "relative_path": "Bank/statement.pdf",
            },
            "statement.pdf",
        )
        payload = json.loads(result)
        self.assertEqual(
            payload["relative_path"], "Bank/statement.pdf",
        )

    def test_omits_relative_path_when_null(self):
        result = _build_structured_asset_reply(
            {
                "id": "f1",
                "file_name": "loose.pdf",
                "content_type": "application/pdf",
                "asset_type": "file",
                "relative_path": None,
            },
            "loose.pdf",
        )
        payload = json.loads(result)
        self.assertNotIn("relative_path", payload)

    def test_omits_relative_path_when_missing_key(self):
        result = _build_structured_asset_reply(
            {
                "id": "f1",
                "file_name": "loose.pdf",
                "content_type": "application/pdf",
                "asset_type": "file",
            },
            "loose.pdf",
        )
        payload = json.loads(result)
        self.assertNotIn("relative_path", payload)


class ChatDispatchWiringTests(unittest.TestCase):


    def test_dispatch_calls_folder_aware_before_retrieve_saved_asset(
        self,
    ):
        import main
                                                                  
                                             
        src = inspect.getsource(main.chat_endpoint)
        folder_idx = src.find("_try_folder_aware_file_retrieval(")
        legacy_idx = src.find("retrieve_saved_asset(vault_id,")
        self.assertGreater(
            folder_idx, -1,
            "chat_endpoint must call _try_folder_aware_file_retrieval",
        )
        self.assertGreater(
            legacy_idx, -1,
            "chat_endpoint must retain the legacy retrieve_saved_asset",
        )
        self.assertLess(
            folder_idx, legacy_idx,
            "folder-aware retrieval must run BEFORE the legacy "
            "name-based handler so structured queries hit the new "
            "path first",
        )


class ListAllFolderNamesTests(unittest.TestCase):
    def test_extracts_distinct_folder_names_excluding_filenames(self):
        rows = [
            _row(id="1", file_name="a.pdf",
                 relative_path="My Life Backup/Bank/a.pdf"),
            _row(id="2", file_name="b.pdf",
                 relative_path="My Life Backup/Bank/b.pdf"),
            _row(id="3", file_name="c.jpg",
                 relative_path="My Life Backup/Photos/c.jpg"),
            _row(id="4", file_name="d.pdf", relative_path=None),
        ]
        with patch("main.list_uploaded_files", return_value=rows):
            result = _list_all_folder_names("vault-1")
                                                                    
                                                             
        self.assertEqual(
            set(result),
            {"My Life Backup", "Bank", "Photos"},
        )

    def test_sorted_longest_first(self):
        rows = [
            _row(id="1", file_name="x.pdf",
                 relative_path="A/Long Folder Name/x.pdf"),
        ]
        with patch("main.list_uploaded_files", return_value=rows):
            result = _list_all_folder_names("vault-1")
                                                             
                                                
        self.assertEqual(result[0], "Long Folder Name")
        self.assertEqual(result[1], "A")

    def test_empty_vault_returns_empty_list(self):
        with patch("main.list_uploaded_files", return_value=[]):
            result = _list_all_folder_names("vault-1")
        self.assertEqual(result, [])


class ScriptsAreNeverExecutedTests(unittest.TestCase):


    DANGEROUS_PATTERNS = (
        r"\bexec\s*\(",
        r"\beval\s*\(",
        r"\bsubprocess\.run\s*\(",
        r"\bsubprocess\.Popen\s*\(",
        r"\bsubprocess\.call\s*\(",
        r"\bos\.system\s*\(",
        r"\bos\.popen\s*\(",
        r"\bcompile\s*\(",
    )

    def _strip_docstring(self, src: str) -> str:
                                                                  
                                                       
        for marker in ('"""', "'''"):
            start = src.find(marker)
            if start == -1:
                continue
            end = src.find(marker, start + 3)
            if end == -1:
                continue
            return src[:start] + src[end + 3:]
        return src

    def _assert_no_dangerous(self, src, where):
        for pattern in self.DANGEROUS_PATTERNS:
            self.assertIsNone(
                re.search(pattern, src),
                f"{where} body must not match {pattern!r}",
            )

    def test_orchestrator_does_not_execute(self):
        src = self._strip_docstring(
            inspect.getsource(_try_folder_aware_file_retrieval),
        )
        self._assert_no_dangerous(
            src, "_try_folder_aware_file_retrieval",
        )

    def test_search_helper_does_not_execute(self):
        src = self._strip_docstring(
            inspect.getsource(search_files_with_filters),
        )
        self._assert_no_dangerous(
            src, "search_files_with_filters",
        )

    def test_file_list_envelope_builder_does_not_execute(self):
                                                                
                                                                     
        src = self._strip_docstring(
            inspect.getsource(_build_vault_file_list_envelope),
        )
        self._assert_no_dangerous(
            src, "_build_vault_file_list_envelope",
        )


class SerializeFileForListCardTests(unittest.TestCase):


    def test_includes_required_render_fields(self):
        row = _row(
            id="f1", file_name="statement.pdf",
            saved_name="Bank Statement",
            relative_path="Bank/statement.pdf",
            content_type="application/pdf",
            asset_type="file",
            file_size=12345,
        )
        out = _serialize_file_for_list_card(row)
        self.assertEqual(out["file_id"], "f1")
        self.assertEqual(out["file_name"], "statement.pdf")
        self.assertEqual(out["saved_name"], "Bank Statement")
        self.assertEqual(out["mime_type"], "application/pdf")
        self.assertEqual(out["asset_type"], "file")
        self.assertEqual(out["relative_path"], "Bank/statement.pdf")
        self.assertEqual(out["size_bytes"], 12345)

    def test_omits_relative_path_when_null(self):
        row = _row(id="f1", file_name="loose.pdf", relative_path=None)
        out = _serialize_file_for_list_card(row)
        self.assertNotIn("relative_path", out)

    def test_defaults_asset_type_to_file(self):
                                                                    
        row = {
            "id": "f1",
            "file_name": "x.pdf",
            "saved_name": "X",
            "content_type": "application/pdf",
            "asset_type": None,
            "file_size": 100,
            "relative_path": None,
        }
        out = _serialize_file_for_list_card(row)
        self.assertEqual(out["asset_type"], "file")

    def test_does_not_leak_internal_state(self):
                                                                    
                                                  
        row = _row(
            id="f1", file_name="x.pdf", relative_path=None,
        )
                                                            
        row["detected_service"] = "stripe"
        row["autosaved_secret"] = True
        row["encryption_key"] = "should-never-leak"
        out = _serialize_file_for_list_card(row)
        self.assertNotIn("detected_service", out)
        self.assertNotIn("autosaved_secret", out)
        self.assertNotIn("encryption_key", out)


class BuildVaultFileListEnvelopeTests(unittest.TestCase):


    def _rows(self, n: int, prefix: str = "Bank") -> list[dict]:
        return [
            _row(
                id=f"f{i}",
                file_name=f"file{i}.pdf",
                relative_path=f"{prefix}/file{i}.pdf",
            )
            for i in range(n)
        ]

    def test_envelope_has_correct_type_and_title(self):
        env = json.loads(
            _build_vault_file_list_envelope(
                self._rows(3),
                "Files inside Bank",
                message="I found 3 files inside Bank.",
            )
        )
        self.assertEqual(env["type"], "vault_file_list")
        self.assertEqual(env["title"], "Files inside Bank")
        self.assertEqual(
            env["message"], "I found 3 files inside Bank.",
        )
        self.assertEqual(env["count"], 3)
        self.assertEqual(env["total_count"], 3)
        self.assertEqual(len(env["files"]), 3)
                                                    
        self.assertNotIn("more_count", env)
                                                                   
        self.assertNotIn("requested_name", env)

    def test_caps_at_25_with_more_count(self):
                                                             
        env = json.loads(
            _build_vault_file_list_envelope(
                self._rows(50), "Files inside Bank",
            )
        )
        self.assertEqual(env["count"], _FILE_LIST_CARD_CAP)
        self.assertEqual(env["total_count"], 50)
        self.assertEqual(env["more_count"], 25)
        self.assertEqual(len(env["files"]), 25)

    def test_exactly_25_rows_has_no_more_count(self):
        env = json.loads(
            _build_vault_file_list_envelope(
                self._rows(_FILE_LIST_CARD_CAP),
                "Files inside Bank",
            )
        )
        self.assertEqual(env["count"], 25)
        self.assertEqual(env["total_count"], 25)
        self.assertNotIn("more_count", env)

    def test_requested_name_surfaces_when_provided(self):
        env = json.loads(
            _build_vault_file_list_envelope(
                self._rows(2),
                'Files named "statement.pdf"',
                requested_name="statement.pdf",
            )
        )
        self.assertEqual(env["requested_name"], "statement.pdf")

    def test_each_file_row_carries_render_fields(self):
        rows = [
            _row(
                id="f1", file_name="app.py", saved_name="App",
                relative_path="Code/app.py",
                content_type="text/x-python", asset_type="file",
            ),
        ]
        env = json.loads(
            _build_vault_file_list_envelope(rows, "Code")
        )
        f = env["files"][0]
        for required_key in (
            "file_id", "file_name", "saved_name",
            "mime_type", "asset_type", "relative_path",
        ):
            self.assertIn(required_key, f)


class FileListTitleTests(unittest.TestCase):
    def test_folder_only(self):
        self.assertEqual(
            _file_list_title("Bank", None),
            "Files inside Bank",
        )

    def test_extension_only(self):
        from main import _EXTENSION_FILTER_GROUPS
        self.assertEqual(
            _file_list_title(
                None, _EXTENSION_FILTER_GROUPS["python"],
            ),
            "Python scripts",
        )

    def test_combined(self):
        from main import _EXTENSION_FILTER_GROUPS
        self.assertEqual(
            _file_list_title(
                "Code", _EXTENSION_FILTER_GROUPS["python"],
            ),
            "Python scripts inside Code",
        )

    def test_neither(self):
        self.assertEqual(_file_list_title(None, None), "Files")


class OrchestratorEnvelopeIntegrationTests(unittest.TestCase):


    def _patched_rows(self, n: int):
        rows = [
            _row(
                id=f"f{i}",
                file_name=f"doc{i}.pdf",
                relative_path=f"My Life Backup/doc{i}.pdf",
            )
            for i in range(n)
        ]
        return patch("main.list_uploaded_files", return_value=rows)

    def test_folder_browse_emits_envelope_with_more_count_when_capped(
        self,
    ):
                                                                        
        with self._patched_rows(60):
            reply = _try_folder_aware_file_retrieval(
                vault_id="v",
                decrypted_message=(
                    "show me all files inside My Life Backup"
                ),
            )
        self.assertIsNotNone(reply)
        env = json.loads(reply)
        self.assertEqual(env["type"], "vault_file_list")
        self.assertEqual(env["count"], _FILE_LIST_CARD_CAP)
        self.assertEqual(env["total_count"], 60)
        self.assertEqual(env["more_count"], 35)

    def test_single_match_still_emits_vault_file_not_list(self):
                                                                 
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                relative_path="Bank/statement.pdf",
            ),
        ]
        with patch("main.list_uploaded_files", return_value=rows):
            reply = _try_folder_aware_file_retrieval(
                vault_id="v",
                decrypted_message="send me statement.pdf inside Bank",
            )
        self.assertIsNotNone(reply)
        env = json.loads(reply)
        self.assertEqual(env["type"], "vault_file")

    def test_no_match_stays_plain_text(self):
                                                                     
                                                       
        with patch("main.list_uploaded_files", return_value=[]):
            reply = _try_folder_aware_file_retrieval(
                vault_id="v",
                decrypted_message="open passport.pdf inside Code",
            )
                                                                      
                                                                
        self.assertTrue(
            reply is None or "couldn't find" in reply,
            reply,
        )


if __name__ == "__main__":
    unittest.main()
