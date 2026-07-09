

from __future__ import annotations

import unittest
from pathlib import Path


_ROUTES_FILE = Path("routes/vault_manage_routes.py")


def _read_routes() -> str:
    return _ROUTES_FILE.read_text(encoding="utf-8")


class TestEndpointDeclared(unittest.TestCase):
    def test_route_decorator_present(self):
        src = _read_routes()
        self.assertIn(
            '@router.post("/list-secure-items")',
            src,
            msg=(
                "vault_manage_routes.py must declare POST "
                "/list-secure-items so the Logins page can fetch "
                "all encrypted text-based records"
            ),
        )

    def test_handler_function_present(self):
        src = _read_routes()
        self.assertIn(
            "async def list_secure_items(",
            src,
        )


class TestHandlerShape(unittest.TestCase):
    def _slice_handler(self) -> str:


        src = _read_routes()
        anchor = '@router.post("/list-secure-items")'
        start  = src.index(anchor)
        end    = src.index("@router.", start + 1) \
            if "@router." in src[start + 1:] else len(src)
        return src[start:end]

    def test_sql_does_not_filter_by_item_type_login(self):
        body = self._slice_handler()
        self.assertNotIn(
            "item_type = 'login'", body,
            msg=(
                "/list-secure-items must NOT filter by "
                "item_type = 'login' — operator brief: the Logins "
                "page now shows ALL encrypted text-based records"
            ),
        )
        self.assertNotIn(
            'item_type = "login"', body,
        )

    def test_sql_selects_item_type(self):
        body = self._slice_handler()
                                                                  
                                              
        self.assertIn(
            "item_type", body,
            msg=(
                "/list-secure-items must return item_type so the "
                "frontend can render per-category cards"
            ),
        )

    def test_response_carries_no_encrypted_blob(self):
        body = self._slice_handler()
                                                             
                                                              
        self.assertNotIn(
            "encrypted_data", body,
            msg=(
                "/list-secure-items must NEVER return "
                "encrypted_data — the masked card renders from "
                "service + item_type + created_at only"
            ),
        )

    def test_response_keys_pinned(self):
        body = self._slice_handler()
                                      
        for needle in ("service", "item_type", "created_at"):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)
                                        
        self.assertIn('"items"', body)


class TestLegacyLoginNamesStaysLoginOnly(unittest.TestCase):
    def test_list_login_names_still_filters_to_login(self):
        src = _read_routes()
                                                                
        anchor = '@router.post("/list-login-names")'
        start  = src.index(anchor)
        end    = src.index("@router.", start + 1)
        body   = src[start:end]
        self.assertIn(
            "item_type = 'login'", body,
            msg=(
                "/list-login-names must still filter to login "
                "rows only so the chat 'show my logins' / legacy "
                "callers keep their old behaviour"
            ),
        )


class TestFilesSurfaceUntouched(unittest.TestCase):
    def test_handler_does_not_read_vault_files(self):
        body = TestHandlerShape()._slice_handler()
                                                                   
                                                                 
        for needle in ("vault_files", "file_id", "saved_name"):
            with self.subTest(needle=needle):
                self.assertNotIn(
                    needle, body,
                    msg=(
                        "/list-secure-items must NOT read or "
                        "expose vault_files columns — uploaded "
                        "files belong in the Files section"
                    ),
                )


if __name__ == "__main__":                    
    unittest.main()
