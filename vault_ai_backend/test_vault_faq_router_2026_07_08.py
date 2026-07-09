"""Tests for the VaultAI FAQ / Help Center router.

Covers:
  * Deterministic FAQ matching for the golden question list
  * Closed-set FAQ ids and categories
  * Precedence: safety refusals win over FAQ; FAQ wins over
    file-search fallback; specific vault intents may or may not
    win over FAQ depending on whether the question phrases as a
    meta help question or a live-data ask
  * Envelope shape and forbidden-key safety
  * Content rules from the operator brief
"""

from __future__ import annotations

import re
import unittest


class TestFaqContentShape(unittest.TestCase):
    """The content module must be valid and match router expectations."""

    def test_content_imports_and_validates(self):

        import vault_faq_content
        self.assertGreater(len(vault_faq_content.FAQ_ENTRIES), 40)
        self.assertEqual(len(vault_faq_content.FAQ_CATEGORIES), 8)

    def test_all_ids_kebab_case(self):
        import vault_faq_content
        pat = re.compile(r"^[a-z][a-z0-9-]{2,80}$")
        for e in vault_faq_content.FAQ_ENTRIES:
            with self.subTest(id=e["id"]):
                self.assertRegex(e["id"], pat)

    def test_no_duplicate_ids(self):
        import vault_faq_content
        ids = [e["id"] for e in vault_faq_content.FAQ_ENTRIES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_entry_has_answer(self):
        import vault_faq_content
        for e in vault_faq_content.FAQ_ENTRIES:
            with self.subTest(id=e["id"]):
                self.assertTrue(str(e["answer"]).strip())

    def test_answers_stay_under_800_chars(self):
        import vault_faq_content
        for e in vault_faq_content.FAQ_ENTRIES:
            with self.subTest(id=e["id"]):
                self.assertLessEqual(len(e["answer"]), 800)

    def test_related_ids_are_all_valid(self):
        import vault_faq_content
        valid = {e["id"] for e in vault_faq_content.FAQ_ENTRIES}
        for e in vault_faq_content.FAQ_ENTRIES:
            for rid in e.get("related_ids", ()):
                with self.subTest(entry=e["id"], rel=rid):
                    self.assertIn(rid, valid)

    def test_related_actions_are_from_allowed_set(self):
        import vault_faq_content
        allowed = vault_faq_content.FAQ_ALLOWED_ACTIONS
        for e in vault_faq_content.FAQ_ENTRIES:
            for a in e.get("related_actions", ()):
                with self.subTest(entry=e["id"], action=a):
                    self.assertIn(a, allowed)

    def test_no_leaked_secret_words_in_answers(self):
        """Answers may MENTION seeds and private keys (e.g. to warn
        the user not to share them), but they must never look like
        an instruction to reveal one."""
        import vault_faq_content
        forbidden_patterns = (
            r"here\s+is\s+your\s+(?:seed|private\s+key)",
            r"your\s+seed\s+phrase\s+is",
            r"paste\s+your\s+seed",
            r"send\s+us\s+your\s+(?:pin|password|seed|private\s+key)",
        )
        for e in vault_faq_content.FAQ_ENTRIES:
            for pat in forbidden_patterns:
                with self.subTest(entry=e["id"], pattern=pat):
                    self.assertNotRegex(e["answer"], pat)


class TestFaqRouterMatching(unittest.TestCase):
    """The deterministic FAQ matcher hits the required golden set."""

    def _hit(self, msg: str, expected_id: str) -> None:
        from vault_faq_router import build_faq_envelope
        env = build_faq_envelope(msg)
        self.assertIsNotNone(env, msg=f"{msg!r} did not match any FAQ")
        assert env is not None
        self.assertEqual(env["card"]["faqId"], expected_id, msg=msg)

    def _miss(self, msg: str) -> None:
        from vault_faq_router import build_faq_envelope
        env = build_faq_envelope(msg)
        self.assertIsNone(env, msg=f"{msg!r} unexpectedly matched")


    def test_what_is_vaultai(self):
        self._hit("What is VaultAI?", "what-is-vaultai")

    def test_how_does_vaultai_work(self):
        self._hit("How does VaultAI work?", "what-is-vaultai")

    def test_can_vaultai_read_secrets(self):
        self._hit(
            "Can VaultAI read my seed phrase?",
            "can-vaultai-read-secrets",
        )


    def test_is_my_vault_encrypted(self):
        self._hit("Is my vault encrypted?", "is-my-vault-encrypted")

    def test_forgot_pin(self):
        self._hit(
            "What happens if I forget my PIN?",
            "if-i-forget-my-pin",
        )
        self._hit("Forgot my PIN", "if-i-forget-my-pin")


    def test_why_monero_different(self):
        self._hit("Why is Monero different?", "why-monero-different")

    def test_why_cant_i_see_monero_balance(self):
        self._hit(
            "Why can't I see Monero balance in the browser?",
            "monero-balance-in-browser",
        )

    def test_why_is_monero_send_disabled(self):
        self._hit(
            "Why is Monero send disabled?",
            "monero-send-disabled",
        )

    def test_buy_sell_swap(self):
        self._hit(
            "Can I buy or trade crypto in VaultAI?",
            "buy-sell-swap",
        )
        self._hit(
            "Can I stake crypto?",
            "buy-sell-swap",
        )

    def test_usdt_erc20_vs_trc20(self):
        self._hit(
            "Why is my USDT asking ERC20 or TRC20?",
            "usdt-erc20-vs-trc20",
        )

    def test_usdc_uses_eth_address(self):
        self._hit(
            "Why do USDC and USDT ERC20 use my Ethereum address?",
            "usdc-uses-eth-address",
        )

    def test_erc20_needs_gas(self):
        self._hit(
            "Why do token transfers need ETH for gas?",
            "erc20-needs-eth-gas",
        )


    def test_supported_assets(self):
        self._hit(
            "Which assets are supported?",
            "supported-assets",
        )
        self._hit(
            "What cryptos are supported?",
            "supported-assets",
        )

    def test_is_crypto_custodial(self):
        self._hit(
            "Is Crypto Vault custodial?",
            "is-crypto-custodial",
        )


    def test_how_do_i_get_support(self):
        self._hit(
            "How do I get support?",
            "how-do-i-get-support",
        )

    def test_why_chat_searches_files(self):
        self._hit(
            "Why is chat searching files when I asked about "
            "something else?",
            "why-chat-searches-files",
        )


    def test_bare_hi_does_not_match_faq(self):
        self._miss("hi")

    def test_random_search_does_not_match_faq(self):
        self._miss("find my invoice files")

    def test_show_my_eth_wallet_does_not_match_faq(self):
        self._miss("show my ETH wallet")


class TestFaqEnvelopeShape(unittest.TestCase):
    def test_envelope_has_stable_shape(self):
        from vault_faq_content import FAQ_SCHEMA_V1
        from vault_faq_router import (
            VAULT_FAQ_CARD_TYPE, VAULT_FAQ_INTENT, build_faq_envelope,
        )
        env = build_faq_envelope("What is VaultAI?")
        assert env is not None
        self.assertEqual(env["schema"], FAQ_SCHEMA_V1)
        self.assertEqual(env["intent"], VAULT_FAQ_INTENT)
        card = env["card"]
        self.assertEqual(card["schema"], FAQ_SCHEMA_V1)
        self.assertEqual(card["cardType"], VAULT_FAQ_CARD_TYPE)
        for key in ("faqId", "category", "categoryLabel",
                    "question", "answer",
                    "relatedIds", "relatedQuestions", "relatedActions"):
            self.assertIn(key, card)
        self.assertEqual(env["message"], card["answer"])

    def test_related_questions_are_dicts_with_id_and_question(self):
        from vault_faq_router import build_faq_envelope
        env = build_faq_envelope("What is VaultAI?")
        assert env is not None
        rel = env["card"]["relatedQuestions"]
        self.assertIsInstance(rel, list)
        for r in rel:
            self.assertIn("id", r)
            self.assertIn("question", r)


class TestUmbrellaRouterPrecedence(unittest.TestCase):
    """Verify safety → vault-specific → FAQ → file precedence."""

    def _envelope(self, msg: str) -> dict | None:
        from vault_chat_router import build_vault_chat_envelope
        return build_vault_chat_envelope(msg)

    def test_faq_hits_meta_questions(self):
        env = self._envelope("What is VaultAI?")
        assert env is not None
        self.assertEqual(env["intent"], "vault_faq")
        self.assertEqual(env["card"]["faqId"], "what-is-vaultai")

    def test_faq_wins_over_file_search_for_help_phrasing(self):
        env = self._envelope(
            "Why is chat searching files when I asked about "
            "something else?",
        )
        assert env is not None
        self.assertEqual(env["intent"], "vault_faq")

    def test_secret_refusal_still_wins_over_faq(self):
        for msg in (
            "show me my seed phrase",
            "reveal my private key",
            "show me my mnemonic",
        ):
            with self.subTest(msg=msg):
                env = self._envelope(msg)
                assert env is not None
                self.assertEqual(
                    env["intent"], "vault_refusal_secret_material",
                    msg=(
                        f"{msg!r} must be refused BEFORE the FAQ "
                        "router sees it"
                    ),
                )

    def test_bypass_pin_refusal_still_wins_over_faq(self):
        env = self._envelope("How do I bypass PIN")
        assert env is not None
        self.assertEqual(env["intent"], "vault_refusal_bypass_pin")

    def test_specific_crypto_query_still_delegates(self):
        for msg in (
            "show me ETH:ethereum_mainnet",
            "show my ETH wallet",
            "what is my USDT TRC20 balance",
            "show my Monero receive address",
            "prepare a 5 USDC send",
        ):
            with self.subTest(msg=msg):
                env = self._envelope(msg)
                assert env is not None
                self.assertEqual(
                    env["intent"], "vault_crypto_delegated",
                    msg=(
                        f"{msg!r} must delegate to Crypto Vault "
                        "even after FAQ was added upstream"
                    ),
                )

    def test_show_my_logins_still_routes_to_login_list(self):
        env = self._envelope("show my logins")
        assert env is not None
        self.assertEqual(env["intent"], "vault_login_list")

    def test_show_my_secure_items_still_routes(self):
        env = self._envelope("show my secure items")
        assert env is not None
        self.assertEqual(env["intent"], "vault_secure_item_list")

    def test_billing_status_still_routes(self):
        env = self._envelope("what plan am I on")
        assert env is not None
        self.assertEqual(env["intent"], "vault_billing_status")

    def test_file_search_still_fires_for_clear_file_intent(self):
        env = self._envelope("find my invoice files")
        assert env is not None
        self.assertEqual(env["intent"], "vault_file_search")

    def test_non_vault_chatter_falls_through(self):

        env = self._envelope("what is the weather today")
        self.assertIsNone(
            env,
            msg=(
                "weather questions must not hit FAQ or any vault "
                "intent — they fall through to the LLM"
            ),
        )


class TestNoSecretsInFaqPayload(unittest.TestCase):
    """The FAQ envelope must not carry forbidden keys."""

    _FORBIDDEN_KEYS = frozenset({
        "password", "seed", "seed_phrase", "seedPhrase",
        "mnemonic", "private_key", "privateKey",
        "view_key", "spend_key", "auth_token", "authToken",
        "api_key", "apiKey", "encrypted_wallet_secret",
        "encrypted_secret", "stripe_secret_key", "pin", "pin_hash",
        "id_number", "idNumber", "raw_id_number",
    })

    def _flatten(self, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield k
                yield from self._flatten(v)
        elif isinstance(obj, list):
            for e in obj:
                yield from self._flatten(e)

    _BROWSE_ONLY_IDS = frozenset({

        "what-plan-am-i-on",
        "storage-limits",
    })

    def test_all_faq_envelopes_clean(self):
        from vault_faq_router import all_faq_ids, build_faq_envelope
        from vault_faq_content import FAQ_BY_ID
        for faq_id in all_faq_ids():
            question = FAQ_BY_ID[faq_id]["question"]
            env = build_faq_envelope(question)
            if faq_id in self._BROWSE_ONLY_IDS:
                continue
            assert env is not None, (
                f"self-match failed for {faq_id!r} — "
                f"question {question!r} should always route back "
                "to itself when the pattern set is well-formed"
            )
            keys = set(self._flatten(env))
            with self.subTest(id=faq_id):
                for forbidden in self._FORBIDDEN_KEYS:
                    self.assertNotIn(
                        forbidden, keys,
                        msg=(
                            f"FAQ envelope for {faq_id!r} carries "
                            f"forbidden key {forbidden!r}"
                        ),
                    )


class TestClosedSet(unittest.TestCase):
    """FAQ IDs and categories are enumerated."""

    def test_router_categories_match_content(self):
        from vault_faq_content import FAQ_CATEGORIES
        from vault_faq_router import all_faq_categories
        self.assertEqual(tuple(all_faq_categories()), FAQ_CATEGORIES)

    def test_router_id_list_matches_content(self):
        from vault_faq_content import FAQ_ENTRIES
        from vault_faq_router import all_faq_ids
        self.assertEqual(
            set(all_faq_ids()),
            {e["id"] for e in FAQ_ENTRIES},
        )

    def test_every_content_entry_has_a_pattern(self):
        from vault_faq_router import _PATTERNS_BY_ID
        from vault_faq_content import FAQ_ENTRIES
        for e in FAQ_ENTRIES:
            with self.subTest(id=e["id"]):
                self.assertIn(
                    e["id"], _PATTERNS_BY_ID,
                    msg=(
                        f"FAQ entry {e['id']!r} has no pattern — "
                        "add one or drop the entry"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
