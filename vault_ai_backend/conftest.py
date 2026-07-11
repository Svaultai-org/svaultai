

from __future__ import annotations

import os
import secrets

import pytest


if not os.environ.get("VAULT_SESSION_SECRET", "").strip():
    os.environ["VAULT_SESSION_SECRET"] = secrets.token_urlsafe(48)



_CRYPTO_TEST_SENSITIVE_ENV_KEYS = (
    "VAULTAI_CRYPTO_XMR_ENABLED",
    "VAULTAI_CRYPTO_XMR_SEND_ENABLED",
    "VAULTAI_CRYPTO_XMR_SCANNER_MODE",
    "VAULTAI_CRYPTO_SOLANA_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_ENABLED",
    "VAULTAI_CRYPTO_SOLANA_SEND_PAUSED",
    "VAULTAI_CRYPTO_TRON_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_ENABLED",
    "VAULTAI_CRYPTO_TRON_SEND_PAUSED",
    "ETHEREUM_MAINNET_RPC_URL",
    "SOLANA_RPC_URL",
    "TRON_API_BASE_URL",
    "TRON_API_KEY",
    "TRON_USDT_CONTRACT_ADDRESS",
    "SOLANA_TX_INDEXER_PROVIDER",
    "SOLANA_TX_INDEXER_API_KEY",
    "ETHEREUM_MAINNET_TX_INDEXER_PROVIDER",
    "ETHEREUM_MAINNET_TX_INDEXER_API_KEY",
)
for _k in _CRYPTO_TEST_SENSITIVE_ENV_KEYS:
    os.environ.pop(_k, None)


@pytest.fixture(autouse=True)
def _reset_crypto_env_between_tests():


    for _k in _CRYPTO_TEST_SENSITIVE_ENV_KEYS:
        os.environ.pop(_k, None)
    try:
        import vault_config
        vault_config.reset_for_tests()
    except Exception:
        pass
    yield
    for _k in _CRYPTO_TEST_SENSITIVE_ENV_KEYS:
        os.environ.pop(_k, None)
    try:
        import vault_config
        vault_config.reset_for_tests()
    except Exception:
        pass


def pytest_configure(config):                                             
    pass


@pytest.fixture(autouse=True)
def _reset_rate_limit_backend_between_tests():


    try:
        from rate_limit_backend import reset_rate_limit_backend_for_tests
        reset_rate_limit_backend_for_tests()
    except Exception:


        pass
    yield
    try:
        from rate_limit_backend import reset_rate_limit_backend_for_tests
        reset_rate_limit_backend_for_tests()
    except Exception:
        pass


# ------------------------------------------------------------------
# Crypto Vault entitlement — test default: PASS
# ------------------------------------------------------------------
# Every user-facing /crypto/wallet/* route now requires the shared
# crypto entitlement dependency (see crypto_entitlement.py). The
# existing wallet-route tests build fake principals whose vault_id
# does not correspond to a real account row, so a live billing lookup
# would fail-close them all to 403.
#
# Default the entitlement resolver to True for the test session; the
# tests that specifically want to exercise the gate itself (e.g.
# test_crypto_wallet_entitlement_gate_2026_07_11.py) already override
# this with their own `patch(...)` block, which wins.
@pytest.fixture(autouse=True)
def _default_crypto_entitlement_passes_in_tests(monkeypatch):
    try:
        import crypto_entitlement
        monkeypatch.setattr(
            crypto_entitlement,
            "_resolve_upgraded_flag",
            lambda _vault_id: True,
        )
    except Exception:
        pass
    yield
