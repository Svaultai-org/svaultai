

from __future__ import annotations

import os
import unittest


def _wipe(*names: str) -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for n in names:
        snap[n] = os.environ.get(n)
        os.environ.pop(n, None)
    return snap


def _restore(snap: dict[str, str | None]) -> None:
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _set_prod_env() -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for var in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
        snap[var] = os.environ.get(var)
        os.environ[var] = "production"
    snap["CORS_ALLOWED_ORIGIN_REGEX"] = os.environ.get(
        "CORS_ALLOWED_ORIGIN_REGEX",
    )
    os.environ.pop("CORS_ALLOWED_ORIGIN_REGEX", None)
    return snap


def _set_dev_env() -> dict[str, str | None]:
    snap: dict[str, str | None] = {}
    for var in ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV"):
        snap[var] = os.environ.get(var)
    os.environ["VAULTAI_ENV"] = "dev"
    snap["CORS_ALLOWED_ORIGIN_REGEX"] = os.environ.get(
        "CORS_ALLOWED_ORIGIN_REGEX",
    )
    os.environ.pop("CORS_ALLOWED_ORIGIN_REGEX", None)
    return snap


class CorsResolverTests(unittest.TestCase):
    def test_dev_falls_back_to_loopback_default(self) -> None:
        from main import _resolve_cors_origin_regex
        snap = _set_dev_env()
        try:
            regex = _resolve_cors_origin_regex()
        finally:
            _restore(snap)
                                                                   
                            
        self.assertIn("localhost", regex)
        self.assertIn("127", regex)

    def test_prod_without_env_raises(self) -> None:
        from main import _resolve_cors_origin_regex
        snap = _set_prod_env()
        try:
            with self.assertRaises(RuntimeError) as cm:
                _resolve_cors_origin_regex()
        finally:
            _restore(snap)
                                                                
                                                      
        self.assertIn("CORS_ALLOWED_ORIGIN_REGEX", str(cm.exception))

    def test_prod_with_explicit_env_uses_it(self) -> None:
        from main import _resolve_cors_origin_regex
        snap = _set_prod_env()
        try:
            os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = (
                r"https://app\.example\.com"
            )
            regex = _resolve_cors_origin_regex()
        finally:
            _restore(snap)
        self.assertEqual(regex, r"https://app\.example\.com")

    def test_dev_with_explicit_env_unions_localhost(self) -> None:



        import re as _re
        from main import _resolve_cors_origin_regex
        snap = _set_dev_env()
        try:
            os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = (
                r"https://dev\.example\.com"
            )
            regex = _resolve_cors_origin_regex()
        finally:
            _restore(snap)

        self.assertIn(r"https://dev\.example\.com", regex)

        for origin in (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "https://dev.example.com",
        ):
            self.assertIsNotNone(
                _re.fullmatch(regex, origin),
                msg=(
                    f"dev-mode CORS regex must accept {origin} even "
                    "when a production-shaped explicit regex is set "
                    "(local misconfig is the common source of the "
                    "OPTIONS /auth/login → 400 bug)"
                ),
            )

    def test_prod_with_explicit_env_does_not_union_localhost(self) -> None:



        import re as _re
        from main import _resolve_cors_origin_regex
        snap = _set_prod_env()
        try:
            os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = (
                r"^https://app\.example\.com$"
            )
            regex = _resolve_cors_origin_regex()
        finally:
            _restore(snap)

        self.assertNotIn("localhost", regex)
        self.assertNotIn("127", regex)

        for origin in (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8080",
        ):
            self.assertIsNone(
                _re.fullmatch(regex, origin),
                msg=(
                    f"production CORS regex must NOT match {origin} — "
                    "production origins stay restricted"
                ),
            )

    def test_prod_resolver_does_not_silently_allow_wildcard(self) -> None:
                                                                        
                                                                  
        import inspect, main
        src = inspect.getsource(main._resolve_cors_origin_regex)
        self.assertNotIn('".*"', src)
        self.assertNotIn("'.*'", src)
        self.assertNotIn('allow_origins=["*"]', src)


if __name__ == "__main__":
    unittest.main()
