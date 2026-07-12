"""Tier-aware chat deflection copy — refreshed 2026-07-12.

Before 2026-07-12 non-upgraded users saw an "Available with upgrade"
band that then described the product as a saved-item store for
wallet addresses, seed phrases, notes, and transaction records —
copy from the old Crypto Vault Lite era. The real product is a
non-custodial wallet with receive, send, and balance tracking.

This suite enforces the new tiered copy:

  * free / basic / unknown user → "You can't access Crypto Vault"
    + upgrade prompt + wallet-product framing (no legacy fragments)
  * upgraded user → "Crypto Vault is a real, non-custodial wallet
    on your account" + open + receive + send + balance instructions
  * Send response mirrors the tier — the old suite treated Send
    as "future only" for both tiers; that is no longer correct.
"""

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


LEGACY_FRAGMENTS: tuple[str, ...] = (
    "crypto vault lite",
    "save wallet addresses",
    "send features will come later",
    "seed phrases",
    "wallet notes",
    "transaction records",
    "private keys",
    "coming soon",
)


def _assert_no_legacy(tc, msg):
    low = msg.lower()
    for frag in LEGACY_FRAGMENTS:
        with tc.subTest(fragment=frag):
            tc.assertNotIn(frag, low)


class TestChatRepliesFreeBasic(unittest.TestCase):

    def _expect_upgrade_prompt(self, msg: str) -> None:
        low = msg.lower()
        self.assertIn("upgrade", low)
        self.assertIn("crypto vault", low)
        # Free/basic must NOT describe the vault as already active.
        for forbidden in (
            "yes.",
            "active on your account",
            "your crypto vault is active",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, low)
        _assert_no_legacy(self, msg)

    def test_save_question_free_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save my Bitcoin in my vault",
            user_tier="free",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self._expect_upgrade_prompt(result["message"])

    def test_generic_question_free_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can i use the crypto in my vault",
            user_tier="free",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self._expect_upgrade_prompt(result["message"])

    def test_basic_user_gets_same_copy_as_free(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier="basic",
        )
        self._expect_upgrade_prompt(result["message"])

    def test_unknown_tier_falls_back_to_checking_message(self):
        # Unknown tier → we say we're checking access, we do NOT
        # blast the upgrade prompt (we don't yet know if they need it).
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier=chat_mod.TIER_UNKNOWN_LABEL,
        )
        self.assertIn(
            "checking your Crypto Vault access",
            result["message"],
        )

    def test_missing_tier_defaults_to_free_copy(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save crypto",
            user_tier=None,
        )
        self._expect_upgrade_prompt(result["message"])


class TestChatRepliesUpgraded(unittest.TestCase):

    def _expect_active_wallet(self, msg: str) -> None:
        low = msg.lower()
        self.assertIn("open crypto vault", low)
        for forbidden in (
            "you can't access crypto vault",
            "upgrade your account to unlock",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, low)
        _assert_no_legacy(self, msg)

    def test_save_question_upgraded_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can I save my Bitcoin in my vault",
            user_tier="upgraded",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self._expect_active_wallet(result["message"])

    def test_generic_question_upgraded_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can i use the crypto in my vault",
            user_tier="upgraded",
        )
        self.assertEqual(result["band"], chat_mod.BAND_DEFLECTED)
        self.assertTrue(
            result["message"].lstrip().startswith("Yes"),
            msg="upgraded generic reply must lead with 'Yes'",
        )
        self._expect_active_wallet(result["message"])

    def test_receive_question_upgraded_user(self):
        result = chat_mod.route_crypto_question(
            user_message="can I receive crypto",
            user_tier="upgraded",
        )
        low = result["message"].lower()
        self.assertIn("open crypto vault", low)
        self.assertIn("qr code", low)
        _assert_no_legacy(self, result["message"])

    def test_buy_question_upgraded_user_keeps_no_buy_disclaimer(self):
        result = chat_mod.route_crypto_question(
            user_message="can I buy crypto here",
            user_tier="upgraded",
        )
        low = result["message"].lower()
        self.assertIn("doesn't buy, sell, or trade crypto", low)
        # Upgraded users see the ACTIVE framing, not the "upgrade" one.
        self.assertIn("active", low)
        _assert_no_legacy(self, result["message"])


class TestSendMirrorsTheTier(unittest.TestCase):

    def test_send_reply_free_user_prompts_upgrade(self):
        # 2026-07-12: the OLD suite claimed Send should be the same
        # message for free and upgraded (both "not active yet"). That
        # is obsolete now — Send is a real, entitled action.
        msg = chat_mod.route_crypto_question(
            user_message="can I send Bitcoin",
            user_tier="free",
        )["message"]
        low = msg.lower()
        self.assertIn("upgrade", low)
        _assert_no_legacy(self, msg)

    def test_send_reply_upgraded_user_describes_real_flow(self):
        msg = chat_mod.route_crypto_question(
            user_message="can I send Bitcoin",
            user_tier="upgraded",
        )["message"]
        low = msg.lower()
        self.assertIn("open crypto vault", low)
        self.assertIn("pin", low)
        _assert_no_legacy(self, msg)


class TestEnvelopeBranchesOnTier(unittest.TestCase):

    def test_free_envelope_shows_locked_card(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_FREE,
        ))
        self.assertEqual(env["status"], "Upgrade required")
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
        self.assertEqual(env["status"], "Upgrade required")
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

    def test_upgraded_envelope_enables_receive_send_and_generation(self):
        env = json.loads(card_mod.build_crypto_locked_envelope(
            user_tier=card_mod.TIER_UPGRADED,
        ))
        self.assertTrue(env["receive_enabled"])
        # 2026-07-12: send is a real feature on upgraded plans —
        # backend routes are gated by require_crypto_entitlement.
        self.assertTrue(env["send_enabled"])
        self.assertTrue(env["wallet_generation_enabled"])
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
