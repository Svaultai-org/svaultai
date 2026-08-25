from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
from fastapi import HTTPException

from routes import vault_delete_routes as routes


class _Cursor:
    def __init__(self, vault_count, rows):
        self._answers = [
            {"account_id": "account-1"},
            {"count": vault_count},
            rows,
        ]

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self._answers.pop(0)

    def fetchall(self):
        return self._answers.pop(0)


class _Connection:
    def __init__(self, vault_count, rows):
        self._cursor = _Cursor(vault_count, rows)

    def cursor(self, **_kwargs):
        return self._cursor

    def close(self):
        return None


def _decision(vault_count, rows):
    with mock.patch.object(
        routes, "get_db", return_value=_Connection(vault_count, rows),
    ):
        return routes._get_deletion_billing_state("vault-1")


def _active_row(renewal_state, *, auto_renewing, cancel_at_period_end):
    return {
        "status": "active",
        "current_period_end": datetime.now(timezone.utc) + timedelta(days=10),
        "auto_renewing": auto_renewing,
        "cancel_at_period_end": cancel_at_period_end,
        "metadata_jsonb": {"apple_auto_renew_state": renewal_state},
    }


def test_non_final_vault_is_not_blocked_by_apple_subscription():
    result = _decision(2, [])
    assert result["deletion_allowed"] is True
    assert result["apple_subscription_state"] == "not_final_vault"


def test_final_vault_active_auto_renew_is_blocked():
    result = _decision(1, [_active_row(
        "enabled", auto_renewing=True, cancel_at_period_end=False,
    )])
    assert result["deletion_allowed"] is False
    assert result["apple_subscription_state"] == "active_auto_renewing"


def test_final_vault_canceled_but_paid_through_period_is_allowed():
    result = _decision(1, [_active_row(
        "disabled", auto_renewing=False, cancel_at_period_end=True,
    )])
    assert result["deletion_allowed"] is True
    assert result["apple_subscription_state"] == "canceled_pending_expiration"


@pytest.mark.parametrize("status", ["expired", "revoked", "refunded"])
def test_final_vault_resolved_subscription_is_allowed(status):
    row = _active_row("disabled", auto_renewing=False, cancel_at_period_end=True)
    row["status"] = status
    assert _decision(1, [row])["deletion_allowed"] is True


def test_unknown_renewal_state_fails_closed_with_typed_retryable_error():
    row = _active_row("unknown", auto_renewing=False, cancel_at_period_end=False)
    with mock.patch.object(routes, "_get_deletion_billing_state", return_value={
        "deletion_allowed": False,
        "apple_subscription_state": "temporarily_unavailable",
    }):
        with pytest.raises(HTTPException) as caught:
            routes._require_authoritative_final_vault_deletion_allowed("vault-1")
    assert caught.value.status_code == 503
    assert caught.value.detail["code"] == (
        "apple_subscription_status_temporarily_unavailable"
    )


def test_active_auto_renew_has_typed_blocking_error():
    with mock.patch.object(routes, "_get_deletion_billing_state", return_value={
        "deletion_allowed": False,
        "apple_subscription_state": "active_auto_renewing",
    }):
        with pytest.raises(HTTPException) as caught:
            routes._require_authoritative_final_vault_deletion_allowed("vault-1")
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == (
        "active_apple_subscription_must_be_canceled_before_final_deletion"
    )


def test_confirm_rechecks_after_pin_and_prevents_safe_status_race():
    payload = routes.DeleteConfirmRequest(
        request_token="valid", pin="123456",
        confirmation_phrase=routes.CONFIRMATION_PHRASE,
    )
    active_error = HTTPException(
        status_code=409,
        detail={
            "code": (
                "active_apple_subscription_must_be_canceled_before_final_deletion"
            ),
        },
    )
    with mock.patch.object(routes, "enforce_delete_vault_rate_limit"), \
            mock.patch.object(routes, "_verify_challenge", return_value=True), \
            mock.patch.object(routes, "_verify_pin", return_value=True), \
            mock.patch.object(
                routes, "_require_authoritative_final_vault_deletion_allowed",
                side_effect=active_error,
            ) as recheck, \
            mock.patch.object(routes, "delete_vault_and_all_data") as delete:
        with pytest.raises(HTTPException) as caught:
            routes.confirm_delete(
                payload, mock.MagicMock(), {"vault_id": "vault-1"},
            )
    assert caught.value.status_code == 409
    recheck.assert_called_once_with("vault-1")
    delete.assert_not_called()
