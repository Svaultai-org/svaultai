from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from scripts.verify_apple_billing import expected_apple_catalog, validate_catalog, verify_configuration


def test_explicit_catalog_covers_current_ios_products():
    backend = Path(__file__).resolve().parent
    source = (backend.parent / "vault_ai_frontend/lib/services/apple_iap_service.dart").read_text()
    products = set(re.findall(r"'([^']+\.monthly\.v2)'", source))
    assert len(products) == 9
    assert products <= set(expected_apple_catalog())


def test_production_example_matches_explicit_catalog(monkeypatch):
    example = (Path(__file__).resolve().parent / ".env.production.example").read_text()
    raw = next(line.partition("=")[2] for line in example.splitlines()
               if line.startswith("VAULTAI_APPLE_PRODUCT_MAP_JSON="))
    assert json.loads(raw) == expected_apple_catalog()


def test_catalog_includes_legacy_restore_products():
    assert "svaultai.storage.50gb.monthly" in expected_apple_catalog()
    assert "svaultai.storage.300gb.monthly" in expected_apple_catalog()
    validate_catalog(expected_apple_catalog())


def test_release_gate_rejects_missing_current_product():
    catalog = expected_apple_catalog()
    del catalog["com.svaultai.app.storage.50gb.monthly.v2"]
    with pytest.raises(RuntimeError, match="missing required"):
        validate_catalog(catalog)


@pytest.mark.parametrize("field,value", [("quantity", 2), ("entitlement_bytes", 1),
                                         ("billing_period", "P1Y"), ("plan_id", "annual")])
def test_release_gate_rejects_wrong_storage_or_period(field, value):
    catalog = expected_apple_catalog()
    catalog["com.svaultai.app.storage.50gb.monthly.v2"][field] = value
    with pytest.raises(RuntimeError, match="incorrect storage/period"):
        validate_catalog(catalog)


def test_configuration_gate_checks_identity_and_verifier(monkeypatch):
    import scripts.verify_apple_billing as gate
    monkeypatch.setenv("VAULTAI_APPLE_PRODUCT_MAP_JSON", json.dumps(expected_apple_catalog()))
    monkeypatch.setenv("VAULTAI_APPLE_BUNDLE_ID", "com.svaultai.app")
    monkeypatch.setenv("VAULTAI_APPLE_APP_ID", "6800601455")
    calls = []
    monkeypatch.setattr(gate, "AppleSignedDataVerifier", lambda env: calls.append(env))
    assert verify_configuration()["apple_billing_ready"]
    assert calls == ["production"]
    monkeypatch.setenv("VAULTAI_APPLE_BUNDLE_ID", "wrong.bundle")
    with pytest.raises(RuntimeError, match="bundle identifier"):
        verify_configuration()
