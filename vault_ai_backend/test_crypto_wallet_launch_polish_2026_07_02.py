


from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path


_BACKEND_ROOT = Path(__file__).parent
_REPO_ROOT = _BACKEND_ROOT.parent


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


ALL_CRYPTO_ENV_KEYS = (
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


CLOSED_SET_BALANCE_REASONS = frozenset({
    "no_wallet_yet",
    "invalid_address",
    "rpc_not_configured",
    "rpc_unreachable",
    "rpc_error",
    "token_contract_not_configured",
    "invalid_contract_address",
    "contract_read_failed",
    "asset_not_enabled_on_mainnet",
    "feature_disabled",
    "xmr_scanner_not_enabled",
    "xmr_scanner_client_required",
    "ready",
    "network_error",
    "server_error",
})


CLOSED_SET_DIAGNOSIS_REASONS = frozenset({
    "feature_disabled",
    "rpc_not_configured",
    "token_contract_not_configured",
    "xmr_scanner_not_enabled",
    "xmr_scanner_client_required",
    "ready",
})


class ReadinessDiagnosisIsSecretSafeTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(*ALL_CRYPTO_ENV_KEYS)
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def _seed_realistic_env(self):
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = (
            "https://mainnet-rpc.example/xxx-secret-yyy"
        )
        os.environ["ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS"] = (
            "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        )
        os.environ["ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS"] = (
            "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        )
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED"] = (
            "true"
        )
        os.environ["SOLANA_RPC_URL"] = "https://sol-rpc.example/secret"
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://tron-api.example"
        os.environ["TRON_API_KEY"] = "TRON-SECRET-KEY"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = (
            "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
        )
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()

    def test_diagnosis_envelope_never_leaks_env_values(self):
        self._seed_realistic_env()
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        blob = json.dumps(build_diagnosis_envelope())
        for banned in (
            "mainnet-rpc.example",
            "xxx-secret-yyy",
            "sol-rpc.example",
            "/secret",
            "tron-api.example",
            "TRON-SECRET-KEY",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj",
        ):
            self.assertNotIn(
                banned, blob,
                f'diagnosis leaked {banned!r}',
            )

    def test_features_envelope_never_leaks_env_values(self):
        self._seed_realistic_env()
        from crypto_wallet_health import build_features_envelope
        blob = json.dumps(build_features_envelope())
        for banned in (
            "mainnet-rpc.example",
            "sol-rpc.example",
            "tron-api.example",
            "TRON-SECRET-KEY",
            "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj",
        ):
            self.assertNotIn(
                banned, blob,
                f'features leaked {banned!r}',
            )

    def test_no_wallet_address_or_tx_hash_in_diagnosis(self):
        self._seed_realistic_env()
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        blob = json.dumps(build_diagnosis_envelope())
        self.assertNotIn("publicAddress", blob)
        self.assertNotIn("privateSpendKey", blob)
        self.assertNotIn("privateViewKey", blob)
        self.assertNotIn("encryptedWalletSecret", blob)
        self.assertNotIn("txHash", blob)
        self.assertNotIn("mnemonic", blob)
        self.assertNotIn("walletPassword", blob)

    def test_no_wallet_address_or_tx_hash_in_features(self):
        self._seed_realistic_env()
        from crypto_wallet_health import build_features_envelope
        blob = json.dumps(build_features_envelope())
        for banned in ("publicAddress", "privateSpendKey",
                       "privateViewKey", "encryptedWalletSecret",
                       "txHash", "mnemonic", "walletPassword"):
            self.assertNotIn(banned, blob)


class DiagnosisReasonsAreClosedSetTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(*ALL_CRYPTO_ENV_KEYS)
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_diagnosis_reason_is_always_in_closed_set(self):
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        env = build_diagnosis_envelope()
        for row in env["assets"]:
            reason = row["lastBalanceReason"]
            self.assertIn(
                reason, CLOSED_SET_DIAGNOSIS_REASONS,
                f'row {row["rowId"]} produced out-of-set reason {reason!r}',
            )

    def test_diagnosis_reason_stays_in_closed_set_when_partial_config(self):

        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        env = build_diagnosis_envelope()
        for row in env["assets"]:
            reason = row["lastBalanceReason"]
            self.assertIn(
                reason, CLOSED_SET_DIAGNOSIS_REASONS,
                f'row {row["rowId"]} produced out-of-set reason {reason!r}',
            )


class HealthFeaturesDiagnosisSchemasStableTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(*ALL_CRYPTO_ENV_KEYS)
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_features_schema_stable(self):
        from crypto_wallet_health import build_features_envelope
        body = build_features_envelope()
        self.assertEqual(body["schema"], "crypto_wallet_features_v1")

    def test_diagnosis_schema_stable(self):
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        body = build_diagnosis_envelope()
        self.assertEqual(body["schema"], "crypto_wallet_diagnosis_v1")

    def test_health_schema_stable(self):
        from crypto_wallet_health import build_health_envelope
        body = build_health_envelope()
        self.assertEqual(body["schema"], "crypto_wallet_health_v1")

    def test_features_envelope_lists_all_expected_scanner_flags(self):
        from crypto_wallet_health import build_features_envelope
        body = build_features_envelope()
        for expected in (
            "walletEngineEnabled",
            "xmrEnabled", "xmrReceiveEnabled", "xmrBalanceEnabled",
            "xmrSendEnabled", "xmrActivityConnected", "xmrScannerMode",
            "xmrClientScannerSupported", "xmrBackendScannerEnabled",
            "solanaEnabled", "tronEnabled",
            "mainnetReceiveEnabled", "mainnetErc20ReceiveEnabled",
            "mainnetSendEnabled", "mainnetSendPaused",
        ):
            self.assertIn(expected, body,
                          f'features missing key {expected!r}')

    def test_diagnosis_envelope_has_all_asset_rows(self):
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        env = build_diagnosis_envelope()
        expected_rows = {
            "ethereum_mainnet_eth",
            "ethereum_mainnet_usdt_erc20",
            "ethereum_mainnet_usdc_erc20",
            "solana_mainnet_sol",
            "tron_mainnet_usdt_trc20",
            "monero_mainnet_xmr",
        }
        observed_rows = {row["rowId"] for row in env["assets"]}
        self.assertEqual(observed_rows, expected_rows)


class DocsExistAndReferenceTheCorrectEnvVarsTests(unittest.TestCase):


    def test_launch_checklist_doc_present(self):
        p = _REPO_ROOT / 'docs' / 'crypto_wallet_launch_checklist.md'
        self.assertTrue(
            p.exists(),
            f'docs/crypto_wallet_launch_checklist.md missing at {p}',
        )
        text = p.read_text(encoding='utf-8')
        for expected_env_var in (
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            "ETHEREUM_MAINNET_RPC_URL",
            "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
            "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
            "SOLANA_RPC_URL",
            "TRON_API_BASE_URL",
            "TRON_USDT_CONTRACT_ADDRESS",
            "VAULTAI_CRYPTO_XMR_ENABLED",
            "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
            "STRIPE_WEBHOOK_SECRET",
            "VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN",
        ):
            self.assertIn(
                expected_env_var, text,
                f'launch checklist missing env {expected_env_var}',
            )

    def test_launch_checklist_references_all_six_asset_rows(self):
        p = _REPO_ROOT / 'docs' / 'crypto_wallet_launch_checklist.md'
        text = p.read_text(encoding='utf-8')
        for asset in ("ETH", "USDT (ERC20)", "USDC (ERC20)",
                      "SOL", "USDT (TRC20)", "XMR"):
            self.assertIn(
                asset, text,
                f'launch checklist missing asset row {asset}',
            )

    def test_runtime_setup_doc_still_present(self):
        p = _REPO_ROOT / 'docs' / 'crypto_wallet_runtime_setup.md'
        self.assertTrue(p.exists())

    def test_no_launch_doc_leaks_a_pre_seeded_secret(self):

        text = (
            (_REPO_ROOT / 'docs' / 'crypto_wallet_launch_checklist.md')
            .read_text(encoding='utf-8')
        )
        secrets = [
            "sk_live_",
            "whsec_",
        ]
        for s in secrets:
            m = re.search(re.escape(s) + r"[A-Za-z0-9]{6,}", text)
            self.assertIsNone(
                m,
                f'launch checklist leaks secret pattern: {s}<...>',
            )


class RoutesStillRegisteredTests(unittest.TestCase):

    def test_features_health_diagnosis_all_registered(self):
        from main import app
        paths = {r.path for r in app.routes}
        for path in (
            "/crypto/wallet/features",
            "/crypto/wallet/health",
            "/crypto/wallet/diagnosis",
        ):
            self.assertIn(path, paths, f'missing route {path}')


class XmrRoutesStillHonestTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(*ALL_CRYPTO_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_xmr_balance_still_scanner_not_enabled(self):
        from routes.crypto_wallet_routes import _xmr_balance
        out = _xmr_balance('XMR', {'vault_id': 'v'})
        self.assertEqual(out['reason'], 'xmr_scanner_not_enabled')

    def test_xmr_transactions_still_scanner_not_enabled(self):
        from routes.crypto_wallet_routes import _xmr_transactions
        out = _xmr_transactions('XMR', 10, {'vault_id': 'v'})
        self.assertEqual(out['reason'], 'xmr_scanner_not_enabled')

    def test_xmr_send_envelope_still_disabled(self):
        from routes.crypto_wallet_routes import _xmr_send_not_enabled_envelope
        env = _xmr_send_not_enabled_envelope('XMR')
        self.assertEqual(env['wallet_engine'], 'xmr_send_not_enabled')


if __name__ == '__main__':
    unittest.main()
