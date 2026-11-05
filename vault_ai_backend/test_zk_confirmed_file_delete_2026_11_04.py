"""Synthetic checks for deleting the sole verified MVK copy of a file."""

from __future__ import annotations

from unittest import mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


PRINCIPAL = {
    "vault_id": "11111111-1111-1111-1111-111111111111",
    "token_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
}
FILE_ID = "synthetic-file"


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.result = None
        self.rowcount = 0
        self.queries = []

    def execute(self, sql, params):
        statement = " ".join(sql.lower().split())
        self.queries.append(statement)
        self.result = None
        self.rowcount = 0
        if statement.startswith("select pg_advisory_xact_lock"):
            return
        if statement.startswith("select verification_state, lifecycle_state"):
            self.result = self.db.state if self.db.v2_exists else None
            return
        if statement.startswith("select file_size, encrypted_file_data is not null"):
            self.result = (40, self.db.legacy_ciphertext_exists) if self.db.marker_exists else None
            return
        if statement.startswith("delete from file_v2_records"):
            if self.db.v2_exists:
                self.db.v2_exists = False
                self.rowcount = 1
            return
        if statement.startswith("delete from uploaded_files"):
            if self.db.marker_exists and not self.db.legacy_ciphertext_exists:
                self.db.marker_exists = False
                self.rowcount = 1
            return
        if statement.startswith("update vaults set total_bytes"):
            decrement, vault_id = params
            assert vault_id == PRINCIPAL["vault_id"]
            self.db.vault_bytes = max(0, self.db.vault_bytes - decrement)
            self.rowcount = 1
            return
        raise AssertionError(f"unexpected synthetic SQL: {statement[:120]}")

    def fetchone(self):
        return self.result


class _Db:
    def __init__(self):
        self.v2_exists = True
        self.marker_exists = True
        self.legacy_ciphertext_exists = False
        self.state = ("client_verified", "legacy_migration_retired")
        self.vault_bytes = 100
        self.cur = _Cursor(self)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


@pytest.fixture
def delete_harness(monkeypatch):
    from routes import file_v2_routes as route
    import billing
    import vault_relationship_graph
    import vault_chat_active_entity
    import vault_tool_result_cache

    db = _Db()
    proof = mock.Mock()
    account_bytes = mock.Mock()
    relationships = mock.Mock()
    active_entity = mock.Mock()
    cache = mock.Mock()
    monkeypatch.setattr(route, "get_db", lambda: db)
    monkeypatch.setattr(route, "_enabled", lambda write=False: None)
    monkeypatch.setattr(route, "require_content_write", mock.Mock())
    monkeypatch.setattr(route, "consume_recent_zk_proof", proof)
    monkeypatch.setattr(billing, "get_account_id_for_vault", lambda _: "synthetic-account")
    monkeypatch.setattr(billing, "bump_account_total_bytes", account_bytes)
    monkeypatch.setattr(vault_relationship_graph, "cleanup_relationships_for_file", relationships)
    monkeypatch.setattr(vault_chat_active_entity, "clear_active_entity_if_matches_file", active_entity)
    monkeypatch.setattr(vault_tool_result_cache, "invalidate_for_event", cache)
    return route, db, proof, account_bytes, relationships, active_entity, cache


def _request(route, confirm=True):
    return route.ConfirmedFileDelete(
        zk_proof_token="synthetic-one-time-proof", confirm=confirm,
    )


def test_confirmed_delete_removes_both_copies_and_updates_quota(delete_harness):
    route, db, proof, account_bytes, relationships, active_entity, cache = delete_harness
    result = route.delete_verified_file(FILE_ID, _request(route), PRINCIPAL)
    assert result == {"file_id": FILE_ID, "deleted": True}
    assert db.v2_exists is False and db.marker_exists is False
    assert db.vault_bytes == 60 and db.commits == 1
    proof.assert_called_once_with("synthetic-one-time-proof", PRINCIPAL)
    account_bytes.assert_called_once_with("synthetic-account", -40)
    relationships.assert_called_once_with(PRINCIPAL["vault_id"], FILE_ID)
    active_entity.assert_called_once_with(PRINCIPAL["vault_id"], FILE_ID)
    cache.assert_called_once_with(vault_id=PRINCIPAL["vault_id"], event="file_deleted")
    assert "for update" in db.cur.queries[1]
    assert "for update" in db.cur.queries[2]


def test_delete_needs_confirmation_before_database_or_proof(delete_harness):
    route, db, proof, account_bytes, relationships, active_entity, cache = delete_harness
    with pytest.raises(HTTPException) as raised:
        route.delete_verified_file(FILE_ID, _request(route, confirm=False), PRINCIPAL)
    assert raised.value.status_code == 400
    assert not db.cur.queries
    proof.assert_not_called()
    assert db.v2_exists and db.marker_exists


def test_failed_proof_cannot_delete_verified_file(delete_harness):
    route, db, proof, account_bytes, relationships, active_entity, cache = delete_harness
    proof.side_effect = HTTPException(401, detail="invalid proof")
    with pytest.raises(HTTPException) as raised:
        route.delete_verified_file(FILE_ID, _request(route), PRINCIPAL)
    assert raised.value.status_code == 401
    assert db.v2_exists and db.marker_exists and db.vault_bytes == 100
    account_bytes.assert_not_called()


def test_delete_refuses_file_with_remaining_legacy_ciphertext(delete_harness):
    route, db, proof, account_bytes, relationships, active_entity, cache = delete_harness
    db.legacy_ciphertext_exists = True
    with pytest.raises(HTTPException) as raised:
        route.delete_verified_file(FILE_ID, _request(route), PRINCIPAL)
    assert raised.value.status_code == 409
    assert db.v2_exists and db.marker_exists
    proof.assert_not_called()


@pytest.mark.parametrize("extra", [{"pin": "123456"}, {"file_content": "secret"}])
def test_delete_contract_rejects_plaintext_fields(delete_harness, extra):
    route, db, proof, account_bytes, relationships, active_entity, cache = delete_harness
    with pytest.raises(ValidationError):
        route.ConfirmedFileDelete(
            zk_proof_token="synthetic-one-time-proof", confirm=True, **extra,
        )
