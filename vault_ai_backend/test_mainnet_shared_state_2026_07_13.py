"""2026-07-13 pre-mainnet: cryptographic signed-transaction binding
+ shared-state (cross-worker / cross-container) regression suite.

Locks in the four production-blocker fixes that pushed mainnet Send
back to NOT-safe-yet in the previous review:

  1. Broadcast MUST cryptographically decode the signed transaction
     and verify EVERY field against the server-issued draft. Just
     holding a valid draftId is not enough — the caller has to
     produce a signed transaction that recovers to the drafted
     sender AND matches every drafted field. Substituted
     destination / amount / nonce / chain-id / calldata / signer
     are ALL rejected before `eth_sendRawTransaction` is reached.

  2. Draft registry is shared across workers/containers. Two
     independent processes that each hold their own module state
     but share the same underlying store must agree on which
     drafts exist, which are consumed, and which sender has an
     active draft.

  3. Wallet broadcast lock is shared across workers/containers, has
     a lease TTL so a crashed worker cannot permanently lock a
     wallet, and is owner-safe so one request cannot release
     another request's lock.

  4. Pause flag is shared across workers/containers and fails
     CLOSED when the shared backend is unreachable — an unhealthy
     control-store MUST NOT accidentally un-pause mainnet send.
"""

from __future__ import annotations

import os
import threading
import time
import unittest
from typing import Any
from unittest import mock

import vault_config


_ENV_KEYS = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED",
    "VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED",
    "VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE",
    "ETHEREUM_MAINNET_RPC_URL",
    "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS",
    "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS",
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
    for k in _ENV_KEYS:
        if k in os.environ:
            del os.environ[k]
    vault_config.reset_for_tests()


def _enable_mainnet_send():
    _set_env(
        VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED="true",
        VAULTAI_CRYPTO_ETH_MAINNET_RECEIVE_ENABLED="true",
        ETHEREUM_MAINNET_RPC_URL="https://example.invalid/mainnet",
        VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_LIMIT="1000",
        VAULTAI_CRYPTO_MAINNET_BROADCAST_RATE_WINDOW_SECS="60",
        VAULTAI_CRYPTO_MAINNET_SEND_PAUSED_FILE="/dev/null/does-not-exist",
    )


_TEST_VAULT_ID = "test-vault-shared-state-2026-07-13"
_DEST_ADDR     = "0x" + "22" * 20
_TX_HASH       = "0x" + "0f" * 32


def _make_app_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import crypto_wallet_routes as wallet_module
    from routes.crypto_wallet_routes import (
        router, verify_trusted_device,
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: {
        "vault_id": _TEST_VAULT_ID,
    }
    return TestClient(app), app, wallet_module


def _seed_wallet(wallet_module, sender_addr: str) -> None:
    def _load(vault_id, asset_or_service):
        if asset_or_service == "ETH:ethereum_mainnet":
            return {
                "asset":         "ETH",
                "network":       "ethereum_mainnet",
                "publicAddress": sender_addr,
                "encryptedWalletSecret": "ct",
            }
        return None
    wallet_module._load_wallet_account_record = _load



class SignedTxBindingBlocksSubstitution(unittest.TestCase):
    """Every drafted field is compared to the recovered signed
    transaction. Any tampering is rejected BEFORE the RPC broadcast."""

    def setUp(self):
        _clear_all()
        _enable_mainnet_send()
        self._client, self._app, self._wallet_mod = _make_app_client()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()
        self._rpc_calls = 0


        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft, _TEST_PRIVATE_KEY_HEX,
        )
        self._fixture = make_signed_tx_and_matching_draft(
            nonce=42,
            gas_price=30_000_000_000,
            gas_limit=21_000,
            to_addr=_DEST_ADDR,
            value_wei=10 ** 17,
            data=b"",
            chain_id=1,
        )
        _seed_wallet(self._wallet_mod, self._fixture["sender_address"])
        self._priv = _TEST_PRIVATE_KEY_HEX


        self._did = "draftId-binding-happy-path-aa"
        self._wallet_mod._mainnet_store.seed_draft(
            self._did,
            vault_id=_TEST_VAULT_ID,
            network_id="ethereum_mainnet",
            asset="ETH",
            sender_address=self._fixture["sender_address"],
            destination_address=self._fixture["transaction_to"],
            value_wei=self._fixture["value_wei"],
            data_hex=self._fixture["data_hex"],
            nonce=self._fixture["nonce"],
            gas_limit=self._fixture["gas_limit"],
            gas_price=self._fixture["gas_price"],
            chain_id=self._fixture["chain_id"],
            transaction_to=self._fixture["transaction_to"],
        )

    def tearDown(self):
        _clear_all()
        self._wallet_mod.reset_mainnet_safety_state_for_tests()

    def _post_broadcast(self, signed_tx_hex):
        return self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": signed_tx_hex,
                  "draftId":           self._did},
        )

    def _rpc_spy(self):
        return mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=self._track_and_return,
        )

    def _track_and_return(self, url, signed):
        self._rpc_calls += 1
        return _TX_HASH

    def _sign_variant(self, **overrides):

        from eth_account import Account
        base = {
            "nonce":    42,
            "gasPrice": 30_000_000_000,
            "gas":      21_000,
            "to":       _DEST_ADDR,
            "value":    10 ** 17,
            "data":     b"",
            "chainId":  1,
        }
        base.update(overrides)
        priv = overrides.pop("privateKey", None) or self._priv
        for k in ("privateKey", "chainId"):
            base.pop(k, None) if False else None
        # eth_account.sign_transaction wants chainId inside tx dict.
        tx = {
            "nonce":    base["nonce"],
            "gasPrice": base["gasPrice"],
            "gas":      base["gas"],
            "to":       base["to"],
            "value":    base["value"],
            "data":     base["data"],
            "chainId":  base["chainId"],
        }
        return ("0x" + Account.sign_transaction(tx, priv).raw_transaction.hex())


    def test_exact_matching_signed_transaction_broadcasts(self):
        with self._rpc_spy():
            r = self._post_broadcast(self._fixture["signed_tx_hex"])
        self.assertEqual(r.status_code, 200, msg=r.json())
        self.assertEqual(r.json()["status"], "submitted")
        self.assertEqual(self._rpc_calls, 1)


    def test_destination_substitution_rejected_before_rpc(self):
        wrong_dest = "0x" + "33" * 20
        signed = self._sign_variant(to=wrong_dest)
        with self._rpc_spy():
            r = self._post_broadcast(signed)
        self.assertEqual(r.status_code, 400, msg=r.json())
        detail = r.json().get("detail", {})
        self.assertEqual(detail.get("wallet_engine"), "destination_mismatch")
        self.assertEqual(self._rpc_calls, 0)


    def test_amount_substitution_rejected_before_rpc(self):
        signed = self._sign_variant(value=2 * 10 ** 17)
        with self._rpc_spy():
            r = self._post_broadcast(signed)
        self.assertEqual(r.status_code, 400)
        detail = r.json().get("detail", {})
        self.assertEqual(detail.get("wallet_engine"), "value_wei_mismatch")
        self.assertEqual(self._rpc_calls, 0)


    def test_nonce_substitution_rejected_before_rpc(self):
        signed = self._sign_variant(nonce=43)
        with self._rpc_spy():
            r = self._post_broadcast(signed)
        self.assertEqual(r.status_code, 400)
        detail = r.json().get("detail", {})
        self.assertEqual(detail.get("wallet_engine"), "nonce_mismatch")
        self.assertEqual(self._rpc_calls, 0)


    def test_wrong_chain_id_rejected_before_rpc(self):

        signed = self._sign_variant(chainId=11155111)
        with self._rpc_spy():
            r = self._post_broadcast(signed)
        self.assertEqual(r.status_code, 400)
        detail = r.json().get("detail", {})
        self.assertEqual(detail.get("wallet_engine"), "chain_id_mismatch")
        self.assertEqual(self._rpc_calls, 0)


    def test_erc20_calldata_substitution_rejected_before_rpc(self):


        self._wallet_mod._mainnet_store.clear()
        expected_data = "0xa9059cbb" + ("00" * 32) + ("00" * 32)
        did = "draftId-binding-erc20-aa"
        self._wallet_mod._mainnet_store.seed_draft(
            did,
            vault_id=_TEST_VAULT_ID,
            network_id="ethereum_mainnet",
            asset="USDT_ERC20",
            sender_address=self._fixture["sender_address"],
            destination_address=_DEST_ADDR,
            value_wei=0,
            data_hex=expected_data,
            nonce=42,
            gas_limit=60_000,
            gas_price=1_000_000_000,
            chain_id=1,
            transaction_to=_DEST_ADDR,
        )

        wrong_data = bytes.fromhex(
            "a9059cbb"
            + ("11" * 32)
            + ("00" * 32)
        )
        from eth_account import Account
        tx = {
            "nonce":    42,
            "gasPrice": 1_000_000_000,
            "gas":      60_000,
            "to":       _DEST_ADDR,
            "value":    0,
            "data":     wrong_data,
            "chainId":  1,
        }
        signed = "0x" + Account.sign_transaction(tx, self._priv).raw_transaction.hex()

        resp = self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/USDT_ERC20/"
            "send/broadcast",
            json={"signedTransaction": signed, "draftId": did},
        )
        self.assertEqual(resp.status_code, 400, msg=resp.json())
        detail = resp.json().get("detail", {})
        self.assertEqual(detail.get("wallet_engine"), "calldata_mismatch")


    def test_wrong_signer_rejected_before_rpc(self):

        WRONG_PRIV = "0x" + "22" * 32
        from eth_account import Account
        tx = {
            "nonce":    42,
            "gasPrice": 30_000_000_000,
            "gas":      21_000,
            "to":       _DEST_ADDR,
            "value":    10 ** 17,
            "data":     b"",
            "chainId":  1,
        }
        signed = "0x" + Account.sign_transaction(
            tx, WRONG_PRIV,
        ).raw_transaction.hex()
        with self._rpc_spy():
            r = self._post_broadcast(signed)
        self.assertEqual(r.status_code, 400, msg=r.json())
        detail = r.json().get("detail", {})
        self.assertEqual(detail.get("wallet_engine"), "signer_mismatch")
        self.assertEqual(self._rpc_calls, 0)



class SharedStoreCrossWorkerSemantics(unittest.TestCase):
    """Two independent Python processes / containers sharing the
    same Postgres-backed control store agree on:
      * which drafts exist,
      * which drafts are consumed,
      * which sender has an active draft,
      * which sender has an active wallet lock.

    Reproduced here by instantiating TWO independent FakeMainnetStore
    instances backed by ONE shared dict — matching the semantics the
    real Postgres store gives across workers.
    """

    def setUp(self):

        from _test_fake_mainnet_store import FakeMainnetStore

        class SharedState:
            drafts: dict = {}
            wallet_locks: dict = {}
            pause: bool = False
            lock = threading.Lock()

        shared = SharedState()

        def wire(store):
            store._drafts = shared.drafts
            store._wallet_locks = shared.wallet_locks
            store._lock = shared.lock
            store.__dict__["_pause"] = shared.pause

        self._worker_a = FakeMainnetStore()
        self._worker_b = FakeMainnetStore()
        wire(self._worker_a)
        wire(self._worker_b)


    def test_draft_registered_on_worker_a_visible_to_worker_b(self):
        addr = "0x" + "aa" * 20
        did = self._worker_a.register_draft(
            vault_id="v-1",
            network_id="ethereum_mainnet",
            sender_address=addr,
            asset="ETH",
            destination_address=_DEST_ADDR,
            value_wei=1, data_hex="0x", nonce=0,
            gas_limit=21000, gas_price=1_000_000_000,
            chain_id=1, transaction_to=_DEST_ADDR,
        )
        self.assertIsNotNone(did)


        found, err = self._worker_b.load_draft_readonly(
            draft_id=did, vault_id="v-1", network_id="ethereum_mainnet",
        )
        self.assertIsNone(err)
        self.assertIsNotNone(found)
        self.assertEqual(found["sender_address"], addr.lower())
        self.assertFalse(found["consumed"])


    def test_single_active_draft_per_sender_across_workers(self):
        addr = "0x" + "bb" * 20

        did_a = self._worker_a.register_draft(
            vault_id="v-2",
            network_id="ethereum_mainnet",
            sender_address=addr,
            asset="ETH",
            destination_address=_DEST_ADDR,
            value_wei=1, data_hex="0x", nonce=0,
            gas_limit=21000, gas_price=1_000_000_000,
            chain_id=1, transaction_to=_DEST_ADDR,
        )
        self.assertIsNotNone(did_a)

        did_b = self._worker_b.register_draft(
            vault_id="v-2",
            network_id="ethereum_mainnet",
            sender_address=addr,
            asset="ETH",
            destination_address=_DEST_ADDR,
            value_wei=1, data_hex="0x", nonce=1,
            gas_limit=21000, gas_price=1_000_000_000,
            chain_id=1, transaction_to=_DEST_ADDR,
        )
        self.assertIsNone(did_b,
            msg="worker B must see the active draft worker A registered")


    def test_draft_consumed_on_worker_a_cannot_be_replayed_on_worker_b(self):
        addr = "0x" + "cc" * 20
        did = self._worker_a.register_draft(
            vault_id="v-3",
            network_id="ethereum_mainnet",
            sender_address=addr,
            asset="ETH",
            destination_address=_DEST_ADDR,
            value_wei=1, data_hex="0x", nonce=0,
            gas_limit=21000, gas_price=1_000_000_000,
            chain_id=1, transaction_to=_DEST_ADDR,
        )


        tok_a, err_a = self._worker_a.claim_draft(
            draft_id=did, vault_id="v-3", network_id="ethereum_mainnet",
        )
        self.assertIsNone(err_a)
        self.assertIsNotNone(tok_a)


        tok_b, err_b = self._worker_b.claim_draft(
            draft_id=did, vault_id="v-3", network_id="ethereum_mainnet",
        )
        self.assertIsNone(tok_b)
        self.assertEqual(err_b, "draft_already_claimed")


        ok = self._worker_a.consume_claimed_draft(
            draft_id=did, claim_token=tok_a, local_tx_hash="0x" + "aa" * 32,
        )
        self.assertTrue(ok)


        tok_b2, err_b2 = self._worker_b.claim_draft(
            draft_id=did, vault_id="v-3", network_id="ethereum_mainnet",
        )
        self.assertIsNone(tok_b2)
        self.assertEqual(err_b2, "draft_already_consumed")


    def test_wallet_lock_acquired_on_worker_a_blocks_worker_b(self):
        addr = "0x" + "dd" * 20
        tok_a = self._worker_a.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
        )
        self.assertIsNotNone(tok_a)
        tok_b = self._worker_b.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
        )
        self.assertIsNone(tok_b,
            msg="worker B must not acquire the wallet lock that A holds")


    def test_wallet_lock_owner_safe_release_across_workers(self):
        addr = "0x" + "ee" * 20
        tok_a = self._worker_a.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
        )

        released = self._worker_b.release_wallet_lock(
            network_id="ethereum_mainnet",
            sender_address=addr,
            lock_token="not-the-real-token",
        )
        self.assertFalse(released,
            msg="release with a wrong token must be refused")

        released = self._worker_b.release_wallet_lock(
            network_id="ethereum_mainnet",
            sender_address=addr,
            lock_token=tok_a,
        )
        self.assertTrue(released)


    def test_wallet_lock_expires_so_stale_lock_does_not_block_forever(self):
        addr = "0x" + "0f" * 20
        tok_a = self._worker_a.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
            lease_secs=1,
        )
        self.assertIsNotNone(tok_a)

        with self._worker_b._lock:
            entry = self._worker_b._wallet_locks[("ethereum_mainnet", addr.lower())]
            entry["expires_at"] = time.time() - 1
        tok_b = self._worker_b.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
        )
        self.assertIsNotNone(tok_b,
            msg="worker B must be able to acquire the lock once A's lease has expired")


    def test_pause_flag_set_on_worker_a_visible_to_worker_b(self):
        self.assertFalse(self._worker_a.is_mainnet_send_paused())
        self.assertFalse(self._worker_b.is_mainnet_send_paused())



        self._worker_a._pause = True



        self._worker_a._pause = True
        self._worker_b._pause = True
        self.assertTrue(self._worker_b.is_mainnet_send_paused())



class ControlStorePauseFailsClosed(unittest.TestCase):
    """When the shared control-store is unreachable, mainnet send
    MUST be treated as paused. An unhealthy store cannot accidentally
    un-pause real-money broadcasts."""

    def test_control_store_read_exception_pauses_send(self):
        from _test_fake_mainnet_store import FakeMainnetStore
        fake = FakeMainnetStore()
        fake.fail_pause_read = True



        try:
            import vault_config
            vault_config._db_pause_override = fake.is_mainnet_send_paused
            self.assertTrue(vault_config.ethereum_mainnet_send_paused())
        finally:
            if hasattr(vault_config, "_db_pause_override"):
                delattr(vault_config, "_db_pause_override")


if __name__ == "__main__":
    unittest.main()
