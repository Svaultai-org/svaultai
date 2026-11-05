"""Synthetic beneficiary authorization tests; no real PIN or database."""

from __future__ import annotations

import asyncio
import inspect
from unittest import mock

import pytest
from fastapi import HTTPException

import main
import vault_core
from routes import auth_zk_routes


PRINCIPAL = {
    "vault_id": "11111111-1111-1111-1111-111111111111",
    "token_id": "22222222-2222-2222-2222-222222222222",
}


@pytest.fixture
def gates(monkeypatch):
    verify_pin = mock.Mock()
    consume = mock.Mock()
    is_zk = mock.Mock(return_value=True)
    monkeypatch.setattr(main, "verify_vault_pin", verify_pin)
    monkeypatch.setattr(auth_zk_routes, "consume_recent_zk_proof", consume)
    monkeypatch.setattr(vault_core, "is_vault_zk_adopted", is_zk)
    return verify_pin, consume, is_zk


def test_zk_action_uses_only_one_time_opaque_proof_when_enabled(
    monkeypatch, gates,
):
    verify_pin, consume, is_zk = gates
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", "true")
    request = main.BeneficiaryListRequest(zk_proof_token="synthetic-proof")
    assert request.pin is None
    assert request.vault_name == ""
    main._verify_beneficiary_action(
        PRINCIPAL, pin=request.pin, proof_token=request.zk_proof_token,
    )
    consume.assert_called_once_with("synthetic-proof", PRINCIPAL)
    verify_pin.assert_not_called()
    is_zk.assert_called_once_with(PRINCIPAL["vault_id"])


def test_zk_action_rejects_raw_pin_and_missing_proof(monkeypatch, gates):
    verify_pin, consume, _ = gates
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", "true")
    for pin, proof, expected in (
        ("synthetic-pin", None, "zk_client_update_required"),
        (None, None, "zk_proof_token_required"),
        ("synthetic-pin", "synthetic-proof", "zk_client_update_required"),
    ):
        with pytest.raises(HTTPException) as denied:
            main._verify_beneficiary_action(
                PRINCIPAL, pin=pin, proof_token=proof,
            )
        assert denied.value.detail == expected
    verify_pin.assert_not_called()
    consume.assert_not_called()


def test_flag_off_and_legacy_account_preserve_pin_flow(monkeypatch, gates):
    verify_pin, consume, is_zk = gates
    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", "false")
    main._verify_beneficiary_action(
        PRINCIPAL, pin="synthetic-legacy-pin", proof_token=None,
    )
    verify_pin.assert_called_once_with(
        PRINCIPAL["vault_id"], "synthetic-legacy-pin",
    )
    is_zk.assert_not_called()
    verify_pin.reset_mock()
    with pytest.raises(HTTPException) as denied:
        main._verify_beneficiary_action(
            PRINCIPAL, pin=None, proof_token="synthetic-proof",
        )
    assert denied.value.status_code == 409
    consume.assert_not_called()

    monkeypatch.setenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", "true")
    is_zk.return_value = False
    main._verify_beneficiary_action(
        PRINCIPAL, pin="synthetic-legacy-pin", proof_token=None,
    )
    verify_pin.assert_called_once_with(
        PRINCIPAL["vault_id"], "synthetic-legacy-pin",
    )
    consume.assert_not_called()


def test_transfer_request_model_accepts_proof_without_pin():
    request = main.TransferActionRequest(
        link_id=7, zk_proof_token="synthetic-proof",
    )
    assert request.pin is None
    assert request.link_id == 7


def test_all_four_pin_only_beneficiary_routes_use_shared_proof_gate(monkeypatch):
    checked = mock.Mock()
    monkeypatch.setattr(main, "_verify_beneficiary_action", checked)

    class Cursor:
        def execute(self, _sql, _params):
            pass

        def fetchall(self):
            return []

        def fetchone(self):
            return None

    class Connection:
        def cursor(self, **_kwargs):
            return Cursor()

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(main, "get_db", lambda: Connection())
    routes = (
        (main.beneficiary_list_mine_endpoint,
         main.BeneficiaryListRequest(zk_proof_token="synthetic-proof")),
        (main.beneficiary_list_inheritances_endpoint,
         main.BeneficiaryListRequest(zk_proof_token="synthetic-proof")),
        (main.beneficiary_request_transfer_endpoint,
         main.TransferActionRequest(link_id=7, zk_proof_token="synthetic-proof")),
        (main.beneficiary_cancel_transfer_endpoint,
         main.TransferActionRequest(link_id=7, zk_proof_token="synthetic-proof")),
    )
    for handler, payload in routes:
        checked.reset_mock()
        original = inspect.unwrap(handler)
        try:
            asyncio.run(original(None, payload, PRINCIPAL))
        except HTTPException as exc:
            # Empty fixture has no linked row for the two mutation actions.
            assert exc.status_code == 404
        checked.assert_called_once_with(
            PRINCIPAL, pin=None, proof_token="synthetic-proof",
        )
