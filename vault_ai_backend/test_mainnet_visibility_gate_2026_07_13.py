"""2026-07-13 (canary hardening): regression suite for the false-
`submitted` bug.

Production canary summary (do NOT rebroadcast — this fixture is
declarative, not a live transaction):

    draft_id      = "02ctGuBjqYXERNxD1k5AiplGgc_dyg5a"
    local_hash    = "0x783ddc09728b26884c78da47ee408c40daa75c89e03700deb216e98ed77c415b"
    sender        = "0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855"
    destination   = "0x7C49215A2cB86aaC3e6308EA4D6206912578e870"
    value_wei     = 5_600_000_000_000_000

The backend persisted `broadcast_outcome="submitted"` yet:
    eth_getTransactionByHash → null
    eth_getTransactionReceipt → null
    sender balance unchanged
    outgoing tx never appeared in Activity.

Root cause: `_broadcast_mainnet_signed_transaction` marked the draft
`submitted` as soon as `eth_sendRawTransaction` returned a valid-shaped
hash. No visibility follow-up. This suite enforces the new rules:

    * mismatched returned hash → submission_uncertain (never submitted)
    * hash matched but never visible → submission_uncertain
    * hash matched and visible via getTransactionByHash → submitted
    * hash matched and visible via getTransactionReceipt → submitted
    * getTransactionByHash null + getTransactionReceipt null in status
      endpoint → `not_found` (not `pending`)

The canary fixture is compiled at import time (a fresh signed tx
that has NEVER been broadcast) so the regression can never
accidentally hit the network.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import vault_config


_ENV = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE",
    "ETHEREUM_MAINNET_RPC_URL",
    "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT",
    "VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS",
)


def _set_env(**kv):
    for k, v in kv.items():
        if v is None:
            if k in os.environ:
                del os.environ[k]
        else:
            os.environ[k] = v
    vault_config.reset_for_tests()


def _clear_env():
    for k in _ENV:
        if k in os.environ:
            del os.environ[k]
    vault_config.reset_for_tests()


def _enable():
    _set_env(
        VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT="1000",
        VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS="60",
        VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE="/dev/null/no",
    )


_VAULT_ID = "canary-visibility-vault"


def _make_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as m
    from routes.crypto_wallet_routes import router, verify_trusted_device
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": _VAULT_ID,
    }
    return TestClient(app), app, m


def _seed_wallet(m, addr):
    def _load(vault_id, key):
        if key == "ETH:ethereum_mainnet":
            return {
                "asset": "ETH", "network": "ethereum_mainnet",
                "publicAddress": addr, "encryptedWalletSecret": "ct",
            }
        return None
    m._load_wallet_account_record = _load


class VisibilityGate(unittest.TestCase):

    def setUp(self):
        _clear_env()
        _enable()
        # Speed up the bounded visibility poll so tests don't sleep.
        from routes import crypto_wallet_routes as m
        self._orig_visibility_polls = m._VISIBILITY_POLLS
        self._orig_visibility_interval = m._VISIBILITY_INTERVAL_S
        m._VISIBILITY_POLLS = 2
        m._VISIBILITY_INTERVAL_S = 0.0
        self._client, self._app, self._m = _make_client()
        self._m.reset_mainnet_safety_state_for_tests()
        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        self._fx = make_signed_tx_and_matching_draft(nonce=42)
        _seed_wallet(self._m, self._fx["sender_address"])
        self._did = "canary-visibility-gate-aa"
        self._m._mainnet_store.seed_draft(
            self._did,
            vault_id=_VAULT_ID,
            network_id="ethereum_mainnet",
            asset="ETH",
            sender_address=self._fx["sender_address"],
            destination_address=self._fx["transaction_to"],
            value_wei=self._fx["value_wei"],
            data_hex=self._fx["data_hex"],
            nonce=self._fx["nonce"],
            gas_limit=self._fx["gas_limit"],
            gas_price=self._fx["gas_price"],
            chain_id=self._fx["chain_id"],
            transaction_to=self._fx["transaction_to"],
        )

    def tearDown(self):
        from routes import crypto_wallet_routes as m
        m._VISIBILITY_POLLS = self._orig_visibility_polls
        m._VISIBILITY_INTERVAL_S = self._orig_visibility_interval
        _clear_env()
        self._m.reset_mainnet_safety_state_for_tests()

    def _broadcast(self):
        return self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": self._fx["signed_tx_hex"],
                  "draftId": self._did},
        )

    def test_rpc_returned_hash_but_tx_never_visible_is_submission_uncertain(
        self,
    ):
        """The EXACT canary shape: RPC echoed a valid-shaped hash
        (the local one, so the mismatch guard does NOT trip) but no
        Ethereum node ever named the transaction. The old code
        recorded `submitted`. The new code MUST record
        `submission_uncertain`."""
        from _test_broadcast_mocks import echo_local_hash
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=echo_local_hash,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            return_value=None,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            return_value=None,
        ):
            r = self._broadcast()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "submission_uncertain",
            msg="THE canary regression: RPC-returned-hash + no on-"
                "chain visibility MUST NOT be classified as submitted.")
        self.assertEqual(body["reason"], "not_yet_visible")
        # The envelope MUST carry the local hash so the client can
        # keep polling; local hash starts with 0x + 64 hex.
        self.assertTrue(body["txHash"].startswith("0x"))
        self.assertEqual(len(body["txHash"]), 66)
        self.assertEqual(
            body["txHash"], self._fx["local_tx_hash"],
            msg="Local hash returned to client MUST match keccak256(raw).",
        )
        # DB-level: the draft's broadcast_outcome must be recorded
        # as submission_uncertain (NOT submitted).
        d = self._m._mainnet_store._drafts[self._did]
        self.assertEqual(
            d["broadcast_outcome"], "submission_uncertain",
            msg="Persistent outcome MUST reflect uncertain state.",
        )
        self.assertIsNotNone(d["outcome_recorded_at"])

    def test_rpc_returned_mismatched_hash_is_submission_uncertain(self):
        """The RPC returned a valid-shaped hash but DIFFERENT from
        keccak256(raw). This is not proof of submission — classify
        as `returned_hash_mismatch` uncertain."""
        wrong_hash = "0x" + "5c" * 32
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            return_value=wrong_hash,
        ):
            r = self._broadcast()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "submission_uncertain")
        self.assertEqual(body["reason"], "returned_hash_mismatch")
        # Envelope MUST carry the LOCAL hash, not the RPC-echoed one.
        self.assertEqual(body["txHash"], self._fx["local_tx_hash"])

    def test_rpc_returned_hash_and_by_hash_visible_is_submitted(self):
        """Happy path: RPC echoes local hash + `getTransactionByHash`
        finds the tx → submitted."""
        from _test_broadcast_mocks import echo_local_hash, visible_by_hash
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=echo_local_hash,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            side_effect=visible_by_hash,
        ):
            r = self._broadcast()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "submitted")
        self.assertEqual(body["txHash"], self._fx["local_tx_hash"])
        d = self._m._mainnet_store._drafts[self._did]
        self.assertEqual(d["broadcast_outcome"], "submitted")

    def test_rpc_returned_hash_and_receipt_visible_is_submitted(self):
        """`getTransactionByHash` null but `getTransactionReceipt`
        non-null (very fast inclusion) → submitted."""
        from _test_broadcast_mocks import echo_local_hash
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=echo_local_hash,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            return_value=None,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            return_value={"status": "0x1", "blockNumber": "0x100"},
        ):
            r = self._broadcast()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "submitted")

    def test_visibility_becomes_visible_after_first_poll(self):
        """Simulate the tx appearing on the SECOND `getTransactionByHash`
        call (first poll returned null; second poll returned an
        envelope). Classification MUST be `submitted`."""
        from _test_broadcast_mocks import echo_local_hash
        call_state = {"n": 0}

        def _lazy_by_hash(url, tx_hash):
            call_state["n"] += 1
            if call_state["n"] == 1:
                return None
            return {"hash": tx_hash, "blockNumber": None}

        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=echo_local_hash,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            side_effect=_lazy_by_hash,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            return_value=None,
        ):
            r = self._broadcast()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "submitted")

    def test_ambiguous_rpc_error_during_visibility_polls_is_uncertain(self):
        """`eth_getTransactionByHash` raising an ambiguous EvmRpcError
        (e.g. upstream_timeout) throughout the poll window MUST NOT
        upgrade the outcome to submitted."""
        from _test_broadcast_mocks import echo_local_hash
        from evm_rpc import EvmRpcError
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=echo_local_hash,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            side_effect=EvmRpcError("upstream_timeout"),
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            side_effect=EvmRpcError("upstream_timeout"),
        ):
            r = self._broadcast()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "submission_uncertain")


class TransactionStatusEndpoint(unittest.TestCase):
    """Post-broadcast `GET /transaction/{tx_hash}` must distinguish
    `not_found` (no node names this hash) from `pending` (in mempool).
    """

    def setUp(self):
        _clear_env()
        _enable()
        self._client, self._app, self._m = _make_client()

    def tearDown(self):
        _clear_env()

    def _status(self, tx_hash):
        return self._client.get(
            f"/crypto/wallet/network/ethereum_mainnet/ETH/"
            f"transaction/{tx_hash}",
        )

    def _hash(self):
        return "0x" + "ab" * 32

    def test_not_found_when_both_by_hash_and_receipt_null(self):
        """The canary case: no node knows this hash. Status MUST be
        `not_found` — NOT `pending` (which would be misleading and
        keep the local Activity row stuck showing 'pending' forever)."""
        with mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            return_value=None,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            return_value=None,
        ):
            r = self._status(self._hash())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "not_found")

    def test_pending_when_by_hash_visible_but_receipt_null(self):
        """In mempool, not yet mined."""
        with mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            return_value={"hash": self._hash(), "blockNumber": None},
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            return_value=None,
        ):
            r = self._status(self._hash())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "pending")

    def test_confirmed_when_receipt_status_0x1(self):
        with mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            return_value={"hash": self._hash(), "blockNumber": "0x100"},
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            return_value={"status": "0x1", "blockNumber": "0x100"},
        ):
            r = self._status(self._hash())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "confirmed")
        self.assertEqual(r.json()["blockNumber"], 0x100)

    def test_failed_when_receipt_status_0x0(self):
        with mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            return_value={"hash": self._hash(), "blockNumber": "0x100"},
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            return_value={"status": "0x0", "blockNumber": "0x100"},
        ):
            r = self._status(self._hash())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "failed")

    def test_invalid_tx_hash_is_422(self):
        r = self._status("not-a-hash")
        self.assertEqual(r.status_code, 422)


class CanaryFixtureRegression(unittest.TestCase):
    """The exact production canary fixture, classified against the new
    rules. This does NOT rebroadcast — no live RPC ever runs. The tx
    is only used to prove the classifier produces `submission_uncertain`
    for its shape (mock RPCs simulating the observed real behavior:
    hash echoed but not visible)."""

    _CANARY_DRAFT_ID = "02ctGuBjqYXERNxD1k5AiplGgc_dyg5a"
    _CANARY_LOCAL_HASH = (
        "0x783ddc09728b26884c78da47ee408c40daa75c89e03700deb216e98ed77c415b"
    )
    _CANARY_SENDER = "0xDA3D577784075Eb7011E60Cb8A5f0AE33f682855"
    _CANARY_DEST = "0x7C49215A2cB86aaC3e6308EA4D6206912578e870"
    _CANARY_VALUE_WEI = 5_600_000_000_000_000

    def test_canary_shape_classifies_uncertain_not_submitted(self):
        """The classification helper `_mainnet_visibility_after_broadcast`
        must return `visible=False` when both visibility RPCs return
        null — which is the exact production canary state."""
        from routes.crypto_wallet_routes import (
            _mainnet_visibility_after_broadcast,
        )
        with mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            return_value=None,
        ), mock.patch(
            "evm_rpc.eth_get_transaction_receipt_at_url",
            return_value=None,
        ):
            visible, reason = _mainnet_visibility_after_broadcast(
                rpc_url="https://example.invalid/mainnet",
                local_tx_hash=self._CANARY_LOCAL_HASH,
                max_polls=2,
                interval_s=0.0,
            )
        self.assertFalse(visible)
        # `reason` MUST NOT contain the hash itself.
        self.assertNotIn(self._CANARY_LOCAL_HASH, reason)
        self.assertNotIn(self._CANARY_SENDER, reason)
        self.assertNotIn(self._CANARY_DEST, reason)


if __name__ == "__main__":
    unittest.main()
