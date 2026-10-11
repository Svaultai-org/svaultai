"""Read-only production probe for the keyless Google Play Cloud Run bridge.

No purchase is made, no entitlement is written, and no secret or token is
printed. The bridge resolves attached ADC and reads the fixed Play catalog.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google_play_billing import (
    GOOGLE_PLAY_PRODUCT_50GB,
    GOOGLE_PLAY_STORAGE_CATALOG,
    GooglePlayPublisherClient,
)


def main(argv: list[str] | None = None) -> int:
    product_ids = tuple(product for product, _plan in GOOGLE_PLAY_STORAGE_CATALOG)
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--product-id", choices=product_ids)
    selection.add_argument("--all-products", action="store_true")
    args = parser.parse_args(argv)
    selected = product_ids if args.all_products else (
        args.product_id or GOOGLE_PLAY_PRODUCT_50GB,
    )
    publisher = GooglePlayPublisherClient()
    for product_id in selected:
        result = publisher.verify_catalog(product_id)
        print("GOOGLE_ADC_RESOLUTION=PASS")
        print(f"ADC_IDENTITY={result['adc_identity']}")
        print("ANDROID_PUBLISHER_API_AUTH=PASS")
        print(f"GOOGLE_PLAY_PRODUCT_ID={result['product_id']}")
        print(f"GOOGLE_PLAY_BASE_PLAN_ID={result['base_plan_id']}")
        print(f"GOOGLE_PLAY_BASE_PLAN_TYPE={result['base_plan_type']}")
        print(f"GOOGLE_PLAY_BILLING_PERIOD={result['billing_period']}")
    if args.all_products:
        print(f"GOOGLE_PLAY_CATALOG_PRODUCTS_VERIFIED={len(selected)}")
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
