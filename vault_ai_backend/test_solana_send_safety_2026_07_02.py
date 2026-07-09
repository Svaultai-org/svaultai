

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
    "VAULTAI_CRYPTO_SOLANA_SEND_PAUSED",
    "VAULTAI_CRYPTO_SOLANA_BROADCAST_RATE_LIMIT",
    "VAULTAI_CRYPTO_SOLANA_BROADCAST_RATE_WINDOW_SECS",
    "SOLANA_RPC_URL",
)


_ADDR_A = "So11111111111111111111111111111111111111112"
_ADDR_B = "11111111111111111111111111111111"


class SolanaSendFlagTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_solana_send_disabled_by_default(self):
        from vault_config import solana_send_enabled
        self.assertFalse(solana_send_enabled())

    def test_solana_send_paused_default_false(self):
        from vault_config import solana_send_paused
        self.assertFalse(solana_send_paused())

    def test_solana_send_enabled_via_env(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        from vault_config import solana_send_enabled
        self.assertTrue(solana_send_enabled())

    def test_features_solana_send_paused_field_present(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_PAUSED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertTrue(env["solanaSendPaused"])
        self.assertFalse(env["solanaSendEnabled"])


class SolanaDraftDispatchDisabledTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def _draft(self, **kwargs):
        from routes.crypto_wallet_routes import (
            SendDraftPayload, _solana_send_dispatch,
        )
        payload = SendDraftPayload(
            fromAddress=_ADDR_A,
            destinationAddress=_ADDR_B,
            amountSol="0.1",
            **kwargs,
        )
        principal = {"vault_id": "v-00000000"}
        return _solana_send_dispatch("SOL", payload, principal)

    def test_draft_returns_disabled_when_solana_off(self):
        result = self._draft()
        self.assertEqual(
            result["wallet_engine"], "solana_not_enabled",
        )

    def test_draft_returns_send_not_enabled_when_only_solana_on(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        result = self._draft()
        self.assertEqual(
            result["wallet_engine"], "solana_send_not_enabled",
        )

    def test_draft_returns_paused_envelope(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_PAUSED"] = "true"
        result = self._draft()
        self.assertEqual(
            result["wallet_engine"], "solana_send_paused",
        )


class SolanaDraftValidationTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def _draft(self, **kwargs):
        from routes.crypto_wallet_routes import (
            SendDraftPayload, _solana_send_dispatch,
        )
        payload = SendDraftPayload(**kwargs)
        principal = {"vault_id": "v-00000000"}
        return _solana_send_dispatch("SOL", payload, principal)

    def test_invalid_from_address_raises(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self._draft(
                fromAddress="notbase58",
                destinationAddress=_ADDR_B,
                amountSol="0.5",
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(
            ctx.exception.detail["wallet_engine"],
            "invalid_from_address",
        )

    def test_invalid_destination_raises(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self._draft(
                fromAddress=_ADDR_A,
                destinationAddress="notbase58",
                amountSol="0.5",
            )
        self.assertEqual(
            ctx.exception.detail["wallet_engine"],
            "invalid_destination_address",
        )

    def test_self_send_refused(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self._draft(
                fromAddress=_ADDR_A,
                destinationAddress=_ADDR_A,
                amountSol="0.5",
            )
        self.assertEqual(
            ctx.exception.detail["wallet_engine"],
            "self_send_refused",
        )

    def test_amount_zero_refused(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self._draft(
                fromAddress=_ADDR_A,
                destinationAddress=_ADDR_B,
                amountSol="0",
            )

    def test_amount_too_many_decimals_refused(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self._draft(
                fromAddress=_ADDR_A,
                destinationAddress=_ADDR_B,
                amountSol="0.1234567890",
            )

    def test_amount_missing_refused(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self._draft(
                fromAddress=_ADDR_A,
                destinationAddress=_ADDR_B,
            )

    def test_draft_rpc_not_configured(self):
        result = self._draft(
            fromAddress=_ADDR_A,
            destinationAddress=_ADDR_B,
            amountSol="0.5",
        )
        self.assertEqual(result["status"], "draft_unavailable")
        self.assertEqual(result["reason"], "rpc_not_configured")


class SolanaDraftHappyPathTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_draft_returns_expected_envelope(self):
        from routes.crypto_wallet_routes import (
            SendDraftPayload, _solana_send_dispatch,
        )
        payload = SendDraftPayload(
            fromAddress=_ADDR_A,
            destinationAddress=_ADDR_B,
            amountSol="0.75",
        )
        principal = {"vault_id": "v-00000000"}
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            return_value={
                "blockhash":
                    "FwZbEB4YfDjK6iEy4uP5oXwUTL7jXbGgnh8UyKz4EbCE",
                "lastValidBlockHeight": 12345678,
            },
        ):
            result = _solana_send_dispatch(
                "SOL", payload, principal,
            )
        self.assertEqual(result["status"], "draft_ready")
        self.assertEqual(result["asset"], "SOL")
        self.assertEqual(result["network"], "solana_mainnet")
        self.assertEqual(result["amountSol"], "0.75")
        self.assertEqual(result["lamports"], "750000000")
        self.assertIn("recentBlockhash", result)
        self.assertIn("warning", result)

    def test_draft_never_returns_encrypted_secret_or_key(self):
        from routes.crypto_wallet_routes import (
            SendDraftPayload, _solana_send_dispatch,
        )
        payload = SendDraftPayload(
            fromAddress=_ADDR_A,
            destinationAddress=_ADDR_B,
            amountSol="0.5",
        )
        principal = {"vault_id": "v-00000000"}
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            return_value={
                "blockhash":
                    "FwZbEB4YfDjK6iEy4uP5oXwUTL7jXbGgnh8UyKz4EbCE",
                "lastValidBlockHeight": 12345678,
            },
        ):
            result = _solana_send_dispatch(
                "SOL", payload, principal,
            )
        blob = repr(result).lower()
        for banned in (
            "encryptedwalletsecret", "privatekey", "secretkey",
            "seedphrase", "mnemonic", "recoveryphrase",
        ):
            self.assertNotIn(banned, blob)


class SolanaBroadcastDispatchTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)
        from routes.crypto_wallet_routes import (
            reset_solana_safety_state_for_tests,
        )
        reset_solana_safety_state_for_tests()

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def _broadcast(self, **kwargs):
        from routes.crypto_wallet_routes import (
            SendBroadcastPayload, _solana_broadcast_dispatch,
        )
        payload = SendBroadcastPayload(**kwargs)
        principal = {"vault_id": "v-broadcast-test"}
        return _solana_broadcast_dispatch(
            "SOL", payload, principal,
        )

    def test_broadcast_disabled_when_solana_off(self):
        result = self._broadcast(signedTransaction="AAAA")
        self.assertEqual(
            result["wallet_engine"], "solana_not_enabled",
        )

    def test_broadcast_send_not_enabled(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        result = self._broadcast(signedTransaction="AAAA")
        self.assertEqual(
            result["wallet_engine"], "solana_send_not_enabled",
        )

    def test_broadcast_paused(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_PAUSED"] = "true"
        result = self._broadcast(signedTransaction="AAAA")
        self.assertEqual(
            result["wallet_engine"], "solana_send_paused",
        )

    def test_broadcast_rejects_extra_fields(self):
        from routes.crypto_wallet_routes import SendBroadcastPayload
        with self.assertRaises(Exception):
            SendBroadcastPayload(
                signedTransaction="AAAA",
                idempotencyKey="abc12345",
                signedTx="AAAA",
                secretKey="leaked",
            )

    def test_broadcast_returns_real_rpc_signature(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        fake_sig = (
            "4vGVQpTJyGgQMTkwoUn7Xf4WScDW6RxDGNhWQb1QxLGyKcksVezR"
            "GNS4pmH24DngjyfNhBGpAtWxdD8gwucjFCG9"
        )
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            return_value=fake_sig,
        ):
            result = self._broadcast(
                signedTransaction="AAAA",
                idempotencyKey="abc12345678",
            )
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["signature"], fake_sig)

    def test_broadcast_idempotency_replay_returns_same_result(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        fake_sig = (
            "4vGVQpTJyGgQMTkwoUn7Xf4WScDW6RxDGNhWQb1QxLGyKcksVezR"
            "GNS4pmH24DngjyfNhBGpAtWxdD8gwucjFCG9"
        )
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            return_value=fake_sig,
        ) as m:
            first = self._broadcast(
                signedTransaction="AAAA",
                idempotencyKey="abc12345678",
            )
            second = self._broadcast(
                signedTransaction="AAAA",
                idempotencyKey="abc12345678",
            )
        self.assertEqual(first["signature"], second["signature"])
        self.assertEqual(m.call_count, 1)

    def test_broadcast_idempotency_conflict_on_different_body(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        fake_sig = (
            "4vGVQpTJyGgQMTkwoUn7Xf4WScDW6RxDGNhWQb1QxLGyKcksVezR"
            "GNS4pmH24DngjyfNhBGpAtWxdD8gwucjFCG9"
        )
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            return_value=fake_sig,
        ):
            self._broadcast(
                signedTransaction="AAAA",
                idempotencyKey="abc12345678",
            )
            conflict = self._broadcast(
                signedTransaction="BBBB",
                idempotencyKey="abc12345678",
            )
        self.assertEqual(
            conflict["wallet_engine"], "idempotency_conflict",
        )

    def test_broadcast_rate_limit(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        os.environ[
            "VAULTAI_CRYPTO_SOLANA_BROADCAST_RATE_LIMIT"
        ] = "2"
        fake_sig = (
            "4vGVQpTJyGgQMTkwoUn7Xf4WScDW6RxDGNhWQb1QxLGyKcksVezR"
            "GNS4pmH24DngjyfNhBGpAtWxdD8gwucjFCG9"
        )
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            return_value=fake_sig,
        ):
            self._broadcast(
                signedTransaction="AAAA",
                idempotencyKey="key1abcdef",
            )
            self._broadcast(
                signedTransaction="BBBB",
                idempotencyKey="key2abcdef",
            )
            third = self._broadcast(
                signedTransaction="CCCC",
                idempotencyKey="key3abcdef",
            )
        self.assertEqual(third["status"], "rate_limited")

    def test_broadcast_never_returns_raw_rpc_body(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://leaky.example/xxx"
        from solana_rpc import SolanaRpcError, REASON_RPC_ERROR
        with mock.patch(
            "solana_rpc.sol_send_signed_transaction_at_url",
            side_effect=SolanaRpcError(REASON_RPC_ERROR),
        ):
            result = self._broadcast(signedTransaction="AAAA")
        blob = repr(result)
        self.assertNotIn("leaky.example", blob)


class SolanaSendLoggingRestrictionsTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")

    def test_solana_broadcast_logs_only_signature_prefix(self):
        idx = self._src.find("solana_broadcast_ok")
        self.assertGreater(idx, -1)
        slice_ = self._src[idx - 400:idx + 600]
        self.assertIn("sig_prefix", slice_)
        self.assertNotIn("signedTransaction=%", slice_)

    def test_solana_send_never_logs_amount_or_addresses(self):
        idx = self._src.find("_solana_send_dispatch")
        self.assertGreater(idx, -1)
        slice_ = self._src[idx:idx + 5000]
        self.assertNotIn("logger.info(\"[WALLET-ENGINE] solana_send",
                         slice_)
        self.assertNotIn("amountSol=%", slice_)


class SolanaSendPayloadForbidsExtraTests(unittest.TestCase):

    def test_send_draft_payload_forbids_extra_fields(self):
        from routes.crypto_wallet_routes import SendDraftPayload
        with self.assertRaises(Exception):
            SendDraftPayload(
                fromAddress=_ADDR_A,
                destinationAddress=_ADDR_B,
                amountSol="0.5",
                secretKey="leaked",
            )

    def test_send_draft_payload_forbids_plaintext_key_aliases(self):
        from routes.crypto_wallet_routes import SendDraftPayload
        for banned in (
            "privateKey", "seedPhrase", "mnemonic",
            "recoveryPhrase", "solanaPrivateKey",
        ):
            with self.subTest(banned=banned):
                with self.assertRaises(Exception):
                    SendDraftPayload(**{
                        "fromAddress":        _ADDR_A,
                        "destinationAddress": _ADDR_B,
                        "amountSol":          "0.5",
                        banned:                "leaked",
                    })


class SolanaBalanceReceiveStillWorkWhenSendPausedTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_PAUSED"] = "true"

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_receive_still_works_when_send_paused(self):
        from routes.crypto_wallet_routes import _solana_receive
        principal = {"vault_id": "v-00000000"}
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value=None,
        ):
            result = _solana_receive("SOL", principal)
        self.assertEqual(
            result["wallet_engine"], "create_solana_wallet_first",
        )

    def test_balance_still_works_when_send_paused(self):
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        from routes.crypto_wallet_routes import _solana_balance
        principal = {"vault_id": "v-00000000"}
        with mock.patch(
            "solana_rpc.sol_get_balance_lamports_at_url",
            return_value=1_500_000_000,
        ):
            result = _solana_balance("SOL", _ADDR_A, principal)
        self.assertEqual(result["balanceStatus"], "available")
        self.assertEqual(result["availableAmount"], "1.5")


class ChatParserSolanaSendTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_send_sol_disabled_becomes_unsupported(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            f"send 0.5 SOL to {_ADDR_A}",
        )
        self.assertEqual(parsed["intent"], "unsupported_asset")

    def test_send_sol_enabled_becomes_send_draft(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            f"send 0.5 SOL to {_ADDR_A}",
        )
        self.assertEqual(parsed["intent"], "send_draft")
        self.assertEqual(parsed["asset"], "SOL")
        self.assertEqual(parsed["network"], "solana_mainnet")
        self.assertEqual(parsed["amount"], "0.5")
        self.assertEqual(parsed["destinationAddress"], _ADDR_A)


class NoBackendSigningImportsSendSliceTests(unittest.TestCase):

    def test_solana_rpc_has_no_sign_symbols(self):
        src = (_BACKEND_ROOT / "solana_rpc.py").read_text(
            encoding="utf-8",
        )
        low = src.lower()
        for banned in (
            "signtransaction", "sign_transaction",
            "solana.transaction.sign",
            "ed25519.sign",
        ):
            self.assertNotIn(banned, low)

    def test_crypto_wallet_routes_never_imports_ed25519(self):
        src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")
        low = src.lower()
        self.assertNotIn("from cryptography", low)
        self.assertNotIn("import ed25519", low)


class NoExchangeCopyTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_SOLANA_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_solana_draft_ready_copy_no_exchange_verbs(self):
        os.environ["VAULTAI_CRYPTO_SOLANA_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_SOLANA_SEND_ENABLED"] = "true"
        os.environ["SOLANA_RPC_URL"] = "https://rpc.example"
        from routes.crypto_wallet_routes import (
            SendDraftPayload, _solana_send_dispatch,
        )
        payload = SendDraftPayload(
            fromAddress=_ADDR_A,
            destinationAddress=_ADDR_B,
            amountSol="0.5",
        )
        principal = {"vault_id": "v-00000000"}
        with mock.patch(
            "solana_rpc.sol_get_latest_blockhash_at_url",
            return_value={
                "blockhash":
                    "FwZbEB4YfDjK6iEy4uP5oXwUTL7jXbGgnh8UyKz4EbCE",
                "lastValidBlockHeight": 12345678,
            },
        ):
            result = _solana_send_dispatch(
                "SOL", payload, principal,
            )
        blob = repr(result).lower()
        for banned in ("swap", "stake", "bridge",
                       " buy ", " sell ", " trade "):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
