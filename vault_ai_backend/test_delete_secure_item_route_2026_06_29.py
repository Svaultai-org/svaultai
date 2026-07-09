

from __future__ import annotations

import unittest
from pathlib import Path


_ROUTES_FILE = Path("routes/login_routes.py")


def _read_routes() -> str:
    return _ROUTES_FILE.read_text(encoding="utf-8")


class TestDeleteSecureItemEndpointDeclared(unittest.TestCase):
    def test_route_decorator_present(self) -> None:
        src = _read_routes()
        self.assertIn(
            '@router.post("/delete-secure-item")', src,
            msg=(
                "login_routes.py must declare POST "
                "/delete-secure-item so the Flutter generic-delete "
                "call resolves without 404"
            ),
        )

    def test_handler_function_present(self) -> None:
        src = _read_routes()
        self.assertIn("def delete_secure_item(", src)

    def test_request_model_present(self) -> None:
        src = _read_routes()
                                                         
        self.assertIn("class DeleteSecureItemRequest(BaseModel):", src)
        self.assertRegex(
            src, r"item_type\s*:\s*str",
        )


class TestHandlerShape(unittest.TestCase):
    def _slice_handler(self) -> str:


        src = _read_routes()
        anchor = '@router.post("/delete-secure-item")'
        start  = src.index(anchor)
                                                               
                                                                  
        boundaries = []
        for marker in ('@router.post("/list-secure-items")',
                       '@router.post("/list-login-names")',
                       '# 2026-06-29 — Broader',
                       '# 2026-06-29 - Broader'):
            idx = src.find(marker, start + 1)
            if idx != -1:
                boundaries.append(idx)
        end = min(boundaries) if boundaries else len(src)
        return src[start:end]

    def test_sql_does_not_filter_by_login(self) -> None:
        body = self._slice_handler()
        self.assertNotIn(
            "item_type = 'login'", body,
            msg=(
                "/delete-secure-item must NOT hardcode "
                "item_type='login' — that's the live bug"
            ),
        )
        self.assertNotIn('item_type = "login"', body)

    def test_sql_filters_by_payload_item_type(self) -> None:
        body = self._slice_handler()
                                                                 
                                                     
        self.assertRegex(
            body,
            r"WHERE\s+vault_id\s*=\s*%s",
        )
        self.assertIn("item_type = %s", body)
        self.assertIn("LOWER(service)", body)

    def test_response_carries_no_encrypted_blob(self) -> None:
                                                              
                                                                   
        body = self._slice_handler()
                                                                  
                                        
        return_idx = body.index("return {")
        end_idx = body.index("}", return_idx)
        return_dict = body[return_idx:end_idx + 1]
        self.assertNotIn(
            "encrypted_data", return_dict,
            msg=(
                "Delete response dict must not surface encrypted "
                "blob payload"
            ),
        )


class TestErrorLanguageGeneric(unittest.TestCase):
    def _slice_handler(self) -> str:
        return TestHandlerShape()._slice_handler()

    def test_404_message_does_not_say_login(self) -> None:
        body = self._slice_handler()
                                               
        self.assertIn(
            'detail="Saved item not found"', body,
            msg=(
                "Operator brief: error must read 'Saved item "
                "not found' for non-login rows"
            ),
        )
                                              
        self.assertNotIn(
            'detail="Login not found"', body,
            msg=(
                "Generic delete must NOT say 'Login not found' — "
                "operator brief: only say 'login' when the item "
                "IS one"
            ),
        )


class TestLegacyLoginDeleteStaysAvailable(unittest.TestCase):
    def setUp(self) -> None:
        import main
        self.app = main.app
        self.paths = {r.path for r in self.app.routes}

    def test_legacy_login_delete_routes_still_registered(self) -> None:
                                                               
                                                              
        self.assertIn(
            "/manage/login/delete", self.paths,
            msg=(
                "Removing /manage/login/delete would break the "
                "legacy login delete flow + the prior tests"
            ),
        )


class TestDeleteSecureItemDoesNotReturn404(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_root_mount_does_not_404(self) -> None:
                                                                 
                                                                
        resp = self.client.post(
            "/delete-secure-item",
            json={
                "vault_name": "x",
                "service":    "Norton key",
                "item_type":  "license_key",
                "pin":        "0000",
            },
        )
        self.assertNotEqual(
            resp.status_code, 404,
            msg=(
                "POST /delete-secure-item returned 404 — the "
                "Flutter delete call would surface the live bug"
            ),
        )
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)


class TestSupportsBroadItemTypeFamily(unittest.TestCase):


    def _slice_handler(self) -> str:
        return TestHandlerShape()._slice_handler()

    def test_handler_does_not_whitelist_a_handful_of_types(self) -> None:
        body = self._slice_handler()
                                                          
                    
        for forbidden in (
            'if item_type == "login"',
            "if item_type == 'login'",
            'if item_type not in (',
            "if item_type not in [",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, body)


if __name__ == "__main__":                    
    unittest.main()
