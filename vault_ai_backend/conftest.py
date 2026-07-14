

from __future__ import annotations

import os
import secrets

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "opaque_interop: cross-language OPAQUE wire-interop test; "
        "requires the vaultai_opaque_server pyo3 wheel and Node runtime. "
        "Auto-skipped in environments missing either.",
    )


if not os.environ.get("VAULT_SESSION_SECRET", "").strip():
    os.environ["VAULT_SESSION_SECRET"] = secrets.token_urlsafe(48)

# Pin the initial value so per-test env-restoration can converge to it
# even when a test file mutates VAULT_SESSION_SECRET during a run.
_PINNED_SESSION_SECRET = os.environ["VAULT_SESSION_SECRET"]


@pytest.fixture(autouse=True)
def _install_fake_mainnet_control_store():
    """2026-07-13: swap the Postgres-backed mainnet safety store for
    the in-process `FakeMainnetStore` so every test file exercises
    the real routing/binding/lock ordering without needing a live
    Postgres. Tests that specifically want to simulate cross-worker
    behavior instantiate TWO independent FakeMainnetStore instances
    inside the test body — see `test_mainnet_shared_state_2026_07_13`.
    """
    try:
        from routes import crypto_wallet_routes as _routes
    except Exception:
        yield
        return
    from _test_fake_mainnet_store import get_shared_fake, reset_shared_fake
    reset_shared_fake()
    fake = get_shared_fake()
    original = getattr(_routes, "_mainnet_store", None)
    _routes._mainnet_store = fake
    try:
        import vault_config
        original_pause = getattr(vault_config, "_db_pause_override", None)
        vault_config._db_pause_override = fake.is_mainnet_send_paused
    except Exception:
        original_pause = None
    try:
        yield fake
    finally:
        _routes._mainnet_store = original
        try:
            import vault_config
            if original_pause is None:
                if hasattr(vault_config, "_db_pause_override"):
                    delattr(vault_config, "_db_pause_override")
            else:
                vault_config._db_pause_override = original_pause
        except Exception:
            pass
        reset_shared_fake()


@pytest.fixture(autouse=True)
def _install_fake_solana_control_store():
    """2026-07-14 (Round 6): mirror of the mainnet fake install for
    Solana Send safety. Route code should reference
    `_routes._solana_store` (added alongside the ETH store); the
    fixture swaps in an in-process FakeSolanaStore so tests can
    exercise the SOL draft state machine without a live Postgres."""
    try:
        from routes import crypto_wallet_routes as _routes
    except Exception:
        yield
        return
    from _test_fake_solana_store import (
        get_shared_fake as _sol_get, reset_shared_fake as _sol_reset,
    )
    _sol_reset()
    fake = _sol_get()
    original = getattr(_routes, "_solana_store", None)
    _routes._solana_store = fake
    try:
        yield fake
    finally:
        _routes._solana_store = original
        _sol_reset()


@pytest.fixture(autouse=True)
def _install_fake_tron_control_store():
    """2026-07-14 (Round 6): mirror for TRON Send safety."""
    try:
        from routes import crypto_wallet_routes as _routes
    except Exception:
        yield
        return
    from _test_fake_tron_store import (
        get_shared_fake as _trn_get, reset_shared_fake as _trn_reset,
    )
    _trn_reset()
    fake = _trn_get()
    original = getattr(_routes, "_tron_store", None)
    _routes._tron_store = fake
    try:
        yield fake
    finally:
        _routes._tron_store = original
        _trn_reset()


@pytest.fixture(autouse=True)
def _restore_session_secret_between_tests():
    """Guarantee every test starts with the process's pinned
    VAULT_SESSION_SECRET and that auth_local's module-level cache is
    invalidated. Some test files (e.g. test_vault_config.py,
    test_auth_session_token.py) legitimately mutate this env var and
    pop it in tearDown, but tests that use it in setUp/collection may
    already have observed the pre-mutation value via cached module
    state. This fixture centralises the reset so no downstream test
    (e.g. test_vault_delete_and_inactive_cleanup_2026_07_08.py's HMAC
    challenge signing) sees a stale or missing secret."""
    os.environ["VAULT_SESSION_SECRET"] = _PINNED_SESSION_SECRET
    try:
        import auth_local
        auth_local.reset_secret_for_tests()
    except Exception:
        pass
    yield
    os.environ["VAULT_SESSION_SECRET"] = _PINNED_SESSION_SECRET
    try:
        import auth_local
        auth_local.reset_secret_for_tests()
    except Exception:
        pass



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
