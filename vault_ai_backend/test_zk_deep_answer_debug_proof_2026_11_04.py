"""Synthetic PIN-free debug snapshot authorization; scanning still needs its key."""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest
from fastapi import HTTPException

import vault_core
import vault_deep_answer
from routes import auth_zk_routes, deep_answer_routes as routes


PRINCIPAL = {
    "vault_id": "synthetic-vault",
    "token_id": "synthetic-session",
    "device_id": "synthetic-trusted-device",
}


@pytest.fixture
def debug_fixtures(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_DEEP_ANSWER_DEBUG_PROOF_ENABLED", "true")
    monkeypatch.setattr(vault_core, "is_vault_zk_adopted", lambda *_: True)
    verify_pin = mock.Mock()
    consume = mock.Mock()
    get_job = mock.Mock(return_value=object())
    snapshot = mock.Mock(return_value={"status": "scanning"})
    monkeypatch.setattr(vault_core, "verify_vault_pin", verify_pin)
    monkeypatch.setattr(auth_zk_routes, "consume_recent_zk_proof", consume)
    monkeypatch.setattr(vault_deep_answer, "get_job", get_job)
    monkeypatch.setattr(vault_deep_answer, "debug_job_snapshot", snapshot)
    return verify_pin, consume, get_job, snapshot


def test_debug_uses_one_time_opaque_proof_without_legacy_key(debug_fixtures):
    verify_pin, consume, get_job, snapshot = debug_fixtures
    payload = routes._DeepAnswerDebugRequest(zk_proof_token="synthetic-proof")
    assert payload.pin is None
    assert asyncio.run(routes.deep_answer_debug(
        "synthetic-job", payload, PRINCIPAL,
    )) == {"status": "scanning"}
    consume.assert_called_once_with("synthetic-proof", PRINCIPAL)
    verify_pin.assert_not_called()
    get_job.assert_called_once_with(PRINCIPAL["vault_id"], "synthetic-job")
    snapshot.assert_called_once()


@pytest.mark.parametrize("pin,proof,detail", [
    ("synthetic-pin", None, "zk_client_update_required"),
    (None, None, "zk_proof_token_required"),
])
def test_debug_rejects_raw_pin_or_missing_proof_before_lookup(
    debug_fixtures, pin, proof, detail,
):
    verify_pin, consume, get_job, _ = debug_fixtures
    payload = routes._DeepAnswerDebugRequest(pin=pin, zk_proof_token=proof)
    with pytest.raises(HTTPException) as denied:
        asyncio.run(routes.deep_answer_debug("synthetic-job", payload, PRINCIPAL))
    assert denied.value.detail == detail
    verify_pin.assert_not_called()
    consume.assert_not_called()
    get_job.assert_not_called()


def test_flag_off_and_legacy_debug_keep_pin_recheck(monkeypatch, debug_fixtures):
    verify_pin, consume, _, _ = debug_fixtures
    monkeypatch.setenv("VAULTAI_ZK_DEEP_ANSWER_DEBUG_PROOF_ENABLED", "false")
    payload = routes._DeepAnswerDebugRequest(pin="synthetic-pin")
    asyncio.run(routes.deep_answer_debug("synthetic-job", payload, PRINCIPAL))
    verify_pin.assert_called_once_with(PRINCIPAL["vault_id"], "synthetic-pin")
    consume.assert_not_called()

    verify_pin.reset_mock()
    monkeypatch.setenv("VAULTAI_ZK_DEEP_ANSWER_DEBUG_PROOF_ENABLED", "true")
    monkeypatch.setattr(vault_core, "is_vault_zk_adopted", lambda *_: False)
    asyncio.run(routes.deep_answer_debug("synthetic-job", payload, PRINCIPAL))
    verify_pin.assert_called_once_with(PRINCIPAL["vault_id"], "synthetic-pin")
    consume.assert_not_called()


def test_scanning_models_still_require_pin():
    with pytest.raises(Exception):
        routes._DeepAnswerStartRequest(intent="search_files_for_credentials")
    with pytest.raises(Exception):
        routes._DeepAnswerPollRequest()
