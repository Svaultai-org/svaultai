

from __future__ import annotations

import unittest
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


class TestListSecureItemsRouteRegistered(unittest.TestCase):
    def setUp(self) -> None:
        import main
        self.app = main.app
                                                                
        self.paths = {r.path for r in self.app.routes}

    def test_root_mount_is_registered(self) -> None:
        self.assertIn(
            "/list-secure-items", self.paths,
            msg=(
                "POST /list-secure-items must be mounted at the "
                "ROOT prefix — the Flutter client posts to "
                "/list-secure-items (no /manage prefix)."
            ),
        )

    def test_manage_prefix_mount_stays_registered(self) -> None:
                                                               
                                                               
        self.assertIn(
            "/manage/list-secure-items", self.paths,
            msg=(
                "Removing /manage/list-secure-items would break "
                "the manage-router shape tests + any future "
                "manage-router admin callers. Keep both mounts."
            ),
        )


class TestListSecureItemsDoesNotReturn404(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        import main
        self.client = TestClient(main.app)

    def test_unauth_call_returns_4xx_but_not_404(self) -> None:


        resp = self.client.post(
            "/list-secure-items",
            json={"vault_name": "x", "pin": "0000"},
        )
        self.assertNotEqual(
            resp.status_code, 404,
            msg=(
                "POST /list-secure-items returned 404 — the live "
                "browser bug. Confirm the handler is mounted in "
                "routes/login_routes.py (mounted at root)."
            ),
        )
                                                              
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertLess(resp.status_code, 500)


class TestRootMountedHandlerShape(unittest.TestCase):
    SRC_PATH = "routes/login_routes.py"

    def _slice_handler(self) -> str:
        src = _read(self.SRC_PATH)
        anchor = '@router.post("/list-secure-items")'
        start  = src.index(anchor)
                                                              
        idx = src.find("@router.", start + 1)
        end = idx if idx != -1 else len(src)
        return src[start:end]

    def test_handler_present(self) -> None:
        body = self._slice_handler()
        self.assertIn("def list_secure_items(", body)

    def test_handler_does_not_filter_by_login(self) -> None:
        body = self._slice_handler()
        self.assertNotIn(
            "item_type = 'login'", body,
            msg=(
                "POST /list-secure-items at root must NOT filter "
                "to item_type='login' — the operator brief: the "
                "Logins & Secure Items page surfaces every "
                "vault_items row."
            ),
        )
        self.assertNotIn('item_type = "login"', body)

    def test_handler_does_not_return_encrypted_data(self) -> None:
        body = self._slice_handler()
        self.assertNotIn(
            "encrypted_data", body,
            msg=(
                "POST /list-secure-items must NEVER return "
                "encrypted_data — secrets reach the user only "
                "through the chat retrieve / explicit-reveal flow."
            ),
        )

    def test_handler_does_not_read_uploaded_files(self) -> None:
        body = self._slice_handler()
        for needle in ("uploaded_files", "file_id", "saved_name"):
            with self.subTest(needle=needle):
                self.assertNotIn(
                    needle, body,
                    msg=(
                        "POST /list-secure-items must NOT touch "
                        "uploaded_files — typed items go to Logins, "
                        "uploaded files stay in Files."
                    ),
                )

    def test_response_keys_pinned(self) -> None:
        body = self._slice_handler()
        for needle in ("service", "item_type", "created_at", '"items"'):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)


if __name__ == "__main__":                    
    unittest.main()
