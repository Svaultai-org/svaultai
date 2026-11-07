"""Synthetic cutover tests; never use a real vault or PIN."""

from __future__ import annotations

from pathlib import Path
from unittest import mock
import os
import uuid

import pytest
import psycopg2
from fastapi import HTTPException, Request
from psycopg2.errors import LockNotAvailable
from psycopg2.extras import RealDictCursor

from auth_local import (
    PIN_FREE_BENEFICIARY_OFFER,
    PIN_FREE_FILE_CREATE_OFFER,
    PIN_FREE_FILE_DOWNLOAD_OFFER,
    PIN_FREE_FILE_LIST_OFFER,
    PIN_FREE_FILE_MUTATION_OFFER,
    PIN_FREE_ITEM_READ_OFFER,
    PIN_FREE_PASSWORD_ANALYSIS_OFFER,
    PIN_FREE_PRIVATE_CHAT_OFFER,
)
from routes import zk_verifier_retirement_routes as route
from strict_raw_pin_ingress_gate import FLAG_NAME


VAULT = "11111111-1111-1111-1111-111111111111"
OFFERS = (
    PIN_FREE_ITEM_READ_OFFER | PIN_FREE_FILE_LIST_OFFER |
    PIN_FREE_FILE_DOWNLOAD_OFFER | PIN_FREE_FILE_CREATE_OFFER |
    PIN_FREE_FILE_MUTATION_OFFER | PIN_FREE_PASSWORD_ANALYSIS_OFFER |
    PIN_FREE_BENEFICIARY_OFFER | PIN_FREE_PRIVATE_CHAT_OFFER
)
BLOCKER_CODES = (
    "legacy_items", "incomplete_items", "legacy_item_edits",
    "legacy_item_history", "legacy_files", "legacy_file_chunks",
    "incomplete_files", "pending_file_v2", "pending_wallet_v2",
    "legacy_beneficiary_links", "retained_migration_journal",
    "active_legacy_session",
)


def _request(*header_values: bytes) -> Request:
    return Request({
        "type": "http", "method": "POST",
        "path": "/auth/zk-pin-verifier-retire",
        "headers": [
            (b"x-svaultai-strict-pin-free-client", value)
            for value in header_values
        ],
    })


def _principal(*, offers=OFFERS, method="opaque") -> dict:
    return {"vault_id": VAULT, "auth_method": method,
            "pin_free_read_offers": offers}


def _payload(*, ack=True) -> route.RetirePinVerifierRequest:
    return route.RetirePinVerifierRequest(
        zk_proof_token="synthetic-proof", client_verified_exact_readback=ack,
    )


class FakeCursor:
    def __init__(self, *, blockers=(), retired=False, update_ok=True, busy=False):
        self.blockers = set(blockers)
        self.retired = retired
        self.update_ok = update_ok
        self.busy = busy
        self.events = []
        self.fetch_result = None
        self.check_index = 0

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.events.append((normalized, params))
        if normalized.startswith("LOCK TABLE"):
            if self.busy:
                raise LockNotAvailable()
            self.fetch_result = None
        elif "FROM vaults WHERE vault_id=%s FOR UPDATE" in normalized:
            self.fetch_result = {
                "vault_handle": b"synthetic", "opaque_registration_record": b"synthetic",
                "wrapped_mvk": b"synthetic", "wrapped_sk_vault": b"synthetic",
                "pk_vault_public": b"synthetic",
                "display_name_ciphertext": b"synthetic",
                "pin_verifier": "synthetic-verifier",
                "pin_verifier_retired_at": "synthetic-time" if self.retired else None,
            }
        elif normalized.startswith("SELECT EXISTS"):
            code = BLOCKER_CODES[self.check_index]
            self.check_index += 1
            self.fetch_result = {"blocked": code in self.blockers}
        elif normalized.startswith("UPDATE vaults SET pin_verifier=''"):
            self.fetch_result = (
                {"pin_verifier_retired_at": "synthetic-time"}
                if self.update_ok else None
            )
        else:
            raise AssertionError(f"unexpected SQL: {normalized[:100]}")

    def fetchone(self):
        return self.fetch_result


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def cursor(self, **_kwargs):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


def _enable(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_PIN_VERIFIER_RETIRE_ENABLED", "true")
    monkeypatch.setenv(FLAG_NAME, "true")


def test_default_off_retirement_never_opens_database(monkeypatch):
    monkeypatch.delenv("VAULTAI_ZK_PIN_VERIFIER_RETIRE_ENABLED", raising=False)
    monkeypatch.setenv(FLAG_NAME, "true")
    with mock.patch.object(route, "get_db") as db, pytest.raises(HTTPException) as exc:
        route.retire_pin_verifier(_payload(), _request(b"v1"), _principal())
    assert exc.value.status_code == 404
    db.assert_not_called()


@pytest.mark.parametrize("strict,headers,offers,method,status", [
    (False, (b"v1",), OFFERS, "opaque", 409),
    (True, (), OFFERS, "opaque", 426),
    (True, (b"v1", b"v1"), OFFERS, "opaque", 426),
    (True, (b"v1",), OFFERS & ~PIN_FREE_PRIVATE_CHAT_OFFER, "opaque", 409),
    (True, (b"v1",), OFFERS, "legacy_pin", 409),
])
def test_cutover_requires_server_and_session_parity(
    monkeypatch, strict, headers, offers, method, status,
):
    _enable(monkeypatch)
    if not strict:
        monkeypatch.setenv(FLAG_NAME, "false")
    with mock.patch.object(route, "get_db") as db, pytest.raises(HTTPException) as exc:
        route.retire_pin_verifier(
            _payload(), _request(*headers),
            _principal(offers=offers, method=method),
        )
    assert exc.value.status_code == status
    db.assert_not_called()


def test_client_readback_ack_is_required_before_any_db_work(monkeypatch):
    _enable(monkeypatch)
    with mock.patch.object(route, "get_db") as db, pytest.raises(HTTPException) as exc:
        route.retire_pin_verifier(_payload(ack=False), _request(b"v1"), _principal())
    assert exc.value.status_code == 400
    db.assert_not_called()


@pytest.mark.parametrize("blocker", BLOCKER_CODES)
def test_each_known_legacy_source_blocks_verifier_retirement(monkeypatch, blocker):
    _enable(monkeypatch)
    cur = FakeCursor(blockers=(blocker,))
    conn = FakeConnection(cur)
    with mock.patch.object(route, "get_db", return_value=conn), \
         mock.patch.object(route, "consume_recent_zk_proof_on_cursor") as proof, \
         pytest.raises(HTTPException) as exc:
        route.retire_pin_verifier(_payload(), _request(b"v1"), _principal())
    assert exc.value.status_code == 409
    assert exc.value.detail == {
        "code": "verifier_retirement_not_ready", "blockers": [blocker],
    }
    assert conn.commits == 0 and conn.rollbacks == 1 and conn.closed == 1
    proof.assert_called_once()
    assert not any(sql.startswith("UPDATE vaults SET pin_verifier=''" )
                   for sql, _ in cur.events)


def test_clean_vault_retires_atomically_after_owner_proof(monkeypatch):
    _enable(monkeypatch)
    cur = FakeCursor()
    conn = FakeConnection(cur)
    with mock.patch.object(route, "get_db", return_value=conn), \
         mock.patch.object(route, "consume_recent_zk_proof_on_cursor") as proof:
        result = route.retire_pin_verifier(
            _payload(), _request(b"v1"), _principal(),
        )
    assert result == {"retired": True, "already_retired": False}
    assert conn.commits == 1 and conn.rollbacks == 0 and conn.closed == 1
    assert cur.check_index == len(BLOCKER_CODES)
    assert cur.events[0][0].startswith("LOCK TABLE ")
    proof.assert_called_once()
    updates = [sql for sql, _ in cur.events if sql.startswith("UPDATE vaults")]
    assert updates == [
        "UPDATE vaults SET pin_verifier='', pin_verifier_retired_at=NOW() "
        "WHERE vault_id=%s AND pin_verifier_retired_at IS NULL "
        "RETURNING pin_verifier_retired_at"
    ]


def test_failed_update_rolls_back_proof_and_verifier_change(monkeypatch):
    _enable(monkeypatch)
    conn = FakeConnection(FakeCursor(update_ok=False))
    with mock.patch.object(route, "get_db", return_value=conn), \
         mock.patch.object(route, "consume_recent_zk_proof_on_cursor") as proof, \
         pytest.raises(HTTPException) as exc:
        route.retire_pin_verifier(_payload(), _request(b"v1"), _principal())
    assert exc.value.status_code == 409
    proof.assert_called_once()
    assert conn.commits == 0 and conn.rollbacks == 1


def test_invalid_owner_proof_cannot_learn_blocker_categories(monkeypatch):
    _enable(monkeypatch)
    cur = FakeCursor(blockers=("legacy_items",))
    conn = FakeConnection(cur)
    with mock.patch.object(route, "get_db", return_value=conn), \
         mock.patch.object(
             route, "consume_recent_zk_proof_on_cursor",
             side_effect=HTTPException(status_code=401, detail="invalid_proof"),
         ), pytest.raises(HTTPException) as exc:
        route.retire_pin_verifier(_payload(), _request(b"v1"), _principal())
    assert exc.value.status_code == 401
    assert "legacy_items" not in str(exc.value.detail)
    assert cur.check_index == 0
    assert conn.commits == 0 and conn.rollbacks == 1


def test_busy_source_table_fails_closed_without_wait_or_proof(monkeypatch):
    _enable(monkeypatch)
    cur = FakeCursor(busy=True)
    conn = FakeConnection(cur)
    with mock.patch.object(route, "get_db", return_value=conn), \
         mock.patch.object(route, "consume_recent_zk_proof_on_cursor") as proof, \
         pytest.raises(HTTPException) as exc:
        route.retire_pin_verifier(_payload(), _request(b"v1"), _principal())
    assert exc.value.status_code == 409
    assert exc.value.detail == "verifier_retirement_busy"
    assert "NOWAIT" in cur.events[0][0]
    assert conn.commits == 0 and conn.rollbacks == 1
    proof.assert_not_called()


def test_existing_retirement_is_idempotent_and_does_not_consume_proof(monkeypatch):
    _enable(monkeypatch)
    conn = FakeConnection(FakeCursor(retired=True))
    with mock.patch.object(route, "get_db", return_value=conn), \
         mock.patch.object(route, "consume_recent_zk_proof_on_cursor") as proof:
        result = route.retire_pin_verifier(_payload(), _request(b"v1"), _principal())
    assert result == {"retired": True, "already_retired": True}
    assert conn.commits == 1
    proof.assert_not_called()


def test_schema_guards_every_checked_legacy_oracle_table():
    migration = (Path(__file__).parent / "migrations/versions/0060_pin_verifier_retirement.py").read_text()
    for table in route._SOURCE_TABLES:
        assert f'"{table}"' in migration
    assert "pin_verifier_retirement_is_irreversible" in migration
    assert "retired_vault_cannot_store_legacy_pin_oracle" in migration


def test_my_vault_reports_opaque_signin_after_verifier_retirement():
    import main

    cur = mock.Mock()
    cur.fetchone.return_value = {
        "vault_id": VAULT, "pin_salt": "synthetic-salt",
        "pin_verifier": "", "vault_handle": b"synthetic-handle",
        "must_reset": False, "locked_until": None,
    }
    conn = mock.Mock()
    conn.cursor.return_value = cur
    with mock.patch.object(main, "get_db", return_value=conn):
        result = main.get_my_vault(principal={"vault_id": VAULT})
    assert result["has_pin"] is True
    assert result["vault_name"] is None
    conn.close.assert_called_once()


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="isolated migrated PostgreSQL test database not configured",
)
def test_migrated_database_rejects_reintroduced_verifier_and_legacy_content():
    """Use a disposable synthetic vault; rollback keeps the DB empty."""
    vault_id = str(uuid.uuid4())
    label = "vault-" + vault_id.replace("-", "")
    conn = psycopg2.connect(os.environ["VAULTAI_TEST_DATABASE_URL"])
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO vaults (
                  vault_id, vault_name, pin_salt, pin_verifier,
                  username_lookup_v1, vault_handle,
                  opaque_registration_record, wrapped_mvk,
                  wrapped_sk_vault, pk_vault_public,
                  display_name_ciphertext
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (vault_id, label, "synthetic-salt", "synthetic-verifier",
                  bytes([1]) * 32, bytes([2]) * 15, b"synthetic-record",
                  b"synthetic-mvk", b"synthetic-sk", bytes([3]) * 32,
                  b"synthetic-display"))
            cur.execute(
                "UPDATE vaults SET pin_verifier='', "
                "pin_verifier_retired_at=NOW() WHERE vault_id=%s",
                (vault_id,),
            )
            for sql, params in (
                ("UPDATE vaults SET pin_verifier='restored' WHERE vault_id=%s",
                 (vault_id,)),
                ("INSERT INTO vault_items "
                 "(vault_id,item_type,service,encrypted_data) "
                 "VALUES (%s,'login','synthetic','synthetic-ciphertext')",
                 (vault_id,)),
                ("INSERT INTO uploaded_files "
                 "(id,vault_id,file_name,file_size,encrypted_file_data) "
                 "VALUES ('synthetic-file',%s,'synthetic',1,'synthetic-ciphertext')",
                 (vault_id,)),
                ("INSERT INTO beneficiary_links "
                 "(passer_vault_id,passer_label,wrapped_vault_key) "
                 "VALUES (%s,'synthetic','synthetic-legacy-wrap')",
                 (vault_id,)),
            ):
                cur.execute("SAVEPOINT source_attempt")
                with pytest.raises(psycopg2.Error) as exc:
                    cur.execute(sql, params)
                assert exc.value.pgcode == "23514"
                cur.execute("ROLLBACK TO SAVEPOINT source_attempt")
            # The same marker still allows a V2-only item.
            cur.execute("""
                INSERT INTO vault_items (
                  vault_id,item_type,service,encrypted_data,
                  item_type_ciphertext,service_ciphertext,payload_ciphertext
                ) VALUES (%s,NULL,NULL,NULL,%s,%s,%s)
            """, (vault_id, b"synthetic-type", b"synthetic-service",
                  b"synthetic-payload"))
            assert route._source_blockers(cur, vault_id) == []
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="isolated migrated PostgreSQL test database not configured",
)
def test_clean_synthetic_vault_retires_in_one_postgres_transaction():
    vault_id = str(uuid.uuid4())
    label = "vault-" + vault_id.replace("-", "")
    url = os.environ["VAULTAI_TEST_DATABASE_URL"]
    conn = psycopg2.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vaults (
                  vault_id,vault_name,pin_salt,pin_verifier,
                  username_lookup_v1,vault_handle,
                  opaque_registration_record,wrapped_mvk,
                  wrapped_sk_vault,pk_vault_public,
                  display_name_ciphertext
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (vault_id, label, "synthetic-salt", "synthetic-verifier",
                  uuid.UUID(vault_id).bytes * 2, uuid.UUID(vault_id).bytes[:15],
                  b"synthetic-record", b"synthetic-mvk", b"synthetic-sk",
                  bytes([3]) * 32, b"synthetic-display"))
        conn.commit()
    finally:
        conn.close()
    try:
        with mock.patch.object(route, "get_db", side_effect=lambda: psycopg2.connect(url)), \
             mock.patch.object(route, "consume_recent_zk_proof_on_cursor") as proof:
            result = route._retire_pin_verifier(
                _payload(), {"vault_id": vault_id},
            )
        assert result == {"retired": True, "already_retired": False}
        proof.assert_called_once()
        check = psycopg2.connect(url)
        try:
            with check.cursor() as cur:
                cur.execute("""
                    SELECT pin_verifier,pin_verifier_retired_at,
                           opaque_registration_record,wrapped_mvk
                      FROM vaults WHERE vault_id=%s
                """, (vault_id,))
                verifier, retired_at, opaque_record, wrapped_mvk = cur.fetchone()
                assert verifier == ""
                assert retired_at is not None
                assert bytes(opaque_record) == b"synthetic-record"
                assert bytes(wrapped_mvk) == b"synthetic-mvk"
        finally:
            check.close()
    finally:
        cleanup = psycopg2.connect(url)
        try:
            with cleanup.cursor() as cur:
                cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))
            cleanup.commit()
        finally:
            cleanup.close()
