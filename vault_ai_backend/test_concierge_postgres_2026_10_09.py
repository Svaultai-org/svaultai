"""Opt-in disposable PostgreSQL validation; refuses any production/default DSN.

Set only VAULTAI_CONCIERGE_TEST_DATABASE_URL to the explicitly isolated local
database. A fresh generated schema contains synthetic fixtures and is removed
afterward. No vault from another schema is touched, even in this test database.
"""
from __future__ import annotations

import base64
import importlib.util
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
import pytest
from fastapi import HTTPException

import concierge_exposure as ex
from routes import concierge_routes as routes

_DSN = os.getenv("VAULTAI_CONCIERGE_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not _DSN, reason="Explicit disposable Concierge PostgreSQL DSN not supplied")


@pytest.fixture
def db(monkeypatch):
    parsed = urlparse(_DSN)
    if (parsed.scheme not in ("postgresql", "postgres") or parsed.hostname != "127.0.0.1"
            or parsed.port != 55438 or parsed.path != "/svaultai_concierge_tests"
            or parsed.username != "svaultai_concierge_tests"):
        pytest.fail("Refusing non-disposable test database target")
    schema = "concierge_test_" + uuid4().hex
    assert re.fullmatch(r"concierge_test_[0-9a-f]{32}", schema)
    admin = psycopg2.connect(_DSN)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT current_database(),current_user")
        assert cur.fetchone() == ("svaultai_concierge_tests", "svaultai_concierge_tests")
        cur.execute(f'CREATE SCHEMA "{schema}"')

    connections = []
    def connect():
        connection = psycopg2.connect(_DSN, options=f"-c search_path={schema}")
        connections.append(connection)
        with connection.cursor() as cur:
            cur.execute("SELECT current_database(),current_schema()")
            assert cur.fetchone() == ("svaultai_concierge_tests", schema)
        return connection

    path = Path(__file__).parent / "migrations/versions/0047_concierge_exposure.py"
    spec = importlib.util.spec_from_file_location("concierge_pg_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    with monkeypatch.context() as patch:
        patch.setattr(migration.op, "execute", statements.append)
        migration.upgrade()
    with connect() as connection:
        with connection.cursor() as cur:
            # Minimum preexisting tables used by this additive feature, not copies
            # of production rows and not an attempted legacy auth migration.
            cur.execute("""CREATE TABLE vaults(vault_id UUID PRIMARY KEY);
              CREATE TABLE vault_items(id BIGSERIAL PRIMARY KEY,vault_id UUID NOT NULL REFERENCES vaults(vault_id) ON DELETE CASCADE);
              CREATE TABLE vault_crypto_envelopes(vault_id UUID,record_domain TEXT,record_id TEXT,deleted_at TIMESTAMPTZ);
              CREATE TABLE unrelated_encrypted_fixture(id INTEGER PRIMARY KEY,ciphertext BYTEA NOT NULL);
              INSERT INTO unrelated_encrypted_fixture VALUES(1,decode('0123456789abcdef','hex'));""")
            for statement in statements:
                cur.execute(statement)
    vault_id, other_id = str(uuid4()), str(uuid4())
    with connect() as connection:
        with connection.cursor() as cur:
            cur.execute("INSERT INTO vaults VALUES(%s),(%s)", (vault_id, other_id))
    settings = ex.Settings(True, True, True, "1" * 32, {"v1": bytes(range(32))}, "v1", 5, 86400)
    monkeypatch.setattr(ex, "get_db", connect)
    monkeypatch.setattr(routes, "get_db", connect)
    monkeypatch.setattr(ex.Settings, "from_environment", lambda: settings)
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: {
        "email_monitoring": {"status": "available"}, "email_range": {"status": "available"},
        "stealer_logs": {"status": "conditional", "verified_email_domains": ["example.com"]}})
    try:
        yield connect, vault_id, other_id, settings
    finally:
        for connection in connections:
            connection.close()
        # Exact generated test schema only; guard connection identity again before
        # cleanup. This never deletes a database or a checkout/root directory.
        with admin.cursor() as cur:
            cur.execute("SELECT current_database(),current_user")
            assert cur.fetchone() == ("svaultai_concierge_tests", "svaultai_concierge_tests")
            cur.execute(f'DROP SCHEMA "{schema}" CASCADE')
        admin.close()


def new_monitor(vault_id, settings):
    return ex.create_monitor(vault_id, "synthetic@example.com", None, stealer_logs=False, settings=settings)


def test_real_pg_migration_ciphertext_and_cascade_leave_unrelated_data(db):
    connect, vault_id, _, settings = db
    monitor = new_monitor(vault_id, settings)
    routes.put_state(routes.OpaqueStateRequest(ciphertext=base64.urlsafe_b64encode(b"c" * 40).decode().rstrip("="),
                                               expected_revision=0, envelope_version="v1"), {"vault_id": vault_id})
    ex.consume_vault_budget(vault_id)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT email_ciphertext FROM concierge_monitors WHERE id=%s", (monitor["id"],))
            assert b"synthetic@" not in bytes(cur.fetchone()[0])
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))
            for table in ("concierge_monitors", "concierge_client_state", "concierge_request_budget"):
                cur.execute(f"SELECT COUNT(*) FROM {table} WHERE vault_id=%s", (vault_id,))
                assert cur.fetchone()[0] == 0
            cur.execute("SELECT encode(ciphertext,'hex') FROM unrelated_encrypted_fixture")
            assert cur.fetchone()[0] == "0123456789abcdef"


def test_real_pg_concurrent_background_claim_is_single(db):
    _, vault_id, _, settings = db
    new_monitor(vault_id, settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _x: ex.claim_monitor(), [1, 2]))
    assert sum(value is not None for value in claims) == 1


def test_real_pg_manual_scope_and_lease_prevent_other_vault_or_duplicate(db):
    _, vault_id, other_id, settings = db
    monitor = new_monitor(vault_id, settings)
    assert ex.claim_monitor(vault_id=other_id, monitor_id=monitor["id"]) is None
    first = ex.claim_monitor(vault_id=vault_id, monitor_id=monitor["id"])
    assert first
    with pytest.raises(ex.ProviderError, match="monitor_check_in_progress"):
        ex.claim_monitor(vault_id=vault_id, monitor_id=monitor["id"])


def test_real_pg_shared_provider_budget_and_vault_budget(db):
    _, vault_id, _, settings = db
    def reserve(_x):
        try:
            ex.reserve_provider_slot(settings)
            return "reserved"
        except ex.ProviderError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, [1, 2]))
    assert sorted(outcomes) == ["provider_rate_limited", "reserved"]
    for _ in range(20):
        ex.consume_vault_budget(vault_id)
    with pytest.raises(ex.ProviderError, match="concierge_rate_limited"):
        ex.consume_vault_budget(vault_id)


def test_real_pg_withdrawal_serializes_with_external_disclosure(db, monkeypatch):
    _, vault_id, other_id, settings = db
    monitor = new_monitor(vault_id, settings)
    claim = ex.claim_monitor(vault_id=vault_id, monitor_id=monitor["id"])
    entered, release, deleted = threading.Event(), threading.Event(), threading.Event()
    class Provider:
        def __init__(self, *_a, **_kw): pass
        def email_breaches(self, _email):
            entered.set()
            assert release.wait(5)
            return []
    monkeypatch.setattr(ex, "HibpProvider", Provider)
    def withdraw():
        result = ex.delete_monitor(vault_id, monitor["id"])
        deleted.set()
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        checking = pool.submit(ex.perform_monitor_check, *claim, settings=settings)
        assert entered.wait(5)
        assert not ex.delete_monitor(other_id, monitor["id"])
        withdrawal = pool.submit(withdraw)
        assert not deleted.wait(0.1)
        release.set()
        assert checking.result(timeout=5)["status"] == "no_known_findings"
        assert withdrawal.result(timeout=5)
    assert ex.perform_monitor_check(*claim, settings=settings) is None


def test_real_pg_state_optimistic_revision_does_not_overwrite(db):
    _, vault_id, _, _ = db
    payload = routes.OpaqueStateRequest(ciphertext=base64.urlsafe_b64encode(b"c" * 40).decode().rstrip("="),
                                        expected_revision=0, envelope_version="v1")
    assert routes.put_state(payload, {"vault_id": vault_id})["revision"] == 1
    with pytest.raises(HTTPException) as error:
        routes.put_state(payload, {"vault_id": vault_id})
    assert error.value.status_code == 409
    assert routes.get_state({"vault_id": vault_id})["revision"] == 1


def test_real_pg_failed_source_validation_cannot_create_unowned_monitor(db):
    connect, vault_id, other_id, settings = db
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO vault_items(vault_id) VALUES(%s) RETURNING id", (other_id,))
            item_id = str(cur.fetchone()[0])
    with pytest.raises(ValueError, match="source_item_not_found"):
        ex.create_monitor(vault_id, "synthetic@example.com", item_id, stealer_logs=False, settings=settings)
    assert ex.list_monitors(vault_id) == []
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM vault_items WHERE vault_id=%s", (other_id,))
            assert cur.fetchone()[0] == 1


def test_real_pg_deleted_source_stops_monitor_without_provider_call(db):
    connect, vault_id, _, settings = db
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO vault_items(vault_id) VALUES(%s) RETURNING id", (vault_id,))
            item_id = str(cur.fetchone()[0])
    monitor = ex.create_monitor(vault_id, "synthetic@example.com", item_id, stealer_logs=False, settings=settings)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vault_items WHERE vault_id=%s", (vault_id,))
    claim = ex.claim_monitor(vault_id=vault_id, monitor_id=monitor["id"])
    result = ex.perform_monitor_check(*claim, settings=settings)
    assert result["status"] == "unavailable" and not result["background"]
    assert result["error_code"] == "source_item_no_longer_available"
