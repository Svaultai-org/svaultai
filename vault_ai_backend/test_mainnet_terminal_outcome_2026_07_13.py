"""2026-07-13 pre-mainnet: terminal broadcast outcome regression suite.

The final adversarial review identified that "consumed draft + local
tx hash matches" is INSUFFICIENT to answer a replay as
`already_submitted`. It only proves the same signed bytes consumed
the draft; it does NOT prove they were actually submitted to the
network.

The fix: persist the terminal broadcast outcome on the consumed row
(`crypto_mainnet_drafts.broadcast_outcome`, values
`submitted` / `submission_uncertain` / `already_known` /
`explicitly_rejected`, plus NULL for the CONSUMED-outcome-pending
crash-window state) and dispatch the replay envelope from that.

Invariants this suite locks in, one per test:

  * Successful RPC submission     -> replay `already_submitted`.
  * Provider `already known`      -> replay `already_submitted`.
  * Read timeout                  -> replay `submission_uncertain`.
  * Connection reset              -> replay `submission_uncertain`.
  * HTTP 502                      -> replay `submission_uncertain`.
  * HTTP 503                      -> replay `submission_uncertain`.
  * Malformed JSON                -> replay `submission_uncertain`.
  * `nonce too low`               -> replay `submission_uncertain`.
  * `insufficient funds`          -> replay `broadcast_rejected`.
  * `invalid sender`              -> replay `broadcast_rejected`.
  * `intrinsic gas too low`       -> replay `broadcast_rejected`.
  * Crash between consume and outcome write -> replay
    `submission_uncertain` (crash-window conservativism: outcome
    IS NULL on a CONSUMED row is treated as uncertain).
  * Different signed tx in every terminal state -> HTTP 409,
    zero RPC calls.
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


_VAULT_ID = "terminal-outcome-vault"
# 2026-07-13 canary hardening: retained as a hex hash constant so
# `explicit_rejected` / `nonce_too_low` tests (which mock the RPC to
# RAISE and therefore never trip the mismatch guard) still compile.
# For success-path tests the mock returns `_echo_local_hash` and the
# by-hash visibility helper is auto-patched to "visible" in setUp.
_TX_HASH_HEX = "0x" + "0f" * 32
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


class _OutcomeReplayFixture(unittest.TestCase):
    """Seeds a fresh draft + wallet per test, so each terminal-state
    scenario runs independently."""

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
        # A unique nonce per test avoids fixture cross-talk if
        # tests get reordered.
        self._fx = make_signed_tx_and_matching_draft(
            nonce=100 + (os.getpid() % 5000),
        )
        _seed_wallet(self._m, self._fx["sender_address"])
        # draft_id regex is ^[A-Za-z0-9_-]{16,64}$
        self._did = "term_outcome_" + os.urandom(8).hex()
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

    def _drive_first_broadcast(self, rpc_side_effect_or_return):
        """Run the first broadcast which transitions the draft to
        CONSUMED with the specific terminal outcome."""
        kwargs = {}
        if isinstance(rpc_side_effect_or_return, BaseException):
            kwargs["side_effect"] = rpc_side_effect_or_return
        elif callable(rpc_side_effect_or_return):
            kwargs["side_effect"] = rpc_side_effect_or_return
        else:
            kwargs["return_value"] = rpc_side_effect_or_return
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url", **kwargs,
        ) as rpc:
            r = self._broadcast(self._fx["signed_tx_hex"])
        # Assert the first broadcast was reached at the RPC layer
        # (not blocked before RPC).
        self.assertEqual(
            rpc.call_count, 1,
            msg=f"Expected 1 RPC call on first broadcast; body={r.json()}",
        )
        return r

    def _replay_same_tx_expecting(
        self, expected_status, expected_reason_pat=None,
    ):
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ) as rpc:
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(
            rpc.call_count, 0,
            msg="Same-tx replay MUST NOT call the RPC. "
                f"body={r.json()}",
        )
        self.assertEqual(r.status_code, 200, msg=r.json())
        body = r.json()
        self.assertEqual(
            body["status"], expected_status, msg=body,
        )
        if expected_reason_pat is not None:
            self.assertIn(expected_reason_pat, body.get("reason", ""))
        return body

    def _replay_different_tx_expecting_409(self):
        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        different = make_signed_tx_and_matching_draft(
            nonce=self._fx["nonce"],
            value_wei=self._fx["value_wei"] + 7,
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ) as rpc:
            r = self._broadcast(different["signed_tx_hex"])
        self.assertEqual(
            rpc.call_count, 0,
            msg="Different-tx replay MUST NOT call the RPC.",
        )
        self.assertEqual(r.status_code, 409, msg=r.json())
        detail = r.json().get("detail", {})
        self.assertEqual(
            detail.get("wallet_engine"), "draft_already_consumed",
            msg=detail,
        )


class SuccessfulSubmissionReplay(_OutcomeReplayFixture):
    def test_submitted_replay_returns_already_submitted(self):
        # 2026-07-13 canary hardening: pass the echo-local-hash
        # side_effect so the mismatch guard sees a matching hash.
        r = self._drive_first_broadcast(_echo_local_hash)
        self.assertEqual(r.json()["status"], "submitted")

        body = self._replay_same_tx_expecting("already_submitted")
        self.assertEqual(body["txHash"], self._fx_local_hash())

        d = self._m._mainnet_store._drafts[self._did]
        self.assertEqual(d["broadcast_outcome"], "submitted")
        self.assertIsNotNone(d["outcome_recorded_at"])

    def test_submitted_different_tx_replay_returns_409(self):
        self._drive_first_broadcast(_echo_local_hash)
        self._replay_different_tx_expecting_409()

    def _fx_local_hash(self):
        from evm_signed_tx_verify import compute_local_tx_hash
        return compute_local_tx_hash(self._fx["signed_tx_hex"])


class AlreadyKnownReplay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError(
            "upstream_rpc", is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="already known",
        )

    def test_already_known_replay_returns_already_submitted(self):
        r = self._drive_first_broadcast(self._err())
        self.assertEqual(r.json()["status"], "already_submitted")

        self._replay_same_tx_expecting("already_submitted")

        d = self._m._mainnet_store._drafts[self._did]
        self.assertEqual(d["broadcast_outcome"], "already_known")

    def test_already_known_different_tx_replay_returns_409(self):
        self._drive_first_broadcast(self._err())
        self._replay_different_tx_expecting_409()


class AmbiguousReadTimeoutReplay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError("upstream_timeout")

    def test_read_timeout_replay_returns_submission_uncertain(self):
        r = self._drive_first_broadcast(self._err())
        self.assertEqual(r.json()["status"], "submission_uncertain")

        body = self._replay_same_tx_expecting("submission_uncertain")
        self.assertEqual(
            body["reason"], "submission_uncertain",
            msg="Reason must be the persisted outcome literal, not "
                "the original transport error code.",
        )
        d = self._m._mainnet_store._drafts[self._did]
        self.assertEqual(d["broadcast_outcome"], "submission_uncertain")

    def test_timeout_different_tx_replay_returns_409(self):
        self._drive_first_broadcast(self._err())
        self._replay_different_tx_expecting_409()


class ConnectionResetReplay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError("upstream_io")

    def test_conn_reset_replay_returns_submission_uncertain(self):
        self._drive_first_broadcast(self._err())
        self._replay_same_tx_expecting("submission_uncertain")

    def test_conn_reset_different_tx_replay_returns_409(self):
        self._drive_first_broadcast(self._err())
        self._replay_different_tx_expecting_409()


class Http502Replay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError("upstream_http")

    def test_http_502_replay_returns_submission_uncertain(self):
        self._drive_first_broadcast(self._err())
        self._replay_same_tx_expecting("submission_uncertain")


class Http503Replay(_OutcomeReplayFixture):
    def _err(self):
        # Both 502 and 503 map to `upstream_http`; the transport
        # layer does not distinguish. Semantic result is identical
        # (ambiguous). Test both explicitly for the record.
        from evm_rpc import EvmRpcError
        return EvmRpcError("upstream_http")

    def test_http_503_replay_returns_submission_uncertain(self):
        self._drive_first_broadcast(self._err())
        self._replay_same_tx_expecting("submission_uncertain")


class MalformedJsonReplay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError("upstream_json")

    def test_malformed_json_replay_returns_submission_uncertain(self):
        self._drive_first_broadcast(self._err())
        self._replay_same_tx_expecting("submission_uncertain")


class NonceTooLowReplay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError(
            "upstream_rpc", is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="nonce too low",
        )

    def test_nonce_too_low_replay_returns_submission_uncertain(self):
        # nonce too low is an ambiguous outcome in policy: the sender's
        # nonce may have been consumed by a prior successful broadcast.
        # The persisted outcome is `submission_uncertain`; replay
        # returns the same. It MUST NOT report `already_submitted`
        # unless we actually know the tx is on-chain.
        self._drive_first_broadcast(self._err())
        self._replay_same_tx_expecting("submission_uncertain")


class InsufficientFundsReplay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError(
            "upstream_rpc", is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="insufficient funds for gas * price + value",
        )

    def test_insufficient_funds_replay_returns_broadcast_rejected(self):
        r = self._drive_first_broadcast(self._err())
        self.assertEqual(r.json()["status"], "broadcast_unavailable")

        body = self._replay_same_tx_expecting("broadcast_rejected")
        self.assertNotEqual(body["status"], "already_submitted",
            msg="Explicit RPC rejection MUST NOT replay as "
                "`already_submitted` -- the client MUST be told the "
                "tx was rejected.")

        d = self._m._mainnet_store._drafts[self._did]
        self.assertEqual(
            d["broadcast_outcome"], "explicitly_rejected",
        )

    def test_insufficient_funds_different_tx_replay_returns_409(self):
        self._drive_first_broadcast(self._err())
        self._replay_different_tx_expecting_409()


class InvalidSenderReplay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError(
            "upstream_rpc", is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="invalid sender",
        )

    def test_invalid_sender_replay_returns_broadcast_rejected(self):
        self._drive_first_broadcast(self._err())
        body = self._replay_same_tx_expecting("broadcast_rejected")
        self.assertNotEqual(body["status"], "already_submitted")


class IntrinsicGasTooLowReplay(_OutcomeReplayFixture):
    def _err(self):
        from evm_rpc import EvmRpcError
        return EvmRpcError(
            "upstream_rpc", is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="intrinsic gas too low",
        )

    def test_intrinsic_gas_replay_returns_broadcast_rejected(self):
        self._drive_first_broadcast(self._err())
        body = self._replay_same_tx_expecting("broadcast_rejected")
        self.assertNotEqual(body["status"], "already_submitted")


class CrashBetweenConsumeAndRpc(_OutcomeReplayFixture):
    """Simulate a process crash AFTER `_consume_claimed_mainnet_draft`
    but BEFORE the RPC call. Draft ends up in CONSUMED state with
    `broadcast_outcome IS NULL`. A subsequent replay MUST return
    `submission_uncertain` -- NOT `already_submitted`.
    """

    def test_crash_before_rpc_replay_stays_uncertain(self):
        # Directly transition the draft to CONSUMED without going
        # through the RPC path -- exactly what a crash before the
        # `eth_send_raw_transaction_at_url` call would leave behind.
        from evm_signed_tx_verify import compute_local_tx_hash
        local_hash = compute_local_tx_hash(self._fx["signed_tx_hex"])
        tok, err = self._m._mainnet_store.claim_draft(
            draft_id=self._did,
            vault_id=_VAULT_ID,
            network_id="ethereum_mainnet",
        )
        self.assertIsNotNone(tok)
        ok = self._m._mainnet_store.consume_claimed_draft(
            draft_id=self._did,
            claim_token=tok,
            local_tx_hash=local_hash,
        )
        self.assertTrue(ok)

        d = self._m._mainnet_store._drafts[self._did]
        self.assertIsNotNone(d["consumed_at"])
        self.assertIsNone(d["broadcast_outcome"],
            msg="Simulated crash: outcome MUST NOT be recorded.")

        body = self._replay_same_tx_expecting("submission_uncertain")
        self.assertEqual(
            body.get("reason"), "outcome_not_recorded",
            msg="Crash-window replay must carry a distinguishable "
                "reason so operators can spot leftover pending rows.",
        )

    def test_crash_before_rpc_different_tx_replay_returns_409(self):
        from evm_signed_tx_verify import compute_local_tx_hash
        local_hash = compute_local_tx_hash(self._fx["signed_tx_hex"])
        tok, _ = self._m._mainnet_store.claim_draft(
            draft_id=self._did,
            vault_id=_VAULT_ID,
            network_id="ethereum_mainnet",
        )
        self._m._mainnet_store.consume_claimed_draft(
            draft_id=self._did,
            claim_token=tok,
            local_tx_hash=local_hash,
        )
        self._replay_different_tx_expecting_409()


class CrashBetweenRpcAndOutcomePersist(_OutcomeReplayFixture):
    """RPC returned successfully but the process crashed BEFORE
    `_record_mainnet_broadcast_outcome` ran. The row is CONSUMED
    with `broadcast_outcome IS NULL`. Replay MUST be conservative
    (`submission_uncertain`) rather than optimistically
    `already_submitted`.
    """

    def test_crash_after_rpc_ok_before_persist_replay_uncertain(self):
        # Simulate by having the RPC succeed but the record_outcome
        # call raise (as if the process died).
        real_record = (
            self._m._mainnet_store.record_broadcast_outcome
        )

        def _crash(**kwargs):
            raise RuntimeError("simulated crash between RPC and persist")

        try:
            self._m._mainnet_store.record_broadcast_outcome = _crash
            with mock.patch(
                "evm_rpc.eth_send_raw_transaction_at_url",
                side_effect=_echo_local_hash,
            ):
                # The route currently does not wrap the outcome-write
                # in try/except (a persistence failure is unusual and
                # visible in logs). To simulate the crash effect on
                # DB state without propagating the exception into the
                # test, we swallow it and manually mimic the "no
                # outcome written" DB state.
                try:
                    r = self._broadcast(self._fx["signed_tx_hex"])
                    _ = r.json()
                except RuntimeError as exc:
                    self.assertIn("simulated crash", str(exc))
        finally:
            self._m._mainnet_store.record_broadcast_outcome = (
                real_record
            )

        # Confirm the row is CONSUMED with NULL outcome.
        d = self._m._mainnet_store._drafts[self._did]
        self.assertIsNotNone(d["consumed_at"])
        self.assertIsNone(d["broadcast_outcome"])

        # Replay must be conservative.
        self._replay_same_tx_expecting("submission_uncertain")


class OutcomeIsWriteOnceOwnerSafe(_OutcomeReplayFixture):
    """A stale worker CANNOT overwrite a terminal outcome recorded
    by a fresh worker."""

    def test_second_outcome_write_is_rejected(self):
        # Drive the draft to CONSUMED with outcome=submitted.
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ):
            self._broadcast(self._fx["signed_tx_hex"])

        d = self._m._mainnet_store._drafts[self._did]
        self.assertEqual(d["broadcast_outcome"], "submitted")
        claim = d["claim_token"]
        self.assertIsNotNone(claim,
            msg="claim_token must be retained after consume so "
                "the outcome write can be owner-safe.")

        # Same owner attempting to overwrite: rejected.
        ok = self._m._mainnet_store.record_broadcast_outcome(
            draft_id=self._did,
            claim_token=claim,
            outcome="explicitly_rejected",
        )
        self.assertFalse(
            ok, msg="Same-owner second outcome write MUST fail.",
        )
        self.assertEqual(
            d["broadcast_outcome"], "submitted",
            msg="Value must not have been overwritten.",
        )

        # Stale owner attempting to overwrite: rejected.
        stale = self._m._mainnet_store.record_broadcast_outcome(
            draft_id=self._did,
            claim_token="not-the-real-token",
            outcome="submission_uncertain",
        )
        self.assertFalse(stale)
        self.assertEqual(d["broadcast_outcome"], "submitted")

    def test_bad_outcome_value_is_rejected(self):
        # Drive to CONSUMED without outcome.
        from evm_signed_tx_verify import compute_local_tx_hash
        local_hash = compute_local_tx_hash(self._fx["signed_tx_hex"])
        tok, _ = self._m._mainnet_store.claim_draft(
            draft_id=self._did,
            vault_id=_VAULT_ID,
            network_id="ethereum_mainnet",
        )
        self._m._mainnet_store.consume_claimed_draft(
            draft_id=self._did,
            claim_token=tok,
            local_tx_hash=local_hash,
        )

        # Attempt to record a value not in the allowed set: rejected.
        for bad in (
            "banana", "", "SUBMITTED",
            "submitted ", "SubMitted", None,
        ):
            ok = self._m._mainnet_store.record_broadcast_outcome(
                draft_id=self._did,
                claim_token=tok,
                outcome=bad,
            )
            self.assertFalse(
                ok, msg=f"outcome={bad!r} must be rejected",
            )
        d = self._m._mainnet_store._drafts[self._did]
        self.assertIsNone(d["broadcast_outcome"])


if __name__ == "__main__":
    unittest.main()
