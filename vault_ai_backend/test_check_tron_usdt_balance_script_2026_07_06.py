"""Verifies scripts/check_tron_usdt_balance.py:
   1. reads TRON_API_BASE_URL / TRON_API_KEY / TRON_USDT_CONTRACT_ADDRESS
   2. prints only closed-set fields
   3. never leaks the address, key, contract, provider URL, or raw body
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock


_BACKEND_ROOT = Path(__file__).parent
_SCRIPT_PATH = _BACKEND_ROOT / "scripts" / "check_tron_usdt_balance.py"


_USDT_MAINNET_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
_HOLDER = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
_SECRET_API_KEY = "sensitive_key_value_XYZ_do_not_leak"
_SECRET_URL     = "https://mock.trongrid.example.internal/wallet"


class _FakeUrlopenResp:
    def __init__(self, body_obj):
        self._body = json.dumps(body_obj).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self._body


def _import_script_main():

    scripts_dir = str(_SCRIPT_PATH.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))
    if "check_tron_usdt_balance" in sys.modules:
        del sys.modules["check_tron_usdt_balance"]
    import check_tron_usdt_balance
    return check_tron_usdt_balance.main


def _run_script(argv, env, urlopen_side_effect, env_loader=None):
    main = _import_script_main()
    import check_tron_usdt_balance as script_mod
    if env_loader is None:
        env_loader = lambda: (False, False)
    stdout, stderr = io.StringIO(), io.StringIO()
    with mock.patch.dict(os.environ, env, clear=False):
        with mock.patch.object(
            script_mod, "_load_backend_env", side_effect=env_loader,
        ):
            with mock.patch("urllib.request.urlopen",
                            side_effect=urlopen_side_effect):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    try:
                        exit_code = main(argv)
                    except SystemExit as se:
                        exit_code = int(se.code or 0)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class CheckTronUsdtBalanceScriptOutputTests(unittest.TestCase):


    def test_all_env_missing_prints_configured_flags_false(self):
        env = {}

        for var in ("TRON_API_BASE_URL", "TRON_RPC_URL",
                    "TRON_API_KEY", "TRON_USDT_CONTRACT_ADDRESS"):
            env[var] = ""

        exit_code, out, _ = _run_script(
            ["--address", _HOLDER], env,
            lambda r, timeout=None: _FakeUrlopenResp({}),
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("tron_configured=false", out)
        self.assertIn("api_key_present=false", out)
        self.assertIn("contract_configured=false", out)
        self.assertIn("provider_status=api_not_configured", out)
        self.assertIn("balance_status=unavailable", out)


    def test_missing_contract_prints_invalid_contract(self):
        env = {
            "TRON_API_BASE_URL": _SECRET_URL,
            "TRON_API_KEY":      _SECRET_API_KEY,
            "TRON_USDT_CONTRACT_ADDRESS": "",
        }
        exit_code, out, _ = _run_script(
            ["--address", _HOLDER], env,
            lambda r, timeout=None: _FakeUrlopenResp({}),
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("tron_configured=true", out)
        self.assertIn("api_key_present=true", out)
        self.assertIn("contract_configured=false", out)
        self.assertIn("provider_status=invalid_contract", out)
        self.assertIn("balance_status=unavailable", out)


    def test_real_zero_prints_amount_zero_and_available(self):
        env = {
            "TRON_API_BASE_URL": _SECRET_URL,
            "TRON_API_KEY":      _SECRET_API_KEY,
            "TRON_USDT_CONTRACT_ADDRESS": _USDT_MAINNET_CONTRACT,
        }
        exit_code, out, _ = _run_script(
            ["--address", _HOLDER], env,
            lambda r, timeout=None: _FakeUrlopenResp({
                "result": {"result": True},
                "constant_result": ["0" * 64],
            }),
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("provider_status=ok", out)
        self.assertIn("balance_status=available", out)
        self.assertIn("amount=0", out)


    def test_provider_error_prints_provider_error_message_status(self):
        env = {
            "TRON_API_BASE_URL": _SECRET_URL,
            "TRON_API_KEY":      _SECRET_API_KEY,
            "TRON_USDT_CONTRACT_ADDRESS": _USDT_MAINNET_CONTRACT,
        }
        exit_code, out, _ = _run_script(
            ["--address", _HOLDER], env,
            lambda r, timeout=None: _FakeUrlopenResp({
                "result": {
                    "result": False,
                    "code":    "CONTRACT_VALIDATE_ERROR",
                    "message": "malformed",
                },
            }),
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("provider_status=provider_error_message", out)
        self.assertIn("balance_status=unavailable", out)
        self.assertNotIn("amount=", out)


    def test_401_with_key_prints_api_unauthorized(self):
        def raise_401(req, timeout=None):
            raise urllib.error.HTTPError(
                url="x", code=401, msg="unauth",
                hdrs=None, fp=io.BytesIO(b""),
            )

        env = {
            "TRON_API_BASE_URL": _SECRET_URL,
            "TRON_API_KEY":      _SECRET_API_KEY,
            "TRON_USDT_CONTRACT_ADDRESS": _USDT_MAINNET_CONTRACT,
        }
        exit_code, out, _ = _run_script(
            ["--address", _HOLDER], env, raise_401,
        )
        self.assertEqual(exit_code, 1)
        self.assertIn("provider_status=api_unauthorized", out)


class CheckTronUsdtBalanceScriptSecretSafetyTests(unittest.TestCase):


    def _run_and_get_output(self, response_body):
        env = {
            "TRON_API_BASE_URL": _SECRET_URL,
            "TRON_API_KEY":      _SECRET_API_KEY,
            "TRON_USDT_CONTRACT_ADDRESS": _USDT_MAINNET_CONTRACT,
        }
        _, out, err = _run_script(
            ["--address", _HOLDER], env,
            lambda r, timeout=None: _FakeUrlopenResp(response_body),
        )
        return (out + err).lower()


    def test_output_never_leaks_the_address(self):
        combined = self._run_and_get_output({
            "result": {"result": True},
            "constant_result": ["0" * 64],
        })
        self.assertNotIn(_HOLDER.lower(), combined)


    def test_output_never_leaks_the_api_key_value(self):
        combined = self._run_and_get_output({
            "result": {"result": True},
            "constant_result": ["0" * 64],
        })
        self.assertNotIn(_SECRET_API_KEY.lower(), combined)


    def test_output_never_leaks_the_contract_value(self):
        combined = self._run_and_get_output({
            "result": {"result": True},
            "constant_result": ["0" * 64],
        })
        self.assertNotIn(_USDT_MAINNET_CONTRACT.lower(), combined)


    def test_output_never_leaks_the_provider_url(self):
        combined = self._run_and_get_output({
            "result": {"result": True},
            "constant_result": ["0" * 64],
        })
        self.assertNotIn(_SECRET_URL.lower(), combined)
        self.assertNotIn("mock.trongrid", combined)


    def test_output_never_leaks_raw_response_body_fragments(self):
        combined = self._run_and_get_output({
            "result": {"result": True},
            "constant_result": ["deadbeef" + "0" * 56],
        })

        for banned in ('"result":', "constant_result:[",
                       "deadbeef", "trongrid",
                       "bearer", "authorization",
                       "private_key", "encrypted_secret",
                       "tx_hash", "txid",):
            self.assertNotIn(banned, combined,
                f"CLI output leaks {banned!r}")


class CheckTronUsdtBalanceScriptSourceSafetyTests(unittest.TestCase):


    def test_source_never_prints_env_values_directly(self):
        src = _SCRIPT_PATH.read_text(encoding="utf-8")

        for banned in (
            "print(base_url",
            "print(api_key",
            "print(contract",
            "print(args.address",
            "print(f\"{base_url",
            "print(f\"{api_key",
            "print(f\"{contract",
            "print(f\"{args.address",
        ):
            self.assertNotIn(
                banned, src,
                f"script leaks a raw env/address value with {banned!r}",
            )


    def test_source_only_uses_the_safe_emit_helper_for_printing(self):
        src = _SCRIPT_PATH.read_text(encoding="utf-8")

        printed_lines = [
            ln.strip() for ln in src.splitlines()
            if ln.strip().startswith("print(")
        ]

        for ln in printed_lines:
            self.assertTrue(
                'f"{k}={v}"' in ln,
                f"unexpected print statement (only the closed-set "
                f"emit helper is allowed): {ln!r}",
            )


class CheckTronUsdtBalanceEnvFieldsAlwaysEmittedTests(unittest.TestCase):


    def test_env_path_found_and_env_loaded_always_appear(self):

        env = {
            "TRON_API_BASE_URL": "",
            "TRON_RPC_URL":      "",
            "TRON_API_KEY":      "",
            "TRON_USDT_CONTRACT_ADDRESS": "",
        }
        _, out, _ = _run_script(
            ["--address", _HOLDER], env,
            lambda r, timeout=None: _FakeUrlopenResp({}),
            env_loader=lambda: (True, True),
        )
        self.assertIn("env_path_found=true", out)
        self.assertIn("env_loaded=true", out)


    def test_env_fields_report_false_when_dotenv_missing(self):

        env = {
            "TRON_API_BASE_URL": "",
            "TRON_RPC_URL":      "",
            "TRON_API_KEY":      "",
            "TRON_USDT_CONTRACT_ADDRESS": "",
        }
        _, out, _ = _run_script(
            ["--address", _HOLDER], env,
            lambda r, timeout=None: _FakeUrlopenResp({}),
            env_loader=lambda: (False, False),
        )
        self.assertIn("env_path_found=false", out)
        self.assertIn("env_loaded=false", out)


    def test_env_fields_appear_before_configured_fields(self):

        env = {
            "TRON_API_BASE_URL": "",
            "TRON_RPC_URL":      "",
            "TRON_API_KEY":      "",
            "TRON_USDT_CONTRACT_ADDRESS": "",
        }
        _, out, _ = _run_script(
            ["--address", _HOLDER], env,
            lambda r, timeout=None: _FakeUrlopenResp({}),
            env_loader=lambda: (True, True),
        )
        env_path_idx = out.find("env_path_found=")
        env_loaded_idx = out.find("env_loaded=")
        configured_idx = out.find("tron_configured=")
        self.assertGreater(env_path_idx,   -1)
        self.assertGreater(env_loaded_idx, env_path_idx)
        self.assertGreater(configured_idx, env_loaded_idx,
            "env_* fields must be reported before tron_configured "
            "so the user sees the env-loading status first",
        )


class CheckTronUsdtBalanceEnvLoaderTests(unittest.TestCase):


    def _write_env(self, dir_path, contents):
        env_path = dir_path / ".env"
        env_path.write_text(contents, encoding="utf-8")
        return env_path


    def test_load_backend_env_finds_dotenv_and_populates_os_environ(self):

        try:
            import dotenv
        except ImportError:
            self.skipTest("python-dotenv not installed")

        from unittest.mock import patch
        import tempfile
        _import_script_main()
        import check_tron_usdt_balance as script_mod

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._write_env(tmp_path,
                "TRON_API_BASE_URL=https://placeholder.example/api\n"
                "TRON_API_KEY=placeholder-key-value\n"
                "TRON_USDT_CONTRACT_ADDRESS="
                "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t\n",
            )


            snapshot_keys = (
                "TRON_API_BASE_URL",
                "TRON_API_KEY",
                "TRON_USDT_CONTRACT_ADDRESS",
            )
            saved = {k: os.environ.pop(k, None) for k in snapshot_keys}
            try:
                with patch.object(
                    script_mod, "_BACKEND_ROOT", tmp_path,
                ):
                    env_path_found, env_loaded = \
                        script_mod._load_backend_env()
                self.assertTrue(env_path_found)
                self.assertTrue(env_loaded)

                self.assertEqual(
                    os.environ.get("TRON_API_KEY"),
                    "placeholder-key-value",
                )
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


    def test_load_backend_env_reports_false_when_dotenv_missing(self):
        from unittest.mock import patch
        import tempfile
        _import_script_main()
        import check_tron_usdt_balance as script_mod

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            with patch.object(script_mod, "_BACKEND_ROOT", tmp_path):
                env_path_found, env_loaded = \
                    script_mod._load_backend_env()
            self.assertFalse(env_path_found)
            self.assertFalse(env_loaded)


    def test_load_backend_env_uses_same_dotenv_module_as_main(self):

        script_src = _SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertIn(
            "from dotenv import load_dotenv", script_src,
            "check_tron_usdt_balance.py must load .env using the "
            "same python-dotenv module main.py uses",
        )

        main_src = (_BACKEND_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("from dotenv import load_dotenv", main_src)


    def test_load_backend_env_prefers_backend_root_dotenv(self):

        script_src = _SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertRegex(
            script_src,
            r"load_dotenv\(\s*env_path\s*\)",
            "the loader must pass the explicit backend-root .env path "
            "so it works no matter what CWD the user runs from",
        )


class CheckTronUsdtBalanceEnvLoaderSafetyTests(unittest.TestCase):


    def test_env_loader_output_never_prints_env_values(self):
        from unittest.mock import patch
        import tempfile
        _import_script_main()
        import check_tron_usdt_balance as script_mod

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".env").write_text(
                "TRON_API_BASE_URL=https://SECRET_URL.example\n"
                "TRON_API_KEY=SECRET_KEY_ABCDEF_LEAK_CANARY\n"
                "TRON_USDT_CONTRACT_ADDRESS="
                "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t\n",
                encoding="utf-8",
            )
            snapshot_keys = (
                "TRON_API_BASE_URL",
                "TRON_API_KEY",
                "TRON_USDT_CONTRACT_ADDRESS",
            )
            saved = {k: os.environ.pop(k, None) for k in snapshot_keys}
            try:
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(
                    script_mod, "_BACKEND_ROOT", tmp_path,
                ):
                    with mock.patch(
                        "urllib.request.urlopen",
                        side_effect=lambda r, timeout=None:
                            _FakeUrlopenResp({
                                "result": {"result": True},
                                "constant_result": ["0" * 64],
                            }),
                    ):
                        with redirect_stdout(stdout), \
                                redirect_stderr(stderr):
                            try:
                                script_mod.main([
                                    "--address", _HOLDER,
                                ])
                            except SystemExit:
                                pass
                combined = (stdout.getvalue()
                            + stderr.getvalue()).lower()

                self.assertNotIn(
                    "secret_key_abcdef_leak_canary", combined,
                    "CLI must NEVER print the API key even after "
                    "loading .env",
                )
                self.assertNotIn(
                    "secret_url.example", combined,
                    "CLI must NEVER print the provider URL even "
                    "after loading .env",
                )
                self.assertNotIn(
                    "tr7nhqjekqxgtci8q8zy4pl8otszgjlj6t", combined,
                    "CLI must NEVER print the contract value even "
                    "after loading .env",
                )
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
