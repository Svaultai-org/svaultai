"""Ciphertext memory identity/race tests; never connects to a database."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading

import pytest
from fastapi import HTTPException
from psycopg2.errors import UniqueViolation

from routes import vault_ciphertext_write_routes as routes


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _request(record: str, *, lookup: bytes = b"A" * 32, edit=False, value=b"new"):
    return routes.AiMemoryCiphertextRequest(
        memory_id=record,
        memory_type="note",
        memory_lookup_hash=_b64(lookup),
        payload_ciphertext=_b64(value),
        replace_existing=edit,
    )


class _Store:
    def __init__(self, rows=(), *, synchronize_create=False):
        self.rows = deepcopy(list(rows))
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2) if synchronize_create else None
        self.commits = 0
        self.updates = 0
        self.inserts = 0
        self.force_unique_error = False

    def connect(self):
        return _Connection(self)


class _Connection:
    def __init__(self, store):
        self.store = store
        self.selects = 0

    def cursor(self, **_kwargs):
        return _Cursor(self)

    def commit(self):
        with self.store.lock:
            self.store.commits += 1

    def close(self):
        pass


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def execute(self, query, parameters):
        store = self.connection.store
        sql = " ".join(query.lower().split())
        if sql.startswith("select id, memory_record_id"):
            vault, lookup = parameters
            with store.lock:
                row = next((row for row in store.rows
                            if row["vault_id"] == vault
                            and row["lookup"] == lookup), None)
                self.result = None if row is None else {
                    "id": row["id"], "memory_record_id": row["record"]
                }
            self.connection.selects += 1
            if store.barrier and self.connection.selects == 1:
                # Both callers see the title absent before either INSERTs.
                store.barrier.wait(timeout=3)
            return
        if sql.startswith("update vault_ai_memory"):
            assert "where vault_id = %s and memory_record_id = %s" in sql
            assert "superseded_at is null" in sql
            _type, ciphertext, lookup, vault, record = parameters
            with store.lock:
                if store.force_unique_error:
                    raise UniqueViolation("synthetic concurrent edit collision")
                row = next((row for row in store.rows
                            if row["vault_id"] == vault
                            and row["record"] == record), None)
                self.result = None
                if row:
                    row["ciphertext"] = ciphertext
                    row["lookup"] = lookup
                    store.updates += 1
                    self.result = {"id": row["id"]}
            return
        if sql.startswith("insert into vault_ai_memory"):
            assert "do nothing" in sql
            assert "do update" not in sql
            vault, record, _type, ciphertext, lookup = parameters
            with store.lock:
                collision = any(row["vault_id"] == vault and row["lookup"] == lookup
                                for row in store.rows)
                self.result = None
                if not collision:
                    row_id = max([row["id"] for row in store.rows], default=0) + 1
                    store.rows.append({"id": row_id, "vault_id": vault,
                                       "record": record, "lookup": lookup,
                                       "ciphertext": ciphertext})
                    store.inserts += 1
                    self.result = {"id": row_id}
            return
        raise AssertionError(f"Unexpected SQL operation: {sql}")

    def fetchone(self):
        return self.result


def _row(record="existing", lookup=b"A" * 32, vault="synthetic-vault", row_id=1):
    return {"id": row_id, "vault_id": vault, "record": record,
            "lookup": lookup, "ciphertext": b"original-opaque-ciphertext"}


def _install(monkeypatch, store):
    monkeypatch.setattr(routes, "get_db", store.connect)
    monkeypatch.setattr(routes, "require_content_write", lambda _principal: None)
    monkeypatch.setenv("MEMORY_V2_READ_ENABLED", "true")
    monkeypatch.setenv("MEMORY_V2_WRITE_ENABLED", "true")
    monkeypatch.delenv("QA_CHAT_PRIVACY_DIAGNOSTICS", raising=False)


def _call(request):
    return routes.ai_memory_ciphertext_upsert(
        request, principal={"vault_id": "synthetic-vault"}
    )


def test_duplicate_create_preserves_the_original_record(monkeypatch):
    store = _Store([_row()])
    _install(monkeypatch, store)
    original = deepcopy(store.rows)
    with pytest.raises(HTTPException) as error:
        _call(_request("different-record"))
    assert error.value.status_code == 409
    assert error.value.detail == "memory_title_conflict"
    assert store.rows == original
    assert store.commits == store.updates == store.inserts == 0


def test_identical_id_create_retry_does_not_rewrite_ciphertext(monkeypatch):
    store = _Store([_row()])
    _install(monkeypatch, store)
    original = deepcopy(store.rows)
    response = _call(_request("existing", value=b"different-encryption-nonce"))
    assert response.duplicate is True
    assert store.rows == original
    assert store.commits == store.updates == store.inserts == 0


def test_renaming_an_edit_cannot_overwrite_another_identity(monkeypatch):
    store = _Store([_row(), _row("selected", b"B" * 32, row_id=2)])
    _install(monkeypatch, store)
    original = deepcopy(store.rows)
    with pytest.raises(HTTPException) as error:
        _call(_request("selected", edit=True))
    assert error.value.status_code == 409
    assert store.rows == original
    assert store.updates == 0


def test_edit_changes_only_its_selected_stable_id(monkeypatch):
    store = _Store([_row(), _row("other", b"B" * 32, row_id=2)])
    _install(monkeypatch, store)
    other = deepcopy(store.rows[1])
    response = _call(_request("existing", lookup=b"C" * 32, edit=True))
    assert response.duplicate is False
    assert store.rows[0]["record"] == "existing"
    assert store.rows[0]["ciphertext"] == b"new"
    assert store.rows[1] == other
    assert store.updates == store.commits == 1
    assert store.inserts == 0


def test_missing_selected_edit_returns404_and_never_inserts(monkeypatch):
    store = _Store()
    _install(monkeypatch, store)
    with pytest.raises(HTTPException) as error:
        _call(_request("deleted-record", edit=True))
    assert error.value.status_code == 404
    assert store.rows == []
    assert store.inserts == store.commits == 0


@pytest.mark.parametrize("same_id", [False, True])
def test_concurrent_creates_never_replace_the_winner(monkeypatch, same_id):
    store = _Store(synchronize_create=True)
    _install(monkeypatch, store)
    requests = [_request("one", value=b"first"),
                _request("one" if same_id else "two", value=b"second")]

    def attempt(request):
        try:
            return _call(request)
        except HTTPException as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, requests))
    assert len(store.rows) == 1
    assert store.inserts == store.commits == 1
    assert store.updates == 0
    assert store.rows[0]["ciphertext"] in (b"first", b"second")
    if same_id:
        assert all(not isinstance(result, HTTPException) for result in results)
        assert sum(result.duplicate for result in results) == 1
    else:
        errors = [result for result in results if isinstance(result, HTTPException)]
        assert len(errors) == 1
        assert errors[0].status_code == 409


def test_concurrent_edit_uniqueness_error_is_safe409(monkeypatch):
    store = _Store([_row()])
    _install(monkeypatch, store)
    store.force_unique_error = True
    original = deepcopy(store.rows)
    with pytest.raises(HTTPException) as error:
        _call(_request("existing", lookup=b"C" * 32, edit=True))
    assert error.value.status_code == 409
    assert store.rows == original
    assert store.commits == 0


def test_same_blind_title_in_other_vault_does_not_block_creation(monkeypatch):
    store = _Store([_row(vault="different-synthetic-vault")])
    _install(monkeypatch, store)
    original = deepcopy(store.rows[0])
    response = _call(_request("new-record"))
    assert response.duplicate is False
    assert len(store.rows) == 2
    assert store.rows[0] == original
