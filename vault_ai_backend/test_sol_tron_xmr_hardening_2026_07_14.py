"""2026-07-14 (Round 6): SOL + TRON + XMR hardening regression.

Exercises:

  * SOL send now requires a server-issued draftId + binds signed
    transaction to the drafted primary Ed25519 signature identity.
  * SOL broadcast state machine: register → claim → consume →
    record_outcome, with replay classification (already_submitted /
    submission_uncertain / broadcast_rejected).
  * SOL outgoing history endpoint returns the vault-scoped
    projection of `crypto_solana_drafts` — no claim tokens leak.
  * TRON send registers a draft with the drafted server_txid_hex +
    expiration_ms; broadcast refuses when the signed txID does not
    match; broadcast refuses when expiration_ms has passed.
  * TRON outgoing history endpoint mirrors ETH/SOL shape.
  * XMR draft/broadcast/status ALL block — Send is not implemented,
    the router only returns disabled envelopes.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

import vault_config


_ENV_KEYS = (
    "VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_PAUSED",
    "SOLANA_RPC_URL",
    "VAULTAI_CRYPTO_TRON_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_PAUSED",
    "TRON_API_BASE_URL",
    "TRON_API_KEY",
    "TRON_USDT_CONTRACT_ADDRESS",
    "VAULTAI_CRYPTO_XMR_ENABLED",
    "VAULTAI_CRYPTO_XMR_SEND_ENABLED",
)


def _clear() -> None:
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
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
    os.environ["TRON_API_KEY"] = "key"
    os.environ["TRON_USDT_CONTRACT_ADDRESS"] = (
        "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    )
    vault_config.reset_for_tests()


_VAULT = "vault-round6-hardening"
_SOL_A = "So11111111111111111111111111111111111111112"
_SOL_B = "11111111111111111111111111111111"
_TRN_A = "TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq"
_TRN_B = "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9"
_TRN_C = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


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


# ---------------------------------------------------------------
# SOL draft state machine
# ---------------------------------------------------------------


class SolDraftBinding(unittest.TestCase):

    def setUp(self) -> None:
        _enable_sol()
        self._client, self._app, self._m = _make_client()
        self._m.reset_solana_safety_state_for_tests()

    def tearDown(self) -> None:
        self._m.reset_solana_safety_state_for_tests()
        _clear()

    def _mk_dispatch(self):
        from routes.crypto_wallet_routes import (
            SendBroadcastPayload, SendDraftPayload,
            _solana_send_dispatch, _solana_broadcast_dispatch,
        )
        principal = {"vault_id": _VAULT}
        return (
            SendDraftPayload, SendBroadcastPayload,
            _solana_send_dispatch, _solana_broadcast_dispatch,
            principal,
        )

    def test_broadcast_without_draftid_is_rejected(self):
        _sp, sb, _sd, brd, principal = self._mk_dispatch()
        from fastapi import HTTPException
        payload = sb(signedTransaction="AAAA")
        with self.assertRaises(HTTPException) as ctx:
            brd("SOL", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(
            ctx.exception.detail["wallet_engine"], "draft_id_required",
        )

    def test_broadcast_with_unknown_draftid_400(self):
        _sp, sb, _sd, brd, principal = self._mk_dispatch()
        from fastapi import HTTPException
        payload = sb(
            signedTransaction="AAAA",
            draftId="round6-unknown-draft-abcd",
        )
        with self.assertRaises(HTTPException) as ctx:
            brd("SOL", payload, principal)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail["wallet_engine"], "draft_load_failed",
        )

    def test_broadcast_records_submitted_outcome(self):
        _sp, sb, _sd, brd, principal = self._mk_dispatch()
        # Seed a draft in the fake store.
        did = self._m._solana_store.register_draft(
            vault_id=_VAULT, network_id="solana_mainnet",
            sender_address=_SOL_A, asset="SOL",
            destination_address=_SOL_B,
            value_lamports=1_000_000, fee_lamports=5000,
            recent_blockhash=("GfVPzKR8Uz2Sa4Pxrw6JHQKtu4LFB1cU"
                              "KQwT8b9DhP7A"),
            last_valid_block_height=250_000_000, ttl_secs=600,
        )
        fake_sig = "A" * 64
        payload = sb(signedTransaction="AAAA", draftId=did)
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            return_value=fake_sig,
        ), mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=1,
        ), mock.patch(
            "routes.crypto_wallet_routes."
            "_extract_solana_primary_signature",
            return_value=fake_sig,
        ):
            result = brd("SOL", payload, principal)
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["signature"], fake_sig)
        # Persistent state: broadcast_outcome recorded on the draft.
        d = self._m._solana_store._drafts[did]
        self.assertEqual(d["broadcast_outcome"], "submitted")
        self.assertEqual(d["local_signature"], fake_sig)

    def test_broadcast_records_submission_uncertain_on_rpc_error(
        self,
    ):
        _sp, sb, _sd, brd, principal = self._mk_dispatch()
        did = self._m._solana_store.register_draft(
            vault_id=_VAULT, network_id="solana_mainnet",
            sender_address=_SOL_A, asset="SOL",
            destination_address=_SOL_B,
            value_lamports=1_000_000, fee_lamports=5000,
            recent_blockhash="Zzz", last_valid_block_height=1,
            ttl_secs=600,
        )
        from solana_rpc import (
            SolanaRpcError, REASON_RPC_UNREACHABLE,
        )
        fake_sig = "B" * 64
        payload = sb(signedTransaction="AAAA", draftId=did)
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            side_effect=SolanaRpcError(REASON_RPC_UNREACHABLE),
        ), mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=1,
        ), mock.patch(
            "routes.crypto_wallet_routes."
            "_extract_solana_primary_signature",
            return_value=fake_sig,
        ):
            result = brd("SOL", payload, principal)
        self.assertEqual(result["status"], "submission_uncertain")
        d = self._m._solana_store._drafts[did]
        self.assertEqual(d["broadcast_outcome"], "submission_uncertain")

    def test_replay_of_submitted_draft_returns_already_submitted(
        self,
    ):
        _sp, sb, _sd, brd, principal = self._mk_dispatch()
        did = self._m._solana_store.register_draft(
            vault_id=_VAULT, network_id="solana_mainnet",
            sender_address=_SOL_A, asset="SOL",
            destination_address=_SOL_B,
            value_lamports=1_000_000, fee_lamports=5000,
            recent_blockhash="Zzz", last_valid_block_height=1,
            ttl_secs=600,
        )
        fake_sig = "C" * 64
        payload = sb(
            signedTransaction="AAAA", draftId=did,
            idempotencyKey="k1abcdef12",
        )
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            return_value=fake_sig,
        ), mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=1,
        ), mock.patch(
            "routes.crypto_wallet_routes."
            "_extract_solana_primary_signature",
            return_value=fake_sig,
        ):
            brd("SOL", payload, principal)
        # A second dispatch with a different idempotency key must
        # NOT retry the RPC. State-machine says already broadcast.
        payload2 = sb(
            signedTransaction="AAAA", draftId=did,
            idempotencyKey="k2abcdef34",
        )
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            return_value=fake_sig,
        ), mock.patch(
            "solana_rpc.sol_get_block_height_at_url",
            return_value=1,
        ), mock.patch(
            "routes.crypto_wallet_routes."
            "_extract_solana_primary_signature",
            return_value=fake_sig,
        ):
            second = brd("SOL", payload2, principal)
        self.assertEqual(second["status"], "already_submitted")


class SolOutgoingHistory(unittest.TestCase):

    def setUp(self) -> None:
        _enable_sol()
        self._client, self._app, self._m = _make_client()

    def tearDown(self) -> None:
        _clear()

    def _seed_consumed(self, draft_id: str, sig: str) -> None:
        self._m._solana_store.seed_draft(
            draft_id,
            vault_id=_VAULT, network_id="solana_mainnet",
            sender_address=_SOL_A,
            destination_address=_SOL_B,
            value_lamports=1_000_000, fee_lamports=5000,
        )
        d = self._m._solana_store._drafts[draft_id]
        d["consumed_at"] = 1_720_100_000.0
        d["local_signature"] = sig
        d["broadcast_outcome"] = "submitted"
        d["outcome_recorded_at"] = 1_720_100_001.0

    def test_history_projection_shape(self):
        self._seed_consumed("drft-sol-1", "sig-abcdef")
        r = self._client.get(
            "/crypto/wallet/network/solana_mainnet/outgoing/history",
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        rows = body["outgoing"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["draftId"], "drft-sol-1")
        self.assertEqual(row["localSignature"], "sig-abcdef")
        self.assertEqual(row["broadcastOutcome"], "submitted")
        self.assertEqual(row["unit"], "SOL")
        self.assertEqual(row["decimals"], 9)

    def test_no_claim_token_or_internal_fields_leak(self):
        self._seed_consumed("drft-sol-secrets", "sig-x")
        self._m._solana_store._drafts["drft-sol-secrets"][
            "claim_token"
        ] = "SOL_CLAIM_TOKEN_LEAK_CHECK"
        r = self._client.get(
            "/crypto/wallet/network/solana_mainnet/outgoing/history",
        )
        raw = r.text
        self.assertNotIn("SOL_CLAIM_TOKEN_LEAK_CHECK", raw)
        self.assertNotIn("claim_token", raw)
        self.assertNotIn("vault_id", raw)


# ---------------------------------------------------------------
# TRON draft state machine
# ---------------------------------------------------------------


def _valid_tron_signed_tx() -> dict:
    return {
        "txID": "a" * 64,
        "raw_data": {
            "contract": [{"type": "TriggerSmartContract"}],
            "expiration": 99_999_999_999_999,
        },
        "raw_data_hex": "0a" * 20,
        "signature": ["b" * 130],
    }


class TronDraftBinding(unittest.TestCase):

    def setUp(self) -> None:
        _enable_tron()
        self._client, self._app, self._m = _make_client()
        self._m.reset_tron_safety_state_for_tests()

    def tearDown(self) -> None:
        self._m.reset_tron_safety_state_for_tests()
        _clear()

    def _mk(self):
        from routes.crypto_wallet_routes import (
            SendBroadcastPayload, _tron_broadcast_dispatch,
        )
        return SendBroadcastPayload, _tron_broadcast_dispatch, {
            "vault_id": _VAULT,
        }

    def test_broadcast_without_draftid_is_rejected(self):
        SB, brd, principal = self._mk()
        from fastapi import HTTPException
        payload = SB(signedTransaction=_valid_tron_signed_tx())
        with self.assertRaises(HTTPException) as ctx:
            brd("USDT_TRC20", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(
            ctx.exception.detail["wallet_engine"], "draft_id_required",
        )

    def test_broadcast_txid_mismatch_is_rejected(self):
        SB, brd, principal = self._mk()
        from fastapi import HTTPException
        did = self._m._tron_store.register_draft(
            vault_id=_VAULT, network_id="tron_mainnet",
            sender_address=_TRN_A, asset="USDT_TRC20",
            destination_address=_TRN_B,
            token_contract_address=_TRN_C,
            amount_base_units=1_000_000, fee_limit_sun=100_000_000,
            raw_data_hex="0a" * 20,
            expiration_ms=99_999_999_999_999,
            server_txid_hex="a" * 64,
            ttl_secs=600,
        )
        # Client submits a signed tx with a DIFFERENT txID than the
        # drafted one — refuse the broadcast.
        signed = _valid_tron_signed_tx()
        signed["txID"] = "c" * 64
        payload = SB(signedTransaction=signed, draftId=did)
        with self.assertRaises(HTTPException) as ctx:
            brd("USDT_TRC20", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(
            ctx.exception.detail["wallet_engine"],
            "signed_tx_id_mismatch",
        )

    def test_broadcast_after_expiration_is_rejected(self):
        SB, brd, principal = self._mk()
        # Expiration in the past — the store keeps the row alive but
        # broadcast dispatch refuses.
        did = self._m._tron_store.register_draft(
            vault_id=_VAULT, network_id="tron_mainnet",
            sender_address=_TRN_A, asset="USDT_TRC20",
            destination_address=_TRN_B,
            token_contract_address=_TRN_C,
            amount_base_units=1_000_000, fee_limit_sun=100_000_000,
            raw_data_hex="0a" * 20,
            expiration_ms=1,  # 1970-01-01 → past
            server_txid_hex="a" * 64,
            ttl_secs=600,
        )
        payload = SB(
            signedTransaction=_valid_tron_signed_tx(), draftId=did,
        )
        result = brd("USDT_TRC20", payload, principal)
        self.assertEqual(result["status"], "draft_expired")
        self.assertEqual(result["reason"], "expiration_passed")

    def test_broadcast_records_submitted_outcome(self):
        SB, brd, principal = self._mk()
        did = self._m._tron_store.register_draft(
            vault_id=_VAULT, network_id="tron_mainnet",
            sender_address=_TRN_A, asset="USDT_TRC20",
            destination_address=_TRN_B,
            token_contract_address=_TRN_C,
            amount_base_units=1_000_000, fee_limit_sun=100_000_000,
            raw_data_hex="0a" * 20,
            expiration_ms=99_999_999_999_999,
            server_txid_hex="a" * 64,
            ttl_secs=600,
        )
        payload = SB(
            signedTransaction=_valid_tron_signed_tx(), draftId=did,
        )
        with mock.patch(
            "tron_rpc.tron_broadcast_signed_transaction_at_url",
            return_value="a" * 64,
        ):
            result = brd("USDT_TRC20", payload, principal)
        self.assertEqual(result["status"], "submitted")
        d = self._m._tron_store._drafts[did]
        self.assertEqual(d["broadcast_outcome"], "submitted")
        self.assertEqual(d["local_txid_hex"], "a" * 64)


class TronOutgoingHistory(unittest.TestCase):

    def setUp(self) -> None:
        _enable_tron()
        self._client, self._app, self._m = _make_client()

    def tearDown(self) -> None:
        _clear()

    def test_history_projection_shape(self):
        self._m._tron_store.seed_draft(
            "drft-trn-1",
            vault_id=_VAULT, network_id="tron_mainnet",
            sender_address=_TRN_A,
            destination_address=_TRN_B,
            token_contract_address=_TRN_C,
            amount_base_units=5_000_000,
            fee_limit_sun=100_000_000,
        )
        d = self._m._tron_store._drafts["drft-trn-1"]
        d["consumed_at"] = 1_720_100_000.0
        d["local_txid_hex"] = "d" * 64
        d["broadcast_outcome"] = "submitted"
        d["outcome_recorded_at"] = 1_720_100_001.0

        r = self._client.get(
            "/crypto/wallet/network/tron_mainnet/outgoing/history",
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        rows = body["outgoing"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["draftId"], "drft-trn-1")
        self.assertEqual(row["localTxIdHex"], "d" * 64)
        self.assertEqual(row["broadcastOutcome"], "submitted")
        self.assertEqual(row["unit"], "USDT")
        self.assertEqual(row["decimals"], 6)


# ---------------------------------------------------------------
# XMR blocked-path regression
# ---------------------------------------------------------------


class XmrSendPathIsAlwaysBlocked(unittest.TestCase):
    """XMR Send is not implemented. Every send-shaped route must
    return a disabled envelope — no draft creation, no signing path,
    no broadcast, no status polling. The frontend must never expose
    an enabled XMR Send action."""

    def setUp(self) -> None:
        _clear()
        os.environ["VAULTAI_CRYPTO_WALLET_ENGINE_ENABLED"] = "true"
        # Force XMR "enabled" so the router chooses XMR dispatch
        # rather than falling into a generic engine-off envelope.
        os.environ["VAULTAI_CRYPTO_XMR_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_XMR_SEND_ENABLED"] = "true"
        vault_config.reset_for_tests()
        self._client, self._app, self._m = _make_client()

    def tearDown(self) -> None:
        _clear()

    def test_draft_route_blocks(self):
        r = self._client.post(
            "/crypto/wallet/network/monero_mainnet/XMR/send/draft",
            json={"fromAddress": "4X", "destinationAddress": "4Y",
                  "amountEth": "0.01"},
        )
        # 2026-07-14: draft must return a disabled envelope OR the
        # send-not-enabled wallet_engine — never a `draft_ready`.
        blob = r.json()
        status = str(blob.get("status") or blob.get("wallet_engine"))
        self.assertNotIn("draft_ready", str(blob))
        self.assertTrue(
            "xmr_send_not_enabled" in str(blob)
            or "not_enabled" in status
            or "disabled" in status
            or "coming_soon" in str(blob).lower()
            or "unavailable" in status,
            msg=f"XMR draft response unexpectedly permissive: {blob}",
        )

    def test_broadcast_route_blocks(self):
        r = self._client.post(
            "/crypto/wallet/network/monero_mainnet/XMR/send/broadcast",
            json={"signedTransaction": "not-used"},
        )
        blob = r.json()
        self.assertNotIn("submitted", str(blob))
        self.assertNotIn("broadcast_submitted", str(blob))
        self.assertTrue(
            "xmr_send_not_enabled" in str(blob)
            or "not_enabled" in str(blob)
            or "disabled" in str(blob).lower()
            or "unavailable" in str(blob).lower(),
            msg=f"XMR broadcast response unexpectedly permissive: "
                f"{blob}",
        )

    def test_status_route_blocks(self):
        r = self._client.get(
            "/crypto/wallet/network/monero_mainnet/XMR/transaction/"
            + "0x" + "aa" * 32,
        )
        blob = r.json()
        # Status route should either 404-shape the envelope or
        # return the disabled XMR envelope. Never a `confirmed` or
        # `submitted` status.
        self.assertNotIn("confirmed", str(blob))
        self.assertNotIn("submitted", str(blob))


if __name__ == "__main__":
    unittest.main()
