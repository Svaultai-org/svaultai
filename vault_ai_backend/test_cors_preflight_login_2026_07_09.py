"""End-to-end CORS preflight regression tests for the frontend →
backend login handshake.

Motivation: before this fix, launching the Vite dev server on
``http://localhost:5173`` and pointing it at a locally-running backend
whose ``.env`` was carrying a production-shaped
``CORS_ALLOWED_ORIGIN_REGEX`` produced::

    OPTIONS /auth/login HTTP/1.1  400 Bad Request

because the CORS middleware refused the loopback origin. The fix
unions the localhost loopback pattern with any explicit regex whenever
``VAULTAI_ENV`` reads as development/local/test/ci, while leaving
production strict.

These tests exercise ``_resolve_cors_origin_regex()`` inside a real
``FastAPI`` app wearing Starlette's ``CORSMiddleware`` — the same
middleware ``main.py`` mounts — and drive a real ``OPTIONS`` preflight
through it. They do NOT touch authentication logic, PIN handling,
trusted device verification, or session security; the ``/auth/login``
route is stubbed with a no-op POST handler so the test focuses purely
on the CORS handshake.
"""

from __future__ import annotations

import os
import re
import unittest

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient



def _wipe(*names: str) -> dict:
    snap = {}
    for n in names:
        snap[n] = os.environ.get(n)
        os.environ.pop(n, None)
    return snap


def _restore(snap: dict) -> None:
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _snapshot_cors_env() -> dict:
    return _wipe(
        "VAULTAI_ENV", "ENVIRONMENT", "FLASK_ENV", "NODE_ENV",
        "CORS_ALLOWED_ORIGIN_REGEX",
    )


def _mount_preflight_app(regex: str) -> TestClient:
    """Mount a stub FastAPI app carrying the same ``CORSMiddleware``
    config ``main.py`` uses. The ``/auth/login`` POST handler is a
    no-op — CORS preflight never invokes it, so we don't need auth
    machinery."""
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-Device-Id",
        ],
        max_age=600,
    )

    @app.post("/auth/login")
    async def _login_stub() -> dict:
        return {"ok": True}

    return TestClient(app)


def _resolve_regex_under_env(env: dict) -> str:
    """Freshly resolve the CORS regex with the given env vars applied."""
    snap = _snapshot_cors_env()
    try:
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        from main import _resolve_cors_origin_regex
        return _resolve_cors_origin_regex()
    finally:
        _restore(snap)



class DevPreflightAcceptsLocalhost(unittest.TestCase):
    """OPTIONS /auth/login from :5173 succeeds in dev, even when the
    operator has also configured a production-shaped explicit regex
    (which is the common local misconfig)."""

    def test_dev_only_env_permits_localhost_5173_preflight(self) -> None:
        regex = _resolve_regex_under_env({"VAULTAI_ENV": "development"})
        client = _mount_preflight_app(regex)

        resp = client.options(
            "/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-device-id",
            },
        )
        self.assertEqual(
            resp.status_code, 200,
            msg=f"preflight failed: body={resp.text!r}",
        )
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )

        self.assertIn(
            "POST",
            resp.headers.get("access-control-allow-methods", ""),
        )

        allow_headers = (
            resp.headers.get("access-control-allow-headers", "").lower()
        )
        self.assertIn("content-type", allow_headers)
        self.assertIn("x-device-id", allow_headers)

        self.assertEqual(
            resp.headers.get("access-control-allow-credentials"),
            "true",
        )

    def test_dev_with_prod_regex_still_permits_localhost_5173(self) -> None:



        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "development",
            "CORS_ALLOWED_ORIGIN_REGEX":
                r"^https://(app|www)\.vaultai\.com$",
        })
        client = _mount_preflight_app(regex)

        resp = client.options(
            "/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-device-id",
            },
        )
        self.assertEqual(
            resp.status_code, 200,
            msg=(
                "regression: OPTIONS /auth/login from :5173 must succeed "
                "in dev even when the operator has ALSO set a "
                "production-shaped CORS_ALLOWED_ORIGIN_REGEX in .env "
                f"— body={resp.text!r}"
            ),
        )
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )

    def test_dev_permits_localhost_5173_and_127_0_0_1_5173(self) -> None:
        regex = _resolve_regex_under_env({"VAULTAI_ENV": "development"})
        client = _mount_preflight_app(regex)
        for origin in (
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ):
            with self.subTest(origin=origin):
                resp = client.options(
                    "/auth/login",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers":
                            "content-type,x-device-id",
                    },
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(
                    resp.headers.get("access-control-allow-origin"),
                    origin,
                )

    def test_dev_permits_case_insensitive_x_device_id_header(self) -> None:



        regex = _resolve_regex_under_env({"VAULTAI_ENV": "development"})
        client = _mount_preflight_app(regex)
        for hdr_variant in (
            "content-type,x-device-id",
            "content-type,X-Device-Id",
            "content-type,X-DEVICE-ID",
        ):
            with self.subTest(header=hdr_variant):
                resp = client.options(
                    "/auth/login",
                    headers={
                        "Origin": "http://localhost:5173",
                        "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": hdr_variant,
                    },
                )
                self.assertEqual(resp.status_code, 200)



class ActualPostFollowsThroughInDev(unittest.TestCase):
    """After the preflight succeeds, the real POST /auth/login from
    :5173 must also see the CORS response header attached."""

    def test_post_login_response_carries_allow_origin_header(self) -> None:
        regex = _resolve_regex_under_env({"VAULTAI_ENV": "development"})
        client = _mount_preflight_app(regex)

        resp = client.post(
            "/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Content-Type": "application/json",
                "X-Device-Id": "dev-abc",
            },
            json={"vault_name": "x", "pin": "000000"},
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )
        self.assertEqual(
            resp.headers.get("access-control-allow-credentials"),
            "true",
        )



class ProdPreflightRejectsUnknownOrigins(unittest.TestCase):
    """Production must refuse localhost preflight even after the fix.
    The union only happens in dev/local/test/ci."""

    def test_prod_refuses_localhost_5173_preflight(self) -> None:
        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "production",
            "CORS_ALLOWED_ORIGIN_REGEX":
                r"^https://(app|www)\.vaultai\.com$",
        })

        self.assertIsNone(
            re.fullmatch(regex, "http://localhost:5173"),
            msg="production regex must not match loopback origins",
        )
        self.assertIsNone(
            re.fullmatch(regex, "http://127.0.0.1:5173"),
        )

        client = _mount_preflight_app(regex)
        resp = client.options(
            "/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-device-id",
            },
        )
        self.assertEqual(
            resp.status_code, 400,
            msg=(
                "production must return 400 preflight rejection for "
                "unknown/loopback origins so the browser refuses to "
                "make the real POST"
            ),
        )

        self.assertNotIn(
            "access-control-allow-origin", resp.headers,
        )

    def test_prod_still_allows_configured_prod_origin(self) -> None:
        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "production",
            "CORS_ALLOWED_ORIGIN_REGEX":
                r"^https://(app|www)\.vaultai\.com$",
        })
        client = _mount_preflight_app(regex)
        resp = client.options(
            "/auth/login",
            headers={
                "Origin": "https://app.vaultai.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-device-id",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            "https://app.vaultai.com",
        )

    def test_prod_rejects_random_third_party_origin(self) -> None:
        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "production",
            "CORS_ALLOWED_ORIGIN_REGEX":
                r"^https://(app|www)\.vaultai\.com$",
        })
        client = _mount_preflight_app(regex)
        resp = client.options(
            "/auth/login",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertNotIn(
            "access-control-allow-origin", resp.headers,
        )



class CorsHeadersAndMethodsInvariants(unittest.TestCase):
    """Static invariants that must hold in every environment."""

    def test_x_device_id_is_in_allow_headers_list(self) -> None:
        import main
        lower = [h.lower() for h in main.CORS_ALLOWED_HEADERS]
        self.assertIn("x-device-id", lower)
        self.assertIn("content-type", lower)
        self.assertIn("authorization", lower)

    def test_options_and_post_are_in_allow_methods(self) -> None:
        import main
        upper = [m.upper() for m in main.CORS_ALLOWED_METHODS]
        self.assertIn("OPTIONS", upper)
        self.assertIn("POST", upper)

    def test_no_wildcard_origin_ever(self) -> None:



        for env in (
            {"VAULTAI_ENV": "development"},
            {"VAULTAI_ENV": "development",
             "CORS_ALLOWED_ORIGIN_REGEX": r"^https://a\.example\.com$"},
            {"VAULTAI_ENV": "production",
             "CORS_ALLOWED_ORIGIN_REGEX": r"^https://a\.example\.com$"},
        ):
            with self.subTest(env=env):
                regex = _resolve_regex_under_env(env)
                self.assertNotEqual(regex, "*")


                self.assertIsNone(
                    re.fullmatch(regex, "https://evil.example.com"),
                    msg="regex must not degenerate into a match-all",
                )


if __name__ == "__main__":
    unittest.main()
