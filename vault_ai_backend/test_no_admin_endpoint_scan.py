"""Scan the FastAPI route table for any admin/staff endpoint over users.

This test locks in the "no admin console" invariant. It permits the
existing per-vault self-service and infra-health-token routes but
fails if anything that could enumerate, inspect, delete, suspend, or
pause a specific user account slips into the router.

Runs without the OPAQUE wheel. Uses ``main.app`` directly.
"""

from __future__ import annotations

import re

import pytest


ALLOWED_ADMIN_PATTERNS = {
    "/billing/admin/health",
    "/crypto/wallet/health",
    "/crypto/mainnet/admin/health",
    "/crypto/solana/admin/health",
    "/crypto/tron/admin/health",
    "/vault-analysis/",
    "/billing/dev/",
}


FORBIDDEN_SUBSTRINGS = (
    "/users",
    "/user/",
    "/admin/users",
    "/admin/vault",
    "/staff/",
    "/support/",
)


def _load_routes() -> list[str]:
    import main
    paths: list[str] = []
    for route in main.app.routes:
        p = getattr(route, "path", None)
        if isinstance(p, str):
            paths.append(p)
    return paths


def test_no_admin_user_listing_endpoint() -> None:
    paths = _load_routes()
    offenders: list[str] = []
    for p in paths:
        low = p.lower()
        if any(a in low for a in ALLOWED_ADMIN_PATTERNS):
            continue
        if any(f in low for f in FORBIDDEN_SUBSTRINGS):
            offenders.append(p)
    assert offenders == [], (
        f"Admin user-manipulation route(s) leaked into the router: "
        f"{offenders}. VaultAI's product rule forbids any admin path "
        "over individual users. Remove or gate them out."
    )


def test_zk_routes_are_registered() -> None:
    paths = set(_load_routes())
    expected = {
        "/auth/zk-register-init",
        "/auth/zk-register-finalize",
        "/auth/zk-login-init",
        "/auth/zk-login-finalize",
        "/auth/zk-adopt",
    }
    missing = expected - paths
    assert not missing, (
        f"Expected ZK auth routes are missing: {sorted(missing)}"
    )


def test_no_admin_route_lists_users_or_decrypts_content() -> None:
    """Comprehensive admin-surface capability audit. Fails if any
    route in the running FastAPI app matches any pattern that could
    plausibly (a) enumerate individual users, (b) return another
    vault's content or metadata to an admin, (c) reset a PIN, (d)
    decrypt a vault, or (e) manually delete/suspend a specific vault.
    """
    import main
    routes = list(main.app.routes)
    forbidden_patterns = (
        "/admin/users", "/admin/vaults", "/admin/vault/",
        "/staff/", "/support/", "/impersonate", "/support-mode",
        "/admin/list-users", "/admin/search-users",
        "/admin/user/", "/admin/decrypt", "/admin/reset-pin",
        "/admin/suspend", "/admin/ban", "/admin/delete-vault",
        "/admin/vault-inspect", "/master-decrypt", "/god-mode",
        "/support/decrypt", "/support/impersonate",
    )
    offenders: list[str] = []
    for r in routes:
        p = getattr(r, "path", None)
        if not isinstance(p, str):
            continue
        low = p.lower()
        for fp in forbidden_patterns:
            if fp in low:
                offenders.append(p)
    assert offenders == [], (
        "Admin-surface capability check failed. VaultAI must not "
        "expose any route capable of enumerating, inspecting, "
        "decrypting, resetting, suspending, or deleting an "
        "individual user. Offenders: " + repr(offenders)
    )


def test_zk_routes_never_accept_vault_name_field() -> None:
    """The ZK request models must not have a `vault_name` field. Only
    `vault_handle` should be accepted so that the plaintext human-
    readable name never transits during ZK login/signup.
    """
    import routes.auth_zk_routes as zk

    request_models = [
        zk.ZkRegisterInitRequest,
        zk.ZkRegisterFinalizeRequest,
        zk.ZkLoginInitRequest,
        zk.ZkLoginFinalizeRequest,
        zk.ZkAdoptRequest,
    ]
    for model in request_models:
        fields = set(model.model_fields.keys())
        assert "vault_name" not in fields, (
            f"{model.__name__} accepts vault_name — ZK auth must "
            "only accept vault_handle"
        )
        assert "display_username" not in fields, (
            f"{model.__name__} accepts display_username — must not"
        )
        assert "display_name" not in fields, (
            f"{model.__name__} accepts display_name — must be "
            "display_name_ciphertext only, not plaintext"
        )
