

from __future__ import annotations

import unittest
from pathlib import Path


_ROUTES_FILE  = Path("routes/login_routes.py")
_MAIN_FILE    = Path("main.py")


_FORBIDDEN_SEED_NAMES: tuple[str, ...] = (
    "'Payment Card'",
    "'ID Document'",
    "'Bank Account'",
    '"Payment Card"',
    '"ID Document"',
    '"Bank Account"',
)


class TestListSecureItemsHandlerHasNoHardcodedRows(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _ROUTES_FILE.read_text(encoding="utf-8")
        anchor = '@router.post("/list-secure-items")'
        start  = self.src.index(anchor)
                                                               
                                   
        idx = self.src.find("@router.", start + 1)
        end = idx if idx != -1 else len(self.src)
        self.body = self.src[start:end]

    def test_handler_filters_by_vault_id(self) -> None:
                                                               
                                      
        self.assertRegex(
            self.body,
            r"WHERE\s+vault_id\s*=\s*%s",
            msg=(
                "list_secure_items must scope rows by vault_id — "
                "operator: production/local real vault must only "
                "return rows for that vault"
            ),
        )

    def test_handler_does_not_carry_hardcoded_demo_rows(self) -> None:
        for name in _FORBIDDEN_SEED_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(
                    name, self.body,
                    msg=(
                        f"list_secure_items handler contains the "
                        f"hardcoded name {name} — operator: NO "
                        "demo / seed rows may surface in a real "
                        "user's Logins page"
                    ),
                )

    def test_handler_does_not_insert_demo_rows(self) -> None:
                                
        for needle in (
            "INSERT INTO vault_items",
            "INSERT INTO uploaded_files",
        ):
            with self.subTest(needle=needle):
                self.assertNotIn(
                    needle, self.body,
                    msg=(
                        f"list_secure_items must NOT execute "
                        f"{needle!r} — read-only handler"
                    ),
                )


class TestRouteFileHasNoSeededInserts(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _ROUTES_FILE.read_text(encoding="utf-8")

    def test_file_does_not_insert_demo_rows(self) -> None:
                                                            
                                                              
        self.assertNotIn(
            "INSERT INTO vault_items", self.src,
            msg=(
                "routes/login_routes.py grew an INSERT — that "
                "doesn't belong here. Writes belong in the "
                "save / manage paths"
            ),
        )

    def test_no_hardcoded_seed_names_in_file(self) -> None:
        for name in _FORBIDDEN_SEED_NAMES:
            with self.subTest(name=name):
                self.assertNotIn(
                    name, self.src,
                    msg=(
                        f"routes/login_routes.py contains the "
                        f"hardcoded name {name} — operator brief "
                        "forbids seeded demo rows"
                    ),
                )


class TestMainHasNoUnconditionalSeedInsert(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _MAIN_FILE.read_text(encoding="utf-8")

    def test_no_hardcoded_payment_card_insert(self) -> None:
                                                           
                                                              
        import re
        for name in ("Payment Card", "ID Document", "Bank Account"):
            pattern = re.compile(
                r"INSERT INTO vault_items[\s\S]{0,400}?"
                + re.escape(name),
                re.IGNORECASE,
            )
            matches = pattern.findall(self.src)
            with self.subTest(name=name):
                self.assertEqual(
                    matches, [],
                    msg=(
                        f"main.py contains an INSERT for the "
                        f"hardcoded name {name!r} within 400 chars "
                        "— operator: no demo seed rows. If this is "
                        "user-driven (e.g. extracted credentials), "
                        "guard the path behind an explicit user "
                        "action."
                    ),
                )


class TestFlutterApiClientHasNoMockFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(
            "../vault_ai_frontend/lib/api_client.dart"
        )

    def test_list_secure_items_function_does_not_return_mocks(self) -> None:
        if not self.path.exists():
            self.skipTest("api_client.dart not on disk")
        src = self.path.read_text(encoding="utf-8")
        anchor = "Future<Map<String, dynamic>> listVaultSecureItems("
        start  = src.index(anchor)
                                                                  
                                    
        idx = src.find("\nFuture<", start + 1)
        end = idx if idx != -1 else min(start + 4000, len(src))
        body = src[start:end]
        for needle in (
            "Payment Card",
            "ID Document",
            "Bank Account",
            "demoItems",
            "mockItems",
            "fakeItems",
            "sampleItems",
        ):
            with self.subTest(needle=needle):
                self.assertNotIn(
                    needle, body,
                    msg=(
                        f"listVaultSecureItems body contains "
                        f"{needle!r} — operator brief: no "
                        "mock / demo fallback. Surface the error "
                        "instead so the user knows the list "
                        "didn't load."
                    ),
                )


if __name__ == "__main__":                    
    unittest.main()
