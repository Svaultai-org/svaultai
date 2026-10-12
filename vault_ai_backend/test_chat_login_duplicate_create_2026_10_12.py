"""Actual legacy chat save primitive must refuse duplicate credential titles."""
from pathlib import Path
from unittest.mock import Mock

import pytest
import main


@pytest.mark.parametrize("item_type", ["login", "credential"])
def test_chat_save_never_encrypts_merges_or_updates_an_existing_title(monkeypatch, item_type):
    cursor = Mock()
    cursor.fetchone.return_value = {"id": 11, "encrypted_data": "original-opaque-record"}
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(main, "ensure_vault_exists", lambda *args: None)
    monkeypatch.setattr(main, "get_db", lambda: connection)
    encrypt = Mock(side_effect=AssertionError("Duplicate cannot reach encryption"))
    decrypt = Mock(side_effect=AssertionError("Duplicate cannot reach field merge"))
    monkeypatch.setattr(main, "encrypt_message", encrypt)
    monkeypatch.setattr(main, "decrypt_message", decrypt)
    with pytest.raises(main.SaveSecretDuplicateTitleError) as raised:
        main.save_secret_tool("synthetic-vault", {
            "secret_type": item_type, "service": "Duplicate",
            "fields": {"username": "synthetic", "password": "synthetic-only"},
        }, bytes(32))
    assert raised.value.reason == "duplicate_saved_item"
    assert len(cursor.execute.call_args_list) == 1
    assert cursor.execute.call_args.args[0].lstrip().startswith("SELECT")
    encrypt.assert_not_called()
    decrypt.assert_not_called()
    connection.commit.assert_not_called()
    connection.close.assert_called_once()


def test_direct_chat_duplicate_has_clear_warning_and_adapter_cannot_mark_success():
    source = Path("main.py").read_text()
    branch = source[source.index('if intent == "save_login":'):]
    assert "except SaveSecretDuplicateTitleError:" in branch
    assert "select the existing login in Logins to edit it." in branch
    adapter = Path("vault_chat_executor_adapters_v2.py").read_text()
    guard = adapter[adapter.index('if getattr(exc, "reason", None) == "duplicate_saved_item":'):]
    guard = guard[:guard.index('logger.exception(')]
    assert "RESULT_VALIDATION_FAILED" in guard and "raise ExecutorError" in guard
    assert "consume_draft" not in guard and "_ok(" not in guard


def test_tool_payload_cannot_opt_itself_into_an_existing_item_edit(monkeypatch):
    cursor = Mock()
    cursor.fetchone.return_value = {"id": 11, "encrypted_data": "opaque"}
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(main, "ensure_vault_exists", lambda *args: None)
    monkeypatch.setattr(main, "get_db", lambda: connection)
    with pytest.raises(main.SaveSecretDuplicateTitleError):
        main.save_secret_tool("synthetic", {
            "secret_type": "login", "service": "Duplicate",
            "fields": {"password": "synthetic-only"},
            "update_existing": True,
        }, bytes(32))
    connection.commit.assert_not_called()


def test_ambiguous_legacy_retrieval_returns_choice_not_first_secret(monkeypatch):
    cursor = Mock()
    cursor.fetchone.return_value = {"id": 11, "encrypted_data": "opaque", "matching_count": 2}
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(main, "get_db", lambda: connection)
    decrypt = Mock(side_effect=AssertionError("Ambiguity cannot reveal an arbitrary item"))
    monkeypatch.setattr(main, "decrypt_message", decrypt)
    result = main.retrieve_secret_tool("synthetic", {"service": "Duplicate"}, bytes(32))
    assert "select the specific item" in result
    decrypt.assert_not_called()


def test_legacy_chat_delete_refuses_duplicates_before_mutation():
    from fastapi import HTTPException
    cursor = Mock()
    cursor.fetchall.return_value = [{"id": 11}, {"id": 12}]
    with pytest.raises(HTTPException) as raised:
        main._delete_unique_login_row(cursor, "synthetic", "Duplicate")
    assert raised.value.status_code == 409
    assert len(cursor.execute.call_args_list) == 1
    assert cursor.execute.call_args.args[0].lstrip().startswith("SELECT")
