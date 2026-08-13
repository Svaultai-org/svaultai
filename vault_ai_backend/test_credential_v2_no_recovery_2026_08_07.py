"""No-recovery and service-authority regressions for client_mvk_v2."""

from __future__ import annotations

import inspect
from pathlib import Path

import routes.credential_v2_routes as credential_v2


ROOT = Path(__file__).resolve().parent


def test_support_admin_account_reset_cannot_restore_client_mvk_v2() -> None:
    """Support/admin account reset cannot restore access to a
    client_mvk_v2 vault when the original unlock secret is lost."""
    source = inspect.getsource(credential_v2).lower()
    for capability in (
        "decrypt_credential", "verify_vault_pin", "admin_unlock",
        "support_key", "recovery_key", "master_key", "unwrap_mvk",
        "extract_mvk", "vaultkeyhierarchy",
    ):
        assert capability not in source


def test_v2_api_has_no_recovery_reset_or_plaintext_capability() -> None:
    route_paths = {getattr(route, "path", "") for route in credential_v2.router.routes}
    assert not any(
        marker in path.lower()
        for path in route_paths
        for marker in ("recover", "reset-pin", "admin", "support", "unlock")
    )
    request_fields = set(credential_v2.CredentialV2WriteRequest.model_fields)
    assert request_fields.isdisjoint(
        {
            "pin", "mvk", "content_key", "credential_key", "password",
            "totp_secret", "notes", "custom_fields", "recovery_secret",
        }
    )


def test_billing_device_and_account_modules_cannot_decrypt_v2() -> None:
    candidates = [
        *ROOT.glob("routes/billing*.py"),
        ROOT / "device_monitor.py",
        ROOT / "auth_local.py",
    ]
    offenders: list[str] = []
    for path in candidates:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8").lower()
        for capability in (
            "decrypt_credential_v2", "credentialcontentkey", "credential_key(",
            "vaultkeyhierarchy", "unwrap_mvk", "extract_mvk",
        ):
            if capability in source:
                offenders.append(f"{path.name}: {capability}")
    assert offenders == [], (
        "Hosted entitlement/account/device control gained a vault-decryption "
        f"capability: {offenders}"
    )


def test_opaque_server_setup_is_not_a_vault_recovery_key() -> None:
    opaque_source = (
        ROOT / "opaque_server_crate" / "src" / "lib.rs"
    ).read_text(encoding="utf-8")
    assert "ServerSetup" in opaque_source
    assert "credentialKey" not in opaque_source
    assert "VaultKeyHierarchy" not in opaque_source
    assert "decrypt_credential" not in opaque_source
