"""Execute real login/session/trust SQL with synthetic transactional rows.

SQLite runs the SQL (only FOR UPDATE syntax is translated). A small adapter
models psycopg's implicit transaction start and the actual pool wrapper.
PostgreSQL locking/concurrency integration remains separately gated.
"""
import asyncio
import base64
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from starlette.requests import Request

os.environ.setdefault("DATABASE_URL", "postgresql://synthetic:synthetic@127.0.0.1:1/synthetic")
import auth_local
import device_monitor
import vault_core
from opaque_server_module import OpaqueError
from routes import auth_zk_routes as routes
from vault_handle import to_display

VAULT = "11111111-1111-1111-1111-111111111111"
OLD_TOKEN = "22222222-2222-2222-2222-222222222222"
HANDLE = b"h" * 15
LOOKUP = b"l" * 32
SALT = base64.b64encode(b"synthetic-salt16!").decode()
DEVICE = "synthetic-current-device"


class Cursor:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql, params=()):
        compact = " ".join(sql.split())
        if compact == "SELECT 1":
            phase = "health"
        elif compact.startswith("DELETE FROM vault_zk_login_slots"):
            phase = "slot_consume"
        elif compact.startswith("UPDATE vaults"):
            phase = "vault_update"
        elif "FOR UPDATE" in compact:
            phase = "session_lock"
        elif compact.startswith("UPDATE auth_sessions"):
            phase = "session_revoke"
        elif compact.startswith("INSERT INTO auth_sessions"):
            phase = "session_insert"
        elif compact.startswith("INSERT INTO trusted_devices"):
            phase = "trust_upsert"
        elif compact.startswith("UPDATE trusted_devices"):
            phase = "trust_revoke"
        elif compact.startswith("SELECT v.vault_id"):
            phase = "metadata"
        elif compact.startswith("INSERT INTO vault_zk_login_slots"):
            phase = "slot_create"
        else:
            phase = "lookup" if compact.startswith("SELECT") else "audit"
        self.raw.last_phase = phase
        self.raw.events.append(phase)
        if not self.raw.db.in_transaction:
            self.raw.db.execute("BEGIN")
        if self.raw.fail_query == phase:
            raise RuntimeError("synthetic query failure")
        values = [v.isoformat() if isinstance(v, datetime) else v for v in params]
        self.result = self.raw.db.execute(sql.replace("FOR UPDATE", "").replace("%s", "?"), values)

    def convert(self, row):
        if row is None:
            return None
        result = dict(row)
        for key in ("created_at", "issued_at", "expires_at"):
            if result.get(key):
                value = datetime.fromisoformat(result[key])
                result[key] = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return result

    def fetchone(self):
        return self.convert(self.result.fetchone())

    def fetchall(self):
        return [self.convert(row) for row in self.result.fetchall()]


class RawConnection:
    def __init__(self):
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat())
        self.db.executescript("""
          CREATE TABLE vaults (vault_id TEXT PRIMARY KEY, pin_salt TEXT, kdf_iterations INTEGER,
            total_bytes INTEGER, created_at TEXT, vault_handle BLOB, opaque_registration_record BLOB,
            username_lookup_v1 BLOB, wrapped_mvk BLOB, wrapped_sk_vault BLOB,
            display_name_ciphertext BLOB, last_login_at TEXT, last_vault_unlock_at TEXT,
            last_any_activity_at TEXT, failed_pin_attempts INTEGER);
          CREATE TABLE auth_sessions (token_id TEXT PRIMARY KEY, token_id_hash BLOB, vault_id TEXT,
            device_id TEXT, client_label TEXT, client_label_source INTEGER, expires_at TEXT,
            revoked_at TEXT, revoked_reason TEXT, issued_at TEXT DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE vault_security_events (vault_id TEXT, event_type TEXT, client_label TEXT);
          CREATE TABLE trusted_devices (vault_id TEXT, device_id TEXT, label TEXT,
            user_agent_brand TEXT, last_ip_prefix TEXT, status TEXT, approved_at TEXT,
            last_seen_at TEXT, revoked_at TEXT, cooldown_until TEXT, PRIMARY KEY(vault_id,device_id));
          CREATE TABLE vault_zk_login_slots (slot_id TEXT PRIMARY KEY, vault_id TEXT,
            server_state BLOB, expires_at TEXT);
        """)
        now = datetime.now(timezone.utc)
        self.db.execute("INSERT INTO vaults VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (VAULT, SALT, 600000, 1234, now.isoformat(), HANDLE, b"synthetic-record", LOOKUP,
             b"wrapped-mvk", b"wrapped-sk", b"display-ciphertext", None, None, None, 0))
        self.db.execute("INSERT INTO auth_sessions (token_id,vault_id,device_id,client_label,expires_at,issued_at) VALUES (?,?,?,?,?,?)",
            (OLD_TOKEN, VAULT, "synthetic-prior-device", "Unknown device",
             (now + timedelta(hours=1)).isoformat(), now.isoformat()))
        self.db.execute("INSERT INTO trusted_devices (vault_id,device_id,status) VALUES (?,?,?)",
            (VAULT, "synthetic-prior-device", "trusted"))
        self.db.execute("INSERT INTO vault_zk_login_slots VALUES (?,?,?,?)",
            ("synthetic-slot", VAULT, b"synthetic-state", (now + timedelta(minutes=5)).isoformat()))
        self.db.commit()
        self.closed = False
        self.events = []
        self.last_phase = None
        self.fail_query = None
        self.fail_final_rollback = False

    def cursor(self, **_kwargs):
        return Cursor(self)

    def commit(self):
        self.events.append("commit")
        self.db.commit()

    def rollback(self):
        self.events.append("rollback")
        if self.fail_final_rollback and self.last_phase == "metadata":
            raise RuntimeError("synthetic dead socket on release")
        self.db.rollback()

    def close(self):
        self.closed = True
        self.db.close()


class Pool:
    def __init__(self, raw):
        self.raw = raw
        self.borrows = 0
        self.returns = []

    def getconn(self):
        self.borrows += 1
        return self.raw

    def putconn(self, conn, *, close=False):
        self.returns.append(close)
        if close:
            conn.close()


@pytest.fixture
def runtime(monkeypatch):
    raw = RawConnection()
    pool = Pool(raw)
    monkeypatch.setattr(vault_core, "_get_pool", lambda: pool)
    # Any callee borrowing again fails: the real primitives receive the lease.
    monkeypatch.setattr(auth_local, "get_db", mock.Mock(side_effect=AssertionError("session borrowed again")))
    monkeypatch.setattr(device_monitor, "get_db", mock.Mock(side_effect=AssertionError("trust borrowed again")))
    monkeypatch.setattr(auth_local, "_get_secret", lambda: b"synthetic-session-secret-more-than32bytes")
    monkeypatch.setattr(routes, "enforce_login_init_rate_limits", lambda *_a, **_k: None)
    monkeypatch.setattr(routes, "enforce_login_finalize_rate_limit", lambda *_a: None)

    def opaque_start(*_args):
        assert not raw.db.in_transaction  # lookup transaction has ended
        raw.events.append("opaque_start")
        return b"synthetic-ke2", b"synthetic-state"

    def opaque_finish(*_args):
        assert not raw.db.in_transaction  # slot consumption already committed
        assert raw.events[-1] == "commit"
        raw.events.append("opaque_finish")
        return b"synthetic-opaque-session-key"

    monkeypatch.setattr(routes, "opaque_login_start", opaque_start)
    monkeypatch.setattr(routes, "opaque_login_finish", opaque_finish)
    yield raw, pool
    if not raw.closed:
        raw.close()


def request(device=DEVICE):
    return Request({"type": "http", "headers": [(b"x-device-id", device.encode())],
                    "client": ("192.0.2.1", 12345)})


def finalize(slot="synthetic-slot", device=DEVICE):
    payload = routes.ZkLoginFinalizeRequest(slot_id=slot, ke3="eA", device_id=device)
    return asyncio.run(routes.zk_login_finalize(payload, request(device)))


def initialize():
    payload = routes.ZkLoginInitRequest(vault_handle=to_display(HANDLE), ke1="eA",
        username_lookup=routes._b64url_encode(LOOKUP))
    return asyncio.run(routes.zk_login_init(payload, request()))


def test_successful_finalize_uses_one_health_check_and_retains_all_commit_boundaries(runtime):
    raw, pool = runtime
    result = finalize()
    assert result.device_trust_complete is True
    assert result.vault_meta["pin_salt"] == SALT and result.vault_meta["kdf_iterations"] == 600000
    token_bytes = auth_local._parse_token(result.session_token)
    assert token_bytes is not None
    live = raw.db.execute("SELECT * FROM auth_sessions WHERE revoked_at IS NULL").fetchall()
    assert len(live) == 1 and live[0]["token_id_hash"] == auth_local._hash_token_id(token_bytes)
    assert pool.borrows == 1 and pool.returns == [False]
    assert raw.events.count("health") == 1 and raw.events.count("commit") == 4
    assert raw.events.index("slot_consume") < raw.events.index("commit") < raw.events.index("opaque_finish")
    assert raw.events.index("session_lock") < raw.events.index("session_revoke") < raw.events.index("session_insert")
    assert raw.events.index("trust_upsert") < raw.events.index("trust_revoke") < raw.events.index("metadata")
    devices = dict(raw.db.execute("SELECT device_id,status FROM trusted_devices"))
    assert devices == {"synthetic-prior-device": "revoked", DEVICE: "trusted"}
    events = raw.db.execute("SELECT event_type FROM vault_security_events").fetchall()
    assert [row[0] for row in events] == ["new_session_created", "previous_session_revoked"]
    assert not raw.db.in_transaction


def test_init_reuses_lease_after_ending_lookup_transaction(runtime):
    raw, pool = runtime
    result = initialize()
    assert pool.borrows == 1 and pool.returns == [False]
    assert raw.events == ["health", "rollback", "lookup", "rollback", "opaque_start", "slot_create", "commit", "rollback"]
    assert raw.db.execute("SELECT 1 FROM vault_zk_login_slots WHERE slot_id=?", (result.slot_id,)).fetchone()
    assert not raw.db.in_transaction


def test_separate_exchanges_never_hold_connection_across_client_work(runtime):
    raw, pool = runtime
    first = initialize()
    assert pool.returns == [False] and not raw.db.in_transaction
    finalize(first.slot_id)
    second = initialize()
    assert pool.returns == [False, False, False] and not raw.db.in_transaction
    finalize(second.slot_id, "synthetic-other-device")
    assert pool.borrows == 4 and pool.returns == [False] * 4
    assert raw.db.execute("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL").fetchone()[0] == 1
    assert raw.db.execute("SELECT COUNT(*) FROM trusted_devices WHERE status='trusted'").fetchone()[0] == 1
    assert raw.db.execute("SELECT status FROM trusted_devices WHERE device_id=?", (DEVICE,)).fetchone()[0] == "revoked"


def test_invalid_proof_leaves_consumed_slot_committed_and_issues_no_session(runtime, monkeypatch):
    raw, pool = runtime
    monkeypatch.setattr(routes, "opaque_login_finish", mock.Mock(side_effect=OpaqueError("synthetic reject")))
    with pytest.raises(routes.HTTPException) as error:
        finalize()
    assert error.value.status_code == 401
    assert raw.db.execute("SELECT 1 FROM vault_zk_login_slots WHERE slot_id='synthetic-slot'").fetchone() is None
    assert raw.db.execute("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL").fetchone()[0] == 1
    assert "session_insert" not in raw.events and "trust_upsert" not in raw.events
    assert pool.borrows == 1 and pool.returns == [False]


def test_failed_session_insert_rolls_back_revocation_without_returning_new_token(runtime):
    raw, pool = runtime
    raw.fail_query = "session_insert"
    with pytest.raises(RuntimeError, match="synthetic query failure"):
        finalize()
    assert raw.db.execute("SELECT token_id FROM auth_sessions WHERE revoked_at IS NULL").fetchone()[0] == OLD_TOKEN
    assert raw.db.execute("SELECT COUNT(*) FROM vault_security_events").fetchone()[0] == 0
    assert "trust_upsert" not in raw.events
    assert pool.borrows == 1 and pool.returns == [False]
    assert not raw.db.in_transaction


def test_failed_device_transaction_keeps_issued_session_and_falls_back(runtime):
    raw, pool = runtime
    raw.fail_query = "trust_revoke"
    result = finalize()
    assert result.device_trust_complete is False and result.vault_meta is None
    assert auth_local._parse_token(result.session_token) is not None
    assert raw.db.execute("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL").fetchone()[0] == 1
    assert raw.db.execute("SELECT device_id FROM trusted_devices WHERE status='trusted'").fetchone()[0] == "synthetic-prior-device"
    assert "metadata" not in raw.events and not raw.db.in_transaction
    assert pool.borrows == 1 and pool.returns == [False]


def test_failed_freshness_read_keeps_fallback_and_releases_transaction(runtime):
    raw, pool = runtime
    raw.fail_query = "metadata"
    result = finalize()
    assert result.device_trust_complete is False and result.vault_meta is None
    assert pool.borrows == 1 and pool.returns == [False]
    assert not raw.db.in_transaction


def test_broken_rollback_on_final_release_discards_connection(runtime):
    raw, pool = runtime
    raw.fail_final_rollback = True
    result = finalize()
    assert result.device_trust_complete is True
    assert pool.borrows == 1 and pool.returns == [True]
    assert raw.closed  # actual _PooledConnection.close discarded the socket
