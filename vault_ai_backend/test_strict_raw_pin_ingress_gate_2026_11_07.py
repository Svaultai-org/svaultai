"""Synthetic proof that strict cutover reads no legacy request body."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from unittest import mock

import main
from routes import auth_zk_routes
from routes.chunked_upload_routes import router as chunked_upload_router
from strict_raw_pin_ingress_gate import (
    FLAG_NAME, LEGACY_PIN_ROUTES, StrictRawPinIngressGate,
    is_legacy_pin_route, require_strict_private_client,
    strict_raw_pin_ingress_enabled,
)


def _registered_pin_routes(routes) -> set[tuple[str, str]]:
    found = set()
    for route in routes:
        body_field = getattr(route, "body_field", None)
        model = getattr(body_field, "type_", None)
        if "pin" not in getattr(model, "model_fields", {}):
            continue
        found.update(
            (method, route.path)
            for method in getattr(route, "methods", ())
            if method in {"POST", "PATCH", "DELETE", "PUT"}
        )
    return found


def _concrete_path(template: str) -> str:
    return (template.replace("{file_id}", "synthetic-file")
            .replace("{import_id}", "synthetic-import")
            .replace("{job_id}", "synthetic-job"))


async def _probe(app, method: str, path: str, *, headers=()):
    reads = []
    starts = []
    bodies = []

    async def receive():
        reads.append(True)
        return {"type": "http.request", "body": b'{"pin":"synthetic-pin"}',
                "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            starts.append(message)
        elif message["type"] == "http.response.body":
            bodies.append(message.get("body", b""))

    scope = {
        "type": "http", "method": method, "path": path,
        "root_path": "", "scheme": "https", "http_version": "1.1",
        "server": ("synthetic.example", 443), "client": ("127.0.0.1", 12345),
        "query_string": b"", "headers": list(headers),
    }
    await app(scope, receive, send)
    return reads, starts, b"".join(bodies)


async def _inner(scope, receive, send):
    await receive()
    await send({"type": "http.response.start", "status": 200,
                "headers": []})
    await send({"type": "http.response.body", "body": b"passed"})


def test_manifest_matches_all_registered_pin_fields_and_form_parameters():
    actual = _registered_pin_routes(main.app.routes)
    actual |= _registered_pin_routes(chunked_upload_router.routes)
    assert len(LEGACY_PIN_ROUTES) == 64
    assert actual == LEGACY_PIN_ROUTES


@pytest.mark.parametrize("method,template", sorted(LEGACY_PIN_ROUTES))
def test_enabled_gate_rejects_each_route_before_body_read(
    monkeypatch, method, template,
):
    monkeypatch.setenv(FLAG_NAME, "true")
    for suffix in ("", "/"):
        reads, starts, body = asyncio.run(_probe(
            StrictRawPinIngressGate(_inner), method,
            _concrete_path(template) + suffix,
            headers=(
                (b"content-type", b"multipart/form-data; boundary=synthetic")
                if template in ("/upload-file", "/name-file") else
                (b"content-type", b"application/json"),
                (b"authorization", b"Bearer invalid-one"),
                (b"authorization", b"Bearer invalid-two"),
            ),
        ))
        assert reads == []
        assert [start["status"] for start in starts] == [426]
        assert json.loads(body)["detail"]["code"] == "client_upgrade_required"
        assert b"synthetic-pin" not in body
        assert (b"cache-control", b"no-store") in starts[0]["headers"]


def test_flag_is_default_off_and_preserves_all_legacy_route_dispatch(
    monkeypatch,
):
    monkeypatch.delenv(FLAG_NAME, raising=False)
    assert strict_raw_pin_ingress_enabled() is False
    for method, template in sorted(LEGACY_PIN_ROUTES):
        reads, starts, body = asyncio.run(_probe(
            StrictRawPinIngressGate(_inner), method,
            _concrete_path(template),
        ))
        assert len(reads) == 1
        assert [start["status"] for start in starts] == [200]
        assert body == b"passed"


def test_gate_does_not_intercept_private_routes_or_other_methods(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "true")
    for method, path in (
        ("POST", "/vault/ciphertext/vault-items"),
        ("POST", "/chat/zk/general"),
        ("GET", "/auth/login"),
        ("OPTIONS", "/upload-file"),
    ):
        assert not is_legacy_pin_route(method, path)
        reads, starts, body = asyncio.run(_probe(
            StrictRawPinIngressGate(_inner), method, path,
        ))
        assert len(reads) == 1
        assert [start["status"] for start in starts] == [200]
        assert body == b"passed"


def test_old_opaque_finalize_is_rejected_before_body_read(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "true")
    for values in ((), (b"other",), (b"v1", b"v1")):
        reads, starts, body = asyncio.run(_probe(
            StrictRawPinIngressGate(_inner), "POST",
            "/auth/zk-login-finalize",
            headers=tuple(
                (b"x-svaultai-strict-pin-free-client", value)
                for value in values
            ),
        ))
        assert reads == []
        assert [start["status"] for start in starts] == [426]
        assert json.loads(body)["detail"]["code"] == "client_upgrade_required"
    reads, starts, body = asyncio.run(_probe(
        StrictRawPinIngressGate(_inner), "POST",
        "/auth/zk-login-finalize",
        headers=((b"x-svaultai-strict-pin-free-client", b"v1"),),
    ))
    assert len(reads) == 1
    assert [start["status"] for start in starts] == [200]
    assert body == b"passed"


def test_integrated_middleware_order_keeps_cors_outside_strict_fence():
    classes = [entry.cls for entry in main.app.user_middleware]
    assert classes.index(CORSMiddleware) < classes.index(StrictRawPinIngressGate)


def test_browser_preflight_accepts_strict_client_signal(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "true")
    reads, starts, _ = asyncio.run(_probe(
        main.app, "OPTIONS", "/auth/zk-login-finalize",
        headers=(
            (b"origin", b"https://synthetic.example"),
            (b"access-control-request-method", b"POST"),
            (b"access-control-request-headers",
             b"content-type,x-svaultai-strict-pin-free-client"),
        ),
    ))
    assert reads == []
    assert [start["status"] for start in starts] == [200]
    assert (b"access-control-allow-origin", b"https://synthetic.example") \
        in starts[0]["headers"]


def test_integrated_app_rejects_before_body_and_keeps_browser_upgrade_visible(
    monkeypatch,
):
    monkeypatch.setenv(FLAG_NAME, "true")
    for method, path, content_type in (
        ("POST", "/auth/login", b"application/json"),
        ("POST", "/auth/zk-login-finalize", b"application/json"),
        ("POST", "/upload-file", b"multipart/form-data; boundary=synthetic"),
        ("PATCH", "/manage/file", b"application/json"),
        ("DELETE", "/delete-file", b"application/json"),
        ("POST", "/files/synthetic-file/related", b"application/json"),
    ):
        reads, starts, body = asyncio.run(_probe(
            main.app, method, path,
            headers=((b"origin", b"https://synthetic.example"),
                     (b"content-type", content_type)),
        ))
        assert reads == []
        assert [start["status"] for start in starts] == [426]
        assert json.loads(body)["detail"]["code"] == "client_upgrade_required"
        assert (b"access-control-allow-origin", b"https://synthetic.example") \
            in starts[0]["headers"]


def _finalize_request(*values: bytes) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/auth/zk-login-finalize",
        "headers": [(b"x-svaultai-strict-pin-free-client", value)
                    for value in values],
    })


def test_old_opaque_finalize_is_rejected_before_session_supersession(
    monkeypatch,
):
    monkeypatch.setenv(FLAG_NAME, "true")
    payload = auth_zk_routes.ZkLoginFinalizeRequest(
        slot_id="synthetic-slot", ke3="c3ludGhldGlj",
    )
    with mock.patch.object(auth_zk_routes, "_zk_login_connection") as db, \
         mock.patch.object(auth_zk_routes, "issue_session_token") as issue, \
         mock.patch.object(auth_zk_routes, "enforce_login_finalize_rate_limit") as rate:
        with pytest.raises(HTTPException) as exc:
            auth_zk_routes._zk_login_finalize_sync(
                payload, _finalize_request(),
            )
        assert exc.value.status_code == 426
        assert exc.value.detail["code"] == "client_upgrade_required"
        db.assert_not_called()
        issue.assert_not_called()
        rate.assert_not_called()
    # A duplicate or malformed client claim cannot pass the gate either.
    for values in ((b"v1", b"v1"), (b"other",), (b"V1",)):
        with pytest.raises(HTTPException) as exc:
            require_strict_private_client(_finalize_request(*values))
        assert exc.value.status_code == 426


def test_capable_client_header_is_only_checked_when_strict_flag_is_on(
    monkeypatch,
):
    monkeypatch.delenv(FLAG_NAME, raising=False)
    require_strict_private_client(_finalize_request())
    monkeypatch.setenv(FLAG_NAME, "true")
    require_strict_private_client(_finalize_request(b"v1"))

