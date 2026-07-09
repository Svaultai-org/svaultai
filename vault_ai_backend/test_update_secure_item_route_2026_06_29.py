

from __future__ import annotations

import unittest
from pathlib import Path


_ROUTES_FILE = Path("routes/login_routes.py")


def _read_routes() -> str:
    return _ROUTES_FILE.read_text(encoding="utf-8")


def _slice_handler() -> str:
    src = _read_routes()
    anchor = '@router.post("/update-secure-item")'
    start  = src.index(anchor)
                                                              
                                                              
    boundaries = []
    for marker in ('@router.post("/delete-secure-item")',
                   '@router.post("/list-secure-items")',
                   '# 2026-06-29 — Generic secure-item DELETE',
                   '# 2026-06-29 - Generic secure-item DELETE'):
        idx = src.find(marker, start + 1)
        if idx != -1:
            boundaries.append(idx)
    end = min(boundaries) if boundaries else len(src)
    return src[start:end]


class TestEndpointDeclared(unittest.TestCase):
    def test_route_decorator_present(self) -> None:
        src = _read_routes()
        self.assertIn('@router.post("/update-secure-item")', src)

    def test_handler_function_present(self) -> None:
        src = _read_routes()
        self.assertIn("def update_secure_item(", src)

    def test_request_model_carries_item_type(self) -> None:
        src = _read_routes()
        self.assertIn(
            "class UpdateSecureItemRequest(BaseModel):", src,
        )
        self.assertRegex(src, r"item_type\s*:\s*str")
        self.assertRegex(src, r"new_service\s*:\s*Optional\[str\]")
        self.assertRegex(src, r"fields\s*:\s*Optional\[dict")


class TestHandlerShape(unittest.TestCase):
    def test_sql_does_not_filter_by_login(self) -> None:
        body = _slice_handler()
        self.assertNotIn(
            "item_type = 'login'", body,
            msg=(
                "/update-secure-item must NOT hardcode "
                "item_type='login'"
            ),
        )
        self.assertNotIn('item_type = "login"', body)

    def test_sql_filters_by_payload_item_type(self) -> None:
        body = _slice_handler()
        self.assertIn("item_type = %s", body)
        self.assertIn("LOWER(service)", body)
        self.assertRegex(body, r"WHERE\s+vault_id\s*=\s*%s")

    def test_decrypts_existing_blob_before_merging(self) -> None:
        body = _slice_handler()
                                                               
                                                                
        self.assertIn("decrypt_message(", body)
        self.assertIn("encrypt_message(", body)
                                                               
        self.assertIn("**existing_fields", body)


class TestErrorLanguage(unittest.TestCase):
    def test_404_message_is_saved_item_not_login(self) -> None:
        body = _slice_handler()
        self.assertIn(
            'detail="Saved item not found"', body,
            msg=(
                "Operator brief: 404 must read 'Saved item not "
                "found' for every item_type"
            ),
        )
                                              
        import re
        for m in re.finditer(
            r'HTTPException\s*\([^)]*detail\s*=\s*"([^"]+)"', body,
        ):
            with self.subTest(detail=m.group(1)):
                self.assertNotIn("Login not found", m.group(1))


class TestCacheInvalidationFiresPerType(unittest.TestCase):
    def test_credential_edited_event_for_login(self) -> None:
        body = _slice_handler()
        self.assertIn('"credential_edited"', body)

    def test_secure_item_edited_event_for_non_login(self) -> None:
        body = _slice_handler()
        self.assertIn('"secure_item_edited"', body)


class TestUpdateSecureItemDoesNotReturn404(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)
        self.paths = {r.path for r in main.app.routes}

    def test_root_mount_registered(self) -> None:
        self.assertIn(
            "/update-secure-item", self.paths,
            msg=(
                "POST /update-secure-item must be mounted at "
                "the ROOT prefix so the Flutter Edit dialog "
                "resolves without 404"
            ),
        )

    def test_unauth_call_returns_4xx_but_not_404(self) -> None:
        resp = self.client.post(
            "/update-secure-item",
            json={
                "vault_name":  "x",
                "old_service": "Phone IMEI",
                "item_type":   "imei",
                "new_service": "iPhone 15 IMEI",
                "pin":         "0000",
                "fields":      {"imei_1": "12345"},
            },
        )
        self.assertNotEqual(resp.status_code, 404)
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)


if __name__ == "__main__":                    
    unittest.main()
