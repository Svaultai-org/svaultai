


from __future__ import annotations

import io
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock


_BACKEND_ROOT = Path(__file__).parent
_REPO_ROOT = _BACKEND_ROOT.parent


def _import_script():

    script_dir = _BACKEND_ROOT / "scripts"
    sys.path.insert(0, str(script_dir))
    try:
        import importlib
        if "check_crypto_wallet_readiness" in sys.modules:
            mod = importlib.reload(
                sys.modules["check_crypto_wallet_readiness"],
            )
        else:
            mod = importlib.import_module(
                "check_crypto_wallet_readiness",
            )
        return mod
    finally:
        if str(script_dir) in sys.path:
            sys.path.remove(str(script_dir))


def _wipe_env(*names: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for n in names:
        snap[n] = os.environ.get(n)
        os.environ.pop(n, None)
    return snap


def _restore_env(snap: dict[str, str | None]) -> None:
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class EnvExampleFilesPresentAndSafeTests(unittest.TestCase):


    def test_env_example_present(self):
        p = _BACKEND_ROOT / ".env.example"
        self.assertTrue(p.exists(), f"missing {p}")

    def test_env_production_example_present(self):
        p = _BACKEND_ROOT / ".env.production.example"
        self.assertTrue(p.exists(), f"missing {p}")

    def _example_text(self, name: str) -> str:
        return (_BACKEND_ROOT / name).read_text(encoding="utf-8")

    def test_env_example_contains_all_required_crypto_keys(self):
        text = self._example_text(".env.example")
        for k in (
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            "VAULTAI_CRYPTO_DEFAULT_NETWORK",
            "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
            "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED",
            "ETHEREUM_MAINNET_RPC_URL",
            "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
            "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
            "VAULTAI_CRYPTO_SOLANA_ENABLED",
            "VAULTAI_CRYPTO_SOLANA_SEND_ENABLED",
            "VAULTAI_CRYPTO_SOLANA_SEND_PAUSED",
            "SOLANA_RPC_URL",
            "VAULTAI_CRYPTO_TRON_ENABLED",
            "VAULTAI_CRYPTO_TRON_SEND_ENABLED",
            "VAULTAI_CRYPTO_TRON_SEND_PAUSED",
            "TRON_API_BASE_URL",
            "TRON_API_KEY",
            "TRON_USDT_CONTRACT_ADDRESS",
            "VAULTAI_CRYPTO_XMR_ENABLED",
            "VAULTAI_CRYPTO_XMR_SEND_ENABLED",
            "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
            "VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN",
            "VAULTAI_BILLING_HEALTH_ADMIN_TOKEN",
        ):
            self.assertIn(k, text, f".env.example missing {k}")

    def test_env_production_example_contains_all_required_keys(self):
        text = self._example_text(".env.production.example")
        for k in (
            "VAULT_SESSION_SECRET",
            "DATABASE_URL",
            "DESCOPE_PROJECT_ID",
            "OPENAI_API_KEY",
            "CORS_ALLOWED_ORIGIN_REGEX",
            "VAULTAI_DEBUG_ENDPOINTS_ENABLED",
            "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST",
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            "VAULTAI_CRYPTO_DEFAULT_NETWORK",
            "ETHEREUM_MAINNET_RPC_URL",
            "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
            "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
            "SOLANA_RPC_URL",
            "TRON_API_BASE_URL",
            "TRON_API_KEY",
            "TRON_USDT_CONTRACT_ADDRESS",
            "VAULTAI_CRYPTO_XMR_ENABLED",
            "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
            "VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN",
            "STRIPE_API_KEY",
            "STRIPE_WEBHOOK_SECRET",
        ):
            self.assertIn(k, text, f".env.production.example missing {k}")

    def test_env_examples_contain_only_placeholders(self):

        for name in (".env.example", ".env.production.example"):
            text = self._example_text(name)
            for pattern in (
                r"sk_live_[A-Za-z0-9]{6,}",
                r"whsec_[A-Za-z0-9]{6,}",
                r"pk_live_[A-Za-z0-9]{6,}",

                r"https://mainnet\.infura\.io/v3/[A-Za-z0-9]{16,}",
                r"https://[a-z0-9-]+\.alchemyapi\.io/v2/[A-Za-z0-9]{16,}",
            ):
                m = re.search(pattern, text)
                self.assertIsNone(
                    m,
                    f"{name} contains what looks like a real "
                    f"secret matching {pattern!r}: {m}",
                )

    def test_env_example_leaves_sensitive_values_blank(self):

        text = self._example_text(".env.example")
        for sensitive_key in (
            "ETHEREUM_MAINNET_RPC_URL",
            "SOLANA_RPC_URL",
            "TRON_API_BASE_URL",
            "TRON_API_KEY",
            "VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN",
            "VAULTAI_BILLING_HEALTH_ADMIN_TOKEN",
        ):
            m = re.search(
                r"^" + re.escape(sensitive_key) + r"[ \t]*=[ \t]*(\S[^\r\n]*)$",
                text, re.MULTILINE,
            )
            self.assertIsNone(
                m,
                f".env.example {sensitive_key} must be blank (found "
                f"{m.group(1) if m else None!r})",
            )


class ScrubHelperTests(unittest.TestCase):


    def setUp(self) -> None:
        self.mod = _import_script()

    def test_scrub_redacts_key_named_rpc_url(self):
        out = self.mod.scrub({
            "ETHEREUM_MAINNET_RPC_URL":
                "https://mainnet-rpc.example/abc-xyz-secret",
        })
        self.assertEqual(
            out["ETHEREUM_MAINNET_RPC_URL"], "<redacted>",
        )

    def test_scrub_redacts_key_named_api_key(self):
        out = self.mod.scrub({"apiKey": "SUPER-SECRET-STRING"})
        self.assertEqual(out["apiKey"], "<redacted>")

    def test_scrub_redacts_key_named_contract(self):
        out = self.mod.scrub({
            "usdtContract": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "tokenContract": "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj",
        })
        self.assertEqual(out["usdtContract"], "<redacted>")
        self.assertEqual(out["tokenContract"], "<redacted>")

    def test_scrub_redacts_key_named_public_address(self):
        out = self.mod.scrub({
            "publicAddress": "0x1111111111111111111111111111111111111111",
        })
        self.assertEqual(out["publicAddress"], "<redacted>")

    def test_scrub_redacts_key_named_tx_hash(self):
        out = self.mod.scrub({
            "txHash":
                "0x1111111111111111111111111111111111111111"
                "111111111111111111111111",
        })
        self.assertEqual(out["txHash"], "<redacted>")

    def test_scrub_redacts_key_named_encrypted_wallet_secret(self):
        out = self.mod.scrub({
            "encryptedWalletSecret": "vault-cipher:xxxxxxxxxxxx",
        })
        self.assertEqual(out["encryptedWalletSecret"], "<redacted>")

    def test_scrub_redacts_key_named_mnemonic_or_seed(self):
        for k in ("mnemonic", "seed", "polyseed",
                  "moneroSeed", "privateSpendKey",
                  "privateViewKey", "walletPassword"):
            out = self.mod.scrub({k: "leaked-plaintext"})
            self.assertEqual(out[k], "<redacted>")

    def test_scrub_redacts_url_inside_a_free_text_message(self):
        out = self.mod.scrub({
            "message": "Failed hitting https://leak.example/rpc timeout",
        })
        self.assertNotIn("leak.example", out["message"])
        self.assertIn("<redacted>", out["message"])

    def test_scrub_redacts_eth_address_pattern_in_free_text(self):
        out = self.mod.scrub({
            "message":
                "USDT contract 0xdAC17F958D2ee523a2206206994597C13D831ec7 "
                "read fail",
        })
        self.assertNotIn(
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            out["message"],
        )
        self.assertIn("<redacted>", out["message"])

    def test_scrub_redacts_tron_address_pattern_in_free_text(self):
        out = self.mod.scrub({
            "message": "TRC20 contract TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj fail",
        })
        self.assertNotIn(
            "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj", out["message"],
        )

    def test_scrub_redacts_xmr_address_pattern_in_free_text(self):
        addr = (
            "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7"
            "SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A"
        )
        out = self.mod.scrub({"message": f"XMR addr {addr} scan error"})
        self.assertNotIn(addr, out["message"])

    def test_scrub_handles_nested_structures(self):
        payload = {
            "assets": [
                {"rowId": "ethereum_mainnet_eth",
                 "featureEnabled": True,
                 "ETHEREUM_MAINNET_RPC_URL":
                     "https://mainnet.example/xxx"},
                {"rowId": "tron_mainnet_usdt_trc20",
                 "tokenContract":
                     "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"},
            ],
        }
        out = self.mod.scrub(payload)
        self.assertEqual(
            out["assets"][0]["ETHEREUM_MAINNET_RPC_URL"], "<redacted>",
        )
        self.assertEqual(
            out["assets"][1]["tokenContract"], "<redacted>",
        )
        self.assertTrue(out["assets"][0]["featureEnabled"])

    def test_scrub_preserves_safe_scalar_values(self):
        out = self.mod.scrub({
            "walletEngineEnabled": True,
            "defaultNetwork": "ethereum_mainnet",
            "assetsReady": 5,
            "assetsTotal": 6,
        })
        self.assertEqual(out["walletEngineEnabled"], True)
        self.assertEqual(out["defaultNetwork"], "ethereum_mainnet")
        self.assertEqual(out["assetsReady"], 5)
        self.assertEqual(out["assetsTotal"], 6)


class SummarizeTests(unittest.TestCase):

    def setUp(self) -> None:
        self.mod = _import_script()

    def _diag(self, overrides: dict[str, tuple[bool, str]]):

        base = {
            "ethereum_mainnet_eth":         (True,  "ready"),
            "ethereum_mainnet_usdt_erc20":  (True,  "ready"),
            "ethereum_mainnet_usdc_erc20":  (True,  "ready"),
            "solana_mainnet_sol":           (True,  "ready"),
            "tron_mainnet_usdt_trc20":      (True,  "ready"),
            "monero_mainnet_xmr":           (False, "xmr_scanner_client_required"),
        }
        base.update(overrides)
        return {
            "assets": [
                {"rowId": rid,
                 "balanceRouteReady": r,
                 "lastBalanceReason": reason}
                for rid, (r, reason) in base.items()
            ],
        }

    def test_all_ready_including_xmr_intentional(self):
        features = {"walletEngineEnabled": True}
        lines, fixable, intentional, total = self.mod.summarize(
            features, self._diag({}),
        )
        self.assertEqual(total, 6)
        self.assertEqual(fixable, 0)
        self.assertEqual(intentional, 1)
        self.assertTrue(
            any("XMR" in ln and "not ready" in ln for ln in lines),
        )
        self.assertTrue(any("ready" in ln for ln in lines))

    def test_eth_rpc_missing_produces_fixable_not_ready(self):
        features = {"walletEngineEnabled": True}
        diag = self._diag({
            "ethereum_mainnet_eth": (False, "rpc_not_configured"),
        })
        lines, fixable, intentional, total = self.mod.summarize(features, diag)
        self.assertEqual(fixable, 1)
        self.assertEqual(intentional, 1)
        self.assertTrue(
            any(ln.startswith("ETH Mainnet") and "not ready" in ln
                and "rpc_not_configured" in ln
                for ln in lines),
        )

    def test_diagnosis_none_marks_every_row_unknown(self):
        features = {"walletEngineEnabled": True}
        lines, fixable, intentional, total = self.mod.summarize(
            features, None,
        )
        self.assertEqual(fixable, 6)
        for ln in lines:
            self.assertIn("unknown", ln)


class ReportOutputHasNoSecretsTests(unittest.TestCase):

    def setUp(self) -> None:
        self.mod = _import_script()

    def test_report_never_prints_configured_url(self):

        features = {
            "walletEngineEnabled": True,
            "defaultNetwork": "ethereum_mainnet",
            "defaultNetworkConfigValid": True,
        }
        diag = {
            "assets": [
                {"rowId": "ethereum_mainnet_eth",
                 "balanceRouteReady": True,
                 "lastBalanceReason": "ready",
                 "rpcEnvVar": "ETHEREUM_MAINNET_RPC_URL"},
            ],
        }
        report = self.mod.format_report(features, None, diag)
        for banned in (
            "https://",
            "mainnet-rpc.example",
            "sk_live_",
            "whsec_",
        ):
            self.assertNotIn(banned, report,
                             f"report leaked {banned!r}")

    def test_report_says_secret_safe_footer(self):
        features = {"walletEngineEnabled": True}
        report = self.mod.format_report(features, None, None)
        self.assertIn("no RPC URLs", report)
        self.assertIn("no API keys", report)
        self.assertIn("no token contract values", report)
        self.assertIn("no wallet addresses", report)
        self.assertIn("no tx hashes", report)
        self.assertIn("no private keys", report)
        self.assertIn("no mnemonics", report)


class ErrorHandlingTests(unittest.TestCase):


    def setUp(self) -> None:
        self.mod = _import_script()

    def test_backend_unreachable_returns_exit_2(self):
        with mock.patch(
            "check_crypto_wallet_readiness."
            "_fetch_features_health_diagnosis",
            side_effect=self.mod.BackendUnreachableError("connection refused"),
        ):
            captured = io.StringIO()
            with mock.patch("sys.stderr", captured):
                rc = self.mod.main([
                    "--base-url", "http://localhost:0",
                    "--auth-token", "tok",
                ])
        self.assertEqual(rc, 2)
        self.assertIn("backend unreachable", captured.getvalue())

    def test_admin_auth_denied_returns_exit_2(self):
        with mock.patch(
            "check_crypto_wallet_readiness."
            "_fetch_features_health_diagnosis",
            side_effect=self.mod.AdminAuthError("HTTP 403"),
        ):
            captured = io.StringIO()
            with mock.patch("sys.stderr", captured):
                rc = self.mod.main([
                    "--base-url", "http://localhost:0",
                    "--auth-token", "tok",
                ])
        self.assertEqual(rc, 2)
        self.assertIn("admin auth denied", captured.getvalue())

    def test_all_ready_returns_exit_0(self):
        features = {"walletEngineEnabled": True}
        diag = {
            "assets": [
                {"rowId": rid, "balanceRouteReady": True,
                 "lastBalanceReason": "ready"}
                for rid in (
                    "ethereum_mainnet_eth",
                    "ethereum_mainnet_usdt_erc20",
                    "ethereum_mainnet_usdc_erc20",
                    "solana_mainnet_sol",
                    "tron_mainnet_usdt_trc20",
                )
            ] + [
                {"rowId": "monero_mainnet_xmr",
                 "balanceRouteReady": False,
                 "lastBalanceReason": "xmr_scanner_client_required"},
            ],
        }
        with mock.patch(
            "check_crypto_wallet_readiness."
            "_fetch_features_health_diagnosis",
            return_value=(features, None, diag),
        ), mock.patch("builtins.print"):
            rc = self.mod.main([
                "--base-url", "http://localhost:0",
                "--auth-token", "tok",
            ])
        self.assertEqual(rc, 0)

    def test_fixable_not_ready_returns_exit_1(self):
        features = {"walletEngineEnabled": True}
        diag = {
            "assets": [
                {"rowId": "ethereum_mainnet_eth",
                 "balanceRouteReady": False,
                 "lastBalanceReason": "rpc_not_configured"},
                {"rowId": "ethereum_mainnet_usdt_erc20",
                 "balanceRouteReady": True,
                 "lastBalanceReason": "ready"},
                {"rowId": "ethereum_mainnet_usdc_erc20",
                 "balanceRouteReady": True,
                 "lastBalanceReason": "ready"},
                {"rowId": "solana_mainnet_sol",
                 "balanceRouteReady": True,
                 "lastBalanceReason": "ready"},
                {"rowId": "tron_mainnet_usdt_trc20",
                 "balanceRouteReady": True,
                 "lastBalanceReason": "ready"},
                {"rowId": "monero_mainnet_xmr",
                 "balanceRouteReady": False,
                 "lastBalanceReason": "xmr_scanner_client_required"},
            ],
        }
        with mock.patch(
            "check_crypto_wallet_readiness."
            "_fetch_features_health_diagnosis",
            return_value=(features, None, diag),
        ), mock.patch("builtins.print"):
            rc = self.mod.main([
                "--base-url", "http://localhost:0",
                "--auth-token", "tok",
            ])
        self.assertEqual(rc, 1)


class ProductionBootStillGuardedTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(
            "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
            "VAULT_SESSION_SECRET",
            "CORS_ALLOWED_ORIGIN_REGEX", "CORS_ALLOWED_ORIGINS",
            "VAULTAI_DEBUG_ENDPOINTS_ENABLED",
            "STRIPE_WEBHOOK_SECRET",
            "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST",
        )
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_production_boot_refuses_without_session_secret(self):
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = "^https://app\\.example$"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
        import vault_config
        vault_config.reset_for_tests()
        with self.assertRaises(RuntimeError) as cm:
            vault_config.get_config()
        self.assertIn("VAULT_SESSION_SECRET", str(cm.exception))

    def test_production_boot_refuses_without_stripe_webhook_secret(self):
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = "^https://app\\.example$"
        import vault_config
        vault_config.reset_for_tests()
        with self.assertRaises(RuntimeError) as cm:
            vault_config.get_config()
        self.assertIn("STRIPE_WEBHOOK_SECRET", str(cm.exception))

    def test_production_boot_refuses_without_cors(self):
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
        import vault_config
        vault_config.reset_for_tests()
        with self.assertRaises(RuntimeError) as cm:
            vault_config.get_config()
        self.assertIn("CORS", str(cm.exception))

    def test_production_boot_refuses_with_debug_endpoints_on(self):
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = "^https://app\\.example$"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
        os.environ["VAULTAI_DEBUG_ENDPOINTS_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        with self.assertRaises(RuntimeError) as cm:
            vault_config.get_config()
        self.assertIn("VAULTAI_DEBUG_ENDPOINTS_ENABLED", str(cm.exception))

    def test_production_boot_refuses_with_dev_auto_trust_on(self):
        os.environ["VAULTAI_ENV"] = "production"
        os.environ["VAULT_SESSION_SECRET"] = "x" * 48
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = "^https://app\\.example$"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
        os.environ["VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        with self.assertRaises(RuntimeError) as cm:
            vault_config.get_config()
        self.assertIn("VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
