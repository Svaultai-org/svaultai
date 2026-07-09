

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path


_BACKEND_DIR = Path(__file__).parent
_TEST_DB_VAR = "VAULTAI_TEST_DATABASE_URL"


def _e2e_test_files() -> list[Path]:
    return [
        p for p in _BACKEND_DIR.glob("test_*_e2e.py")
        if p.is_file()
    ]


class E2EDoesNotUseDatabaseUrlTests(unittest.TestCase):
    def test_at_least_one_e2e_file_exists(self):
        files = _e2e_test_files()
        self.assertGreater(
            len(files), 0,
            "no test_*_e2e.py files found — the guard has no work to do",
        )

    def test_no_e2e_file_references_database_url_in_executable_code(self):
        offenders: list[str] = []
        for path in _e2e_test_files():
            src = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(src)
            except SyntaxError as exc:
                self.fail(f"could not parse {path.name}: {exc}")

                                                               
            docstring_node_ids: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.FunctionDef,
                                     ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.body and isinstance(node.body[0], ast.Expr):
                        expr = node.body[0]
                        if isinstance(expr.value, ast.Constant):
                            docstring_node_ids.add(id(expr.value))

            for node in ast.walk(tree):
                                                                      
                                                        
                if isinstance(node, ast.Constant) \
                        and isinstance(node.value, str):
                    if id(node) in docstring_node_ids:
                        continue
                    val = node.value
                    if val == "DATABASE_URL":
                        offenders.append(
                            f"{path.name}:{node.lineno} "
                            f"literal \"DATABASE_URL\""
                        )
                                                                
                if isinstance(node, ast.Subscript):
                    snippet = ast.unparse(node)
                    if (
                        "os.environ" in snippet
                        and "DATABASE_URL" in snippet
                        and _TEST_DB_VAR not in snippet
                    ):
                        offenders.append(
                            f"{path.name}:{node.lineno} {snippet}"
                        )
                                                               
                if isinstance(node, ast.Call):
                    snippet = ast.unparse(node)
                    if (
                        "os.environ.get" in snippet
                        and "DATABASE_URL" in snippet
                        and _TEST_DB_VAR not in snippet
                    ):
                        offenders.append(
                            f"{path.name}:{node.lineno} {snippet}"
                        )

        self.assertEqual(
            offenders, [],
            "E2E test files must use VAULTAI_TEST_DATABASE_URL, "
            "NEVER DATABASE_URL. Offenders:\n"
            + "\n".join(offenders),
        )

    def test_every_e2e_file_uses_vaultai_test_database_url(self):
                                                                   
                                                                   
        misses: list[str] = []
        for path in _e2e_test_files():
            src = path.read_text(encoding="utf-8")
            if "psycopg2" not in src:
                continue
            if _TEST_DB_VAR not in src:
                misses.append(path.name)
        self.assertEqual(
            misses, [],
            "DB-bound E2E test files must reference "
            f"{_TEST_DB_VAR}: {misses!r}",
        )


if __name__ == "__main__":
    unittest.main()
