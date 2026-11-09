"""Synthetic transaction and privacy checks for new client-MVK files."""

from __future__ import annotations

import copy
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://fixture.invalid/test")

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes import file_v2_new_upload_routes as route
from routes import file_v2_routes as staging


VAULT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
FILE = "v2-AAAAAAAAAAAAAAAAAAAAAAAAAAA"  # Canonical 20-byte writer ID.
UUID_FILE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PRINCIPAL = {"vault_id": VAULT, "token_id": "synthetic-session",
             "file_v2_reader_capable": True}


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.result = None
        self.rows = []
        self.rowcount = 0
        self.sql = []

    def execute(self, sql, params):
        statement = " ".join(sql.lower().split())
        self.sql.append(statement)
        self.result = None
        self.rows = []
        self.rowcount = 0
        if statement.startswith("select pg_advisory_xact_lock"):
            return
        if statement.startswith("select 1 from auth_sessions"):
            self.result = (1,) if self.db.session_current and params == (
                PRINCIPAL["token_id"], self.db.owner,
            ) else None
            return
        if statement.startswith("select file_id, manifest_ciphertext"):
            self.result = self.db.record if params == (FILE, self.db.owner) else None
            return
        if statement.startswith("select file_size, encrypted_file_data is not null"):
            self.result = self.db.marker if params == (FILE, self.db.owner) else None
            return
        if statement.startswith("select chunk_index, octet_length"):
            self.rows = self.db.chunks if params == (FILE, route.MAX_CHUNKS + 1) else []
            return
        if statement.startswith("select total_bytes, account_id from vaults"):
            self.result = {"total_bytes": self.db.vault_bytes,
                           "account_id": self.db.account_id} if params == (self.db.owner,) else None
            return
        if statement.startswith("select account_id from vaults"):
            self.result = {"account_id": self.db.account_id} if params == (self.db.owner,) else None
            return
        if statement.startswith("select account_id from accounts"):
            self.result = {"account_id": self.db.account_id} if params == (self.db.account_id,) else None
            return
        if statement.startswith("select coalesce(sum(total_bytes)"):
            self.result = {"used": self.db.vault_bytes}
            return
        if statement.startswith("insert into uploaded_files"):
            file_id, vault_id, size = params
            assert file_id == FILE and vault_id == self.db.owner
            if self.db.marker is not None:
                raise AssertionError("duplicate marker insert")
            self.db.marker = {"file_size": size, "has_legacy": False,
                              "file_name": None, "content_type": None,
                              "storage_mode": "inline", "upload_status": "complete"}
            return
        if statement.startswith("update file_v2_records set lifecycle_state"):
            if self.db.record is not None and self.db.record["lifecycle_state"] == "file_v2_written":
                self.db.record["lifecycle_state"] = "client_v2_ready"
                self.db.record["verification_state"] = "client_verified"
                self.rowcount = 1
            return
        if statement.startswith("update vaults set total_bytes=total_bytes+"):
            self.db.vault_bytes += params[0]
            self.rowcount = 1
            return
        if statement.startswith("insert into account_storage_totals"):
            self.db.account_bytes = params[1]
            return
        if statement.startswith("select total_bytes, lifecycle_state"):
            self.result = self.db.record if params == (FILE, self.db.owner) else None
            return
        if statement.startswith("delete from file_v2_records"):
            self.db.record = None
            self.db.chunks = []
            self.rowcount = 1
            return
        if statement.startswith("delete from uploaded_files"):
            if self.db.marker is not None:
                self.db.marker = None
                self.rowcount = 1
            return
        if statement.startswith("update vaults set total_bytes=greatest"):
            self.db.vault_bytes = max(0, self.db.vault_bytes - params[0])
            self.rowcount = 1
            return
        if statement.startswith("update account_storage_totals set"):
            self.db.account_bytes = max(0, self.db.account_bytes - params[0])
            return
        raise AssertionError(f"unexpected SQL: {statement[:130]}")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.rows


class _Db:
    def __init__(self):
        self.owner = VAULT
        self.account_id = "33333333-3333-3333-3333-333333333333"
        self.record = {
            "file_id": FILE,
            "manifest_ciphertext": b"x" * 60,
            "total_bytes": 5,
            "chunk_size": 5,
            "chunk_count": 1,
            "lifecycle_state": "file_v2_written",
            "verification_state": "not_verified",
        }
        self.chunks = [{"chunk_index": 0,
                        "ciphertext_bytes": 5 + route.AES_GCM_FRAME_OVERHEAD}]
        self.marker = None
        self.vault_bytes = 100
        self.account_bytes = 100
        self.session_current = True
        self.commits = 0
        self.rollbacks = 0
        self.cur = _Cursor(self)
        self._before = None

    def cursor(self, **_):
        if self._before is None:
            self._before = copy.deepcopy((self.record, self.chunks, self.marker,
                                          self.vault_bytes, self.account_bytes))
        return self.cur

    def commit(self):
        self.commits += 1
        self._before = None

    def rollback(self):
        self.rollbacks += 1
        if self._before is not None:
            (self.record, self.chunks, self.marker,
             self.vault_bytes, self.account_bytes) = self._before
        self._before = None

    def close(self):
        pass


@pytest.fixture
def harness(monkeypatch):
    db = _Db()
    proof = mock.Mock()
    # Transport-only fixture: model an indexed vault after the prerequisite.
    # Production readiness remains false; the separate gate suite checks it.
    monkeypatch.setattr(
        "file_create_conflict_gate.new_file_conflict_parity_ready",
        lambda: True,
    )
    monkeypatch.setattr(route, "get_db", lambda: db)
    monkeypatch.setattr(route, "_enabled", lambda write=False: None)
    monkeypatch.setattr(route, "_new_upload_enabled", lambda: None)
    monkeypatch.setattr(route, "require_content_write", mock.Mock())
    monkeypatch.setattr(route, "is_vault_zk_adopted", lambda _: True)
    monkeypatch.setattr(route, "_account_quota", lambda *_: (1000, db.account_bytes))
    monkeypatch.setattr(route, "consume_recent_zk_proof", proof)
    return db, proof


def _publish():
    return route.PublishNewFile(confirm=True)


def test_publishes_exact_ciphertext_once_and_retries_without_double_charge(harness):
    db, _ = harness
    first = route.publish_new_file(FILE, _publish(), PRINCIPAL)
    second = route.publish_new_file(FILE, _publish(), PRINCIPAL)
    assert first == {"file_id": FILE, "status": "published"}
    assert second == {"file_id": FILE, "status": "already_published"}
    assert db.marker == {"file_size": 5, "has_legacy": False,
                         "file_name": None, "content_type": None,
                         "storage_mode": "inline", "upload_status": "complete"}
    assert db.record["lifecycle_state"] == "client_v2_ready"
    assert db.record["verification_state"] == "client_verified"
    assert db.vault_bytes == 105 and db.account_bytes == 105
    assert db.commits == 2 and db.rollbacks == 0
    assert all("pin" not in sql and "filename" not in sql
               for sql in db.cur.sql)


def test_inherited_publish_needs_one_beneficiary_proof(harness, monkeypatch):
    db, _ = harness
    monkeypatch.setattr(route.inheritance_files, "_enabled", lambda: None)
    release = mock.Mock()
    monkeypatch.setattr(route, "_require_inheritance_release_for_publish",
                        release)
    consume = mock.Mock()
    monkeypatch.setattr(route, "consume_recent_zk_proof_on_cursor", consume)
    inherited = {
        "inheritance_link_id": 17,
        "inheritance_source_file_id": "synthetic-owner-file",
    }
    with pytest.raises(HTTPException) as missing:
        route.publish_new_file(
            FILE, route.PublishNewFile(confirm=True, **inherited), PRINCIPAL,
        )
    assert missing.value.status_code == 400
    assert db.commits == 0 and db.cur.sql == []
    assert release.call_count == 0 and consume.call_count == 0

    payload = route.PublishNewFile(
        confirm=True, zk_proof_token="synthetic-opaque-proof", **inherited,
    )
    first = route.publish_new_file(FILE, payload, PRINCIPAL)
    second = route.publish_new_file(FILE, payload, PRINCIPAL)
    assert first["status"] == "published"
    assert second["status"] == "already_published"
    assert release.call_count == 2
    consume.assert_called_once_with("synthetic-opaque-proof", PRINCIPAL, db.cur)
    assert db.commits == 2


def test_512_mib_private_file_framing_is_bounded_without_file_allocation():
    assert route.MAX_NEW_FILE_BYTES == 512 * 1024 * 1024
    payload = staging.Manifest(
        file_id=FILE,
        crypto_version="client_mvk_v2",
        manifest_ciphertext="AQID",
        total_bytes=route.MAX_NEW_FILE_BYTES,
        chunk_size=route.MAX_CHUNK_BYTES,
        chunk_count=512,
    )
    assert payload.chunk_count == 512
    record = {
        "total_bytes": payload.total_bytes,
        "chunk_size": payload.chunk_size,
        "chunk_count": payload.chunk_count,
        "manifest_ciphertext": b"x" * route.AES_GCM_FRAME_OVERHEAD,
    }
    chunks = [
        {"chunk_index": index,
         "ciphertext_bytes": route.MAX_CHUNK_BYTES +
         route.AES_GCM_FRAME_OVERHEAD}
        for index in range(payload.chunk_count)
    ]
    route._validate_framing(record, chunks)
    record["total_bytes"] += 1
    with pytest.raises(HTTPException) as oversized:
        route._validate_framing(record, chunks)
    assert oversized.value.detail == "file_v2_invalid_framing"


@pytest.mark.parametrize("change,detail", [
    (lambda db: db.chunks.clear(), "file_v2_chunks_incomplete"),
    (lambda db: db.chunks.__setitem__(0, {"chunk_index": 0,
                                        "ciphertext_bytes": 5 +
                                        route.AES_GCM_FRAME_OVERHEAD + 1}),
     "file_v2_invalid_chunk_size"),
    (lambda db: db.record.__setitem__("manifest_ciphertext", b"x" * 65537),
     "file_v2_invalid_framing"),
    (lambda db: db.record.__setitem__("total_bytes", route.MAX_NEW_FILE_BYTES + 1),
     "file_v2_invalid_framing"),
    (lambda db: db.marker.__setitem__("has_legacy", True),
     "file_v2_not_new"),
])
def test_incomplete_oversized_or_migration_file_cannot_publish(harness, change, detail):
    db, _ = harness
    if detail == "file_v2_not_new":
        db.marker = {"file_size": 5, "has_legacy": True,
                     "file_name": "legacy", "content_type": None,
                     "storage_mode": "inline", "upload_status": "complete"}
    change(db)
    with pytest.raises(HTTPException) as raised:
        route.publish_new_file(FILE, _publish(), PRINCIPAL)
    assert raised.value.detail == detail
    assert db.vault_bytes == 100 and db.account_bytes == 100
    assert db.record["lifecycle_state"] == "file_v2_written"
    assert db.rollbacks == 1


def test_quota_failure_preserves_staged_ciphertext(harness, monkeypatch):
    db, _ = harness
    monkeypatch.setattr(route, "_account_quota", lambda *_: (103, 100))
    with pytest.raises(HTTPException) as raised:
        route.publish_new_file(FILE, _publish(), PRINCIPAL)
    assert raised.value.status_code == 413
    assert db.record is not None and db.marker is None
    assert db.vault_bytes == 100 and db.account_bytes == 100


def test_old_client_session_cannot_publish_a_client_only_file(harness):
    db, _ = harness
    with pytest.raises(HTTPException) as raised:
        route.publish_new_file(
            FILE, _publish(), {**PRINCIPAL, "file_v2_reader_capable": False},
        )
    assert raised.value.status_code == 426
    assert raised.value.detail["code"] == "client_update_required"
    assert db.marker is None and db.vault_bytes == 100


def test_superseded_capable_session_cannot_publish_after_old_login(harness):
    db, _ = harness
    # Models a login that obtained the vault lock while this request waited
    # for it. The dependency had already accepted the old bearer, but the
    # under-lock check must reject it before changing file visibility.
    db.session_current = False
    with pytest.raises(HTTPException) as raised:
        route.publish_new_file(FILE, _publish(), PRINCIPAL)
    assert raised.value.status_code == 401
    assert raised.value.detail == "session_expired"
    assert db.record["lifecycle_state"] == "file_v2_written"
    assert db.marker is None and db.vault_bytes == 100
    assert db.rollbacks == 1 and db.commits == 0
    sql = db.cur.sql
    vault_lock = next(i for i, s in enumerate(sql)
                      if s.startswith("select total_bytes, account_id from vaults"))
    session_check = next(i for i, s in enumerate(sql)
                         if s.startswith("select 1 from auth_sessions"))
    assert vault_lock < session_check
    assert not any("update file_v2_records" in s or
                   "insert into uploaded_files" in s for s in sql)


def test_zero_byte_file_has_no_chunks_or_quota_delta(harness):
    db, _ = harness
    db.record["total_bytes"] = 0
    db.record["chunk_count"] = 0
    db.chunks = []
    assert route.publish_new_file(FILE, _publish(), PRINCIPAL)["status"] == "published"
    assert db.marker["file_size"] == 0
    assert db.vault_bytes == 100 and db.account_bytes == 100


def test_publish_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", raising=False)
    monkeypatch.setattr(route, "_enabled", lambda write=False: None)
    with pytest.raises(HTTPException) as raised:
        route._new_upload_enabled()
    assert raised.value.status_code == 404


def test_cross_vault_and_unconfirmed_requests_do_not_write(harness):
    db, _ = harness
    with pytest.raises(HTTPException) as cross:
        route.publish_new_file(FILE, _publish(),
                               {**PRINCIPAL, "vault_id": OTHER})
    assert cross.value.status_code == 404
    with pytest.raises(HTTPException) as unconfirmed:
        route.publish_new_file(FILE, route.PublishNewFile(confirm=False), PRINCIPAL)
    assert unconfirmed.value.status_code == 400
    with pytest.raises(HTTPException) as bad_id:
        route.publish_new_file("not-a-uuid", _publish(), PRINCIPAL)
    assert bad_id.value.status_code == 400
    assert route._file_id(UUID_FILE) == UUID_FILE
    assert db.marker is None and db.vault_bytes == 100


def test_new_file_delete_consumes_proof_and_decrements_once(harness):
    db, proof = harness
    route.publish_new_file(FILE, _publish(), PRINCIPAL)
    result = route.delete_new_file(
        FILE, route.DeleteNewFile(confirm=True, zk_proof_token="synthetic-proof"),
        PRINCIPAL,
    )
    assert result == {"file_id": FILE, "deleted": True}
    proof.assert_called_once_with("synthetic-proof", PRINCIPAL)
    assert db.record is None and db.marker is None
    assert db.vault_bytes == 100 and db.account_bytes == 100
    with pytest.raises(HTTPException) as replay:
        route.delete_new_file(
            FILE, route.DeleteNewFile(confirm=True,
                                      zk_proof_token="synthetic-proof"),
            PRINCIPAL,
        )
    assert replay.value.status_code == 404
    proof.assert_called_once()


def test_models_reject_plaintext_fields_and_routes_require_trusted_device():
    with pytest.raises(ValidationError):
        route.PublishNewFile(confirm=True, pin="synthetic-pin")
    with pytest.raises(ValidationError):
        route.DeleteNewFile(confirm=True, zk_proof_token="proof",
                            filename="private.jpg")
    for endpoint in (route.publish_new_file, route.delete_new_file):
        dependency = endpoint.__defaults__[-1]
        assert dependency.dependency is route.verify_trusted_device


def test_account_quota_uses_higher_of_counter_and_vault_sum(monkeypatch):
    class Cursor:
        def __init__(self):
            self.result = None
        def execute(self, sql, params):
            self.result = ({"account_id": params[0]} if "FROM accounts" in sql
                           else {"used": 80})
        def fetchone(self):
            return self.result
    import billing
    monkeypatch.setattr(billing, "get_entitlement", lambda _:
                        SimpleNamespace(used_bytes=90, effective_limit_bytes=200))
    assert route._account_quota(Cursor(), "account-a", 70) == (200, 90)
