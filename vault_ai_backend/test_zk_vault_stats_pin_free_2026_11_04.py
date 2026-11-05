"""A trusted ZK session reads aggregate stats without supplying a PIN."""

import asyncio

import pytest
from fastapi import HTTPException

import billing
import main


class _Cursor:
    def __init__(self, *, zk: bool):
        self.zk = zk
        self.query = ""

    def execute(self, query, params):
        assert params == ("vault-1",)
        self.query = query

    def fetchone(self):
        if "FROM vaults" in self.query:
            return {"total_bytes": 123, "vault_handle": b"zk" if self.zk else None}
        if "FROM vault_items" in self.query:
            return {"login_count": 2, "card_count": 1, "id_count": 0}
        if "upload_status = 'complete'" in self.query:
            return {"file_count": 3}
        if "upload_status = 'uploading'" in self.query:
            return {"pending_bytes": 7}
        raise AssertionError("Unexpected stats query")


class _Connection:
    def __init__(self, *, zk: bool):
        self.cursor_value = _Cursor(zk=zk)
        self.closed = False

    def cursor(self, **_kwargs):
        return self.cursor_value

    def close(self):
        self.closed = True


def test_zk_stats_returns_counts_without_legacy_pin_verification(monkeypatch):
    conn = _Connection(zk=True)
    monkeypatch.setattr(main, "get_db", lambda: conn)
    monkeypatch.setattr(
        main, "verify_vault_pin",
        lambda *_args: (_ for _ in ()).throw(AssertionError("PIN path called")),
    )
    monkeypatch.setattr(billing, "get_account_id_for_vault", lambda _v: "acct")
    monkeypatch.setattr(billing, "get_effective_storage_limit", lambda _a: 1000)

    result = asyncio.run(main.zk_vault_stats_endpoint(principal={"vault_id": "vault-1"}))

    assert result["storage_used_bytes"] == 123
    assert result["file_count"] == 3
    assert result["storage_pending_bytes"] == 7
    assert conn.closed


def test_zk_stats_rejects_legacy_vault(monkeypatch):
    conn = _Connection(zk=False)
    monkeypatch.setattr(main, "get_db", lambda: conn)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.zk_vault_stats_endpoint(principal={"vault_id": "vault-1"}))
    assert error.value.status_code == 404
    assert conn.closed
