"""Read-only release gate for Apple billing configuration.

Never charges, restores, writes entitlements or prints credentials/receipts.
The explicit catalogue is shared with the release configuration, not inferred
from product prefixes or unverified transaction fields.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from apple_billing import AppleSignedDataVerifier, configured_apple_catalog


def expected_apple_catalog() -> dict:
    return json.loads((BACKEND_ROOT / "config/apple-storage-products.json").read_text())


def validate_catalog(catalog: dict) -> None:
    expected = expected_apple_catalog()
    missing = sorted(set(expected) - set(catalog))
    if missing:
        raise RuntimeError("Apple billing catalogue is missing required current/restore products")
    for product_id, required in expected.items():
        actual = catalog[product_id]
        if any(actual.get(key) != value for key, value in required.items()):
            raise RuntimeError("Apple billing catalogue has incorrect storage/period mapping")


def verify_configuration() -> dict:
    catalog = configured_apple_catalog()
    validate_catalog(catalog)
    if os.getenv("VAULTAI_APPLE_BUNDLE_ID", "").strip() != "com.svaultai.app":
        raise RuntimeError("Apple billing bundle identifier does not match SVaultAI")
    if os.getenv("VAULTAI_APPLE_APP_ID", "").strip() != "6800601455":
        raise RuntimeError("Apple billing app identifier does not match SVaultAI")
    AppleSignedDataVerifier("production")
    return {"apple_billing_ready": True, "configured_products": len(catalog),
            "required_products": len(expected_apple_catalog())}


if __name__ == "__main__":
    try:
        print(json.dumps(verify_configuration(), sort_keys=True))
    except Exception:
        # Deliberately avoid echoing configuration, secrets or raw exceptions.
        print("Apple billing release gate failed: check catalogue, app identity, dependency and certificates.",
              file=sys.stderr)
        raise SystemExit(1)
