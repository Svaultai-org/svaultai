

from __future__ import annotations

import inspect
import io
import json
import os
import unittest
import zipfile
from typing import Optional
from unittest.mock import patch

import vault_analysis as va
import vault_archive_indexing as ai
import vault_document_purpose as vp
import vault_understanding as vu
import vault_understanding_search as vus


def _migration_0011_source() -> str:
    path = os.path.join(
        os.path.dirname(__file__),
        "migrations", "versions",
        "0011_archive_signals.py",
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _build_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            info = zipfile.ZipInfo(name)
            zf.writestr(info, content)
    return buf.getvalue()


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "Patrick62109", "MKSherm81765", "e&t082826",
    "sunshine6856", "loul82!Bridge",
)


def _make_archive_row(
    *,
    file_id: str,
    file_name: str,
    purpose: str = "generic_text",
    purpose_label: str = "general text",
    topics: Optional[list] = None,
    entities: Optional[dict] = None,
    categories: Optional[list] = None,
    archive_signals: Optional[dict] = None,
    understanding_status: str = "ready",
) -> dict:

    return {
        "file_id":              file_id,
        "file_name":            file_name,
        "saved_name":           None,
        "relative_path":        None,
        "content_type":         "application/zip",
        "asset_type":           "archive",
        "extracted_text":       None,
        "extracted_text_encrypted": None,
        "understanding_status": understanding_status,
        "document_purpose":     purpose,
        "purpose_label":        purpose_label,
        "summary_encrypted":    None,
        "safe_preview_encrypted": None,
        "topics_jsonb":         topics or [],
        "entities_jsonb":       entities or {},
        "dates_jsonb":          [],
        "detected_categories_jsonb": categories or [],
        "searchable_terms_jsonb": [],
        "archive_signals_jsonb": archive_signals or {},
        "embedding_status":     None,
        "embedding_model":      None,
        "embedding_dim":        0,
        "embedding_vector_text": None,
        "embedding_vector_decoded": None,
    }


class MigrationSchemaGuardTests(unittest.TestCase):
    def setUp(self):
        self.src = _migration_0011_source()

    def test_adds_archive_signals_column(self):
        self.assertIn("archive_signals_jsonb", self.src)
        self.assertIn("ADD COLUMN", self.src)
        self.assertIn("JSONB", self.src)

    def test_default_is_empty_object(self):
        self.assertIn("'{}'::jsonb", self.src)

    def test_reversible(self):
        self.assertIn(
            "DROP COLUMN IF EXISTS archive_signals_jsonb", self.src,
        )


class DetectInnerFileSignalsTests(unittest.TestCase):
    def test_credential_list_classified(self):
        text = "\n".join([
            "AOL", "alice@example.com", "Patrick62109",
            "Apple", "bob@example.com", "MKSherm81765",
            "Wells Fargo", "carol@example.com", "e&t082826",
            "Gmail", "dan@example.com", "sunshine6856",
        ])
        sig = vu.detect_inner_file_signals(
            text, file_name="accounts.txt",
        )
        self.assertEqual(sig["path"], "accounts.txt")
        self.assertTrue(sig["is_text"])
        self.assertEqual(sig["purpose"], vp.PURPOSE_SAVED_LOGIN_LIST)
        self.assertTrue(sig["is_credential_bearing"])

    def test_credential_values_never_in_signal_output(self):
        text = "\n".join([
            "AOL", "alice@example.com", "Patrick62109",
            "Apple", "bob@example.com", "MKSherm81765",
        ])
        sig = vu.detect_inner_file_signals(
            text, file_name="logins.txt",
        )
        payload = json.dumps(sig)
        for sentinel in SENTINELS:
            self.assertNotIn(
                sentinel, payload,
                f"sentinel {sentinel!r} leaked into "
                "detect_inner_file_signals output",
            )

    def test_entity_extraction(self):
        text = (
            "Today I called Wells Fargo about my bank statement."
        )
        sig = vu.detect_inner_file_signals(
            text, file_name="notes.md",
        )
        names = sig["entity_names"]
        self.assertTrue(
            any("Wells Fargo" in n for n in names),
            f"Wells Fargo should appear in entity_names; got {names!r}",
        )

    def test_topic_extraction(self):
        text = (
            "Tax year 2023. Form W-2 attached. Schedule B."
        )
        sig = vu.detect_inner_file_signals(
            text, file_name="tax_2023.txt",
        )
        self.assertIn("taxes", sig["topics"])

    def test_language_detection_from_path(self):
        sig = vu.detect_inner_file_signals(
            "print('hello')", file_name="scripts/deploy.py",
        )
        self.assertEqual(sig["language"], "Python")

    def test_no_language_for_plain_text(self):
        sig = vu.detect_inner_file_signals(
            "hello", file_name="notes.txt",
        )
        self.assertIsNone(sig["language"])

    def test_empty_text_returns_binary_shape(self):
        sig = vu.detect_inner_file_signals(
            "", file_name="image.png",
        )
        self.assertFalse(sig["is_text"])
        self.assertEqual(sig["size_chars"], 0)
        self.assertEqual(sig["topics"], [])
        self.assertEqual(sig["entity_names"], [])


class IndexerInnerFileSignalsTests(unittest.TestCase):
    def test_inner_file_signals_populated_for_text_entries(self):
        archive = _build_zip({
            "notes.md":     b"Wells Fargo mentioned here.",
            "tax_2023.txt": b"Tax year 2023. Form W-2 attached.",
        })
        report = ai.index_archive(archive, file_name="backup.zip")
        self.assertTrue(report["ok"])
        paths = [s["path"] for s in report["inner_file_signals"]]
        self.assertIn("notes.md", paths)
        self.assertIn("tax_2023.txt", paths)

    def test_binary_entries_not_in_inner_file_signals(self):
        archive = _build_zip({
            "notes.md":   b"Hello",
            "photo.jpg":  b"\xff\xd8\xff\xe0fake-jpeg",
        })
        report = ai.index_archive(archive, file_name="mix.zip")
        paths = [s["path"] for s in report["inner_file_signals"]]
        self.assertIn("notes.md", paths)
        self.assertNotIn("photo.jpg", paths)

    def test_build_archive_signals_compact_payload(self):
        archive = _build_zip({
            "notes.md": b"Wells Fargo today.",
        })
        report = ai.index_archive(archive, file_name="backup.zip")
        payload = ai.build_archive_signals(report)
        self.assertEqual(payload["format"], "zip")
        self.assertEqual(payload["inner_file_count"], 1)
        self.assertEqual(payload["rejected_count"], 0)
        self.assertEqual(len(payload["inner_files"]), 1)
                                                          
                                                             
        for key in ("truncated_by_entry_cap",
                    "truncated_by_size_cap",
                    "truncated_by_text_cap"):
            self.assertIn(key, payload)

    def test_archive_signals_never_carries_raw_text(self):


        archive = _build_zip({
            "notes.md": b"Wells Fargo today. UNIQUE_RAW_BODY_MARKER",
            "accounts.txt": "\n".join([
                "AOL", "alice@example.com", "Patrick62109",
            ]).encode("utf-8"),
        })
        report = ai.index_archive(archive, file_name="backup.zip")
        payload = ai.build_archive_signals(report)
        serialised = json.dumps(payload)
                            
        self.assertIn("notes.md", serialised)
                               
        self.assertNotIn("UNIQUE_RAW_BODY_MARKER", serialised)
                           
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, serialised)


class WorkerWiringTests(unittest.TestCase):
    def test_archive_worker_builds_archive_signals_after_persist(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw._process_one_archive_job)
        self.assertIn("build_archive_signals", src)
                                                          
        analyzed_idx = src.find("mark_file_analysis_analyzed")
        build_idx = src.find("build_archive_signals")
        self.assertGreater(analyzed_idx, -1)
        self.assertGreater(build_idx, -1)
        self.assertLess(analyzed_idx, build_idx)

    def test_archive_worker_passes_metadata_to_enqueue(self):
        import vault_archive_worker as vaw
        src = inspect.getsource(vaw._process_one_archive_job)
                                                                
        self.assertIn("metadata={\"archive_signals\":", src)

    def test_enqueue_understanding_accepts_metadata_kwarg(self):
        import vault_understanding_worker as vuw
        sig = inspect.signature(
            vuw.enqueue_understanding_after_text_extraction
        )
        self.assertIn("metadata", sig.parameters)

    def test_understanding_worker_reads_archive_signals_from_metadata(self):
        import vault_understanding_worker as vuw
        src = inspect.getsource(vuw._process_one_understanding_job)
                                                           
                                                      
        self.assertIn("archive_signals", src)
        self.assertIn("metadata_jsonb", src)
                                                             
        self.assertIn("archive_signals=archive_signals", src)


class BuildUnderstandingArchiveSignalsTests(unittest.TestCase):
    def test_record_carries_archive_signals(self):
        signals = {
            "format": "zip",
            "inner_file_count": 2,
            "rejected_count": 0,
            "inner_files": [
                {"path": "notes.md", "is_text": True,
                 "entity_names": ["Wells Fargo"]},
            ],
        }
        record = vu.build_understanding(
            "Wells Fargo bank statement note",
            file_name="backup.zip",
            archive_signals=signals,
        )
        self.assertEqual(
            record["archive_signals"]["format"], "zip",
        )

    def test_default_archive_signals_is_empty_dict(self):
        record = vu.build_understanding(
            "some text", file_name="doc.pdf",
        )
        self.assertEqual(record["archive_signals"], {})

    def test_unsupported_branch_also_carries_archive_signals(self):
        signals = {"format": "zip", "inner_file_count": 0}
        record = vu.build_understanding(
            "", file_name="empty.zip", archive_signals=signals,
        )
        self.assertEqual(record["archive_signals"], signals)


class UpsertGetArchiveSignalsTests(unittest.TestCase):
    def test_upsert_sql_includes_archive_signals_jsonb(self):
        src = inspect.getsource(vu.upsert_understanding)
        self.assertIn("archive_signals_jsonb", src)

    def test_get_sql_includes_archive_signals_jsonb(self):
        src = inspect.getsource(vu.get_understanding_for_file)
        self.assertIn("archive_signals_jsonb", src)


class ArchiveReasonBuilderTests(unittest.TestCase):
    def _archive_signals(self, **kwargs) -> dict:

        base = {
            "format": "zip", "inner_file_count": 1,
            "rejected_count": 0,
            "truncated_by_entry_cap": False,
            "truncated_by_size_cap":  False,
            "truncated_by_text_cap":  False,
            "inner_files": [],
        }
        base.update(kwargs)
        return base

    def test_single_inner_file_entity_match(self):
        signals = self._archive_signals(inner_files=[
            {
                "path": "notes.md", "is_text": True,
                "entity_names": ["Wells Fargo"], "topics": [],
                "is_credential_bearing": False, "language": None,
            },
        ])
        rows = [_make_archive_row(
            file_id="zip-1", file_name="backup.zip",
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        self.assertEqual(len(report["results"]), 1)
        m = report["results"][0]
        self.assertIn("archive content match", m["match_reason"])
        self.assertIn("notes.md", m["match_reason"])
        self.assertIn("Wells Fargo", m["match_reason"])

    def test_multi_inner_file_entity_match_aggregated(self):
        signals = self._archive_signals(inner_files=[
            {"path": "notes.md",     "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
            {"path": "letter.txt",   "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
            {"path": "subdir/x.txt", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
        ])
        rows = [_make_archive_row(
            file_id="zip-2", file_name="backup.zip",
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        m = report["results"][0]
        self.assertIn("3 inner files mention Wells Fargo",
                      m["match_reason"])

    def test_credential_inner_file_reason(self):
        signals = self._archive_signals(inner_files=[
            {"path": "accounts.txt", "is_text": True,
             "entity_names": [],
             "topics": ["credentials"],
             "is_credential_bearing": True,
             "purpose": vp.PURPOSE_SAVED_LOGIN_LIST,
             "purpose_label": "saved login list",
             "language": None},
        ])
        rows = [_make_archive_row(
            file_id="zip-3", file_name="backup.zip",
            purpose=vp.PURPOSE_SAVED_LOGIN_LIST,
            purpose_label="saved login list",
            topics=["credentials"],
            categories=["security"],
            archive_signals=signals,
        )]
                                                              
                                                      
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "saved logins",
            )
        m = report["results"][0]
        self.assertIn("archive content match", m["match_reason"])
        self.assertIn("accounts.txt", m["match_reason"])
        self.assertIn("saved-login records", m["match_reason"])

    def test_topic_inner_file_reason(self):
        signals = self._archive_signals(inner_files=[
            {"path": "tax_2023.txt", "is_text": True,
             "entity_names": [], "topics": ["taxes"],
             "is_credential_bearing": False, "language": None},
        ])
        rows = [_make_archive_row(
            file_id="zip-4", file_name="backup.zip",
            topics=["taxes"], categories=["tax"],
            archive_signals=signals,
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "show tax documents",
            )
        m = report["results"][0]
        self.assertIn("archive content match", m["match_reason"])
        self.assertIn("tax_2023.txt", m["match_reason"])
        self.assertIn("taxes", m["match_reason"])

    def test_code_inner_file_reason(self):
        signals = self._archive_signals(inner_files=[
            {"path": "scripts/deploy.py", "is_text": True,
             "entity_names": [], "topics": [],
             "is_credential_bearing": False,
             "language": "Python"},
                                                      
            {"path": "README.md", "is_text": True,
             "entity_names": [], "topics": [],
             "is_credential_bearing": False, "language": None},
        ])
        rows = [_make_archive_row(
            file_id="zip-5", file_name="archive.zip",
            archive_signals=signals,
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "find scripts in my archive",
            )
        m = report["results"][0]
        self.assertIn("archive content match", m["match_reason"])
        self.assertIn("scripts/deploy.py", m["match_reason"])
        self.assertIn("Python code", m["match_reason"])

    def test_filename_tier_match_NOT_overridden(self):


        signals = self._archive_signals(inner_files=[
            {"path": "notes.md", "is_text": True,
             "entity_names": [], "topics": [],
             "is_credential_bearing": False, "language": None},
        ])
                                                           
                                                              
        rows = [_make_archive_row(
            file_id="zip-6", file_name="rare_unique_word.zip",
            archive_signals=signals,
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "rare_unique_word",
            )
        if report["results"]:
            m = report["results"][0]
            self.assertNotIn(
                "archive content match", m["match_reason"],
                "filename-only matches should keep the generic "
                "filename reason",
            )

    def test_is_archive_match_flag_set_when_reason_overridden(self):
        signals = self._archive_signals(inner_files=[
            {"path": "notes.md", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
        ])
        rows = [_make_archive_row(
            file_id="zip-7", file_name="backup.zip",
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        m = report["results"][0]
        self.assertTrue(m.get("is_archive_match"))

    def test_empty_archive_signals_falls_back_to_regular_reason(self):
                                                                 
                                     
        rows = [_make_archive_row(
            file_id="zip-8", file_name="backup.zip",
            entities={"names": ["Wells Fargo"]},
            archive_signals={},
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        m = report["results"][0]
        self.assertNotIn("archive content match", m["match_reason"])
                                                        
        self.assertIn("entity match", m["match_reason"])


class ArchiveReasonSafetyTests(unittest.TestCase):
    def test_credential_reason_never_includes_password_value(self):
                                                                  
                                                                
        signals = {
            "format": "zip", "inner_file_count": 1,
            "rejected_count": 0,
            "truncated_by_entry_cap": False,
            "truncated_by_size_cap":  False,
            "truncated_by_text_cap":  False,
            "inner_files": [
                {
                    "path": "accounts.txt", "is_text": True,
                    "entity_names": [],
                    "topics": ["credentials"],
                    "is_credential_bearing": True,
                    "purpose": vp.PURPOSE_SAVED_LOGIN_LIST,
                    "purpose_label": "saved login list",
                    "language": None,
                },
            ],
        }
        rows = [_make_archive_row(
            file_id="zip-9", file_name="backup.zip",
            purpose=vp.PURPOSE_SAVED_LOGIN_LIST,
            purpose_label="saved login list",
            topics=["credentials"],
            categories=["security"],
            archive_signals=signals,
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "saved logins",
            )
        m = report["results"][0]
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, m["match_reason"])

    def test_rejected_paths_never_surface_as_trusted_match(self):


        signals = {
            "format": "zip", "inner_file_count": 1,
            "rejected_count": 1,
            "truncated_by_entry_cap": False,
            "truncated_by_size_cap":  False,
            "truncated_by_text_cap":  False,
            "inner_files": [
                {"path": "safe.md", "is_text": True,
                 "entity_names": ["Wells Fargo"], "topics": [],
                 "is_credential_bearing": False, "language": None},
            ],
                                                         
                                                               
        }
        rows = [_make_archive_row(
            file_id="zip-10", file_name="backup.zip",
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )]
        with patch.object(vus, "_fetch_search_rows", return_value=rows):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        m = report["results"][0]
                                                            
        self.assertIn("safe.md", m["match_reason"])
        self.assertNotIn("..", m["match_reason"])
        self.assertNotIn("/etc/", m["match_reason"])

    def test_build_archive_signals_does_not_include_rejected_paths(self):


        archive = _build_zip({"safe.md": b"hello"})
        report = ai.index_archive(archive, file_name="backup.zip")
        payload = ai.build_archive_signals(report)
        self.assertNotIn("rejected_paths", payload)


class EndToEndIndexThenBuildTests(unittest.TestCase):
    def test_wells_fargo_archive_understanding_carries_signals(self):
        archive = _build_zip({
            "notes.md":  b"Today I called Wells Fargo about my bank statement.",
            "todo.txt":  b"Pay rent on the 5th.",
        })
        report = ai.index_archive(archive, file_name="backup.zip")
        payload = ai.build_archive_signals(report)
                                                         
                                                                 
        record = vu.build_understanding(
            report["aggregated_text"],
            file_name="backup.zip",
            archive_signals=payload,
        )
                                                           
        self.assertEqual(
            record["archive_signals"]["format"], "zip",
        )
                                                              
        inners = record["archive_signals"]["inner_files"]
        self.assertTrue(
            any(
                "Wells Fargo" in (f.get("entity_names") or [])
                for f in inners
                if isinstance(f, dict)
            )
        )


if __name__ == "__main__":
    unittest.main()
