"""Crypto Vault chat control — classifier + envelope + endpoint tests.

Verifies the closed-set intent classifier is deterministic, refuses
secret-material + exchange-action requests, disambiguates bare USDT,
never fabricates balance/activity, and never leaks secrets.
"""

from __future__ import annotations

import inspect
import io
import logging
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


_BACKEND_ROOT = Path(__file__).parent


def _wipe_env(*names):
    snap = {n: os.environ.get(n) for n in names}
    for n in names:
        os.environ.pop(n, None)
    return snap


def _restore_env(snap):
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


_CLASSIFY_PATH = "/crypto/vault/chat/classify"


class _BaseTest(unittest.TestCase):

    def setUp(self):
        from main import app
        from device_gate import verify_trusted_device
        self._app = app
        self._dep_key = verify_trusted_device
        self._prior_override = app.dependency_overrides.get(
            verify_trusted_device,
        )
        app.dependency_overrides[verify_trusted_device] = lambda: {
            "vault_id": "test-vault-uuid",
            "account_id": "test-account",
        }

    def tearDown(self):
        if self._prior_override is None:
            self._app.dependency_overrides.pop(self._dep_key, None)
        else:
            self._app.dependency_overrides[self._dep_key] = (
                self._prior_override
            )

    def _client(self):
        return TestClient(self._app)


class ClassifierIntentTests(unittest.TestCase):


    def _intent(self, message):
        from crypto_vault_chat_control import classify_and_build
        return classify_and_build(message)["intent"]


    def test_show_vault(self):
        for m in [
            "Show my Crypto Vault",
            "show my vault",
            "open my crypto vault",
            "my wallets",
            "crypto vault",
        ]:
            self.assertEqual(self._intent(m),
                "crypto_vault_show_vault",
                f"failed to classify show-vault: {m!r}")


    def test_balance_by_asset(self):
        pairs = [
            ("What is my ETH balance?",           "ETH"),
            ("How much SOL do I have?",           "SOL"),
            ("Show my USDC balance",              "USDC_ERC20"),
            ("What is my monero balance?",        "XMR"),
        ]
        from crypto_vault_chat_control import (
            classify_and_build, INTENT_BALANCE,
        )
        for msg, expected_asset in pairs:
            r = classify_and_build(msg)
            self.assertEqual(r["intent"], INTENT_BALANCE, msg)
            self.assertEqual(
                r["card"]["asset"], expected_asset, msg,
            )
            self.assertTrue(r["card"]["liveFetchRequired"])


    def test_usdt_ambiguity_asks_which_network(self):
        for m in [
            "What is my USDT balance?",
            "show my USDT",
            "how much USDT do I have",
            "prepare a 10 USDT transfer to 0x1234567890abcdef1234567890abcdef12345678",
        ]:
            from crypto_vault_chat_control import (
                classify_and_build, INTENT_CLARIFY_USDT_NETWORK,
            )
            r = classify_and_build(m)
            self.assertEqual(
                r["intent"], INTENT_CLARIFY_USDT_NETWORK,
                f"USDT ambiguity not caught: {m!r}",
            )
            self.assertEqual(
                r["card"]["cardType"], "crypto_vault_clarify_card",
            )
            self.assertEqual(
                sorted(r["card"]["options"]),
                ["USDT_ERC20", "USDT_TRC20"],
            )


    def test_usdt_erc20_and_usdt_trc20_are_distinguished(self):
        from crypto_vault_chat_control import (
            classify_and_build, INTENT_BALANCE,
        )
        r1 = classify_and_build("show my USDT ERC20 balance")
        self.assertEqual(r1["intent"], INTENT_BALANCE)
        self.assertEqual(r1["card"]["asset"], "USDT_ERC20")

        r2 = classify_and_build("show my USDT TRC20 balance")
        self.assertEqual(r2["intent"], INTENT_BALANCE)
        self.assertEqual(r2["card"]["asset"], "USDT_TRC20")


    def test_receive_address(self):
        from crypto_vault_chat_control import (
            classify_and_build, INTENT_RECEIVE_ADDRESS,
        )
        for m in [
            "Show my Solana address",
            "Show my Monero receive address",
            "What is my ETH address",
            "my receive address",
        ]:
            r = classify_and_build(m)
            self.assertEqual(r["intent"], INTENT_RECEIVE_ADDRESS, m)


    def test_receive_qr(self):
        from crypto_vault_chat_control import (
            classify_and_build, INTENT_RECEIVE_QR,
        )
        r = classify_and_build("Show my Monero receive QR")
        self.assertEqual(r["intent"], INTENT_RECEIVE_QR)
        self.assertEqual(r["card"]["asset"], "XMR")


    def test_scanner_status(self):
        from crypto_vault_chat_control import (
            classify_and_build, INTENT_SCANNER_STATUS,
        )
        for m in [
            "Why is Monero balance unavailable?",
            "Monero scanner",
            "scanner status",
        ]:
            r = classify_and_build(m)
            self.assertEqual(r["intent"], INTENT_SCANNER_STATUS, m)
            self.assertEqual(r["card"]["asset"], "XMR")


    def test_activity(self):
        from crypto_vault_chat_control import (
            classify_and_build, INTENT_ACTIVITY,
        )
        r = classify_and_build("Show my recent crypto activity")
        self.assertEqual(r["intent"], INTENT_ACTIVITY)


    def test_unrecognized_falls_through(self):
        from crypto_vault_chat_control import (
            classify_and_build, INTENT_UNRECOGNIZED,
        )
        for m in [
            "How is the weather today",
            "",
            "abcdefghijklmn",
        ]:
            r = classify_and_build(m)
            self.assertEqual(r["intent"], INTENT_UNRECOGNIZED, m)


    def test_non_string_input_is_unrecognized(self):
        from crypto_vault_chat_control import (
            classify_crypto_vault_intent, INTENT_UNRECOGNIZED,
        )
        for junk in (None, 123, [], {}, object()):
            self.assertEqual(
                classify_crypto_vault_intent(junk).intent,
                INTENT_UNRECOGNIZED,
            )


class SendDraftTests(unittest.TestCase):


    def test_send_draft_extracts_amount_asset_recipient(self):
        from crypto_vault_chat_control import (
            classify_and_build, INTENT_SEND_DRAFT,
        )
        cases = [
            ("Prepare a 5 USDC send to "
             "0x1234567890abcdef1234567890abcdef12345678",
             "USDC_ERC20", "5",
             "0x1234567890abcdef1234567890abcdef12345678"),
            ("Prepare a 0.1 SOL transfer",
             "SOL", "0.1", None),
            ("Prepare a 10 USDT TRC20 transfer",
             "USDT_TRC20", "10", None),
            ("send 0.05 ETH to "
             "0xABCDEF0000000000000000000000000000000000",
             "ETH", "0.05",
             "0xABCDEF0000000000000000000000000000000000"),
        ]
        for msg, exp_asset, exp_amount, exp_recipient in cases:
            r = classify_and_build(msg)
            self.assertEqual(r["intent"], INTENT_SEND_DRAFT, msg)
            self.assertEqual(r["card"]["asset"],  exp_asset,  msg)
            self.assertEqual(r["card"]["amount"], exp_amount, msg)
            if exp_recipient:
                self.assertEqual(
                    r["card"]["recipient"], exp_recipient, msg,
                )


    def test_send_draft_card_can_never_broadcast(self):

        from crypto_vault_chat_control import classify_and_build
        r = classify_and_build(
            "Prepare 5 USDC send to 0x1234567890abcdef1234567890abcdef12345678"
        )
        card = r["card"]
        self.assertFalse(card["canBroadcast"],
            "chat MUST NOT be allowed to broadcast a send")
        self.assertTrue(card["requiresPinUnlock"])
        self.assertTrue(card["requiresTrustedDevice"])
        self.assertTrue(card["requiresLocalSigning"])
        self.assertTrue(card["requiresExplicitConfirmation"])


class SecretMaterialRefusalTests(unittest.TestCase):


    def test_secret_material_requests_are_refused(self):
        from crypto_vault_chat_control import (
            classify_and_build,
            INTENT_REFUSAL_SECRET_MATERIAL,
        )
        for m in [
            "What is my private key?",
            "Show me my seed phrase",
            "Give me the mnemonic",
            "Show my polyseed",
            "Where is my recovery phrase",
            "Show my spend key",
            "Show my view key",
            "What is my encrypted secret",
            "What is my api key",
            "Show my auth token",
            "give me the wallet secret",
        ]:
            r = classify_and_build(m)
            self.assertEqual(
                r["intent"], INTENT_REFUSAL_SECRET_MATERIAL,
                f"failed to refuse: {m!r}",
            )
            self.assertEqual(
                r["card"]["cardType"], "crypto_vault_refusal_card",
            )
            self.assertEqual(
                r["card"]["refusalReason"],
                "secret_material_request",
            )


    def test_refusal_card_never_contains_actual_secret_or_amount(
        self,
    ):

        from crypto_vault_chat_control import classify_and_build
        r = classify_and_build(
            "My private key is 0xdeadbeef1234567890abcdef "
            "and my seed is arm turn gate ..."
        )

        blob = str(r)
        self.assertNotIn("0xdeadbeef1234567890abcdef", blob)
        self.assertNotIn("arm turn gate", blob)


    def test_secret_refusal_beats_send_draft_when_both_present(self):

        from crypto_vault_chat_control import classify_and_build
        r = classify_and_build(
            "Send 5 ETH to 0x1234567890abcdef1234567890abcdef12345678 "
            "using my seed phrase"
        )

        self.assertEqual(
            r["intent"], "crypto_vault_refusal_secret_material",
        )


class ExchangeActionRefusalTests(unittest.TestCase):


    def test_exchange_action_verbs_are_refused(self):
        from crypto_vault_chat_control import (
            classify_and_build,
            INTENT_REFUSAL_EXCHANGE_ACTION,
        )
        cases = [
            "Buy 100 USDC",
            "Buy some ETH",
            "Sell 5 SOL",
            "Swap USDT for USDC",
            "Trade USDT for SOL",
            "Bridge ETH to Solana",
            "Stake ETH",
            "Convert USDT to USDC",
            "Exchange ETH for USDC",
        ]
        for msg in cases:
            r = classify_and_build(msg)
            self.assertEqual(
                r["intent"], INTENT_REFUSAL_EXCHANGE_ACTION,
                f"failed to refuse exchange verb: {msg!r}",
            )
            self.assertEqual(
                r["card"]["refusalReason"],
                "exchange_action_request",
            )


    def test_exchange_refusal_beats_send_draft(self):
        from crypto_vault_chat_control import classify_and_build

        r = classify_and_build(
            "Prepare 10 SOL to swap for USDC"
        )
        self.assertEqual(
            r["intent"], "crypto_vault_refusal_exchange_action",
        )


    def test_word_exchange_alone_is_not_refused_in_legitimate_use(
        self,
    ):

        from crypto_vault_chat_control import classify_and_build
        r = classify_and_build("Show my exchange note")

        self.assertNotEqual(
            r["intent"], "crypto_vault_refusal_exchange_action",
        )


class NoFakeDataInvariants(unittest.TestCase):


    def test_balance_card_never_carries_a_numeric_amount(self):

        from crypto_vault_chat_control import classify_and_build
        r = classify_and_build("What is my ETH balance?")
        self.assertNotIn("availableAmount", r["card"])
        self.assertNotIn("amount", r["card"])
        self.assertNotIn("balance", r["card"])

        self.assertTrue(r["card"]["liveFetchRequired"])


    def test_activity_card_never_carries_transactions_field(self):
        from crypto_vault_chat_control import classify_and_build
        r = classify_and_build("Show my recent crypto activity")
        self.assertNotIn("transactions", r["card"])


    def test_scanner_status_card_never_carries_can_broadcast_true(
        self,
    ):
        from crypto_vault_chat_control import classify_and_build
        r = classify_and_build("Why is Monero balance unavailable?")

        self.assertNotIn("canBroadcast", r["card"])


class ClassifierPurityTests(unittest.TestCase):


    def test_module_source_has_no_forbidden_secret_field_names(self):
        src = (_BACKEND_ROOT / "crypto_vault_chat_control.py"
               ).read_text(encoding="utf-8").lower()
        for banned in (
            "encrypted_wallet_secret",
            "encryptedwalletsecret",
            "private_view_key",
            "private_spend_key",
            "seed_hex",
            "mnemonic_words",
            "auth_token=",
            "api_key=",
        ):
            self.assertNotIn(
                banned, src,
                f"module references forbidden identifier {banned!r}",
            )


    def test_classify_signature_only_takes_a_string(self):

        from crypto_vault_chat_control import classify_and_build
        sig = inspect.signature(classify_and_build)
        params = list(sig.parameters)
        self.assertEqual(params, ["message"],
            "classifier must accept only a chat-message string")


class EndpointRoutingTests(_BaseTest):


    def test_endpoint_returns_intent_and_card_for_a_balance_query(
        self,
    ):
        r = self._client().post(
            _CLASSIFY_PATH, json={"message": "What is my ETH balance?"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["intent"], "crypto_vault_balance")
        self.assertEqual(
            body["card"]["cardType"], "crypto_vault_balance_card",
        )
        self.assertEqual(body["card"]["asset"], "ETH")


    def test_endpoint_returns_refusal_for_seed_phrase_request(self):
        r = self._client().post(
            _CLASSIFY_PATH,
            json={"message": "show me my seed phrase"},
        )
        body = r.json()
        self.assertEqual(
            body["intent"], "crypto_vault_refusal_secret_material",
        )


    def test_endpoint_rejects_empty_message(self):

        r = self._client().post(
            _CLASSIFY_PATH, json={"message": ""},
        )
        self.assertGreaterEqual(r.status_code, 400)


    def test_endpoint_rejects_message_over_2000_chars(self):

        r = self._client().post(
            _CLASSIFY_PATH,
            json={"message": "x" * 2001},
        )
        self.assertGreaterEqual(r.status_code, 400)


    def test_endpoint_requires_trusted_device(self):

        self._app.dependency_overrides.pop(self._dep_key, None)
        try:
            r = self._client().post(
                _CLASSIFY_PATH,
                json={"message": "show my vault"},
            )
            self.assertNotEqual(r.status_code, 200)
        finally:
            self._app.dependency_overrides[self._dep_key] = lambda: {
                "vault_id": "test-vault-uuid",
                "account_id": "test-account",
            }


class EndpointLogSafetyTests(_BaseTest):


    def _capture_log(self, message):
        logger = logging.getLogger("crypto_wallet_routes")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        original_level = logger.level
        original_disabled = logger.disabled
        logger.disabled = False
        logger.setLevel(logging.INFO)
        try:
            self._client().post(
                _CLASSIFY_PATH, json={"message": message},
            )
            handler.flush()
            return stream.getvalue()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original_level)
            logger.disabled = original_disabled


    def test_log_line_does_not_echo_the_message_body(self):

        secret_marker = "ULTRA_SECRET_CANARY_12345"
        log = self._capture_log(
            f"Show my ETH balance {secret_marker}"
        )
        self.assertNotIn(secret_marker, log,
            "the log line MUST NOT echo the raw message body")


    def test_log_line_carries_only_closed_set_fields(self):
        log = self._capture_log("What is my ETH balance?")
        self.assertIn("crypto_vault_chat_classify", log)
        self.assertIn("intent=crypto_vault_balance", log)
        self.assertIn("card_type=crypto_vault_balance_card", log)
        self.assertIn("message_len=", log)


    def test_log_line_never_echos_seed_content_from_a_refused_msg(
        self,
    ):

        canary = "correct horse battery staple"
        log = self._capture_log(
            f"my seed phrase is {canary}"
        )
        self.assertNotIn(canary, log)
        self.assertIn(
            "intent=crypto_vault_refusal_secret_material", log,
        )


if __name__ == "__main__":
    unittest.main()
