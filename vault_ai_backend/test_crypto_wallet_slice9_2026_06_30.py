

from __future__ import annotations

import io
import json
import os
import re
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import vault_config


_BACKEND_ROOT = Path(__file__).parent


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


def _make_app_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as wallet_module
    from routes.crypto_wallet_routes import (
        router,
        verify_trusted_device,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": "test-vault-id-slice9",
    }
    return TestClient(app), app, wallet_module


class DefaultFlagsTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_env(
            "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
        )

    def tearDown(self) -> None:
        _clear_env(
            "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
        )

    def test_M1_mainnet_receive_default_false(self) -> None:
        from evm_networks import (
            NETWORK_ETHEREUM_MAINNET, is_receive_enabled,
        )
        self.assertFalse(is_receive_enabled(NETWORK_ETHEREUM_MAINNET))

    def test_M2_mainnet_send_default_false(self) -> None:
        from evm_networks import (
            NETWORK_ETHEREUM_MAINNET, is_send_enabled,
        )
        self.assertFalse(is_send_enabled(NETWORK_ETHEREUM_MAINNET))

    def test_M2b_mainnet_receive_enables_independent_of_send(self) -> None:
        from evm_networks import (
            NETWORK_ETHEREUM_MAINNET, is_receive_enabled, is_send_enabled,
        )
        _set_env(VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true")
        self.assertTrue(is_receive_enabled(NETWORK_ETHEREUM_MAINNET))
                                                   
        self.assertFalse(is_send_enabled(NETWORK_ETHEREUM_MAINNET))


class ServiceKeyTests(unittest.TestCase):

    def test_M16_service_key_per_network(self) -> None:
        from routes.crypto_wallet_routes import _service_key_for_network
                                                  
        self.assertEqual(
            _service_key_for_network("ETH", "ethereum_sepolia"), "ETH",
        )
                                                                 
                                       
        self.assertEqual(
            _service_key_for_network("ETH", "ethereum_mainnet"),
            "ETH:ethereum_mainnet",
        )

    def test_M16b_record_matches_network_rejects_crossover(self) -> None:
        from routes.crypto_wallet_routes import _record_matches_network
        from evm_networks import (
            NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        )
                                                   
        self.assertFalse(_record_matches_network(
            "Ethereum Sepolia", NETWORK_ETHEREUM_MAINNET,
        ))
                                                   
        self.assertFalse(_record_matches_network(
            "Ethereum Mainnet", NETWORK_ETHEREUM_SEPOLIA,
        ))
                                                                   
        self.assertTrue(_record_matches_network(
            "ethereum_mainnet", NETWORK_ETHEREUM_MAINNET,
        ))
        self.assertTrue(_record_matches_network(
            "Ethereum Mainnet", NETWORK_ETHEREUM_MAINNET,
        ))
        self.assertTrue(_record_matches_network(
            "Ethereum Sepolia", NETWORK_ETHEREUM_SEPOLIA,
        ))


class MainnetRoutesTests(unittest.TestCase):

    def setUp(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        vault_config.reset_for_tests()
        self._client, self._app, self._wallet_mod = _make_app_client()
                                                                    
        self._store: dict[tuple[str, str], dict] = {}
        self._orig_load = self._wallet_mod._load_wallet_account_record
        self._orig_insert = self._wallet_mod._insert_wallet_account_record

        def _load(vault_id: str, asset_or_service: str):
                                                                
                                                  
            return self._store.get(("vault", asset_or_service))

        def _insert(vault_id: str, asset_or_service: str, record):
            self._store[("vault", asset_or_service)] = record

        self._wallet_mod._load_wallet_account_record = _load
        self._wallet_mod._insert_wallet_account_record = _insert

    def tearDown(self) -> None:
        self._wallet_mod._load_wallet_account_record = self._orig_load
        self._wallet_mod._insert_wallet_account_record = self._orig_insert
        _clear_env(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
            "ETHEREUM_MAINNET_RPC_URL",
            "ETHEREUM_MAINNET_TX_INDEXER_PROVIDER",
            "ETHEREUM_MAINNET_TX_INDEXER_API_KEY",
            "ETHEREUM_MAINNET_TX_INDEXER_BASE_URL",
            "ETHEREUM_SEPOLIA_RPC_URL",
        )

                                                                        
    def test_M3_mainnet_receive_no_account(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/receive",
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "no_account")
        self.assertEqual(body["network"], "Ethereum Mainnet")
                          
        self.assertNotIn("publicAddress", body)

    def test_M4_mainnet_receive_ready(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
        addr = "0x" + "ab" * 20
        self._store[("vault", "ETH:ethereum_mainnet")] = {
            "schema":        "crypto_wallet_account_v1",
            "asset":         "ETH",
            "network":       "ethereum_mainnet",
            "walletLabel":   "VaultAI Mainnet ETH",
            "publicAddress": addr,
            "encryptedWalletSecret": "ct-xxxxx",
            "keyOrigin":     "generated_client_side",
            "signingMode":   "client_side",
            "backupStatus":  "encrypted_backup_saved",
        }
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/receive",
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "receive_ready")
        self.assertEqual(body["publicAddress"], addr)
        self.assertEqual(body["network"], "Ethereum Mainnet")
                                                
        warning = body["warning"].lower()
        self.assertIn("real funds", warning)
        self.assertIn("mainnet", warning)
                                                    
        self.assertNotIn("encryptedWalletSecret", body)

    def test_M3b_mainnet_receive_disabled_default(self) -> None:
        _set_env(VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true")
                                               
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/receive",
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "network_not_enabled")

                                                                        
    def test_M5_mainnet_create_uses_per_network_service_key(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
                                                                 
                                                   
        self._store[("vault", "ETH")] = {
            "asset": "ETH", "network": "ethereum_sepolia",
            "publicAddress": "0x" + "11" * 20,
        }
        addr = "0x" + "cc" * 20
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/create",
            json={
                "walletLabel":           "Mainnet wallet",
                "publicAddress":         addr,
                "network":               "ethereum_mainnet",
                "encryptedWalletSecret": "ct-xxxxx",
            },
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "created")
                                
        self.assertEqual(
            self._store[("vault", "ETH")]["network"], "ethereum_sepolia",
        )
                                                   
        self.assertIn(("vault", "ETH:ethereum_mainnet"), self._store)
        self.assertEqual(
            self._store[("vault", "ETH:ethereum_mainnet")]["network"],
            "ethereum_mainnet",
        )

    def test_M6_mainnet_create_refuses_plaintext_key_aliases(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
        for banned in (
            "privateKey", "seedPhrase", "mnemonic", "recoveryPhrase",
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/create",
                json={
                    "walletLabel":           "x",
                    "publicAddress":         "0x" + "dd" * 20,
                    "network":               "ethereum_mainnet",
                    "encryptedWalletSecret": "ct",
                    banned:                  "leaked",
                },
            )
            self.assertEqual(resp.status_code, 422, msg=banned)

                                                                        
    def test_M7_M8_mainnet_balance_rpc_not_configured(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        )
        addr = "0x" + "bb" * 20
                                                           
        resp = self._client.get(
            f"/crypto/wallet/network/ethereum_mainnet/ETH/balance?address={addr}",
        )
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")
        self.assertEqual(body["network"], "Ethereum Mainnet")
                                                              
        self.assertNotIn("Sepolia", body.get("network", ""))

    def test_M9_mainnet_balance_parses_eth_getBalance(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        addr = "0x" + "ee" * 20
        captured_urls: list[str] = []

        def _stub(url: str, address: str) -> int:
            captured_urls.append(url)
                             
            return 1_500_000_000_000_000_000

        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            side_effect=_stub,
        ):
            resp = self._client.get(
                f"/crypto/wallet/network/ethereum_mainnet/ETH/balance?address={addr}",
            )
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "available")
        self.assertEqual(body["availableAmount"], "1.5")
        self.assertEqual(body["unit"], "ETH")
        self.assertEqual(body["network"], "Ethereum Mainnet")
                                                               
        self.assertEqual(captured_urls, ["https://example.invalid/mainnet"])

    def test_M8b_mainnet_balance_rpc_error(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        from evm_rpc import EvmRpcError
        import evm_rpc

        def _stub_err(url: str, address: str) -> int:
            raise EvmRpcError("upstream_io")

        with mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            side_effect=_stub_err,
        ):
            resp = self._client.get(
                "/crypto/wallet/network/ethereum_mainnet/ETH/balance"
                "?address=0x" + "bb" * 20,
            )
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "unavailable")
        self.assertEqual(body["reason"], "upstream_io")

                                                                        
    def test_M11_mainnet_transactions_indexer_not_configured(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
        self._store[("vault", "ETH:ethereum_mainnet")] = {
            "publicAddress": "0x" + "ee" * 20,
            "network": "ethereum_mainnet",
        }
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/transactions",
        )
        body = resp.json()
        self.assertEqual(body["reason"], "indexer_not_configured")
        self.assertEqual(body["network"], "ethereum_mainnet")
        self.assertEqual(body["networkLabel"], "Ethereum Mainnet")

    def test_M12_mainnet_transactions_no_wallet_yet(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
                                         
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/transactions",
        )
        body = resp.json()
        self.assertEqual(body["reason"], "no_wallet_yet")
        self.assertEqual(body["transactions"], [])

    def test_M10_mainnet_tx_uses_mainnet_env_only(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
                              
            ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY="sepolia-key",
                                                          
        )
        self._store[("vault", "ETH:ethereum_mainnet")] = {
            "publicAddress": "0x" + "ee" * 20,
            "network": "ethereum_mainnet",
        }
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/transactions",
        )
        body = resp.json()
                                                       
                                 
        self.assertEqual(body["reason"], "indexer_not_configured")
                                                                 
        self.assertIn("ETHEREUM_MAINNET_TX_INDEXER_PROVIDER", body["message"])

                                                                       
    def test_M14_mainnet_send_draft_always_blocked(self) -> None:
                                                                 
                                                             
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":         "0x" + "11" * 20,
                "destinationAddress":  "0x" + "22" * 20,
                "amountEth":           "0.01",
            },
        )
        body = resp.json()
                                                                
                                          
        self.assertIn(
            body.get("status") or body.get("reason"),
            {"draft_unavailable", "mainnet_send_disabled",
             "mainnet_handler_not_implemented"},
        )
                                                          
        self.assertNotIn("nonce", body)
        self.assertNotIn("gasPrice", body)

    def test_M14b_mainnet_send_draft_blocked_with_send_flag_off(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
                            
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":         "0x" + "11" * 20,
                "destinationAddress":  "0x" + "22" * 20,
                "amountEth":           "0.01",
            },
        )
        body = resp.json()
                                                                   
        self.assertEqual(
            body.get("wallet_engine"), "mainnet_send_disabled",
        )

    def test_M15_mainnet_broadcast_always_refused(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": "0x" + "ab" * 100},
        )
        body = resp.json()
                                            
        self.assertNotIn("txHash", body)
                                                               
                                             
        self.assertIn(
            body.get("wallet_engine") or body.get("status"),
            {
                "mainnet_send_disabled",
                "broadcast_unavailable",
            },
        )

                                                                       
    def test_M13_sepolia_routes_unchanged(self) -> None:
                                                                   
                                                             
        _set_env(VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true")
        addr = "0x" + "11" * 20
        self._store[("vault", "ETH")] = {
            "schema":        "crypto_wallet_account_v1",
            "asset":         "ETH",
            "network":       "Ethereum Sepolia",
            "walletLabel":   "VaultAI ETH wallet",
            "publicAddress": addr,
            "encryptedWalletSecret": "ct-xxxxx",
            "keyOrigin":     "generated_client_side",
            "signingMode":   "client_side",
            "backupStatus":  "encrypted_backup_saved",
        }
        resp = self._client.get("/crypto/wallet/ETH/receive")
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "receive_ready")
        self.assertEqual(body["publicAddress"], addr)
        self.assertEqual(body["network"], "Ethereum Sepolia")

                                                                       
    def test_M17_mainnet_account_detail_no_account(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH",
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "no_account")


class ChatComposerMainnetTests(unittest.TestCase):

    def test_M18_chat_balance_on_mainnet_allowed_with_flag(self) -> None:
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_SHOW_BALANCE,
            WALLET_CHAT_NETWORK_MAINNET,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        parsed = parse_wallet_engine_chat_message(
            "show my ETH balance on mainnet",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_receive_enabled=True,
        )
        self.assertEqual(env["intent"], WALLET_CHAT_INTENT_SHOW_BALANCE)
        self.assertEqual(env["network"], WALLET_CHAT_NETWORK_MAINNET)
                                    
        self.assertIn("Mainnet", env["message"])
        self.assertNotIn("Sepolia", env["message"])

    def test_M18b_chat_receive_on_mainnet_real_funds_copy(self) -> None:
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_RECEIVE_ADDRESS,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        parsed = parse_wallet_engine_chat_message(
            "give me my ETH mainnet receive address",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_receive_enabled=True,
        )
        self.assertEqual(env["intent"], WALLET_CHAT_INTENT_RECEIVE_ADDRESS)
        self.assertIn("REAL", env["message"].upper())

    def test_M18c_chat_receive_blocked_when_flag_off(self) -> None:
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        parsed = parse_wallet_engine_chat_message(
            "give me my ETH mainnet receive address",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_receive_enabled=False,
        )
        self.assertEqual(
            env["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
        )

    def test_M19_chat_send_on_mainnet_blocked_without_send_flag(self) -> None:
                                                                
                                                         
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        dest = "0x" + "ab" * 20
        parsed = parse_wallet_engine_chat_message(
            f"send 0.01 ETH on mainnet to {dest}",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_receive_enabled=True,
            mainnet_send_enabled=False,
        )
        self.assertEqual(
            env["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
        )
        self.assertEqual(env["blockedReason"], "mainnet_disabled")
                                                              
                       
        self.assertIsNone(env["destinationAddress"])
        self.assertIsNone(env["amount"])


class SourceGuardTests(unittest.TestCase):

    def test_M20_evm_rpc_no_signing_imports(self) -> None:
        src = (_BACKEND_ROOT / "evm_rpc.py").read_text(encoding="utf-8")
        scrubbed = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
        scrubbed = re.sub(
            r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
        )
        for banned in (
            "eth_account", "web3", "ethereum_transaction",
            "ethereum_sepolia_proxy", "ethereum_wallet", "eth_keys",
        ):
            self.assertNotIn(
                banned, scrubbed,
                msg=f"evm_rpc.py must not import {banned}",
            )

    def test_M21_no_hardcoded_fake_mainnet_literals(self) -> None:
                                                            
                                                               
        for path in (
            _BACKEND_ROOT / "evm_rpc.py",
            _BACKEND_ROOT / "evm_transaction_history.py",
        ):
            src = path.read_text(encoding="utf-8")
            scrubbed = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
            scrubbed = re.sub(
                r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
            )
                                                             
                                            
            scrubbed = re.sub(
                r"r['\"][^'\"]*0x[^'\"]*['\"]", "", scrubbed,
            )
            addr_re = re.compile(r"0x[0-9a-fA-F]{40,}")
            for m in addr_re.finditer(scrubbed):
                self.fail(
                    f"{path.name} contains hardcoded 0x literal: "
                    f"{m.group(0)}",
                )

    def test_M22_evm_rpc_logger_no_url_or_key(self) -> None:
        src = (_BACKEND_ROOT / "evm_rpc.py").read_text(encoding="utf-8")
                            
        scrubbed = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
        scrubbed = re.sub(
            r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
        )
                                                 
        log_calls = re.findall(
            r"logger\.(?:info|warning|error|debug)\([^)]*\)",
            scrubbed,
        )
        for call in log_calls:
                                                                 
                                                                 
            for banned in ("rpc_url", "api_key"):
                self.assertNotIn(
                    banned, call,
                    msg=f"Logger call leaks {banned}: {call}",
                )
                                                                
                                                                     
            if " url" in call or "(url" in call:
                self.fail(f"Logger call references url: {call}")


class VaultConfigMainnetHelpersTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_env(
            "ETHEREUM_MAINNET_RPC_URL",
            "ETHEREUM_MAINNET_TX_INDEXER_PROVIDER",
            "ETHEREUM_MAINNET_TX_INDEXER_API_KEY",
            "ETHEREUM_MAINNET_TX_INDEXER_BASE_URL",
        )

    def tearDown(self) -> None:
        _clear_env(
            "ETHEREUM_MAINNET_RPC_URL",
            "ETHEREUM_MAINNET_TX_INDEXER_PROVIDER",
            "ETHEREUM_MAINNET_TX_INDEXER_API_KEY",
            "ETHEREUM_MAINNET_TX_INDEXER_BASE_URL",
        )

    def test_mainnet_rpc_url_default_empty(self) -> None:
        self.assertEqual(vault_config.ethereum_mainnet_rpc_url(), "")

    def test_mainnet_indexer_default_unconfigured(self) -> None:
        self.assertFalse(
            vault_config.ethereum_mainnet_tx_indexer_configured(),
        )

    def test_mainnet_etherscan_needs_api_key(self) -> None:
        _set_env(ETHEREUM_MAINNET_TX_INDEXER_PROVIDER="etherscan")
        self.assertFalse(
            vault_config.ethereum_mainnet_tx_indexer_configured(),
        )
        _set_env(
            ETHEREUM_MAINNET_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_MAINNET_TX_INDEXER_API_KEY="k",
        )
        self.assertTrue(
            vault_config.ethereum_mainnet_tx_indexer_configured(),
        )

    def test_mainnet_indexer_default_base_url_per_provider(self) -> None:
        _set_env(
            ETHEREUM_MAINNET_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_MAINNET_TX_INDEXER_API_KEY="k",
        )
        url = vault_config.ethereum_mainnet_tx_indexer_base_url()
        self.assertTrue(url.startswith("https://"))
                                
        self.assertIn("etherscan", url)
        _set_env(ETHEREUM_MAINNET_TX_INDEXER_PROVIDER="blockscout")
        url = vault_config.ethereum_mainnet_tx_indexer_base_url()
        self.assertIn("blockscout", url)


if __name__ == "__main__":
    unittest.main()
