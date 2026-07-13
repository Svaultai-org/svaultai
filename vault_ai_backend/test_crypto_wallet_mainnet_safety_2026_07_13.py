"""2026-07-13: mainnet-safety regression suite.

Locks in three real-money guardrails added ahead of enabling
`VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED=true`:

  1. Backend `_create_mainnet_send_draft` refuses to hand back a
     `draft_ready` envelope for a native ETH send when
     `balance_wei < value_wei + gas_limit * gas_price`. The old
     draft flow only fetched nonce+gas+gasLimit and returned
     `draft_ready` regardless of balance — a wallet with 0.05 ETH
     could draft a 0.05 ETH send and the broadcast would fail at
     the RPC with `insufficient funds for gas * price + value`.
  2. Same draft flow refuses ERC20 sends when either the token
     balance is smaller than the send amount, OR the wallet does
     not hold enough ETH to pay the drafted gas. The check uses
     the LIVE `eth_estimateGas * gas_price` — never a hard-coded
     0.0005 ETH threshold — because a token approval or complex
     transfer could easily exceed a hard-coded floor.
  3. Server-side wallet-level concurrency lock:
     `_broadcast_mainnet_signed_transaction` refuses to run two
     concurrent broadcasts for the same `(vault_id,
     ethereum_mainnet)` pair. The client-side `_broadcastInFlight`
     flag only protects a single tab / device; the server lock is
     the authoritative guard against two tabs, two devices, or
     rapid double-submit races.

The suite uses in-process patching against `evm_rpc.*_at_url`
helpers so no HTTP requests leave the test process — it exercises
the exact production dispatch paths through the FastAPI TestClient.
"""

from __future__ import annotations

import os
import threading
import time
import unittest
from typing import Any, Optional
from unittest import mock

import vault_config


_ALL_RELEVANT_ENV: tuple[str, ...] = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
    "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT",
    "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS",
)


def _set_env(**kvs: str) -> None:
    for k, v in kvs.items():
        if v is None:
            if k in os.environ:
                del os.environ[k]
        else:
            os.environ[k] = v
    vault_config.reset_for_tests()


def _clear_all_env() -> None:
    for k in _ALL_RELEVANT_ENV:
        if k in os.environ:
            del os.environ[k]
    vault_config.reset_for_tests()


def _enable_mainnet_send() -> None:
    _set_env(
        VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS="0x" + "11" * 20,
        ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS="0x" + "22" * 20,
        # Rate limit high enough that the tests below hit the
        # wallet-inflight guard, NOT the rate limiter.
        VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT="1000",
        VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS="60",
    )


_TEST_VAULT_ID = "test-vault-safety-2026-07-13"


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
        "vault_id": _TEST_VAULT_ID,
    }
    return TestClient(app), app, wallet_module


def _seed_wallet(wallet_module) -> None:



    def _load(vault_id, asset_or_service):
        if asset_or_service == "ETH:ethereum_mainnet":
            return {
                "schema":        "crypto_wallet_account_v1",
                "asset":         "ETH",
                "network":       "ethereum_mainnet",
                "walletLabel":   "VaultAI Mainnet ETH",
                "publicAddress": _FROM_ADDR,
                "encryptedWalletSecret": "ct",
                "keyOrigin":     "generated_client_side",
                "signingMode":   "client_side",
                "backupStatus":  "encrypted_backup_saved",
            }
        return None
    wallet_module._load_wallet_account_record = _load


def _seed_broadcast_draft(
    wallet_module,
    *,
    suffix: str = "aa",
    asset: str = "ETH",
    sender_address: Optional[str] = None,
) -> str:



    did = f"safetydraft-{suffix}"
    wallet_module._mainnet_store.seed_draft(
            did,
            vault_id=_TEST_VAULT_ID,
            network_id="ethereum_mainnet",
            asset=asset,
            sender_address=sender_address or _FROM_ADDR,
            destination_address=_DEST_ADDR,
            value_wei=0,
            data_hex="0x",
            nonce=0,
            gas_limit=21000,
            gas_price=1000000000,
            chain_id=1,
            transaction_to=_DEST_ADDR,
        )
    return did


_FROM_ADDR = "0x" + "ab" * 20
_DEST_ADDR = "0x" + "cd" * 20
_SIGNED_TX = "0x" + "ee" * 120
_TX_HASH   = "0x" + "0f" * 32


class MainnetEthBalancePlusGasCheck(unittest.TestCase):
    """Native ETH send: `value + fee <= balance` enforced by backend."""

    def setUp(self) -> None:
        _clear_all_env()
        _enable_mainnet_send()
        self._client, self._app, self._wallet_mod = _make_app_client()
        # Reset in-memory safety state so the wallet-inflight guard
        # and idempotency cache are pristine between tests.
        self._wallet_mod.reset_mainnet_safety_state_for_tests()
        _seed_wallet(self._wallet_mod)

    def tearDown(self) -> None:
        _clear_all_env()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def _patch_gas_and_nonce(
        self,
        *,
        nonce: int = 42,
        gas_price: int = 30_000_000_000,     # 30 gwei
        gas_limit: int = 21_000,
    ):
        import evm_rpc
        return mock.patch.multiple(
            evm_rpc,
            eth_get_transaction_count_at_url=mock.DEFAULT,
            eth_gas_price_wei_at_url=mock.DEFAULT,
            eth_estimate_gas_at_url=mock.DEFAULT,
        )

    def _post_eth_draft(self, amount_eth: str) -> dict[str, Any]:
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  _DEST_ADDR,
                "amountEth":           amount_eth,
            },
        )
        return resp.json()

    def test_eth_send_rejected_when_amount_plus_gas_exceeds_balance(
        self,
    ) -> None:
        """Balance = 0.05 ETH; send 0.05 ETH → fee makes total > balance."""
        import evm_rpc
        gas_price = 30_000_000_000       # 30 gwei
        gas_limit = 21_000
        fee_wei = gas_price * gas_limit
        # Balance exactly matches the requested send amount, ONE wei
        # short of `value + fee`.
        value_wei = 5 * (10 ** 16)       # 0.05 ETH
        balance_wei = value_wei          # 0.05 ETH — no room for gas
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=gas_price,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=gas_limit,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            return_value=balance_wei,
        ):
            body = self._post_eth_draft("0.05")
        self.assertEqual(body["status"], "insufficient_balance")
        self.assertEqual(
            body["reason"], "insufficient_eth_for_amount_plus_gas",
        )
        # Envelope MUST expose the exact numbers the frontend needs
        # to render a specific "you're X wei short" message.
        self.assertEqual(body["valueWei"], str(value_wei))
        self.assertEqual(body["feeWei"], str(fee_wei))
        self.assertEqual(body["availableWei"], str(balance_wei))
        self.assertEqual(body["requiredWei"], str(value_wei + fee_wei))
        # Never a draft_ready envelope for this state.
        self.assertNotIn("nonce", body)

    def test_eth_send_accepted_when_balance_covers_amount_plus_gas(
        self,
    ) -> None:
        import evm_rpc
        gas_price = 30_000_000_000
        gas_limit = 21_000
        fee_wei = gas_price * gas_limit
        value_wei = 5 * (10 ** 16)       # 0.05 ETH
        balance_wei = value_wei + fee_wei + 1  # exactly enough + 1 wei
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=gas_price,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=gas_limit,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            return_value=balance_wei,
        ):
            body = self._post_eth_draft("0.05")
        self.assertEqual(body["status"], "draft_ready")

    def test_eth_send_rejected_when_balance_check_rpc_fails(
        self,
    ) -> None:
        """The check MUST fail closed — never fall through to draft_ready."""
        import evm_rpc
        from evm_rpc import EvmRpcError
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=1_000_000_000,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=21_000,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            side_effect=EvmRpcError("upstream_io"),
        ):
            body = self._post_eth_draft("0.01")
        self.assertEqual(body["status"], "draft_unavailable")
        self.assertEqual(body["reason"], "balance_check_failed")

    def test_eth_send_no_hardcoded_gas_floor(self) -> None:
        """
        Even a wallet with 100 ETH is rejected if the LIVE gas
        estimate exceeds the balance. The check uses the live
        estimate — never a hardcoded 0.0005 ETH threshold.
        """
        import evm_rpc
        gas_price = 10 ** 15   # 0.001 ETH per gas → wildly high
        gas_limit = 200_000    # 200 ETH total fee estimate
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=gas_price,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=gas_limit,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            return_value=100 * (10 ** 18),   # 100 ETH
        ):
            body = self._post_eth_draft("1.0")
        # A 1 ETH send + 200 ETH gas fee > 100 ETH balance → reject.
        self.assertEqual(body["status"], "insufficient_balance")
        self.assertEqual(
            body["reason"], "insufficient_eth_for_amount_plus_gas",
        )


class MainnetErc20BalanceAndGasCheck(unittest.TestCase):
    """ERC20 send: token balance AND ETH-for-gas both enforced."""

    def setUp(self) -> None:
        _clear_all_env()
        _enable_mainnet_send()
        self._client, self._app, self._wallet_mod = _make_app_client()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def tearDown(self) -> None:
        _clear_all_env()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def _post_usdt_draft(self, amount: str) -> dict[str, Any]:
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/"
            "send/draft",
            json={
                "fromAddress":         _FROM_ADDR,
                "destinationAddress":  _DEST_ADDR,
                "amountEth":           amount,
            },
        )
        return resp.json()

    def test_usdt_send_rejected_when_token_balance_less_than_amount(
        self,
    ) -> None:
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=1_000_000_000,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=60_000,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            # Enough ETH for gas.
            return_value=10 * (10 ** 18),
        ), mock.patch.object(
            evm_rpc, "erc20_balance_of_at_url",
            # Only 0.5 USDT (6 decimals) — trying to send 1.0 USDT.
            return_value=500_000,
        ):
            body = self._post_usdt_draft("1.0")
        self.assertEqual(body["status"], "insufficient_balance")
        self.assertEqual(body["reason"], "insufficient_token_balance")
        # Envelope exposes the exact base-unit shortage.
        self.assertEqual(body["requiredBaseUnits"], "1000000")
        self.assertEqual(body["availableBaseUnits"], "500000")
        self.assertEqual(body["unit"], "USDT")

    def test_usdt_send_rejected_when_eth_for_gas_insufficient(
        self,
    ) -> None:
        import evm_rpc
        gas_price = 30_000_000_000       # 30 gwei
        gas_limit = 60_000
        fee_wei = gas_price * gas_limit
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=gas_price,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=gas_limit,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            # ETH balance is ONE wei short of the estimated fee.
            return_value=fee_wei - 1,
        ), mock.patch.object(
            evm_rpc, "erc20_balance_of_at_url",
            return_value=10_000_000,    # 10 USDT
        ):
            body = self._post_usdt_draft("1.0")
        self.assertEqual(body["status"], "insufficient_balance")
        self.assertEqual(body["reason"], "insufficient_gas_eth")
        self.assertEqual(body["requiredWei"], str(fee_wei))
        self.assertEqual(body["availableWei"], str(fee_wei - 1))

    def test_usdt_send_accepted_when_token_and_gas_both_covered(
        self,
    ) -> None:
        import evm_rpc
        with mock.patch.object(
            evm_rpc, "eth_get_transaction_count_at_url",
            return_value=1,
        ), mock.patch.object(
            evm_rpc, "eth_gas_price_wei_at_url",
            return_value=1_000_000_000,
        ), mock.patch.object(
            evm_rpc, "eth_estimate_gas_at_url",
            return_value=60_000,
        ), mock.patch.object(
            evm_rpc, "eth_get_balance_wei_at_url",
            return_value=1 * (10 ** 18),
        ), mock.patch.object(
            evm_rpc, "erc20_balance_of_at_url",
            return_value=10_000_000,
        ):
            body = self._post_usdt_draft("1.0")
        self.assertEqual(body["status"], "draft_ready")


class MainnetWalletBroadcastConcurrency(unittest.TestCase):
    """Server-side wallet-level in-flight concurrency guard."""

    def setUp(self) -> None:
        _clear_all_env()
        _enable_mainnet_send()
        self._client, self._app, self._wallet_mod = _make_app_client()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()
        _seed_wallet(self._wallet_mod)

    def tearDown(self) -> None:
        _clear_all_env()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def test_concurrent_broadcast_second_rejected_with_409(self) -> None:
        """
        Two concurrent broadcasts against the same wallet — the
        second must be refused with `wallet_broadcast_inflight`.
        This is the authoritative multi-tab / multi-device guard.
        """
        import evm_rpc
        # Signal-and-wait pattern: we make the first broadcast's RPC
        # call block until the second broadcast has attempted to
        # acquire the wallet-inflight lock. Only then release the
        # first so it can proceed.
        first_entered = threading.Event()
        second_tried = threading.Event()

        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        fixture1 = make_signed_tx_and_matching_draft(nonce=0)
        fixture2 = make_signed_tx_and_matching_draft(nonce=1)

        # 2026-07-13 canary hardening: the broadcast route now rejects
        # a returned hash that does not match `keccak256(raw)`, and
        # ALSO requires a post-broadcast visibility observation on
        # `eth_getTransactionByHash` before recording `submitted`.
        # Have the mock echo the exact local hash and separately mock
        # the by-hash visibility helper to return a non-null envelope.
        _local_hash_by_signed = {
            fixture1["signed_tx_hex"].lower(): fixture1["local_tx_hash"],
            fixture2["signed_tx_hex"].lower(): fixture2["local_tx_hash"],
        }

        def _blocking_send(rpc_url, signed_tx_hex):
            first_entered.set()
            # Wait for the second call to have tried the guard.
            if not second_tried.wait(timeout=5):
                raise AssertionError("second broadcast never landed")
            return _local_hash_by_signed[signed_tx_hex.lower()]

        def _by_hash_visible(rpc_url, tx_hash):
            return {"hash": tx_hash, "blockNumber": None}

        results: list[Any] = []
        results_lock = threading.Lock()


        did_first = "safetydraft-conc-first"
        self._wallet_mod._mainnet_store.seed_draft(
            did_first,
            vault_id=_TEST_VAULT_ID,
            network_id="ethereum_mainnet",
            asset="ETH",
            sender_address=fixture1["sender_address"],
            destination_address=fixture1["transaction_to"],
            value_wei=fixture1["value_wei"],
            data_hex=fixture1["data_hex"],
            nonce=fixture1["nonce"],
            gas_limit=fixture1["gas_limit"],
            gas_price=fixture1["gas_price"],
            chain_id=fixture1["chain_id"],
            transaction_to=fixture1["transaction_to"],
        )
        did_second = "safetydraft-conc-second"
        self._wallet_mod._mainnet_store.seed_draft(
            did_second,
            vault_id=_TEST_VAULT_ID,
            network_id="ethereum_mainnet",
            asset="ETH",
            sender_address=fixture2["sender_address"],
            destination_address=fixture2["transaction_to"],
            value_wei=fixture2["value_wei"],
            data_hex=fixture2["data_hex"],
            nonce=fixture2["nonce"],
            gas_limit=fixture2["gas_limit"],
            gas_price=fixture2["gas_price"],
            chain_id=fixture2["chain_id"],
            transaction_to=fixture2["transaction_to"],
        )
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=_blocking_send,
        ), mock.patch.object(
            evm_rpc, "eth_get_transaction_by_hash_at_url",
            side_effect=_by_hash_visible,
        ):
            t1 = threading.Thread(
                target=self._raw_broadcast,
                args=("first", did_first,
                      fixture1["signed_tx_hex"], results, results_lock),
            )
            t2 = threading.Thread(
                target=self._raw_broadcast,
                args=("second", did_second,
                      fixture2["signed_tx_hex"], results, results_lock),
            )
            t1.start()
            # Wait for the first thread to enter the RPC call —
            # meaning it has already acquired the wallet lock.
            if not first_entered.wait(timeout=5):
                raise AssertionError("first broadcast never entered")
            t2.start()
            # Give the second thread a moment to attempt the guard.
            # We can't easily observe the exact moment it hits the
            # lock, so a short sleep then set(). The guard is
            # synchronous under the mainnet-safety mutex so if the
            # second thread has reached the broadcast route body,
            # it has already hit the guard.
            time.sleep(0.2)
            second_tried.set()
            t1.join(timeout=10)
            t2.join(timeout=10)
        by_key = {r[0]: r for r in results}
        first_result = by_key["first"]
        second_result = by_key["second"]
        # First broadcast succeeds with the tx hash.
        self.assertEqual(first_result[1], 200)
        self.assertEqual(first_result[2]["status"], "submitted")
        # Second broadcast is refused with a 409 and the exact
        # `wallet_broadcast_inflight` error envelope.
        self.assertEqual(second_result[1], 409)
        detail = second_result[2].get("detail") or second_result[2]
        self.assertEqual(
            detail.get("wallet_engine"), "wallet_broadcast_inflight",
        )

    def _raw_broadcast(
        self,
        suffix: str,
        draft_id: str,
        signed_tx_hex: str,
        results: list[Any],
        results_lock: threading.Lock,
    ) -> None:
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/"
            "send/broadcast",
            json={
                "signedTransaction": signed_tx_hex,
                "idempotencyKey":    f"walletlock-key-{suffix}",
                "draftId":           draft_id,
            },
        )
        with results_lock:
            results.append((suffix, resp.status_code, resp.json()))

    def _seed_fixture_draft(
        self, suffix: str, nonce: int,
    ) -> tuple[str, dict]:
        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        fixture = make_signed_tx_and_matching_draft(nonce=nonce)
        did = f"safetydraft-{suffix}"
        self._wallet_mod._mainnet_store.seed_draft(
            did,
            vault_id=_TEST_VAULT_ID,
            network_id="ethereum_mainnet",
            asset="ETH",
            sender_address=fixture["sender_address"],
            destination_address=fixture["transaction_to"],
            value_wei=fixture["value_wei"],
            data_hex=fixture["data_hex"],
            nonce=fixture["nonce"],
            gas_limit=fixture["gas_limit"],
            gas_price=fixture["gas_price"],
            chain_id=fixture["chain_id"],
            transaction_to=fixture["transaction_to"],
        )
        return did, fixture

    def test_wallet_lock_released_after_success(self) -> None:
        """Sequential broadcasts against same wallet must both succeed."""
        import evm_rpc
        did1, fixture1 = self._seed_fixture_draft("rel-1a", 10)
        did2, fixture2 = self._seed_fixture_draft("rel-2b", 11)
        _local_hash_by_signed = {
            fixture1["signed_tx_hex"].lower(): fixture1["local_tx_hash"],
            fixture2["signed_tx_hex"].lower(): fixture2["local_tx_hash"],
        }

        def _send_echo_local(rpc_url, signed_tx_hex):
            return _local_hash_by_signed[signed_tx_hex.lower()]

        def _by_hash_visible(rpc_url, tx_hash):
            return {"hash": tx_hash, "blockNumber": None}

        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=_send_echo_local,
        ), mock.patch.object(
            evm_rpc, "eth_get_transaction_by_hash_at_url",
            side_effect=_by_hash_visible,
        ):
            first = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/"
                "send/broadcast",
                json={
                    "signedTransaction": fixture1["signed_tx_hex"],
                    "idempotencyKey":    "seqcheck-key-a",
                    "draftId":           did1,
                },
            )
            second = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/"
                "send/broadcast",
                json={
                    "signedTransaction": fixture2["signed_tx_hex"],
                    "idempotencyKey":    "seqcheck-key-b",
                    "draftId":           did2,
                },
            )
        self.assertEqual(first.status_code, 200, msg=first.json())
        self.assertEqual(first.json()["status"], "submitted")
        self.assertEqual(second.status_code, 200, msg=second.json())
        self.assertEqual(second.json()["status"], "submitted")

    def test_wallet_lock_released_after_rpc_error(self) -> None:
        """Even if the RPC raises, the wallet lock is released."""
        import evm_rpc
        from evm_rpc import EvmRpcError
        did1, fixture1 = self._seed_fixture_draft("err-1a", 20)
        did2, fixture2 = self._seed_fixture_draft("err-2b", 21)
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            side_effect=EvmRpcError("upstream_io"),
        ):
            first = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/"
                "send/broadcast",
                json={
                    "signedTransaction": fixture1["signed_tx_hex"],
                    "idempotencyKey":    "errreleased-key-a",
                    "draftId":           did1,
                },
            )
        self.assertEqual(first.status_code, 200, msg=first.json())
        self.assertEqual(first.json()["reason"], "upstream_io")
        # A subsequent broadcast must not be locked out.
        def _by_hash_visible(rpc_url, tx_hash):
            return {"hash": tx_hash, "blockNumber": None}
        with mock.patch.object(
            evm_rpc, "eth_send_raw_transaction_at_url",
            return_value=fixture2["local_tx_hash"],
        ), mock.patch.object(
            evm_rpc, "eth_get_transaction_by_hash_at_url",
            side_effect=_by_hash_visible,
        ):
            second = self._client.post(
                "/crypto/wallet/network/ethereum_mainnet/ETH/"
                "send/broadcast",
                json={
                    "signedTransaction": fixture2["signed_tx_hex"],
                    "idempotencyKey":    "errreleased-key-b",
                    "draftId":           did2,
                },
            )
        self.assertEqual(second.status_code, 200, msg=second.json())
        self.assertEqual(second.json()["status"], "submitted")


class MainnetContractsAndDecimals(unittest.TestCase):
    """
    Balance and Send share the SAME token contract config + decimals
    source. If either drifts, a token amount could be scaled by the
    wrong number of decimals — a real-money bug on real tokens.
    """

    def setUp(self) -> None:
        _clear_all_env()

    def tearDown(self) -> None:
        _clear_all_env()

    def test_usdt_decimals_default_is_6(self) -> None:
        from vault_config import ethereum_mainnet_token_decimals
        self.assertEqual(
            ethereum_mainnet_token_decimals("USDT_ERC20"), 6,
        )

    def test_usdc_decimals_default_is_6(self) -> None:
        from vault_config import ethereum_mainnet_token_decimals
        self.assertEqual(
            ethereum_mainnet_token_decimals("USDC_ERC20"), 6,
        )

    def test_env_override_respected(self) -> None:
        from vault_config import ethereum_mainnet_token_decimals
        _set_env(ETHEREUM_MAINNET_USDT_DECIMALS="18")
        try:
            self.assertEqual(
                ethereum_mainnet_token_decimals("USDT_ERC20"), 18,
            )
        finally:
            _set_env(ETHEREUM_MAINNET_USDT_DECIMALS=None)

    def test_balance_and_send_use_same_config_source(self) -> None:
        """
        Trace-level guard: both `_get_mainnet_balance` and
        `_create_mainnet_send_draft` MUST call the same
        `evm_networks.token_contract_for(NETWORK_ETHEREUM_MAINNET,
        asset)` and `vault_config.ethereum_mainnet_token_decimals(
        asset)`. If someone forks either code path to a separate
        source of truth, this test fails.
        """
        import inspect
        from routes import crypto_wallet_routes as wallet_module
        balance_src = inspect.getsource(
            wallet_module._get_mainnet_balance,
        )
        send_src = inspect.getsource(
            wallet_module._create_mainnet_send_draft,
        )
        for symbol in (
            "token_contract_for",
            "ethereum_mainnet_token_decimals",
            "erc20_balance_of_at_url",
        ):
            self.assertIn(
                symbol, balance_src,
                msg=f"_get_mainnet_balance no longer uses `{symbol}`",
            )
            self.assertIn(
                symbol, send_src,
                msg=f"_create_mainnet_send_draft no longer uses `{symbol}`",
            )


class MainnetRpcMethodContract(unittest.TestCase):
    """
    The only JSON-RPC methods VaultAI ever sends to a mainnet RPC
    are documented in `evm_rpc.ALLOWED_RPC_METHODS`. Any method
    outside that set raises `method_forbidden` before ever reaching
    the wire. This is what makes VaultAI compatible with any standard
    Ethereum JSON-RPC provider — no archive node, no debug/trace
    methods, no WebSocket, no paid-only endpoints.

    2026-07-13 canary hardening: `eth_getTransactionByHash` was added
    so the broadcast handler can verify the transaction actually
    reached at least one Ethereum node before recording `submitted`.
    """

    def test_allowed_rpc_methods_is_the_public_surface(self) -> None:
        from evm_rpc import ALLOWED_RPC_METHODS
        self.assertEqual(
            ALLOWED_RPC_METHODS,
            frozenset({
                "eth_getBalance",
                "eth_call",
                "eth_getTransactionCount",
                "eth_gasPrice",
                "eth_estimateGas",
                "eth_sendRawTransaction",
                "eth_getTransactionByHash",
                "eth_getTransactionReceipt",
            }),
        )

    def test_forbidden_method_never_reaches_wire(self) -> None:
        """
        `_emit_rpc_at_url` blocks any method not on the allowlist
        before the HTTP client is created — no debug_traceCall,
        no trace_call, no personal_signTransaction leak.
        """
        from evm_rpc import EvmRpcError, _emit_rpc_at_url
        with self.assertRaises(EvmRpcError) as ctx:
            _emit_rpc_at_url(
                "https://example.invalid/mainnet",
                "debug_traceTransaction",
                ["0x" + "0" * 64],
            )
        self.assertEqual(ctx.exception.code, "method_forbidden")

    def test_nonce_uses_pending_block_tag(self) -> None:
        """
        Nonce MUST be fetched with `pending`, not `latest`. If the
        block tag drifts to `latest`, a wallet with a tx already
        in the mempool would draft a new tx with a nonce that is
        already in use — wasted gas at the RPC.
        """
        import evm_rpc
        seen_params: list[Any] = []

        def _capture(rpc_url, method, params):
            seen_params.append((method, params))
            return {"result": "0x0"}

        with mock.patch.object(
            evm_rpc, "_emit_rpc_at_url", side_effect=_capture,
        ):
            evm_rpc.eth_get_transaction_count_at_url(
                "https://example.invalid/mainnet",
                _FROM_ADDR,
            )
        self.assertEqual(len(seen_params), 1)
        method, params = seen_params[0]
        self.assertEqual(method, "eth_getTransactionCount")
        self.assertEqual(params, [_FROM_ADDR, "pending"])


class MainnetTrustBoundary(unittest.TestCase):
    """
    Non-custodial trust boundary — the backend must never receive
    a plaintext private key, seed phrase, mnemonic, recovery phrase,
    or PIN-derived key material. The signing happens client-side;
    only the signed transaction hex reaches the broadcast route.
    """

    def setUp(self) -> None:
        _clear_all_env()
        _enable_mainnet_send()
        self._client, self._app, self._wallet_mod = _make_app_client()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def tearDown(self) -> None:
        _clear_all_env()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def test_broadcast_payload_schema_forbids_plaintext_keys(
        self,
    ) -> None:
        """
        `SendBroadcastPayload.model_config = {'extra': 'forbid'}`
        rejects any unknown field. Pydantic returns 422 before the
        route body ever runs.
        """
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/"
            "send/broadcast",
            json={
                "signedTransaction": _SIGNED_TX,
                "privateKey":        "leaked-would-be-a-blocker",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_broadcast_payload_extra_field_rejected(self) -> None:
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/"
            "send/broadcast",
            json={
                "signedTransaction": _SIGNED_TX,
                "seedPhrase":        "leaked-would-be-a-blocker",
            },
        )
        self.assertEqual(resp.status_code, 422)

    def test_broadcast_payload_pin_field_rejected(self) -> None:
        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/"
            "send/broadcast",
            json={
                "signedTransaction": _SIGNED_TX,
                "pinDerivedKey":     "leaked-would-be-a-blocker",
            },
        )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main()
