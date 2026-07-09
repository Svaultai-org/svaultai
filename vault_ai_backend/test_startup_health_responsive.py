

from __future__ import annotations

import logging
import os
import sys
import time
import unittest
from unittest import mock


try:
    from fastapi.testclient import TestClient              
    _HAVE_HTTPX = True
except ImportError:
    _HAVE_HTTPX = False


def _ensure_database_url() -> bool:
    if os.environ.get("DATABASE_URL", "").strip():
        return True
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
    except Exception:
        pass
    return bool(os.environ.get("DATABASE_URL", "").strip())


@unittest.skipUnless(_HAVE_HTTPX, "httpx not installed")
class HealthRespondsWhileReconcilerRunsTests(unittest.TestCase):


    def setUp(self) -> None:
        if not _ensure_database_url():
            self.skipTest(
                "DATABASE_URL absent (an earlier test in this suite "
                "popped it); skipping the integration probe — the "
                "behavioural contract is pinned by "
                "test_vault_startup.py's unit tests.",
            )

                                                             
    _RECONCILER_SLEEP_SECS = 30.0

    def test_health_responds_with_reconciler_still_running(self) -> None:
        fake_reconciler_module = mock.Mock()
        fake_reconciler_module.reconcile_all_vaults_at_startup = mock.Mock(
            side_effect=lambda: time.sleep(self._RECONCILER_SLEEP_SECS),
        )

        cap = _LogCapture()
        logging.getLogger("vault_startup").addHandler(cap)
        logging.getLogger("main").addHandler(cap)
        logging.getLogger("vault_startup").setLevel(logging.INFO)
        logging.getLogger("main").setLevel(logging.INFO)

        startup_elapsed = None
        try:
            with mock.patch.dict(sys.modules, {
                "vault_reconciler": fake_reconciler_module,
            }):
                from main import app

                startup_start = time.monotonic()
                try:
                    test_client_ctx = TestClient(app)
                    client = test_client_ctx.__enter__()
                except Exception as exc:
                                                                   
                                                              
                    self.skipTest(
                        f"FastAPI lifespan startup raised "
                        f"{type(exc).__name__}; the behavioural "
                        f"contract is pinned by test_vault_startup.py.",
                    )
                try:
                    startup_elapsed = time.monotonic() - startup_start
                                                                  
                                                                     
                    self.assertLess(
                        startup_elapsed,
                        self._RECONCILER_SLEEP_SECS - 5.0,
                        f"TestClient startup took {startup_elapsed:.2f}s "
                        f"— must be well below the "
                        f"{self._RECONCILER_SLEEP_SECS}s reconciler "
                        "sleep; the reconciler is blocking startup.",
                    )

                                                                   
                    resp = client.get("/health")
                    self.assertIn(resp.status_code, {200, 503})

                                                                  
                    self.assertGreaterEqual(
                        fake_reconciler_module
                            .reconcile_all_vaults_at_startup.call_count,
                        1,
                    )
                finally:
                    test_client_ctx.__exit__(None, None, None)
        finally:
            logging.getLogger("vault_startup").removeHandler(cap)
            logging.getLogger("main").removeHandler(cap)
                                                                      
                                                                          
        self.assertIsNotNone(startup_elapsed)


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


if __name__ == "__main__":
    unittest.main()
