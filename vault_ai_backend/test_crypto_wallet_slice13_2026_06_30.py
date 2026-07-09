

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import vault_config


_BACKEND_ROOT = Path(__file__).parent


_RELEVANT_ENV: tuple[str, ...] = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED",
    "VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN",
    "VAULTAI_DEBUG_ENDPOINTS_ENABLED",
    "VAULTAI_ENV",
    "ETHEREUM_SEPOLIA_RPC_URL",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER",
    "ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY",
    "ETHEREUM_SEPOLIA_TX_INDEXER_BASE_URL",
    "ETHEREUM_MAINNET_TX_INDEXER_PROVIDER",
    "ETHEREUM_MAINNET_TX_INDEXER_API_KEY",
    "ETHEREUM_MAINNET_TX_INDEXER_BASE_URL",
    "ETH_SEPOLIA_USDT_CONTRACT_ADDRESS",
    "ETH_SEPOLIA_USDC_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
)


def _set_env(**kvs: str) -> None:
    for k, v in kvs.items():
        if v is None:
            if k in os.environ:
                del os.environ[k]
        else:
            os.environ[k] = v
    vault_config.reset_for_tests()


def _clear_env(*keys: str) -> None:
    for k in keys:
        if k in os.environ:
            del os.environ[k]
    vault_config.reset_for_tests()


def _clear_all_env() -> None:
    _clear_env(*_RELEVANT_ENV)


def _make_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.crypto_wallet_routes import (
        router, verify_trusted_device,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": "test-vault-slice13",
    }
    return TestClient(app)


_USDT_MAINNET = "0x" + "11" * 20
_USDC_MAINNET = "0x" + "22" * 20


class FeaturesRouteTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_all_env()
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        vault_config.reset_for_tests()
        self._client = _make_client()

    def tearDown(self) -> None:
        _clear_all_env()

    def test_P1_features_envelope_closed_set(self) -> None:
        resp = self._client.get("/crypto/wallet/features")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["schema"], "crypto_wallet_features_v1")
        self.assertEqual(body["status"], "ok")
                        
        for key in (
            "walletEngineEnabled",
            "sepoliaReceiveEnabled",
            "sepoliaSendEnabled",
            "mainnetReceiveEnabled",
            "mainnetErc20ReceiveEnabled",
            "mainnetSendEnabled",
            "mainnetSendPaused",
            "supportedNetworks",
            "supportedAssetsByNetwork",
        ):
            self.assertIn(key, body)

    def test_P2_features_envelope_no_secrets(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://sepolia.invalid/secret-key",
            ETHEREUM_MAINNET_RPC_URL="https://mainnet.invalid/secret-key",
            ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY="SUPER-SECRET-KEY",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=_USDT_MAINNET,
        )
        resp = self._client.get("/crypto/wallet/features")
        body_str = str(resp.json())
        self.assertNotIn("sepolia.invalid", body_str)
        self.assertNotIn("mainnet.invalid", body_str)
        self.assertNotIn("SUPER-SECRET-KEY", body_str)
        self.assertNotIn(_USDT_MAINNET, body_str)

    def test_P18_features_reflect_live_state(self) -> None:
                                               
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="true",
        )
        body = self._client.get("/crypto/wallet/features").json()
        self.assertTrue(body["mainnetReceiveEnabled"])
        self.assertTrue(body["mainnetSendEnabled"])
        self.assertTrue(body["mainnetSendPaused"])

    def test_features_assets_per_network(self) -> None:
        body = self._client.get("/crypto/wallet/features").json()
        self.assertEqual(
            body["supportedNetworks"],
            ["ethereum_sepolia", "ethereum_mainnet"],
        )
                                                          
        for net in body["supportedNetworks"]:
            self.assertEqual(
                body["supportedAssetsByNetwork"][net],
                ["ETH", "USDT_ERC20", "USDC_ERC20"],
            )


class HealthRouteAuthTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_all_env()
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        vault_config.reset_for_tests()
        self._client = _make_client()

    def tearDown(self) -> None:
        _clear_all_env()

    def test_P3_admin_token_required(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN="super-admin-token-001",
        )
                          
        resp = self._client.get("/crypto/wallet/health")
        self.assertEqual(resp.status_code, 403)
                            
        resp = self._client.get(
            "/crypto/wallet/health",
            headers={"X-Crypto-Health-Admin-Token": "nope"},
        )
        self.assertEqual(resp.status_code, 403)
                              
        resp = self._client.get(
            "/crypto/wallet/health",
            headers={
                "X-Crypto-Health-Admin-Token": "super-admin-token-001",
            },
        )
        self.assertEqual(resp.status_code, 200)

    def test_P4_no_token_in_prod_refuses(self) -> None:
                                                                 
                                                                
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_DEBUG_ENDPOINTS_ENABLED="false",
        )
        resp = self._client.get("/crypto/wallet/health")
        self.assertEqual(resp.status_code, 403)

    def test_P4b_no_token_in_dev_is_ok(self) -> None:
                                                                  
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
        )
        resp = self._client.get("/crypto/wallet/health")
        self.assertEqual(resp.status_code, 200)


class HealthEnvelopeTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_all_env()
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        vault_config.reset_for_tests()
        self._client = _make_client()

    def tearDown(self) -> None:
        _clear_all_env()

    def _fetch(self) -> dict[str, Any]:
        return self._client.get("/crypto/wallet/health").json()

    def test_P5_missing_sepolia_rpc(self) -> None:
                                                                
                                  
        body = self._fetch()
        sep = next(n for n in body["networks"]
                   if n["id"] == "ethereum_sepolia")
        self.assertEqual(sep["status"], "not_ready")
        self.assertEqual(sep["reason"], "rpc_not_configured")
        self.assertFalse(sep["rpcConfigured"])
        self.assertFalse(sep["rpcReachable"])

    def test_P6_missing_mainnet_rpc(self) -> None:
        body = self._fetch()
        main = next(n for n in body["networks"]
                    if n["id"] == "ethereum_mainnet")
        self.assertEqual(main["status"], "not_ready")
        self.assertEqual(main["reason"], "rpc_not_configured")

    def test_P7_chain_id_mismatch_detected(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://invalid/sepolia",
        )
                                                                    
                                 
        import crypto_wallet_health
        with mock.patch.object(
            crypto_wallet_health, "_eth_chain_id",
            side_effect=lambda url: 1,
        ):
            body = self._fetch()
        sep = next(n for n in body["networks"]
                   if n["id"] == "ethereum_sepolia")
        self.assertEqual(sep["status"], "not_ready")
        self.assertEqual(sep["reason"], "chain_id_mismatch")
        self.assertEqual(sep["chainIdExpected"], 11155111)
        self.assertEqual(sep["chainIdObserved"], 1)

    def test_P8_sepolia_check_never_reads_mainnet_url(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        urls_seen: list[str] = []
        import crypto_wallet_health

        def _stub(url: str) -> int:
            urls_seen.append(url)
            if "sepolia" in url:
                return 11155111
            return 1

        with mock.patch.object(
            crypto_wallet_health, "_eth_chain_id",
            side_effect=_stub,
        ):
            self._fetch()
                                                                   
                                                                 
        sepolia_calls = [u for u in urls_seen if "sepolia" in u]
        mainnet_calls = [u for u in urls_seen if "mainnet" in u]
        self.assertGreaterEqual(len(sepolia_calls), 1)
        self.assertGreaterEqual(len(mainnet_calls), 1)
                                                                  
                                                                 
        for u in urls_seen:
            self.assertIn(u, [
                "https://example.invalid/sepolia",
                "https://example.invalid/mainnet",
            ])

    def test_P9_indexer_missing_is_degraded_not_not_ready(self) -> None:
                                                            
                                                                 
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://invalid/sepolia",
        )
        import crypto_wallet_health
        with mock.patch.object(
            crypto_wallet_health, "_eth_chain_id",
            side_effect=lambda url: 11155111,
        ):
            body = self._fetch()
        sep = next(n for n in body["networks"]
                   if n["id"] == "ethereum_sepolia")
        self.assertEqual(sep["status"], "degraded")
        self.assertEqual(
            sep["txIndexerConfigured"], False,
        )

    def test_P10_envelope_no_rpc_url_or_api_key_leak(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL=(
                "https://example.invalid/sepolia-secret-suffix"
            ),
            ETHEREUM_MAINNET_RPC_URL=(
                "https://example.invalid/mainnet-secret-suffix"
            ),
            ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY="VERY-SECRET-API-KEY",
            ETHEREUM_MAINNET_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_MAINNET_TX_INDEXER_API_KEY="ANOTHER-SECRET-KEY",
        )
        body_str = str(self._fetch())
        self.assertNotIn("sepolia-secret-suffix", body_str)
        self.assertNotIn("mainnet-secret-suffix", body_str)
        self.assertNotIn("VERY-SECRET-API-KEY", body_str)
        self.assertNotIn("ANOTHER-SECRET-KEY", body_str)

    def test_P11_token_contract_missing(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://invalid/mainnet",
        )
        import crypto_wallet_health
        with mock.patch.object(
            crypto_wallet_health, "_eth_chain_id",
            side_effect=lambda url: 1,
        ):
            body = self._fetch()
        main = next(n for n in body["networks"]
                    if n["id"] == "ethereum_mainnet")
        usdt = next(t for t in main["tokens"] if t["asset"] == "USDT_ERC20")
        self.assertFalse(usdt["configured"])
        self.assertEqual(usdt["reason"], "token_contract_not_configured")
                                                            
                                       
        self.assertEqual(main["status"], "degraded")

    def test_P12_token_contract_malformed(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://invalid/mainnet",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS="not-a-real-address",
        )
        import crypto_wallet_health
        with mock.patch.object(
            crypto_wallet_health, "_eth_chain_id",
            side_effect=lambda url: 1,
        ):
            body = self._fetch()
        main = next(n for n in body["networks"]
                    if n["id"] == "ethereum_mainnet")
        usdt = next(t for t in main["tokens"] if t["asset"] == "USDT_ERC20")
        self.assertFalse(usdt["configured"])
        self.assertEqual(usdt["reason"], "invalid_contract_address")

    def test_P13_token_contract_probe_uses_eth_call_only(self) -> None:
                                                                       
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://invalid/mainnet",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=_USDT_MAINNET,
            ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS=_USDC_MAINNET,
        )
        captured: list[str] = []

        def _stub_chain_id(url):
            return 1

        def _stub_decimals(url, contract):
            captured.append(contract)
            return 6

        import crypto_wallet_health
        with mock.patch.object(
            crypto_wallet_health, "_eth_chain_id",
            side_effect=_stub_chain_id,
        ), mock.patch.object(
            crypto_wallet_health, "_erc20_decimals_call",
            side_effect=_stub_decimals,
        ):
            self._fetch()
        self.assertIn(_USDT_MAINNET, captured)
        self.assertIn(_USDC_MAINNET, captured)

    def test_P14_pause_flag_reflected(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="true",
        )
        body = self._fetch()
        self.assertTrue(body["features"]["mainnetSendPaused"])
        main = next(n for n in body["networks"]
                    if n["id"] == "ethereum_mainnet")
        self.assertTrue(main["send"]["mainnetSendPaused"])

    def test_P15_rate_limit_settings_in_envelope(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT="7",
            VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS="30",
        )
        body = self._fetch()
        self.assertEqual(body["features"]["broadcastRateLimit"], 7)
        self.assertEqual(body["features"]["broadcastRateWindowSecs"], 30)


class HealthLoggingTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_all_env()
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        vault_config.reset_for_tests()
        self._client = _make_client()

    def tearDown(self) -> None:
        _clear_all_env()

    def test_P16_logs_redact_url_and_api_key(self) -> None:
        import io
        import logging
        from logging import getLogger
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/secret",
            ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY="LEAK-ME-API-KEY",
            ETHEREUM_SEPOLIA_TX_INDEXER_BASE_URL="https://invalid/etherscan",
        )
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        logger = getLogger("crypto_wallet_health")
        prev = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            import crypto_wallet_health
            with mock.patch.object(
                crypto_wallet_health, "_eth_chain_id",
                side_effect=lambda url: 11155111,
            ), mock.patch.object(
                crypto_wallet_health, "_redacted_indexer_probe",
                                                               
                                                               
                side_effect=lambda base_url, *, provider: (
                    crypto_wallet_health.REASON_INDEXER_UNREACHABLE
                ),
            ):
                self._client.get("/crypto/wallet/health")
            logs = stream.getvalue()
            self.assertNotIn("https://example.invalid/secret", logs)
            self.assertNotIn("LEAK-ME-API-KEY", logs)
            self.assertNotIn("https://invalid/etherscan", logs)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prev)


class SourceGuardTests(unittest.TestCase):

    def test_P17_no_signing_imports_in_health(self) -> None:
        src = (_BACKEND_ROOT / "crypto_wallet_health.py"
            ).read_text(encoding="utf-8")
        scrubbed = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
        scrubbed = re.sub(
            r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
        )
        for banned in (
            "eth_account", "from eth_account",
            "import eth_keys", "from eth_keys",
            "import web3", "from web3",
            "ethereum_sepolia_proxy", "ethereum_wallet",
            "ethereum_transaction",
        ):
            self.assertNotIn(
                banned, scrubbed,
                msg=f"crypto_wallet_health imports {banned}",
            )

    def test_P17b_no_state_changing_rpc_method_names(self) -> None:
        src = (_BACKEND_ROOT / "crypto_wallet_health.py"
            ).read_text(encoding="utf-8")
                                                                    
        scrubbed = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
        scrubbed = re.sub(
            r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
        )
                                                                     
                                         
        for banned in (
            "eth_sendTransaction", "eth_sendRawTransaction",
            "eth_sign", "personal_sign",
            "eth_signTransaction", "personal_signTransaction",
            "personal_sendTransaction",
            "debug_traceTransaction", "debug_traceCall",
        ):
            self.assertNotIn(
                banned, scrubbed,
                msg=f"crypto_wallet_health code references {banned}",
            )

    def test_P17c_health_module_allows_read_only_methods(self) -> None:
        from crypto_wallet_health import _ALLOWED_HEALTH_METHODS
        self.assertEqual(
            _ALLOWED_HEALTH_METHODS,
            frozenset({"eth_chainId", "eth_blockNumber", "eth_call"}),
        )


if __name__ == "__main__":
    unittest.main()
