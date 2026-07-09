

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


class ProxyWhitelistAndSelectorsTests(unittest.TestCase):

    def test_whitelist_includes_eth_call(self) -> None:
        from ethereum_sepolia_proxy import ALLOWED_RPC_METHODS
        self.assertIn("eth_call", ALLOWED_RPC_METHODS)
                                                 
        for m in (
            "eth_getBalance", "eth_getTransactionCount", "eth_gasPrice",
            "eth_estimateGas", "eth_sendRawTransaction",
            "eth_getTransactionReceipt",
        ):
            self.assertIn(m, ALLOWED_RPC_METHODS)
                                       
        self.assertEqual(len(ALLOWED_RPC_METHODS), 7)

    def test_erc20_selectors_pinned(self) -> None:
        from ethereum_sepolia_proxy import (
            ERC20_SELECTOR_BALANCE_OF, ERC20_SELECTOR_TRANSFER,
        )
        self.assertEqual(ERC20_SELECTOR_BALANCE_OF, "0x70a08231")
        self.assertEqual(ERC20_SELECTOR_TRANSFER,   "0xa9059cbb")


class CalldataEncoderTests(unittest.TestCase):

    def test_transfer_calldata_shape(self) -> None:
        from ethereum_sepolia_proxy import encode_erc20_transfer_calldata
                                                                  
                                  
        addr = "0x" + "a" * 40
        calldata = encode_erc20_transfer_calldata(
            destination_address=addr,
            amount_base_units=1_000_000,
        )
                                                                      
        self.assertEqual(len(calldata), 2 + 8 + 64 + 64)
                          
        self.assertTrue(calldata.startswith("0xa9059cbb"))
                                                                 
                       
        addr_segment = calldata[10:10 + 64]
        self.assertEqual(addr_segment, "0" * 24 + "a" * 40)
                                                               
        amount_segment = calldata[10 + 64:]
        self.assertEqual(amount_segment, format(1_000_000, "064x"))

    def test_balance_of_calldata_shape(self) -> None:
        from ethereum_sepolia_proxy import encode_erc20_balance_of_calldata
        addr = "0x" + "b" * 40
        calldata = encode_erc20_balance_of_calldata(addr)
                                                  
        self.assertEqual(len(calldata), 2 + 8 + 64)
        self.assertTrue(calldata.startswith("0x70a08231"))

    def test_encoders_refuse_bad_inputs(self) -> None:
        from ethereum_sepolia_proxy import (
            encode_erc20_transfer_calldata,
            encode_erc20_balance_of_calldata,
            SepoliaProxyError,
        )
                      
        with self.assertRaises(SepoliaProxyError):
            encode_erc20_balance_of_calldata("not-an-address")
        with self.assertRaises(SepoliaProxyError):
            encode_erc20_transfer_calldata(
                destination_address="not-an-address",
                amount_base_units=1,
            )
                          
        with self.assertRaises(SepoliaProxyError):
            encode_erc20_transfer_calldata(
                destination_address="0x" + "a" * 40,
                amount_base_units=-1,
            )
                   
        with self.assertRaises(SepoliaProxyError):
            encode_erc20_transfer_calldata(
                destination_address="0x" + "a" * 40,
                amount_base_units=1 << 256,
            )


class TokenEnvAccessorTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(
            "ETH_SEPOLIA_USDT_CONTRACT_ADDRESS",
            "ETH_SEPOLIA_USDC_CONTRACT_ADDRESS",
            "ETH_SEPOLIA_USDT_DECIMALS",
            "ETH_SEPOLIA_USDC_DECIMALS",
        )

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_contract_returns_empty_when_unset(self) -> None:
        from vault_config import ethereum_sepolia_token_contract
        self.assertEqual(ethereum_sepolia_token_contract("USDT_ERC20"), "")
        self.assertEqual(ethereum_sepolia_token_contract("USDC_ERC20"), "")

    def test_contract_returns_verbatim_when_set(self) -> None:
        os.environ["ETH_SEPOLIA_USDT_CONTRACT_ADDRESS"] = "0xUSDTcontract"
        from vault_config import ethereum_sepolia_token_contract
        self.assertEqual(
            ethereum_sepolia_token_contract("USDT_ERC20"),
            "0xUSDTcontract",
        )

    def test_decimals_defaults_to_six(self) -> None:
        from vault_config import ethereum_sepolia_token_decimals
        self.assertEqual(ethereum_sepolia_token_decimals("USDT_ERC20"), 6)
        self.assertEqual(ethereum_sepolia_token_decimals("USDC_ERC20"), 6)

    def test_decimals_honors_env_override(self) -> None:
        os.environ["ETH_SEPOLIA_USDT_DECIMALS"] = "8"
        from vault_config import ethereum_sepolia_token_decimals
        self.assertEqual(ethereum_sepolia_token_decimals("USDT_ERC20"), 8)

    def test_decimals_falls_back_on_garbage(self) -> None:
        os.environ["ETH_SEPOLIA_USDT_DECIMALS"] = "garbage"
        from vault_config import ethereum_sepolia_token_decimals
        self.assertEqual(ethereum_sepolia_token_decimals("USDT_ERC20"), 6)


class _AuthedRouteCase(unittest.TestCase):

    def setUp(self) -> None:
        self._env_snap = _wipe_env(
            "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
            "ETHEREUM_SEPOLIA_RPC_URL",
            "ETH_SEPOLIA_USDT_CONTRACT_ADDRESS",
            "ETH_SEPOLIA_USDC_CONTRACT_ADDRESS",
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

    @staticmethod
    def _fake_eth_account_record(addr: str = None) -> dict:
        return {
            "schema": "crypto_wallet_account_v1",
            "asset": "ETH",
            "network": "Ethereum Sepolia",
            "walletLabel": "VaultAI ETH wallet",
            "publicAddress": addr or "0x" + "a" * 40,
            "encryptedWalletSecret": "CT-xyz",
            "keyOrigin": "generated_client_side",
            "signingMode": "client_side",
            "backupStatus": "encrypted_backup_saved",
        }


class AccountRouteTokenTests(_AuthedRouteCase):

    def test_account_returns_eth_summary_with_token_asset_id(self) -> None:
        self._enable_engine()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=self._fake_eth_account_record(),
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/USDT_ERC20")
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "enabled")
        acct = body["account"]
                                                     
        self.assertEqual(acct["asset"], "USDT_ERC20")
        self.assertEqual(acct["underlyingAsset"], "ETH")
        self.assertEqual(
            acct["publicAddress"], "0x" + "a" * 40,
        )
                                                          
        self.assertNotIn("encryptedWalletSecret", acct)

    def test_account_returns_no_account_when_eth_missing(self) -> None:
        self._enable_engine()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=None,
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/USDC_ERC20")
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "no_account")
        self.assertEqual(body["asset"], "USDC_ERC20")
        self.assertEqual(body["underlyingAsset"], "ETH")


class ReceiveRouteTokenTests(_AuthedRouteCase):

    def test_E8_create_eth_first_when_no_eth_wallet(self) -> None:
        self._enable_engine()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=None,
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/USDT_ERC20/receive")
        body = resp.json()
        self.assertEqual(
            body["wallet_engine"], "create_eth_wallet_first",
        )
        self.assertEqual(body["asset"], "USDT_ERC20")
        self.assertEqual(body["underlyingAsset"], "ETH")

    def test_E9_token_receive_returns_eth_address(self) -> None:
        self._enable_engine()
        addr = "0x" + "a" * 40
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=self._fake_eth_account_record(addr=addr),
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/USDT_ERC20/receive")
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "receive_ready")
        self.assertEqual(body["asset"], "USDT_ERC20")
        self.assertEqual(body["underlyingAsset"], "ETH")
        self.assertEqual(body["publicAddress"], addr)
        self.assertEqual(body["unit"], "USDT")
                                                        
        self.assertIn("USDT", body["warning"])
        self.assertIn("Sepolia", body["warning"])

    def test_USDC_receive_returns_USDC_unit_and_warning(self) -> None:
        self._enable_engine()
        addr = "0x" + "a" * 40
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=self._fake_eth_account_record(addr=addr),
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/USDC_ERC20/receive")
        body = resp.json()
        self.assertEqual(body["unit"], "USDC")
        self.assertIn("USDC", body["warning"])


class BalanceRouteTokenTests(_AuthedRouteCase):

    def test_E10_unavailable_when_contract_unset(self) -> None:
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
                                               
        c = self._client()
        resp = c.get(
            "/crypto/wallet/USDT_ERC20/balance?address=0x" + "1" * 40,
        )
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "unavailable")
        self.assertEqual(body["reason"], "token_contract_not_configured")
        self.assertIsNone(body["availableAmount"])
                                                            
                            
        self.assertEqual(body["unit"], "USDT")

    def test_E11_unavailable_when_address_invalid(self) -> None:
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        os.environ["ETH_SEPOLIA_USDT_CONTRACT_ADDRESS"] = "0x" + "c" * 40
        import vault_config
        vault_config.reset_for_tests()
        with patch(
            "ethereum_sepolia_proxy.erc20_balance_of",
        ) as mock:
            c = self._client()
            resp = c.get(
                "/crypto/wallet/USDT_ERC20/balance?address=not-an-address",
            )
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "unavailable")
        self.assertEqual(body["reason"], "invalid_address")
                                                     
        mock.assert_not_called()

    def test_E12_balance_uses_erc20_balanceOf_and_formats(self) -> None:
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        os.environ["ETH_SEPOLIA_USDT_CONTRACT_ADDRESS"] = "0x" + "c" * 40
        import vault_config
        vault_config.reset_for_tests()
                                                                      
        with patch(
            "ethereum_sepolia_proxy.erc20_balance_of",
            return_value=12_345_678,
        ) as mock:
            c = self._client()
            resp = c.get(
                "/crypto/wallet/USDT_ERC20/balance?address=0x" + "1" * 40,
            )
        mock.assert_called_once()
        body = resp.json()
        self.assertEqual(body["balanceStatus"], "available")
                                                    
        self.assertEqual(body["availableAmount"], "12.345678")
        self.assertEqual(body["unit"], "USDT")
        self.assertEqual(body["baseUnits"], "12345678")
        self.assertEqual(body["decimals"], 6)
        self.assertEqual(body["tokenContract"], "0x" + "c" * 40)


class SendDraftTokenTests(_AuthedRouteCase):

    def test_E13_draft_refuses_plaintext_key(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/USDT_ERC20/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "10",
                "privateKey":         "0xdeadbeef",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_E14_draft_refuses_bad_destination(self) -> None:
        self._enable_engine()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/USDT_ERC20/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "not-an-address",
                "amountEth":          "10",
            },
        )
        self.assertEqual(resp.status_code, 422)
        body = resp.json()
        self.assertEqual(
            body["detail"]["wallet_engine"],
            "invalid_destination_address",
        )

    def test_E15_draft_unavailable_when_token_contract_unset(self) -> None:
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        import vault_config
        vault_config.reset_for_tests()
        c = self._client()
        resp = c.post(
            "/crypto/wallet/USDT_ERC20/send/draft",
            json={
                "fromAddress":        "0x" + "a" * 40,
                "destinationAddress": "0x" + "b" * 40,
                "amountEth":          "10",
            },
        )
        body = resp.json()
        self.assertEqual(body["status"], "draft_unavailable")
        self.assertEqual(body["reason"], "token_contract_not_configured")
                                                                 
        self.assertNotIn("dataHex", body)
        self.assertNotIn("nonce", body)
        self.assertNotIn("gasLimit", body)

    def test_E16_draft_returns_erc20_calldata(self) -> None:
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        os.environ["ETH_SEPOLIA_USDT_CONTRACT_ADDRESS"] = "0x" + "c" * 40
        import vault_config
        vault_config.reset_for_tests()
                                     
        with patch(
            "ethereum_sepolia_proxy.eth_get_transaction_count",
            return_value=7,
        ), patch(
            "ethereum_sepolia_proxy.eth_gas_price_wei",
            return_value=20_000_000_000,
        ), patch(
            "ethereum_sepolia_proxy.eth_estimate_gas",
            return_value=65_000,
        ) as mock_gas:
            c = self._client()
            resp = c.post(
                "/crypto/wallet/USDT_ERC20/send/draft",
                json={
                    "fromAddress":        "0x" + "a" * 40,
                    "destinationAddress": "0x" + "b" * 40,
                    "amountEth":          "10",                              
                },
            )
        body = resp.json()
        self.assertEqual(body["status"], "draft_ready")
        self.assertEqual(body["asset"], "USDT_ERC20")
        self.assertEqual(body["network"], "Ethereum Sepolia")
        self.assertEqual(body["unit"], "USDT")
        self.assertEqual(body["tokenContract"], "0x" + "c" * 40)
        self.assertEqual(body["transactionTo"], "0x" + "c" * 40)
        self.assertEqual(body["transactionValueWei"], "0")
                                                    
        self.assertTrue(body["dataHex"].startswith("0xa9059cbb"))
                                                                       
        self.assertIn("b" * 40, body["dataHex"])
                                                        
        self.assertEqual(body["amountBaseUnits"], "10000000")
                                                                
                           
        mock_gas.assert_called_once()
        kwargs = mock_gas.call_args.kwargs
        self.assertEqual(kwargs["value_wei"], 0)
        self.assertEqual(kwargs["to_address"], "0x" + "c" * 40)
        self.assertTrue(kwargs["data_hex"].startswith("0xa9059cbb"))

    def test_draft_response_does_not_leak_secrets(self) -> None:
                                                                  
                                                            
        self._enable_engine()
        os.environ["ETHEREUM_SEPOLIA_RPC_URL"] = "https://example.com"
        os.environ["ETH_SEPOLIA_USDT_CONTRACT_ADDRESS"] = "0x" + "c" * 40
        import vault_config
        vault_config.reset_for_tests()
        with patch(
            "ethereum_sepolia_proxy.eth_get_transaction_count",
            return_value=7,
        ), patch(
            "ethereum_sepolia_proxy.eth_gas_price_wei",
            return_value=20_000_000_000,
        ), patch(
            "ethereum_sepolia_proxy.eth_estimate_gas",
            return_value=65_000,
        ):
            c = self._client()
            resp = c.post(
                "/crypto/wallet/USDT_ERC20/send/draft",
                json={
                    "fromAddress":        "0x" + "a" * 40,
                    "destinationAddress": "0x" + "b" * 40,
                    "amountEth":          "10",
                },
            )
        flat = str(resp.json())
        self.assertNotIn("privateKey", flat)
        self.assertNotIn("encryptedWalletSecret", flat)
        self.assertNotIn("seedPhrase", flat)


class CreateAndEncryptedSecretTokenTests(_AuthedRouteCase):

    def test_E17_create_route_refuses_token_assets(self) -> None:
        self._enable_engine()
        c = self._client()
                                                                
                                   
        resp = c.post(
            "/crypto/wallet/USDT_ERC20/create",
            json={
                "walletLabel":           "x",
                "publicAddress":         "0x" + "a" * 40,
                "network":               "Ethereum Sepolia",
                "encryptedWalletSecret": "ct-12345678",
            },
        )
        body = resp.json()
        self.assertEqual(body["wallet_engine"], "use_eth_wallet")
        self.assertEqual(body["underlyingAsset"], "ETH")

    def test_E18_encrypted_secret_reads_eth_account(self) -> None:
        self._enable_engine()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=self._fake_eth_account_record(),
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/USDT_ERC20/encrypted-secret")
        body = resp.json()
        self.assertEqual(body["status"], "encrypted_secret_ready")
        self.assertEqual(body["asset"], "USDT_ERC20")
        self.assertEqual(body["underlyingAsset"], "ETH")
        self.assertEqual(body["encryptedWalletSecret"], "CT-xyz")

    def test_encrypted_secret_create_eth_first_when_no_eth(self) -> None:
        self._enable_engine()
        with patch(
            "routes.crypto_wallet_routes._load_wallet_account_record",
            return_value=None,
        ):
            c = self._client()
            resp = c.get("/crypto/wallet/USDC_ERC20/encrypted-secret")
        body = resp.json()
        self.assertEqual(body["status"], "create_eth_wallet_first")
        self.assertEqual(body["asset"], "USDC_ERC20")
        self.assertEqual(body["underlyingAsset"], "ETH")
        self.assertNotIn("encryptedWalletSecret", body)


class RouteSourceGuardSlice4Tests(unittest.TestCase):

    def _route_src(self) -> str:
        path = _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        with io.open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_E19_route_logs_omit_dataHex_destination_amount(self) -> None:
        src = self._route_src()
                                                                       
                                                                    
        forbidden_log_substrings = (
            "logger.info(payload.dataHex",
            "logger.info(payload.destinationAddress",
            "logger.info(payload.amountEth",
            "logger.info(payload.amount",
            "logger.warning(payload.dataHex",
            "logger.warning(payload.destinationAddress",
            "logger.warning(payload.amount",
            "%s\", payload.dataHex",
            "%s\", payload.destinationAddress",
            "%s\", payload.amount",
            "dataHex=%s",
            "destinationAddress=%s",
        )
        for needle in forbidden_log_substrings:
            self.assertNotIn(
                needle, src,
                f"crypto_wallet_routes.py must not log {needle!r}",
            )

    def test_E20_no_fake_token_contract_literal(self) -> None:
                                                              
                                                                  
        src = self._route_src()
                                                                    
                                                
        matches = re.findall(r'"0x[0-9a-fA-F]{40}"', src)
        self.assertEqual(
            matches, [],
            f"crypto_wallet_routes.py must not contain a fake 40-hex "
            f"address literal: {matches}",
        )

    def test_E21_broadcast_route_extra_forbid_intact(self) -> None:


        src = self._route_src()
        self.assertIn("class SendBroadcastPayload", src)
        self.assertIn("signedTransaction: Any", src)

        bdcast_idx = src.index("class SendBroadcastPayload")
        bdcast_body = src[bdcast_idx : bdcast_idx + 1500]
        self.assertIn('"extra": "forbid"', bdcast_body)


if __name__ == "__main__":
    unittest.main()
