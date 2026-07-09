

from __future__ import annotations

import inspect
import json
import unittest
from typing import Optional
from unittest.mock import patch

import vault_document_purpose as vp
import vault_understanding_search as vus


SENTINELS = (
    "hunter2", "SUPERSECRET-XYZ-123",
    "Patrick62109", "MKSherm81765", "e&t082826",
    "sunshine6856", "loul82!Bridge",
    "plaintext-inner-file-leak", "archive-internal-secret",
)


def _make_archive_row(
    *,
    file_id: str = "zip-1",
    file_name: str = "backup.zip",
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


def _archive_signals(*, inner_files: list) -> dict:
    return {
        "format":                  "zip",
        "inner_file_count":        len(inner_files),
        "rejected_count":          0,
        "truncated_by_entry_cap":  False,
        "truncated_by_size_cap":   False,
        "truncated_by_text_cap":   False,
        "inner_files":             inner_files,
    }


class HelperSourceGuardTests(unittest.TestCase):
    def test_helper_exists(self):
        self.assertTrue(
            hasattr(vus, "_maybe_archive_match_details"),
        )

    def test_helper_uses_safe_dict(self):
        src = inspect.getsource(vus._maybe_archive_match_details)
                                                           
                                                          
        self.assertIn("_safe_dict", src)
        self.assertIn("archive_signals_jsonb", src)

    def test_helper_iterates_inner_files_not_rejected_paths(self):
        import ast
        src = inspect.getsource(vus._maybe_archive_match_details)
                                                             
                                                           
        try:
            tree = ast.parse(src.lstrip())
            fn = tree.body[0]
            doc = ast.get_docstring(fn) or ""
        except Exception:
            doc = ""
        code_only = src.replace(doc, "") if doc else src
        self.assertIn("inner_files", code_only)
        self.assertNotIn("rejected_paths", code_only)

    def test_helper_kinds_are_closed_set(self):
        src = inspect.getsource(vus._maybe_archive_match_details)
                                                         
        for kind in (
            vus._INNER_KIND_ENTITY,
            vus._INNER_KIND_CREDENTIALS,
            vus._INNER_KIND_CODE,
            vus._INNER_KIND_TOPIC,
        ):
            self.assertIn(kind, src)

    def test_helper_caps_inner_matches_shipped(self):
        src = inspect.getsource(vus._maybe_archive_match_details)
        self.assertIn("_MAX_INNER_MATCHES_SHIPPED", src)
        self.assertIn("total_inner_matches", src)

    def test_helper_never_executes_user_content(self):
        src = inspect.getsource(vus._maybe_archive_match_details)
        for forbidden in ("eval(", "exec(", "subprocess",
                          "os.system(", "popen("):
            self.assertNotIn(forbidden, src)


class InnerAttributionTests(unittest.TestCase):
    def test_entity_kind_with_canonical_name(self):
        signals = _archive_signals(inner_files=[
            {"path": "notes.md", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
        ])
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        details = report["results"][0]["archive_match_details"]
        self.assertIsNotNone(details)
        self.assertEqual(len(details["inner_matches"]), 1)
        m = details["inner_matches"][0]
        self.assertEqual(m["path"], "notes.md")
        self.assertEqual(m["kind"], "entity")
                                                            
        self.assertEqual(m["reason"], "mentions Wells Fargo")
        self.assertEqual(m["confidence"], "strong")

    def test_credentials_kind_when_query_hits_security(self):
        signals = _archive_signals(inner_files=[
            {"path": "accounts.txt", "is_text": True,
             "entity_names": [], "topics": ["credentials"],
             "is_credential_bearing": True,
             "purpose": vp.PURPOSE_SAVED_LOGIN_LIST,
             "purpose_label": "saved login list",
             "language": None},
        ])
        row = _make_archive_row(
            purpose=vp.PURPOSE_SAVED_LOGIN_LIST,
            purpose_label="saved login list",
            topics=["credentials"],
            categories=["security"],
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "saved logins",
            )
        details = report["results"][0]["archive_match_details"]
        self.assertIsNotNone(details)
        m = details["inner_matches"][0]
        self.assertEqual(m["path"], "accounts.txt")
        self.assertEqual(m["kind"], "credentials")
        self.assertEqual(
            m["reason"], "appears to contain saved-login records",
        )
        self.assertEqual(m["confidence"], "strong")

    def test_code_kind_with_language(self):
        signals = _archive_signals(inner_files=[
            {"path": "scripts/deploy.py", "is_text": True,
             "entity_names": [], "topics": [],
             "is_credential_bearing": False,
             "language": "Python"},
        ])
                                                             
                                                             
        row = _make_archive_row(
            file_name="archive.zip",
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "find scripts in my archive",
            )
        details = report["results"][0]["archive_match_details"]
        self.assertIsNotNone(details)
        m = details["inner_matches"][0]
        self.assertEqual(m["path"], "scripts/deploy.py")
        self.assertEqual(m["kind"], "code")
        self.assertEqual(m["reason"], "contains Python code")
        self.assertEqual(m["confidence"], "medium")

    def test_topic_kind_via_category_map(self):
                                                            
                                                      
        signals = _archive_signals(inner_files=[
            {"path": "tax_2023.txt", "is_text": True,
             "entity_names": [], "topics": ["taxes"],
             "is_credential_bearing": False, "language": None},
        ])
        row = _make_archive_row(
            topics=["taxes"], categories=["tax"],
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "show tax documents",
            )
        details = report["results"][0]["archive_match_details"]
        self.assertIsNotNone(details)
        m = details["inner_matches"][0]
        self.assertEqual(m["path"], "tax_2023.txt")
        self.assertEqual(m["kind"], "topic")
        self.assertEqual(m["reason"], "is about taxes")
        self.assertEqual(m["confidence"], "medium")


class MultiInnerAggregationTests(unittest.TestCase):
    def test_total_inner_matches_counts_all_attributable(self):
                                                    
        signals = _archive_signals(inner_files=[
            {"path": "notes_1.md", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
            {"path": "notes_2.md", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
            {"path": "notes_3.md", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
        ])
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        details = report["results"][0]["archive_match_details"]
        self.assertEqual(details["total_inner_matches"], 3)
        self.assertEqual(len(details["inner_matches"]), 3)

    def test_inner_matches_capped_total_unaffected(self):
                                                               
        inner = [
            {"path": f"notes_{i}.md", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None}
            for i in range(25)
        ]
        signals = _archive_signals(inner_files=inner)
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        details = report["results"][0]["archive_match_details"]
        self.assertEqual(details["total_inner_matches"], 25)
        self.assertEqual(
            len(details["inner_matches"]),
            vus._MAX_INNER_MATCHES_SHIPPED,
        )


class AttributionOrderTests(unittest.TestCase):
    def test_code_beats_entity_when_query_has_scripts(self):
                                                                  
                                                                  
        signals = _archive_signals(inner_files=[
            {"path": "scripts/install.py", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False,
             "language": "Python"},
        ])
        row = _make_archive_row(
            file_name="archive.zip",
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "find scripts in my archive",
            )
        details = report["results"][0]["archive_match_details"]
        self.assertEqual(len(details["inner_matches"]), 1)
        m = details["inner_matches"][0]
        self.assertEqual(m["kind"], "code")

    def test_entity_beats_credentials_when_inner_has_both(self):
                                                            
                                                                   
        signals = _archive_signals(inner_files=[
            {"path": "accounts.txt", "is_text": True,
             "entity_names": ["Wells Fargo"],
             "topics": ["credentials"],
             "is_credential_bearing": True,
             "purpose": vp.PURPOSE_SAVED_LOGIN_LIST,
             "purpose_label": "saved login list",
             "language": None},
        ])
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        details = report["results"][0]["archive_match_details"]
        m = details["inner_matches"][0]
        self.assertEqual(m["kind"], "entity")


class NonArchiveRowsTests(unittest.TestCase):
    def test_empty_archive_signals_omits_details(self):
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals={},
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        m = report["results"][0]
        self.assertIsNone(m.get("archive_match_details"))

    def test_no_inner_files_omits_details(self):
        signals = {
            "format": "zip", "inner_file_count": 0,
            "rejected_count": 0,
            "truncated_by_entry_cap": False,
            "truncated_by_size_cap":  False,
            "truncated_by_text_cap":  False,
            "inner_files":            [],
        }
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        m = report["results"][0]
        self.assertIsNone(m.get("archive_match_details"))

    def test_no_attributable_inner_files_omits_details(self):
                                                     
        signals = _archive_signals(inner_files=[
            {"path": "random.txt", "is_text": True,
             "entity_names": ["Unrelated Name"],
             "topics": [], "is_credential_bearing": False,
             "language": None},
        ])
                                                             
                                                               
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        m = report["results"][0]
                                                                
        self.assertIsNone(m.get("archive_match_details"))


class SafetyTests(unittest.TestCase):
    def test_inner_match_path_must_come_from_inner_files(self):


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
                                                               
                                                            
            "rejected_paths": [
                ("/etc/plaintext-inner-file-leak", "absolute path"),
            ],
        }
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        details = report["results"][0]["archive_match_details"]
                                                    
        paths = [m["path"] for m in details["inner_matches"]]
        self.assertEqual(paths, ["safe.md"])
        for sentinel in SENTINELS:
            for m in details["inner_matches"]:
                self.assertNotIn(sentinel, m["path"])
                self.assertNotIn(sentinel, m["reason"])
                self.assertNotIn(sentinel, m["kind"])
                self.assertNotIn(sentinel, m["confidence"])

    def test_credential_reason_never_includes_password_value(self):
                                                             
                                                         
        signals = _archive_signals(inner_files=[
            {"path": "accounts.txt", "is_text": True,
             "entity_names": [], "topics": ["credentials"],
             "is_credential_bearing": True,
             "purpose": vp.PURPOSE_SAVED_LOGIN_LIST,
             "purpose_label": "saved login list",
             "language": None},
        ])
        row = _make_archive_row(
            purpose=vp.PURPOSE_SAVED_LOGIN_LIST,
            purpose_label="saved login list",
            topics=["credentials"],
            categories=["security"],
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "saved logins",
            )
        m = report["results"][0]["archive_match_details"][
            "inner_matches"][0]
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, m["path"])
            self.assertNotIn(sentinel, m["reason"])

    def test_details_payload_serialises_without_sentinels(self):
        signals = _archive_signals(inner_files=[
            {"path": "notes.md", "is_text": True,
             "entity_names": ["Wells Fargo"], "topics": [],
             "is_credential_bearing": False, "language": None},
        ])
        row = _make_archive_row(
            entities={"names": ["Wells Fargo"]},
            archive_signals=signals,
        )
        with patch.object(vus, "_fetch_search_rows",
                          return_value=[row]):
            report = vus.search_vault_understanding(
                "vault-x", "Wells Fargo",
            )
        details = report["results"][0]["archive_match_details"]
        encoded = json.dumps(details)
        for sentinel in SENTINELS:
            self.assertNotIn(sentinel, encoded)


class EnvelopeWiringTests(unittest.TestCase):
    def test_envelope_carries_archive_match_details_when_present(self):
        import main
        env = main._build_file_search_envelope(
            query="Wells Fargo",
            results=[{
                "file_id":      "zip-1",
                "file_name":    "backup.zip",
                "match_type":   "entity",
                "match_reason": "archive content match: notes.md mentions Wells Fargo",
                "confidence":   "strong",
                "is_archive_match": True,
                "archive_match_details": {
                    "inner_matches": [
                        {"path": "notes.md",
                         "reason": "mentions Wells Fargo",
                         "kind": "entity",
                         "confidence": "strong"},
                    ],
                    "total_inner_matches": 1,
                },
            }],
            message="",
            pending_count=0,
        )
        payload = json.loads(env)
        row = payload["results"][0]
        self.assertIsNotNone(row["archive_match_details"])
        self.assertEqual(
            row["archive_match_details"]["total_inner_matches"], 1,
        )
        inner = row["archive_match_details"]["inner_matches"][0]
        self.assertEqual(inner["path"], "notes.md")
        self.assertEqual(inner["kind"], "entity")

    def test_envelope_omits_field_when_none(self):
        import main
        env = main._build_file_search_envelope(
            query="x",
            results=[{
                "file_id":      "f1",
                "file_name":    "doc.pdf",
                "match_type":   "entity",
                "match_reason": "entity match: X",
                "confidence":   "strong",
                                           
            }],
            message="",
            pending_count=0,
        )
        payload = json.loads(env)
        row = payload["results"][0]
                                                                 
                                     
        self.assertIsNone(row["archive_match_details"])

    def test_envelope_drops_wrong_typed_details(self):


        import main
        env = main._build_file_search_envelope(
            query="x",
            results=[{
                "file_id":      "f1",
                "file_name":    "doc.pdf",
                "match_type":   "entity",
                "match_reason": "entity match: X",
                "confidence":   "strong",
                "is_archive_match": True,
                "archive_match_details": "not-a-dict",             
            }],
            message="",
            pending_count=0,
        )
        payload = json.loads(env)
        self.assertIsNone(payload["results"][0]["archive_match_details"])


if __name__ == "__main__":
    unittest.main()
