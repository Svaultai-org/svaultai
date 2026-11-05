"""Synthetic route tests for OPAQUE PIN re-entry and single-use action proof.

No real vault, OPAQUE wheel, rate limiter, or database is touched.
"""

from __future__ import annotations

import base64
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


VAULT_A = "11111111-1111-1111-1111-111111111111"
VAULT_B = "22222222-2222-2222-2222-222222222222"
SESSION_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SESSION_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
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
        if "select vault_handle, opaque_registration_record" in normalized:
            vault_id, handle = params
            if vault_id == VAULT_A and bytes(handle) == HANDLE:
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
                if "returning server_state" in normalized:
                    self.result = {"server_state": stored[1]}
                else:
                    self.result = {"slot_id": slot_id}
        else:
            raise AssertionError(f"unexpected SQL in synthetic fixture: {normalized[:90]}")

    def fetchone(self):
        return self.result


class _Db:
    def __init__(self):
        self.slots = {}

    def cursor(self, cursor_factory=None):
        return _Cursor(self)

    def commit(self):
        pass

    def close(self):
        pass


@pytest.fixture
def route_harness():
    from routes import auth_zk_routes as zk
    from vault_handle import to_display

    db = _Db()
    selected = {"principal": {"vault_id": VAULT_A, "token_id": SESSION_A}}
    app = FastAPI()
    app.include_router(zk.router)
    app.dependency_overrides[zk.verify_trusted_device] = lambda: selected["principal"]
    with (
        mock.patch.object(zk, "_zk_login_connection", side_effect=lambda: nullcontext(db)),
        mock.patch.object(zk, "_get_secret", return_value=b"synthetic-session-signing-secret-32bytes"),
        mock.patch.object(zk, "opaque_login_start", return_value=(b"synthetic-ke2", b"synthetic-state")),
        mock.patch.object(zk, "opaque_login_finish", return_value=None) as finish,
        mock.patch.object(zk, "enforce_login_init_rate_limits"),
        mock.patch.object(zk, "enforce_login_finalize_rate_limit"),
        mock.patch.object(zk, "issue_session_token") as issue,
    ):
        with TestClient(app, raise_server_exceptions=False) as client:
            yield zk, client, db, selected, to_display(HANDLE), finish, issue


def _init(client, handle):
    return client.post("/auth/zk-verify-init", json={
        "vault_handle": handle, "ke1": _b64(b"synthetic-ke1"),
    })


def _finish(client, slot_id):
    return client.post("/auth/zk-verify-finalize", json={
        "slot_id": slot_id, "ke3": _b64(b"synthetic-ke3"),
    })


def test_reverify_issues_no_session_and_needs_no_raw_pin(route_harness):
    zk, client, db, selected, handle, opaque_finish, issue = route_harness
    init = _init(client, handle)
    assert init.status_code == 200, init.text
    assert set(init.json()) == {"slot_id", "ke2"}
    finalized = _finish(client, init.json()["slot_id"])
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["verified"] is True
    assert finalized.json()["proof_token"]
    assert "session_token" not in finalized.json()
    opaque_finish.assert_called_once()
    issue.assert_not_called()


@pytest.mark.parametrize("principal", [
    {"vault_id": VAULT_A, "token_id": SESSION_B},
    {"vault_id": VAULT_B, "token_id": SESSION_A},
])
def test_slot_is_bound_to_vault_and_session(route_harness, principal):
    zk, client, db, selected, handle, opaque_finish, issue = route_harness
    slot_id = _init(client, handle).json()["slot_id"]
    selected["principal"] = principal
    denied = _finish(client, slot_id)
    assert denied.status_code == 401
    assert slot_id in db.slots
    opaque_finish.assert_not_called()
    selected["principal"] = {"vault_id": VAULT_A, "token_id": SESSION_A}
    assert _finish(client, slot_id).status_code == 200


def test_slot_expiry_and_replay_fail(route_harness):
    zk, client, db, selected, handle, opaque_finish, issue = route_harness
    slot_id = _init(client, handle).json()["slot_id"]
    vault_id, state, _ = db.slots[slot_id]
    db.slots[slot_id] = (vault_id, state, datetime.now(timezone.utc) - timedelta(seconds=1))
    assert _finish(client, slot_id).status_code == 401
    assert opaque_finish.call_count == 0

    good_slot = _init(client, handle).json()["slot_id"]
    assert _finish(client, good_slot).status_code == 200
    assert _finish(client, good_slot).status_code == 401
    assert opaque_finish.call_count == 1


def test_bad_opaque_finish_consumes_slot_without_proof(route_harness):
    zk, client, db, selected, handle, opaque_finish, issue = route_harness
    slot_id = _init(client, handle).json()["slot_id"]
    opaque_finish.side_effect = zk.OpaqueError("synthetic rejected finish")
    denied = _finish(client, slot_id)
    assert denied.status_code == 401
    assert slot_id not in db.slots
    assert not any(key.startswith(zk.RECENT_PROOF_VERSION + ".") for key in db.slots)
    assert _finish(client, slot_id).status_code == 401


def test_proof_is_single_use_and_bound_to_vault_and_session(route_harness):
    zk, client, db, selected, handle, opaque_finish, issue = route_harness
    slot_id = _init(client, handle).json()["slot_id"]
    proof = _finish(client, slot_id).json()["proof_token"]
    owner = {"vault_id": VAULT_A, "token_id": SESSION_A}
    for other in (
        {"vault_id": VAULT_A, "token_id": SESSION_B},
        {"vault_id": VAULT_B, "token_id": SESSION_A},
    ):
        with pytest.raises(HTTPException) as exc:
            zk.consume_recent_zk_proof(proof, other)
        assert exc.value.status_code == 401
        assert proof in db.slots
    zk.consume_recent_zk_proof(proof, owner)
    with pytest.raises(HTTPException) as exc:
        zk.consume_recent_zk_proof(proof, owner)
    assert exc.value.status_code == 401


def test_proof_expiry_fails_before_db_consumption(route_harness):
    zk, client, db, selected, handle, opaque_finish, issue = route_harness
    slot_id = _init(client, handle).json()["slot_id"]
    proof = _finish(client, slot_id).json()["proof_token"]
    expiry_ts = int(proof.split(".")[1])
    with mock.patch.object(zk.time, "time", return_value=expiry_ts + 1):
        with pytest.raises(HTTPException) as exc:
            zk.consume_recent_zk_proof(
                proof, {"vault_id": VAULT_A, "token_id": SESSION_A},
            )
    assert exc.value.status_code == 401
    assert proof in db.slots
