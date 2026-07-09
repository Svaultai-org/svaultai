

from __future__ import annotations

import unittest
from pathlib import Path


_ROUTES_FILE = Path("routes/login_routes.py")


def _read_routes() -> str:
    return _ROUTES_FILE.read_text(encoding="utf-8")


class TestRouteDeclared(unittest.TestCase):

    def test_route_decorator_present(self):
        src = _read_routes()
        self.assertIn(
            '@router.post("/get-secure-item")', src,
            msg=(
                "login_routes.py must declare POST "
                "/get-secure-item so the Flutter Edit dialog "
                "can fetch decrypted fields."
            ),
        )

    def test_handler_function_present(self):
        src = _read_routes()
        self.assertIn("def get_secure_item(", src)

    def test_request_model_carries_service_and_item_type_and_pin(self):
        src = _read_routes()
                                                             
        self.assertIn("class GetSecureItemRequest(BaseModel):", src)
        idx = src.index("class GetSecureItemRequest(BaseModel):")
        snippet = src[idx:idx + 400]
        for field in ("service:", "item_type:", "pin:"):
            with self.subTest(field=field):
                self.assertIn(field, snippet)


class TestHandlerShape(unittest.TestCase):

    def _slice_handler(self) -> str:
        src = _read_routes()
        anchor = '@router.post("/get-secure-item")'
        start  = src.index(anchor)
                                                                
        boundaries = []
        for marker in (
            '@router.post("/delete-secure-item")',
            '@router.post("/list-secure-items")',
            '@router.post("/update-secure-item")',
        ):
            idx = src.find(marker, start + 1)
            if idx != -1:
                boundaries.append(idx)
        end = min(boundaries) if boundaries else len(src)
        return src[start:end]

    def test_sql_queries_vault_items_by_composite_key(self):
        body = self._slice_handler()
        self.assertIn("FROM vault_items", body)
        self.assertIn("vault_id = %s", body)
        self.assertIn("item_type = %s", body)
        self.assertIn("LOWER(service)", body)

    def test_handler_decrypts_with_pin_derived_key(self):
        body = self._slice_handler()
                                                              
                                                             
        self.assertIn("verify_vault_pin", body)
        self.assertIn("decrypt_message(row[\"encrypted_data\"], key)", body)

    def test_handler_tolerates_both_payload_schemas(self):
        body = self._slice_handler()
                                                              
                                                         
        self.assertIn("_SCHEMA_B_MARKERS", body)
        self.assertIn("fields_out = record", body)

    def test_response_shape_carries_closed_set_keys(self):
        body = self._slice_handler()
                                                             
        for key in (
            '"service":', '"item_type":', '"fields":',
            '"notes":', '"created_at":',
        ):
            with self.subTest(key=key):
                self.assertIn(key, body)

    def test_handler_does_not_log_fields_or_record(self):
                                                      
                                                    
        body = self._slice_handler()
        for forbidden in (
            "logger.info", "logger.warning", "logger.error",
            "print(", "logger.debug",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden, body,
                    msg=(
                        f"/get-secure-item handler must not "
                        f"contain {forbidden} — privacy floor."
                    ),
                )


class TestErrorLanguage(unittest.TestCase):

    def _slice_handler(self) -> str:
        return TestHandlerShape()._slice_handler()

    def test_404_on_no_match(self):
        body = self._slice_handler()
        self.assertIn('detail="Saved item not found"', body)
                                                          
        self.assertNotIn('detail="Login not found"', body)

    def test_400_on_missing_item_type(self):
        body = self._slice_handler()
        self.assertIn('detail="Missing item type"', body)


class TestRouteMountedOnApp(unittest.TestCase):

    def setUp(self):
        import main
        self.app = main.app
        self.paths = {r.path for r in self.app.routes}

    def test_get_secure_item_route_is_registered_at_root(self):
        self.assertIn(
            "/get-secure-item", self.paths,
            msg=(
                "The /get-secure-item route is not mounted on "
                "the FastAPI app at the root. The Flutter client "
                "POSTs to ``$baseUrl/get-secure-item``."
            ),
        )

    def test_route_method_is_post(self):
        for r in self.app.routes:
            if getattr(r, "path", None) == "/get-secure-item":
                methods = getattr(r, "methods", set()) or set()
                self.assertIn(
                    "POST", methods,
                    msg=(
                        "/get-secure-item must accept POST so "
                        "the Pydantic body deserialises."
                    ),
                )
                return
        self.fail("/get-secure-item route object not found")


class TestRouteDoesNotReturn500OnUnauthCall(unittest.TestCase):

    def setUp(self):
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_unauthenticated_call_returns_4xx_not_500(self):
                                                          
                                                         
        resp = self.client.post(
            "/get-secure-item",
            json={
                "vault_name": "x",
                "service":    "Instagram",
                "item_type":  "login",
                "pin":        "0000",
            },
        )
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)

    def test_missing_item_type_returns_400(self):
        resp = self.client.post(
            "/get-secure-item",
            json={
                "vault_name": "x",
                "service":    "Instagram",
                                                                
                "pin":        "0000",
            },
        )
                                                             
                                                          
        self.assertIn(resp.status_code, (400, 401, 403, 422))


if __name__ == "__main__":                    
    unittest.main()
