# Single-active-device idempotency contract (2026-07-20).
#
# The pre-2026-07-20 behavior of ``register_or_refresh`` — refresh
# leaves an existing 'pending' row 'pending', refresh never touches
# the ``status`` column — is retired. Under the new model any call
# to /devices/register (or to the underlying primitive) trusts the
# current device and revokes every other device on that vault, in
# one transaction. The tests below lock in the new contract at the
# unit level; the DB-shape end-to-end assertions live in
# ``test_single_active_device_2026_07_20.py``.

from __future__ import annotations

import re
import unittest

import device_monitor


class _FakeCursor:
    # Minimal DB replay of the new two-statement primitive:
    #   1. INSERT ... ON CONFLICT DO UPDATE  (upsert to 'trusted')
    #   2. UPDATE ... SET status='revoked' WHERE device_id <> current
    # The cursor doesn't need to model row storage; it only needs to
    # record the SQL for assertions and return sensible fetchall/one
    # values.

    def __init__(self, sql_log, revoked_ids, prior_row):
        self.sql_log = sql_log
        self._revoked_ids = revoked_ids
        self._prior_row = prior_row
        self._pending: list = []

    def execute(self, sql, _params=None):
        self.sql_log.append(sql)
        stripped = sql.strip().upper()
        if "RETURNING DEVICE_ID" in stripped and stripped.startswith("UPDATE"):
            self._pending = [{"device_id": d} for d in self._revoked_ids]
        elif "SELECT STATUS FROM TRUSTED_DEVICES" in stripped:
            # The peek query inside register_or_refresh checks whether
            # a prior row exists for the given (vault_id, device_id).
            self._pending = [self._prior_row] if self._prior_row else []
        else:
            self._pending = []

    def fetchall(self):
        rows = list(self._pending)
        self._pending.clear()
        return rows

    def fetchone(self):
        return self._pending.pop(0) if self._pending else None


class FakeConnection:
    def __init__(self, revoked_ids=None, prior_row=None):
        self._revoked_ids = revoked_ids or []
        self._prior_row = prior_row
        self.sql_log: list[str] = []
        self.committed = False
        self.rolled_back = False
        self._cursor = _FakeCursor(
            self.sql_log, self._revoked_ids, self._prior_row,
        )

    def cursor(self, *_args, **_kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _swap_get_db(conn):
    original = device_monitor.get_db
    device_monitor.get_db = lambda: conn
    return original


class TrustCurrentAndRevokeOthersTests(unittest.TestCase):
    # trust_current_and_revoke_others is the primitive; the flow tests
    # against a live DB live in test_single_active_device_2026_07_20.

    def test_upsert_uses_on_conflict_do_update(self):
        conn = FakeConnection(revoked_ids=[])
        original = _swap_get_db(conn)
        try:
            device_monitor.trust_current_and_revoke_others(
                vault_id="00000000-0000-4000-8000-0000000000a1",
                device_id="dev-current",
                label=None,
                user_agent_brand=None,
                ip_prefix=None,
            )
        finally:
            device_monitor.get_db = original

        insert_stmts = [
            s for s in conn.sql_log if s.strip().upper().startswith("INSERT")
        ]
        self.assertTrue(
            insert_stmts, msg="expected the trust UPSERT INSERT statement",
        )
        for sql in insert_stmts:
            up = sql.upper()
            self.assertIn(
                "ON CONFLICT", up,
                msg="trust primitive must use UPSERT (ON CONFLICT DO UPDATE)",
            )
            self.assertIn(
                "DO UPDATE", up,
                msg="trust primitive must UPDATE the row on conflict",
            )
            # And the target status must be literal 'trusted' — a
            # pending default would let a stale check-constraint hide
            # a regression.
            self.assertIn(
                "'TRUSTED'", up,
                msg="upsert must set status='trusted' explicitly",
            )

    def test_revoke_others_matches_all_other_devices(self):
        conn = FakeConnection(revoked_ids=["dev-old-1", "dev-old-2"])
        original = _swap_get_db(conn)
        try:
            outcome = device_monitor.trust_current_and_revoke_others(
                vault_id="00000000-0000-4000-8000-0000000000a2",
                device_id="dev-current",
                label=None,
                user_agent_brand=None,
                ip_prefix=None,
            )
        finally:
            device_monitor.get_db = original

        self.assertEqual(outcome["status"], "trusted")
        self.assertEqual(outcome["revoked_other_count"], 2)
        self.assertEqual(
            set(outcome["revoked_other_device_ids"]),
            {"dev-old-1", "dev-old-2"},
        )

        update_stmts = [
            s for s in conn.sql_log
            if s.strip().upper().startswith("UPDATE")
               and "SET STATUS" in s.upper()
        ]
        self.assertTrue(
            update_stmts,
            msg="expected the revoke-others UPDATE statement",
        )
        for sql in update_stmts:
            normalized = re.sub(r"\s+", " ", sql).lower()
            self.assertIn(
                "device_id <> %s", normalized,
                msg="revoke UPDATE must exclude the current device_id",
            )
            self.assertIn(
                "set status = 'revoked'", normalized,
                msg="revoke UPDATE must set status to 'revoked'",
            )

    def test_commit_is_called_after_both_statements(self):
        conn = FakeConnection(revoked_ids=["dev-old"])
        original = _swap_get_db(conn)
        try:
            device_monitor.trust_current_and_revoke_others(
                vault_id="00000000-0000-4000-8000-0000000000a3",
                device_id="dev-current",
                label=None,
                user_agent_brand=None,
                ip_prefix=None,
            )
        finally:
            device_monitor.get_db = original

        self.assertTrue(
            conn.committed,
            msg="single commit must fire after INSERT + UPDATE (atomic op)",
        )
        self.assertFalse(conn.rolled_back)


class RegisterOrRefreshDelegatesToPrimitiveTests(unittest.TestCase):
    # The public /devices/register path now flows through the atomic
    # primitive. Its legacy return shape stays compatible so existing
    # front-end code that reads ``result['status']`` keeps working.

    def test_new_device_returns_trusted(self):
        conn = FakeConnection(revoked_ids=[], prior_row=None)
        original = _swap_get_db(conn)
        try:
            result = device_monitor.register_or_refresh(
                vault_id="00000000-0000-4000-8000-0000000000b1",
                device_id="dev-new",
                label="fresh",
                user_agent_brand="Chrome",
                ip_prefix="203.0.113",
            )
        finally:
            device_monitor.get_db = original

        # New model: register_or_refresh always ends with the caller
        # holding trusted status — 'pending' is retired for this
        # code path.
        self.assertEqual(result["status"], "trusted")
        self.assertTrue(result["created"])
        self.assertTrue(result["is_first_device"])

    def test_existing_device_still_returns_trusted(self):
        conn = FakeConnection(revoked_ids=[], prior_row={"status": "trusted"})
        original = _swap_get_db(conn)
        try:
            result = device_monitor.register_or_refresh(
                vault_id="00000000-0000-4000-8000-0000000000b2",
                device_id="dev-existing",
                label="refreshed-label",
                user_agent_brand="Chrome",
                ip_prefix="203.0.113",
            )
        finally:
            device_monitor.get_db = original

        self.assertEqual(result["status"], "trusted")
        self.assertFalse(result["created"])

    def test_no_row_ever_returned_as_pending(self):
        # Regression guard: under any input shape, the public
        # register_or_refresh path must NEVER return 'pending'.
        # That eliminates the ed825aa-and-earlier signup dead end
        # where the client held a session but got 403'd on every
        # protected endpoint pending an approval from another device.
        for prior in (None, {"status": "pending"}, {"status": "trusted"}):
            with self.subTest(prior=prior):
                conn = FakeConnection(revoked_ids=[], prior_row=prior)
                original = _swap_get_db(conn)
                try:
                    result = device_monitor.register_or_refresh(
                        vault_id="00000000-0000-4000-8000-0000000000b3",
                        device_id="dev-any",
                        label=None,
                        user_agent_brand=None,
                        ip_prefix=None,
                    )
                finally:
                    device_monitor.get_db = original
                self.assertNotEqual(result["status"], "pending")
                self.assertEqual(result["status"], "trusted")


if __name__ == "__main__":
    unittest.main()
