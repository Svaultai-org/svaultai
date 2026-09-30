"""Regression guards for client-private vault login names."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def test_auth_models_do_not_accept_readable_login_name() -> None:
    from routes.auth_routes import LoginRequest
    from routes.auth_zk_routes import (
        ZkLoginFinalizeRequest,
        ZkRegisterFinalizeRequest,
    )

    assert set(LoginRequest.model_fields) == {"username_lookup", "pin"}
    assert "vault_name" not in ZkLoginFinalizeRequest.model_fields
    assert "vault_name" not in ZkRegisterFinalizeRequest.model_fields
    assert ZkRegisterFinalizeRequest.model_fields["username_lookup"].is_required()


def test_frontend_never_transmits_readable_vault_name() -> None:
    api = (ROOT / "vault_ai_frontend/lib/api_client.dart").read_text()
    zk = (ROOT / "vault_ai_frontend/lib/services/zk_auth_service.dart").read_text()

    assert "'vault_name': vaultName" not in api
    assert "request.fields['vault_name'] = vaultName" not in api
    assert "encodeQueryComponent(vaultName)" not in api
    assert "'vault_name': vaultName" not in zk
    assert "'username_lookup':" in api
    assert "'username_lookup':" in zk


def test_server_auth_never_scans_or_returns_readable_names() -> None:
    zk = (ROOT / "vault_ai_backend/routes/auth_zk_routes.py").read_text()
    legacy = (ROOT / "vault_ai_backend/routes/auth_routes.py").read_text()
    assert "_match_legacy_username_lookup_candidate" not in zk
    assert "LOWER(vault_name)" not in zk
    assert "WHERE LOWER(vault_name)" not in legacy
    assert 'vault_name=""' in zk


def test_migration_replaces_names_and_enforces_opaque_label() -> None:
    migration = (
        ROOT
        / "vault_ai_backend/migrations/versions/0045_private_vault_identifiers.py"
    ).read_text()
    assert "username_lookup_v1 IS NULL" in migration
    assert "display_username = NULL" in migration
    assert "vaults_vault_name_is_opaque_ck" in migration
    assert "'vault-' || replace(vault_id::text, '-', '')" in migration


def test_deletion_service_refuses_non_user_callers() -> None:
    import vault_deletion_service as deletion

    with pytest.raises(ValueError, match="invalid deletion reason"):
        deletion.delete_vault_and_all_data(
            "00000000-0000-0000-0000-000000000000",
            reason=deletion.REASON_DEVELOPMENT_FULL_USER_WIPE,
        )
    with pytest.raises(ValueError, match="invalid deletion reason"):
        deletion.delete_vault_and_all_data(
            "00000000-0000-0000-0000-000000000000",
            reason=deletion.REASON_UNPAID_INACTIVE_6_MONTHS,
        )


def test_no_admin_delete_route_exists() -> None:
    import main

    admin_delete_paths = [
        route.path
        for route in main.app.routes
        if hasattr(route, "path")
        and ("admin" in route.path.lower() or "support" in route.path.lower())
        and ("delete" in route.path.lower() or "remove" in route.path.lower())
    ]
    assert admin_delete_paths == []


def test_automatic_account_deletion_is_not_scheduled() -> None:
    startup = (ROOT / "vault_ai_backend/vault_startup.py").read_text()
    assert "from inactive_unpaid_cleanup import run_forever_daily" not in startup
    assert "deletion is user-only" in startup


def test_help_center_promises_user_only_account_deletion() -> None:
    frontend = (ROOT / "vault_ai_frontend/lib/help_center_content.dart").read_text()
    backend = (ROOT / "vault_ai_backend/vault_faq_content.py").read_text()
    assert "Only the signed-in vault owner can request permanent deletion" in frontend
    assert "does not delete a vault because it is inactive" in frontend
    assert "only be started by the vault owner after signing in" in backend
