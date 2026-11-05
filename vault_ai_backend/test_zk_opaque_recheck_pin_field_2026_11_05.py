"""OPAQUE rechecks refuse accidental legacy PIN fields without echoing them."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


os.environ.setdefault(
    "VAULT_SESSION_SECRET", "synthetic_test_only_secret_12345678901234567890",
)
os.environ.setdefault("VAULTAI_ENV", "local")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://synthetic:synthetic@127.0.0.1:1/synthetic",
)

from routes import auth_zk_routes as zk  # noqa: E402


_PRINCIPAL = {
    "vault_id": "11111111-1111-1111-1111-111111111111",
    "token_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "device_id": "synthetic-device-0001",
}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(zk.router)
    app.dependency_overrides[zk.verify_trusted_device] = lambda: _PRINCIPAL
    app.dependency_overrides[zk.verify_session_token] = lambda: _PRINCIPAL
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("finalize", [False, True])
@pytest.mark.parametrize("field", ["pin", "pin_verifier"])
def test_recheck_rejects_legacy_pin_fields_before_opaque_work(
    pending: bool, finalize: bool, field: str,
) -> None:
    path = (
        "/auth/zk-"
        + ("pending-" if pending else "")
        + "verify-"
        + ("finalize" if finalize else "init")
    )
    body = (
        {"slot_id": "synthetic-slot", "ke3": "synthetic-ke3"}
        if finalize else
        {"vault_handle": "synthetic-handle", "ke1": "synthetic-ke1"}
    )
    marker = "synthetic-pin-marker-123456"
    body[field] = marker
    with (
        mock.patch.object(
            zk, "_zk_verify_init_sync", side_effect=AssertionError("OPAQUE started"),
        ) as init,
        mock.patch.object(
            zk, "_zk_verify_finalize_sync", side_effect=AssertionError("OPAQUE finished"),
        ) as finish,
        mock.patch.object(
            zk, "_require_pending_session_device",
            side_effect=AssertionError("pending-device lookup started"),
        ) as pending_lookup,
        _client() as client,
    ):
        response = client.post(path, json=body)
    assert response.status_code == 409
    assert response.json() == {"detail": "zk_client_update_required"}
    assert marker not in response.text
    init.assert_not_called()
    finish.assert_not_called()
    pending_lookup.assert_not_called()


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("finalize", [False, True])
def test_recheck_keeps_valid_opaque_request_shape(
    pending: bool, finalize: bool,
) -> None:
    path = (
        "/auth/zk-"
        + ("pending-" if pending else "")
        + "verify-"
        + ("finalize" if finalize else "init")
    )
    body = (
        {"slot_id": "synthetic-slot", "ke3": "synthetic-ke3"}
        if finalize else
        {"vault_handle": "synthetic-handle", "ke1": "synthetic-ke1"}
    )
    expected = (
        zk.ZkVerifyFinalizeResponse(
            verified=True,
            proof_token="synthetic-proof",
            proof_expires_at=datetime.now(timezone.utc),
        ) if finalize else
        zk.ZkVerifyInitResponse(slot_id="synthetic-slot", ke2="synthetic-ke2")
    )
    with (
        mock.patch.object(
            zk, "_zk_verify_init_sync", return_value=expected,
        ) as init,
        mock.patch.object(
            zk, "_zk_verify_finalize_sync", return_value=expected,
        ) as finish,
        mock.patch.object(
            zk, "_require_pending_session_device", return_value="synthetic-device-0001",
        ) as pending_lookup,
        _client() as client,
    ):
        response = client.post(path, json=body)
    assert response.status_code == 200
    (finish if finalize else init).assert_called_once()
    assert pending_lookup.call_count == (1 if pending else 0)
