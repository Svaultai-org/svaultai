

from __future__ import annotations

import inspect
import unittest


class TestChatHandlerImportsNewBands(unittest.TestCase):
    def setUp(self) -> None:
        with open("main.py", "r", encoding="utf-8") as f:
            self.src = f.read()

    def test_imports_three_new_bands(self) -> None:
                                                              
                                                         
        for needle in (
            "BAND_DELETE_CONFIRMATION_PENDING as _SECURE_BAND_DELETE_CONF",
            "BAND_DELETED as _SECURE_BAND_DELETED",
            "BAND_DELETE_CANCELLED as _SECURE_BAND_DELETE_CANCELLED",
        ):
            with self.subTest(needle=needle):
                self.assertIn(
                    needle, self.src,
                    msg=(
                        f"main.py must import {needle!r} so the chat "
                        "handler can branch on the new delete bands"
                    ),
                )

    def test_imports_delete_confirmation_context_label(self) -> None:
        self.assertIn(
            "CONTEXT_SECURE_ITEM_DELETE_CONFIRMATION as _SECURE_DELETE_CTX",
            self.src,
            msg=(
                "main.py must import the delete-confirmation context "
                "label so the next turn's confirm/cancel routes "
                "through the orchestrator"
            ),
        )


class TestChatHandlerBranchesOnNewBands(unittest.TestCase):


    def setUp(self) -> None:
        with open("main.py", "r", encoding="utf-8") as f:
            self.src = f.read()

    def test_pending_branch_returns_encrypted_reply(self) -> None:
                                                             
                           
        self.assertRegex(
            self.src,
            r"_secure_band\s*==\s*_SECURE_BAND_DELETE_CONF",
            "main.py must include an explicit branch on the "
            "delete-confirmation-pending band",
        )
                                                            
                                                              
        self.assertIn(
            "_set_active_ctx(vault_id, _SECURE_DELETE_CTX)",
            self.src,
            msg=(
                "main.py must stamp the delete-confirmation context "
                "so the next 'yes' / 'cancel' routes correctly"
            ),
        )

    def test_deleted_and_cancelled_clear_active_context(self) -> None:
                                                          
                                                                
        self.assertRegex(
            self.src,
            r"_secure_band\s+in\s*\(\s*\n\s*_SECURE_BAND_DELETED,\s*"
            r"\n\s*_SECURE_BAND_DELETE_CANCELLED,",
            msg=(
                "main.py must branch on BOTH BAND_DELETED and "
                "BAND_DELETE_CANCELLED together with a clear-context "
                "call"
            ),
        )

    def test_handler_uses_encrypted_reply_for_delete_bands(self) -> None:
                                                               
                                                               
        anchor = "_secure_band == _SECURE_BAND_DELETE_CONF"
        idx = self.src.index(anchor)
        window = self.src[idx:idx + 1500]
        self.assertIn(
            "encrypted_reply(", window,
            msg=(
                "DELETE_CONFIRMATION_PENDING reply must go through "
                "encrypted_reply(...)"
            ),
        )
                                                                
                              
        anchor2 = "_SECURE_BAND_DELETED,"
                                                               
                                                                
        idx2 = self.src.index(anchor2)
                                                  
        idx2 = self.src.index(anchor2, idx2 + 1)
        window2 = self.src[idx2:idx2 + 1500]
        self.assertIn(
            "encrypted_reply(", window2,
            msg=(
                "DELETED / DELETE_CANCELLED reply must go through "
                "encrypted_reply(...)"
            ),
        )


class TestOrchestratorSentinelEntryPoint(unittest.TestCase):


    def test_sentinel_parser_called_inside_route(self) -> None:
        from vault_secure_item_save import route_secure_item_message
        src = inspect.getsource(route_secure_item_message)
        self.assertIn(
            "parse_delete_intent_sentinel",
            src,
            msg=(
                "route_secure_item_message must call the sentinel "
                "parser; the chat handler only knows BAND names, "
                "not wire formats"
            ),
        )

    def test_orchestrator_handles_confirm_and_cancel_phrases(self) -> None:
        from vault_secure_item_save import route_secure_item_message
        src = inspect.getsource(route_secure_item_message)
        self.assertIn("is_confirm_delete_phrase", src)
        self.assertIn("is_cancel_delete_phrase", src)


if __name__ == "__main__":                    
    unittest.main()
