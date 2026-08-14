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
GOOGLE_PLAY_BASE_PLAN_MONTHLY = "monthly"
STORAGE_BLOCK_BYTES = 53_687_091_200
INTENDED_MONTHLY_PRICE_CENTS_USD = 2500
GOOGLE_PLAY_CATALOG = {
    GOOGLE_PLAY_PRODUCT_50GB: {
        "quantity": 1,
        "entitlement_bytes": STORAGE_BLOCK_BYTES,
        "plan_id": GOOGLE_PLAY_BASE_PLAN_MONTHLY,
    },
}
ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"


class GooglePlayConfigurationError(RuntimeError):
    pass


class GooglePlayVerificationError(RuntimeError):
    pass


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
            raise GooglePlayVerificationError(
                f"Android Publisher verification failed ({response.status_code})"
            )
        payload = response.json()
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


def verify_and_apply_google_subscription(
    *,
    account_id: str,
    purchase_token: str,
    expected_product_id: Optional[str] = None,
    event_id: Optional[str] = None,
    event_time: Optional[datetime] = None,
    publisher: Optional[GooglePlayPublisherClient] = None,
) -> GooglePlayVerificationResult:
    if not purchase_token or len(purchase_token) > 4096:
        raise GooglePlayVerificationError("invalid Google Play purchase token")
    publisher = publisher or GooglePlayPublisherClient()
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
    test_purchase = "testPurchase" in payload and payload.get("testPurchase") is not None
    environment = "sandbox" if test_purchase else "production"
    if test_purchase and os.getenv(
        "VAULTAI_GOOGLE_PLAY_ALLOW_TEST_PURCHASES", "false",
    ).strip().lower() not in {"1", "true", "yes", "on"}:
        raise GooglePlayVerificationError("Google Play test purchase is not enabled")

    auto_plan = line.get("autoRenewingPlan")
    auto_renewing = isinstance(auto_plan, dict) and bool(
        auto_plan.get("autoRenewEnabled")
    )
    canceled_at_end = (
        provider_status.upper() == "SUBSCRIPTION_STATE_CANCELED"
        or not auto_renewing
    )
    offer = line.get("offerDetails")
    plan_id = (
        str(offer.get("basePlanId"))
        if isinstance(offer, dict) and offer.get("basePlanId")
        else GOOGLE_PLAY_CATALOG[product_id]["plan_id"]
    )
    # Only the production base plan declared in source can grant production
    # storage. Offers may alter price, but not this entitlement identity.
    if plan_id != GOOGLE_PLAY_BASE_PLAN_MONTHLY:
        raise GooglePlayVerificationError("unexpected Google Play base plan")

    ack_state = str(payload.get("acknowledgementState") or "")
    update = VerifiedEntitlementUpdate(
        provider="google_play",
        external_purchase_id=purchase_token,
        product_id=product_id,
        plan_id=plan_id,
        quantity=int(GOOGLE_PLAY_CATALOG[product_id]["quantity"]),
        entitlement_bytes=int(
            GOOGLE_PLAY_CATALOG[product_id]["entitlement_bytes"]
        ),
        status=normalized,
        provider_status=provider_status,
        environment=environment,
        auto_renewing=auto_renewing,
        cancel_at_period_end=canceled_at_end,
        current_period_start=start,
        current_period_end=expiry,
        provider_event_at=event_time or datetime.now(timezone.utc),
        provider_event_id=event_id,
        metadata={
            "acknowledgement_state": ack_state,
            "account_identifier_verified": True,
        },
    )
    entitlement_id, transition = upsert_verified_entitlement(account_id, update)
    linked_token = str(payload.get("linkedPurchaseToken") or "")
    if linked_token:
        supersede_linked_purchase(
            provider="google_play",
            account_id=account_id,
            linked_purchase_id=linked_token,
            replacement_purchase_id=purchase_token,
        )

    acknowledged = ack_state == "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    if normalized in {"active", "reactivated", "grace_period"} and not acknowledged:
        publisher.acknowledge_subscription(product_id, purchase_token)
        acknowledged = True
    return GooglePlayVerificationResult(
        product_id=product_id,
        normalized_status=normalized,
        provider_status=provider_status,
        acknowledged=acknowledged,
        entitlement_id=entitlement_id,
        transition=transition,
        current_period_end=expiry,
    )
