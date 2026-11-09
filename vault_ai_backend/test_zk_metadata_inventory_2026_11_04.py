"""Synthetic PIN-free ZK metadata inventory contracts; no real vault data."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_local import PIN_FREE_FILE_LIST_OFFER
from routes import auth_zk_routes, zk_metadata_inventory_routes as inventory


VAULT = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
CREATED = datetime(2026, 11, 4, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.rows = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.lower().split())
        self.db.queries.append(normalized)
        if normalized.startswith("set transaction isolation level"):
            return
        vault_id, after, count = params
        assert vault_id == self.db.principal["vault_id"]
        if "from vault_items" in normalized:
            self.rows = [row for row in self.db.items
                         if row["id"] > after and vault_id == VAULT][:count]
        elif "from uploaded_files u" in normalized:
            self.rows = [row for row in self.db.files
                         if row["id"] > after and vault_id == VAULT][:count]
        else:
            raise AssertionError(f"unexpected SQL: {normalized}")

    def fetchall(self):
        return self.rows


class _Db:
    def __init__(self):
        self.principal = {"vault_id": VAULT, "token_id": "synthetic"}
        self.queries = []
        self.items = [
            {"id": 1, "item_type": "login", "service": "example",
             "item_type_ciphertext": None, "service_ciphertext": None,
             "is_legacy": True, "has_v2_payload": False,
             "created_at": CREATED},
            {"id": 2, "item_type": "hidden-legacy-label",
             "service": "hidden-legacy-service",
             "item_type_ciphertext": b"type-ciphertext",
             "service_ciphertext": b"service-ciphertext",
             "is_legacy": True, "has_v2_payload": True,
             "created_at": CREATED},
        ]
        self.files = [
            {"id": "file-a", "file_size": 4, "storage_mode": "inline",
             "upload_status": "complete", "file_name_ciphertext": b"name-ct",
             "saved_name_ciphertext": None,
             "content_type_ciphertext": b"mime-ct",
             "detected_type_ciphertext": None,
             "detected_service_ciphertext": None,
             "asset_type_ciphertext": None,
             "has_inline_ciphertext": True, "created_at": CREATED,
             "lifecycle_state": None, "verification_state": None},
            {"id": "file-b", "file_size": 7, "storage_mode": "inline",
             "upload_status": "complete", "file_name_ciphertext": b"name-ct-b",
             "saved_name_ciphertext": None,
             "content_type_ciphertext": b"mime-ct-b",
             "detected_type_ciphertext": None,
             "detected_service_ciphertext": None,
             "asset_type_ciphertext": None,
             "has_inline_ciphertext": False, "created_at": CREATED,
             "lifecycle_state": "legacy_migration_retired",
             "verification_state": "client_verified"},
        ]

    def cursor(self, cursor_factory=None):
        return _Cursor(self)

    def close(self):
        pass


def _client(monkeypatch, *, enabled=True):
    db = _Db()
    monkeypatch.setenv(
        "VAULTAI_ZK_METADATA_INVENTORY_ENABLED",
        "true" if enabled else "false",
    )
    monkeypatch.setattr(inventory, "get_db", lambda: db)
    monkeypatch.setattr(inventory, "is_vault_zk_adopted", lambda vault_id: vault_id == VAULT)
    app = FastAPI()
    app.include_router(inventory.router)
    app.dependency_overrides[inventory.verify_trusted_device] = lambda: db.principal
    return TestClient(app), db


def test_item_inventory_pages_without_values_or_legacy_ciphertext(monkeypatch):
    client, db = _client(monkeypatch)
    first = client.get("/vault/items/metadata?limit=1")
    assert first.status_code == 200, first.text
    assert first.json()["has_more"] is True
    assert first.json()["next_after_item_id"] == 1
    assert first.json()["records"][0]["item_type"] == "login"
    second = client.get("/vault/items/metadata?limit=1&after_item_id=1")
    assert second.status_code == 200, second.text
    record = second.json()["records"][0]
    assert record["item_id"] == 2
    assert record["item_type"] is None
    assert record["service"] is None
    assert record["item_type_ciphertext"]
    assert record["has_v2_payload"] is True
    assert "encrypted_data" not in second.text
    assert "hidden-legacy" not in second.text
    assert all("select id, item_type, service" in query for query in db.queries)


def test_file_inventory_includes_retired_marker_without_plaintext(monkeypatch):
    client, db = _client(monkeypatch)
    response = client.get("/vault/files/metadata?limit=2")
    assert response.status_code == 200, response.text
    records = response.json()["records"]
    assert len(records) == 2
    assert records[1]["lifecycle_state"] == "legacy_migration_retired"
    assert records[1]["has_inline_ciphertext"] is False
    assert records[1]["created_at"]
    assert records[0]["file_name_ciphertext"]
    for forbidden in ("encrypted_file_data", "file_name\"", "content_type\""):
        assert forbidden not in response.text


def test_file_inventory_exposes_chunk_shape_for_local_readback(monkeypatch):
    client, db = _client(monkeypatch)
    db.files.append({
        **db.files[0], "id": "file-c", "file_size": 7,
        "storage_mode": "chunks", "chunk_size": 4, "chunk_count": 2,
        "has_inline_ciphertext": False,
    })
    response = client.get("/vault/files/metadata?limit=3")
    assert response.status_code == 200, response.text
    records = response.json()["records"]
    assert records[0]["chunk_size"] is None
    assert records[0]["chunk_count"] is None
    assert records[2]["file_id"] == "file-c"
    assert (records[2]["chunk_size"], records[2]["chunk_count"]) == (4, 2)
    assert any("u.chunk_size" in query and "u.chunk_count" in query
               for query in db.queries)
    assert "encrypted_file_data" not in response.text


def test_offered_file_list_rechecks_after_another_device_changes_files(monkeypatch):
    client, db = _client(monkeypatch)
    monkeypatch.setattr(
        auth_zk_routes, "_pin_free_legacy_file_list_ready",
        lambda _conn, _vault_id, **_kwargs: False,
    )
    blocked = client.get(
        "/vault/files/metadata?require_legacy_complete=true",
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "legacy_file_list_changed"
    assert not any("from uploaded_files u" in query for query in db.queries)
    db.queries.clear()
    monkeypatch.setattr(
        auth_zk_routes, "_pin_free_legacy_file_list_ready",
        lambda _conn, _vault_id, **_kwargs: True,
    )
    current = client.get(
        "/vault/files/metadata?require_legacy_complete=true",
    )
    assert current.status_code == 200
    assert len(current.json()["records"]) == 2


def test_mixed_v2_recheck_requires_signed_reader_and_live_route(monkeypatch):
    client, db = _client(monkeypatch)
    checked = []
    monkeypatch.setattr(
        auth_zk_routes, "_pin_free_legacy_file_list_ready",
        lambda _conn, _vault_id, **kwargs:
            checked.append(kwargs["allow_ready_v2"]) or True,
    )
    monkeypatch.setattr(
        auth_zk_routes, "pin_free_v2_file_reader_enabled", lambda: True,
    )
    route = "/vault/files/metadata?require_legacy_complete=true"
    db.principal["file_v2_reader_capable"] = True
    db.principal["pin_free_read_offers"] = PIN_FREE_FILE_LIST_OFFER
    assert client.get(route).status_code == 200
    assert checked[-1] is True
    db.principal["file_v2_reader_capable"] = False
    assert client.get(route).status_code == 200
    assert checked[-1] is False
    db.principal["file_v2_reader_capable"] = True
    monkeypatch.setattr(
        auth_zk_routes, "pin_free_v2_file_reader_enabled", lambda: False,
    )
    monkeypatch.setattr(
        auth_zk_routes, "_pin_free_legacy_file_list_ready",
        lambda _conn, _vault_id, **kwargs:
            checked.append(kwargs["allow_ready_v2"]) or True,
    )
    assert client.get(route).status_code == 200
    assert checked[-1] is False


def test_inventory_flag_and_vault_guard_fail_closed(monkeypatch):
    client, db = _client(monkeypatch, enabled=False)
    assert client.get("/vault/items/metadata").status_code == 404
    assert not db.queries
    monkeypatch.setenv("VAULTAI_ZK_METADATA_INVENTORY_ENABLED", "true")
    db.principal = {"vault_id": OTHER, "token_id": "other"}
    assert client.get("/vault/files/metadata").status_code == 409
    assert not db.queries
    db.principal = {"vault_id": VAULT, "token_id": "synthetic"}
    assert client.get("/vault/files/metadata?limit=101").status_code == 422
