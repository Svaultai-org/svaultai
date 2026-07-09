

from __future__ import annotations

import io
import os
import re
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


class SepoliaProxyWhitelistSlice3Tests(unittest.TestCase):

    def test_whitelist_includes_slice3_six_methods(self) -> None:
                                                                   
                                                                  
        from ethereum_sepolia_proxy import ALLOWED_RPC_METHODS
        for method in (
            "eth_getBalance",
            "eth_getTransactionCount",
            "eth_gasPrice",
            "eth_estimateGas",
            "eth_sendRawTransaction",
            "eth_getTransactionReceipt",
        ):
            self.assertIn(method, ALLOWED_RPC_METHODS)

    def test_sepolia_chain_id_is_pinned(self) -> None:
        from ethereum_sepolia_proxy import SEPOLIA_CHAIN_ID
        self.assertEqual(SEPOLIA_CHAIN_ID, 11155111)


class SepoliaProxyShapeValidationTests(unittest.TestCase):

    def test_signed_tx_hex_shapes(self) -> None:
        from ethereum_sepolia_proxy import is_valid_signed_tx_hex
                                    
        self.assertTrue(is_valid_signed_tx_hex("0x" + "a" * 200))
                             
        self.assertFalse(is_valid_signed_tx_hex("0x" + "a" * 10))
                                
        self.assertFalse(is_valid_signed_tx_hex("a" * 200))
                                 
        self.assertFalse(is_valid_signed_tx_hex("0x" + "z" * 200))
                              
        self.assertFalse(is_valid_signed_tx_hex(None))
        self.assertFalse(is_valid_signed_tx_hex(42))

    def test_tx_hash_shapes(self) -> None:
        from ethereum_sepolia_proxy import is_valid_tx_hash
        self.assertTrue(is_valid_tx_hash("0x" + "1" * 64))
        self.assertFalse(is_valid_tx_hash("0x" + "1" * 63))
        self.assertFalse(is_valid_tx_hash("0x" + "1" * 65))
        self.assertFalse(is_valid_tx_hash("1" * 64))
        self.assertFalse(is_valid_tx_hash(None))


class _AuthedRouteCase(unittest.TestCase):

    def setUp(self) -> None:
        self._env_snap = _wipe_env(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            "ETHEREUM_SEPOLIA_RPC_URL",
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


class SendDraftRouteTests(_AuthedRouteCase):

    def test_T5_draft_refuses_plaintext_private_key(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "0.01",
                "privateKey":         "0xdeadbeef",             
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_T5b_draft_refuses_seed_phrase(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "0.01",
                "seedPhrase":         "twelve words ...",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_T6_draft_refuses_extra_field(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "0.01",
                "extra":              "not allowed",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_T7_draft_refuses_bad_destination_address(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "not-an-address",
                "amountEth":          "0.01",
            },
        )
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(
            body["detail"]["wallet_engine"],
            "invalid_destination_address",
        )

    def test_T8_draft_refuses_zero_or_negative_amount(self) -> None:
        self._enable_engine()
        c = self._client()
        for amt in ("0", "0.0", "-1", "not-a-number", ""):
            resp = c.post(
                "/crypto/wallet/ETH/send/draft",
                json={
                    "fromAddress":        "0x" + "a" * 40,
                    "destinationAddress": "0x" + "b" * 40,
                    "amountEth":          amt,
                },
            )
                                                                 
                                                         
            self.assertEqual(resp.status_code, 422, msg=amt)

    def test_T9_draft_refuses_self_send(self) -> None:
        self._enable_engine()
        c = self._client()
        addr = "0x" + "a" * 40
        resp = c.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":        addr,
                "destinationAddress": addr,
                "amountEth":          "0.01",
            },
        )
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(
            body["detail"]["wallet_engine"], "self_send_refused",
        )

    def test_T10_draft_unavailable_when_rpc_unset(self) -> None:
        self._enable_engine()
                                                      
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "0.01",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "draft_unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")
                                                 
        self.assertNotIn("nonce", body)
        self.assertNotIn("gasPrice", body)

    def test_T11_draft_surfaces_rpc_error_code(self) -> None:
                                                              
                                                                  
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        from ethereum_sepolia_proxy import SepoliaProxyError
        with patch(
            "ethereum_sepolia_proxy.eth_get_transaction_count",
            side_effect=SepoliaProxyError("upstream_timeout"),
        ):
            c = self._client()
            resp = c.post(
                "/crypto/wallet/ETH/send/draft",
                json={
                    "fromAddress":        "0x" + "a" * 40,
                    "destinationAddress": "0x" + "b" * 40,
                    "amountEth":          "0.01",
                },
            )
        body = resp.json()
        self.assertEqual(body["status"], "draft_unavailable")
        self.assertEqual(body["reason"], "upstream_timeout")

    def test_draft_returns_no_private_key_or_secret(self) -> None:
                                                                  
                                                    
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "0.01",
            },
        )
        body = resp.json()
        flat = str(body)
        self.assertNotIn("privateKey", flat)
        self.assertNotIn("encryptedWalletSecret", flat)
        self.assertNotIn("seedPhrase", flat)


class BroadcastRouteTests(_AuthedRouteCase):

    def test_T12_broadcast_refuses_plaintext_private_key(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/broadcast",
            json={
                "signedTransaction": "0x" + "a" * 200,
                "privateKey":        "0xdeadbeef",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_T13_broadcast_refuses_extra_field(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/broadcast",
            json={
                "signedTransaction": "0x" + "a" * 200,
                "fromAddress":       "0x" + "b" * 40,
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_T14_broadcast_refuses_bad_hex_shape(self) -> None:
        self._enable_engine()
        c = self._client()
        for bad in (
            "0x" + "a" * 10,                    
            "a" * 200,                             
            "0x" + "z" * 200,                 
        ):
            resp = c.post(
                "/crypto/wallet/ETH/send/broadcast",
                json={"signedTransaction": bad},
            )
            self.assertEqual(resp.status_code, 422, msg=bad)

    def test_T15_broadcast_unavailable_when_rpc_unset(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/send/broadcast",
            json={"signedTransaction": "0x" + "a" * 200},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "broadcast_unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")
                                                 
        self.assertNotIn("txHash", body)

    def test_broadcast_uses_eth_send_raw_transaction_only(self) -> None:
                                                                  
                                                                  
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        fake_hash = "0x" + "f" * 64
        with patch(
            "ethereum_sepolia_proxy.eth_send_raw_transaction",
            return_value=fake_hash,
        ) as mock:
            c = self._client()
            resp = c.post(
                "/crypto/wallet/ETH/send/broadcast",
                json={"signedTransaction": "0x" + "a" * 200},
            )
        body = resp.json()
        self.assertEqual(body["status"], "submitted")
        self.assertEqual(body["txHash"], fake_hash)
        mock.assert_called_once_with("0x" + "a" * 200)


class TransactionStatusRouteTests(_AuthedRouteCase):

    def test_T16_status_refuses_bad_tx_hash(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.get("/crypto/wallet/ETH/transaction/not-a-hash")
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(
            body["detail"]["wallet_engine"], "invalid_tx_hash",
        )

    def test_status_unavailable_when_rpc_unset(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.get("/crypto/wallet/ETH/transaction/0x" + "f" * 64)
        body = resp.json()
        self.assertEqual(body["status"], "unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")
                                                            
        self.assertNotIn("blockNumber", body)

    def test_status_pending_when_upstream_returns_null(self) -> None:
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        with patch(
            "ethereum_sepolia_proxy.eth_get_transaction_receipt",
            return_value=None,
        ):
            c = self._client()
            resp = c.get(
                "/crypto/wallet/ETH/transaction/0x" + "f" * 64,
            )
        body = resp.json()
        self.assertEqual(body["status"], "pending")

    def test_status_confirmed_when_upstream_returns_success(self) -> None:
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        with patch(
            "ethereum_sepolia_proxy.eth_get_transaction_receipt",
            return_value={"status": "0x1", "blockNumber": "0x1234"},
        ):
            c = self._client()
            resp = c.get(
                "/crypto/wallet/ETH/transaction/0x" + "f" * 64,
            )
        body = resp.json()
        self.assertEqual(body["status"], "confirmed")
        self.assertEqual(body["blockNumber"], 0x1234)

    def test_status_failed_when_upstream_returns_failure(self) -> None:
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        with patch(
            "ethereum_sepolia_proxy.eth_get_transaction_receipt",
            return_value={"status": "0x0", "blockNumber": "0x1"},
        ):
            c = self._client()
            resp = c.get(
                "/crypto/wallet/ETH/transaction/0x" + "f" * 64,
            )
        body = resp.json()
        self.assertEqual(body["status"], "failed")


class EncryptedSecretRouteTests(_AuthedRouteCase):

    def test_T17_returns_encrypted_secret_verbatim(self) -> None:
        self._enable_engine()
        fake_record = {
            "schema": "crypto_wallet_account_v1",
            "asset": "ETH",
            "encryptedWalletSecret": "CT-XYZ-VERY-PRIVATE-CIPHERTEXT",
        }
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=fake_record,
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/ETH/encrypted-secret")
        body = resp.json()
        self.assertEqual(body["status"], "encrypted_secret_ready")
        self.assertEqual(body["asset"], "ETH")
        self.assertEqual(
            body["encryptedWalletSecret"],
            "CT-XYZ-VERY-PRIVATE-CIPHERTEXT",
        )

    def test_T18_returns_no_account_when_missing(self) -> None:
        self._enable_engine()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=None,
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/ETH/encrypted-secret")
        body = resp.json()
        self.assertEqual(body["status"], "no_account")
        self.assertNotIn("encryptedWalletSecret", body)

    def test_returns_no_account_when_record_lacks_secret(self) -> None:
        self._enable_engine()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value={
                "schema": "crypto_wallet_account_v1",
                "asset": "ETH",
                                                 
            },
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/ETH/encrypted-secret")
        body = resp.json()
        self.assertEqual(body["status"], "no_account")


class RouteSourceGuardTests(unittest.TestCase):

    def _route_src(self) -> str:
        path = _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        with io.open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_T19_no_signing_library_call_in_route_module(self) -> None:
                                                              
                                                        
        src = self._route_src()
        forbidden = (
            "import secp256k1",
            "from secp256k1",
            "import keccak",
            "from keccak",
            "import rlp",
            "from rlp",
            "import eth_keys",
            "from eth_keys",
            "import eth_account",
            "from eth_account",
            "import web3",
            "from web3",
                                         
            "pointycastle",
        )
        for needle in forbidden:
            self.assertNotIn(
                needle, src,
                f"crypto_wallet_routes.py must not import {needle!r}",
            )

    def test_T20_broadcast_does_not_log_raw_signed_tx(self) -> None:
        src = self._route_src()
                                                                 
                                                                
        forbidden_substrings = (
            "logger.info(payload.signedTransaction",
            "logger.warning(payload.signedTransaction",
            "logger.info(signed_tx",
            "logger.warning(signed_tx",
            "%s\", payload.signedTransaction",
            "%s\", signed_tx",
        )
        for needle in forbidden_substrings:
            self.assertNotIn(
                needle, src,
                f"Broadcast handler must not log raw signed tx "
                f"({needle!r})",
            )

    def test_T21_no_fake_tx_hash_literal(self) -> None:
                                                               
                       
        src = self._route_src()
        matches = re.findall(r'"0x[0-9a-fA-F]{64}"', src)
        self.assertEqual(
            matches, [],
            f"crypto_wallet_routes.py must not contain a fake tx "
            f"hash literal: {matches}",
        )


if __name__ == "__main__":
    unittest.main()
