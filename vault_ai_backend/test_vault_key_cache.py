

from __future__ import annotations

import threading
import time
import unittest

from vault_key_cache import get_cache, reset_for_tests


class StoreAndGetTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests(idle_ttl_seconds=60, hard_ttl_seconds=3600)

    def test_store_then_get_returns_the_same_key(self) -> None:
        c = get_cache()
        c.store(vault_id="v1", token_id="t1", key=b"K" * 32)
        self.assertEqual(c.get(vault_id="v1", token_id="t1"), b"K" * 32)

    def test_missing_entry_returns_none(self) -> None:
        c = get_cache()
        self.assertIsNone(c.get(vault_id="vX", token_id="tX"))

    def test_empty_scope_returns_none(self) -> None:
        c = get_cache()
        c.store(vault_id="v1", token_id="t1", key=b"K" * 32)
        self.assertIsNone(c.get(vault_id="", token_id="t1"))
        self.assertIsNone(c.get(vault_id="v1", token_id=""))

    def test_store_rejects_non_bytes_key(self) -> None:
        c = get_cache()
        with self.assertRaises(TypeError):
            c.store(vault_id="v1", token_id="t1", key="not-bytes")                

    def test_store_with_empty_scope_is_noop(self) -> None:
        c = get_cache()
        c.store(vault_id="", token_id="t1", key=b"K" * 32)
        c.store(vault_id="v1", token_id="", key=b"K" * 32)
        self.assertEqual(c.snapshot_counts()["active_entries"], 0)


class CrossVaultCrossSessionIsolationTests(unittest.TestCase):


    def setUp(self) -> None:
        reset_for_tests(idle_ttl_seconds=60, hard_ttl_seconds=3600)

    def test_wrong_vault_cannot_read_another_vault_key(self) -> None:
        c = get_cache()
        c.store(vault_id="vault-alice", token_id="sess-alice",
                key=b"A" * 32)
                                                        
        self.assertIsNone(c.get(vault_id="vault-alice", token_id="sess-bob"))
                                                        
        self.assertIsNone(c.get(vault_id="vault-bob", token_id="sess-alice"))
                                                   
        self.assertIsNone(c.get(vault_id="vault-bob", token_id="sess-bob"))

    def test_two_users_two_vaults_each_isolated(self) -> None:
        c = get_cache()
        c.store(vault_id="vA", token_id="sA", key=b"A" * 32)
        c.store(vault_id="vB", token_id="sB", key=b"B" * 32)
        self.assertEqual(c.get(vault_id="vA", token_id="sA"), b"A" * 32)
        self.assertEqual(c.get(vault_id="vB", token_id="sB"), b"B" * 32)
                                        
        self.assertIsNone(c.get(vault_id="vA", token_id="sB"))
        self.assertIsNone(c.get(vault_id="vB", token_id="sA"))

    def test_same_vault_two_sessions_each_isolated(self) -> None:


        c = get_cache()
        c.store(vault_id="v1", token_id="phone", key=b"P" * 32)
        c.store(vault_id="v1", token_id="laptop", key=b"L" * 32)
        self.assertEqual(c.get(vault_id="v1", token_id="phone"), b"P" * 32)
        self.assertEqual(c.get(vault_id="v1", token_id="laptop"), b"L" * 32)
                                                     
        n = c.clear_session("phone")
        self.assertEqual(n, 1)
        self.assertIsNone(c.get(vault_id="v1", token_id="phone"))
        self.assertEqual(c.get(vault_id="v1", token_id="laptop"), b"L" * 32)


class TtlTests(unittest.TestCase):
    def test_idle_ttl_expires_entry(self) -> None:
        c = reset_for_tests(idle_ttl_seconds=0.05, hard_ttl_seconds=3600)
        c.store(vault_id="v1", token_id="t1", key=b"K" * 32)
        time.sleep(0.10)
        self.assertIsNone(c.get(vault_id="v1", token_id="t1"))

    def test_get_refreshes_idle_clock(self) -> None:
        c = reset_for_tests(idle_ttl_seconds=0.20, hard_ttl_seconds=3600)
        c.store(vault_id="v1", token_id="t1", key=b"K" * 32)
                                                                       
        for _ in range(5):
            time.sleep(0.05)
            self.assertEqual(c.get(vault_id="v1", token_id="t1"), b"K" * 32)

    def test_hard_ttl_caps_total_lifetime(self) -> None:
        c = reset_for_tests(idle_ttl_seconds=3600, hard_ttl_seconds=0.10)
        c.store(vault_id="v1", token_id="t1", key=b"K" * 32)
        time.sleep(0.15)
                                                          
        self.assertIsNone(c.get(vault_id="v1", token_id="t1"))


class ClearOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests(idle_ttl_seconds=60, hard_ttl_seconds=3600)

    def test_clear_session_drops_all_vaults_for_that_session(self) -> None:
        c = get_cache()
                                                        
        c.store(vault_id="v1", token_id="t1", key=b"1" * 32)
        c.store(vault_id="v2", token_id="t1", key=b"2" * 32)
        c.store(vault_id="v1", token_id="t2", key=b"3" * 32)
        dropped = c.clear_session("t1")
        self.assertEqual(dropped, 2)
        self.assertIsNone(c.get(vault_id="v1", token_id="t1"))
        self.assertIsNone(c.get(vault_id="v2", token_id="t1"))
        self.assertEqual(c.get(vault_id="v1", token_id="t2"), b"3" * 32)

    def test_clear_vault_drops_all_sessions_for_that_vault(self) -> None:
        c = get_cache()
        c.store(vault_id="v1", token_id="t1", key=b"1" * 32)
        c.store(vault_id="v1", token_id="t2", key=b"2" * 32)
        c.store(vault_id="v2", token_id="t1", key=b"3" * 32)
        dropped = c.clear_vault("v1")
        self.assertEqual(dropped, 2)
        self.assertIsNone(c.get(vault_id="v1", token_id="t1"))
        self.assertIsNone(c.get(vault_id="v1", token_id="t2"))
        self.assertEqual(c.get(vault_id="v2", token_id="t1"), b"3" * 32)

    def test_clear_all_drops_everything(self) -> None:
        c = get_cache()
        for i in range(5):
            c.store(vault_id=f"v{i}", token_id=f"t{i}", key=b"K" * 32)
        dropped = c.clear_all()
        self.assertEqual(dropped, 5)
        self.assertEqual(c.snapshot_counts()["active_entries"], 0)


class ObservabilityNeverLeaksKeysTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests(idle_ttl_seconds=60, hard_ttl_seconds=3600)

    def test_snapshot_counts_returns_only_counts(self) -> None:
        c = get_cache()
        c.store(vault_id="vault-secret", token_id="session-secret",
                key=b"S" * 32)
        snap = c.snapshot_counts()
                                                                       
        self.assertEqual(
            set(snap.keys()),
            {
                "active_entries", "distinct_vaults", "distinct_sessions",
                "idle_ttl_seconds", "hard_ttl_seconds",
            },
        )
                                                                      
                                             
        for v in snap.values():
            self.assertIsInstance(v, (int, float))
                                                                  
                                                        
        flat = repr(snap)
        self.assertNotIn("vault-secret", flat)
        self.assertNotIn("session-secret", flat)
        self.assertNotIn("SSSS", flat)                           

    def test_active_scopes_only_returns_vault_and_token_tuples(self) -> None:
        c = get_cache()
        c.store(vault_id="v1", token_id="t1", key=b"K" * 32)
        scopes = c.active_scopes()
                                                             
        for vid, tid in scopes:
            self.assertIsInstance(vid, str)
            self.assertIsInstance(tid, str)
        self.assertEqual(scopes, [("v1", "t1")])


class VacuumTests(unittest.TestCase):
    def test_vacuum_removes_expired_only(self) -> None:
        c = reset_for_tests(idle_ttl_seconds=0.05, hard_ttl_seconds=3600)
        c.store(vault_id="v-old", token_id="t-old", key=b"O" * 32)
        time.sleep(0.10)
        c.store(vault_id="v-new", token_id="t-new", key=b"N" * 32)
        n = c.vacuum()
        self.assertEqual(n, 1)
        self.assertIsNone(c.get(vault_id="v-old", token_id="t-old"))
        self.assertEqual(c.get(vault_id="v-new", token_id="t-new"), b"N" * 32)

    def test_active_scopes_vacuums_before_returning(self) -> None:
        c = reset_for_tests(idle_ttl_seconds=0.05, hard_ttl_seconds=3600)
        c.store(vault_id="v-old", token_id="t-old", key=b"O" * 32)
        time.sleep(0.10)
        scopes = c.active_scopes()
                                                                 
        self.assertEqual(scopes, [])


class ConcurrencyTests(unittest.TestCase):


    def setUp(self) -> None:
        reset_for_tests(idle_ttl_seconds=60, hard_ttl_seconds=3600)

    def test_concurrent_stores_do_not_corrupt_state(self) -> None:
        c = get_cache()
        N = 200

        def worker(i: int) -> None:
            c.store(vault_id=f"v{i}", token_id=f"t{i}", key=bytes([i % 256]) * 32)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(c.snapshot_counts()["active_entries"], N)
        for i in range(N):
            self.assertEqual(
                c.get(vault_id=f"v{i}", token_id=f"t{i}"),
                bytes([i % 256]) * 32,
            )


class NoPersistenceTests(unittest.TestCase):


    def test_module_does_not_import_db_helpers(self) -> None:
        import inspect, vault_key_cache
        src = inspect.getsource(vault_key_cache)
        for forbidden in (
            "psycopg2", "sqlalchemy", "from vault_core import get_db",
            ".execute(", "INSERT", "UPDATE", "DELETE", "SELECT",
            "open(",               
            "logger.info", "logger.warning", "logger.error", "logger.debug",
            "print(",             
        ):
            self.assertNotIn(
                forbidden, src,
                f"vault_key_cache must not contain {forbidden!r} — "
                "the cache lives in memory only and never logs",
            )


if __name__ == "__main__":
    unittest.main()
