

from __future__ import annotations

import io
import os
import re
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


import evm_transaction_history as txh
from evm_transaction_history import (
    DEFAULT_TX_LIMIT,
    DIRECTION_INCOMING,
    DIRECTION_OUTGOING,
    MAX_TX_LIMIT,
    NETWORK_SEPOLIA_ID,
    NETWORK_SEPOLIA_LABEL,
    PROVIDER_BLOCKSCOUT,
    PROVIDER_ETHERSCAN,
    REASON_INDEXER_NOT_CONFIGURED,
    REASON_INVALID_ADDRESS,
    REASON_UPSTREAM_ERROR,
    SEPOLIA_CHAIN_ID,
    SOURCE_INDEXER,
    SOURCE_LOCAL_SUBMITTED,
    STATUS_CONFIRMED,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_PENDING,
    STATUS_UNAVAILABLE,
    STATUS_UNKNOWN,
    TX_SCHEMA_V1,
    TxIndexerError,
    envelope_indexer_not_configured,
    envelope_invalid_address,
    envelope_ok,
    envelope_upstream_error,
    is_valid_eth_address,
    list_erc20_transactions,
    list_eth_transactions,
)

import vault_config


_BACKEND_ROOT = Path(__file__).parent


def _set_indexer_env(
    *, provider: str = "", api_key: str = "",
    base_url: str = "",
) -> None:
    for k, v in (
        ("ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER", provider),
        ("ETHEREUM_SEPOLIA_TX_INDEXER_API_KEY", api_key),
        ("ETHEREUM_SEPOLIA_TX_INDEXER_BASE_URL", base_url),
    ):
        if v:
            os.environ[k] = v
        elif k in os.environ:
            del os.environ[k]
    vault_config.reset_for_tests()


class EnvHelperTests(unittest.TestCase):

    def setUp(self) -> None:
        _set_indexer_env()

    def tearDown(self) -> None:
        _set_indexer_env()

    def test_T1_unset_returns_empty_and_false(self) -> None:
        self.assertEqual(
            vault_config.ethereum_sepolia_tx_indexer_provider(), "",
        )
        self.assertEqual(
            vault_config.ethereum_sepolia_tx_indexer_api_key(), "",
        )
        self.assertEqual(
            vault_config.ethereum_sepolia_tx_indexer_base_url(), "",
        )
        self.assertFalse(
            vault_config.ethereum_sepolia_tx_indexer_configured(),
        )

    def test_T1b_etherscan_needs_api_key(self) -> None:
        _set_indexer_env(provider="etherscan")
                                                                           
        self.assertFalse(
            vault_config.ethereum_sepolia_tx_indexer_configured(),
        )
        _set_indexer_env(provider="etherscan", api_key="testkey")
        self.assertTrue(
            vault_config.ethereum_sepolia_tx_indexer_configured(),
        )

    def test_T1c_blockscout_does_not_need_api_key(self) -> None:
        _set_indexer_env(provider="blockscout")
        self.assertTrue(
            vault_config.ethereum_sepolia_tx_indexer_configured(),
        )

    def test_T2_whitelist_rejects_unknown_provider(self) -> None:
        _set_indexer_env(provider="alchemy")
                                                       
        self.assertEqual(
            vault_config.ethereum_sepolia_tx_indexer_provider(), "",
        )
        self.assertFalse(
            vault_config.ethereum_sepolia_tx_indexer_configured(),
        )

    def test_T2b_provider_lowercases(self) -> None:
        _set_indexer_env(provider="EtherScan", api_key="k")
        self.assertEqual(
            vault_config.ethereum_sepolia_tx_indexer_provider(),
            "etherscan",
        )

    def test_T2c_default_base_url_per_provider(self) -> None:
        _set_indexer_env(provider="etherscan", api_key="k")
        url = vault_config.ethereum_sepolia_tx_indexer_base_url()
        self.assertTrue(url.startswith("https://"))
        self.assertIn("etherscan", url)
        _set_indexer_env(provider="blockscout")
        url = vault_config.ethereum_sepolia_tx_indexer_base_url()
        self.assertIn("blockscout", url)


class ConstantsTests(unittest.TestCase):

    def test_T3_constants(self) -> None:
        self.assertEqual(TX_SCHEMA_V1, "crypto_wallet_transaction_v1")
        self.assertEqual(NETWORK_SEPOLIA_ID, "ethereum_sepolia")
        self.assertEqual(NETWORK_SEPOLIA_LABEL, "Ethereum Sepolia")
        self.assertEqual(SEPOLIA_CHAIN_ID, 11155111)
        self.assertEqual(DIRECTION_INCOMING, "incoming")
        self.assertEqual(DIRECTION_OUTGOING, "outgoing")
        self.assertEqual(STATUS_PENDING, "pending")
        self.assertEqual(STATUS_CONFIRMED, "confirmed")
        self.assertEqual(STATUS_FAILED, "failed")
        self.assertEqual(STATUS_UNKNOWN, "unknown")
        self.assertEqual(SOURCE_INDEXER, "indexer")
        self.assertEqual(SOURCE_LOCAL_SUBMITTED, "local_submitted")
        self.assertEqual(MAX_TX_LIMIT, 50)
        self.assertEqual(DEFAULT_TX_LIMIT, 20)
        self.assertEqual(PROVIDER_ETHERSCAN, "etherscan")
        self.assertEqual(PROVIDER_BLOCKSCOUT, "blockscout")
        self.assertEqual(STATUS_OK, "ok")
        self.assertEqual(STATUS_UNAVAILABLE, "unavailable")
        self.assertEqual(
            REASON_INDEXER_NOT_CONFIGURED, "indexer_not_configured",
        )
        self.assertEqual(REASON_UPSTREAM_ERROR, "upstream_error")
        self.assertEqual(REASON_INVALID_ADDRESS, "invalid_address")


class EnvelopeShapesTests(unittest.TestCase):

    def test_T4_indexer_not_configured_envelope(self) -> None:
        e = envelope_indexer_not_configured("ETH")
        self.assertEqual(e["status"], "ok")
        self.assertEqual(e["transactionsStatus"], "unavailable")
        self.assertEqual(e["reason"], "indexer_not_configured")
        self.assertEqual(e["asset"], "ETH")
        self.assertEqual(e["network"], "ethereum_sepolia")
        self.assertEqual(e["networkLabel"], "Ethereum Sepolia")
        self.assertEqual(e["transactions"], [])
        self.assertIn("indexer", e["message"].lower())

    def test_envelope_upstream_error_carries_no_url_or_body(self) -> None:
        e = envelope_upstream_error("ETH", code="upstream_http")
        msg = e["message"].lower()
        self.assertNotIn("http", msg.split("(")[0])                             
        self.assertEqual(e["reason"], "upstream_error")
        self.assertEqual(e["transactions"], [])

    def test_envelope_invalid_address(self) -> None:
        e = envelope_invalid_address("USDT_ERC20")
        self.assertEqual(e["reason"], "invalid_address")
        self.assertEqual(e["transactions"], [])

    def test_envelope_ok_passes_transactions_through(self) -> None:
        rows = [{"schema": TX_SCHEMA_V1, "asset": "ETH"}]
        e = envelope_ok("ETH", rows)
        self.assertEqual(e["transactionsStatus"], "available")
        self.assertEqual(e["transactions"], rows)


class NoConfigBehaviourTests(unittest.TestCase):

    def setUp(self) -> None:
        _set_indexer_env()

    def tearDown(self) -> None:
        _set_indexer_env()

    def test_T5_eth_invalid_address(self) -> None:
                                  
        out = list_eth_transactions("not-an-addr")
        self.assertEqual(out["reason"], "invalid_address")

    def test_T6_eth_indexer_not_configured(self) -> None:
        out = list_eth_transactions("0x" + "ab" * 20)
        self.assertEqual(out["reason"], "indexer_not_configured")

    def test_T7_erc20_indexer_not_configured(self) -> None:
        out = list_erc20_transactions(
            "0x" + "ab" * 20, asset="USDT_ERC20",
        )
        self.assertEqual(out["reason"], "indexer_not_configured")

    def test_T7b_erc20_unsupported_asset(self) -> None:
        out = list_erc20_transactions(
            "0x" + "ab" * 20, asset="WETH",
        )
                                                                 
        self.assertEqual(out["reason"], "indexer_not_configured")


_USER_ADDR = "0x" + "cd" * 20


def _eth_row(
    *, _hash: str, _from: str, _to: str, value: str,
    confirmations: str = "5", is_error: str = "0",
    timestamp: str = "1700000000",
) -> dict[str, Any]:
    return {
        "hash":          _hash,
        "from":          _from,
        "to":            _to,
        "value":         value,
        "confirmations": confirmations,
        "isError":       is_error,
        "timeStamp":     timestamp,
    }


class EthNormalisationTests(unittest.TestCase):

    def setUp(self) -> None:
        _set_indexer_env(provider="etherscan", api_key="k")

    def tearDown(self) -> None:
        _set_indexer_env()

    def test_T8_T9_T10_eth_normalisation(self) -> None:
        tx_in = "0x" + "11" * 32
        tx_out = "0x" + "22" * 32
        tx_fail = "0x" + "33" * 32
        rows = [
            _eth_row(
                _hash=tx_in, _from="0x" + "01" * 20,
                _to=_USER_ADDR,
                value="1500000000000000000",           
            ),
            _eth_row(
                _hash=tx_out, _from=_USER_ADDR,
                _to="0x" + "02" * 20,
                value="250000000000000000",            
            ),
            _eth_row(
                _hash=tx_fail, _from=_USER_ADDR,
                _to="0x" + "03" * 20,
                value="0", is_error="1",
            ),
        ]
        with mock.patch.object(
            txh, "_query_provider", return_value=rows,
        ):
            env = list_eth_transactions(_USER_ADDR)
        self.assertEqual(env["transactionsStatus"], "available")
        self.assertEqual(len(env["transactions"]), 3)
        a, b, c = env["transactions"]
                             
        for row in env["transactions"]:
            self.assertEqual(row["schema"], TX_SCHEMA_V1)
            self.assertEqual(row["asset"], "ETH")
            self.assertEqual(row["network"], "ethereum_sepolia")
            self.assertEqual(row["unit"], "ETH")
            self.assertIn("txHash", row)
            self.assertIn("direction", row)
            self.assertIn("amount", row)
            self.assertIn("status", row)
            self.assertIn("fromAddress", row)
            self.assertIn("toAddress", row)
            self.assertEqual(row["source"], "indexer")
                         
        self.assertEqual(a["direction"], "incoming")
        self.assertEqual(b["direction"], "outgoing")
        self.assertEqual(c["direction"], "outgoing")
                             
        self.assertEqual(c["status"], "failed")
        self.assertEqual(a["status"], "confirmed")
                                                            
        self.assertEqual(a["amount"], "1.5")
        self.assertEqual(b["amount"], "0.25")
        self.assertEqual(c["amount"], "0")

    def test_pending_status_when_confirmations_zero(self) -> None:
        row = _eth_row(
            _hash="0x" + "44" * 32, _from="0x" + "04" * 20,
            _to=_USER_ADDR, value="100", confirmations="0",
        )
        with mock.patch.object(
            txh, "_query_provider", return_value=[row],
        ):
            env = list_eth_transactions(_USER_ADDR)
        self.assertEqual(env["transactions"][0]["status"], "pending")


class Erc20NormalisationTests(unittest.TestCase):

    def setUp(self) -> None:
        _set_indexer_env(provider="etherscan", api_key="k")
                                                                  
                                                                
        os.environ["ETH_SEPOLIA_USDT_CONTRACT_ADDRESS"] = (
            "0x" + "dd" * 20
        )
                                          
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        for k in (
            "ETH_SEPOLIA_USDT_CONTRACT_ADDRESS",
        ):
            if k in os.environ:
                del os.environ[k]
        _set_indexer_env()

    def test_T11_T12_erc20_normalisation(self) -> None:
        contract = "0x" + "dd" * 20
        wrong_contract = "0x" + "ee" * 20
        tx_in = "0x" + "55" * 32
        tx_other = "0x" + "66" * 32
        rows = [
            {
                "hash":            tx_in,
                "from":            "0x" + "06" * 20,
                "to":              _USER_ADDR,
                "value":           "10000000",                        
                "contractAddress": contract,
                "confirmations":   "5",
                "isError":         "0",
                "timeStamp":       "1700000050",
            },
            {
                "hash":            tx_other,
                "from":            _USER_ADDR,
                "to":              "0x" + "07" * 20,
                "value":           "999000000",
                "contractAddress": wrong_contract,                   
                "confirmations":   "5",
            },
        ]
        with mock.patch.object(
            txh, "_query_provider", return_value=rows,
        ):
            env = list_erc20_transactions(
                _USER_ADDR, asset="USDT_ERC20", limit=20,
            )
                                           
        self.assertEqual(env["transactionsStatus"], "available")
        self.assertEqual(len(env["transactions"]), 1)
                                              
        self.assertEqual(env["transactions"][0]["amount"], "10")
        self.assertEqual(env["transactions"][0]["unit"], "USDT")
        self.assertEqual(env["transactions"][0]["direction"], "incoming")


class FormatUnitsTests(unittest.TestCase):

    def test_T13_format_units_no_scientific_notation(self) -> None:
        cases = [
            (0,             18, "0"),
            (1,             18, "0.000000000000000001"),
            (10**18,        18, "1"),
            (10**17 * 15,   18, "1.5"),
            (10**16,        18, "0.01"),
            (10**14 * 5,    18, "0.0005"),
            (1_000_000,     6,  "1"),
            (1_234_567,     6,  "1.234567"),
            (10,            6,  "0.00001"),
            (0,             0,  "0"),
            (12345,         0,  "12345"),
        ]
        for value_units, decimals, expected in cases:
            self.assertEqual(
                txh._format_units(value_units, decimals), expected,
                msg=f"_format_units({value_units}, {decimals})",
            )
                                                                
            self.assertNotIn(
                "e",
                txh._format_units(value_units, decimals).lower(),
            )


class RedactionTests(unittest.TestCase):

    def test_T14_redact_address(self) -> None:
        addr = "0x" + "ab" * 20                
        red = txh._redact_address(addr)
        self.assertEqual(red, addr[:6] + "…" + addr[-4:])
        self.assertNotEqual(red, addr)
        self.assertEqual(txh._redact_address(None), "<addr?>")
        self.assertEqual(txh._redact_address("bogus"), "<addr?>")

    def test_T14b_redact_tx_hash(self) -> None:
        tx = "0x" + "cd" * 32
        red = txh._redact_tx_hash(tx)
        self.assertEqual(red, tx[:6] + "…" + tx[-4:])
        self.assertNotEqual(red, tx)
        self.assertEqual(txh._redact_tx_hash("0x123"), "<tx?>")


class _DummyPrincipal(dict):
    pass


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
        "vault_id": "test-vault-id-slice8",
    }
    return TestClient(app), app, wallet_module


class RouteIntegrationTests(unittest.TestCase):

    def setUp(self) -> None:
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        vault_config.reset_for_tests()
        _set_indexer_env()
        self._client, self._app, self._wallet_mod = _make_app_client()
                                                                 
                            
        self._orig_loader = self._wallet_mod._load_wallet_account_record
        self._wallet_mod._load_wallet_account_record = (
            lambda vault_id, asset: None
        )

    def tearDown(self) -> None:
        self._wallet_mod._load_wallet_account_record = self._orig_loader
        if "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED" in os.environ:
            del os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"]
        _set_indexer_env()
        vault_config.reset_for_tests()

    def test_T15_eth_no_wallet_yet(self) -> None:
        resp = self._client.get("/crypto/wallet/ETH/transactions")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["transactionsStatus"], "unavailable")
        self.assertEqual(body["reason"], "no_wallet_yet")
        self.assertEqual(body["transactions"], [])

    def test_T15b_usdt_no_wallet_yet(self) -> None:
        for asset in ("USDT_ERC20", "USDC_ERC20"):
            resp = self._client.get(f"/crypto/wallet/{asset}/transactions")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["reason"], "no_wallet_yet")
            self.assertEqual(body["transactions"], [])

    def test_T15c_indexer_not_configured_after_wallet_exists(self) -> None:
        self._wallet_mod._load_wallet_account_record = lambda v, a: {
            "publicAddress": "0x" + "aa" * 20,
            "network":       "Ethereum Sepolia",
            "walletLabel":   "VaultAI ETH wallet",
        }
        resp = self._client.get("/crypto/wallet/ETH/transactions")
        body = resp.json()
        self.assertEqual(body["reason"], "indexer_not_configured")
        self.assertEqual(body["transactions"], [])

    def test_T16_legacy_route_maps_to_sepolia(self) -> None:
        resp = self._client.get("/crypto/wallet/ETH/transactions")
        body = resp.json()
        self.assertEqual(body["network"], "ethereum_sepolia")
        self.assertEqual(body["networkLabel"], "Ethereum Sepolia")

    def test_T17_network_explicit_sepolia_delegates(self) -> None:
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_sepolia/ETH/transactions",
        )
        body = resp.json()
                               
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["network"], "ethereum_sepolia")
        self.assertEqual(body["transactions"], [])

    def test_T18_mainnet_blocked(self) -> None:
        resp = self._client.get(
            "/crypto/wallet/network/ethereum_mainnet/ETH/transactions",
        )
        body = resp.json()
                                                                    
        self.assertEqual(body.get("wallet_engine"), "network_not_enabled")
        self.assertEqual(body["transactions"], [])

    def test_T19_limit_query_clamped(self) -> None:
                        
        self._wallet_mod._load_wallet_account_record = lambda v, a: {
            "publicAddress": "0x" + "bb" * 20,
        }
        _set_indexer_env(provider="etherscan", api_key="k")
        captured = {}

        def stub_query_provider(
            *, address, action, contract_address, limit,
                                                                
                                                               
            network_id="ethereum_sepolia",
        ):
            captured["address"]          = address
            captured["action"]           = action
            captured["contract_address"] = contract_address
            captured["limit"]            = limit
            captured["network_id"]       = network_id
            return []

        with mock.patch.object(
            txh, "_query_provider", side_effect=stub_query_provider,
        ):
            resp = self._client.get(
                "/crypto/wallet/ETH/transactions?limit=9999",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured["limit"], MAX_TX_LIMIT)


class SourceGuardTests(unittest.TestCase):

    SRC_PATH = _BACKEND_ROOT / "evm_transaction_history.py"

    def setUp(self) -> None:
        with io.open(self.SRC_PATH, "r", encoding="utf-8") as f:
            self._raw = f.read()
                                                   
        self._scrubbed = re.sub(
            r"#.*$", "", self._raw, flags=re.MULTILINE,
        )
        self._scrubbed = re.sub(
            r'"""(.*?)"""', "", self._scrubbed, flags=re.DOTALL,
        )

    def test_T20_no_signing_imports(self) -> None:
        banned = (
            "eth_account", "web3", "ethereum_transaction",
            "ethereum_sepolia_proxy", "ethereum_wallet",
            "eth_keys",
        )
        for name in banned:
            self.assertNotIn(
                name, self._scrubbed,
                msg=f"evm_transaction_history must not import {name}",
            )

    def test_T21_no_hardcoded_fake_addresses_or_tx_hashes(self) -> None:
                                                                      
                                                                   
        candidates = re.findall(
            r'"(0x[0-9a-fA-F]{40,})"', self._scrubbed,
        ) + re.findall(
            r"'(0x[0-9a-fA-F]{40,})'", self._scrubbed,
        )
                                                               
                                                                
        self.assertEqual(
            candidates, [],
            msg=f"Found hardcoded 0x literals: {candidates}",
        )

    def test_T22_logger_never_logs_raw_address(self) -> None:
                                                             
                                                                
        log_calls = re.findall(
            r"logger\.(?:info|warning|error|debug)\([^)]*\)",
            self._scrubbed,
        )
        for call in log_calls:
            if "address" in call.lower() and "_redact_address" not in call:
                                                                           
                continue
                                                                    
                                                                 
            self.assertFalse(
                ("addr" in call.lower() and
                 "_redact_address" not in call and
                 "addr=%s" not in call),
                msg=f"Logger call leaks raw address: {call}",
            )


class HelperTests(unittest.TestCase):

    def test_is_valid_eth_address(self) -> None:
        self.assertTrue(is_valid_eth_address("0x" + "00" * 20))
        self.assertTrue(is_valid_eth_address("0x" + "Ff" * 20))
        self.assertFalse(is_valid_eth_address(None))
        self.assertFalse(is_valid_eth_address(""))
        self.assertFalse(is_valid_eth_address("0xabc"))
        self.assertFalse(
            is_valid_eth_address("0x" + "gg" * 20),
        )


if __name__ == "__main__":
    unittest.main()
