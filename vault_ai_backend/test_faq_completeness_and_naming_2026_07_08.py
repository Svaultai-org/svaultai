"""Regression tests for FAQ completeness + assistant-name cleanup.

Covers:

  * Part A — every FAQ question the operator brief requires is
    answered inside the chat pipeline (either via vault_faq or via
    a specific vault card that answers the same question with live
    data — billing_status, storage_usage, crypto_delegated).
  * Part B — FAQ precedence: safety-refusal > FAQ > file-search;
    file-search never catches FAQ/help/product questions.
  * Part D — no "Aisha" in generic product copy.
  * Part E — every FAQ entry has at least one matcher pattern.
  * Part F — the FAQ card carries the safe support note copy.
  * Part G items 3, 4, 7, 8, 9, 10, 11, 12, 13.
"""

from __future__ import annotations


def test_delinquent_inheritance_question_answers_billing_condition():
    from vault_faq_router import build_faq_envelope
    from vault_faq_content_i18n import apply_locale_to_faq_envelope

    envelope = build_faq_envelope(
        "What happens to inheritance access if my subscription is delinquent?"
    )
    envelope = apply_locale_to_faq_envelope(envelope, "en")
    assert envelope is not None
    answer = envelope["message"].lower()
    assert "preserved" in answer
    assert "delinquent" in answer
    assert "reactivating" in answer

import re
import unittest
from pathlib import Path


_BACKEND_ROOT = Path(__file__).parent


_BRIEF_QUESTIONS: tuple[str, ...] = (

    "What is VaultAI?",
    "What can I save in VaultAI?",
    "How do I create my vault?",
    "How do I unlock my vault?",
    "What is a trusted device?",
    "What is the difference between files and secure items?",

    "Is my vault encrypted?",
    "Can VaultAI read my saved secrets?",
    "What happens if I forget my PIN?",
    "Can someone else access my vault?",
    "What should I do if I lose my device?",
    "How does local signing work for crypto?",
    "Why should I not share my seed phrase?",

    "How do I upload files?",
    "What file types can I store?",
    "Can I search inside documents?",
    "Can VaultAI summarize my PDF?",
    "Why can't VaultAI find my file?",
    "How do I delete a file?",

    "How do I save a password?",
    "How do I view a saved password?",
    "Why are passwords masked?",
    "How do I create a generated login?",
    "How do I edit or delete a secure item?",
    "Can VaultAI find duplicate logins?",

    "Can I save my passport or driver license?",
    "Are ID numbers hidden by default?",
    "Can VaultAI remind me about expiration dates?",
    "How do I search my ID documents?",

    "What is Crypto Vault?",
    "Which assets are supported?",
    "Is Crypto Vault custodial?",
    "Can VaultAI move my crypto?",
    "Why do I need a PIN before sending?",
    "Why does USDT have ERC20 and TRC20?",
    "Why does USDC use my Ethereum address?",
    "Why do token transfers need ETH for gas?",
    "Why is Monero different?",
    "Why can't I see my Monero balance in the browser?",
    "Why is Monero send disabled?",
    "Can I buy crypto in VaultAI?",
    "Can I sell crypto in VaultAI?",
    "Can I swap crypto in VaultAI?",
    "Can I trade crypto in VaultAI?",
    "What happens if a provider is unavailable?",
    "Why does my balance say 0?",
    "Can I receive crypto even if balance is 0?",

    "What plan am I on?",
    "How much storage do I have?",
    "What happens if I exceed storage?",
    "How do I upgrade storage?",
    "How do I cancel or manage subscription?",
    "Why does checkout open?",
    "How is storage calculated?",

    "Why is my balance unavailable?",
    "Why is my file not showing?",
    "Why is chat searching files when I asked about something else?",
    "Why does Monero say desktop app required?",
    "Why does TRON say provider unavailable?",
    "Why is subscription status checking?",
    "How do I refresh my vault?",
    "How do I report a bug?",
    "How do I get support?",
)


_ACCEPTED_INTENTS_FOR_BRIEF_QUESTIONS: frozenset[str] = frozenset({

    "vault_faq",


    "vault_billing_status",
    "vault_storage_usage",
    "vault_crypto_delegated",
})


class TestPartACoverage(unittest.TestCase):
    """Every question the operator brief lists returns a usable
    answer in the chat pipeline — never file-search, never None."""

    def test_every_brief_question_routes_to_a_helpful_intent(self):
        from vault_chat_router import build_vault_chat_envelope
        failures: list[tuple[str, str]] = []
        for q in _BRIEF_QUESTIONS:
            env = build_vault_chat_envelope(q)
            intent = env["intent"] if isinstance(env, dict) else "None"
            if intent not in _ACCEPTED_INTENTS_FOR_BRIEF_QUESTIONS:
                failures.append((q, intent))
        self.assertEqual(
            failures, [],
            msg=(
                "The following brief-mandated questions did not "
                "route to FAQ or a specific vault card. File-"
                "search must never catch help questions:\n"
                + "\n".join(
                    f"  {q!r} → {i}" for q, i in failures
                )
            ),
        )

    def test_no_brief_question_falls_to_file_search(self):
        from vault_chat_router import build_vault_chat_envelope
        leaked = []
        for q in _BRIEF_QUESTIONS:
            env = build_vault_chat_envelope(q)
            if isinstance(env, dict) and env.get("intent") == \
                    "vault_file_search":
                leaked.append(q)
        self.assertEqual(
            leaked, [],
            msg=(
                "These help questions leaked to file_search: "
                + repr(leaked)
            ),
        )


class TestSafetyRefusalPrecedence(unittest.TestCase):
    """Safety refusals still win over FAQ for clear reveal /
    bypass intents."""

    def _route(self, msg: str) -> str:
        from vault_chat_router import build_vault_chat_envelope
        env = build_vault_chat_envelope(msg)
        return env["intent"] if isinstance(env, dict) else "None"

    def test_show_seed_phrase_refused(self):
        self.assertEqual(
            self._route("Show me my seed phrase"),
            "vault_refusal_secret_material",
        )

    def test_reveal_private_key_refused(self):
        self.assertEqual(
            self._route("Reveal my private key"),
            "vault_refusal_secret_material",
        )

    def test_show_mnemonic_refused(self):
        self.assertEqual(
            self._route("Show me my mnemonic"),
            "vault_refusal_secret_material",
        )

    def test_bypass_pin_refused(self):
        self.assertEqual(
            self._route("How do I bypass PIN"),
            "vault_refusal_bypass_pin",
        )

    def test_export_all_refused(self):
        self.assertEqual(
            self._route("Export my whole vault"),
            "vault_refusal_export_all",
        )


class TestEducationalSecretQuestionsSkipRefusal(unittest.TestCase):
    """Educational meta questions that mention a secret keyword
    are NOT refusals — they route to FAQ."""

    def _route(self, msg: str) -> tuple[str, str]:
        from vault_chat_router import build_vault_chat_envelope
        env = build_vault_chat_envelope(msg)
        if not isinstance(env, dict):
            return ("None", "")
        return (env["intent"], env["card"].get("faqId", ""))

    def test_why_should_i_not_share_seed_hits_faq(self):
        intent, faq_id = self._route(
            "Why should I not share my seed phrase?",
        )
        self.assertEqual(intent, "vault_faq")
        self.assertEqual(faq_id, "never-share-seed")

    def test_why_shouldnt_i_share_seed_hits_faq(self):
        intent, faq_id = self._route(
            "Why shouldn't I share my seed phrase?",
        )
        self.assertEqual(intent, "vault_faq")

    def test_how_does_local_signing_work_hits_faq(self):
        intent, faq_id = self._route(
            "How does local signing work for crypto?",
        )
        self.assertEqual(intent, "vault_faq")
        self.assertEqual(faq_id, "how-local-signing-works")


class TestFileSearchStillWorks(unittest.TestCase):
    """Clear file requests must still hit file-search."""

    def _route(self, msg: str) -> str:
        from vault_chat_router import build_vault_chat_envelope
        env = build_vault_chat_envelope(msg)
        return env["intent"] if isinstance(env, dict) else "None"

    def test_find_my_invoice_files_hits_file_search(self):
        self.assertEqual(
            self._route("find my invoice files"),
            "vault_file_search",
        )

    def test_search_my_documents_hits_file_search(self):
        self.assertEqual(
            self._route("search my documents"),
            "vault_file_search",
        )

    def test_show_my_uploaded_files_hits_file_search(self):
        self.assertEqual(
            self._route("show my files uploaded this week"),
            "vault_file_search",
        )


class TestNonVaultChatterFallsThrough(unittest.TestCase):
    def test_tell_me_a_joke_returns_none(self):
        from vault_chat_router import build_vault_chat_envelope
        env = build_vault_chat_envelope("Tell me a joke")
        self.assertIsNone(
            env,
            msg=(
                "Non-vault questions must fall through to the "
                "LLM (envelope=None) — jokes are not FAQ or vault "
                "intents"
            ),
        )

    def test_weather_returns_none(self):
        from vault_chat_router import build_vault_chat_envelope
        self.assertIsNone(
            build_vault_chat_envelope("what is the weather today"),
        )


class TestNoAishaInGenericCopy(unittest.TestCase):
    """Backend product copy must not use 'Aisha' as a generic
    assistant name."""

    _BACKEND_FILES: tuple[str, ...] = (
        "vault_faq_content.py",
        "vault_faq_router.py",
        "vault_chat_router.py",
        "crypto_vault_chat_control.py",
    )

    def test_no_generic_aisha_in_backend_copy(self):

        offenders: list[tuple[str, int, str]] = []
        for rel in self._BACKEND_FILES:
            path = _BACKEND_ROOT / rel
            if not path.exists():
                continue
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1,
            ):
                if re.search(r"\bAisha\b", line, re.IGNORECASE):
                    offenders.append((rel, lineno, line.strip()))
        self.assertEqual(
            offenders, [],
            msg=(
                "'Aisha' appears in backend product copy. Use "
                "'VaultAI Chat' / 'Ask VaultAI' / 'the "
                "assistant' instead:\n"
                + "\n".join(
                    f"  {rel}:{n}: {l}" for rel, n, l in offenders
                )
            ),
        )

    def test_no_faq_envelope_carries_aisha(self):

        from vault_faq_router import (
            all_faq_ids, build_faq_envelope,
        )
        from vault_faq_content import FAQ_BY_ID
        offenders = []
        for faq_id in all_faq_ids():
            question = FAQ_BY_ID[faq_id]["question"]
            env = build_faq_envelope(question)
            if not isinstance(env, dict):
                continue
            answer = env["card"].get("answer", "")
            if re.search(r"\bAisha\b", answer, re.IGNORECASE):
                offenders.append(faq_id)
        self.assertEqual(offenders, [])


class TestFaqMatcherCoverage(unittest.TestCase):
    """Part E — every FAQ entry has at least one matcher pattern."""

    def test_every_content_entry_has_a_pattern(self):
        from vault_faq_content import FAQ_ENTRIES
        from vault_faq_router import _PATTERNS_BY_ID
        missing = [
            e["id"] for e in FAQ_ENTRIES
            if e["id"] not in _PATTERNS_BY_ID
        ]
        self.assertEqual(
            missing, [],
            msg=(
                "These FAQ ids have no matcher — chat cannot "
                "reach them: " + repr(missing)
            ),
        )

    def test_router_and_content_id_sets_align(self):
        from vault_faq_content import FAQ_ENTRIES
        from vault_faq_router import _PATTERNS_BY_ID
        self.assertEqual(
            {e["id"] for e in FAQ_ENTRIES},
            set(_PATTERNS_BY_ID.keys()),
        )


class TestFaqAnswersHonorContentRules(unittest.TestCase):
    """Part F — no fake customer service promise, no reveal
    instruction, forgot-PIN answer is honest about recovery."""

    def test_no_customer_service_promise(self):
        from vault_faq_content import FAQ_ENTRIES
        for e in FAQ_ENTRIES:
            with self.subTest(id=e["id"]):
                self.assertNotRegex(
                    e["answer"],
                    r"(?:24/7|24-7|our\s+support\s+team|call\s+us|"
                    r"live\s+agent|our\s+agents)",
                    msg=(
                        f"{e['id']!r} answer promises live "
                        "customer support that does not exist"
                    ),
                )

    def test_forgot_pin_is_honest_about_recovery(self):
        from vault_faq_content import FAQ_BY_ID
        answer = FAQ_BY_ID["forgot-pin"]["answer"].lower()

        self.assertIn("cannot reset or recover a forgotten pin", answer)
        self.assertIn("support", answer)

    def test_no_reveal_instruction_leaks(self):
        from vault_faq_content import FAQ_ENTRIES
        for e in FAQ_ENTRIES:
            with self.subTest(id=e["id"]):
                for bad in (
                    r"paste\s+your\s+seed",
                    r"send\s+us\s+your\s+(?:pin|password|seed)",
                    r"here\s+is\s+your\s+(?:seed|private\s+key)",
                ):
                    self.assertNotRegex(
                        e["answer"], bad,
                        msg=(
                            f"{e['id']!r} answer contains "
                            "reveal-instruction pattern: " + bad
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
