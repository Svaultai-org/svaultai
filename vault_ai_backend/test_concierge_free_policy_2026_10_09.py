"""Offline budget-policy regressions; no paid requests or real customer data."""
from __future__ import annotations

import base64
from dataclasses import replace

import pytest

import concierge_exposure as ex
import concierge_scheduler as scheduler
from routes import concierge_routes as routes
from test_concierge_exposure_2026_10_09 import (
    API_KEY, KEY, LEASE, MONITOR, VAULT, Connection, Cursor, client, settings,
)

_actual_reserve_provider_slot = ex.reserve_provider_slot


def reject_external(*_args, **_kwargs):
    pytest.fail("Free/invalid policy must not access provider, budgets or monitor DB")


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(ex, "get_db", reject_external)
    monkeypatch.setattr(routes, "get_db", reject_external)
    monkeypatch.setattr(ex, "reserve_provider_slot", reject_external)
    monkeypatch.setattr(ex, "consume_vault_budget", reject_external)
    monkeypatch.setattr(ex.httpx, "Client", reject_external)
    monkeypatch.setattr(ex, "_caps_cache", None)


def test_constructor_defaults_to_free_without_requiring_a_paid_subscription():
    value = ex.Settings(True, True, True, API_KEY, {"v1": KEY}, "v1", 5, 86400)
    assert value.provider_mode == "free" and not value.paid_provider_allowed
    caps = ex.capabilities(value)
    assert caps["provider_mode"] == "free" and caps["policy"] == "free_password_only"
    assert caps["password_breaches"] == {"status": "available", "mode": "client_range"}
    assert caps["file_exposure"]["status"] == "unsupported"
    for name in ("email_range", "email_monitoring", "stealer_logs"):
        assert caps[name]["status"] == "deferred"
        assert "error_code" not in caps[name]
    assert "deferred" in caps["coverage"] and "client" in caps["coverage"]


@pytest.mark.parametrize("configured,expected", [(None, "free"), ("free", "free"),
                                                ("HIBP", "hibp"), ("typo", "invalid"),
                                                ("", "invalid")])
def test_environment_defaults_and_unknown_mode_fail_closed(monkeypatch, configured, expected):
    monkeypatch.delenv("VAULTAI_CONCIERGE_PROVIDER_MODE", raising=False)
    if configured is not None:
        monkeypatch.setenv("VAULTAI_CONCIERGE_PROVIDER_MODE", configured)
    for flag in ("VAULTAI_CONCIERGE_ENABLED", "VAULTAI_CONCIERGE_BACKGROUND_ENABLED",
                 "VAULTAI_CONCIERGE_STEALER_LOGS_ENABLED"):
        monkeypatch.setenv(flag, "true")
    monkeypatch.setenv("CONCIERGE_HIBP_API_KEY", API_KEY)
    monkeypatch.setenv("CONCIERGE_MONITORING_KEY", base64.urlsafe_b64encode(KEY).decode().rstrip("="))
    monkeypatch.delenv("CONCIERGE_MONITORING_KEYRING_JSON", raising=False)
    value = ex.Settings.from_environment()
    assert value.provider_mode == expected
    assert value.paid_provider_allowed is (expected == "hibp")
    assert value.enabled and value.api_key and value.encryption_available
    if expected != "hibp":
        caps = ex.capabilities(value)
        assert caps["email_monitoring"]["status"] == ("deferred" if expected == "free" else "not_configured")
        if expected == "invalid":
            assert caps["email_monitoring"]["error_code"] == "provider_mode_invalid"
            assert "typo" not in repr(caps)


def test_paid_capability_cache_cannot_enable_free_requests(monkeypatch):
    paid = settings()
    identity = (paid.provider_mode, paid.api_key, paid.background_enabled, paid.stealer_enabled,
                paid.encryption_available, paid.rpm)
    monkeypatch.setattr(ex, "_caps_cache", (float("inf"), identity, {
        "email_range": {"status": "available"}, "email_monitoring": {"status": "available"},
        "stealer_logs": {"status": "conditional"}}))
    caps = ex.capabilities(replace(paid, provider_mode="free"))
    assert caps["email_range"]["status"] == "deferred"
    assert caps["stealer_logs"]["verified_email_domains"] == []


@pytest.mark.parametrize("mode", ["free", "invalid"])
def test_actual_rate_reservation_rejects_before_any_database_access(mode):
    # Exercise the real helper, not the fixture's rejecting budget stub.
    with pytest.raises(ex.ProviderError, match="provider_deferred" if mode == "free" else "provider_mode_invalid"):
        _actual_reserve_provider_slot(settings(provider_mode=mode))


@pytest.mark.parametrize("mode", ["free", "invalid"])
@pytest.mark.parametrize("operation", ["subscription", "domains", "range", "email", "breach", "stealer"])
def test_all_hibp_methods_deny_before_budgets_or_transport(mode, operation):
    provider = ex.HibpProvider(settings(provider_mode=mode), allow_rate_wait=True)
    calls = {
        "subscription": provider.subscription,
        "domains": provider.verified_domains,
        "range": lambda: provider.email_range("ABC123"),
        "email": lambda: provider.email_breaches("synthetic@example.com"),
        "breach": lambda: provider.breach("SyntheticBreach"),
        "stealer": lambda: provider.stealer_domains("synthetic@example.com", ["example.com"]),
    }
    with pytest.raises(ex.ProviderError, match="provider_deferred" if mode == "free" else "provider_mode_invalid"):
        calls[operation]()


@pytest.mark.parametrize("mode", ["free", "invalid"])
@pytest.mark.parametrize("operation", ["create", "claim", "perform"])
def test_monitor_work_cannot_claim_decrypt_or_write_in_free_policy(mode, operation):
    value = settings(provider_mode=mode)
    calls = {
        "create": lambda: ex.create_monitor(VAULT, "synthetic@example.com", None,
                                             stealer_logs=True, settings=value),
        "claim": lambda: ex.claim_monitor(vault_id=VAULT, monitor_id=MONITOR, settings=value),
        "perform": lambda: ex.perform_monitor_check(MONITOR, LEASE, settings=value),
    }
    with pytest.raises(ex.ProviderError, match="provider_deferred" if mode == "free" else "provider_mode_invalid"):
        calls[operation]()


@pytest.mark.parametrize("mode", ["free", "invalid"])
def test_background_no_task_and_no_claim_even_with_key_and_all_flags(monkeypatch, mode):
    value = settings(provider_mode=mode)
    monkeypatch.setattr(ex.Settings, "from_environment", lambda: value)
    monkeypatch.setattr(ex, "claim_monitor", reject_external)
    monkeypatch.setattr(scheduler.asyncio, "create_task", reject_external)
    assert scheduler.start_concierge_scheduler() is None
    assert ex.run_background_iteration() == 0


@pytest.mark.parametrize("mode,http_status,code,status", [
    ("free", 403, "provider_deferred", "deferred"),
    ("invalid", 503, "provider_mode_invalid", "not_configured"),
])
@pytest.mark.parametrize("endpoint", ["range", "breach", "create", "check"])
def test_direct_paid_routes_return_policy_not_outage_before_budget(monkeypatch, mode, http_status, code, status, endpoint):
    api = client(monkeypatch)
    monkeypatch.setattr(ex.Settings, "from_environment", lambda: settings(provider_mode=mode))
    if endpoint == "range":
        response = api.post("/concierge/email-range", json={"prefix": "ABC123",
            "consent_version": ex.CONSENT_VERSION, "prefix_disclosure_consent": True})
    elif endpoint == "breach":
        response = api.get("/concierge/breaches/SyntheticBreach")
    elif endpoint == "create":
        response = api.post("/concierge/monitors", json={"email": "synthetic@example.com",
            "consent_version": ex.CONSENT_VERSION, "email_disclosure_consent": True, "background": True})
    else:
        response = api.post("/concierge/monitors/" + MONITOR + "/check")
    assert response.status_code == http_status
    assert response.json()["detail"] == {"code": code, "status": status, "retry_after_seconds": None}


def test_free_state_read_write_and_consent_withdrawal_remain_functional(monkeypatch):
    api = client(monkeypatch)
    monkeypatch.setattr(ex.Settings, "from_environment", lambda: settings(provider_mode="free"))
    connection = Connection(Cursor([None]))
    monkeypatch.setattr(routes, "get_db", lambda: connection)
    assert api.get("/concierge/state").json()["revision"] == 0
    assert connection.closed
    opaque = b"c" * 40
    ciphertext = base64.urlsafe_b64encode(opaque).decode().rstrip("=")
    connection = Connection(Cursor([{"vault_id": VAULT}, None,
                                    {"revision": 1, "envelope_version": "v1", "updated_at": None}]))
    monkeypatch.setattr(routes, "get_db", lambda: connection)
    response = api.put("/concierge/state", json={"ciphertext": ciphertext,
                                               "envelope_version": "v1", "expected_revision": 0})
    assert response.status_code == 200 and connection.commits == 1
    assert connection.cur.commands[-1][1] == (VAULT, opaque, 1)
    connection = Connection(Cursor())
    monkeypatch.setattr(ex, "get_db", lambda: connection)
    response = api.delete("/concierge/monitors/" + MONITOR)
    assert response.status_code == 200 and response.json()["status"] == "withdrawn"
    assert connection.cur.commands[0][1] == (VAULT, MONITOR) and connection.commits == 1
