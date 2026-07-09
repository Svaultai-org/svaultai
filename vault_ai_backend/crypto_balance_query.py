

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

from crypto_schemas import (
    ALL_CRYPTO_ASSETS,
    BALANCE_STATUS_UNAVAILABLE_PRIVACY,
    BALANCE_STATUS_LOOKUP_NOT_CONNECTED,
    NETWORK_LABEL_FOR_ASSET,
    PRIVACY_CHAIN_ASSETS,
    SCHEMA_CRYPTO_WALLET_PROFILE_V1,
    balance_status_for_asset,
    balance_status_message,
    is_wallet_profile_schema,
)


_BALANCE_QUERY_RE = re.compile(
    r"\b(?:"
    r"show|tell|give|list|what(?:\s+is|(?:'|’)?s)?|"
    r"how\s+much\s+(?:do\s+i\s+have|is)|"
    r"check"
    r")\b[^.?!]{0,40}\b(?:crypto|wallet|coins?)\s+balances?\b",
    re.IGNORECASE,
)

_BARE_BALANCE_QUERY_RE = re.compile(
    r"\b(?:my|all|the)\s+crypto\s+balances?\b",
    re.IGNORECASE,
)


def is_crypto_balance_query(message: Optional[str]) -> bool:


    if not isinstance(message, str) or not message.strip():
        return False
    return bool(
        _BALANCE_QUERY_RE.search(message)
        or _BARE_BALANCE_QUERY_RE.search(message)
    )


ALLOWED_BALANCE_INPUT_FIELDS: frozenset[str] = frozenset({
    "schema",
    "asset",
    "network",
                                                                  
                                                                
    "publicAddress",
})


BALANCE_SUMMARY_HEADER: str = "Here are your current crypto balances:"
BALANCE_SUMMARY_FOOTER_HONEST: str = (
    "Balance lookup is not connected, so live amounts are "
    "unavailable. Saved wallet addresses are still safe in your "
    "encrypted vault."
)


def _read_safe_view(record: Mapping[str, Any]) -> dict[str, Any]:


    out: dict[str, Any] = {}
    for k in ALLOWED_BALANCE_INPUT_FIELDS:
        if k in record:
            out[k] = record[k]
    return out


def _normalise_asset(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    v = value.strip().upper().replace("-", "_").replace(" ", "_")
    if v in ALL_CRYPTO_ASSETS:
        return v
    return None


def build_balance_summary(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:


    by_asset: dict[str, int] = {a: 0 for a in ALL_CRYPTO_ASSETS}
    for r in records or ():
        if not isinstance(r, Mapping):
            continue
        if not is_wallet_profile_schema(r.get("schema")):
                                                               
                                                          
            continue
        safe = _read_safe_view(r)
        asset = _normalise_asset(safe.get("asset"))
        if asset is None:
            continue
                                                        
        pa = safe.get("publicAddress")
        if not isinstance(pa, str) or not pa.strip():
            continue
        by_asset[asset] = by_asset.get(asset, 0) + 1
    assets_out: list[dict[str, Any]] = []
    for asset in ALL_CRYPTO_ASSETS:
        status = balance_status_for_asset(asset)
        assets_out.append({
            "asset":        asset,
            "network":      NETWORK_LABEL_FOR_ASSET.get(asset, asset),
            "savedWallets": by_asset.get(asset, 0),
            "status":       status,
            "message":      balance_status_message(status),
        })
    return {
        "header":  BALANCE_SUMMARY_HEADER,
        "footer":  BALANCE_SUMMARY_FOOTER_HONEST,
        "assets":  assets_out,
                                                              
                                               
        "schema":  SCHEMA_CRYPTO_WALLET_PROFILE_V1,
    }


def format_balance_summary_message(summary: Mapping[str, Any]) -> str:


    if not isinstance(summary, Mapping):
        return ""
    parts: list[str] = []
    header = summary.get("header")
    if isinstance(header, str) and header:
        parts.append(header)
    assets = summary.get("assets")
    if isinstance(assets, list):
        for a in assets:
            if not isinstance(a, Mapping):
                continue
            asset   = a.get("asset", "")
            count   = a.get("savedWallets", 0)
            msg     = a.get("message", "")
            saved_v = f"{count} saved" if isinstance(count, int) else "0 saved"
            parts.append(f"  • {asset} — {saved_v} — {msg}")
    footer = summary.get("footer")
    if isinstance(footer, str) and footer:
        parts.append(footer)
    return "\n".join(parts)


__all__ = [
    "ALLOWED_BALANCE_INPUT_FIELDS",
    "BALANCE_SUMMARY_HEADER",
    "BALANCE_SUMMARY_FOOTER_HONEST",
    "is_crypto_balance_query",
    "build_balance_summary",
    "format_balance_summary_message",
]
