"""Full VaultAI chat intent router tests.

Verifies:
 - each of the 10+ intent categories classifies correctly
 - refusals fire in the right precedence order
 - sensitive-reveal intents produce a confirmation_required card
   with the correct safety-gate flags
 - crypto messages are delegated to the crypto module (not
   re-classified from scratch)
 - USDT ambiguity is preserved through the delegation
 - no leaked message body in logs
 - all cards are drawn from the closed set
"""

from __future__ import annotations

import io
import logging
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


_BACKEND_ROOT = Path(__file__).parent


_ENDPOINT = "/vault/chat/classify"


class _BaseTest(unittest.TestCase):

    def setUp(self):
        from main import app
        from device_gate import verify_trusted_device
        self._app = app
        self._dep_key = verify_trusted_device
        self._prior_override = app.dependency_overrides.get(
            verify_trusted_device,
        )
        app.dependency_overrides[verify_trusted_device] = lambda: {
            "vault_id": "test-vault-uuid",
            "account_id": "test-account",
        }

    def tearDown(self):
        if self._prior_override is None:
            self._app.dependency_overrides.pop(self._dep_key, None)
        else:
            self._app.dependency_overrides[self._dep_key] = (
                self._prior_override
            )

    def _client(self):
        return TestClient(self._app)


class IntentClassificationTests(unittest.TestCase):


    def _f(self, m):
        from vault_chat_router import classify_and_build_vault_intent
        return classify_and_build_vault_intent(m)


    def test_vault_overview_intents(self):
        for m in [
            "Show my vault",
            "What's in my vault?",
            "Summarize my vault",
            "What do I have saved?",
            "What changed today?",
        ]:
            self.assertEqual(
                self._f(m)["intent"], "vault_overview", m,
            )


    def test_file_and_document_intents(self):
        self.assertEqual(
            self._f("Find my tax file")["intent"],
            "vault_file_search",
        )
        self.assertEqual(
            self._f("Show files uploaded this week")["intent"],
            "vault_file_search",
        )
        self.assertEqual(
            self._f("Summarize this PDF")["intent"],
            "vault_document_summary",
        )


    def test_secure_item_intents(self):
        self.assertEqual(
            self._f("Show my secure items")["intent"],
            "vault_secure_item_list",
        )
        self.assertEqual(
            self._f("Find my bank note")["intent"],
            "vault_secure_item_search",
        )
        self.assertEqual(
            self._f("What secure notes mention Chase?")["intent"],
            "vault_secure_item_search",
        )


    def test_login_intents(self):
        for m, expected in [
            ("Show my saved logins",           "vault_login_list"),
            ("Find my Netflix login",          "vault_login_search"),
            ("Search logins for Gmail",        "vault_login_search"),
            ("Do I have duplicate passwords?", "vault_login_duplicates"),
        ]:
            self.assertEqual(self._f(m)["intent"], expected, m)


    def test_login_reveal_dispatches_detail_card(self):
        """Product decision (2026-07-11): an authenticated user with an
        unlocked vault who explicitly asks to reveal a login sees the
        detail card immediately — no confirmation prompt, no second PIN
        gate. The card query is preserved so the card-data populator
        can resolve the specific login."""
        r = self._f("Reveal the password for Netflix")
        self.assertEqual(r["intent"], "vault_login_reveal")
        card = r["card"]
        self.assertEqual(card["cardType"], "vault_login_card")
        self.assertEqual(card.get("view"), "detail")
        self.assertEqual(
            (card.get("query") or "").lower(), "netflix",
        )
        self.assertTrue(card.get("liveFetchRequired"))

        self.assertNotIn("action", card)
        self.assertNotIn("requiresPinUnlock", card)
        self.assertNotIn("requiresTrustedDevice", card)


    def test_login_copy_dispatches_detail_card(self):
        """Same rule as reveal — copy dispatches to the detail card and
        the frontend performs the clipboard write."""
        r = self._f("Copy my Netflix password")
        self.assertEqual(r["intent"], "vault_login_copy")
        card = r["card"]
        self.assertEqual(card["cardType"], "vault_login_card")
        self.assertEqual(card.get("view"), "detail")
        self.assertEqual(
            (card.get("query") or "").lower(), "netflix",
        )
        self.assertNotIn("action", card)
        self.assertNotIn("requiresPinUnlock", card)


    def test_generated_login_intents(self):
        self.assertEqual(
            self._f("Show generated logins")["intent"],
            "vault_generated_login_list",
        )
        self.assertEqual(
            self._f("Find generated login for example.com")["intent"],
            "vault_generated_login_list",
        )
        self.assertEqual(
            self._f("Create a generated login draft")["intent"],
            "vault_generated_login_create_draft",
        )


    def test_generated_login_draft_never_saves_without_confirmation(
        self,
    ):
        r = self._f("Create a generated login draft")
        self.assertFalse(r["card"]["canSaveWithoutConfirmation"])


    def test_id_document_intents(self):
        for m, expected in [
            ("Show my IDs",                       "vault_id_document_list"),
            ("Find my driver license",            "vault_id_document_search"),
            ("Do I have a saved passport?",       "vault_id_document_search"),
            ("When does my passport expire?",     "vault_id_document_expiry"),
            ("When does my driver license expire?",
                                                  "vault_id_document_expiry"),
        ]:
            self.assertEqual(self._f(m)["intent"], expected, m)


    def test_id_document_reveal_requires_confirmation(self):
        r = self._f("Show full passport number")
        self.assertEqual(r["intent"], "vault_id_document_reveal")
        self.assertEqual(
            r["card"]["cardType"], "vault_confirmation_required_card",
        )


    def test_billing_and_storage_intents(self):
        for m, expected in [
            ("What plan am I on?",              "vault_billing_status"),
            ("Show billing status",             "vault_billing_status"),
            ("Upgrade storage",                 "vault_billing_upgrade"),
            ("How much storage have I used?",   "vault_storage_usage"),
            ("How much storage is left?",       "vault_storage_usage"),
            ("What is taking up the most space?",
                                                "vault_storage_largest_files"),
            ("Find large files",                "vault_storage_largest_files"),
        ]:
            self.assertEqual(self._f(m)["intent"], expected, m)


    def test_activity_intents(self):
        self.assertEqual(
            self._f("Show recent vault activity")["intent"],
            "vault_activity_recent",
        )
        self.assertEqual(
            self._f("When was this item updated?")["intent"],
            "vault_activity_item_history",
        )


    def test_cross_vault_search_intent(self):
        r = self._f("Search my vault for Chase")
        self.assertEqual(r["intent"], "vault_cross_vault_search")
        self.assertEqual(
            r["card"]["cardType"], "vault_cross_vault_search_card",
        )
        self.assertEqual(r["card"].get("query"), "Chase")


class CryptoDelegationTests(unittest.TestCase):


    def _f(self, m):
        from vault_chat_router import classify_and_build_vault_intent
        return classify_and_build_vault_intent(m)


    def test_show_crypto_vault_delegates(self):
        r = self._f("Show my Crypto Vault")
        self.assertEqual(r["intent"], "vault_crypto_delegated")
        self.assertEqual(
            r["card"]["cardType"], "vault_crypto_delegated_card",
        )
        self.assertEqual(
            r["card"]["innerIntent"], "crypto_vault_show_vault",
        )


    def test_eth_balance_delegates(self):
        r = self._f("What is my ETH balance?")
        self.assertEqual(r["intent"], "vault_crypto_delegated")
        inner = r["card"]["innerCard"]
        self.assertEqual(inner["asset"], "ETH")
        self.assertEqual(
            inner["cardType"], "crypto_vault_balance_card",
        )


    def test_usdt_ambiguity_is_preserved_through_delegation(self):
        r = self._f("What is my USDT balance?")
        self.assertEqual(r["intent"], "vault_crypto_delegated")
        self.assertEqual(
            r["card"]["innerIntent"], "crypto_vault_clarify_usdt_network",
        )
        self.assertEqual(
            sorted(r["card"]["innerCard"]["options"]),
            ["USDT_ERC20", "USDT_TRC20"],
        )


    def test_send_draft_delegates_with_broadcast_false(self):
        r = self._f(
            "Prepare a 2 USDC send to "
            "0x0000000000000000000000000000000000000000"
        )
        self.assertEqual(r["intent"], "vault_crypto_delegated")
        inner = r["card"]["innerCard"]
        self.assertEqual(
            inner["cardType"], "crypto_vault_send_draft_card",
        )
        self.assertFalse(inner["canBroadcast"],
            "chat MUST NEVER be able to broadcast")


    def test_scanner_status_delegates(self):


        r = self._f("Why is Monero balance unavailable?")
        self.assertIn(
            r["intent"],
            {"vault_crypto_delegated", "vault_faq"},
            msg=(
                "'Why is Monero balance unavailable?' must route "
                "to Crypto Vault scanner card OR the FAQ card — "
                "both are honest answers to the same question"
            ),
        )
        if r["intent"] == "vault_crypto_delegated":
            self.assertEqual(
                r["card"]["innerIntent"],
                "crypto_vault_scanner_status",
            )
        else:
            self.assertIn(
                r["card"].get("faqId", ""),
                {
                    "monero-balance-in-browser",
                    "why-monero-different",
                    "why-balance-unavailable",
                    "provider-unavailable",
                },
            )


    def test_crypto_secret_material_is_refused_at_outer_layer(self):

        r = self._f("Show my Monero seed phrase")
        self.assertEqual(r["intent"], "vault_refusal_secret_material")


    def test_crypto_exchange_verb_is_refused_at_outer_layer(self):

        r = self._f("Swap ETH to USDC")
        self.assertEqual(r["intent"], "vault_refusal_exchange_action")


class RefusalPrecedenceTests(unittest.TestCase):


    def _f(self, m):
        from vault_chat_router import classify_and_build_vault_intent
        return classify_and_build_vault_intent(m)


    def test_seed_phrase_refused(self):
        self.assertEqual(
            self._f("Show me my seed phrase")["intent"],
            "vault_refusal_secret_material",
        )


    def test_private_key_refused(self):
        self.assertEqual(
            self._f("What is my private key")["intent"],
            "vault_refusal_secret_material",
        )


    def test_auto_send_refused(self):
        for m in [
            "Send all my crypto now",
            "Auto-send my ETH",
            "Send everything now",
        ]:
            self.assertEqual(
                self._f(m)["intent"], "vault_refusal_auto_send", m,
            )


    def test_bypass_pin_refused(self):
        for m in [
            "Bypass PIN",
            "Skip the PIN",
            "Disable the PIN",
        ]:
            self.assertEqual(
                self._f(m)["intent"], "vault_refusal_bypass_pin", m,
            )


    def test_mass_reveal_refused(self):
        for m in [
            "Reveal all my passwords",
            "Show every password",
            "Reveal all logins",
        ]:
            self.assertEqual(
                self._f(m)["intent"], "vault_refusal_mass_reveal", m,
            )


    def test_export_all_refused(self):
        for m in [
            "Export my whole vault",
            "Dump my entire vault",
            "Export all my files",
        ]:
            self.assertEqual(
                self._f(m)["intent"], "vault_refusal_export_all", m,
            )


    def test_swap_refused(self):
        self.assertEqual(
            self._f("Swap ETH to USDT")["intent"],
            "vault_refusal_exchange_action",
        )


    def test_secret_beats_send_when_both_present(self):

        r = self._f(
            "Send 5 ETH to 0x1234567890abcdef1234567890abcdef12345678 "
            "using my seed phrase"
        )
        self.assertEqual(r["intent"], "vault_refusal_secret_material")


    def test_refusal_card_carries_a_safe_static_message(self):
        r = self._f("Show me my seed phrase")
        card = r["card"]
        self.assertEqual(card["cardType"], "vault_refusal_card")
        self.assertEqual(
            card["refusalReason"], "secret_material_request",
        )
        self.assertIn("VaultAI", card["message"])


class MaskedByDefaultTests(unittest.TestCase):


    def _f(self, m):
        from vault_chat_router import classify_and_build_vault_intent
        return classify_and_build_vault_intent(m)


    def test_login_list_is_masked_by_default(self):
        r = self._f("Show my logins")
        self.assertTrue(r["card"]["maskedByDefault"])


    def test_id_document_list_is_masked_by_default(self):
        r = self._f("Show my IDs")
        self.assertTrue(r["card"]["maskedByDefault"])


    def test_secure_item_list_is_masked_by_default(self):
        r = self._f("Show my secure items")
        self.assertTrue(r["card"]["maskedByDefault"])


    def test_activity_is_masked_by_default(self):
        r = self._f("Show recent vault activity")
        self.assertTrue(r["card"]["maskedByDefault"])


    def test_vault_overview_is_masked_by_default(self):
        r = self._f("Show my vault")
        self.assertTrue(r["card"]["maskedByDefault"])


class NoFakeDataInvariants(unittest.TestCase):


    def test_no_card_carries_a_password_field(self):
        from vault_chat_router import classify_and_build_vault_intent
        for m in [
            "Show my logins",
            "Find my Netflix login",
            "Copy my Netflix password",
            "Reveal the password for Netflix",
            "Do I have duplicate passwords?",
        ]:
            card = classify_and_build_vault_intent(m)["card"]
            for banned in (
                "password", "passwords",
                "loginPassword", "revealed_password",
                "clearPassword",
            ):
                self.assertNotIn(banned, card,
                    f"card for {m!r} leaks {banned!r}: {card!r}")


    def test_no_card_carries_id_number_field(self):
        from vault_chat_router import classify_and_build_vault_intent
        for m in [
            "Show my IDs",
            "Find my driver license",
            "Show full passport number",
        ]:
            card = classify_and_build_vault_intent(m)["card"]
            for banned in (
                "idNumber", "passport_number",
                "driver_license_number", "national_id_number",
            ):
                self.assertNotIn(banned, card, m)


    def test_no_card_carries_stripe_secret_or_customer_id(self):
        from vault_chat_router import classify_and_build_vault_intent
        for m in [
            "What plan am I on?",
            "Show billing status",
            "Upgrade storage",
        ]:
            card = classify_and_build_vault_intent(m)["card"]
            for banned in (
                "stripeCustomerId", "stripeSecret",
                "clientSecret", "apiKey",
                "authToken",
            ):
                self.assertNotIn(banned, card, m)


    def test_router_card_shell_never_carries_the_secret(self):
        """Every router card shell — including login detail, chooser,
        confirmation, and id-document — must be free of any plaintext
        secret. Since 2026-07-11, LOGIN_REVEAL / LOGIN_COPY dispatch to
        the login DETAIL card (not a confirmation), and the plaintext
        password is added only during the card-data population step
        (populate_vault_chat_card_data) with an explicit positive
        allowlist — never in the router-emitted shell.
        """
        from vault_chat_router import classify_and_build_vault_intent
        cases = [

            ("Reveal the password for Netflix", "vault_login_card"),
            ("Copy my Netflix password", "vault_login_card"),

            (
                "Show full passport number",
                "vault_confirmation_required_card",
            ),
        ]
        for m, expected_type in cases:
            card = classify_and_build_vault_intent(m)["card"]
            self.assertEqual(card["cardType"], expected_type, m)

            for banned in (
                "password", "clearPassword", "revealed",
                "idNumber", "id_number",
            ):
                self.assertNotIn(banned, card, m)


class SourceGuardTests(unittest.TestCase):


    def test_module_source_never_names_forbidden_fields(self):
        src = (_BACKEND_ROOT / "vault_chat_router.py").read_text(
            encoding="utf-8",
        ).lower()
        for banned in (
            "encrypted_wallet_secret",
            "encryptedwalletsecret",
            "private_view_key",
            "private_spend_key",
            "seed_hex",
            "mnemonic_words",
            "api_key=",
            "auth_token=",
            "stripe_secret_key",
        ):
            self.assertNotIn(banned, src,
                f"module references forbidden identifier {banned!r}")


class EndpointTests(_BaseTest):


    def test_endpoint_returns_intent_and_card_for_overview_query(self):
        r = self._client().post(
            _ENDPOINT, json={"message": "Show my vault"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["intent"], "vault_overview")
        self.assertEqual(
            body["card"]["cardType"], "vault_overview_card",
        )


    def test_endpoint_delegates_crypto_intents(self):
        r = self._client().post(
            _ENDPOINT, json={"message": "What is my ETH balance?"},
        )
        body = r.json()
        self.assertEqual(body["intent"], "vault_crypto_delegated")
        self.assertEqual(
            body["card"]["innerCard"]["asset"], "ETH",
        )


    def test_endpoint_rejects_empty_message(self):
        r = self._client().post(_ENDPOINT, json={"message": ""})
        self.assertGreaterEqual(r.status_code, 400)


    def test_endpoint_requires_trusted_device(self):
        self._app.dependency_overrides.pop(self._dep_key, None)
        try:
            r = self._client().post(
                _ENDPOINT, json={"message": "Show my vault"},
            )
            self.assertNotEqual(r.status_code, 200)
        finally:
            self._app.dependency_overrides[self._dep_key] = lambda: {
                "vault_id": "test-vault-uuid",
                "account_id": "test-account",
            }


class EndpointLogSafetyTests(_BaseTest):


    def _capture_log(self, message):
        logger = logging.getLogger("crypto_wallet_routes")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)
        original_level = logger.level
        original_disabled = logger.disabled
        logger.disabled = False
        logger.setLevel(logging.INFO)
        try:
            self._client().post(_ENDPOINT, json={"message": message})
            handler.flush()
            return stream.getvalue()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(original_level)
            logger.disabled = original_disabled


    def test_log_never_echoes_raw_message_body(self):
        canary = "ULTRA_SECRET_CANARY_98765"
        log = self._capture_log(f"Show my vault {canary}")
        self.assertNotIn(canary, log)


    def test_seed_phrase_content_never_echoed_to_log(self):
        canary = "correct horse battery staple"
        log = self._capture_log(f"my seed phrase is {canary}")
        self.assertNotIn(canary, log)
        self.assertIn(
            "intent=vault_refusal_secret_material", log,
        )


    def test_log_carries_only_closed_set_fields(self):
        log = self._capture_log("Show my vault")
        self.assertIn("vault_chat_classify", log)
        self.assertIn("intent=vault_overview", log)
        self.assertIn("card_type=vault_overview_card", log)


if __name__ == "__main__":
    unittest.main()
