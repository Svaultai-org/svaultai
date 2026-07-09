

from __future__ import annotations

import io
import json
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


class SepoliaRpcConfigTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env("ETHEREUM_SEPOLIA_RPC_URL")

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_unset_env_returns_empty_string(self) -> None:
        from vault_config import ethereum_sepolia_rpc_url
        self.assertEqual(ethereum_sepolia_rpc_url(), "")

    def test_set_env_returns_verbatim(self) -> None:
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = (
            "https://sepolia.infura.io/v3/some-key"
        )
        from vault_config import ethereum_sepolia_rpc_url
        self.assertEqual(
            ethereum_sepolia_rpc_url(),
            "https://sepolia.infura.io/v3/some-key",
        )


class SepoliaProxyWhitelistTests(unittest.TestCase):


    def test_eth_getBalance_remains_in_whitelist(self) -> None:
        from ethereum_sepolia_proxy import ALLOWED_RPC_METHODS
        self.assertIn("eth_getBalance", ALLOWED_RPC_METHODS)

    def test_method_not_in_whitelist_raises_method_forbidden(self) -> None:
                                                                   
                                                          
        from ethereum_sepolia_proxy import SepoliaProxyError, _emit_rpc
        with patch.dict(
            os.environ,
            {"ETHEREUM_SEPOLIA_RPC_URL": "https://example.com"},
            clear=False,
        ):
            with self.assertRaises(SepoliaProxyError) as cm:
                                                                 
                                                                   
                _emit_rpc("personal_sendTransaction", [])
        self.assertEqual(cm.exception.code, "method_forbidden")


class SepoliaAddressValidationTests(unittest.TestCase):

    def test_valid_addresses(self) -> None:
        from ethereum_sepolia_proxy import is_valid_eth_address
                                                             
        self.assertTrue(
            is_valid_eth_address("0x" + "a" * 40),
        )
        self.assertTrue(
            is_valid_eth_address("0x" + "1234567890abcdef" * 2 + "12345678"),
        )

    def test_invalid_addresses(self) -> None:
        from ethereum_sepolia_proxy import is_valid_eth_address
        for bad in (
            "",
            "0x",
            "0xZZZ",
            "0x" + "g" * 40,                          
            "0x" + "a" * 39,                   
            "0x" + "a" * 41,                  
            "a" * 40,                                   
            None,
            42,
        ):
            self.assertFalse(
                is_valid_eth_address(bad),
                f"{bad!r} must NOT be valid",
            )


class SepoliaBalanceUnconfiguredEnvTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env("ETHEREUM_SEPOLIA_RPC_URL")

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_balance_raises_not_configured(self) -> None:
        from ethereum_sepolia_proxy import (
            eth_get_balance_wei, SepoliaProxyError,
        )
        with self.assertRaises(SepoliaProxyError) as cm:
            eth_get_balance_wei("0x" + "1" * 40)
        self.assertEqual(cm.exception.code, "not_configured")


def _override_principal():
    from main import app
    from device_gate import verify_trusted_device
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": "test-vault-uuid", "account_id": "test-account",
    }
    return app


def _restore_overrides(app, prior):
    from device_gate import verify_trusted_device
    if prior is None:
        app.dependency_overrides.pop(verify_trusted_device, None)
    else:
        app.dependency_overrides[verify_trusted_device] = prior


class BalanceRouteHonestStateTests(unittest.TestCase):

    def setUp(self) -> None:
        self._env_snap = _wipe_env(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            "ETHEREUM_SEPOLIA_RPC_URL",
        )
                                                                 
                                                                    
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "false"
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
        _restore_overrides(self._app, self._prior)
        _restore_env(self._env_snap)
        import vault_config
        vault_config.reset_for_tests()

    def _client(self) -> TestClient:
        return TestClient(self._app)

    def test_flag_off_disabled_envelope_no_balance_fields(self) -> None:
        c = self._client()
        resp = c.get("/crypto/wallet/ETH/balance")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "engine_disabled")
        self.assertNotIn("availableAmount", body)
        self.assertNotIn("balanceStatus", body)

    def test_flag_on_eth_no_rpc_returns_unavailable_reason(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
                                                      
        import vault_config
        vault_config.reset_for_tests()
        c = self._client()
        resp = c.get(
            "/crypto/wallet/ETH/balance?address=0x" + "1" * 40,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")
        self.assertIsNone(body["availableAmount"])
        self.assertIsNone(body["unit"])

    def test_flag_on_eth_invalid_address_returns_unavailable(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        c = self._client()
        resp = c.get("/crypto/wallet/ETH/balance?address=not-an-address")
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "unavailable")
        self.assertEqual(body["reason"], "invalid_address")
        self.assertIsNone(body["availableAmount"])

    def test_flag_on_btc_still_not_ready(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        c = self._client()
        resp = c.get("/crypto/wallet/BTC/balance")
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "engine_not_ready")
        self.assertNotIn("availableAmount", body)


class ReceiveRouteNoAccountTests(unittest.TestCase):

    def setUp(self) -> None:
        self._env_snap = _wipe_env(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
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
        _restore_overrides(self._app, self._prior)
        _restore_env(self._env_snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_no_account_returns_closed_set_envelope(self) -> None:
                                                                
                                                              
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=None,
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/ETH/receive")
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "no_account")
        self.assertEqual(body["asset"], "ETH")
        self.assertNotIn("publicAddress", body)
        self.assertNotIn("encryptedWalletSecret", body)

    def test_receive_existing_account_does_not_echo_encrypted_secret(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        fake_record = {
            "schema": "crypto_wallet_account_v1",
            "asset": "ETH",
            "network": "Ethereum Sepolia",
            "walletLabel": "my eth wallet",
            "publicAddress": "0x" + "a" * 40,
            "encryptedWalletSecret": "VERY-PRIVATE-CIPHERTEXT-XYZ",
            "keyOrigin": "generated_client_side",
            "signingMode": "client_side",
            "backupStatus": "encrypted_backup_saved",
        }
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=fake_record,
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/ETH/receive")
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "receive_ready")
                                                   
        flat = json.dumps(body)
        self.assertNotIn("VERY-PRIVATE-CIPHERTEXT-XYZ", flat)
        self.assertNotIn("encryptedWalletSecret", flat)

    def _client(self) -> TestClient:
        return TestClient(self._app)


class CreateRouteValidationTests(unittest.TestCase):

    def setUp(self) -> None:
        self._env_snap = _wipe_env(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
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
        _restore_overrides(self._app, self._prior)
        _restore_env(self._env_snap)
        import vault_config
        vault_config.reset_for_tests()

    def _client(self) -> TestClient:
        return TestClient(self._app)

    def test_invalid_public_address_rejected_with_422(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/create",
            json={
                "walletLabel":           "x",
                "publicAddress":         "not-an-address",
                "network":               "Ethereum Sepolia",
                "encryptedWalletSecret": "ct-xxxxx",
            },
        )
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(
            body["detail"]["wallet_engine"], "invalid_public_address",
        )

    def test_unknown_network_rejected_with_422(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/create",
            json={
                "walletLabel":           "x",
                "publicAddress":         "0x" + "a" * 40,
                "network":               "Ethereum Mainnet",               
                "encryptedWalletSecret": "ct-xxxxx",
            },
        )
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(
            body["detail"]["wallet_engine"], "unsupported_network",
        )

    def test_plaintext_key_field_still_rejected(self) -> None:
                                                                 
                                                            
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/ETH/create",
            json={
                "walletLabel":           "x",
                "publicAddress":         "0x" + "a" * 40,
                "network":               "Ethereum Sepolia",
                "encryptedWalletSecret": "ct-xxxxx",
                "privateKey":            "0xdeadbeef",             
            },
        )
        self.assertEqual(resp.status_code, 422)


class TransactionsHonestEmptyTests(unittest.TestCase):

    def setUp(self) -> None:
        self._env_snap = _wipe_env(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
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
        _restore_overrides(self._app, self._prior)
        _restore_env(self._env_snap)
        import vault_config
        vault_config.reset_for_tests()

    def test_engine_on_eth_transactions_empty_list(self) -> None:
                                                               
                                                                   
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        import vault_config
        vault_config.reset_for_tests()
        from routes import crypto_wallet_routes as wallet_module
        orig_loader = wallet_module._load_wallet_account_record
        wallet_module._load_wallet_account_record = lambda v, a: None
        try:
            c = TestClient(self._app)
            resp = c.get("/crypto/wallet/ETH/transactions")
        finally:
            wallet_module._load_wallet_account_record = orig_loader
        body = resp.json()
                                                               
                                                                 
        self.assertEqual(body.get("status"), "ok")
        self.assertEqual(body.get("transactionsStatus"), "unavailable")
        self.assertIn(
            body.get("reason"),
            {"no_wallet_yet", "indexer_not_configured", "invalid_address"},
        )
        self.assertEqual(body["transactions"], [])


class SepoliaProxySourceGuardTests(unittest.TestCase):

    def test_proxy_module_never_logs_url_or_address_value(self) -> None:
        path = _BACKEND_ROOT / "ethereum_sepolia_proxy.py"
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
                                                                  
                                                                 
        forbidden_substrings = (
            "logger.warning(url",
            "logger.info(url",
            "logger.warning(addr",
            "logger.info(addr",
            "url=%s",
            "addr=%s",
            "address=%s",
        )
        for needle in forbidden_substrings:
            self.assertNotIn(
                needle, src,
                f"ethereum_sepolia_proxy.py must not log {needle!r}",
            )

    def test_proxy_module_has_no_fallback_synthesised_balance(self) -> None:
                                                                  
                                                                    
        path = _BACKEND_ROOT / "ethereum_sepolia_proxy.py"
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
                                                                   
                                                               
        import re
        bad = re.findall(r"return\s+\d+\s*(?:#|$)", src, re.MULTILINE)
        self.assertEqual(
            bad, [],
            f"ethereum_sepolia_proxy must not return a synthesised "
            f"integer balance: {bad}",
        )


if __name__ == "__main__":
    unittest.main()
