

from __future__ import annotations

import hashlib
import inspect
import re
import unittest

from duplicate_detection import (
    find_existing_file_by_hash,
    find_name_conflict,
    next_available_versioned_name,
    normalize_content_sha256,
    normalize_duplicate_action,
    short_hash_for_log,
)


def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _row(
    *,
    id: str,
    file_name: str,
    content_sha256: str | None,
    file_size: int,
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


class NormalizeContentSha256Tests(unittest.TestCase):
    def test_valid_lowercase_hex_passes_through(self):
        valid = "a" * 64
        self.assertEqual(normalize_content_sha256(valid), valid)

    def test_uppercase_is_lowercased(self):
        self.assertEqual(
            normalize_content_sha256("A" * 64),
            "a" * 64,
        )

    def test_whitespace_trimmed(self):
        h = _hash(b"hello")
        self.assertEqual(
            normalize_content_sha256(f"  {h}  "),
            h,
        )

    def test_short_returns_none(self):
        self.assertIsNone(normalize_content_sha256("abcd"))

    def test_long_returns_none(self):
        self.assertIsNone(normalize_content_sha256("a" * 65))

    def test_non_hex_returns_none(self):
                                                
        self.assertIsNone(normalize_content_sha256("z" + ("a" * 63)))

    def test_none_returns_none(self):
        self.assertIsNone(normalize_content_sha256(None))

    def test_empty_returns_none(self):
        self.assertIsNone(normalize_content_sha256(""))

    def test_non_string_returns_none(self):
                                                                 
                               
        self.assertIsNone(normalize_content_sha256(12345))


class NormalizeDuplicateActionTests(unittest.TestCase):
    def test_known_values_pass_through(self):
        for v in ("prompt", "skip", "keep_both", "replace"):
            self.assertEqual(normalize_duplicate_action(v), v)

    def test_uppercase_is_normalised(self):
        self.assertEqual(normalize_duplicate_action("SKIP"), "skip")

    def test_unknown_folds_to_prompt(self):
                                                                    
                 
        self.assertEqual(
            normalize_duplicate_action("delete_existing"),
            "prompt",
        )

    def test_empty_folds_to_prompt(self):
        self.assertEqual(normalize_duplicate_action(""), "prompt")
        self.assertEqual(normalize_duplicate_action(None), "prompt")


class FindExistingFileByHashTests(unittest.TestCase):
    def test_matches_same_hash_and_size(self):
        h = _hash(b"hello")
        rows = [
            _row(
                id="f1", file_name="a.pdf",
                content_sha256=h, file_size=5,
            ),
        ]
        result = find_existing_file_by_hash(
            rows, content_sha256=h, file_size=5,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "f1")

    def test_same_hash_different_size_does_not_match(self):
                                                                      
        h = _hash(b"hello")
        rows = [
            _row(
                id="f1", file_name="a.pdf",
                content_sha256=h, file_size=999,
            ),
        ]
        result = find_existing_file_by_hash(
            rows, content_sha256=h, file_size=5,
        )
        self.assertIsNone(result)

    def test_no_match_returns_none(self):
        h = _hash(b"hello")
        rows = [
            _row(
                id="f1", file_name="a.pdf",
                content_sha256="b" * 64, file_size=5,
            ),
        ]
        result = find_existing_file_by_hash(
            rows, content_sha256=h, file_size=5,
        )
        self.assertIsNone(result)

    def test_legacy_rows_without_hash_are_skipped(self):
                                                                     
                                         
        h = _hash(b"hello")
        rows = [
            _row(
                id="legacy", file_name="a.pdf",
                content_sha256=None, file_size=5,
            ),
        ]
        result = find_existing_file_by_hash(
            rows, content_sha256=h, file_size=5,
        )
        self.assertIsNone(result)

    def test_prefers_canonical_over_keep_both_copy(self):
                                                           
                                                                  
        h = _hash(b"hello")
        rows = [
            _row(
                id="copy",
                file_name="a (1).pdf",
                content_sha256=h, file_size=5,
                duplicate_of_file_id="original",
            ),
            _row(
                id="original",
                file_name="a.pdf",
                content_sha256=h, file_size=5,
            ),
        ]
        result = find_existing_file_by_hash(
            rows, content_sha256=h, file_size=5,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "original")

    def test_none_hash_returns_none(self):
        rows = [
            _row(
                id="f1", file_name="a.pdf",
                content_sha256="a" * 64, file_size=5,
            ),
        ]
        self.assertIsNone(
            find_existing_file_by_hash(
                rows, content_sha256=None, file_size=5,
            ),
        )


class FindNameConflictTests(unittest.TestCase):
    def test_same_saved_name_same_folder_returns_existing(self):
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                saved_name="statement.pdf",
                relative_path="Bank/statement.pdf",
                content_sha256="a" * 64, file_size=10,
            ),
        ]
        result = find_name_conflict(
            rows,
            saved_name="statement.pdf",
            relative_path="Bank/statement.pdf",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "f1")

    def test_same_saved_name_different_folder_no_conflict(self):
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                saved_name="statement.pdf",
                relative_path="Bank/statement.pdf",
                content_sha256="a" * 64, file_size=10,
            ),
        ]
        result = find_name_conflict(
            rows,
            saved_name="statement.pdf",
            relative_path="Taxes/statement.pdf",
        )
        self.assertIsNone(result)

    def test_case_insensitive_match(self):
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                saved_name="Statement.PDF",
                relative_path="Bank/statement.pdf",
                content_sha256="a" * 64, file_size=10,
            ),
        ]
        result = find_name_conflict(
            rows,
            saved_name="statement.pdf",
            relative_path="Bank/statement.pdf",
        )
        self.assertIsNotNone(result)

    def test_empty_saved_name_no_conflict(self):
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                saved_name="statement.pdf",
                relative_path=None,
                content_sha256="a" * 64, file_size=10,
            ),
        ]
        self.assertIsNone(
            find_name_conflict(
                rows, saved_name="", relative_path=None,
            ),
        )


class NextAvailableVersionedNameTests(unittest.TestCase):
    def test_first_keep_both_returns_paren_1(self):
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                saved_name="statement.pdf",
                relative_path=None,
                content_sha256="a" * 64, file_size=10,
            ),
        ]
        self.assertEqual(
            next_available_versioned_name(
                rows,
                base_name="statement.pdf",
                relative_path=None,
            ),
            "statement (1).pdf",
        )

    def test_second_keep_both_returns_paren_2(self):
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                saved_name="statement.pdf",
                relative_path=None,
                content_sha256="a" * 64, file_size=10,
            ),
            _row(
                id="f2", file_name="statement (1).pdf",
                saved_name="statement (1).pdf",
                relative_path=None,
                content_sha256="b" * 64, file_size=11,
            ),
        ]
        self.assertEqual(
            next_available_versioned_name(
                rows,
                base_name="statement.pdf",
                relative_path=None,
            ),
            "statement (2).pdf",
        )

    def test_python_script_keeps_extension(self):
        rows = [
            _row(
                id="f1", file_name="app.py",
                saved_name="app.py",
                relative_path="Code/app.py",
                content_sha256="a" * 64, file_size=100,
            ),
        ]
        self.assertEqual(
            next_available_versioned_name(
                rows,
                base_name="app.py",
                relative_path="Code/app.py",
            ),
            "app (1).py",
        )

    def test_no_extension_filename(self):
        rows = [
            _row(
                id="f1", file_name="photo",
                saved_name="photo",
                relative_path=None,
                content_sha256="a" * 64, file_size=100,
            ),
        ]
        self.assertEqual(
            next_available_versioned_name(
                rows,
                base_name="photo",
                relative_path=None,
            ),
            "photo (1)",
        )

    def test_folder_scoped_versions(self):
                                                                 
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                saved_name="statement.pdf",
                relative_path="Bank/statement.pdf",
                content_sha256="a" * 64, file_size=10,
            ),
            _row(
                id="f2", file_name="statement (1).pdf",
                saved_name="statement (1).pdf",
                relative_path="Bank/statement (1).pdf",
                content_sha256="b" * 64, file_size=11,
            ),
        ]
                                                               
        self.assertEqual(
            next_available_versioned_name(
                rows,
                base_name="statement.pdf",
                relative_path="Taxes/statement.pdf",
            ),
            "statement.pdf",                        
        )

    def test_repeated_keep_both_caps_increment_via_strip(self):
                                                                   
                                                                   
        rows = [
            _row(
                id="f1", file_name="statement.pdf",
                saved_name="statement.pdf",
                relative_path=None,
                content_sha256="a" * 64, file_size=10,
            ),
            _row(
                id="f2", file_name="statement (1).pdf",
                saved_name="statement (1).pdf",
                relative_path=None,
                content_sha256="b" * 64, file_size=11,
            ),
        ]
        self.assertEqual(
            next_available_versioned_name(
                rows,
                base_name="statement (1).pdf",
                relative_path=None,
            ),
            "statement (2).pdf",
        )


class ShortHashForLogTests(unittest.TestCase):
    def test_returns_first_8_chars(self):
        h = _hash(b"hello")
        self.assertEqual(short_hash_for_log(h), h[:8])
        self.assertEqual(len(short_hash_for_log(h)), 8)

    def test_none_returns_dash(self):
        self.assertEqual(short_hash_for_log(None), "-")

    def test_empty_returns_dash(self):
        self.assertEqual(short_hash_for_log(""), "-")

    def test_never_returns_more_than_8_chars(self):
                                                            
        for inp in ("a" * 64, "deadbeef" * 8, "x" * 100):
            self.assertLessEqual(len(short_hash_for_log(inp)), 8)


class UploadEndpointWiringTests(unittest.TestCase):


    def _endpoint_src(self) -> str:
        import main
        return inspect.getsource(main.upload_file_endpoint)

    def test_endpoint_accepts_content_sha256(self):
        src = self._endpoint_src()
        self.assertIn("content_sha256:", src)

    def test_endpoint_accepts_duplicate_action(self):
        src = self._endpoint_src()
        self.assertIn("duplicate_action:", src)

    def test_endpoint_passes_hash_and_action_to_save(self):
        src = self._endpoint_src()
        self.assertIn("content_sha256=content_sha256", src)
        self.assertIn("duplicate_action=", src)

    def test_endpoint_returns_skipped_duplicate_without_naming(self):
                                                                
                                                                    
        src = self._endpoint_src()
        self.assertIn('"skipped_duplicate"', src)
        skip_idx = src.find('"skipped_duplicate"')
        naming_idx = src.find("extract_naming_intent")
        self.assertLess(
            skip_idx, naming_idx,
            "skipped_duplicate return must precede the naming pipeline",
        )


class SaveUploadedFileBranchTests(unittest.TestCase):


    def _src(self) -> str:
        import main
        return inspect.getsource(main.save_uploaded_file)

    def test_dedup_runs_before_encryption(self):
        src = self._src()
        find_idx = src.find("find_existing_file_by_hash(")
        encrypt_idx = src.find("encrypt_bytes(")
        self.assertGreater(find_idx, -1)
        self.assertGreater(encrypt_idx, -1)
        self.assertLess(
            find_idx, encrypt_idx,
            "Duplicate detection must run before encryption to avoid "
            "wasting AES-GCM cycles on a file we'll skip.",
        )

    def test_skip_branch_bumps_batch_counter(self):
        src = self._src()
        self.assertIn(
            "_bump_import_batch_on_skipped_duplicate(",
            src,
        )

    def test_skip_branch_returns_without_writing(self):
        src = self._src()
                                                                       
                                                                  
        skip_idx = src.find('"skipped_duplicate"')
                                                                   
        encrypt_idx = src.find("encrypt_bytes(")
        self.assertGreater(skip_idx, -1)
        self.assertLess(
            skip_idx, encrypt_idx,
            "skipped_duplicate return must be reachable before encryption",
        )

    def test_prompt_branch_raises_409(self):
        src = self._src()
        self.assertIn('"duplicate_found"', src)
        self.assertIn("status_code=409", src)

    def test_insert_includes_new_columns(self):
        src = self._src()
        for col in ("content_sha256", "duplicate_of_file_id", "version_number"):
            self.assertIn(col, src, f"INSERT must include {col}")

    def test_keep_both_uses_versioned_name(self):
        src = self._src()
        self.assertIn("next_available_versioned_name(", src)


class HashLoggingRedactionTests(unittest.TestCase):


    def _save_src(self) -> str:
        import main
        return inspect.getsource(main.save_uploaded_file)

    def test_no_direct_hash_logging(self):
                                                                    
                                                                      
        src = self._save_src()
                                                                    
                                                     
        hash_log_pattern = re.compile(
            r"(?:_ulog|logger\.\w+|print)\([^)]*?"
            r"(?:safe_hash|content_sha256)\b",
            re.DOTALL,
        )
        for match in hash_log_pattern.finditer(src):
            window = src[match.start():match.end() + 200]
            self.assertIn(
                "short_hash_for_log(", window,
                "Hash variable used in log call without "
                "short_hash_for_log redaction: " + window[:200],
            )


class MigrationFileTests(unittest.TestCase):


    MIG_PATH = (
        "migrations/versions/0004_uploaded_files_content_hash.py"
    )

    def _read_migration(self) -> str:
        with open(self.MIG_PATH, encoding="utf-8") as f:
            return f.read()

    def test_revision_id_is_0004(self):
        src = self._read_migration()
        self.assertIn('revision: str = "0004_uploaded_files_content_hash"', src)
        self.assertIn(
            'down_revision: Union[str, None] = "0003_import_batches"',
            src,
        )

    def test_adds_content_sha256_column(self):
        src = self._read_migration()
        self.assertIn("content_sha256", src)
        self.assertIn("CHECK (content_sha256 IS NULL OR length(content_sha256) = 64)", src)

    def test_adds_duplicate_of_file_id_column(self):
        src = self._read_migration()
        self.assertIn("duplicate_of_file_id", src)
        self.assertIn("ON DELETE SET NULL", src)

    def test_duplicate_of_file_id_uses_text_to_match_baseline_pk(self):
                                                                   
                                                                   
        src = self._read_migration()
        self.assertIn(
            "ADD COLUMN IF NOT EXISTS duplicate_of_file_id TEXT",
            src,
            "duplicate_of_file_id must be TEXT — uploaded_files.id is "
            "TEXT in the baseline, and Postgres rejects UUID→TEXT FKs.",
        )
        self.assertNotIn(
            "ADD COLUMN IF NOT EXISTS duplicate_of_file_id UUID",
            src,
            "duplicate_of_file_id must NOT be UUID; uploaded_files.id is TEXT.",
        )

    def test_adds_version_number_column(self):
        src = self._read_migration()
        self.assertIn("version_number", src)
        self.assertIn("DEFAULT 1", src)

    def test_adds_required_indexes(self):
        src = self._read_migration()
        for idx in (
            "uploaded_files_content_hash_idx",
            "uploaded_files_duplicate_of_idx",
            "uploaded_files_name_conflict_idx",
        ):
            self.assertIn(idx, src, f"Missing index {idx}")


if __name__ == "__main__":
    unittest.main()
