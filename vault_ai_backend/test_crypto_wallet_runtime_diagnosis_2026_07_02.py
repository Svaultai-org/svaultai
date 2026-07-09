


from __future__ import annotations

import json
import os
import unittest
from pathlib import Path


_BACKEND_ROOT = Path(__file__).parent


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


_RUNTIME_ENV_KEYS = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_DEFAULT_NETWORK",
    "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
    "VAULTAI_CRYPTO_SOLANA_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_ENABLED",
    "SOLANA_RPC_URL",
    "VAULTAI_CRYPTO_TRON_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_ENABLED",
    "TRON_API_BASE_URL",
    "TRON_API_KEY",
    "TRON_USDT_CONTRACT_ADDRESS",
    "VAULTAI_CRYPTO_XMR_ENABLED",
    "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
)


class DiagnosisEnvelopeShapeTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_RUNTIME_ENV_KEYS)
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_envelope_has_all_expected_asset_rows(self):
        from crypto_wallet_diagnosis import (
            ROW_ETHEREUM_MAINNET_ETH,
            ROW_ETHEREUM_MAINNET_USDT_ERC20,
            ROW_ETHEREUM_MAINNET_USDC_ERC20,
            ROW_MONERO_MAINNET_XMR,
            ROW_SOLANA_MAINNET_SOL,
            ROW_TRON_MAINNET_USDT_TRC20,
            build_diagnosis_envelope,
        )
        env = build_diagnosis_envelope()
        rowIds = {r["rowId"] for r in env["assets"]}
        self.assertIn(ROW_ETHEREUM_MAINNET_ETH, rowIds)
        self.assertIn(ROW_ETHEREUM_MAINNET_USDT_ERC20, rowIds)
        self.assertIn(ROW_ETHEREUM_MAINNET_USDC_ERC20, rowIds)
        self.assertIn(ROW_SOLANA_MAINNET_SOL, rowIds)
        self.assertIn(ROW_TRON_MAINNET_USDT_TRC20, rowIds)
        self.assertIn(ROW_MONERO_MAINNET_XMR, rowIds)
        self.assertEqual(env["assetsTotal"], 6)

    def test_envelope_schema_string_is_stable(self):
        from crypto_wallet_diagnosis import (
            CRYPTO_WALLET_DIAGNOSIS_SCHEMA, build_diagnosis_envelope,
        )
        env = build_diagnosis_envelope()
        self.assertEqual(env["schema"], CRYPTO_WALLET_DIAGNOSIS_SCHEMA)
        self.assertEqual(env["schema"], "crypto_wallet_diagnosis_v1")

    def test_envelope_reveals_no_secret_values(self):
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = "https://secret-rpc.example"
        os.environ["ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS"] = (
            "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        )
        os.environ["TRON_API_KEY"] = "SUPER-SECRET-KEY"
        os.environ["TRON_API_BASE_URL"] = "https://tron-api.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = (
            "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
        )
        os.environ["SOLANA_RPC_URL"] = "https://sol-rpc.example"
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        env = build_diagnosis_envelope()
        blob = json.dumps(env)
        self.assertNotIn("secret-rpc.example", blob)
        self.assertNotIn("tron-api.example", blob)
        self.assertNotIn("sol-rpc.example", blob)
        self.assertNotIn("SUPER-SECRET-KEY", blob)
        self.assertNotIn("0xdAC17F958D2ee523a2206206994597C13D831ec7", blob)
        self.assertNotIn("TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj", blob)


class DiagnosisReasonTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(*_RUNTIME_ENV_KEYS)
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def _row(self, rowId: str) -> dict:
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        env = build_diagnosis_envelope()
        return next(r for r in env["assets"] if r["rowId"] == rowId)

    def test_eth_mainnet_reports_feature_disabled_when_flag_off(self):
        from crypto_wallet_diagnosis import (
            DIAG_REASON_FEATURE_DISABLED, ROW_ETHEREUM_MAINNET_ETH,
        )
        row = self._row(ROW_ETHEREUM_MAINNET_ETH)
        self.assertFalse(row["featureEnabled"])
        self.assertEqual(row["lastBalanceReason"], DIAG_REASON_FEATURE_DISABLED)
        self.assertFalse(row["balanceRouteReady"])

    def test_eth_mainnet_reports_rpc_not_configured(self):
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import (
            DIAG_REASON_RPC_NOT_CONFIGURED, ROW_ETHEREUM_MAINNET_ETH,
        )
        row = self._row(ROW_ETHEREUM_MAINNET_ETH)
        self.assertTrue(row["featureEnabled"])
        self.assertFalse(row["rpcConfigured"])
        self.assertEqual(row["lastBalanceReason"], DIAG_REASON_RPC_NOT_CONFIGURED)
        self.assertFalse(row["balanceRouteReady"])

    def test_usdt_erc20_reports_token_contract_not_configured(self):
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED"] = "true"
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = "https://rpc.example"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import (
            DIAG_REASON_TOKEN_CONTRACT, ROW_ETHEREUM_MAINNET_USDT_ERC20,
        )
        row = self._row(ROW_ETHEREUM_MAINNET_USDT_ERC20)
        self.assertTrue(row["featureEnabled"])
        self.assertTrue(row["rpcConfigured"])
        self.assertTrue(row["tokenContractRequired"])
        self.assertFalse(row["tokenContractConfigured"])
        self.assertEqual(row["lastBalanceReason"], DIAG_REASON_TOKEN_CONTRACT)
        self.assertFalse(row["balanceRouteReady"])

    def test_usdt_erc20_reports_ready_when_fully_configured(self):
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED"] = "true"
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = "https://rpc.example"
        os.environ["ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS"] = (
            "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        )
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import (
            DIAG_REASON_READY, ROW_ETHEREUM_MAINNET_USDT_ERC20,
        )
        row = self._row(ROW_ETHEREUM_MAINNET_USDT_ERC20)
        self.assertTrue(row["balanceRouteReady"])
        self.assertEqual(row["lastBalanceReason"], DIAG_REASON_READY)

    def test_solana_reports_feature_disabled_by_default(self):
        from crypto_wallet_diagnosis import ROW_SOLANA_MAINNET_SOL
        row = self._row(ROW_SOLANA_MAINNET_SOL)
        self.assertFalse(row["featureEnabled"])
        self.assertEqual(row["lastBalanceReason"], "feature_disabled")

    def test_solana_reports_rpc_not_configured_when_flag_on(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import ROW_SOLANA_MAINNET_SOL
        row = self._row(ROW_SOLANA_MAINNET_SOL)
        self.assertTrue(row["featureEnabled"])
        self.assertFalse(row["rpcConfigured"])
        self.assertEqual(row["lastBalanceReason"], "rpc_not_configured")

    def test_tron_reports_feature_disabled_by_default(self):
        from crypto_wallet_diagnosis import ROW_TRON_MAINNET_USDT_TRC20
        row = self._row(ROW_TRON_MAINNET_USDT_TRC20)
        self.assertFalse(row["featureEnabled"])

    def test_tron_reports_token_contract_not_configured(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://tron-api.example"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import ROW_TRON_MAINNET_USDT_TRC20
        row = self._row(ROW_TRON_MAINNET_USDT_TRC20)
        self.assertTrue(row["rpcConfigured"])
        self.assertFalse(row["tokenContractConfigured"])
        self.assertEqual(
            row["lastBalanceReason"], "token_contract_not_configured",
        )

    def test_tron_reports_ready_when_fully_configured(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://tron-api.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = (
            "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
        )
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import ROW_TRON_MAINNET_USDT_TRC20
        row = self._row(ROW_TRON_MAINNET_USDT_TRC20)
        self.assertTrue(row["balanceRouteReady"])
        self.assertEqual(row["lastBalanceReason"], "ready")

    def test_monero_reports_xmr_scanner_client_required_when_enabled(self):
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import ROW_MONERO_MAINNET_XMR
        row = self._row(ROW_MONERO_MAINNET_XMR)
        self.assertTrue(row["featureEnabled"])
        self.assertFalse(row["balanceRouteReady"])
        self.assertEqual(
            row["lastBalanceReason"], "xmr_scanner_client_required",
        )
        self.assertEqual(
            row["xmrBalanceReason"], "xmr_scanner_client_required",
        )
        self.assertFalse(row["xmrClientScannerSupported"])
        self.assertFalse(row["xmrBackendScannerEnabled"])

    def test_monero_reports_feature_disabled_when_flag_off(self):
        from crypto_wallet_diagnosis import ROW_MONERO_MAINNET_XMR
        row = self._row(ROW_MONERO_MAINNET_XMR)
        self.assertFalse(row["featureEnabled"])
        self.assertEqual(row["lastBalanceReason"], "feature_disabled")


class DiagnosisFieldNamesReferenceRealEnvVars(unittest.TestCase):


    def test_env_var_names_reference_the_correct_process_env_keys(self):
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        env = build_diagnosis_envelope()
        rowsById = {r["rowId"]: r for r in env["assets"]}
        self.assertEqual(
            rowsById["ethereum_mainnet_eth"]["rpcEnvVar"],
            "ETHEREUM_MAINNET_RPC_URL",
        )
        self.assertEqual(
            rowsById["ethereum_mainnet_usdt_erc20"]["tokenContractEnvVar"],
            "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
        )
        self.assertEqual(
            rowsById["ethereum_mainnet_usdc_erc20"]["tokenContractEnvVar"],
            "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
        )
        self.assertEqual(
            rowsById["solana_mainnet_sol"]["rpcEnvVar"], "SOLANA_RPC_URL",
        )
        self.assertEqual(
            rowsById["tron_mainnet_usdt_trc20"]["rpcEnvVar"],
            "TRON_API_BASE_URL",
        )
        self.assertEqual(
            rowsById["tron_mainnet_usdt_trc20"]["tokenContractEnvVar"],
            "TRON_USDT_CONTRACT_ADDRESS",
        )


class BalanceReasonBackendGuaranteesTests(unittest.TestCase):


    def test_solana_balance_returns_no_wallet_yet_when_missing(self):
        from vault_config import solana_enabled, solana_rpc_url
        snap = _wipe_env(
            "VAULTAI_CRYPTO_SOLANA_ENABLED",
            "SOLANA_RPC_URL",
        )
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://sol-rpc.example"
        try:
            import vault_config
            vault_config.reset_for_tests()
            self.assertTrue(solana_enabled())
            self.assertEqual(
                solana_rpc_url(), "https://sol-rpc.example",
            )
            from routes.crypto_wallet_routes import _solana_balance
            principal = {"vault_id": "test-vault"}
            from unittest import mock
            with mock.patch(
                "routes.crypto_wallet_routes."
                "_load_wallet_account_record_network",
                return_value=None,
            ):
                out = _solana_balance("SOL", None, principal)
            self.assertEqual(out["reason"], "no_wallet_yet")
            self.assertEqual(out["balanceStatus"], "unavailable")
            self.assertIsNone(out["availableAmount"])
        finally:
            _restore_env(snap)
            import vault_config
            vault_config.reset_for_tests()

    def test_tron_balance_returns_rpc_not_configured_when_missing(self):
        snap = _wipe_env(
            "VAULTAI_CRYPTO_TRON_ENABLED", "TRON_API_BASE_URL",
        )
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        try:
            import vault_config
            vault_config.reset_for_tests()
            from routes.crypto_wallet_routes import _tron_balance
            from unittest import mock
            fake_addr = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
            with mock.patch(
                "routes.crypto_wallet_routes."
                "_load_wallet_account_record_network",
                return_value={"publicAddress": fake_addr},
            ):
                out = _tron_balance(
                    "USDT_TRC20", None, {"vault_id": "v"},
                )




            self.assertEqual(out["reason"], "tron_api_not_configured")
            self.assertEqual(out["balanceStatus"], "unavailable")
            self.assertIsNone(out["availableAmount"])
        finally:
            _restore_env(snap)
            import vault_config
            vault_config.reset_for_tests()

    def test_tron_balance_returns_token_contract_not_configured(self):
        snap = _wipe_env(
            "VAULTAI_CRYPTO_TRON_ENABLED", "TRON_API_BASE_URL",
            "TRON_USDT_CONTRACT_ADDRESS",
        )
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://tron-api.example"
        try:
            import vault_config
            vault_config.reset_for_tests()
            from routes.crypto_wallet_routes import _tron_balance
            from unittest import mock
            fake_addr = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
            with mock.patch(
                "routes.crypto_wallet_routes."
                "_load_wallet_account_record_network",
                return_value={"publicAddress": fake_addr},
            ):
                out = _tron_balance(
                    "USDT_TRC20", None, {"vault_id": "v"},
                )
            self.assertEqual(
                out["reason"], "tron_contract_not_configured",
            )
        finally:
            _restore_env(snap)
            import vault_config
            vault_config.reset_for_tests()


class FeaturesSecretSafetyTests(unittest.TestCase):


    def test_features_envelope_never_leaks_configured_env_values(self):
        snap = _wipe_env(*_RUNTIME_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://sol-rpc.example"
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://tron-api.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = (
            "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
        )
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = (
            "https://eth-rpc.example"
        )
        os.environ["ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS"] = (
            "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        )
        try:
            import vault_config
            vault_config.reset_for_tests()
            from crypto_wallet_health import build_features_envelope
            body = build_features_envelope()
            blob = json.dumps(body)
            self.assertNotIn("sol-rpc.example", blob)
            self.assertNotIn("tron-api.example", blob)
            self.assertNotIn("eth-rpc.example", blob)
            self.assertNotIn("TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj", blob)
            self.assertNotIn(
                "0xdAC17F958D2ee523a2206206994597C13D831ec7", blob,
            )
        finally:
            _restore_env(snap)
            import vault_config
            vault_config.reset_for_tests()


class DiagnosisSourceGuardTests(unittest.TestCase):


    def test_diagnosis_source_never_prints_env_values(self):
        src = (
            _BACKEND_ROOT / "crypto_wallet_diagnosis.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "os.environ.get",
            'os.getenv("ETHEREUM_MAINNET_RPC_URL"',
            'os.getenv("SOLANA_RPC_URL"',
        ):
            self.assertNotIn(forbidden, src)


class DiagnosisRouteWiredTests(unittest.TestCase):


    def test_diagnosis_route_registered(self):
        from main import app
        paths = {r.path for r in app.routes}
        self.assertIn("/crypto/wallet/diagnosis", paths)


if __name__ == "__main__":
    unittest.main()
