from types import SimpleNamespace
import sys

import pytest
from fastapi import HTTPException

import subscription_entitlement as se


def _ent(status="active", limit=53_687_091_200):
    return SimpleNamespace(status=status, effective_limit_bytes=limit)


def _install_billing(monkeypatch, entitlement):
    monkeypatch.setitem(sys.modules, "billing", SimpleNamespace(
        get_account_id_for_vault=lambda _vault_id: "account-1",
        get_entitlement=lambda _account_id: entitlement,
    ))


@pytest.mark.parametrize("status", sorted(se.DELINQUENT_STATUSES))
def test_every_delinquent_status_blocks_content_writes(status, monkeypatch):
    _install_billing(monkeypatch, _ent(status))
    with pytest.raises(HTTPException) as caught:
        se.require_content_write({"vault_id": "vault-1"})
    assert caught.value.status_code == 402
    assert caught.value.detail["code"] == "subscription_delinquent_write_blocked"
    assert "preserved" in caught.value.detail["message"]


def test_active_and_reactivated_states_restore_plan_quota_and_writes(monkeypatch):
    for status in ("active", "in_grace", "canceled_pending"):
        _install_billing(monkeypatch, _ent(status))
        state = se.resolve_vault_entitlement("vault-1")
        assert state.delinquent is False
        assert state.effective_quota_bytes == 53_687_091_200
        assert se.require_content_write({"vault_id": "vault-1"})["vault_id"] == "vault-1"


def test_delinquent_quota_is_one_gib_without_mutating_usage_or_data(monkeypatch):
    _install_billing(monkeypatch, _ent("past_due"))
    state = se.resolve_vault_entitlement("vault-1")
    assert state.effective_quota_bytes == 1_073_741_824
    assert state.plan_quota_bytes == 53_687_091_200


def test_delinquent_small_file_allowed_but_large_file_blocked(monkeypatch):
    _install_billing(monkeypatch, _ent("unpaid"))
    assert se.require_file_read(
        {"vault_id": "vault-1"}, se.LARGE_FILE_THRESHOLD_BYTES
    )["vault_id"] == "vault-1"
    with pytest.raises(HTTPException) as caught:
        se.require_file_read(
            {"vault_id": "vault-1"}, se.LARGE_FILE_THRESHOLD_BYTES + 1
        )
    assert caught.value.status_code == 403
    assert caught.value.detail["code"] == "subscription_delinquent_large_file_blocked"


def test_delinquent_crypto_access_is_blocked_without_reading_wallet_data(monkeypatch):
    _install_billing(monkeypatch, _ent("payment_failed"))
    with pytest.raises(HTTPException) as caught:
        se.require_crypto_access({"vault_id": "vault-1"})
    assert caught.value.detail["code"] == "subscription_delinquent_crypto_blocked"
