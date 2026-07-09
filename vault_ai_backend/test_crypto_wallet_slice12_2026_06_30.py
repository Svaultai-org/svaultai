

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
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED",
    "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT",
    "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
    "ETHEREUM_SEPOLIA_RPC_URL",
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


def _make_app_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as wallet_module
    from routes.crypto_wallet_routes import (
        router,
        reset_mainnet_safety_state_for_tests,
        verify_trusted_device,
    )
    reset_mainnet_safety_state_for_tests()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": "test-vault-id-slice12",
    }
    return TestClient(app), app, wallet_module


_FROM_ADDR = "0x" + "ab" * 20
_DEST_ADDR = "0x" + "cd" * 20
_SIGNED_TX = "0x" + "ee" * 120
_SIGNED_TX_ALT = "0x" + "ff" * 120
_TX_HASH = "0x" + "12" * 32
_TX_HASH_2 = "0x" + "34" * 32
_VALID_IDEM = "test-idem-key-001"


class FlagDefaultsTests(unittest.TestCase):

    def setUp(self) -> None:
        _clear_all_env()

    def tearDown(self) -> None:
        _clear_all_env()

    def test_H1_pause_default_false(self) -> None:
        from vault_config import ethereum_mainnet_send_paused
        self.assertFalse(ethereum_mainnet_send_paused())
        _set_env(VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="true")
        self.assertTrue(ethereum_mainnet_send_paused())

    def test_H1b_rate_limit_default_3_per_60s(self) -> None:
        from vault_config import (
            ethereum_mainnet_broadcast_rate_limit,
            ethereum_mainnet_broadcast_rate_window_secs,
        )
        self.assertEqual(ethereum_mainnet_broadcast_rate_limit(), 3)
        self.assertEqual(
            ethereum_mainnet_broadcast_rate_window_secs(), 60,
        )


class MainnetSendSafetyRouteTests(unittest.TestCase):

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
        self._wallet_mod.reset_mainnet_safety_state_for_tests()
        _clear_all_env()

                                                                       
    def test_H2_pause_blocks_send_draft(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":        _FROM_ADDR,
                "destinationAddress": _DEST_ADDR,
                "amountEth":          "0.01",
            },
        )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "mainnet_send_paused",
        )
                                                                 
        body_str = str(body)
        self.assertNotIn(_DEST_ADDR, body_str)
        self.assertNotIn("0.01", body_str)

    def test_H3_pause_blocks_broadcast(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
                                                                 
        from evm_rpc import EvmRpcError
        import evm_rpc

        call_count = {"n": 0}

        def _stub(rpc_url, signed_tx_hex):
            call_count["n"] += 1
            return _TX_HASH

        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=_stub,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={"signedTransaction": _SIGNED_TX},
            )
        body = resp.json()
        self.assertEqual(
            body.get("wallet_engine"), "mainnet_send_paused",
        )
                                                
        self.assertEqual(call_count["n"], 0)
                                   
        self.assertNotIn("txHash", body)

    def test_H4_pause_does_not_affect_receive_balance_activity(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
                                    
        self._store[("vault", "ETH:ethereum_mainnet")] = {
            "asset":         "ETH",
            "network":       "ethereum_mainnet",
            "walletLabel":   "VaultAI ETH",
            "publicAddress": _FROM_ADDR,
            "encryptedWalletSecret": "ct",
            "keyOrigin":     "generated_client_side",
            "signingMode":   "client_side",
            "backupStatus":  "encrypted_backup_saved",
        }
                              
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/receive",
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "receive_ready")
                                    
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/receive",
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "receive_ready")

                                                                      
    def test_H5_H6_rate_limit_triggers_429_with_retry_after(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT="2",
            VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS="60",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=lambda u, s: _TX_HASH,
        ):
                              
            for i in range(2):
                resp = self._client.post(
                    "/crypto/wallet/network/ethereum_mainnet/"
                    "ETH/send/broadcast",
                    json={
                        "signedTransaction": "0x" + (str(i) * 2 + "ab") * 60,
                    },
                )
                self.assertEqual(resp.status_code, 200, msg=i)
                                           
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={"signedTransaction": _SIGNED_TX},
            )
        self.assertEqual(resp.status_code, 429)
        self.assertIn("retry-after", {k.lower() for k in resp.headers})
        body = resp.json()
                                                               
        detail = body.get("detail", body)
        self.assertEqual(detail.get("wallet_engine"), "rate_limited")
        self.assertIn("retryAfterSeconds", detail)
                                                           
                              
        body_str = str(body)
        self.assertNotIn(_SIGNED_TX, body_str)
        self.assertNotIn(_DEST_ADDR, body_str)
        self.assertNotIn(_FROM_ADDR, body_str)

    def test_H5b_zero_rate_limit_disables_limiter(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT="0",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=lambda u, s: _TX_HASH,
        ):
                                                             
            for i in range(5):
                resp = self._client.post(
                    "/crypto/wallet/network/ethereum_mainnet/"
                    "ETH/send/broadcast",
                    json={
                        "signedTransaction": "0x" + (str(i) * 2 + "ab") * 60,
                    },
                )
                self.assertEqual(resp.status_code, 200)

                                                                      
    def test_H7_broadcast_accepts_idempotency_key(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=lambda u, s: _TX_HASH,
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={
                    "signedTransaction": _SIGNED_TX,
                    "idempotencyKey":    _VALID_IDEM,
                },
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "submitted")
        self.assertEqual(body["txHash"], _TX_HASH)

    def test_H7b_broadcast_still_rejects_other_extras(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={
                "signedTransaction": _SIGNED_TX,
                "idempotencyKey":    _VALID_IDEM,
                "fromAddress":       _FROM_ADDR,
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_H8_duplicate_idempotency_key_returns_same_envelope(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        import evm_rpc
        call_count = {"n": 0}

        def _stub(rpc_url, signed_tx_hex):
            call_count["n"] += 1
            return _TX_HASH

        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=_stub,
        ):
                                 
            resp1 = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={
                    "signedTransaction": _SIGNED_TX,
                    "idempotencyKey":    _VALID_IDEM,
                },
            )
                                                                      
                                                  
            resp2 = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={
                    "signedTransaction": _SIGNED_TX,
                    "idempotencyKey":    _VALID_IDEM,
                },
            )
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp1.json(), resp2.json())
                                      
        self.assertEqual(call_count["n"], 1)

    def test_H9_duplicate_key_different_payload_rejected(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=lambda u, s: _TX_HASH,
        ):
            resp1 = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={
                    "signedTransaction": _SIGNED_TX,
                    "idempotencyKey":    _VALID_IDEM,
                },
            )
            self.assertEqual(resp1.status_code, 200)
                                                 
            resp2 = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={
                    "signedTransaction": _SIGNED_TX_ALT,
                    "idempotencyKey":    _VALID_IDEM,
                },
            )
        self.assertEqual(resp2.status_code, 409)
        body = resp2.json()
        detail = body.get("detail", body)
        self.assertEqual(
            detail.get("wallet_engine"), "idempotency_conflict",
        )
                                                               
        body_str = str(body)
        self.assertNotIn(_SIGNED_TX, body_str)
        self.assertNotIn(_SIGNED_TX_ALT, body_str)

    def test_H10_malformed_idempotency_key_returns_422(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
                    
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={
                "signedTransaction": _SIGNED_TX,
                "idempotencyKey":    "abc",
            },
        )
        self.assertEqual(resp.status_code, 422)
                          
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={
                "signedTransaction": _SIGNED_TX,
                "idempotencyKey":    "bad spaces here oh no",
            },
        )
        self.assertEqual(resp.status_code, 422)

                                                                       
    def test_H11_plaintext_key_aliases_still_rejected(self) -> None:
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
                    "idempotencyKey":    _VALID_IDEM,
                    banned:              "leaked-value",
                },
            )
            self.assertEqual(resp.status_code, 422, msg=banned)

                                                                       
    def test_H12_draft_errors_do_not_echo_destination_or_amount(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
                                                      
        )
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":        _FROM_ADDR,
                "destinationAddress": _DEST_ADDR,
                "amountEth":          "0.01",
            },
        )
        body_str = str(resp.json())
        self.assertNotIn(_DEST_ADDR, body_str)
        self.assertNotIn(_FROM_ADDR, body_str)
        self.assertNotIn("0.01", body_str)

    def test_H13_broadcast_errors_do_not_echo_signed_tx(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        from evm_rpc import EvmRpcError
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=lambda u, s: (_ for _ in ()).throw(
                EvmRpcError("upstream_io"),
            ),
        ):
            resp = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={"signedTransaction": _SIGNED_TX},
            )
        body_str = str(resp.json())
        self.assertNotIn(_SIGNED_TX, body_str)

                                                                       
    def test_H14_logs_redact_signed_tx_address_amount(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        from logging import getLogger
        import io, logging
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        logger = getLogger("crypto_wallet_routes")
        prev = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            import evm_rpc
            with mock.patch.object(
                evm_rpc, "eth_send_raw_transaction_at_url",
                side_effect=lambda u, s: _TX_HASH,
            ):
                self._client.post(
                    "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                    json={
                        "signedTransaction": _SIGNED_TX,
                        "idempotencyKey":    _VALID_IDEM,
                    },
                )
            logs = stream.getvalue()
                                             
            self.assertNotIn(_SIGNED_TX, logs)
                                              
            self.assertNotIn(_VALID_IDEM, logs)
                                                                     
                                                                 
            self.assertNotIn(_FROM_ADDR, logs)
            self.assertNotIn(_DEST_ADDR, logs)
                                                               
            self.assertNotIn(_TX_HASH, logs)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(prev)

                                                                       
    def test_H15_sepolia_send_unaffected_by_pause(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_SEND_PAUSED="true",
            ETHEREUM_SEPOLIA_RPC_URL="https://example.invalid/sepolia",
        )
        resp = self._client.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":        _FROM_ADDR,
                "destinationAddress": _DEST_ADDR,
                "amountEth":          "0.01",
            },
        )
                                                                   
        body = resp.json()
        self.assertNotEqual(
            body.get("wallet_engine"), "mainnet_send_paused",
        )

                                                                      
    def test_H16_reset_clears_state(self) -> None:
        _set_env(
            VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
            VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
            VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT="1",
            ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        )
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=lambda u, s: _TX_HASH,
        ):
                                        
            r1 = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={"signedTransaction": _SIGNED_TX},
            )
            self.assertEqual(r1.status_code, 200)
                                       
            r2 = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={"signedTransaction": _SIGNED_TX_ALT},
            )
            self.assertEqual(r2.status_code, 429)
                                   
            self._wallet_mod.reset_mainnet_safety_state_for_tests()
            r3 = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
                json={"signedTransaction": _SIGNED_TX_ALT},
            )
            self.assertEqual(r3.status_code, 200)


class SourceGuardTests(unittest.TestCase):

    def test_H17_route_source_has_no_signing_imports(self) -> None:
        src = (_BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
            ).read_text(encoding="utf-8")
        scrubbed = re.sub(r"#.*$", "", src, flags=re.MULTILINE)
        scrubbed = re.sub(
            r'"""(.*?)"""', "", scrubbed, flags=re.DOTALL,
        )
        for banned in (
            "import eth_account", "from eth_account",
            "import web3", "from web3",
            "import eth_keys", "from eth_keys",
        ):
            self.assertNotIn(
                banned, scrubbed,
                msg=f"route source imports signing module: {banned}",
            )

    def test_H17b_no_hardcoded_tx_hash_or_address_in_safety_block(self) -> None:
        src = (_BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
            ).read_text(encoding="utf-8")
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
                "route source contains hardcoded 0x literal: "
                f"{m.group(0)}",
            )


if __name__ == "__main__":
    unittest.main()
