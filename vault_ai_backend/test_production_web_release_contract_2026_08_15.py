"""Prevent another web/iOS/Android/backend feature-matrix split."""

import json
import re
from pathlib import Path

from zk_migration_flags import WEB_API_CONTRACT, ZkMigrationFlags


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "vault_ai_frontend"
BACKEND = ROOT / "vault_ai_backend"

EXPECTED = {
    "ZK_V2_READ_ENABLED": True,
    "ZK_V2_WRITE_ENABLED": False,
    "MEMORY_V2_READ_ENABLED": True,
    "MEMORY_V2_WRITE_ENABLED": True,
    "FILE_V2_READ_ENABLED": True,
    "FILE_V2_WRITE_ENABLED": True,
    "FILE_V2_MIGRATION_ENABLED": False,
    "ZK_V2_MIGRATION_ENABLED": False,
    "MEMORY_V2_MIGRATION_ENABLED": False,
    "WALLET_BACKUP_V2_READ_ENABLED": False,
    "WALLET_BACKUP_V2_WRITE_ENABLED": False,
    "WALLET_BACKUP_V2_MIGRATION_ENABLED": False,
    "WALLET_V2_READ_ENABLED": False,
    "WALLET_V2_WRITE_ENABLED": False,
    "WALLET_V2_MIGRATION_ENABLED": False,
    "PRIVATE_VAULT_LOCAL_ROUTING_ENABLED": False,
}


def _bools_from_text(text: str) -> dict[str, bool]:
    found: dict[str, bool] = {}
    for name in EXPECTED:
        match = re.search(
            rf"{name}(?:=|:)[^\r\n]*?(true|false)", text, re.IGNORECASE
        )
        assert match is not None, f"{name} missing from production contract"
        found[name] = match.group(1).lower() == "true"
    return found


def test_every_release_surface_shares_the_canonical_feature_matrix() -> None:
    powershell = (FRONTEND / "scripts" / "build-web-release.ps1").read_text()
    shell = (FRONTEND / "scripts" / "build-web-release.sh").read_text()
    compose = (BACKEND / "docker-compose.production.example.yml").read_text()
    production_env = (BACKEND / ".env.production.example").read_text()
    canonical = json.loads(
        (FRONTEND / "config" / "release-contract.production.json").read_text()
    )

    assert canonical == EXPECTED
    assert _bools_from_text(compose) == EXPECTED
    assert _bools_from_text(production_env) == EXPECTED
    assert "--dart-define-from-file=config/release-contract.production.json" in shell
    assert "--dart-define-from-file=config/release-contract.production.json" in powershell

    for verifier_name in ("verify-web-release.ps1", "verify-web-release.sh"):
        verifier = (FRONTEND / "scripts" / verifier_name).read_text()
        assert WEB_API_CONTRACT in verifier
        for feature_name in ZkMigrationFlags.from_environment(
            {name: str(value).lower() for name, value in EXPECTED.items()}
        ).public_client_features():
            assert feature_name in verifier


def test_public_contract_is_non_secret_and_matches_expected_matrix() -> None:
    env = {name: str(value).lower() for name, value in EXPECTED.items()}
    flags = ZkMigrationFlags.from_environment(env)

    assert WEB_API_CONTRACT == "svaultai-core-v2-2026-08-16"
    assert flags.public_client_features() == {
        "credentialV2Read": True,
        "credentialV2Write": False,
        "credentialV2Migration": False,
        "memoryV2Read": True,
        "memoryV2Write": True,
        "memoryV2Migration": False,
        "fileV2Read": True,
        "fileV2Write": True,
        "fileV2Migration": False,
        "walletBackupV2Read": False,
        "walletBackupV2Write": False,
        "walletBackupV2Migration": False,
        "walletV2Read": False,
        "walletV2Write": False,
        "walletV2Migration": False,
        "privateVaultLocalRouting": False,
    }
