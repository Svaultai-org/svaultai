from __future__ import annotations

import pytest

from vault_credential_command import ACTION_CREATE, extract_credential_command
from vault_pending_credential_confirm import save_pending_credential


@pytest.mark.parametrize(
    "message",
    [
        "username john password abc123 is my instagram login",
        "my instagram username is john and password is abc123",
        "instagram login is john / abc123",
        "save instagram username john password abc123",
        "save my instagram login john and pass abc123",
    ],
)
def test_assertion_parses_exact_supplied_values_and_never_becomes_lookup(message):
    command = extract_credential_command(message)

    assert command.action == ACTION_CREATE
    assert command.service.lower() == "instagram"
    assert command.explicit_fields == {
        "username": "john",
        "password": "abc123",
    }


def test_supplied_values_survive_draft_confirmation_save_without_generation():
    command = extract_credential_command(
        "save my instagram login synthetic-user and pass synthetic-password"
    )
    memory = {
        "pending_login_draft": {
            "service": command.service,
            "username_options": [command.explicit_fields["username"]],
            "password": command.explicit_fields["password"],
            "explicit_username_supplied": True,
            "explicit_password_supplied": True,
        }
    }
    saved_calls = []

    def save_secret_tool(vault_id, payload, key, generated=False):
        saved_calls.append((vault_id, payload, key, generated))

    result = save_pending_credential(
        vault_id="synthetic-vault",
        key=b"0" * 32,
        memory=memory,
        save_secret_tool=save_secret_tool,
    )

    assert result is not None
    assert result.action == "save"
    assert len(saved_calls) == 1
    assert saved_calls[0][1]["service"].lower() == "instagram"
    assert saved_calls[0][1]["fields"] == {
        "username": "synthetic-user",
        "password": "synthetic-password",
    }
    assert saved_calls[0][3] is False
    assert "pending_login_draft" not in memory
