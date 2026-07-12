"""Copy refresh test — updated 2026-07-12 to the real wallet product.

The previous version of this file was written when Crypto Vault
was still marketed as "Crypto Vault Lite" and described as a
saved-item store for wallet addresses, seed phrases, notes, etc.
That copy is now obsolete: Crypto Vault is a real, non-custodial
wallet with receive, send, and balance tracking on supported
networks. This test file enforces the new copy across every user-
facing crypto surface and forbids the legacy fragments.
"""

from __future__ import annotations

import unittest

import vault_crypto_locked_card as card_mod
import vault_crypto_locked_chat as chat_mod
import vault_secure_item_save as vsi


_FORBIDDEN_LEGACY: tuple[str, ...] = (
    "crypto vault is coming soon",
    "coming soon for upgraded users",
    "receive and send features will come later",
    "send features will come later",
    "save wallet addresses",
    "crypto vault lite",
    "wallet notes",
    "transaction records",
    "seed phrases",
    "private keys",
)


class TestLockedCardCopyRefreshed(unittest.TestCase):

    def test_card_status_reads_upgrade_required(self):
        self.assertEqual(card_mod.CARD_STATUS, "Upgrade required")
        self.assertEqual(card_mod.CARD_STATUS_ACTIVE, "Active")

    def test_locked_card_body_describes_real_wallet_and_upgrade(self):
        body = card_mod.CARD_BODY.lower()
        self.assertIn("non-custodial wallet", body)
        self.assertIn("receive", body)
        self.assertIn("send", body)
        self.assertIn("balance", body)
        self.assertIn("upgrade", body)

    def test_active_card_body_names_receive_send_balance(self):
        body = card_mod.CARD_BODY_ACTIVE.lower()
        self.assertIn("active on your account", body)
        self.assertIn("receive", body)
        self.assertIn("send", body)
        self.assertIn("balance", body)

    def test_card_module_has_no_forbidden_legacy_strings(self):
        for text_name, text in (
            ("CARD_STATUS", card_mod.CARD_STATUS.lower()),
            ("CARD_BODY", card_mod.CARD_BODY.lower()),
            ("CARD_BODY_ACTIVE", card_mod.CARD_BODY_ACTIVE.lower()),
        ):
            for forbidden in _FORBIDDEN_LEGACY:
                with self.subTest(surface=text_name, forbidden=forbidden):
                    self.assertNotIn(forbidden, text)


class TestChatDeflectionRepliesRefreshed(unittest.TestCase):

    _DEFLECTION_REPLIES = (
        "MESSAGE_CRYPTO_SAVE",
        "MESSAGE_CRYPTO_SAVE_UPGRADED",
        "MESSAGE_CRYPTO_SEND",
        "MESSAGE_CRYPTO_SEND_UPGRADED",
        "MESSAGE_CRYPTO_RECEIVE",
        "MESSAGE_CRYPTO_RECEIVE_UPGRADED",
        "MESSAGE_CRYPTO_BUY",
        "MESSAGE_CRYPTO_BUY_UPGRADED",
        "MESSAGE_CRYPTO_GENERIC",
        "MESSAGE_CRYPTO_GENERIC_UPGRADED",
    )

    def test_non_upgraded_replies_require_upgrade(self):
        for name in (
            "MESSAGE_CRYPTO_SAVE",
            "MESSAGE_CRYPTO_SEND",
            "MESSAGE_CRYPTO_RECEIVE",
            "MESSAGE_CRYPTO_GENERIC",
        ):
            msg = getattr(chat_mod, name).lower()
            with self.subTest(reply=name):
                self.assertIn("upgrade", msg)

    def test_upgraded_replies_describe_the_real_wallet_flow(self):
        # SAVE_UPGRADED talks about opening + receive + send
        for name in (
            "MESSAGE_CRYPTO_SAVE_UPGRADED",
            "MESSAGE_CRYPTO_RECEIVE_UPGRADED",
            "MESSAGE_CRYPTO_SEND_UPGRADED",
            "MESSAGE_CRYPTO_GENERIC_UPGRADED",
        ):
            msg = getattr(chat_mod, name).lower()
            with self.subTest(reply=name):
                self.assertIn("open crypto vault", msg)

    def test_buy_reply_disclaims_trading_at_both_tiers(self):
        for name in ("MESSAGE_CRYPTO_BUY", "MESSAGE_CRYPTO_BUY_UPGRADED"):
            msg = getattr(chat_mod, name).lower()
            with self.subTest(reply=name):
                self.assertIn("doesn't buy, sell, or trade crypto", msg)

    def test_no_deflection_reply_carries_forbidden_legacy_strings(self):
        for name in self._DEFLECTION_REPLIES:
            msg = getattr(chat_mod, name).lower()
            for forbidden in _FORBIDDEN_LEGACY:
                with self.subTest(reply=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, msg)


class TestTierGateReplyRefreshed(unittest.TestCase):

    def test_tier_gate_message_points_to_the_real_wallet(self):
        msg = vsi._TIER_REQUIRED_MESSAGE.lower()
        self.assertIn("upgrade", msg)
        self.assertIn("non-custodial wallet", msg)

    def test_tier_gate_message_has_no_forbidden_legacy_strings(self):
        msg = vsi._TIER_REQUIRED_MESSAGE.lower()
        for forbidden in _FORBIDDEN_LEGACY:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, msg)


class TestAntiClaimGuardrailsStillHold(unittest.TestCase):

    _FORBIDDEN_ACTIVE_CLAIMS = (
        "you can send",
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
        "to the moon",
        "we are an exchange",
        "vaultai is an exchange",
        "vaultai sells",
        "vaultai is a broker",
    )

    _SURFACES = (
        ("card_status",             lambda: card_mod.CARD_STATUS),
        ("card_status_active",      lambda: card_mod.CARD_STATUS_ACTIVE),
        ("card_body",               lambda: card_mod.CARD_BODY),
        ("card_body_active",        lambda: card_mod.CARD_BODY_ACTIVE),
        ("save_reply",              lambda: chat_mod.MESSAGE_CRYPTO_SAVE),
        ("save_reply_up",           lambda: chat_mod.MESSAGE_CRYPTO_SAVE_UPGRADED),
        ("send_reply",              lambda: chat_mod.MESSAGE_CRYPTO_SEND),
        ("send_reply_up",           lambda: chat_mod.MESSAGE_CRYPTO_SEND_UPGRADED),
        ("receive_reply",           lambda: chat_mod.MESSAGE_CRYPTO_RECEIVE),
        ("receive_reply_up",        lambda: chat_mod.MESSAGE_CRYPTO_RECEIVE_UPGRADED),
        ("buy_reply",               lambda: chat_mod.MESSAGE_CRYPTO_BUY),
        ("buy_reply_up",            lambda: chat_mod.MESSAGE_CRYPTO_BUY_UPGRADED),
        ("generic_reply",           lambda: chat_mod.MESSAGE_CRYPTO_GENERIC),
        ("generic_reply_up",        lambda: chat_mod.MESSAGE_CRYPTO_GENERIC_UPGRADED),
        ("tier_gate_message",       lambda: vsi._TIER_REQUIRED_MESSAGE),
    )

    def test_no_surface_carries_a_forbidden_active_claim(self):
        for surface_name, getter in self._SURFACES:
            text = getter().lower()
            for needle in self._FORBIDDEN_ACTIVE_CLAIMS:
                with self.subTest(surface=surface_name, needle=needle):
                    self.assertNotIn(
                        needle, text,
                        msg=(
                            f"{surface_name} must NEVER carry "
                            f"the forbidden claim {needle!r}"
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
