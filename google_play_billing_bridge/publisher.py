"""Keyless Android Publisher client for the isolated Cloud Run service."""

from __future__ import annotations

import os
import threading
from typing import Any, Mapping
from urllib.parse import quote


ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
PROJECT_ID = "svaultai-production"
SERVICE_ACCOUNT = (
    "svaultai-play-billing@svaultai-production.iam.gserviceaccount.com"
)
PACKAGE_NAME = "com.svaultai.app"
PRODUCT_ID = "svaultai_storage_50gb"
BASE_PLAN_ID = "monthly-auto"
BILLING_PERIOD = "P1M"


class PublisherConfigurationError(RuntimeError):
    pass


class PublisherTransientError(RuntimeError):
    pass


class PublisherVerificationError(RuntimeError):
    pass


class PurchaseNotFoundError(PublisherVerificationError):
    pass


_session = None
_session_lock = threading.Lock()


def _assert_fixed_configuration() -> None:
    expected = {
        "VAULTAI_GOOGLE_PROJECT_ID": PROJECT_ID,
        "VAULTAI_GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL": SERVICE_ACCOUNT,
        "VAULTAI_GOOGLE_PLAY_PACKAGE_NAME": PACKAGE_NAME,
    }
    for name, fixed_value in expected.items():
        if os.getenv(name, fixed_value).strip() != fixed_value:
            raise PublisherConfigurationError(f"{name} does not match production")
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip():
        raise PublisherConfigurationError(
            "downloadable Google credentials are forbidden in this runtime"
        )


def authorized_session():
    global _session
    _assert_fixed_configuration()
    if _session is not None:
        return _session
    with _session_lock:
        if _session is not None:
            return _session
        try:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession, Request
        except ImportError as exc:
            raise PublisherConfigurationError(
                "Google ADC dependency is unavailable"
            ) from exc
        credentials, project_id = google.auth.default(
            scopes=[ANDROID_PUBLISHER_SCOPE],
        )
        if project_id != PROJECT_ID:
            raise PublisherConfigurationError("Google ADC project mismatch")
        # ComputeCredentials learns the attached service-account email during
        # refresh. No token or credential material is logged or returned.
        credentials.refresh(Request())
        actual_email = str(
            getattr(credentials, "service_account_email", "")
            or getattr(credentials, "_service_account_email", "")
        ).strip().lower()
        if actual_email != SERVICE_ACCOUNT:
            raise PublisherConfigurationError("Google ADC identity mismatch")
        _session = AuthorizedSession(credentials)
        return _session


def _parse_json_response(response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise PublisherVerificationError(
            "Android Publisher returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise PublisherVerificationError("Android Publisher returned invalid JSON")
    return payload


def _raise_upstream_error(status: int, *, purchase_lookup: bool = False) -> None:
    if purchase_lookup and status in {404, 410}:
        raise PurchaseNotFoundError("purchase was not found")
    if status in {401, 403}:
        raise PublisherConfigurationError("Android Publisher rejected ADC")
    if status == 429 or status >= 500:
        raise PublisherTransientError("Android Publisher is temporarily unavailable")
    raise PublisherVerificationError(f"Android Publisher rejected request ({status})")


def get_subscription(purchase_token: str) -> Mapping[str, Any]:
    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{quote(PACKAGE_NAME, safe='')}/purchases/"
        f"subscriptionsv2/tokens/{quote(purchase_token, safe='')}"
    )
    response = authorized_session().get(url, timeout=20)
    if response.status_code != 200:
        _raise_upstream_error(response.status_code, purchase_lookup=True)
    return _parse_json_response(response)


def acknowledge_subscription(product_id: str, purchase_token: str) -> None:
    if product_id != PRODUCT_ID:
        raise PublisherVerificationError("product is not in the fixed catalog")
    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{quote(PACKAGE_NAME, safe='')}/purchases/subscriptions/"
        f"{quote(PRODUCT_ID, safe='')}/tokens/"
        f"{quote(purchase_token, safe='')}:acknowledge"
    )
    response = authorized_session().post(url, json={}, timeout=20)
    if response.status_code not in {200, 204}:
        _raise_upstream_error(response.status_code)


def validate_catalog(payload: Mapping[str, Any]) -> None:
    if str(payload.get("packageName") or "") != PACKAGE_NAME:
        raise PublisherVerificationError("Google Play package mismatch")
    if str(payload.get("productId") or "") != PRODUCT_ID:
        raise PublisherVerificationError("Google Play product mismatch")
    base_plans = payload.get("basePlans")
    if not isinstance(base_plans, list):
        raise PublisherVerificationError("Google Play base plans missing")
    matches = [
        plan for plan in base_plans
        if isinstance(plan, dict)
        and str(plan.get("basePlanId") or "") == BASE_PLAN_ID
    ]
    if len(matches) != 1:
        raise PublisherVerificationError("Google Play base plan mismatch")
    plan = matches[0]
    auto = plan.get("autoRenewingBasePlanType")
    if (
        str(plan.get("state") or "") != "ACTIVE"
        or not isinstance(auto, dict)
        or str(auto.get("billingPeriodDuration") or "") != BILLING_PERIOD
        or isinstance(plan.get("prepaidBasePlanType"), dict)
    ):
        raise PublisherVerificationError(
            "Google Play active auto-renewing plan mismatch"
        )


def verify_catalog() -> Mapping[str, str]:
    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{quote(PACKAGE_NAME, safe='')}/subscriptions/"
        f"{quote(PRODUCT_ID, safe='')}"
    )
    response = authorized_session().get(url, timeout=20)
    if response.status_code != 200:
        _raise_upstream_error(response.status_code)
    validate_catalog(_parse_json_response(response))
    return {
        "adc_resolution": "PASS",
        "adc_identity": SERVICE_ACCOUNT,
        "android_publisher_api_auth": "PASS",
        "package_name": PACKAGE_NAME,
        "product_id": PRODUCT_ID,
        "base_plan_id": BASE_PLAN_ID,
        "base_plan_type": "AUTO_RENEWING",
        "billing_period": BILLING_PERIOD,
    }
