from __future__ import annotations

import base64
import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import apple_billing
import billing_entitlements as ent
import google_play_billing as google
import routes.provider_billing_routes as provider_routes
from routes.provider_billing_routes import _decode_pubsub_message


class _Publisher:
    def __init__(self, payload):
        self.payload = payload
        self.acknowledged = []

    def get_subscription(self, token):
        assert token == "purchase-token"
        return self.payload

    def acknowledge_subscription(self, product_id, token):
        self.acknowledged.append((product_id, token))


def _google_payload(account_id="account-1", state="SUBSCRIPTION_STATE_ACTIVE"):
    return {
        "subscriptionState": state,
        "acknowledgementState": "ACKNOWLEDGEMENT_STATE_PENDING",
        "startTime": "2026-08-01T00:00:00Z",
        "externalAccountIdentifiers": {
            "obfuscatedExternalAccountId": google.purchase_account_token(account_id),
        },
        "lineItems": [{
            "productId": google.GOOGLE_PLAY_PRODUCT_50GB,
            "expiryTime": "2099-09-01T00:00:00Z",
            "autoRenewingPlan": {"autoRenewEnabled": True},
            "offerDetails": {
                "basePlanId": google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
            },
        }],
    }


def test_google_catalog_matches_active_play_console_plan():
    assert google.GOOGLE_PLAY_PACKAGE_NAME == "com.svaultai.app"
    assert google.GOOGLE_PLAY_PRODUCT_50GB == "svaultai_storage_50gb"
    assert google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO == "monthly-auto"
    assert google.GOOGLE_PLAY_BASE_PLAN_TYPE == "AUTO_RENEWING"
    assert google.GOOGLE_PLAY_BILLING_PERIOD == "P1M"
    catalog = google.GOOGLE_PLAY_CATALOG[google.GOOGLE_PLAY_PRODUCT_50GB]
    assert catalog["plan_id"] == google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO
    assert catalog["plan_type"] == google.GOOGLE_PLAY_BASE_PLAN_TYPE
    assert catalog["billing_period"] == google.GOOGLE_PLAY_BILLING_PERIOD


def test_read_only_adc_probe_requires_exact_active_auto_renewing_plan():
    from scripts.verify_google_play_adc import validate_subscription_payload

    payload = {
        "packageName": google.GOOGLE_PLAY_PACKAGE_NAME,
        "productId": google.GOOGLE_PLAY_PRODUCT_50GB,
        "basePlans": [{
            "basePlanId": google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
            "state": "ACTIVE",
            "autoRenewingBasePlanType": {"billingPeriodDuration": "P1M"},
        }],
    }
    validate_subscription_payload(payload)
    payload["basePlans"][0]["prepaidBasePlanType"] = {
        "billingPeriodDuration": "P1M",
    }
    with pytest.raises(RuntimeError):
        validate_subscription_payload(payload)


def test_google_active_purchase_is_server_derived_and_acknowledged(monkeypatch):
    captured = []
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda account_id, update, **kwargs: (
            captured.append((account_id, update, kwargs))
            or ("e1", "none_to_active")
        ),
    )
    publisher = _Publisher(_google_payload())
    result = google.verify_and_apply_google_subscription(
        account_id="account-1",
        purchase_token="purchase-token",
        expected_product_id=google.GOOGLE_PLAY_PRODUCT_50GB,
        publisher=publisher,
    )
    assert result.acknowledged is True
    assert publisher.acknowledged == [
        (google.GOOGLE_PLAY_PRODUCT_50GB, "purchase-token")
    ]
    update = captured[0][1]
    assert update.entitlement_bytes == 53_687_091_200
    assert update.quantity == 1
    assert update.status == "active"
    assert update.environment == "production"
    assert update.plan_id == "monthly-auto"
    assert update.metadata["base_plan_type"] == "AUTO_RENEWING"
    assert update.metadata["billing_period"] == "P1M"


def test_google_authoritative_test_purchase_is_accepted_only_when_enabled(
    monkeypatch,
):
    payload = _google_payload()
    payload["testPurchase"] = {}
    writes = []
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda account_id, update, **kwargs: (
            writes.append((account_id, update, kwargs))
            or ("e1", "none_to_active")
        ),
    )
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_ALLOW_TEST_PURCHASES", "true")

    result = google.verify_and_apply_google_subscription(
        account_id="account-1",
        purchase_token="purchase-token",
        publisher=_Publisher(payload),
    )

    assert result.normalized_status == "active"
    assert writes[0][1].environment == "sandbox"


def test_google_authoritative_test_purchase_is_rejected_when_disabled(monkeypatch):
    payload = _google_payload()
    payload["testPurchase"] = {}
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_ALLOW_TEST_PURCHASES", "false")
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda *_args, **_kwargs: pytest.fail("must not write entitlement"),
    )

    with pytest.raises(
        google.GooglePlayVerificationError,
        match="test purchase is not enabled",
    ):
        google.verify_and_apply_google_subscription(
            account_id="account-1",
            purchase_token="purchase-token",
            publisher=_Publisher(payload),
        )


def test_google_fabricated_test_token_is_rejected_before_entitlement_write(
    monkeypatch,
):
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_ALLOW_TEST_PURCHASES", "true")
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda *_args, **_kwargs: pytest.fail("must not write entitlement"),
    )

    class MissingPublisher:
        def get_subscription(self, _token):
            raise google.GooglePlayPurchaseNotFoundError("not found")

    with pytest.raises(google.GooglePlayPurchaseNotFoundError):
        google.verify_and_apply_google_subscription(
            account_id="account-1",
            purchase_token="fabricated-token",
            publisher=MissingPublisher(),
        )


def test_google_rejects_wrong_or_prepaid_base_plan(monkeypatch):
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda *_args, **_kwargs: pytest.fail("must not write entitlement"),
    )

    wrong_plan = _google_payload()
    wrong_plan["lineItems"][0]["offerDetails"]["basePlanId"] = "wrong-plan"
    with pytest.raises(google.GooglePlayVerificationError):
        google.verify_and_apply_google_subscription(
            account_id="account-1",
            purchase_token="purchase-token",
            publisher=_Publisher(wrong_plan),
        )

    prepaid = _google_payload()
    prepaid["lineItems"][0].pop("autoRenewingPlan")
    prepaid["lineItems"][0]["prepaidPlan"] = {
        "allowExtendAfterTime": "2099-08-01T00:00:00Z",
    }
    with pytest.raises(google.GooglePlayVerificationError):
        google.verify_and_apply_google_subscription(
            account_id="account-1",
            purchase_token="purchase-token",
            publisher=_Publisher(prepaid),
        )


def test_google_pending_purchase_never_grants_or_acknowledges(monkeypatch):
    captured = []
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda _account_id, update, **_kwargs: (
            captured.append(update) or ("e1", "none_to_pending")
        ),
    )
    publisher = _Publisher(_google_payload(state="SUBSCRIPTION_STATE_PENDING"))
    result = google.verify_and_apply_google_subscription(
        account_id="account-1",
        purchase_token="purchase-token",
        publisher=publisher,
    )
    assert result.normalized_status == "pending"
    assert publisher.acknowledged == []
    assert captured[0].status not in ent.GRANTING_STATUSES


def test_google_account_correlation_mismatch_is_rejected(monkeypatch):
    monkeypatch.setattr(
        google, "reconcile_google_play_storage_entitlement",
        lambda *_args, **_kwargs: pytest.fail("must not write entitlement"),
    )
    with pytest.raises(google.GooglePlayVerificationError):
        google.verify_and_apply_google_subscription(
            account_id="different-account",
            purchase_token="purchase-token",
            publisher=_Publisher(_google_payload(account_id="account-1")),
        )


def test_google_account_correlation_is_required(monkeypatch):
    payload = _google_payload()
    payload.pop("externalAccountIdentifiers")
    monkeypatch.setattr(
        google, "reconcile_google_play_storage_entitlement",
        lambda *_args, **_kwargs: pytest.fail("must not write entitlement"),
    )
    with pytest.raises(google.GooglePlayVerificationError):
        google.verify_and_apply_google_subscription(
            account_id="account-1",
            purchase_token="purchase-token",
            publisher=_Publisher(payload),
        )


def test_google_revoke_identity_check_never_writes_or_acknowledges(monkeypatch):
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda *_args, **_kwargs: pytest.fail("revoke check must not write"),
    )
    publisher = _Publisher(_google_payload())
    snapshot = google.verify_google_subscription_identity(
        account_id="account-1",
        purchase_token="purchase-token",
        publisher=publisher,
    )
    assert snapshot.product_id == google.GOOGLE_PLAY_PRODUCT_50GB
    assert snapshot.plan_id == google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO
    assert publisher.acknowledged == []


def test_google_publisher_distinguishes_voided_purchase_not_found():
    response = SimpleNamespace(status_code=404)
    session = SimpleNamespace(get=lambda *_args, **_kwargs: response)
    client = google.GooglePlayPublisherClient(session=session)
    with pytest.raises(google.GooglePlayPurchaseNotFoundError):
        client.get_subscription("purchase-token")


def test_google_bridge_response_is_authenticated_before_use(monkeypatch):
    secret = "test-only-host-bridge-secret-at-least-32-bytes"
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_BRIDGE_URL", "https://bridge.example")
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", secret)
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL",
        "svaultai-play-billing@svaultai-production.iam.gserviceaccount.com",
    )
    monkeypatch.setattr(google.time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(google.secrets, "token_urlsafe", lambda _size: "n" * 32)
    subscription = _google_payload()

    def post(url, *, content, headers, timeout):
        assert url == "https://bridge.example/v1/subscriptions:get"
        assert timeout == 20
        assert json.loads(content) == {"purchase_token": "purchase-token"}
        expected_request = google.GooglePlayPublisherClient._request_signature(
            secret=secret.encode(),
            timestamp=headers[google.BRIDGE_TIMESTAMP_HEADER],
            nonce=headers[google.BRIDGE_NONCE_HEADER],
            path="/v1/subscriptions:get",
            body=content,
        )
        assert hmac.compare_digest(
            headers[google.BRIDGE_SIGNATURE_HEADER], expected_request,
        )
        response_body = google.GooglePlayPublisherClient._canonical_json(
            {"subscription": subscription},
        )
        response_signature = (
            google.GooglePlayPublisherClient._response_signature(
                secret=secret.encode(),
                timestamp=headers[google.BRIDGE_TIMESTAMP_HEADER],
                nonce=headers[google.BRIDGE_NONCE_HEADER],
                status=200,
                body=response_body,
            )
        )
        return SimpleNamespace(
            status_code=200,
            content=response_body,
            headers={google.BRIDGE_RESPONSE_SIGNATURE_HEADER: response_signature},
        )

    client = google.GooglePlayPublisherClient(bridge_post=post)
    assert client.get_subscription("purchase-token") == subscription


def test_google_bridge_tampered_response_fails_closed(monkeypatch):
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_BRIDGE_URL", "https://bridge.example")
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET",
        "test-only-host-bridge-secret-at-least-32-bytes",
    )

    def post(*_args, **_kwargs):
        return SimpleNamespace(
            status_code=200,
            content=b'{"subscription":{}}',
            headers={google.BRIDGE_RESPONSE_SIGNATURE_HEADER: "v1=invalid"},
        )

    with pytest.raises(google.GooglePlayConfigurationError):
        google.GooglePlayPublisherClient(bridge_post=post).get_subscription(
            "purchase-token"
        )


def test_google_production_forbids_direct_adc_when_bridge_is_absent(monkeypatch):
    monkeypatch.setenv("VAULTAI_ENV", "production")
    monkeypatch.delenv("VAULTAI_GOOGLE_PLAY_BRIDGE_URL", raising=False)
    with pytest.raises(google.GooglePlayConfigurationError):
        google.GooglePlayPublisherClient().get_subscription("purchase-token")


@pytest.mark.parametrize(
    "url",
    [
        "http://bridge.example",
        "https://user@bridge.example",
        "https://bridge.example/unexpected-path",
        "https://bridge.example?token=forbidden",
    ],
)
def test_google_bridge_requires_clean_https_origin(monkeypatch, url):
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_BRIDGE_URL", url)
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", "x" * 32,
    )
    with pytest.raises(google.GooglePlayConfigurationError):
        google.GooglePlayPublisherClient().get_subscription("purchase-token")


@pytest.mark.parametrize(
    ("provider_state", "normalized"),
    [
        ("SUBSCRIPTION_STATE_ACTIVE", "active"),
        ("SUBSCRIPTION_STATE_IN_GRACE_PERIOD", "grace_period"),
        ("SUBSCRIPTION_STATE_ON_HOLD", "delinquent"),
        ("SUBSCRIPTION_STATE_EXPIRED", "expired"),
        ("SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED", "canceled"),
        ("SUBSCRIPTION_STATE_PENDING_PURCHASE_EXPIRED", "canceled"),
        ("SUBSCRIPTION_STATE_REVOKED", "revoked"),
    ],
)
def test_google_lifecycle_normalization(provider_state, normalized):
    assert ent.normalize_google_subscription_state(
        provider_state,
        expiry_time=datetime(2099, 1, 1, tzinfo=timezone.utc),
    ) == normalized


def test_google_empty_device_query_reconciles_to_free_without_ledger(monkeypatch):
    monkeypatch.setattr(
        google, "list_bound_provider_entitlements", lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        google, "get_normalized_account_entitlement", lambda _account_id: None,
    )
    result = google.reconcile_google_subscriptions(
        account_id="account-1",
        current_purchase_tokens=[],
        publisher=SimpleNamespace(),
    )
    assert result.status == "none"
    assert result.has_active_subscription is False
    assert result.current_purchase_count == 0
    assert result.cleared_pending is True


def test_google_missing_bound_pending_purchase_is_canceled(monkeypatch):
    monkeypatch.setattr(
        google,
        "list_bound_provider_entitlements",
        lambda **_kwargs: [{
            "external_purchase_id": "purchase-token",
            "status": "pending",
            "product_id": google.GOOGLE_PLAY_PRODUCT_50GB,
            "plan_id": google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        }],
    )
    terminalized = []
    monkeypatch.setattr(
        google,
        "terminalize_missing_provider_purchase",
        lambda **kwargs: (
            terminalized.append(kwargs) or ("entitlement-1", "pending_to_canceled", "canceled")
        ),
    )
    monkeypatch.setattr(
        google,
        "get_normalized_account_entitlement",
        lambda _account_id: SimpleNamespace(
            status="past_due", has_active_subscription=False,
        ),
    )

    class MissingPublisher:
        def get_subscription(self, _token):
            raise google.GooglePlayPurchaseNotFoundError("gone")

    result = google.reconcile_google_subscriptions(
        account_id="account-1",
        current_purchase_tokens=[],
        publisher=MissingPublisher(),
    )
    assert result.cleared_pending is True
    assert result.has_active_subscription is False
    assert terminalized[0]["provider_status"] == (
        "SUBSCRIPTION_NOT_FOUND_DURING_RECONCILIATION"
    )


def test_google_reconcile_applies_authoritative_pending_cancellation(monkeypatch):
    captured = []
    monkeypatch.setattr(
        google,
        "list_bound_provider_entitlements",
        lambda **_kwargs: [{
            "external_purchase_id": "purchase-token",
            "status": "pending",
            "product_id": google.GOOGLE_PLAY_PRODUCT_50GB,
            "plan_id": google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        }],
    )
    monkeypatch.setattr(
        google,
        "reconcile_google_play_storage_entitlement",
        lambda _account_id, update, **_kwargs: (
            captured.append(update) or ("entitlement-1", "pending_to_canceled")
        ),
    )
    monkeypatch.setattr(
        google,
        "get_normalized_account_entitlement",
        lambda _account_id: SimpleNamespace(
            status="past_due", has_active_subscription=False,
        ),
    )
    publisher = _Publisher(
        _google_payload(state="SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED")
    )
    result = google.reconcile_google_subscriptions(
        account_id="account-1",
        current_purchase_tokens=["purchase-token"],
        publisher=publisher,
    )
    assert captured[0].status == "canceled"
    assert publisher.acknowledged == []
    assert result.has_active_subscription is False
    assert result.status == "past_due"


def test_google_reconcile_accepts_authoritative_non_50gb_catalog_tier(monkeypatch):
    calls = []
    monkeypatch.setattr(
        google, "list_bound_provider_entitlements", lambda **_kwargs: [],
    )
    monkeypatch.setattr(
        google,
        "verify_and_apply_google_subscription",
        lambda **kwargs: (
            calls.append(kwargs)
            or SimpleNamespace(normalized_status="active")
        ),
    )
    monkeypatch.setattr(
        google,
        "get_normalized_account_entitlement",
        lambda _account_id: SimpleNamespace(
            status="active", has_active_subscription=True,
        ),
    )

    result = google.reconcile_google_subscriptions(
        account_id="account-1",
        current_purchase_tokens=["authoritative-100gb-token"],
        publisher=SimpleNamespace(),
    )

    assert calls[0]["expected_product_id"] is None
    assert result.has_active_subscription is True


@pytest.mark.asyncio
async def test_google_reconcile_route_returns_safe_final_state(monkeypatch):
    monkeypatch.setattr(provider_routes, "_account_id", lambda _principal: "account-1")
    monkeypatch.setattr(
        google,
        "reconcile_google_subscriptions",
        lambda **_kwargs: google.GooglePlayReconciliationResult(
            status="none",
            has_active_subscription=False,
            current_purchase_count=0,
            reconciled_count=0,
            cleared_pending=True,
        ),
    )
    response = await provider_routes.reconcile_google_play_purchases(
        provider_routes.GooglePlayReconcileRequest(purchase_tokens=[]),
        principal={"vault_id": "vault-1"},
    )
    assert response == {
        "reconciled": True,
        "provider": "google_play",
        "status": "none",
        "has_active_subscription": False,
        "current_purchase_count": 0,
        "reconciled_count": 0,
        "cleared_pending": True,
    }


def test_rtdn_decoder_requires_message_id_and_base64_json():
    data = base64.b64encode(json.dumps({"packageName": "com.svaultai.app"}).encode()).decode()
    event_id, payload = _decode_pubsub_message({
        "message": {"messageId": "m-1", "data": data},
    })
    assert event_id == "m-1"
    assert payload["packageName"] == "com.svaultai.app"


def _rtdn_envelope(message_id: str, notification: dict) -> dict:
    return {
        "message": {
            "messageId": message_id,
            "data": base64.b64encode(
                json.dumps(notification).encode("utf-8")
            ).decode("ascii"),
        },
    }


def _voided_notification(**overrides) -> dict:
    voided = {
        "purchaseToken": "purchase-token",
        "orderId": "GPA.0000-0000-0000-00000",
        "productType": 1,
        "refundType": 1,
    }
    voided.update(overrides)
    return {
        "version": "1.0",
        "packageName": google.GOOGLE_PLAY_PACKAGE_NAME,
        "eventTimeMillis": str(int(time.time() * 1000)),
        "voidedPurchaseNotification": voided,
    }


def _voided_rtdn_client(monkeypatch, *, authoritative_error=None):
    claimed: set[str] = set()
    calls = {"claimed": [], "finished": [], "verified": [], "revoked": []}

    monkeypatch.setattr(
        provider_routes, "_verify_google_pubsub_request", lambda _request: None,
    )

    def claim(**kwargs):
        calls["claimed"].append(kwargs)
        if kwargs["event_id"] in claimed:
            return False
        claimed.add(kwargs["event_id"])
        return True

    def finish(**kwargs):
        calls["finished"].append(kwargs)

    def verify(**kwargs):
        calls["verified"].append(kwargs)
        if authoritative_error:
            raise authoritative_error
        return SimpleNamespace(
            product_id=google.GOOGLE_PLAY_PRODUCT_50GB,
            plan_id=google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        )

    def revoke(**kwargs):
        calls["revoked"].append(kwargs)
        return "entitlement-1", "active_to_revoked"

    monkeypatch.setattr(ent, "claim_provider_event", claim)
    monkeypatch.setattr(ent, "finish_provider_event", finish)
    monkeypatch.setattr(
        ent, "find_account_for_purchase", lambda *_args: "account-1",
    )
    monkeypatch.setattr(ent, "revoke_verified_purchase_entitlement", revoke)
    monkeypatch.setattr(google, "verify_google_subscription_identity", verify)

    app = FastAPI()
    app.include_router(provider_routes.router)
    return TestClient(app), calls


def test_voided_purchase_notification_reclaims_only_entitlement(monkeypatch):
    client, calls = _voided_rtdn_client(monkeypatch)
    response = client.post(
        "/billing/google-play/rtdn",
        json=_rtdn_envelope("void-1", _voided_notification()),
    )
    assert response.status_code == 200
    assert response.json() == {
        "outcome": "applied",
        "status": "revoked",
        "transition": "active_to_revoked",
    }
    assert len(calls["verified"]) == 1
    assert len(calls["revoked"]) == 1
    revoked = calls["revoked"][0]
    assert revoked["external_purchase_id"] == "purchase-token"
    assert revoked["expected_product_id"] == google.GOOGLE_PLAY_PRODUCT_50GB
    assert revoked["expected_plan_id"] == google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO
    sanitized = calls["claimed"][0]["sanitized_payload"]
    assert "purchase-token" not in repr(sanitized)
    assert "GPA.0000" not in repr(sanitized)


def test_duplicate_voided_notification_is_idempotent(monkeypatch):
    client, calls = _voided_rtdn_client(monkeypatch)
    envelope = _rtdn_envelope("void-duplicate", _voided_notification())
    first = client.post("/billing/google-play/rtdn", json=envelope)
    second = client.post("/billing/google-play/rtdn", json=envelope)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"outcome": "duplicate"}
    assert len(calls["revoked"]) == 1


def test_invalid_voided_notification_is_rejected_without_write(monkeypatch):
    client, calls = _voided_rtdn_client(monkeypatch)
    response = client.post(
        "/billing/google-play/rtdn",
        json=_rtdn_envelope(
            "void-invalid", _voided_notification(refundType=2),
        ),
    )
    assert response.status_code == 400
    assert calls["claimed"] == []
    assert calls["verified"] == []
    assert calls["revoked"] == []


def test_pending_refund_review_notification_is_fail_closed(monkeypatch):
    client, calls = _voided_rtdn_client(monkeypatch)
    notification = {
        "version": "1.0",
        "packageName": google.GOOGLE_PLAY_PACKAGE_NAME,
        "eventTimeMillis": str(int(time.time() * 1000)),
        "pendingRefundReviewNotification": {
            "version": "1.0",
            "pendingRefundToken": "opaque-token",
            "orderId": "GPA.0000-0000-0000-00000",
            "refundReason": 7,
        },
    }
    response = client.post(
        "/billing/google-play/rtdn",
        json=_rtdn_envelope("pending-review", notification),
    )
    assert response.status_code == 400
    assert calls["claimed"] == []
    assert calls["revoked"] == []


def test_voided_notification_rejects_authoritative_identity_mismatch(monkeypatch):
    client, calls = _voided_rtdn_client(
        monkeypatch,
        authoritative_error=google.GooglePlayVerificationError("mismatch"),
    )
    response = client.post(
        "/billing/google-play/rtdn",
        json=_rtdn_envelope("void-mismatch", _voided_notification()),
    )
    assert response.status_code == 400
    assert calls["revoked"] == []
    assert calls["finished"][-1]["outcome"] == "rejected"


def test_voided_notification_reclaims_if_publisher_already_removed_purchase(
    monkeypatch,
):
    client, calls = _voided_rtdn_client(
        monkeypatch,
        authoritative_error=google.GooglePlayPurchaseNotFoundError("gone"),
    )
    response = client.post(
        "/billing/google-play/rtdn",
        json=_rtdn_envelope("void-gone", _voided_notification()),
    )
    assert response.status_code == 200
    assert calls["revoked"][0]["metadata"]["publisher_lookup"] == (
        "not_found_after_void"
    )


def test_revoke_ledger_sql_preserves_user_data_and_history(monkeypatch):
    executed = []
    row = {
        "entitlement_id": "entitlement-1",
        "account_id": "account-1",
        "product_id": google.GOOGLE_PLAY_PRODUCT_50GB,
        "plan_id": google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        "status": "active",
        "current_period_end": datetime(2099, 1, 1, tzinfo=timezone.utc),
        "last_provider_event_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "metadata_jsonb": {"account_identifier_verified": True},
    }

    class Cursor:
        def execute(self, sql, params):
            executed.append((sql, params))

        def fetchone(self):
            return row

    class Connection:
        committed = False
        rolled_back = False

        def cursor(self, **_kwargs):
            return Cursor()

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    connection = Connection()
    monkeypatch.setattr(ent, "get_db", lambda: connection)
    result = ent.revoke_verified_purchase_entitlement(
        provider="google_play",
        account_id="account-1",
        external_purchase_id="purchase-token",
        provider_status="VOIDED_PURCHASE_FULL_REFUND",
        provider_event_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
        provider_event_id="void-1",
        expected_product_id=google.GOOGLE_PLAY_PRODUCT_50GB,
        expected_plan_id=google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
    )
    sql = "\n".join(statement for statement, _params in executed).lower()
    assert result == ("entitlement-1", "active_to_revoked")
    assert "update billing_entitlements" in sql
    assert "insert into subscription_events" in sql
    assert "delete" not in sql
    assert not any(name in sql for name in (
        "vaults", "credentials", "memories", "files", "wallet", "sessions",
    ))
    assert connection.committed is True
    assert connection.rolled_back is False


def test_revoke_ledger_rejects_out_of_order_event(monkeypatch):
    executed = []
    row = {
        "entitlement_id": "entitlement-1",
        "account_id": "account-1",
        "product_id": google.GOOGLE_PLAY_PRODUCT_50GB,
        "plan_id": google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        "status": "active",
        "current_period_end": datetime(2099, 1, 1, tzinfo=timezone.utc),
        "last_provider_event_at": datetime(2026, 8, 15, tzinfo=timezone.utc),
        "metadata_jsonb": {},
    }

    class Cursor:
        def execute(self, sql, params):
            executed.append((sql, params))

        def fetchone(self):
            return row

    class Connection:
        committed = False
        rolled_back = False

        def cursor(self, **_kwargs):
            return Cursor()

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            pass

    connection = Connection()
    monkeypatch.setattr(ent, "get_db", lambda: connection)
    with pytest.raises(ent.StaleProviderEventError):
        ent.revoke_verified_purchase_entitlement(
            provider="google_play",
            account_id="account-1",
            external_purchase_id="purchase-token",
            provider_status="VOIDED_PURCHASE_FULL_REFUND",
            provider_event_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
            provider_event_id="void-stale",
            expected_product_id=google.GOOGLE_PLAY_PRODUCT_50GB,
            expected_plan_id=google.GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        )
    assert len(executed) == 1
    assert connection.committed is False
    assert connection.rolled_back is True


def test_rtdn_jwt_requires_exact_google_claims(monkeypatch):
    from google.oauth2 import id_token

    audience = "https://api.svaultai.com/billing/google-play/rtdn"
    email = "svaultai-play-rtdn-push@svaultai-production.iam.gserviceaccount.com"
    monkeypatch.setenv("VAULTAI_GOOGLE_PLAY_RTDN_AUDIENCE", audience)
    monkeypatch.setenv(
        "VAULTAI_GOOGLE_PLAY_RTDN_SERVICE_ACCOUNT_EMAIL", email,
    )
    now = int(time.time())
    claims = {
        "aud": audience,
        "email": email,
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "sub": "1234567890",
        "iat": now - 10,
        "exp": now + 3500,
    }
    monkeypatch.setattr(
        id_token, "verify_oauth2_token",
        lambda *_args, **_kwargs: dict(claims),
    )
    request = SimpleNamespace(headers={"authorization": "Bearer signed-token"})
    provider_routes._verify_google_pubsub_request(request)

    claims["aud"] = "https://api.svaultai.com/wrong"
    with pytest.raises(HTTPException) as rejected:
        provider_routes._verify_google_pubsub_request(request)
    assert rejected.value.status_code == 403

    claims["aud"] = audience
    claims["email"] = "different@svaultai-production.iam.gserviceaccount.com"
    with pytest.raises(HTTPException) as rejected:
        provider_routes._verify_google_pubsub_request(request)
    assert rejected.value.status_code == 403

    claims["email"] = email
    claims["exp"] = now - 1
    with pytest.raises(HTTPException) as rejected:
        provider_routes._verify_google_pubsub_request(request)
    assert rejected.value.status_code == 401


def test_apple_catalog_is_explicit_and_transaction_mapping_is_verified(monkeypatch):
    monkeypatch.setenv(
        "VAULTAI_APPLE_PRODUCT_MAP_JSON",
        json.dumps({
            "real.product.from.appstore": {
                "quantity": 1,
                "entitlement_bytes": 53_687_091_200,
                "plan_id": "monthly",
                "billing_period": "P1M",
            },
        }),
    )
    transaction = SimpleNamespace(
        productId="real.product.from.appstore",
        transactionId="tx-1",
        originalTransactionId="otx-1",
        purchaseDate=1_786_000_000_000,
        expiresDate=4_102_444_800_000,
        revocationDate=None,
        signedDate=1_786_000_001_000,
    )
    update = apple_billing._transaction_update(
        transaction,
        environment="production",
        notification_type="DID_RENEW",
    )
    assert update.provider == "apple"
    assert update.status == "active"
    assert update.original_transaction_id == "otx-1"
    assert update.entitlement_bytes == 53_687_091_200


@pytest.mark.asyncio
async def test_apple_provider_catalog_returns_only_explicit_product_ids(monkeypatch):
    monkeypatch.setattr(
        provider_routes, "_account_id", lambda _principal: "account-apple-test"
    )
    monkeypatch.setenv(
        "VAULTAI_APPLE_PRODUCT_MAP_JSON",
        json.dumps({
            "svaultai.storage.50gb.monthly": {
                "quantity": 1,
                "entitlement_bytes": 53_687_091_200,
                "plan_id": "monthly",
                "billing_period": "P1M",
            },
        }),
    )

    payload = await provider_routes.billing_providers(
        principal={"vault_id": "synthetic-vault"},
    )

    assert payload["apple"]["configured"] is True
    assert payload["apple"]["product_id"] == "svaultai.storage.50gb.monthly"
    assert payload["apple"]["product_ids"] == [
        "svaultai.storage.50gb.monthly"
    ]
    assert payload["apple"]["billing_period"] == "P1M"
    assert payload["apple"]["storage_entitlement_bytes"] == 53_687_091_200
    assert payload["apple"]["quantity"] == 1
    assert payload["apple"]["products"] == [{
        "product_id": "svaultai.storage.50gb.monthly",
        "billing_period": "P1M",
        "storage_entitlement_bytes": 53_687_091_200,
        "quantity": 1,
        "display_capacity": "50 GB",
    }]


@pytest.mark.asyncio
async def test_google_play_provider_catalog_exposes_exact_storage_allowlist(
    monkeypatch,
):
    monkeypatch.setattr(
        provider_routes, "_account_id", lambda _principal: "account-play-test"
    )

    payload = await provider_routes.billing_providers(
        principal={"vault_id": "synthetic-vault"},
    )

    google_provider = payload["google_play"]
    expected_ids = [
        "svaultai_storage_50gb",
        "svaultai_storage_100gb",
        "svaultai_storage_150gb",
        "svaultai_storage_200gb",
        "svaultai_storage_250gb",
        "svaultai_storage_300gb",
        "svaultai_storage_500gb",
        "svaultai_storage_1tb",
    ]
    assert google_provider["product_id"] == expected_ids[0]
    assert google_provider["product_ids"] == expected_ids
    assert google_provider["base_plan_id"] == "monthly-auto"
    assert google_provider["base_plan_type"] == "AUTO_RENEWING"
    assert google_provider["billing_period"] == "P1M"
    assert [item["product_id"] for item in google_provider["products"]] == expected_ids
    assert [item["tier_rank"] for item in google_provider["products"]] == list(
        range(1, 9)
    )
    assert [item["quantity"] for item in google_provider["products"]] == [
        1, 2, 3, 4, 5, 6, 10, 20,
    ]
    assert [item["display_capacity"] for item in google_provider["products"]] == [
        "50 GB", "100 GB", "150 GB", "200 GB", "250 GB", "300 GB",
        "500 GB", "1 TB",
    ]
    assert all(
        item["base_plan_id"] == "monthly-auto"
        and item["billing_period"] == "P1M"
        for item in google_provider["products"]
    )


@pytest.mark.asyncio
async def test_apple_provider_catalog_does_not_guess_among_multiple_tiers(monkeypatch):
    monkeypatch.setattr(
        provider_routes, "_account_id", lambda _principal: "account-apple-test"
    )
    monkeypatch.setenv(
        "VAULTAI_APPLE_PRODUCT_MAP_JSON",
        json.dumps({
            "synthetic.storage.50gb": {
                "quantity": 1,
                "entitlement_bytes": 53_687_091_200,
                "billing_period": "P1M",
            },
            "synthetic.storage.100gb": {
                "quantity": 2,
                "entitlement_bytes": 107_374_182_400,
                "billing_period": "P1M",
            },
        }),
    )

    payload = await provider_routes.billing_providers(
        principal={"vault_id": "synthetic-vault"},
    )

    assert payload["apple"]["configured"] is True
    assert payload["apple"]["product_id"] is None
    assert payload["apple"]["product_ids"] == [
        "synthetic.storage.100gb",
        "synthetic.storage.50gb",
    ]
    assert payload["apple"]["products"] == [
        {
            "product_id": "synthetic.storage.100gb",
            "billing_period": "P1M",
            "storage_entitlement_bytes": 107_374_182_400,
            "quantity": 2,
            "display_capacity": "100 GB",
        },
        {
            "product_id": "synthetic.storage.50gb",
            "billing_period": "P1M",
            "storage_entitlement_bytes": 53_687_091_200,
            "quantity": 1,
            "display_capacity": "50 GB",
        },
    ]
    assert payload["apple"]["billing_period"] is None
    assert payload["apple"]["storage_entitlement_bytes"] is None
    assert payload["apple"]["quantity"] is None


@pytest.mark.asyncio
async def test_apple_provider_catalog_fails_closed_without_billing_period(
    monkeypatch,
):
    monkeypatch.setattr(
        provider_routes, "_account_id", lambda _principal: "account-apple-test"
    )
    monkeypatch.setenv(
        "VAULTAI_APPLE_PRODUCT_MAP_JSON",
        json.dumps({
            "svaultai.storage.50gb.monthly": {
                "quantity": 1,
                "entitlement_bytes": 53_687_091_200,
                "plan_id": "monthly",
            },
        }),
    )

    payload = await provider_routes.billing_providers(
        principal={"vault_id": "synthetic-vault"},
    )

    assert payload["apple"]["configured"] is False
    assert payload["apple"]["product_id"] is None
    assert payload["apple"]["billing_period"] is None


class _AppleJSONRequest:
    def __init__(self, payload=None, *, error=None):
        self.payload = payload
        self.error = error

    async def json(self):
        if self.error is not None:
            raise self.error
        return self.payload


@pytest.mark.asyncio
async def test_apple_sandbox_notification_is_verified_logged_and_idempotent(
    monkeypatch,
):
    notification = SimpleNamespace(
        notificationUUID="synthetic-notification-event",
        notificationType="TEST",
        subtype=None,
        data=SimpleNamespace(signedTransactionInfo=None),
    )
    verifier = SimpleNamespace()
    monkeypatch.setattr(
        apple_billing,
        "decode_verified_apple_notification",
        lambda _payload: ("sandbox", verifier, notification),
    )
    claims = []
    finishes = []
    inserted = [True, False]
    monkeypatch.setattr(
        ent,
        "claim_provider_event",
        lambda **kwargs: claims.append(dict(kwargs)) or inserted.pop(0),
    )
    monkeypatch.setattr(
        ent,
        "finish_provider_event",
        lambda **kwargs: finishes.append(dict(kwargs)),
    )
    request = _AppleJSONRequest({"signedPayload": "synthetic-signed-jws"})

    first = await provider_routes.apple_notifications_v2(request)
    second = await provider_routes.apple_notifications_v2(request)

    assert first == {"outcome": "verified_no_transaction"}
    assert second == {"outcome": "duplicate"}
    assert claims[0]["signature_verified"] is True
    assert claims[0]["environment"] == "sandbox"
    assert claims[0]["sanitized_payload"] == {
        "notification_type": "TEST",
        "subtype": None,
    }
    assert "synthetic-signed-jws" not in json.dumps(claims)
    assert finishes == [{
        "source": "apple",
        "event_id": "synthetic-notification-event",
        "outcome": "verified_no_transaction",
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "error", "expected_status"),
    [
        ({}, None, 400),
        (None, ValueError("invalid json"), 400),
    ],
)
async def test_apple_unsigned_notification_is_rejected_before_event_log(
    monkeypatch, payload, error, expected_status,
):
    claims = []
    monkeypatch.setattr(
        ent,
        "claim_provider_event",
        lambda **kwargs: claims.append(dict(kwargs)) or True,
    )

    with pytest.raises(HTTPException) as rejected:
        await provider_routes.apple_notifications_v2(
            _AppleJSONRequest(payload, error=error),
        )

    assert rejected.value.status_code == expected_status
    assert claims == []


@pytest.mark.asyncio
async def test_apple_invalid_signature_is_rejected_before_event_log(monkeypatch):
    monkeypatch.setattr(
        apple_billing,
        "decode_verified_apple_notification",
        lambda _payload: (_ for _ in ()).throw(
            apple_billing.AppleTransactionVerificationError("invalid")
        ),
    )
    claims = []
    monkeypatch.setattr(
        ent,
        "claim_provider_event",
        lambda **kwargs: claims.append(dict(kwargs)) or True,
    )

    with pytest.raises(HTTPException) as rejected:
        await provider_routes.apple_notifications_v2(
            _AppleJSONRequest({"signedPayload": "unsigned-or-invalid"}),
        )

    assert rejected.value.status_code == 400
    assert claims == []


@pytest.mark.asyncio
async def test_apple_notification_configuration_failure_requests_retry(monkeypatch):
    monkeypatch.setattr(
        apple_billing,
        "decode_verified_apple_notification",
        lambda _payload: (_ for _ in ()).throw(
            apple_billing.AppleBillingConfigurationError("not configured")
        ),
    )

    with pytest.raises(HTTPException) as rejected:
        await provider_routes.apple_notifications_v2(
            _AppleJSONRequest({"signedPayload": "synthetic-jws"}),
        )

    assert rejected.value.status_code == 503


def test_apple_notification_verifier_accepts_sandbox_only_when_enabled(
    monkeypatch,
):
    calls = []

    class _Verifier:
        def __init__(self, environment):
            self.environment = environment

        def verify_notification(self, _payload):
            calls.append(self.environment)
            if self.environment == "production":
                raise apple_billing.AppleTransactionVerificationError(
                    "wrong environment"
                )
            return "verified-sandbox-notification"

    monkeypatch.setenv("VAULTAI_APPLE_ACCEPT_SANDBOX", "true")
    environment, verifier, notification = (
        apple_billing.decode_verified_apple_notification(
            "synthetic-jws",
            verifier_factory=_Verifier,
        )
    )

    assert calls == ["production", "sandbox"]
    assert environment == "sandbox"
    assert verifier.environment == "sandbox"
    assert notification == "verified-sandbox-notification"


def test_apple_notification_verifier_rejects_sandbox_when_disabled(monkeypatch):
    calls = []

    class _Verifier:
        def __init__(self, environment):
            self.environment = environment

        def verify_notification(self, _payload):
            calls.append(self.environment)
            raise apple_billing.AppleTransactionVerificationError(
                "wrong environment"
            )

    monkeypatch.setenv("VAULTAI_APPLE_ACCEPT_SANDBOX", "false")

    with pytest.raises(apple_billing.AppleTransactionVerificationError):
        apple_billing.decode_verified_apple_notification(
            "synthetic-jws",
            verifier_factory=_Verifier,
        )

    assert calls == ["production"]


@pytest.mark.asyncio
async def test_apple_client_transaction_falls_back_to_sandbox_for_testflight(
    monkeypatch,
):
    calls = []

    def _verify(**kwargs):
        calls.append(kwargs["environment"])
        if kwargs["environment"] == "production":
            raise apple_billing.AppleTransactionVerificationError(
                "wrong environment"
            )
        return {
            "verified": True,
            "provider": "apple",
            "product_id": "svaultai.storage.50gb.monthly",
            "status": "active",
        }

    monkeypatch.setenv("VAULTAI_APPLE_ACCEPT_SANDBOX", "true")
    monkeypatch.setattr(
        apple_billing, "verify_and_apply_apple_transaction", _verify,
    )
    monkeypatch.setattr(provider_routes, "_account_id", lambda _principal: "account")

    result = await provider_routes.verify_apple_transaction(
        provider_routes.AppleTransactionRequest(
            signed_transaction="synthetic-sandbox-jws",
            environment="production",
        ),
        principal={"vault_id": "synthetic-vault"},
    )

    assert calls == ["production", "sandbox"]
    assert result["verified"] is True
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_apple_client_transaction_never_tries_sandbox_when_disabled(
    monkeypatch,
):
    calls = []

    def _verify(**kwargs):
        calls.append(kwargs["environment"])
        raise apple_billing.AppleTransactionVerificationError("invalid")

    monkeypatch.setenv("VAULTAI_APPLE_ACCEPT_SANDBOX", "false")
    monkeypatch.setattr(
        apple_billing, "verify_and_apply_apple_transaction", _verify,
    )
    monkeypatch.setattr(provider_routes, "_account_id", lambda _principal: "account")

    with pytest.raises(HTTPException) as rejected:
        await provider_routes.verify_apple_transaction(
            provider_routes.AppleTransactionRequest(
                signed_transaction="synthetic-invalid-jws",
                environment="production",
            ),
            principal={"vault_id": "synthetic-vault"},
        )

    assert rejected.value.status_code == 400
    assert calls == ["production"]


def test_apple_refund_and_revocation_remove_grant():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert ent.normalize_apple_transaction_state(
        notification_type="REFUND", expires_at=future, revoked=True,
    ) == "refunded"
    assert ent.normalize_apple_transaction_state(
        notification_type="REVOKE", expires_at=future, revoked=True,
    ) == "revoked"


def test_apple_transaction_requires_app_account_token(monkeypatch):
    monkeypatch.setenv(
        "VAULTAI_APPLE_PRODUCT_MAP_JSON",
        json.dumps({
            "svaultai.storage.50gb.monthly": {
                "quantity": 1,
                "entitlement_bytes": 53_687_091_200,
                "plan_id": "monthly",
            },
        }),
    )
    transaction = SimpleNamespace(
        productId="svaultai.storage.50gb.monthly",
        transactionId="tx-1",
        originalTransactionId="otx-1",
        appAccountToken=None,
        purchaseDate=1_786_000_000_000,
        expiresDate=4_102_444_800_000,
        revocationDate=None,
        signedDate=1_786_000_001_000,
    )
    verifier = SimpleNamespace(verify_transaction=lambda _jws: transaction)
    monkeypatch.setattr(
        apple_billing,
        "upsert_verified_entitlement",
        lambda *_args, **_kwargs: pytest.fail("unbound purchase must not grant"),
    )
    with pytest.raises(apple_billing.AppleTransactionVerificationError):
        apple_billing.verify_and_apply_apple_transaction(
            account_id="account-1",
            signed_transaction="signed-jws",
            environment="production",
            verifier=verifier,
        )


def test_apple_library_enums_use_wire_values():
    from appstoreserverlibrary.models.NotificationTypeV2 import NotificationTypeV2
    from appstoreserverlibrary.models.Subtype import Subtype

    assert apple_billing.enum_text(NotificationTypeV2.DID_RENEW) == "DID_RENEW"
    assert apple_billing.enum_text(Subtype.GRACE_PERIOD) == "GRACE_PERIOD"


def test_schema_and_routes_preserve_history_and_retire_checkout():
    root = Path(__file__).parent
    migration = (root / "migrations/versions/0042_provider_neutral_billing.py").read_text()
    stripe_routes = (root / "routes/stripe_routes.py").read_text()
    main = (root / "main.py").read_text()
    assert "UNIQUE (provider, external_purchase_id)" in migration
    assert "data-preserving no-op" in migration
    checkout_window = stripe_routes[stripe_routes.index("async def create_checkout_session_endpoint"):]
    assert checkout_window.index("checkout_provider_retired") < checkout_window.index("from stripe_service import")
    lifespan = main[main.index("async def lifespan"):main.index("app = FastAPI")]
    assert "probe_stripe" not in lifespan


def test_billing_request_contracts_accept_only_provider_proof():
    from routes.provider_billing_routes import (
        AppleTransactionRequest,
        GooglePlayVerifyRequest,
    )
    assert set(GooglePlayVerifyRequest.model_fields) == {
        "purchase_token", "product_id",
    }
    assert set(AppleTransactionRequest.model_fields) == {
        "signed_transaction", "environment",
    }
    ledger_fields = set(ent.VerifiedEntitlementUpdate.__dataclass_fields__)
    assert not ledger_fields.intersection({
        "pin", "mvk", "private_key", "seed_phrase", "vault_plaintext",
    })
