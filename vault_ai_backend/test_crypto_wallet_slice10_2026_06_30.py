

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


_ALL_RELEVANT_ENV: tuple[str, ...] = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDT_DECIMALS",
    "ETHEREUM_MAINNET_USDC_DECIMALS",
    "ETHEREUM_MAINNET_TX_INDEXER_PROVIDER",
    "ETHEREUM_MAINNET_TX_INDEXER_API_KEY",
    "ETHEREUM_MAINNET_TX_INDEXER_BASE_URL",
    "ETHEREUM_SEPOLIA_RPC_URL",
    "ETH_SEPOLIA_USDT_CONTRACT_ADDRESS",
    "ETH_SEPOLIA_USDC_CONTRACT_ADDRESS",
    "ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER",
    "ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY",
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
    _clear_env(*_ALL_RELEVANT_ENV)


def _make_app_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as wallet_module
    from routes.crypto_wallet_routes import (
        router,
        verify_trusted_device,
        require_crypto_entitlement,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": "test-vault-id-slice10",
    }
    app.dependency_overrides[require_crypto_entitlement] = lambda: {
        "vault_id": "test-vault-id-slice10",
    }
    return TestClient(app), app, wallet_module


_USDT_MAINNET = "0x" + "11" * 20                                  
_USDC_MAINNET = "0x" + "22" * 20
_ETH_ADDR     = "0x" + "ab" * 20
_OTHER_ADDR   = "0x" + "ee" * 20


class FlagDefaultsTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_all_env()

    def tearDown(self) -> None:
        _clear_all_env()

    def test_T1_erc20_receive_default_false(self) -> None:
        from vault_config import ethereum_mainnet_erc20_receive_enabled
        self.assertFalse(ethereum_mainnet_erc20_receive_enabled())

    def test_T1b_erc20_receive_can_be_enabled(self) -> None:
        from vault_config import ethereum_mainnet_erc20_receive_enabled
        _set_env(
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
        self.assertTrue(ethereum_mainnet_erc20_receive_enabled())

    def test_T2_erc20_flag_does_not_enable_send(self) -> None:
                                                                  
        from evm_networks import (
            NETWORK_ETHEREUM_MAINNET, is_send_enabled,
        )
        _set_env(
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
        self.assertFalse(is_send_enabled(NETWORK_ETHEREUM_MAINNET))


class MainnetErc20RoutesTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_all_env()
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
        self._chain_id_patch = mock.patch(
            "evm_rpc.eth_chain_id_at_url", return_value=1,
        )
        self._block_number_patch = mock.patch(
            "evm_rpc.eth_block_number_at_url", return_value=20_000_000,
        )
        self._chain_id_patch.start()
        self._block_number_patch.start()
        self.addCleanup(self._chain_id_patch.stop)
        self.addCleanup(self._block_number_patch.stop)

    def tearDown(self) -> None:
        self._wallet_mod._load_wallet_account_record = self._orig_load
        self._wallet_mod._insert_wallet_account_record = self._orig_insert
        _clear_all_env()

    def _create_mainnet_eth_record(self) -> None:
        self._store[("vault", "ETH:ethereum_mainnet")] = {
            "schema":        "crypto_wallet_account_v1",
            "asset":         "ETH",
            "network":       "ethereum_mainnet",
            "walletLabel":   "VaultAI Mainnet ETH",
            "publicAddress": _ETH_ADDR,
            "encryptedWalletSecret": "ct-mainnet",
            "keyOrigin":     "generated_client_side",
            "signingMode":   "client_side",
            "backupStatus":  "encrypted_backup_saved",
        }

                                                                        
    def test_T14_token_receive_disabled_when_flag_off(self) -> None:
                                                    
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        )
        self._create_mainnet_eth_record()
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/receive",
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "token_receive_disabled",
        )
                          
        self.assertNotIn("publicAddress", body)

    def test_T3_token_receive_no_eth_wallet_yet(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
                                             
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/USDC_ERC20/receive",
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "create_eth_mainnet_wallet_first",
        )
        self.assertEqual(body.get("underlyingAsset"), "ETH")
                          
        self.assertNotIn("publicAddress", body)

    def test_T4_token_receive_reuses_eth_address(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
        self._create_mainnet_eth_record()
        for asset, unit in (("USDT_ERC20", "USDT"), ("USDC_ERC20", "USDC")):
            resp = self._client.get(
                f"/crypto/wallet/network/ethereum_mainnet/{asset}/receive",
            )
            body = resp.json()
            self.assertEqual(body["wallet_engine"], "receive_ready", asset)
                                                                  
                                 
            self.assertEqual(body["publicAddress"], _ETH_ADDR, asset)
            self.assertEqual(body["underlyingAsset"], "ETH", asset)
            self.assertEqual(body["unit"], unit, asset)
            self.assertEqual(body["network"], "Ethereum Mainnet", asset)
                                                                  
            warn = body["warning"].lower()
            self.assertIn(unit.lower(), warn, asset)
            self.assertIn("mainnet", warn, asset)
            self.assertIn("real", warn, asset)
            self.assertIn("gas", body["gasNote"].lower(), asset)
            self.assertIn(
                "ethereum mainnet wallet address",
                body["sharedAddressNote"].lower(),
                asset,
            )
                                                        
            self.assertNotIn("encryptedWalletSecret", body, asset)

                                                                        
    def test_T6_token_balance_contract_not_configured(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
                                                     
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
            ETH_SEPOLIA_USDT_CONTRACT_ADDRESS="0x" + "33" * 20,
        )
        addr = _OTHER_ADDR
        resp = self._client.get(
            f"/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/balance"
            f"?address={addr}",
        )
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "unavailable")
        self.assertEqual(body["reason"], "token_contract_not_configured")

    def test_T5_T6_T8_token_balance_uses_mainnet_only(self) -> None:
                                                                    
                                            
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=_USDT_MAINNET,
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
            ETH_SEPOLIA_USDT_CONTRACT_ADDRESS="0x" + "44" * 20,
        )
        captured: list[dict[str, Any]] = []

        def _stub(rpc_url, *, token_contract_address, holder_address):
            captured.append({
                "url": rpc_url,
                "contract": token_contract_address,
                "holder": holder_address,
            })
                                   
            return 1_500_000

        import evm_rpc
        with mock.patch.object(
            evm_rpc, "erc20_balance_of_at_url", side_effect=_stub,
        ):
            resp = self._client.get(
                f"/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/"
                f"balance?address={_OTHER_ADDR}",
            )
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "available")
        self.assertEqual(body["availableAmount"], "1.5")
        self.assertEqual(body["unit"], "USDT")
        self.assertEqual(body["network"], "Ethereum Mainnet")
        self.assertEqual(body["tokenContract"], _USDT_MAINNET)
                                                                      
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["url"], "https://example.invalid/mainnet")
        self.assertEqual(captured[0]["contract"], _USDT_MAINNET)
                                         
        self.assertNotIn("sepolia", captured[0]["url"].lower())

    def test_T5b_token_balance_rpc_not_configured(self) -> None:
                                                  
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=_USDT_MAINNET,
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        )
        resp = self._client.get(
            f"/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/balance"
            f"?address={_OTHER_ADDR}",
        )
        body = resp.json()
        self.assertEqual(body["reason"], "rpc_not_configured")

    def test_T5c_token_balance_disabled_without_flag(self) -> None:
                                                             
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=_USDT_MAINNET,
        )
        resp = self._client.get(
            f"/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/balance"
            f"?address={_OTHER_ADDR}",
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "token_receive_disabled",
        )

                                                                        
    def test_T9_token_activity_no_indexer(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
                                                     
            ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY="sepolia-key",
        )
        self._create_mainnet_eth_record()
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/transactions",
        )
        body = resp.json()
        self.assertEqual(body["reason"], "indexer_not_configured")
                                            
        self.assertIn(
            "ETHEREUM_MAINNET_TX_INDEXER_PROVIDER", body["message"],
        )

    def test_T9b_token_activity_create_eth_first(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_MAINNET_TX_INDEXER_API_KEY="mainnet-key",
        )
                                                                   
                                              
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/USDC_ERC20/transactions",
        )
        body = resp.json()
        self.assertEqual(
            body["reason"], "create_eth_mainnet_wallet_first",
        )
        self.assertEqual(body["transactions"], [])

    def test_T10_token_activity_filters_by_mainnet_contract(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_MAINNET_TX_INDEXER_API_KEY="mainnet-key",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=_USDT_MAINNET,
            ETH_SEPOLIA_USDT_CONTRACT_ADDRESS="0x" + "55" * 20,
        )
        self._create_mainnet_eth_record()
        captured: list[dict[str, Any]] = []

        def _stub_query(*, address, action, contract_address, limit,
                        network_id="ethereum_sepolia"):
            captured.append({
                "address": address, "action": action,
                "contract": contract_address, "network": network_id,
            })
            return []

        import evm_transaction_history
        with mock.patch.object(
            evm_transaction_history, "_query_provider",
            side_effect=_stub_query,
        ):
            resp = self._client.get(
                "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/"
                "transactions",
            )
        body = resp.json()
        self.assertEqual(body["transactionsStatus"], "available")
        self.assertEqual(len(captured), 1)
                                                                
        self.assertEqual(captured[0]["contract"], _USDT_MAINNET)
        self.assertEqual(captured[0]["network"], "ethereum_mainnet")
        self.assertEqual(captured[0]["action"], "tokentx")

    def test_T7_token_activity_contract_missing(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_TX_INDEXER_PROVIDER="etherscan",
            ETHEREUM_MAINNET_TX_INDEXER_API_KEY="mainnet-key",
                                            
        )
        self._create_mainnet_eth_record()
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/transactions",
        )
        body = resp.json()
        self.assertEqual(body["reason"], "token_contract_not_configured")

                                                                       
    def test_T11_token_send_draft_always_blocked(self) -> None:
                                                                   
                                                         
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/send/draft",
            json={
                "fromAddress":         _ETH_ADDR,
                "destinationAddress":  "0x" + "22" * 20,
                "amountEth":           "1.0",
            },
        )
        body = resp.json()
        self.assertIn(
            body.get("status") or body.get("reason")
            or body.get("wallet_engine"),
            {"draft_unavailable", "mainnet_send_disabled",
             "mainnet_handler_not_implemented"},
        )
        self.assertNotIn("nonce", body)
        self.assertNotIn("gasPrice", body)
        self.assertNotIn("calldata", body)

    def test_T11b_token_send_draft_blocked_send_flag_off(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/USDC_ERC20/send/draft",
            json={
                "fromAddress":         _ETH_ADDR,
                "destinationAddress":  "0x" + "33" * 20,
                "amountEth":           "1.0",
            },
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "mainnet_send_disabled",
        )

    def test_T12_token_broadcast_always_refused(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/send/broadcast",
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

                                                                        
    def test_T15_token_create_reuses_eth_wallet(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
        self._create_mainnet_eth_record()
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/create",
            json={
                "walletLabel":           "mainnet usdt",
                "publicAddress":         "0x" + "99" * 20,
                "network":               "ethereum_mainnet",
                "encryptedWalletSecret": "ct-token",
            },
        )
        body = resp.json()
                                                                 
        self.assertEqual(
            body.get("wallet_engine"), "token_uses_eth_address",
        )
        self.assertEqual(body.get("publicAddress"), _ETH_ADDR)
                                        
        self.assertNotIn(
            ("vault", "USDT_ERC20:ethereum_mainnet"), self._store,
        )

    def test_T15b_token_create_no_eth_yet(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/USDC_ERC20/create",
            json={
                "walletLabel":           "mainnet usdc",
                "publicAddress":         "0x" + "88" * 20,
                "network":               "ethereum_mainnet",
                "encryptedWalletSecret": "ct-stub-x",
            },
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "create_eth_mainnet_wallet_first",
        )

                                                                       
    def test_T13_sepolia_routes_unchanged(self) -> None:
                                                                  
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
        resp = self._client.get("/crypto/wallet/USDT_ERC20/receive")
        body = resp.json()
                                                                  
        self.assertEqual(body["wallet_engine"], "receive_ready")
        self.assertEqual(body["publicAddress"], addr)
        self.assertEqual(body["network"], "Ethereum Sepolia")

                                                                       
    def test_T15c_token_account_detail_uses_eth_wallet(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
        )
        self._create_mainnet_eth_record()
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20",
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "account_ready")
        acc = body["account"]
                                                               
        self.assertEqual(acc["asset"], "USDT_ERC20")
        self.assertEqual(acc["publicAddress"], _ETH_ADDR)
        self.assertEqual(acc["underlyingAsset"], "ETH")


class ChatComposerMainnetErc20Tests(unittest.TestCase):

    def test_T16_chat_token_receive_on_mainnet_allowed_with_flag(self) -> None:
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_RECEIVE_ADDRESS,
            WALLET_CHAT_NETWORK_MAINNET,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        parsed = parse_wallet_engine_chat_message(
            "give me my mainnet USDT receive address",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_receive_enabled=False,
            mainnet_erc20_receive_enabled=True,
        )
        self.assertEqual(env["intent"], WALLET_CHAT_INTENT_RECEIVE_ADDRESS)
        self.assertEqual(env["network"], WALLET_CHAT_NETWORK_MAINNET)
        self.assertEqual(env["asset"], "USDT_ERC20")

    def test_T16b_chat_token_balance_on_mainnet_allowed(self) -> None:
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_SHOW_BALANCE,
            WALLET_CHAT_NETWORK_MAINNET,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        parsed = parse_wallet_engine_chat_message(
            "show my USDC balance on mainnet",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_erc20_receive_enabled=True,
        )
        self.assertEqual(env["intent"], WALLET_CHAT_INTENT_SHOW_BALANCE)
        self.assertEqual(env["network"], WALLET_CHAT_NETWORK_MAINNET)
        self.assertIn("Mainnet", env["message"])
        self.assertNotIn("Sepolia", env["message"])

    def test_T16c_chat_token_blocked_without_flag(self) -> None:
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
                                                                   
                                                
        parsed = parse_wallet_engine_chat_message(
            "give me my mainnet USDC receive address",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_receive_enabled=True,
            mainnet_erc20_receive_enabled=False,
        )
        self.assertEqual(
            env["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
        )
        self.assertEqual(env["blockedReason"], "mainnet_disabled")

    def test_T17_chat_token_send_on_mainnet_blocked_without_send_flag(self) -> None:
                                                                  
                                                         
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        dest = "0x" + "ab" * 20
        parsed = parse_wallet_engine_chat_message(
            f"send 1.0 USDT on mainnet to {dest}",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_receive_enabled=True,
            mainnet_send_enabled=False,
            mainnet_erc20_receive_enabled=True,
        )
        self.assertEqual(
            env["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
        )
        self.assertEqual(env["blockedReason"], "mainnet_disabled")
        self.assertIsNone(env["destinationAddress"])
        self.assertIsNone(env["amount"])
                                                      
        self.assertIn("mainnet", env["message"].lower())

    def test_T18_chat_token_receive_real_funds_copy(self) -> None:
        from wallet_engine_chat import (
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        parsed = parse_wallet_engine_chat_message(
            "show my mainnet USDT QR",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_erc20_receive_enabled=True,
        )
        msg = env["message"]
        self.assertIn("USDT", msg)
        self.assertIn("REAL", msg.upper())
        self.assertIn("Mainnet", msg)
                                            
        self.assertIn("gas", msg.lower())


class SourceGuardTests(unittest.TestCase):

    def test_T19_evm_rpc_eth_call_no_signing(self) -> None:
        src = (_BACKEND_ROOT / "evm_rpc.py").read_text(encoding="utf-8")
                            
        scrubbed = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
        scrubbed = re.sub(
            r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
        )
                                                          
                                                                  
        for banned in (
            "eth_sign", "personal_sign", "personal_signTransaction",
            "personal_sendTransaction",
            "eth_signTransaction", "eth_sendTransaction",
            "debug_traceTransaction", "debug_traceCall",
            "eth_account", "eth_keys", "web3", "ethereum_transaction",
            "ethereum_sepolia_proxy", "ethereum_wallet",
        ):
            self.assertNotIn(
                banned, scrubbed,
                msg=f"evm_rpc.py must not import or call {banned}",
            )

    def test_T19b_erc20_balance_helper_uses_eth_call(self) -> None:
                                                                   
                                                                   
        from evm_rpc import ALLOWED_RPC_METHODS
        self.assertIn("eth_call", ALLOWED_RPC_METHODS)
        self.assertIn("eth_getBalance", ALLOWED_RPC_METHODS)
                                                           
                                                                 
        for banned in (
            "eth_sendTransaction",
            "eth_sign", "personal_sign",
            "debug_traceTransaction",
        ):
            self.assertNotIn(banned, ALLOWED_RPC_METHODS)
                                                                   
                                                                   
        for banned in (
            "eth_sendTransaction",
            "eth_sign", "personal_sign",
            "eth_signTransaction", "personal_signTransaction",
            "debug_traceTransaction", "debug_traceCall",
        ):
            self.assertNotIn(banned, ALLOWED_RPC_METHODS)

    def test_T20_no_hardcoded_mainnet_token_address_literals(self) -> None:
                                                                    
                                                                
        for path in (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py",
            _BACKEND_ROOT / "evm_rpc.py",
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

    def test_T21_route_logger_no_address_amount(self) -> None:
        path = _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        src = path.read_text(encoding="utf-8")
        scrubbed = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
        scrubbed = re.sub(
            r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
        )
        log_calls = re.findall(
            r"logger\.(?:info|warning|error|debug)\([^)]*\)",
            scrubbed,
        )
        for call in log_calls:



            allowed_safe_flags = ("api_key_present=%s",)

            for banned in (
                "rpc_url", "api_key", "publicAddress",
                "tokenContract", "contractAddress",
            ):
                if banned == "api_key" and any(
                    s in call for s in allowed_safe_flags
                ):
                    continue
                self.assertNotIn(
                    banned, call,
                    msg=f"Logger call leaks {banned}: {call}",
                )


if __name__ == "__main__":
    unittest.main()
