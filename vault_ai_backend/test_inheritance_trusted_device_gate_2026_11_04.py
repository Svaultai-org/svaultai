"""Trusted-device boundary for inheritance actions and legacy ZK adoption."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import device_gate
from auth_local import verify_session_token
from routes import auth_zk_routes, inheritance_release_routes as release


PENDING = "synthetic-pending-device"


def _principal(device_id: str = PENDING):
    return {
        "vault_id": "synthetic-vault",
        "vault_name": "",
        "token_id": "synthetic-token",
        "device_id": device_id,
    }


def test_release_actions_require_trust_except_pending_device_consume():
    routes = [route for route in release.router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 9
    for route in routes:
        dependencies = {dependency.call for dependency in route.dependant.dependencies}
        if route.path == "/inheritance/device/consume":
            assert verify_session_token in dependencies
            assert device_gate.verify_trusted_device not in dependencies
        else:
            assert device_gate.verify_trusted_device in dependencies, route.path


def test_zk_adoption_requires_trusted_legacy_session():
    route = next(
        route for route in auth_zk_routes.router.routes
        if isinstance(route, APIRoute) and route.path == "/auth/zk-adopt"
    )
    assert device_gate.verify_trusted_device in {
        dependency.call for dependency in route.dependant.dependencies
    }


@pytest.mark.parametrize("status,code", [
    ("pending", "device_not_trusted"),
    ("revoked", "device_revoked"),
])
def test_inheritance_status_cannot_reach_db_from_untrusted_device(
    monkeypatch, status, code,
):
    monkeypatch.setattr(device_gate, "_gate_enabled", lambda: True)
    monkeypatch.setattr(device_gate, "_lookup_device_status", lambda *_: status)
    monkeypatch.setattr(device_gate, "is_dev_auto_trust_enabled", lambda: False)
    monkeypatch.setattr(release, "get_db", lambda: pytest.fail("inheritance DB reached"))
    app = FastAPI()
    app.include_router(release.router)
    app.dependency_overrides[verify_session_token] = _principal
    client = TestClient(app)
    headers = {"X-Device-Id": PENDING}
    responses = (
        client.get("/inheritance/access/status?link_id=1", headers=headers),
        client.post("/inheritance/access/request", headers=headers,
                    json={"beneficiary_link_id": 1}),
    )
    for response in responses:
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize("status", ["pending", "revoked"])
def test_zk_adoption_cannot_write_from_untrusted_session(monkeypatch, status):
    monkeypatch.setattr(device_gate, "_gate_enabled", lambda: True)
    monkeypatch.setattr(device_gate, "_lookup_device_status", lambda *_: status)
    monkeypatch.setattr(device_gate, "is_dev_auto_trust_enabled", lambda: False)
    monkeypatch.setattr(auth_zk_routes, "get_db", lambda: pytest.fail("adoption DB reached"))
    app = FastAPI()
    app.include_router(auth_zk_routes.router)
    app.dependency_overrides[verify_session_token] = _principal
    response = TestClient(app).post(
        "/auth/zk-adopt",
        headers={"X-Device-Id": PENDING},
        json={
            "vault_handle": "VLT-0000-0000-0000-0000-0000-0000",
            "opaque_registration_record": "AQID",
            "wrapped_mvk": "AQID",
            "wrapped_sk_vault": "AQID",
            "pk_vault_public": "AQID",
            "display_name_ciphertext": "AQID",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == (
        "device_revoked" if status == "revoked" else "device_not_trusted"
    )


def test_pending_inherited_owner_consumption_requires_own_session_device(monkeypatch):
    monkeypatch.setattr(release, "get_db", lambda: pytest.fail("DB reached"))
    request = Request({
        "type": "http", "method": "POST",
        "path": "/inheritance/device/consume",
        "headers": [(b"x-device-id", b"synthetic-other-device")],
    })
    with pytest.raises(HTTPException) as raised:
        release.consume_device_authorization(
            release.DeviceConsumeBody(token="synthetic-token"),
            request,
            _principal(),
        )
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "device_session_mismatch"


def test_pending_consume_still_uses_session_not_general_trusted_gate():
    route = next(
        route for route in release.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/inheritance/device/consume"
    )
    assert verify_session_token in {
        dependency.call for dependency in route.dependant.dependencies
    }
