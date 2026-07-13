"""2026-07-13 pre-mainnet: RPC failure classification suite.

The final adversarial review pointed out that classifying every
non-timeout `EvmRpcError` as `broadcast_unavailable` ("definitely
not submitted") is unsafe:

  * A TCP RESET after the write half was completed leaves the raw
    transaction potentially delivered to the RPC node.
  * An HTTP 502/503 from a reverse proxy in front of the RPC node
    may occur AFTER the node processed the request.
  * A malformed / truncated JSON body after HTTP 200 means the
    node responded but we cannot know the outcome.
  * A missing `result` field with no `error` field is likewise an
    unknown-outcome envelope.

The invariant this suite locks in:

  Only an EXPLICIT JSON-RPC error response (parsed successfully
  from the provider) is a definite rejection. Every transport or
  protocol failure is ambiguous and MUST return
  `submission_uncertain` with the locally derived tx hash.

Additionally two explicit-rejection patterns must not be
"broadcast_unavailable":

  * `already known` / `known transaction` from the provider means
    the same raw tx is already in the mempool. Return
    `already_submitted` with the local tx hash.

  * `nonce too low` may mean this sender's nonce was consumed by
    a prior successful broadcast (possibly via a different
    provider). Return `submission_uncertain` so the client polls
    the local hash instead of assuming rejection.

Every ambiguous outcome preserves the CONSUMED state of the draft
so a retry with the same signed transaction returns
`already_submitted`, and a retry with a DIFFERENT signed
transaction is rejected with 409 `draft_already_consumed`.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import httpx

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


_VAULT_ID = "rpc-classification-vault"
_TX_HASH_HEX = "0x" + "0f" * 32
# 2026-07-13 canary hardening.
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


class _BroadcastFixture(unittest.TestCase):
    """Base fixture. Subclasses install a specific mocked
    `eth_send_raw_transaction_at_url` behavior and assert on the
    envelope."""

    def _seed(self, nonce):
        _clear_all()
        _enable()
        self._client, self._app, self._m = _make_client()
        self._m.reset_mainnet_safety_state_for_tests()
        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        self._fx = make_signed_tx_and_matching_draft(nonce=nonce)
        _seed_wallet(self._m, self._fx["sender_address"])
        self._did = f"rpc-cls-{nonce}-{os.urandom(4).hex()}"
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

    def setUp(self):
        # 2026-07-13 canary hardening: baseline
        # `eth_getTransactionByHash` to "visible".
        self._by_hash_patcher = mock.patch(
            "evm_rpc.eth_get_transaction_by_hash_at_url",
            side_effect=_visible_by_hash,
        )
        self._by_hash_patcher.start()
        self.addCleanup(self._by_hash_patcher.stop)
        self._seed(nonce=1000 + os.getpid() % 8000)

    def tearDown(self):
        _clear_all()
        self._m.reset_mainnet_safety_state_for_tests()

    def _broadcast(self, signed_tx_hex):
        return self._client.post(
            "/crypto/wallet/network/ethereum_mainnet/ETH/send/broadcast",
            json={"signedTransaction": signed_tx_hex,
                  "draftId":           self._did},
        )


class RpcAmbiguousFailures(_BroadcastFixture):
    """Every transport/protocol failure must be treated as ambiguous
    (submission_uncertain) with the LOCAL tx hash returned."""

    def _assert_uncertain(self, rpc_side_effect, expected_reason):
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=rpc_side_effect,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r.status_code, 200, msg=r.json())
        body = r.json()
        self.assertEqual(
            body["status"], "submission_uncertain", msg=body,
        )
        self.assertEqual(body["reason"], expected_reason)
        self.assertTrue(body["txHash"].startswith("0x"))
        self.assertEqual(len(body["txHash"]), 66)

    def test_read_timeout_after_request_accepts_is_ambiguous(self):
        from evm_rpc import EvmRpcError
        self._assert_uncertain(
            EvmRpcError("upstream_timeout"),
            "upstream_timeout",
        )

    def test_connection_reset_during_write_is_ambiguous(self):
        from evm_rpc import EvmRpcError
        self._assert_uncertain(
            EvmRpcError("upstream_io"),
            "upstream_io",
        )

    def test_http_502_is_ambiguous(self):
        from evm_rpc import EvmRpcError
        self._assert_uncertain(
            EvmRpcError("upstream_http"),
            "upstream_http",
        )

    def test_http_503_is_ambiguous(self):
        from evm_rpc import EvmRpcError
        self._assert_uncertain(
            EvmRpcError("upstream_http"),
            "upstream_http",
        )

    def test_malformed_json_after_200_is_ambiguous(self):
        from evm_rpc import EvmRpcError
        self._assert_uncertain(
            EvmRpcError("upstream_json"),
            "upstream_json",
        )

    def test_missing_result_field_is_ambiguous(self):
        from evm_rpc import EvmRpcError
        self._assert_uncertain(
            EvmRpcError("upstream_json"),
            "upstream_json",
        )


class RpcExplicitRejection(_BroadcastFixture):
    """Only explicit JSON-RPC error responses are definite rejections
    -- and even then, `already known` and `nonce too low` require
    special handling."""

    def test_insufficient_funds_is_broadcast_unavailable(self):
        from evm_rpc import EvmRpcError
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="insufficient funds for transfer",
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=rpc_err,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r.status_code, 200, msg=r.json())
        body = r.json()
        self.assertEqual(body["status"], "broadcast_unavailable")
        self.assertEqual(body["reason"], "upstream_rpc")

    def test_invalid_sender_is_broadcast_unavailable(self):
        from evm_rpc import EvmRpcError
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="invalid sender",
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=rpc_err,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        body = r.json()
        self.assertEqual(body["status"], "broadcast_unavailable")

    def test_intrinsic_gas_too_low_is_broadcast_unavailable(self):
        from evm_rpc import EvmRpcError
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="intrinsic gas too low",
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=rpc_err,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        body = r.json()
        self.assertEqual(body["status"], "broadcast_unavailable")

    def test_already_known_returns_already_submitted_with_local_hash(
        self,
    ):
        """`already known` from the provider means our raw tx is
        already in the network mempool. Return `already_submitted`
        with the LOCAL tx hash so the client can poll status."""
        from evm_rpc import EvmRpcError
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="already known",
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=rpc_err,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r.status_code, 200, msg=r.json())
        body = r.json()
        self.assertEqual(body["status"], "already_submitted", msg=body)
        self.assertTrue(body["txHash"].startswith("0x"))
        self.assertEqual(len(body["txHash"]), 66)

    def test_known_transaction_returns_already_submitted(self):
        """Some providers return 'known transaction' instead of
        'already known'. Both must be treated the same."""
        from evm_rpc import EvmRpcError
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="known transaction: 0xabc...",
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=rpc_err,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        body = r.json()
        self.assertEqual(body["status"], "already_submitted", msg=body)

    def test_nonce_too_low_returns_submission_uncertain(self):
        """`nonce too low` may mean this sender's nonce was consumed
        by a prior successful broadcast (possibly via a different
        provider). Return `submission_uncertain` so the client
        polls the local hash instead of assuming rejection."""
        from evm_rpc import EvmRpcError
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="nonce too low",
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=rpc_err,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r.status_code, 200, msg=r.json())
        body = r.json()
        self.assertEqual(
            body["status"], "submission_uncertain", msg=body,
        )
        self.assertTrue(body["txHash"].startswith("0x"))


class RpcRetryAfterAmbiguity(_BroadcastFixture):
    """After an ambiguous or nonce-too-low outcome the draft stays
    CONSUMED with `broadcast_outcome = 'submission_uncertain'`. A
    same-tx retry re-reads the persisted outcome and returns
    `submission_uncertain` WITHOUT calling the RPC. This preserves
    the truthful "uncertain" signal to the client -- it must NOT
    silently upgrade to `already_submitted`. A different-tx retry
    returns 409.
    """

    def _run_ambig_then_retries(
        self, first_side_effect, expected_replay_status,
    ):
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=first_side_effect,
        ):
            r1 = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r1.status_code, 200, msg=r1.json())
        body1 = r1.json()
        self.assertIn(
            body1["status"],
            ("submission_uncertain", "already_submitted"),
            msg=body1,
        )
        first_hash = body1["txHash"]

        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ) as rpc:
            r2 = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r2.status_code, 200, msg=r2.json())
        body2 = r2.json()
        self.assertEqual(
            body2["status"], expected_replay_status, msg=body2,
        )
        self.assertEqual(body2["txHash"], first_hash)
        self.assertEqual(
            rpc.call_count, 0,
            msg="Same-tx retry MUST NOT re-invoke eth_sendRawTransaction",
        )

        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        different = make_signed_tx_and_matching_draft(
            nonce=self._fx["nonce"], value_wei=self._fx["value_wei"] + 1,
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=_echo_local_hash,
        ) as rpc2:
            r3 = self._broadcast(different["signed_tx_hex"])
        self.assertEqual(r3.status_code, 409, msg=r3.json())
        detail = r3.json().get("detail", {})
        self.assertEqual(
            detail.get("wallet_engine"), "draft_already_consumed",
            msg=detail,
        )
        self.assertEqual(rpc2.call_count, 0)

    def test_retry_after_upstream_timeout(self):
        from evm_rpc import EvmRpcError
        # Ambiguous replay MUST stay uncertain -- do not silently
        # upgrade to already_submitted.
        self._run_ambig_then_retries(
            EvmRpcError("upstream_timeout"),
            expected_replay_status="submission_uncertain",
        )

    def test_retry_after_upstream_io_connection_reset(self):
        from evm_rpc import EvmRpcError
        self._run_ambig_then_retries(
            EvmRpcError("upstream_io"),
            expected_replay_status="submission_uncertain",
        )

    def test_retry_after_upstream_http_502(self):
        from evm_rpc import EvmRpcError
        self._run_ambig_then_retries(
            EvmRpcError("upstream_http"),
            expected_replay_status="submission_uncertain",
        )

    def test_retry_after_upstream_json_malformed(self):
        from evm_rpc import EvmRpcError
        self._run_ambig_then_retries(
            EvmRpcError("upstream_json"),
            expected_replay_status="submission_uncertain",
        )

    def test_retry_after_nonce_too_low(self):
        from evm_rpc import EvmRpcError
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="nonce too low",
        )
        self._run_ambig_then_retries(
            rpc_err,
            expected_replay_status="submission_uncertain",
        )

    def test_retry_after_already_known(self):
        from evm_rpc import EvmRpcError
        # `already known` is the ONE explicit outcome where the
        # network genuinely holds the tx; replay is
        # `already_submitted`, not `submission_uncertain`.
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="already known",
        )
        self._run_ambig_then_retries(
            rpc_err,
            expected_replay_status="already_submitted",
        )


class ExplicitRejectionConsumedDraftPolicy(_BroadcastFixture):
    """Item 5 of the 2026-07-13 review: single-attempt policy.

    A valid signed transaction that verifies against the draft
    consumes the draft BEFORE calling the RPC, so an explicit
    pre-acceptance rejection (insufficient_funds, invalid_sender,
    intrinsic_gas_too_low) leaves the draft permanently CONSUMED.

    Rationale: this is simpler and safer for mainnet than trying
    to release the draft on explicit rejection -- it avoids a
    class of subtle bugs where the release / retry / consume flow
    could enable double-spend under provider quirks. The client
    contract is: after `broadcast_unavailable`, DRAFT A NEW SEND
    for any retry.
    """

    def test_insufficient_funds_leaves_draft_consumed(self):
        from evm_rpc import EvmRpcError
        rpc_err = EvmRpcError(
            "upstream_rpc",
            is_ambiguous=False,
            rpc_error_code=-32000,
            rpc_error_message="insufficient funds for gas * price + value",
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            side_effect=rpc_err,
        ):
            r = self._broadcast(self._fx["signed_tx_hex"])
        self.assertEqual(r.json()["status"], "broadcast_unavailable")

        drafts = self._m._mainnet_store._drafts
        d = drafts[self._did]
        self.assertIsNotNone(
            d["consumed_at"],
            msg="Draft MUST be marked CONSUMED even under explicit "
                "RPC rejection (single-attempt policy).",
        )
        self.assertIsNotNone(
            d["local_tx_hash"],
            msg="local_tx_hash MUST be recorded on the consumed row.",
        )

        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            return_value="0x" + "aa" * 32,
        ) as rpc:
            r_retry_same = self._broadcast(self._fx["signed_tx_hex"])
        # 2026-07-13: replay of a same-tx after an EXPLICIT parsed
        # RPC rejection MUST NOT be reported as `already_submitted`.
        # The persisted `broadcast_outcome = 'explicitly_rejected'`
        # dispatches the replay envelope to `broadcast_rejected`.
        # The client must know the provider rejected this tx and
        # that any retry requires a fresh draft.
        self.assertEqual(r_retry_same.status_code, 200)
        self.assertEqual(
            r_retry_same.json()["status"], "broadcast_rejected",
            msg="Same-tx replay after an explicit RPC rejection MUST "
                "NOT return already_submitted; must be "
                "broadcast_rejected so the client does not conclude "
                "the tx is on-chain.",
        )
        self.assertNotEqual(
            r_retry_same.json()["status"], "already_submitted",
        )
        self.assertEqual(rpc.call_count, 0)

        from _test_fake_mainnet_store import (
            make_signed_tx_and_matching_draft,
        )
        different = make_signed_tx_and_matching_draft(
            nonce=self._fx["nonce"],
            value_wei=self._fx["value_wei"] + 5,
        )
        with mock.patch(
            "evm_rpc.eth_send_raw_transaction_at_url",
            return_value="0x" + "bb" * 32,
        ) as rpc2:
            r_retry_diff = self._broadcast(different["signed_tx_hex"])
        self.assertEqual(
            r_retry_diff.status_code, 409,
            msg="Different signed tx against a consumed draft must "
                "be rejected; retry requires a FRESH draft.",
        )
        detail = r_retry_diff.json().get("detail", {})
        self.assertEqual(
            detail.get("wallet_engine"), "draft_already_consumed",
        )
        self.assertEqual(rpc2.call_count, 0)


class RpcLowLevelClassification(unittest.TestCase):
    """Exercise `_emit_rpc_at_url` directly to confirm the exception
    it raises has the right `is_ambiguous` value for each transport
    outcome. Locks in the EvmRpcError classification separately from
    the broadcast route -- so a route rewrite alone can't accidentally
    downgrade the low-level classification."""

    def _make_client_ctx(self, side_effect_or_resp):
        """Return a fake httpx.Client that either raises or returns
        a mocked Response object."""
        client_ctx = mock.MagicMock()
        client_ctx.__enter__ = mock.MagicMock(return_value=client_ctx)
        client_ctx.__exit__ = mock.MagicMock(return_value=False)
        if isinstance(side_effect_or_resp, BaseException):
            client_ctx.post = mock.MagicMock(
                side_effect=side_effect_or_resp,
            )
        elif callable(side_effect_or_resp) and (
            not isinstance(side_effect_or_resp, mock.MagicMock)
        ):
            client_ctx.post = side_effect_or_resp
        else:
            client_ctx.post = mock.MagicMock(
                return_value=side_effect_or_resp,
            )
        return client_ctx

    def _fake_resp(self, status_code, body_bytes=None, body_json=None):
        r = mock.MagicMock()
        r.status_code = status_code
        if body_bytes is not None:
            def _raise():
                import json as _json
                raise _json.JSONDecodeError("boom", "x", 0)
            r.json = mock.MagicMock(side_effect=_raise)
        elif body_json is not None:
            r.json = mock.MagicMock(return_value=body_json)
        else:
            r.json = mock.MagicMock(return_value={"result": "0x1"})
        return r

    def _emit(self, side_effect_or_resp):
        from evm_rpc import _emit_rpc_at_url
        ctx = self._make_client_ctx(side_effect_or_resp)
        with mock.patch(
            "evm_rpc.httpx.Client", return_value=ctx,
        ):
            return _emit_rpc_at_url(
                "https://example.invalid/mainnet",
                "eth_sendRawTransaction",
                ["0x" + "ab" * 60],
            )

    def test_timeout_raises_ambiguous(self):
        from evm_rpc import EvmRpcError
        with self.assertRaises(EvmRpcError) as cm:
            self._emit(httpx.ReadTimeout("timed out"))
        self.assertEqual(cm.exception.code, "upstream_timeout")
        self.assertTrue(cm.exception.is_ambiguous)

    def test_connection_reset_raises_ambiguous(self):
        from evm_rpc import EvmRpcError
        with self.assertRaises(EvmRpcError) as cm:
            self._emit(
                httpx.RemoteProtocolError("connection reset"),
            )
        self.assertEqual(cm.exception.code, "upstream_io")
        self.assertTrue(cm.exception.is_ambiguous)

    def test_http_502_raises_ambiguous(self):
        from evm_rpc import EvmRpcError
        resp = self._fake_resp(status_code=502)
        with self.assertRaises(EvmRpcError) as cm:
            self._emit(resp)
        self.assertEqual(cm.exception.code, "upstream_http")
        self.assertTrue(cm.exception.is_ambiguous)

    def test_http_503_raises_ambiguous(self):
        from evm_rpc import EvmRpcError
        resp = self._fake_resp(status_code=503)
        with self.assertRaises(EvmRpcError) as cm:
            self._emit(resp)
        self.assertEqual(cm.exception.code, "upstream_http")
        self.assertTrue(cm.exception.is_ambiguous)

    def test_malformed_json_after_200_raises_ambiguous(self):
        from evm_rpc import EvmRpcError
        resp = self._fake_resp(status_code=200, body_bytes=b"garbage")
        with self.assertRaises(EvmRpcError) as cm:
            self._emit(resp)
        self.assertEqual(cm.exception.code, "upstream_json")
        self.assertTrue(cm.exception.is_ambiguous)

    def test_missing_result_and_no_error_raises_ambiguous(self):
        from evm_rpc import EvmRpcError
        resp = self._fake_resp(
            status_code=200, body_json={"jsonrpc": "2.0", "id": 1},
        )
        with self.assertRaises(EvmRpcError) as cm:
            self._emit(resp)
        self.assertEqual(cm.exception.code, "upstream_json")
        self.assertTrue(cm.exception.is_ambiguous)

    def test_explicit_rpc_error_raises_non_ambiguous_with_details(
        self,
    ):
        from evm_rpc import EvmRpcError
        resp = self._fake_resp(
            status_code=200,
            body_json={
                "jsonrpc": "2.0", "id": 1,
                "error": {
                    "code": -32000,
                    "message": "insufficient funds for transfer",
                },
            },
        )
        with self.assertRaises(EvmRpcError) as cm:
            self._emit(resp)
        self.assertEqual(cm.exception.code, "upstream_rpc")
        self.assertFalse(cm.exception.is_ambiguous)
        self.assertEqual(cm.exception.rpc_error_code, -32000)
        self.assertIn(
            "insufficient funds",
            (cm.exception.rpc_error_message or "").lower(),
        )


if __name__ == "__main__":
    unittest.main()
