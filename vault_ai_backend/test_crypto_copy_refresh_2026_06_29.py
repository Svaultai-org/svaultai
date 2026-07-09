

from __future__ import annotations

import unittest

import vault_crypto_locked_card as card_mod
import vault_crypto_locked_chat as chat_mod
import vault_secure_item_save as vsi


_FORBIDDEN_LEGACY: tuple[str, ...] = (
    "Crypto Vault is coming soon",
    "Coming soon for upgraded users",
    "coming soon for upgraded users",
    "Receive and send features will come later",
    "receive and send features will come later",
                                                                  
                                                    
    "Crypto Vault is coming for upgraded users",
)


_REQUIRED_NEW_FRAGMENTS = {
    "card_status": "Available with upgrade",
    "card_body":   "receive QR codes",
    "save_reply":  "Crypto Vault is available with upgrade",
    "generic_reply": "Send features will come later",
    "tier_required": "Crypto Vault is available with upgrade",
}


class TestLockedCardCopyRefreshed(unittest.TestCase):

    def test_card_status_reads_available_with_upgrade(self):
        self.assertEqual(
            card_mod.CARD_STATUS, "Available with upgrade",
        )

    def test_card_body_lists_receive_qr_and_send_only_future(self):
        body = card_mod.CARD_BODY
        self.assertIn("receive QR codes", body)
        self.assertIn("Send features will come later", body)

    def test_card_module_has_no_forbidden_legacy_strings(self):
        for forbidden in _FORBIDDEN_LEGACY:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, card_mod.CARD_STATUS)
                self.assertNotIn(forbidden, card_mod.CARD_BODY)


class TestChatDeflectionRepliesRefreshed(unittest.TestCase):

    _DEFLECTION_REPLIES = (
        "MESSAGE_CRYPTO_SAVE",
        "MESSAGE_CRYPTO_RECEIVE",
        "MESSAGE_CRYPTO_BUY",
        "MESSAGE_CRYPTO_GENERIC",
    )

    def test_save_reply_confirms_availability_and_names_receive_qr(self):
        msg = chat_mod.MESSAGE_CRYPTO_SAVE
        self.assertIn(
            "Crypto Vault is available with upgrade", msg,
        )
        self.assertIn("receive QR codes", msg)
        self.assertIn("Send features will come later", msg)

    def test_generic_reply_confirms_availability_and_names_receive_qr(self):
        msg = chat_mod.MESSAGE_CRYPTO_GENERIC
        self.assertIn(
            "Crypto Vault is available with upgrade", msg,
        )
        self.assertIn("receive QR codes", msg)
        self.assertIn("Send features will come later", msg)

    def test_receive_reply_confirms_receive_qr_is_available(self):
        msg = chat_mod.MESSAGE_CRYPTO_RECEIVE
        self.assertIn(
            "Crypto Vault is available with upgrade", msg,
        )
        self.assertIn("receive QR code", msg)
        self.assertNotIn("not active yet", msg)

    def test_buy_reply_disclaims_trading_and_names_what_is_available(self):
        msg = chat_mod.MESSAGE_CRYPTO_BUY
        self.assertIn("doesn't buy, sell, or trade crypto", msg)
        self.assertIn("available with upgrade", msg)
        self.assertIn("receive QR codes", msg)

    def test_send_reply_remains_pinned_as_future_only(self):
                                                              
                                                  
        msg = chat_mod.MESSAGE_CRYPTO_SEND
        self.assertIn("Crypto send is not active yet", msg)

    def test_no_deflection_reply_carries_forbidden_legacy_strings(self):
        for name in self._DEFLECTION_REPLIES:
            msg = getattr(chat_mod, name)
            for forbidden in _FORBIDDEN_LEGACY:
                with self.subTest(reply=name, forbidden=forbidden):
                    self.assertNotIn(
                        forbidden, msg,
                        msg=(
                            f"{name} must NOT carry the legacy "
                            f"phrase {forbidden!r}"
                        ),
                    )


class TestTierGateReplyRefreshed(unittest.TestCase):

    def test_tier_gate_message_confirms_availability(self):
        msg = vsi._TIER_REQUIRED_MESSAGE
        self.assertIn(
            "Crypto Vault is available with upgrade", msg,
        )
        self.assertIn("receive QR codes", msg)
        self.assertIn("Send features will come later", msg)

    def test_tier_gate_message_has_no_forbidden_legacy_strings(self):
        msg = vsi._TIER_REQUIRED_MESSAGE
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
        ("card_status",       lambda: card_mod.CARD_STATUS),
        ("card_body",         lambda: card_mod.CARD_BODY),
        ("save_reply",        lambda: chat_mod.MESSAGE_CRYPTO_SAVE),
        ("send_reply",        lambda: chat_mod.MESSAGE_CRYPTO_SEND),
        ("receive_reply",     lambda: chat_mod.MESSAGE_CRYPTO_RECEIVE),
        ("buy_reply",         lambda: chat_mod.MESSAGE_CRYPTO_BUY),
        ("generic_reply",     lambda: chat_mod.MESSAGE_CRYPTO_GENERIC),
        ("tier_gate_message", lambda: vsi._TIER_REQUIRED_MESSAGE),
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
