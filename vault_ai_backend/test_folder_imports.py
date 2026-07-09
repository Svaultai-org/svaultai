

from __future__ import annotations

import inspect
import unittest

from main import (
    _RELATIVE_PATH_MAX_LEN,
    _is_document_like_file,
    _sanitize_relative_path,
    _should_analyze_upload,
    save_uploaded_file,
)


class SanitizeRelativePathHappyTests(unittest.TestCase):


    def test_simple_two_segment_path(self):
        self.assertEqual(
            _sanitize_relative_path("Bank/statement.pdf"),
            "Bank/statement.pdf",
        )

    def test_three_level_nested_path(self):
                                               
        self.assertEqual(
            _sanitize_relative_path("My Life Backup/Photos/family.jpg"),
            "My Life Backup/Photos/family.jpg",
        )

    def test_deeply_nested_path(self):
        self.assertEqual(
            _sanitize_relative_path("a/b/c/d/e/f/g/file.txt"),
            "a/b/c/d/e/f/g/file.txt",
        )

    def test_filename_with_spaces(self):
        self.assertEqual(
            _sanitize_relative_path("Family Photos/Christmas 2024/photo.jpg"),
            "Family Photos/Christmas 2024/photo.jpg",
        )

    def test_filename_with_unicode(self):
                                                                   
                                       
        self.assertEqual(
            _sanitize_relative_path("仕事/書類/契約.pdf"),
            "仕事/書類/契約.pdf",
        )

    def test_windows_backslashes_normalized(self):
                                                              
                                                           
        self.assertEqual(
            _sanitize_relative_path("Bank\\statement.pdf"),
            "Bank/statement.pdf",
        )

    def test_mixed_separators_normalized(self):
        self.assertEqual(
            _sanitize_relative_path("Bank\\sub/statement.pdf"),
            "Bank/sub/statement.pdf",
        )

    def test_doubled_slashes_collapsed(self):
                                                                      
                                                                
        self.assertEqual(
            _sanitize_relative_path("Bank//statement.pdf"),
            "Bank/statement.pdf",
        )

    def test_trailing_slash_stripped(self):
        self.assertEqual(
            _sanitize_relative_path("Bank/statement.pdf/"),
            "Bank/statement.pdf",
        )

    def test_leading_whitespace_stripped(self):
        self.assertEqual(
            _sanitize_relative_path("   Bank/statement.pdf"),
            "Bank/statement.pdf",
        )

    def test_dot_extensions_allowed_in_filename(self):
                                                                     
                                                              
        self.assertEqual(
            _sanitize_relative_path("project/.env.example"),
            "project/.env.example",
        )

    def test_unknown_extensions_pass(self):
                                                                    
                                                                 
        self.assertEqual(
            _sanitize_relative_path("Archive/data.xyz"),
            "Archive/data.xyz",
        )

    def test_at_max_length_passes(self):
                                         
        long_segment = "a" * 50
        depth = (_RELATIVE_PATH_MAX_LEN // (len(long_segment) + 1))
        path = "/".join([long_segment] * depth) + "/x"
                                                                    
                        
        if len(path) <= _RELATIVE_PATH_MAX_LEN:
            self.assertIsNotNone(_sanitize_relative_path(path))


class SanitizeRelativePathRejectionTests(unittest.TestCase):


    def test_none_is_none(self):
        self.assertIsNone(_sanitize_relative_path(None))

    def test_empty_string_is_none(self):
        self.assertIsNone(_sanitize_relative_path(""))

    def test_whitespace_only_is_none(self):
        self.assertIsNone(_sanitize_relative_path("   "))
        self.assertIsNone(_sanitize_relative_path("\t\n"))

    def test_non_string_is_none(self):
                                                                  
        self.assertIsNone(_sanitize_relative_path(42))                          
        self.assertIsNone(_sanitize_relative_path({"name": "x"}))                          
        self.assertIsNone(_sanitize_relative_path(["a", "b"]))                          

    def test_absolute_posix_path_rejected(self):
                                                                     
                                                                     
        self.assertIsNone(_sanitize_relative_path("/etc/passwd"))
        self.assertIsNone(_sanitize_relative_path("/Users/alice/file.txt"))

    def test_absolute_windows_path_rejected(self):
        self.assertIsNone(_sanitize_relative_path("C:\\Windows\\System32\\cmd.exe"))
        self.assertIsNone(_sanitize_relative_path("D:/Backups/file.zip"))
        self.assertIsNone(_sanitize_relative_path("c:/lowercase.txt"))

    def test_dotdot_segment_rejected(self):
                                                                 
                                                                    
        self.assertIsNone(_sanitize_relative_path("../escape.txt"))
        self.assertIsNone(_sanitize_relative_path("Bank/../secret.txt"))
        self.assertIsNone(_sanitize_relative_path("..//foo"))
        self.assertIsNone(_sanitize_relative_path("a/b/.."))

    def test_dot_only_segment_rejected(self):
                                                                      
                                                                       
        self.assertIsNone(_sanitize_relative_path("./file.txt"))
        self.assertIsNone(_sanitize_relative_path("Bank/./statement.pdf"))

    def test_null_byte_rejected(self):
                                                   
        self.assertIsNone(_sanitize_relative_path("Bank/\x00statement.pdf"))

    def test_newline_rejected(self):
                                                                  
        self.assertIsNone(_sanitize_relative_path("Bank/file\nname.txt"))
        self.assertIsNone(_sanitize_relative_path("Bank/file\rname.txt"))

    def test_over_max_length_rejected(self):
        too_long = "x" * (_RELATIVE_PATH_MAX_LEN + 1)
        self.assertIsNone(_sanitize_relative_path(too_long))

    def test_only_separators_rejected(self):
                                                                  
        self.assertIsNone(_sanitize_relative_path("/"))
        self.assertIsNone(_sanitize_relative_path("//"))
        self.assertIsNone(_sanitize_relative_path("\\\\"))

    def test_sanitiser_never_raises_on_arbitrary_input(self):
                                                                     
                                                                     
        weird_inputs = [
            "",
            None,
            "\x00\x01\x02",
            "\\" * 1000,
            "/" * 1000,
            "💀" * 100,
            "正常な/ パス/file.txt",
            42,
            {"nested": "object"},
            [1, 2, 3],
        ]
        for value in weird_inputs:
            try:
                _sanitize_relative_path(value)                          
            except Exception as exc:                                
                self.fail(
                    f"_sanitize_relative_path raised on {value!r}: {exc!r} "
                    "— it must always fold to None on unsafe input"
                )


class AnyFileAcceptanceTests(unittest.TestCase):


    DOC_LIKE_EXTENSIONS = (
        ".pdf", ".docx", ".xlsx", ".txt", ".csv", ".json",
    )

    EVERYDAY_NON_DOC_EXTENSIONS = (
        ".py", ".js", ".html", ".css", ".sh", ".ps1",
        ".env.example", ".env", ".yaml", ".yml", ".toml",
        ".zip", ".tar", ".gz", ".7z", ".rar",
        ".jpg", ".png", ".gif", ".heic", ".webp",
        ".mp4", ".mov", ".webm", ".mkv", ".avi",
        ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac",
        ".exe",                                                    
        ".bat", ".cmd",                  
        ".dat", ".bin", ".unknown",
        "",                 
    )

    def test_should_analyze_returns_bool_for_every_shape(self):
                                                                  
                                       
        for ext in self.DOC_LIKE_EXTENSIONS + self.EVERYDAY_NON_DOC_EXTENSIONS:
            file_name = f"thing{ext}" if ext else "thing"
            for ctype in (None, "application/octet-stream",
                          "text/plain", "application/pdf"):
                result = _should_analyze_upload(ctype, file_name)
                self.assertIsInstance(
                    result, bool,
                    f"_should_analyze_upload must return bool for "
                    f"({ctype!r}, {file_name!r}) — got {result!r}",
                )

    def test_doc_like_extensions_route_to_text_extraction(self):
                                                                   
                                                            
        for ext in self.DOC_LIKE_EXTENSIONS:
            self.assertTrue(
                _is_document_like_file(None, f"file{ext}"),
                f"{ext} should be document-like (text extraction runs)",
            )

    def test_scripts_and_archives_are_not_doc_like_but_still_accepted(self):
                                                                  
                                                                  
        for ext in (".py", ".js", ".sh", ".ps1", ".zip", ".tar", ".gz"):
            self.assertFalse(
                _is_document_like_file(None, f"file{ext}"),
                f"{ext} should not be document-like (extraction skipped)",
            )

    def test_save_uploaded_file_signature_takes_relative_path(self):
                                                        
                                                                
        sig = inspect.signature(save_uploaded_file)
        param = sig.parameters.get("relative_path")
        self.assertIsNotNone(
            param,
            "save_uploaded_file must accept relative_path",
        )
        self.assertIsNone(
            param.default,
            "relative_path default must be None (no folder context)",
        )


class UploadedScriptsNeverExecuteTests(unittest.TestCase):


    DANGEROUS_TOKENS = (
        "exec(",
        "eval(",
        "subprocess.run(",
        "subprocess.Popen(",
        "subprocess.call(",
        "os.system(",
        "os.popen(",
        "compile(",
        "__import__(",
    )

    def test_save_uploaded_file_does_not_execute_uploaded_bytes(self):
        src = inspect.getsource(save_uploaded_file)
                                                                     
                                        
        stripped = self._strip_docstring(src)
        for token in self.DANGEROUS_TOKENS:
            self.assertNotIn(
                token,
                stripped,
                f"save_uploaded_file body must not contain {token!r} "
                "— uploaded content is data, never executable",
            )

    def test_sanitize_relative_path_does_not_execute_input(self):
                                                                     
        src = inspect.getsource(_sanitize_relative_path)
        stripped = self._strip_docstring(src)
        for token in self.DANGEROUS_TOKENS:
            self.assertNotIn(
                token,
                stripped,
                f"_sanitize_relative_path must not contain {token!r}",
            )

    @staticmethod
    def _strip_docstring(src: str) -> str:
                                                                  
                                       
        for marker in ('"""', "'''"):
            start = src.find(marker)
            if start == -1:
                continue
            end = src.find(marker, start + 3)
            if end == -1:
                continue
            return src[:start] + src[end + 3:]
        return src


if __name__ == "__main__":
    unittest.main()
