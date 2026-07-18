

from __future__ import annotations

import inspect
import json
import unittest
from unittest import mock

import vault_surface_tools as vst


_KEY = b"\x77" * 32


def _cur_with(*sequences):


    cur = mock.MagicMock()
    one_results = [s for s in sequences if isinstance(s, dict)]
    all_results = [s for s in sequences if isinstance(s, list)]
    cur.fetchone.side_effect = one_results or [None]
    cur.fetchall.side_effect = all_results or [[]]
    return cur


def _conn_with_cursor(cur):
    conn = mock.MagicMock()
    conn.cursor.return_value = cur
    return conn


class WiringTests(unittest.TestCase):
    _EXPECTED = (
        "get_vault_status",
        "list_expiring_items",
        "get_expiry_alert",
        "list_vault_entities",
        "find_files_for_entity",
        "list_file_relationships",
        "list_document_categories",
        "list_files_by_category",
        "get_vault_activity",
    )

    def test_surface_dispatch_contains_every_tool(self):
        for name in self._EXPECTED:
            self.assertIn(name, vst.SURFACE_DISPATCH)

    def test_surface_functions_schema_contains_every_tool(self):
        names = [f["function"]["name"] for f in vst.SURFACE_FUNCTIONS]
        for n in self._EXPECTED:
            self.assertIn(n, names)

    def test_vault_knowledge_dispatch_merges_surface(self):
        from vault_knowledge_tools import VAULT_KNOWLEDGE_DISPATCH
        for n in self._EXPECTED:
            self.assertIn(n, VAULT_KNOWLEDGE_DISPATCH)

    def test_vault_knowledge_functions_includes_surface_schemas(self):
        from vault_knowledge_tools import VAULT_KNOWLEDGE_FUNCTIONS
        names = [
            f["function"]["name"] for f in VAULT_KNOWLEDGE_FUNCTIONS
        ]
        for n in self._EXPECTED:
            self.assertIn(n, names)


class VaultScopeGuards(unittest.TestCase):
    def test_every_tool_sql_filters_by_vault_id(self):
        for fn in (
            vst.get_vault_status,
            vst.list_expiring_items,
            vst.get_expiry_alert,
            vst.list_vault_entities,
            vst.find_files_for_entity,
            vst.list_file_relationships,
            vst.list_document_categories,
            vst.list_files_by_category,
            vst.get_vault_activity,
        ):
            with self.subTest(fn=fn.__name__):
                src = inspect.getsource(fn)
                self.assertIn(
                    "vault_id = %s", src,
                    msg=(
                        f"{fn.__name__} must filter by vault_id "
                        "in every query."
                    ),
                )


class GetVaultStatusTests(unittest.TestCase):
    def test_happy_path_emits_closed_set_fields(self):
        cur = mock.MagicMock()
        cur.fetchone.side_effect = [
            {
                "vault_name":   "My Vault",
                "total_bytes":  123456,
                "locked_until": None,
                "created_at":   None,
                "updated_at":   None,
            },
            {"n": 7},                           
            {"n": 4},                        
            {"n": 3},                        
        ]
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 7, "analyzed": 5, "pending": 2,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ):
            out = vst.get_vault_status(vault_id="v1", key=_KEY)
        payload = json.loads(out)
        self.assertEqual(payload["vault_name"], "My Vault")
        self.assertEqual(payload["vault_state"], "unlocked")
        self.assertEqual(payload["total_files"], 7)
        self.assertEqual(payload["total_saved_credentials"], 4)
        self.assertEqual(payload["distinct_services"], 3)
        self.assertEqual(payload["total_bytes"], 123456)
        cov = payload["analysis_coverage"]
        self.assertEqual(cov["total"], 7)
        self.assertEqual(cov["analyzed"], 5)
        self.assertFalse(cov["is_complete"])

    def test_locked_state_reported_when_key_invalid(self):
        cur = mock.MagicMock()
        cur.fetchone.side_effect = [
            {
                "vault_name":   "Locked Vault",
                "total_bytes":  0,
                "locked_until": None,
                "created_at":   None,
                "updated_at":   None,
            },
            {"n": 0}, {"n": 0}, {"n": 0},
        ]
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={},
        ):
            out = vst.get_vault_status(
                vault_id="v1", key=b"short",
            )
        self.assertEqual(
            json.loads(out)["vault_state"], "locked",
        )

    def test_db_failure_returns_unavailable(self):
        with mock.patch(
            "main.get_db", side_effect=RuntimeError("db down"),
        ):
            out = vst.get_vault_status(vault_id="v1", key=_KEY)
        self.assertEqual(json.loads(out).get("error"), "unavailable")


class ListExpiringItemsTests(unittest.TestCase):
    def test_returns_items_with_file_and_item_sources(self):
        cur = mock.MagicMock()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = [
            {
                "id": 1, "source_kind": "uploaded_file",
                "source_file_id": "f1", "source_item_id": None,
                "expiry_type": "passport", "expiry_date": None,
                "severity": "warn", "alert_window_days": 90,
                "f_name": "passport.pdf",
                "f_saved": "passport.pdf",
                "f_path": "/IDs/",
                "i_service": None, "i_kind": None,
            },
            {
                "id": 2, "source_kind": "vault_item",
                "source_file_id": None, "source_item_id": 42,
                "expiry_type": "subscription", "expiry_date": None,
                "severity": "info", "alert_window_days": 30,
                "f_name": None, "f_saved": None, "f_path": None,
                "i_service": "Netflix", "i_kind": "subscription",
            },
        ]
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.list_expiring_items(vault_id="v1", key=_KEY)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 2)
        first, second = payload["items"]
        self.assertEqual(first["file_id"], "f1")
        self.assertEqual(first["file_name"], "passport.pdf")
        self.assertEqual(second["item_id"], 42)
        self.assertEqual(second["service"], "Netflix")

    def test_severity_filter_falls_back_to_none_for_unknown(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = []
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.list_expiring_items(
                vault_id="v1", key=_KEY,
                severity="bogus-severity",
            )
        payload = json.loads(out)
        self.assertIsNone(payload["filter"]["severity"])

    def test_window_days_clamps_to_upper_bound(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = []
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.list_expiring_items(
                vault_id="v1", key=_KEY,
                window_days=10_000_000,
            )
        payload = json.loads(out)
        self.assertLessEqual(
            payload["filter"]["window_days"], vst.MAX_WINDOW_DAYS,
        )


class GetExpiryAlertTests(unittest.TestCase):
    def test_requires_alert_id(self):
        out = vst.get_expiry_alert(
            vault_id="v1", key=_KEY, alert_id=0,
        )
        self.assertEqual(
            json.loads(out).get("error"), "missing_alert_id",
        )

    def test_not_found_when_alert_doesnt_belong_to_vault(self):
        cur = mock.MagicMock()
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.get_expiry_alert(
                vault_id="v-OTHER", key=_KEY, alert_id=99,
            )
        self.assertEqual(json.loads(out).get("error"), "not_found")

    def test_returns_alert_details(self):
        cur = mock.MagicMock()
        cur.fetchone.return_value = {
            "id": 5, "source_kind": "uploaded_file",
            "source_file_id": "f1", "source_item_id": None,
            "expiry_type": "id_card",
            "expiry_date": None,
            "severity": "critical", "alert_window_days": 30,
            "status": "active",
            "created_at": None, "updated_at": None,
            "f_name": "id.pdf", "f_saved": "id.pdf",
            "f_path": "/IDs/",
            "i_service": None, "i_kind": None,
        }
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.get_expiry_alert(
                vault_id="v1", key=_KEY, alert_id=5,
            )
        payload = json.loads(out)
        self.assertEqual(payload["alert_id"], 5)
        self.assertEqual(payload["severity"], "critical")
        self.assertEqual(payload["file_name"], "id.pdf")


class EntityToolsTests(unittest.TestCase):
    def test_list_vault_entities_filters_unknown_type(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = []
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.list_vault_entities(
                vault_id="v1", key=_KEY,
                entity_type="bogus-type",
            )
                                                               
        self.assertIsNone(
            json.loads(out)["filter"]["entity_type"],
        )

    def test_list_vault_entities_returns_tallies(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [
            {
                "entity_type": "identity",
                "entity_value": "Louis Iodato",
                "file_count": 3,
            },
            {
                "entity_type": "finance",
                "entity_value": "Wells Fargo",
                "file_count": 1,
            },
        ]
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.list_vault_entities(vault_id="v1", key=_KEY)
        payload = json.loads(out)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            payload["entities"][0]["entity_value"], "Louis Iodato",
        )
        self.assertEqual(payload["entities"][0]["file_count"], 3)

    def test_find_files_for_entity_requires_value(self):
        out = vst.find_files_for_entity(
            vault_id="v1", key=_KEY, entity_value="   ",
        )
        self.assertEqual(
            json.loads(out).get("error"), "missing_entity_value",
        )

    def test_find_files_for_entity_returns_files(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [{
            "source_file_id": "f1",
            "entity_type": "identity",
            "entity_key": "name",
            "confidence": 0.95,
            "file_name": "id.pdf",
            "saved_name": "id.pdf",
            "relative_path": "/IDs/",
            "created_at": None,
        }]
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.find_files_for_entity(
                vault_id="v1", key=_KEY,
                entity_value="Louis Iodato",
            )
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            payload["files"][0]["file_id"], "f1",
        )
        self.assertEqual(payload["files"][0]["confidence"], 0.95)


class ListFileRelationshipsTests(unittest.TestCase):
    def test_returns_file_to_file_relationship(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [{
            "id": 1, "source_kind": "uploaded_file",
            "source_file_id": "fA", "source_item_id": None,
            "target_kind": "uploaded_file",
            "target_file_id": "fB", "target_item_id": None,
            "relation_type": "travel_related",
            "confidence": 0.9,
            "s_name": "passport.pdf", "s_saved": "passport.pdf",
            "t_name": "boarding.pdf", "t_saved": "boarding.pdf",
            "s_service": None, "t_service": None,
        }]
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.list_file_relationships(
                vault_id="v1", key=_KEY, file_id="fA",
            )
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        rel = payload["relationships"][0]
        self.assertEqual(rel["relation_type"], "travel_related")
        self.assertEqual(rel["source"]["file_id"], "fA")
        self.assertEqual(rel["target"]["file_id"], "fB")


class CategoryToolsTests(unittest.TestCase):
    def test_list_document_categories_returns_distinct_purposes(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [
            {"document_purpose": "passport", "file_count": 3},
            {"document_purpose": "tax_document", "file_count": 12},
        ]
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.list_document_categories(
                vault_id="v1", key=_KEY,
            )
        payload = json.loads(out)
        self.assertEqual(payload["count"], 2)
        purposes = {c["document_purpose"] for c in payload["categories"]}
        self.assertEqual(
            purposes, {"passport", "tax_document"},
        )

    def test_list_files_by_category_requires_purpose(self):
        out = vst.list_files_by_category(
            vault_id="v1", key=_KEY, document_purpose="  ",
        )
        self.assertEqual(
            json.loads(out).get("error"),
            "missing_document_purpose",
        )

    def test_list_files_by_category_returns_files(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [{
            "file_id": "fX",
            "purpose_label": "Tax return",
            "purpose_confidence": 0.88,
            "file_name": "1040.pdf",
            "saved_name": "1040.pdf",
            "relative_path": "/Tax/",
            "created_at": None,
            "asset_type": "document",
            "content_type": "application/pdf",
        }]
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.list_files_by_category(
                vault_id="v1", key=_KEY,
                document_purpose="tax_document",
            )
        payload = json.loads(out)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            payload["files"][0]["file_id"], "fX",
        )


class GetVaultActivityTests(unittest.TestCase):
    def test_returns_mixed_uploads_and_credential_saves(self):
        cur = mock.MagicMock()
        cur.fetchall.side_effect = [
            [{
                "id": "f1", "file_name": "n.pdf",
                "saved_name": "n.pdf",
                "relative_path": "/",
                "asset_type": "document",
                "created_at": None,
            }],
            [{
                "id": 99, "service": "Chase",
                "item_type": "login",
                "created_at": None,
            }],
        ]
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.get_vault_activity(
                vault_id="v1", key=_KEY, window_days=14,
            )
        payload = json.loads(out)
        kinds = {e["kind"] for e in payload["entries"]}
        self.assertEqual(kinds, {"file_upload", "credential_save"})
        self.assertEqual(payload["window_days"], 14)

    def test_kind_filter_restricts_to_credential_saves(self):
        cur = mock.MagicMock()
        cur.fetchall.return_value = [{
            "id": 99, "service": "Chase",
            "item_type": "login",
            "created_at": None,
        }]
        cur.fetchone.return_value = None
        conn = _conn_with_cursor(cur)
        with mock.patch("main.get_db", return_value=conn):
            out = vst.get_vault_activity(
                vault_id="v1", key=_KEY,
                kind="credential_save",
            )
        payload = json.loads(out)
        self.assertTrue(all(
            e["kind"] == "credential_save"
            for e in payload["entries"]
        ))


class SystemPromptDirectsEverySurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("tools.py", "r", encoding="utf-8") as f:
            cls._src = f.read()

    def test_prompt_lists_every_surface_tool(self):
                                                               
                                                              
        for name in (
            "get_vault_status",
            "list_expiring_items",
            "list_vault_entities",
            "find_files_for_entity",
            "list_file_relationships",
            "list_document_categories",
            "list_files_by_category",
            "get_vault_activity",
        ):
            with self.subTest(name=name):
                self.assertIn(name, self._src)

    def test_prompt_documents_full_vault_focus(self):
                                                                
                                               
        self.assertIn("FULL-VAULT SURFACE", self._src)
        self.assertIn("not file-only", self._src)

    def test_prompt_includes_examples_for_non_file_surfaces(self):
                                                             
                                                          
        for keyword in (
            "what's expiring",
            "who is in my vault",
            "what categories",
            "what's in my vault",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, self._src)


if __name__ == "__main__":
    unittest.main()
