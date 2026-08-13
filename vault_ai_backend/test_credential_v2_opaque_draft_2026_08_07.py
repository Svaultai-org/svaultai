"""Server-side generated-login staging never persists v2 secret fields."""

import json

import vault_credential_draft as drafts
from vault_chat_state_store import compose_key, get_chat_state_backend


def test_opaque_draft_keeps_values_only_in_response_object():
    drafts._reset_store_for_test()
    returned = drafts.store_draft(
        vault_id="opaque-vault",
        service_name="Example",
        username="user@example.test",
        password="generated-secret",
        opaque_server_storage=True,
        ttl_seconds=600,
    )
    assert returned.username == "user@example.test"
    assert returned.password == "generated-secret"

    backend = get_chat_state_backend()
    key = compose_key(
        bucket="cred_draft", vault_id="opaque-vault", sub=returned.draft_id,
    )
    raw = backend.get(key)
    assert raw is not None
    payload = json.loads(raw.decode("utf-8"))
    assert payload["opaque_server_storage"] is True
    for forbidden in (
        "username", "password", "url", "notes", "totp", "custom_fields",
        "pin", "mvk", "content_key", "recovery_secret",
    ):
        assert forbidden not in payload

    stored = drafts.get_draft(vault_id="opaque-vault", draft_id=returned.draft_id)
    assert stored is not None
    assert stored.username == ""
    assert stored.password == ""
