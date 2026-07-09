

from __future__ import annotations

import os
import unittest


os.environ.setdefault("DATABASE_URL", "postgresql://noop:noop@localhost/noop")
os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")

import vault_crypto_locked_chat as chat_mod              


class TestLoadingStateConstants(unittest.TestCase):

    def test_checking_access_message_is_operator_pinned(self):
                                         
        self.assertEqual(
            chat_mod.MESSAGE_CRYPTO_CHECKING_ACCESS,
            "I'm checking your Crypto Vault access. Try again "
            "in a moment.",
        )

    def test_tier_unknown_label_is_closed_set(self):
        self.assertEqual(chat_mod.TIER_UNKNOWN_LABEL, "unknown")

    def test_checking_access_message_avoids_upgrade_wording(self):
        msg = chat_mod.MESSAGE_CRYPTO_CHECKING_ACCESS.lower()
        for forbidden in (
            "upgrade required",
            "available with upgrade",
            "for upgraded users",
            "active",
            "lite is active",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, msg,
                    msg=(
                        f"checking-access reply must NOT carry "
                        f"{forbidden!r} — the wording is neutral by "
                        f"design."
                    ),
                )


class TestUnknownTierRoutesToCheckingAccess(unittest.TestCase):

    _PROMPTS = (
        ("can I save my Bitcoin in my vault",  "save"),
        ("can I receive crypto here",          "receive"),
        ("can I buy crypto",                   "buy"),
        ("can i use the crypto in my vault",   "generic"),
    )

    def test_every_question_routes_to_checking_access_for_unknown(self):
        for (prompt, label) in self._PROMPTS:
            with self.subTest(label=label):
                result = chat_mod.route_crypto_question(
                    user_message=prompt,
                    user_tier=chat_mod.TIER_UNKNOWN_LABEL,
                )
                self.assertEqual(
                    result["band"], chat_mod.BAND_DEFLECTED,
                )
                self.assertEqual(
                    result["message"],
                    chat_mod.MESSAGE_CRYPTO_CHECKING_ACCESS,
                )

    def test_unknown_reply_never_carries_forbidden_wording(self):
        for (prompt, label) in self._PROMPTS:
            with self.subTest(label=label):
                result = chat_mod.route_crypto_question(
                    user_message=prompt,
                    user_tier=chat_mod.TIER_UNKNOWN_LABEL,
                )
                lower = result["message"].lower()
                for forbidden in (
                    "upgrade required",
                    "available with upgrade",
                    "for upgraded users",
                    "lite is active",
                ):
                    self.assertNotIn(
                        forbidden, lower,
                        msg=(
                            f"unknown-tier reply for {label} must not "
                            f"carry {forbidden!r}"
                        ),
                    )


class TestSendStaysFutureOnly(unittest.TestCase):

    def test_send_reply_same_for_unknown_and_free(self):
        unknown_msg = chat_mod.route_crypto_question(
            user_message="can I send Bitcoin",
            user_tier=chat_mod.TIER_UNKNOWN_LABEL,
        )["message"]
        free_msg = chat_mod.route_crypto_question(
            user_message="can I send Bitcoin",
            user_tier=chat_mod.TIER_FREE_LABEL,
        )["message"]
        self.assertEqual(unknown_msg, free_msg)
                                                          
        self.assertEqual(unknown_msg, chat_mod.MESSAGE_CRYPTO_SEND)


class TestResolvedTiersUnchanged(unittest.TestCase):

    def test_free_tier_keeps_available_with_upgrade(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier=chat_mod.TIER_FREE_LABEL,
        )
        self.assertIn(
            "Crypto Vault is available with upgrade",
            result["message"],
        )

    def test_basic_tier_keeps_available_with_upgrade(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier=chat_mod.TIER_BASIC_LABEL,
        )
        self.assertIn(
            "Crypto Vault is available with upgrade",
            result["message"],
        )

    def test_upgraded_tier_keeps_active_wording(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier=chat_mod.TIER_UPGRADED_LABEL,
        )
        self.assertIn(
            "Crypto Vault Lite is active",
            result["message"],
        )

    def test_implicit_none_tier_still_defaults_to_free(self):
                                                                  
                                                                  
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier=None,
        )
        self.assertIn(
            "Crypto Vault is available with upgrade",
            result["message"],
        )


if __name__ == "__main__":                    
    unittest.main()
