"""Pytest coverage for the crypto-vault chat entitlement gate
(production bug 2026-07-11).

Product decision: the crypto vault is a paid-tier feature. If the
caller is NOT upgraded (block_count > 0 AND purchased_bytes > 0), the
show-vault card must carry ``locked: True`` and
``entitlement: "upgrade_required"``. The frontend uses those flags to
swap the affordance for an "Upgrade required" CTA.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch


from vault_chat_crypto_data import populate_crypto_delegated_card_data
from vault_chat_router import build_vault_chat_envelope


def _fake_overview(*_args, **_kwargs):
    return {
        "schema":            "vault_crypto_overview_data.v1",
        "available":         True,
        "assets":            [],
        "unavailableCount":  0,
        "xmrScannerStatus":  None,
        "xmrReason":         None,
        "xmrCanShowBalance": False,
        "xmrMode":           None,
    }


class RouterStillClassifies(unittest.TestCase):
    def test_can_i_access_crypto_vault_hits_delegated(self):
        env = build_vault_chat_envelope("can i access the crypto vault")
        self.assertIsNotNone(env)
        self.assertEqual(env["intent"], "vault_crypto_delegated")
        self.assertEqual(
            env["card"]["cardType"], "vault_crypto_delegated_card",
        )
        self.assertEqual(
            env["card"]["innerIntent"], "crypto_vault_show_vault",
        )


class NonEntitledCallerSeesLockedCard(unittest.TestCase):
    def setUp(self):
        self.envelope = build_vault_chat_envelope(
            "can i access the crypto vault",
        )
        self.assertIsNotNone(self.envelope)

    def _populate(self, tier):
        with patch(
            "vault_chat_crypto_data.build_crypto_overview_data",
            side_effect=_fake_overview,
        ):
            return populate_crypto_delegated_card_data(
                self.envelope,
                vault_id="test-vault",
                client_platform="web",
                user_tier=tier,
            )

    def test_free_tier_receives_locked_flag(self):
        env = self._populate("free")
        inner = env["card"]["innerCard"]
        data = inner.get("data")
        self.assertIsInstance(data, dict)
        self.assertTrue(data.get("locked"))
        self.assertEqual(data.get("entitlement"), "upgrade_required")
        self.assertEqual(data.get("tier"), "free")

    def test_empty_tier_defaults_to_locked(self):
        env = self._populate("")
        data = env["card"]["innerCard"]["data"]
        self.assertTrue(data.get("locked"))
        self.assertEqual(data.get("entitlement"), "upgrade_required")

    def test_none_tier_defaults_to_locked(self):
        with patch(
            "vault_chat_crypto_data.build_crypto_overview_data",
            side_effect=_fake_overview,
        ):
            env = populate_crypto_delegated_card_data(
                self.envelope,
                vault_id="test-vault",
                client_platform="web",
                user_tier=None,
            )
        data = env["card"]["innerCard"]["data"]
        self.assertTrue(data.get("locked"))

    def test_unknown_tier_string_defaults_to_locked(self):
        env = self._populate("premium_gold")
        data = env["card"]["innerCard"]["data"]
        self.assertTrue(data.get("locked"))
        self.assertEqual(data.get("entitlement"), "upgrade_required")


class EntitledCallerSeesUnlockedCard(unittest.TestCase):
    def setUp(self):
        self.envelope = build_vault_chat_envelope(
            "can i access the crypto vault",
        )

    def _populate(self, tier):
        with patch(
            "vault_chat_crypto_data.build_crypto_overview_data",
            side_effect=_fake_overview,
        ):
            return populate_crypto_delegated_card_data(
                self.envelope,
                vault_id="test-vault",
                client_platform="web",
                user_tier=tier,
            )

    def test_upgraded_tier_receives_unlocked(self):
        env = self._populate("upgraded")
        data = env["card"]["innerCard"]["data"]
        self.assertFalse(data.get("locked"))
        self.assertEqual(data.get("entitlement"), "upgraded")
        self.assertEqual(data.get("tier"), "upgraded")

    def test_upgraded_case_insensitive(self):
        env = self._populate("UpGrAdEd")
        data = env["card"]["innerCard"]["data"]
        self.assertFalse(data.get("locked"))

    def test_upgraded_response_includes_open_select_receive_send_instructions(self):

        env = self._populate("upgraded")
        top_msg = str(env.get("message") or "")
        self.assertTrue(
            top_msg,
            msg="entitled response must include a non-empty top-line "
                "message so the user gets an ANSWER, not just a card",
        )
        low = top_msg.lower()
        self.assertIn("yes", low,
                      msg="entitled response must say yes")
        self.assertIn("open", low)
        self.assertIn("receive", low)
        self.assertIn("send", low)

        data = env["card"]["innerCard"]["data"]
        instructions = data.get("instructions") or []
        self.assertIsInstance(instructions, list)
        joined = " ".join(instructions).lower()
        self.assertIn("open", joined)
        self.assertIn("asset", joined)
        self.assertIn("receive", joined)
        self.assertIn("send", joined)


class OtherCryptoIntentsAreNotGated(unittest.TestCase):

    def test_receive_address_intent_does_not_add_locked_flag(self):
        env = build_vault_chat_envelope(
            "what's my Bitcoin receive address",
        )
        if env is None or env.get("intent") != "vault_crypto_delegated":
            self.skipTest("router did not classify as crypto_delegated")
        inner_intent = env["card"].get("innerIntent")
        if inner_intent == "crypto_vault_show_vault":
            self.skipTest("phrase resolved to show_vault intent, not receive")
        with patch(
            "vault_chat_crypto_data.build_crypto_overview_data",
            side_effect=_fake_overview,
        ), patch(
            "vault_chat_crypto_data.build_crypto_receive_data",
            return_value={"schema": "x", "available": True},
        ):
            env = populate_crypto_delegated_card_data(
                env,
                vault_id="test-vault",
                client_platform="web",
                user_tier="free",
            )
        inner = env["card"]["innerCard"]
        data = inner.get("data")
        if data is not None:
            self.assertNotIn("locked", data)


class BackwardsCompat(unittest.TestCase):
    def test_no_tier_arg_still_works_but_defaults_locked(self):
        envelope = build_vault_chat_envelope(
            "can i access the crypto vault",
        )
        with patch(
            "vault_chat_crypto_data.build_crypto_overview_data",
            side_effect=_fake_overview,
        ):
            out = populate_crypto_delegated_card_data(
                envelope,
                vault_id="test-vault",
                client_platform="web",
            )
        data = out["card"]["innerCard"]["data"]
        self.assertTrue(data.get("locked"))
        self.assertEqual(data.get("entitlement"), "upgrade_required")


if __name__ == "__main__":
    unittest.main()
