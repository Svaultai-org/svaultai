

from __future__ import annotations

import asyncio
import json
import os
import time
import unittest
from unittest import mock

import vault_intelligence_cache as cache_mod
from vault_intelligence_cache import (
    DEFAULT_STALE_AFTER_SECONDS,
    REFRESH_IDLE,
    REFRESH_REFRESHING,
    REFRESH_STALE,
    SCHEMA_VERSION,
    CachedSnapshotRow,
    canonical_snapshot_hash,
    read_cache,
    write_cache,
)
import vault_intelligence_updater as updater_mod


_KEY_A = b"\x11" * 32
_KEY_B = b"\x22" * 32


def _make_fake_db_state():


    table: dict[str, dict] = {}

    def _fake_get_db():
        conn = mock.MagicMock()
        cur = mock.MagicMock()

        def _execute(sql, params=()):
            sql_l = sql.lower()
            if sql_l.lstrip().startswith("select"):
                vid = params[0]
                cur._last_row = table.get(vid)
                cur._last_was_select = True
            elif "insert into vault_intelligence_summary" in sql_l \
                    and "on conflict" in sql_l:
                                        
                                                              
                vid = params[0]
                row = table.get(vid, {})
                if "encrypted_snapshot" in sql_l:
                    (
                        v, sv, cov, fc, ssc, enc, h, status, _status2,
                    ) = params
                    row.update({
                        "vault_id":              v,
                        "schema_version":        sv,
                        "coverage_jsonb":        json.loads(cov)
                                                 if isinstance(cov, str) else cov,
                        "file_counts_jsonb":     json.loads(fc)
                                                 if isinstance(fc, str) else fc,
                        "saved_services_count":  ssc,
                        "encrypted_snapshot":    enc,
                        "snapshot_hash":         h,
                        "last_refreshed_epoch":  time.time(),
                        "refresh_status":        status,
                        "refresh_error_class":   None,
                        "refresh_error_reason":  None,
                    })
                elif len(params) == 4 and "refresh_error_class" in sql_l:
                    v, status, ec, er = params[:4]
                    row.update({
                        "vault_id":             v,
                        "refresh_status":       status,
                        "refresh_error_class":  ec,
                        "refresh_error_reason": er,
                    })
                else:
                                                                          
                    v, status, _status2 = params
                    row.update({
                        "vault_id":             v,
                        "refresh_status":       status,
                    })
                table[v] = row
                cur._last_was_select = False
            else:
                cur._last_was_select = False
            return None

        def _fetchone():
            if not getattr(cur, "_last_was_select", False):
                return None
            return cur._last_row

        cur.execute.side_effect = _execute
        cur.fetchone.side_effect = _fetchone
        conn.cursor.return_value = cur
        return conn

    return table, _fake_get_db


class CacheRowEncryptionTests(unittest.TestCase):
    def test_snapshot_payload_is_encrypted_at_rest(self):
        table, fake_db = _make_fake_db_state()
        snap = {
            "schema_version": 1,
            "coverage": {"analyzed": 7, "total": 7, "is_complete": True},
            "files_by_kind": {"counts": {"document": 7}},
            "credentials": {"saved_credential_services_count": 3},
            "recent_uploads": {
                "files": [{"file_name": "PLAINTEXT-DO-NOT-LEAK.pdf"}],
            },
        }
        with mock.patch("main.get_db", side_effect=fake_db):
            ok = write_cache("vault-A", _KEY_A, snap)
        self.assertTrue(ok)
                                                            
                              
        stored = table["vault-A"]
        enc = stored["encrypted_snapshot"]
        self.assertIsInstance(enc, str)
        self.assertNotIn("PLAINTEXT-DO-NOT-LEAK", enc)
                                   
        self.assertEqual(len(stored["snapshot_hash"] or ""), 64)

    def test_wrong_key_cannot_decrypt(self):
        table, fake_db = _make_fake_db_state()
        snap = {"coverage": {"analyzed": 1, "total": 1}}
        with mock.patch("main.get_db", side_effect=fake_db):
            write_cache("vault-A", _KEY_A, snap)
                                      
            row = read_cache("vault-A", _KEY_B)
        self.assertFalse(row.available)
        self.assertEqual(row.reason, "decrypt_failed")
        self.assertIsNone(row.snapshot)


class CacheVaultScopingTests(unittest.TestCase):
    def test_two_vaults_round_trip_independently(self):
        table, fake_db = _make_fake_db_state()
        snap_a = {"coverage": {"analyzed": 1, "total": 1},
                  "files_by_kind": {"counts": {"document": 1}},
                  "credentials": {"saved_credential_services_count": 1}}
        snap_b = {"coverage": {"analyzed": 99, "total": 100},
                  "files_by_kind": {"counts": {"image": 99}},
                  "credentials": {"saved_credential_services_count": 5}}
        with mock.patch("main.get_db", side_effect=fake_db):
            write_cache("vault-A", _KEY_A, snap_a)
            write_cache("vault-B", _KEY_B, snap_b)
            row_a = read_cache("vault-A", _KEY_A)
            row_b = read_cache("vault-B", _KEY_B)
        self.assertTrue(row_a.available)
        self.assertTrue(row_b.available)
        self.assertEqual(
            row_a.snapshot["coverage"]["analyzed"], 1,
        )
        self.assertEqual(
            row_b.snapshot["coverage"]["analyzed"], 99,
        )

    def test_vault_b_cannot_read_vault_a(self):
                                                                  
                                                               
        table, fake_db = _make_fake_db_state()
        snap_a = {"coverage": {"analyzed": 1, "total": 1}}
        with mock.patch("main.get_db", side_effect=fake_db):
            write_cache("vault-A", _KEY_A, snap_a)
            row = read_cache("vault-A", _KEY_B)
        self.assertFalse(row.available)
        self.assertEqual(row.reason, "decrypt_failed")


class CacheKeyGateTests(unittest.TestCase):
    def test_short_key_returns_vault_locked(self):
        table, fake_db = _make_fake_db_state()
        snap = {"coverage": {"analyzed": 1, "total": 1}}
        with mock.patch("main.get_db", side_effect=fake_db):
            write_cache("vault-A", _KEY_A, snap)
            row = read_cache("vault-A", b"short")
        self.assertFalse(row.available)
        self.assertEqual(row.reason, "vault_locked")
        self.assertIsNone(row.snapshot)

    def test_write_with_short_key_refused(self):
        table, fake_db = _make_fake_db_state()
        with mock.patch("main.get_db", side_effect=fake_db):
            ok = write_cache("vault-A", b"short", {"coverage": {}})
        self.assertFalse(ok)


class CacheStalenessTests(unittest.TestCase):
    def test_stale_row_returns_snapshot_with_reason_stale(self):
        table, fake_db = _make_fake_db_state()
        snap = {"coverage": {"analyzed": 5, "total": 5}}
        with mock.patch("main.get_db", side_effect=fake_db):
            write_cache("vault-A", _KEY_A, snap)
                                             
        table["vault-A"]["last_refreshed_epoch"] = time.time() - (
            DEFAULT_STALE_AFTER_SECONDS + 1
        )
        with mock.patch("main.get_db", side_effect=fake_db):
            row = read_cache("vault-A", _KEY_A)
        self.assertTrue(row.available)
        self.assertEqual(row.reason, "stale")
        self.assertIsNotNone(row.snapshot)

    def test_cache_miss_when_row_absent(self):
        table, fake_db = _make_fake_db_state()
        with mock.patch("main.get_db", side_effect=fake_db):
            row = read_cache("vault-no-row", _KEY_A)
        self.assertFalse(row.available)
        self.assertEqual(row.reason, "cache_miss")


class UpdaterTriggerHookTests(unittest.TestCase):
    def setUp(self):
        updater_mod.clear_dirty_for_tests()

    def tearDown(self):
        updater_mod.clear_dirty_for_tests()

    def _mark_via(self, fn):
        with mock.patch(
            "vault_intelligence_cache.mark_stale",
        ):
            fn("vault-A")

    def test_on_vault_unlock_marks_dirty(self):
        self._mark_via(updater_mod.on_vault_unlock)
        self.assertEqual(updater_mod.get_dirty_count(), 1)

    def test_on_file_uploaded_marks_dirty(self):
        self._mark_via(updater_mod.on_file_uploaded)
        self.assertEqual(updater_mod.get_dirty_count(), 1)

    def test_on_file_extracted_marks_dirty(self):
        self._mark_via(updater_mod.on_file_extracted)
        self.assertEqual(updater_mod.get_dirty_count(), 1)

    def test_on_file_ocr_marks_dirty(self):
        self._mark_via(updater_mod.on_file_ocr)
        self.assertEqual(updater_mod.get_dirty_count(), 1)

    def test_on_file_transcribed_marks_dirty(self):
        self._mark_via(updater_mod.on_file_transcribed)
        self.assertEqual(updater_mod.get_dirty_count(), 1)

    def test_on_file_chunked_marks_dirty(self):
        self._mark_via(updater_mod.on_file_chunked)
        self.assertEqual(updater_mod.get_dirty_count(), 1)

    def test_on_credential_changed_marks_dirty(self):
        self._mark_via(updater_mod.on_credential_changed)
        self.assertEqual(updater_mod.get_dirty_count(), 1)

    def test_repeated_marks_coalesce_to_one_entry(self):
        with mock.patch(
            "vault_intelligence_cache.mark_stale",
        ):
            for _ in range(20):
                updater_mod.on_file_uploaded("vault-A")
        self.assertEqual(updater_mod.get_dirty_count(), 1)


class TriggerWiringSourceGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def _read(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        cls._main = _read("main.py")
        cls._startup = _read("vault_startup.py")
        cls._workers = {
            name: _read(f"vault_{name}_worker.py")
            for name in (
                "analysis", "ocr", "audio", "video", "brain", "archive",
            )
        }

    def test_startup_spawns_updater(self):
        self.assertIn(
            "startup_intelligence_updater()", self._startup,
        )

    def test_main_imports_unlock_trigger(self):
        self.assertIn(
            "from vault_intelligence_updater import on_vault_unlock",
            self._main,
        )

    def test_main_imports_upload_trigger(self):
        self.assertIn(
            "from vault_intelligence_updater import on_file_uploaded",
            self._main,
        )

    def test_main_imports_credential_trigger(self):
        self.assertIn(
            "from vault_intelligence_updater import on_credential_changed",
            self._main,
        )

    def test_analysis_worker_fires_extracted(self):
        self.assertIn(
            "from vault_intelligence_updater import on_file_extracted",
            self._workers["analysis"],
        )

    def test_ocr_worker_fires_ocr(self):
        self.assertIn(
            "from vault_intelligence_updater import on_file_ocr",
            self._workers["ocr"],
        )

    def test_audio_worker_fires_transcribed(self):
        self.assertIn(
            "from vault_intelligence_updater import on_file_transcribed",
            self._workers["audio"],
        )

    def test_video_worker_fires_transcribed(self):
        self.assertIn(
            "from vault_intelligence_updater import on_file_transcribed",
            self._workers["video"],
        )

    def test_brain_worker_fires_chunked(self):
        self.assertIn(
            "from vault_intelligence_updater import on_file_chunked",
            self._workers["brain"],
        )

    def test_archive_worker_fires_extracted(self):
        self.assertIn(
            "from vault_intelligence_updater import on_file_extracted",
            self._workers["archive"],
        )


class ChatReadsCacheFirstTests(unittest.TestCase):
    def setUp(self):
        updater_mod.clear_dirty_for_tests()

    def tearDown(self):
        updater_mod.clear_dirty_for_tests()

    def test_cache_hit_skips_live_recompute(self):
        from vault_knowledge_tools import get_vault_intelligence
        fake_snap = {
            "schema_version": 1,
            "coverage": {"analyzed": 120, "total": 425,
                         "is_complete": False, "percent": 28.2},
            "files_by_kind": {"counts": {"document": 200}},
            "credentials": {"saved_credential_services_count": 7},
            "from_cache_sentinel": "yes",
        }
        cached = CachedSnapshotRow(
            available=True, snapshot=fake_snap,
            last_refreshed_at=time.time(),
            refresh_status=REFRESH_IDLE,
            refresh_error_class=None, refresh_error_reason=None,
            snapshot_hash="abc",
            reason=None,
        )
                                                                     
                     
        with mock.patch(
            "vault_intelligence_cache.read_cache",
            return_value=cached,
        ), mock.patch(
            "vault_knowledge_tools._coverage_block",
            side_effect=AssertionError("live recompute should not fire"),
        ):
            blob = get_vault_intelligence(vault_id="vault-A", key=_KEY_A)
        snap = json.loads(blob)
        self.assertEqual(snap["from_cache_sentinel"], "yes")
        self.assertEqual(snap["cache"]["source"], "cache")
        self.assertFalse(snap["cache"]["stale"])

    def test_stale_cache_returns_snapshot_and_enqueues_refresh(self):
        from vault_knowledge_tools import get_vault_intelligence
        fake_snap = {
            "schema_version": 1,
            "coverage": {"analyzed": 1, "total": 1, "is_complete": True},
        }
        cached = CachedSnapshotRow(
            available=True, snapshot=fake_snap,
            last_refreshed_at=time.time() - 99999,
            refresh_status=REFRESH_STALE,
            refresh_error_class=None, refresh_error_reason=None,
            snapshot_hash="abc",
            reason="stale",
        )
        with mock.patch(
            "vault_intelligence_cache.read_cache",
            return_value=cached,
        ), mock.patch(
            "vault_intelligence_cache.mark_stale",
        ):
            blob = get_vault_intelligence(vault_id="vault-A", key=_KEY_A)
        snap = json.loads(blob)
        self.assertEqual(snap["cache"]["source"], "cache")
        self.assertTrue(snap["cache"]["stale"])
                                                     
        self.assertEqual(updater_mod.get_dirty_count(), 1)

    def test_cache_miss_falls_back_to_live_and_enqueues(self):
        from vault_knowledge_tools import get_vault_intelligence
        empty = CachedSnapshotRow(
            available=False, snapshot=None,
            last_refreshed_at=None,
            refresh_status=REFRESH_IDLE,
            refresh_error_class=None, refresh_error_reason=None,
            snapshot_hash=None, reason="cache_miss",
        )
        with mock.patch(
            "vault_intelligence_cache.read_cache",
            return_value=empty,
        ), mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 425, "analyzed": 0, "pending": 425,
                "processing": 0, "failed": 0, "unsupported": 0,
            },
        ), mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=[],
        ), mock.patch(
            "vault_intelligence_cache.mark_stale",
        ), mock.patch("main.get_db") as _db:
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.return_value = []
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            blob = get_vault_intelligence(
                vault_id="vault-A", key=_KEY_A,
            )
        snap = json.loads(blob)
        self.assertEqual(snap["cache"]["source"], "live")
        self.assertIn("coverage", snap)
                                 
        self.assertEqual(snap["coverage"]["total"], 425)
        self.assertEqual(snap["coverage"]["analyzed"], 0)
        self.assertFalse(snap["coverage"]["is_complete"])
                                                     
        self.assertEqual(updater_mod.get_dirty_count(), 1)


class CoverageTransparencyTests(unittest.TestCase):
    def test_coverage_flag_surfaces_when_incomplete(self):
        from vault_knowledge_tools import get_vault_intelligence
        empty = CachedSnapshotRow(
            available=False, snapshot=None,
            last_refreshed_at=None,
            refresh_status=REFRESH_IDLE,
            refresh_error_class=None, refresh_error_reason=None,
            snapshot_hash=None, reason="cache_miss",
        )
        with mock.patch(
            "vault_intelligence_cache.read_cache", return_value=empty,
        ), mock.patch(
            "main.list_uploaded_files", return_value=[],
        ), mock.patch(
            "vault_analysis.analysis_coverage_for_vault",
            return_value={
                "total": 425, "analyzed": 120, "pending": 200,
                "processing": 100, "failed": 5, "unsupported": 0,
            },
        ), mock.patch(
            "main._list_uploaded_files_for_credential_search",
            return_value=[],
        ), mock.patch(
            "vault_intelligence_cache.mark_stale",
        ), mock.patch("main.get_db") as _db:
            updater_mod.clear_dirty_for_tests()
            _cur = mock.MagicMock()
            _cur.fetchone.return_value = {"n": 0}
            _cur.fetchall.return_value = []
            _conn = mock.MagicMock()
            _conn.cursor.return_value = _cur
            _db.return_value = _conn
            snap = json.loads(get_vault_intelligence(
                vault_id="vault-A", key=_KEY_A,
            ))
            updater_mod.clear_dirty_for_tests()
                                                      
        self.assertFalse(snap["coverage"]["is_complete"])
                           
        self.assertAlmostEqual(snap["coverage"]["percent"], 28.2, places=1)


class CachedSnapshotSafetyFloorTests(unittest.TestCase):
    def test_canonical_hash_is_stable_and_hex(self):
        snap = {"coverage": {"a": 1, "b": 2}}
        h = canonical_snapshot_hash(snap)
        self.assertEqual(len(h), 64)
                                            
        h2 = canonical_snapshot_hash({"coverage": {"b": 2, "a": 1}})
        self.assertEqual(h, h2)

    def test_snapshot_blob_has_no_secret_shaped_keys(self):
        table, fake_db = _make_fake_db_state()
                                                     
        snap = {
            "schema_version": 1,
            "coverage": {"analyzed": 1, "total": 1},
            "files_by_kind": {"counts": {"document": 1}},
            "credentials": {
                "saved_credential_services_count": 1,
                                                                
                                                               
            },
        }
        with mock.patch("main.get_db", side_effect=fake_db):
            write_cache("vault-A", _KEY_A, snap)
            row = read_cache("vault-A", _KEY_A)
                                                              
                                                        
        for forbidden in (
            "password", "secret", "token", "pin", "private_key",
            "api_key", "encrypted_data", "encrypted_chunk_text",
            "extracted_text",
        ):
            self.assertNotIn(forbidden, row.snapshot)


if __name__ == "__main__":
    unittest.main()
