

import inspect
import re
import unittest
from unittest.mock import MagicMock

import device_monitor


class FakeConnection:


    def __init__(self, *, existing_row, trusted_count):
        self._existing_row = existing_row
        self._trusted_count = trusted_count
        self._sql_log: list[str] = []
        self.committed = False
        self.rolled_back = False
                                                                      
                                                                       
        self._cursor = _FakeCursor(
            existing_row=existing_row,
            trusted_count=trusted_count,
            sql_log=self._sql_log,
        )

    def cursor(self, *_args, **_kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


class _FakeCursor:
    def __init__(self, *, existing_row, trusted_count, sql_log):
        self.existing_row = existing_row
        self.trusted_count = trusted_count
        self.sql_log = sql_log
                                                            
        self._next = "existing"

    def execute(self, sql, _params=None):
        self.sql_log.append(sql)
        if "FROM trusted_devices" in sql and "status = 'trusted'" in sql:
            self._next = "trusted_count"
            return
        if sql.strip().upper().startswith("UPDATE"):
            self._next = "update_done"
            return
        if sql.strip().upper().startswith("INSERT"):
            self._next = "insert_done"
            return
                                                                   
                                                                   
    def fetchone(self):
        if self._next == "existing":
            self._next = "after_first_select"
            return self.existing_row
        if self._next == "trusted_count":
            self._next = "after_count"
            return {"n": self.trusted_count}
        if self._next in ("update_done", "insert_done", "after_first_select",
                         "after_count"):
                                                                       
                              
            if self.existing_row:
                return {"status": self.existing_row["status"]}
            return {"status": "trusted" if self.trusted_count == 0 else "pending"}
        return None


class RegisterOrRefreshIdempotencyTests(unittest.TestCase):
    def test_existing_trusted_row_keeps_trusted_status(self):


        fake_conn = FakeConnection(
            existing_row={"status": "trusted"},
            trusted_count=1,
        )
        original_get_db = device_monitor.get_db
        device_monitor.get_db = lambda: fake_conn
        try:
            result = device_monitor.register_or_refresh(
                vault_id="00000000-0000-4000-8000-0000000000a1",
                device_id="dev-abc",
                label="refreshed-label",
                user_agent_brand="Chrome",
                ip_prefix="203.0.113",
            )
        finally:
            device_monitor.get_db = original_get_db

                           
        self.assertEqual(result["status"], "trusted")
        self.assertFalse(result["is_first_device"])
        self.assertFalse(result["created"])
                                                                  
                                                              
        update_stmts = [
            sql for sql in fake_conn._sql_log
            if sql.strip().upper().startswith("UPDATE")
        ]
        self.assertTrue(update_stmts, msg="expected an UPDATE on refresh")
        for sql in update_stmts:
            normalized = re.sub(r"\s+", " ", sql.lower())
            self.assertNotRegex(
                normalized,
                r"\bset\b.*\bstatus\s*=",
                msg=f"UPDATE must not modify status; got: {sql!r}",
            )

    def test_existing_pending_row_stays_pending(self):


        fake_conn = FakeConnection(
            existing_row={"status": "pending"},
            trusted_count=0,
        )
        original_get_db = device_monitor.get_db
        device_monitor.get_db = lambda: fake_conn
        try:
            result = device_monitor.register_or_refresh(
                vault_id="00000000-0000-4000-8000-0000000000a2",
                device_id="dev-abc",
                label=None,
                user_agent_brand=None,
                ip_prefix=None,
            )
        finally:
            device_monitor.get_db = original_get_db

        self.assertEqual(result["status"], "pending")
        self.assertFalse(result["is_first_device"])

    def test_new_device_uses_upsert_not_blind_insert(self):


        fake_conn = FakeConnection(existing_row=None, trusted_count=0)
        original_get_db = device_monitor.get_db
        device_monitor.get_db = lambda: fake_conn
        try:
            device_monitor.register_or_refresh(
                vault_id="00000000-0000-4000-8000-0000000000a3",
                device_id="dev-new",
                label="fresh",
                user_agent_brand="Chrome",
                ip_prefix="203.0.113",
            )
        finally:
            device_monitor.get_db = original_get_db

        insert_stmts = [
            sql for sql in fake_conn._sql_log
            if sql.strip().upper().startswith("INSERT")
        ]
        self.assertTrue(insert_stmts, msg="expected an INSERT on first reg")
        for sql in insert_stmts:
            self.assertIn(
                "ON CONFLICT", sql.upper(),
                msg=f"INSERT must be UPSERT-shaped; got: {sql!r}",
            )


class RegisterOrRefreshStaticContractTests(unittest.TestCase):


    def test_existing_row_update_only_touches_metadata(self):
        source = inspect.getsource(device_monitor.register_or_refresh)
                                                                    
                                                                  
        update_match = re.search(
            r"UPDATE\s+trusted_devices\s+SET([\s\S]*?)WHERE",
            source,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(
            update_match, msg="expected an UPDATE on refresh in source",
        )
        update_body = update_match.group(1).lower()
                                                                     
                                                                      
        self.assertNotRegex(
            update_body,
            r"\bstatus\b\s*=",
            msg="refresh UPDATE is modifying the status column",
        )
                                                                     
                                                                    
        self.assertIn("last_seen_at", update_body)


if __name__ == "__main__":
    unittest.main()
