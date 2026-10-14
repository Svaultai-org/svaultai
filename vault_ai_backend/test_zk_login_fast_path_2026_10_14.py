"""Additive login hints, using synthetic rows and an executable SQL guard.

No real credentials, production services, or disposable database are needed.
SQLite executes the freshness join rather than a mock deciding its outcome.
Existing integration suites cover the PostgreSQL transaction primitives.
"""

import asyncio
import base64
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "postgresql://synthetic:synthetic@127.0.0.1:1/synthetic")
os.environ.setdefault("OPENAI_API_KEY", "synthetic-unused")

import auth_local
import rate_limit_auth as limits
import rate_limit_backend as backends
from opaque_server_module import OpaqueError
from routes import auth_zk_routes as routes
from vault_handle import to_display


VAULT_ID = "11111111-1111-1111-1111-111111111111"
TOKEN_ID = "22222222-2222-2222-2222-222222222222"
DEVICE_ID = "synthetic-device"
SALT = base64.b64encode(b"synthetic-salt16!").decode()
CREATED = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def vault_row(**overrides):
    row = dict(vault_id=VAULT_ID, pin_salt=SALT, kdf_iterations=600_000,
               total_bytes=1234, created_at=CREATED)
    row.update(overrides)
    return row


def issued_token(**overrides):
    token = dict(token="synthetic-signed-token", token_id=TOKEN_ID,
                 vault_id=VAULT_ID, vault_name="", client_label="Unknown device",
                 expires_at=NOW + timedelta(hours=1),
                 vault_meta=auth_local._vault_meta_snapshot(vault_row()))
    token.update(overrides)
    return token


def request(device_id=DEVICE_ID):
    headers = [] if device_id is None else [(b"x-device-id", device_id.encode())]
    return Request({"type": "http", "headers": headers,
                    "client": ("192.0.2.1", 12345)})


class PlaybackConnection:
    def __init__(self, row):
        self.row = row
        self.queries = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, **_kwargs):
        return self

    def execute(self, query, params):
        self.queries.append((query, params))

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class GuardDb:
    """Translate psycopg placeholders; execute the production SELECT itself."""
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("NOW", 0, lambda: NOW.isoformat())
        self.db.executescript("""
            CREATE TABLE vaults (vault_id TEXT PRIMARY KEY, pin_salt TEXT,
                kdf_iterations INTEGER, total_bytes INTEGER, created_at TEXT);
            CREATE TABLE auth_sessions (token_id TEXT PRIMARY KEY, vault_id TEXT,
                device_id TEXT, revoked_at TEXT, expires_at TEXT);
            CREATE TABLE trusted_devices (vault_id TEXT, device_id TEXT, status TEXT);
        """)
        self.db.execute("INSERT INTO vaults VALUES (?,?,?,?,?)",
                        (VAULT_ID, SALT, 600_000, 1234, CREATED.isoformat()))
        self.db.execute("INSERT INTO auth_sessions VALUES (?,?,?,?,?)",
                        (TOKEN_ID, VAULT_ID, DEVICE_ID, None,
                         (NOW + timedelta(hours=1)).isoformat()))
        self.db.execute("INSERT INTO trusted_devices VALUES (?,?,?)",
                        (VAULT_ID, DEVICE_ID, "trusted"))
        self.reads = 0
        self.closed = False

    def cursor(self, **_kwargs):
        return self

    def execute(self, query, params):
        self.reads += 1
        self.result = self.db.execute(query.replace("%s", "?"), params)

    def fetchone(self):
        row = self.result.fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("created_at"):
            result["created_at"] = datetime.fromisoformat(result["created_at"])
        return result

    def close(self):
        self.closed = True


@pytest.fixture
def guard():
    db = GuardDb()
    yield db
    db.db.close()


@pytest.fixture
def finalizer(monkeypatch, guard):
    slot = PlaybackConnection(dict(vault_id=VAULT_ID, server_state=b"synthetic-state"))
    updated = PlaybackConnection(dict(vault_id=VAULT_ID, vault_handle=bytes(range(15)),
        wrapped_mvk=b"wrapped-mvk", wrapped_sk_vault=b"wrapped-sk",
        display_name_ciphertext=b"display-ciphertext", pin_salt=SALT,
        kdf_iterations=600_000))
    db = mock.Mock(side_effect=[slot, updated, guard])
    finish = mock.Mock(return_value=b"synthetic-opaque-session-key")
    issue = mock.Mock(return_value=issued_token())
    trust = mock.Mock(return_value=dict(status="trusted", device_id=DEVICE_ID))
    monkeypatch.setattr(routes, "get_db", db)
    monkeypatch.setattr(routes, "opaque_login_finish", finish)
    monkeypatch.setattr(routes, "issue_session_token", issue)
    monkeypatch.setattr(routes, "enforce_login_finalize_rate_limit", lambda _r: None)
    monkeypatch.setattr("device_monitor.trust_current_and_revoke_others", trust)
    payload = routes.ZkLoginFinalizeRequest(slot_id="synthetic-slot",
        ke3=routes._b64url_encode(b"synthetic-proof"), device_id=DEVICE_ID)
    return dict(slot=slot, updated=updated, db=db, finish=finish,
                issue=issue, trust=trust, payload=payload)


def run_finalizer(state, *, header=DEVICE_ID):
    return asyncio.run(routes.zk_login_finalize(state["payload"], request(header)))


def test_successful_api_returns_additive_hints_and_existing_crypto_fields(finalizer):
    app = FastAPI()
    app.include_router(routes.router)
    response = TestClient(app).post("/auth/zk-login-finalize",
        json=finalizer["payload"].model_dump(), headers={"X-Device-Id": DEVICE_ID})
    assert response.status_code == 200
    body = response.json()
    assert body["device_trust_complete"] is True
    assert body["vault_meta"] == auth_local._vault_meta_snapshot(vault_row())
    assert body["session_token"] == "synthetic-signed-token"
    assert body["wrapped_mvk"] == routes._b64url_encode(b"wrapped-mvk")
    assert body["wrapped_sk_vault"] == routes._b64url_encode(b"wrapped-sk")
    assert body["display_name_ciphertext"] == routes._b64url_encode(b"display-ciphertext")
    assert not {"token_id", "client_label", "pin_verifier", "expires_at"} & body.keys()
    finalizer["finish"].assert_called_once_with(b"synthetic-state", b"synthetic-proof")
    assert finalizer["slot"].commits == finalizer["updated"].commits == 1
    assert finalizer["issue"].call_args.kwargs["include_vault_meta"] is True


@pytest.mark.parametrize("trust_result", [None, {}, {"status": "pending", "device_id": DEVICE_ID},
    {"status": "trusted", "device_id": "other-device"}])
def test_unconfirmed_trust_preserves_login_and_uses_fallback(finalizer, trust_result):
    finalizer["trust"].return_value = trust_result
    response = run_finalizer(finalizer)
    assert response.session_token == "synthetic-signed-token"
    assert response.device_trust_complete is False and response.vault_meta is None
    assert finalizer["db"].call_count == 2


def test_trust_exception_preserves_login_and_uses_fallback(finalizer):
    finalizer["trust"].side_effect = RuntimeError("synthetic trust unavailable")
    response = run_finalizer(finalizer)
    assert response.device_trust_complete is False and response.vault_meta is None
    assert response.session_token == "synthetic-signed-token"
    assert finalizer["db"].call_count == 2


@pytest.mark.parametrize("header", [None, "different-device"])
def test_missing_or_mismatched_request_device_cannot_skip_registration(finalizer, header):
    response = run_finalizer(finalizer, header=header)
    assert response.device_trust_complete is False and response.vault_meta is None
    assert finalizer["db"].call_count == 2


def test_missing_body_device_uses_fallback(finalizer):
    finalizer["payload"].device_id = None
    response = run_finalizer(finalizer)
    assert response.device_trust_complete is False and response.vault_meta is None
    finalizer["trust"].assert_not_called()
    assert finalizer["db"].call_count == 2


@pytest.mark.parametrize("token", [issued_token(vault_meta=None),
    issued_token(vault_meta=auth_local._vault_meta_snapshot(vault_row(pin_salt=None))),
    issued_token(vault_meta={"vault_id": VAULT_ID, "pin_salt": SALT, "kdf_iterations": True})])
def test_missing_or_legacy_metadata_keeps_the_existing_fetch_path(finalizer, token):
    finalizer["issue"].return_value = token
    response = run_finalizer(finalizer)
    assert response.device_trust_complete is False and response.vault_meta is None
    assert finalizer["db"].call_count == 2


@pytest.mark.parametrize("changed", [{"pin_salt": "old-salt"}, {"kdf_iterations": 700_000}])
def test_rotation_between_wrapped_key_read_and_issuance_requires_fallback(finalizer, changed):
    finalizer["updated"].row.update(changed)
    response = run_finalizer(finalizer)
    assert response.device_trust_complete is False and response.vault_meta is None
    assert response.session_token == "synthetic-signed-token"
    assert finalizer["db"].call_count == 2


@pytest.mark.parametrize("mutation", [
    "UPDATE vaults SET pin_salt = 'different-salt'",
    "UPDATE vaults SET kdf_iterations = 700000",
    "UPDATE auth_sessions SET revoked_at = '2026-10-14'",
    "UPDATE auth_sessions SET token_id = 'other-session'",
    "UPDATE auth_sessions SET expires_at = '2026-10-13'",
    "UPDATE auth_sessions SET device_id = 'other-device'",
    "UPDATE trusted_devices SET status = 'revoked'",
    "UPDATE trusted_devices SET device_id = 'other-device'",
    "DELETE FROM vaults",
])
def test_rotation_or_revocation_after_issuance_requires_fallback(finalizer, guard, mutation):
    # Models a concurrent change after issuance but before the fresh guard.
    def trust(**_kwargs):
        guard.db.execute(mutation)
        return dict(status="trusted", device_id=DEVICE_ID)
    finalizer["trust"].side_effect = trust
    response = run_finalizer(finalizer)
    assert response.device_trust_complete is False and response.vault_meta is None
    assert response.session_token == "synthetic-signed-token"
    assert guard.reads == 1 and guard.closed


def test_unavailable_guard_preserves_login_and_requires_fallback(finalizer):
    finalizer["db"].side_effect = [finalizer["slot"], finalizer["updated"],
                                    RuntimeError("synthetic metadata unavailable")]
    response = run_finalizer(finalizer)
    assert response.device_trust_complete is False and response.vault_meta is None
    assert response.session_token == "synthetic-signed-token"


def test_guard_returns_current_non_crypto_metadata_and_matches_existing_endpoint(finalizer, guard, monkeypatch):
    guard.db.execute("UPDATE vaults SET total_bytes = 9876")
    response = run_finalizer(finalizer)
    assert response.device_trust_complete is True
    assert response.vault_meta["total_bytes"] == 9876
    assert response.vault_meta["pin_salt"] == SALT
    assert response.vault_meta["kdf_iterations"] == 600_000
    # Run the actual existing endpoint with an already validated principal;
    # its auth/device checks are independently covered by the auth suites.
    import main
    conn = PlaybackConnection(vault_row(total_bytes=9876))
    monkeypatch.setattr(main, "get_db", lambda: conn)
    existing = asyncio.run(main.vault_meta_endpoint(request(), principal={"vault_id": VAULT_ID}))
    assert response.vault_meta == existing
    assert conn.closed


def test_invalid_opaque_proof_still_consumes_slot_before_rejecting(finalizer):
    finalizer["finish"].side_effect = OpaqueError("synthetic reject")
    with pytest.raises(routes.HTTPException) as rejected:
        run_finalizer(finalizer)
    assert rejected.value.status_code == 401
    assert finalizer["slot"].commits == 1 and finalizer["slot"].closed
    finalizer["issue"].assert_not_called()
    finalizer["trust"].assert_not_called()


@pytest.mark.parametrize("include", [False, True])
def test_optional_issuance_snapshot_does_not_change_token_or_session_transaction(monkeypatch, include):
    conn = PlaybackConnection(vault_row())
    monkeypatch.setattr(auth_local, "get_db", lambda: conn)
    token_bytes = uuid.UUID(TOKEN_ID).bytes
    monkeypatch.setattr(auth_local.secrets, "token_bytes", lambda n: token_bytes)
    monkeypatch.setattr(auth_local, "_get_secret", lambda: b"synthetic-test-secret-32-bytes-long")
    result = auth_local.issue_session_token(vault_id=VAULT_ID, device_id=DEVICE_ID,
        client_label="Unknown device", ttl_hours=1, include_vault_meta=include)
    assert auth_local._parse_token(result["token"]) == token_bytes
    assert result["token_id"] == TOKEN_ID and result["vault_id"] == VAULT_ID
    assert conn.commits == 1 and conn.rollbacks == 0 and conn.closed
    assert len(conn.queries) == 4  # existing lock, revoke, insert, audit only
    lock_sql, lock_params = conn.queries[0]
    assert "FOR UPDATE" in lock_sql and lock_params == (VAULT_ID,)
    if include:
        assert result["vault_meta"] == auth_local._vault_meta_snapshot(vault_row())
        assert "pin_salt" in lock_sql
    else:
        assert "vault_meta" not in result
        assert lock_sql == "SELECT vault_id FROM vaults WHERE vault_id = %s FOR UPDATE"
    revoke_sql, revoke_params = conn.queries[1]
    assert "superseded-by-new-login" in revoke_sql
    assert revoke_params == (VAULT_ID,)
    insert_sql, insert_params = conn.queries[2]
    assert "INSERT INTO auth_sessions" in insert_sql
    assert insert_params[:5] == (TOKEN_ID, auth_local._hash_token_id(token_bytes),
                               VAULT_ID, DEVICE_ID, "Unknown device")
    remaining = result["expires_at"] - datetime.now(timezone.utc)
    assert timedelta(minutes=59) < remaining <= timedelta(hours=1)


def test_failed_session_commit_does_not_surface_a_token_or_snapshot(monkeypatch):
    conn = PlaybackConnection(vault_row())
    conn.commit = mock.Mock(side_effect=RuntimeError("synthetic commit failure"))
    monkeypatch.setattr(auth_local, "get_db", lambda: conn)
    monkeypatch.setattr(auth_local, "_get_secret", lambda: b"synthetic-test-secret-32-bytes-long")
    format_token = mock.Mock(side_effect=AssertionError("wire token built before commit"))
    monkeypatch.setattr(auth_local, "_format_token", format_token)
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        auth_local.issue_session_token(vault_id=VAULT_ID, device_id=DEVICE_ID,
            client_label="Unknown device", include_vault_meta=True)
    format_token.assert_not_called()
    assert conn.rollbacks == 1 and conn.closed


@pytest.mark.parametrize("missing_slot", [False, True])
def test_finalize_phase_diagnostics_contain_only_closed_labels_and_durations(finalizer, caplog, missing_slot):
    if missing_slot:
        finalizer["slot"].row = None
    with caplog.at_level(logging.INFO, logger=routes.__name__):
        if missing_slot:
            with pytest.raises(routes.HTTPException):
                run_finalizer(finalizer)
        else:
            run_finalizer(finalizer)
    records = [record.getMessage() for record in caplog.records
               if record.getMessage().startswith("[AUTH-ZK-TIMING]")]
    assert len(records) == 1
    diagnostic = records[0]
    assert "step=finalize" in diagnostic
    assert f"status={401 if missing_slot else 200}" in diagnostic
    assert all(f"{phase}_ms=" in diagnostic for phase in routes._ZK_LOGIN_PHASES)
    assert "total_ms=" in diagnostic
    assert all(secret not in diagnostic for secret in (
        VAULT_ID, TOKEN_ID, DEVICE_ID, SALT, "synthetic-proof",
        "synthetic-state", "synthetic-signed-token", "192.0.2.1"))
    assert routes._zk_login_timings.get() is None


def test_malformed_login_init_still_consumes_ip_budget_before_400(monkeypatch):
    backend = backends.InMemoryRateLimitBackend()
    monkeypatch.setattr(limits, "get_rate_limit_backend", lambda: backend)
    monkeypatch.setattr(limits, "LOGIN_LIMIT_PER_WINDOW", 10)
    monkeypatch.setattr(limits, "LOGIN_WINDOW_SECONDS", 60)
    db = mock.Mock(side_effect=AssertionError("DB before valid syntax/limit"))
    opaque = mock.Mock(side_effect=AssertionError("OPAQUE before valid syntax/limit"))
    monkeypatch.setattr(routes, "get_db", db)
    monkeypatch.setattr(routes, "opaque_login_start", opaque)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    for _ in range(10):
        response = client.post("/auth/zk-login-init", json={"vault_handle": "invalid-handle", "ke1": "eA"})
        assert response.status_code == 400
    denied = client.post("/auth/zk-login-init", json={"vault_handle": "invalid-handle", "ke1": "eA"})
    assert denied.status_code == 429
    assert 1 <= int(denied.headers["Retry-After"]) <= 60
    db.assert_not_called()
    opaque.assert_not_called()


def test_valid_login_init_consumes_ip_once_and_limits_before_db_opaque(monkeypatch, caplog):
    backend = backends.InMemoryRateLimitBackend()
    monkeypatch.setattr(limits, "get_rate_limit_backend", lambda: backend)
    monkeypatch.setattr(limits, "LOGIN_LIMIT_PER_WINDOW", 2)
    monkeypatch.setattr(limits, "LOGIN_WINDOW_SECONDS", 60)
    handle = b"h" * 15
    lookup = b"l" * 32
    record = dict(vault_id=VAULT_ID, vault_handle=handle,
                  username_lookup_v1=lookup, opaque_registration_record=b"synthetic-record")
    db = mock.Mock(side_effect=lambda: PlaybackConnection(record))
    opaque = mock.Mock(return_value=(b"synthetic-ke2", b"synthetic-state"))
    monkeypatch.setattr(routes, "get_db", db)
    monkeypatch.setattr(routes, "opaque_login_start", opaque)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    payload = {"vault_handle": to_display(handle), "ke1": "eA",
               "username_lookup": routes._b64url_encode(lookup)}
    with caplog.at_level(logging.INFO, logger=routes.__name__):
        assert client.post("/auth/zk-login-init", json=payload).status_code == 200
        assert client.post("/auth/zk-login-init", json=payload).status_code == 200
        denied = client.post("/auth/zk-login-init", json=payload)
    assert denied.status_code == 429
    assert db.call_count == 4 and opaque.call_count == 2
    diagnostics = [record.getMessage() for record in caplog.records
                   if record.getMessage().startswith("[AUTH-ZK-TIMING]")]
    assert len(diagnostics) == 3
    assert "step=init" in diagnostics[-1] and "status=429" in diagnostics[-1]
    assert all(VAULT_ID not in line and "synthetic-record" not in line for line in diagnostics)
