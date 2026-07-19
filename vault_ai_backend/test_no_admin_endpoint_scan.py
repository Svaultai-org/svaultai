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


def test_ciphertext_write_router_registers_inheritance_rewrap() -> None:
    from routes.vault_ciphertext_write_routes import router
    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/vault/ciphertext/inheritance-rewrap" in paths


def test_zk_routes_privacy_surface() -> None:
    """Fixed 2026-07-20 (corrected). The privacy contract:

    * ``vault_name`` (the user-chosen identity for both signing in
      AND the vault AI) IS product-facing server-visible metadata
      per the 2026-07-20 product-model clarification. The register-
      finalize + login-finalize endpoints accept it so the server
      can store it in ``vaults.vault_name`` and inject it
      authoritatively into the LLM prompt.
    * ``display_name`` must NEVER appear as a plaintext request
      field — the ZK design encrypts it into
      ``display_name_ciphertext`` client-side.
    * ``display_username`` (a retired legacy field name) must
      never resurface.

    Endpoints that DO NOT store vault_name (init variants + adopt)
    must not accept it either.
    """
    import routes.auth_zk_routes as zk

    # Endpoints that legitimately need vault_name for the plaintext
    # store: register-finalize (initial write) and login-finalize
    # (opportunistic backfill for post-migration-0031 accounts).
    vault_name_writers = {
        zk.ZkRegisterFinalizeRequest,
        zk.ZkLoginFinalizeRequest,
    }
    all_zk_models = {
        zk.ZkRegisterInitRequest,
        zk.ZkRegisterFinalizeRequest,
        zk.ZkLoginInitRequest,
        zk.ZkLoginFinalizeRequest,
        zk.ZkAdoptRequest,
    }

    for model in all_zk_models:
        fields = set(model.model_fields.keys())
        if model in vault_name_writers:
            assert "vault_name" in fields, (
                f"{model.__name__} must accept vault_name — the "
                "server needs it to populate vaults.vault_name for "
                "prompt injection"
            )
        else:
            assert "vault_name" not in fields, (
                f"{model.__name__} accepts vault_name but must not "
                "— only the finalize endpoints write vault_name"
            )
        # Plaintext display fields are always forbidden.
        assert "display_username" not in fields, (
            f"{model.__name__} accepts display_username — retired"
        )
        assert "display_name" not in fields, (
            f"{model.__name__} accepts plaintext display_name — must "
            "be display_name_ciphertext only, decrypted client-side"
        )
