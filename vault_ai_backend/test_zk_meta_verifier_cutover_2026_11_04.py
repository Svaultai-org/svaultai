"""The metadata endpoint must not recreate an offline PIN oracle for ZK vaults.

This uses synthetic rows and a recording DB seam; it never opens a real DB.
"""

from __future__ import annotations

import asyncio
from unittest import mock


_VAULT_ID = "11111111-1111-1111-1111-111111111111"


class _Cursor:
    def __init__(self, row):
        self.row = dict(row)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.cursor_value = _Cursor(row)
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _invoke(row, pin="123456"):
    import main

    conn = _Conn(row)
    with (
        mock.patch.object(main, "get_db", return_value=conn),
        mock.patch.object(main, "get_or_create_pin_salt", return_value="synthetic-salt"),
        mock.patch.object(main, "create_pin_verifier", return_value="synthetic-verifier") as create,
    ):
        result = asyncio.run(main.get_or_create_vault_meta_endpoint(
            request=None,
            payload=main.VaultMetaRequest(vault_name="", pin=pin),
            principal={"vault_id": _VAULT_ID},
        ))
    return result, conn, create


def _row(vault_handle):
    return {
        "vault_id": _VAULT_ID,
        "pin_salt": "synthetic-salt",
        "pin_verifier": "",
        "vault_handle": vault_handle,
        "total_bytes": 0,
        "created_at": None,
        "kdf_iterations": 600000,
    }


def test_zk_metadata_never_recreates_verifier_even_with_pin():
    result, conn, create = _invoke(_row(b"synthetic-zk-handle"))
    assert result["vault_id"] == _VAULT_ID
    create.assert_not_called()
    assert conn.commits == 0
    assert not any("UPDATE vaults" in sql for sql, _ in conn.cursor_value.calls)


def test_legacy_blank_verifier_still_initializes():
    result, conn, create = _invoke(_row(None))
    assert result["vault_id"] == _VAULT_ID
    create.assert_called_once_with("123456", "synthetic-salt", 600000)
    assert conn.commits == 1
    writes = [(sql, params) for sql, params in conn.cursor_value.calls
              if "UPDATE vaults" in sql]
    assert len(writes) == 1
    assert writes[0][1] == ("synthetic-verifier", _VAULT_ID)
