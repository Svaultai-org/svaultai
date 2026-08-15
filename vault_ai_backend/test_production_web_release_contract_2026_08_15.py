"""Prevent another frontend/backend v2 feature-matrix split deployment."""

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


def test_frontend_build_scripts_and_backend_compose_share_feature_matrix() -> None:
    powershell = (FRONTEND / "scripts" / "build-web-release.ps1").read_text()
    shell = (FRONTEND / "scripts" / "build-web-release.sh").read_text()
    compose = (BACKEND / "docker-compose.production.example.yml").read_text()

    assert _bools_from_text(powershell) == EXPECTED
    assert _bools_from_text(shell) == EXPECTED
    assert _bools_from_text(compose) == EXPECTED

    for verifier_name in ("verify-web-release.ps1", "verify-web-release.sh"):
        verifier = (FRONTEND / "scripts" / verifier_name).read_text()
        assert WEB_API_CONTRACT in verifier
        for feature_name in (
            "credentialV2Read",
            "credentialV2Write",
            "memoryV2Read",
            "memoryV2Write",
            "fileV2Read",
            "fileV2Write",
        ):
            assert feature_name in verifier


def test_public_contract_is_non_secret_and_matches_expected_matrix() -> None:
    env = {name: str(value).lower() for name, value in EXPECTED.items()}
    flags = ZkMigrationFlags.from_environment(env)

    assert WEB_API_CONTRACT == "svaultai-core-v2-2026-08-15"
    assert flags.public_web_features() == {
        "credentialV2Read": True,
        "credentialV2Write": False,
        "memoryV2Read": True,
        "memoryV2Write": True,
        "fileV2Read": True,
        "fileV2Write": True,
    }
