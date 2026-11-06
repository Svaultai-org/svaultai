"""Synthetic HTTP regression for the proof-bound legacy chunk manifest.

Only structural metadata and an existing chunk token leave this route. The
stored chunk bytes remain encrypted and are fetched through the old chunk API.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from device_gate import verify_trusted_device
from routes import auth_zk_routes, chunked_download_routes


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = None

    def execute(self, sql, params):
        if "DELETE FROM vault_zk_login_slots" in sql:
            proof, vault_id = params
            if (proof, vault_id) in self.conn.state["proofs"]:
                self.conn.pending_proof = (proof, vault_id)
                self.result = {"slot_id": proof}
            else:
                self.result = None
        elif "FROM uploaded_file_chunks" in sql:
            file_id, chunk_index = params
            self.result = {"chunk_bytes": b"synthetic-encrypted-frame"} if (
                file_id == self.conn.state["file_id"] and chunk_index == 0
            ) else None
        elif "FROM uploaded_files" in sql:
            file_id = params[0]
            row = self.conn.state["row"]
            if "WHERE id = %s AND vault_id = %s::uuid" in sql:
                self.result = row if (
                    file_id == self.conn.state["file_id"]
                    and params[1] == self.conn.state["owner_id"]
                ) else None
            else:
                self.result = {
                    **row, "vault_id": self.conn.state["owner_id"],
                } if file_id == self.conn.state["file_id"] else None
        else:
            raise AssertionError(f"unexpected query: {sql}")

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self, state):
        self.state = state
        self.pending_proof = None

    def cursor(self, **_kwargs):
        return _Cursor(self)

    def commit(self):
        self.state["commits"] += 1
        if self.pending_proof:
            self.state["proofs"].remove(self.pending_proof)
            self.pending_proof = None

    def rollback(self):
        self.state["rollbacks"] += 1
        self.pending_proof = None

    def close(self):
        pass


@pytest.fixture
def harness(monkeypatch):
    owner_id = str(uuid.uuid4())
    principal = {"vault_id": owner_id, "token_id": str(uuid.uuid4())}
    file_id = "synthetic-file-id"
    state = {
        "file_id": file_id,
        "owner_id": owner_id,
        "row": {
            "id": file_id,
            "file_size": 2_100_000,
            "chunk_size": 1_048_576,
            "chunk_count": 3,
            "storage_mode": "chunked",
            "upload_status": "complete",
        },
        "proofs": set(),
        "commits": 0,
        "rollbacks": 0,
        "connections": 0,
        "reads": [],
    }

    def get_db():
        state["connections"] += 1
        return _Connection(state)

    monkeypatch.setenv("VAULT_SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("VAULTAI_UPLOAD_TOKEN_SECRET", "t" * 48)
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_CHUNK_MANIFEST_ENABLED", "true")
    monkeypatch.setattr(chunked_download_routes, "get_db", get_db)
    monkeypatch.setattr(
        chunked_download_routes, "is_vault_zk_adopted",
        lambda candidate: candidate == owner_id,
    )
    monkeypatch.setattr(
        chunked_download_routes, "require_file_read",
        lambda principal, size: state["reads"].append((principal["vault_id"], size)),
    )
    app = FastAPI()
    app.include_router(chunked_download_routes.router)
    app.dependency_overrides[verify_trusted_device] = lambda: principal
    client = TestClient(app)

    def proof():
        token, _expires = auth_zk_routes._new_recent_proof(principal)
        state["proofs"].add((token, principal["vault_id"]))
        return token

    return client, state, principal, proof


def _manifest(client, file_id, proof, **extra):
    return client.post(
        "/vault/legacy-file/chunked/manifest",
        json={"file_id": file_id, "zk_proof_token": proof, **extra},
    )


def test_manifest_uses_real_one_time_session_proof_and_existing_chunk_token(harness):
    client, state, principal, new_proof = harness
    proof = new_proof()
    response = _manifest(client, state["file_id"], proof)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == {
        "file_id", "storage_mode", "file_size", "chunk_size",
        "chunk_count", "download_token", "download_token_expires_at",
    }
    assert response.json()["storage_mode"] == "chunked"
    assert response.json()["file_size"] == state["row"]["file_size"]
    assert state["reads"] == [(principal["vault_id"], state["row"]["file_size"])]
    assert state["commits"] == 1
    assert proof not in response.text
    chunked_download_routes.verify_chunk_token(
        response.json()["download_token"], kind="download",
        vault_id=principal["vault_id"], file_id=state["file_id"],
    )
    chunk = client.post("/download-file/chunk", json={
        "file_id": state["file_id"], "chunk_index": 0,
        "download_token": response.json()["download_token"],
    })
    assert chunk.status_code == 200
    assert chunk.content == b"synthetic-encrypted-frame"
    assert chunk.headers["cache-control"] == "no-store"
    with pytest.raises(HTTPException) as wrong_vault:
        chunked_download_routes.verify_chunk_token(
            response.json()["download_token"], kind="download",
            vault_id=str(uuid.uuid4()), file_id=state["file_id"],
        )
    assert wrong_vault.value.status_code == 401

    replay = _manifest(client, state["file_id"], proof)
    assert replay.status_code == 401
    assert state["commits"] == 1


def test_flag_and_stable_token_secret_fail_closed_before_database(harness, monkeypatch):
    client, state, _principal, new_proof = harness
    proof = new_proof()
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_CHUNK_MANIFEST_ENABLED", "false")
    disabled = _manifest(client, state["file_id"], proof)
    assert disabled.status_code == 404
    assert state["connections"] == 0
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_CHUNK_MANIFEST_ENABLED", "true")
    monkeypatch.delenv("VAULTAI_UPLOAD_TOKEN_SECRET")
    missing_secret = _manifest(client, state["file_id"], proof)
    assert missing_secret.status_code == 503
    assert state["connections"] == 0
    assert (proof, state["owner_id"]) in state["proofs"]


def test_wrong_vault_and_incomplete_file_do_not_spend_proof(harness):
    client, state, principal, new_proof = harness
    proof = new_proof()
    missing = _manifest(client, "somebody-elses-file", proof)
    assert missing.status_code == 404
    assert (proof, principal["vault_id"]) in state["proofs"]
    state["row"]["upload_status"] = "incomplete"
    incomplete = _manifest(client, state["file_id"], proof)
    assert incomplete.status_code == 409
    assert (proof, principal["vault_id"]) in state["proofs"]
    state["row"]["upload_status"] = "complete"
    state["row"]["storage_mode"] = "inline"
    inline = _manifest(client, state["file_id"], proof)
    assert inline.status_code == 409
    assert (proof, principal["vault_id"]) in state["proofs"]
    assert state["commits"] == 0


def test_owner_scoped_lookup_hides_another_vaults_file(harness, monkeypatch):
    client, state, _principal, _new_proof = harness
    intruder = {"vault_id": str(uuid.uuid4()), "token_id": str(uuid.uuid4())}
    monkeypatch.setattr(chunked_download_routes, "is_vault_zk_adopted", lambda _: True)
    client.app.dependency_overrides[verify_trusted_device] = lambda: intruder
    proof, _expires = auth_zk_routes._new_recent_proof(intruder)
    state["proofs"].add((proof, intruder["vault_id"]))
    response = _manifest(client, state["file_id"], proof)
    assert response.status_code == 404
    assert (proof, intruder["vault_id"]) in state["proofs"]
    assert state["commits"] == 0
    assert state["reads"] == []


def test_entitlement_and_session_binding_fail_before_token(harness, monkeypatch):
    client, state, principal, new_proof = harness
    proof = new_proof()

    def deny(_principal, _size):
        raise HTTPException(status_code=403, detail="entitlement_denied")

    monkeypatch.setattr(chunked_download_routes, "require_file_read", deny)
    denied = _manifest(client, state["file_id"], proof)
    assert denied.status_code == 403
    assert (proof, principal["vault_id"]) in state["proofs"]
    monkeypatch.setattr(chunked_download_routes, "require_file_read", lambda *_: None)
    other_session = {**principal, "token_id": str(uuid.uuid4())}
    client.app.dependency_overrides[verify_trusted_device] = lambda: other_session
    wrong_session = _manifest(client, state["file_id"], proof)
    assert wrong_session.status_code == 401
    assert (proof, principal["vault_id"]) in state["proofs"]
    assert state["commits"] == 0


def test_raw_pin_and_vault_name_are_rejected_without_echo_or_lookup(harness, caplog):
    client, state, _principal, new_proof = harness
    marker = "synthetic-private-pin-marker"
    proof = new_proof()
    with caplog.at_level("DEBUG"):
        for extra in ({"pin": marker}, {"vault_name": marker}):
            response = _manifest(client, state["file_id"], proof, **extra)
            assert response.status_code == 400
            assert response.json() == {"detail": "invalid_request"}
            assert marker not in response.text
    assert marker not in caplog.text
    assert state["connections"] == 0
    assert (proof, state["owner_id"]) in state["proofs"]


def test_oversized_body_is_rejected_before_database(harness):
    client, state, _principal, new_proof = harness
    response = client.post(
        "/vault/legacy-file/chunked/manifest",
        content=b"{" + b"x" * 1025,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert state["connections"] == 0
    assert state["commits"] == 0
