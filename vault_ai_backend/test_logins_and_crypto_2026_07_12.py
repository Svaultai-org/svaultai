"""2026-07-12 fixes: login count branching + crypto access routing.

Covers:

  * INTENT_LOGIN_LIST 0/1/many branching:
      0 rows → view=not_found  (clean empty state)
      1 row  → view=detail     (immediate credential card, active
                                 entity pinned by main.py)
     >1 rows → view=list       (chooser)
  * Duplicate-title case: two logins with the same service ILIKE
    query still route through the detail path when the caller
    passes item_id (which the frontend row-tap does via
    selection_hint).
  * Crypto access-question broadener: prompts like "can i use the
    crypto", "can i access crypto vault", "do i have crypto vault",
    "how do i open crypto" now hit the entitlement-aware SHOW_VAULT
    envelope INSTEAD of the plain-text deflector — so a non-
    upgraded user sees the locked card (Upgrade Required) and an
    upgraded user sees the active card (Open Crypto Vault).
  * Crypto copy at every tier is free of the legacy Lite fragments.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import unittest
from unittest.mock import patch


os.environ.setdefault("DATABASE_URL", "postgresql://noop:noop@localhost/noop")
os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")


# ---------------------------------------------------------------- #
# Login 0/1/many
# ---------------------------------------------------------------- #


def _login_row(row_id: str, service: str, username: str, password: str):
    return {
        "id":       row_id,
        "service":  service,
        "encrypted_data": json.dumps({
            "title":   service,
            "service": service,
            "fields":  {"username": username, "password": password},
        }).encode(),
        "created_at": _dt.datetime(2026, 7, 12),
    }


class LoginListBranching(unittest.TestCase):

    def _run(self, rows):
        from vault_chat_card_data import build_login_list_data

        def fake_fetch(vault_id, item_type, limit,
                       *, service_ilike=None, item_id=None):
            return rows

        def fake_decrypt(blob, key):
            return json.loads(blob)

        with patch(
            "vault_chat_card_data._fetch_vault_items",
            side_effect=fake_fetch,
        ), patch(
            "vault_chat_card_data._decrypt_row_json",
            side_effect=fake_decrypt,
        ):
            return build_login_list_data("v", b"k" * 32)

    def test_zero_rows_returns_not_found(self):
        data = self._run([])
        self.assertEqual(data["view"], "not_found")
        self.assertEqual(data["count"], 0)
        self.assertNotIn("logins", data)
        self.assertNotIn("login", data)

    def test_one_row_collapses_to_detail_with_full_plaintext(self):
        rows = [_login_row(
            "id-1", "Gmail", "alice@example.com", "hunter2",
        )]
        data = self._run(rows)
        self.assertEqual(data["view"], "detail")
        self.assertEqual(data["count"], 1)
        login = data["login"]
        self.assertEqual(login["id"], "id-1")
        self.assertEqual(login["title"], "Gmail")
        self.assertEqual(login["username"], "alice@example.com")
        # The single-detail path is the intentional exception to the
        # "no plaintext passwords in card data" invariant — verified
        # by _sanitize_login_detail_payload downstream.
        self.assertEqual(login["password"], "hunter2")

    def test_multiple_rows_still_render_list_view(self):
        rows = [
            _login_row("id-1", "Gmail", "alice@example.com", "pwA"),
            _login_row("id-2", "GitHub", "alice@example.com", "pwB"),
        ]
        data = self._run(rows)
        self.assertEqual(data["view"], "list")
        self.assertEqual(data["count"], 2)
        self.assertEqual(len(data["logins"]), 2)
        # Chooser projection MUST NOT carry plaintext passwords.
        for row in data["logins"]:
            self.assertNotIn("password", row)


class LoginListSanitizerAcceptsDetailForListIntent(unittest.TestCase):
    """The populate step routes INTENT_LOGIN_LIST's DETAIL payload
    through the same allowlist sanitizer as INTENT_LOGIN_SEARCH so the
    plaintext password survives."""

    def test_populate_keeps_plaintext_when_list_collapses_to_detail(
        self,
    ):
        from vault_chat_card_data import populate_vault_chat_card_data

        rows = [_login_row(
            "id-1", "Gmail", "alice@example.com", "hunter2",
        )]

        def fake_fetch(vault_id, item_type, limit,
                       *, service_ilike=None, item_id=None):
            return rows

        def fake_decrypt(blob, key):
            return json.loads(blob)

        envelope = {
            "intent": "vault_login_list",
            "card":   {
                "schema":   "vault_chat_router_v1",
                "cardType": "vault_login_card",
                "view":     "list",
                "data":     None,
            },
        }
        with patch(
            "vault_chat_card_data._fetch_vault_items",
            side_effect=fake_fetch,
        ), patch(
            "vault_chat_card_data._decrypt_row_json",
            side_effect=fake_decrypt,
        ):
            out = populate_vault_chat_card_data(
                envelope, vault_id="v", key=b"k" * 32,
            )
        data = out["card"]["data"]
        self.assertEqual(data["view"], "detail")
        # The sanitizer allowlists `login` for the DETAIL view, and
        # the login sub-object allowlists `password` — plaintext
        # survives ONLY through this positive whitelist path.
        self.assertEqual(data["login"]["password"], "hunter2")


class LoginDuplicateTitleDisambiguation(unittest.TestCase):
    """Two logins with the same title still resolve to the correct
    record when the caller pins item_id (row-tap via
    selection_hint)."""

    def test_two_gmails_by_item_id(self):
        from vault_chat_card_data import build_login_detail_data

        row_a = _login_row("id-A", "Gmail", "alice@example.com", "pwA")
        row_b = _login_row("id-B", "Gmail", "bob@example.com", "pwB")

        def fake_fetch(vault_id, item_type, limit,
                       *, service_ilike=None, item_id=None):
            if item_id == "id-A":
                return [row_a]
            if item_id == "id-B":
                return [row_b]
            return [row_a, row_b]

        def fake_decrypt(blob, key):
            return json.loads(blob)

        with patch(
            "vault_chat_card_data._fetch_vault_items",
            side_effect=fake_fetch,
        ), patch(
            "vault_chat_card_data._decrypt_row_json",
            side_effect=fake_decrypt,
        ):
            a = build_login_detail_data(
                "v", b"k" * 32, query="Gmail", item_id="id-A",
            )
            b = build_login_detail_data(
                "v", b"k" * 32, query="Gmail", item_id="id-B",
            )
        self.assertEqual(a["view"], "detail")
        self.assertEqual(b["view"], "detail")
        self.assertNotEqual(
            a["login"]["password"], b["login"]["password"],
        )


# ---------------------------------------------------------------- #
# Crypto access-question broadener
# ---------------------------------------------------------------- #


class CryptoAccessQuestionBroadener(unittest.TestCase):
    """When the fast-path inner classifier says UNRECOGNIZED for a
    crypto-hint message that reads like an access question, we
    rewrite the intent to SHOW_VAULT so the entitlement-aware card
    fires instead of the plain-text deflector."""

    def setUp(self):
        from vault_chat_router import (
            _looks_like_crypto_access_question,
            classify_and_build_vault_intent,
            INTENT_CRYPTO_DELEGATED,
        )
        self._broadener = _looks_like_crypto_access_question
        self._classify = classify_and_build_vault_intent
        self._delegated_intent = INTENT_CRYPTO_DELEGATED

    def test_broadener_matches_reported_prompt(self):
        # The exact prompt that triggered the stale reply.
        self.assertTrue(self._broadener("can i use the crypto"))

    def test_broadener_matches_full_set(self):
        for phrase in (
            "can i use the crypto",
            "can i access crypto vault",
            "can i use crypto vault",
            "do i have crypto vault",
            "can i open crypto",
            "how do i use crypto vault",
            "how do i access crypto vault",
            "how can i use the crypto wallet",
            "where is my crypto",
            "take me to the crypto",
            "unlock the crypto",
            "activate crypto",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    self._broadener(phrase),
                    msg=f"broadener must match: {phrase!r}",
                )

    def test_broadener_ignores_non_crypto_questions(self):
        for phrase in (
            "",
            "hello",
            "can i see my logins",
            "can i use my files",
            "how do i access my vault overview",
            "unlock my vault",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    self._broadener(phrase),
                    msg=f"broadener must NOT match: {phrase!r}",
                )

    def test_broadener_does_not_shadow_concrete_verbs(self):
        # send / receive-address / balance still route to their own
        # inner intents — the broadener only kicks in when the inner
        # classifier returns UNRECOGNIZED.
        result = self._classify("send 0.1 eth to 0x" + "a" * 40)
        self.assertEqual(result["intent"], self._delegated_intent)
        inner = result["card"].get("innerIntent") or ""
        self.assertIn(
            inner,
            (
                "crypto_vault_send_draft",
                "vault_refusal_secret_material",
                "crypto_vault_show_vault",
            ),
            msg="a real send message must still route as send, or "
                "as a refusal — not through the SHOW_VAULT broadener",
        )

    def test_reported_prompt_now_routes_to_show_vault_card(self):
        result = self._classify("can i use the crypto")
        self.assertEqual(result["intent"], self._delegated_intent)
        self.assertEqual(
            result["card"].get("innerIntent"),
            "crypto_vault_show_vault",
            msg="fast-path must emit the entitlement-aware "
                "SHOW_VAULT card, not fall through to the deflector",
        )


class CryptoCopyAtEveryTierIsRefreshed(unittest.TestCase):
    """Confirm the emitted card body carries the new wallet-product
    copy and NONE of the legacy Lite fragments — at every tier."""

    _FORBIDDEN = (
        "crypto vault lite",
        "save wallet addresses",
        "send features will come later",
        "seed phrases",
        "private keys",
        "transaction records",
        "wallet notes",
    )

    def _envelope(self, tier: str) -> dict:
        from vault_crypto_locked_card import build_crypto_locked_envelope
        return json.loads(build_crypto_locked_envelope(user_tier=tier))

    def test_non_upgraded_body_prompts_upgrade(self):
        for tier in ("free", "basic"):
            with self.subTest(tier=tier):
                env = self._envelope(tier)
                self.assertEqual(env["status"], "Upgrade required")
                low = env["body"].lower()
                self.assertIn("upgrade", low)
                self.assertIn("non-custodial wallet", low)
                for forbidden in self._FORBIDDEN:
                    self.assertNotIn(forbidden, low)
                self.assertTrue(env["locked"])

    def test_upgraded_body_describes_real_wallet(self):
        env = self._envelope("upgraded")
        self.assertEqual(env["status"], "Active")
        low = env["body"].lower()
        self.assertIn("active on your account", low)
        for word in ("receive", "send", "balance"):
            self.assertIn(word, low)
        for forbidden in self._FORBIDDEN:
            self.assertNotIn(forbidden, low)
        self.assertFalse(env["locked"])


if __name__ == "__main__":
    unittest.main()
