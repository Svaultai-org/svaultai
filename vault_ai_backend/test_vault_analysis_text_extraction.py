

from __future__ import annotations

import inspect
import os
import unittest

import vault_analysis_text_extraction as text_ext
import vault_analysis_worker as worker
import vault_analysis as va


def _migration_source() -> str:
    path = os.path.join(
        os.path.dirname(__file__),
        "migrations", "versions",
        "0006_extracted_text_lifecycle.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class Migration0006SchemaTests(unittest.TestCase):
    def setUp(self):
        self.src = _migration_source()

    def test_revises_0005(self):
        self.assertIn(
            'down_revision: Union[str, None] = "0005_vault_analysis_foundation"',
            self.src,
        )

    def test_adds_required_columns(self):
        for col in (
            "extracted_text_status",
            "extracted_text_source",
            "extracted_text_updated_at",
            "extracted_text_truncated",
            "extracted_text_char_count",
            "extracted_text_version",
        ):
            self.assertIn(
                f"ADD COLUMN IF NOT EXISTS {col}",
                self.src,
                f"migration must add {col}",
            )

    def test_status_default_is_not_available(self):
                                                               
                                                                    
        self.assertIn("DEFAULT 'not_available'", self.src)

    def test_status_enum_is_closed(self):
        for status in ("not_available", "available", "failed", "stale"):
            self.assertTrue(
                f"'{status}'" in self.src or f'"{status}"' in self.src,
                f"migration must declare extracted_text_status {status!r}",
            )

    def test_source_enum_is_closed(self):
        for source in ("upload", "worker", "ocr", "transcript"):
            self.assertTrue(
                f"'{source}'" in self.src or f'"{source}"' in self.src,
                f"migration must declare extracted_text_source {source!r}",
            )

    def test_no_plaintext_at_rest_constraint(self):
                                                                    
                                                                   
        self.assertIn(
            "uploaded_files_no_plaintext_at_rest_chk", self.src,
        )
        self.assertIn("extracted_text_encrypted = TRUE", self.src)

    def test_one_shot_backfill_for_existing_ciphertext(self):
                                                             
                                                         
        self.assertIn("UPDATE uploaded_files", self.src)
        self.assertIn("extracted_text_status = 'available'", self.src)
        self.assertIn("extracted_text_source = 'upload'", self.src)

    def test_coverage_index_present(self):
        self.assertIn("uploaded_files_text_status_idx", self.src)

    def test_downgrade_is_complete(self):
        for needle in (
            "DROP COLUMN IF EXISTS extracted_text_status",
            "DROP COLUMN IF EXISTS extracted_text_source",
            "DROP COLUMN IF EXISTS extracted_text_updated_at",
            "DROP COLUMN IF EXISTS extracted_text_truncated",
            "DROP COLUMN IF EXISTS extracted_text_char_count",
            "DROP COLUMN IF EXISTS extracted_text_version",
            "DROP CONSTRAINT IF EXISTS uploaded_files_no_plaintext_at_rest_chk",
            "DROP INDEX IF EXISTS uploaded_files_text_status_idx",
        ):
            self.assertIn(needle, self.src)


class HardSafetyFloorsTests(unittest.TestCase):


    @staticmethod
    def _module_ast(module):
        import ast
        return ast.parse(inspect.getsource(module))

    @staticmethod
    def _imported_names(tree):
        import ast
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name.split(".")[0])
                    names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root:
                    names.add(root)
                if node.module:
                    names.add(node.module)
        return names

    @staticmethod
    def _called_names(tree):
        import ast
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name):
                    called.add(f.id)
                elif isinstance(f, ast.Attribute):
                    parts: list[str] = []
                    cur: ast.AST = f
                    while isinstance(cur, ast.Attribute):
                        parts.insert(0, cur.attr)
                        cur = cur.value
                    if isinstance(cur, ast.Name):
                        parts.insert(0, cur.id)
                        called.add(".".join(parts))
        return called

    def test_extractor_never_imports_subprocess(self):
        tree = self._module_ast(text_ext)
        imports = self._imported_names(tree)
        self.assertNotIn(
            "subprocess", imports,
            "text extractor MUST NOT import subprocess — uploaded "
            "files are NEVER executed",
        )

    def test_extractor_never_calls_exec_or_eval(self):
        tree = self._module_ast(text_ext)
        called = self._called_names(tree)
        for forbidden in ("exec", "eval", "compile", "os.system"):
            self.assertNotIn(
                forbidden, called,
                f"text extractor MUST NOT call {forbidden!r}",
            )

    def test_extractor_does_not_use_real_html_parser(self):
                                                                
                                                                 
        tree = self._module_ast(text_ext)
        imports = self._imported_names(tree)
        for forbidden in (
            "html.parser", "lxml", "xml.etree", "xml.dom",
            "xml.sax", "html",
        ):
            self.assertNotIn(
                forbidden, imports,
                f"extractor MUST NOT import {forbidden!r} — DTD / "
                "external entity resolution is an attack surface",
            )

    def test_extractor_module_has_no_network_imports(self):
        tree = self._module_ast(text_ext)
        imports = self._imported_names(tree)
        for forbidden in (
            "requests", "urllib", "urllib3", "http",
            "socket", "httpx", "aiohttp",
        ):
            self.assertNotIn(forbidden, imports)

    def test_code_files_are_listed_in_code_extension_set(self):
                                                                  
                                                                  
        for ext in ("py", "sh", "ps1", "js", "rb", "php", "rs"):
            self.assertTrue(
                text_ext.is_code_file(f"thing.{ext}"),
                f".{ext} files must be marked code (text-only path)",
            )


class ExtractTextTypeRouterTests(unittest.TestCase):
    def test_txt_plain_decode(self):
        text, truncated = text_ext.extract_text(
            file_name="notes.txt",
            file_bytes=b"hello world\n",
        )
        self.assertEqual(text, "hello world")
        self.assertFalse(truncated)

    def test_md_plain_decode(self):
        text, _ = text_ext.extract_text(
            file_name="readme.md",
            file_bytes=b"# Title\n\nbody",
        )
        self.assertIn("Title", text)
        self.assertIn("body", text)

    def test_csv_plain_decode(self):
        text, _ = text_ext.extract_text(
            file_name="data.csv",
            file_bytes=b"a,b,c\n1,2,3",
        )
        self.assertIn("a,b,c", text)
        self.assertIn("1,2,3", text)

    def test_json_pretty_printed(self):
        text, _ = text_ext.extract_text(
            file_name="config.json",
            file_bytes=b'{"name":"vault","count":3}',
        )
                                                              
        self.assertIn("name", text)
        self.assertIn("vault", text)

    def test_malformed_json_falls_back_to_raw(self):
        text, _ = text_ext.extract_text(
            file_name="bad.json",
            file_bytes=b"{this is not json}",
        )
        self.assertIn("not json", text)

    def test_html_strips_tags_but_keeps_text(self):
        text, _ = text_ext.extract_text(
            file_name="page.html",
            file_bytes=b"<html><body><h1>Hello</h1><p>World</p></body></html>",
        )
        self.assertIn("Hello", text)
        self.assertIn("World", text)
                                    
        self.assertNotIn("<h1>", text)
        self.assertNotIn("<html>", text)

    def test_html_scrubs_script_and_style_bodies(self):
        text, _ = text_ext.extract_text(
            file_name="page.html",
            file_bytes=(
                b"<html><head><script>alert('xss')</script>"
                b"<style>.x{color:red}</style></head>"
                b"<body>Visible</body></html>"
            ),
        )
        self.assertIn("Visible", text)
        self.assertNotIn("alert(", text,
            "<script> body must NOT leak into the index — it's not "
            "useful content and looks like code")
        self.assertNotIn("color:red", text)

    def test_html_entities_resolve_to_chars(self):
        text, _ = text_ext.extract_text(
            file_name="x.html",
            file_bytes=b"<p>1 &lt; 2 &amp; 3 &gt; 0</p>",
        )
        self.assertIn("1 < 2 & 3 > 0", text)

    def test_unsupported_type_raises(self):
        with self.assertRaises(text_ext.TextExtractionError):
            text_ext.extract_text(
                file_name="x.zip",
                file_bytes=b"\x50\x4b\x03\x04",
            )

    def test_image_mime_is_unsupported_by_this_stage(self):
                                                                    
                          
        with self.assertRaises(text_ext.TextExtractionError):
            text_ext.extract_text(
                file_name="passport.jpg",
                file_bytes=b"\xff\xd8\xff\xe0junk",
                content_type="image/jpeg",
            )


class ExtractTextCodeFilesAreTextOnlyTests(unittest.TestCase):


    def test_python_script_returned_as_text(self):
                                                                
                                                                
        src = b"import os\nos.makedirs('/should/not/exist/please')\n"
        text, _ = text_ext.extract_text(
            file_name="hostile.py",
            file_bytes=src,
        )
        self.assertEqual(text.strip(), src.decode().strip())
        self.assertIn("import os", text)

    def test_shell_script_returned_as_text(self):
        src = b"#!/bin/sh\nrm -rf /tmp/should_not_run\n"
        text, _ = text_ext.extract_text(
            file_name="hostile.sh",
            file_bytes=src,
        )
        self.assertIn("rm -rf", text)
                                                                  

    def test_powershell_script_returned_as_text(self):
        src = b"Remove-Item C:\\Windows\\System32\\* -Recurse\n"
        text, _ = text_ext.extract_text(
            file_name="hostile.ps1",
            file_bytes=src,
        )
        self.assertIn("Remove-Item", text)


class ExtractTextTruncationTests(unittest.TestCase):
    def test_truncated_when_over_cap(self):
        huge = b"x" * (text_ext.MAX_EXTRACTED_CHARS + 50)
        text, truncated = text_ext.extract_text(
            file_name="big.txt",
            file_bytes=huge,
        )
        self.assertTrue(truncated)
        self.assertEqual(len(text), text_ext.MAX_EXTRACTED_CHARS)

    def test_not_truncated_under_cap(self):
        small = b"a" * 100
        _, truncated = text_ext.extract_text(
            file_name="small.txt",
            file_bytes=small,
        )
        self.assertFalse(truncated)


class DrainWiringTests(unittest.TestCase):
    def test_drain_helper_signature(self):
        sig = inspect.signature(worker.drain_text_extraction)
        params = set(sig.parameters)
        self.assertIn("vault_id", params)
        self.assertIn("key", params)
        self.assertIn("max_jobs", params)

    def test_drain_only_handles_text_extraction_stage(self):
                                                                   
                                                                
        src = inspect.getsource(worker)
        self.assertIn(
            f'_HANDLED_STAGE = va.STAGE_TEXT_EXTRACTION',
            src,
        )
        self.assertIn(
            'job.get("stage") != _HANDLED_STAGE',
            src,
        )

    def test_chat_endpoint_runs_drain_after_decrypt(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
                                                                 
                                                                 
        decrypt_idx = src.find("decrypted_message = decrypt_message(")
        drain_idx = src.find("drain_text_extraction(vault_id=")
        intent_dispatch_idx = src.find('if intent in ("summarize_vault"')
        self.assertGreater(decrypt_idx, -1)
        self.assertGreater(drain_idx, -1,
            "chat_endpoint must call drain_text_extraction after "
            "PIN verify / decrypt so the key is in hand")
        self.assertLess(decrypt_idx, drain_idx)
        if intent_dispatch_idx > -1:
            self.assertLess(
                drain_idx, intent_dispatch_idx,
                "drain MUST run before the intent dispatcher so "
                "content search sees the freshly extracted text",
            )

    def test_drain_does_not_log_plaintext(self):
                                                               
                                                                  
        src = inspect.getsource(worker)
        for needle in (
            "logger.info(plaintext", "logger.debug(plaintext",
            "print(plaintext", "logger.info(text",
            "print(text)",
        ):
            self.assertNotIn(needle, src)

    def test_drain_does_not_create_login_items(self):
                                                             
        src = inspect.getsource(worker)
        self.assertNotIn("INSERT INTO vault_items", src)
        self.assertNotIn("save_login", src)

    def test_drain_uses_encrypt_message_for_persistence(self):
                                                                  
                                                                 
        src = inspect.getsource(worker)
        self.assertIn("encrypt_message(text, key)", src)
                                                                        
        self.assertIn("extracted_text_encrypted = TRUE", src)

    def test_drain_marks_file_analysis_states_through_lifecycle(self):
        src = inspect.getsource(worker)
                                           
        self.assertIn("mark_file_analysis_processing", src)
        self.assertIn("mark_file_analysis_analyzed", src)
                                          
        self.assertIn("mark_file_analysis_failed", src)
                                                         
        self.assertIn("mark_file_analysis_unsupported", src)

    def test_drain_caps_per_call_work(self):
                                                                  
                                                         
        self.assertLessEqual(
            worker.DEFAULT_MAX_JOBS_PER_DRAIN, 16,
            "drain default cap must keep chat turns responsive",
        )
        self.assertGreaterEqual(worker.DEFAULT_MAX_JOBS_PER_DRAIN, 1)


class DrainBehaviourWithStubbedDepsTests(unittest.TestCase):


    def test_empty_queue_returns_zeroed_report(self):
        original = va.claim_next_analysis_job
        try:
            va.claim_next_analysis_job = lambda **kw: None                
            report = worker.drain_text_extraction(
                vault_id="vault-1",
                key=b"\x00" * 32,
                max_jobs=4,
            )
        finally:
            va.claim_next_analysis_job = original                
        self.assertEqual(report["processed"], 0)
        self.assertEqual(report["succeeded"], 0)
        self.assertEqual(report["failed"], 0)

    def test_zero_max_jobs_does_no_work(self):
        report = worker.drain_text_extraction(
            vault_id="vault-1",
            key=b"\x00" * 32,
            max_jobs=0,
        )
        self.assertEqual(report["processed"], 0)


class CredentialSearchUsesPersistedExtractedTextTests(unittest.TestCase):


    def test_credential_search_lister_selects_encrypted_text_columns(self):
        import main
        src = inspect.getsource(
            main._list_uploaded_files_for_credential_search,
        )
        self.assertIn("extracted_text", src)
        self.assertIn("extracted_text_encrypted", src)

    def test_credential_search_lister_decrypts_with_key(self):
        import main
        src = inspect.getsource(
            main._list_uploaded_files_for_credential_search,
        )
        self.assertIn("decrypt_message", src)

    def test_drain_writes_to_same_column_credential_search_reads(self):
                                                       
                                                                 
        drain_src = inspect.getsource(worker._persist_extracted_text)
        self.assertIn("UPDATE uploaded_files", drain_src)
        self.assertIn("SET extracted_text = %s", drain_src)
        self.assertIn("extracted_text_encrypted = TRUE", drain_src)


class CredentialSearchContentBeatsFilenameTests(unittest.TestCase):


    def test_content_match_outranks_filename_match(self):
        from vault_inventory import search_files_for_credentials_report
        rows = [
                                                                  
            {
                "id": "filename-only",
                "file_name": "passwords.txt",
                "saved_name": "",
                "relative_path": "",
                "content_type": "text/plain",
                "file_size": 1,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": None,
            },
                                                                
                                              
            {
                "id": "content-strong",
                "file_name": "doculetter.html",
                "saved_name": "",
                "relative_path": "",
                "content_type": "text/html",
                "file_size": 1,
                "asset_type": "file",
                "detected_service": "",
                "created_at": None,
                "extracted_text": (
                    "username: alice@example.com\n"
                    "password: hunter2\n"
                ),
            },
        ]
        report = search_files_for_credentials_report(rows)
        self.assertEqual(report["matches"][0]["file_id"], "content-strong")
        self.assertEqual(report["matches"][0]["confidence"], "strong")
                                   
        self.assertEqual(report["matches"][1]["confidence"], "weak")


if __name__ == "__main__":
    unittest.main()
