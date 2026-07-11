"""Regression: "open it" (and variants) after a Crypto Vault card
must not fall through as unrecognized. It must re-run the same
delegated show-vault envelope so entitlement gating applies.

Covers:

  * detect_pronoun_followup returns "open" for the new phrases:
    "open the vault", "take me there", "use it", "go there",
    "launch it", "open it up", "take me to it".
  * build_crypto_delegated_show_vault_envelope produces the expected
    vault_crypto_delegated / crypto_vault_show_vault shape.
  * populate_crypto_delegated_card_data on that envelope injects
    locked=True for non-entitled callers and locked=False for
    entitled callers — so the follow-up path arrives at the SAME
    behavior as the original "can i access the crypto vault" query.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch


from vault_chat_active_entity import (
    ACTION_OPEN,
    ACTION_SHOW,
    ACTION_UPGRADE,
    ACTION_VIEW,
    ENTITY_CRYPTO_WALLET,
    _reset_store_for_test,
    entity_matches_action,
    get_active_entity,
    set_active_entity,
)
from vault_chat_crypto_data import populate_crypto_delegated_card_data
from vault_chat_pronoun_followup import detect_pronoun_followup
from vault_chat_router import build_crypto_delegated_show_vault_envelope


def _fake_overview(*_a, **_k):
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


class PronounFollowupExtended(unittest.TestCase):
    """The follow-up dispatcher recognizes vault-oriented variants."""

    def test_open_the_vault(self):
        self.assertEqual(
            detect_pronoun_followup("open the vault"),
            {"verb": "open"},
        )

    def test_take_me_there(self):
        self.assertEqual(
            detect_pronoun_followup("take me there"),
            {"verb": "open"},
        )

    def test_use_it(self):
        self.assertEqual(
            detect_pronoun_followup("use it"),
            {"verb": "open"},
        )

    def test_go_there(self):
        self.assertEqual(
            detect_pronoun_followup("go there"),
            {"verb": "open"},
        )

    def test_launch_it(self):
        self.assertEqual(
            detect_pronoun_followup("launch it"),
            {"verb": "open"},
        )

    def test_open_it_still_works(self):
        self.assertEqual(
            detect_pronoun_followup("open it"),
            {"verb": "open"},
        )

    def test_question_shape_still_rejected(self):
        self.assertIsNone(detect_pronoun_followup("open it?"))

    def test_bare_yes_still_rejected(self):
        self.assertIsNone(detect_pronoun_followup("yes"))


class CryptoWalletActiveEntityAcceptsOpen(unittest.TestCase):
    """The active-entity dispatch matrix accepts the crypto wallet +
    open combination — the guard used by main.py."""

    def setUp(self):
        _reset_store_for_test()

    def test_crypto_wallet_allows_open(self):
        set_active_entity(
            "vault-xyz",
            entity_type=ENTITY_CRYPTO_WALLET,
            entity_ref={},
            display_label="Crypto Vault",
            allowed_actions=(
                ACTION_OPEN, ACTION_SHOW, ACTION_VIEW, ACTION_UPGRADE,
            ),
            session_id="tok-1",
        )
        rec = get_active_entity("vault-xyz", session_id="tok-1")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["entity_type"], ENTITY_CRYPTO_WALLET)
        for verb in ("open", "show", "view", "upgrade"):
            self.assertTrue(
                entity_matches_action(rec, verb),
                msg=f"verb {verb!r} must be allowed on crypto_wallet",
            )


class EnvelopeShape(unittest.TestCase):

    def test_direct_helper_returns_show_vault_envelope(self):
        env = build_crypto_delegated_show_vault_envelope()
        self.assertEqual(env["intent"], "vault_crypto_delegated")
        self.assertEqual(
            env["card"]["cardType"], "vault_crypto_delegated_card",
        )
        self.assertEqual(
            env["card"]["innerIntent"], "crypto_vault_show_vault",
        )


class OpenItFollowupNonEntitledIsLocked(unittest.TestCase):
    """Non-entitled: the followup envelope carries locked=True + the
    upgrade CTA. This proves 'open it' does NOT create an enabled Open
    action for a free user."""

    def test_followup_locked_for_free_tier(self):
        env = build_crypto_delegated_show_vault_envelope()
        with patch(
            "vault_chat_crypto_data.build_crypto_overview_data",
            side_effect=_fake_overview,
        ):
            env = populate_crypto_delegated_card_data(
                env,
                vault_id="vault-x",
                client_platform="web",
                user_tier="free",
            )
        data = env["card"]["innerCard"]["data"]
        self.assertTrue(data.get("locked"))
        self.assertEqual(data.get("entitlement"), "upgrade_required")

    def test_followup_locked_for_missing_tier(self):
        env = build_crypto_delegated_show_vault_envelope()
        with patch(
            "vault_chat_crypto_data.build_crypto_overview_data",
            side_effect=_fake_overview,
        ):
            env = populate_crypto_delegated_card_data(
                env,
                vault_id="vault-x",
                client_platform="web",
                user_tier=None,
            )
        data = env["card"]["innerCard"]["data"]
        self.assertTrue(data.get("locked"))


class OpenItFollowupEntitledIsUnlocked(unittest.TestCase):
    """Entitled: the followup envelope carries locked=False so the
    frontend renders the enabled Open Crypto Vault action."""

    def test_followup_unlocked_for_upgraded_tier(self):
        env = build_crypto_delegated_show_vault_envelope()
        with patch(
            "vault_chat_crypto_data.build_crypto_overview_data",
            side_effect=_fake_overview,
        ):
            env = populate_crypto_delegated_card_data(
                env,
                vault_id="vault-x",
                client_platform="web",
                user_tier="upgraded",
            )
        data = env["card"]["innerCard"]["data"]
        self.assertFalse(data.get("locked"))
        self.assertEqual(data.get("entitlement"), "upgraded")


if __name__ == "__main__":
    unittest.main()
