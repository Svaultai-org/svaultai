from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

import _generate_frontend_faq_i18n as generator
from vault_faq_content import FAQ_BY_ID, FAQ_ENTRIES
from vault_faq_content_i18n import get_localized_faq
from vault_faq_router import build_faq_envelope


ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "vault_ai_frontend" / "lib" / "help_center_content.dart"


class TestBackendFaqAlignment(unittest.TestCase):
    def test_curated_count_and_nonempty_copy(self):
        self.assertEqual(len(FAQ_ENTRIES), 25)
        self.assertTrue(all(e["question"].strip() and e["answer"].strip()
                            for e in FAQ_ENTRIES))

    def test_no_qa_provider_or_testnet_copy(self):
        copy = "\n".join(
            f"{e['question']} {e['answer']}" for e in FAQ_ENTRIES
        ).lower()
        forbidden = (
            "that is a bug", "specific phrase", "provider unavailable",
            "testnet", "debug", "qa", ".py", ".dart",
            "desktop app required", "send disabled", "no live customer",
        )
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, copy)

    def test_required_trust_copy(self):
        copy = " ".join(e["answer"] for e in FAQ_ENTRIES).lower()
        for phrase in (
            "master key", "developer backdoor", "cannot open your vault",
            "cannot browse protected uploads", "saved credential values",
            "six months", "logging in resets", "subscribed vaults are not",
            "non-custodial", "explicitly approve", "vaultai@svaultai.com",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, copy)

    def test_key_answers_match_canonical_frontend_wording(self):
        frontend = FRONTEND.read_text(encoding="utf-8")
        for faq_id in (
            "what-is-svaultai", "inactive-unsubscribed-vault",
            "wallet-non-custodial",
        ):
            answer = FAQ_BY_ID[faq_id]["answer"]
            self.assertIn(answer, frontend)

    def test_every_question_routes_to_itself(self):
        for entry in FAQ_ENTRIES:
            with self.subTest(faq_id=entry["id"]):
                envelope = build_faq_envelope(entry["question"])
                self.assertIsNotNone(envelope)
                self.assertEqual(envelope["card"]["faqId"], entry["id"])

    def test_unreviewed_locales_fall_back_to_english(self):
        for locale in ("ar", "fr", "es", "ja", "ko", "zh"):
            localized = get_localized_faq("can-staff-open-vault", locale)
            self.assertEqual(localized["answer"],
                             FAQ_BY_ID["can-staff-open-vault"]["answer"])

    def test_retired_generator_cannot_overwrite_frontend(self):
        targets = (generator.FRONTEND_CANONICAL, generator.FRONTEND_I18N)
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in targets}
        generator.main()
        after = {p: hashlib.sha256(p.read_bytes()).digest() for p in targets}
        self.assertEqual(before, after)

    def test_support_address_is_exact(self):
        answer = FAQ_BY_ID["contact-support"]["answer"]
        self.assertEqual(re.findall(r"[\w.+-]+@[\w.-]+[a-z]", answer),
                         ["vaultai@svaultai.com"])


if __name__ == "__main__":
    unittest.main()
