"""Executable File V2 manifest retry/idempotency contract."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://fixture.invalid/test")

from fastapi import HTTPException
import pytest

from routes import file_v2_routes as routes


class _Cursor:
    def __init__(self, store):
        self.store = store
        self.result = None

    def execute(self, sql, params):
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("insert into file_v2_records"):
            file_id, vault_id, crypto, ciphertext, total, chunk, count = params
            if file_id in self.store:
                self.result = None
            else:
                self.store[file_id] = (
                    str(vault_id), crypto, total, chunk, count, ciphertext
                )
                self.result = (file_id,)
            return
        if normalized.startswith("select 1 from file_v2_records"):
            file_id, vault_id, crypto, total, chunk, count = params
            row = self.store.get(file_id)
            self.result = (1,) if row and row[:5] == (
                str(vault_id), crypto, total, chunk, count
            ) else None
            return
        raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self):
        self.store = {}
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _Cursor(self.store)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _manifest(total=3):
    return routes.Manifest(
        file_id="file-att-stable",
        crypto_version="client_mvk_v2",
        manifest_ciphertext="AQID",
        total_bytes=total,
        chunk_size=1024,
        chunk_count=1,
    )


def test_same_vault_same_logical_manifest_is_one_authoritative_row(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(routes, "get_db", lambda: connection)
    monkeypatch.setattr(routes, "_enabled", lambda write=False: None)

    principal = {"vault_id": "vault-a"}
    first = routes.create_manifest(_manifest(), principal)
    second = routes.create_manifest(_manifest(), principal)

    assert first == second
    assert list(connection.store) == ["file-att-stable"]
    assert connection.commits == 2


@pytest.mark.parametrize(
    "principal,total",
    [({"vault_id": "vault-b"}, 3), ({"vault_id": "vault-a"}, 4)],
)
def test_collision_cannot_rebind_or_change_manifest(
    monkeypatch, principal, total
):
    connection = _Connection()
    monkeypatch.setattr(routes, "get_db", lambda: connection)
    monkeypatch.setattr(routes, "_enabled", lambda write=False: None)
    routes.create_manifest(_manifest(), {"vault_id": "vault-a"})

    with pytest.raises(HTTPException) as raised:
        routes.create_manifest(_manifest(total=total), principal)
    assert raised.value.status_code == 409
    assert len(connection.store) == 1
