"""Only bounded explicit edits may overwrite an existing opaque saved item."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes import vault_ciphertext_write_routes as route


def request(**extra):
    return route.VaultItemUpsertRequest(item_type_ciphertext="AQ", service_ciphertext="Ag",
                                       payload_ciphertext="Aw", **extra)


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", "true")
    cursor = Mock()
    cursor.rowcount = 1
    cursor.fetchone.return_value = {"id": 42}
    connection = Mock()
    connection.cursor.return_value = cursor
    lookup = Mock(return_value=connection)
    monkeypatch.setattr(route, "get_db", lookup)
    monkeypatch.setattr(route, "require_content_write", lambda *args: None)
    return lookup, connection, cursor


@pytest.mark.parametrize("body,status", [
    ({"item_id": 42}, 409),
    ({"item_id": 42, "mutation_intent": "create"}, 409),
    ({"mutation_intent": "edit"}, 400),
])
def test_unmarked_old_edit_or_inconsistent_intent_refused_before_db(database, body, status):
    lookup, connection, cursor = database
    with pytest.raises(HTTPException) as raised:
        route.vault_item_upsert_ciphertext(request(**body), principal={"vault_id": "synthetic"})
    assert raised.value.status_code == status
    if status == 409:
        assert raised.value.detail["code"] == "update_app_required"
    lookup.assert_not_called()
    connection.commit.assert_not_called()
    cursor.execute.assert_not_called()


@pytest.mark.parametrize("body", [{}, {"mutation_intent": "create"}])
def test_no_id_safe_create_never_uses_update(database, body):
    _, connection, cursor = database
    result = route.vault_item_upsert_ciphertext(request(**body), principal={"vault_id": "synthetic"})
    assert result.item_id == 42 and result.created is True
    assert cursor.execute.call_args.args[0].lstrip().startswith("INSERT")
    assert cursor.execute.call_args.args[1] == ("synthetic", b"\x01", b"\x02", b"\x03")
    connection.commit.assert_called_once()


def test_explicit_edit_is_exact_id_and_authenticated_vault_scoped(database):
    _, connection, cursor = database
    result = route.vault_item_upsert_ciphertext(request(item_id=42, mutation_intent="edit"),
                                                principal={"vault_id": "synthetic"})
    assert result.item_id == 42 and result.created is False
    assert cursor.execute.call_args.args[0].lstrip().startswith("UPDATE")
    assert cursor.execute.call_args.args[1][-2:] == (42, "synthetic")
    connection.commit.assert_called_once()


def test_explicit_edit_cannot_become_insert_when_id_is_foreign_or_deleted(database):
    _, connection, cursor = database
    cursor.rowcount = 0
    with pytest.raises(HTTPException) as raised:
        route.vault_item_upsert_ciphertext(request(item_id=42, mutation_intent="edit"),
                                            principal={"vault_id": "other-synthetic"})
    assert raised.value.status_code == 404
    assert len(cursor.execute.call_args_list) == 1
    assert cursor.execute.call_args.args[0].lstrip().startswith("UPDATE")
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()


@pytest.mark.parametrize("body", [{"mutation_intent": "upsert"}, {"mutation_intent": 1},
                                 {"item_id": 0, "mutation_intent": "edit"}])
def test_intent_and_item_identity_schema_is_closed(body):
    with pytest.raises(ValidationError):
        request(**body)


def test_rollout_default_allows_omitted_old_marker_but_not_explicit_create_edit_conflict(database, monkeypatch):
    lookup, connection, cursor = database
    monkeypatch.delenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", raising=False)
    result = route.vault_item_upsert_ciphertext(request(item_id=42),
                                                principal={"vault_id": "synthetic"})
    assert result.created is False
    assert cursor.execute.call_args.args[0].lstrip().startswith("UPDATE")
    lookup.reset_mock()
    with pytest.raises(HTTPException) as raised:
        route.vault_item_upsert_ciphertext(request(item_id=42, mutation_intent="create"),
                                            principal={"vault_id": "synthetic"})
    assert raised.value.status_code == 409
    lookup.assert_not_called()


def test_compatibility_mode_still_refuses_edit_without_an_id(database, monkeypatch):
    lookup, _, _ = database
    monkeypatch.setenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", "false")
    with pytest.raises(HTTPException) as raised:
        route.vault_item_upsert_ciphertext(request(mutation_intent="edit"),
                                            principal={"vault_id": "synthetic"})
    assert raised.value.status_code == 400
    lookup.assert_not_called()
