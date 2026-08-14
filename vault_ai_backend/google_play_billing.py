"""Google Play Billing server verification and acknowledgement.

The Android client supplies only an opaque Play purchase token. Entitlements
are derived from the authoritative Android Publisher API response and the
server-owned catalog below; client price, quantity, and status are ignored.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import quote

from billing_entitlements import (
    VerifiedEntitlementUpdate,
    normalize_google_subscription_state,
    supersede_linked_purchase,
    upsert_verified_entitlement,
    utc_from_rfc3339,
)


GOOGLE_PLAY_PACKAGE_NAME = "com.svaultai.app"
GOOGLE_PLAY_PRODUCT_50GB = "svaultai_storage_50gb"
GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO = "monthly-auto"
GOOGLE_PLAY_BASE_PLAN_TYPE = "AUTO_RENEWING"
GOOGLE_PLAY_BILLING_PERIOD = "P1M"
STORAGE_BLOCK_BYTES = 53_687_091_200
INTENDED_MONTHLY_PRICE_CENTS_USD = 2500
GOOGLE_PLAY_CATALOG = {
    GOOGLE_PLAY_PRODUCT_50GB: {
        "quantity": 1,
        "entitlement_bytes": STORAGE_BLOCK_BYTES,
        "plan_id": GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        "plan_type": GOOGLE_PLAY_BASE_PLAN_TYPE,
        "billing_period": GOOGLE_PLAY_BILLING_PERIOD,
    },
}
ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"


class GooglePlayConfigurationError(RuntimeError):
    pass


class GooglePlayVerificationError(RuntimeError):
    pass


class GooglePlayPurchaseNotFoundError(GooglePlayVerificationError):
    """The Publisher API no longer has a purchase for this token."""


class GooglePlayTransientError(RuntimeError):
    pass


@dataclass(frozen=True)
class GooglePlayVerificationResult:
    product_id: str
    normalized_status: str
    provider_status: str
    acknowledged: bool
    entitlement_id: str
    transition: str
    current_period_end: Optional[datetime]


@dataclass(frozen=True)
class GooglePlaySubscriptionSnapshot:
    """Authoritative identity and lifecycle fields from SubscriptionsV2."""

    product_id: str
    plan_id: str
    normalized_status: str
    provider_status: str
    environment: str
    acknowledgement_state: str
    auto_renewing: bool
    cancel_at_period_end: bool
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    linked_purchase_token: str


def purchase_account_token(account_id: str) -> str:
    """Stable non-secret correlator; never sends a vault name to Google."""
    return hashlib.sha256(
        f"svaultai:billing-account:{account_id}".encode("utf-8")
    ).hexdigest()


class GooglePlayPublisherClient:
    def __init__(self, session=None):
        self._session = session

    def _authorized_session(self):
        if self._session is not None:
            return self._session
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
        except ImportError as exc:
            raise GooglePlayConfigurationError(
                "Google server verification dependency is unavailable"
            ) from exc
        credentials, _project = google.auth.default(
            scopes=[ANDROID_PUBLISHER_SCOPE],
        )
        self._session = AuthorizedSession(credentials)
        return self._session

    def get_subscription(self, purchase_token: str) -> Mapping[str, Any]:
        package = _configured_package_name()
        url = (
            "https://androidpublisher.googleapis.com/androidpublisher/v3/"
            f"applications/{quote(package, safe='')}/purchases/"
            f"subscriptionsv2/tokens/{quote(purchase_token, safe='')}"
        )
        response = self._authorized_session().get(url, timeout=20)
        if response.status_code != 200:
            if response.status_code in {401, 403}:
                raise GooglePlayConfigurationError(
                    "Android Publisher credentials are not authorized"
                )
            if response.status_code == 429 or response.status_code >= 500:
                raise GooglePlayTransientError(
                    "Android Publisher verification is temporarily unavailable"
                )
            if response.status_code in {404, 410}:
                raise GooglePlayPurchaseNotFoundError(
                    "Android Publisher purchase was not found"
                )
            raise GooglePlayVerificationError(
                f"Android Publisher verification failed ({response.status_code})"
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise GooglePlayVerificationError(
                "invalid Android Publisher response"
            ) from exc
        if not isinstance(payload, dict):
            raise GooglePlayVerificationError("invalid Android Publisher response")
        return payload

    def acknowledge_subscription(self, product_id: str, purchase_token: str) -> None:
        package = _configured_package_name()
        url = (
            "https://androidpublisher.googleapis.com/androidpublisher/v3/"
            f"applications/{quote(package, safe='')}/purchases/subscriptions/"
            f"{quote(product_id, safe='')}/tokens/"
            f"{quote(purchase_token, safe='')}:acknowledge"
        )
        response = self._authorized_session().post(url, json={}, timeout=20)
        if response.status_code not in {200, 204}:
            raise GooglePlayTransientError(
                f"Google Play acknowledgement failed ({response.status_code})"
            )


def _configured_package_name() -> str:
    configured = os.getenv(
        "VAULTAI_GOOGLE_PLAY_PACKAGE_NAME", GOOGLE_PLAY_PACKAGE_NAME,
    ).strip()
    if configured != GOOGLE_PLAY_PACKAGE_NAME:
        raise GooglePlayConfigurationError("Google Play package name mismatch")
    return configured


def _select_catalog_line(payload: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    lines = payload.get("lineItems")
    if not isinstance(lines, list):
        raise GooglePlayVerificationError("subscription has no line items")
    matches: list[tuple[str, Mapping[str, Any]]] = []
    for raw in lines:
        if not isinstance(raw, dict):
            continue
        product_id = str(raw.get("productId") or "")
        if product_id in GOOGLE_PLAY_CATALOG:
            matches.append((product_id, raw))
    if len(matches) != 1:
        raise GooglePlayVerificationError(
            "subscription product does not match the SVaultAI catalog"
        )
    return matches[0]


def _verified_subscription_snapshot(
    *,
    account_id: str,
    purchase_token: str,
    expected_product_id: Optional[str],
    publisher: GooglePlayPublisherClient,
    enforce_test_purchase_policy: bool,
) -> GooglePlaySubscriptionSnapshot:
    if not purchase_token or len(purchase_token) > 4096:
        raise GooglePlayVerificationError("invalid Google Play purchase token")
    payload = publisher.get_subscription(purchase_token)
    product_id, line = _select_catalog_line(payload)
    if expected_product_id and expected_product_id != product_id:
        raise GooglePlayVerificationError("client product identity mismatch")

    identifiers = payload.get("externalAccountIdentifiers")
    supplied = (
        str(identifiers.get("obfuscatedExternalAccountId") or "")
        if isinstance(identifiers, dict)
        else ""
    )
    if not supplied or supplied != purchase_account_token(account_id):
        raise GooglePlayVerificationError(
            "purchase is not associated with this SVaultAI account"
        )

    expiry = utc_from_rfc3339(line.get("expiryTime"))
    start = utc_from_rfc3339(payload.get("startTime"))
    provider_status = str(payload.get("subscriptionState") or "UNKNOWN")
    normalized = normalize_google_subscription_state(
        provider_status, expiry_time=expiry,
    )
    test_purchase = (
        "testPurchase" in payload and payload.get("testPurchase") is not None
    )
    environment = "sandbox" if test_purchase else "production"
    if enforce_test_purchase_policy and test_purchase and os.getenv(
        "VAULTAI_GOOGLE_PLAY_ALLOW_TEST_PURCHASES", "false",
    ).strip().lower() not in {"1", "true", "yes", "on"}:
        raise GooglePlayVerificationError("Google Play test purchase is not enabled")

    auto_plan = line.get("autoRenewingPlan")
    if not isinstance(auto_plan, dict) or isinstance(line.get("prepaidPlan"), dict):
        raise GooglePlayVerificationError(
            "Google Play purchase is not from the auto-renewing base plan"
        )
    auto_renewing = bool(auto_plan.get("autoRenewEnabled"))
    canceled_at_end = (
        provider_status.upper() == "SUBSCRIPTION_STATE_CANCELED"
        or not auto_renewing
    )
    offer = line.get("offerDetails")
    plan_id = (
        str(offer.get("basePlanId"))
        if isinstance(offer, dict) and offer.get("basePlanId")
        else ""
    )
    if plan_id != GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO:
        raise GooglePlayVerificationError("unexpected Google Play base plan")

    return GooglePlaySubscriptionSnapshot(
        product_id=product_id,
        plan_id=plan_id,
        normalized_status=normalized,
        provider_status=provider_status,
        environment=environment,
        acknowledgement_state=str(payload.get("acknowledgementState") or ""),
        auto_renewing=auto_renewing,
        cancel_at_period_end=canceled_at_end,
        current_period_start=start,
        current_period_end=expiry,
        linked_purchase_token=str(payload.get("linkedPurchaseToken") or ""),
    )


def verify_google_subscription_identity(
    *,
    account_id: str,
    purchase_token: str,
    publisher: Optional[GooglePlayPublisherClient] = None,
) -> GooglePlaySubscriptionSnapshot:
    """Verify a purchase before a revoke-only operation.

    This deliberately cannot acknowledge a purchase or write an entitlement.
    Test-purchase acceptance is irrelevant here because this path only removes
    an already-bound grant.
    """
    return _verified_subscription_snapshot(
        account_id=account_id,
        purchase_token=purchase_token,
        expected_product_id=GOOGLE_PLAY_PRODUCT_50GB,
        publisher=publisher or GooglePlayPublisherClient(),
        enforce_test_purchase_policy=False,
    )


def verify_and_apply_google_subscription(
    *,
    account_id: str,
    purchase_token: str,
    expected_product_id: Optional[str] = None,
    event_id: Optional[str] = None,
    event_time: Optional[datetime] = None,
    publisher: Optional[GooglePlayPublisherClient] = None,
) -> GooglePlayVerificationResult:
    publisher = publisher or GooglePlayPublisherClient()
    snapshot = _verified_subscription_snapshot(
        account_id=account_id,
        purchase_token=purchase_token,
        expected_product_id=expected_product_id,
        publisher=publisher,
        enforce_test_purchase_policy=True,
    )
    update = VerifiedEntitlementUpdate(
        provider="google_play",
        external_purchase_id=purchase_token,
        product_id=snapshot.product_id,
        plan_id=snapshot.plan_id,
        quantity=int(GOOGLE_PLAY_CATALOG[snapshot.product_id]["quantity"]),
        entitlement_bytes=int(
            GOOGLE_PLAY_CATALOG[snapshot.product_id]["entitlement_bytes"]
        ),
        status=snapshot.normalized_status,
        provider_status=snapshot.provider_status,
        environment=snapshot.environment,
        auto_renewing=snapshot.auto_renewing,
        cancel_at_period_end=snapshot.cancel_at_period_end,
        current_period_start=snapshot.current_period_start,
        current_period_end=snapshot.current_period_end,
        provider_event_at=event_time or datetime.now(timezone.utc),
        provider_event_id=event_id,
        metadata={
            "acknowledgement_state": snapshot.acknowledgement_state,
            "account_identifier_verified": True,
            "base_plan_type": GOOGLE_PLAY_BASE_PLAN_TYPE,
            "billing_period": GOOGLE_PLAY_BILLING_PERIOD,
        },
    )
    entitlement_id, transition = upsert_verified_entitlement(account_id, update)
    if snapshot.linked_purchase_token:
        supersede_linked_purchase(
            provider="google_play",
            account_id=account_id,
            linked_purchase_id=snapshot.linked_purchase_token,
            replacement_purchase_id=purchase_token,
        )

    acknowledged = (
        snapshot.acknowledgement_state
        == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    )
    if snapshot.normalized_status in {
        "active", "reactivated", "grace_period",
    } and not acknowledged:
        publisher.acknowledge_subscription(snapshot.product_id, purchase_token)
        acknowledged = True
    return GooglePlayVerificationResult(
        product_id=snapshot.product_id,
        normalized_status=snapshot.normalized_status,
        provider_status=snapshot.provider_status,
        acknowledged=acknowledged,
        entitlement_id=entitlement_id,
        transition=transition,
        current_period_end=snapshot.current_period_end,
    )
