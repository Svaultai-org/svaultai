

from __future__ import annotations

import unittest
from pathlib import Path


def _read(p: str) -> str:
    return Path(p).read_text(encoding="utf-8")


class TestEnvelopeProse(unittest.TestCase):
    def test_found_message_uses_saved_items_plural(self) -> None:
        from vault_secure_item_card_envelope import _found_message
        line = _found_message(3)
        self.assertIn("saved items", line.lower(),
            msg='Plural count line must say "saved items"')
        self.assertNotIn("credentials", line.lower(),
            msg='Plural count line must NOT say "credentials"')
        self.assertNotIn("logins", line.lower(),
            msg='Plural count line must NOT say "logins"')

    def test_found_message_singular_is_saved_item(self) -> None:
        from vault_secure_item_card_envelope import _found_message
        line = _found_message(1)
        self.assertIn("saved item", line.lower())
        self.assertNotIn("login", line.lower())
        self.assertNotIn("credential", line.lower())

    def test_generic_none_found_is_not_login_specific(self) -> None:
        from vault_secure_item_card_envelope import (
            _none_found_message, MESSAGE_NONE_FOUND_GENERIC,
        )
                                                       
        self.assertEqual(
            _none_found_message(""),
            MESSAGE_NONE_FOUND_GENERIC,
        )
        self.assertNotIn("login", MESSAGE_NONE_FOUND_GENERIC.lower())
        self.assertNotIn("credential", MESSAGE_NONE_FOUND_GENERIC.lower())


class TestSecureItemDraftLanguage(unittest.TestCase):
    def test_saved_to_vault_pinned(self) -> None:
        import vault_secure_item_save as vsi
        self.assertEqual(
            vsi._SAVED_TO_VAULT_MESSAGE, "Saved to your vault 🔐",
            msg="Operator-pinned final-save reply",
        )
                                         
        self.assertNotIn("login", vsi._SAVED_TO_VAULT_MESSAGE.lower())

    def test_missing_title_question_not_service_name(self) -> None:
        import vault_secure_item_save as vsi
                                                                   
                                                                  
        missing_title_q = vsi._CLARIFY_QUESTIONS.get("missing_title", "")
        self.assertNotIn("service name", missing_title_q.lower(),
            msg=(
                "Operator brief: stop asking for 'service name' "
                "on secure-item saves"
            ),
        )
                                                                 
                                
        self.assertTrue(len(missing_title_q) > 10)

    def test_draft_render_does_not_say_login(self) -> None:
        import vault_secure_item_save as vsi
        msg = vsi._render_draft_message(title="Norton key recovery phrase")
        self.assertIn("Norton key recovery phrase", msg)
        self.assertNotIn("login", msg.lower())
        self.assertNotIn("credential", msg.lower())
        self.assertNotIn("service name", msg.lower())


class TestDeleteRouteLanguage(unittest.TestCase):
    def test_404_message_is_generic(self) -> None:
        src = _read("routes/login_routes.py")
        anchor = '@router.post("/delete-secure-item")'
        start  = src.index(anchor)
                                                             
                                                               
        close_marker = "conn.close()"
        idx = src.find(close_marker, start + 1)
        end = idx + len(close_marker) if idx != -1 else len(src)
        body = src[start:end]
                                                              
        self.assertIn('"Saved item not found"', body)
                                                              
                                                              
        import re
        for m in re.finditer(
            r'HTTPException\s*\([^)]*detail\s*=\s*"([^"]+)"', body,
        ):
            with self.subTest(detail=m.group(1)):
                self.assertNotIn(
                    "Login not found", m.group(1),
                    msg=(
                        "Generic delete handler must not raise "
                        "HTTPException with 'Login not found'"
                    ),
                )


class TestFlutterDeleteHandlerLanguage(unittest.TestCase):
    def test_handler_says_saved_item_for_non_login(self) -> None:
        path = Path("../vault_ai_frontend/lib/main.dart")
        if not path.exists():
            self.skipTest("main.dart not on disk")
        src = path.read_text(encoding="utf-8")
                                                               
                                                                
        self.assertIn(
            "_startSecureItemDeleteConfirmation(", src,
            msg=(
                "Flutter delete handler must use the chat-confirmed "
                "entry point"
            ),
        )
                                                               
                                              
        self.assertNotIn(
            "Future<void> _confirmDeleteSecureItem(", src,
            msg=(
                "Operator brief: delete must route through chat "
                "confirmation; the legacy direct helper must be "
                "removed"
            ),
        )

    def test_api_client_error_prefix_is_generic(self) -> None:
        path = Path("../vault_ai_frontend/lib/api_client.dart")
        if not path.exists():
            self.skipTest("api_client.dart not on disk")
        src = path.read_text(encoding="utf-8")
                                                                   
        anchor = "Future<Map<String, dynamic>> deleteVaultSecureItem("
        start  = src.index(anchor)
        idx = src.find("\nFuture<", start + 1)
        end = idx if idx != -1 else min(start + 4000, len(src))
        body = src[start:end]
                         
        self.assertIn("'Could not delete saved item'", body)
                                           
        self.assertNotIn("'Delete login failed'", body)


class TestFollowupClarifyLanguage(unittest.TestCase):
    def test_clarify_message_uses_saved_items_for_multi(self) -> None:
        from vault_secure_item_results_followup import (
            SecureItemResultsCard, _clarify,
        )
        cards = (
            SecureItemResultsCard(
                item_id="a", title="Payment Card", item_type="card",
            ),
            SecureItemResultsCard(
                item_id="b", title="Phone IMEI", item_type="imei",
            ),
            SecureItemResultsCard(
                item_id="c", title="Bank Account", item_type="bank",
            ),
        )
        msg = _clarify(cards).message
        self.assertIn("saved items", msg.lower())
        self.assertNotIn("credentials", msg.lower())
                              
        self.assertIn("Payment Card", msg)
        self.assertIn("Phone IMEI", msg)
        self.assertIn("Bank Account", msg)


class TestChatReplyLanguageStability(unittest.TestCase):
    def test_accept_language_does_not_switch_english_chat_to_french(self) -> None:
        import vault_multilingual as mling

        self.assertEqual(
            mling.resolve_reply_language(
                detected_from_message=mling.detect_language("my name is Kola"),
                app_locale_hint=None,
                header_locale_hint="fr-FR",
            ),
            "en",
        )

    def test_explicit_app_language_still_wins_for_short_messages(self) -> None:
        import vault_multilingual as mling

        self.assertEqual(
            mling.resolve_reply_language(
                detected_from_message=None,
                app_locale_hint="fr",
                header_locale_hint="en-US",
            ),
            "fr",
        )


if __name__ == "__main__":                    
    unittest.main()
