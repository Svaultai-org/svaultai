

from __future__ import annotations

import inspect
import os
import re
import unittest
from contextlib import contextmanager

import device_gate


@contextmanager
def env_vars(**vars_to_set):

    saved = {k: os.environ.get(k) for k in vars_to_set}
    try:
        for k, v in vars_to_set.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _clear_all_dev_env():
    return env_vars(
        VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=None,
        VAULTAI_ENV=None,
        ENVIRONMENT=None,
        FLASK_ENV=None,
        NODE_ENV=None,
    )


class IsDevAutoTrustEnabledTests(unittest.TestCase):
    def test_default_is_disabled(self):
                                                                   
                                             
        with _clear_all_dev_env():
            self.assertFalse(device_gate.is_dev_auto_trust_enabled())

    def test_flag_alone_does_not_enable_in_unknown_env(self):
                                                              
                                                                 
        with _clear_all_dev_env(), env_vars(
            VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST="true",
        ):
            self.assertFalse(device_gate.is_dev_auto_trust_enabled())

    def test_dev_env_alone_does_not_enable(self):
                                                               
                                                                     
        with _clear_all_dev_env(), env_vars(VAULTAI_ENV="local"):
            self.assertFalse(device_gate.is_dev_auto_trust_enabled())

    def test_both_conditions_enable(self):
        with _clear_all_dev_env(), env_vars(
            VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST="true",
            VAULTAI_ENV="local",
        ):
            self.assertTrue(device_gate.is_dev_auto_trust_enabled())

    def test_environment_var_also_recognised(self):
                                                             
        with _clear_all_dev_env(), env_vars(
            VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST="true",
            ENVIRONMENT="development",
        ):
            self.assertTrue(device_gate.is_dev_auto_trust_enabled())

    def test_production_env_token_blocks(self):
                                                                    
                
        with _clear_all_dev_env(), env_vars(
            VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST="true",
            VAULTAI_ENV="production",
        ):
            self.assertFalse(device_gate.is_dev_auto_trust_enabled())

    def test_flag_must_be_literal_true(self):
                                                                  
                                                    
        for raw in ("1", "yes", "on", "TRUE_ISH", "y"):
            with _clear_all_dev_env(), env_vars(
                VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=raw,
                VAULTAI_ENV="local",
            ):
                with self.subTest(flag_value=raw):
                    self.assertFalse(device_gate.is_dev_auto_trust_enabled())

    def test_flag_case_insensitive(self):
        for raw in ("true", "TRUE", "True"):
            with _clear_all_dev_env(), env_vars(
                VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST=raw,
                VAULTAI_ENV="local",
            ):
                with self.subTest(flag_value=raw):
                    self.assertTrue(device_gate.is_dev_auto_trust_enabled())


class VerifyTrustedDeviceDevAutoTrustBranchTests(unittest.TestCase):


    def setUp(self):
        self.source = inspect.getsource(device_gate.verify_trusted_device)

    def test_branch_exists(self):
                                                                  
                                                                      
        self.assertIn("is_dev_auto_trust_enabled()", self.source)
        self.assertIn("DEV_AUTO_TRUST", self.source)

    def test_branch_refuses_revoked(self):
                                                                   
                                                                   
        m = re.search(
            r"status\s*!=\s*\"revoked\".*is_dev_auto_trust_enabled\(\)",
            self.source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(
            m,
            msg=(
                "expected `if status != 'revoked' and "
                "is_dev_auto_trust_enabled():` form in verify_trusted_device"
            ),
        )

    def test_branch_calls_auto_trust(self):
                                                                        
                                                                      
        self.assertIn(
            "_auto_trust(vault_id, device_id, db_status)", self.source,
        )


class GateRejectsPendingWhenFlagOffTests(unittest.TestCase):


    def test_pending_with_flag_off_resolves_to_pending(self):
        with _clear_all_dev_env():
            status, msg = device_gate.resolve_response_status(
                db_status="pending", row_missing=False,
            )
            self.assertEqual(status, "pending")
            self.assertIn("not trusted", msg.lower())


class CleanupPendingContractTests(unittest.TestCase):


    def test_cleanup_sql_only_deletes_pending(self):
        from routes import device_routes
        source = inspect.getsource(
            device_routes.dev_cleanup_pending_devices,
        )
                                                                
        m = re.search(
            r"DELETE\s+FROM\s+trusted_devices\s+WHERE([\s\S]*?)RETURNING",
            source,
            flags=re.IGNORECASE,
        )
        self.assertIsNotNone(m, msg="expected a single DELETE in cleanup")
        where_clause = m.group(1).lower()
                                                                   
                                                                      
        self.assertRegex(where_clause, r"status\s*=\s*'pending'")
                                                                     
                                                                
        self.assertNotIn("trusted'", where_clause)
        self.assertNotIn("revoked'", where_clause)

    def test_cleanup_refuses_when_flag_off(self):
                                                                      
                                                                   
        from routes import device_routes
        source = inspect.getsource(
            device_routes.dev_cleanup_pending_devices,
        )
        self.assertIn("is_dev_auto_trust_enabled()", source)
        self.assertIn("dev_cleanup_disabled", source)


class ResetTrustStateContractTests(unittest.TestCase):


    def test_two_step_sql_upserts_current_then_deletes_others(self):
                                                                   
                                                               
        from routes import device_routes
        source = inspect.getsource(device_routes.dev_reset_trust_state)

        upsert = re.search(
            r"INSERT\s+INTO\s+trusted_devices[\s\S]*?ON\s+CONFLICT[\s\S]*?"
            r"status\s*=\s*'trusted'",
            source, flags=re.IGNORECASE,
        )
        self.assertIsNotNone(
            upsert,
            "expected an INSERT … ON CONFLICT … status='trusted' upsert "
            "of the current device before any deletes",
        )

        delete = re.search(
            r"DELETE\s+FROM\s+trusted_devices\s+WHERE([\s\S]*?)RETURNING",
            source, flags=re.IGNORECASE,
        )
        self.assertIsNotNone(delete, "expected a DELETE with RETURNING")
        where_clause = delete.group(1).lower()
                                                                    
                                                                      
        self.assertRegex(
            where_clause,
            r"device_id\s*(<>|!=)\s*%s",
            "DELETE must exclude the kept device_id — without this, the "
            "endpoint would wipe the very row it just upserted.",
        )
                                                                  
                                                           
        self.assertRegex(where_clause, r"vault_id\s*=\s*%s")

                                                                      
        upsert_pos = source.lower().index("on conflict")
        delete_pos = source.lower().index("delete from trusted_devices")
        self.assertLess(
            upsert_pos, delete_pos,
            "UPSERT of current device must run BEFORE the DELETE of "
            "others — reversing this order opens a window where "
            "concurrent gate checks see zero trusted rows.",
        )

    def test_two_key_dev_gate_present(self):
                                                                    
                                                                   
        from routes import device_routes
        source = inspect.getsource(device_routes.dev_reset_trust_state)
        self.assertIn("is_dev_auto_trust_enabled()", source)
        self.assertIn("dev_reset_disabled", source)

    def test_missing_x_device_id_refuses_400(self):
                                                                     
                                                                   
        from routes import device_routes
        source = inspect.getsource(device_routes.dev_reset_trust_state)
        self.assertIn("missing_device_id", source)
        self.assertIn("status_code=400", source)


class ResetTrustStateBehaviouralTests(unittest.IsolatedAsyncioTestCase):


    def _make_fake_db(self, *, prior_rows: list[dict]):


        from unittest.mock import patch, MagicMock

                               
        prior_counts_rows: list[dict] = []
        by_status: dict[str, int] = {}
        for r in prior_rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        for s, n in by_status.items():
            prior_counts_rows.append({"status": s, "n": n})

                                                                      
        kept = self._kept_device_id
        deleted_returning = [
            {"device_id": r["device_id"], "status": r["status"]}
            for r in prior_rows
            if r["device_id"] != kept
        ]

        fetch_queue = [prior_counts_rows, deleted_returning]
        store = {"commits": 0, "executed_sql": []}

        cursor = MagicMock()
        def _execute(sql, params=None):
            store["executed_sql"].append(sql)
        cursor.execute.side_effect = _execute
        cursor.fetchall.side_effect = lambda: fetch_queue.pop(0) if fetch_queue else []

        conn = MagicMock()
        conn.cursor.return_value = cursor
        def _commit():
            store["commits"] += 1
        conn.commit.side_effect = _commit

        return patch("routes.device_routes.get_db", return_value=conn), store

    async def test_wipes_stale_trusted_and_upserts_current(self):
        from fastapi import Request
        from routes import device_routes

        self._kept_device_id = "currentcurrentcurrent_aBcDeFgH"                      
        prior = [
            {"device_id": "stale_trusted_one_aaaaaaaaaaaaaa",  "status": "trusted"},
            {"device_id": "stale_trusted_two_bbbbbbbbbbbbbb",  "status": "trusted"},
            {"device_id": "stale_pending_cccccccccccccccc",     "status": "pending"},
            {"device_id": "stale_revoked_dddddddddddddddd",     "status": "revoked"},
            {"device_id": self._kept_device_id,                  "status": "pending"},
        ]
        patcher, store = self._make_fake_db(prior_rows=prior)

                                                                      
        scope = {
            "type": "http",
            "headers": [(b"x-device-id", self._kept_device_id.encode())],
            "method": "POST",
            "path": "/devices/dev/reset-trust-state",
        }
        request = Request(scope)

                                                                    
        with patcher, env_vars(
            VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST="true",
            VAULTAI_ENV="local",
        ):
            result = await device_routes.dev_reset_trust_state(
                request,
                principal={
                    "vault_id":   "00000000-0000-4000-8000-000000000001",
                    "vault_name": "test-vault",
                    "token_id":   "00000000-0000-4000-8000-00000000aaaa",
                    "device_id":  None,
                },
            )

                                                                   
        self.assertEqual(result["deleted_count"], 4)
                                                                           
                                                                   
        self.assertEqual(result["deleted_by_status"], {
            "trusted": 2, "pending": 1, "revoked": 1,
        })
                                                  
        self.assertEqual(result["prior_counts_by_status"], {
            "trusted": 2, "pending": 2, "revoked": 1,
        })
                                                                      
                                                                     
        self.assertEqual(result["kept_device_id_prefix"],
                         self._kept_device_id[:8])
                                                               
                                                                     
        self.assertEqual(store["commits"], 1)

    async def test_refuses_when_flags_off(self):
        from fastapi import HTTPException, Request
        from routes import device_routes
        self._kept_device_id = "currentcurrentcurrent_aBcDeFgH"

        scope = {
            "type": "http",
            "headers": [(b"x-device-id", self._kept_device_id.encode())],
            "method": "POST",
            "path": "/devices/dev/reset-trust-state",
        }
        request = Request(scope)

        with _clear_all_dev_env():
            with self.assertRaises(HTTPException) as ctx:
                await device_routes.dev_reset_trust_state(
                    request,
                    principal={
                        "vault_id":   "00000000-0000-4000-8000-000000000002",
                        "vault_name": "test-vault",
                        "token_id":   "00000000-0000-4000-8000-00000000bbbb",
                        "device_id":  None,
                    },
                )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(
            ctx.exception.detail["code"], "dev_reset_disabled",
        )

    async def test_refuses_when_no_device_id_header(self):
                                                                   
                                                              
        from fastapi import HTTPException, Request
        from routes import device_routes
        self._kept_device_id = "n/a"

        scope = {
            "type": "http",
            "headers": [],
            "method": "POST",
            "path": "/devices/dev/reset-trust-state",
        }
        request = Request(scope)

        with env_vars(
            VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST="true",
            VAULTAI_ENV="local",
        ):
            with self.assertRaises(HTTPException) as ctx:
                await device_routes.dev_reset_trust_state(
                    request,
                    principal={
                        "vault_id":   "00000000-0000-4000-8000-000000000003",
                        "vault_name": "test-vault",
                        "token_id":   "00000000-0000-4000-8000-00000000cccc",
                        "device_id":  None,
                    },
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail["code"], "missing_device_id",
        )


if __name__ == "__main__":
    unittest.main()
