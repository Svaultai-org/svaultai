"""Synthetic device-gate regression for opaque vault content routes."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import device_gate
from auth_local import verify_session_token
from routes import (
    credential_v2_routes,
    file_v2_routes,
    inheritance_credential_routes,
    inheritance_release_routes,
    vault_ciphertext_write_routes,
    vault_metadata_migration_routes,
    wallet_backup_v2_routes,
    wallet_v2_routes,
)


VAULT = "synthetic-vault"
PENDING = "synthetic-pending-device"
TRUSTED = "synthetic-trusted-device"


def _principal(device_id: str | None = PENDING) -> dict:
    return {
        "vault_id": VAULT,
        "vault_name": "",
        "token_id": "synthetic-token-id",
        "device_id": device_id,
    }


def _request(device_id: str, path: str = "/vault/file-v2") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(b"x-device-id", device_id.encode("ascii"))],
    })


@pytest.mark.parametrize(
    "module,expected_count",
    [
        (file_v2_routes, 7),
        (vault_ciphertext_write_routes, 14),
        (credential_v2_routes, 8),
        (wallet_v2_routes, 4),
        (wallet_backup_v2_routes, 4),
        (vault_metadata_migration_routes, 3),
    ],
)
def test_all_opaque_content_routes_require_trusted_device(module, expected_count):
    routes = [route for route in module.router.routes if isinstance(route, APIRoute)]
    assert len(routes) == expected_count
    for route in routes:
        assert device_gate.verify_trusted_device in {
            dependency.call for dependency in route.dependant.dependencies
        }, route.path


def test_escrow_content_routes_require_trusted_device_but_diagnostic_does_not():
    routes = [
        route for route in inheritance_credential_routes.router.routes
        if isinstance(route, APIRoute)
    ]
    assert len(routes) == 6
    for route in routes:
        dependencies = {dependency.call for dependency in route.dependant.dependencies}
        if route.path.endswith("/client-diagnostic"):
            assert verify_session_token in dependencies
        else:
            assert device_gate.verify_trusted_device in dependencies, route.path
    retrieve = next(
        route for route in inheritance_release_routes.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/inheritance/credentials/retrieve"
    )
    assert device_gate.verify_trusted_device in {
        dependency.call for dependency in retrieve.dependant.dependencies
    }


@pytest.mark.parametrize(
    "status,code",
    [("pending", "device_not_trusted"), ("revoked", "device_revoked")],
)
def test_session_bound_pending_or_revoked_device_is_denied(monkeypatch, status, code):
    monkeypatch.setattr(device_gate, "_gate_enabled", lambda: True)
    monkeypatch.setattr(device_gate, "_lookup_device_status", lambda *_: status)
    monkeypatch.setattr(device_gate, "is_dev_auto_trust_enabled", lambda: False)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(device_gate.verify_trusted_device(_request(PENDING), _principal()))
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == code


@pytest.mark.parametrize("bound_device", [PENDING, None])
def test_spoofed_trusted_header_cannot_borrow_another_device(monkeypatch, bound_device):
    monkeypatch.setattr(device_gate, "_gate_enabled", lambda: True)
    lookup = MagicMock(return_value="trusted")
    monkeypatch.setattr(device_gate, "_lookup_device_status", lookup)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(device_gate.verify_trusted_device(
            _request(TRUSTED), _principal(bound_device),
        ))
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "device_session_mismatch"
    lookup.assert_not_called()


def test_bound_trusted_device_passes(monkeypatch):
    monkeypatch.setattr(device_gate, "_gate_enabled", lambda: True)
    monkeypatch.setattr(device_gate, "_lookup_device_status", lambda *_: "trusted")
    principal = _principal(TRUSTED)
    assert asyncio.run(device_gate.verify_trusted_device(
        _request(TRUSTED), principal,
    )) is principal


@pytest.mark.parametrize("status", ["pending", "revoked"])
def test_opaque_file_and_item_reads_stop_before_database(monkeypatch, status):
    monkeypatch.setattr(device_gate, "_gate_enabled", lambda: True)
    monkeypatch.setattr(device_gate, "_lookup_device_status", lambda *_: status)
    monkeypatch.setattr(device_gate, "is_dev_auto_trust_enabled", lambda: False)
    monkeypatch.setattr(file_v2_routes, "get_db", lambda: pytest.fail("file DB reached"))
    monkeypatch.setattr(vault_ciphertext_write_routes, "get_db", lambda: pytest.fail("item DB reached"))

    app = FastAPI()
    app.include_router(file_v2_routes.router)
    app.include_router(vault_ciphertext_write_routes.router)
    app.dependency_overrides[verify_session_token] = _principal
    client = TestClient(app)
    for path in ("/vault/file-v2", "/vault/ciphertext/vault-items"):
        response = client.get(path, headers={"X-Device-Id": PENDING})
        assert response.status_code == 403, path
        assert response.json()["detail"]["code"] == (
            "device_revoked" if status == "revoked" else "device_not_trusted"
        )


def test_opaque_file_and_item_reads_work_for_bound_trusted_device(monkeypatch):
    monkeypatch.setattr(device_gate, "_gate_enabled", lambda: True)
    monkeypatch.setattr(device_gate, "_lookup_device_status", lambda *_: "trusted")
    monkeypatch.setattr(file_v2_routes, "_enabled", lambda *_: None)
    file_conn = MagicMock()
    file_conn.cursor.return_value.fetchall.return_value = []
    item_conn = MagicMock()
    item_conn.cursor.return_value.fetchall.return_value = []
    monkeypatch.setattr(file_v2_routes, "get_db", lambda: file_conn)
    monkeypatch.setattr(vault_ciphertext_write_routes, "get_db", lambda: item_conn)

    app = FastAPI()
    app.include_router(file_v2_routes.router)
    app.include_router(vault_ciphertext_write_routes.router)
    app.dependency_overrides[verify_session_token] = lambda: _principal(TRUSTED)
    client = TestClient(app)
    headers = {"X-Device-Id": TRUSTED}
    assert client.get("/vault/file-v2", headers=headers).json() == {"files": []}
    assert client.get("/vault/ciphertext/vault-items", headers=headers).json() == []
    assert file_conn.cursor.return_value.execute.called
    assert item_conn.cursor.return_value.execute.called
