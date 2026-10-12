"""Synthetic route tests: titles never authorize a duplicate-row mutation."""
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.login_routes as routes
import vault_core
import vault_secure_item_save as saver
from vault_saved_item_chat_intent import SecureItemIntent, INTENT_RETRIEVE_SECURE_ITEM, INTENT_SAVE_SECURE_ITEM


class Store:
    def __init__(self):
        self.rows = [self.row(11, "vault-a", "First"), self.row(12, "vault-a", "Second")]
        self.mutations = []
        self.commits = 0

    @staticmethod
    def row(item_id, vault_id, password, title="Duplicate"):
        return dict(id=item_id, vault_id=vault_id, service=title, item_type="login",
                    encrypted_data=json.dumps({"fields": {"password": password}}), created_at=None)

    def cursor(self, cursor_factory=None):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


class Cursor:
    def __init__(self, store):
        self.store = store
        self.result = []

    def execute(self, sql, params=()):
        text = " ".join(sql.lower().split())
        if text.startswith("select"):
            rows = [r for r in self.store.rows if r["vault_id"] == params[0]]
            if "item_type not in" in text:
                rows = [r for r in rows if r["item_type"] not in params[1]]
            else:
                rows = [r for r in rows if r["item_type"] == params[1]]
                if "and id = %s" in text:
                    rows = [r for r in rows if r["id"] == params[2]]
                else:
                    rows = [r for r in rows if r["service"].lower() == params[2].lower()]
            self.result = rows[:1] if "limit 1" in text else rows[:2] if "limit 2" in text else rows
        elif text.startswith("delete"):
            self.store.mutations.append((text, params))
            item_type = params[1] if len(params) == 3 else "login"
            item_id = params[2] if len(params) == 3 else params[1]
            self.result = [r for r in self.store.rows if r["vault_id"] == params[0] and r["item_type"] == item_type and r["id"] == item_id]
            self.store.rows = [r for r in self.store.rows if r not in self.result]
        elif text.startswith("update"):
            self.store.mutations.append((text, params))
            row = next(r for r in self.store.rows if r["id"] == params[2])
            row.update(service=params[0], encrypted_data=params[1])
        elif text.startswith("insert"):
            self.store.mutations.append((text, params))
            row = self.store.row(99, params[0], "", params[2])
            row.update(item_type=params[1], encrypted_data=params[3])
            self.store.rows.append(row)
            self.result = [row]
        else:
            raise AssertionError("Unexpected synthetic SQL operation")

    def fetchone(self):
        return self.result[0] if self.result else None

    def fetchall(self):
        return self.result


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", "true")
    store = Store()
    monkeypatch.setattr(routes, "get_db", lambda: store)
    monkeypatch.setattr(routes, "verify_vault_pin", lambda *args: bytes(32))
    monkeypatch.setattr(routes, "require_content_write", lambda *args: None)
    monkeypatch.setattr(routes, "decrypt_message", lambda data, key: data)
    monkeypatch.setattr(routes, "encrypt_message", lambda data, key: data)
    monkeypatch.setattr(vault_core, "encrypt_message", lambda data, key: data)
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(get_db=lambda: store, bump_vault_total_bytes=lambda *args: None))
    monkeypatch.setattr(vault_core, "decrypt_message", lambda data, key: data)
    monkeypatch.setitem(sys.modules, "vault_tool_result_cache", SimpleNamespace(invalidate_for_event=lambda **kwargs: None))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.verify_trusted_device] = lambda: {"vault_id": "vault-a"}
    return store, TestClient(app)


def request(client, path, **extra):
    body = dict(service="Duplicate", item_type="login", pin="synthetic-only")
    if path == "/update-secure-item":
        body["old_service"] = body.pop("service")
        body["fields"] = {"password": "Changed"}
    return client.post(path, json={**body, **extra})


@pytest.mark.parametrize("path", ["/get-secure-item", "/update-secure-item", "/delete-secure-item"])
def test_ambiguous_title_fails_without_selecting_or_mutating(fixture, path):
    store, client = fixture
    response = request(client, path)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ambiguous_saved_item"
    assert not store.mutations and not store.commits
    assert len(store.rows) == 2


def test_list_preserves_duplicate_rows_with_distinct_ids(fixture):
    _, client = fixture
    items = client.post("/list-secure-items", json={"pin": "synthetic-only"}).json()["items"]
    assert [item["id"] for item in items] == [11, 12]
    assert all(item["service"] == "Duplicate" for item in items)
    assert all("encrypted_data" not in item and "fields" not in item for item in items)


def test_exact_id_get_edit_delete_affect_only_selected_row(fixture):
    store, client = fixture
    response = request(client, "/get-secure-item", item_id=12)
    assert response.json()["id"] == 12
    assert response.json()["fields"]["password"] == "Second"
    assert request(client, "/update-secure-item", item_id=12).status_code == 200
    assert json.loads(store.rows[0]["encrypted_data"])["fields"]["password"] == "First"
    assert json.loads(store.rows[1]["encrypted_data"])["fields"]["password"] == "Changed"
    response = request(client, "/delete-secure-item", item_id=12)
    assert response.json()["count"] == 1
    assert [r["id"] for r in store.rows] == [11]


@pytest.mark.parametrize("path", ["/get-secure-item", "/update-secure-item", "/delete-secure-item"])
def test_foreign_id_never_falls_back_to_title(fixture, path):
    store, client = fixture
    store.rows.append(store.row(13, "vault-b", "Foreign"))
    assert request(client, path, item_id=13).status_code == 404
    assert not store.mutations


def test_create_only_duplicate_warns_without_write(fixture):
    store, client = fixture
    response = request(client, "/update-secure-item", create_only=True)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_saved_item"
    assert not store.mutations and len(store.rows) == 2


def test_create_only_new_title_uses_insert_not_upsert(fixture):
    store, client = fixture
    response = request(client, "/update-secure-item", create_only=True, new_service="Different")
    assert response.status_code == 200
    assert response.json()["id"] == 99 and response.json()["created"] is True
    assert len(store.rows) == 3
    assert len(store.mutations) == 1 and store.mutations[0][0].startswith("insert")


@pytest.mark.parametrize("path", ["/get-secure-item", "/update-secure-item", "/delete-secure-item"])
def test_unique_title_old_request_stays_compatible(fixture, path):
    store, client = fixture
    store.rows.pop()
    response = request(client, path)
    if path == "/update-secure-item":
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "update_app_required"
        assert not store.mutations
    else:
        assert response.status_code == 200


def test_create_cannot_also_target_an_id(fixture):
    store, client = fixture
    assert request(client, "/update-secure-item", create_only=True, item_id=12).status_code == 400
    assert not store.mutations


@pytest.mark.parametrize("path", ["/get-login", "/delete-login"])
def test_old_login_endpoints_refuse_ambiguous_title(fixture, path):
    store, client = fixture
    assert request(client, path).status_code == 409
    assert not store.mutations


def test_old_login_endpoints_accept_selected_owned_id(fixture):
    store, client = fixture
    assert request(client, "/get-login", item_id=12).json()["id"] == 12
    assert request(client, "/delete-login", item_id=12).json()["count"] == 1
    assert [row["id"] for row in store.rows] == [11]


def test_legacy_secure_save_intent_warns_before_overwriting(fixture):
    store, _ = fixture
    before = list(store.rows)
    result = saver.save_secure_item_from_intent(
        vault_id="vault-a", key=bytes(32),
        intent=SecureItemIntent(intent=INTENT_SAVE_SECURE_ITEM, category="login",
                                title="Duplicate", field="password", value="changed-synthetic"),
    )
    assert result["band"] == saver.BAND_NEEDS_CLARIFICATION
    assert "different title" in result["message"]
    assert not store.mutations and store.rows == before


def test_legacy_secure_save_intent_new_title_still_inserts(fixture):
    store, _ = fixture
    result = saver.save_secure_item_from_intent(
        vault_id="vault-a", key=bytes(32),
        intent=SecureItemIntent(intent=INTENT_SAVE_SECURE_ITEM, category="login",
                                title="Different", field="password", value="changed-synthetic"),
    )
    assert result["band"] == saver.BAND_SAVED
    assert len(store.rows) == 3
    assert store.mutations[0][0].startswith("insert")


def test_natural_language_title_only_delete_never_deletes_duplicate_logins(fixture):
    store, _ = fixture
    with pytest.raises(saver.SavedItemTitleConflict):
        saver._default_delete({"vault_id": "vault-a", "item_type": "login", "service": "Duplicate"})
    assert not store.mutations and len(store.rows) == 2


def test_selected_result_card_id_deletes_only_that_login(fixture):
    store, _ = fixture
    assert saver._default_delete({"vault_id": "vault-a", "item_type": "login", "service": "Duplicate", "item_id": "12"}) == 1
    assert [row["id"] for row in store.rows] == [11]


def test_duplicate_results_keep_db_identity_and_exact_reveal(fixture):
    store, _ = fixture
    intent = SecureItemIntent(intent=INTENT_RETRIEVE_SECURE_ITEM, category="login", title="Duplicate")
    reader = lambda vault_id, category: store.rows if category == "login" else []
    result = saver.retrieve_secure_items_from_intent(vault_id="vault-a", key=bytes(32), intent=intent, db_reader=reader)
    assert result["count"] == 2
    assert '"item_id": "11"' in result["envelope"] or '"item_id":"11"' in result["envelope"]
    selected = saver.retrieve_secure_items_from_intent(vault_id="vault-a", key=bytes(32), intent=intent,
                                                     db_reader=reader, reveal=True, exact_item_id="12")
    assert selected["count"] == 1
    assert "Second" in selected["envelope"] and "First" not in selected["envelope"]


def test_legacy_unique_title_edit_is_temporarily_compatible_when_strict_flag_off(fixture, monkeypatch):
    store, client = fixture
    monkeypatch.setenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", "false")
    store.rows.pop()
    assert request(client, "/update-secure-item").status_code == 200
    assert len(store.mutations) == 1


def test_legacy_ambiguous_title_edit_still_refused_when_strict_flag_off(fixture, monkeypatch):
    store, client = fixture
    monkeypatch.setenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", "false")
    assert request(client, "/update-secure-item").status_code == 409
    assert not store.mutations
