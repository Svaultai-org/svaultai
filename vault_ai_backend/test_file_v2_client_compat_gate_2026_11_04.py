"""Fail-closed login gate for vaults with client-only V2 files."""

from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://fixture.invalid/test")

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import auth_local
from file_v2_client_capability import (
    require_file_v2_reader_for_login,
    request_has_file_v2_reader,
)


VAULT = "11111111-1111-1111-1111-111111111111"


class _Cursor:
    def __init__(self, ready=True):
        self.ready = ready
        self.queries = []
        self.result = None

    def execute(self, sql, params):
        statement = " ".join(sql.lower().split())
        self.queries.append(statement)
        if statement.startswith("select vault_id from vaults"):
            self.result = {"vault_id": VAULT}
        elif statement.startswith("select 1 from file_v2_records"):
            self.result = (1,) if self.ready else None
        else:
            raise AssertionError(f"unexpected mutation/query: {statement}")

    def fetchone(self):
        return self.result


class _Connection:
    def __init__(self):
        self.cur = _Cursor()
        self.rollbacks = 0
        self.commits = 0

    def cursor(self, **_):
        return self.cur

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def test_old_client_login_is_rejected_before_revoking_current_session(monkeypatch):
    db = _Connection()
    monkeypatch.setattr(auth_local, "get_db", lambda: db)
    with pytest.raises(HTTPException) as raised:
        auth_local.issue_session_token(
            vault_id=VAULT, device_id="synthetic-old-device",
            client_label="Old iPhone", file_v2_reader_capable=False,
        )
    assert raised.value.status_code == 426
    assert raised.value.detail["code"] == "client_update_required"
    assert db.commits == 0 and db.rollbacks == 1
    assert not any("update auth_sessions" in sql or
                   "update trusted_devices" in sql or
                   "insert into auth_sessions" in sql for sql in db.cur.queries)
    assert db.cur.queries[0].startswith("select vault_id from vaults")
    assert db.cur.queries[1].startswith("select 1 from file_v2_records")


def test_capable_login_skips_compatibility_query():
    cur = _Cursor()
    require_file_v2_reader_for_login(cur, VAULT, capable=True)
    assert cur.queries == []


def test_old_client_can_still_login_before_any_new_v2_file_exists():
    cur = _Cursor(ready=False)
    require_file_v2_reader_for_login(cur, VAULT, capable=False)
    assert cur.queries == [
        "select 1 from file_v2_records where vault_id=%s "
        "and lifecycle_state='client_v2_ready' "
        "and verification_state='client_verified' limit 1"
    ]


def test_header_is_exact_and_old_builds_omit_it():
    def request(headers):
        return Request({"type": "http", "method": "POST", "path": "/",
                        "headers": headers})
    assert request_has_file_v2_reader(request([])) is False
    assert request_has_file_v2_reader(request([
        (b"x-svaultai-file-v2-reader", b"1")])) is True
    assert request_has_file_v2_reader(request([
        (b"x-svaultai-file-v2-reader", b"true")])) is False


def test_every_session_issuer_binds_reader_capability():
    root = Path(__file__).parent / "routes"
    for filename, expected in (("auth_routes.py", 1),
                               ("auth_zk_routes.py", 2)):
        tree = ast.parse((root / filename).read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "issue_session_token"]
        assert len(calls) == expected
        assert all(any(keyword.arg == "file_v2_reader_capable"
                       for keyword in call.keywords) for call in calls)


def test_browser_cors_allows_reader_capability_header():
    tree = ast.parse((Path(__file__).parent / "main.py").read_text())
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and
                           target.id == "CORS_ALLOWED_HEADERS"
                           for target in node.targets)]
    assert len(assignments) == 1
    assert "X-SVaultAI-File-V2-Reader" in ast.literal_eval(assignments[0].value)
