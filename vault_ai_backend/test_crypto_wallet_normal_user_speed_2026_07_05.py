


from __future__ import annotations

import json
import os
import time
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


_CRYPTO_ENV_KEYS = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_DEFAULT_NETWORK",
    "VAULTAI_CRYPTO_XMR_ENABLED",
    "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
    "VAULTAI_CRYPTO_SOLANA_ENABLED",
    "VAULTAI_CRYPTO_TRON_ENABLED",
    "SOLANA_RPC_URL",
    "TRON_API_BASE_URL",
    "ETHEREUM_MAINNET_RPC_URL",
)


class NormalUserFeaturesEndpointIsFastAndSecretSafeTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(*_CRYPTO_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = (
            "https://mainnet-rpc.example/secret"
        )
        os.environ["SOLANA_RPC_URL"] = (
            "https://sol-rpc.example/secret"
        )
        os.environ["TRON_API_BASE_URL"] = "https://tron.example"
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_features_envelope_builds_in_under_100ms(self):

        from crypto_wallet_health import build_features_envelope
        started = time.perf_counter()
        env = build_features_envelope()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertLess(
            elapsed_ms, 100,
            f"features envelope must be fast; took {elapsed_ms:.1f}ms",
        )
        self.assertEqual(env["schema"], "crypto_wallet_features_v1")

    def test_features_envelope_makes_no_http_request(self):


        from unittest import mock
        with mock.patch("httpx.Client") as httpx_client_mock, \
             mock.patch("httpx.AsyncClient") as httpx_async_mock:
            from crypto_wallet_health import build_features_envelope
            build_features_envelope()
            self.assertEqual(
                httpx_client_mock.call_count, 0,
                "features envelope must not open any HTTP clients",
            )
            self.assertEqual(httpx_async_mock.call_count, 0)

    def test_features_envelope_never_leaks_rpc_urls_or_api_keys(self):
        from crypto_wallet_health import build_features_envelope
        blob = json.dumps(build_features_envelope())
        for banned in (
            "mainnet-rpc.example",
            "sol-rpc.example",
            "tron.example",
            "/secret",
        ):
            self.assertNotIn(banned, blob,
                             f"features envelope leaked {banned!r}")


class HealthAndDiagnosisRemainAdminOnlyTests(unittest.TestCase):


    def test_health_route_registered(self):
        from main import app
        paths = {r.path for r in app.routes}
        self.assertIn("/crypto/wallet/health", paths)

    def test_diagnosis_route_registered(self):
        from main import app
        paths = {r.path for r in app.routes}
        self.assertIn("/crypto/wallet/diagnosis", paths)

    def test_features_route_registered(self):
        from main import app
        paths = {r.path for r in app.routes}
        self.assertIn("/crypto/wallet/features", paths)

    def test_features_route_is_separate_from_health_and_diagnosis(self):

        from main import app
        features = None
        health = None
        diagnosis = None
        for r in app.routes:
            if r.path == "/crypto/wallet/features":
                features = r
            if r.path == "/crypto/wallet/health":
                health = r
            if r.path == "/crypto/wallet/diagnosis":
                diagnosis = r
        self.assertIsNotNone(features)
        self.assertIsNotNone(health)
        self.assertIsNotNone(diagnosis)


class ClosedSetBalanceReasonsRemainStableTests(unittest.TestCase):


    def setUp(self) -> None:
        self._snap = _wipe_env(*_CRYPTO_ENV_KEYS)
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_diagnosis_reasons_stay_in_closed_set(self):
        allowed = {
            "feature_disabled",
            "rpc_not_configured",
            "token_contract_not_configured",
            "xmr_scanner_client_required",
            "xmr_scanner_not_enabled",
            "ready",
        }
        from crypto_wallet_diagnosis import build_diagnosis_envelope
        env = build_diagnosis_envelope()
        for row in env["assets"]:
            reason = row["lastBalanceReason"]
            self.assertIn(
                reason, allowed,
                f"row {row['rowId']} produced out-of-set reason {reason!r}",
            )


if __name__ == "__main__":
    unittest.main()
