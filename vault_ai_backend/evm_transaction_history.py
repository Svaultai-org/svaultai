

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from vault_config import (
    ethereum_mainnet_tx_indexer_api_key,
    ethereum_mainnet_tx_indexer_base_url,
    ethereum_mainnet_tx_indexer_configured,
    ethereum_mainnet_tx_indexer_provider,
    ethereum_sepolia_token_contract,
    ethereum_sepolia_token_decimals,
    ethereum_sepolia_token_unit,
    ethereum_sepolia_tx_indexer_api_key,
    ethereum_sepolia_tx_indexer_base_url,
    ethereum_sepolia_tx_indexer_configured,
    ethereum_sepolia_tx_indexer_provider,
)


logger = logging.getLogger("evm_transaction_history")


TX_SCHEMA_V1: str = "crypto_wallet_transaction_v1"

NETWORK_SEPOLIA_ID:    str = "ethereum_sepolia"
NETWORK_SEPOLIA_LABEL: str = "Ethereum Sepolia"
SEPOLIA_CHAIN_ID:      int = 11155111

NETWORK_MAINNET_ID:    str = "ethereum_mainnet"
NETWORK_MAINNET_LABEL: str = "Ethereum Mainnet"
MAINNET_CHAIN_ID:      int = 1


REASON_TOKEN_CONTRACT_NOT_CONFIGURED: str = "token_contract_not_configured"

DIRECTION_INCOMING: str = "incoming"
DIRECTION_OUTGOING: str = "outgoing"

STATUS_PENDING:   str = "pending"
STATUS_CONFIRMED: str = "confirmed"
STATUS_FAILED:    str = "failed"
STATUS_UNKNOWN:   str = "unknown"

SOURCE_INDEXER:         str = "indexer"
SOURCE_LOCAL_SUBMITTED: str = "local_submitted"

                                                               
MAX_TX_LIMIT:     int = 50
DEFAULT_TX_LIMIT: int = 20


PROVIDER_ETHERSCAN:  str = "etherscan"
PROVIDER_BLOCKSCOUT: str = "blockscout"

ALL_PROVIDERS: tuple[str, ...] = (PROVIDER_ETHERSCAN, PROVIDER_BLOCKSCOUT)


STATUS_OK:          str = "ok"
STATUS_UNAVAILABLE: str = "unavailable"

REASON_INDEXER_NOT_CONFIGURED: str = "indexer_not_configured"
REASON_UPSTREAM_ERROR:         str = "upstream_error"
REASON_INVALID_ADDRESS:        str = "invalid_address"

                                                               
LIVE_ETH_ASSET:  str = "ETH"
LIVE_TOKEN_ASSETS: frozenset[str] = frozenset({
    "USDT_ERC20", "USDC_ERC20",
})


_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TX_HASH_RE     = re.compile(r"^0x[0-9a-fA-F]{64}$")


_TIMEOUT_SECS = 8


class TxIndexerError(RuntimeError):


    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _redact_address(addr: Optional[str]) -> str:


    if not isinstance(addr, str) or not _ETH_ADDRESS_RE.match(addr):
        return "<addr?>"
    return f"{addr[:6]}…{addr[-4:]}"


def _redact_tx_hash(tx: Optional[str]) -> str:

    if not isinstance(tx, str) or not _TX_HASH_RE.match(tx):
        return "<tx?>"
    return f"{tx[:6]}…{tx[-4:]}"


def is_valid_eth_address(addr: Optional[str]) -> bool:
    if not isinstance(addr, str):
        return False
    return bool(_ETH_ADDRESS_RE.match(addr))


def _network_id_and_label(network_id: str) -> tuple[str, str]:


    if network_id == NETWORK_MAINNET_ID:
        return NETWORK_MAINNET_ID, NETWORK_MAINNET_LABEL
    return NETWORK_SEPOLIA_ID, NETWORK_SEPOLIA_LABEL


def _indexer_message_for_network(network_id: str) -> str:


    if network_id == NETWORK_MAINNET_ID:
        return (
            "Transaction history is not connected yet. The wallet "
            "engine needs an on-chain indexer "
            "(ETHEREUM_MAINNET_TX_INDEXER_PROVIDER + API key) before "
            "it can list real transactions."
        )
    return (
        "Transaction history is not connected yet. The wallet "
        "engine needs an on-chain indexer "
        "(ETHEREUM_SEPOLIA_TX_INDEXER_PROVIDER + API key) before "
        "it can list real transactions."
    )


def envelope_indexer_not_configured(
    asset: str, *, network_id: str = NETWORK_SEPOLIA_ID,
) -> dict[str, Any]:


    nid, label = _network_id_and_label(network_id)
    return {
        "status":             STATUS_OK,
        "transactionsStatus": STATUS_UNAVAILABLE,
        "reason":             REASON_INDEXER_NOT_CONFIGURED,
        "asset":              asset,
        "network":            nid,
        "networkLabel":       label,
        "transactions":       [],
        "message":            _indexer_message_for_network(nid),
    }


def envelope_upstream_error(
    asset: str, *, code: str, network_id: str = NETWORK_SEPOLIA_ID,
) -> dict[str, Any]:


    nid, label = _network_id_and_label(network_id)
    return {
        "status":             STATUS_OK,
        "transactionsStatus": STATUS_UNAVAILABLE,
        "reason":             REASON_UPSTREAM_ERROR,
        "asset":              asset,
        "network":            nid,
        "networkLabel":       label,
        "transactions":       [],
        "message": (
            "Transaction history could not be loaded from the indexer "
            f"({code}). Try again shortly."
        ),
    }


def envelope_token_contract_not_configured(
    asset: str, *, network_id: str = NETWORK_SEPOLIA_ID,
) -> dict[str, Any]:


    nid, label = _network_id_and_label(network_id)
    if nid == NETWORK_MAINNET_ID:
        env_var = (
            "ETHEREUM_MAINNET_USDT_CONTRACT_ADDRESS"
            if asset == "USDT_ERC20"
            else "ETHEREUM_MAINNET_USDC_CONTRACT_ADDRESS"
        )
    else:
        env_var = (
            "ETH_SEPOLIA_USDT_CONTRACT_ADDRESS"
            if asset == "USDT_ERC20"
            else "ETH_SEPOLIA_USDC_CONTRACT_ADDRESS"
        )
    return {
        "status":             STATUS_OK,
        "transactionsStatus": STATUS_UNAVAILABLE,
        "reason":             REASON_TOKEN_CONTRACT_NOT_CONFIGURED,
        "asset":              asset,
        "network":            nid,
        "networkLabel":       label,
        "transactions":       [],
        "message": (
            "Token contract is not configured. The wallet engine needs "
            f"{env_var} set before it can filter on-chain activity for "
            "this token."
        ),
    }


def envelope_invalid_address(
    asset: str, *, network_id: str = NETWORK_SEPOLIA_ID,
) -> dict[str, Any]:
    nid, label = _network_id_and_label(network_id)
    create_first_label = (
        "Ethereum Mainnet" if nid == NETWORK_MAINNET_ID
        else "Ethereum Sepolia"
    )
    return {
        "status":             STATUS_OK,
        "transactionsStatus": STATUS_UNAVAILABLE,
        "reason":             REASON_INVALID_ADDRESS,
        "asset":              asset,
        "network":            nid,
        "networkLabel":       label,
        "transactions":       [],
        "message": (
            "Cannot load transactions without a wallet address. "
            f"Create your {create_first_label} wallet first."
        ),
    }


def envelope_ok(
    asset: str,
    transactions: list[dict[str, Any]],
    *,
    network_id: str = NETWORK_SEPOLIA_ID,
) -> dict[str, Any]:


    nid, label = _network_id_and_label(network_id)
    return {
        "status":             STATUS_OK,
        "transactionsStatus": "available",
        "asset":              asset,
        "network":            nid,
        "networkLabel":       label,
        "transactions":       list(transactions),
    }


@dataclass(frozen=True)
class _RawEvmTx:


    tx_hash:        str
    from_address:   str
    to_address:     str
    value_units:    int                                                 
    timestamp_s:    Optional[int]
    confirmations:  Optional[int]
    is_error:       bool


def _build_normalised_row(
    *,
    raw: _RawEvmTx,
    asset: str,
    user_address: str,
    decimals: int,
    unit: str,
    network_id: str = NETWORK_SEPOLIA_ID,
) -> dict[str, Any]:


    user_lc = user_address.lower()
    from_lc = raw.from_address.lower()
    to_lc   = raw.to_address.lower()
    if to_lc == user_lc:
        direction = DIRECTION_INCOMING
    elif from_lc == user_lc:
        direction = DIRECTION_OUTGOING
    else:
                                                                 
                                                                 
        direction = DIRECTION_OUTGOING

    if raw.is_error:
        status = STATUS_FAILED
    elif raw.confirmations is not None and raw.confirmations >= 1:
        status = STATUS_CONFIRMED
    elif raw.confirmations == 0:
        status = STATUS_PENDING
    else:
        status = STATUS_UNKNOWN

    amount_str = _format_units(raw.value_units, decimals)
    nid, label = _network_id_and_label(network_id)

    return {
        "schema":        TX_SCHEMA_V1,
        "asset":         asset,
        "network":       nid,
        "networkLabel":  label,
        "txHash":        raw.tx_hash,
        "direction":     direction,
        "amount":        amount_str,
        "unit":          unit,
        "status":        status,
        "confirmations": int(raw.confirmations) if raw.confirmations is not None else 0,
        "fromAddress":   raw.from_address,
        "toAddress":     raw.to_address,
        "timestamp":     int(raw.timestamp_s) if raw.timestamp_s is not None else None,
        "source":        SOURCE_INDEXER,
    }


def _format_units(value_units: int, decimals: int) -> str:


    if decimals <= 0:
        return str(int(value_units))
    if value_units == 0:
        return "0"
    sign = "-" if value_units < 0 else ""
    v = abs(int(value_units))
    s = str(v).rjust(decimals + 1, "0")
    whole = s[:-decimals]
    frac = s[-decimals:]
                                                                  
                        
    trimmed = frac.rstrip("0")
    if trimmed == "":
        return f"{sign}{whole}"
    return f"{sign}{whole}.{trimmed}"


def _http_get(url: str, *, params: dict[str, Any]) -> dict[str, Any]:


    try:
        with httpx.Client(timeout=_TIMEOUT_SECS) as client:
            resp = client.get(url, params=params)
    except httpx.TimeoutException:
        logger.warning("[TX-INDEXER] upstream_timeout")
        raise TxIndexerError("upstream_timeout")
    except (httpx.HTTPError, OSError):
        logger.warning("[TX-INDEXER] upstream_io")
        raise TxIndexerError("upstream_io")
    if resp.status_code != 200:
        logger.warning(
            "[TX-INDEXER] upstream_http status=%s", resp.status_code,
        )
        raise TxIndexerError("upstream_http")
    try:
        body = resp.json()
    except (ValueError, TypeError):
        logger.warning("[TX-INDEXER] upstream_json")
        raise TxIndexerError("upstream_json")
    if not isinstance(body, dict):
        raise TxIndexerError("upstream_json")
    return body


def _network_indexer_config(network_id: str) -> tuple[str, str, str, int]:


    if network_id == NETWORK_MAINNET_ID:
        return (
            ethereum_mainnet_tx_indexer_provider(),
            ethereum_mainnet_tx_indexer_base_url(),
            ethereum_mainnet_tx_indexer_api_key(),
            MAINNET_CHAIN_ID,
        )
    return (
        ethereum_sepolia_tx_indexer_provider(),
        ethereum_sepolia_tx_indexer_base_url(),
        ethereum_sepolia_tx_indexer_api_key(),
        SEPOLIA_CHAIN_ID,
    )


def _network_indexer_configured(network_id: str) -> bool:
    if network_id == NETWORK_MAINNET_ID:
        return ethereum_mainnet_tx_indexer_configured()
    return ethereum_sepolia_tx_indexer_configured()


def _etherscan_query(
    *,
    address: str,
    action: str,
    contract_address: Optional[str],
    limit: int,
    network_id: str = NETWORK_SEPOLIA_ID,
) -> list[dict[str, Any]]:


    _, base, key, chain_id = _network_indexer_config(network_id)
    params: dict[str, Any] = {
        "chainid": chain_id,
        "module":  "account",
        "action":  action,
        "address": address,
        "page":    1,
        "offset":  max(1, min(MAX_TX_LIMIT, int(limit))),
        "sort":    "desc",
        "apikey":  key,
    }
    if contract_address:
        params["contractaddress"] = contract_address
    body = _http_get(base, params=params)
                                                                    
    status = str(body.get("status", "")).strip()
    result = body.get("result")
    if status == "0":
                                                                     
                                                                     
        if isinstance(result, list):
            return result
        if isinstance(result, str):
            return []
                                                      
        msg = str(body.get("message", "")).strip().lower()
        if msg in {"no transactions found", "no records found", ""}:
            return []
        raise TxIndexerError("upstream_rpc")
    if not isinstance(result, list):
        raise TxIndexerError("upstream_json")
    return result


def _blockscout_query(
    *,
    address: str,
    action: str,                        
    contract_address: Optional[str],
    limit: int,
    network_id: str = NETWORK_SEPOLIA_ID,
) -> list[dict[str, Any]]:


    _, base, _, _ = _network_indexer_config(network_id)
    params: dict[str, Any] = {
        "module":  "account",
        "action":  action,
        "address": address,
        "page":    1,
        "offset":  max(1, min(MAX_TX_LIMIT, int(limit))),
        "sort":    "desc",
    }
    if contract_address:
        params["contractaddress"] = contract_address
    body = _http_get(base, params=params)
    status = str(body.get("status", "")).strip()
    result = body.get("result")
    if status == "0":
        if isinstance(result, list):
            return result
        return []
    if not isinstance(result, list):
        raise TxIndexerError("upstream_json")
    return result


def _query_provider(
    *,
    address: str,
    action: str,
    contract_address: Optional[str],
    limit: int,
    network_id: str = NETWORK_SEPOLIA_ID,
) -> list[dict[str, Any]]:


    provider, _, _, _ = _network_indexer_config(network_id)
    if provider == PROVIDER_ETHERSCAN:
        return _etherscan_query(
            address=address, action=action,
            contract_address=contract_address, limit=limit,
            network_id=network_id,
        )
    if provider == PROVIDER_BLOCKSCOUT:
        return _blockscout_query(
            address=address, action=action,
            contract_address=contract_address, limit=limit,
            network_id=network_id,
        )
    raise TxIndexerError("provider_not_supported")


def _safe_int(raw: object) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return int(raw.strip())
        except ValueError:
            return None
    return None


def _row_to_raw_eth(row: dict[str, Any]) -> Optional[_RawEvmTx]:


    tx_hash = str(row.get("hash") or "").strip()
    if not _TX_HASH_RE.match(tx_hash):
        return None
    from_addr = str(row.get("from") or "").strip()
    to_addr   = str(row.get("to") or "").strip()
    if not _ETH_ADDRESS_RE.match(from_addr) or not _ETH_ADDRESS_RE.match(to_addr):
        return None
    value_wei = _safe_int(row.get("value"))
    if value_wei is None:
        return None
    is_error = str(row.get("isError", "0")).strip() == "1"
    confirmations = _safe_int(row.get("confirmations"))
    ts = _safe_int(row.get("timeStamp"))
    return _RawEvmTx(
        tx_hash=tx_hash, from_address=from_addr, to_address=to_addr,
        value_units=value_wei, timestamp_s=ts,
        confirmations=confirmations, is_error=is_error,
    )


def _row_to_raw_erc20(
    row: dict[str, Any],
    *,
    expected_contract: str,
) -> Optional[_RawEvmTx]:


    tx_hash = str(row.get("hash") or "").strip()
    if not _TX_HASH_RE.match(tx_hash):
        return None
    contract = str(row.get("contractAddress") or "").strip().lower()
    if expected_contract and contract != expected_contract.lower():
                                                                       
        return None
    from_addr = str(row.get("from") or "").strip()
    to_addr   = str(row.get("to") or "").strip()
    if not _ETH_ADDRESS_RE.match(from_addr) or not _ETH_ADDRESS_RE.match(to_addr):
        return None
    value_units = _safe_int(row.get("value"))
    if value_units is None:
        return None
    confirmations = _safe_int(row.get("confirmations"))
    ts = _safe_int(row.get("timeStamp"))
                                                                   
                                                      
    is_error = str(row.get("isError", "0")).strip() == "1"
    return _RawEvmTx(
        tx_hash=tx_hash, from_address=from_addr, to_address=to_addr,
        value_units=value_units, timestamp_s=ts,
        confirmations=confirmations, is_error=is_error,
    )


def list_eth_transactions(
    address: Optional[str],
    *,
    limit: int = DEFAULT_TX_LIMIT,
    network_id: str = NETWORK_SEPOLIA_ID,
) -> dict[str, Any]:


    asset = LIVE_ETH_ASSET
    if not is_valid_eth_address(address):
        return envelope_invalid_address(asset, network_id=network_id)
    if not _network_indexer_configured(network_id):
        return envelope_indexer_not_configured(asset, network_id=network_id)
    bounded_limit = max(1, min(MAX_TX_LIMIT, int(limit)))
    try:
        raw_rows = _query_provider(
            address=address, action="txlist",
            contract_address=None, limit=bounded_limit,
            network_id=network_id,
        )
    except TxIndexerError as exc:
        logger.info(
            "[TX-INDEXER] eth_failed network=%s addr=%s code=%s",
            network_id, _redact_address(address), exc.code,
        )
        return envelope_upstream_error(
            asset, code=exc.code, network_id=network_id,
        )
    rows: list[dict[str, Any]] = []
    for r in raw_rows[:bounded_limit]:
        raw = _row_to_raw_eth(r)
        if raw is None:
            continue
        rows.append(_build_normalised_row(
            raw=raw, asset=asset, user_address=address,
            decimals=18, unit="ETH", network_id=network_id,
        ))
    logger.info(
        "[TX-INDEXER] eth_ok network=%s addr=%s rows=%d",
        network_id, _redact_address(address), len(rows),
    )
    return envelope_ok(asset, rows, network_id=network_id)


def _network_token_contract(network_id: str, asset: str) -> str:


    if network_id == NETWORK_MAINNET_ID:
        from evm_networks import token_contract_for
        return token_contract_for(NETWORK_MAINNET_ID, asset)
    return ethereum_sepolia_token_contract(asset)


def _network_token_decimals(network_id: str, asset: str) -> int:


    if network_id == NETWORK_MAINNET_ID:
        from vault_config import ethereum_mainnet_token_decimals
        return ethereum_mainnet_token_decimals(asset)
    return ethereum_sepolia_token_decimals(asset)


def _network_token_unit(network_id: str, asset: str) -> str:

    if network_id == NETWORK_MAINNET_ID:
        from vault_config import ethereum_mainnet_token_unit
        return ethereum_mainnet_token_unit(asset)
    return ethereum_sepolia_token_unit(asset)


def list_erc20_transactions(
    address: Optional[str],
    *,
    asset: str,
    limit: int = DEFAULT_TX_LIMIT,
    network_id: str = NETWORK_SEPOLIA_ID,
) -> dict[str, Any]:


    if asset not in LIVE_TOKEN_ASSETS:
        return envelope_indexer_not_configured(asset, network_id=network_id)
    if not is_valid_eth_address(address):
        return envelope_invalid_address(asset, network_id=network_id)
    if not _network_indexer_configured(network_id):
        return envelope_indexer_not_configured(asset, network_id=network_id)
    contract = _network_token_contract(network_id, asset)
    if not contract or not _ETH_ADDRESS_RE.match(contract):
        return envelope_token_contract_not_configured(
            asset, network_id=network_id,
        )
    decimals = _network_token_decimals(network_id, asset)
    unit     = _network_token_unit(network_id, asset)
    bounded_limit = max(1, min(MAX_TX_LIMIT, int(limit)))
    try:
        raw_rows = _query_provider(
            address=address, action="tokentx",
            contract_address=contract, limit=bounded_limit,
            network_id=network_id,
        )
    except TxIndexerError as exc:
        logger.info(
            "[TX-INDEXER] erc20_failed network=%s asset=%s addr=%s code=%s",
            network_id, asset, _redact_address(address), exc.code,
        )
        return envelope_upstream_error(
            asset, code=exc.code, network_id=network_id,
        )
    rows: list[dict[str, Any]] = []
    for r in raw_rows[:bounded_limit]:
        raw = _row_to_raw_erc20(r, expected_contract=contract)
        if raw is None:
            continue
        rows.append(_build_normalised_row(
            raw=raw, asset=asset, user_address=address,
            decimals=decimals, unit=unit, network_id=network_id,
        ))
    logger.info(
        "[TX-INDEXER] erc20_ok network=%s asset=%s addr=%s rows=%d",
        network_id, asset, _redact_address(address), len(rows),
    )
    return envelope_ok(asset, rows, network_id=network_id)


__all__ = [
    "TX_SCHEMA_V1",
    "NETWORK_SEPOLIA_ID",
    "NETWORK_SEPOLIA_LABEL",
    "SEPOLIA_CHAIN_ID",
    "DIRECTION_INCOMING",
    "DIRECTION_OUTGOING",
    "STATUS_PENDING",
    "STATUS_CONFIRMED",
    "STATUS_FAILED",
    "STATUS_UNKNOWN",
    "SOURCE_INDEXER",
    "SOURCE_LOCAL_SUBMITTED",
    "MAX_TX_LIMIT",
    "DEFAULT_TX_LIMIT",
    "PROVIDER_ETHERSCAN",
    "PROVIDER_BLOCKSCOUT",
    "ALL_PROVIDERS",
    "STATUS_OK",
    "STATUS_UNAVAILABLE",
    "REASON_INDEXER_NOT_CONFIGURED",
    "REASON_UPSTREAM_ERROR",
    "REASON_INVALID_ADDRESS",
    "REASON_TOKEN_CONTRACT_NOT_CONFIGURED",
    "LIVE_ETH_ASSET",
    "LIVE_TOKEN_ASSETS",
    "TxIndexerError",
    "is_valid_eth_address",
    "envelope_indexer_not_configured",
    "envelope_token_contract_not_configured",
    "envelope_upstream_error",
    "envelope_invalid_address",
    "envelope_ok",
    "NETWORK_MAINNET_ID",
    "NETWORK_MAINNET_LABEL",
    "MAINNET_CHAIN_ID",
    "list_eth_transactions",
    "list_erc20_transactions",
]
