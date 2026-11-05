"""Synthetic pending-device OPAQUE proof tests; no real PIN or database."""

from __future__ import annotations

import base64
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


VAULT = "11111111-1111-1111-1111-111111111111"
OTHER_VAULT = "22222222-2222-2222-2222-222222222222"
SESSION = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_SESSION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEVICE = "pending_device_1234567890"
OTHER_DEVICE = "different_device_1234567"
HANDLE = bytes(range(15))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.result = None

    def execute(self, sql, params=None):
        normalized = " ".join(sql.lower().split())
        self.result = None
        if normalized.startswith("select status from trusted_devices"):
            vault_id, device_id = params
            if vault_id == VAULT and device_id in self.db.devices:
                self.result = {"status": self.db.devices[device_id]}
        elif "select vault_handle, opaque_registration_record" in normalized:
            vault_id, handle = params
            if vault_id == VAULT and bytes(handle) == HANDLE:
                self.result = {
                    "vault_handle": HANDLE,
                    "opaque_registration_record": b"synthetic-record",
                }
        elif "insert into vault_zk_login_slots" in normalized:
            slot_id, vault_id, state, expiry = params
            self.db.slots[slot_id] = (vault_id, state, expiry)
        elif "delete from vault_zk_login_slots" in normalized:
            slot_id, vault_id = params
            stored = self.db.slots.get(slot_id)
            if (stored and stored[0] == vault_id
                    and stored[2] > datetime.now(timezone.utc)):
                self.db.slots.pop(slot_id)
                self.result = (
                    {"server_state": stored[1]}
                    if "returning server_state" in normalized
                    else {"slot_id": slot_id}
                )
        else:
            raise AssertionError(f"unexpected synthetic SQL: {normalized[:90]}")

    def fetchone(self):
        return self.result


class _Db:
    def __init__(self):
        self.slots = {}
        self.devices = {DEVICE: "pending", OTHER_DEVICE: "pending"}

    def cursor(self, cursor_factory=None):
        return _Cursor(self)

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def harness(monkeypatch):
    from routes import auth_zk_routes as zk
    from vault_handle import to_display

    db = _Db()
    selected = {"principal": {
        "vault_id": VAULT, "token_id": SESSION, "device_id": DEVICE,
    }}
    monkeypatch.setenv("VAULTAI_ZK_PENDING_DEVICE_PROOF_ENABLED", "true")
    app = FastAPI()
    app.include_router(zk.router)
    app.dependency_overrides[zk.verify_session_token] = lambda: selected["principal"]
    app.dependency_overrides[zk.verify_trusted_device] = lambda: selected["principal"]
    with (
        mock.patch.object(zk, "_zk_login_connection", side_effect=lambda: nullcontext(db)),
        mock.patch.object(zk, "_get_secret", return_value=b"synthetic-session-signing-secret-32bytes"),
        mock.patch.object(zk, "opaque_login_start", return_value=(b"ke2", b"state")),
        mock.patch.object(zk, "opaque_login_finish", return_value=None) as finish,
        mock.patch.object(zk, "enforce_login_init_rate_limits"),
        mock.patch.object(zk, "enforce_login_finalize_rate_limit"),
        mock.patch.object(zk, "issue_session_token") as issue,
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield zk, client, db, selected, to_display(HANDLE), finish, issue


def _init(client, handle, device=DEVICE):
    return client.post(
        "/auth/zk-pending-verify-init",
        headers={"X-Device-Id": device},
        json={"vault_handle": handle, "ke1": _b64(b"ke1")},
    )


def _finish(client, slot, device=DEVICE):
    return client.post(
        "/auth/zk-pending-verify-finalize",
        headers={"X-Device-Id": device},
        json={"slot_id": slot, "ke3": _b64(b"ke3")},
    )


def test_pending_opaque_proof_is_device_bound_one_time_and_not_general(harness):
    zk, client, db, selected, handle, finish, issue = harness
    started = _init(client, handle)
    assert started.status_code == 200, started.text
    slot = started.json()["slot_id"]
    assert slot.startswith("pv1.")
    assert _finish(client, slot, OTHER_DEVICE).status_code == 403
    assert slot in db.slots
    verified = _finish(client, slot)
    assert verified.status_code == 200, verified.text
    proof = verified.json()["proof_token"]
    assert proof.startswith("pp1.")
    assert "session_token" not in verified.json()
    finish.assert_called_once()
    issue.assert_not_called()

    owner = selected["principal"]
    for altered in (
        {**owner, "token_id": OTHER_SESSION},
        {**owner, "vault_id": OTHER_VAULT},
        {**owner, "device_id": OTHER_DEVICE},
    ):
        with pytest.raises(HTTPException):
            zk.consume_pending_self_approval_proof(proof, altered, DEVICE)
        assert proof in db.slots
    with pytest.raises(HTTPException):
        zk.consume_recent_zk_proof(proof, owner)
    assert proof in db.slots
    zk.consume_pending_self_approval_proof(proof, owner, DEVICE)
    with pytest.raises(HTTPException):
        zk.consume_pending_self_approval_proof(proof, owner, DEVICE)


def test_pending_proof_expiry_and_protocol_separation(harness):
    zk, client, db, selected, handle, finish, issue = harness
    slot = _init(client, handle).json()["slot_id"]
    assert client.post("/auth/zk-verify-finalize", json={
        "slot_id": slot, "ke3": _b64(b"ke3"),
    }).status_code == 401
    assert client.post("/auth/zk-login-finalize", json={
        "slot_id": slot, "ke3": _b64(b"ke3"),
    }).status_code == 401
    proof = _finish(client, slot).json()["proof_token"]
    assert client.post("/auth/zk-login-finalize", json={
        "slot_id": proof, "ke3": _b64(b"ke3"),
    }).status_code == 401
    expiry = int(proof.split(".")[1])
    with mock.patch.object(zk.time, "time", return_value=expiry + 1):
        with pytest.raises(HTTPException):
            zk.consume_pending_self_approval_proof(
                proof, selected["principal"], DEVICE,
            )
    assert proof in db.slots
    issue.assert_not_called()


def test_pending_route_refuses_trusted_or_mismatched_device(harness):
    zk, client, db, selected, handle, finish, issue = harness
    db.devices[DEVICE] = "trusted"
    assert _init(client, handle).status_code == 403
    db.devices[DEVICE] = "pending"
    selected["principal"] = {
        **selected["principal"], "device_id": OTHER_DEVICE,
    }
    assert _init(client, handle).status_code == 403


def test_pending_self_approval_rejects_raw_pin_when_flag_on(monkeypatch):
    from routes import device_routes as devices

    monkeypatch.setattr(devices, "is_vault_zk_adopted", lambda _vault: True)
    monkeypatch.setattr(
        "routes.auth_zk_routes.pending_device_proof_enabled", lambda: True,
    )
    consume = mock.Mock()
    verify_pin = mock.Mock()
    monkeypatch.setattr(
        "routes.auth_zk_routes.consume_pending_self_approval_proof", consume,
    )
    monkeypatch.setattr(devices, "verify_vault_pin", verify_pin)
    principal = {"vault_id": VAULT, "token_id": SESSION, "device_id": DEVICE}
    with pytest.raises(HTTPException) as denied:
        devices._verify_self_approval_credential(
            VAULT, DEVICE, principal,
            devices.SelfApprovalRequest(pin="synthetic-not-real-pin"),
        )
    assert denied.value.status_code == 409
    verify_pin.assert_not_called()
    consume.assert_not_called()
    devices._verify_self_approval_credential(
        VAULT, DEVICE, principal,
        devices.SelfApprovalRequest(zk_proof_token="synthetic-proof"),
    )
    consume.assert_called_once_with("synthetic-proof", principal, DEVICE)
    verify_pin.assert_not_called()
