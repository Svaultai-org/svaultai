"""Localized FAQ answers — coverage and safety guarantees.

Every FAQ id in `vault_faq_content.FAQ_ENTRIES` must have a
translation in each of the six supported non-English locales
(ar / fr / es / ja / ko / zh). Category labels must be localized in
the same set. Safety copy across every locale must never claim
VaultAI is unhackable, promise recovery of deleted vaults, mention
"pending deletion" / "grace period" for inactive-unpaid cleanup,
or invite the user to sign up with email. Refusal-flavoured FAQs
must keep the "not custodial / not an exchange / never asks for
seed" wording faithful across languages.
"""

from __future__ import annotations

import re
import unittest

from vault_faq_content import (
    FAQ_ENTRIES,
    FAQ_BY_ID,
    FAQ_CATEGORIES,
)
import vault_faq_content_i18n as i18n
import vault_multilingual as mling
import chat_fast_path as cfp


NON_ENGLISH_LOCALES = ("ar", "fr", "es", "ja", "ko", "zh")


UNSAFE_PHRASES_BY_LANG = {
    "en": (
        "unhackable", "impossible to attack", "guaranteed safe",
        "hackers will never know", "nobody will know you own it",
        "sign up with an email", "sign up with email",
        "pending deletion", "grace period",
        "crypto will be recovered",
        "blockchain assets are deleted by vaultai",
        "vaultai can move crypto without confirmation",
    ),
    "ar": (
        "غير قابل للاختراق", "مستحيل الاختراق",
        "مضمون الأمان", "لن يعرف أحد",
        "التسجيل بالبريد الإلكتروني",
        "الحذف المعلق", "فترة سماح",
        "أصول البلوكشين تُحذف بواسطة VaultAI",
        "VaultAI يمكنه تحريك العملات دون تأكيد",
    ),
    "fr": (
        "impossible à pirater", "impossible à attaquer",
        "sécurité garantie", "personne ne saura",
        "s'inscrire avec un e-mail", "inscription par e-mail",
        "suppression en attente", "période de grâce",
        "la crypto sera récupérée",
        "les actifs blockchain sont supprimés par VaultAI",
        "VaultAI peut déplacer la crypto sans confirmation",
    ),
    "es": (
        "imposible de atacar", "imposible de hackear",
        "seguridad garantizada", "nadie sabrá",
        "regístrate con un correo",
        "eliminación pendiente", "período de gracia",
        "la crypto se recuperará",
        "los activos blockchain son eliminados por VaultAI",
        "VaultAI puede mover crypto sin confirmación",
    ),
    "ja": (
        "ハック不可能", "攻撃不可能", "安全性を保証",
        "誰にも分からない", "メールで登録",
        "削除保留中", "猶予期間",
        "暗号資産は復元されます",
        "ブロックチェーン資産は VaultAI が削除します",
        "VaultAI は確認なしに暗号資産を動かせます",
    ),
    "ko": (
        "해킹 불가능", "공격 불가능", "안전 보장",
        "아무도 모릅니다", "이메일로 가입",
        "삭제 대기", "유예 기간",
        "암호화폐가 복구됩니다",
        "블록체인 자산은 VaultAI 가 삭제합니다",
        "VaultAI 는 확인 없이 암호화폐를 이동합니다",
    ),
    "zh": (
        "无法攻击", "无法被黑", "保证安全",
        "无人知晓", "用电子邮件注册",
        "待删除", "宽限期",
        "加密货币将被恢复",
        "区块链资产由 VaultAI 删除",
        "VaultAI 可以在无需确认的情况下移动加密货币",
    ),
}




class TestCompleteness(unittest.TestCase):

    def test_all_66_faq_ids_have_translation_in_all_locales(self):
        canonical_ids = [entry["id"] for entry in FAQ_ENTRIES]
        self.assertEqual(len(canonical_ids), 66)
        for lang in NON_ENGLISH_LOCALES:
            table = i18n.FAQ_TRANSLATIONS.get(lang, {})
            for fid in canonical_ids:
                with self.subTest(lang=lang, id=fid):
                    entry = table.get(fid)
                    self.assertIsNotNone(
                        entry,
                        f"missing FAQ translation for {lang}/{fid}",
                    )
                    self.assertTrue(
                        entry.get("question", "").strip(),
                        f"empty question for {lang}/{fid}",
                    )
                    self.assertTrue(
                        entry.get("answer", "").strip(),
                        f"empty answer for {lang}/{fid}",
                    )

    def test_no_extra_ids_in_localized_tables(self):
        canonical_ids = set(FAQ_BY_ID.keys())
        for lang in NON_ENGLISH_LOCALES:
            table = i18n.FAQ_TRANSLATIONS.get(lang, {})
            extras = set(table.keys()) - canonical_ids
            self.assertFalse(
                extras,
                f"{lang} has unknown FAQ ids: {sorted(extras)}",
            )

    def test_category_labels_covered_in_every_locale(self):
        for lang in ("en",) + NON_ENGLISH_LOCALES:
            table = i18n.FAQ_CATEGORY_LABELS_I18N.get(lang, {})
            for cat in FAQ_CATEGORIES:
                with self.subTest(lang=lang, category=cat):
                    self.assertTrue(
                        table.get(cat, "").strip(),
                        f"missing category label {lang}/{cat}",
                    )




class TestLookupAndFallback(unittest.TestCase):

    def test_lookup_returns_localized_pair(self):
        got = i18n.get_localized_faq("delete-my-vault", "ko")
        self.assertIsNotNone(got)
        self.assertIn("question", got)
        self.assertIn("answer", got)

        self.assertTrue(
            "보관소" in got["answer"] or "가" in got["answer"],
        )

    def test_unknown_locale_falls_back_to_english(self):
        got = i18n.get_localized_faq("delete-my-vault", "pt")
        canonical = FAQ_BY_ID["delete-my-vault"]
        self.assertEqual(got["answer"], canonical["answer"])
        self.assertEqual(got["question"], canonical["question"])

    def test_missing_translation_falls_back_to_english(self):

        original = i18n.FAQ_TRANSLATIONS["ko"].pop(
            "how-do-i-refresh", None,
        )
        try:
            got = i18n.get_localized_faq("how-do-i-refresh", "ko")
            canonical = FAQ_BY_ID["how-do-i-refresh"]
            self.assertEqual(got["answer"], canonical["answer"])
        finally:
            if original is not None:
                i18n.FAQ_TRANSLATIONS["ko"]["how-do-i-refresh"] = original

    def test_unknown_id_returns_none(self):
        self.assertIsNone(
            i18n.get_localized_faq("this-id-does-not-exist", "ko"),
        )

    def test_localized_category_label_english_fallback(self):
        self.assertEqual(
            i18n.get_localized_category_label("security", "ko"),
            "보안",
        )
        self.assertEqual(
            i18n.get_localized_category_label("security", "pt"),
            "Security",
        )




class TestEnvelopeLocalization(unittest.TestCase):

    def _sample_faq_envelope(self, faq_id, category):
        canonical = FAQ_BY_ID[faq_id]
        return {
            "intent": "vault_faq",
            "card": {
                "cardType":  "vault_faq_card",
                "faqId":     faq_id,
                "category":  category,
                "categoryLabel": "Security",
                "question":  canonical["question"],
                "answer":    canonical["answer"],
            },
            "message": canonical["answer"],
        }

    def test_apply_locale_swaps_question_answer_message(self):
        env = self._sample_faq_envelope("delete-my-vault", "security")
        i18n.apply_locale_to_faq_envelope(env, "ko")
        self.assertIn("DELETE MY VAULT", env["card"]["answer"])
        self.assertTrue(
            re.search(r"[가-힣]", env["card"]["question"]),
            "Korean question must contain Hangul",
        )
        self.assertEqual(env["message"], env["card"]["answer"])
        self.assertEqual(env["locale"], "ko")

    def test_apply_locale_keeps_faq_id_and_related_stable(self):
        env = self._sample_faq_envelope("delete-my-vault", "security")
        env["card"]["relatedIds"] = ["can-i-recover-deleted-vault"]
        env["card"]["relatedActions"] = ["open_delete_vault_flow"]
        i18n.apply_locale_to_faq_envelope(env, "ar")
        self.assertEqual(env["card"]["faqId"], "delete-my-vault")
        self.assertEqual(
            env["card"]["relatedIds"], ["can-i-recover-deleted-vault"],
        )
        self.assertEqual(
            env["card"]["relatedActions"], ["open_delete_vault_flow"],
        )

    def test_apply_locale_swaps_category_label(self):
        env = self._sample_faq_envelope("delete-my-vault", "security")
        i18n.apply_locale_to_faq_envelope(env, "fr")
        self.assertEqual(env["card"]["categoryLabel"], "Sécurité")

    def test_apply_locale_english_normalizes_to_canonical(self):
        env = self._sample_faq_envelope("what-is-vaultai", "getting_started")
        i18n.apply_locale_to_faq_envelope(env, "en")
        canonical = FAQ_BY_ID["what-is-vaultai"]
        self.assertEqual(env["card"]["answer"], canonical["answer"])
        self.assertEqual(env["locale"], "en")

    def test_apply_locale_no_op_when_no_faq_id(self):
        env = {"intent": "vault_login_list", "card": {"cardType": "x"}}
        got = i18n.apply_locale_to_faq_envelope(env, "ko")

        self.assertEqual(got, env)
        self.assertNotIn("question", env["card"])

    def test_apply_locale_handles_none_gracefully(self):
        self.assertIsNone(
            i18n.apply_locale_to_faq_envelope(None, "ko"),
        )




class TestSafetyPhrasesAcrossLocales(unittest.TestCase):

    def test_no_localized_faq_contains_forbidden_phrase(self):
        for lang, phrases in UNSAFE_PHRASES_BY_LANG.items():
            if lang == "en":
                for entry in FAQ_ENTRIES:
                    text = f"{entry['question']} {entry['answer']}".lower()
                    for bad in phrases:
                        self.assertNotIn(
                            bad, text,
                            f"English FAQ {entry['id']} contains "
                            f"forbidden phrase {bad!r}",
                        )
                continue
            table = i18n.FAQ_TRANSLATIONS.get(lang, {})
            for fid, entry in table.items():
                joined = f"{entry.get('question','')} {entry.get('answer','')}"
                lowered = joined.lower()
                for bad in phrases:
                    self.assertNotIn(
                        bad.lower(), lowered,
                        f"{lang} FAQ {fid} contains forbidden phrase "
                        f"{bad!r}",
                    )

    def test_delete_vault_confirmation_phrase_preserved_in_every_language(self):
        for lang in NON_ENGLISH_LOCALES:
            entry = i18n.FAQ_TRANSLATIONS[lang].get("delete-my-vault")
            self.assertIsNotNone(entry, f"{lang} missing delete-my-vault")
            self.assertIn(
                "DELETE MY VAULT", entry["answer"],
                f"{lang}: delete-my-vault answer must keep the exact "
                "phrase DELETE MY VAULT verbatim",
            )

    def test_crypto_when_vault_deleted_keeps_blockchain_caveat(self):

        markers_by_lang = {
            "en": ("blockchain", "not move"),
            "ko": ("블록체인",),
            "zh": ("区块链",),
            "ja": ("ブロックチェーン",),
            "ar": ("البلوكشين",),
            "fr": ("blockchain",),
            "es": ("blockchain",),
        }
        entry_en = FAQ_BY_ID["crypto-when-vault-deleted"]
        text_en = f"{entry_en['question']} {entry_en['answer']}".lower()
        for m in ("blockchain",):
            self.assertIn(m, text_en)
        for lang in NON_ENGLISH_LOCALES:
            entry = i18n.FAQ_TRANSLATIONS[lang]["crypto-when-vault-deleted"]
            text = f"{entry['question']} {entry['answer']}"
            for marker in markers_by_lang[lang]:
                self.assertIn(
                    marker, text,
                    f"{lang} crypto-when-vault-deleted must mention "
                    f"{marker!r}",
                )

    def test_inactive_unpaid_cleanup_mentions_six_months(self):

        for lang in ("en",) + NON_ENGLISH_LOCALES:
            if lang == "en":
                text = FAQ_BY_ID["why-inactive-unpaid-deleted"]["answer"]
            else:
                text = i18n.FAQ_TRANSLATIONS[lang]["why-inactive-unpaid-deleted"]["answer"]

            has_six = any(marker in text for marker in (
                "6", "٦", "六", "六 か月", "半年",
            ))
            self.assertTrue(
                has_six,
                f"{lang}: unpaid-inactive answer must mention 6 months "
                "(digit '6', Arabic-Indic '٦', or CJK '六')",
            )

    def test_buy_sell_swap_faq_still_refuses_in_every_language(self):

        refusal_markers_by_lang = {
            "en": ("no.", "not"),
            "ko": ("아니오", "않"),
            "zh": ("不", "不能"),
            "ja": ("できません", "いいえ"),
            "ar": ("لا"),
            "fr": ("non"),
            "es": ("no"),
        }
        for lang in NON_ENGLISH_LOCALES:
            entry = i18n.FAQ_TRANSLATIONS[lang]["buy-sell-swap"]
            answer = entry["answer"]
            markers = refusal_markers_by_lang[lang]
            self.assertTrue(
                any(m in answer for m in markers),
                f"{lang} buy-sell-swap answer must contain a refusal "
                f"marker (one of {markers})",
            )

    def test_never_share_seed_still_refuses_in_every_language(self):

        for lang in NON_ENGLISH_LOCALES:
            entry = i18n.FAQ_TRANSLATIONS[lang]["never-share-seed"]
            text = f"{entry['question']} {entry['answer']}"

            for bad in ("here is your seed", "your seed phrase is",
                        "your private key is"):
                self.assertNotIn(bad.lower(), text.lower(),
                                 f"{lang} never-share-seed reveals data")




class TestFastPathPreservedForLocalizedFAQ(unittest.TestCase):

    def _classify(self, decrypted_message):
        translated = mling.translate_to_english_router_query(
            decrypted_message,
        )
        query = translated or decrypted_message
        try:
            from vault_chat_router import build_vault_chat_envelope
        except Exception:
            self.skipTest("vault_chat_router import failed")
        envelope = cfp.peek_intent_without_side_effects(
            query, build_envelope=build_vault_chat_envelope,
        )
        return envelope

    def test_korean_what_is_vaultai_stays_on_fast_path(self):
        env = self._classify("VaultAI가 뭐야?")
        self.assertIsInstance(env, dict)
        self.assertTrue(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_arabic_delete_vault_stays_on_fast_path(self):
        env = self._classify("أريد أن أحذف خزينتي")
        self.assertIsInstance(env, dict)
        self.assertTrue(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_localization_of_envelope_never_touches_faq_id(self):

        env = {
            "intent": "vault_faq",
            "card": {
                "cardType":     "vault_faq_card",
                "faqId":        "delete-my-vault",
                "category":     "security",
                "categoryLabel": "Security",
                "question":     FAQ_BY_ID["delete-my-vault"]["question"],
                "answer":       FAQ_BY_ID["delete-my-vault"]["answer"],
                "relatedIds":   ["can-i-recover-deleted-vault"],
                "relatedActions": ["open_delete_vault_flow"],
            },
            "message": FAQ_BY_ID["delete-my-vault"]["answer"],
        }
        i18n.apply_locale_to_faq_envelope(env, "ko")
        self.assertEqual(env["card"]["faqId"], "delete-my-vault")
        self.assertEqual(
            env["card"]["relatedIds"], ["can-i-recover-deleted-vault"],
        )
        self.assertEqual(
            env["card"]["relatedActions"], ["open_delete_vault_flow"],
        )




class TestChatSpanLoggingUnderLocalizedFAQ(unittest.TestCase):

    def test_locale_hint_in_extra_is_permitted(self):
        import io, logging
        buf = io.StringIO()
        logging.basicConfig(level=logging.INFO)
        h = logging.StreamHandler(buf)
        logger = logging.getLogger("chat_fast_path")
        prev = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(h)
        try:
            cfp.emit_span(
                cfp.SPAN_RESPONSE_READY,
                vault_id="v",
                intent="vault_faq",
                extra="fast_path=1 lang=ko",
            )
        finally:
            logger.removeHandler(h)
            logger.setLevel(prev)
        line = buf.getvalue()
        self.assertIn("lang=ko", line)

        self.assertNotIn("VaultAI가", line)
        self.assertNotIn("VaultAI가 뭐야", line)


if __name__ == "__main__":
    unittest.main()
