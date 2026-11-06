"""A signed read offer must reject its old PIN route before body parsing."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from signed_offer_prebody_pin_fence import FLAG_NAME, SignedOfferPrebodyPinFence


def _bearer(monkeypatch, offer_bits: int | None) -> tuple[bytes, bytes]:
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/test")
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-test-session-secret-2026")
    import auth_local

    auth_local.reset_secret_for_tests()
    token = auth_local._format_token(uuid.uuid4().bytes)
    if offer_bits is not None:
        token = auth_local.sign_opaque_read_offer_token(token, offer_bits)
    return b"authorization", f"Bearer {token}".encode("ascii")


def _exercise(path: str, *, headers=(), method="POST") -> dict:
    seen = {"downstream": False, "body_read": False, "messages": []}

    async def downstream(_scope, receive, send):
        seen["downstream"] = True
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        seen["body_read"] = True
        return {"type": "http.request", "body": b'{"pin":"999991"}',
                "more_body": False}

    async def send(message):
        seen["messages"].append(message)

    scope = {"type": "http", "method": method, "path": path,
             "headers": headers, "query_string": b""}
    asyncio.run(SignedOfferPrebodyPinFence(downstream)(scope, receive, send))
    return seen


@pytest.mark.parametrize("path,bits,detail", [
    ("/list-secure-items", 1, "pin_free_read_required"),
    ("/get-secure-item", 1, "pin_free_read_required"),
    ("/list-files", 2, "pin_free_read_required"),
    ("/download-file", 4, "pin_free_read_required"),
    ("/download-file/manifest", 4, "pin_free_read_required"),
    ("/files/synthetic-file/related", 2, "pin_free_read_required"),
    ("/upload-file", 8, "pin_free_file_create_required"),
    ("/upload-file/init", 8, "pin_free_file_create_required"),
])
def test_offered_routes_reject_before_read(monkeypatch, path, bits, detail):
    monkeypatch.setenv(FLAG_NAME, "true")
    result = _exercise(path + "/", headers=[_bearer(monkeypatch, bits)])
    assert not result["downstream"] and not result["body_read"]
    assert result["messages"][0]["status"] == 409
    assert json.loads(result["messages"][1]["body"])["detail"] == detail
    assert (b"cache-control", b"no-store") in result["messages"][0]["headers"]
    assert b"999991" not in result["messages"][1]["body"]


def test_default_off_and_unoffered_access_continue(monkeypatch):
    signed = _bearer(monkeypatch, 2)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    result = _exercise("/list-files", headers=[signed])
    assert result["downstream"] and result["body_read"]

    monkeypatch.setenv(FLAG_NAME, "true")
    for headers in ([_bearer(monkeypatch, None)],
                    [_bearer(monkeypatch, 1)]):
        result = _exercise("/list-files", headers=headers)
        assert result["downstream"] and result["body_read"]


def test_duplicate_headers_and_mixed_case_cannot_hide_signed_offer(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "true")
    old = _bearer(monkeypatch, None)
    signed = _bearer(monkeypatch, 2)
    signed = (b"AUTHORIZATION", b"bEaReR " + signed[1].split(b" ", 1)[1])
    for headers in ([old, signed], [signed, old]):
        result = _exercise("/list-files", headers=headers)
        assert not result["downstream"] and not result["body_read"]
        assert result["messages"][0]["status"] == 409


def test_tampered_offer_cannot_claim_a_signed_route(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "true")
    signed = _bearer(monkeypatch, 2)
    import auth_local
    raw = bytearray(auth_local._b64url_decode(signed[1].split(b" ", 1)[1].decode()))
    raw[-1] ^= 1
    invalid = (b"authorization",
               b"Bearer " + auth_local._b64url_encode(raw).encode())
    result = _exercise("/list-files", headers=[invalid])
    # Downstream authentication rejects the invalid token; the pre-body
    # fence must not treat an attacker-chosen offer bit as authentic.
    assert result["downstream"] and result["body_read"]


def test_offered_unrelated_action_and_preflight_remain_available(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "true")
    signed = _bearer(monkeypatch, 2)
    for path, method in (("/update-secure-item", "POST"),
                         ("/list-files", "GET"),
                         ("/list-files", "OPTIONS")):
        result = _exercise(path, method=method, headers=[signed])
        assert result["downstream"] and result["body_read"]


def test_invalid_setting_fails_closed(monkeypatch):
    monkeypatch.setenv(FLAG_NAME, "ture")
    with pytest.raises(RuntimeError, match="Invalid signed-offer pre-body"):
        _exercise("/list-files")


def test_registered_app_rejects_offered_pin_before_db(monkeypatch, caplog):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic.invalid/test")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unused")
    monkeypatch.setenv("VAULT_SESSION_SECRET", "synthetic-test-session-secret-2026")
    monkeypatch.setenv("VAULTAI_ENV", "development")
    monkeypatch.setenv("CORS_ALLOWED_ORIGIN_REGEX", r"https://app\.svaultai\.com")
    monkeypatch.setenv(FLAG_NAME, "true")
    import main

    bearer = _bearer(monkeypatch, 2)[1].decode("ascii")
    response = TestClient(main.app).post(
        "/list-files", headers={
            "Authorization": bearer, "Origin": "https://app.svaultai.com",
        },
        json={"pin": "999991"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "pin_free_read_required"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Access-Control-Allow-Origin"] == \
        "https://app.svaultai.com"
    assert "999991" not in caplog.text
