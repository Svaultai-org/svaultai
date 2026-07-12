"""Wire-shape + copy tests for the Crypto Vault locked / active card.

2026-07-12 refresh: the old "Crypto Vault Lite / save wallet
addresses / seed phrases / send features will come later" copy
described a saved-item vault feature, not the real wallet product
that shipped. Users hitting the non-upgraded chat card thought the
product only stored strings. This suite now enforces the new copy:

  * Non-upgraded users see: "You can't access Crypto Vault on your
    current plan. Upgrade your account to unlock it — Crypto Vault
    is a real, non-custodial wallet…".
  * Upgraded users see:      "Crypto Vault is active. Open it to
    pick a supported asset, use Receive / Send / view balance…".
  * Forbidden legacy fragments (Send features will come later, save
    wallet addresses, seed phrases, Crypto Vault Lite, coming soon)
    must not appear in any surface.
"""

from __future__ import annotations

import importlib
import json
import logging
import unittest

import vault_crypto_locked_card as card_mod
import vault_crypto_locked_chat as chat_mod


LEGACY_STALE_FRAGMENTS: tuple[str, ...] = (
    "send features will come later",
    "save wallet addresses",
    "seed phrases",
    "private keys",
    "transaction records",
    "crypto vault lite",
    "coming soon",
    "receive and send features will come later",
)


class TestLockedCardWireShape(unittest.TestCase):
    def test_envelope_type_and_schema_version(self):
        payload = json.loads(card_mod.build_crypto_locked_envelope())
        self.assertEqual(
            payload["type"], card_mod.TYPE_CRYPTO_VAULT_LOCKED,
        )
        self.assertEqual(payload["type"], "crypto_vault_locked")
        self.assertEqual(
            payload["schema_version"], card_mod.SCHEMA_VERSION,
        )

    def test_title_is_crypto_vault(self):
        payload = json.loads(card_mod.build_crypto_locked_envelope())
        self.assertEqual(payload["title"], "Crypto Vault")
        self.assertEqual(card_mod.CARD_TITLE, "Crypto Vault")

    def test_status_reads_upgrade_required_for_non_upgraded(self):
        payload = json.loads(card_mod.build_crypto_locked_envelope())
        self.assertEqual(payload["status"], "Upgrade required")
        self.assertEqual(card_mod.CARD_STATUS, "Upgrade required")

    def test_body_uses_new_wallet_copy_and_drops_legacy(self):
        payload = json.loads(card_mod.build_crypto_locked_envelope())
        body = payload["body"]
        low = body.lower()
        for fragment in (
            "non-custodial wallet",
            "receive",
            "send",
            "balance",
            "upgrade",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, low)
        for legacy in LEGACY_STALE_FRAGMENTS:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, low)

    def test_card_carries_exactly_two_buttons(self):
        payload = json.loads(card_mod.build_crypto_locked_envelope())
        self.assertEqual(len(payload["buttons"]), 2)
        ids = [b["id"] for b in payload["buttons"]]
        labels = [b["label"] for b in payload["buttons"]]
        self.assertIn(card_mod.ACTION_LEARN_MORE, ids)
        self.assertIn(card_mod.ACTION_UPGRADE_REQUIRED, ids)
        self.assertIn("Learn more", labels)
        self.assertIn("Upgrade required", labels)


class TestLockedAcrossTiers(unittest.TestCase):

    def test_free_user_sees_locked_card(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_FREE,
        ))
        self.assertTrue(env["locked"])
        self.assertFalse(env["send_enabled"])
        self.assertFalse(env["receive_enabled"])
        self.assertFalse(env["wallet_generation_enabled"])
        self.assertFalse(env["trading_enabled"])
        self.assertEqual(env["tier"], "free")

    def test_basic_user_sees_locked_card(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_BASIC,
        ))
        self.assertTrue(env["locked"])
        self.assertFalse(env["send_enabled"])
        self.assertEqual(env["tier"], "basic")

    def test_upgraded_user_card_renders_active_with_new_copy(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_UPGRADED,
        ))
        self.assertFalse(
            env["locked"],
            msg="upgraded users must NOT see the locked card",
        )
        # 2026-07-12: real wallet product — receive, send, and
        # wallet generation are all live on the upgraded plan.
        # Backend routes are authoritatively gated by
        # require_crypto_entitlement so exposing these flags is safe.
        self.assertTrue(env["send_enabled"])
        self.assertTrue(env["receive_enabled"])
        self.assertTrue(env["wallet_generation_enabled"])
        self.assertFalse(env["trading_enabled"])
        self.assertEqual(env["status"], "Active")
        self.assertEqual(env["tier"], "upgraded")
        secondary_labels = [
            b["label"] for b in env["buttons"]
            if b["id"] != card_mod.ACTION_LEARN_MORE
        ]
        self.assertEqual(secondary_labels, ["Open Crypto Vault"])

        low = env["body"].lower()
        for fragment in (
            "active on your account",
            "open",
            "receive",
            "send",
            "balance",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, low)
        for legacy in LEGACY_STALE_FRAGMENTS:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, low)

    def test_unknown_tier_falls_back_to_free(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier="enterprise_platinum_quantum",
        ))
        self.assertEqual(env["tier"], "free")
        self.assertTrue(env["locked"])

    def test_missing_tier_falls_back_to_free(self):
        env = json.loads(card_mod.build_crypto_locked_envelope())
        self.assertEqual(env["tier"], "free")


class TestChatDeflectionRouting(unittest.TestCase):
    def test_save_question_routes_to_save_intent(self):
        for phrase in (
            "Can I save crypto in my vault?",
            "Can I store my Bitcoin in VaultAI?",
            "How do I save my seed phrase?",
            "Can I keep my Ethereum wallet here?",
        ):
            with self.subTest(phrase=phrase):
                intent = chat_mod.classify_crypto_question(phrase)
                self.assertEqual(
                    intent, chat_mod.INTENT_CRYPTO_SAVE_QUESTION,
                )

    def test_send_question_routes_to_send_intent(self):
        for phrase in (
            "Can I send crypto?",
            "How do I send Bitcoin?",
            "Can I transfer ETH to a friend?",
            "I want to withdraw my crypto",
        ):
            with self.subTest(phrase=phrase):
                intent = chat_mod.classify_crypto_question(phrase)
                self.assertEqual(
                    intent, chat_mod.INTENT_CRYPTO_SEND_QUESTION,
                )

    def test_receive_question_routes_to_receive_intent(self):
        for phrase in (
            "Can I receive crypto?",
            "Can I get a deposit address for Bitcoin?",
            "How do I receive ETH here?",
        ):
            with self.subTest(phrase=phrase):
                intent = chat_mod.classify_crypto_question(phrase)
                self.assertEqual(
                    intent, chat_mod.INTENT_CRYPTO_RECEIVE_QUESTION,
                )

    def test_buy_sell_trade_routes_to_buy_intent(self):
        for phrase in (
            "Can I buy crypto?",
            "Can I sell my Bitcoin?",
            "Can I trade ETH for USDC?",
            "Does VaultAI exchange crypto?",
            "Is VaultAI a crypto exchange?",
            "Can I swap my crypto here?",
        ):
            with self.subTest(phrase=phrase):
                intent = chat_mod.classify_crypto_question(phrase)
                self.assertEqual(
                    intent, chat_mod.INTENT_CRYPTO_BUY_QUESTION,
                )

    def test_generic_crypto_question_falls_back_to_generic(self):
        intent = chat_mod.classify_crypto_question(
            "Can VaultAI do crypto?",
        )
        self.assertEqual(
            intent, chat_mod.INTENT_CRYPTO_GENERIC_QUESTION,
        )

    def test_unrelated_messages_return_none(self):
        for phrase in (
            "save my Netflix login",
            "show my IMEI",
            "what's the weather today",
            "great, what more can you do",
            "",
            None,
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    chat_mod.classify_crypto_question(phrase),
                    chat_mod.INTENT_NONE,
                )


class TestDeflectionReplies(unittest.TestCase):

    def _assert_no_legacy(self, message: str):
        low = message.lower()
        for legacy in LEGACY_STALE_FRAGMENTS:
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, low)

    def test_save_reply_offers_upgrade_and_wallet_language(self):
        result = chat_mod.route_crypto_question(
            user_message="Can I save crypto in my vault?",
            user_tier="free",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertEqual(
            result["message"], chat_mod.MESSAGE_CRYPTO_SAVE,
        )
        low = result["message"].lower()
        for fragment in (
            "can't access crypto vault",
            "upgrade",
            "non-custodial wallet",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, low)
        self._assert_no_legacy(result["message"])

    def test_send_reply_non_upgraded_requires_upgrade(self):
        result = chat_mod.route_crypto_question(
            user_message="Can I send crypto?",
            user_tier="free",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertEqual(
            result["message"], chat_mod.MESSAGE_CRYPTO_SEND,
        )
        low = result["message"].lower()
        self.assertIn("upgrade", low)
        self.assertIn("send", low)
        self.assertIn("pin", low)
        self._assert_no_legacy(result["message"])

    def test_send_reply_upgraded_describes_real_send_flow(self):
        result = chat_mod.route_crypto_question(
            user_message="Can I send crypto?",
            user_tier="upgraded",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertEqual(
            result["message"], chat_mod.MESSAGE_CRYPTO_SEND_UPGRADED,
        )
        low = result["message"].lower()
        self.assertIn("open crypto vault", low)
        self.assertIn("recipient", low)
        self.assertIn("pin", low)
        self._assert_no_legacy(result["message"])

    def test_receive_reply_confirms_receive_flow(self):
        result_free = chat_mod.route_crypto_question(
            user_message="Can I receive crypto?",
            user_tier="free",
        )
        self.assertEqual(
            result_free["band"], chat_mod.BAND_DEFLECTED,
        )
        low_free = result_free["message"].lower()
        self.assertIn("can't access crypto vault", low_free)
        self.assertIn("upgrade", low_free)
        self._assert_no_legacy(result_free["message"])

        result_up = chat_mod.route_crypto_question(
            user_message="Can I receive crypto?",
            user_tier="upgraded",
        )
        low_up = result_up["message"].lower()
        self.assertIn("open crypto vault", low_up)
        self.assertIn("qr code", low_up)
        self.assertIn("non-custodial", low_up)
        self._assert_no_legacy(result_up["message"])

    def test_buy_reply_disclaims_exchange_and_trading(self):
        result = chat_mod.route_crypto_question(
            user_message="Can I buy crypto?",
            user_tier="free",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertIn(
            "doesn't buy, sell, or trade crypto", result["message"],
        )
        self._assert_no_legacy(result["message"])

    def test_generic_reply_non_upgraded_requires_upgrade(self):
        # 2026-07-12 core bug fixture: these are the exact prompts
        # users sent and got the stale Lite copy back. Prompts like
        # "do i have crypto vault" match the router's SHOW_VAULT
        # regex directly at the router level and never reach this
        # deflector; the router-level normalization covers them (see
        # test_logins_and_crypto_2026_07_12.py).
        for phrase in (
            "can i use the crypto",
            "can i access crypto vault",
            "can i use crypto vault",
        ):
            with self.subTest(phrase=phrase):
                result = chat_mod.route_crypto_question(
                    user_message=phrase,
                    user_tier="free",
                )
                self.assertEqual(
                    result["band"], chat_mod.BAND_DEFLECTED,
                )
                self.assertEqual(
                    result["message"],
                    chat_mod.MESSAGE_CRYPTO_GENERIC,
                )
                low = result["message"].lower()
                self.assertIn("can't access crypto vault", low)
                self.assertIn("upgrade", low)
                self.assertIn("non-custodial wallet", low)
                self._assert_no_legacy(result["message"])

    def test_generic_reply_upgraded_describes_real_wallet(self):
        result = chat_mod.route_crypto_question(
            user_message="can i use the crypto",
            user_tier="upgraded",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertEqual(
            result["message"],
            chat_mod.MESSAGE_CRYPTO_GENERIC_UPGRADED,
        )
        low = result["message"].lower()
        for fragment in (
            "yes",
            "open crypto vault",
            "receive",
            "send",
            "balance",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, low)
        self._assert_no_legacy(result["message"])


class TestAntiClaimGuardrails(unittest.TestCase):

    _FORBIDDEN = (
        "you can send",
        "you can receive",
        "you can buy",
        "you can sell",
        "you can trade",
        "you can swap",
        "you can exchange",
        "guaranteed",
        "profit",
        "high return",
        "high returns",
        "investment return",
        "make money",
        "double your",
        "triple your",
        "10x",
        "100x",
        "moon",
        "to the moon",
        "we are an exchange",
        "we sell crypto",
        "we trade",
        "vaultai is an exchange",
        "vaultai sells",
        "vaultai is a broker",
    )

    def _check(self, text: str) -> None:
        lower = text.lower()
        for needle in self._FORBIDDEN:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, lower)

    def test_card_body_has_no_claims(self):
        for tier in ("free", "basic", "upgraded"):
            env = json.loads(card_mod.build_crypto_locked_envelope(
                user_tier=tier,
            ))
            self._check(env["body"])
            self._check(env["status"])

    def test_save_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_SAVE)
        self._check(chat_mod.MESSAGE_CRYPTO_SAVE_UPGRADED)

    def test_send_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_SEND)
        self._check(chat_mod.MESSAGE_CRYPTO_SEND_UPGRADED)

    def test_receive_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_RECEIVE)
        self._check(chat_mod.MESSAGE_CRYPTO_RECEIVE_UPGRADED)

    def test_buy_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_BUY)
        self._check(chat_mod.MESSAGE_CRYPTO_BUY_UPGRADED)

    def test_generic_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_GENERIC)
        self._check(chat_mod.MESSAGE_CRYPTO_GENERIC_UPGRADED)


class TestNoTransactionCodeAdded(unittest.TestCase):

    _FORBIDDEN_IMPORTS = (
        "web3", "eth_account", "ecdsa",
        "secp256k1", "coincurve",
        "bitcoinlib", "bitcoin",
        "solana", "ethers",
        "hashlib_signing",
    )

    _FORBIDDEN_NAMES = (
        "sign_transaction", "broadcast_transaction",
        "submit_transaction", "send_transaction",
        "create_wallet", "generate_wallet", "generate_seed_phrase",
        "generate_private_key", "derive_address",
        "post_to_blockchain", "post_to_network",
        "rpc_node", "rpc_endpoint", "rpc_url",
    )

    def _read(self, mod) -> str:
        with open(mod.__file__, encoding="utf-8") as f:
            return f.read()

    def test_card_module_imports_no_crypto_libraries(self):
        src = self._read(card_mod)
        for needle in self._FORBIDDEN_IMPORTS:
            with self.subTest(needle=needle):
                self.assertNotIn(needle, src.lower())

    def test_chat_module_imports_no_crypto_libraries(self):
        src = self._read(chat_mod)
        for needle in self._FORBIDDEN_IMPORTS:
            with self.subTest(needle=needle):
                self.assertNotIn(f"import {needle}", src)
                self.assertNotIn(f"from {needle}", src)

    def test_modules_expose_no_signing_or_broadcast_names(self):
        for mod in (card_mod, chat_mod):
            src = self._read(mod)
            for needle in self._FORBIDDEN_NAMES:
                with self.subTest(mod=mod.__name__, needle=needle):
                    self.assertNotIn(needle, src)


class TestCryptoDeflectionPrivacy(unittest.TestCase):

    def test_route_logs_carry_no_user_text(self):
        records: list[logging.LogRecord] = []

        class _Sink(logging.Handler):
            def emit(self, record):
                records.append(record)

        sink = _Sink(level=logging.DEBUG)
        sink.setLevel(logging.DEBUG)
        log_names = (
            "vault_crypto_locked_chat",
            "vault_crypto_locked_card",
        )
        for name in log_names:
            log = logging.getLogger(name)
            log.addHandler(sink)
            log.setLevel(logging.DEBUG)
        try:
            for msg in (
                "Can I send 0xDEADBEEF Bitcoin to my ex-roommate?",
                "Can I save my seed phrase mountain river apple river?",
                "How do I buy 12 ETH using my secret bank login?",
            ):
                chat_mod.route_crypto_question(user_message=msg)
            for tier in ("free", "basic", "upgraded"):
                card_mod.build_crypto_locked_envelope(user_tier=tier)
        finally:
            for name in log_names:
                logging.getLogger(name).removeHandler(sink)

        joined = "\n".join(r.getMessage() for r in records)
        for forbidden in (
            "0xDEADBEEF",
            "ex-roommate",
            "mountain river apple",
            "secret bank login",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, joined)


if __name__ == "__main__":
    unittest.main()
