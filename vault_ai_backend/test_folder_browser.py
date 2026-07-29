

from __future__ import annotations

import unittest
from unittest.mock import patch

import main
from main import (
    _extract_extension_filter,
    _file_matches_extensions,
    _format_disambiguation_reply,
    _is_under_folder,
    build_folder_tree,
)


def _row(
    *,
    id: str,
    file_name: str,
    relative_path: str | None,
    saved_name: str | None = None,
    file_size: int = 1024,
) -> dict:
    return {
        "id": id,
        "file_name": file_name,
        "saved_name": saved_name or file_name,
        "relative_path": relative_path,
        "content_type": "application/pdf",
        "file_size": file_size,
        "detected_type": "file",
        "detected_service": "general",
        "autosaved_secret": False,
        "asset_type": "file",
        "needs_naming": False,
        "created_at": None,
    }


class BuildFolderTreeTests(unittest.TestCase):


    @staticmethod
    def _patched(rows):
        return patch("main.list_uploaded_files", return_value=rows)

    def test_root_view_separates_flat_files_from_folders(self):
        rows = [
            _row(id="1", file_name="loose.pdf", relative_path=None),
            _row(
                id="2",
                file_name="family.jpg",
                relative_path="My Life Backup/Photos/family.jpg",
            ),
            _row(
                id="3",
                file_name="statement.pdf",
                relative_path="My Life Backup/Bank/statement.pdf",
            ),
        ]
        with self._patched(rows):
            tree = build_folder_tree(vault_id="vault-1")

        self.assertEqual(tree["path"], "")
        self.assertEqual(tree["breadcrumbs"], [])
                               
        self.assertEqual(
            [f["name"] for f in tree["folders"]],
            ["My Life Backup"],
        )
                                                 
        self.assertEqual(tree["folders"][0]["file_count"], 2)
                                      
        self.assertEqual(len(tree["files"]), 1)
        self.assertEqual(tree["files"][0]["file_name"], "loose.pdf")

    def test_folder_tree_includes_ciphertext_metadata_for_client_decrypt(self):
        rows = [
            {
                **_row(
                    id="1",
                    file_name="Unnamed file",
                    saved_name=None,
                    relative_path=None,
                ),
                "saved_name_ciphertext": b"ciphertext",
            },
        ]
        with patch("main.list_uploaded_files", return_value=rows) as mocked:
            tree = build_folder_tree(vault_id="vault-1")

        mocked.assert_called_once_with("vault-1", include_ciphertext=True)
        self.assertEqual(len(tree["files"]), 1)
        self.assertEqual(
            tree["files"][0]["saved_name_ciphertext"],
            "Y2lwaGVydGV4dA",
        )

    def test_nested_view_returns_subfolders_and_files_at_path(self):
        rows = [
            _row(
                id="1",
                file_name="family.jpg",
                relative_path="My Life Backup/Photos/family.jpg",
            ),
            _row(
                id="2",
                file_name="dad.jpg",
                relative_path="My Life Backup/Photos/Family/dad.jpg",
            ),
            _row(
                id="3",
                file_name="statement.pdf",
                relative_path="My Life Backup/Bank/statement.pdf",
            ),
        ]
        with self._patched(rows):
            tree = build_folder_tree(
                vault_id="vault-1",
                path="My Life Backup",
            )

        self.assertEqual(tree["path"], "My Life Backup")
        self.assertEqual(tree["breadcrumbs"], ["My Life Backup"])
                                          
        self.assertEqual(
            [f["name"] for f in tree["folders"]],
            ["Bank", "Photos"],
        )
                                                                  
                     
        self.assertEqual(tree["files"], [])

    def test_deep_view_returns_files_at_exact_path(self):
        rows = [
            _row(
                id="1",
                file_name="family.jpg",
                relative_path="My Life Backup/Photos/family.jpg",
            ),
            _row(
                id="2",
                file_name="dad.jpg",
                relative_path="My Life Backup/Photos/Family/dad.jpg",
            ),
            _row(
                id="3",
                file_name="mom.jpg",
                relative_path="My Life Backup/Photos/family-portraits/mom.jpg",
            ),
        ]
        with self._patched(rows):
            tree = build_folder_tree(
                vault_id="vault-1",
                path="My Life Backup/Photos",
            )

        self.assertEqual(tree["path"], "My Life Backup/Photos")
        self.assertEqual(
            tree["breadcrumbs"],
            ["My Life Backup", "Photos"],
        )
        self.assertEqual(
            sorted(f["name"] for f in tree["folders"]),
            ["Family", "family-portraits"],
        )
                                                            
        self.assertEqual(len(tree["files"]), 1)
        self.assertEqual(
            tree["files"][0]["file_name"], "family.jpg",
        )

    def test_root_view_with_no_files_returns_empty(self):
        with self._patched([]):
            tree = build_folder_tree(vault_id="vault-1")
        self.assertEqual(tree["folders"], [])
        self.assertEqual(tree["files"], [])

    def test_nested_view_with_no_matches_returns_empty(self):
        rows = [
            _row(
                id="1",
                file_name="x.pdf",
                relative_path="Other/x.pdf",
            ),
        ]
        with self._patched(rows):
            tree = build_folder_tree(
                vault_id="vault-1",
                path="Missing",
            )
        self.assertEqual(tree["folders"], [])
        self.assertEqual(tree["files"], [])

    def test_case_insensitive_prefix_match(self):
                                                                     
                                                               
        rows = [
            _row(
                id="1",
                file_name="x.pdf",
                relative_path="My Life Backup/Bank/x.pdf",
            ),
        ]
        with self._patched(rows):
            tree = build_folder_tree(
                vault_id="vault-1",
                path="my life backup",
            )
        self.assertEqual(len(tree["files"]), 0)
        self.assertEqual([f["name"] for f in tree["folders"]], ["Bank"])

    def test_unsafe_path_folds_to_root(self):
                                                                    
                                                               
        rows = [
            _row(id="1", file_name="loose.pdf", relative_path=None),
        ]
        with self._patched(rows):
            tree = build_folder_tree(
                vault_id="vault-1",
                path="../escape",
            )
        self.assertEqual(tree["path"], "")
        self.assertEqual(tree["breadcrumbs"], [])
        self.assertEqual(len(tree["files"]), 1)

    def test_files_at_path_serialise_with_relative_path(self):
                                                                      
                                                             
        rows = [
            _row(
                id="1",
                file_name="x.pdf",
                relative_path="Bank/x.pdf",
            ),
        ]
        with self._patched(rows):
            tree = build_folder_tree(
                vault_id="vault-1",
                path="Bank",
            )
        self.assertEqual(len(tree["files"]), 1)
        self.assertEqual(
            tree["files"][0]["relative_path"], "Bank/x.pdf",
        )

    def test_root_view_with_single_segment_relative_path(self):
                                                                 
                                                               
        rows = [
            _row(id="1", file_name="x.pdf", relative_path="x.pdf"),
        ]
        with self._patched(rows):
            tree = build_folder_tree(vault_id="vault-1")
        self.assertEqual(tree["folders"], [])
        self.assertEqual(len(tree["files"]), 1)

    def test_folder_with_many_files_aggregates_count_correctly(self):
        rows = [
            _row(
                id=f"f{i}",
                file_name=f"file_{i}.pdf",
                relative_path=f"Bank/file_{i}.pdf",
            )
            for i in range(50)
        ]
        with self._patched(rows):
            tree = build_folder_tree(vault_id="vault-1")
        self.assertEqual(len(tree["folders"]), 1)
        self.assertEqual(tree["folders"][0]["name"], "Bank")
        self.assertEqual(tree["folders"][0]["file_count"], 50)


class ExtractExtensionFilterTests(unittest.TestCase):


    def test_show_all_zip_files(self):
        result = _extract_extension_filter("Show all zip files")
        self.assertIn("zip", result or ())

    def test_show_all_python_scripts(self):
        result = _extract_extension_filter("Show all Python scripts")
        self.assertEqual(result, ("py",))

    def test_find_my_pdfs(self):
        result = _extract_extension_filter("find my pdfs please")
        self.assertEqual(result, ("pdf",))

    def test_recognises_image_synonyms(self):
        for phrase in (
            "show me my photos",
            "list every image",
            "find images",
        ):
            self.assertIsNotNone(
                _extract_extension_filter(phrase),
                f"phrase {phrase!r} must trigger the image filter",
            )

    def test_recognises_audio_synonyms(self):
        result = _extract_extension_filter("show my voice recordings")
                                                                   
                                                    
        self.assertIn("m4a", result or ())

    def test_none_for_plain_filename_query(self):
        self.assertIsNone(
            _extract_extension_filter("show me statement.pdf inside bank"),
            "a filename query (even with a recognised extension) "
            "should not coerce to a type-wide filter unless the "
            "user used a plural / kind phrasing",
        )

    def test_none_for_empty_input(self):
        self.assertIsNone(_extract_extension_filter(""))
        self.assertIsNone(_extract_extension_filter(None))
        self.assertIsNone(_extract_extension_filter("   "))

    def test_none_for_unrelated_query(self):
        self.assertIsNone(
            _extract_extension_filter("what's the weather like"),
        )


class FileMatchesExtensionsTests(unittest.TestCase):

    def test_matches_lowercase_extension(self):
        self.assertTrue(
            _file_matches_extensions("app.py", None, ("py",)),
        )

    def test_matches_uppercase_extension_in_filename(self):
        self.assertTrue(
            _file_matches_extensions("APP.PY", None, ("py",)),
        )

    def test_matches_saved_name_when_filename_does_not(self):
        self.assertTrue(
            _file_matches_extensions(
                "uploaded_blob", "report.pdf", ("pdf",),
            ),
        )

    def test_rejects_no_match(self):
        self.assertFalse(
            _file_matches_extensions("readme.md", None, ("py",)),
        )

    def test_empty_extensions_passes_through(self):
                                                               
        self.assertTrue(
            _file_matches_extensions("file.bin", None, ()),
        )

    def test_handles_none_filename_and_saved_name(self):
        self.assertFalse(
            _file_matches_extensions(None, None, ("py",)),
        )

    def test_extension_with_leading_dot_normalises(self):
                                                                  
        self.assertTrue(
            _file_matches_extensions("a.py", None, (".py",)),
        )


class IsUnderFolderTests(unittest.TestCase):


    def test_matches_immediate_children(self):
        self.assertTrue(
            _is_under_folder("Bank/statement.pdf", "Bank"),
        )

    def test_matches_nested_descendants(self):
        self.assertTrue(
            _is_under_folder(
                "Bank/2024/april/statement.pdf", "Bank",
            ),
        )

    def test_does_not_match_sibling_with_prefix(self):
                                                                   
        self.assertFalse(
            _is_under_folder("Banking/statement.pdf", "Bank"),
        )
        self.assertFalse(
            _is_under_folder("Banker/x.pdf", "Bank"),
        )

    def test_case_insensitive(self):
        self.assertTrue(
            _is_under_folder("Bank/statement.pdf", "bank"),
        )
        self.assertTrue(
            _is_under_folder("BANK/statement.pdf", "Bank"),
        )

    def test_strips_leading_trailing_slashes_on_prefix(self):
                                                                  
                                              
        self.assertTrue(
            _is_under_folder("Bank/x.pdf", "/Bank/"),
        )

    def test_empty_prefix_returns_true(self):
                                               
        self.assertTrue(
            _is_under_folder("Bank/x.pdf", None),
        )
        self.assertTrue(
            _is_under_folder("Bank/x.pdf", ""),
        )

    def test_none_relative_path_with_prefix_is_false(self):
                                                                     
        self.assertFalse(
            _is_under_folder(None, "Bank"),
        )

    def test_none_relative_path_with_no_prefix_is_true(self):
                                            
        self.assertTrue(
            _is_under_folder(None, None),
        )


class FormatDisambiguationReplyTests(unittest.TestCase):

    @staticmethod
    def _candidate(*, name: str, relative_path: str | None) -> dict:
        return {
            "file_name": name,
            "saved_name": name,
            "relative_path": relative_path,
        }

    def test_single_match_returns_empty(self):
                                                                    
        result = _format_disambiguation_reply(
            [self._candidate(name="x.pdf", relative_path="A/x.pdf")],
            "x.pdf",
        )
        self.assertEqual(result, "")

    def test_two_matches_shows_count_and_paths(self):
        result = _format_disambiguation_reply(
            [
                self._candidate(
                    name="statement.pdf",
                    relative_path="Bank/statement.pdf",
                ),
                self._candidate(
                    name="statement.pdf",
                    relative_path="Taxes/statement.pdf",
                ),
            ],
            "statement.pdf",
        )
        self.assertIn("I found 2 files", result)
        self.assertIn("statement.pdf", result)
        self.assertIn("Bank/statement.pdf", result)
        self.assertIn("Taxes/statement.pdf", result)
                                                                   
        self.assertIn("Which one do you want", result)

    def test_three_matches_shows_all_three(self):
        candidates = [
            self._candidate(name="a.pdf", relative_path="A/a.pdf"),
            self._candidate(name="a.pdf", relative_path="B/a.pdf"),
            self._candidate(name="a.pdf", relative_path="C/a.pdf"),
        ]
        result = _format_disambiguation_reply(candidates, "a.pdf")
        self.assertIn("I found 3 files", result)
        for letter in ("A/a.pdf", "B/a.pdf", "C/a.pdf"):
            self.assertIn(letter, result)

    def test_more_than_ten_matches_caps_with_summary(self):
        candidates = [
            self._candidate(name="x.pdf", relative_path=f"F{i}/x.pdf")
            for i in range(15)
        ]
        result = _format_disambiguation_reply(candidates, "x.pdf")
        self.assertIn("I found 15 files", result)
        self.assertIn("…and 5 more", result)

    def test_no_requested_name_omits_named_phrase(self):
        result = _format_disambiguation_reply(
            [
                self._candidate(name="x.pdf", relative_path="A/x.pdf"),
                self._candidate(name="x.pdf", relative_path="B/x.pdf"),
            ],
            None,
        )
                                                                    
                 
        self.assertIn("I found 2 files", result)
        self.assertNotIn('named ""', result)


class FolderBrowserRouteShapeTests(unittest.TestCase):


    def test_route_registered_on_app(self):
        paths = {
            getattr(r, "path", None) for r in main.app.routes
        }
        self.assertIn(
            "/folders",
            paths,
            "/folders must be registered on the FastAPI app",
        )

    def test_route_uses_get_method(self):
        for route in main.app.routes:
            if getattr(route, "path", None) == "/folders":
                methods = getattr(route, "methods", set()) or set()
                self.assertIn(
                    "GET", methods,
                    "/folders must accept GET",
                )
                return
        self.fail("/folders route not found")


class ListUploadedFilesShapeTests(unittest.TestCase):


    def test_select_lists_relative_path(self):
        import inspect
        src = inspect.getsource(main.list_uploaded_files)
        self.assertIn(
            "relative_path",
            src,
            "list_uploaded_files SELECT must include relative_path",
        )


if __name__ == "__main__":
    unittest.main()
