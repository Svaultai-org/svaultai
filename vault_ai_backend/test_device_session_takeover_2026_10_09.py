"""Offline atomic-issuer and current-session device-bound regression tests.

Real PostgreSQL concurrency/rollback coverage is in the separate disposable
database suite. No test here opens a database or calls production.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi import HTTPException, Request

import auth_local
import device_monitor
from routes import auth_routes, auth_zk_routes, device_routes


VAULT = "00000000-0000-4000-8000-000000000001"
TOKEN = "00000000-0000-4000-8000-000000000002"
DEVICE = "device-current-aaaaaaaaaaaa"
OTHER = "device-previous-bbbbbbbbbbb"


def request(device_id=DEVICE):
    headers = [] if device_id is None else [(b"x-device-id", device_id.encode())]
    return Request({"type": "http", "method": "POST", "path": "/devices/register",
                    "headers": headers})


def current_session(**overrides):
    return {"device_id": DEVICE, "revoked_at": None, "revoked_reason": None,
            "unexpired": True, **overrides}


def register(**overrides):
    return device_monitor.register_or_refresh(
        vault_id=VAULT, device_id=DEVICE, session_token_id=TOKEN,
        label="Untrusted client label", user_agent_brand="Client metadata",
        ip_prefix=None, **overrides,
    )


@pytest.mark.parametrize("session,status,code", [
    (None, 401, "invalid_session"),
    (current_session(revoked_at=datetime.now(timezone.utc),
                     revoked_reason="superseded-by-new-login"), 401, "session_superseded"),
    (current_session(revoked_at=datetime.now(timezone.utc),
                     revoked_reason="logout"), 401, "session_revoked"),
    (current_session(unexpired=False), 401, "session_expired"),
    (current_session(device_id=OTHER), 403, "device_session_mismatch"),
])
def test_register_revalidates_current_session_before_device_mutation(session, status, code):
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.side_effect = [{"vault_id": VAULT}, session]
    with mock.patch.object(device_monitor, "get_db", return_value=conn), \
         mock.patch.object(device_monitor, "apply_login_device_takeover") as takeover:
        with pytest.raises(HTTPException) as err:
            register()
    assert err.value.status_code == status
    assert err.value.detail["code"] == code
    takeover.assert_not_called()
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    sql = [call.args[0] for call in conn.cursor.return_value.execute.call_args_list]
    assert "FROM vaults" in sql[0] and "FOR UPDATE" in sql[0]
    assert "FROM auth_sessions" in sql[1] and "FOR UPDATE" in sql[1]


def test_register_cannot_undo_manual_revocation_with_bound_bearer():
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.side_effect = [
        {"vault_id": VAULT}, current_session(), {"status": "revoked"},
    ]
    with mock.patch.object(device_monitor, "get_db", return_value=conn), \
         mock.patch.object(device_monitor, "apply_login_device_takeover") as takeover:
        with pytest.raises(HTTPException) as err:
            register()
    assert err.value.status_code == 403
    assert err.value.detail["code"] == "device_revoked"
    takeover.assert_not_called()
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    device_check = conn.cursor.return_value.execute.call_args.args[0]
    assert "SELECT status FROM trusted_devices" in device_check
    assert device_check.endswith("FOR UPDATE")


def test_legacy_unbound_current_session_binds_once_under_lock():
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.side_effect = [
        {"vault_id": VAULT}, current_session(device_id=None),
    ]
    outcome = {"revoked_other_count": 1, "created": True}
    with mock.patch.object(device_monitor, "get_db", return_value=conn), \
         mock.patch.object(device_monitor, "apply_login_device_takeover", return_value=outcome) as takeover:
        assert register() == {"status": "trusted", "is_first_device": False, "created": True}
    calls = conn.cursor.return_value.execute.call_args_list
    assert "UPDATE auth_sessions SET device_id" in calls[2].args[0]
    assert calls[2].args[1] == (DEVICE, TOKEN)
    assert takeover.call_args.args[0] is conn.cursor.return_value
    conn.commit.assert_called_once()


def test_issuer_device_failure_rolls_back_before_token_is_built():
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.return_value = {"vault_id": VAULT}
    conn.cursor.return_value.fetchall.return_value = []
    with mock.patch.object(auth_local, "get_db", return_value=conn), \
         mock.patch.object(device_monitor, "apply_login_device_takeover", side_effect=RuntimeError("fixture failure")), \
         mock.patch.object(auth_local, "_format_token") as format_token:
        with pytest.raises(RuntimeError, match="fixture failure"):
            auth_local.issue_session_token(vault_id=VAULT, device_id=DEVICE,
                                           client_label="iOS/Safari")
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    format_token.assert_not_called()


def test_issuer_device_and_session_share_cursor_and_commit_order():
    conn = mock.MagicMock()
    cursor = conn.cursor.return_value
    cursor.fetchone.return_value = {"vault_id": VAULT}
    cursor.fetchall.return_value = []
    timeline = []
    cursor.execute.side_effect = lambda sql, *_: timeline.append(sql.strip())
    conn.commit.side_effect = lambda: timeline.append("COMMIT")
    with mock.patch.object(auth_local, "get_db", return_value=conn), \
         mock.patch.object(device_monitor, "apply_login_device_takeover", side_effect=lambda cur, **_: (
             timeline.append("DEVICE TAKEOVER"), {"new_device_trusted": True})[1]) as takeover, \
         mock.patch.object(auth_local, "_format_token", side_effect=lambda _: (
             timeline.append("TOKEN RETURN"), "fixture-wire-token")[1]):
        issued = auth_local.issue_session_token(vault_id=VAULT, device_id=DEVICE,
                                                client_label="iOS/Safari")
    assert takeover.call_args.args[0] is cursor
    assert timeline[0].endswith("FOR UPDATE")
    assert timeline[-2:] == ["COMMIT", "TOKEN RETURN"]
    assert timeline.index("DEVICE TAKEOVER") < timeline.index("COMMIT")
    assert issued["new_device_trusted"] is True
    conn.commit.assert_called_once()


def test_issuer_commit_failure_never_returns_token():
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.return_value = {"vault_id": VAULT}
    conn.cursor.return_value.fetchall.return_value = []
    conn.commit.side_effect = RuntimeError("commit failed")
    with mock.patch.object(auth_local, "get_db", return_value=conn), \
         mock.patch.object(device_monitor, "apply_login_device_takeover", return_value={"new_device_trusted": True}), \
         mock.patch.object(auth_local, "_format_token") as format_token:
        with pytest.raises(RuntimeError, match="commit failed"):
            auth_local.issue_session_token(vault_id=VAULT, device_id=DEVICE,
                                           client_label="iOS/Safari")
    conn.rollback.assert_called_once()
    format_token.assert_not_called()


@pytest.mark.parametrize("header", [None, OTHER])
def test_monitor_ignores_absent_or_spoofed_device_header(header):
    with mock.patch.object(device_monitor, "get_db") as get_db:
        device_monitor.monitor_best_effort(request(header), {
            "vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE,
        })
    get_db.assert_not_called()


def test_monitor_can_only_update_presence_for_current_bound_live_token():
    conn = mock.MagicMock()
    device_monitor._reset_monitor_cache_for_tests()
    with mock.patch.object(device_monitor, "get_db", return_value=conn):
        device_monitor.monitor_best_effort(request(), {
            "vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE,
        })
    sql, params = conn.cursor.return_value.execute.call_args.args
    normalized = " ".join(sql.lower().split())
    assert normalized.startswith("update trusted_devices d set last_seen_at")
    assert "from auth_sessions s" in normalized
    assert "s.token_id = %s" in normalized and "s.device_id = d.device_id" in normalized
    assert "s.revoked_at is null" in normalized and "s.expires_at > now()" in normalized
    assert "d.status = 'trusted'" in normalized
    assert "set status" not in normalized and "insert" not in normalized
    assert params[1:] == (VAULT, DEVICE, TOKEN)
    conn.commit.assert_called_once()


def test_route_rejects_header_payload_pivot_before_register():
    with mock.patch.object(device_routes, "register_or_refresh") as helper:
        with pytest.raises(HTTPException) as err:
            asyncio.run(device_routes.register_device_endpoint(
                device_routes.RegisterDeviceRequest(device_id=OTHER), request(),
                {"vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE},
            ))
    assert err.value.status_code == 403
    assert err.value.detail["code"] == "device_session_mismatch"
    helper.assert_not_called()


@pytest.mark.parametrize("header", [None, DEVICE])
def test_route_preserves_current_session_register_contract(header):
    response = {"status": "trusted", "created": False, "is_first_device": False}
    with mock.patch.object(device_routes, "register_or_refresh", return_value=response) as helper:
        assert asyncio.run(device_routes.register_device_endpoint(
            device_routes.RegisterDeviceRequest(device_id=DEVICE), request(header),
            {"vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE},
        )) == response
    assert helper.call_args.kwargs["session_token_id"] == TOKEN
    assert helper.call_args.kwargs["device_id"] == DEVICE


def test_legacy_and_zk_auth_routes_do_not_use_separate_device_transaction():
    import inspect
    for handler in (auth_routes._login_impl, auth_zk_routes._zk_register_finalize_sync,
                    auth_zk_routes._zk_login_finalize_sync):
        source = inspect.getsource(handler)
        assert "issue_session_token(" in source
        assert "apply_login_device_takeover" not in source
        assert "trust_current_and_revoke_others" not in source
        assert "_upsert_trusted_device" not in source


@pytest.mark.parametrize("session,status,code", [
    (None, 401, "invalid_session"),
    (current_session(revoked_at=datetime.now(timezone.utc),
                     revoked_reason="superseded-by-new-login"), 401, "session_superseded"),
    (current_session(revoked_at=datetime.now(timezone.utc),
                     revoked_reason="logout"), 401, "session_revoked"),
    (current_session(unexpired=False), 401, "session_expired"),
])
def test_late_revoke_revalidates_old_session_before_touching_winning_device(session, status, code):
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.side_effect = [{"vault_id": VAULT}, session]
    with mock.patch.object(device_routes, "get_db", return_value=conn), \
         mock.patch.object(device_routes, "_notify") as notify:
        with pytest.raises(HTTPException) as err:
            asyncio.run(device_routes.revoke_device_endpoint(
                device_routes.TargetDeviceRequest(device_id=OTHER), request(),
                {"vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE},
            ))
    assert err.value.status_code == status and err.value.detail["code"] == code
    sql = [call.args[0] for call in conn.cursor.return_value.execute.call_args_list]
    assert len(sql) == 2
    assert "FROM vaults" in sql[0] and "FOR UPDATE" in sql[0]
    assert "FROM auth_sessions" in sql[1] and "FOR UPDATE" in sql[1]
    assert not any("trusted_devices" in statement for statement in sql)
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    notify.assert_not_called()


@pytest.mark.parametrize("header,bound", [(OTHER, DEVICE), (None, DEVICE), (DEVICE, None)])
def test_revoke_cannot_pivot_header_or_adopt_an_unbound_session(header, bound):
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.side_effect = [
        {"vault_id": VAULT}, current_session(device_id=bound),
    ]
    with mock.patch.object(device_routes, "get_db", return_value=conn):
        with pytest.raises(HTTPException) as err:
            asyncio.run(device_routes.revoke_device_endpoint(
                device_routes.TargetDeviceRequest(device_id=OTHER), request(header),
                {"vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE},
            ))
    assert err.value.status_code == 403
    assert err.value.detail["code"] == "device_session_mismatch"
    assert conn.cursor.return_value.execute.call_count == 2
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


@pytest.mark.parametrize("caller,code", [(None, "device_not_trusted"),
    ({"status": "revoked"}, "device_revoked"), ({"status": "pending"}, "device_not_trusted")])
def test_revoke_rechecks_caller_trust_under_lock_before_target(caller, code):
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.side_effect = [
        {"vault_id": VAULT}, current_session(), caller,
    ]
    with mock.patch.object(device_routes, "get_db", return_value=conn):
        with pytest.raises(HTTPException) as err:
            asyncio.run(device_routes.revoke_device_endpoint(
                device_routes.TargetDeviceRequest(device_id=OTHER), request(),
                {"vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE},
            ))
    assert err.value.status_code == 403 and err.value.detail["code"] == code
    assert conn.cursor.return_value.execute.call_count == 3
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


@pytest.mark.parametrize("target_id", [DEVICE, OTHER])
def test_current_trusted_device_can_still_revoke_self_or_other(target_id):
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.side_effect = [
        {"vault_id": VAULT}, current_session(), {"status": "trusted"},
        {"device_id": target_id, "status": "trusted", "label": "Synthetic phone", "user_agent_brand": None},
    ]
    with mock.patch.object(device_routes, "get_db", return_value=conn), \
         mock.patch.object(device_routes, "_notify") as notify:
        result = asyncio.run(device_routes.revoke_device_endpoint(
            device_routes.TargetDeviceRequest(device_id=target_id), request(),
            {"vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE},
        ))
    assert result == {"status": "revoked", "device_id": target_id,
                      "caller_revoked": target_id == DEVICE, "already_revoked": False}
    calls = conn.cursor.return_value.execute.call_args_list
    assert all("FOR UPDATE" in call.args[0] for call in calls[:4])
    assert calls[2].args[1] == (VAULT, DEVICE)
    assert calls[3].args[1] == (VAULT, target_id)
    assert "SET status = 'revoked'" in calls[4].args[0]
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    notify.assert_called_once()


def test_revoke_commit_error_rolls_back_and_never_notifies_success():
    conn = mock.MagicMock()
    conn.cursor.return_value.fetchone.side_effect = [
        {"vault_id": VAULT}, current_session(), {"status": "trusted"},
        {"device_id": OTHER, "status": "trusted", "label": None, "user_agent_brand": None},
    ]
    conn.commit.side_effect = RuntimeError("fixture commit failure")
    with mock.patch.object(device_routes, "get_db", return_value=conn), \
         mock.patch.object(device_routes, "_notify") as notify:
        with pytest.raises(RuntimeError, match="fixture commit failure"):
            asyncio.run(device_routes.revoke_device_endpoint(
                device_routes.TargetDeviceRequest(device_id=OTHER), request(),
                {"vault_id": VAULT, "token_id": TOKEN, "device_id": DEVICE},
            ))
    conn.rollback.assert_called_once()
    notify.assert_not_called()
