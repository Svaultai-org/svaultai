"""Synthetic eight-tier bridge/host contract tests: no Google or database calls."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1] / "vault_ai_backend"
sys.path.insert(0, str(BACKEND_DIR))

import google_play_billing as host  # noqa: E402
from google_play_billing_bridge import main, publisher  # noqa: E402
from google_play_billing_bridge.protocol import NonceReplayCache  # noqa: E402
from google_play_billing_bridge.test_bridge import (  # noqa: E402
    SECRET,
    _assert_signed,
    _request,
)


def _catalog(product_id):
    return {
        "packageName": publisher.PACKAGE_NAME,
        "productId": product_id,
        "basePlans": [{
            "basePlanId": publisher.BASE_PLAN_ID,
            "state": "ACTIVE",
            "autoRenewingBasePlanType": {"billingPeriodDuration": "P1M"},
        }],
    }


def _safe_catalog_result(product_id):
    return {
        "adc_resolution": "PASS",
        "adc_identity": publisher.SERVICE_ACCOUNT,
        "android_publisher_api_auth": "PASS",
        "package_name": publisher.PACKAGE_NAME,
        "product_id": product_id,
        "base_plan_id": publisher.BASE_PLAN_ID,
        "base_plan_type": "AUTO_RENEWING",
        "billing_period": publisher.BILLING_PERIOD,
    }


class _Session:
    def __init__(self):
        self.calls = []
        self.ack_status = 204
        self.on_ack = lambda: None

    def get(self, url, *, timeout):
        self.calls.append(("GET", url, timeout))
        return SimpleNamespace(
            status_code=200,
            json=lambda: _catalog(url.rsplit("/", 1)[-1]),
        )

    def post(self, url, *, json, timeout):
        self.calls.append(("POST", url, json, timeout))
        self.on_ack()
        return SimpleNamespace(status_code=self.ack_status)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    main._replay_cache = NonceReplayCache()
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", SECRET.decode())
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_BRIDGE_URL", "https://bridge.test.invalid")
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL", publisher.SERVICE_ACCOUNT)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("VAULTAI_GOOGLE_PLAY_PACKAGE_NAME", raising=False)
    session = _Session()
    monkeypatch.setattr(publisher, "authorized_session", lambda: session)
    return session


def test_bridge_closed_catalog_exactly_matches_existing_host_mapping():
    assert publisher.PRODUCT_IDS == tuple(
        product for product, plan in host.GOOGLE_PLAY_STORAGE_CATALOG
        if plan == publisher.BASE_PLAN_ID
    )
    assert len(publisher.PRODUCT_IDS) == len(set(publisher.PRODUCT_IDS)) == 8
    assert publisher.PRODUCT_ID == host.GOOGLE_PLAY_PRODUCT_50GB
    assert publisher.PACKAGE_NAME == host.GOOGLE_PLAY_PACKAGE_NAME


@pytest.mark.parametrize("product_id", publisher.PRODUCT_IDS)
def test_ack_uses_exact_allowlisted_product_url(isolated, product_id):
    publisher.acknowledge_subscription(product_id, "opaque/synthetic-token")
    assert isolated.calls == [(
        "POST",
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/com.svaultai.app/purchases/subscriptions/{product_id}/"
        "tokens/opaque%2Fsynthetic-token:acknowledge",
        {},
        20,
    )]


@pytest.mark.parametrize("product_id", publisher.PRODUCT_IDS)
def test_catalog_uses_and_verifies_exact_allowlisted_product(isolated, product_id):
    assert publisher.verify_catalog(product_id) == _safe_catalog_result(product_id)
    assert isolated.calls == [(
        "GET",
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/com.svaultai.app/subscriptions/{product_id}",
        20,
    )]
    publisher.validate_catalog(_catalog(product_id), product_id)
    wrong = _catalog(next(p for p in publisher.PRODUCT_IDS if p != product_id))
    with pytest.raises(publisher.PublisherVerificationError, match="product mismatch"):
        publisher.validate_catalog(wrong, product_id)


def test_catalog_defaults_remain_50gb(isolated):
    publisher.validate_catalog(_catalog(publisher.PRODUCT_ID))
    assert publisher.verify_catalog()["product_id"] == publisher.PRODUCT_ID
    assert isolated.calls[0][1].endswith("/svaultai_storage_50gb")


@pytest.mark.parametrize("product_id", [
    "other_product", "svaultai_storage_2tb", "svaultai_storage_50gb/../../other",
    "SVAULTAI_STORAGE_50GB", " svaultai_storage_50gb", "", None, 50, True, [], {},
])
def test_unknown_or_nonstring_product_never_reaches_publisher(isolated, product_id):
    for operation in (
        lambda: publisher.acknowledge_subscription(product_id, "synthetic-token"),
        lambda: publisher.verify_catalog(product_id),
        lambda: publisher.validate_catalog(_catalog(publisher.PRODUCT_ID), product_id),
    ):
        with pytest.raises(publisher.PublisherVerificationError, match="fixed catalog"):
            operation()
    assert isolated.calls == []


@pytest.mark.parametrize("product_id", publisher.PRODUCT_IDS)
@pytest.mark.parametrize("path", ["/v1/subscriptions:acknowledge", "/v1/catalog:verify"])
def test_authenticated_routes_forward_requested_tier_and_sign_response(isolated, product_id, path):
    payload = {"product_id": product_id}
    if path.endswith(":acknowledge"):
        payload["purchase_token"] = "synthetic-token"
    body, timestamp, headers = _request(path, payload)
    response = TestClient(main.app).post(path, content=body, headers=headers)
    assert response.status_code == 200
    if path.endswith(":acknowledge"):
        assert response.json() == {"acknowledged": True}
    else:
        assert response.json() == _safe_catalog_result(product_id)
    assert f"/{product_id}" in isolated.calls[0][1]
    _assert_signed(response, timestamp=timestamp, nonce="n" * 32)


@pytest.mark.parametrize("product_id", ["unknown", "", None, [], {}])
@pytest.mark.parametrize("path", ["/v1/subscriptions:acknowledge", "/v1/catalog:verify"])
def test_routes_reject_unknown_products_before_google(isolated, product_id, path):
    payload = {"product_id": product_id}
    if path.endswith(":acknowledge"):
        payload["purchase_token"] = "synthetic-token"
    body, timestamp, headers = _request(path, payload)
    response = TestClient(main.app).post(path, content=body, headers=headers)
    assert response.status_code == 400
    assert response.json() == {"error": "publisher_request_rejected"}
    assert isolated.calls == []
    _assert_signed(response, timestamp=timestamp, nonce="n" * 32)


@pytest.mark.parametrize("payload", [
    {"product_id": publisher.PRODUCT_ID, "purchase_token": "x" * 4097},
    {"product_id": publisher.PRODUCT_ID, "purchase_token": ""},
    {"product_id": publisher.PRODUCT_ID, "purchase_token": None},
    {"product_id": publisher.PRODUCT_ID, "purchase_token": "token", "package_name": "other"},
])
def test_ack_preserves_token_and_field_bounds(isolated, payload):
    path = "/v1/subscriptions:acknowledge"
    body, _timestamp, headers = _request(path, payload)
    response = TestClient(main.app).post(path, content=body, headers=headers)
    assert response.status_code == 400
    assert isolated.calls == []


def test_oversized_signed_request_never_reaches_google(isolated):
    path = "/v1/subscriptions:acknowledge"
    body, _timestamp, headers = _request(path, {
        "product_id": publisher.PRODUCT_ID, "purchase_token": "x" * 8192,
    })
    response = TestClient(main.app).post(path, content=body, headers=headers)
    assert response.status_code == 401
    assert isolated.calls == []


def _host_client():
    client = TestClient(main.app)

    def post(url, *, content, headers, timeout):
        assert urlsplit(url).netloc == "bridge.test.invalid"
        assert timeout == 20
        return client.post(urlsplit(url).path, content=content, headers=headers)

    return host.GooglePlayPublisherClient(bridge_post=post)


@pytest.mark.parametrize("product_id", publisher.PRODUCT_IDS)
def test_host_catalog_parameter_traverses_authenticated_bridge(isolated, product_id):
    assert _host_client().verify_catalog(product_id) == _safe_catalog_result(product_id)
    assert isolated.calls[0][1].endswith(f"/{product_id}")


def test_host_catalog_default_is_backwards_compatible(isolated):
    assert _host_client().verify_catalog()["product_id"] == publisher.PRODUCT_ID


@pytest.mark.parametrize("product_id", ["unknown", "", None, [], {}])
def test_host_catalog_rejects_bad_product_before_bridge(monkeypatch, product_id):
    client = host.GooglePlayPublisherClient()
    monkeypatch.setattr(client, "_bridge_request", lambda *_args: pytest.fail("no bridge call"))
    with pytest.raises(host.GooglePlayVerificationError, match="fixed catalog"):
        client.verify_catalog(product_id)


def test_host_rejects_authenticated_wrong_product_catalog_response(monkeypatch):
    client = host.GooglePlayPublisherClient()
    monkeypatch.setattr(client, "_bridge_request", lambda *_args: _safe_catalog_result(publisher.PRODUCT_ID))
    with pytest.raises(host.GooglePlayVerificationError, match="verification mismatch"):
        client.verify_catalog("svaultai_storage_100gb")


@pytest.mark.parametrize("product_id", publisher.PRODUCT_IDS)
def test_host_ack_traverses_authenticated_bridge_for_each_tier(isolated, product_id):
    _host_client().acknowledge_subscription(product_id, "synthetic-token")
    assert isolated.calls[0][1].endswith(f"/{product_id}/tokens/synthetic-token:acknowledge")


def test_non50gb_retry_keeps_activation_before_ack_and_finishes_after_success(isolated, monkeypatch):
    account = "00000000-0000-0000-0000-000000000001"
    product_id = "svaultai_storage_100gb"
    payload = {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
        "startTime": "2026-08-01T00:00:00Z",
        "externalAccountIdentifiers": {
            "obfuscatedExternalAccountId": host.purchase_account_token(account),
        },
        "lineItems": [{
            "productId": product_id,
            "expiryTime": "2099-09-01T00:00:00Z",
            "autoRenewingPlan": {"autoRenewEnabled": True},
            "offerDetails": {"basePlanId": publisher.BASE_PLAN_ID},
        }],
    }
    monkeypatch.setattr(main, "get_subscription", lambda _token: payload)
    persisted = []

    def reconcile(account_id, update, **_kwargs):
        assert account_id == account
        persisted.append((update.product_id, update.quantity))
        return "synthetic-entitlement", "unchanged" if len(persisted) > 1 else "none_to_active"

    monkeypatch.setattr(host, "reconcile_google_play_storage_entitlement", reconcile)
    isolated.on_ack = lambda: persisted or pytest.fail("ACK before ownership persistence")
    isolated.ack_status = 503
    client = _host_client()
    with pytest.raises(host.GooglePlayTransientError):
        host.verify_and_apply_google_subscription(
            account_id=account, purchase_token="synthetic-token",
            expected_product_id=product_id, publisher=client,
        )
    assert persisted == [(product_id, 2)]
    isolated.ack_status = 204
    result = host.verify_and_apply_google_subscription(
        account_id=account, purchase_token="synthetic-token",
        expected_product_id=product_id, publisher=client,
    )
    assert result.acknowledged is True
    assert result.product_id == product_id
    assert result.transition == "unchanged"
    assert persisted == [(product_id, 2), (product_id, 2)]


def _probe_module():
    path = BACKEND_DIR / "scripts" / "verify_google_play_bridge.py"
    spec = importlib.util.spec_from_file_location("synthetic_bridge_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_read_only_probe_defaults_50gb_and_sweeps_exact_eight(monkeypatch, capsys):
    probe = _probe_module()
    calls = []

    class Client:
        def verify_catalog(self, product_id):
            calls.append(product_id)
            return _safe_catalog_result(product_id)

    monkeypatch.setattr(probe, "GooglePlayPublisherClient", Client)
    assert probe.main([]) == 0
    assert calls == [publisher.PRODUCT_ID]
    assert "CATALOG_PRODUCTS_VERIFIED" not in capsys.readouterr().out
    calls.clear()
    assert probe.main(["--all-products"]) == 0
    assert tuple(calls) == publisher.PRODUCT_IDS
    assert "GOOGLE_PLAY_CATALOG_PRODUCTS_VERIFIED=8" in capsys.readouterr().out


def test_probe_does_not_report_full_success_after_one_tier_fails(monkeypatch, capsys):
    probe = _probe_module()

    class Client:
        def verify_catalog(self, product_id):
            if product_id == "svaultai_storage_100gb":
                raise host.GooglePlayVerificationError("synthetic catalog unavailable")
            return _safe_catalog_result(product_id)

    monkeypatch.setattr(probe, "GooglePlayPublisherClient", Client)
    with pytest.raises(host.GooglePlayVerificationError):
        probe.main(["--all-products"])
    assert "GOOGLE_PLAY_CATALOG_PRODUCTS_VERIFIED=8" not in capsys.readouterr().out
