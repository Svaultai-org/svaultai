

from __future__ import annotations

import ast
import inspect
import io
import os
import tarfile
import unittest
import zipfile
from typing import Optional
from unittest.mock import patch

import vault_analysis as va
import vault_archive_indexing as ai
import vault_document_purpose as vp
import vault_understanding as vu
import vault_understanding_search as vus


def _build_zip(entries: dict[str, bytes]) -> bytes:

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name)
            zf.writestr(info, content)
    return buf.getvalue()


def _build_tar(entries: dict[str, bytes], *, gzip: bool = False) -> bytes:

    buf = io.BytesIO()
    mode = "w:gz" if gzip else "w:"
    with tarfile.open(fileobj=buf, mode=mode) as tf:
        for name, content in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _migration_0010_source() -> str:
    path = os.path.join(
        os.path.dirname(__file__),
        "migrations", "versions",
        "0010_archive_and_video_source.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class MigrationSchemaGuardTests(unittest.TestCase):
    def setUp(self):
        self.src = _migration_0010_source()

    def test_extends_extracted_text_source_check(self):
        self.assertIn(
            "uploaded_files_extracted_text_source_chk", self.src,
        )
                                                 
        for value in (
            "upload", "worker", "ocr", "transcript",
            "video_transcript", "archive_index",
        ):
            self.assertTrue(
                f'"{value}"' in self.src or f"'{value}'" in self.src,
                f"migration must declare extracted_text_source "
                f"value {value!r}",
            )

    def test_extends_stage_check(self):
        self.assertIn(
            "vault_analysis_jobs_stage_chk", self.src,
        )
        self.assertTrue(
            '"archive_indexing"' in self.src
            or "'archive_indexing'" in self.src,
            "migration must declare the archive_indexing stage",
        )

    def test_is_reversible(self):
        for needle in (
            "DROP CONSTRAINT IF EXISTS uploaded_files_extracted_text_source_chk",
            "DROP CONSTRAINT IF EXISTS vault_analysis_jobs_stage_chk",
        ):
            self.assertIn(needle, self.src)


class StageConstantTests(unittest.TestCase):
    def test_stage_archive_indexing_in_python_stages(self):
        self.assertIn(va.STAGE_ARCHIVE_INDEXING, va.STAGES)

    def test_stage_name_matches_string(self):
        self.assertEqual(
            va.STAGE_ARCHIVE_INDEXING, "archive_indexing",
        )


class SupportsArchiveIndexingTests(unittest.TestCase):
    def test_zip_supported(self):
        self.assertTrue(
            ai.supports_archive_indexing(file_name="backup.zip")
        )

    def test_tar_supported(self):
        self.assertTrue(
            ai.supports_archive_indexing(file_name="files.tar")
        )

    def test_tar_gz_supported(self):
        self.assertTrue(
            ai.supports_archive_indexing(file_name="files.tar.gz")
        )

    def test_tgz_supported(self):
        self.assertTrue(
            ai.supports_archive_indexing(file_name="files.tgz")
        )

    def test_application_zip_mime_supported(self):
        self.assertTrue(
            ai.supports_archive_indexing(
                file_name="unknown",
                content_type="application/zip",
            )
        )

    def test_pdf_not_supported(self):
        self.assertFalse(
            ai.supports_archive_indexing(file_name="doc.pdf")
        )

    def test_image_not_supported(self):
        self.assertFalse(
            ai.supports_archive_indexing(file_name="photo.png")
        )


class PathSafetyFilterTests(unittest.TestCase):
    def test_normal_name_is_safe(self):
        self.assertIsNone(ai._is_unsafe_path("accounts.txt"))

    def test_subdirectory_name_is_safe(self):
        self.assertIsNone(
            ai._is_unsafe_path("subdir/notes.md")
        )

    def test_parent_traversal_rejected(self):
        self.assertIsNotNone(
            ai._is_unsafe_path("../etc/passwd")
        )
        self.assertIsNotNone(
            ai._is_unsafe_path("subdir/../../etc")
        )

    def test_absolute_unix_path_rejected(self):
        self.assertIsNotNone(
            ai._is_unsafe_path("/etc/passwd")
        )

    def test_absolute_windows_path_rejected(self):
        self.assertIsNotNone(
            ai._is_unsafe_path("C:\\Users\\victim")
        )

    def test_unc_path_rejected(self):
        self.assertIsNotNone(
            ai._is_unsafe_path("\\Server\\share")
        )

    def test_null_byte_rejected(self):
        self.assertIsNotNone(
            ai._is_unsafe_path("accounts.txt\x00.png")
        )

    def test_empty_path_rejected(self):
        self.assertIsNotNone(ai._is_unsafe_path(""))


class ZipWalkerTests(unittest.TestCase):
    def test_happy_path_aggregates_inner_text(self):
        archive = _build_zip({
            "accounts.txt": b"AOL\nalice@example.com\nhunter2",
            "notes.md":     b"# Meeting Notes\n\nWells Fargo call today.",
            "config.json":  b'{"api": "https://example.com"}',
        })
        report = ai.index_archive(archive, file_name="backup.zip")
        self.assertTrue(report["ok"])
        self.assertEqual(report["format"], "zip")
        self.assertEqual(report["inner_file_count"], 3)
        self.assertEqual(report["rejected_count"], 0)
                                                           
                                                               
        agg = report["aggregated_text"]
        self.assertIn("accounts.txt", agg)
        self.assertIn("notes.md", agg)
        self.assertIn("config.json", agg)
                                                                
        self.assertIn("Wells Fargo", agg)

    def test_binary_inner_files_listed_but_not_read(self):
        archive = _build_zip({
            "notes.md":   b"# Plan",
            "photo.jpg":  b"\xff\xd8\xff\xe0fake-jpeg",
        })
        report = ai.index_archive(archive, file_name="mix.zip")
                                        
        names = [e["name"] for e in report["entries"]]
        self.assertIn("notes.md", names)
        self.assertIn("photo.jpg", names)
                                            
        photo = next(e for e in report["entries"] if e["name"] == "photo.jpg")
        self.assertFalse(photo["is_text"])
                                                                 
        self.assertNotIn(b"\xff\xd8".decode("utf-8", errors="replace"),
                         report["aggregated_text"])

    def test_path_traversal_entry_rejected(self):
                                            
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../etc/passwd", b"safe")
            zf.writestr("good.txt", b"safe content")
        report = ai.index_archive(buf.getvalue(), file_name="bad.zip")
        self.assertTrue(report["ok"])
        self.assertEqual(report["inner_file_count"], 1)
        self.assertEqual(report["rejected_count"], 1)
        rejected_names = [name for name, _ in report["rejected_paths"]]
        self.assertIn("../etc/passwd", rejected_names)

    def test_absolute_path_entry_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/passwd", b"oof")
            zf.writestr("ok.txt", b"safe")
        report = ai.index_archive(buf.getvalue(), file_name="bad.zip")
        self.assertEqual(report["inner_file_count"], 1)
        self.assertEqual(report["rejected_count"], 1)

    def test_corrupt_zip_returns_failed_report_not_crash(self):
        report = ai.index_archive(
            b"NOT A ZIP", file_name="bad.zip",
        )
        self.assertFalse(report["ok"])
        self.assertEqual(report["format"], "zip")
        self.assertIsNotNone(report["error"])

    def test_empty_bytes_raises(self):
        with self.assertRaises(ai.ArchiveIndexingError):
            ai.index_archive(b"", file_name="empty.zip")


class TarWalkerTests(unittest.TestCase):
    def test_tar_happy_path(self):
        archive = _build_tar({
            "report.txt": b"Some text",
            "data.json":  b"{}",
        })
        report = ai.index_archive(archive, file_name="files.tar")
        self.assertTrue(report["ok"])
        self.assertEqual(report["format"], "tar")
        self.assertEqual(report["inner_file_count"], 2)

    def test_tar_gz_happy_path(self):
        archive = _build_tar(
            {"a.txt": b"Hello"},
            gzip=True,
        )
        report = ai.index_archive(archive, file_name="files.tar.gz")
        self.assertTrue(report["ok"])
        self.assertEqual(report["format"], "tar.gz")

    def test_tar_symlink_rejected(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:") as tf:
                                    
            info = tarfile.TarInfo("evil_link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
                         
            normal = tarfile.TarInfo("ok.txt")
            normal.size = 5
            tf.addfile(normal, io.BytesIO(b"hello"))
        report = ai.index_archive(buf.getvalue(), file_name="bad.tar")
        self.assertTrue(report["ok"])
        self.assertEqual(report["inner_file_count"], 1)
                                                    
        self.assertGreater(report["rejected_count"], 0)
        rejected_names = [n for n, _ in report["rejected_paths"]]
        self.assertIn("evil_link", rejected_names)


class ZipBombCapsTests(unittest.TestCase):
    def test_entry_cap_truncates(self):
                                                            
                                                                   
        with patch.object(ai, "MAX_ENTRIES", 3):
            archive = _build_zip({
                "a.txt": b"a", "b.txt": b"b",
                "c.txt": b"c", "d.txt": b"d",
            })
            report = ai.index_archive(
                archive, file_name="many.zip",
            )
        self.assertTrue(report["ok"])
        self.assertTrue(report["truncated_by_entry_cap"])
        self.assertLessEqual(report["inner_file_count"], 3)

    def test_per_inner_file_cap_rejects_huge_entry(self):
        with patch.object(ai, "MAX_PER_INNER_FILE_BYTES", 10):
            archive = _build_zip({
                "big.txt": b"x" * 1000,
                "small.txt": b"ok",
            })
            report = ai.index_archive(
                archive, file_name="big.zip",
            )
                                              
        self.assertEqual(report["inner_file_count"], 1)
        self.assertEqual(report["rejected_count"], 1)
        rejected_names = [n for n, _ in report["rejected_paths"]]
        self.assertIn("big.txt", rejected_names)

    def test_total_uncompressed_cap_truncates(self):
        with patch.object(ai, "MAX_TOTAL_UNCOMPRESSED_BYTES", 10):
            archive = _build_zip({
                "a.txt": b"x" * 8,
                "b.txt": b"x" * 8,
                "c.txt": b"x" * 8,
            })
            report = ai.index_archive(
                archive, file_name="big.zip",
            )
                                              
        self.assertTrue(report["truncated_by_size_cap"])
        self.assertLess(report["inner_file_count"], 3)

    def test_aggregated_text_cap_truncates(self):
        with patch.object(ai, "MAX_AGGREGATED_TEXT_BYTES", 100):
                                                              
                                                         
            archive = _build_zip({
                "a.txt": b"x" * 500,
                "b.txt": b"y" * 500,
            })
            report = ai.index_archive(
                archive, file_name="lots.zip",
            )
        self.assertTrue(report["truncated_by_text_cap"])
        self.assertLessEqual(len(report["aggregated_text"]), 100)


class DefaultStagesRoutingTests(unittest.TestCase):
    def test_zip_routes_to_archive_indexing(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="backup.zip"),
            [va.STAGE_ARCHIVE_INDEXING],
        )

    def test_tar_routes_to_archive_indexing(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="files.tar"),
            [va.STAGE_ARCHIVE_INDEXING],
        )

    def test_tar_gz_routes_to_archive_indexing(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="files.tar.gz"),
            [va.STAGE_ARCHIVE_INDEXING],
        )

    def test_tgz_routes_to_archive_indexing(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="files.tgz"),
            [va.STAGE_ARCHIVE_INDEXING],
        )

    def test_zip_mime_routes_to_archive_indexing(self):
        self.assertEqual(
            va.default_stages_for_file(
                file_name="unknown",
                content_type="application/zip",
            ),
            [va.STAGE_ARCHIVE_INDEXING],
        )

    def test_pdf_still_routes_to_text_extraction(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="doc.pdf"),
            [va.STAGE_TEXT_EXTRACTION],
        )

    def test_audio_still_routes_to_audio(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="memo.mp3"),
            [va.STAGE_AUDIO_TRANSCRIPTION],
        )

    def test_video_still_routes_to_video(self):
        self.assertEqual(
            va.default_stages_for_file(file_name="trip.mp4"),
            [va.STAGE_VIDEO_TRANSCRIPTION],
        )


class WorkerSourceGuardTests(unittest.TestCase):
    def test_worker_exists_and_drains_via_claim(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw.drain_archive_indexing)
        self.assertIn("claim_next_analysis_job", src)
        mod_src = inspect.getsource(vaw)
        self.assertIn("STAGE_ARCHIVE_INDEXING", mod_src)
        self.assertIn("_HANDLED_STAGE", src)

    def test_worker_calls_index_archive(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw._process_one_archive_job)
        self.assertIn("index_archive", src)

    def test_worker_encrypts_before_persist(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw._process_one_archive_job)
        encrypt_idx = src.find("encrypt_message")
        persist_idx = src.find("_persist_extracted_text")
        self.assertGreater(encrypt_idx, -1)
        self.assertGreater(persist_idx, -1)
        self.assertLess(
            encrypt_idx, persist_idx,
            "aggregated text MUST be encrypted before being "
            "persisted",
        )

    def test_worker_persists_with_source_archive_index(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw._process_one_archive_job)
        self.assertIn('source="archive_index"', src)

    def test_worker_drops_plaintext_bytes_after_use(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw._process_one_archive_job)
        self.assertIn("plaintext_bytes = None", src)
        self.assertIn('aggregated_text = ""', src)

    def test_worker_enqueues_understanding_after_success(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw._process_one_archive_job)
        analyzed_idx = src.find("mark_file_analysis_analyzed")
        enqueue_idx = src.find(
            "enqueue_understanding_after_text_extraction"
        )
        self.assertGreater(analyzed_idx, -1)
        self.assertGreater(enqueue_idx, -1)
        self.assertLess(analyzed_idx, enqueue_idx)

    def test_worker_calls_stale_helpers_after_success(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw._process_one_archive_job)
        self.assertIn(
            "mark_stale_understandings_for_changed_text", src,
        )
        self.assertIn(
            "mark_stale_embeddings_for_changed_text", src,
        )


class SafetyFloorTests(unittest.TestCase):
    def test_archive_module_never_executes_inner_content(self):
                                                              
                                                         
        src = inspect.getsource(ai)
        try:
            tree = ast.parse(src)
            doc = ast.get_docstring(tree) or ""
        except Exception:
            doc = ""
        code_only = src.replace(doc, "") if doc else src
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(
                forbidden, code_only,
                f"archive module MUST NOT use {forbidden} on "
                "inner content — uploaded archives are read as "
                "data only",
            )

    def test_worker_never_executes_user_content(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)

    def test_worker_does_not_touch_vault_items_table(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw)
        try:
            tree = ast.parse(src)
            doc = ast.get_docstring(tree) or ""
        except Exception:
            doc = ""
        code_only = src.replace(doc, "") if doc else src
        self.assertNotIn("INSERT INTO vault_items", code_only)
        self.assertNotIn("vault_items", code_only)

    def test_worker_logs_do_not_include_aggregated_text(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw)
        for forbidden in (
            'logger.info("%s", aggregated_text',
            'logger.info("%s", plaintext',
            'logger.info("%s", inner_bytes',
            'logger.exception("%s", aggregated_text',
            'logger.exception("%s", plaintext',
        ):
            self.assertNotIn(forbidden, src)

    def test_archive_module_logs_do_not_include_inner_bytes(self):
        src = inspect.getsource(ai)
        for forbidden in (
            'logger.info("%s", inner_bytes',
            'logger.info("%s", aggregated_text',
            'logger.info("%s", file_bytes',
            'logger.exception("%s", inner_bytes',
            'logger.exception("%s", aggregated_text',
        ):
            self.assertNotIn(forbidden, src)


class ChatHandlerWiringTests(unittest.TestCase):
    def test_chat_handler_runs_archive_drain_after_video(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        video_idx = src.find("drain_video_transcription")
        archive_idx = src.find("drain_archive_indexing")
        self.assertGreater(video_idx, -1)
        self.assertGreater(archive_idx, -1)
        self.assertLess(
            video_idx, archive_idx,
            "archive drain runs after video (no strict ordering "
            "requirement; both feed the same lifecycle)",
        )

    def test_chat_handler_runs_archive_drain_before_understanding(self):
        import main
        src = inspect.getsource(main.chat_endpoint)
        archive_idx = src.find("drain_archive_indexing")
        understanding_idx = src.find("drain_file_understanding")
        self.assertGreater(archive_idx, -1)
        self.assertGreater(understanding_idx, -1)
        self.assertLess(
            archive_idx, understanding_idx,
            "freshly indexed archives must feed the understanding "
            "drain in the SAME chat turn",
        )


class ArchiveSearchIntegrationTests(unittest.TestCase):
    def test_archive_aggregated_text_drives_topic_detection(self):


        archive = _build_zip({
            "notes.md": b"Today I called Wells Fargo about my bank statement.",
            "todo.txt": b"Pay rent.",
        })
        report = ai.index_archive(archive, file_name="backup.zip")
        record = vu.build_understanding(
            report["aggregated_text"], file_name="backup.zip",
        )
                                                    
        self.assertIn("finance", record["topics"])
                                                  
        names = (record["entities"] or {}).get("names") or []
        self.assertTrue(any("Wells Fargo" in n for n in names))

    def test_archive_with_credentials_classified_correctly(self):


        archive = _build_zip({
            "accounts.txt": "\n".join([
                "AOL", "alice@example.com", "Patrick62109",
                "Apple", "bob@example.com", "MKSherm81765",
                "American Express", "carol@example.com", "e&t082826",
                "Wells Fargo", "dan@example.com", "sunshine6856",
                "Gmail", "erin@example.com", "loul82!Bridge",
            ]).encode("utf-8"),
        })
        report = ai.index_archive(archive, file_name="backup.zip")
        record = vu.build_understanding(
            report["aggregated_text"], file_name="backup.zip",
        )
        self.assertEqual(
            record["document_purpose"],
            vp.PURPOSE_SAVED_LOGIN_LIST,
        )
                                                              
                           
        for sentinel in ("Patrick62109", "MKSherm81765",
                         "e&t082826", "sunshine6856",
                         "loul82!Bridge"):
            self.assertNotIn(sentinel, record["summary"] or "")
            self.assertNotIn(sentinel, record["safe_preview"] or "")
            terms = " ".join(record["searchable_terms"] or [])
            self.assertNotIn(sentinel, terms)


class InnerTextExtensionAllowListTests(unittest.TestCase):
    def test_script_extensions_treated_as_text(self):
                                                           
                                                             
        for ext in ("sh", "py", "js", "rb", "go", "rs"):
            self.assertTrue(
                ai._is_text_inner_extension(f"x.{ext}"),
                f".{ext} should be in the text allow-list — "
                "treated as TEXT (not executed)",
            )

    def test_binary_extensions_not_text(self):
        for ext in ("jpg", "png", "pdf", "docx", "mp4",
                    "exe", "dll", "so"):
            self.assertFalse(
                ai._is_text_inner_extension(f"x.{ext}"),
                f".{ext} should NOT be in the text allow-list",
            )

    def test_no_extension_not_text(self):
        self.assertFalse(ai._is_text_inner_extension("nodot"))


class AvailabilityFlagTests(unittest.TestCase):
    def test_archive_available_is_true_stdlib_backed(self):
                                                      
        self.assertTrue(ai.ARCHIVE_AVAILABLE)
        self.assertEqual(ai.ARCHIVE_BACKEND, "stdlib-zipfile-tarfile")


class FileExtensionHelperTests(unittest.TestCase):
    def test_simple_extension(self):
        self.assertEqual(ai._file_extension("backup.zip"), "zip")

    def test_uppercase_normalised(self):
        self.assertEqual(ai._file_extension("BACKUP.ZIP"), "zip")

    def test_double_extension_detected(self):
        self.assertTrue(ai._is_double_extension("files.tar.gz"))
        self.assertFalse(ai._is_double_extension("plain.gz"))


if __name__ == "__main__":
    unittest.main()
