

from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


_BACKEND_ROOT = Path(__file__).resolve().parent


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


class IsProductionEnvTokenTests(unittest.TestCase):


    ENV_VARS = ("VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV")

    def setUp(self) -> None:
        self._snap = _wipe(*self.ENV_VARS)

    def tearDown(self) -> None:
        _restore(self._snap)

    def test_no_env_token_is_dev(self) -> None:
                                                                
        from vault_config import is_production, is_dev_or_local
        self.assertFalse(is_production())
        self.assertTrue(is_dev_or_local())

    def test_prod_tokens_flip_to_production(self) -> None:
        from vault_config import is_production
        for token in ("prod", "production", "live"):
            for var in self.ENV_VARS:
                _restore(self._snap)
                _wipe(*self.ENV_VARS)
                os.environ[var] = token
                self.assertTrue(
                    is_production(),
                    f"{var}={token!r} must flip is_production()",
                )

    def test_dev_tokens_stay_dev(self) -> None:
        from vault_config import is_production, is_dev_or_local
        for token in ("dev", "development", "local", "test", "ci"):
            for var in self.ENV_VARS:
                _restore(self._snap)
                _wipe(*self.ENV_VARS)
                os.environ[var] = token
                self.assertFalse(
                    is_production(),
                    f"{var}={token!r} must NOT be production",
                )
                self.assertTrue(is_dev_or_local())

    def test_garbage_token_does_not_flip_to_prod(self) -> None:
        from vault_config import is_production
        for var in self.ENV_VARS:
            _restore(self._snap)
            _wipe(*self.ENV_VARS)
            os.environ[var] = "wat"
            self.assertFalse(is_production())


class ProductionFailClosedBootTests(unittest.TestCase):


    ENV_VARS = (
        "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
        "VAULT_SESSION_SECRET",
        "CORS_ALLOWED_ORIGIN_REGEX",
        "CORS_ALLOWED_ORIGINS",
        "VAULTAI_DEBUG_ENDPOINTS_ENABLED",
        "STRIPE_WEBHOOK_SECRET",
        "VAULTAI_DEVICE_GATE_DEV_AUTO_TRUST",
    )

    def setUp(self) -> None:
        self._snap = _wipe(*self.ENV_VARS)
                                            
        import vault_config
        vault_config.reset_for_tests()

    def tearDown(self) -> None:
        _restore(self._snap)
        import vault_config
        vault_config.reset_for_tests()

    def _set_prod(self) -> None:
        os.environ["VAULTAI_ENV"] = "production"

    def test_prod_without_session_secret_refuses_boot(self) -> None:
        self._set_prod()
                                                                     
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = r"https://app\.example\.com"
        from vault_config import get_config, reset_for_tests
        reset_for_tests()
        with self.assertRaises(RuntimeError) as cm:
            get_config()
        msg = str(cm.exception)
                                                                
        self.assertIn("VAULT_SESSION_SECRET", msg)
                                                    
        self.assertNotIn("password", msg.lower())

    def test_prod_without_cors_refuses_boot(self) -> None:
        self._set_prod()
        os.environ["VAULT_SESSION_SECRET"] = "x" * 64
        from vault_config import get_config, reset_for_tests
        reset_for_tests()
        with self.assertRaises(RuntimeError) as cm:
            get_config()
        msg = str(cm.exception)
        self.assertIn("CORS_ALLOWED_ORIGIN_REGEX", msg)

    def test_prod_with_debug_endpoints_refuses_boot(self) -> None:
        self._set_prod()
        os.environ["VAULT_SESSION_SECRET"] = "x" * 64
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = r"https://app\.example\.com"
        os.environ["VAULTAI_DEBUG_ENDPOINTS_ENABLED"] = "true"
        from vault_config import get_config, reset_for_tests
        reset_for_tests()
        with self.assertRaises(RuntimeError) as cm:
            get_config()
        self.assertIn("VAULTAI_DEBUG_ENDPOINTS_ENABLED", str(cm.exception))

    def test_prod_with_all_required_vars_boots(self) -> None:


        self._set_prod()
        os.environ["VAULT_SESSION_SECRET"] = "x" * 64
        os.environ["CORS_ALLOWED_ORIGIN_REGEX"] = r"https://app\.example\.com"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_stub"
        from vault_config import get_config, reset_for_tests
        reset_for_tests()
        cfg = get_config()
        self.assertTrue(cfg.is_production)
        self.assertFalse(cfg.cache.debug_endpoints_enabled)
                                                             
        described = cfg.describe()
        flat = repr(described).lower()
        self.assertNotIn("vault_session_secret", flat)
        self.assertNotIn(("x" * 64).lower(), flat)


class HealthEndpointSourceGuardTests(unittest.TestCase):


    def test_health_endpoint_uses_safe_error_envelope(self) -> None:
        path = _BACKEND_ROOT / "main.py"
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
                                                                 
                                                               
        anchor = '@app.get("/health")'
        self.assertIn(anchor, src, "/health route must exist")
        idx = src.index(anchor)
                                                           
        body = src[idx : idx + 4000]
        self.assertIn(
            "type(exc).__name__", body,
            "/health must log exception CLASS NAME, not str(exc) "
            "(psycopg2.OperationalError stringifies into the DSN).",
        )
                                                              
        self.assertIn('"connected"', body)
        self.assertIn('"unavailable"', body)


class CryptoRevealRateLimitTests(unittest.TestCase):


    def setUp(self) -> None:
                                                               
                                                                   
        from rate_limit_backend import reset_rate_limit_backend_for_tests
        reset_rate_limit_backend_for_tests()

    def tearDown(self) -> None:
        from rate_limit_backend import reset_rate_limit_backend_for_tests
        reset_rate_limit_backend_for_tests()

    def test_under_limit_does_not_raise(self) -> None:
        from rate_limit_crypto_reveal import (
            enforce_crypto_reveal_rate_limit,
            CRYPTO_REVEAL_LIMIT_PER_WINDOW,
        )
                                        
        for _ in range(CRYPTO_REVEAL_LIMIT_PER_WINDOW):
            enforce_crypto_reveal_rate_limit("vault-A")

    def test_over_limit_raises_429(self) -> None:
        from fastapi import HTTPException
        from rate_limit_crypto_reveal import (
            enforce_crypto_reveal_rate_limit,
            CRYPTO_REVEAL_LIMIT_PER_WINDOW,
        )
        for _ in range(CRYPTO_REVEAL_LIMIT_PER_WINDOW):
            enforce_crypto_reveal_rate_limit("vault-A")
        with self.assertRaises(HTTPException) as cm:
            enforce_crypto_reveal_rate_limit("vault-A")
        self.assertEqual(cm.exception.status_code, 429)
        detail = cm.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual(detail.get("reveal_error"), "rate_limited")
        self.assertIn("reset_in_seconds", detail)
                                                                     
        self.assertNotIn("vault", str(detail).lower())
        self.assertNotIn("pin", str(detail).lower())

    def test_429_carries_retry_after_header(self) -> None:
        from fastapi import HTTPException
        from rate_limit_crypto_reveal import (
            enforce_crypto_reveal_rate_limit,
            CRYPTO_REVEAL_LIMIT_PER_WINDOW,
        )
        for _ in range(CRYPTO_REVEAL_LIMIT_PER_WINDOW):
            enforce_crypto_reveal_rate_limit("vault-A")
        with self.assertRaises(HTTPException) as cm:
            enforce_crypto_reveal_rate_limit("vault-A")
        headers = cm.exception.headers or {}
        self.assertIn("Retry-After", headers)

    def test_buckets_isolate_by_vault(self) -> None:
                                                                  
                                                                  
        from fastapi import HTTPException
        from rate_limit_crypto_reveal import (
            enforce_crypto_reveal_rate_limit,
            CRYPTO_REVEAL_LIMIT_PER_WINDOW,
        )
        for _ in range(CRYPTO_REVEAL_LIMIT_PER_WINDOW):
            enforce_crypto_reveal_rate_limit("vault-A")
                                  
        with self.assertRaises(HTTPException):
            enforce_crypto_reveal_rate_limit("vault-A")
                                               
        for _ in range(CRYPTO_REVEAL_LIMIT_PER_WINDOW):
            enforce_crypto_reveal_rate_limit("vault-B")

    def test_module_does_not_import_secret_state(self) -> None:
                                                                
                                                                  
        import ast
        path = _BACKEND_ROOT / "rate_limit_crypto_reveal.py"
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        forbidden_modules = {
            "vault_core", "auth_local", "crypto_schemas",
            "device_gate", "stripe_service",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name.split(".")[0], forbidden_modules,
                        f"rate_limit_crypto_reveal must not import "
                        f"{alias.name!r}",
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                self.assertNotIn(
                    mod, forbidden_modules,
                    f"rate_limit_crypto_reveal must not import "
                    f"from {node.module!r}",
                )

    def test_reveal_handler_calls_limit_before_pin_verify(self) -> None:
                                               
                                                                    
        path = _BACKEND_ROOT / "routes" / "login_routes.py"
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
                                                                   
        anchor = '@router.post("/crypto/reveal-sensitive-backup")'
        self.assertIn(anchor, src)
        body = src[src.index(anchor):]
                                                                  
                                                           
        next_route = body.find("\n@router.", 50)
        if next_route > 0:
            body = body[:next_route]
        limit_at = body.find("enforce_crypto_reveal_rate_limit(")
        pin_at   = body.find("verify_vault_pin(")
        self.assertGreater(
            limit_at, -1, "rate limit not wired into reveal handler",
        )
        self.assertGreater(
            pin_at, -1, "PIN verify must remain in reveal handler",
        )
        self.assertLess(
            limit_at, pin_at,
            "rate limit MUST fire before PIN verify so a flood can't "
            "pin the worker on PBKDF2 work",
        )

    def test_reveal_handler_category_precheck_still_first(self) -> None:
                                                                 
                                                                  
        path = _BACKEND_ROOT / "routes" / "login_routes.py"
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
        anchor = '@router.post("/crypto/reveal-sensitive-backup")'
        body = src[src.index(anchor):]
        next_route = body.find("\n@router.", 50)
        if next_route > 0:
            body = body[:next_route]
        category_at = body.find(
            "requires_warning_confirmation_for_category(",
        )
        limit_at = body.find("enforce_crypto_reveal_rate_limit(")
        self.assertGreater(category_at, -1)
        self.assertGreater(limit_at, -1)
        self.assertLess(
            category_at, limit_at,
            "category pre-check must remain BEFORE rate-limit so "
            "wrong-category probes don't burn the legit budget",
        )


class CryptoRevealLimitEnvOverrideTests(unittest.TestCase):


    def test_env_int_safely_falls_back_on_garbage(self) -> None:
                                                                    
                                                                   
        with patch.dict(
            os.environ,
            {"VAULTAI_CRYPTO_REVEAL_LIMIT": "nope-not-a-number"},
            clear=False,
        ):
            sys.modules.pop("rate_limit_crypto_reveal", None)
            import rate_limit_crypto_reveal as rlc
            self.assertGreaterEqual(rlc.CRYPTO_REVEAL_LIMIT_PER_WINDOW, 1)
            self.assertLessEqual(rlc.CRYPTO_REVEAL_LIMIT_PER_WINDOW, 10_000)
                                                          
        sys.modules.pop("rate_limit_crypto_reveal", None)


if __name__ == "__main__":
    unittest.main()
