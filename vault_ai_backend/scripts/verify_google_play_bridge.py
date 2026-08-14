"""Read-only production probe for the keyless Google Play Cloud Run bridge.

No purchase is made, no entitlement is written, and no secret or token is
printed. The bridge resolves attached ADC and reads the fixed Play catalog.
"""

from __future__ import annotations

import sys

from google_play_billing import GooglePlayPublisherClient


def main() -> int:
    result = GooglePlayPublisherClient().verify_catalog()
    print("GOOGLE_ADC_RESOLUTION=PASS")
    print(f"ADC_IDENTITY={result['adc_identity']}")
    print("ANDROID_PUBLISHER_API_AUTH=PASS")
    print(f"GOOGLE_PLAY_PRODUCT_ID={result['product_id']}")
    print(f"GOOGLE_PLAY_BASE_PLAN_ID={result['base_plan_id']}")
    print(f"GOOGLE_PLAY_BASE_PLAN_TYPE={result['base_plan_type']}")
    print(f"GOOGLE_PLAY_BILLING_PERIOD={result['billing_period']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            f"GOOGLE_PLAY_BRIDGE_PROBE=FAIL:{type(exc).__name__}",
            file=sys.stderr,
        )
        raise
