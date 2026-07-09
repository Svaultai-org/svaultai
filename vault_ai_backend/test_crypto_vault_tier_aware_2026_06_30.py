

from __future__ import annotations

import inspect
import json
import os
import unittest


os.environ.setdefault("DATABASE_URL", "postgresql://noop:noop@localhost/noop")
os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")

import vault_crypto_locked_card as card_mod              
import vault_crypto_locked_chat as chat_mod              


class TestChatRepliesFreeBasic(unittest.TestCase):

    def _expect_available_with_upgrade(self, msg: str) -> None:
                                                                     
                                        
        self.assertIn("available with upgrade", msg.lower())
                                                                      
                                                                
        for forbidden in (
            "for upgraded users",
            "upgrade required",
            "active in your vault",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, msg.lower(),
                    msg=(
                        f"free/basic chat reply must NOT carry "
                        f"{forbidden!r} — that's upgraded-tier copy"
                    ),
                )

    def test_save_question_free_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save my Bitcoin in my vault",
            user_tier="free",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self._expect_available_with_upgrade(result["message"])

    def test_generic_question_free_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can i use the crypto in my vault",
            user_tier="free",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self._expect_available_with_upgrade(result["message"])

    def test_basic_user_gets_same_copy_as_free(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier="basic",
        )
        self._expect_available_with_upgrade(result["message"])

    def test_unknown_tier_defaults_to_free_copy(self):
                                                                  
                                                              
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier="enterprise_quantum_platinum",
        )
        self._expect_available_with_upgrade(result["message"])

    def test_missing_tier_defaults_to_free_copy(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier=None,
        )
        self._expect_available_with_upgrade(result["message"])


class TestChatRepliesUpgraded(unittest.TestCase):

    def _expect_active_in_vault(self, msg: str) -> None:
                                                                 
        self.assertIn("Crypto Vault Lite is active", msg)
                                                                  
        for forbidden in (
            "available with upgrade",
            "for upgraded users",
            "upgrade required",
            "Upgrade required",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, msg,
                    msg=(
                        f"upgraded chat reply must NOT carry "
                        f"{forbidden!r}"
                    ),
                )

    def test_save_question_upgraded_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save my Bitcoin in my vault",
            user_tier="upgraded",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self._expect_active_in_vault(result["message"])

    def test_generic_question_upgraded_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can i use the crypto in my vault",
            user_tier="upgraded",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
                                                                 
                                                         
        self.assertTrue(result["message"].startswith("Yes."))
        self._expect_active_in_vault(result["message"])

    def test_receive_question_upgraded_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can I receive crypto",
            user_tier="upgraded",
        )
        self._expect_active_in_vault(result["message"])

    def test_buy_question_upgraded_user_keeps_no_buy_disclaimer(self):
                                                                   
                                                                   
        result = chat_mod.route_crypto_question(
            user_message="can I buy crypto here",
            user_tier="upgraded",
        )
        self.assertIn("doesn't buy, sell, or trade", result["message"])
                                            
        self.assertIn(
            "Crypto Vault Lite is active",
            result["message"],
        )


class TestSendRemainsFutureOnly(unittest.TestCase):

    def test_send_reply_same_for_free_and_upgraded(self):
        free_msg = chat_mod.route_crypto_question(
            user_message="can I send Bitcoin",
            user_tier="free",
        )["message"]
        upg_msg = chat_mod.route_crypto_question(
            user_message="can I send Bitcoin",
            user_tier="upgraded",
        )["message"]
                                                                
        self.assertEqual(free_msg, upg_msg)
                                                 
        self.assertIn("Crypto send is not active yet", free_msg)
        self.assertIn("Crypto send is not active yet", upg_msg)


class TestEnvelopeBranchesOnTier(unittest.TestCase):

    def test_free_envelope_shows_locked_card(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_FREE,
        ))
        self.assertEqual(env["status"], "Available with upgrade")
        self.assertTrue(env["locked"])
        secondary = [
            b for b in env["buttons"]
            if b["id"] != card_mod.ACTION_LEARN_MORE
        ]
        self.assertEqual(len(secondary), 1)
        self.assertEqual(secondary[0]["label"], "Upgrade required")
        self.assertEqual(
            secondary[0]["id"], card_mod.ACTION_UPGRADE_REQUIRED,
        )

    def test_basic_envelope_shows_locked_card(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_BASIC,
        ))
        self.assertEqual(env["status"], "Available with upgrade")
        self.assertTrue(env["locked"])

    def test_upgraded_envelope_shows_active_card(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_UPGRADED,
        ))
        self.assertEqual(env["status"], "Active")
        self.assertFalse(env["locked"])
        secondary = [
            b for b in env["buttons"]
            if b["id"] != card_mod.ACTION_LEARN_MORE
        ]
        self.assertEqual(len(secondary), 1)
        self.assertEqual(secondary[0]["label"], "Open Crypto Vault")
        self.assertEqual(
            secondary[0]["id"], card_mod.ACTION_OPEN_CRYPTO_VAULT,
        )

    def test_upgraded_envelope_flips_receive_enabled(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_UPGRADED,
        ))
        self.assertTrue(env["receive_enabled"])
                                                       
        self.assertFalse(env["send_enabled"])
        self.assertFalse(env["wallet_generation_enabled"])
        self.assertFalse(env["trading_enabled"])


class TestMainPyThreadsUserTier(unittest.TestCase):

    def test_chat_endpoint_passes_user_tier_to_route_crypto_question(self):
                                                              
                                                                 
        import main
        src = inspect.getsource(main)
        self.assertIn(
            'user_tier=locals().get("_user_tier", "free")',
            src,
            msg=(
                "main.py's chat handler must pass user_tier into "
                "route_crypto_question so the deflection copy matches "
                "the user's actual tier — the same _user_tier the "
                "secure_item_router already derived from the billing "
                "entitlement."
            ),
        )


if __name__ == "__main__":                    
    unittest.main()
