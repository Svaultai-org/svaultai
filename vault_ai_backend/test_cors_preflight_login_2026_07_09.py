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
            "X-App-Locale",
            "X-Device-Id",
            # Kept in lock-step with main.CORS_ALLOWED_HEADERS.
            # The 2026-07-22 (3) production CORS regression traced
            # to this stub falling behind the real allowlist.
            "X-App-Release",
            # 2026-07-22 (4) Safari preflight adds Cache-Control and
            # Pragma to Access-Control-Request-Headers for GETs. Same
            # lock-step invariant: this stub must mirror the real
            # main.CORS_ALLOWED_HEADERS list or the browser-shape
            # regression tests below silently pass on a wrong stub.
            "Cache-Control",
            "Pragma",
        ],
        max_age=600,
    )

    @app.post("/auth/login")
    async def _login_stub() -> dict:
        return {"ok": True}

    @app.post("/chat")
    async def _chat_stub() -> dict:
        return {"ok": True}

    # 2026-07-22 (3): stubs for the endpoints that broke in
    # production when the CORS preflight started including
    # x-app-release. Only OPTIONS matters for the preflight
    # invariant; the concrete method (GET/POST) is preflight-
    # neutral so a single POST stub covers all of them.
    async def _empty_ok() -> dict:
        return {"ok": True}

    for _path in (
        "/vault-meta",
        "/devices/register",
        "/list-my-vaults",
        "/notifications",
        "/vault-stats",
        "/billing/me",
        "/list-files",
        "/folders",
        "/list-secure-items",
    ):
        app.add_api_route(_path, _empty_ok, methods=["POST", "GET"])

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

    def test_x_app_locale_is_in_allow_headers_list(self) -> None:

        import main
        lower = [h.lower() for h in main.CORS_ALLOWED_HEADERS]
        self.assertIn(
            "x-app-locale", lower,
            msg=(
                "X-App-Locale must be in CORS_ALLOWED_HEADERS or the "
                "production browser preflight for /chat will fail "
                "with 400 Bad Request from the frontend at "
                "https://app.svaultai.com"
            ),
        )

    def test_x_app_release_is_in_allow_headers_list(self) -> None:
        # 2026-07-22 (3) production CORS regression: the 7b34d92
        # client build added X-App-Release to _defaultHeaders() as
        # a diagnostic-only field. Every preflight from
        # https://app.svaultai.com included it in
        # Access-Control-Request-Headers, and every one was
        # rejected 400 by Starlette because this list did not
        # include x-app-release. Every authenticated endpoint
        # stopped working from the browser (the real GET/POST
        # never fired). This invariant makes sure the header stays
        # in the allowlist while it is emitted by the client.
        import main
        lower = [h.lower() for h in main.CORS_ALLOWED_HEADERS]
        self.assertIn(
            "x-app-release", lower,
            msg=(
                "X-App-Release must be in CORS_ALLOWED_HEADERS or "
                "every browser preflight from the production frontend "
                "will fail with 400 Bad Request — same class of "
                "regression that blocked /vault-meta, "
                "/devices/register, /list-my-vaults, /notifications, "
                "/vault-stats, /billing/me, /list-files, /folders, "
                "/list-secure-items after the 7b34d92 deploy."
            ),
        )

    def test_cache_control_and_pragma_are_in_allow_headers_list(
        self,
    ) -> None:
        # 2026-07-22 (4) Safari CORS regression follow-up. After (3)
        # landed and X-App-Release was allowed, Safari's preflight
        # for /vault-meta still failed 400 because its Access-
        # Control-Request-Headers also carries Cache-Control and
        # Pragma. Same class of bug as (3): a header the client
        # forwards to the preflight is absent from the server
        # allowlist. Both must remain in the allowlist for Safari
        # to reach any authenticated endpoint from the production
        # frontend.
        import main
        lower = [h.lower() for h in main.CORS_ALLOWED_HEADERS]
        self.assertIn(
            "cache-control", lower,
            msg=(
                "Cache-Control must be in CORS_ALLOWED_HEADERS or "
                "Safari's preflight for /vault-meta from "
                "https://app.svaultai.com will fail 400 — same class "
                "of regression as (3)/x-app-release."
            ),
        )
        self.assertIn(
            "pragma", lower,
            msg=(
                "Pragma must be in CORS_ALLOWED_HEADERS or Safari's "
                "preflight will fail 400 alongside Cache-Control."
            ),
        )

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


class ProdChatPreflightAcceptsAppLocaleFromSvaultai(unittest.TestCase):
    """Regression: production browser chat preflight from
    ``https://app.svaultai.com`` sends the header set

        authorization,content-type,x-app-locale,x-device-id

    and must return 200 with all four headers echoed in
    ``access-control-allow-headers`` and the concrete origin echoed
    in ``access-control-allow-origin``. Before the fix, ``x-app-locale``
    was missing from ``CORS_ALLOWED_HEADERS`` and Starlette returned
    400."""

    _PROD_REGEX = (
        r"^https://(app|www)\.svaultai\.com$|^https://svaultai\.com$"
    )
    _ORIGIN = "https://app.svaultai.com"

    def test_options_chat_from_app_svaultai_succeeds_with_all_headers(
        self,
    ) -> None:
        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "production",
            "CORS_ALLOWED_ORIGIN_REGEX": self._PROD_REGEX,
        })
        client = _mount_preflight_app(regex)

        resp = client.options(
            "/chat",
            headers={
                "Origin": self._ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers":
                    "authorization,content-type,x-app-locale,x-device-id",
            },
        )
        self.assertEqual(
            resp.status_code, 200,
            msg=(
                f"prod preflight for /chat from {self._ORIGIN} must "
                f"return 200 — got {resp.status_code}: {resp.text!r}"
            ),
        )
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            self._ORIGIN,
            msg="ACAO must echo the exact concrete origin, not '*'",
        )

        allow_hdrs = (
            resp.headers.get("access-control-allow-headers", "").lower()
        )
        for h in (
            "authorization", "content-type",
            "x-app-locale", "x-device-id",
        ):
            self.assertIn(
                h, allow_hdrs,
                msg=(
                    f"access-control-allow-headers must include {h}: "
                    f"got {allow_hdrs!r}"
                ),
            )

        self.assertIn(
            "POST",
            resp.headers.get("access-control-allow-methods", ""),
        )

        self.assertEqual(
            resp.headers.get("access-control-allow-credentials"),
            "true",
        )

    def test_options_auth_login_from_app_svaultai_also_accepts_app_locale(
        self,
    ) -> None:

        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "production",
            "CORS_ALLOWED_ORIGIN_REGEX": self._PROD_REGEX,
        })
        client = _mount_preflight_app(regex)
        resp = client.options(
            "/auth/login",
            headers={
                "Origin": self._ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers":
                    "content-type,x-app-locale,x-device-id",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            self._ORIGIN,
        )

    def test_prod_still_refuses_localhost_when_x_app_locale_is_in_header_set(
        self,
    ) -> None:

        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "production",
            "CORS_ALLOWED_ORIGIN_REGEX": self._PROD_REGEX,
        })
        client = _mount_preflight_app(regex)
        resp = client.options(
            "/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers":
                    "authorization,content-type,x-app-locale,x-device-id",
            },
        )
        self.assertEqual(
            resp.status_code, 400,
            msg="production must refuse localhost even when the "
                "requested headers are all in the allow-list",
        )
        self.assertNotIn(
            "access-control-allow-origin", resp.headers,
        )

    def test_dev_still_accepts_x_app_locale_from_localhost(self) -> None:

        regex = _resolve_regex_under_env({"VAULTAI_ENV": "development"})
        client = _mount_preflight_app(regex)
        resp = client.options(
            "/chat",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers":
                    "authorization,content-type,x-app-locale,x-device-id",
            },
        )
        self.assertEqual(resp.status_code, 200)
        allow_hdrs = (
            resp.headers.get("access-control-allow-headers", "").lower()
        )
        self.assertIn("x-app-locale", allow_hdrs)


class ProdPreflightAcceptsXAppReleaseFromSvaultai(unittest.TestCase):
    """2026-07-22 (3) production CORS regression reproduction.

    After the 7b34d92 deploy, the frontend at
    https://app.svaultai.com sent this preflight for every
    authenticated request:

        OPTIONS <endpoint>
        Origin: https://app.svaultai.com
        Access-Control-Request-Method: GET | POST
        Access-Control-Request-Headers:
            authorization, content-type, x-app-release, x-device-id

    Starlette returned 400 because x-app-release was not in
    CORS_ALLOWED_HEADERS. That silently blocked /vault-meta,
    /devices/register, /list-my-vaults, /notifications,
    /vault-stats, /billing/me, /list-files, /folders,
    /list-secure-items — the browser never sent the real GET/POST.
    Surface symptoms: "Could not load files" and "Vault crypto
    state is out of sync" (because /vault-meta never executed).

    These tests reproduce the exact preflight for every endpoint
    named in the production report. Each must return 200 with
    x-app-release echoed in access-control-allow-headers."""

    _PROD_REGEX = (
        r"^https://(app|www)\.svaultai\.com$|^https://svaultai\.com$"
    )
    _ORIGIN = "https://app.svaultai.com"
    # The exact ACRH string production browsers emitted post-7b34d92.
    _ACRH_WITH_APP_RELEASE = (
        "authorization,content-type,x-app-release,x-device-id"
    )
    # Endpoints from the production incident report.
    _AFFECTED_ENDPOINTS = (
        ("/devices/register",       "POST"),
        ("/vault-meta",             "GET"),
        ("/list-my-vaults",         "POST"),
        ("/notifications",          "GET"),
        ("/vault-stats",            "POST"),
        ("/billing/me",             "GET"),
        ("/list-files",             "POST"),
        ("/folders",                "GET"),
        ("/list-secure-items",      "POST"),
    )

    def _client(self) -> TestClient:
        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "production",
            "CORS_ALLOWED_ORIGIN_REGEX": self._PROD_REGEX,
        })
        return _mount_preflight_app(regex)

    def test_every_reported_endpoint_preflight_from_svaultai_returns_200(
        self,
    ) -> None:
        client = self._client()
        for path, method in self._AFFECTED_ENDPOINTS:
            with self.subTest(path=path, method=method):
                resp = client.options(
                    path,
                    headers={
                        "Origin": self._ORIGIN,
                        "Access-Control-Request-Method": method,
                        "Access-Control-Request-Headers":
                            self._ACRH_WITH_APP_RELEASE,
                    },
                )
                self.assertEqual(
                    resp.status_code, 200,
                    msg=(
                        f"OPTIONS {path} from {self._ORIGIN} with "
                        f"ACRH={self._ACRH_WITH_APP_RELEASE!r} must "
                        f"return 200 — got {resp.status_code}. "
                        f"body={resp.text!r}"
                    ),
                )
                self.assertEqual(
                    resp.headers.get("access-control-allow-origin"),
                    self._ORIGIN,
                    msg=(
                        "ACAO must echo the concrete production origin, "
                        "not '*'"
                    ),
                )
                allow_hdrs = (
                    resp.headers.get(
                        "access-control-allow-headers", "",
                    ).lower()
                )
                for h in (
                    "authorization", "content-type",
                    "x-app-release", "x-device-id",
                ):
                    self.assertIn(
                        h, allow_hdrs,
                        msg=(
                            f"access-control-allow-headers must include "
                            f"{h}: got {allow_hdrs!r}"
                        ),
                    )

    def test_options_vault_meta_specifically_returns_200(self) -> None:
        # Named-endpoint test so a grep for '/vault-meta' in future
        # test failures immediately points here. /vault-meta is the
        # request whose 400 preflight surfaced client-side as "Vault
        # crypto state is out of sync" (the client's own error copy
        # for a missing meta refetch).
        client = self._client()
        resp = client.options(
            "/vault-meta",
            headers={
                "Origin": self._ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers":
                    self._ACRH_WITH_APP_RELEASE,
            },
        )
        self.assertEqual(resp.status_code, 200, msg=resp.text)
        self.assertIn(
            "x-app-release",
            resp.headers.get("access-control-allow-headers", "").lower(),
        )

    def test_pre_fix_state_is_the_400_the_production_frontend_saw(
        self,
    ) -> None:
        # Sanity check that the regression scenario is REAL: mount a
        # stub app whose CORS allowlist is missing x-app-release
        # (the pre-fix state) and confirm the exact production
        # symptom — Starlette returns 400 with no ACAO header.
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        pre_fix_app = FastAPI()
        pre_fix_app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=self._PROD_REGEX,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "Authorization", "Content-Type", "Accept", "Origin",
                "X-Requested-With", "X-App-Locale", "X-Device-Id",
                # Deliberately WITHOUT X-App-Release — mirrors the
                # 7b34d92 pre-fix state.
            ],
            max_age=600,
        )

        @pre_fix_app.get("/vault-meta")
        async def _stub() -> dict:
            return {"ok": True}

        client = TestClient(pre_fix_app)
        resp = client.options(
            "/vault-meta",
            headers={
                "Origin": self._ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers":
                    self._ACRH_WITH_APP_RELEASE,
            },
        )
        self.assertEqual(
            resp.status_code, 400,
            msg=(
                "PROVEN — the pre-fix state (x-app-release absent from "
                "the CORS allowlist) returns exactly 400 for the "
                "production preflight. That is the response the "
                "frontend saw for every failing endpoint after the "
                "7b34d92 deploy."
            ),
        )
        # The rejected preflight's access-control-allow-headers must
        # NOT include x-app-release — that mismatch (requested but
        # not allowed) is the exact reason the browser blocks the
        # follow-up GET/POST. The 400 status is the primary signal
        # the frontend saw; this assertion documents why the browser
        # treated it as a CORS failure regardless of status code.
        allow_hdrs = (
            resp.headers.get(
                "access-control-allow-headers", "",
            ).lower()
        )
        self.assertNotIn(
            "x-app-release", allow_hdrs,
            msg=(
                "pre-fix allow-headers must NOT include x-app-release "
                "— that omission is the reason the browser refused "
                "the follow-up request"
            ),
        )


class ProdPreflightAcceptsSafariCacheHintsFromSvaultai(unittest.TestCase):
    """2026-07-22 (4) Safari-specific CORS regression follow-up.

    After the (3) X-App-Release fix landed and Chrome preflights
    succeeded, Safari on the production frontend still failed
    OPTIONS /vault-meta with:

        400 Bad Request
        Disallowed CORS headers

    with failing header list
        authorization,cache-control,pragma,x-app-release,x-device-id

    Safari attaches Cache-Control and Pragma to
    Access-Control-Request-Headers for GETs (unlike Chrome, which
    only forwards custom headers). Same class of bug as (3): the
    browser advertises a header in the preflight that the server's
    allowlist does not include. Both Cache-Control and Pragma must
    now be present.

    These tests reproduce the exact Safari preflight for
    /vault-meta and confirm 200 with Cache-Control, Pragma, and
    X-App-Release all echoed in access-control-allow-headers."""

    _PROD_REGEX = (
        r"^https://(app|www)\.svaultai\.com$|^https://svaultai\.com$"
    )
    _ORIGIN = "https://app.svaultai.com"
    # The exact ACRH string Safari sent for OPTIONS /vault-meta on
    # the post-(3) deploy.
    _SAFARI_ACRH = (
        "authorization,cache-control,pragma,x-app-release,x-device-id"
    )

    def _client(self) -> TestClient:
        regex = _resolve_regex_under_env({
            "VAULTAI_ENV": "production",
            "CORS_ALLOWED_ORIGIN_REGEX": self._PROD_REGEX,
        })
        return _mount_preflight_app(regex)

    def test_safari_vault_meta_preflight_returns_200(self) -> None:
        # Exact production-Safari preflight for /vault-meta.
        client = self._client()
        resp = client.options(
            "/vault-meta",
            headers={
                "Origin": self._ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": self._SAFARI_ACRH,
            },
        )
        self.assertEqual(
            resp.status_code, 200,
            msg=(
                f"Safari preflight for /vault-meta must return 200 "
                f"with ACRH={self._SAFARI_ACRH!r}. Got "
                f"{resp.status_code}. body={resp.text!r}"
            ),
        )
        self.assertEqual(
            resp.headers.get("access-control-allow-origin"),
            self._ORIGIN,
        )
        allow_hdrs = (
            resp.headers.get("access-control-allow-headers", "").lower()
        )
        for h in (
            "authorization",
            "cache-control",
            "pragma",
            "x-app-release",
            "x-device-id",
        ):
            self.assertIn(
                h, allow_hdrs,
                msg=(
                    f"access-control-allow-headers must include {h} "
                    f"for the Safari preflight — got {allow_hdrs!r}"
                ),
            )

    def test_safari_preflight_shape_across_reported_endpoints(
        self,
    ) -> None:
        # Guard: Safari's ACRH shape must work on every endpoint the
        # (3) fix already covered. If any of these were to 400 under
        # the Safari header set, /vault-meta would not be the only
        # broken surface — that failure mode is what happened before
        # this commit.
        client = self._client()
        endpoints = (
            ("/devices/register",  "POST"),
            ("/vault-meta",        "GET"),
            ("/list-my-vaults",    "POST"),
            ("/notifications",     "GET"),
            ("/vault-stats",       "POST"),
            ("/billing/me",        "GET"),
            ("/list-files",        "POST"),
            ("/folders",           "GET"),
            ("/list-secure-items", "POST"),
        )
        for path, method in endpoints:
            with self.subTest(path=path, method=method):
                resp = client.options(
                    path,
                    headers={
                        "Origin": self._ORIGIN,
                        "Access-Control-Request-Method": method,
                        "Access-Control-Request-Headers":
                            self._SAFARI_ACRH,
                    },
                )
                self.assertEqual(
                    resp.status_code, 200,
                    msg=(
                        f"OPTIONS {path} (Safari-shape preflight) "
                        f"must return 200 — got {resp.status_code}. "
                        f"body={resp.text!r}"
                    ),
                )
                allow_hdrs = (
                    resp.headers.get(
                        "access-control-allow-headers", "",
                    ).lower()
                )
                # Both new headers must be present. The (3) header
                # set is covered by the other class; this class's
                # unique invariant is Cache-Control + Pragma.
                self.assertIn("cache-control", allow_hdrs)
                self.assertIn("pragma", allow_hdrs)

    def test_pre_fix_state_is_the_400_safari_saw(self) -> None:
        # Negative-path proof: the pre-(4) state (Cache-Control and
        # Pragma absent from the allowlist) returns exactly the 400
        # Safari saw. Mirrors the pattern in the (3) regression
        # class and guarantees the fix would fail closed if either
        # header were dropped from CORS_ALLOWED_HEADERS.
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        pre_fix_app = FastAPI()
        pre_fix_app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=self._PROD_REGEX,
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "Authorization", "Content-Type", "Accept", "Origin",
                "X-Requested-With", "X-App-Locale", "X-Device-Id",
                "X-App-Release",
                # Deliberately WITHOUT Cache-Control and Pragma —
                # mirrors the post-(3) / pre-(4) production state.
            ],
            max_age=600,
        )

        @pre_fix_app.get("/vault-meta")
        async def _stub() -> dict:
            return {"ok": True}

        client = TestClient(pre_fix_app)
        resp = client.options(
            "/vault-meta",
            headers={
                "Origin": self._ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": self._SAFARI_ACRH,
            },
        )
        self.assertEqual(
            resp.status_code, 400,
            msg=(
                "PROVEN — with Cache-Control and Pragma absent from "
                "the CORS allowlist, Safari's /vault-meta preflight "
                "returns exactly 400. That is the response Safari "
                "showed after the (3) deploy on the production "
                "frontend."
            ),
        )
        allow_hdrs = (
            resp.headers.get(
                "access-control-allow-headers", "",
            ).lower()
        )
        self.assertNotIn(
            "cache-control", allow_hdrs,
            msg=(
                "pre-fix allow-headers must NOT include cache-control "
                "— that omission is why Safari refused /vault-meta"
            ),
        )
        self.assertNotIn(
            "pragma", allow_hdrs,
            msg=(
                "pre-fix allow-headers must NOT include pragma — "
                "same reason"
            ),
        )


if __name__ == "__main__":
    unittest.main()
