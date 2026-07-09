

from __future__ import annotations

import inspect
import os
import unittest
from unittest import mock


def _set_prod_env(monkey: dict[str, str | None]) -> dict[str, str | None]:


    snapshot: dict[str, str | None] = {}
    for var in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
        snapshot[var] = os.environ.get(var)
        os.environ[var] = "production"
    return snapshot


def _restore_env(snapshot: dict[str, str | None]) -> None:
    for k, v in snapshot.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _set_dev_env() -> dict[str, str | None]:
    snapshot: dict[str, str | None] = {}
    for var in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
        snapshot[var] = os.environ.get(var)
    os.environ["VAULTAI_ENV"] = "dev"
    return snapshot


class DebugEndpointsProdGateTests(unittest.TestCase):
    def setUp(self) -> None:
                                                               
                                                                 
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_debug_routes_404_in_production(self) -> None:
        snap = _set_prod_env({})
        try:
            r = self.client.get("/debug/routes")
        finally:
            _restore_env(snap)
        self.assertEqual(r.status_code, 404)

    def test_debug_ping_404_in_production(self) -> None:
        snap = _set_prod_env({})
        try:
            r = self.client.get("/debug/ping")
        finally:
            _restore_env(snap)
        self.assertEqual(r.status_code, 404)

    def test_debug_routes_200_in_dev(self) -> None:
        snap = _set_dev_env()
        try:
            r = self.client.get("/debug/routes")
        finally:
            _restore_env(snap)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("count", body)
        self.assertIn("routes", body)

    def test_debug_ping_200_in_dev(self) -> None:
        snap = _set_dev_env()
        try:
            r = self.client.get("/debug/ping")
        finally:
            _restore_env(snap)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("ok"))
        self.assertIn("pid", body)
        self.assertIn("cwd", body)
        self.assertIn("file", body)

    def test_debug_ping_does_not_use_raw_print(self) -> None:
                                                                      
                                                                   
        import main
        src = inspect.getsource(main.debug_ping_endpoint)
        self.assertNotIn("print(", src)
        self.assertIn("logger", src)


class HealthEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_health_returns_ok_when_select_1_succeeds(self) -> None:
                                                                        
        cursor_mock = mock.MagicMock()
        cursor_mock.fetchone.return_value = (1,)
        conn_mock = mock.MagicMock()
        conn_mock.cursor.return_value = cursor_mock
        with mock.patch("main.get_db", return_value=conn_mock):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json(),
            {"status": "ok", "db": "connected"},
        )
                                     
        cursor_mock.execute.assert_called_once()
        args, _ = cursor_mock.execute.call_args
        self.assertEqual(args[0].strip(), "SELECT 1")

    def test_health_returns_503_when_get_db_raises(self) -> None:
                                                  
        class _FakeOpErr(Exception):
            pass
        _FakeOpErr.__name__ = "OperationalError"
        with mock.patch(
            "main.get_db",
            side_effect=_FakeOpErr(
                "could not translate host name "
                "\"super-secret-db.example.internal\" to address"
            ),
        ):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 503)
        body = r.json()
        self.assertEqual(body.get("status"), "unhealthy")
        self.assertEqual(body.get("db"), "unavailable")
                                                            
        self.assertEqual(body.get("error"), "OperationalError")
        flat = repr(body)
        self.assertNotIn("super-secret-db", flat,
            "health response must NEVER echo the DB host / DSN / URL")

    def test_health_returns_503_when_cursor_execute_raises(self) -> None:
                                                                 
        cursor_mock = mock.MagicMock()
        cursor_mock.execute.side_effect = RuntimeError(
            "password=hunter2 invalid"
        )
        conn_mock = mock.MagicMock()
        conn_mock.cursor.return_value = cursor_mock
        with mock.patch("main.get_db", return_value=conn_mock):
            r = self.client.get("/health")
        self.assertEqual(r.status_code, 503)
        body = r.json()
        self.assertEqual(body.get("status"), "unhealthy")
        self.assertEqual(body.get("error"), "RuntimeError")
                                                               
                                      
        flat = repr(body)
        self.assertNotIn("hunter2", flat)
        self.assertNotIn("password", flat)

    def test_health_handler_source_does_not_format_exception_message(self) -> None:
                                                                    
                                                                  
        import ast, inspect, main
        src = inspect.getsource(main.health)
        self.assertIn("type(exc).__name__", src)
        tree = ast.parse(src)
        offenders: list[str] = []
        for node in ast.walk(tree):
                                          
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("str", "repr"):
                    for arg in node.args:
                        if isinstance(arg, ast.Name) and arg.id == "exc":
                            offenders.append(ast.unparse(node))
                                                      
            if isinstance(node, ast.JoinedStr):
                for v in node.values:
                    if isinstance(v, ast.FormattedValue):
                        if (isinstance(v.value, ast.Name)
                                and v.value.id == "exc"):
                            offenders.append(ast.unparse(node))
        self.assertEqual(
            offenders, [],
            f"health handler may leak exception message: {offenders!r}",
        )


if __name__ == "__main__":
    unittest.main()
