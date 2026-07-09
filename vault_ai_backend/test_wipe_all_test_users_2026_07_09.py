"""Acceptance tests for scripts/wipe_all_test_users.py.

Covers:
  * dry-run is default (no flags) and never touches DB
  * dry-run counts show only non-PII fields
  * dry-run under any env prints safe counts (no email, no filename,
    no wallet address, no PIN, no token)
  * development destructive run routes every vault through
    delete_vault_and_all_data(reason="development_full_user_wipe")
  * production refuses by default (no allow-env override)
  * production with allow-env override still requires both flags
  * missing --i-understand-this-deletes-all-users refuses
  * missing --confirm-wipe-all-test-users refuses
  * script uses the shared deletion service (not raw SQL vault delete)
  * ``alembic_version`` is NEVER truncated or added to any allowlist
  * config tables (storage_skus, storage_pricing, username_policies,
    vault_service_categories) are preserved
  * log output contains no email, filename, wallet address, PIN,
    session token, or Stripe customer id — only hashed prefixes and
    per-table counts
  * new deletion reason is registered in the shared service
"""

from __future__ import annotations

import importlib.util
import io
import os
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


_HERE = Path(__file__).resolve().parent
_SCRIPT_PATH = _HERE / "scripts" / "wipe_all_test_users.py"


def _load_wipe_module():
    """Load the wipe script as a private module for tests. The script
    is intentionally not a package member (no ``__init__.py``) so we
    import by explicit file path. The module is registered in
    ``sys.modules`` under a stable name before ``exec_module`` runs so
    ``@dataclass`` (which walks ``sys.modules[cls.__module__]``) sees
    the right namespace on Python 3.13+."""
    name = "wipe_all_test_users_module"
    spec = importlib.util.spec_from_file_location(name, str(_SCRIPT_PATH))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return mod


WIPE = _load_wipe_module()


PII_SUBSTRINGS = (

    "@example.com", "@gmail.com", "@yahoo.com", "@outlook.com", "@icloud.com",

    "cus_",

    "sess_", "vsess_", "session_token", "Authorization: Bearer ",

    "0x", "bc1", "tron:", "xpub", "xprv",

    "PIN=", "pin=1", "pin=0",

    ".pdf", ".png", ".jpg", ".jpeg", ".mp3", ".m4a", ".docx", ".xlsx",

    "sk_live_", "sk_test_", "whsec_",

    "seed=", "mnemonic",
)


def _run_main_capturing(argv, env):
    """Run wipe.main(argv) with a patched environment and captured
    stdout/stderr. Returns (exit_code, out, err)."""
    with mock.patch.dict(os.environ, env, clear=False):

        for k in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
                  "VAULTAI_ALLOW_TEST_USER_WIPE"):
            if k not in env:
                os.environ.pop(k, None)
        buf_out, buf_err = io.StringIO(), io.StringIO()
        exit_code = 0
        try:
            with redirect_stdout(buf_out), redirect_stderr(buf_err):
                try:
                    rc = WIPE.main(argv)
                    exit_code = int(rc or 0)
                except SystemExit as exc:
                    if isinstance(exc.code, int):
                        exit_code = exc.code
                    else:

                        exit_code = 1
                        if exc.code:
                            print(str(exc.code), file=sys.stderr)
        except SystemExit as exc:
            exit_code = (
                int(exc.code) if isinstance(exc.code, int) else 1
            )
        return exit_code, buf_out.getvalue(), buf_err.getvalue()


class TestNewDeletionReasonRegistered(unittest.TestCase):
    def test_new_reason_registered_in_shared_service(self):
        import vault_deletion_service as vds
        self.assertEqual(
            vds.REASON_DEVELOPMENT_FULL_USER_WIPE,
            "development_full_user_wipe",
        )
        self.assertIn(
            vds.REASON_DEVELOPMENT_FULL_USER_WIPE,
            vds._ALLOWED_REASONS,
        )
        for public in (
            "REASON_USER_REQUESTED",
            "REASON_UNPAID_INACTIVE_6_MONTHS",
            "REASON_DEVELOPMENT_FULL_USER_WIPE",
        ):
            self.assertIn(public, vds.__all__)


class TestArgparse(unittest.TestCase):
    def test_no_flags_is_dry_run_default(self):
        p = WIPE.build_parser()
        args = p.parse_args([])
        self.assertFalse(args.dry_run)
        self.assertFalse(args.confirm_wipe)
        self.assertFalse(args.understand_flag)

    def test_destructive_requires_both_flags(self):
        p = WIPE.build_parser()
        args = p.parse_args([
            "--confirm-wipe-all-test-users",
            "--i-understand-this-deletes-all-users",
        ])
        self.assertTrue(args.confirm_wipe)
        self.assertTrue(args.understand_flag)


class TestPermissionGate(unittest.TestCase):
    def test_dev_env_allows_run(self):
        WIPE._check_permission_or_refuse(
            is_prod=False, is_dev=True, env_token="development",
            confirm_wipe=False, understand_flag=False, allow_env=False,
        )

    def test_missing_env_and_no_override_refuses(self):
        with self.assertRaises(SystemExit):
            WIPE._check_permission_or_refuse(
                is_prod=False, is_dev=False, env_token="unset",
                confirm_wipe=False, understand_flag=False,
                allow_env=False,
            )

    def test_production_refuses_without_override(self):
        with self.assertRaises(SystemExit):
            WIPE._check_permission_or_refuse(
                is_prod=True, is_dev=False, env_token="production",
                confirm_wipe=False, understand_flag=False,
                allow_env=False,
            )

    def test_production_with_override_allowed(self):

        WIPE._check_permission_or_refuse(
            is_prod=True, is_dev=False, env_token="production",
            confirm_wipe=False, understand_flag=False, allow_env=True,
        )


class TestDestructiveGate(unittest.TestCase):
    def test_destructive_requires_confirm_flag(self):
        with self.assertRaises(SystemExit):
            WIPE._check_destructive_gates_or_refuse(
                is_prod=False, confirm_wipe=False,
                understand_flag=True, allow_env=False,
            )

    def test_destructive_requires_understand_flag(self):
        with self.assertRaises(SystemExit):
            WIPE._check_destructive_gates_or_refuse(
                is_prod=False, confirm_wipe=True,
                understand_flag=False, allow_env=False,
            )

    def test_production_destructive_requires_env_override(self):
        with self.assertRaises(SystemExit):
            WIPE._check_destructive_gates_or_refuse(
                is_prod=True, confirm_wipe=True,
                understand_flag=True, allow_env=False,
            )

    def test_production_destructive_with_all_gates_allowed(self):

        WIPE._check_destructive_gates_or_refuse(
            is_prod=True, confirm_wipe=True, understand_flag=True,
            allow_env=True,
        )


class TestTableAllowlistsAreSafe(unittest.TestCase):
    def test_alembic_version_never_in_any_allowlist(self):
        for table, _key in WIPE._COUNT_TABLES:
            self.assertNotEqual(table, "alembic_version")
        self.assertNotIn("alembic_version", WIPE._LEFTOVER_TABLES_ALLOWLIST)
        self.assertIn("alembic_version", WIPE._CONFIG_TABLES_PRESERVED)

    def test_config_tables_preserved(self):
        must_preserve = {
            "storage_skus", "storage_pricing",
            "username_policies", "vault_service_categories",
        }
        for t in must_preserve:
            self.assertIn(t, WIPE._CONFIG_TABLES_PRESERVED)
            self.assertNotIn(t, WIPE._LEFTOVER_TABLES_ALLOWLIST)

            leftover_set = set(WIPE._LEFTOVER_TABLES_ALLOWLIST)
            self.assertFalse(must_preserve & leftover_set)

    def test_count_tables_include_user_data_categories(self):

        keys = {k for _, k in WIPE._COUNT_TABLES}
        for expected in (
            "accounts", "vaults", "files", "sessions", "trusted_devices",
            "secure_items_all_kinds", "notifications",
            "subscriptions_local",
        ):
            self.assertIn(expected, keys,
                          msg=f"dry-run must expose {expected} count")


class TestDryRunDoesNothing(unittest.TestCase):
    def test_dry_run_does_not_invoke_deleter(self):
        plan = WIPE.WipePlan(
            counts={"accounts": 3, "vaults": 3},
            vault_ids=["v1", "v2", "v3"],
        )
        calls = []
        def _fake_deleter(vault_id):
            calls.append(vault_id)
            return True, "hpxxx"

        with mock.patch.object(WIPE, "_wipe_leftovers_after_vaults",
                               return_value={"contact_sales_requests": 0}), \
             mock.patch.object(WIPE, "_delete_orphaned_accounts",
                               return_value=3):
            stats = WIPE.run_destructive(
                plan, dry_run=True, deleter=_fake_deleter,
            )
        self.assertEqual(calls, [])
        self.assertEqual(stats["vaults_processed"], 3)
        self.assertEqual(stats["vaults_deleted"], 0)
        self.assertEqual(stats["vaults_failed"], 0)


class TestDestructiveWipeRoutesEachVault(unittest.TestCase):
    def test_every_vault_reaches_deletion_service_with_correct_reason(self):
        calls = []
        def _fake_deleter(vault_id):
            calls.append(vault_id)
            return True, "hpxxx"

        plan = WIPE.WipePlan(
            counts={"accounts": 2, "vaults": 2},
            vault_ids=["v-alpha", "v-beta"],
        )
        with mock.patch.object(WIPE, "_wipe_leftovers_after_vaults",
                               return_value={}), \
             mock.patch.object(WIPE, "_delete_orphaned_accounts",
                               return_value=2):
            stats = WIPE.run_destructive(
                plan, dry_run=False, deleter=_fake_deleter,
            )
        self.assertEqual(calls, ["v-alpha", "v-beta"])
        self.assertEqual(stats["vaults_processed"], 2)
        self.assertEqual(stats["vaults_deleted"], 2)
        self.assertEqual(stats["accounts_deleted"], 2)

    def test_deleter_uses_shared_service_with_correct_reason(self):

        captured_reasons = []
        captured_ids = []
        fake_vds = mock.MagicMock()
        fake_vds.REASON_DEVELOPMENT_FULL_USER_WIPE = \
            "development_full_user_wipe"
        fake_vds.hashed_vault_id.return_value = "0" * 64
        def _fake_delete(vid, *, reason):
            captured_ids.append(vid)
            captured_reasons.append(reason)
        fake_vds.delete_vault_and_all_data = _fake_delete

        with mock.patch.dict(sys.modules,
                             {"vault_deletion_service": fake_vds}):
            ok, hp = WIPE._delete_one_vault("v-alpha")
        self.assertTrue(ok)
        self.assertEqual(captured_ids, ["v-alpha"])
        self.assertEqual(captured_reasons, ["development_full_user_wipe"])
        self.assertEqual(hp, "0" * 12)


class TestFullMainDryRunSafeInDev(unittest.TestCase):
    def test_dry_run_in_dev_prints_counts_only_no_pii(self):
        fake_plan = WIPE.WipePlan(
            counts={key: 0 for _, key in WIPE._COUNT_TABLES},
            vault_ids=[],
        )
        with mock.patch.object(WIPE, "collect_plan", return_value=fake_plan), \
             mock.patch.object(WIPE, "_wipe_leftovers_after_vaults",
                               return_value={}), \
             mock.patch.object(WIPE, "_delete_orphaned_accounts",
                               return_value=0):
            code, out, err = _run_main_capturing(
                ["--dry-run"], {"VAULTAI_ENV": "development"},
            )
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", out)
        self.assertIn("dry-run complete", out)
        for needle in PII_SUBSTRINGS:
            self.assertNotIn(needle, out,
                             msg=f"PII substring leaked into stdout: {needle}")
            self.assertNotIn(needle, err,
                             msg=f"PII substring leaked into stderr: {needle}")

    def test_no_flags_defaults_to_dry_run_and_refuses_destructive(self):

        fake_plan = WIPE.WipePlan(
            counts={key: 0 for _, key in WIPE._COUNT_TABLES},
            vault_ids=[],
        )
        with mock.patch.object(WIPE, "collect_plan", return_value=fake_plan), \
             mock.patch.object(WIPE, "_wipe_leftovers_after_vaults",
                               return_value={}), \
             mock.patch.object(WIPE, "_delete_orphaned_accounts",
                               return_value=0):
            code, out, _ = _run_main_capturing(
                [], {"VAULTAI_ENV": "development"},
            )
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", out)


class TestFullMainRefusesInProduction(unittest.TestCase):
    def test_production_refuses_dry_run_without_override(self):

        code, out, err = _run_main_capturing(
            ["--dry-run"], {"VAULTAI_ENV": "production"},
        )
        self.assertNotEqual(code, 0)
        combined = (out + err).lower()
        self.assertTrue(
            "refused" in combined or "production" in combined,
            msg=f"expected refusal message, got: {out!r} {err!r}",
        )

    def test_production_refuses_destructive_without_override(self):
        code, out, err = _run_main_capturing(
            [
                "--confirm-wipe-all-test-users",
                "--i-understand-this-deletes-all-users",
            ],
            {"VAULTAI_ENV": "production"},
        )
        self.assertNotEqual(code, 0)

    def test_production_refuses_destructive_without_understand_flag(self):

        code, out, err = _run_main_capturing(
            ["--confirm-wipe-all-test-users"],
            {
                "VAULTAI_ENV": "production",
                "VAULTAI_ALLOW_TEST_USER_WIPE": "true",
            },
        )
        self.assertNotEqual(code, 0)

    def test_production_refuses_destructive_without_confirm_flag(self):




        fake_plan = WIPE.WipePlan(
            counts={key: 0 for _, key in WIPE._COUNT_TABLES},
            vault_ids=[],
        )
        with mock.patch.object(WIPE, "collect_plan", return_value=fake_plan), \
             mock.patch.object(WIPE, "_wipe_leftovers_after_vaults",
                               return_value={}), \
             mock.patch.object(WIPE, "_delete_orphaned_accounts",
                               return_value=0):
            code, out, err = _run_main_capturing(
                ["--i-understand-this-deletes-all-users"],
                {
                    "VAULTAI_ENV": "production",
                    "VAULTAI_ALLOW_TEST_USER_WIPE": "true",
                },
            )
        self.assertIn("DRY-RUN", out)
        self.assertNotIn("DESTRUCTIVE wipe complete", out)


class TestLogsCarryNoPii(unittest.TestCase):
    def test_delete_one_vault_logs_only_hashed_prefix_on_failure(self):

        buf_err = io.StringIO()
        import logging as _logging
        h = _logging.StreamHandler(buf_err)
        h.setFormatter(_logging.Formatter("%(message)s"))
        WIPE.logger.addHandler(h)
        WIPE.logger.setLevel(_logging.WARNING)
        try:
            fake_vds = mock.MagicMock()
            fake_vds.REASON_DEVELOPMENT_FULL_USER_WIPE = \
                "development_full_user_wipe"
            fake_vds.hashed_vault_id.return_value = "0" * 64
            def _boom(vid, *, reason):
                raise ValueError(
                    "sensitive-looking user@example.com should never surface"
                )
            fake_vds.delete_vault_and_all_data = _boom

            with mock.patch.dict(sys.modules,
                                 {"vault_deletion_service": fake_vds}):
                ok, _ = WIPE._delete_one_vault(
                    "the-real-vault-id-should-not-appear",
                )
            self.assertFalse(ok)
            log_text = buf_err.getvalue()
            self.assertNotIn(
                "the-real-vault-id-should-not-appear",
                log_text,
                msg="raw vault id must never appear in log lines",
            )
            self.assertNotIn(
                "user@example.com", log_text,
                msg="exception detail with email must never surface",
            )
            self.assertIn("hashed=", log_text)
        finally:
            WIPE.logger.removeHandler(h)


class TestScriptUsesSharedDeletionService(unittest.TestCase):
    def test_script_source_calls_delete_vault_and_all_data(self):
        src = _SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("delete_vault_and_all_data", src,
                      msg="wipe script must use the shared deletion "
                          "service, not raw SQL vault delete")
        self.assertIn("REASON_DEVELOPMENT_FULL_USER_WIPE", src)

    def test_script_source_does_not_touch_alembic_version(self):
        src = _SCRIPT_PATH.read_text(encoding="utf-8")




        code_only = re.sub(r'""".*?"""', "", src, flags=re.DOTALL)
        code_only = re.sub(r"'''.*?'''", "", code_only, flags=re.DOTALL)
        code_only_upper = code_only.upper()

        self.assertNotRegex(
            code_only_upper, r"\bTRUNCATE\s+",
            msg="wipe script code must not TRUNCATE anything",
        )
        self.assertNotRegex(
            code_only_upper, r"\bDROP\s+TABLE\b",
            msg="wipe script code must not DROP TABLE anything",
        )


        self.assertNotIn(
            "DELETE FROM alembic_version", src,
            msg="wipe script must never issue DELETE against "
                "alembic_version",
        )

        matches = re.findall(r"alembic_version", src)
        self.assertTrue(
            len(matches) >= 1,
            msg="alembic_version should be named in the preserved-"
                "tables list so future readers see it's intentionally "
                "protected",
        )


class TestPlanShape(unittest.TestCase):
    def test_wipe_plan_defaults_are_zero(self):
        plan = WIPE.WipePlan()
        self.assertEqual(plan.accounts_count, 0)
        self.assertEqual(plan.vaults_count, 0)

    def test_wipe_plan_reflects_counts(self):
        plan = WIPE.WipePlan(counts={"accounts": 7, "vaults": 4})
        self.assertEqual(plan.accounts_count, 7)
        self.assertEqual(plan.vaults_count, 4)


class TestPrintSafePlanCarriesNoPii(unittest.TestCase):
    def test_safe_plan_printout_only_contains_counts_and_labels(self):
        plan = WIPE.WipePlan(
            counts={key: 42 for _, key in WIPE._COUNT_TABLES},
            vault_ids=["v-1", "v-2"],
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            WIPE._print_safe_plan(plan)
        out = buf.getvalue()
        for needle in PII_SUBSTRINGS:
            self.assertNotIn(needle, out,
                             msg=f"PII substring in plan printout: {needle}")

        for _, key in WIPE._COUNT_TABLES:
            self.assertIn(key, out)


if __name__ == "__main__":
    unittest.main()
