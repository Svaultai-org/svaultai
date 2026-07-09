

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


_TRON_ENV_KEYS = (
    "VAULTAI_CRYPTO_TRON_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_PAUSED",
    "VAULTAI_CRYPTO_TRON_BROADCAST_RATE_LIMIT",
    "VAULTAI_CRYPTO_TRON_BROADCAST_RATE_WINDOW_SECS",
    "VAULTAI_CRYPTO_TRON_SEND_FEE_LIMIT_SUN",
    "VAULTAI_CRYPTO_TRON_LOW_TRX_THRESHOLD_SUN",
    "TRON_API_BASE_URL",
    "TRON_RPC_URL",
    "TRON_API_KEY",
    "TRON_USDT_CONTRACT_ADDRESS",
    "TRON_USDT_DECIMALS",
)


TRON_USDT_MAINNET   = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"
TRON_TEST_FROM_ADDR = "TFczxzPhnThNSqr5by8tvxsdCFRRz6cPNq"
TRON_TEST_DEST_ADDR = "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9"

_VALID_TXID = "a" * 64


def _valid_signed_tx() -> dict:
    return {
        "txID":         _VALID_TXID,
        "raw_data":     {"contract": [{"type": "TriggerSmartContract"}]},
        "raw_data_hex": "0a" * 20,
        "signature":    ["b" * 130],
    }


class TronSendConfigTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_tron_send_disabled_by_default(self):
        from vault_config import tron_send_enabled
        self.assertFalse(tron_send_enabled())

    def test_tron_send_paused_disabled_by_default(self):
        from vault_config import tron_send_paused
        self.assertFalse(tron_send_paused())

    def test_tron_broadcast_rate_limit_default_3(self):
        from vault_config import tron_broadcast_rate_limit
        self.assertEqual(tron_broadcast_rate_limit(), 3)

    def test_tron_broadcast_rate_window_default_60(self):
        from vault_config import tron_broadcast_rate_window_secs
        self.assertEqual(tron_broadcast_rate_window_secs(), 60)

    def test_tron_send_flag_toggle(self):
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        from vault_config import tron_send_enabled
        self.assertTrue(tron_send_enabled())


class TronRpcSendHelpersTests(unittest.TestCase):

    def test_txid_hex_validation(self):
        from tron_rpc import is_valid_txid_hex
        self.assertTrue(is_valid_txid_hex(_VALID_TXID))
        self.assertFalse(is_valid_txid_hex("A" * 63))
        self.assertFalse(is_valid_txid_hex("z" * 64))
        self.assertFalse(is_valid_txid_hex(""))
        self.assertFalse(is_valid_txid_hex(None))

    def test_signed_tx_validation_shape(self):
        from tron_rpc import is_valid_tron_signed_transaction
        self.assertTrue(
            is_valid_tron_signed_transaction(_valid_signed_tx()),
        )
        self.assertFalse(is_valid_tron_signed_transaction(None))
        self.assertFalse(is_valid_tron_signed_transaction({}))

        missing_sig = _valid_signed_tx()
        missing_sig.pop("signature")
        self.assertFalse(is_valid_tron_signed_transaction(missing_sig))

        empty_sig = _valid_signed_tx()
        empty_sig["signature"] = []
        self.assertFalse(is_valid_tron_signed_transaction(empty_sig))

        short_sig = _valid_signed_tx()
        short_sig["signature"] = ["ab" * 10]
        self.assertFalse(is_valid_tron_signed_transaction(short_sig))

    def test_sun_to_trx_string(self):
        from tron_rpc import sun_to_trx_string
        self.assertEqual(sun_to_trx_string(0), "0")
        self.assertEqual(sun_to_trx_string(1), "0.000001")
        self.assertEqual(sun_to_trx_string(1_000_000), "1")
        self.assertEqual(sun_to_trx_string(1_500_000), "1.5")


class TronSendDraftBehaviorTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)
        from routes.crypto_wallet_routes import (
            reset_tron_safety_state_for_tests,
        )
        reset_tron_safety_state_for_tests()

    def _payload(self, amount: str = "5.5"):
        from routes.crypto_wallet_routes import SendDraftPayload
        return SendDraftPayload(
            fromAddress=TRON_TEST_FROM_ADDR,
            destinationAddress=TRON_TEST_DEST_ADDR,
            amountUsdt=amount,
        )

    def test_draft_disabled_when_send_flag_off(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _tron_send_dispatch
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_send_dispatch(
            "USDT_TRC20", self._payload(), principal,
        )
        self.assertEqual(
            result["wallet_engine"], "tron_send_not_enabled",
        )

    def test_draft_paused_returns_paused_envelope(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_PAUSED"] = "true"
        from routes.crypto_wallet_routes import _tron_send_dispatch
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_send_dispatch(
            "USDT_TRC20", self._payload(), principal,
        )
        self.assertEqual(
            result["wallet_engine"], "tron_send_paused",
        )

    def test_draft_rejects_invalid_from(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _tron_send_dispatch, SendDraftPayload,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        payload = SendDraftPayload(
            fromAddress="0x" + "a" * 40,
            destinationAddress=TRON_TEST_DEST_ADDR,
            amountUsdt="5",
        )
        with self.assertRaises(HTTPException) as ctx:
            _tron_send_dispatch("USDT_TRC20", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_draft_rejects_invalid_destination(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _tron_send_dispatch, SendDraftPayload,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        payload = SendDraftPayload(
            fromAddress=TRON_TEST_FROM_ADDR,
            destinationAddress="not-an-address",
            amountUsdt="5",
        )
        with self.assertRaises(HTTPException) as ctx:
            _tron_send_dispatch("USDT_TRC20", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_draft_refuses_self_send(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _tron_send_dispatch, SendDraftPayload,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        payload = SendDraftPayload(
            fromAddress=TRON_TEST_FROM_ADDR,
            destinationAddress=TRON_TEST_FROM_ADDR,
            amountUsdt="5",
        )
        with self.assertRaises(HTTPException) as ctx:
            _tron_send_dispatch("USDT_TRC20", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_draft_rejects_more_than_six_decimals(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _tron_send_dispatch, SendDraftPayload,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        payload = SendDraftPayload(
            fromAddress=TRON_TEST_FROM_ADDR,
            destinationAddress=TRON_TEST_DEST_ADDR,
            amountUsdt="1.1234567",
        )
        with self.assertRaises(HTTPException) as ctx:
            _tron_send_dispatch("USDT_TRC20", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_draft_rejects_negative_or_zero(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _tron_send_dispatch, SendDraftPayload,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        for bad in ("0", "0.0", ""):
            payload = SendDraftPayload(
                fromAddress=TRON_TEST_FROM_ADDR,
                destinationAddress=TRON_TEST_DEST_ADDR,
                amountUsdt=bad,
            )
            with self.assertRaises(HTTPException) as ctx:
                _tron_send_dispatch("USDT_TRC20", payload, principal)
            self.assertEqual(ctx.exception.status_code, 422)

    def test_draft_reports_rpc_not_configured(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        from routes.crypto_wallet_routes import _tron_send_dispatch
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_send_dispatch(
            "USDT_TRC20", self._payload(), principal,
        )
        self.assertEqual(result["status"], "draft_unavailable")
        self.assertEqual(result["reason"], "rpc_not_configured")

    def test_draft_reports_no_token_contract(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        from routes.crypto_wallet_routes import _tron_send_dispatch
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_send_dispatch(
            "USDT_TRC20", self._payload(), principal,
        )
        self.assertEqual(result["status"], "draft_unavailable")
        self.assertEqual(
            result["reason"], "token_contract_not_configured",
        )

    def test_draft_success_returns_unsigned_and_no_secrets(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        unsigned = {
            "txID":         _VALID_TXID,
            "raw_data":     {"contract": []},
            "raw_data_hex": "0a" * 30,
        }
        with mock.patch(
            "tron_rpc.tron_create_trc20_transfer_at_url",
            return_value={
                "unsignedTransaction": unsigned,
                "txID":                _VALID_TXID,
                "rawDataHex":          "0a" * 30,
            },
        ), mock.patch(
            "tron_rpc.tron_get_trx_balance_sun_at_url",
            return_value=200_000_000,
        ), mock.patch(
            "tron_rpc.tron_get_account_resource_at_url",
            return_value={"EnergyLimit": 100, "EnergyUsed": 0},
        ):
            from routes.crypto_wallet_routes import _tron_send_dispatch
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            result = _tron_send_dispatch(
                "USDT_TRC20", self._payload("12.5"), principal,
            )
        self.assertEqual(result["status"], "draft_ready")
        self.assertEqual(result["amountUsdt"], "12.5")
        self.assertEqual(result["amountBaseUnits"], "12500000")
        self.assertEqual(result["txID"], _VALID_TXID)
        self.assertEqual(result["resourceStatus"], "ready")
        self.assertEqual(result["trxBalance"], "200")
        self.assertIn("USDT TRC20", result["feeWarning"])
        self.assertIn("TRON", result["feeWarning"])
        blob = repr(result)
        for banned in ("privateKey", "encryptedWalletSecret",
                       "seedPhrase", "mnemonic", "recoveryPhrase"):
            self.assertNotIn(banned, blob)

    def test_draft_low_trx_flag_set_when_under_threshold(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        unsigned = {
            "txID":         _VALID_TXID,
            "raw_data":     {"contract": []},
            "raw_data_hex": "0a" * 30,
        }
        with mock.patch(
            "tron_rpc.tron_create_trc20_transfer_at_url",
            return_value={
                "unsignedTransaction": unsigned,
                "txID":                _VALID_TXID,
                "rawDataHex":          "0a" * 30,
            },
        ), mock.patch(
            "tron_rpc.tron_get_trx_balance_sun_at_url",
            return_value=1000,
        ), mock.patch(
            "tron_rpc.tron_get_account_resource_at_url",
            return_value={},
        ):
            from routes.crypto_wallet_routes import _tron_send_dispatch
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            result = _tron_send_dispatch(
                "USDT_TRC20", self._payload("5"), principal,
            )
        self.assertEqual(result["resourceStatus"], "low_trx")

    def test_draft_receive_and_balance_work_when_send_paused(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_PAUSED"] = "true"
        from routes.crypto_wallet_routes import _tron_receive
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with mock.patch(
            "routes.crypto_wallet_routes."
            "_load_wallet_account_record_network",
            return_value={
                "walletLabel":   "My TRON",
                "publicAddress": TRON_USDT_MAINNET,
            },
        ):
            receive_body = _tron_receive("USDT_TRC20", principal)
        self.assertEqual(receive_body["wallet_engine"], "receive_ready")


class TronBroadcastBehaviorTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)
        from routes.crypto_wallet_routes import (
            reset_tron_safety_state_for_tests,
        )
        reset_tron_safety_state_for_tests()

    def _broadcast_payload(self, key: str = "idempo-key-1"):
        from routes.crypto_wallet_routes import SendBroadcastPayload
        return SendBroadcastPayload(
            signedTransaction=_valid_signed_tx(),
            idempotencyKey=key,
        )

    def test_broadcast_disabled_when_send_flag_off(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from routes.crypto_wallet_routes import (
            _tron_broadcast_dispatch,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_broadcast_dispatch(
            "USDT_TRC20", self._broadcast_payload(), principal,
        )
        self.assertEqual(
            result["wallet_engine"], "tron_send_not_enabled",
        )

    def test_broadcast_paused_returns_paused_envelope(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_PAUSED"] = "true"
        from routes.crypto_wallet_routes import (
            _tron_broadcast_dispatch,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        result = _tron_broadcast_dispatch(
            "USDT_TRC20", self._broadcast_payload(), principal,
        )
        self.assertEqual(
            result["wallet_engine"], "tron_send_paused",
        )

    def test_broadcast_rejects_malformed_signed_tx(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _tron_broadcast_dispatch, SendBroadcastPayload,
        )
        payload = SendBroadcastPayload(
            signedTransaction={"raw_data_hex": "aa"},
            idempotencyKey="k12345678",
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with self.assertRaises(HTTPException) as ctx:
            _tron_broadcast_dispatch("USDT_TRC20", payload, principal)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_broadcast_rejects_extra_fields(self):
        from pydantic import ValidationError
        from routes.crypto_wallet_routes import SendBroadcastPayload
        with self.assertRaises(ValidationError):
            SendBroadcastPayload(
                signedTransaction=_valid_signed_tx(),
                idempotencyKey="k12345678",
                privateKey="beef" * 16,
            )

    def test_broadcast_success_returns_real_txid_no_fake(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        with mock.patch(
            "tron_rpc.tron_broadcast_signed_transaction_at_url",
            return_value=_VALID_TXID,
        ):
            from routes.crypto_wallet_routes import (
                _tron_broadcast_dispatch,
            )
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            result = _tron_broadcast_dispatch(
                "USDT_TRC20", self._broadcast_payload(), principal,
            )
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["txHash"], _VALID_TXID)
        blob = repr(result)
        self.assertNotIn("signature", blob)
        self.assertNotIn("raw_data_hex", blob)

    def test_broadcast_idempotency_replay_returns_cached(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        call_counter = {"n": 0}

        def _spy(*a, **kw):
            call_counter["n"] += 1
            return _VALID_TXID

        with mock.patch(
            "tron_rpc.tron_broadcast_signed_transaction_at_url",
            side_effect=_spy,
        ):
            from routes.crypto_wallet_routes import (
                _tron_broadcast_dispatch,
            )
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            first = _tron_broadcast_dispatch(
                "USDT_TRC20",
                self._broadcast_payload("k12345678"),
                principal,
            )
            second = _tron_broadcast_dispatch(
                "USDT_TRC20",
                self._broadcast_payload("k12345678"),
                principal,
            )
        self.assertEqual(first, second)
        self.assertEqual(call_counter["n"], 1)

    def test_broadcast_idempotency_conflict_safe(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        from routes.crypto_wallet_routes import (
            _tron_broadcast_dispatch, SendBroadcastPayload,
        )
        principal = {"vault_id": "00000000-0000-0000-0000-000000000000"}
        with mock.patch(
            "tron_rpc.tron_broadcast_signed_transaction_at_url",
            return_value=_VALID_TXID,
        ):
            first = _tron_broadcast_dispatch(
                "USDT_TRC20",
                self._broadcast_payload("k12345678"),
                principal,
            )
            self.assertEqual(first["status"], "submitted")
            alt_signed = _valid_signed_tx()
            alt_signed["txID"] = "c" * 64
            second = _tron_broadcast_dispatch(
                "USDT_TRC20",
                SendBroadcastPayload(
                    signedTransaction=alt_signed,
                    idempotencyKey="k12345678",
                ),
                principal,
            )
        self.assertEqual(
            second["wallet_engine"], "idempotency_conflict",
        )

    def test_broadcast_rate_limit_triggers(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_BROADCAST_RATE_LIMIT"] = "2"
        os.environ["VAULTAI_CRYPTO_TRON_BROADCAST_RATE_WINDOW_SECS"] = "60"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        with mock.patch(
            "tron_rpc.tron_broadcast_signed_transaction_at_url",
            return_value=_VALID_TXID,
        ):
            from routes.crypto_wallet_routes import (
                _tron_broadcast_dispatch, SendBroadcastPayload,
            )
            principal = {
                "vault_id":
                "00000000-0000-0000-0000-000000000000",
            }
            _tron_broadcast_dispatch(
                "USDT_TRC20",
                SendBroadcastPayload(
                    signedTransaction=_valid_signed_tx(),
                    idempotencyKey="k1abcd001",
                ),
                principal,
            )
            _tron_broadcast_dispatch(
                "USDT_TRC20",
                SendBroadcastPayload(
                    signedTransaction={
                        **_valid_signed_tx(), "txID": "d" * 64,
                    },
                    idempotencyKey="k1abcd002",
                ),
                principal,
            )
            blocked = _tron_broadcast_dispatch(
                "USDT_TRC20",
                SendBroadcastPayload(
                    signedTransaction={
                        **_valid_signed_tx(), "txID": "e" * 64,
                    },
                    idempotencyKey="k1abcd003",
                ),
                principal,
            )
        self.assertEqual(blocked["status"], "rate_limited")


class TronTransactionStatusTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_status_route_validates_txid(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from fastapi import HTTPException
        from routes.crypto_wallet_routes import (
            _tron_transaction_status,
        )
        with self.assertRaises(HTTPException):
            _tron_transaction_status("USDT_TRC20", "shorttxid")

    def test_status_returns_confirmed_when_block_present(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        with mock.patch(
            "tron_rpc.tron_get_transaction_info_at_url",
            return_value={
                "status": "confirmed",
                "blockNumber": 60_000_000,
                "blockTimeStamp": 1_700_000_000_000,
                "contractResult": "SUCCESS",
            },
        ):
            from routes.crypto_wallet_routes import (
                _tron_transaction_status,
            )
            result = _tron_transaction_status(
                "USDT_TRC20", _VALID_TXID,
            )
        self.assertEqual(result["transactionStatus"], "confirmed")

    def test_status_returns_failed_when_contract_ret_bad(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        with mock.patch(
            "tron_rpc.tron_get_transaction_info_at_url",
            return_value={
                "status": "failed",
                "contractResult": "OUT_OF_ENERGY",
            },
        ):
            from routes.crypto_wallet_routes import (
                _tron_transaction_status,
            )
            result = _tron_transaction_status(
                "USDT_TRC20", _VALID_TXID,
            )
        self.assertEqual(result["transactionStatus"], "failed")

    def test_status_pending_when_provider_returns_pending(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        with mock.patch(
            "tron_rpc.tron_get_transaction_info_at_url",
            return_value={"status": "pending"},
        ):
            from routes.crypto_wallet_routes import (
                _tron_transaction_status,
            )
            result = _tron_transaction_status(
                "USDT_TRC20", _VALID_TXID,
            )
        self.assertEqual(result["transactionStatus"], "pending")


class TronFeaturesAndHealthWithSendTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_features_send_enabled_flag_reflected(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertTrue(env["tronSendEnabled"])
        self.assertFalse(env["tronSendPaused"])

    def test_features_send_paused_takes_precedence(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_PAUSED"] = "true"
        from crypto_wallet_health import build_features_envelope
        env = build_features_envelope()
        self.assertFalse(env["tronSendEnabled"])
        self.assertTrue(env["tronSendPaused"])

    def test_health_never_exposes_leaky_url_or_key(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = (
            "https://api.trongrid.io/?key=leaky-tron-send"
        )
        os.environ["TRON_API_KEY"] = "leaky-tron-send-key"
        with mock.patch(
            "tron_rpc.tron_get_health_at_url", return_value=False,
        ):
            from crypto_wallet_health import build_health_envelope
            env = build_health_envelope()
        blob = repr(env)
        self.assertNotIn("leaky-tron-send", blob)
        self.assertNotIn("trongrid.io", blob)


class TronChatSendRoutingTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)

    def test_chat_send_disabled_returns_unsupported_asset(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            f"send 25 USDT TRC20 to {TRON_TEST_DEST_ADDR}",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "USDT_TRC20")
        self.assertEqual(parsed["intent"], "unsupported_asset")

    def test_chat_send_enabled_routes_to_tron_send_draft(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            f"send 25 USDT TRC20 to {TRON_TEST_DEST_ADDR}",
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "USDT_TRC20")
        self.assertEqual(parsed["network"], "tron_mainnet")
        self.assertEqual(parsed["intent"], "send_draft")
        self.assertEqual(parsed["amount"], "25")
        self.assertEqual(
            parsed["destinationAddress"], TRON_TEST_DEST_ADDR,
        )

    def test_chat_send_usdt_erc20_stays_on_ethereum(self):
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        from wallet_engine_chat import parse_wallet_engine_chat_message
        parsed = parse_wallet_engine_chat_message(
            "send 25 USDT ERC20 to 0x" + "a" * 40,
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["asset"], "USDT_ERC20")
        self.assertNotEqual(parsed["network"], "tron_mainnet")


class TronBackendLoggingSafetyTests(unittest.TestCase):

    def setUp(self) -> None:
        self._snap = _wipe_env(*_TRON_ENV_KEYS)

    def tearDown(self) -> None:
        _restore_env(self._snap)
        from routes.crypto_wallet_routes import (
            reset_tron_safety_state_for_tests,
        )
        reset_tron_safety_state_for_tests()

    def test_broadcast_log_line_carries_no_signed_tx_or_secret(self):
        import logging
        os.environ["VAULTAI_CRYPTO_TRON_ENABLED"] = "true"
        os.environ["VAULTAI_CRYPTO_TRON_SEND_ENABLED"] = "true"
        os.environ["TRON_API_BASE_URL"] = "https://x.example"
        os.environ["TRON_USDT_CONTRACT_ADDRESS"] = TRON_USDT_MAINNET
        captured: list[str] = []

        class _Cap(logging.Handler):
            def emit(self, record):
                captured.append(self.format(record))

        handler = _Cap()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger("crypto_wallet_routes")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            with mock.patch(
                "tron_rpc.tron_broadcast_signed_transaction_at_url",
                return_value=_VALID_TXID,
            ):
                from routes.crypto_wallet_routes import (
                    _tron_broadcast_dispatch,
                    SendBroadcastPayload,
                )
                principal = {
                    "vault_id":
                    "00000000-0000-0000-0000-000000000000",
                }
                _tron_broadcast_dispatch(
                    "USDT_TRC20",
                    SendBroadcastPayload(
                        signedTransaction=_valid_signed_tx(),
                        idempotencyKey="k1abcd001",
                    ),
                    principal,
                )
        finally:
            logger.removeHandler(handler)
        joined = "\n".join(captured)
        for banned in (
            _valid_signed_tx()["signature"][0],
            _valid_signed_tx()["raw_data_hex"],
            TRON_TEST_FROM_ADDR, TRON_TEST_DEST_ADDR,
            TRON_USDT_MAINNET, "12500000",
            "k1abcd001",
        ):
            self.assertNotIn(banned, joined,
                             f"log leaked {banned!r}")


class TronSendSourceGuardTests(unittest.TestCase):

    def setUp(self) -> None:
        self._src = (
            _BACKEND_ROOT / "routes" / "crypto_wallet_routes.py"
        ).read_text(encoding="utf-8")
        self._rpc_src = (
            _BACKEND_ROOT / "tron_rpc.py"
        ).read_text(encoding="utf-8")

    def test_no_backend_signing_present(self):
        low = self._src.lower()
        self.assertNotIn("sign_transaction", low)
        self.assertNotIn("privatekey", low)
        self.assertNotIn("mnemonic", low)

    def test_no_seed_or_mnemonic_helpers_in_rpc(self):
        low = self._rpc_src.lower()
        self.assertNotIn("privatekey", low)
        self.assertNotIn("mnemonic", low)
        self.assertNotIn("seed_phrase", low)

    def test_no_fake_txid_hardcoded_in_routes(self):
        self.assertNotIn('"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', self._src)
        self.assertNotIn(
            '"111111111111111111111111111111111111', self._src,
        )


if __name__ == "__main__":
    unittest.main()
