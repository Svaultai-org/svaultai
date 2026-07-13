"""2026-07-14 (Round 10 — Max UX): dedicated backend regression
suite for the fee-estimate endpoint used by the client's Max button.

The endpoint is:

    POST /crypto/wallet/network/{network}/send/fee_estimate
    body: { fromAddress, destinationAddress, asset }

It returns:

    { status: "fee_estimate_ready",
      authorizedMaxFeeBaseUnits: "<int>",
      feeSource: "eth_estimateGas_x_gasPrice" | "sol_getFeeForMessage",
      network: "ethereum_mainnet" | "solana_mainnet",
      asset: "..." }

or a `fee_estimate_unavailable` envelope with a `reason` code on
any RPC / validation failure. The endpoint MUST NOT persist a
draft, retrieve any secret, or advance any state machine — it is a
pure read-only estimate.

Coverage:

  1. ETH: happy path — gas_limit × gas_price returned.
  2. ETH: ERC-20 happy path — data_hex for a 1-base-unit transfer.
  3. ETH: invalid destination → 200 fee_estimate_unavailable +
     invalid_destination_address reason.
  4. ETH: invalid from → same envelope with invalid_from_address.
  5. ETH: RPC unreachable → fee_estimate_unavailable + rpc_unreachable.
  6. ETH: RPC not configured → fee_estimate_unavailable +
     rpc_not_configured.
  7. SOL: happy path — sol_getFeeForMessage returned.
  8. SOL: invalid destination.
  9. SOL: RPC unreachable.
 10. SOL: RPC not configured.
 11. TRON: 200 fee_estimate_unavailable + no_fee_estimate_semantics
     (TRC-20 Max = full token balance; no server fee estimate).
 12. Endpoint does not persist a draft or touch the state machine.
 13. Endpoint requires auth — missing session → 401.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import vault_config


_ENV_KEYS = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_ETHEREUM_MAINNET_ENABLED",
    "VAULTAI_CRYPTO_ETHEREUM_MAINNET_SEND_ENABLED",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
    "VAULTAI_CRYPTO_SOLANA_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_ENABLED",
    "SOLANA_RPC_URL",
    "VAULTAI_CRYPTO_TRON_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_ENABLED",
    "TRON_API_BASE_URL",
    "TRON_API_KEY",
    "TRON_USDT_CONTRACT_ADDRESS",
)


def _clear() -> None:
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
    vault_config.reset_for_tests()


def _enable_eth() -> None:
    _clear()
    os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_ETHEREUM_MAINNET_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_ETHEREUM_MAINNET_SEND_ENABLED"] = "true"
    os.environ["ETHEREUM_MAINNET_RPC_URL"] = "https://eth.example"
    os.environ[
        "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS"
    ] = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    os.environ[
        "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS"
    ] = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    vault_config.reset_for_tests()


def _enable_sol() -> None:
    _clear()
    os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
    os.environ["SOLANA_RPC_URL"] = "https://sol.example"
    vault_config.reset_for_tests()


def _enable_tron() -> None:
    _clear()
    os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
    os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
    os.environ["TRON_API_BASE_URL"] = "https://tron.example"
    os.environ["TRON_API_KEY"] = "k"
    os.environ["TRON_USDT_CONTRACT_ADDRESS"] = (
        "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    )
    vault_config.reset_for_tests()


_VAULT = "vault-fee-estimate-caller"
_ETH_A = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb0"
_ETH_B = "0x8B3392483BA26D65E331dB86D4F430E9B3814979"
_SOL_A = "So11111111111111111111111111111111111111112"
_SOL_B = "11111111111111111111111111111111"
_TRN_A = "TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq"


def _make_client(vault_id: str = _VAULT):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as m
    from routes.crypto_wallet_routes import (
        router, verify_trusted_device,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": vault_id,
    }
    return TestClient(app), app, m


def _make_client_no_auth():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.crypto_wallet_routes import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------
# ETH
# ---------------------------------------------------------------


class EthFeeEstimate(unittest.TestCase):

    def setUp(self) -> None:
        _enable_eth()
        self._client, self._app, self._m = _make_client()

    def tearDown(self) -> None:
        _clear()

    def _hit(
        self,
        *,
        from_addr: str = _ETH_A,
        dest_addr: str = _ETH_B,
        asset: str = "ETH",
    ):
        return self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/send/fee_estimate",
            json={
                "fromAddress":        from_addr,
                "destinationAddress": dest_addr,
                "asset":              asset,
            },
        )

    def test_happy_path_returns_gas_x_price(self):
        with mock.patch(
            "evm_rpc.eth_estimate_gas_at_url",
            return_value=21000,
        ), mock.patch(
            "evm_rpc.eth_gas_price_wei_at_url",
            return_value=20_000_000_000,
        ):
            r = self._hit()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_ready")
        self.assertEqual(body["network"], "ethereum_mainnet")
        self.assertEqual(body["asset"], "ETH")
        self.assertEqual(
            body["authorizedMaxFeeBaseUnits"],
            str(21000 * 20_000_000_000),
        )
        self.assertEqual(body["gasLimit"], "21000")
        self.assertEqual(body["gasPriceWei"], "20000000000")
        self.assertEqual(
            body["feeSource"], "eth_estimateGas_x_gasPrice",
        )

    def test_erc20_transfer_uses_calldata(self):
        with mock.patch(
            "evm_rpc.eth_estimate_gas_at_url",
            return_value=65000,
        ) as est, mock.patch(
            "evm_rpc.eth_gas_price_wei_at_url",
            return_value=25_000_000_000,
        ):
            r = self._hit(asset="USDT_ERC20")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_ready")
        # ERC-20 estimate must have been asked with data_hex (not "0x").
        est.assert_called_once()
        kwargs = est.call_args.kwargs
        self.assertNotEqual(kwargs.get("data_hex"), "0x")
        # Must target the token contract, not the ETH destination.
        self.assertNotEqual(kwargs.get("to_address"), _ETH_B)

    def test_invalid_destination_fails_closed(self):
        r = self._hit(dest_addr="not-an-address")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(
            body["reason"], "invalid_destination_address",
        )

    def test_invalid_from_fails_closed(self):
        r = self._hit(from_addr="0xdeadbeef")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(body["reason"], "invalid_from_address")

    def test_rpc_unreachable_fails_closed_temporarily(self):
        from evm_rpc import EvmRpcError
        with mock.patch(
            "evm_rpc.eth_estimate_gas_at_url",
            side_effect=EvmRpcError("rpc_unreachable"),
        ):
            r = self._hit()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(body["reason"], "rpc_unreachable")

    def test_rpc_not_configured_fails_closed(self):
        os.environ.pop("ETHEREUM_MAINNET_RPC_URL", None)
        vault_config.reset_for_tests()
        r = self._hit()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")

    def test_endpoint_does_not_persist_a_draft(self):
        # Rehit multiple times — the SOL draft-store and the ETH
        # store (if any) should stay empty because fee_estimate
        # never touches the state machine.
        before = dict(self._m._solana_store._drafts)
        with mock.patch(
            "evm_rpc.eth_estimate_gas_at_url", return_value=21000,
        ), mock.patch(
            "evm_rpc.eth_gas_price_wei_at_url",
            return_value=25_000_000_000,
        ):
            for _ in range(3):
                r = self._hit()
                self.assertEqual(r.status_code, 200)
        self.assertEqual(before, self._m._solana_store._drafts)


# ---------------------------------------------------------------
# SOL
# ---------------------------------------------------------------


class SolFeeEstimate(unittest.TestCase):

    def setUp(self) -> None:
        _enable_sol()
        self._client, self._app, self._m = _make_client()

    def tearDown(self) -> None:
        _clear()

    def _hit(
        self,
        *,
        from_addr: str = _SOL_A,
        dest_addr: str = _SOL_B,
        asset: str = "SOL",
    ):
        return self._client.post(
            "/crypto/wallet/network/solana_mainnet/send/fee_estimate",
            json={
                "fromAddress":        from_addr,
                "destinationAddress": dest_addr,
                "asset":              asset,
            },
        )

    def test_happy_path_uses_getfeeformessage(self):
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            return_value={
                "blockhash": "GfVPzKR8Uz2Sa4Pxrw6JHQKtu4LFB1cUKQwT8b9DhP7A",
                "lastValidBlockHeight": 250_000_000,
            },
        ), mock.patch(
            "solana_rpc.sol_get_fee_for_message_at_url",
            return_value=5000,
        ):
            r = self._hit()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_ready")
        self.assertEqual(body["network"], "solana_mainnet")
        self.assertEqual(body["authorizedMaxFeeBaseUnits"], "5000")
        self.assertEqual(body["feeSource"], "sol_getFeeForMessage")

    def test_invalid_destination_fails_closed(self):
        r = self._hit(dest_addr="not-solana")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(
            body["reason"], "invalid_destination_address",
        )

    def test_rpc_unreachable_fails_closed(self):
        from solana_rpc import SolanaRpcError, REASON_RPC_UNREACHABLE
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            side_effect=SolanaRpcError(REASON_RPC_UNREACHABLE),
        ):
            r = self._hit()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(body["reason"], "rpc_unreachable")

    def test_rpc_not_configured_fails_closed(self):
        os.environ.pop("SOLANA_RPC_URL", None)
        vault_config.reset_for_tests()
        r = self._hit()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(body["reason"], "rpc_not_configured")

    def test_zero_or_negative_fee_fails_closed(self):
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            return_value={
                "blockhash": "GfVPzKR8Uz2Sa4Pxrw6JHQKtu4LFB1cUKQwT8b9DhP7A",
                "lastValidBlockHeight": 250_000_000,
            },
        ), mock.patch(
            "solana_rpc.sol_get_fee_for_message_at_url",
            return_value=0,
        ):
            r = self._hit()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(body["reason"], "malformed_fee_estimate")


# ---------------------------------------------------------------
# TRON — endpoint declines with a stable envelope so the client
# knows not to call it for TRC-20 Max.
# ---------------------------------------------------------------


class TronFeeEstimateDeclines(unittest.TestCase):

    def setUp(self) -> None:
        _enable_tron()
        self._client, self._app, self._m = _make_client()

    def tearDown(self) -> None:
        _clear()

    def test_returns_no_fee_estimate_semantics(self):
        r = self._client.post(
            "/crypto/wallet/network/tron_mainnet/send/fee_estimate",
            json={
                "fromAddress":        _TRN_A,
                "destinationAddress": "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9",
                "asset":              "USDT_TRC20",
            },
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "fee_estimate_unavailable")
        self.assertEqual(
            body["reason"], "no_fee_estimate_semantics",
        )


# ---------------------------------------------------------------
# Auth
# ---------------------------------------------------------------


class FeeEstimateAuth(unittest.TestCase):

    def setUp(self) -> None:
        _enable_eth()

    def tearDown(self) -> None:
        _clear()

    def test_missing_auth_returns_401(self):
        client = _make_client_no_auth()
        r = client.post(
            "/crypto/wallet/network/ethereum_mainnet/send/fee_estimate",
            json={
                "fromAddress":        _ETH_A,
                "destinationAddress": _ETH_B,
                "asset":              "ETH",
            },
        )
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
