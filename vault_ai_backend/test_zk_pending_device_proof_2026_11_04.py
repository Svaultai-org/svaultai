"""Offline pending-device OPAQUE proof and self-approval tests.

Only synthetic slots, devices and OPAQUE results are used. No real vault or
device state is read or modified.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request


VAULT_A = "11111111-1111-1111-1111-111111111111"
VAULT_B = "22222222-2222-2222-2222-222222222222"
SESSION_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SESSION_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
DEVICE_A = "synthetic-device-0001"
DEVICE_B = "synthetic-device-0002"
HANDLE = bytes(range(15))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _principal(*, vault=VAULT_A, session=SESSION_A, device=DEVICE_A):
    return {"vault_id": vault, "token_id": session, "device_id": device}


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.result = None

    def execute(self, sql, params=None):
        query = " ".join(sql.lower().split())
        self.result = None
        if query.startswith("select status from trusted_devices"):
            vault, device = params
            if vault == VAULT_A and device == DEVICE_A:
                self.result = {"status": self.db.device_status}
        elif "select vault_handle, opaque_registration_record" in query:
            vault, handle = params
            if vault == VAULT_A and bytes(handle) == HANDLE:
                self.result = {
                    "vault_handle": HANDLE,
                    "opaque_registration_record": b"synthetic-opaque-record",
                }
        elif query.startswith("insert into vault_zk_login_slots"):
            slot_id, vault, state, expiry = params
            self.db.slots[slot_id] = (vault, state, expiry)
        elif query.startswith("delete from vault_zk_login_slots"):
            slot_id, vault = params
            slot = self.db.slots.get(slot_id)
            if slot and slot[0] == vault and slot[2] > datetime.now(timezone.utc):
                del self.db.slots[slot_id]
                self.result = ({"server_state": slot[1]}
                               if "returning server_state" in query
                               else {"slot_id": slot_id})
        elif "select status, cooldown_until, label, user_agent_brand" in query:
            vault, device = params
            if vault == VAULT_A and device == DEVICE_A:
                self.result = {
                    "status": self.db.device_status,
                    "cooldown_until": self.db.cooldown_until,
                    "label": "Synthetic device",
                    "user_agent_brand": None,
                }
        elif "select (now() at time zone 'utc') as now" in query:
            self.result = {"now": self.db.now}
        elif query.startswith("update trusted_devices set cooldown_until"):
            seconds, vault, device = params
            if vault == VAULT_A and device == DEVICE_A:
                self.db.cooldown_until = self.db.now + timedelta(seconds=seconds)
                self.result = {"cooldown_until": self.db.cooldown_until}
        elif query.startswith("update trusted_devices set status = 'trusted'"):
            vault, device = params
            if vault == VAULT_A and device == DEVICE_A:
                self.db.device_status = "trusted"
        else:
            raise AssertionError(f"unexpected synthetic SQL: {query[:115]}")

    def fetchone(self):
        return self.result


class _Db:
    def __init__(self):
        self.slots = {}
        self.device_status = "pending"
        self.cooldown_until = None
        self.now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def harness():
    from routes import auth_zk_routes as zk
    from routes import device_routes as device
    from vault_handle import to_display

    db = _Db()
    selected = {"principal": _principal()}
    app = FastAPI()
    app.include_router(zk.router)
    app.include_router(device.router)
    app.dependency_overrides[zk.verify_session_token] = lambda: selected["principal"]
    app.dependency_overrides[zk.verify_trusted_device] = (
        lambda: (_ for _ in ()).throw(HTTPException(403, "device_not_trusted"))
    )
    with (
        mock.patch.dict("os.environ", {"VAULTAI_ZK_PENDING_DEVICE_PROOF_ENABLED": "true"}),
        mock.patch.object(zk, "_zk_login_connection", side_effect=lambda: nullcontext(db)),
        mock.patch.object(zk, "_get_secret", return_value=b"synthetic-pending-proof-secret-32bytes"),
        mock.patch.object(zk, "opaque_login_start", return_value=(b"synthetic-ke2", b"synthetic-server-state")),
        mock.patch.object(zk, "opaque_login_finish") as finish,
        mock.patch.object(zk, "enforce_login_init_rate_limits") as init_limit,
        mock.patch.object(zk, "enforce_login_finalize_rate_limit") as final_limit,
        mock.patch.object(zk, "enforce_login_rate_limit") as bad_limit,
        mock.patch.object(zk, "issue_session_token") as issue,
        mock.patch.object(device, "get_db", return_value=db),
        mock.patch.object(device, "is_vault_zk_adopted", return_value=True),
        mock.patch.object(device, "verify_vault_pin") as legacy_pin,
        mock.patch.object(device, "_notify") as notify,
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield (zk, device, client, db, selected, to_display(HANDLE),
                   finish, init_limit, final_limit, bad_limit, issue,
                   legacy_pin, notify, app)


def _init(client, handle, *, device=DEVICE_A, ke1=None):
    return client.post("/auth/zk-pending-verify-init", headers={"X-Device-Id": device},
                       json={"vault_handle": handle,
                             "ke1": ke1 or _b64(b"synthetic-ke1")})


def _finalize(client, slot_id, *, device=DEVICE_A):
    return client.post("/auth/zk-pending-verify-finalize",
                       headers={"X-Device-Id": device},
                       json={"slot_id": slot_id, "ke3": _b64(b"synthetic-ke3")})


def _proof(h):
    zk, device, client, db, selected, handle, *rest = h
    slot = _init(client, handle).json()["slot_id"]
    result = _finalize(client, slot)
    assert result.status_code == 200, result.text
    return slot, result.json()["proof_token"]


def test_pending_opaque_exchange_issues_only_device_bound_proof(harness):
    zk, device, client, db, selected, handle, finish, init_limit, final_limit, bad_limit, issue, legacy_pin, notify, app = harness
    slot, proof = _proof(harness)
    assert slot.startswith("pv1.") and proof.startswith("pp1.")
    assert proof in db.slots
    assert finish.call_count == 1
    assert init_limit.call_count == 1 and final_limit.call_count == 1
    issue.assert_not_called()
    legacy_pin.assert_not_called()
    assert client.post("/auth/zk-verify-init", json={
        "vault_handle": handle, "ke1": _b64(b"synthetic-ke1"),
    }).status_code == 403


@pytest.mark.parametrize("other", [
    _principal(device=DEVICE_B),
    _principal(session=SESSION_B),
    _principal(vault=VAULT_B),
])
def test_pending_slot_cannot_cross_device_session_or_vault(harness, other):
    zk, device, client, db, selected, handle, finish, *rest = harness
    slot = _init(client, handle).json()["slot_id"]
    selected["principal"] = other
    assert _finalize(client, slot).status_code in (401, 403)
    assert slot in db.slots
    finish.assert_not_called()


def test_pending_slot_expiry_replay_and_normal_login_misuse(harness):
    zk, device, client, db, selected, handle, finish, *rest = harness
    slot = _init(client, handle).json()["slot_id"]
    denied = client.post("/auth/zk-login-finalize", json={
        "slot_id": slot, "ke3": _b64(b"synthetic-ke3"),
    })
    assert denied.status_code == 401 and slot in db.slots
    vault, state, _ = db.slots[slot]
    db.slots[slot] = (vault, state, datetime.now(timezone.utc) - timedelta(seconds=1))
    assert _finalize(client, slot).status_code == 401
    assert finish.call_count == 0
    fresh = _init(client, handle).json()["slot_id"]
    assert _finalize(client, fresh).status_code == 200
    assert _finalize(client, fresh).status_code == 401
    assert finish.call_count == 1


def test_trusted_session_verify_slot_cannot_finish_as_pending(harness):
    zk, device, client, db, selected, handle, finish, *rest = harness
    trusted_slot = zk._new_verify_slot_id(_principal())
    db.slots[trusted_slot] = (
        VAULT_A, b"synthetic-trusted-state",
        datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    assert _finalize(client, trusted_slot).status_code == 401
    assert trusted_slot in db.slots
    finish.assert_not_called()


def test_pending_proof_bound_to_device_session_vault_and_single_use(harness):
    zk, device, client, db, selected, handle, finish, *rest = harness
    _, proof = _proof(harness)
    for other in (
        _principal(device=DEVICE_B),
        _principal(session=SESSION_B),
        _principal(vault=VAULT_B),
    ):
        with pytest.raises(HTTPException) as raised:
            zk.consume_pending_self_approval_proof(proof, other, DEVICE_A)
        assert raised.value.status_code == 401
        assert proof in db.slots
    with pytest.raises(HTTPException) as raised:
        zk.consume_pending_self_approval_proof(proof, _principal(), DEVICE_B)
    assert raised.value.status_code == 401
    with pytest.raises(HTTPException) as raised:
        zk.consume_recent_zk_proof(proof, _principal())
    assert raised.value.status_code == 401
    zk.consume_pending_self_approval_proof(proof, _principal(), DEVICE_A)
    with pytest.raises(HTTPException) as raised:
        zk.consume_pending_self_approval_proof(proof, _principal(), DEVICE_A)
    assert raised.value.status_code == 401


def test_pending_proof_expiry_and_login_slot_misuse(harness):
    zk, device, client, db, selected, handle, finish, *rest = harness
    _, proof = _proof(harness)
    denied = client.post("/auth/zk-login-finalize", json={
        "slot_id": proof, "ke3": _b64(b"synthetic-ke3"),
    })
    assert denied.status_code == 401
    assert proof in db.slots
    expiry = int(proof.split(".")[1])
    with mock.patch.object(zk.time, "time", return_value=expiry + 1):
        with pytest.raises(HTTPException) as raised:
            zk.consume_pending_self_approval_proof(proof, _principal(), DEVICE_A)
    assert raised.value.status_code == 401
    assert proof in db.slots


def test_pending_proof_does_not_open_general_trusted_device_gate(harness, monkeypatch):
    import device_gate

    zk, device, client, db, selected, handle, finish, *rest = harness
    _, proof = _proof(harness)
    monkeypatch.setattr(device_gate, "_gate_enabled", lambda: True)
    monkeypatch.setattr(device_gate, "_lookup_device_status", lambda *_: "pending")
    monkeypatch.setattr(device_gate, "is_dev_auto_trust_enabled", lambda: False)
    request = Request({
        "type": "http", "method": "GET",
        "path": "/vault/ciphertext/vault-items",
        "headers": [
            (b"x-device-id", DEVICE_A.encode("ascii")),
            (b"x-zk-proof-token", proof.encode("ascii")),
        ],
        "query_string": b"",
    })
    with pytest.raises(HTTPException) as raised:
        asyncio.run(device_gate.verify_trusted_device(request, _principal()))
    assert raised.value.status_code == 403
    assert raised.value.detail["code"] == "device_not_trusted"


def test_self_approval_requires_pending_proof_not_raw_pin(harness):
    zk, device, client, db, selected, handle, finish, init_limit, final_limit, bad_limit, issue, legacy_pin, notify, app = harness
    for body in ({"pin": "123456"}, {}, {"zk_proof_token": "p1.not-pending"}):
        result = client.post("/devices/request-self-approval",
                             headers={"X-Device-Id": DEVICE_A}, json=body)
        assert result.status_code in (400, 401, 409)
    assert db.cooldown_until is None
    denied_final = client.post("/devices/finalize-self-approval",
                               headers={"X-Device-Id": DEVICE_A},
                               json={"pin": "123456"})
    assert denied_final.status_code == 409
    legacy_pin.assert_not_called()
    _, proof = _proof(harness)
    started = client.post("/devices/request-self-approval",
                          headers={"X-Device-Id": DEVICE_A},
                          json={"zk_proof_token": proof})
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "cooldown"
    assert proof not in db.slots and db.cooldown_until is not None
    legacy_pin.assert_not_called()


def test_self_approval_finalize_needs_new_proof_and_elapsed_cooldown(harness):
    zk, device, client, db, selected, handle, finish, *rest = harness
    _, first_proof = _proof(harness)
    started = client.post("/devices/request-self-approval",
                          headers={"X-Device-Id": DEVICE_A},
                          json={"zk_proof_token": first_proof})
    assert started.status_code == 200
    db.cooldown_until = db.now - timedelta(seconds=1)
    replay = client.post("/devices/finalize-self-approval",
                         headers={"X-Device-Id": DEVICE_A},
                         json={"zk_proof_token": first_proof})
    assert replay.status_code == 401
    assert db.device_status == "pending"
    _, second_proof = _proof(harness)
    approved = client.post("/devices/finalize-self-approval",
                           headers={"X-Device-Id": DEVICE_A},
                           json={"zk_proof_token": second_proof})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "trusted"
    assert db.device_status == "trusted"


def test_pending_init_and_finalize_are_rate_limited(harness):
    zk, device, client, db, selected, handle, finish, init_limit, final_limit, bad_limit, issue, legacy_pin, notify, app = harness
    init_limit.side_effect = HTTPException(status_code=429, detail="rate limited")
    assert _init(client, handle).status_code == 429
    assert not db.slots
    init_limit.side_effect = None
    slot = _init(client, handle).json()["slot_id"]
    final_limit.side_effect = HTTPException(status_code=429, detail="rate limited")
    assert _finalize(client, slot).status_code == 429
    assert slot in db.slots
    final_limit.side_effect = None
    assert _finalize(client, slot).status_code == 200
    assert init_limit.call_count == 2 and final_limit.call_count == 2


def test_malformed_pending_init_consumes_generic_auth_rate_budget(harness):
    zk, device, client, db, selected, handle, finish, init_limit, final_limit, bad_limit, issue, legacy_pin, notify, app = harness
    bad = _init(client, handle, ke1="A" * (zk.MAX_OPAQUE_MESSAGE_BYTES * 2 + 1))
    assert bad.status_code == 413
    bad_limit.assert_called_once()
    init_limit.assert_not_called()
    assert not db.slots


def test_flag_off_blocks_pending_routes_and_preserves_legacy_pin(harness):
    zk, device, client, db, selected, handle, finish, init_limit, final_limit, bad_limit, issue, legacy_pin, notify, app = harness
    with mock.patch.dict("os.environ", {"VAULTAI_ZK_PENDING_DEVICE_PROOF_ENABLED": "false"}):
        assert _init(client, handle).status_code == 404
        result = client.post("/devices/request-self-approval",
                             headers={"X-Device-Id": DEVICE_A},
                             json={"pin": "123456"})
    assert result.status_code == 200, result.text
    legacy_pin.assert_called_once_with(VAULT_A, "123456")
