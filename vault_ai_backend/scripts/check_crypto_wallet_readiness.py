"""Crypto Wallet operator readiness checker.

Hits /crypto/wallet/features, /crypto/wallet/health,
/crypto/wallet/diagnosis on a running VaultAI backend and prints
a clean per-asset summary.

Never prints RPC URLs, API keys, contract-address values, wallet
addresses, tx hashes, private keys, mnemonics, seeds, or encrypted
secrets. If a response somehow contains one of those, this script
still redacts it before printing.

Usage:

    python check_crypto_wallet_readiness.py \\
        --base-url https://api.your-domain.example \\
        --auth-token "$SESSION_TOKEN" \\
        --admin-token "$VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN"

Exit codes:
    0  every asset is ready (or intentionally not-ready by policy,
       i.e. XMR whose scanner remains unavailable)
    1  at least one asset is not ready because of a fixable config
       issue (rpc_not_configured, token_contract_not_configured,
       feature_disabled)
    2  the readiness script itself could not reach the backend or
       was denied by admin-token auth
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any


ASSET_DISPLAY_ORDER = (
    ("ethereum_mainnet_eth",         "ETH Mainnet"),
    ("ethereum_mainnet_usdt_erc20",  "USDT ERC20"),
    ("ethereum_mainnet_usdc_erc20",  "USDC ERC20"),
    ("solana_mainnet_sol",           "SOL"),
    ("tron_mainnet_usdt_trc20",      "USDT TRC20"),
    ("monero_mainnet_xmr",           "XMR"),
)


INTENTIONAL_NOT_READY_ROWS: frozenset[str] = frozenset({
    "monero_mainnet_xmr",
})


REDACT_TOKEN = "<redacted>"


_REDACT_KEY_SUBSTRINGS = (
    "rpcurl", "rpc_url",
    "apibase", "api_base",
    "apikey", "api_key",
    "contract",
    "publicaddress", "public_address",
    "walletaddress", "wallet_address",
    "address",
    "txhash", "tx_hash",
    "tx_id", "txid",
    "encryptedwalletsecret",
    "encrypted_wallet_secret",
    "mnemonic",
    "seed",
    "polyseed",
    "spendkey", "spend_key",
    "viewkey", "view_key",
    "walletpassword", "wallet_password",
    "privatekey", "private_key",
    "secret",
    "sessiontoken", "session_token",
    "authorization",
)


_URL_RE = re.compile(r"https?://[^\s\"'`)>]+")
_ETH_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]{40}\b")
_TRON_ADDR_RE = re.compile(r"\bT[1-9A-HJ-NP-Za-km-z]{33}\b")
_XMR_ADDR_RE = re.compile(r"\b[48][1-9A-HJ-NP-Za-km-z]{94}\b")
_TX_HASH_RE = re.compile(r"\b0x[0-9a-fA-F]{64}\b")
_BASE58_LIKE_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{43,88}\b")


def _looks_like_secret_key(k: str) -> bool:
    kn = k.lower().replace("-", "").replace("_", "")
    for banned in _REDACT_KEY_SUBSTRINGS:
        if banned.replace("_", "") in kn:
            return True
    return False


def _scrub_string_value(s: str) -> str:

    if not s:
        return s
    scrubbed = _URL_RE.sub(REDACT_TOKEN, s)
    scrubbed = _TX_HASH_RE.sub(REDACT_TOKEN, scrubbed)
    scrubbed = _ETH_ADDR_RE.sub(REDACT_TOKEN, scrubbed)
    scrubbed = _TRON_ADDR_RE.sub(REDACT_TOKEN, scrubbed)
    scrubbed = _XMR_ADDR_RE.sub(REDACT_TOKEN, scrubbed)
    scrubbed = _BASE58_LIKE_RE.sub(REDACT_TOKEN, scrubbed)
    return scrubbed


def scrub(obj: Any, parent_key: str = "") -> Any:

    if isinstance(obj, dict):
        return {
            k: (
                REDACT_TOKEN if _looks_like_secret_key(k)
                else scrub(v, parent_key=k)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [scrub(x, parent_key=parent_key) for x in obj]
    if isinstance(obj, str):
        if _looks_like_secret_key(parent_key):
            return REDACT_TOKEN
        return _scrub_string_value(obj)
    return obj


class BackendUnreachableError(RuntimeError):
    pass


class AdminAuthError(RuntimeError):
    pass


def _http_get(
    url: str,
    *,
    auth_token: str,
    admin_token: str | None,
    timeout: int,
) -> dict[str, Any]:

    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {auth_token}")
    req.add_header("Accept", "application/json")
    if admin_token:
        req.add_header("X-Crypto-Health-Admin-Token", admin_token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise AdminAuthError(f"HTTP 403 for {url}") from exc
        raise BackendUnreachableError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BackendUnreachableError(str(exc)) from exc
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise BackendUnreachableError(
            f"non-JSON response from {url}",
        ) from exc
    if not isinstance(data, dict):
        raise BackendUnreachableError(
            f"unexpected non-object response from {url}",
        )
    return data


def _fetch_features_health_diagnosis(
    base_url: str,
    auth_token: str,
    admin_token: str | None,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:

    base = base_url.rstrip("/")
    features = _http_get(
        f"{base}/crypto/wallet/features",
        auth_token=auth_token, admin_token=None, timeout=timeout,
    )
    health: dict[str, Any] | None = None
    diagnosis: dict[str, Any] | None = None
    try:
        health = _http_get(
            f"{base}/crypto/wallet/health",
            auth_token=auth_token,
            admin_token=admin_token, timeout=timeout,
        )
    except AdminAuthError:
        health = None
    try:
        diagnosis = _http_get(
            f"{base}/crypto/wallet/diagnosis",
            auth_token=auth_token,
            admin_token=admin_token, timeout=timeout,
        )
    except AdminAuthError:
        diagnosis = None
    return features, health, diagnosis


def summarize(
    features: dict[str, Any],
    diagnosis: dict[str, Any] | None,
) -> tuple[list[str], int, int, int]:

    lines: list[str] = []
    fixable_not_ready = 0
    intentional_not_ready = 0
    total = 0
    row_by_id: dict[str, dict[str, Any]] = {}
    if diagnosis is not None:
        for row in diagnosis.get("assets", []):
            if isinstance(row, dict):
                rid = row.get("rowId")
                if isinstance(rid, str):
                    row_by_id[rid] = row
    for row_id, label in ASSET_DISPLAY_ORDER:
        total += 1
        row = row_by_id.get(row_id)
        if row is None:
            lines.append(
                f"{label:14} unknown — diagnosis unavailable "
                "(admin token required?)",
            )
            fixable_not_ready += 1
            continue
        ready = row.get("balanceRouteReady") is True
        reason = str(row.get("lastBalanceReason") or "unknown")
        status = "ready" if ready else "not ready"
        if not ready and row_id in INTENTIONAL_NOT_READY_ROWS:
            intentional_not_ready += 1
        elif not ready:
            fixable_not_ready += 1
        lines.append(f"{label:14} {status:9} — reason {reason}")
    return lines, fixable_not_ready, intentional_not_ready, total


def format_report(
    features: dict[str, Any],
    health: dict[str, Any] | None,
    diagnosis: dict[str, Any] | None,
) -> str:

    lines: list[str] = []
    lines.append("VaultAI Crypto Wallet — provider readiness")
    lines.append("")
    engine_on = features.get("walletEngineEnabled")
    default_network = features.get("defaultNetwork") or "—"
    default_valid = features.get("defaultNetworkConfigValid")
    lines.append(f"walletEngineEnabled       : {engine_on}")
    lines.append(f"defaultNetwork            : {default_network}")
    lines.append(f"defaultNetworkConfigValid : {default_valid}")
    if health is not None:
        overall = health.get("overallStatus") or "—"
        lines.append(f"overallHealth             : {overall}")
    else:
        lines.append("overallHealth             : (unauthorized — supply --admin-token)")
    lines.append("")
    summary_lines, fixable, intentional, total = summarize(features, diagnosis)
    lines.extend(summary_lines)
    lines.append("")
    ready = total - fixable - intentional
    lines.append(
        f"Summary: {ready} ready · "
        f"{intentional} intentionally not ready · "
        f"{fixable} not ready · {total} total",
    )
    lines.append("")
    lines.append(
        "This report contains no RPC URLs, no API keys, no token "
        "contract values, no wallet addresses, no tx hashes, no "
        "private keys, no mnemonics, no encrypted wallet secrets, "
        "no session tokens.",
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Print a safe operator readiness summary for the VaultAI "
            "Crypto Wallet provider setup. Never prints secrets."
        ),
    )
    parser.add_argument(
        "--base-url", required=True,
        help="Backend base URL, e.g. https://api.your-domain.example",
    )
    parser.add_argument(
        "--auth-token", required=True,
        help="Trusted-device session token (Bearer).",
    )
    parser.add_argument(
        "--admin-token", default=None,
        help=(
            "Optional X-Crypto-Health-Admin-Token for /health and "
            "/diagnosis. Omit to see the features-only summary."
        ),
    )
    parser.add_argument(
        "--timeout", type=int, default=10,
        help="HTTP timeout in seconds (default 10).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit the scrubbed envelopes as JSON in addition to the summary.",
    )
    args = parser.parse_args(argv)

    try:
        features, health, diagnosis = _fetch_features_health_diagnosis(
            args.base_url,
            args.auth_token,
            args.admin_token,
            args.timeout,
        )
    except BackendUnreachableError as exc:
        sys.stderr.write(f"backend unreachable: {exc}\n")
        return 2
    except AdminAuthError as exc:
        sys.stderr.write(f"admin auth denied: {exc}\n")
        return 2

    print(format_report(features, health, diagnosis))
    if args.json:
        payload = {
            "features": scrub(features),
            "health":   scrub(health) if health is not None else None,
            "diagnosis": scrub(diagnosis) if diagnosis is not None else None,
        }
        print("")
        print(json.dumps(payload, indent=2, sort_keys=True))

    _, fixable, _, _ = summarize(features, diagnosis)
    return 0 if fixable == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
