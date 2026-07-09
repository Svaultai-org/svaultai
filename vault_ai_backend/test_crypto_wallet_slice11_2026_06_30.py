

from __future__ import annotations

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
    "ETHEREUM_SEPOLIA_RPC_URL",
    "ETH_SEPOLIA_USDT_CONTRACT_ADDRESS",
    "ETH_SEPOLIA_USDC_CONTRACT_ADDRESS",
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
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": "test-vault-id-slice11",
    }
    return TestClient(app), app, wallet_module


_USDT_MAINNET = "0x" + "11" * 20
_USDC_MAINNET = "0x" + "22" * 20
_FROM_ADDR    = "0x" + "ab" * 20
_DEST_ADDR    = "0x" + "cd" * 20
_SIGNED_TX    = "0x" + "ee" * 120
_TX_HASH      = "0x" + "0f" * 32


class FlagDefaultsTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_all_env()

    def tearDown(self) -> None:
        _clear_all_env()

    def test_S1_mainnet_send_default_false(self) -> None:
        from evm_networks import (
            NETWORK_ETHEREUM_MAINNET, is_send_enabled,
        )
        self.assertFalse(is_send_enabled(NETWORK_ETHEREUM_MAINNET))
                                                
        _set_env(VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true")
        self.assertFalse(is_send_enabled(NETWORK_ETHEREUM_MAINNET))


class MainnetSendRouteTests(unittest.TestCase):

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
            "publicAddress": _FROM_ADDR,
            "encryptedWalletSecret": "ct-mainnet-secret",
            "keyOrigin":     "generated_client_side",
            "signingMode":   "client_side",
            "backupStatus":  "encrypted_backup_saved",
        }

                                                                        
    def test_S13_S20_draft_refused_when_send_flag_off(self) -> None:
                                                            
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  _DEST_ADDR,
                "amountEth":           "0.01",
            },
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "mainnet_send_disabled",
        )

    def test_S2_S3_S5_S6_eth_draft_uses_mainnet_only(self) -> None:
                                                                    
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        )
        urls_seen: list[str] = []

        def _nonce(rpc_url, address):
            urls_seen.append(("nonce", rpc_url))
            return 17

        def _gas_price(rpc_url):
            urls_seen.append(("gas_price", rpc_url))
            return 1_000_000_000          

        def _estimate(rpc_url, **kwargs):
            urls_seen.append(("estimate", rpc_url))
            return 21_000

        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            side_effect=_nonce,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            side_effect=_gas_price,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            side_effect=_estimate,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
                json={
                    "fromAddress":         _FROM_ADDR,
                    "destinationAddress":  _DEST_ADDR,
                    "amountEth":           "0.01",
                },
            )
        body = resp.json()
        self.assertEqual(body["status"], "draft_ready")
                                   
        self.assertEqual(body["chainId"], 1)
        self.assertEqual(body["network"], "Ethereum Mainnet")
        self.assertEqual(body["nonce"], "17")
        self.assertEqual(body["gasLimit"], "21000")
        self.assertEqual(body["gasPrice"], "1000000000")
                                                    
        self.assertEqual(len(urls_seen), 3)
        for _, url in urls_seen:
            self.assertEqual(url, "https://example.invalid/mainnet")
                                         
            self.assertNotIn("sepolia", url.lower())
                                           
        self.assertIn(
            "real eth", body["realFundsWarning"].lower(),
        )
        self.assertIn(
            "mainnet", body["realFundsWarning"].lower(),
        )
                                  
        self.assertNotIn("encryptedWalletSecret", body)
        self.assertNotIn("privateKey", body)

    def test_S4_eth_draft_refuses_self_send(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  _FROM_ADDR,
                "amountEth":           "0.01",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_S4b_eth_draft_refuses_invalid_amount(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  _DEST_ADDR,
                "amountEth":           "-1.0",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_S4c_eth_draft_refuses_invalid_destination(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  "0xnothex",
                "amountEth":           "0.01",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_S5b_eth_draft_rpc_not_configured(self) -> None:
                                               
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  _DEST_ADDR,
                "amountEth":           "0.01",
            },
        )
        body = resp.json()
        self.assertEqual(body["status"], "draft_unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")

                                                                        
    def test_S7_erc20_draft_token_contract_missing(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
                                                   
            ETH_SEPOLIA_USDT_CONTRACT_ADDRESS="0x" + "33" * 20,
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  _DEST_ADDR,
                "amountEth":           "1.0",
            },
        )
        body = resp.json()
        self.assertEqual(body["status"], "draft_unavailable")
        self.assertEqual(body["reason"], "token_contract_not_configured")

    def test_S8_S9_erc20_draft_uses_mainnet_contract_only(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
            ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS=_USDT_MAINNET,
                                                            
            ETH_SEPOLIA_USDT_CONTRACT_ADDRESS="0x" + "44" * 20,
        )
        urls_seen: list[str] = []

        def _nonce(rpc_url, address):
            urls_seen.append(rpc_url)
            return 5

        def _gas_price(rpc_url):
            urls_seen.append(rpc_url)
            return 2_000_000_000

        captured_estimate: dict[str, Any] = {}

        def _estimate(rpc_url, **kwargs):
            captured_estimate["url"] = rpc_url
            captured_estimate.update(kwargs)
            return 60_000

        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            side_effect=_nonce,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            side_effect=_gas_price,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            side_effect=_estimate,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/"
                "send/draft",
                json={
                    "fromAddress":         _FROM_ADDR,
                    "destinationAddress":  _DEST_ADDR,
                    "amountEth":           "1.0",
                },
            )
        body = resp.json()
        self.assertEqual(body["status"], "draft_ready")
        self.assertEqual(body["chainId"], 1)
                                                               
        self.assertEqual(body["transactionValueWei"], "0")
        self.assertEqual(body["transactionTo"], _USDT_MAINNET)
                                                                      
        self.assertTrue(body["dataHex"].startswith("0xa9059cbb"))
                                                               
        self.assertIn(
            _DEST_ADDR[2:].lower(), body["dataHex"].lower(),
        )
                                                                 
        self.assertIn("f4240", body["dataHex"].lower())
                                                    
        self.assertEqual(captured_estimate["url"],
                         "https://example.invalid/mainnet")
        self.assertEqual(captured_estimate["to_address"], _USDT_MAINNET)
                                           
        for url in urls_seen:
            self.assertEqual(url, "https://example.invalid/mainnet")
                              
        self.assertEqual(body["amountBaseUnits"], "1000000")
        self.assertEqual(body["unit"], "USDT")
        self.assertEqual(body["decimals"], 6)
                                 
        self.assertIn("gas", body["realFundsWarning"].lower())

    def test_S9b_usdc_draft_uses_usdc_contract(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
            ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS=_USDC_MAINNET,
        )
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=5,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url", return_value=1000,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url", return_value=60_000,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/USDC_ERC20/"
                "send/draft",
                json={
                    "fromAddress":         _FROM_ADDR,
                    "destinationAddress":  _DEST_ADDR,
                    "amountEth":           "2.5",
                },
            )
        body = resp.json()
        self.assertEqual(body["status"], "draft_ready")
        self.assertEqual(body["transactionTo"], _USDC_MAINNET)
        self.assertEqual(body["unit"], "USDC")
                                            
        self.assertEqual(body["amountBaseUnits"], "2500000")

                                                                        
    def test_S10_broadcast_rejects_extra_fields(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={
                "signedTransaction": _SIGNED_TX,
                "fromAddress":       _FROM_ADDR,
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_S11_broadcast_rejects_plaintext_key_aliases(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        for banned in (
            "privateKey", "seedPhrase", "mnemonic", "recoveryPhrase",
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={
                    "signedTransaction": _SIGNED_TX,
                    banned:              "leaked",
                },
            )
            self.assertEqual(resp.status_code, 422, msg=banned)

    def test_S12_broadcast_forwards_to_mainnet_rpc(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
                                                       
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        )
        captured: list[Any] = []

        def _stub(rpc_url, signed_tx_hex):
            captured.append((rpc_url, signed_tx_hex))
            return _TX_HASH

        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=_stub,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={"signedTransaction": _SIGNED_TX},
            )
        body = resp.json()
        self.assertEqual(body["status"], "submitted")
        self.assertEqual(body["txHash"], _TX_HASH)
        self.assertEqual(body["network"], "Ethereum Mainnet")
                                                   
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0], "https://example.invalid/mainnet")
                                                    
        self.assertEqual(captured[0][1], _SIGNED_TX)

    def test_S13b_broadcast_send_flag_off(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": _SIGNED_TX},
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "mainnet_send_disabled",
        )

    def test_S14_broadcast_rpc_not_configured(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": _SIGNED_TX},
        )
        body = resp.json()
        self.assertEqual(body["status"], "broadcast_unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")

    def test_S15_broadcast_never_fakes_tx_hash(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        from evm_rpc import EvmRpcError
        import evm_rpc

        def _stub_err(rpc_url, signed_tx_hex):
            raise EvmRpcError("upstream_io")

        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=_stub_err,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={"signedTransaction": _SIGNED_TX},
            )
        body = resp.json()
        self.assertEqual(body["status"], "broadcast_unavailable")
        self.assertEqual(body["reason"], "upstream_io")
        self.assertNotIn("txHash", body)

    def test_S10b_broadcast_invalid_hex_refused(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": "not-a-hex-tx"},
        )
        self.assertEqual(resp.status_code, 422)

                                                                      
    def test_S17_status_uses_mainnet_rpc_only(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
                                    
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        )
        captured: list[str] = []

        def _stub(rpc_url, tx_hash):
            captured.append(rpc_url)
            return {"status": "0x1", "blockNumber": "0x1234"}

        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_receipt_at_url",
            side_effect=_stub,
        ):
            resp = self._client.get(
                f"/crypto/wallet/network/ethereum_mainnet/ETH/"
                f"transaction/{_TX_HASH}",
            )
        body = resp.json()
        self.assertEqual(body["status"], "confirmed")
        self.assertEqual(body["txHash"], _TX_HASH)
        self.assertEqual(body["blockNumber"], 0x1234)
        self.assertEqual(captured, ["https://example.invalid/mainnet"])

    def test_S17b_status_pending_when_receipt_null(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )

        def _stub(rpc_url, tx_hash):
            return None

        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_receipt_at_url",
            side_effect=_stub,
        ):
            resp = self._client.get(
                f"/crypto/wallet/network/ethereum_mainnet/ETH/"
                f"transaction/{_TX_HASH}",
            )
        body = resp.json()
        self.assertEqual(body["status"], "pending")

                                                                     
    def test_S18_encrypted_secret_returns_ciphertext(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        )
        self._create_mainnet_eth_record()
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/encrypted-secret",
        )
        body = resp.json()
        self.assertEqual(body["status"], "encrypted_secret_ready")
        self.assertEqual(body["encryptedWalletSecret"], "ct-mainnet-secret")

    def test_S18b_encrypted_secret_no_account(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        )
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/encrypted-secret",
        )
        body = resp.json()
        self.assertEqual(body["status"], "no_account")

    def test_S18c_encrypted_secret_token_shares_eth_record(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        )
        self._create_mainnet_eth_record()
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/"
            "encrypted-secret",
        )
        body = resp.json()
        self.assertEqual(body["status"], "encrypted_secret_ready")
        self.assertEqual(body["encryptedWalletSecret"], "ct-mainnet-secret")

                                                                     
    def test_S23_sepolia_send_routes_unchanged(self) -> None:
                                                                    
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        )
                                                     
        resp = self._client.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  _DEST_ADDR,
                "amountEth":           "0.001",
            },
        )
        body = resp.json()
                                                                      
                                                          
        self.assertNotEqual(resp.status_code, 422)
        self.assertNotEqual(
            body.get("wallet_engine"), "mainnet_send_disabled",
        )
        if body.get("status") == "draft_ready":
            self.assertEqual(body["chainId"], 11155111)
            self.assertEqual(body["network"], "Ethereum Sepolia")


class ChatComposerMainnetSendTests(unittest.TestCase):

    def test_S19_chat_send_on_mainnet_allowed_with_both_flags(self) -> None:
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_SEND_DRAFT,
            WALLET_CHAT_NETWORK_MAINNET,
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
            mainnet_send_enabled=True,
        )
                                                                    
                                                                     
        self.assertEqual(env["intent"], WALLET_CHAT_INTENT_SEND_DRAFT)
        self.assertEqual(env["network"], WALLET_CHAT_NETWORK_MAINNET)
        self.assertEqual(env["asset"], "ETH")
        self.assertEqual(env["destinationAddress"], dest)
        self.assertEqual(env["amount"], "0.01")
                                                               
        msg = env["message"].lower()
        self.assertIn("mainnet", msg)
        self.assertIn("real funds", msg)
        self.assertIn("pin", msg)

    def test_S20_chat_send_on_mainnet_blocked_with_only_receive(self) -> None:
                                                    
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
            mainnet_erc20_receive_enabled=True,
            mainnet_send_enabled=False,
        )
        self.assertEqual(
            env["intent"], WALLET_CHAT_INTENT_UNSUPPORTED_NETWORK,
        )
        self.assertEqual(env["blockedReason"], "mainnet_disabled")
                                                          
        self.assertIsNone(env["destinationAddress"])
        self.assertIsNone(env["amount"])

    def test_S19b_chat_send_usdc_mainnet_with_both_flags(self) -> None:
        from wallet_engine_chat import (
            WALLET_CHAT_INTENT_SEND_DRAFT,
            WALLET_CHAT_NETWORK_MAINNET,
            compose_wallet_engine_chat_envelope,
            parse_wallet_engine_chat_message,
        )
        dest = "0x" + "ab" * 20
        parsed = parse_wallet_engine_chat_message(
            f"send 5 USDC on mainnet to {dest}",
        )
        env = compose_wallet_engine_chat_envelope(
            parsed, engine_enabled=True,
            mainnet_send_enabled=True,
            mainnet_erc20_receive_enabled=True,
        )
        self.assertEqual(env["intent"], WALLET_CHAT_INTENT_SEND_DRAFT)
        self.assertEqual(env["network"], WALLET_CHAT_NETWORK_MAINNET)
        self.assertEqual(env["asset"], "USDC_ERC20")
        self.assertEqual(env["amount"], "5")


class SourceGuardTests(unittest.TestCase):

    def test_S21_evm_rpc_whitelist_is_closed_set(self) -> None:
        from evm_rpc import ALLOWED_RPC_METHODS
        expected = {
            "eth_getBalance", "eth_call",
            "eth_getTransactionCount", "eth_gasPrice",
            "eth_estimateGas", "eth_sendRawTransaction",
            "eth_getTransactionReceipt",
        }
        self.assertEqual(set(ALLOWED_RPC_METHODS), expected)
                                             
        for banned in (
            "personal_sign", "personal_sendTransaction",
            "eth_sign", "eth_signTransaction",
            "eth_sendTransaction",
            "debug_traceTransaction", "debug_traceCall",
        ):
            self.assertNotIn(banned, ALLOWED_RPC_METHODS)

    def test_S21b_evm_rpc_no_signing_imports(self) -> None:
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

    def test_S22_no_hardcoded_mainnet_send_literals(self) -> None:
                                                                    
                                                              
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

    def test_S22b_no_fallback_sepolia_in_mainnet_handlers(self) -> None:
                                                                    
                                    
        src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")
                                                                 
                                                                      
        for helper in (
            "_create_mainnet_send_draft",
            "_broadcast_mainnet_signed_transaction",
            "_get_mainnet_transaction_status",
        ):
                                                                    
                                                                  
            m = re.search(
                rf"^def {re.escape(helper)}\(.*?(?=^def |^@router\.)",
                src, flags=re.DOTALL | re.MULTILINE,
            )
            self.assertIsNotNone(m, msg=f"helper {helper} not found")
            body = m.group(0)
            self.assertNotIn(
                "ethereum_sepolia_rpc_url", body,
                msg=f"{helper} must not import Sepolia RPC URL",
            )
            self.assertNotIn(
                "ethereum_sepolia_proxy", body,
                msg=f"{helper} must not import Sepolia proxy",
            )

    def test_S16_route_logger_no_signed_tx_or_address(self) -> None:
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
                "signedTransaction",
                "signed_tx_hex",
                "destinationAddress",
                "fromAddress",
                "amountEth",
                "amountBaseUnits",
                "dataHex",
                "encryptedWalletSecret",
                "rpc_url", "api_key",
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
