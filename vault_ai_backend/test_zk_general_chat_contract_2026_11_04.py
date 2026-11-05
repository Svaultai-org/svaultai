"""Offline route tests for the separate PIN-free general-chat slice."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def chat_harness():
    from routes import zk_general_chat_routes as chat

    app = FastAPI()
    app.include_router(chat.router)
    app.dependency_overrides[chat.verify_trusted_device] = lambda: {
        "vault_id": "11111111-1111-1111-1111-111111111111",
        "token_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    }
    with (
        mock.patch.object(chat, "enforce_chat_rate_limit") as limit,
        mock.patch.object(chat, "chat_complete_with_fallback",
                          new_callable=mock.AsyncMock) as complete,
    ):
        complete.return_value = SimpleNamespace(content="A useful general answer")
        with TestClient(app, raise_server_exceptions=False) as client:
            yield chat, client, limit, complete


def test_route_disabled_by_default(chat_harness):
    chat, client, limit, complete = chat_harness
    with mock.patch.dict("os.environ", {"VAULTAI_ZK_GENERAL_CHAT_ENABLED": "false"}):
        response = client.post("/chat/zk/general", json={"message": "Hello"})
    assert response.status_code == 404
    limit.assert_not_called()
    complete.assert_not_awaited()


def test_general_followup_uses_only_user_authored_history(chat_harness):
    chat, client, limit, complete = chat_harness
    body = {
        "message": "Could you explain the second point?",
        "history": [
            {"role": "user", "content": "How does two-factor authentication work?"},
            {"role": "assistant", "content": "It adds a second check."},
        ],
    }
    with mock.patch.dict("os.environ", {"VAULTAI_ZK_GENERAL_CHAT_ENABLED": "true"}):
        response = client.post("/chat/zk/general", json=body)
    assert response.status_code == 200, response.text
    assert response.json() == {"reply": "A useful general answer", "mode": "general"}
    messages = complete.await_args.kwargs["messages"]
    assert [message["role"] for message in messages] == [
        "system", "user", "assistant", "user",
    ]
    assert messages[-1]["content"] == body["message"]
    assert "pin" not in body
    assert "vault_items" not in body
    limit.assert_called_once()


@pytest.mark.parametrize("extra", [
    {"pin": "123456"},
    {"vault_key": "synthetic-secret"},
    {"saved_items": [{"title": "private"}]},
    {"encrypted_message": "synthetic-ciphertext"},
])
def test_private_fields_are_rejected(chat_harness, extra):
    chat, client, limit, complete = chat_harness
    with mock.patch.dict("os.environ", {"VAULTAI_ZK_GENERAL_CHAT_ENABLED": "true"}):
        response = client.post("/chat/zk/general", json={"message": "Hello", **extra})
    assert response.status_code == 422
    complete.assert_not_awaited()


def test_provider_failure_is_generic_and_contains_no_prompt(chat_harness):
    chat, client, limit, complete = chat_harness
    complete.side_effect = RuntimeError("synthetic provider detail")
    with mock.patch.dict("os.environ", {"VAULTAI_ZK_GENERAL_CHAT_ENABLED": "true"}):
        response = client.post("/chat/zk/general", json={"message": "private canary"})
    assert response.status_code == 503
    assert "private canary" not in response.text
    assert "synthetic provider detail" not in response.text


def test_history_cannot_smuggle_pin_or_exceed_bound(chat_harness):
    chat, client, limit, complete = chat_harness
    with mock.patch.dict("os.environ", {"VAULTAI_ZK_GENERAL_CHAT_ENABLED": "true"}):
        smuggled = client.post("/chat/zk/general", json={
            "message": "Hello", "history": [
                {"role": "user", "content": "Earlier", "pin": "123456"},
            ],
        })
        oversized = client.post("/chat/zk/general", json={
            "message": "Hello",
            "history": [{"role": "user", "content": "Earlier"}] * 13,
        })
    assert smuggled.status_code == 422
    assert oversized.status_code == 422
    complete.assert_not_awaited()
