"""Read-only production probe for Google Play ADC and subscription catalog.

This script never prints access tokens, credential JSON, purchase tokens, or
response bodies. It performs one GET against monetization.subscriptions.get.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Mapping
from urllib.parse import quote

import google.auth
from google.auth.transport.requests import AuthorizedSession


ANDROID_PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
EXPECTED_PROJECT_ID = "svaultai-production"
EXPECTED_SERVICE_ACCOUNT = (
    "svaultai-play-billing@svaultai-production.iam.gserviceaccount.com"
)
PACKAGE_NAME = "com.svaultai.app"
PRODUCT_ID = "svaultai_storage_50gb"
BASE_PLAN_ID = "monthly-auto"
BILLING_PERIOD = "P1M"


def validate_subscription_payload(payload: Mapping[str, Any]) -> None:
    if str(payload.get("packageName") or "") != PACKAGE_NAME:
        raise RuntimeError("Google Play package mismatch")
    if str(payload.get("productId") or "") != PRODUCT_ID:
        raise RuntimeError("Google Play product mismatch")
    base_plans = payload.get("basePlans")
    if not isinstance(base_plans, list):
        raise RuntimeError("Google Play base plans missing")
    matches = [
        plan for plan in base_plans
        if isinstance(plan, dict)
        and str(plan.get("basePlanId") or "") == BASE_PLAN_ID
    ]
    if len(matches) != 1:
        raise RuntimeError("Google Play base plan mismatch")
    plan = matches[0]
    auto = plan.get("autoRenewingBasePlanType")
    if (
        str(plan.get("state") or "") != "ACTIVE"
        or not isinstance(auto, dict)
        or str(auto.get("billingPeriodDuration") or "") != BILLING_PERIOD
        or isinstance(plan.get("prepaidBasePlanType"), dict)
    ):
        raise RuntimeError("Google Play active auto-renewing plan mismatch")


def main() -> int:
    expected_email = os.getenv(
        "VAULTAI_GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL",
        EXPECTED_SERVICE_ACCOUNT,
    ).strip().lower()
    credentials, project_id = google.auth.default(
        scopes=[ANDROID_PUBLISHER_SCOPE],
    )
    actual_email = str(
        getattr(credentials, "service_account_email", "")
        or getattr(credentials, "_service_account_email", "")
    ).strip().lower()
    if project_id != EXPECTED_PROJECT_ID:
        raise RuntimeError("Google ADC project mismatch")
    if actual_email != expected_email:
        raise RuntimeError("Google ADC service account mismatch")

    url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{quote(PACKAGE_NAME, safe='')}/subscriptions/"
        f"{quote(PRODUCT_ID, safe='')}"
    )
    response = AuthorizedSession(credentials).get(url, timeout=20)
    if response.status_code != 200:
        raise RuntimeError(
            f"Google Play read-only subscription probe failed ({response.status_code})"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Google Play subscription response invalid")
    validate_subscription_payload(payload)

    print(f"GOOGLE_PLAY_ADC_PROJECT={project_id}")
    print(f"GOOGLE_PLAY_ADC_IDENTITY={actual_email}")
    print("GOOGLE_PLAY_SUBSCRIPTION_READ=PASS")
    print(f"GOOGLE_PLAY_PRODUCT_ID={PRODUCT_ID}")
    print(f"GOOGLE_PLAY_BASE_PLAN_ID={BASE_PLAN_ID}")
    print("GOOGLE_PLAY_BASE_PLAN_STATE=ACTIVE")
    print("GOOGLE_PLAY_BASE_PLAN_TYPE=AUTO_RENEWING")
    print(f"GOOGLE_PLAY_BILLING_PERIOD={BILLING_PERIOD}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"GOOGLE_PLAY_ADC_PROBE=FAIL:{type(exc).__name__}", file=sys.stderr)
        raise
