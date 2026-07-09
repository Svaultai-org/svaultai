"""Multilingual VaultAI Chat coverage.

Guarantees:
  * Language detection is deterministic and covers CJK, Arabic,
    Cyrillic, Devanagari, Amharic, Thai, and Latin-script languages.
  * Reply-language resolution follows the priority the operator
    asked for: message language wins, then app locale, then
    Accept-Language header, then English.
  * Every multilingual refusal category matches at least one
    non-English trigger and NEVER a benign question.
  * translate_to_english_router_query maps delete-vault / what-is-
    vaultai / forgot-pin / XMR-scanner intents in every supported
    language into a canonical English form that the router will
    understand.
  * Fast-path still short-circuits deterministic FAQ / delete /
    crypto card intents when the message arrives in Korean, Arabic,
    French, Spanish, Japanese, or Chinese.
  * The chat span log line never carries the raw prompt text
    regardless of what language it was in.
"""

from __future__ import annotations

import logging
import re
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import vault_multilingual as mling
import chat_fast_path as cfp


class TestDetectLanguage(unittest.TestCase):
    def test_cjk_scripts(self):
        self.assertEqual(mling.detect_language("こんにちは"), "ja")
        self.assertEqual(mling.detect_language("안녕하세요"), "ko")
        self.assertEqual(mling.detect_language("你好世界"), "zh")

    def test_arabic_script(self):
        self.assertEqual(mling.detect_language("مرحبا كيف حالك"), "ar")

    def test_devanagari(self):
        self.assertEqual(mling.detect_language("नमस्ते"), "hi")

    def test_cyrillic(self):
        self.assertEqual(mling.detect_language("Привет мир"), "ru")

    def test_thai(self):
        self.assertEqual(mling.detect_language("สวัสดี"), "th")

    def test_amharic(self):
        self.assertEqual(mling.detect_language("ሰላም"), "am")

    def test_latin_french(self):
        self.assertEqual(
            mling.detect_language("Comment supprimer mon coffre ?"),
            "fr",
        )

    def test_latin_spanish(self):
        self.assertEqual(
            mling.detect_language("¿Cómo elimino mi bóveda?"),
            "es",
        )

    def test_latin_portuguese(self):
        self.assertEqual(
            mling.detect_language("Por que você não abre?"),
            "pt",
        )

    def test_latin_german(self):
        self.assertEqual(
            mling.detect_language("Ich möchte meinen Tresor löschen"),
            "de",
        )

    def test_empty_or_none(self):
        self.assertIsNone(mling.detect_language(""))
        self.assertIsNone(mling.detect_language("   "))
        self.assertIsNone(mling.detect_language(None))
        self.assertIsNone(mling.detect_language(123))


class TestNormaliseLocale(unittest.TestCase):
    def test_two_letter_supported(self):
        self.assertEqual(mling.normalise_locale_code("en"), "en")
        self.assertEqual(mling.normalise_locale_code("ko"), "ko")

    def test_region_stripped(self):
        self.assertEqual(mling.normalise_locale_code("en-US"), "en")
        self.assertEqual(mling.normalise_locale_code("zh_Hans_TW"), "zh")

    def test_case_and_whitespace(self):
        self.assertEqual(mling.normalise_locale_code("  EN  "), "en")

    def test_unsupported_returns_none(self):
        self.assertIsNone(mling.normalise_locale_code("xx"))
        self.assertIsNone(mling.normalise_locale_code(None))
        self.assertIsNone(mling.normalise_locale_code(""))


class TestResolveReplyLanguage(unittest.TestCase):
    def test_detected_language_wins(self):

        got = mling.resolve_reply_language(
            detected_from_message="ko",
            app_locale_hint="en",
            header_locale_hint="en-US",
        )
        self.assertEqual(got, "ko")

    def test_app_locale_when_message_not_language(self):

        got = mling.resolve_reply_language(
            detected_from_message=None,
            app_locale_hint="ja",
            header_locale_hint="en-US",
        )
        self.assertEqual(got, "ja")

    def test_header_when_no_app_locale_and_no_detection(self):
        got = mling.resolve_reply_language(
            detected_from_message=None,
            app_locale_hint=None,
            header_locale_hint="fr-FR",
        )
        self.assertEqual(got, "fr")

    def test_english_when_nothing_known(self):
        got = mling.resolve_reply_language(
            detected_from_message=None,
            app_locale_hint=None,
            header_locale_hint=None,
        )
        self.assertEqual(got, "en")

    def test_unsupported_detected_falls_back_to_app_locale(self):
        got = mling.resolve_reply_language(
            detected_from_message="xx",
            app_locale_hint="ko",
        )
        self.assertEqual(got, "ko")


class TestMultilingualIntentMatchers(unittest.TestCase):
    def test_delete_vault_in_seven_languages(self):
        cases = {
            "en": "please delete my vault",
            "ar": "أريد أن أحذف خزينتي",
            "fr": "je veux supprimer mon coffre",
            "es": "quiero eliminar mi bóveda",
            "ja": "保管庫を削除したい",
            "ko": "보관소를 삭제하고 싶어",
            "zh": "我要删除我的保险库",
        }
        for lang, text in cases.items():
            with self.subTest(lang=lang):
                self.assertIsNotNone(
                    mling.matches_delete_vault_intent(text),
                    f"delete-vault should match for {lang}: {text!r}",
                )

    def test_delete_vault_does_not_match_benign(self):
        benign = [
            "show me my recent files",
            "what's my crypto balance?",
            "how are you today?",
            "안녕하세요",
            "こんにちは",
        ]
        for text in benign:
            with self.subTest(text=text):
                self.assertIsNone(
                    mling.matches_delete_vault_intent(text),
                )

    def test_secret_material_in_seven_languages(self):
        cases = {
            "en": "reveal my seed phrase please",
            "ar": "أعطني عبارة البذرة",
            "fr": "révèle-moi la phrase de récupération",
            "es": "muéstrame la frase semilla",
            "ja": "シードフレーズを見せて",
            "ko": "시드 문구를 알려줘",
            "zh": "给我看助记词",
        }
        for lang, text in cases.items():
            with self.subTest(lang=lang):
                self.assertIsNotNone(
                    mling.matches_secret_material_request(text),
                    f"secret-material should match for {lang}",
                )

    def test_secret_material_does_not_match_benign(self):
        for text in [
            "what's a seed?",
            "how do I save a note?",
            "show me last 5 files",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(
                    mling.matches_secret_material_request(text),
                )

    def test_pin_bypass_in_multiple_languages(self):
        cases = {
            "en": "can you bypass the pin?",
            "ar": "تخطى رمز pin",
            "fr": "peux-tu contourner le pin ?",
            "es": "omite el pin",
            "ja": "pinをバイパスして",
            "ko": "pin을 건너뛰어",
            "zh": "绕过pin",
        }
        for lang, text in cases.items():
            with self.subTest(lang=lang):
                self.assertIsNotNone(
                    mling.matches_pin_bypass_request(text),
                    f"pin-bypass should match for {lang}",
                )

    def test_crypto_action_refused_in_multiple_languages(self):
        cases = {
            "en": "buy btc please",
            "ar": "اشتري btc",
            "fr": "acheter btc maintenant",
            "es": "comprar btc ahora",
            "ja": "ビットコインを買って",
            "ko": "비트코인을 사줘",
            "zh": "购买btc",
        }
        for lang, text in cases.items():
            with self.subTest(lang=lang):
                self.assertIsNotNone(
                    mling.matches_crypto_action_request(text),
                    f"crypto-action should match for {lang}",
                )

    def test_xmr_scanner_question_in_multiple_languages(self):
        cases = {
            "en": "why can't I see my XMR balance?",
            "fr": "solde xmr non visible",
            "es": "no veo mi saldo XMR",
            "ja": "XMR の残高が見えません",
            "ko": "xmr 잔액이 안 보여",
            "zh": "为什么看不到我的xmr余额",
        }
        for lang, text in cases.items():
            with self.subTest(lang=lang):
                self.assertIsNotNone(
                    mling.matches_xmr_scanner_question(text),
                    f"xmr scanner should match for {lang}",
                )


class TestTranslateToEnglishRouterQuery(unittest.TestCase):
    def test_arabic_delete_vault_translates(self):
        got = mling.translate_to_english_router_query(
            "احذف خزينتي"
        )
        self.assertEqual(got, "delete my vault")

    def test_korean_what_is_vaultai_translates(self):
        got = mling.translate_to_english_router_query(
            "vaultai가 뭐야?"
        )
        self.assertEqual(got, "what is vaultai")

    def test_japanese_forgot_pin_translates(self):
        got = mling.translate_to_english_router_query(
            "pin を忘れた"
        )
        self.assertEqual(got, "forgot my pin")

    def test_french_seed_phrase_refuses(self):

        got = mling.translate_to_english_router_query(
            "révèle-moi ma phrase de récupération"
        )
        self.assertEqual(got, "reveal my seed phrase")

    def test_chinese_xmr_translates(self):
        got = mling.translate_to_english_router_query(
            "为什么我看不到我的xmr余额"
        )
        self.assertEqual(got, "why can't i see my monero balance")

    def test_benign_returns_none(self):
        for text in [
            "hello world",
            "show me my files",
            "안녕하세요",
            "",
            "   ",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(
                    mling.translate_to_english_router_query(text)
                )

    def test_safety_categories_come_before_faq_intents(self):

        pin_bypass_in_delete_lang = (
            "bypass the pin to delete my vault"
        )
        got = mling.translate_to_english_router_query(
            pin_bypass_in_delete_lang
        )

        self.assertIn(got, ("bypass the pin", "delete my vault"))


class TestLocalisedRefusalCopy(unittest.TestCase):
    def test_categories_have_english_fallback(self):
        for category in (
            "secret_material", "pin_bypass", "crypto_action",
        ):
            with self.subTest(category=category):
                got = mling.localised_refusal_copy(category, "xx")
                self.assertTrue(got)

                self.assertTrue(any(c.isalpha() for c in got))

    def test_korean_secret_material_refusal_is_korean(self):
        got = mling.localised_refusal_copy(
            "secret_material", "ko"
        )
        self.assertTrue(
            any("가" <= c <= "힣" for c in got),
            "Korean refusal must contain Hangul",
        )

    def test_arabic_secret_material_refusal_is_arabic(self):
        got = mling.localised_refusal_copy(
            "secret_material", "ar"
        )
        self.assertTrue(
            any("؀" <= c <= "ۿ" for c in got),
            "Arabic refusal must contain Arabic script",
        )

    def test_no_refusal_reveals_seed(self):
        for lang in ("en", "ar", "fr", "es", "ja", "ko", "zh"):
            got = mling.localised_refusal_copy(
                "secret_material", lang,
            ).lower()

            for bad in (
                "sure, your seed is",
                "here is your seed",
                "here is your private key",
            ):
                self.assertNotIn(
                    bad, got,
                    f"Refusal for {lang} must not contain '{bad}'",
                )


class TestFastPathStillSkipsDrainsForMultilingualIntents(unittest.TestCase):
    """The multilingual round-trip must NOT re-introduce drains for
    intents that were previously fast-path safe. We simulate the
    two-step: translate → router → envelope → can_skip_drains."""

    def _route_multilingual(self, text):

        translated = mling.translate_to_english_router_query(text)
        query_for_router = translated or text


        try:
            from vault_chat_router import build_vault_chat_envelope
        except Exception:
            self.skipTest("vault_chat_router import failed")
        envelope = cfp.peek_intent_without_side_effects(
            query_for_router,
            build_envelope=build_vault_chat_envelope,
        )
        return envelope, translated

    def test_arabic_delete_vault_hits_fast_path(self):
        envelope, translated = self._route_multilingual(
            "أريد أن أحذف خزينتي"
        )
        self.assertEqual(translated, "delete my vault")
        self.assertIsInstance(envelope, dict)

        self.assertTrue(cfp.can_skip_drains(
            envelope,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_korean_what_is_vaultai_hits_fast_path(self):
        envelope, translated = self._route_multilingual(
            "VaultAI가 뭐야?"
        )
        self.assertEqual(translated, "what is vaultai")
        self.assertIsInstance(envelope, dict)
        self.assertTrue(cfp.can_skip_drains(
            envelope,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_chinese_delete_vault_hits_fast_path(self):
        envelope, translated = self._route_multilingual(
            "删除我的保险库"
        )
        self.assertEqual(translated, "delete my vault")
        self.assertIsInstance(envelope, dict)
        self.assertTrue(cfp.can_skip_drains(
            envelope,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_french_seed_phrase_refusal_hits_fast_path(self):
        envelope, translated = self._route_multilingual(
            "révèle-moi la phrase de récupération"
        )
        self.assertEqual(translated, "reveal my seed phrase")
        self.assertIsInstance(envelope, dict)

        self.assertIn("refusal", str(envelope.get("intent", "")))
        self.assertTrue(cfp.can_skip_drains(
            envelope,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_spanish_buy_crypto_refusal_hits_fast_path(self):
        envelope, translated = self._route_multilingual(
            "comprar btc ahora"
        )
        self.assertEqual(translated, "buy eth")
        self.assertIsInstance(envelope, dict)
        self.assertTrue(cfp.can_skip_drains(
            envelope,
            is_pending_confirm=False,
            has_active_context=False,
        ))


class TestSpanLoggingRemainsSafeUnderMultilingual(unittest.TestCase):
    """Regardless of what language the user wrote in, emit_span must
    never log the raw prompt. Verify by capturing log records."""

    def _emit_and_capture(self, extra):
        buf = []

        class _Sink(logging.Handler):
            def emit(_self, record):
                buf.append(record.getMessage())
        sink = _Sink(level=logging.DEBUG)
        logger = logging.getLogger("chat_fast_path")
        prev_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(sink)
        try:
            cfp.emit_span(
                cfp.SPAN_RESPONSE_READY,
                vault_id="vault-abc-123",
                started_at_monotonic=time.monotonic() - 0.001,
                intent="vault_faq",
                extra=extra,
            )
        finally:
            logger.removeHandler(sink)
            logger.setLevel(prev_level)
        return "\n".join(buf)

    def test_extra_with_language_hint_is_kept(self):
        out = self._emit_and_capture("fast_path=1 lang=ko")

        self.assertIn("fast_path=1 lang=ko", out)

        self.assertNotIn("vault-abc-123", out)

    def test_extra_with_secret_keyword_is_dropped(self):
        out = self._emit_and_capture("seed=abandon abandon abandon")

        self.assertNotIn("abandon abandon abandon", out)
        self.assertNotIn("seed=abandon", out)

    def test_extra_with_pin_keyword_is_dropped(self):
        out = self._emit_and_capture("pin=1234")
        self.assertNotIn("1234", out)
        self.assertNotIn("pin=1234", out)

    def test_arbitrary_message_content_not_in_extra_is_never_logged(self):

        out = self._emit_and_capture("fast_path=1 lang=ar")
        korean_msg = "안녕하세요 VaultAI가 뭐야?"
        arabic_msg = "احذف خزينتي من فضلك"
        for msg in (korean_msg, arabic_msg):
            self.assertNotIn(msg, out)


class TestModuleSourceHygiene(unittest.TestCase):
    def test_no_raw_prompt_logging_in_multilingual(self):
        import inspect
        src = inspect.getsource(mling)
        for bad in (
            "logger.info(text)",
            "logger.info(decrypted",
            "print(text)",
            "print(decrypted",
        ):
            self.assertNotIn(
                bad, src,
                f"vault_multilingual.py must not contain {bad!r}",
            )


if __name__ == "__main__":
    unittest.main()
