

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock


_BACKEND_ROOT = Path(__file__).parent


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


_SOLANA_ENV_KEYS = (
    "VAULTAI_CRYPTO_SOLANA_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_ENABLED",
    "SOLANA_RPC_URL",
)


_ADDR_A = "So11111111111111111111111111111111111111112"
_ADDR_B = "11111111111111111111111111111111"
_SIG = (
    "4vGVQpTJyGgQMTkwoUn7Xf4WScDW6RxDGNhWQb1QxLGyKcksVezR"
    "GNS4pmH24DngjyfNhBGpAtWxdD8gwucjFCG9"
)
_BLOCKHASH = "FwZbEB4YfDjK6iEy4uP5oXwUTL7jXbGgnh8UyKz4EbCE"


class SolanaTransactionStatusTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def _status(self, sig=_SIG):
        from routes.crypto_wallet_routes import (
            _solana_transaction_status,
        )
        return _solana_transaction_status("SOL", sig)

    def test_invalid_signature_raises_422(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self._status("not-a-signature")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_missing_rpc_returns_rpc_not_configured(self):
        result = self._status()
        self.assertEqual(
            result["transactionStatus"], "unavailable",
        )
        self.assertEqual(result["reason"], "rpc_not_configured")

    def test_confirmed_signature_maps_to_confirmed(self):
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        with mock.patch(
            "solana_rpc.sol_get_signature_status_at_url",
            return_value={
                "status": "confirmed",
                "slot": 12345,
                "confirmations": None,
                "confirmationStatus": "finalized",
            },
        ):
            result = self._status()
        self.assertEqual(
            result["transactionStatus"], "confirmed",
        )
        self.assertEqual(result["slot"], 12345)
        self.assertEqual(
            result["confirmationStatus"], "finalized",
        )

    def test_failed_signature_maps_to_failed(self):
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        with mock.patch(
            "solana_rpc.sol_get_signature_status_at_url",
            return_value={
                "status": "failed",
                "slot": 200,
                "confirmations": None,
                "confirmationStatus": "confirmed",
            },
        ):
            result = self._status()
        self.assertEqual(
            result["transactionStatus"], "failed",
        )

    def test_pending_signature_maps_to_pending(self):
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        with mock.patch(
            "solana_rpc.sol_get_signature_status_at_url",
            return_value={
                "status": "pending",
                "slot": None,
                "confirmations": None,
                "confirmationStatus": "processed",
            },
        ):
            result = self._status()
        self.assertEqual(
            result["transactionStatus"], "pending",
        )

    def test_rpc_error_maps_to_unavailable(self):
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        from solana_rpc import SolanaRpcError, REASON_RPC_ERROR
        with mock.patch(
            "solana_rpc.sol_get_signature_status_at_url",
            side_effect=SolanaRpcError(REASON_RPC_ERROR),
        ):
            result = self._status()
        self.assertEqual(
            result["transactionStatus"], "unavailable",
        )
        self.assertEqual(result["reason"], "rpc_error")

    def test_status_never_exposes_rpc_url(self):
        os.environ["SOLANA_RPC_URL"] = (
            "https://leaky-solana.example/?key=leaky-key"
        )
        with mock.patch(
            "solana_rpc.sol_get_signature_status_at_url",
            return_value={
                "status": "pending",
                "slot": None,
                "confirmations": None,
                "confirmationStatus": "processed",
            },
        ):
            result = self._status()
        blob = repr(result)
        self.assertNotIn("leaky-solana.example", blob)
        self.assertNotIn("leaky-key", blob)


class SolanaActivityTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def _activity(self, limit=20):
        from routes.crypto_wallet_routes import _solana_transactions
        principal = {
            "vault_id": "00000000-0000-0000-0000-000000000000",
        }
        return _solana_transactions("SOL", limit, principal)

    def test_activity_returns_no_wallet_yet_when_no_record(self):
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ):
            result = self._activity()
        self.assertEqual(
            result["transactionsStatus"], "unavailable",
        )
        self.assertEqual(result["reason"], "no_wallet_yet")
        self.assertEqual(result["transactions"], [])

    def test_activity_returns_rpc_not_configured(self):
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value={"publicAddress": _ADDR_A},
        ):
            result = self._activity()
        self.assertEqual(
            result["transactionsStatus"], "unavailable",
        )
        self.assertEqual(result["reason"], "rpc_not_configured")

    def test_activity_parses_signatures_for_address(self):
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        rows = [
            {
                "signature":          _SIG,
                "slot":               12345,
                "blockTime":          1700000000,
                "confirmationStatus": "finalized",
                "err":                None,
                "memo":               None,
            },
            {
                "signature":          _SIG,
                "slot":               12344,
                "blockTime":          1699999900,
                "confirmationStatus": "processed",
                "err":                None,
                "memo":               None,
            },
            {
                "signature":          _SIG,
                "slot":               12343,
                "blockTime":          1699999800,
                "confirmationStatus": "confirmed",
                "err":                {"InstructionError": []},
                "memo":               None,
            },
        ]
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value={"publicAddress": _ADDR_A},
        ), mock.patch(
            "solana_rpc.sol_get_signatures_for_address_at_url",
            return_value=rows,
        ):
            result = self._activity()
        self.assertEqual(
            result["transactionsStatus"], "available",
        )
        self.assertEqual(len(result["transactions"]), 3)
        statuses = [t["status"] for t in result["transactions"]]
        self.assertEqual(
            statuses, ["confirmed", "pending", "failed"],
        )
        for t in result["transactions"]:
            self.assertEqual(t["direction"], "unknown")
            self.assertIsNone(t["amount"])
            self.assertEqual(t["source"], "rpc_signatures")

    def test_activity_limit_clamped_to_50(self):
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        captured_limits: list[int] = []

        def _spy(_url, _addr, limit=20):
            captured_limits.append(limit)
            return []
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value={"publicAddress": _ADDR_A},
        ), mock.patch(
            "solana_rpc.sol_get_signatures_for_address_at_url",
            side_effect=_spy,
        ):
            self._activity(limit=10_000)
        self.assertEqual(captured_limits, [50])

    def test_activity_never_fakes_amount_or_direction(self):
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        rows = [{
            "signature":          _SIG,
            "slot":               1,
            "blockTime":          1700000000,
            "confirmationStatus": "confirmed",
            "err":                None,
            "memo":               None,
        }]
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value={"publicAddress": _ADDR_A},
        ), mock.patch(
            "solana_rpc.sol_get_signatures_for_address_at_url",
            return_value=rows,
        ):
            result = self._activity()
        for t in result["transactions"]:
            self.assertIsNone(t["amount"])
            self.assertEqual(t["direction"], "unknown")

    def test_activity_never_exposes_rpc_url(self):
        os.environ["SOLANA_RPC_URL"] = (
            "https://leaky-rpc.example/?key=leaky-secret-xyz"
        )
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value={"publicAddress": _ADDR_A},
        ), mock.patch(
            "solana_rpc.sol_get_signatures_for_address_at_url",
            return_value=[],
        ):
            result = self._activity()
        blob = repr(result)
        self.assertNotIn("leaky-rpc.example", blob)
        self.assertNotIn("leaky-secret-xyz", blob)


class SolanaMessageBuilderTests(unittest.TestCase):

    def test_message_shape_is_150_bytes_for_simple_transfer(self):
        from solana_rpc import build_sol_transfer_message_bytes
        msg = build_sol_transfer_message_bytes(
            from_address_b58=_ADDR_A,
            to_address_b58=_ADDR_B,
            lamports=500_000_000,
            recent_blockhash_b58=_BLOCKHASH,
        )
        self.assertEqual(len(msg), 150)
        self.assertEqual(msg[0], 1)
        self.assertEqual(msg[1], 0)
        self.assertEqual(msg[2], 1)

    def test_message_builder_rejects_invalid_addresses(self):
        from solana_rpc import (
            build_sol_transfer_message_bytes, SolanaRpcError,
        )
        with self.assertRaises(SolanaRpcError):
            build_sol_transfer_message_bytes(
                from_address_b58="not-a-solana-address",
                to_address_b58=_ADDR_B,
                lamports=500_000_000,
                recent_blockhash_b58=_BLOCKHASH,
            )

    def test_message_builder_rejects_zero_amount(self):
        from solana_rpc import build_sol_transfer_message_bytes
        with self.assertRaises(ValueError):
            build_sol_transfer_message_bytes(
                from_address_b58=_ADDR_A,
                to_address_b58=_ADDR_B,
                lamports=0,
                recent_blockhash_b58=_BLOCKHASH,
            )


class SolanaFeeCalculationTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def _draft(self):
        from routes.crypto_wallet_routes import (
            SendDraftPayload, _solana_send_dispatch,
        )
        payload = SendDraftPayload(
            fromAddress=_ADDR_A,
            destinationAddress=_ADDR_B,
            amountSol="0.5",
        )
        principal = {"vault_id": "v-fee-test"}
        return _solana_send_dispatch("SOL", payload, principal)

    def test_draft_uses_real_rpc_fee_when_available(self):
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            return_value={
                "blockhash": _BLOCKHASH,
                "lastValidBlockHeight": 100,
            },
        ), mock.patch(
            "solana_rpc.sol_get_fee_for_message_at_url",
            return_value=7500,
        ):
            result = self._draft()
        self.assertEqual(result["feeLamports"], 7500)
        self.assertEqual(
            result["feeSource"], "rpc_getFeeForMessage",
        )

    def test_draft_falls_back_to_default_when_rpc_fee_fails(self):
        from solana_rpc import SolanaRpcError, REASON_RPC_ERROR
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            return_value={
                "blockhash": _BLOCKHASH,
                "lastValidBlockHeight": 100,
            },
        ), mock.patch(
            "solana_rpc.sol_get_fee_for_message_at_url",
            side_effect=SolanaRpcError(REASON_RPC_ERROR),
        ):
            result = self._draft()
        self.assertEqual(result["feeLamports"], 5000)
        self.assertEqual(
            result["feeSource"], "default_lamports",
        )

    def test_fee_calculation_never_requires_private_key(self):
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            return_value={
                "blockhash": _BLOCKHASH,
                "lastValidBlockHeight": 100,
            },
        ), mock.patch(
            "solana_rpc.sol_get_fee_for_message_at_url",
            return_value=5001,
        ):
            result = self._draft()
        blob = repr(result).lower()
        for banned in (
            "encryptedwalletsecret", "privatekey", "secretkey",
            "seedphrase", "mnemonic",
        ):
            self.assertNotIn(banned, blob)


class SolanaFeaturesFlagsTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_features_include_solana_activity_status_fee_flags(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertIn("solanaActivityConnected", env)
        self.assertIn("solanaStatusReady", env)
        self.assertIn("solanaFeeReady", env)
        self.assertTrue(env["solanaActivityConnected"])
        self.assertTrue(env["solanaStatusReady"])
        self.assertTrue(env["solanaFeeReady"])

    def test_features_disabled_flags_when_rpc_missing(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertFalse(env["solanaActivityConnected"])
        self.assertFalse(env["solanaStatusReady"])
        self.assertFalse(env["solanaFeeReady"])


class SolanaTransactionStatusRouteRegistrationTests(unittest.TestCase):

    def test_transaction_status_route_registered(self):
        from routes.crypto_wallet_routes import router
        paths = [r.path for r in router.routes]
        self.assertIn(
            "/crypto/wallet/network/{network}/{asset}/transaction/{tx_hash}",
            paths,
        )


class SolanaLoggingRestrictionsTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")
        self._rpc_src = (
            _BACKEND_ROOT / "solana_rpc.py"
        ).read_text(encoding="utf-8")

    def test_status_route_never_logs_signature(self):
        idx = self._src.find("_solana_transaction_status")
        self.assertGreater(idx, -1)
        slice_ = self._src[idx:idx + 6000]
        self.assertNotIn("logger.info(\"[WALLET-ENGINE] "
                         "solana_status sig=", slice_)
        self.assertNotIn("signature=%s", slice_)

    def test_activity_route_never_logs_address(self):
        idx = self._src.find("_solana_transactions")
        self.assertGreater(idx, -1)
        slice_ = self._src[idx:idx + 6000]
        self.assertNotIn("logger.info(\"[WALLET-ENGINE] "
                         "solana_activity addr=", slice_)
        self.assertNotIn("address=%s", slice_)


class NoBackendSigningInActivitySliceTests(unittest.TestCase):

    def test_solana_rpc_never_imports_ed25519_signer(self):
        src = (_BACKEND_ROOT / "solana_rpc.py").read_text(
            encoding="utf-8",
        )
        low = src.lower()
        for banned in (
            "sign_transaction", "signtransaction",
            "solana.transaction.sign", "ed25519.sign",
        ):
            self.assertNotIn(banned, low)


class NoExchangeCopySliceTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_activity_envelope_has_no_exchange_verbs(self):
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ):
            from routes.crypto_wallet_routes import _solana_transactions
            principal = {"vault_id": "v-nx"}
            result = _solana_transactions("SOL", 20, principal)
        blob = repr(result).lower()
        for banned in (
            "swap", "stake", "bridge",
            " buy ", " sell ", " trade ",
        ):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
