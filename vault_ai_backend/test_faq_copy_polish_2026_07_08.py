"""Regression tests for the FAQ copy polish pass.

Locks in:
  * Part A — "What is VaultAI?" uses the physical vault/safe
    analogy and enumerates the record kinds users can keep.
  * Part B — "What can I save?" no longer says "wallet records"
    (which was a confusing internal-plumbing term) and instead
    calls internal wallet records out as Crypto-Vault-managed.
  * Part C — "How do I create my vault?" does NOT tell users to
    sign up with an email (VaultAI does not use email sign-up).
  * Part D — "How do I unlock my vault?" uses accurate wording
    without implying email login.
  * Part E — no FAQ answer overpromises security ("hackers
    won't know", "impossible to hack", "guaranteed safe",
    "anonymous vault", "no one can ever access", etc).
"""

from __future__ import annotations

import re
import unittest


class TestPartAWhatIsVaultAI(unittest.TestCase):
    """Physical-vault-analogy explanation of VaultAI."""

    def _answer(self) -> str:
        from vault_faq_content import FAQ_BY_ID
        return FAQ_BY_ID["what-is-vaultai"]["answer"]

    def test_uses_physical_vault_analogy(self):
        lower = self._answer().lower()

        markers = ("bank vault", "safe at home")
        self.assertTrue(
            any(m in lower for m in markers),
            msg=(
                "answer must include a physical vault / safe "
                "analogy so non-technical users get the concept"
            ),
        )

    def test_lists_kinds_of_records_user_can_keep(self):
        lower = self._answer().lower()

        for kind in (
            "files", "documents", "photos", "videos", "audio",
            "passwords", "secure notes", "id documents",
            "crypto vault",
        ):
            with self.subTest(kind=kind):
                self.assertIn(kind, lower)

    def test_contrasts_with_scattered_password_storage(self):
        lower = self._answer().lower()
        self.assertTrue(
            any(
                pat in lower
                for pat in (
                    "emails, notes, screenshots",
                    "random folders",
                    "instead of saving",
                )
            ),
            msg=(
                "answer should contrast VaultAI with saving "
                "passwords in scattered places"
            ),
        )

    def test_does_not_overpromise(self):
        lower = self._answer().lower()
        for forbidden in (
            "hackers won", "hackers will never",
            "impossible to hack", "guaranteed safe",
            "anonymous vault", "nobody will know",
            "no one can ever access", "unhackable",
            "perfect security", "perfectly safe",
            "completely anonymous",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lower)


class TestPartBWhatCanISave(unittest.TestCase):

    def _answer(self) -> str:
        from vault_faq_content import FAQ_BY_ID
        return FAQ_BY_ID["what-can-i-save"]["answer"]

    def test_does_not_say_wallet_records_as_user_secure_items(self):

        lower = self._answer().lower()
        self.assertNotIn(
            "crypto vault wallet records", lower,
            msg=(
                "'wallet records' as a user-facing category "
                "was the previous confusing wording — the fix "
                "must not restore it"
            ),
        )

    def test_calls_out_internal_wallet_records_separately(self):
        lower = self._answer().lower()
        self.assertIn(
            "internal wallet records", lower,
            msg=(
                "answer must explicitly clarify that internal "
                "wallet records are NOT normal secure items"
            ),
        )
        self.assertIn(
            "not shown as normal secure items", lower,
        )

    def test_lists_photos_videos_audio_as_savable(self):

        lower = self._answer().lower()
        for k in ("photos", "videos", "audio"):
            with self.subTest(k=k):
                self.assertIn(k, lower)

    def test_mentions_crypto_vault_assets(self):
        lower = self._answer().lower()
        self.assertIn("crypto vault assets", lower)


class TestPartCHowDoICreateMyVault(unittest.TestCase):

    def _answer(self) -> str:
        from vault_faq_content import FAQ_BY_ID
        return FAQ_BY_ID["how-do-i-create-my-vault"]["answer"]

    def test_does_not_claim_email_sign_up(self):
        lower = self._answer().lower()

        forbidden_patterns = (
            r"sign\s+up\s+with\s+an\s+email",
            r"sign\s+up\s+with\s+your\s+email",
            r"register\s+with\s+(?:an\s+)?email",
            r"email\s+registration",
        )
        for pat in forbidden_patterns:
            with self.subTest(pat=pat):
                self.assertIsNone(
                    re.search(pat, lower),
                    msg=(
                        f"answer contains email-sign-up wording "
                        f"({pat!r}) but VaultAI does not use "
                        "email sign-up"
                    ),
                )

    def test_mentions_the_vault_sign_in_flow(self):
        lower = self._answer().lower()
        self.assertIn("sign-in flow", lower)

    def test_mentions_pin(self):
        self.assertIn("PIN", self._answer())

    def test_is_honest_about_recovery(self):
        lower = self._answer().lower()

        self.assertIn(
            "recovery is not available", lower,
            msg=(
                "answer should be honest that recovery may not "
                "be available — do not promise recovery"
            ),
        )


class TestPartDHowDoIUnlockMyVault(unittest.TestCase):

    def _answer(self) -> str:
        from vault_faq_content import FAQ_BY_ID
        return FAQ_BY_ID["how-do-i-unlock-my-vault"]["answer"]

    def test_uses_trusted_device_and_pin(self):
        lower = self._answer().lower()
        self.assertIn("trusted device", lower)
        self.assertIn("pin", lower)

    def test_does_not_claim_email_login(self):
        lower = self._answer().lower()
        for forbidden in (
            "log in with your email", "log in with email",
            "sign in with your email", "sign in with email",
            "email login",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lower)

    def test_notes_that_pin_never_leaves_device_in_plaintext(self):
        lower = self._answer().lower()
        self.assertIn(
            "server never sees your pin in plaintext", lower,
        )


class TestPartENoOverpromisingAcrossAllEntries(unittest.TestCase):
    """No FAQ answer overpromises security anywhere."""

    _FORBIDDEN_PATTERNS: tuple[str, ...] = (
        r"hackers?\s+will\s+never",
        r"hackers?\s+won['’]?t\s+know",
        r"hackers?\s+can['’]?t",
        r"impossible\s+to\s+hack",
        r"guaranteed\s+safe",
        r"anonymous\s+vault",
        r"nobody\s+will\s+know\s+you\s+own",
        r"no\s+one\s+can\s+ever\s+access",
        r"perfectly\s+safe",
        r"unhackable",
        r"completely\s+anonymous",
        r"perfect\s+security",
        r"total\s+privacy",
        r"no\s+one\s+else\s+can\s+ever",
        r"immune\s+to\s+(?:hackers?|attacks?)",
    )

    def test_no_forbidden_phrase_anywhere(self):
        from vault_faq_content import FAQ_ENTRIES
        offenders: list[tuple[str, str]] = []
        for e in FAQ_ENTRIES:
            for pat in self._FORBIDDEN_PATTERNS:
                if re.search(pat, e["answer"], re.IGNORECASE):
                    offenders.append((e["id"], pat))
        self.assertEqual(
            offenders, [],
            msg=(
                "FAQ answers overpromise security:\n"
                + "\n".join(
                    f"  {fid}: matched pattern {pat!r}"
                    for fid, pat in offenders
                )
            ),
        )


class TestPartFAlignmentAndCharBudget(unittest.TestCase):
    """The 4 rewritten answers stay within the shared 800-char
    budget and remain reachable via the deterministic matcher."""

    _TARGET_IDS: tuple[str, ...] = (
        "what-is-vaultai",
        "what-can-i-save",
        "how-do-i-create-my-vault",
        "how-do-i-unlock-my-vault",
    )

    def test_answers_stay_under_800_chars(self):
        from vault_faq_content import FAQ_BY_ID
        for fid in self._TARGET_IDS:
            with self.subTest(id=fid):
                answer = FAQ_BY_ID[fid]["answer"]
                self.assertLessEqual(
                    len(answer), 800,
                    msg=(
                        f"{fid} answer is {len(answer)} chars, "
                        "over the 800-char per-card budget"
                    ),
                )

    def test_router_still_matches_each_updated_question(self):
        from vault_faq_content import FAQ_BY_ID
        from vault_faq_router import build_faq_envelope
        for fid in self._TARGET_IDS:
            with self.subTest(id=fid):
                q = FAQ_BY_ID[fid]["question"]
                env = build_faq_envelope(q)
                self.assertIsNotNone(env)
                assert env is not None
                self.assertEqual(env["card"]["faqId"], fid)


if __name__ == "__main__":
    unittest.main()
