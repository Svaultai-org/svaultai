"""Fail closed when a release client/backend feature matrix can diverge."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen


FRONTEND = Path(__file__).resolve().parents[1]
ROOT = FRONTEND.parent
BACKEND = ROOT / "vault_ai_backend"
CONTRACT_PATH = FRONTEND / "config" / "release-contract.production.json"
API_CONTRACT = "svaultai-core-v2-2026-08-16"

PUBLIC_NAMES = {
    "ZK_V2_READ_ENABLED": "credentialV2Read",
    "ZK_V2_WRITE_ENABLED": "credentialV2Write",
    "ZK_V2_MIGRATION_ENABLED": "credentialV2Migration",
    "MEMORY_V2_READ_ENABLED": "memoryV2Read",
    "MEMORY_V2_WRITE_ENABLED": "memoryV2Write",
    "MEMORY_V2_MIGRATION_ENABLED": "memoryV2Migration",
    "FILE_V2_READ_ENABLED": "fileV2Read",
    "FILE_V2_WRITE_ENABLED": "fileV2Write",
    "FILE_V2_MIGRATION_ENABLED": "fileV2Migration",
    "WALLET_BACKUP_V2_READ_ENABLED": "walletBackupV2Read",
    "WALLET_BACKUP_V2_WRITE_ENABLED": "walletBackupV2Write",
    "WALLET_BACKUP_V2_MIGRATION_ENABLED": "walletBackupV2Migration",
    "WALLET_V2_READ_ENABLED": "walletV2Read",
    "WALLET_V2_WRITE_ENABLED": "walletV2Write",
    "WALLET_V2_MIGRATION_ENABLED": "walletV2Migration",
    "PRIVATE_VAULT_LOCAL_ROUTING_ENABLED": "privateVaultLocalRouting",
}


def _fail(message: str) -> None:
    print(f"RELEASE_CONTRACT_COMPATIBLE=false reason={message}", file=sys.stderr)
    raise SystemExit(2)


def _load_contract() -> dict[str, bool]:
    raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if set(raw) != set(PUBLIC_NAMES) or not all(
        isinstance(value, bool) for value in raw.values()
    ):
        _fail("canonical_matrix_invalid")
    return raw


def _flags_from_text(path: Path, expected: dict[str, bool]) -> dict[str, bool]:
    text = path.read_text(encoding="utf-8")
    found: dict[str, bool] = {}
    for name in expected:
        match = re.search(
            rf"(?m)^\s*{re.escape(name)}\s*(?:=|:)\s*[\"']?(true|false)",
            text,
            re.IGNORECASE,
        )
        if match is None:
            _fail(f"{path.name}:{name}_missing")
        found[name] = match.group(1).lower() == "true"
    return found


def _public_features(contract: dict[str, bool]) -> dict[str, bool]:
    return {PUBLIC_NAMES[name]: value for name, value in contract.items()}


def _live_contract(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        if response.status != 200:
            _fail(f"live_contract_http_{response.status}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        _fail("live_contract_invalid_json")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url")
    parser.add_argument("--print-public-features", action="store_true")
    args = parser.parse_args()

    contract = _load_contract()
    for path in (
        BACKEND / ".env.production.example",
        BACKEND / "docker-compose.production.example.yml",
    ):
        if _flags_from_text(path, contract) != contract:
            _fail(f"{path.name}_matrix_mismatch")

    dart_contract = (
        FRONTEND / "lib" / "services" / "release_feature_contract.dart"
    ).read_text(encoding="utf-8")
    for name in contract:
        if f"'{name}'" not in dart_contract:
            _fail(f"dart_contract:{name}_missing")
    if API_CONTRACT not in dart_contract:
        _fail("dart_api_contract_mismatch")

    backend_contract = (BACKEND / "zk_migration_flags.py").read_text(
        encoding="utf-8"
    )
    if API_CONTRACT not in backend_contract:
        _fail("backend_api_contract_mismatch")
    for public_name in PUBLIC_NAMES.values():
        if f'"{public_name}"' not in backend_contract:
            _fail(f"backend_public_contract:{public_name}_missing")

    expected_public = _public_features(contract)
    if args.backend_url:
        live = _live_contract(args.backend_url)
        if live.get("apiContract") != API_CONTRACT:
            _fail("live_api_contract_mismatch")
        if live.get("features") != expected_public:
            _fail("live_feature_matrix_mismatch")

    if args.print_public_features:
        print(json.dumps(expected_public, separators=(",", ":")))
    else:
        print(f"RELEASE_API_CONTRACT={API_CONTRACT}")
        print("RELEASE_CONTRACT_COMPATIBLE=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
