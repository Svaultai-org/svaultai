from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from google_play_billing_bridge import main, publisher
from google_play_billing_bridge.protocol import (
    NONCE_HEADER,
    RESPONSE_SIGNATURE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    NonceReplayCache,
    canonical_json,
    request_signature,
    response_signature,
)


SECRET = b"test-only-bridge-secret-at-least-32-bytes"


def _request(path: str, payload: dict, *, nonce: str = "n" * 32):
    body = canonical_json(payload)
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        TIMESTAMP_HEADER: timestamp,
        NONCE_HEADER: nonce,
        SIGNATURE_HEADER: request_signature(
            secret=SECRET,
            timestamp=timestamp,
            nonce=nonce,
            method="POST",
            path=path,
            body=body,
        ),
    }
    return body, timestamp, headers


def _assert_signed(response, *, timestamp: str, nonce: str):
    expected = response_signature(
        secret=SECRET,
        timestamp=timestamp,
        nonce=nonce,
        status=response.status_code,
        body=response.content,
    )
    assert response.headers[RESPONSE_SIGNATURE_HEADER] == expected


def setup_function():
    main._replay_cache = NonceReplayCache()


def test_public_health_is_non_operative(monkeypatch):
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", SECRET.decode(),
    )
    monkeypatch.setattr(
        main,
        "verify_catalog",
        lambda: (_ for _ in ()).throw(AssertionError("health must not call Google")),
    )
    response = TestClient(main.app).get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_subscription_lookup_requires_hmac_and_signs_response(monkeypatch):
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", SECRET.decode(),
    )
    monkeypatch.setattr(
        main,
        "get_subscription",
        lambda token: {"subscriptionState": "SUBSCRIPTION_STATE_ACTIVE", "token": token},
    )
    body, timestamp, headers = _request(
        "/v1/subscriptions:get", {"purchase_token": "opaque-purchase-token"},
    )
    response = TestClient(main.app).post(
        "/v1/subscriptions:get", content=body, headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["subscription"]["token"] == "opaque-purchase-token"
    _assert_signed(response, timestamp=timestamp, nonce="n" * 32)


def test_invalid_auth_never_reaches_publisher(monkeypatch):
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", SECRET.decode(),
    )
    monkeypatch.setattr(
        main,
        "get_subscription",
        lambda _token: (_ for _ in ()).throw(AssertionError("must not call Google")),
    )
    response = TestClient(main.app).post(
        "/v1/subscriptions:get",
        json={"purchase_token": "opaque-purchase-token"},
    )
    assert response.status_code == 401


def test_nonce_replay_is_rejected_with_authenticated_error(monkeypatch):
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", SECRET.decode(),
    )
    monkeypatch.setattr(main, "get_subscription", lambda _token: {})
    nonce = "r" * 32
    body, timestamp, headers = _request(
        "/v1/subscriptions:get",
        {"purchase_token": "opaque-purchase-token"},
        nonce=nonce,
    )
    client = TestClient(main.app)
    assert client.post(
        "/v1/subscriptions:get", content=body, headers=headers,
    ).status_code == 200
    replay = client.post(
        "/v1/subscriptions:get", content=body, headers=headers,
    )
    assert replay.status_code == 409
    assert replay.json() == {"error": "request_replayed"}
    _assert_signed(replay, timestamp=timestamp, nonce=nonce)


def test_catalog_probe_returns_only_fixed_safe_metadata(monkeypatch):
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", SECRET.decode(),
    )
    safe_result = {
        "adc_resolution": "PASS",
        "adc_identity": publisher.SERVICE_ACCOUNT,
        "android_publisher_api_auth": "PASS",
        "package_name": publisher.PACKAGE_NAME,
        "product_id": publisher.PRODUCT_ID,
        "base_plan_id": publisher.BASE_PLAN_ID,
        "base_plan_type": "AUTO_RENEWING",
        "billing_period": publisher.BILLING_PERIOD,
    }
    monkeypatch.setattr(main, "verify_catalog", lambda: safe_result)
    body, timestamp, headers = _request(
        "/v1/catalog:verify", {"product_id": publisher.PRODUCT_ID},
    )
    response = TestClient(main.app).post(
        "/v1/catalog:verify", content=body, headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == safe_result
    assert "secret" not in json.dumps(response.json()).lower()
    _assert_signed(response, timestamp=timestamp, nonce="n" * 32)


def test_downloadable_google_credentials_are_fail_closed(monkeypatch):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/forbidden/key.json")
    try:
        publisher._assert_fixed_configuration()
    except publisher.PublisherConfigurationError:
        pass
    else:
        raise AssertionError("downloadable credentials must be rejected")


def test_catalog_validation_rejects_prepaid_plan():
    payload = {
        "packageName": publisher.PACKAGE_NAME,
        "productId": publisher.PRODUCT_ID,
        "basePlans": [{
            "basePlanId": publisher.BASE_PLAN_ID,
            "state": "ACTIVE",
            "autoRenewingBasePlanType": {"billingPeriodDuration": "P1M"},
            "prepaidBasePlanType": {"billingPeriodDuration": "P1M"},
        }],
    }
    try:
        publisher.validate_catalog(payload)
    except publisher.PublisherVerificationError:
        pass
    else:
        raise AssertionError("prepaid catalog must be rejected")
