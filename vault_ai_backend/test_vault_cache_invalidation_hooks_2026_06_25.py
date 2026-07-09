

from __future__ import annotations

import unittest
from unittest import mock

import vault_tool_result_cache as cache


_VAULT = "00000000-0000-0000-0000-000000000aaa"


class _Base(unittest.TestCase):
    def setUp(self):
        cache.reset_cache_for_tests()


class SourceGuards(unittest.TestCase):
    def _read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_manage_routes_credential_edit_fires_credential_edited(self):
        src = self._read("routes/vault_manage_routes.py")
        self.assertIn(
            "from vault_tool_result_cache import invalidate_for_event",
            src,
        )
        self.assertIn('event="credential_edited"', src)

    def test_manage_routes_credential_delete_fires_credential_deleted(self):
        src = self._read("routes/vault_manage_routes.py")
        self.assertIn('event="credential_deleted"', src)

    def test_manage_routes_file_rename_fires_file_renamed(self):
        src = self._read("routes/vault_manage_routes.py")
        self.assertIn('event="file_renamed"', src)

    def test_manage_routes_file_delete_fires_file_deleted(self):
        src = self._read("routes/vault_manage_routes.py")
        self.assertIn('event="file_deleted"', src)

    def test_vault_analysis_chokepoint_fires_file_analysis_changed(self):
        src = self._read("vault_analysis.py")
        self.assertIn(
            "from vault_tool_result_cache import invalidate_for_event",
            src,
        )
        self.assertIn('event="file_analysis_changed"', src)

    def test_expiry_engine_file_path_fires_expiry_updated(self):
        src = self._read("expiry_engine.py")
        self.assertIn(
            "from vault_tool_result_cache import invalidate_for_event",
            src,
        )
        self.assertIn('event="expiry_updated"', src)


class VaultAnalysisChokepoint(_Base):


    def _mock_db(self, rowcount):
        fake_cur = mock.MagicMock()
        fake_cur.rowcount = rowcount
        fake_conn = mock.MagicMock()
        fake_conn.cursor.return_value = fake_cur
        return fake_conn

    def _call(self, *, vault_id, rowcount):
        from vault_analysis import (
            _set_file_analysis_status,
            ANALYSIS_STATUS_ANALYZED,
        )
        with mock.patch(
            "vault_analysis._get_db",
            return_value=self._mock_db(rowcount),
        ):
            return _set_file_analysis_status(
                file_id="f-xyz",
                new_status=ANALYSIS_STATUS_ANALYZED,
                vault_id=vault_id,
                touch_started_at=False,
                touch_completed_at=True,
                last_error=None,
            )

    def test_invalidates_only_after_successful_row_update(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id="tok",
            tool_name="get_vault_intelligence", args={},
            result='{"x":"1"}',
        )
                                                         
        wrote = self._call(vault_id=_VAULT, rowcount=1)
        self.assertTrue(wrote)
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id="tok",
            tool_name="get_vault_intelligence", args={},
        ))

    def test_does_not_invalidate_on_zero_row_update(self):
                                                              
                                                               
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id="tok",
            tool_name="get_vault_intelligence", args={},
            result='{"x":"2"}',
        )
        wrote = self._call(vault_id=_VAULT, rowcount=0)
        self.assertFalse(wrote)
                                                  
        self.assertEqual(c.get(
            vault_id=_VAULT, token_id="tok",
            tool_name="get_vault_intelligence", args={},
        ), '{"x":"2"}')

    def test_does_not_drop_other_vaults_entries(self):
        c = cache.get_cache()
        other_vault = "00000000-0000-0000-0000-0000000bbbb"
        c.put(
            vault_id=other_vault, token_id="tok",
            tool_name="get_vault_intelligence", args={},
            result='{"other":"1"}',
        )
        self._call(vault_id=_VAULT, rowcount=1)
        self.assertEqual(c.get(
            vault_id=other_vault, token_id="tok",
            tool_name="get_vault_intelligence", args={},
        ), '{"other":"1"}')


class FileDeletedInvalidatesEverything(_Base):
    def test_file_deleted_drops_listings_status_search_relations_expiry(self):
        c = cache.get_cache()
        for tool in (
            "list_vault_files",
            "get_vault_status",
            "search_extracted_text",
            "list_file_relationships",
            "list_expiring_items",
            "list_vault_entities",
        ):
            c.put(
                vault_id=_VAULT, token_id="tok",
                tool_name=tool, args={},
                result='{"x":"1"}',
            )
        c.invalidate_for_event(
            vault_id=_VAULT, event="file_deleted",
        )
        for tool in (
            "list_vault_files",
            "get_vault_status",
            "search_extracted_text",
            "list_file_relationships",
            "list_expiring_items",
            "list_vault_entities",
        ):
            with self.subTest(tool=tool):
                self.assertIsNone(c.get(
                    vault_id=_VAULT, token_id="tok",
                    tool_name=tool, args={},
                ))


class FileRenamedScopedInvalidation(_Base):
    def test_file_renamed_drops_only_listings_metadata_search(self):
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id="tok",
            tool_name="list_vault_files", args={},
            result='{"a":1}',
        )
        c.put(
            vault_id=_VAULT, token_id="tok",
            tool_name="get_file_metadata", args={},
            result='{"b":2}',
        )
        c.put(
            vault_id=_VAULT, token_id="tok",
            tool_name="search_extracted_text", args={},
            result='{"c":3}',
        )
                                   
        c.put(
            vault_id=_VAULT, token_id="tok",
            tool_name="list_expiring_items", args={},
            result='{"d":4}',
        )
        c.put(
            vault_id=_VAULT, token_id="tok",
            tool_name="list_vault_entities", args={},
            result='{"e":5}',
        )
        c.invalidate_for_event(
            vault_id=_VAULT, event="file_renamed",
        )
                  
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id="tok",
            tool_name="list_vault_files", args={},
        ))
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id="tok",
            tool_name="get_file_metadata", args={},
        ))
        self.assertIsNone(c.get(
            vault_id=_VAULT, token_id="tok",
            tool_name="search_extracted_text", args={},
        ))
                   
        self.assertEqual(c.get(
            vault_id=_VAULT, token_id="tok",
            tool_name="list_expiring_items", args={},
        ), '{"d":4}')
        self.assertEqual(c.get(
            vault_id=_VAULT, token_id="tok",
            tool_name="list_vault_entities", args={},
        ), '{"e":5}')


class CredentialEditedInvalidation(_Base):
    def test_drops_credential_metadata_and_intelligence(self):
        c = cache.get_cache()
        for tool in (
            "list_saved_credentials",
            "list_secrets",
            "get_credential_metadata",
            "get_vault_intelligence",
        ):
            c.put(
                vault_id=_VAULT, token_id="tok",
                tool_name=tool, args={},
                result='{"x":"1"}',
            )
        c.invalidate_for_event(
            vault_id=_VAULT, event="credential_edited",
        )
        for tool in (
            "list_saved_credentials",
            "list_secrets",
            "get_credential_metadata",
            "get_vault_intelligence",
        ):
            with self.subTest(tool=tool):
                self.assertIsNone(c.get(
                    vault_id=_VAULT, token_id="tok",
                    tool_name=tool, args={},
                ))


class AnalysisChangedInvalidation(_Base):
    def test_drops_intelligence_categories_entities_chunks_search(self):
        c = cache.get_cache()
        for tool in (
            "get_vault_intelligence",
            "list_document_categories",
            "list_vault_entities",
            "find_files_for_entity",
            "list_file_chunks",
            "search_extracted_text",
            "search_vault_content",
            "inspect_uploaded_file",
        ):
            c.put(
                vault_id=_VAULT, token_id="tok",
                tool_name=tool, args={},
                result='{"x":"1"}',
            )
        c.invalidate_for_event(
            vault_id=_VAULT, event="file_analysis_changed",
        )
        for tool in (
            "get_vault_intelligence",
            "list_document_categories",
            "list_vault_entities",
            "find_files_for_entity",
            "list_file_chunks",
            "search_extracted_text",
            "search_vault_content",
            "inspect_uploaded_file",
        ):
            with self.subTest(tool=tool):
                self.assertIsNone(c.get(
                    vault_id=_VAULT, token_id="tok",
                    tool_name=tool, args={},
                ))


class ExpiryUpdatedInvalidation(_Base):
    def test_drops_expiry_and_intelligence(self):
        c = cache.get_cache()
        for tool in (
            "list_expiring_items",
            "get_expiry_alert",
            "get_vault_intelligence",
        ):
            c.put(
                vault_id=_VAULT, token_id="tok",
                tool_name=tool, args={},
                result='{"x":"1"}',
            )
        c.invalidate_for_event(
            vault_id=_VAULT, event="expiry_updated",
        )
        for tool in (
            "list_expiring_items",
            "get_expiry_alert",
            "get_vault_intelligence",
        ):
            with self.subTest(tool=tool):
                self.assertIsNone(c.get(
                    vault_id=_VAULT, token_id="tok",
                    tool_name=tool, args={},
                ))


class InvalidationFiresOnlyAfterCommit(unittest.TestCase):
    def _read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_file_delete_invalidates_after_conn_commit(self):
        src = self._read("routes/vault_manage_routes.py")
                                     
        idx = src.find('event="file_deleted"')
        self.assertGreater(idx, -1)
                                                                 
                                       
        before = src[max(0, idx - 600): idx]
        self.assertIn("conn.commit()", before)

    def test_file_rename_invalidates_after_conn_commit(self):
        src = self._read("routes/vault_manage_routes.py")
        idx = src.find('event="file_renamed"')
        self.assertGreater(idx, -1)
        before = src[max(0, idx - 600): idx]
        self.assertIn("conn.commit()", before)

    def test_credential_edit_invalidates_after_conn_commit(self):
        src = self._read("routes/vault_manage_routes.py")
        idx = src.find('event="credential_edited"')
        self.assertGreater(idx, -1)
        before = src[max(0, idx - 600): idx]
        self.assertIn("conn.commit()", before)

    def test_credential_delete_invalidates_after_conn_commit(self):
        src = self._read("routes/vault_manage_routes.py")
        idx = src.find('event="credential_deleted"')
        self.assertGreater(idx, -1)
        before = src[max(0, idx - 600): idx]
        self.assertIn("conn.commit()", before)

    def test_expiry_invalidates_after_conn_commit(self):
        src = self._read("expiry_engine.py")
        idx = src.find('event="expiry_updated"')
        self.assertGreater(idx, -1)
        before = src[max(0, idx - 600): idx]
        self.assertIn("conn.commit()", before)

    def test_analysis_status_invalidates_after_conn_commit(self):
                                                              
                                                                 
        src = self._read("vault_analysis.py")
        idx = src.find('event="file_analysis_changed"')
        self.assertGreater(idx, -1)
        before = src[max(0, idx - 600): idx]
        self.assertIn("wrote = bool(affected)", before)
        self.assertIn("if wrote and vault_id", before)

    def test_analysis_status_invalidates_only_when_wrote(self):
                                                          
                                                                  
        src = self._read("vault_analysis.py")
        idx = src.find('event="file_analysis_changed"')
        before = src[max(0, idx - 400): idx]
        self.assertIn("if wrote and vault_id", before)


class InvalidationObservability(_Base):
    def test_invalidation_log_contains_only_closed_set_metadata(self):
                                                          
                                                                
        c = cache.get_cache()
        c.put(
            vault_id=_VAULT, token_id="tok",
            tool_name="list_vault_files",
            args={"query": "supersecretquery"},
            result='{"hits":[]}',
        )

        captured: list[str] = []

        def _fake_info(fmt, *args, **kwargs):
            try:
                captured.append(fmt % args if args else fmt)
            except Exception:
                captured.append(str(fmt))

        with mock.patch.object(
            cache.logger, "info", side_effect=_fake_info,
        ):
            c.invalidate_for_event(
                vault_id=_VAULT, event="file_deleted",
            )

        all_logs = "\n".join(captured)
                                         
        self.assertIn("invalidated", all_logs)
        self.assertIn("event=file_deleted", all_logs)
        self.assertIn("entries_dropped=", all_logs)
        self.assertIn(f"vault={_VAULT[:8]}", all_logs)
                                                           
        self.assertNotIn("supersecretquery", all_logs)
        self.assertNotIn("query=", all_logs)
        self.assertNotIn("args_hash", all_logs)


if __name__ == "__main__":
    unittest.main()
