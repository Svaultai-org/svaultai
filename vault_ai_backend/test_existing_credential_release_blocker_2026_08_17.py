from __future__ import annotations

import json

import pytest

import vault_credential_draft as drafts
from vault_chat_deterministic_router import (
    KIND_CREDENTIAL_DRAFT,
    try_route_deterministically,
)
from vault_credential_command import (
    ACTION_CREATE,
    extract_credential_command,
)
from vault_pending_credential_confirm import save_pending_credential
from vault_pending_draft_confirm import pending_draft_confirm_service


VAULT_ID = "synthetic-existing-credential-vault"
KEY = b"7" * 32
USERNAME = "synthetic-existing-user"
PASSWORD = "SyntheticExistingPass-2727"


@pytest.fixture(autouse=True)
def reset_drafts(monkeypatch):
    monkeypatch.setenv("VAULTAI_CHAT_STATE_BACKEND", "memory")
    drafts._reset_store_for_test()
    yield
    drafts._reset_store_for_test()


@pytest.mark.parametrize(
    "message",
    [
        f"save my instagram login username {USERNAME} and password {PASSWORD}",
        f"my instagram username is {USERNAME} and password is {PASSWORD}",
        f"instagram is username {USERNAME} and password {PASSWORD}",
        f"username {USERNAME} password {PASSWORD} is my instagram login",
        f"remember my instagram login, username {USERNAME}, password {PASSWORD}",
    ],
)
def test_existing_single_turn_creates_exact_non_generated_draft(message):
    command = extract_credential_command(message)
    assert command.action == ACTION_CREATE
    assert command.service.lower() == "instagram"
    assert command.explicit_fields == {
        "username": USERNAME,
        "password": PASSWORD,
    }

    planner_calls = []
    drafter_calls = []

    def drafter(**kwargs):
        drafter_calls.append(dict(kwargs))
        draft = drafts.store_draft(
            vault_id=kwargs["vault_id"],
            service_name=kwargs["service_name"],
            username=kwargs["username"],
            password=kwargs["password"],
            generated=False,
        )
        payload = draft.to_public_dict()
        payload["explicit_fields"] = ["username", "password"]
        return json.dumps(payload)

    outcome = try_route_deterministically(
        vault_id=VAULT_ID,
        session_id="synthetic-session",
        key=KEY,
        decrypted_message=message,
        files_lister=lambda: planner_calls.append("files") or [],
        credential_drafter=drafter,
        active_entity_getter=lambda *args, **kwargs: None,
        active_entity_setter=lambda *args, **kwargs: True,
        chat_request_id="synthetic-request",
    )

    assert outcome is not None
    assert outcome.kind == KIND_CREDENTIAL_DRAFT
    assert planner_calls == []
    assert len(drafter_calls) == 1
    assert drafter_calls[0]["service_name"].lower() == "instagram"
    assert drafter_calls[0]["username"] == USERNAME
    assert drafter_calls[0]["password"] == PASSWORD
    stored = drafts.get_draft(vault_id=VAULT_ID, service_name="instagram")
    assert stored is not None
    assert stored.username == USERNAME
    assert stored.password == PASSWORD
    assert stored.generated is False


@pytest.mark.parametrize(
    "follow_up",
    ["save it", "save my instagram login"],
)
def test_existing_multi_turn_save_preserves_values_and_provenance(follow_up):
    draft = drafts.store_draft(
        vault_id=VAULT_ID,
        service_name="instagram",
        username=USERNAME,
        password=PASSWORD,
        generated=False,
    )
    if follow_up != "save it":
        assert pending_draft_confirm_service(follow_up) == "instagram"

    saved = []

    def saver(vault_id, payload, key, generated=False):
        saved.append((vault_id, payload, key, generated))

    result = save_pending_credential(
        vault_id=VAULT_ID,
        key=KEY,
        memory={},
        save_secret_tool=saver,
        selection_hint={
            "kind": "generated_login_draft",
            "id": draft.draft_id,
        },
    )

    assert result is not None
    assert len(saved) == 1
    assert saved[0][1] == {
        "secret_type": "login",
        "service": "instagram",
        "fields": {"password": PASSWORD, "username": USERNAME},
    }
    assert saved[0][3] is False
    assert drafts.get_draft(vault_id=VAULT_ID, draft_id=draft.draft_id) is None


def test_service_scoped_save_cannot_consume_a_different_pending_draft():
    drafts.store_draft(
        vault_id=VAULT_ID,
        service_name="github",
        username=USERNAME,
        password=PASSWORD,
        generated=False,
    )
    assert pending_draft_confirm_service("save my instagram login") == "instagram"
    assert drafts.get_draft(vault_id=VAULT_ID, service_name="instagram") is None


def test_service_scoped_save_without_draft_never_generates_replacement_values():
    drafter_calls = []
    outcome = try_route_deterministically(
        vault_id=VAULT_ID,
        session_id="synthetic-session",
        key=KEY,
        decrypted_message="save my instagram login",
        files_lister=lambda: [],
        credential_drafter=lambda **kwargs: drafter_calls.append(kwargs),
        active_entity_getter=lambda *args, **kwargs: None,
        active_entity_setter=lambda *args, **kwargs: True,
        chat_request_id="synthetic-request",
    )

    assert outcome is None
    assert drafter_calls == []


@pytest.mark.parametrize(
    "message",
    [
        "generate me an instagram login",
        "create me a new instagram login",
    ],
)
def test_explicit_generation_requests_still_generate(message):
    drafter_calls = []

    def drafter(**kwargs):
        drafter_calls.append(dict(kwargs))
        draft = drafts.store_draft(
            vault_id=kwargs["vault_id"],
            service_name=kwargs["service_name"],
            username="generated-synthetic-user",
            password="GeneratedSyntheticPass-8844",
            generated=True,
        )
        payload = draft.to_public_dict()
        payload["explicit_fields"] = []
        return json.dumps(payload)

    outcome = try_route_deterministically(
        vault_id=VAULT_ID,
        session_id="synthetic-session",
        key=KEY,
        decrypted_message=message,
        files_lister=lambda: [],
        credential_drafter=drafter,
        active_entity_getter=lambda *args, **kwargs: None,
        active_entity_setter=lambda *args, **kwargs: True,
        chat_request_id="synthetic-request",
    )

    assert outcome is not None
    assert outcome.kind == KIND_CREDENTIAL_DRAFT
    assert len(drafter_calls) == 1
    assert drafter_calls[0]["username"] is None
    assert drafter_calls[0]["password"] is None
    stored = drafts.get_draft(vault_id=VAULT_ID, service_name="instagram")
    assert stored is not None
    assert stored.generated is True
