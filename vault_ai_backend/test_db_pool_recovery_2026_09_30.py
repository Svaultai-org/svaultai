"""Regression coverage for stale managed-Postgres pool connections.

The production incident on 2026-09-30 left a timed-out psycopg2 connection
inside ``ThreadedConnectionPool``.  Every auth request borrowed and returned
that same unusable socket until the API container was restarted.
"""

from __future__ import annotations

import importlib
import os
import sys
import unittest
from unittest import mock


os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://fixture:fixture@127.0.0.1:1/fixture",
)


class _Cursor:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql: str) -> None:
        if self.fail:
            raise RuntimeError("stale socket")

    def fetchone(self):
        return (1,)


class _Connection:
    def __init__(self, *, fail_probe: bool = False, fail_rollback: bool = False):
        self.closed = 0
        self.fail_probe = fail_probe
        self.fail_rollback = fail_rollback

    def cursor(self):
        return _Cursor(fail=self.fail_probe)

    def rollback(self):
        if self.fail_rollback:
            raise RuntimeError("connection lost")

    def close(self):
        self.closed = 1


class _Pool:
    def __init__(self, *connections):
        self.connections = list(connections)
        self.returned = []

    def getconn(self):
        return self.connections.pop(0)

    def putconn(self, conn, close=False):
        self.returned.append((conn, close))


class DbPoolRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "vault_core" in sys.modules:
            cls.vault_core = importlib.reload(sys.modules["vault_core"])
        else:
            cls.vault_core = importlib.import_module("vault_core")

    def test_checkout_discards_stale_connection_and_retries(self):
        stale = _Connection(fail_probe=True)
        healthy = _Connection()
        pool = _Pool(stale, healthy)

        with mock.patch.object(self.vault_core, "_get_pool", return_value=pool), \
             mock.patch.object(self.vault_core, "DB_POOL_MAX", 2):
            wrapped = self.vault_core.get_db()

        self.assertIs(wrapped._conn, healthy)
        self.assertEqual(pool.returned, [(stale, True)])

    def test_close_discards_connection_when_rollback_fails(self):
        broken = _Connection(fail_rollback=True)
        pool = _Pool()
        wrapped = self.vault_core._PooledConnection(broken, pool)

        wrapped.close()

        self.assertEqual(pool.returned, [(broken, True)])

    def test_close_reuses_healthy_connection(self):
        healthy = _Connection()
        pool = _Pool()
        wrapped = self.vault_core._PooledConnection(healthy, pool)

        wrapped.close()

        self.assertEqual(pool.returned, [(healthy, False)])


if __name__ == "__main__":
    unittest.main()
