from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import apple_billing
import billing_entitlements as ent
import google_play_billing as google
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
            "offerDetails": {"basePlanId": google.GOOGLE_PLAY_BASE_PLAN_MONTHLY},
        }],
    }


def test_google_active_purchase_is_server_derived_and_acknowledged(monkeypatch):
    captured = []
    monkeypatch.setattr(
        google,
        "upsert_verified_entitlement",
        lambda account_id, update: (captured.append((account_id, update)) or ("e1", "none_to_active")),
    )
    monkeypatch.setattr(google, "supersede_linked_purchase", lambda **_kwargs: None)
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


def test_google_pending_purchase_never_grants_or_acknowledges(monkeypatch):
    captured = []
    monkeypatch.setattr(
        google,
        "upsert_verified_entitlement",
        lambda _account_id, update: (captured.append(update) or ("e1", "none_to_pending")),
    )
    monkeypatch.setattr(google, "supersede_linked_purchase", lambda **_kwargs: None)
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
        google, "upsert_verified_entitlement",
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
        google, "upsert_verified_entitlement",
        lambda *_args, **_kwargs: pytest.fail("must not write entitlement"),
    )
    with pytest.raises(google.GooglePlayVerificationError):
        google.verify_and_apply_google_subscription(
            account_id="account-1",
            purchase_token="purchase-token",
            publisher=_Publisher(payload),
        )


@pytest.mark.parametrize(
    ("provider_state", "normalized"),
    [
        ("SUBSCRIPTION_STATE_ACTIVE", "active"),
        ("SUBSCRIPTION_STATE_IN_GRACE_PERIOD", "grace_period"),
        ("SUBSCRIPTION_STATE_ON_HOLD", "delinquent"),
        ("SUBSCRIPTION_STATE_EXPIRED", "expired"),
        ("SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED", "canceled"),
    ],
)
def test_google_lifecycle_normalization(provider_state, normalized):
    assert ent.normalize_google_subscription_state(
        provider_state,
        expiry_time=datetime(2099, 1, 1, tzinfo=timezone.utc),
    ) == normalized


def test_rtdn_decoder_requires_message_id_and_base64_json():
    data = base64.b64encode(json.dumps({"packageName": "com.svaultai.app"}).encode()).decode()
    event_id, payload = _decode_pubsub_message({
        "message": {"messageId": "m-1", "data": data},
    })
    assert event_id == "m-1"
    assert payload["packageName"] == "com.svaultai.app"


def test_apple_catalog_is_explicit_and_transaction_mapping_is_verified(monkeypatch):
    monkeypatch.setenv(
        "VAULTAI_APPLE_PRODUCT_MAP_JSON",
        json.dumps({
            "real.product.from.appstore": {
                "quantity": 1,
                "entitlement_bytes": 53_687_091_200,
                "plan_id": "monthly",
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


def test_apple_refund_and_revocation_remove_grant():
    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    assert ent.normalize_apple_transaction_state(
        notification_type="REFUND", expires_at=future, revoked=True,
    ) == "refunded"
    assert ent.normalize_apple_transaction_state(
        notification_type="REVOKE", expires_at=future, revoked=True,
    ) == "revoked"


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
