"""2026-07-13 pre-mainnet: draft state-machine + ambiguous-RPC
regression suite.

Locks in the four safety fixes introduced by the CLAIM -> CONSUME
state machine:

  1. A signed-tx VERIFICATION FAILURE MUST NOT permanently consume
     a legitimate draft. The verifier runs before the claim; a
     failure returns HTTP 400 but leaves the draft in ACTIVE state
     so the honest client can re-sign against the same draft.

  2. A pause flag flipped AFTER a draft is issued but BEFORE it is
     broadcast MUST block the broadcast.

  3. A structural verification failure MUST leave the draft
     claimable by a subsequent correct signed tx. Once the CORRECT
     signed tx is submitted the draft moves CLAIMED -> CONSUMED and
     is broadcast exactly once.

  4. An ambiguous RPC timeout AFTER the raw transaction has been
     submitted MUST return `submission_uncertain` with the local
     `txHash`. A subsequent retry with the SAME signed tx sees the
     draft is CONSUMED and returns `already_submitted` with the
     stored `txHash` — no double-broadcast, no burn of an unrelated
     draft.
"""

from __future__ import annotations

import os
import unittest
from typing import Any
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


def _clear_all():
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


_VAULT_ID = "state-machine-vault"
# 2026-07-13 canary hardening: broadcast handler now rejects a
# returned hash that does not match `keccak256(raw)` and requires
# a post-broadcast visibility observation before recording
# `submitted`. These helpers make the pre-hardening test structure
# still exercise a successful broadcast — the mock echoes the local
# hash and `eth_getTransactionByHash` reports the tx as visible.
from _test_broadcast_mocks import (
    echo_local_hash as _echo_local_hash,
    visible_by_hash as _visible_by_hash,
)


def _make_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as m
    from routes.crypto_wallet_routes import (
        router, verify_trusted_device,
    )
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


class DraftClaimStateMachine(unittest.TestCase):
    """The CLAIM -> CONSUME machine correctly retains the draft on
    verification failure and correctly commits it on success."""

    def setUp(self):
        _clear_all()
        _enable()
        # 2026-07-13 canary hardening: baseline the post-broadcast
        # visibility helper to "visible". Tests that specifically
        # probe the invisible / not-yet-visible cases replace this
        # inside the test body.
        self._by_hash_patcher = mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            side_effect=_visible_by_hash,
        )
        self._by_hash_patcher.start()
        self.addCleanup(self._by_hash_patcher.stop)
        self._client, self._app, self._m = _make_client()
        self._m.reset_mainnet_safety_state_for_tests()

        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        self._fx = make_signed_tx_and_matching_draft(nonce=7)
        _seed_wallet(self._m, self._fx["sender_address"])

        self._did = "sm-draftId-happy-aa"
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
        _clear_all()
        self._m.reset_mainnet_safety_state_for_tests()

    def _broadcast(self, signed_tx_hex):
        return self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": signed_tx_hex,
                  "draftId":           self._did},
        )

    def test_verify_failure_does_not_burn_draft(self):
        """The central bug fix: a mismatched signed tx returns 400
        but leaves the draft in ACTIVE state so a subsequent
        correct signed tx can still consume it."""
        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        bad = make_signed_tx_and_matching_draft(nonce=999)
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ) as rpc:

            r1 = self._broadcast(bad["signed_tx_hex"])
            self.assertEqual(r1.status_code, 400)
            self.assertEqual(rpc.call_count, 0,
                msg="RPC must not run when verification fails")


            r2 = self._broadcast(self._fx["signed_tx_hex"])
            self.assertEqual(r2.status_code, 200, msg=r2.json())
            self.assertEqual(r2.json()["status"], "submitted")
            self.assertEqual(rpc.call_count, 1)

    def test_multiple_verify_failures_do_not_burn_draft(self):
        """Even repeated verification failures do not consume the
        draft. The client can keep re-signing until it gets it right."""
        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ) as rpc:
            for _ in range(3):
                bad = make_signed_tx_and_matching_draft(nonce=1234)
                r = self._broadcast(bad["signed_tx_hex"])
                self.assertEqual(r.status_code, 400)
            self.assertEqual(rpc.call_count, 0)
            r_ok = self._broadcast(self._fx["signed_tx_hex"])
            self.assertEqual(r_ok.status_code, 200, msg=r_ok.json())
            self.assertEqual(rpc.call_count, 1)

    def test_successful_broadcast_records_local_tx_hash(self):
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r.status_code, 200)


        d = self._m._mainnet_store._drafts[self._did]
        self.assertIsNotNone(d["consumed_at"])
        self.assertIsNotNone(d["local_tx_hash"])
        self.assertTrue(d["local_tx_hash"].startswith("0x"))
        self.assertEqual(len(d["local_tx_hash"]), 66)

    def test_pause_flipped_after_draft_blocks_broadcast(self):
        """A pause flag flipped AFTER a draft is issued MUST block
        the broadcast — the draft is left intact for future action."""
        self._m._mainnet_store.set_mainnet_send_paused(True)
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ) as rpc:
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(
            body.get("wallet_engine"), "mainnet_send_paused",
            msg=body,
        )
        self.assertEqual(rpc.call_count, 0)


        d = self._m._mainnet_store._drafts[self._did]
        self.assertIsNone(d["consumed_at"])


class AmbiguousRpcTimeout(unittest.TestCase):
    """RPC timeout AFTER a submission was potentially accepted must
    return `submission_uncertain` with the local tx hash; subsequent
    retry with the same signed tx returns `already_submitted`."""

    def setUp(self):
        _clear_all()
        _enable()
        # 2026-07-13 canary hardening: baseline `eth_getTransactionByHash`
        # to "visible" for tests that don't override it.
        self._by_hash_patcher = mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            side_effect=_visible_by_hash,
        )
        self._by_hash_patcher.start()
        self.addCleanup(self._by_hash_patcher.stop)
        self._client, self._app, self._m = _make_client()
        self._m.reset_mainnet_safety_state_for_tests()
        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        self._fx = make_signed_tx_and_matching_draft(nonce=13)
        _seed_wallet(self._m, self._fx["sender_address"])
        self._did = "sm-draftId-ambig-aa"
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
        _clear_all()
        self._m.reset_mainnet_safety_state_for_tests()

    def _broadcast(self, signed_tx_hex):
        return self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": signed_tx_hex,
                  "draftId":           self._did},
        )

    def test_upstream_timeout_returns_submission_uncertain_with_local_hash(
        self,
    ):
        from evm_rpc import EvmRpcError
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=EvmRpcError("upstream_timeout"),
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "submission_uncertain")
        self.assertEqual(body["reason"], "upstream_timeout")
        self.assertTrue(body["txHash"].startswith("0x"))
        self.assertEqual(len(body["txHash"]), 66)

    def test_retry_after_ambiguous_timeout_stays_uncertain(self):
        """Client whose HTTP connection dropped after RPC timeout
        must be able to re-submit with the same signed_tx and see
        `submission_uncertain` again — NOT `already_submitted`.

        2026-07-13: this test previously asserted
        `already_submitted`. That was the CENTRAL BUG the outcome-
        column rework fixes. `submission_uncertain` on first response
        MUST replay as `submission_uncertain`, not silently upgrade
        to `already_submitted` — the client must be told the on-
        chain state is still unknown so they keep polling.
        """
        from evm_rpc import EvmRpcError

        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=EvmRpcError("upstream_timeout"),
        ):
            r1 = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["status"], "submission_uncertain")
        first_hash = r1.json()["txHash"]

        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ) as rpc:
            r2 = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r2.status_code, 200, msg=r2.json())
        self.assertEqual(
            r2.json()["status"], "submission_uncertain",
            msg="Ambiguous outcome MUST NOT be silently upgraded to "
                "already_submitted on replay -- the client still "
                "does not know if the tx is on-chain.",
        )
        self.assertEqual(r2.json()["txHash"], first_hash)
        self.assertEqual(rpc.call_count, 0,
            msg="Second RPC broadcast MUST NOT run for a same-tx retry")

    def test_retry_with_different_signed_tx_rejected_as_consumed(self):
        """After the draft is CONSUMED, a retry with a DIFFERENT
        signed tx is rejected with 409 `draft_already_consumed` —
        not silently accepted as a fresh broadcast."""
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ):
            r_ok = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r_ok.status_code, 200)


        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        different = make_signed_tx_and_matching_draft(nonce=13, value_wei=999)
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            return_value="0x" + "aa" * 32,
        ) as rpc:
            r_bad = self._broadcast(different["signed_tx_hex"])
        self.assertEqual(r_bad.status_code, 409, msg=r_bad.json())
        detail = r_bad.json().get("detail", {})
        self.assertEqual(
            detail.get("wallet_engine"), "draft_already_consumed",
        )
        self.assertEqual(rpc.call_count, 0)


if __name__ == "__main__":
    unittest.main()
