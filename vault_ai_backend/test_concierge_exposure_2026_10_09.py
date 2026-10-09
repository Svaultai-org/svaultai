"""Synthetic fixtures only: no live provider, vault, secret or database."""
from __future__ import annotations

import base64
import asyncio
import importlib.util
import json
import logging
import threading
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

import concierge_exposure as ex
import concierge_scheduler as scheduler
from device_gate import verify_trusted_device
from routes import concierge_routes as routes

VAULT = "11111111-1111-4111-8111-111111111111"
OTHER_VAULT = "22222222-2222-4222-8222-222222222222"
MONITOR = "33333333-3333-4333-8333-333333333333"
LEASE = "44444444-4444-4444-8444-444444444444"
KEY = bytes(range(32))  # Fixture only, exactly AES-256 length.
API_KEY = "1" * 32


def settings(**changes):
    value = ex.Settings(True, True, True, API_KEY, {"v1": KEY}, "v1", 5, 86400)
    return replace(value, **changes)


@pytest.fixture(autouse=True)
def never_live(monkeypatch):
    def reject_db():
        pytest.fail("No live database is allowed in this synthetic target")
    monkeypatch.setattr(ex, "get_db", reject_db)
    monkeypatch.setattr(routes, "get_db", reject_db)
    monkeypatch.setattr(ex, "reserve_provider_slot", lambda _s: None)
    monkeypatch.setattr(ex, "block_provider", lambda _seconds: None)
    monkeypatch.setattr(ex, "consume_vault_budget", lambda _vault: None)
    monkeypatch.setattr(ex, "_caps_cache", None)
    # An un-injected request is always a test failure, not a network attempt.
    original = httpx.Client
    def offline_client(*args, **kwargs):
        if kwargs.get("transport") is None:
            pytest.fail("Provider transport must be synthetic")
        return original(*args, **kwargs)
    monkeypatch.setattr(ex.httpx, "Client", offline_client)


def provider_response(payload, *, status=200, headers=None):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=payload, headers=headers)
    return ex.HibpProvider(settings(), transport=httpx.MockTransport(handle)), requests


def breach_fixture():
    return {"Name": "SyntheticBreach", "Title": "Synthetic Breach", "Domain": "example.com",
            "BreachDate": "2026-01-02", "DataClasses": ["Email addresses", "Passwords"],
            "IsVerified": True, "IsSpamList": False, "IsStealerLog": False,
            "Description": "<script>never returned</script>", "LogoPath": "https://unsafe.invalid/logo"}


def available_caps():
    return {"email_range": {"status": "available"}, "email_monitoring": {"status": "available"},
            "stealer_logs": {"status": "conditional", "verified_email_domains": ["example.com"]}}


def client(monkeypatch, *, authenticated=True):
    app = FastAPI()
    app.include_router(routes.router)
    async def principal():
        if not authenticated:
            raise HTTPException(401, detail="invalid_session")
        return {"vault_id": VAULT}
    app.dependency_overrides[verify_trusted_device] = principal
    monkeypatch.setattr(ex.Settings, "from_environment", lambda: settings())
    return TestClient(app)


class Cursor:
    def __init__(self, rows=None, *, rowcount=1, failure=None):
        self.rows = list(rows or [])
        self.commands = []
        self.rowcount = rowcount
        self.failure = failure
    def execute(self, sql, params=None):
        if sql.startswith("SET LOCAL "):
            return
        self.commands.append((sql, params))
        if self.failure:
            raise self.failure
    def fetchone(self):
        return self.rows.pop(0) if self.rows else None
    def fetchall(self):
        return self.rows.pop(0) if self.rows else []


class Connection:
    def __init__(self, cursor):
        self.cur = cursor
        self.commits = 0
        self.closed = False
    def cursor(self, **_kwargs):
        return self.cur
    def commit(self):
        self.commits += 1
    def close(self):
        self.closed = True


def test_settings_default_off_and_no_secrets_in_repr(monkeypatch):
    for name in ("VAULTAI_CONCIERGE_ENABLED", "CONCIERGE_HIBP_API_KEY",
                 "CONCIERGE_MONITORING_KEY", "CONCIERGE_MONITORING_KEYRING_JSON"):
        monkeypatch.delenv(name, raising=False)
    value = ex.Settings.from_environment()
    assert not value.enabled and not value.background_enabled
    assert not value.api_key and not value.encryption_available
    assert API_KEY not in repr(settings())
    assert KEY.decode() not in repr(settings())
    caps = ex.capabilities(value)
    assert caps["email_range"]["status"] == "disabled"
    assert caps["file_exposure"]["status"] == "unsupported"


def test_operational_key_environment_and_rotation(monkeypatch):
    monkeypatch.setenv("CONCIERGE_HIBP_API_KEY", API_KEY)
    monkeypatch.setenv("CONCIERGE_MONITORING_KEY", base64.urlsafe_b64encode(KEY).decode().rstrip("="))
    value = ex.Settings.from_environment()
    assert value.api_key == API_KEY and value.encryption_available
    monkeypatch.setenv("CONCIERGE_MONITORING_KEYRING_JSON", '{"bad":"not-a-32-byte-key"}')
    assert not ex.Settings.from_environment().encryption_available
    monkeypatch.setenv("CONCIERGE_HIBP_API_KEY", "0" * 32)
    assert not ex.Settings.from_environment().api_key


@pytest.mark.parametrize("email", ["email@example.com/path", "a@b.com\nX-Test: injected", "x@@example.com",
                                    "https://example.com", "x@localhost", "x@example.com?token=a"])
def test_invalid_email_never_reaches_provider(email):
    provider, calls = provider_response([])
    with pytest.raises(ValueError):
        provider.email_breaches(email)
    assert not calls


def test_email_normalized_and_path_encoded_headers_private():
    provider, calls = provider_response([breach_fixture()])
    value = provider.email_breaches(" Example+test@Example.COM ")
    assert len(value) == 1
    assert calls[0].url.host == "haveibeenpwned.com"
    assert b"example%2Btest%40example.com" in calls[0].url.raw_path
    assert calls[0].headers["hibp-api-key"] == API_KEY
    assert "SVaultAI" in calls[0].headers["User-Agent"]
    assert "Description" not in value[0] and "LogoPath" not in value[0]


def test_range_accepts_only_six_hex_and_returns_only_documented_shape():
    provider, calls = provider_response([{"hashSuffix": "A" * 34, "websites": ["SyntheticBreach"]}])
    assert provider.email_range("abc123") == [{"hashSuffix": "A" * 34, "websites": ["SyntheticBreach"]}]
    assert calls[0].url.path.endswith("/range/ABC123")
    with pytest.raises(ValueError):
        provider.email_range("A" * 40)
    with pytest.raises(ValueError):
        provider.email_range("raw@email.com")
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [{}, [{"hashSuffix": "x", "websites": []}],
                                      [{"hashSuffix": "A" * 34, "websites": ["../admin"]}]])
def test_invalid_ranges_fail_closed(payload):
    provider, _ = provider_response(payload)
    with pytest.raises(ex.ProviderError, match="provider_invalid_response"):
        provider.email_range("ABC123")


@pytest.mark.parametrize("status,code", [(401, "provider_unauthorized"), (403, "provider_permission_denied"),
                                         (429, "provider_rate_limited"), (503, "provider_unavailable"),
                                         (302, "provider_unavailable"), (404, "provider_unavailable")])
def test_provider_errors_never_produce_clean_result(status, code):
    provider, calls = provider_response({"message": "secret detail must not escape"}, status=status,
                                        headers={"retry-after": "120"})
    with pytest.raises(ex.ProviderError) as info:
        provider.email_range("ABC123")
    assert info.value.code == code
    assert "secret" not in str(info.value)
    assert len(calls) == 1


def test_only_documented_account_404_is_no_known_records():
    provider, _ = provider_response({}, status=404)
    assert provider.email_breaches("synthetic@example.com") == []
    assert provider.stealer_domains("synthetic@example.com", ["example.com"]) == []


def test_unsupported_stealer_domain_never_disclosed():
    provider, calls = provider_response([])
    with pytest.raises(ex.ProviderError, match="stealer_domain_unsupported"):
        provider.stealer_domains("synthetic@gmail.com", ["example.com"])
    assert not calls


def test_timeout_repr_does_not_leak_selected_address_or_key():
    def fail(request):
        raise httpx.ReadTimeout("email synthetic@example.com", request=request)
    provider = ex.HibpProvider(settings(), transport=httpx.MockTransport(fail))
    with pytest.raises(ex.ProviderError) as info:
        provider.email_breaches("synthetic@example.com")
    assert str(info.value) == "provider_unavailable"
    assert "synthetic@" not in repr(info.value) and API_KEY not in repr(info.value)


def test_http_provider_debug_logs_are_suppressed_only_in_private_request_scope(caplog):
    caplog.set_level(logging.DEBUG)
    def handle(_request):
        logging.getLogger("httpcore.http11").debug("provider header key=%s email=%s", API_KEY, "synthetic@example.com")
        return httpx.Response(200, json=[])
    provider = ex.HibpProvider(settings(), transport=httpx.MockTransport(handle))
    provider.email_breaches("synthetic@example.com")
    assert "synthetic" not in caplog.text and API_KEY not in caplog.text
    logging.getLogger("httpx").info("unrelated HTTP diagnostic remains visible")
    assert "unrelated HTTP diagnostic" in caplog.text


def test_response_size_bounded():
    provider = ex.HibpProvider(settings(), transport=httpx.MockTransport(
        lambda _r: httpx.Response(200, content=b" " * (ex.MAX_PROVIDER_BYTES + 1))))
    with pytest.raises(ex.ProviderError, match="provider_invalid_response"):
        provider.email_range("ABC123")


def test_operational_envelopes_randomized_and_bound_to_vault_monitor_purpose():
    first = ex.seal(settings(), VAULT, MONITOR, "email", b"synthetic@example.com")
    second = ex.seal(settings(), VAULT, MONITOR, "email", b"synthetic@example.com")
    assert first != second and b"synthetic" not in first
    assert ex.unseal(settings(), "v1", VAULT, MONITOR, "email", first) == b"synthetic@example.com"
    for vault, monitor, purpose in [(OTHER_VAULT, MONITOR, "email"), (VAULT, LEASE, "email"), (VAULT, MONITOR, "result")]:
        with pytest.raises(ex.ProviderError, match="monitoring_key_unavailable"):
            ex.unseal(settings(), "v1", vault, monitor, purpose, first)
    with pytest.raises(ex.ProviderError):
        ex.unseal(settings(keyring={}), "v1", VAULT, MONITOR, "email", first)
    with pytest.raises(ex.ProviderError):
        ex.unseal(settings(), "v1", VAULT, MONITOR, "email", first[:-1] + bytes([first[-1] ^ 1]))


class FakePlan:
    calls = []
    def __init__(self, _settings, **_kwargs):
        pass
    def subscription(self):
        self.calls.append("subscription")
        return {"Rpm": 10, "IncludesKAnon": True, "IncludesStealerLogs": True}
    def verified_domains(self):
        self.calls.append("domains")
        return ["example.com"]


def test_capabilities_use_real_plan_flags_and_domain_confirmation(monkeypatch):
    FakePlan.calls = []
    monkeypatch.setattr(ex, "HibpProvider", FakePlan)
    caps = ex.capabilities(settings())
    assert caps["email_range"]["status"] == "available"
    assert caps["stealer_logs"]["status"] == "conditional"
    assert caps["stealer_logs"]["verified_email_domains"] == ["example.com"]
    assert FakePlan.calls == ["subscription", "domains"]
    ex.capabilities(settings())
    assert len(FakePlan.calls) == 2
    caps["stealer_logs"]["verified_email_domains"].clear()
    assert ex.capabilities(settings())["stealer_logs"]["verified_email_domains"] == ["example.com"]


def test_capabilities_missing_crypto_key_or_unsupported_plan(monkeypatch):
    class Basic(FakePlan):
        def subscription(self):
            return {"Rpm": 10, "IncludesKAnon": False, "IncludesStealerLogs": False}
    monkeypatch.setattr(ex, "HibpProvider", Basic)
    caps = ex.capabilities(settings(keyring={}))
    assert caps["email_range"]["status"] == "unsupported_plan"
    assert caps["email_monitoring"]["status"] == "not_configured"
    assert caps["stealer_logs"]["status"] == "unsupported_plan"


def test_capability_failure_and_misconfigured_budget_are_unknown(monkeypatch):
    monkeypatch.setattr(ex, "HibpProvider", FakePlan)
    caps = ex.capabilities(settings(rpm=11))
    assert caps["email_monitoring"]["status"] == "unavailable"
    assert caps["email_range"]["error_code"] == "provider_rate_configuration_invalid"


def test_expired_provider_subscription_cannot_be_available():
    provider, _ = provider_response({"Rpm": 10, "SubscribedUntil": "2000-01-01T00:00:00Z"})
    with pytest.raises(ex.ProviderError, match="provider_subscription_expired"):
        provider.subscription()


@pytest.mark.parametrize("extra", [{"password": "never"}, {"pin": "never"}, {"name": "friendly"},
                                    {"hash": "F" * 40}, {"private_key": "never"}])
def test_range_and_monitor_requests_reject_plaintext_extra_fields(extra):
    with pytest.raises(ValidationError):
        routes.EmailRangeRequest(prefix="ABC123", consent_version=ex.CONSENT_VERSION,
                                 prefix_disclosure_consent=True, **extra)
    with pytest.raises(ValidationError):
        routes.MonitorRequest(email="synthetic@example.com", consent_version=ex.CONSENT_VERSION,
                              background=True, email_disclosure_consent=True, **extra)


@pytest.mark.parametrize("change", [{"email_disclosure_consent": False}, {"background": False},
                                     {"consent_version": "old"}, {"stealer_logs": True}])
def test_monitor_consent_is_separate_current_and_explicit(change):
    payload = {"email": "synthetic@example.com", "consent_version": ex.CONSENT_VERSION,
               "background": True, "email_disclosure_consent": True, **change}
    with pytest.raises(ValidationError):
        routes.MonitorRequest(**payload)


def test_range_route_uses_only_prefix_and_returns_failure_timestamps(monkeypatch):
    api = client(monkeypatch)
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: available_caps())
    class Fail:
        def __init__(self, *_a, **_kw): pass
        def email_range(self, prefix):
            assert prefix == "ABC123"
            raise ex.ProviderError("provider_permission_denied")
    monkeypatch.setattr(ex, "HibpProvider", Fail)
    response = api.post("/concierge/email-range", json={"prefix": "ABC123", "consent_version": ex.CONSENT_VERSION,
                                                         "prefix_disclosure_consent": True})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "unavailable" and result["successful_at"] is None
    assert result["attempted_at"] and result["rows"] == []
    response = api.post("/concierge/email-range", json={"prefix": "ABC123", "consent_version": "old",
                                                         "prefix_disclosure_consent": True})
    assert response.status_code == 400


def test_all_routes_authenticate_and_disabled_caps_are_explicit(monkeypatch):
    api = client(monkeypatch, authenticated=False)
    assert api.get("/concierge/capabilities").status_code == 401
    assert api.get("/concierge/state").status_code == 401
    assert api.get("/concierge/monitors").status_code == 401
    api = client(monkeypatch)
    monkeypatch.setattr(ex.Settings, "from_environment", lambda: settings(enabled=False))
    caps = api.get("/concierge/capabilities").json()
    assert not caps["enabled"] and caps["email_range"]["status"] == "disabled"


def test_monitor_create_encrypts_only_consented_information_and_checks_owned_source(monkeypatch):
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: available_caps())
    cursor = Cursor([(UUID(VAULT),), (True,), (0,)])
    conn = Connection(cursor)
    monkeypatch.setattr(ex, "get_db", lambda: conn)
    result = ex.create_monitor(VAULT, "synthetic@example.com", "42", stealer_logs=False, settings=settings())
    assert result["status"] == "not_checked" and result["successful_at"] is None
    assert "email" not in result
    assert any("FOR UPDATE" in sql for sql, _ in cursor.commands)
    params = cursor.commands[-1][1]
    assert "synthetic@example.com" not in repr(params)
    assert ex.unseal(settings(), "v1", VAULT, result["id"], "email", params[4]) == b"synthetic@example.com"
    assert conn.commits == 1 and conn.closed


def test_monitor_cannot_reference_another_vault_item(monkeypatch):
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: available_caps())
    cursor = Cursor([(UUID(VAULT),), (False,)])
    conn = Connection(cursor)
    monkeypatch.setattr(ex, "get_db", lambda: conn)
    with pytest.raises(ValueError, match="source_item_not_found"):
        ex.create_monitor(VAULT, "synthetic@example.com", "42", stealer_logs=False, settings=settings())
    assert conn.commits == 0 and not any("INSERT INTO concierge_monitors" in s for s, _ in cursor.commands)


def test_monitor_cap_limit_and_unsupported_domain_prevent_storage(monkeypatch):
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: available_caps())
    with pytest.raises(ex.ProviderError, match="stealer_domain_unsupported"):
        ex.create_monitor(VAULT, "synthetic@gmail.com", None, stealer_logs=True, settings=settings())
    cursor = Cursor([(UUID(VAULT),), (20,)])
    monkeypatch.setattr(ex, "get_db", lambda: Connection(cursor))
    with pytest.raises(ValueError, match="monitor_limit_reached"):
        ex.create_monitor(VAULT, "synthetic@example.com", None, stealer_logs=False, settings=settings())


def monitor_row(**changes):
    return {"id": UUID(MONITOR), "vault_id": UUID(VAULT), "source_item_id": None,
            "key_id": "v1", "email_ciphertext": ex.seal(settings(), VAULT, MONITOR, "email", b"synthetic@example.com"),
            "result_ciphertext": None, "status": "not_checked", "error_code": None,
            "background": True, "stealer_logs": False, "stealer_disclosure_consent": False,
            "email_disclosure_consent": True, "consent_version": ex.CONSENT_VERSION,
            "attempted_at": None, "successful_at": None, "retry_after_seconds": None,
            "lease_token": UUID(LEASE), "lease_until": ex.now_utc() + timedelta(seconds=120), **changes}


def test_worker_success_never_stores_plaintext_results(monkeypatch):
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: available_caps())
    class Provider:
        def __init__(self, *_a, **_kw): pass
        def email_breaches(self, email):
            assert email == "synthetic@example.com"
            return [ex.sanitize_breach(breach_fixture())]
    monkeypatch.setattr(ex, "HibpProvider", Provider)
    cursor = Cursor([monitor_row(), monitor_row(status="found")])
    conn = Connection(cursor)
    monkeypatch.setattr(ex, "get_db", lambda: conn)
    ex.perform_monitor_check(MONITOR, LEASE, settings=settings())
    assert "lease_until>NOW() FOR UPDATE" in cursor.commands[0][0]
    params = cursor.commands[1][1]
    assert params[0] == "found"
    assert "synthetic@example.com" not in repr(params) and "Synthetic Breach" not in repr(params)
    decrypted = json.loads(ex.unseal(settings(), "v1", VAULT, MONITOR, "result", params[4]))
    assert decrypted["breaches"][0]["title"] == "Synthetic Breach"
    assert conn.commits == 1


def test_worker_failure_keeps_previous_evidence_and_success_time(monkeypatch):
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: available_caps())
    prior = ex.seal(settings(), VAULT, MONITOR, "result", json.dumps(
        {"breaches": [ex.sanitize_breach(breach_fixture())], "stealer_domains": []}).encode())
    success_time = ex.now_utc() - timedelta(days=1)
    row = monitor_row(status="found", result_ciphertext=prior, successful_at=success_time)
    class Fail:
        def __init__(self, *_a, **_kw): pass
        def email_breaches(self, _email): raise ex.ProviderError("provider_rate_limited", 120)
    monkeypatch.setattr(ex, "HibpProvider", Fail)
    updated = {**row, "status": "unavailable", "error_code": "provider_rate_limited"}
    cursor = Cursor([row, updated])
    monkeypatch.setattr(ex, "get_db", lambda: Connection(cursor))
    result = ex.perform_monitor_check(MONITOR, LEASE, settings=settings())
    assert result["status"] == "unavailable" and result["successful_at"] == success_time
    assert result["breaches"] and result["error_code"] == "provider_rate_limited"
    sql = cursor.commands[1][0]
    assert "result_ciphertext=" not in sql and "successful_at=" not in sql


def test_revoked_or_deleted_monitor_is_not_disclosed(monkeypatch):
    cursor = Cursor([None])
    monkeypatch.setattr(ex, "get_db", lambda: Connection(cursor))
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: available_caps())
    assert ex.perform_monitor_check(MONITOR, LEASE, settings=settings()) is None
    assert len(cursor.commands) == 1


def test_deleted_source_disables_future_background_disclosure(monkeypatch):
    row = monitor_row(source_item_id="42")
    updated = {**row, "status": "unavailable", "background": False,
               "error_code": "source_item_no_longer_available"}
    cursor = Cursor([row, {"exists": False}, updated])
    monkeypatch.setattr(ex, "get_db", lambda: Connection(cursor))
    monkeypatch.setattr(ex, "capabilities", lambda _s=None: available_caps())
    result = ex.perform_monitor_check(MONITOR, LEASE, settings=settings())
    assert not result["background"]
    assert cursor.commands[-1][1][4] is True


def test_lost_operational_key_is_unknown_not_clean():
    row = monitor_row(result_ciphertext=ex.seal(settings(), VAULT, MONITOR, "result", b'{"breaches":[],"stealer_domains":[]}'),
                      status="no_known_findings")
    result = ex.monitor_view(row, settings(keyring={}))
    assert result["status"] == "unavailable" and result["error_code"] == "monitoring_key_unavailable"


def test_status_without_successful_evidence_never_looks_clean():
    result = ex.monitor_view(monitor_row(status="no_known_findings"), settings())
    assert result["status"] == "unavailable" and result["error_code"] == "monitoring_data_unavailable"


def test_claim_has_cross_worker_lease_and_manual_cooldown(monkeypatch):
    row = {"id": UUID(MONITOR), "lease_until": ex.now_utc() + timedelta(seconds=100), "attempted_at": None}
    cursor = Cursor([row])
    monkeypatch.setattr(ex, "get_db", lambda: Connection(cursor))
    with pytest.raises(ex.ProviderError, match="monitor_check_in_progress"):
        ex.claim_monitor(vault_id=VAULT, monitor_id=MONITOR)
    assert cursor.commands[0][1] == (MONITOR, VAULT)
    cursor = Cursor([None])
    monkeypatch.setattr(ex, "get_db", lambda: Connection(cursor))
    assert ex.claim_monitor() is None
    assert "FOR UPDATE SKIP LOCKED" in cursor.commands[0][0]


def test_withdrawal_scoped_to_vault_and_committed_even_when_disabled(monkeypatch):
    api = client(monkeypatch)
    monkeypatch.setattr(ex.Settings, "from_environment", lambda: settings(enabled=False, keyring={}))
    cursor = Cursor()
    conn = Connection(cursor)
    monkeypatch.setattr(ex, "get_db", lambda: conn)
    response = api.delete("/concierge/monitors/" + MONITOR)
    assert response.status_code == 200 and response.json()["status"] == "withdrawn"
    assert cursor.commands[0][1] == (VAULT, MONITOR) and conn.commits == 1


def test_state_read_absent_and_write_opaque_bounded_versioned(monkeypatch):
    api = client(monkeypatch)
    conn = Connection(Cursor([None]))
    monkeypatch.setattr(routes, "get_db", lambda: conn)
    assert api.get("/concierge/state").json()["revision"] == 0
    opaque = b"not-plaintext" + b"a" * 30
    ciphertext = base64.urlsafe_b64encode(opaque).decode().rstrip("=")
    conn = Connection(Cursor([{"vault_id": VAULT}, None, {"revision": 1, "envelope_version": "v1", "updated_at": None}]))
    monkeypatch.setattr(routes, "get_db", lambda: conn)
    result = api.put("/concierge/state", json={"ciphertext": ciphertext, "envelope_version": "v1", "expected_revision": 0})
    assert result.status_code == 200 and result.json()["revision"] == 1
    assert conn.cur.commands[-1][1] == (VAULT, opaque, 1)
    assert conn.commits == 1
    assert api.put("/concierge/state", json={"ciphertext": "a" * 273073, "envelope_version": "v1", "expected_revision": 0}).status_code == 422
    assert api.put("/concierge/state", json={"ciphertext": ciphertext, "envelope_version": "v1", "expected_revision": 0,
                                              "findings": "plaintext"}).status_code == 422


def test_state_stale_write_does_not_overwrite_newer_result(monkeypatch):
    api = client(monkeypatch)
    conn = Connection(Cursor([{"vault_id": VAULT}, {"revision": 2}]))
    monkeypatch.setattr(routes, "get_db", lambda: conn)
    response = api.put("/concierge/state", json={"ciphertext": base64.urlsafe_b64encode(b"c" * 40).decode().rstrip("="),
                                                  "envelope_version": "v1", "expected_revision": 1})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "concierge_state_conflict"
    assert conn.commits == 0 and not any("INSERT" in sql for sql, _ in conn.cur.commands)


def test_post_check_and_delete_routes_cannot_select_another_vault_monitor(monkeypatch):
    api = client(monkeypatch)
    conn = Connection(Cursor([None]))
    monkeypatch.setattr(ex, "get_db", lambda: conn)
    response = api.post("/concierge/monitors/" + MONITOR + "/check")
    assert response.status_code == 404
    assert conn.cur.commands[0][1] == (MONITOR, VAULT)
    conn = Connection(Cursor(rowcount=0))
    monkeypatch.setattr(ex, "get_db", lambda: conn)
    assert api.delete("/concierge/monitors/" + MONITOR).status_code == 404
    assert conn.cur.commands[0][1] == (VAULT, MONITOR)


def test_all_mutating_routes_require_authenticated_trusted_principal(monkeypatch):
    api = client(monkeypatch, authenticated=False)
    monitor = {"email": "synthetic@example.com", "consent_version": ex.CONSENT_VERSION,
               "email_disclosure_consent": True, "background": True}
    assert api.post("/concierge/monitors", json=monitor).status_code == 401
    assert api.post("/concierge/monitors/" + MONITOR + "/check").status_code == 401
    assert api.delete("/concierge/monitors/" + MONITOR).status_code == 401
    assert api.post("/concierge/email-range", json={"prefix": "ABC123", "consent_version": ex.CONSENT_VERSION,
                                                  "prefix_disclosure_consent": True}).status_code == 401
    assert api.put("/concierge/state", json={"ciphertext": "a" * 54, "envelope_version": "v1",
                                             "expected_revision": 0}).status_code == 401


def test_provider_pacing_retries_once_only_and_never_waits_indefinitely(monkeypatch):
    attempts = []
    waits = []
    def reserve(_settings):
        attempts.append(True)
        if len(attempts) == 1:
            raise ex.ProviderError("provider_rate_limited", 2)
    monkeypatch.setattr(ex, "reserve_provider_slot", reserve)
    monkeypatch.setattr(ex.time, "sleep", waits.append)
    provider, _ = provider_response([])
    provider.allow_rate_wait = True
    assert provider.email_range("ABC123") == []
    assert waits == [2] and len(attempts) == 2
    monkeypatch.setattr(ex, "reserve_provider_slot", lambda _s: (_ for _ in ()).throw(ex.ProviderError("provider_rate_limited", 30)))
    with pytest.raises(ex.ProviderError):
        provider.email_range("ABC123")
    assert waits == [2]


def test_scheduler_never_runs_without_all_configuration(monkeypatch):
    for change in ({"enabled": False}, {"background_enabled": False}, {"api_key": ""}, {"keyring": {}}):
        monkeypatch.setattr(ex.Settings, "from_environment", lambda c=change: settings(**c))
        assert ex.run_background_iteration() == 0
    monkeypatch.setattr(scheduler.Settings, "from_environment", lambda: settings(enabled=False))
    assert scheduler.start_concierge_scheduler() is None


def test_scheduler_shutdown_drains_current_thread_without_starting_next_job(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def work():
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return 1
    monkeypatch.setattr(scheduler.Settings, "from_environment", lambda: settings())
    monkeypatch.setattr(scheduler, "run_background_iteration", work)
    async def run():
        handle = scheduler.start_concierge_scheduler()
        assert await asyncio.to_thread(entered.wait, 5)
        stopped = asyncio.create_task(scheduler.stop_concierge_scheduler(handle))
        await asyncio.sleep(0)
        assert not stopped.done()
        release.set()
        await stopped
        assert handle.task.done()
    asyncio.run(run())
    assert len(calls) == 1


def test_migration_is_additive_vault_owned_and_has_no_sqlalchemy_binds(monkeypatch):
    path = Path(__file__).parent / "migrations/versions/0047_concierge_exposure.py"
    spec = importlib.util.spec_from_file_location("concierge_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    assert module.down_revision == "0046_store_only_billing"
    sql = "\n".join(statements)
    assert sql.count("REFERENCES vaults(vault_id) ON DELETE CASCADE") == 3
    assert "CREATE TABLE concierge_monitors" in sql and "CREATE TABLE concierge_client_state" in sql
    assert "UPDATE vaults" not in sql and "ALTER TABLE vaults" not in sql
    assert "password" not in sql.lower() and "email TEXT" not in sql
    assert all(not text(statement)._bindparams for statement in statements)
