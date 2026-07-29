from __future__ import annotations

from pathlib import Path

import pytest

from vault_credential_draft import (
    _reset_store_for_test,
    get_draft,
    store_draft,
)
from vault_pending_credential_confirm import (
    discard_pending_credential,
    save_pending_credential,
)


def setup_function():
    _reset_store_for_test()


def test_yes_save_it_saves_persistent_draft_before_consuming():
    draft = store_draft(
        vault_id="vault-confirm-a",
        service_name="Facebook",
        username="user-a",
        password="password-a",
    )
    saved_calls = []

    def save_secret_tool(vault_id, payload, key, generated=False):
        saved_calls.append((vault_id, payload, key, generated))

    result = save_pending_credential(
        vault_id="vault-confirm-a",
        key=b"0" * 32,
        memory={},
        save_secret_tool=save_secret_tool,
        selection_hint={"kind": "generated_login_draft", "id": draft.draft_id},
    )

    assert result is not None
    assert result.action == "save"
    assert result.draft_id == draft.draft_id
    assert len(saved_calls) == 1
    assert saved_calls[0][1]["service"] == "Facebook"
    assert saved_calls[0][1]["fields"] == {
        "username": "user-a",
        "password": "password-a",
    }
    assert get_draft(vault_id="vault-confirm-a", draft_id=draft.draft_id) is None


def test_save_failure_keeps_persistent_draft_for_retry():
    draft = store_draft(
        vault_id="vault-confirm-a",
        service_name="Facebook",
        username="user-a",
        password="password-a",
    )

    def failing_save_secret_tool(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    with pytest.raises(RuntimeError):
        save_pending_credential(
            vault_id="vault-confirm-a",
            key=b"0" * 32,
            memory={},
            save_secret_tool=failing_save_secret_tool,
            selection_hint={
                "kind": "generated_login_draft",
                "id": draft.draft_id,
            },
        )

    assert get_draft(vault_id="vault-confirm-a", draft_id=draft.draft_id)


def test_cancel_consumes_selected_persistent_draft_only():
    first = store_draft(
        vault_id="vault-confirm-a",
        service_name="Facebook",
        username="user-a",
        password="password-a",
    )
    second = store_draft(
        vault_id="vault-confirm-a",
        service_name="Instagram",
        username="user-b",
        password="password-b",
    )

    result = discard_pending_credential(
        vault_id="vault-confirm-a",
        memory={},
        selection_hint={"kind": "generated_login_draft", "id": first.draft_id},
    )

    assert result is not None
    assert result.action == "cancel"
    assert get_draft(vault_id="vault-confirm-a", draft_id=first.draft_id) is None
    assert get_draft(vault_id="vault-confirm-a", draft_id=second.draft_id)


def test_chat_endpoint_checks_credentials_before_memory_router():
    src = Path("main.py").read_text(encoding="utf-8")
    cred_pos = src.index("save_pending_credential")
    memory_pos = src.index("handle_personal_memory_turn")
    assert cred_pos < memory_pos


def test_unscoped_save_it_prefers_live_credential_draft_over_memory_proposal():
    src = Path("main.py").read_text(encoding="utf-8")
    pending_pos = src.index("_pending_credential_exists")
    guard_pos = src.index("has_pending_memory_proposal")
    cred_branch_pos = src.index("save_pending_credential")
    memory_pos = src.index("handle_personal_memory_turn")
    assert pending_pos < guard_pos < cred_branch_pos < memory_pos
    assert "not _pending_credential_exists" in src
    assert "_selection_hint_is_generated_login" in src
