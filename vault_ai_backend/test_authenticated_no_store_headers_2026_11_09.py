"""Authenticated API responses cannot be cached when a route is added."""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import Response

from security_headers import SecurityHeadersMiddleware


def _request(*, authenticated: bool) -> Request:
    headers = [(b"host", b"test.invalid")]
    if authenticated:
        headers.append((b"authorization", b"Bearer synthetic-session"))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/new-private-route-not-in-prefix-list",
        "raw_path": b"/new-private-route-not-in-prefix-list",
        "query_string": b"",
        "headers": headers,
        "scheme": "https",
        "server": ("test.invalid", 443),
        "client": ("127.0.0.1", 1234),
    })


def test_authenticated_unknown_route_overrides_public_cache_header(monkeypatch):
    monkeypatch.setenv("VAULTAI_SECURITY_HEADERS_ENABLED", "true")
    middleware = SecurityHeadersMiddleware(app=lambda *_: None)

    async def reply(_request):
        return Response("synthetic", headers={"Cache-Control": "public, max-age=3600"})

    private = asyncio.run(middleware.dispatch(
        _request(authenticated=True), reply,
    ))
    public = asyncio.run(middleware.dispatch(
        _request(authenticated=False), reply,
    ))
    assert private.headers["cache-control"] == (
        "no-store, no-cache, must-revalidate, private"
    )
    assert private.headers["pragma"] == "no-cache"
    assert public.headers["cache-control"] == "public, max-age=3600"
