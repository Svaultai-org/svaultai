

from __future__ import annotations

import ast
import importlib.util
import os
import pathlib
import py_compile
import re
import sys
import tempfile
import unittest


BACKEND_DIR = pathlib.Path(__file__).resolve().parent
MIGRATIONS_DIR = BACKEND_DIR / "migrations" / "versions"
MAIN_PY = BACKEND_DIR / "main.py"


def _migration_files() -> list[pathlib.Path]:
    return sorted(MIGRATIONS_DIR.glob("*.py"))


class MigrationCompileTests(unittest.TestCase):


    def test_migrations_directory_is_non_empty(self) -> None:
        files = _migration_files()
        self.assertGreater(
            len(files),
            0,
            "No migration files found — this test should never run "
            "against an empty migrations dir.",
        )

    def test_every_migration_compiles_cleanly(self) -> None:
        for path in _migration_files():
            with self.subTest(migration=path.name):
                try:
                    py_compile.compile(str(path), doraise=True)
                except py_compile.PyCompileError as exc:
                    self.fail(
                        f"{path.name} failed to compile — most likely a "
                        f"broken f-string brace pattern (e.g. ``f\"'{{}}'"
                        f"::jsonb\"`` — empty f-string slot is a SyntaxError). "
                        f"Original error: {exc.msg}"
                    )


class AlembicRevisionGraphTests(unittest.TestCase):


    def test_revision_directory_loads_end_to_end(self) -> None:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option(
            "script_location", str(BACKEND_DIR / "migrations"),
        )
        script_dir = ScriptDirectory.from_config(cfg)

                                                                  
        revisions = list(script_dir.walk_revisions())
        self.assertGreater(len(revisions), 0)

    def test_revision_chain_reaches_head_from_base(self) -> None:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option(
            "script_location", str(BACKEND_DIR / "migrations"),
        )
        script_dir = ScriptDirectory.from_config(cfg)

        heads = script_dir.get_heads()
        self.assertEqual(
            len(heads),
            1,
            "Expected exactly one head — Alembic branching is not "
            f"supported here. Got: {heads}",
        )
        bases = script_dir.get_bases()
        self.assertEqual(
            len(bases),
            1,
            "Expected exactly one base — multiple-base trees would "
            f"break ``alembic upgrade head``. Got: {bases}",
        )

    def test_every_migration_imports_without_raising(self) -> None:
                                                                       
                                                                    
        for path in _migration_files():
            with self.subTest(migration=path.name):
                mod_name = f"_migration_safety_test_{path.stem}"
                spec = importlib.util.spec_from_file_location(mod_name, path)
                self.assertIsNotNone(spec)
                module = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(module)                            
                except Exception as exc:
                    self.fail(
                        f"{path.name} raised at module load time: "
                        f"{type(exc).__name__}: {exc}. This will brick "
                        f"backend startup the moment Alembic tries to "
                        f"import it."
                    )
                finally:
                    sys.modules.pop(mod_name, None)


_BAD_INSIDE_FSTRING = re.compile(r"'\{\}'::jsonb", re.IGNORECASE)

                                                                        
_BAD_OUTSIDE_FSTRING = re.compile(r"'\{\{\}\}'::jsonb", re.IGNORECASE)


def _is_format_call(node: ast.AST) -> bool:

    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    )


def _collect_docstring_ids(tree: ast.AST) -> set[int]:


    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            out.add(id(first.value))
    return out


def _collect_fstring_part_ids(tree: ast.AST) -> set[int]:


    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                out.add(id(value))
    return out


def _collect_format_target_ids(tree: ast.AST) -> dict[int, int]:

    out: dict[int, int] = {}
    for node in ast.walk(tree):
        if not _is_format_call(node):
            continue
        target = node.func.value                            
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            out[id(target)] = node.lineno
    return out


def _collect_string_contexts(
    path: pathlib.Path,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:


    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    docstring_ids = _collect_docstring_ids(tree)
    fstring_part_ids = _collect_fstring_part_ids(tree)
    format_targets = _collect_format_target_ids(tree)

    formatted_blocks: list[tuple[int, str]] = []
    plain_blocks: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        nid = id(node)
        if nid in format_targets:
            formatted_blocks.append((format_targets[nid], node.value))
            continue
        if nid in fstring_part_ids:
            continue
        if nid in docstring_ids:
            continue
        plain_blocks.append((node.lineno, node.value))

    return formatted_blocks, plain_blocks


class JsonbDefaultsAuthoringRuleTests(unittest.TestCase):


    def test_no_bare_jsonb_braces_inside_fstring_or_format_block(self) -> None:
        violations: list[str] = []
        for path in _migration_files():
            formatted, _ = _collect_string_contexts(path)
            for lineno, template in formatted:
                if _BAD_INSIDE_FSTRING.search(template):
                    violations.append(
                        f"{path.name}:{lineno} contains bare ``'{{}}'"
                        f"::jsonb`` inside an f-string or .format() "
                        f"block. Replace with ``'{{{{}}}}'::jsonb`` "
                        f"so the post-format SQL is ``'{{}}'::jsonb``."
                    )
        self.assertFalse(
            violations,
            "Bare JSONB brace defaults inside format blocks "
            "(would silently consume the next .format() positional):\n  "
            + "\n  ".join(violations),
        )

    def test_no_escaped_jsonb_braces_in_plain_string(self) -> None:
        violations: list[str] = []
        for path in _migration_files():
            _, plain = _collect_string_contexts(path)
            for lineno, template in plain:
                if _BAD_OUTSIDE_FSTRING.search(template):
                    violations.append(
                        f"{path.name}:{lineno} contains escaped "
                        f"``'{{{{}}}}'::jsonb`` in a plain (non-formatted) "
                        f"string. PostgreSQL will see the literal "
                        f"``{{{{}}}}`` and reject it at "
                        f"``alembic upgrade``. Replace with "
                        f"``'{{}}'::jsonb``."
                    )
        self.assertFalse(
            violations,
            "Escaped JSONB defaults outside an f-string / format "
            "block (PostgreSQL receives literal ``{{}}`` and fails):\n  "
            + "\n  ".join(violations),
        )

    def test_jsonb_default_pattern_set_is_non_empty(self) -> None:
                                                                     
                                                                    
        found = False
        for path in _migration_files():
            text = path.read_text(encoding="utf-8")
            if "::jsonb" in text.lower() or "::JSONB" in text:
                found = True
                break
        self.assertTrue(
            found,
            "No JSONB defaults found across all migration files — "
            "either every migration dropped them, or the discovery "
            "regex broke. Investigate before relying on this guard.",
        )


class StartupMigrationErrorVisibilityTests(unittest.TestCase):
    def test_init_db_logs_full_traceback_on_failure(self) -> None:
                                                                 
                                                                 
        source = MAIN_PY.read_text(encoding="utf-8")
        idx = source.find("def init_db")
        self.assertGreater(idx, -1)
        end = source.find("\ndef ", idx + 1)
        body = source[idx:end if end > 0 else len(source)]

        self.assertIn(
            "command.upgrade(",
            body,
            "init_db() must call command.upgrade(...) — the only "
            "supported way to apply migrations.",
        )
        self.assertIn(
            "logger.exception",
            body,
            "init_db() must use logger.exception(...) so the FULL "
            "traceback hits the console when a migration fails. "
            "logger.error(...) is not enough — it drops the cause.",
        )
        self.assertIn(
            "raise",
            body,
            "init_db() must re-raise after logging — silently "
            "continuing leaves the app running against a half-"
            "migrated schema, which is exactly the failure mode "
            "this hardening pass exists to prevent.",
        )

    def test_init_db_prints_loud_banner_on_failure(self) -> None:
                                                                
                                                                   
        source = MAIN_PY.read_text(encoding="utf-8")
        idx = source.find("def init_db")
        end = source.find("\ndef ", idx + 1)
        body = source[idx:end if end > 0 else len(source)]
        self.assertIn(
            "MIGRATION FAILURE",
            body,
            "init_db() must print a 'MIGRATION FAILURE' banner so "
            "the error is impossible to miss in console output.",
        )


class JsonbGuardSelfTest(unittest.TestCase):
    def _run_guard_on_synthetic(
        self, source: str,
    ) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
                                                                   
                                                                     
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
        ) as tmp:
            tmp.write(source)
            tmp_path = pathlib.Path(tmp.name)
        try:
            return _collect_string_contexts(tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_guard_fires_on_bare_braces_in_format_call(self) -> None:
                                                                     
                                                                  
        src = 'X = "DEFAULT \'{}\'::jsonb".format(123)\n'
        formatted, _ = self._run_guard_on_synthetic(src)
        self.assertTrue(any(_BAD_INSIDE_FSTRING.search(t) for _, t in formatted))

    def test_guard_does_not_fire_on_correctly_escaped_format_call(self) -> None:
                                                                  
        src = 'X = "DEFAULT \'{{}}\'::jsonb".format(123)\n'
        formatted, _ = self._run_guard_on_synthetic(src)
        self.assertFalse(any(_BAD_INSIDE_FSTRING.search(t) for _, t in formatted))

    def test_guard_fires_on_escaped_braces_in_plain_string(self) -> None:
                                                                    
                                                                
        src = 'X = "DEFAULT \'{{}}\'::jsonb"\n'
        _, plain = self._run_guard_on_synthetic(src)
        self.assertTrue(any(_BAD_OUTSIDE_FSTRING.search(t) for _, t in plain))

    def test_guard_does_not_fire_on_canonical_plain_string(self) -> None:
                                                                     
        src = 'X = "DEFAULT \'{}\'::jsonb"\n'
        _, plain = self._run_guard_on_synthetic(src)
        self.assertFalse(any(_BAD_OUTSIDE_FSTRING.search(t) for _, t in plain))

    def test_guard_does_not_inspect_fstring_constants(self) -> None:
                                                                        
                                                                   
        src = (
            'VAR = "abc"\n'
            'X = f"DEFAULT \'{{}}\'::jsonb USING {VAR}"\n'
        )
        formatted, plain = self._run_guard_on_synthetic(src)
                                                                       
                                                                              
        for lineno, template in formatted + plain:
            self.assertNotIn(
                "::jsonb",
                template,
                f"f-string interior leaked into the brace sweep at "
                f"line {lineno}: {template!r}",
            )

    def test_guard_ignores_docstrings(self) -> None:
                                                                      
                                                                      
        src = (
            '"""Doc: avoid \'{{}}\'::jsonb in plain SQL strings."""\n'
            'X = 1\n'
        )
        _, plain = self._run_guard_on_synthetic(src)
                                                             
        for _, template in plain:
            self.assertNotIn(
                "::jsonb",
                template,
                "docstring leaked into the plain-string guard sweep",
            )


CHECK_MIGRATIONS_SCRIPT = BACKEND_DIR / "scripts" / "check-migrations.ps1"
AUTHORING_RULES_DOC = BACKEND_DIR / "migrations" / "AUTHORING_RULES.md"


class DeveloperReferenceTests(unittest.TestCase):
    def test_check_migrations_script_exists(self) -> None:
        self.assertTrue(
            CHECK_MIGRATIONS_SCRIPT.exists(),
            "scripts/check-migrations.ps1 must exist — referenced from "
            "main.py's migration-failure banner and AUTHORING_RULES.md.",
        )

    def test_check_migrations_script_runs_all_four_commands(self) -> None:
        body = CHECK_MIGRATIONS_SCRIPT.read_text(encoding="utf-8")
                                                                        
                                                                      
        self.assertIn("python -m compileall migrations/versions", body)
        self.assertIn("python -m alembic history", body)
        self.assertIn("python -m alembic current", body)
        self.assertIn("python -m alembic upgrade head", body)

    def test_authoring_rules_doc_exists(self) -> None:
        self.assertTrue(
            AUTHORING_RULES_DOC.exists(),
            "migrations/AUTHORING_RULES.md must exist — it's the human-"
            "readable reference for the JSONB brace rule.",
        )

    def test_authoring_rules_doc_pins_jsonb_examples(self) -> None:
        body = AUTHORING_RULES_DOC.read_text(encoding="utf-8")
                                                                    
                                                                  
        self.assertIn("'{}'::jsonb", body)
        self.assertIn("'{{}}'::jsonb", body)
        self.assertIn("Anti-patterns", body)


if __name__ == "__main__":
    unittest.main()
