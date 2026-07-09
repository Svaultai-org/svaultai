

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch, MagicMock

import main
import vault_relationship_graph as rg


class CleanupSafetySourceGuardTests(unittest.TestCase):
    def _code_only(self, fn) -> str:
        import ast
        src = inspect.getsource(fn)
        try:
            doc = ast.get_docstring(ast.parse(src.lstrip())) or ""
        except Exception:
            doc = ""
        return src.replace(doc, "") if doc else src

    def test_per_file_cleanup_is_vault_scoped(self):
        src = inspect.getsource(rg.cleanup_relationships_for_file)
        self.assertIn("WHERE vault_id = %s", src)
                                             
        self.assertIn("file_a_id = %s OR file_b_id = %s", src)

    def test_vault_cleanup_subquery_is_vault_scoped(self):
        src = inspect.getsource(rg.cleanup_stale_relationships_for_vault)
                                                           
                                                               
        self.assertIn("f.vault_id = %s", src)
                                 
        self.assertIn("f.id::text = r.file_a_id", src)
        self.assertIn("f.id::text = r.file_b_id", src)

    def test_per_file_cleanup_never_decrypts(self):
        code = self._code_only(rg.cleanup_relationships_for_file)
        self.assertNotIn("decrypt_message", code)
        self.assertNotIn("decrypt_bytes", code)

    def test_vault_cleanup_never_decrypts(self):
        code = self._code_only(rg.cleanup_stale_relationships_for_vault)
        self.assertNotIn("decrypt_message", code)
        self.assertNotIn("decrypt_bytes", code)

    def test_cleanup_never_reads_encrypted_columns(self):
        for fn in (
            rg.cleanup_relationships_for_file,
            rg.cleanup_stale_relationships_for_vault,
        ):
            code = self._code_only(fn)
            for col in (
                "encrypted_file_data",
                "extracted_text",
                "summary_encrypted",
                "safe_preview_encrypted",
            ):
                self.assertNotIn(col, code)

    def test_relationship_analysis_version_exists(self):
        self.assertTrue(hasattr(rg, "RELATIONSHIP_ANALYSIS_VERSION"))
        self.assertIsInstance(rg.RELATIONSHIP_ANALYSIS_VERSION, int)
        self.assertGreaterEqual(rg.RELATIONSHIP_ANALYSIS_VERSION, 1)

    def test_vault_cleanup_uses_version_constant(self):
        src = inspect.getsource(rg.cleanup_stale_relationships_for_vault)
        self.assertIn("RELATIONSHIP_ANALYSIS_VERSION", src)


class _FakeCursor:
    def __init__(self, *, rowcount=0, fetchone=None):
        self.executed = []
        self._rowcount = rowcount
        self._fetchone = fetchone

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    @property
    def rowcount(self):
        return self._rowcount

    def fetchone(self):
        return self._fetchone

    def close(self):
        pass


class _FakeConn:
    def __init__(self, *, cursors=None):
                                                               
                                                            
        self._cursors = list(cursors or [])
        self.committed = 0
        self.closed = False

    def cursor(self, *args, **kwargs):
        if not self._cursors:
                                    
            return _FakeCursor()
                                                             
                                                           
        return self._cursors[0]

    def commit(self):
        self.committed += 1

    def close(self):
        self.closed = True


class PerFileCleanupBehaviourTests(unittest.TestCase):
    def test_empty_vault_id_short_circuits(self):
        with patch.object(
            rg, "_get_db",
            side_effect=AssertionError("should not open conn"),
        ):
            report = rg.cleanup_relationships_for_file("", "f-1")
        self.assertEqual(report["deleted"], 0)

    def test_empty_file_id_short_circuits(self):
        with patch.object(
            rg, "_get_db",
            side_effect=AssertionError("should not open conn"),
        ):
            report = rg.cleanup_relationships_for_file("v-1", "")
        self.assertEqual(report["deleted"], 0)

    def test_delete_uses_vault_id_and_file_id_on_both_sides(self):
        cur = _FakeCursor(rowcount=3)
        conn = _FakeConn(cursors=[cur])
        with patch.object(rg, "_get_db", return_value=conn):
            report = rg.cleanup_relationships_for_file("v-1", "f-x")
                                                                 
                           
        self.assertEqual(len(cur.executed), 1)
        sql, params = cur.executed[0]
        self.assertIn("DELETE FROM vault_file_relationships", sql)
        self.assertEqual(params, ("v-1", "f-x", "f-x"))
        self.assertEqual(report["deleted"], 3)
        self.assertEqual(conn.committed, 1)
        self.assertTrue(conn.closed)

    def test_returns_zero_when_nothing_matched(self):
        cur = _FakeCursor(rowcount=0)
        conn = _FakeConn(cursors=[cur])
        with patch.object(rg, "_get_db", return_value=conn):
            report = rg.cleanup_relationships_for_file("v-1", "f-x")
        self.assertEqual(report["deleted"], 0)
        self.assertEqual(report["vault_id"], "v-1")
        self.assertEqual(report["file_id"], "f-x")


class VaultCleanupBehaviourTests(unittest.TestCase):
    def test_empty_vault_id_short_circuits(self):
        with patch.object(
            rg, "_get_db",
            side_effect=AssertionError("should not open conn"),
        ):
            report = rg.cleanup_stale_relationships_for_vault("")
        self.assertEqual(report["deleted_orphans"], 0)
        self.assertEqual(report["stale_version_rows"], 0)

    def test_orphan_delete_runs_then_version_count(self):
                                                              
                                                             
        cur = _FakeCursor(rowcount=2, fetchone=(7,))
        conn = _FakeConn(cursors=[cur])
        with patch.object(rg, "_get_db", return_value=conn):
            report = rg.cleanup_stale_relationships_for_vault("v-1")
        self.assertEqual(len(cur.executed), 2)
        delete_sql, delete_params = cur.executed[0]
        count_sql, count_params = cur.executed[1]
                                           
        self.assertIn("DELETE FROM vault_file_relationships", delete_sql)
                                                              
        self.assertEqual(delete_params, ("v-1", "v-1", "v-1"))
                                                 
        self.assertIn("SELECT COUNT(*)", count_sql)
        self.assertIn("analysis_version", count_sql)
                                                     
        self.assertEqual(
            count_params,
            ("v-1", int(rg.RELATIONSHIP_ANALYSIS_VERSION)),
        )
        self.assertEqual(report["deleted_orphans"], 2)
        self.assertEqual(report["stale_version_rows"], 7)
        self.assertEqual(conn.committed, 1)

    def test_subquery_carries_vault_id_for_both_endpoints(self):
                                                          
                                                          
        src = inspect.getsource(rg.cleanup_stale_relationships_for_vault)
                                                              
                                               
        self.assertGreaterEqual(src.count("f.vault_id = %s"), 2)

    def test_returns_closed_set_shape(self):
        cur = _FakeCursor(rowcount=0, fetchone=(0,))
        conn = _FakeConn(cursors=[cur])
        with patch.object(rg, "_get_db", return_value=conn):
            report = rg.cleanup_stale_relationships_for_vault("v-1")
        self.assertEqual(
            set(report.keys()),
            {"vault_id", "deleted_orphans", "stale_version_rows"},
        )


class DeleteFileIntegrationSourceGuardTests(unittest.TestCase):
    def test_endpoint_calls_per_file_cleanup(self):
        src = inspect.getsource(main.delete_file_endpoint)
        self.assertIn("cleanup_relationships_for_file", src)

    def test_endpoint_passes_vault_id_and_payload_file_id(self):
        src = inspect.getsource(main.delete_file_endpoint)
                                                              
                                                           
        self.assertIn(
            "cleanup_relationships_for_file(vault_id, payload.file_id)",
            src,
        )

    def test_endpoint_swallows_cleanup_exceptions(self):
        src = inspect.getsource(main.delete_file_endpoint)
        idx = src.find("cleanup_relationships_for_file")
        self.assertGreater(idx, -1)
        window = src[max(0, idx - 200):idx + 400]
                                                               
                                                             
        self.assertIn("try:", window)
        self.assertIn("except Exception", window)

    def test_endpoint_calls_cleanup_after_uploaded_files_delete(self):
        src = inspect.getsource(main.delete_file_endpoint)
        delete_idx = src.rfind("DELETE FROM uploaded_files")
        cleanup_idx = src.find("cleanup_relationships_for_file")
        self.assertGreater(delete_idx, -1)
        self.assertGreater(cleanup_idx, -1)
        self.assertLess(
            delete_idx, cleanup_idx,
            "relationship cleanup must run AFTER the file row "
            "is deleted so an aborted delete doesn't strip the "
            "graph",
        )


class ChatHandlerIntegrationSourceGuardTests(unittest.TestCase):
    def test_chat_calls_cleanup_before_relationship_drain(self):
        src = inspect.getsource(main.chat_endpoint)
        cleanup_idx = src.find("cleanup_stale_relationships_for_vault")
        drain_idx = src.find("drain_relationship_building")
        self.assertGreater(cleanup_idx, -1)
        self.assertGreater(drain_idx, -1)
        self.assertLess(
            cleanup_idx, drain_idx,
            "cleanup must run BEFORE the relationship_building "
            "drain so the drain doesn't rebuild rows we're "
            "about to delete",
        )

    def test_chat_cleanup_runs_after_embedding_drain(self):
        src = inspect.getsource(main.chat_endpoint)
        embedding_idx = src.find("drain_file_embedding")
        cleanup_idx = src.find("cleanup_stale_relationships_for_vault")
        self.assertGreater(embedding_idx, -1)
        self.assertGreater(cleanup_idx, -1)
        self.assertLess(embedding_idx, cleanup_idx)

    def test_chat_enqueues_rebuild_when_orphans_or_stale_found(self):
        src = inspect.getsource(main.chat_endpoint)
        idx = src.find("cleanup_stale_relationships_for_vault")
        body = src[idx:idx + 2500]
                                                          
                             
        self.assertIn("deleted_orphans", body)
        self.assertIn("stale_version_rows", body)
        self.assertIn("enqueue_relationship_building", body)

    def test_chat_swallows_cleanup_exceptions(self):
        src = inspect.getsource(main.chat_endpoint)
        idx = src.find("cleanup_stale_relationships_for_vault")
        self.assertGreater(idx, -1)
        window = src[max(0, idx - 400):idx + 400]
                                                  
        self.assertIn("try:", window)
        self.assertIn("except Exception", window)

    def test_chat_swallows_enqueue_exceptions(self):
        src = inspect.getsource(main.chat_endpoint)
        idx = src.find("relationship_cleanup_enqueue")
                                                          
                                                           
        self.assertGreater(idx, -1)


class CrossVaultNonImpactTests(unittest.TestCase):
    def test_per_file_cleanup_never_carries_other_vault_id(self):
        cur = _FakeCursor(rowcount=0)
        conn = _FakeConn(cursors=[cur])
        with patch.object(rg, "_get_db", return_value=conn):
            rg.cleanup_relationships_for_file("vault-A", "file-shared")
        sql, params = cur.executed[0]
                                                           
        self.assertEqual(params[0], "vault-A")
                                                             
                
        for p in params[1:]:
            self.assertNotEqual(p, "vault-B")

    def test_vault_cleanup_carries_only_its_own_vault_id(self):
        cur = _FakeCursor(rowcount=0, fetchone=(0,))
        conn = _FakeConn(cursors=[cur])
        with patch.object(rg, "_get_db", return_value=conn):
            rg.cleanup_stale_relationships_for_vault("vault-A")
        delete_sql, delete_params = cur.executed[0]
        count_sql, count_params = cur.executed[1]
        for p in delete_params:
            self.assertEqual(p, "vault-A")
        self.assertEqual(count_params[0], "vault-A")


class ShowRelatedSurvivesDeletionTests(unittest.TestCase):
    def test_composer_drops_relationships_with_missing_other_side(self):
        src = inspect.getsource(main._compose_related_files_envelope)
                                                         
                                                           
        self.assertIn("file_metadata_by_id", src)
        self.assertIn("if other in file_metadata_by_id", src)

    def test_composer_returns_clean_envelope_even_when_all_related_missing(self):
                                                          
                                                         
        anchor = {
            "id": "anchor-1", "file_name": "x.pdf",
            "saved_name": "X", "relative_path": "/x",
            "content_type": "application/pdf",
            "asset_type": "file",
        }
        rels = [
            {
                "file_a_id": "anchor-1", "file_b_id": "deleted-1",
                "relationship_type": "same_person",
                "confidence": 0.95,
                "reasons_jsonb": ["shared name"],
                "evidence_jsonb": {},
                "updated_at": None,
            },
        ]
        with patch(
            "vault_relationship_graph.get_relationships_for_file",
            return_value=rels,
        ), patch.object(
            main, "_load_safe_file_metadata", return_value={},
        ):
            env = main._compose_related_files_envelope(
                vault_id="v-1", anchor_row=anchor,
            )
                                                          
                                                          
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["relationships"], [])
        self.assertIn("don't see strong related files", env["message"])


if __name__ == "__main__":
    unittest.main()
