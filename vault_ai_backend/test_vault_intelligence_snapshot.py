

from __future__ import annotations

import json
import unittest
from unittest import mock

from vault_knowledge_tools import (
    VAULT_KNOWLEDGE_DISPATCH,
    VAULT_KNOWLEDGE_FUNCTIONS,
    get_vault_intelligence,
    _SENSITIVE_PURPOSES,
)


class IntelligenceToolSurfaceTests(unittest.TestCase):
    def test_schema_lists_get_vault_intelligence(self):
        names = {f["function"]["name"] for f in VAULT_KNOWLEDGE_FUNCTIONS}
        self.assertIn("get_vault_intelligence", names)

    def test_dispatch_routes_get_vault_intelligence(self):
        self.assertIn("get_vault_intelligence", VAULT_KNOWLEDGE_DISPATCH)
        self.assertIs(
            VAULT_KNOWLEDGE_DISPATCH["get_vault_intelligence"],
            get_vault_intelligence,
        )

    def test_schema_advertises_no_vault_id_or_key_param(self):
        for fn in VAULT_KNOWLEDGE_FUNCTIONS:
            if fn["function"]["name"] != "get_vault_intelligence":
                continue
            params = fn["function"]["parameters"]
            props = params.get("properties") or {}
            self.assertNotIn("vault_id", props)
            self.assertNotIn("key", props)


class SnapshotShapeTests(unittest.TestCase):
    def _patch_all_data_sources(self):
                                                           
                                                         
        fake_cur = mock.MagicMock()
        fake_cur.fetchone.return_value = {"n": 0}
        fake_cur.fetchall.return_value = []
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        return mock.patch.multiple(
            "vault_knowledge_tools",
            create=True,
        ), fake_conn

    def test_snapshot_returns_eight_named_blocks(self):
        with mock.patch(
            "main.list_uploaded_files",
            return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 0, "analyzed": 0, "pending": 0,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ), mock.patch(
            "main.get_db",
        ) as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.return_value = []
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            blob = get_vault_intelligence(
                vault_id="v1", key=b"\x00" * 32,
            )
        snap = json.loads(blob)
        for name in (
            "coverage", "files_by_kind", "recent_uploads",
            "credentials", "sensitive_documents", "expiring_soon",
            "needs_attention", "top_entities",
        ):
            self.assertIn(name, snap, f"missing block: {name}")
                                                               
                              
        for name in (
            "coverage", "files_by_kind", "recent_uploads",
            "credentials", "sensitive_documents", "expiring_soon",
            "needs_attention", "top_entities",
        ):
            self.assertIn("available", snap[name],
                          f"block {name!r} missing 'available' flag")

    def test_snapshot_schema_version_present(self):
        with mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={},
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.return_value = []
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            snap = json.loads(get_vault_intelligence(
                vault_id="v1", key=b"\x00" * 32,
            ))
        self.assertEqual(snap.get("schema_version"), 1)


class CoverageTransparencyTests(unittest.TestCase):
    def test_coverage_percent_computed(self):
        with mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 425, "analyzed": 120, "pending": 200,
                "processing": 100, "failed": 3, "unsupported": 2,
            },
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.return_value = []
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            snap = json.loads(get_vault_intelligence(
                vault_id="v1", key=b"\x00" * 32,
            ))
        cov = snap["coverage"]
        self.assertTrue(cov["available"])
        self.assertEqual(cov["total"], 425)
        self.assertEqual(cov["analyzed"], 120)
                                                     
        self.assertAlmostEqual(cov["percent"], 28.2, places=1)
        self.assertFalse(cov["is_complete"])

    def test_coverage_is_complete_when_no_pending(self):
        with mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 10, "analyzed": 10, "pending": 0,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.return_value = []
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            snap = json.loads(get_vault_intelligence(
                vault_id="v1", key=b"\x00" * 32,
            ))
        self.assertTrue(snap["coverage"]["is_complete"])


class CredentialsBlockKeyGateTests(unittest.TestCase):
    def test_locked_vault_returns_available_false_with_reason(self):
        with mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={},
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 7}
            _cur.fetchall.return_value = []
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
                                                      
            snap = json.loads(get_vault_intelligence(
                vault_id="v1", key=b"too-short",
            ))
        creds = snap["credentials"]
        self.assertFalse(creds["available"])
        self.assertEqual(creds["reason"], "vault_locked")
                                                                 
                     
        self.assertEqual(creds["saved_credential_services_count"], 7)


class SensitiveDocsBlockShapeTests(unittest.TestCase):
    def test_sensitive_purpose_list_is_closed_set(self):
                                                         
                                                          
        expected = {
            "id_document", "financial_document", "legal_document",
            "contract", "insurance_form", "medical_document",
            "passport", "visa",
        }
        self.assertTrue(expected.issubset(set(_SENSITIVE_PURPOSES)))

    def test_sensitive_block_rows_have_identity_columns_only(self):
                                                               
                                                               
        fake_row = {
            "file_id":            "f1",
            "document_purpose":   "id_document",
            "purpose_label":      "ID document",
            "purpose_confidence": 0.92,
            "file_name":          "passport.pdf",
            "saved_name":         "passport.pdf",
            "relative_path":      "/Travel/",
            "created_at":         None,
                                                                
            "extracted_text":     "DO-NOT-LEAK passport number 12345",
            "encrypted_data":     "DO-NOT-LEAK",
        }
        with mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={},
        ), mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=[],
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
                                                              
                                             
            _cur.fetchall.side_effect = [
                [fake_row], [], [], [],
            ]
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            snap = json.loads(get_vault_intelligence(
                vault_id="v1", key=b"\x00" * 32,
            ))
        sens = snap["sensitive_documents"]
        self.assertTrue(sens["available"])
                                                        
        blob = json.dumps(snap)
        self.assertNotIn("DO-NOT-LEAK", blob)
        self.assertNotIn("12345", blob)
                                             
        if sens["files"]:
            row = sens["files"][0]
            for k in row.keys():
                self.assertIn(
                    k, {"file_name", "folder", "document_purpose",
                        "purpose_label", "confidence"},
                    f"unexpected key {k!r} in sensitive_documents row",
                )


class ExpiringSoonShapeTests(unittest.TestCase):
    def test_expiring_block_shapes_closed_set_per_row(self):
        from datetime import date
        fake_row = {
            "source_kind":       "uploaded_file",
            "source_file_id":    "f1",
            "source_item_id":    None,
            "expiry_type":       "passport_expiry",
            "expiry_date":       date(2026, 12, 31),
            "severity":          "warning",
            "alert_window_days": 60,
            "file_name":         "passport.pdf",
            "saved_name":        "passport.pdf",
            "relative_path":     "/Travel/",
        }
        with mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={},
        ), mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=[],
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.side_effect = [
                [], [fake_row], [], [],
            ]
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            snap = json.loads(get_vault_intelligence(
                vault_id="v1", key=b"\x00" * 32,
            ))
        exp = snap["expiring_soon"]
        self.assertTrue(exp["available"])
        self.assertEqual(exp["count"], 1)
        row = exp["items"][0]
        self.assertEqual(row["file_name"], "passport.pdf")
        self.assertEqual(row["expiry_type"], "passport_expiry")
        self.assertEqual(row["expiry_date_iso"], "2026-12-31")
        self.assertEqual(row["severity"], "warning")


class TopEntitiesTallyTests(unittest.TestCase):
    def test_entities_tallied_and_ranked(self):
                                                                 
                                                  
        rows = [
            {"entities_jsonb": {
                "people":        ["Alice", "Bob"],
                "organizations": ["Wells Fargo"],
                "places":        ["New York"],
            }},
            {"entities_jsonb": {
                "people":        ["Alice"],
                "organizations": ["Wells Fargo", "Chase"],
                "places":        [],
            }},
        ]
        with mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={},
        ), mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=[],
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.side_effect = [
                [], [], [], rows,
            ]
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            snap = json.loads(get_vault_intelligence(
                vault_id="v1", key=b"\x00" * 32,
            ))
        ents = snap["top_entities"]
        self.assertTrue(ents["available"])
                                        
        alice_count = next(
            (e["files_seen_in"] for e in ents["people"]
             if e["name"] == "Alice"), 0,
        )
        bob_count = next(
            (e["files_seen_in"] for e in ents["people"]
             if e["name"] == "Bob"), 0,
        )
        self.assertEqual(alice_count, 2)
        self.assertEqual(bob_count, 1)
                                          
        wells_count = next(
            (e["files_seen_in"] for e in ents["organizations"]
             if e["name"] == "Wells Fargo"), 0,
        )
        chase_count = next(
            (e["files_seen_in"] for e in ents["organizations"]
             if e["name"] == "Chase"), 0,
        )
        self.assertEqual(wells_count, 2)
        self.assertEqual(chase_count, 1)


class SystemPromptCoverageContractTests(unittest.TestCase):
    def test_prompt_directs_get_vault_intelligence_first(self):
        from tools import SYSTEM_PROMPT
                                                                  
                                                                 
        self.assertIn("get_vault_intelligence", SYSTEM_PROMPT)

    def test_prompt_demands_coverage_transparency(self):
        from tools import SYSTEM_PROMPT
                                                          
        self.assertIn("reviewed", SYSTEM_PROMPT.lower())
        self.assertIn("coverage", SYSTEM_PROMPT.lower())
        self.assertIn("is_complete", SYSTEM_PROMPT)

    def test_prompt_forbids_hallucinated_insight(self):
        from tools import SYSTEM_PROMPT
        self.assertIn("Never claim a file says something you didn't see",
                      SYSTEM_PROMPT)

    def test_prompt_vault_knows_itself_framing(self):
        from tools import SYSTEM_PROMPT
                                                                  
                                                                 
        self.assertIn("FULL-VAULT SURFACE", SYSTEM_PROMPT)


class SnapshotSafetyFloorTests(unittest.TestCase):
    def test_no_encrypted_columns_in_payload(self):
                                                                    
                              
        with mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 1, "analyzed": 1, "pending": 0,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.return_value = []
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            blob = get_vault_intelligence(
                vault_id="v1", key=b"\x00" * 32,
            )
        for needle in (
            "encrypted_data", "encrypted_chunk_text",
            "extracted_text", "content_sha256",
        ):
            self.assertNotIn(needle, blob)


if __name__ == "__main__":
    unittest.main()
