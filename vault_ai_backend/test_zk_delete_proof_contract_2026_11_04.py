"""Synthetic delete-route tests: ZK accounts require server-consumed proof.

The deletion service and DB are mocked; no vault can be removed by this test.
"""

from __future__ import annotations

from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


VAULT_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
PRINCIPAL = {"vault_id": VAULT_ID, "token_id": SESSION_ID}


@pytest.fixture
def delete_harness():
    from routes import vault_delete_routes as delete

    app = FastAPI()
    app.include_router(delete.router)
    app.dependency_overrides[delete.verify_trusted_device] = lambda: PRINCIPAL
    decision = {
        "is_final_vault": False,
        "deletion_allowed": True,
        "has_active_subscription": False,
        "subscription_status": "none",
        "apple_subscription_state": "none",
        "retryable": False,
    }
    with (
        mock.patch.dict("os.environ", {"VAULTAI_ZK_DELETE_PROOF_ENABLED": "true"}),
        mock.patch.object(delete, "enforce_delete_vault_rate_limit"),
        mock.patch.object(delete, "_verify_challenge", return_value=True),
        mock.patch.object(delete, "_vault_has_zk_registration", return_value=True) as is_zk,
        mock.patch.object(delete, "_get_deletion_billing_state", return_value=decision),
        mock.patch.object(delete, "_require_authoritative_final_vault_deletion_allowed") as bill,
        mock.patch.object(delete, "consume_recent_zk_proof") as consume,
        mock.patch.object(delete, "_verify_pin", return_value=True) as verify_pin,
        mock.patch.object(delete, "delete_vault_and_all_data") as destroy,
        mock.patch.object(delete, "revoke_all_sessions_for_vault"),
        mock.patch.object(delete.sec_log, "emit"),
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield delete, client, is_zk, bill, consume, verify_pin, destroy


def _body(delete, **extra):
    return {
        "request_token": "synthetic-challenge",
        "confirmation_phrase": delete.CONFIRMATION_PHRASE,
        **extra,
    }


def test_zk_delete_status_requires_opaque_reentry(delete_harness):
    delete, client, is_zk, bill, consume, verify_pin, destroy = delete_harness
    response = client.get("/vault/delete/status")
    assert response.status_code == 200, response.text
    assert response.json()["requires_pin"] is False
    assert response.json()["requires_opaque_verification"] is True


def test_zk_delete_rejects_raw_pin_and_missing_proof(delete_harness):
    delete, client, is_zk, bill, consume, verify_pin, destroy = delete_harness
    for payload in (_body(delete, pin="123456"), _body(delete)):
        response = client.post("/vault/delete/confirm", json=payload)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "opaque_verification_required"
    consume.assert_not_called()
    verify_pin.assert_not_called()
    bill.assert_not_called()
    destroy.assert_not_called()


def test_zk_delete_consumes_proof_before_destructive_action(delete_harness):
    delete, client, is_zk, bill, consume, verify_pin, destroy = delete_harness
    response = client.post("/vault/delete/confirm", json=_body(
        delete, zk_proof_token="synthetic-one-time-proof",
    ))
    assert response.status_code == 204, response.text
    consume.assert_called_once_with("synthetic-one-time-proof", PRINCIPAL)
    verify_pin.assert_not_called()
    bill.assert_called_once_with(VAULT_ID)
    destroy.assert_called_once()


def test_failed_proof_cannot_reach_deletion_service(delete_harness):
    delete, client, is_zk, bill, consume, verify_pin, destroy = delete_harness
    consume.side_effect = HTTPException(status_code=401, detail="invalid proof")
    response = client.post("/vault/delete/confirm", json=_body(
        delete, zk_proof_token="synthetic-invalid-proof",
    ))
    assert response.status_code == 401
    bill.assert_not_called()
    destroy.assert_not_called()


def test_legacy_vault_keeps_pin_path_during_cutover(delete_harness):
    delete, client, is_zk, bill, consume, verify_pin, destroy = delete_harness
    is_zk.return_value = False
    response = client.post("/vault/delete/confirm", json=_body(
        delete, pin="123456",
    ))
    assert response.status_code == 204, response.text
    verify_pin.assert_called_once_with(VAULT_ID, "123456")
    consume.assert_not_called()
    destroy.assert_called_once()
