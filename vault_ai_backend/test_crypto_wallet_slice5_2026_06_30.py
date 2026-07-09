

from __future__ import annotations

import io
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


_BACKEND_ROOT = Path(__file__).resolve().parent


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


class NetworkRegistryTests(unittest.TestCase):

    def setUp(self) -> None:
                                                               
              
        self._snap = _wipe_env(
            "ETHEREUM_SEPOLIA_RPC_URL",
            "ETHEREUM_MAINNET_RPC_URL",
            "ETHEREUM_SEPOLIA_USDT_CONTRACT_ADDRESS",
            "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
            "ETHEREUM_SEPOLIA_USDC_CONTRACT_ADDRESS",
            "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
            "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
            "VAULTAI_CRYPTO_ETH_SEPOLIA_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_SEPOLIA_SEND_ENABLED",
        )

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_N1_closed_set_two_networks(self) -> None:
        from evm_networks import (
            ALL_EVM_NETWORKS,
            NETWORK_ETHEREUM_SEPOLIA, NETWORK_ETHEREUM_MAINNET,
        )
        self.assertEqual(
            tuple(ALL_EVM_NETWORKS),
            (NETWORK_ETHEREUM_SEPOLIA, NETWORK_ETHEREUM_MAINNET),
        )
                                                                  
                               
        self.assertEqual(NETWORK_ETHEREUM_SEPOLIA, "ethereum_sepolia")
        self.assertEqual(NETWORK_ETHEREUM_MAINNET, "ethereum_mainnet")

    def test_N2_sepolia_metadata(self) -> None:
        from evm_networks import network_config
        cfg = network_config("ethereum_sepolia")
        self.assertEqual(cfg.chain_id, 11155111)
        self.assertTrue(cfg.is_testnet)
        self.assertEqual(cfg.native_asset, "ETH")
        self.assertEqual(cfg.native_unit, "ETH")
        self.assertEqual(cfg.rpc_env_var, "ETHEREUM_SEPOLIA_RPC_URL")
        self.assertEqual(
            cfg.token_contract_env_prefix, "ETHEREUM_SEPOLIA",
        )

    def test_N2_mainnet_metadata(self) -> None:
        from evm_networks import network_config
        cfg = network_config("ethereum_mainnet")
        self.assertEqual(cfg.chain_id, 1)
        self.assertFalse(cfg.is_testnet)
        self.assertEqual(cfg.native_asset, "ETH")
        self.assertEqual(cfg.rpc_env_var, "ETHEREUM_MAINNET_RPC_URL")
        self.assertEqual(
            cfg.token_contract_env_prefix, "ETHEREUM_MAINNET",
        )

    def test_N3_default_enabled_states(self) -> None:
        from evm_networks import is_receive_enabled, is_send_enabled
                                                       
        self.assertTrue(is_receive_enabled("ethereum_sepolia"))
        self.assertTrue(is_send_enabled("ethereum_sepolia"))
                                                          
                                                                
        self.assertFalse(is_receive_enabled("ethereum_mainnet"))
        self.assertFalse(is_send_enabled("ethereum_mainnet"))

    def test_N3_env_overrides(self) -> None:
        from evm_networks import is_send_enabled
        with patch.dict(
            os.environ,
            {"VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED": "true"},
            clear=False,
        ):
            self.assertTrue(is_send_enabled("ethereum_mainnet"))
                                                                
        with patch.dict(
            os.environ,
            {"VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED": "no"},
            clear=False,
        ):
            self.assertFalse(is_send_enabled("ethereum_mainnet"))

    def test_N4_rpc_url_per_network(self) -> None:
        from evm_networks import rpc_url_for
        self.assertEqual(rpc_url_for("ethereum_sepolia"), "")
        self.assertEqual(rpc_url_for("ethereum_mainnet"), "")
        with patch.dict(
            os.environ,
            {"ETHEREUM_SEPOLIA_RPC_URL": "https://sepolia.example.com"},
            clear=False,
        ):
            self.assertEqual(
                rpc_url_for("ethereum_sepolia"),
                "https://sepolia.example.com",
            )
                                                                       
            self.assertEqual(rpc_url_for("ethereum_mainnet"), "")

    def test_N5_token_contract_per_network(self) -> None:
        from evm_networks import token_contract_for
        with patch.dict(
            os.environ,
            {
                "ETHEREUM_SEPOLIA_USDT_CONTRACT_ADDRESS": "0xsep_usdt",
                "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS": "0xmain_usdt",
            },
            clear=False,
        ):
            self.assertEqual(
                token_contract_for("ethereum_sepolia", "USDT_ERC20"),
                "0xsep_usdt",
            )
            self.assertEqual(
                token_contract_for("ethereum_mainnet", "USDT_ERC20"),
                "0xmain_usdt",
            )
                                                                
            self.assertNotEqual(
                token_contract_for("ethereum_sepolia", "USDT_ERC20"),
                token_contract_for("ethereum_mainnet", "USDT_ERC20"),
            )

    def test_unknown_network_returns_safe_empty(self) -> None:
        from evm_networks import (
            is_known_network, rpc_url_for, token_contract_for,
            is_send_enabled, is_receive_enabled,
        )
        for bad in ("polkadot", "", None, "ETHEREUM_SEPOLIA", "12345"):
            self.assertFalse(is_known_network(bad))
                                                                      
            self.assertEqual(rpc_url_for(bad or ""), "")
            self.assertEqual(token_contract_for(bad or "", "USDT_ERC20"), "")
            self.assertFalse(is_send_enabled(bad or ""))
            self.assertFalse(is_receive_enabled(bad or ""))


class _AuthedRouteCase(unittest.TestCase):

    def setUp(self) -> None:
        self._env_snap = _wipe_env(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            "ETHEREUM_SEPOLIA_RPC_URL",
            "ETHEREUM_MAINNET_RPC_URL",
            "ETHEREUM_SEPOLIA_USDT_CONTRACT_ADDRESS",
            "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
            "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
        )
        import vault_config
        vault_config.reset_for_tests()
        from main import app
        from device_gate import verify_trusted_device
        self._app = app
        self._dep_key = verify_trusted_device
        self._prior = app.dependency_overrides.get(verify_trusted_device)
        app.dependency_overrides[verify_trusted_device] = lambda: {
            "vault_id": "test-vault-uuid", "account_id": "test-account",
        }

    def tearDown(self) -> None:
        from device_gate import verify_trusted_device
        if self._prior is None:
            self._app.dependency_overrides.pop(verify_trusted_device, None)
        else:
            self._app.dependency_overrides[verify_trusted_device] = (
                self._prior
            )
        _restore_env(self._env_snap)
        import vault_config
        vault_config.reset_for_tests()

    def _client(self) -> TestClient:
        return TestClient(self._app)

    def _enable_engine(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()


class UnknownNetworkRouteTests(_AuthedRouteCase):

    def test_unknown_network_balance_refused(self) -> None:
        self._enable_engine()
        c = self._client()
        for bad in ("polkadot", "ETHEREUM_SEPOLIA", "garbage-net"):
            resp = c.get(
                f"/crypto/wallet/network/{bad}/ETH/balance"
                "?address=0x" + "1" * 40,
            )
            body = resp.json()
            self.assertEqual(
                body["wallet_engine"], "unknown_network",
                f"network={bad!r}",
            )

    def test_unknown_network_send_draft_refused(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/network/polkadot/ETH/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "0.01",
            },
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "unknown_network")


class MainnetSendDisabledTests(_AuthedRouteCase):

    def test_N7_mainnet_send_draft_refused_by_default(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "0.01",
            },
        )
        body = resp.json()
        self.assertEqual(
            body["wallet_engine"], "mainnet_send_disabled",
        )
                                                                   
        self.assertNotIn("nonce", body)
        self.assertNotIn("gasPrice", body)
        self.assertNotIn("chainId", body)
                                                            
        self.assertIn(
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
            body["message"],
        )

    def test_N8_mainnet_broadcast_refused_by_default(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": "0x" + "a" * 200},
        )
        body = resp.json()
        self.assertEqual(
            body["wallet_engine"], "mainnet_send_disabled",
        )
                                                  
        self.assertNotIn("txHash", body)


class MainnetReceiveDisabledTests(_AuthedRouteCase):

    def test_mainnet_receive_refused_by_default(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/receive",
        )
        body = resp.json()
        self.assertEqual(
            body["wallet_engine"], "network_not_enabled",
        )
                                              
        self.assertNotIn("publicAddress", body)

    def test_mainnet_balance_refused_by_default(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/balance"
            "?address=0x" + "1" * 40,
        )
        body = resp.json()
        self.assertEqual(
            body["wallet_engine"], "network_not_enabled",
        )
                                 
        self.assertNotIn("availableAmount", body)
        self.assertNotIn("balanceStatus", body)

    def test_mainnet_transactions_refused_by_default(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/transactions",
        )
        body = resp.json()
        self.assertEqual(
            body["wallet_engine"], "network_not_enabled",
        )
                                       
        self.assertEqual(body["transactions"], [])


class SepoliaNetworkDelegationTests(_AuthedRouteCase):

    def test_sepolia_balance_route_delegates(self) -> None:
                                                               
                                               
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        with patch(
            "ethereum_sepolia_proxy.eth_get_balance_wei",
            return_value=12_345_678_900_000_000,
        ):
            c = self._client()
            new_resp = c.get(
                "/crypto/wallet/network/ethereum_sepolia/ETH/balance"
                "?address=0x" + "1" * 40,
            )
            old_resp = c.get(
                "/crypto/wallet/ETH/balance?address=0x" + "1" * 40,
            )
        self.assertEqual(
            new_resp.json(), old_resp.json(),
            "Sepolia network-explicit route must produce the same "
            "envelope as the legacy /crypto/wallet/{asset}/... route",
        )

    def test_sepolia_receive_no_account_envelope(self) -> None:
        self._enable_engine()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=None,
        ):
            c = self._client()
            resp = c.get(
                "/crypto/wallet/network/ethereum_sepolia/ETH/receive",
            )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "no_account")


class NetworkCatalogRouteTests(_AuthedRouteCase):

    def test_catalog_lists_two_networks(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.get("/crypto/wallet/evm-networks")
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "enabled")
        nets = body["networks"]
        ids = [n["id"] for n in nets]
        self.assertEqual(
            ids, ["ethereum_sepolia", "ethereum_mainnet"],
        )
        sep = [n for n in nets if n["id"] == "ethereum_sepolia"][0]
        self.assertEqual(sep["chainId"], 11155111)
        self.assertTrue(sep["isTestnet"])
        self.assertTrue(sep["receiveEnabled"])
        self.assertTrue(sep["sendEnabled"])
        main = [n for n in nets if n["id"] == "ethereum_mainnet"][0]
        self.assertEqual(main["chainId"], 1)
        self.assertFalse(main["isTestnet"])
        self.assertFalse(main["receiveEnabled"])
        self.assertFalse(main["sendEnabled"])


class MainnetSendFlagFlipAloneTests(_AuthedRouteCase):

    def test_send_flag_on_with_send_flag_off_refuses(self) -> None:
                                                           
                                                              
        self._enable_engine()
        os.environ["VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED"] = "true"
        os.environ["ETHEREUM_MAINNET_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": "0x" + "a" * 200},
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "mainnet_send_disabled",
        )
        self.assertNotIn("txHash", body)


class SourceGuardTests(unittest.TestCase):

    def _read_src(self, *rel_parts: str) -> str:
        path = _BACKEND_ROOT.joinpath(*rel_parts)
        with io.open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_N13_evm_networks_imports_no_signing_library(self) -> None:
        src = self._read_src("evm_networks.py")
        for needle in (
            "import secp256k1", "from secp256k1",
            "import keccak", "from keccak",
            "import rlp", "from rlp",
            "import eth_keys", "from eth_keys",
            "import eth_account", "from eth_account",
            "import web3", "from web3",
            "pointycastle",
        ):
            self.assertNotIn(
                needle, src,
                f"evm_networks.py must not import {needle!r}",
            )

    def test_N13_route_module_imports_no_signing_library(self) -> None:
        src = self._read_src("routes", "crypto_wallet_routes.py")
        for needle in (
            "import secp256k1", "from secp256k1",
            "import eth_keys", "from eth_keys",
            "import eth_account", "from eth_account",
            "import web3", "from web3",
            "pointycastle",
        ):
            self.assertNotIn(
                needle, src,
                f"crypto_wallet_routes.py must not import {needle!r}",
            )

    def test_N14_route_logs_no_address_or_amount(self) -> None:
        src = self._read_src("routes", "crypto_wallet_routes.py")
                                                                   
                                                        
        forbidden = (
            "logger.info(payload.fromAddress",
            "logger.warning(payload.fromAddress",
            "logger.info(payload.destinationAddress",
            "logger.warning(payload.destinationAddress",
            "logger.info(payload.amount",
            "logger.warning(payload.amount",
            "logger.info(payload.dataHex",
            "logger.warning(payload.dataHex",
            "logger.info(payload.signedTransaction",
            "logger.warning(payload.signedTransaction",
        )
        for needle in forbidden:
            self.assertNotIn(needle, src)


if __name__ == "__main__":
    unittest.main()
