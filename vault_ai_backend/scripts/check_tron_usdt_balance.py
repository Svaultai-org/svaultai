"""One-command local TRON USDT balance diagnostic.

Loads the backend .env exactly the way main.py does, reads
TRON_API_BASE_URL, TRON_API_KEY, TRON_USDT_CONTRACT_ADDRESS from
env, calls the same tron_get_trc20_balance_at_url helper the
backend uses, and prints only closed-set diagnostic fields.

NEVER prints: the address you pass on the CLI, the API key value,
the provider URL, the contract address value, the raw provider
response body, tx hash, private key, or any encrypted secret.

Usage:

    python scripts/check_tron_usdt_balance.py --address <PUBLIC_TRON_ADDRESS>

Fields printed (all closed-set, no env values):

    env_path_found=true|false
    env_loaded=true|false
    tron_configured=true|false
    api_key_present=true|false
    contract_configured=true|false
    provider_status=<closed-set label from tron_contract_call_shape>
    balance_status=available|unavailable
    amount=<integer base units>       (only when balance_status=available)
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import re
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def _load_backend_env() -> tuple[bool, bool]:
    env_path = _BACKEND_ROOT / ".env"
    env_path_found = env_path.exists() and env_path.is_file()
    env_loaded = False
    try:
        from dotenv import load_dotenv
    except ImportError:
        return env_path_found, False
    try:
        if env_path_found:
            env_loaded = bool(load_dotenv(env_path))
        else:

            load_dotenv()
    except Exception:
        env_loaded = False
    return env_path_found, env_loaded


_PROVIDER_STATUS_LABELS: frozenset[str] = frozenset({
    "ok",
    "response_not_dict",
    "provider_error_message",
    "constant_result_missing",
    "constant_result_invalid_string",
    "constant_result_non_hex",
    "negative_value",
    "api_not_configured",
    "api_key_missing",
    "api_unauthorized",
    "rate_limited",
    "provider_unreachable",
    "provider_error",
    "invalid_contract",
    "invalid_address",
    "unknown",
})


def _parse_provider_status(captured_log: str) -> str:
    match = re.search(
        r"tron_contract_call_shape\b[^\n]*?provider_status=(\S+)",
        captured_log,
    )
    if not match:
        return "unknown"
    label = match.group(1).strip()
    if label in _PROVIDER_STATUS_LABELS:
        return label
    return "unknown"


def _capture_shape_log_and_call(
    base_url: str, api_key: str,
    contract: str, address: str,
) -> tuple[str, object]:
    from tron_rpc import (
        tron_get_trc20_balance_at_url, TronRpcError,
    )
    logger = logging.getLogger("tron_rpc")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)
    original_level = logger.level
    original_disabled = logger.disabled
    logger.disabled = False
    logger.setLevel(logging.INFO)
    balance_result: object
    try:
        try:
            balance_result = tron_get_trc20_balance_at_url(
                base_url, api_key,
                contract_address_b58=contract,
                holder_address_b58=address,
            )
        except TronRpcError as exc:
            balance_result = exc
        except Exception:
            balance_result = None
    finally:
        handler.flush()
        logger.removeHandler(handler)
        logger.setLevel(original_level)
        logger.disabled = original_disabled
    return stream.getvalue(), balance_result


def _emit(k: str, v: str) -> None:
    print(f"{k}={v}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local TRON USDT balance diagnostic.",
    )
    parser.add_argument(
        "--address", required=True,
        help="Public TRON address to check (never printed).",
    )
    args = parser.parse_args(argv)

    env_path_found, env_loaded = _load_backend_env()
    _emit("env_path_found", "true" if env_path_found else "false")
    _emit("env_loaded",     "true" if env_loaded else "false")

    base_url = os.getenv("TRON_API_BASE_URL", "").strip()
    if not base_url:
        base_url = os.getenv("TRON_RPC_URL", "").strip()
    api_key  = os.getenv("TRON_API_KEY", "").strip()
    contract = os.getenv("TRON_USDT_CONTRACT_ADDRESS", "").strip()

    tron_configured     = bool(base_url)
    api_key_present     = bool(api_key)
    contract_configured = bool(contract)

    _emit("tron_configured",     "true" if tron_configured else "false")
    _emit("api_key_present",     "true" if api_key_present else "false")
    _emit("contract_configured",
          "true" if contract_configured else "false")

    if not tron_configured:
        _emit("provider_status", "api_not_configured")
        _emit("balance_status",  "unavailable")
        return 1
    if not contract_configured:
        _emit("provider_status", "invalid_contract")
        _emit("balance_status",  "unavailable")
        return 1

    captured_log, result = _capture_shape_log_and_call(
        base_url, api_key, contract, args.address,
    )
    provider_status = _parse_provider_status(captured_log)
    _emit("provider_status", provider_status)

    if isinstance(result, int):
        _emit("balance_status", "available")
        _emit("amount", str(int(result)))
        return 0
    _emit("balance_status", "unavailable")
    return 1


if __name__ == "__main__":
    sys.exit(main())
