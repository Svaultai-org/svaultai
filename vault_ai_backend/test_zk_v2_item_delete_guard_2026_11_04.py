"""A generic V2 delete must preserve a staged legacy item's active copy."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from routes import vault_ciphertext_write_routes as route


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.rowcount = 0
        self.result = None
        self.queries = []

    def execute(self, sql, params):
        query = " ".join(sql.lower().split())
        self.queries.append(query)
        assert params == (7, "owner-vault")
        record = self.rows.get((params[1], params[0]))
        if query.startswith("select encrypted_data is not null"):
            assert query.endswith("for update")
            self.result = None if record is None else (
                record["encrypted_data"] is not None,
            )
            return
        if query.startswith("delete from vault_items"):
            assert "and encrypted_data is null" in query
            if record is not None and record["encrypted_data"] is None:
                del self.rows[(params[1], params[0])]
                self.rowcount = 1
            else:
                self.rowcount = 0
            return
        raise AssertionError(f"Unexpected synthetic SQL: {query}")

    def fetchone(self):
        return self.result


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.cur = _Cursor(rows)
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


@pytest.mark.parametrize("staged", [False, True])
def test_generic_v2_delete_rejects_legacy_row(monkeypatch, staged):
    row = {
        "encrypted_data": b"synthetic-legacy-ciphertext",
        "payload_ciphertext": b"synthetic-v2-ciphertext" if staged else None,
    }
    db = _Db({("owner-vault", 7): row})
    monkeypatch.setattr(route, "get_db", lambda: db)

    with pytest.raises(HTTPException) as raised:
        route.delete_vault_item_ciphertext(7, {"vault_id": "owner-vault"})

    assert raised.value.status_code == 409
    assert raised.value.detail == "legacy_item_migration_required"
    assert db.rows[("owner-vault", 7)] is row
    assert not any(query.startswith("delete") for query in db.cur.queries)
    assert db.commits == 0
    assert db.rollbacks == 1


def test_generic_v2_delete_removes_only_owned_v2_row(monkeypatch):
    rows = {
        ("owner-vault", 7): {
            "encrypted_data": None,
            "payload_ciphertext": b"synthetic-v2-ciphertext",
        },
        ("other-vault", 7): {
            "encrypted_data": b"synthetic-other-ciphertext",
            "payload_ciphertext": None,
        },
    }
    db = _Db(rows)
    monkeypatch.setattr(route, "get_db", lambda: db)

    result = route.delete_vault_item_ciphertext(7, {"vault_id": "owner-vault"})

    assert result == {"status": "deleted", "item_id": 7}
    assert ("owner-vault", 7) not in rows
    assert ("other-vault", 7) in rows
    assert db.commits == 1
    assert db.rollbacks == 0


def test_generic_v2_delete_missing_item_is_404(monkeypatch):
    db = _Db({})
    monkeypatch.setattr(route, "get_db", lambda: db)

    with pytest.raises(HTTPException) as raised:
        route.delete_vault_item_ciphertext(7, {"vault_id": "owner-vault"})

    assert raised.value.status_code == 404
    assert db.commits == 0
    assert db.rollbacks == 1
