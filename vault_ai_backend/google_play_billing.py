"""Google Play Billing server verification and acknowledgement.

The Android client supplies only an opaque Play purchase token. Entitlements
are derived from the authoritative Android Publisher API response and the
server-owned catalog below; client price, quantity, and status are ignored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from urllib.parse import quote, urlparse

import httpx

from billing_entitlements import (
    ScheduledEntitlementReplacement,
    VerifiedEntitlementUpdate,
    get_normalized_account_entitlement,
    list_bound_provider_entitlements,
    normalize_google_subscription_state,
    reconcile_google_play_storage_entitlement,
    terminalize_missing_provider_purchase,
    utc_from_rfc3339,
)


GOOGLE_PLAY_PACKAGE_NAME = "com.svaultai.app"
GOOGLE_PLAY_PRODUCT_50GB = "svaultai_storage_50gb"
GOOGLE_PLAY_PRODUCT_100GB = "svaultai_storage_100gb"
GOOGLE_PLAY_PRODUCT_150GB = "svaultai_storage_150gb"
GOOGLE_PLAY_PRODUCT_200GB = "svaultai_storage_200gb"
GOOGLE_PLAY_PRODUCT_250GB = "svaultai_storage_250gb"
GOOGLE_PLAY_PRODUCT_300GB = "svaultai_storage_300gb"
GOOGLE_PLAY_PRODUCT_500GB = "svaultai_storage_500gb"
GOOGLE_PLAY_PRODUCT_1TB = "svaultai_storage_1tb"
GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO = "monthly-auto"
GOOGLE_PLAY_BASE_PLAN_TYPE = "AUTO_RENEWING"
GOOGLE_PLAY_BILLING_PERIOD = "P1M"
GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL = (
    "svaultai-play-billing@svaultai-production.iam.gserviceaccount.com"
)
STORAGE_BLOCK_BYTES = 53_687_091_200
INTENDED_MONTHLY_PRICE_CENTS_USD = 2500


@dataclass(frozen=True)
class GooglePlayStorageTier:
    product_id: str
    base_plan_id: str
    billing_period: str
    tier_rank: int
    display_capacity: str
    storage_bytes: int
    quantity: int


def _storage_tier(
    product_id: str,
    *,
    tier_rank: int,
    display_capacity: str,
    quantity: int,
) -> GooglePlayStorageTier:
    return GooglePlayStorageTier(
        product_id=product_id,
        base_plan_id=GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
        billing_period=GOOGLE_PLAY_BILLING_PERIOD,
        tier_rank=tier_rank,
        display_capacity=display_capacity,
        storage_bytes=STORAGE_BLOCK_BYTES * quantity,
        quantity=quantity,
    )


_GOOGLE_PLAY_STORAGE_TIERS = (
    _storage_tier(
        GOOGLE_PLAY_PRODUCT_50GB,
        tier_rank=1,
        display_capacity="50 GB",
        quantity=1,
    ),
    _storage_tier(
        GOOGLE_PLAY_PRODUCT_100GB,
        tier_rank=2,
        display_capacity="100 GB",
        quantity=2,
    ),
    _storage_tier(
        GOOGLE_PLAY_PRODUCT_150GB,
        tier_rank=3,
        display_capacity="150 GB",
        quantity=3,
    ),
    _storage_tier(
        GOOGLE_PLAY_PRODUCT_200GB,
        tier_rank=4,
        display_capacity="200 GB",
        quantity=4,
    ),
    _storage_tier(
        GOOGLE_PLAY_PRODUCT_250GB,
        tier_rank=5,
        display_capacity="250 GB",
        quantity=5,
    ),
    _storage_tier(
        GOOGLE_PLAY_PRODUCT_300GB,
        tier_rank=6,
        display_capacity="300 GB",
        quantity=6,
    ),
    _storage_tier(
        GOOGLE_PLAY_PRODUCT_500GB,
        tier_rank=7,
        display_capacity="500 GB",
        quantity=10,
    ),
    # Preserve the existing 50 GiB quota convention: this is exactly twenty
    # existing blocks, so no current customer's capacity is redefined.
    _storage_tier(
        GOOGLE_PLAY_PRODUCT_1TB,
        tier_rank=8,
        display_capacity="1 TB",
        quantity=20,
    ),
)

# The tuple key is the security boundary. Product id alone is never enough to
# derive an entitlement because a future base plan could carry other terms.
GOOGLE_PLAY_STORAGE_CATALOG: Mapping[
    tuple[str, str], GooglePlayStorageTier
] = MappingProxyType({
    (tier.product_id, tier.base_plan_id): tier
    for tier in _GOOGLE_PLAY_STORAGE_TIERS
})

# Read-only compatibility view for diagnostics and existing callers. New
# verification code uses GOOGLE_PLAY_STORAGE_CATALOG exclusively.
GOOGLE_PLAY_CATALOG: Mapping[str, Mapping[str, Any]] = MappingProxyType({
    tier.product_id: MappingProxyType({
        "quantity": tier.quantity,
        "entitlement_bytes": tier.storage_bytes,
        "plan_id": tier.base_plan_id,
        "plan_type": GOOGLE_PLAY_BASE_PLAN_TYPE,
        "billing_period": tier.billing_period,
        "tier_rank": tier.tier_rank,
        "display_capacity": tier.display_capacity,
    })
    for tier in _GOOGLE_PLAY_STORAGE_TIERS
})
ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
BRIDGE_PROTOCOL_VERSION = "v1"
BRIDGE_TIMESTAMP_HEADER = "X-SVaultAI-Timestamp"
BRIDGE_NONCE_HEADER = "X-SVaultAI-Nonce"
BRIDGE_SIGNATURE_HEADER = "X-SVaultAI-Signature"
BRIDGE_RESPONSE_SIGNATURE_HEADER = "X-SVaultAI-Response-Signature"


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
    scheduled_product_id: str = ""
    scheduled_effective_at: Optional[datetime] = None


@dataclass(frozen=True)
class GooglePlayReconciliationResult:
    status: str
    has_active_subscription: bool
    current_purchase_count: int
    reconciled_count: int
    cleared_pending: bool


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
    scheduled_product_id: str = ""
    scheduled_plan_id: str = ""
    scheduled_entitlement_bytes: int = 0
    scheduled_effective_at: Optional[datetime] = None
    replacement_mode: str = ""


@dataclass(frozen=True)
class _SelectedStorageEntitlement:
    current_tier: GooglePlayStorageTier
    current_line: Mapping[str, Any]
    scheduled_tier: Optional[GooglePlayStorageTier] = None
    scheduled_effective_at: Optional[datetime] = None
    replacement_mode: str = ""


def purchase_account_token(account_id: str) -> str:
    """Stable non-secret correlator; never sends a vault name to Google."""
    return hashlib.sha256(
        f"svaultai:billing-account:{account_id}".encode("utf-8")
    ).hexdigest()


class GooglePlayPublisherClient:
    def __init__(self, session=None, *, bridge_post=None):
        self._session = session
        self._bridge_post = bridge_post

    @staticmethod
    def _bridge_configuration() -> tuple[str, bytes] | None:
        raw_url = os.getenv("VAULTAI_GOOGLE_PLAY_BRIDGE_URL", "").strip()
        if not raw_url:
            return None
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
            raise GooglePlayConfigurationError(
                "downloadable Google credentials are forbidden with the bridge"
            )
        parsed = urlparse(raw_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise GooglePlayConfigurationError(
                "Google Play bridge URL must be an HTTPS origin"
            )
        secret = os.getenv(
            "VAULTAI_GOOGLE_PLAY_BRIDGE_HMAC_SECRET", "",
        ).strip().encode("utf-8")
        if len(secret) < 32:
            raise GooglePlayConfigurationError(
                "Google Play bridge authentication is not configured"
            )
        return raw_url.rstrip("/"), secret

    @staticmethod
    def _canonical_json(payload: Mapping[str, Any]) -> bytes:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    @staticmethod
    def _request_signature(
        *, secret: bytes, timestamp: str, nonce: str, path: str, body: bytes,
    ) -> str:
        digest = hashlib.sha256(body).hexdigest()
        canonical = (
            f"{BRIDGE_PROTOCOL_VERSION}\n{timestamp}\n{nonce}\n"
            f"POST\n{path}\n{digest}"
        ).encode("utf-8")
        return "v1=" + hmac.new(secret, canonical, hashlib.sha256).hexdigest()

    @staticmethod
    def _response_signature(
        *, secret: bytes, timestamp: str, nonce: str, status: int, body: bytes,
    ) -> str:
        digest = hashlib.sha256(body).hexdigest()
        canonical = (
            f"{BRIDGE_PROTOCOL_VERSION}\n{timestamp}\n{nonce}\n"
            f"{status}\n{digest}"
        ).encode("utf-8")
        return "v1=" + hmac.new(secret, canonical, hashlib.sha256).hexdigest()

    def _bridge_request(
        self, path: str, payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        configuration = self._bridge_configuration()
        if configuration is None:
            raise GooglePlayConfigurationError(
                "Google Play bridge is not configured"
            )
        base_url, secret = configuration
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(24)
        body = self._canonical_json(payload)
        signature = self._request_signature(
            secret=secret,
            timestamp=timestamp,
            nonce=nonce,
            path=path,
            body=body,
        )
        post = self._bridge_post or httpx.post
        try:
            response = post(
                f"{base_url}{path}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    BRIDGE_TIMESTAMP_HEADER: timestamp,
                    BRIDGE_NONCE_HEADER: nonce,
                    BRIDGE_SIGNATURE_HEADER: signature,
                },
                timeout=20,
            )
        except Exception as exc:
            raise GooglePlayTransientError(
                "Google Play bridge is temporarily unavailable"
            ) from exc

        response_body = bytes(response.content)
        supplied_response_signature = str(
            response.headers.get(BRIDGE_RESPONSE_SIGNATURE_HEADER, "")
        )
        expected_response_signature = self._response_signature(
            secret=secret,
            timestamp=timestamp,
            nonce=nonce,
            status=int(response.status_code),
            body=response_body,
        )
        if not hmac.compare_digest(
            supplied_response_signature, expected_response_signature,
        ):
            raise GooglePlayConfigurationError(
                "Google Play bridge response authentication failed"
            )
        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except Exception as exc:
            raise GooglePlayVerificationError(
                "invalid Google Play bridge response"
            ) from exc
        if not isinstance(decoded, dict):
            raise GooglePlayVerificationError(
                "invalid Google Play bridge response"
            )
        status = int(response.status_code)
        error_code = str(decoded.get("error") or "")
        if status == 404 and error_code == "purchase_not_found":
            raise GooglePlayPurchaseNotFoundError(
                "Android Publisher purchase was not found"
            )
        if status in {401, 403}:
            raise GooglePlayConfigurationError(
                "Google Play bridge authentication was rejected"
            )
        if status == 429 or status >= 500 or status == 409:
            raise GooglePlayTransientError(
                "Google Play bridge is temporarily unavailable"
            )
        if status != 200:
            raise GooglePlayVerificationError(
                f"Google Play bridge request failed ({status})"
            )
        return decoded

    def _authorized_session(self):
        if self._session is not None:
            return self._session
        if os.getenv("VAULTAI_ENV", "").strip().lower() in {
            "production", "prod", "live",
        }:
            raise GooglePlayConfigurationError(
                "the production Google Play bridge is not configured"
            )
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
        if self._session is None and self._bridge_configuration() is not None:
            result = self._bridge_request(
                "/v1/subscriptions:get",
                {"purchase_token": purchase_token},
            )
            subscription = result.get("subscription")
            if not isinstance(subscription, dict):
                raise GooglePlayVerificationError(
                    "invalid Google Play bridge response"
                )
            return subscription
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
        if self._session is None and self._bridge_configuration() is not None:
            result = self._bridge_request(
                "/v1/subscriptions:acknowledge",
                {"product_id": product_id, "purchase_token": purchase_token},
            )
            if result.get("acknowledged") is not True:
                raise GooglePlayVerificationError(
                    "invalid Google Play bridge acknowledgement"
                )
            return
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

    def verify_catalog(self) -> Mapping[str, Any]:
        result = self._bridge_request(
            "/v1/catalog:verify",
            {"product_id": GOOGLE_PLAY_PRODUCT_50GB},
        )
        expected = {
            "adc_resolution": "PASS",
            "adc_identity": os.getenv(
                "VAULTAI_GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL",
                GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL,
            ).strip().lower(),
            "android_publisher_api_auth": "PASS",
            "package_name": GOOGLE_PLAY_PACKAGE_NAME,
            "product_id": GOOGLE_PLAY_PRODUCT_50GB,
            "base_plan_id": GOOGLE_PLAY_BASE_PLAN_MONTHLY_AUTO,
            "base_plan_type": GOOGLE_PLAY_BASE_PLAN_TYPE,
            "billing_period": GOOGLE_PLAY_BILLING_PERIOD,
        }
        if any(str(result.get(key) or "") != value for key, value in expected.items()):
            raise GooglePlayVerificationError(
                "Google Play bridge catalog verification mismatch"
            )
        return result


def _configured_package_name() -> str:
    configured = os.getenv(
        "VAULTAI_GOOGLE_PLAY_PACKAGE_NAME", GOOGLE_PLAY_PACKAGE_NAME,
    ).strip()
    if configured != GOOGLE_PLAY_PACKAGE_NAME:
        raise GooglePlayConfigurationError("Google Play package name mismatch")
    return configured


def _catalog_tier_for_line(
    raw: Mapping[str, Any],
) -> tuple[GooglePlayStorageTier, Optional[datetime]]:
    product_id = str(raw.get("productId") or "")
    offer = raw.get("offerDetails")
    plan_id = (
        str(offer.get("basePlanId") or "")
        if isinstance(offer, dict)
        else ""
    )
    tier = GOOGLE_PLAY_STORAGE_CATALOG.get((product_id, plan_id))
    if tier is None:
        raise GooglePlayVerificationError(
            "subscription product or base plan is not allowlisted"
        )
    auto_plan = raw.get("autoRenewingPlan")
    if not isinstance(auto_plan, dict) or isinstance(raw.get("prepaidPlan"), dict):
        raise GooglePlayVerificationError(
            "Google Play purchase is not from the auto-renewing base plan"
        )
    return tier, utc_from_rfc3339(raw.get("expiryTime"))


def _select_catalog_entitlement(
    payload: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
) -> _SelectedStorageEntitlement:
    """Select one current total-capacity tier from SubscriptionPurchaseV2.

    ReplacementMode.DEFERRED returns two allowlisted line items: the current
    item has a future expiry and names its deferred replacement, while the
    scheduled item has no expiry yet. Only the current item grants storage.
    """
    lines = payload.get("lineItems")
    if not isinstance(lines, list) or not lines:
        raise GooglePlayVerificationError("subscription has no line items")
    parsed: list[
        tuple[GooglePlayStorageTier, Mapping[str, Any], Optional[datetime]]
    ] = []
    for raw in lines:
        if not isinstance(raw, dict):
            raise GooglePlayVerificationError("subscription line item is invalid")
        tier, expiry = _catalog_tier_for_line(raw)
        parsed.append((tier, raw, expiry))

    now = now or datetime.now(timezone.utc)
    future = [item for item in parsed if item[2] is not None and item[2] > now]
    pending = [item for item in parsed if item[2] is None]
    if len(future) > 1:
        raise GooglePlayVerificationError(
            "multiple Google Play storage tiers cannot grant concurrently"
        )

    scheduled_tier: Optional[GooglePlayStorageTier] = None
    scheduled_effective_at: Optional[datetime] = None
    replacement_mode = ""
    if future:
        current_tier, current_line, current_expiry = future[0]
        deferred = current_line.get("deferredItemReplacement")
        if deferred is not None:
            if not isinstance(deferred, dict):
                raise GooglePlayVerificationError(
                    "deferred replacement details are invalid"
                )
            target_product_id = str(deferred.get("productId") or "")
            target_lines = [item for item in pending if item[0].product_id == target_product_id]
            if len(parsed) != 2 or len(target_lines) != 1:
                raise GooglePlayVerificationError(
                    "deferred replacement does not identify one future tier"
                )
            scheduled_tier, target_line, _unused_expiry = target_lines[0]
            if scheduled_tier.tier_rank >= current_tier.tier_rank:
                raise GooglePlayVerificationError(
                    "deferred storage replacement must be a lower tier"
                )
            item_replacement = target_line.get("itemReplacement")
            if item_replacement is not None:
                if not isinstance(item_replacement, dict):
                    raise GooglePlayVerificationError(
                        "replacement details are invalid"
                    )
                replacement_mode = str(
                    item_replacement.get("replacementMode") or ""
                ).upper()
                if replacement_mode not in {"", "DEFERRED"}:
                    raise GooglePlayVerificationError(
                        "scheduled storage replacement is not deferred"
                    )
            replacement_mode = replacement_mode or "DEFERRED"
            scheduled_effective_at = current_expiry
        elif pending:
            raise GooglePlayVerificationError(
                "future storage tier is missing deferred replacement linkage"
            )
    elif pending:
        if len(parsed) != 1 or len(pending) != 1:
            raise GooglePlayVerificationError(
                "pending subscription does not identify one storage tier"
            )
        current_tier, current_line, _unused_expiry = pending[0]
    else:
        # Expired payloads can retain historic line items. Select only the
        # most recently expired tier so historical products never stack.
        current_tier, current_line, _unused_expiry = max(
            parsed,
            key=lambda item: item[2] or datetime.min.replace(tzinfo=timezone.utc),
        )

    item_replacement = current_line.get("itemReplacement")
    if item_replacement is not None:
        if not isinstance(item_replacement, dict):
            raise GooglePlayVerificationError("replacement details are invalid")
        replaced_product = str(item_replacement.get("productId") or "")
        replaced_plan = str(item_replacement.get("basePlanId") or "")
        if (replaced_product, replaced_plan) not in GOOGLE_PLAY_STORAGE_CATALOG:
            raise GooglePlayVerificationError(
                "replaced subscription tier is not allowlisted"
            )
        replacement_mode = str(
            item_replacement.get("replacementMode") or replacement_mode
        ).upper()

    return _SelectedStorageEntitlement(
        current_tier=current_tier,
        current_line=current_line,
        scheduled_tier=scheduled_tier,
        scheduled_effective_at=scheduled_effective_at,
        replacement_mode=replacement_mode,
    )


def _verified_subscription_snapshot(
    *,
    account_id: str,
    purchase_token: str,
    expected_product_id: Optional[str],
    publisher: GooglePlayPublisherClient,
    enforce_test_purchase_policy: bool,
    authoritative_payload: Optional[Mapping[str, Any]] = None,
) -> GooglePlaySubscriptionSnapshot:
    if not purchase_token or len(purchase_token) > 4096:
        raise GooglePlayVerificationError("invalid Google Play purchase token")
    payload = (
        authoritative_payload
        if authoritative_payload is not None
        else publisher.get_subscription(purchase_token)
    )
    selected = _select_catalog_entitlement(payload)
    product_id = selected.current_tier.product_id
    line = selected.current_line
    expected_products = {product_id}
    if selected.scheduled_tier is not None:
        expected_products.add(selected.scheduled_tier.product_id)
    if expected_product_id and expected_product_id not in expected_products:
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
    plan_id = selected.current_tier.base_plan_id

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
        scheduled_product_id=(
            selected.scheduled_tier.product_id
            if selected.scheduled_tier is not None
            else ""
        ),
        scheduled_plan_id=(
            selected.scheduled_tier.base_plan_id
            if selected.scheduled_tier is not None
            else ""
        ),
        scheduled_entitlement_bytes=(
            selected.scheduled_tier.storage_bytes
            if selected.scheduled_tier is not None
            else 0
        ),
        scheduled_effective_at=selected.scheduled_effective_at,
        replacement_mode=selected.replacement_mode,
    )


def verify_google_subscription_identity(
    *,
    account_id: str,
    purchase_token: str,
    publisher: Optional[GooglePlayPublisherClient] = None,
    authoritative_payload: Optional[Mapping[str, Any]] = None,
) -> GooglePlaySubscriptionSnapshot:
    """Verify a purchase before a revoke-only operation.

    This deliberately cannot acknowledge a purchase or write an entitlement.
    Test-purchase acceptance is irrelevant here because this path only removes
    an already-bound grant.
    """
    return _verified_subscription_snapshot(
        account_id=account_id,
        purchase_token=purchase_token,
        expected_product_id=None,
        publisher=publisher or GooglePlayPublisherClient(),
        enforce_test_purchase_policy=False,
        authoritative_payload=authoritative_payload,
    )


def verify_and_apply_google_subscription(
    *,
    account_id: str,
    purchase_token: str,
    expected_product_id: Optional[str] = None,
    event_id: Optional[str] = None,
    event_time: Optional[datetime] = None,
    publisher: Optional[GooglePlayPublisherClient] = None,
    authoritative_payload: Optional[Mapping[str, Any]] = None,
) -> GooglePlayVerificationResult:
    publisher = publisher or GooglePlayPublisherClient()
    snapshot = _verified_subscription_snapshot(
        account_id=account_id,
        purchase_token=purchase_token,
        expected_product_id=expected_product_id,
        publisher=publisher,
        enforce_test_purchase_policy=True,
        authoritative_payload=authoritative_payload,
    )
    tier = GOOGLE_PLAY_STORAGE_CATALOG.get((snapshot.product_id, snapshot.plan_id))
    if tier is None:
        raise GooglePlayVerificationError(
            "verified subscription tier is not allowlisted"
        )
    scheduled = (
        ScheduledEntitlementReplacement(
            product_id=snapshot.scheduled_product_id,
            plan_id=snapshot.scheduled_plan_id,
            entitlement_bytes=snapshot.scheduled_entitlement_bytes,
            effective_at=snapshot.scheduled_effective_at,
        )
        if snapshot.scheduled_product_id and snapshot.scheduled_effective_at
        else None
    )
    update = VerifiedEntitlementUpdate(
        provider="google_play",
        external_purchase_id=purchase_token,
        product_id=snapshot.product_id,
        plan_id=snapshot.plan_id,
        quantity=tier.quantity,
        entitlement_bytes=tier.storage_bytes,
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
            "tier_rank": tier.tier_rank,
            "display_capacity": tier.display_capacity,
            "replacement_mode": snapshot.replacement_mode or None,
            "scheduled_product_id": snapshot.scheduled_product_id or None,
        },
    )
    entitlement_id, transition = reconcile_google_play_storage_entitlement(
        account_id,
        update,
        linked_purchase_id=snapshot.linked_purchase_token,
        scheduled_replacement=scheduled,
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
        scheduled_product_id=snapshot.scheduled_product_id,
        scheduled_effective_at=snapshot.scheduled_effective_at,
    )


def reconcile_google_subscriptions(
    *,
    account_id: str,
    current_purchase_tokens: list[str],
    publisher: Optional[GooglePlayPublisherClient] = None,
) -> GooglePlayReconciliationResult:
    """Refresh device-visible and server-bound purchases from Google Play.

    Device tokens are identifiers only; every lifecycle decision comes from
    SubscriptionsV2. Server-bound non-terminal tokens are also checked so an
    empty BillingClient result can clear a stale pending row safely.
    """
    if not account_id:
        raise GooglePlayVerificationError("billing account is required")
    if len(current_purchase_tokens) > 20:
        raise GooglePlayVerificationError("too many Google Play purchase tokens")

    current: list[str] = []
    seen: set[str] = set()
    for raw in current_purchase_tokens:
        token = str(raw or "").strip()
        if not token or len(token) > 4096:
            raise GooglePlayVerificationError("invalid Google Play purchase token")
        if token not in seen:
            seen.add(token)
            current.append(token)

    bound_rows = list_bound_provider_entitlements(
        provider="google_play", account_id=account_id,
    )
    bound = {
        str(row["external_purchase_id"]): row
        for row in bound_rows
        if row.get("external_purchase_id")
    }
    tokens = list(current)
    for token, row in bound.items():
        if (
            str(row.get("status") or "")
            not in {"canceled", "expired", "revoked", "refunded"}
            and token not in seen
        ):
            seen.add(token)
            tokens.append(token)

    publisher = publisher or GooglePlayPublisherClient()
    reconciled_count = 0
    cleared_server_pending = False
    for token in tokens:
        try:
            verify_and_apply_google_subscription(
                account_id=account_id,
                purchase_token=token,
                # BillingClient reconciliation supplies purchase tokens, not a
                # trusted product identity. The authoritative V2 response is
                # allowlisted against the complete one-of-N tier catalog.
                expected_product_id=None,
                publisher=publisher,
            )
            reconciled_count += 1
        except GooglePlayPurchaseNotFoundError:
            existing = bound.get(token)
            if existing is None:
                # An unbound device token cannot remove or create entitlement.
                continue
            previous = str(existing.get("status") or "")
            now = datetime.now(timezone.utc)
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
            terminalize_missing_provider_purchase(
                provider="google_play",
                account_id=account_id,
                external_purchase_id=token,
                provider_status="SUBSCRIPTION_NOT_FOUND_DURING_RECONCILIATION",
                provider_event_at=now,
                provider_event_id=(
                    f"reconcile-missing-{digest}-{time.time_ns()}"
                ),
            )
            reconciled_count += 1
            cleared_server_pending = cleared_server_pending or previous == "pending"

    entitlement = get_normalized_account_entitlement(account_id)
    status = entitlement.status if entitlement is not None else "none"
    active = bool(
        entitlement is not None and entitlement.has_active_subscription
    )
    return GooglePlayReconciliationResult(
        status=status,
        has_active_subscription=active,
        current_purchase_count=len(current),
        reconciled_count=reconciled_count,
        cleared_pending=(
            cleared_server_pending or (not active and status != "pending")
        ),
    )
