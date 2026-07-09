

from __future__ import annotations

import importlib
import json
import logging
import re
import unittest

import vault_crypto_locked_card as card_mod
import vault_crypto_locked_chat as chat_mod


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

    def test_status_reads_available_with_upgrade(self):
                                                                    
                                                                   
        payload = json.loads(card_mod.build_crypto_locked_envelope())
        self.assertEqual(payload["status"], "Available with upgrade")
        self.assertEqual(card_mod.CARD_STATUS, "Available with upgrade")
                                                                   
        self.assertNotIn("Coming soon", card_mod.CARD_STATUS)

    def test_body_carries_operator_pinned_storage_list(self):
                                                               
                                                                 
        payload = json.loads(card_mod.build_crypto_locked_envelope())
        body = payload["body"]
        for fragment in (
            "Save wallet addresses",
            "crypto notes",
            "seed phrases",
            "private keys",
            "transaction records",
            "receive QR codes",
            "Send features will come later",
            "extra protection",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, body)
                                                                   
                                                
        self.assertNotIn("Coming soon", body)
        self.assertNotIn("Receive and send features will come later", body)

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

    def test_upgraded_user_card_renders_active(self):
                                                             
                                                                    
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_UPGRADED,
        ))
        self.assertFalse(
            env["locked"],
            msg="upgraded users must NOT see the locked card",
        )
        self.assertFalse(env["send_enabled"])
        self.assertTrue(env["receive_enabled"])
        self.assertFalse(env["wallet_generation_enabled"])
        self.assertFalse(env["trading_enabled"])
        self.assertEqual(env["status"], "Active")
        self.assertEqual(env["tier"], "upgraded")
                                                            
                                                      
        secondary_labels = [
            b["label"] for b in env["buttons"]
            if b["id"] != card_mod.ACTION_LEARN_MORE
        ]
        self.assertEqual(secondary_labels, ["Open Crypto Vault"])

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
        self.assertEqual(intent, chat_mod.INTENT_CRYPTO_GENERIC_QUESTION)

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


    def test_save_reply_is_operator_pinned(self):
                                                                 
                                                                 
        result = chat_mod.route_crypto_question(
            user_message="Can I save crypto in my vault?",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertEqual(
            result["message"], chat_mod.MESSAGE_CRYPTO_SAVE,
        )
        for fragment in (
            "Crypto Vault is available with upgrade",
            "save wallet addresses",
            "crypto notes",
            "seed phrases",
            "private keys",
            "transaction records",
            "receive QR codes",
            "Send features will come later",
            "extra protection",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, result["message"])
                                                                   
        self.assertNotIn("coming soon", result["message"].lower())
        self.assertNotIn(
            "Receive and send features will come later",
            result["message"],
        )

    def test_send_reply_is_operator_pinned(self):
        result = chat_mod.route_crypto_question(
            user_message="Can I send crypto?",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertEqual(
            result["message"], chat_mod.MESSAGE_CRYPTO_SEND,
        )
        self.assertIn("Crypto send is not active yet", result["message"])
        self.assertIn("extra protection", result["message"])

    def test_receive_reply_confirms_receive_qr_is_available(self):
                                                           
                                                                
        result = chat_mod.route_crypto_question(
            user_message="Can I receive crypto?",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertIn(
            "Crypto Vault is available with upgrade",
            result["message"],
        )
        self.assertIn("receive QR code", result["message"])
        self.assertNotIn("not active yet", result["message"])
        self.assertNotIn("coming soon", result["message"].lower())

    def test_buy_reply_disclaims_exchange_and_trading(self):
        result = chat_mod.route_crypto_question(
            user_message="Can I buy crypto?",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertIn("doesn't buy, sell, or trade crypto", result["message"])


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
        env = json.loads(card_mod.build_crypto_locked_envelope())
        self._check(env["body"])
        self._check(env["status"])

    def test_save_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_SAVE)

    def test_send_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_SEND)

    def test_receive_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_RECEIVE)

    def test_buy_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_BUY)

    def test_generic_reply_has_no_claims(self):
        self._check(chat_mod.MESSAGE_CRYPTO_GENERIC)


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
                                                                 
                                                                   
                self.assertNotIn(
                    f"import {needle}", src,
                )
                self.assertNotIn(
                    f"from {needle}", src,
                )

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
            for tier in (
                "free", "basic", "upgraded",
            ):
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
