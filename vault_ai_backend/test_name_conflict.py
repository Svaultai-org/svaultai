

from __future__ import annotations

import inspect
import unittest

from duplicate_detection import find_name_conflict


def _row(
    *,
    id: str,
    file_name: str,
    content_sha256: str | None,
    file_size: int = 100,
    saved_name: str | None = None,
    relative_path: str | None = None,
    duplicate_of_file_id: str | None = None,
    version_number: int = 1,
) -> dict:
    return {
        "id": id,
        "file_name": file_name,
        "saved_name": saved_name or file_name,
        "content_sha256": content_sha256,
        "file_size": file_size,
        "relative_path": relative_path,
        "duplicate_of_file_id": duplicate_of_file_id,
        "version_number": version_number,
    }


class FindNameConflictPhase41Tests(unittest.TestCase):


    def test_same_folder_same_saved_name_different_bytes_is_conflict(
        self,
    ):
                                                                    
        existing = _row(
            id="f1", file_name="statement.pdf",
            saved_name="statement.pdf",
            relative_path="Bank",
            content_sha256="a" * 64,
        )
        result = find_name_conflict(
            [existing],
            saved_name="statement.pdf",
            file_name="statement.pdf",
            relative_path="Bank",
            incoming_content_sha256="b" * 64,
        )
        self.assertEqual(result, existing)

    def test_different_folder_same_filename_not_conflict(self):
                                                                 
                                                   
        existing = _row(
            id="f1", file_name="statement.pdf",
            saved_name="statement.pdf",
            relative_path="Bank",
            content_sha256="a" * 64,
        )
        result = find_name_conflict(
            [existing],
            file_name="statement.pdf",
            relative_path="Taxes",
            incoming_content_sha256="b" * 64,
        )
        self.assertIsNone(result)

    def test_same_bytes_is_not_a_name_conflict(self):
                                                              
                                                                
        existing = _row(
            id="f1", file_name="statement.pdf",
            saved_name="statement.pdf",
            relative_path="Bank",
            content_sha256="a" * 64,
        )
        result = find_name_conflict(
            [existing],
            file_name="statement.pdf",
            relative_path="Bank",
            incoming_content_sha256="a" * 64,             
        )
        self.assertIsNone(result)

    def test_legacy_row_without_hash_still_flagged_as_conflict(self):
                                                       
                                                             
        existing = _row(
            id="legacy", file_name="statement.pdf",
            saved_name="statement.pdf",
            relative_path="Bank",
            content_sha256=None,
        )
        result = find_name_conflict(
            [existing],
            file_name="statement.pdf",
            relative_path="Bank",
            incoming_content_sha256="b" * 64,
        )
        self.assertEqual(result, existing)

    def test_match_by_file_name_when_saved_name_is_null(self):
                                                             
                                                                
        existing = _row(
            id="f1", file_name="IMG_001.jpg",
            saved_name="Sara's passport",                
            relative_path="Family",
            content_sha256="a" * 64,
        )
        result = find_name_conflict(
            [existing],
            saved_name=None,
            file_name="IMG_001.jpg",
            relative_path="Family",
            incoming_content_sha256="b" * 64,
        )
        self.assertEqual(result, existing)

    def test_match_by_saved_name_when_existing_file_name_differs(self):
                                                               
                                              
        existing = _row(
            id="f1", file_name="raw_export.pdf",
            saved_name="Tax Return 2023",
            relative_path="Taxes",
            content_sha256="a" * 64,
        )
        result = find_name_conflict(
            [existing],
            saved_name="Tax Return 2023",
            file_name="my_taxes.pdf",
            relative_path="Taxes",
            incoming_content_sha256="b" * 64,
        )
        self.assertEqual(result, existing)

    def test_no_name_inputs_returns_none(self):
        self.assertIsNone(
            find_name_conflict(
                [_row(
                    id="f1", file_name="a.pdf",
                    saved_name="a.pdf",
                    content_sha256="a" * 64,
                )],
                saved_name=None,
                file_name=None,
                relative_path=None,
            )
        )

    def test_case_insensitive_match(self):
        existing = _row(
            id="f1", file_name="Statement.PDF",
            saved_name="Statement.PDF",
            relative_path="bank",
            content_sha256="a" * 64,
        )
        result = find_name_conflict(
            [existing],
            file_name="statement.pdf",
            relative_path="bank",
            incoming_content_sha256="b" * 64,
        )
        self.assertEqual(result, existing)

    def test_root_no_folder_match(self):
                                                              
                                                                  
        existing = _row(
            id="f1", file_name="loose.pdf",
            saved_name="loose.pdf",
            relative_path=None,
            content_sha256="a" * 64,
        )
                                         
        self.assertEqual(
            find_name_conflict(
                [existing],
                file_name="loose.pdf",
                relative_path=None,
                incoming_content_sha256="b" * 64,
            ),
            existing,
        )
                                         
        self.assertIsNone(
            find_name_conflict(
                [existing],
                file_name="loose.pdf",
                relative_path="Bank",
                incoming_content_sha256="b" * 64,
            ),
        )


class SaveUploadedFileNameConflictWiringTests(unittest.TestCase):


    def _src(self) -> str:
        import main
        return inspect.getsource(main.save_uploaded_file)

    def test_name_conflict_runs_after_exact_duplicate_gate(self):
        src = self._src()
                                               
                                                                     
        dup_idx = src.find("find_existing_file_by_hash(")
        nc_idx = src.find("find_name_conflict(")
        self.assertGreater(dup_idx, -1)
        self.assertGreater(nc_idx, -1)
        self.assertLess(
            dup_idx, nc_idx,
            "Phase 4 exact-content gate must run BEFORE the Phase 4.1 "
            "name-conflict gate so an exact duplicate never resurfaces "
            "as a name conflict.",
        )

    def test_name_conflict_runs_before_encryption(self):
        src = self._src()
                                                                  
                                                                    
        nc_idx = src.find("find_name_conflict(")
        encrypt_idx = src.find("encrypt_bytes(")
        self.assertGreater(nc_idx, -1)
        self.assertGreater(encrypt_idx, -1)
        self.assertLess(
            nc_idx, encrypt_idx,
            "Name-conflict gate must run BEFORE encryption to avoid "
            "wasted AES cycles on a 409 prompt.",
        )

    def test_single_file_prompt_raises_409_name_conflict(self):
        src = self._src()
        self.assertIn('"name_conflict"', src)
                                                           
        code_idx = src.find('"name_conflict"')
        encrypt_idx = src.find("encrypt_bytes(")
        self.assertLess(code_idx, encrypt_idx)

    def test_409_envelope_includes_proposed_versioned_name(self):
        src = self._src()
        self.assertIn("proposed_versioned_name", src)
                                                               
                                              
    def test_409_envelope_includes_existing_metadata(self):
        src = self._src()
        for field in (
            "existing_file_id",
            "existing_file_name",
            "existing_saved_name",
            "existing_relative_path",
        ):
            self.assertIn(field, src, f"missing 409 field {field}")

    def test_batch_auto_versions_via_next_available(self):
        src = self._src()
                                                                    
        self.assertIn("next_available_versioned_name(", src)
                                                            
        self.assertIn("default_saved_name = proposed_versioned_name", src)

    def test_name_conflict_does_not_set_duplicate_of_file_id(self):
                                                                
                                                                  
        src = self._src()
                                                              
                                                
        nc_branch_start = src.find(
            "elif name_conflict_existing is not None:"
        )
        self.assertGreater(nc_branch_start, -1)
                                                                
                                         
        nc_branch = src[nc_branch_start:nc_branch_start + 800]
        self.assertNotIn(
            "duplicate_of_file_id =", nc_branch,
            "name-conflict branch must NOT set duplicate_of_file_id "
            "— content differs, so the two files are independent.",
        )

    def test_response_carries_renamed_flag(self):
        src = self._src()
        self.assertIn('"renamed"', src)
        self.assertIn('"original_saved_name"', src)

    def test_keep_both_action_avoids_409_and_auto_versions(self):
                                                                      
                                                          
        src = self._src()
        self.assertIn(
            'action_mode == "prompt"', src,
            "the 409 must be conditional on prompt action",
        )

    def test_message_helper_exists(self):
                                                                    
                                                                 
        import main
        self.assertTrue(
            callable(getattr(main, "_format_name_conflict_message", None)),
            "_format_name_conflict_message must exist",
        )


class FormatNameConflictMessageTests(unittest.TestCase):


    def test_includes_spec_phrase_when_folder_set(self):
        import main
        msg = main._format_name_conflict_message(
            {
                "saved_name": "statement.pdf",
                "relative_path": "Bank/statement.pdf",
            }
        )
                                                                     
                                        
        self.assertIn("name already exists", msg)
        self.assertIn("content is different", msg)
        self.assertIn("Bank", msg)

    def test_falls_back_when_no_folder(self):
        import main
        msg = main._format_name_conflict_message(
            {
                "saved_name": "loose.pdf",
                "relative_path": None,
            }
        )
        self.assertIn("already exists", msg)
        self.assertIn("content is different", msg)


class Phase41SchemaPreconditionsTests(unittest.TestCase):


    def test_phase_4_migration_is_present(self):
        import os
        self.assertTrue(
            os.path.exists(
                "migrations/versions/"
                "0004_uploaded_files_content_hash.py"
            ),
            "Phase 4.1 requires the Phase 4 columns; the migration "
            "file 0004 must remain in the tree.",
        )


if __name__ == "__main__":
    unittest.main()
