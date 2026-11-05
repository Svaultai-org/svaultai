"""Synthetic authorization checks for import bookkeeping; no real content or DB."""

from __future__ import annotations

import asyncio
from unittest import mock

import pytest
from fastapi import HTTPException

import main
import vault_core
from device_gate import verify_trusted_device
from routes import import_batch_routes as routes


PRINCIPAL = {
    "vault_id": "synthetic-vault",
    "token_id": "synthetic-session",
    "device_id": "synthetic-trusted-device",
}


@pytest.fixture
def zk_import_gate(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_IMPORT_SESSION_ACTIONS_ENABLED", "true")
    is_zk = mock.Mock(return_value=True)
    verify_pin = mock.Mock()
    monkeypatch.setattr(vault_core, "is_vault_zk_adopted", is_zk)
    monkeypatch.setattr(routes, "verify_vault_pin", verify_pin)
    return is_zk, verify_pin


def test_all_import_routes_require_trusted_device():
    assert len(routes.router.routes) == 4
    for route in routes.router.routes:
        assert any(
            dependency.call is verify_trusted_device
            for dependency in route.dependant.dependencies
        ), route.path


def test_zk_start_uses_trusted_session_without_pin_or_plaintext_folder(
    monkeypatch, zk_import_gate,
):
    is_zk, verify_pin = zk_import_gate
    created = mock.Mock(return_value={"import_id": "synthetic-import"})
    monkeypatch.setattr(main, "start_import_batch", created)
    payload = routes.ImportBatchStartRequest(
        vault_name="", total_files=3, total_bytes_planned=321,
    )
    assert payload.pin is None
    assert asyncio.run(routes.start_import_endpoint(payload, PRINCIPAL)) == {
        "import_id": "synthetic-import",
    }
    created.assert_called_once_with(
        vault_id=PRINCIPAL["vault_id"], root_folder_name=None,
        total_files=3, total_bytes_planned=321,
    )
    is_zk.assert_called_once_with(PRINCIPAL["vault_id"])
    verify_pin.assert_not_called()


@pytest.mark.parametrize("endpoint", [
    routes.cancel_import_endpoint,
    routes.complete_import_endpoint,
])
def test_zk_cancel_and_complete_use_trusted_session_without_pin(
    monkeypatch, zk_import_gate, endpoint,
):
    _, verify_pin = zk_import_gate
    cancel = mock.Mock(return_value={"status": "cancelled"})
    complete = mock.Mock(return_value={"status": "completed"})
    monkeypatch.setattr(main, "cancel_import_batch", cancel)
    monkeypatch.setattr(main, "complete_import_batch", complete)
    payload = routes.ImportBatchActionRequest(vault_name="")
    result = asyncio.run(endpoint("synthetic-import", payload, PRINCIPAL))
    if endpoint is routes.cancel_import_endpoint:
        assert result == {"status": "cancelled"}
        cancel.assert_called_once_with(
            vault_id=PRINCIPAL["vault_id"], import_id="synthetic-import",
        )
        complete.assert_not_called()
    else:
        assert result == {"status": "completed"}
        complete.assert_called_once_with(
            vault_id=PRINCIPAL["vault_id"], import_id="synthetic-import",
            failed_count_delta=0, skipped_duplicate_count_delta=0,
        )
        cancel.assert_not_called()
    verify_pin.assert_not_called()


def test_zk_start_rejects_plaintext_folder_and_raw_pin_before_mutation(
    monkeypatch, zk_import_gate,
):
    monkeypatch.setattr(main, "start_import_batch", lambda **_: pytest.fail("batch created"))
    for payload, detail in (
        (routes.ImportBatchStartRequest(vault_name="", root_folder_name="private"),
         "zk_plaintext_folder_name_not_supported"),
        (routes.ImportBatchStartRequest(vault_name="", pin="synthetic-pin"),
         "zk_client_update_required"),
    ):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(routes.start_import_endpoint(payload, PRINCIPAL))
        assert denied.value.status_code == 409
        assert denied.value.detail == detail


def test_zk_actions_reject_raw_pin_before_mutation(monkeypatch, zk_import_gate):
    monkeypatch.setattr(main, "cancel_import_batch", lambda **_: pytest.fail("cancelled"))
    monkeypatch.setattr(main, "complete_import_batch", lambda **_: pytest.fail("completed"))
    payload = routes.ImportBatchActionRequest(vault_name="", pin="synthetic-pin")
    for endpoint in (routes.cancel_import_endpoint, routes.complete_import_endpoint):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(endpoint("synthetic-import", payload, PRINCIPAL))
        assert denied.value.status_code == 409
        assert denied.value.detail == "zk_client_update_required"


def test_flag_off_and_legacy_keep_pin_recheck(monkeypatch, zk_import_gate):
    is_zk, verify_pin = zk_import_gate
    monkeypatch.setenv("VAULTAI_ZK_IMPORT_SESSION_ACTIONS_ENABLED", "false")
    with pytest.raises(HTTPException) as denied:
        routes._authorize_import_batch_action(PRINCIPAL, None)
    assert denied.value.status_code == 400
    assert is_zk.call_count == 0

    assert routes._authorize_import_batch_action(PRINCIPAL, "synthetic-pin") is False
    verify_pin.assert_called_once_with(PRINCIPAL["vault_id"], "synthetic-pin")

    monkeypatch.setenv("VAULTAI_ZK_IMPORT_SESSION_ACTIONS_ENABLED", "true")
    is_zk.return_value = False
    verify_pin.reset_mock()
    assert routes._authorize_import_batch_action(PRINCIPAL, "synthetic-pin") is False
    verify_pin.assert_called_once_with(PRINCIPAL["vault_id"], "synthetic-pin")
