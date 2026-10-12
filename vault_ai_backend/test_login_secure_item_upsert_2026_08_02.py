from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from vault_core import derive_key, decrypt_message, KDF_TARGET_ITERATIONS

import routes.login_routes as login_routes
import vault_secure_item_save as secure_item_save


_KEY = derive_key(
    "1234",
    "dmF1bHRhaS1sb2dpbi11cHNlcnQ=",
    iterations=KDF_TARGET_ITERATIONS,
)


class _Cursor:
    def __init__(self, store: "_Store"):
        self.store = store
        self.last = None

    def execute(self, sql: str, params: tuple = ()):
        low = " ".join(sql.lower().split())
        if low.startswith("select id, service, item_type, encrypted_data"):
            self.last = None
            return
        if low.startswith("insert into vault_items"):
            self.store.upsert_payload = dict(zip(
                ("vault_id", "item_type", "service", "encrypted_data"), params))
            self.last = {"id": 42}
            return
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self.last

    def fetchall(self):
        return [] if self.last is None else [self.last]


class _Conn:
    def __init__(self, store: "_Store"):
        self.store = store

    def cursor(self, cursor_factory=None):
        return _Cursor(self.store)

    def commit(self):
        self.store.commits += 1

    def close(self):
        pass


class _Store:
    def __init__(self):
        self.upsert_payload = None
        self.commits = 0

    def get_db(self):
        return _Conn(self)


def test_update_secure_item_creates_missing_login_with_custom_fields(monkeypatch):
    store = _Store()
    monkeypatch.setattr(login_routes, "require_content_write", lambda *args: None)
    monkeypatch.setattr(login_routes, "get_db", store.get_db)
    monkeypatch.setattr(
        login_routes,
        "verify_vault_pin",
        lambda vault_id, pin: _KEY,
    )
    monkeypatch.setattr(
        secure_item_save,
        "_default_upsert",
        lambda payload: setattr(store, "upsert_payload", payload),
    )
    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(bump_vault_total_bytes=lambda vault_id, delta: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "vault_tool_result_cache",
        SimpleNamespace(invalidate_for_event=lambda **kwargs: None),
    )

    response = login_routes.update_secure_item(
        login_routes.UpdateSecureItemRequest(
            old_service="HBO Max",
            item_type="login",
            pin="1234",
            fields={
                "username": "test@gmail.com",
                "password": "generated-value",
                "url": "https://max.example",
                "Recovery Code": "RC-123",
            },
        ),
        principal={"vault_id": "vault-a"},
    )

    assert response["created"] is True
    assert response["id"] == 42
    assert store.commits == 1
    assert store.upsert_payload is not None
    assert store.upsert_payload["vault_id"] == "vault-a"
    assert store.upsert_payload["item_type"] == "login"
    assert store.upsert_payload["service"] == "HBO Max"

    decoded = json.loads(decrypt_message(
        store.upsert_payload["encrypted_data"], _KEY,
    ))
    assert decoded["category"] == "login"
    assert decoded["title"] == "HBO Max"
    assert isinstance(decoded["item_id"], str)
    assert decoded["fields"] == {
        "username": "test@gmail.com",
        "password": "generated-value",
        "url": "https://max.example",
        "Recovery Code": "RC-123",
    }


def test_route_insert_is_only_the_explicit_create_only_encryption_executor():
    from pathlib import Path

    src = Path("routes/login_routes.py").read_text(encoding="utf-8")
    assert src.count("INSERT INTO vault_items") == 1
    assert "db_executor=insert_only," in src
    assert "RETURNING id" in src
