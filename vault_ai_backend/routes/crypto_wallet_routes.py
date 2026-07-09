

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from crypto_wallet_schemas import (
    ASSET_ROLLOUT_PHASE,
    BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
    ENGINE_STATUS_DISABLED,
    ENGINE_STATUS_NOT_READY,
    ENGINE_STATUS_UNSUPPORTED,
    KEY_ORIGIN_GENERATED_CLIENT_SIDE,
    SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
    SCHEMA_CRYPTO_WALLET_BALANCE_V1,
    SIGNING_MODE_CLIENT_SIDE,
    SPECIAL_DESIGN_ASSETS,
    WALLET_BALANCE_STATUS_AVAILABLE,
    WALLET_BALANCE_STATUS_UNAVAILABLE,
    WALLET_ENGINE_ASSETS,
    PlaintextKeyRejected,
    asset_is_wallet_engine_supported,
    engine_disabled_envelope,
    rejects_plaintext_secret,
)
from device_gate import verify_trusted_device
from vault_config import (
    crypto_wallet_engine_enabled,
    ethereum_sepolia_rpc_url,
    ethereum_sepolia_token_contract,
    ethereum_sepolia_token_decimals,
    ethereum_sepolia_token_unit,
)

                                                                    
from vault_core import get_db
from psycopg2.extras import RealDictCursor


logger = logging.getLogger("crypto_wallet_routes")


router = APIRouter(tags=["crypto-wallet-engine"])


ITEM_TYPE_WALLET_ACCOUNT: str = "crypto_wallet_account"


import hashlib
import threading
import time as _time
from collections import deque


_MAINNET_SAFETY_LOCK = threading.Lock()
_MAINNET_BROADCAST_TIMES: dict[str, "deque[float]"] = {}


_MAINNET_IDEMPOTENCY_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_IDEMPOTENCY_TTL_SECS: int = 24 * 60 * 60
_IDEMPOTENCY_KEY_RE = __import__("re").compile(r"^[A-Za-z0-9._\-]{8,128}$")


_SOLANA_SAFETY_LOCK = threading.Lock()
_SOLANA_BROADCAST_TIMES: dict[str, "deque[float]"] = {}
_SOLANA_IDEMPOTENCY_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


_TRON_SAFETY_LOCK = threading.Lock()
_TRON_BROADCAST_TIMES: dict[str, "deque[float]"] = {}
_TRON_IDEMPOTENCY_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def reset_mainnet_safety_state_for_tests() -> None:


    with _MAINNET_SAFETY_LOCK:
        _MAINNET_BROADCAST_TIMES.clear()
        _MAINNET_IDEMPOTENCY_CACHE.clear()


def reset_solana_safety_state_for_tests() -> None:
    with _SOLANA_SAFETY_LOCK:
        _SOLANA_BROADCAST_TIMES.clear()
        _SOLANA_IDEMPOTENCY_CACHE.clear()


def reset_tron_safety_state_for_tests() -> None:
    with _TRON_SAFETY_LOCK:
        _TRON_BROADCAST_TIMES.clear()
        _TRON_IDEMPOTENCY_CACHE.clear()


def _hash_signed_tx(signed_tx_hex: str) -> str:


    return hashlib.sha256(
        (signed_tx_hex or "").encode("utf-8"),
    ).hexdigest()


def _now_secs() -> float:
    return _time.time()


def _purge_idempotency_cache_locked(now: float) -> None:

    expired = [
        k for k, v in _MAINNET_IDEMPOTENCY_CACHE.items()
        if v.get("expires_at", 0) <= now
    ]
    for k in expired:
        _MAINNET_IDEMPOTENCY_CACHE.pop(k, None)


def _check_mainnet_broadcast_rate_limit(
    vault_id: str,
) -> Optional[dict[str, Any]]:


    from vault_config import (
        ethereum_mainnet_broadcast_rate_limit,
        ethereum_mainnet_broadcast_rate_window_secs,
    )
    cap = ethereum_mainnet_broadcast_rate_limit()
    window = ethereum_mainnet_broadcast_rate_window_secs()
    if cap <= 0:
        return None
    now = _now_secs()
    horizon = now - window
    with _MAINNET_SAFETY_LOCK:
        events = _MAINNET_BROADCAST_TIMES.setdefault(vault_id, deque())
        while events and events[0] < horizon:
            events.popleft()
        if len(events) >= cap:
                                                                   
                                               
            oldest = events[0]
            retry_after = max(1, int(window - (now - oldest)) + 1)
            logger.warning(
                "[WALLET-ENGINE] mainnet_broadcast_rate_limited "
                "vault=%s count=%d retry_after=%ds",
                str(vault_id)[:8] + "…", len(events), retry_after,
            )
            return {
                "envelope": {
                    "wallet_engine": "rate_limited",
                    "status":        "rate_limited",
                    "network":       "Ethereum Mainnet",
                    "message": (
                        "Too many recent mainnet broadcast attempts. "
                        "Wait a moment before retrying."
                    ),
                    "retryAfterSeconds": retry_after,
                },
                "retry_after": retry_after,
            }
        events.append(now)
    return None


def _lookup_idempotent_broadcast(
    vault_id: str, idempotency_key: str, signed_tx_hex: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:


    if not idempotency_key:
        return None, None
    sig_hash = _hash_signed_tx(signed_tx_hex)
    with _MAINNET_SAFETY_LOCK:
        _purge_idempotency_cache_locked(_now_secs())
        entry = _MAINNET_IDEMPOTENCY_CACHE.get(
            (vault_id, idempotency_key),
        )
        if entry is None:
            return None, None
        if entry.get("hash") != sig_hash:
            return None, "idempotency_conflict"
        return dict(entry.get("envelope") or {}), None


def _record_idempotent_broadcast(
    vault_id: str,
    idempotency_key: str,
    signed_tx_hex: str,
    envelope: dict[str, Any],
) -> None:
    if not idempotency_key:
        return
    with _MAINNET_SAFETY_LOCK:
        _MAINNET_IDEMPOTENCY_CACHE[(vault_id, idempotency_key)] = {
            "hash":       _hash_signed_tx(signed_tx_hex),
            "envelope":   dict(envelope),
            "expires_at": _now_secs() + _IDEMPOTENCY_TTL_SECS,
        }


def _validate_idempotency_key(raw: Optional[str]) -> Optional[str]:


    if raw is None:
        return None
    candidate = str(raw).strip()
    if not candidate:
        return None
    if not _IDEMPOTENCY_KEY_RE.match(candidate):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_idempotency_key",
                "message": (
                    "The idempotency key must be 8-128 chars from "
                    "[A-Za-z0-9._-]."
                ),
            },
        )
    return candidate


ALLOWED_NETWORKS_FOR_ASSET: dict[str, frozenset[str]] = {
    "ETH":        frozenset({"Ethereum Sepolia"}),
    "USDT_ERC20": frozenset({"Ethereum Sepolia"}),
    "USDC_ERC20": frozenset({"Ethereum Sepolia"}),
}


WEI_PER_ETH: int = 10**18


ERC20_TOKEN_ASSETS: frozenset[str] = frozenset({
    "USDT_ERC20",
    "USDC_ERC20",
})


def _underlying_eth_asset(norm_asset: str) -> str:


    if norm_asset in ERC20_TOKEN_ASSETS:
        return "ETH"
    return norm_asset


def _is_token_asset(norm_asset: str) -> bool:
    return norm_asset in ERC20_TOKEN_ASSETS


class CreateWalletPayload(BaseModel):


    walletLabel:           str = Field(..., min_length=1, max_length=80)
    publicAddress:         str = Field(..., min_length=1, max_length=200)
    network:               str = Field(..., min_length=1, max_length=80)
    encryptedWalletSecret: str = Field(..., min_length=8, max_length=8192)
    restoreHeight:         Optional[int] = Field(default=None, ge=0)
    scannerMode:           Optional[str] = Field(
        default=None, max_length=40,
    )

    model_config = {"extra": "forbid"}


class SendDraftPayload(BaseModel):


    fromAddress:        str
    destinationAddress: str
    amountEth:          Optional[str] = None
    amountSol:          Optional[str] = None
    amountUsdt:         Optional[str] = None

    model_config = {"extra": "forbid"}


class SendBroadcastPayload(BaseModel):


    signedTransaction: Any
    idempotencyKey:    Optional[str] = None

    model_config = {"extra": "forbid"}


def _refuse_plaintext_keys(payload: Any) -> None:
    try:
        if hasattr(payload, "model_dump"):
            scan_target = payload.model_dump()
        elif hasattr(payload, "dict"):
            scan_target = payload.dict()
        else:
            scan_target = payload
        rejects_plaintext_secret(scan_target)
    except PlaintextKeyRejected as exc:
        logger.warning(
            "[WALLET-ENGINE] refused plaintext-key fields=%s",
            sorted(set(exc.field_names)),
        )
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "plaintext_key_rejected",
                "message": (
                    "Crypto Wallet Engine routes refuse plaintext "
                    "private keys, seed phrases, recovery phrases, "
                    "or any other spendable-secret field. The "
                    "engine is non-custodial — encrypt the secret "
                    "client-side and send only the ciphertext."
                ),
                "rejectedFields": sorted(set(exc.field_names)),
            },
        )


def _engine_off_response() -> dict[str, Any]:
    return engine_disabled_envelope(status=ENGINE_STATUS_DISABLED)


def _unsupported_asset_response(asset: str) -> dict[str, Any]:
    body = engine_disabled_envelope(status=ENGINE_STATUS_UNSUPPORTED)
    body["asset"] = asset
    return body


def _not_ready_response(asset: str, capability: str) -> dict[str, Any]:
    body = engine_disabled_envelope(status=ENGINE_STATUS_NOT_READY)
    body["asset"] = asset
    body["capability"] = capability
    body["rolloutPhase"] = ASSET_ROLLOUT_PHASE.get(asset.strip().upper())
    return body


def _normalize_asset(asset: str) -> str:
    if not isinstance(asset, str):
        return ""
    return asset.strip().upper().replace("-", "_").replace(" ", "_")


def _is_slice2_live_asset(asset: str) -> bool:


    return asset == "ETH" or asset in ERC20_TOKEN_ASSETS


def _load_wallet_account_record(
    vault_id: str, asset: str,
) -> Optional[dict[str, Any]]:


    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT encrypted_data
              FROM vault_items
             WHERE vault_id = %s
               AND item_type = %s
               AND LOWER(service) = LOWER(%s)
             ORDER BY created_at DESC
             LIMIT 1
            """,
            (vault_id, ITEM_TYPE_WALLET_ACCOUNT, asset),
        )
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row["encrypted_data"])
        except (json.JSONDecodeError, TypeError):
                                                                  
                                                                
            logger.warning(
                "[WALLET-ENGINE] malformed wallet-account row "
                "vault=%s asset=%s",
                str(vault_id)[:8] + "…", asset,
            )
            return None
    finally:
        conn.close()


def _insert_wallet_account_record(
    vault_id: str, asset: str, record: dict[str, Any],
) -> None:


    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO vault_items
              (vault_id, item_type, service, encrypted_data)
            VALUES (%s, %s, %s, %s)
            """,
            (
                vault_id, ITEM_TYPE_WALLET_ACCOUNT, asset,
                json.dumps(record),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _service_key_for_network(asset: str, network_id: str) -> str:


    from evm_networks import NETWORK_ETHEREUM_SEPOLIA
    if network_id == NETWORK_ETHEREUM_SEPOLIA:
        return asset
    return f"{asset}:{network_id}"


def _load_wallet_account_record_network(
    vault_id: str, asset: str, network_id: str,
) -> Optional[dict[str, Any]]:


    service = _service_key_for_network(asset, network_id)
    record = _load_wallet_account_record(vault_id, service)
    if record is None:
        return None
                                                                    
                                                                 
    stored_network = (record.get("network") or "").strip()
    if stored_network and not _record_matches_network(
        stored_network, network_id,
    ):
        logger.warning(
            "[WALLET-ENGINE] record_network_mismatch "
            "vault=%s asset=%s requested=%s",
            str(vault_id)[:8] + "…", asset, network_id,
        )
        return None
    return record


def _record_matches_network(
    stored_network: str, requested_network_id: str,
) -> bool:


    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
    )
    label = stored_network.strip().lower()
    if requested_network_id == NETWORK_ETHEREUM_MAINNET:
        return label in {"ethereum_mainnet", "ethereum mainnet", "mainnet"}
    if requested_network_id == NETWORK_ETHEREUM_SEPOLIA:
        return label in {
            "ethereum_sepolia", "ethereum sepolia",
            "ethereum sepolia testnet", "sepolia",
        }
    if requested_network_id == NETWORK_SOLANA_MAINNET:
        return label in {
            "solana_mainnet", "solana mainnet", "solana",
        }
    if requested_network_id == NETWORK_TRON_MAINNET:
        return label in {
            "tron_mainnet", "tron mainnet", "tron",
        }
    if requested_network_id == NETWORK_MONERO_MAINNET:
        return label in {
            "monero_mainnet", "monero mainnet", "monero", "xmr",
        }
    return False


def _insert_wallet_account_record_network(
    vault_id: str, asset: str, network_id: str, record: dict[str, Any],
) -> None:


    service = _service_key_for_network(asset, network_id)
    _insert_wallet_account_record(vault_id, service, record)


def _summarize_for_listing(record: dict[str, Any]) -> dict[str, Any]:


    return {
        "schema":        SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
        "asset":         record.get("asset"),
        "network":       record.get("network"),
        "walletLabel":   record.get("walletLabel"),
        "publicAddress": record.get("publicAddress"),
        "keyOrigin":     record.get("keyOrigin"),
        "signingMode":   record.get("signingMode"),
        "backupStatus":  record.get("backupStatus"),
    }


@router.get("/crypto/wallet/assets")
def list_wallet_engine_assets(
    principal=Depends(verify_trusted_device),
):


    return {
        "wallet_engine": (
            "enabled" if crypto_wallet_engine_enabled() else "disabled"
        ),
        "assets": [
            {
                "asset":         a,
                "rolloutPhase":  ASSET_ROLLOUT_PHASE.get(a),
                "specialDesign": a in SPECIAL_DESIGN_ASSETS,
                                                                 
                "live":          _is_slice2_live_asset(a)
                                 and crypto_wallet_engine_enabled(),
            }
            for a in WALLET_ENGINE_ASSETS
        ],
    }


@router.get("/crypto/wallet/accounts")
def list_wallet_engine_accounts(
    principal=Depends(verify_trusted_device),
):


    if not crypto_wallet_engine_enabled():
        body = _engine_off_response()
        body["accounts"] = []
        return body

    vault_id = principal["vault_id"]
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT encrypted_data
              FROM vault_items
             WHERE vault_id = %s
               AND item_type = %s
             ORDER BY created_at DESC
            """,
            (vault_id, ITEM_TYPE_WALLET_ACCOUNT),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    accounts: list[dict[str, Any]] = []
    for row in rows:
        try:
            rec = json.loads(row["encrypted_data"])
        except (json.JSONDecodeError, TypeError):
            continue
        accounts.append(_summarize_for_listing(rec))
    return {
        "wallet_engine": "enabled",
        "accounts":      accounts,
    }


@router.get("/crypto/wallet/evm-networks")
def list_evm_networks(
    principal=Depends(verify_trusted_device),
):


    from evm_networks import (
        ALL_EVM_NETWORKS, network_config,
        is_receive_enabled, is_send_enabled,
    )
    entries: list[dict[str, Any]] = []
    for nid in ALL_EVM_NETWORKS:
        cfg = network_config(nid)
        if cfg is None:
            continue
        entries.append({
            "id":                nid,
            "displayName":       cfg.display_name,
            "chainId":           cfg.chain_id,
            "nativeAsset":       cfg.native_asset,
            "nativeUnit":        cfg.native_unit,
            "isTestnet":         cfg.is_testnet,
            "receiveEnabled":    is_receive_enabled(nid),
            "sendEnabled":       is_send_enabled(nid),
        })
    return {
        "wallet_engine": (
            "enabled" if crypto_wallet_engine_enabled() else "disabled"
        ),
        "networks": entries,
    }


@router.get("/crypto/wallet/features")
def get_wallet_features(
    principal=Depends(verify_trusted_device),
):


    from crypto_wallet_health import build_features_envelope
    return build_features_envelope()


class CryptoVaultChatClassifyRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


@router.post("/crypto/vault/chat/classify")
def classify_crypto_vault_chat(
    payload: CryptoVaultChatClassifyRequest,
    principal=Depends(verify_trusted_device),
):

    from crypto_vault_chat_control import classify_and_build
    result = classify_and_build(payload.message)

    try:
        logger = logging.getLogger("crypto_wallet_routes")
        logger.info(
            "crypto_vault_chat_classify intent=%s card_type=%s "
            "message_len=%d",
            result.get("intent"),
            result.get("card", {}).get("cardType"),
            len(payload.message),
        )
    except Exception:
        pass
    return result


class VaultChatClassifyRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


@router.post("/vault/chat/classify")
def classify_vault_chat(
    payload: VaultChatClassifyRequest,
    principal=Depends(verify_trusted_device),
):

    from vault_chat_router import classify_and_build_vault_intent
    result = classify_and_build_vault_intent(payload.message)

    try:
        logger = logging.getLogger("crypto_wallet_routes")
        logger.info(
            "vault_chat_classify intent=%s card_type=%s "
            "message_len=%d",
            result.get("intent"),
            result.get("card", {}).get("cardType"),
            len(payload.message),
        )
    except Exception:
        pass
    return result


@router.get("/crypto/wallet/xmr/scanner/status")
def get_xmr_scanner_status(
    platform: Optional[str] = Query(default=None),
    principal=Depends(verify_trusted_device),
):

    from xmr_scanner import (
        get_monero_scanner_adapter,
        _normalize_client_platform,
    )
    from vault_config import (
        monero_scanner_mode as _read_scanner_mode,
    )
    normalized_platform = _normalize_client_platform(platform)
    mode = _read_scanner_mode()
    adapter = get_monero_scanner_adapter(
        client_platform=normalized_platform,
    )
    envelope = adapter.get_status()

    envelope["mode"] = mode

    try:
        logger = logging.getLogger("crypto_wallet_routes")
        logger.info(
            "xmr_scanner_status_check scanner_status=%s reason=%s "
            "can_show_balance=%s can_show_activity=%s can_send=%s "
            "client_platform=%s mode=%s",
            envelope.get("scannerStatus"),
            envelope.get("reason"),
            "true" if envelope.get("canShowBalance") else "false",
            "true" if envelope.get("canShowActivity") else "false",
            "true" if envelope.get("canSend") else "false",
            normalized_platform,
            mode,
        )
    except Exception:
        pass
    return envelope


@router.get("/crypto/wallet/health")
def get_wallet_health(
    request: Request,
    principal=Depends(verify_trusted_device),
):


    from vault_config import (
        cache as _cache_cfg,
        crypto_wallet_health_admin_token,
    )
    from crypto_wallet_health import build_health_envelope
    expected = crypto_wallet_health_admin_token()
    provided = (
        request.headers.get("X-Crypto-Health-Admin-Token")
        or request.headers.get("x-crypto-health-admin-token")
        or ""
    ).strip()
    debug_ok = _cache_cfg().debug_endpoints_enabled
    if expected:
                                                  
        if not provided or not _safe_eq(expected, provided):
            raise HTTPException(
                status_code=403,
                detail={
                    "wallet_engine": "health_forbidden",
                    "message":       "Admin token required.",
                },
            )
    elif not debug_ok:
                                                         
        raise HTTPException(
            status_code=403,
            detail={
                "wallet_engine": "health_forbidden",
                "message":       (
                    "Health endpoint requires "
                    "VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN in production."
                ),
            },
        )
    import datetime
    checked_at = (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat()
    )
    return build_health_envelope(checked_at=checked_at)


@router.get("/crypto/wallet/diagnosis")
def get_wallet_diagnosis(
    request: Request,
    principal=Depends(verify_trusted_device),
):


    from vault_config import (
        cache as _cache_cfg,
        crypto_wallet_health_admin_token,
    )
    from crypto_wallet_diagnosis import build_diagnosis_envelope
    expected = crypto_wallet_health_admin_token()
    provided = (
        request.headers.get("X-Crypto-Health-Admin-Token")
        or request.headers.get("x-crypto-health-admin-token")
        or ""
    ).strip()
    debug_ok = _cache_cfg().debug_endpoints_enabled
    if expected:
        if not provided or not _safe_eq(expected, provided):
            raise HTTPException(
                status_code=403,
                detail={
                    "wallet_engine": "diagnosis_forbidden",
                    "message":       "Admin token required.",
                },
            )
    elif not debug_ok:
        raise HTTPException(
            status_code=403,
            detail={
                "wallet_engine": "diagnosis_forbidden",
                "message":       (
                    "Diagnosis endpoint requires "
                    "VAULTAI_CRYPTO_HEALTH_ADMIN_TOKEN in production."
                ),
            },
        )
    return build_diagnosis_envelope()


def _safe_eq(a: str, b: str) -> bool:


    import hmac
    try:
        return hmac.compare_digest(a, b)
    except (TypeError, ValueError):
        return False


@router.post("/crypto/wallet/{asset}/create")
def create_wallet_account(
    asset: str,
    payload: CreateWalletPayload,
    principal=Depends(verify_trusted_device),
):


    _refuse_plaintext_keys(payload)
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        return _unsupported_asset_response(norm)
    if not _is_slice2_live_asset(norm):
        return _not_ready_response(norm, "create")

                                                             
    if _is_token_asset(norm):
        return {
            "wallet_engine": "use_eth_wallet",
            "asset":         norm,
            "underlyingAsset": "ETH",
            "message": (
                "ERC20 tokens use your existing Ethereum wallet. "
                "Create an Ethereum wallet first via the ETH "
                "Receive panel; the same address holds USDT and "
                "USDC on Sepolia."
            ),
        }

                       
    allowed = ALLOWED_NETWORKS_FOR_ASSET.get(norm, frozenset())
    if payload.network not in allowed:
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "unsupported_network",
                "message": (
                    f"Network {payload.network!r} is not supported "
                    f"for {norm} in slice 2. The engine only "
                    f"accepts: {sorted(allowed)}."
                ),
            },
        )

                                                                 
    from ethereum_sepolia_proxy import is_valid_eth_address
    if not is_valid_eth_address(payload.publicAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_public_address",
                "message": (
                    "The public address must be 0x + 40 hex chars "
                    "for an Ethereum wallet."
                ),
            },
        )

    vault_id = principal["vault_id"]

                                                                   
    existing = _load_wallet_account_record(vault_id, norm)
    if existing is not None:
        return {
            "wallet_engine": "account_exists",
            "message": (
                "A wallet account for this asset already exists in "
                "this vault. Open the existing account instead of "
                "creating a new one."
            ),
            "account": _summarize_for_listing(existing),
        }

                                                              
    record = {
        "schema":                SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
        "asset":                 norm,
        "network":               payload.network,
        "walletLabel":           payload.walletLabel,
        "publicAddress":         payload.publicAddress,
        "encryptedWalletSecret": payload.encryptedWalletSecret,
        "keyOrigin":             KEY_ORIGIN_GENERATED_CLIENT_SIDE,
        "signingMode":           SIGNING_MODE_CLIENT_SIDE,
        "backupStatus":          BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
    }
    _insert_wallet_account_record(vault_id, norm, record)

                                                                 
    logger.info(
        "[WALLET-ENGINE] created vault=%s asset=%s",
        str(vault_id)[:8] + "…", norm,
    )

    return {
        "wallet_engine": "created",
        "account":       _summarize_for_listing(record),
    }


@router.get("/crypto/wallet/{asset}")
def get_wallet_account(
    asset: str,
    principal=Depends(verify_trusted_device),
):


    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        return _unsupported_asset_response(norm)
    if not _is_slice2_live_asset(norm):
        return _not_ready_response(norm, "account_detail")

                                                                 
    underlying = _underlying_eth_asset(norm)
    record = _load_wallet_account_record(principal["vault_id"], underlying)
    if record is None:
        return {
            "wallet_engine":    "no_account",
            "asset":            norm,
            "underlyingAsset":  underlying,
        }
    summary = _summarize_for_listing(record)
    if _is_token_asset(norm):
                                                            
                                                              
        summary["asset"] = norm
        summary["underlyingAsset"] = underlying
    return {
        "wallet_engine": "enabled",
        "account":       summary,
    }


@router.get("/crypto/wallet/{asset}/balance")
def get_wallet_balance(
    asset: str,
    address: Optional[str] = Query(default=None),
    principal=Depends(verify_trusted_device),
):


    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        return _unsupported_asset_response(norm)
    if not _is_slice2_live_asset(norm):
        return _not_ready_response(norm, "balance")

                                                                   
    from ethereum_sepolia_proxy import (
        eth_get_balance_wei,
        erc20_balance_of,
        SepoliaProxyError,
        is_valid_eth_address,
    )

    is_token = _is_token_asset(norm)
    token_unit = (
        ethereum_sepolia_token_unit(norm) if is_token else "ETH"
    )

    def _unavailable(reason: str, addr: Optional[str]) -> dict[str, Any]:
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         "Ethereum Sepolia",
            "publicAddress":   addr or "",
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            token_unit if is_token else None,
            "updatedAt":       None,
            "reason":          reason,
        }

    if not address or not is_valid_eth_address(address):
        return _unavailable("invalid_address", address)

    if not ethereum_sepolia_rpc_url():
        return _unavailable("rpc_not_configured", address)

                                                           
    if is_token:
        contract = ethereum_sepolia_token_contract(norm)
        if not contract:
            return _unavailable("token_contract_not_configured", address)
        if not is_valid_eth_address(contract):
                                                                
            return _unavailable("token_contract_not_configured", address)
        decimals = ethereum_sepolia_token_decimals(norm)
        try:
            base_units = erc20_balance_of(
                token_contract_address=contract,
                holder_address=address,
            )
        except SepoliaProxyError as exc:
            return _unavailable(exc.code, address)
                                                             
                                                               
        scale = Decimal(10) ** decimals
        token_value = (Decimal(base_units) / scale).normalize()
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         "Ethereum Sepolia",
            "publicAddress":   address,
            "balanceStatus":   WALLET_BALANCE_STATUS_AVAILABLE,
            "availableAmount": format(token_value, "f"),
            "unit":            token_unit,
            "updatedAt":       None,
            "baseUnits":       str(base_units),
            "tokenContract":   contract,
            "decimals":        decimals,
        }

    try:
        wei = eth_get_balance_wei(address)
    except SepoliaProxyError as exc:
        return _unavailable(exc.code, address)

                                                                   
    eth_value = (Decimal(wei) / Decimal(WEI_PER_ETH)).normalize()
    return {
        "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
        "asset":           norm,
        "network":         "Ethereum Sepolia",
        "publicAddress":   address,
        "balanceStatus":   WALLET_BALANCE_STATUS_AVAILABLE,
                                                                   
                                                       
        "availableAmount": format(eth_value, "f"),
        "unit":            "ETH",
                                                                   
                                                                  
        "updatedAt":       None,
        "weiAmount":       str(wei),
    }


@router.get("/crypto/wallet/{asset}/transactions")
def list_wallet_transactions(
    asset: str,
    limit: int = 20,
    principal=Depends(verify_trusted_device),
):


    if not crypto_wallet_engine_enabled():
        body = _engine_off_response()
        body["transactions"] = []
        return body
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        body = _unsupported_asset_response(norm)
        body["transactions"] = []
        return body
    if not _is_slice2_live_asset(norm):
        body = _not_ready_response(norm, "transactions")
        body["transactions"] = []
        return body
                                                              
                                                               
    from evm_transaction_history import (
        list_erc20_transactions,
        list_eth_transactions,
    )
    underlying = _underlying_eth_asset(norm)
    record = _load_wallet_account_record(principal["vault_id"], underlying)
    if record is None:
                                                                  
                                                                  
        return {
            "status":             "ok",
            "transactionsStatus": "unavailable",
            "reason":             "no_wallet_yet",
            "asset":              norm,
            "network":            "ethereum_sepolia",
            "networkLabel":       "Ethereum Sepolia",
            "transactions":       [],
            "message": (
                "Create your Ethereum Sepolia wallet first. The "
                "Activity feed loads from the indexer using your "
                "public wallet address."
            ),
        }
    address = record.get("publicAddress")
    if _is_token_asset(norm):
        return list_erc20_transactions(
            address, asset=norm, limit=int(limit),
        )
    return list_eth_transactions(address, limit=int(limit))


@router.get("/crypto/wallet/{asset}/receive")
def get_wallet_receive(
    asset: str,
    principal=Depends(verify_trusted_device),
):


    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        return _unsupported_asset_response(norm)
    if not _is_slice2_live_asset(norm):
        return _not_ready_response(norm, "receive")

                                                                  
    underlying = _underlying_eth_asset(norm)
    record = _load_wallet_account_record(principal["vault_id"], underlying)
    if record is None:
        if _is_token_asset(norm):
            return {
                "wallet_engine":   "create_eth_wallet_first",
                "asset":           norm,
                "underlyingAsset": "ETH",
                "message": (
                    "ERC20 tokens use your existing Ethereum wallet "
                    "address. Create an Ethereum wallet from the ETH "
                    "card first; the same address holds USDT and "
                    "USDC on Sepolia."
                ),
            }
        return {
            "wallet_engine": "no_account",
            "asset":         norm,
            "message": (
                "No wallet account exists yet for this asset. "
                "Create one to get a receive address."
            ),
        }

    if _is_token_asset(norm):
        token_unit = ethereum_sepolia_token_unit(norm)
        return {
            "wallet_engine":   "receive_ready",
            "asset":           norm,
            "underlyingAsset": "ETH",
            "network":         "Ethereum Sepolia",
            "walletLabel":     record.get("walletLabel"),
            "publicAddress":   record.get("publicAddress"),
            "unit":            token_unit,
            "warning": (
                f"Only send {token_unit} on Ethereum Sepolia to this "
                f"address. Sending a different token or sending on a "
                f"different network may result in irreversible loss."
            ),
        }

    return {
        "wallet_engine": "receive_ready",
        "asset":         norm,
        "network":       record.get("network"),
        "walletLabel":   record.get("walletLabel"),
        "publicAddress": record.get("publicAddress"),
        "warning": (
            "Only send Ethereum (Sepolia testnet) to this address. "
            "Sending the wrong asset or sending on the wrong network "
            "may result in irreversible loss."
        ),
    }


def _parse_amount_to_base_units(amount_str: str, decimals: int) -> int:


    if not isinstance(amount_str, str) or not amount_str.strip():
        raise ValueError("amount_required")
    if not isinstance(decimals, int) or decimals < 0:
        raise ValueError("decimals_invalid")
    s = amount_str.strip()
    if "e" in s.lower() or s.startswith("-") or s.startswith("+"):
        raise ValueError("amount_format")
    if s.count(".") > 1:
        raise ValueError("amount_format")
    head, _, tail = s.partition(".")
    if head and not head.isdigit():
        raise ValueError("amount_format")
    if tail and not tail.isdigit():
        raise ValueError("amount_format")
    if not head and not tail:
        raise ValueError("amount_format")
    head = head or "0"
                                                              
                                                               
    tail = (tail + "0" * decimals)[:decimals]
    base_units = int(head) * (10 ** decimals) + int(tail or "0")
    if base_units <= 0:
        raise ValueError("amount_must_be_positive")
    return base_units


def _parse_amount_eth_to_wei(amount_str: str) -> int:


    return _parse_amount_to_base_units(amount_str, 18)


@router.post("/crypto/wallet/{asset}/send/draft")
def create_send_draft(
    asset: str,
    payload: SendDraftPayload,
    principal=Depends(verify_trusted_device),
):


    _refuse_plaintext_keys(payload)
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        return _unsupported_asset_response(norm)
    if not _is_slice2_live_asset(norm):
        return _not_ready_response(norm, "send_draft")

                                                          
    from ethereum_sepolia_proxy import (
        SEPOLIA_CHAIN_ID,
        SepoliaProxyError,
        encode_erc20_transfer_calldata,
        eth_estimate_gas,
        eth_gas_price_wei,
        eth_get_transaction_count,
        is_valid_eth_address,
    )

    is_token = _is_token_asset(norm)

                                                               
    if not is_valid_eth_address(payload.fromAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_from_address",
                "message": (
                    "The from address must be 0x + 40 hex chars."
                ),
            },
        )
    if not is_valid_eth_address(payload.destinationAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_destination_address",
                "message": (
                    "The destination address must be 0x + 40 hex "
                    "chars."
                ),
            },
        )

                                                               
    if is_token:
        decimals = ethereum_sepolia_token_decimals(norm)
        try:
            base_units = _parse_amount_to_base_units(
                payload.amountEth, decimals,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "wallet_engine": "invalid_amount",
                    "message":       str(exc),
                },
            )
                                                                  
                                                                  
        value_wei = 0
    else:
        try:
            value_wei = _parse_amount_eth_to_wei(payload.amountEth)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "wallet_engine": "invalid_amount",
                    "message":       str(exc),
                },
            )
        base_units = value_wei                       

                                                                
    if payload.fromAddress.lower() == payload.destinationAddress.lower():
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "self_send_refused",
                "message": (
                    "The destination address matches the from "
                    "address. Refusing to draft a self-send."
                ),
            },
        )

                                                                
    if not ethereum_sepolia_rpc_url():
        return {
            "status":              "draft_unavailable",
            "asset":               norm,
            "network":             "Ethereum Sepolia",
            "reason":              "rpc_not_configured",
            "message": (
                "Cannot draft a send transaction: the operator has "
                "not configured an Ethereum Sepolia RPC endpoint."
            ),
        }

                                                               
    token_contract = ""
    data_hex = "0x"
    if is_token:
        token_contract = ethereum_sepolia_token_contract(norm)
        if not token_contract or not is_valid_eth_address(token_contract):
            return {
                "status":  "draft_unavailable",
                "asset":   norm,
                "network": "Ethereum Sepolia",
                "reason":  "token_contract_not_configured",
                "message": (
                    "Cannot draft a token send: the operator has "
                    "not configured the ERC20 contract address for "
                    "this token on Sepolia."
                ),
            }
                                                                 
                                                                   
        data_hex = encode_erc20_transfer_calldata(
            destination_address=payload.destinationAddress,
            amount_base_units=base_units,
        )

                                                                 
    transaction_to = token_contract if is_token else payload.destinationAddress
    try:
        nonce = eth_get_transaction_count(payload.fromAddress)
        gas_price = eth_gas_price_wei()
        gas_limit = eth_estimate_gas(
            from_address=payload.fromAddress,
            to_address=transaction_to,
            value_wei=value_wei,
            data_hex=data_hex if is_token else "0x",
        )
    except SepoliaProxyError as exc:
                                                                   
                                                                   
        logger.warning(
            "[WALLET-ENGINE] draft unavailable vault=%s "
            "asset=%s reason=%s",
            str(principal["vault_id"])[:8] + "…", norm, exc.code,
        )
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": "Ethereum Sepolia",
            "reason":  exc.code,
            "message": (
                "Cannot draft a send transaction: the upstream "
                "Sepolia RPC returned an error."
            ),
        }

                                                              
    logger.info(
        "[WALLET-ENGINE] draft ok vault=%s asset=%s",
        str(principal["vault_id"])[:8] + "…", norm,
    )

    if is_token:
        token_unit = ethereum_sepolia_token_unit(norm)
        return {
            "status":              "draft_ready",
            "asset":               norm,
            "network":             "Ethereum Sepolia",
            "fromAddress":         payload.fromAddress,
            "destinationAddress":  payload.destinationAddress,
            "amount":              payload.amountEth,
            "amountBaseUnits":     str(base_units),
            "unit":                token_unit,
            "tokenContract":       token_contract,
            "decimals":            ethereum_sepolia_token_decimals(norm),
                                                          
                                                                    
            "transactionTo":       token_contract,
            "transactionValueWei": "0",
            "dataHex":             data_hex,
            "nonce":               str(nonce),
            "gasLimit":            str(gas_limit),
            "gasPrice":            str(gas_price),
            "chainId":             SEPOLIA_CHAIN_ID,
            "feeUnit":             "ETH",
        }

    return {
        "status":             "draft_ready",
        "asset":              norm,
        "network":            "Ethereum Sepolia",
        "fromAddress":        payload.fromAddress,
        "destinationAddress": payload.destinationAddress,
        "amountEth":          payload.amountEth,
        "amountWei":          str(value_wei),
        "nonce":              str(nonce),
        "gasLimit":           str(gas_limit),
        "gasPrice":           str(gas_price),
        "chainId":            SEPOLIA_CHAIN_ID,
    }


@router.post("/crypto/wallet/{asset}/send/broadcast")
def broadcast_signed_transaction(
    asset: str,
    payload: SendBroadcastPayload,
    principal=Depends(verify_trusted_device),
):


    _refuse_plaintext_keys(payload)
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        return _unsupported_asset_response(norm)
    if not _is_slice2_live_asset(norm):
        return _not_ready_response(norm, "send_broadcast")

    from ethereum_sepolia_proxy import (
        SepoliaProxyError,
        eth_send_raw_transaction,
        is_valid_signed_tx_hex,
    )

                                                                   
    if not is_valid_signed_tx_hex(payload.signedTransaction):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_signed_tx",
                "message": (
                    "The signed transaction must be a 0x-prefixed "
                    "hex string of plausible length."
                ),
            },
        )

    if not ethereum_sepolia_rpc_url():
        return {
            "status":  "broadcast_unavailable",
            "asset":   norm,
            "network": "Ethereum Sepolia",
            "reason":  "rpc_not_configured",
            "message": (
                "Cannot broadcast the transaction: the operator has "
                "not configured an Ethereum Sepolia RPC endpoint."
            ),
        }

    try:
        tx_hash = eth_send_raw_transaction(payload.signedTransaction)
    except SepoliaProxyError as exc:
                                                                   
                                                                 
        logger.warning(
            "[WALLET-ENGINE] broadcast unavailable vault=%s "
            "asset=%s reason=%s",
            str(principal["vault_id"])[:8] + "…", norm, exc.code,
        )
        return {
            "status":  "broadcast_unavailable",
            "asset":   norm,
            "network": "Ethereum Sepolia",
            "reason":  exc.code,
            "message": (
                "Cannot broadcast the transaction: the upstream "
                "Sepolia RPC returned an error."
            ),
        }

                                                                  
    logger.info(
        "[WALLET-ENGINE] broadcast ok vault=%s asset=%s "
        "txHashPrefix=%s",
        str(principal["vault_id"])[:8] + "…", norm,
        (tx_hash or "")[:10],
    )

    return {
        "status":  "submitted",
        "asset":   norm,
        "network": "Ethereum Sepolia",
        "txHash":  tx_hash,
    }


@router.get("/crypto/wallet/{asset}/transaction/{tx_hash}")
def get_transaction_status(
    asset: str,
    tx_hash: str,
    principal=Depends(verify_trusted_device),
):


    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        return _unsupported_asset_response(norm)
    if not _is_slice2_live_asset(norm):
        return _not_ready_response(norm, "transaction_status")

    from ethereum_sepolia_proxy import (
        SepoliaProxyError,
        eth_get_transaction_receipt,
        is_valid_tx_hash,
    )

    if not is_valid_tx_hash(tx_hash):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_tx_hash",
                "message": (
                    "The transaction hash must be 0x + 64 hex chars."
                ),
            },
        )

    if not ethereum_sepolia_rpc_url():
        return {
            "status":  "unavailable",
            "asset":   norm,
            "network": "Ethereum Sepolia",
            "txHash":  tx_hash,
            "reason":  "rpc_not_configured",
        }

    try:
        receipt = eth_get_transaction_receipt(tx_hash)
    except SepoliaProxyError as exc:
        return {
            "status":  "unavailable",
            "asset":   norm,
            "network": "Ethereum Sepolia",
            "txHash":  tx_hash,
            "reason":  exc.code,
        }

    if receipt is None:
                                                            
                              
        return {
            "status":  "pending",
            "asset":   norm,
            "network": "Ethereum Sepolia",
            "txHash":  tx_hash,
        }

    raw_status = receipt.get("status")
                                                                  
    if raw_status == "0x1":
        status_str = "confirmed"
    elif raw_status == "0x0":
        status_str = "failed"
    else:
        status_str = "unknown"

    block_number_hex = receipt.get("blockNumber")
    block_number: Optional[int] = None
    if isinstance(block_number_hex, str) and block_number_hex.startswith("0x"):
        try:
            block_number = int(block_number_hex, 16)
        except ValueError:
            block_number = None

    return {
        "status":      status_str,
        "asset":       norm,
        "network":     "Ethereum Sepolia",
        "txHash":      tx_hash,
        "blockNumber": block_number,
    }


@router.get("/crypto/wallet/{asset}/encrypted-secret")
def get_encrypted_wallet_secret(
    asset: str,
    principal=Depends(verify_trusted_device),
):


    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    norm = _normalize_asset(asset)
    if not asset_is_wallet_engine_supported(norm):
        return _unsupported_asset_response(norm)
    if not _is_slice2_live_asset(norm):
        return _not_ready_response(norm, "encrypted_secret")

                                                                   
    underlying = _underlying_eth_asset(norm)
    record = _load_wallet_account_record(principal["vault_id"], underlying)
    if record is None:
                                                                  
                                                                
        if _is_token_asset(norm):
            return {
                "status":          "create_eth_wallet_first",
                "asset":           norm,
                "underlyingAsset": "ETH",
            }
        return {
            "status":  "no_account",
            "asset":   norm,
        }

    secret = record.get("encryptedWalletSecret")
    if not isinstance(secret, str) or not secret:
                                                         
        return {
            "status":  "no_account",
            "asset":   norm,
        }

                                                                 
    logger.info(
        "[WALLET-ENGINE] encrypted_secret served vault=%s asset=%s",
        str(principal["vault_id"])[:8] + "…", norm,
    )

    response = {
        "status":                "encrypted_secret_ready",
        "asset":                 norm,
        "encryptedWalletSecret": secret,
    }
    if _is_token_asset(norm):
        response["underlyingAsset"] = underlying
    return response


def _unknown_network_envelope(raw_network: str) -> dict[str, Any]:

    return {
        "wallet_engine": "unknown_network",
        "network":       raw_network,
        "message": (
            "Unknown EVM network. Use 'ethereum_sepolia' "
            "(testnet) or 'ethereum_mainnet' (gated)."
        ),
    }


def _network_not_enabled_envelope(
    *, network_id: str, asset: str, capability: str,
) -> dict[str, Any]:


    from evm_networks import network_display_name
    return {
        "wallet_engine":  "network_not_enabled",
        "network":        network_id,
        "asset":          asset,
        "capability":     capability,
        "displayName":    network_display_name(network_id),
        "message": (
            "This EVM network's wallet flow is not enabled in this "
            "deployment. Receive and send remain disabled until "
            "the operator opts in via the network's enable flag."
        ),
    }


def _mainnet_send_paused_envelope(asset: str) -> dict[str, Any]:


    return {
        "wallet_engine": "mainnet_send_paused",
        "status":        "mainnet_send_paused",
        "asset":         asset,
        "network":       "ethereum_mainnet",
        "displayName":   "Ethereum Mainnet",
        "message": (
            "Ethereum Mainnet sending is temporarily paused. "
            "Receive, balance, and activity remain available. Try "
            "again later."
        ),
    }


def _mainnet_send_disabled_envelope(asset: str) -> dict[str, Any]:


    return {
        "wallet_engine":  "mainnet_send_disabled",
        "asset":          asset,
        "network":        "ethereum_mainnet",
        "displayName":    "Ethereum Mainnet",
        "message": (
            "Ethereum Mainnet send is disabled. Set "
            "VAULTAI_CRYPTO_ETH_MAINNET_SEND_ENABLED=true to opt in "
            "after a security review."
        ),
    }


NETWORK_SOLANA_MAINNET: str = "solana_mainnet"
NETWORK_TRON_MAINNET:   str = "tron_mainnet"
NETWORK_MONERO_MAINNET: str = "monero_mainnet"


def _resolve_network_for_route(
    raw_network: str,
) -> tuple[Optional[str], Optional[dict[str, Any]]]:


    from evm_networks import is_known_network, normalize_network_id
    nid = normalize_network_id(raw_network)
    if nid == NETWORK_SOLANA_MAINNET:
        return nid, None
    if nid == NETWORK_TRON_MAINNET:
        return nid, None
    if nid == NETWORK_MONERO_MAINNET:
        return nid, None
    if not is_known_network(nid):
        return None, _unknown_network_envelope(raw_network)
    return nid, None


@router.get("/crypto/wallet/network/{network}/{asset}")
def get_wallet_account_network(
    network: str,
    asset: str,
    principal=Depends(verify_trusted_device),
):


    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled,
    )
    if nid == NETWORK_TRON_MAINNET:
        return _tron_account_detail(asset, principal)
    if nid == NETWORK_MONERO_MAINNET:
        return _xmr_account_detail(asset, principal)
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        if not is_receive_enabled(nid):
            return _network_not_enabled_envelope(
                network_id=nid, asset=asset, capability="account_detail",
            )
        return get_wallet_account(asset, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
        from vault_config import ethereum_mainnet_erc20_receive_enabled
        norm = _normalize_asset(asset)
        if norm in ERC20_TOKEN_ASSETS:
            if not ethereum_mainnet_erc20_receive_enabled():
                body = _network_not_enabled_envelope(
                    network_id=nid, asset=norm,
                    capability="account_detail",
                )
                body["wallet_engine"] = "token_receive_disabled"
                return body
            eth_record = _load_wallet_account_record_network(
                principal["vault_id"], "ETH", nid,
            )
            if eth_record is None:
                return {
                    "wallet_engine":   "create_eth_mainnet_wallet_first",
                    "asset":           norm,
                    "network":         "Ethereum Mainnet",
                    "underlyingAsset": "ETH",
                    "message": (
                        "Mainnet ERC20 tokens use your existing "
                        "Ethereum Mainnet wallet address. Create an "
                        "Ethereum Mainnet wallet from the ETH card "
                        "first; the same address holds USDT and USDC "
                        "on Ethereum Mainnet."
                    ),
                }
            return {
                "wallet_engine": "account_ready",
                "account": {
                    "schema":          SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
                    "asset":           norm,
                    "network":         "ethereum_mainnet",
                    "walletLabel":     eth_record.get("walletLabel"),
                    "publicAddress":   eth_record.get("publicAddress"),
                    "underlyingAsset": "ETH",
                    "keyOrigin":       eth_record.get("keyOrigin"),
                    "signingMode":     eth_record.get("signingMode"),
                    "backupStatus":    eth_record.get("backupStatus"),
                },
            }
        if norm != "ETH":
            return _network_not_enabled_envelope(
                network_id=nid, asset=norm, capability="account_detail",
            )
        if not is_receive_enabled(nid):
            return _network_not_enabled_envelope(
                network_id=nid, asset=norm, capability="account_detail",
            )
        record = _load_wallet_account_record_network(
            principal["vault_id"], norm, nid,
        )
        if record is None:
            return {
                "wallet_engine": "no_account",
                "asset":         norm,
                "network":       "Ethereum Mainnet",
                "message": (
                    "No Ethereum Mainnet wallet exists yet. Create "
                    "one to receive ETH on mainnet."
                ),
            }
        return {
            "wallet_engine": "account_ready",
            "account":       _summarize_for_listing(record),
        }
                                                           
    return _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="account_detail",
    )


@router.get("/crypto/wallet/network/{network}/{asset}/receive")
def get_wallet_receive_network(
    network: str,
    asset: str,
    principal=Depends(verify_trusted_device),
):
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled,
    )
    if nid == NETWORK_SOLANA_MAINNET:
        return _solana_receive(asset, principal)
    if nid == NETWORK_TRON_MAINNET:
        return _tron_receive(asset, principal)
    if nid == NETWORK_MONERO_MAINNET:
        return _xmr_receive(asset, principal)
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        if not is_receive_enabled(nid):
            return _network_not_enabled_envelope(
                network_id=nid, asset=asset, capability="receive",
            )
        return get_wallet_receive(asset, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
        return _mainnet_receive(asset, principal)
    return _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="receive",
    )


def _mainnet_receive(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:


    from evm_networks import NETWORK_ETHEREUM_MAINNET, is_receive_enabled
    from vault_config import ethereum_mainnet_erc20_receive_enabled
    norm = _normalize_asset(asset)
    if norm == "ETH":
        if not is_receive_enabled(NETWORK_ETHEREUM_MAINNET):
            return _network_not_enabled_envelope(
                network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
                capability="receive",
            )
        record = _load_wallet_account_record_network(
            principal["vault_id"], norm, NETWORK_ETHEREUM_MAINNET,
        )
        if record is None:
            return {
                "wallet_engine": "no_account",
                "asset":         norm,
                "network":       "Ethereum Mainnet",
                "message": (
                    "No Ethereum Mainnet wallet exists yet. Create "
                    "one to get a real-funds receive address. The "
                    "mainnet account uses a separate key from your "
                    "Sepolia testnet wallet."
                ),
            }
        return {
            "wallet_engine": "receive_ready",
            "asset":         norm,
            "network":       "Ethereum Mainnet",
            "walletLabel":   record.get("walletLabel"),
            "publicAddress": record.get("publicAddress"),
            "warning": (
                "Ethereum Mainnet uses real funds. Only send ETH on "
                "Ethereum Mainnet to this address. Mainnet "
                "transactions cannot be reversed."
            ),
        }
    if norm in ERC20_TOKEN_ASSETS:
        if not ethereum_mainnet_erc20_receive_enabled():
            body = _network_not_enabled_envelope(
                network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
                capability="receive",
            )
            body["wallet_engine"] = "token_receive_disabled"
            body["message"] = (
                "Ethereum Mainnet token receive is not enabled in "
                "this deployment. Set "
                "VAULTAI_CRYPTO_ETH_MAINNET_ERC20_RECEIVE_ENABLED=true "
                "to opt in after a security review."
            )
            return body
                                                                    
                                                                     
        record = _load_wallet_account_record_network(
            principal["vault_id"], "ETH", NETWORK_ETHEREUM_MAINNET,
        )
        if record is None:
            return {
                "wallet_engine":   "create_eth_mainnet_wallet_first",
                "asset":           norm,
                "network":         "Ethereum Mainnet",
                "underlyingAsset": "ETH",
                "message": (
                    "Mainnet ERC20 tokens use your existing Ethereum "
                    "Mainnet wallet address. Create an Ethereum "
                    "Mainnet wallet from the ETH card first; the same "
                    "address holds USDT and USDC on Ethereum Mainnet."
                ),
            }
        token_unit = (
            "USDT" if norm == "USDT_ERC20" else "USDC"
        )
        return {
            "wallet_engine":   "receive_ready",
            "asset":           norm,
            "network":         "Ethereum Mainnet",
            "underlyingAsset": "ETH",
            "walletLabel":     record.get("walletLabel"),
            "publicAddress":   record.get("publicAddress"),
            "unit":            token_unit,
            "warning": (
                f"Only send {token_unit} on Ethereum Mainnet to this "
                "address. Mainnet funds are real and transactions "
                "cannot be reversed."
            ),
            "gasNote": (
                "Sending this token later will require ETH for gas."
            ),
            "sharedAddressNote": (
                "This token uses your Ethereum Mainnet wallet address."
            ),
        }
    return _network_not_enabled_envelope(
        network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
        capability="receive",
    )


@router.get("/crypto/wallet/network/{network}/{asset}/balance")
def get_wallet_balance_network(
    network: str,
    asset: str,
    address: Optional[str] = Query(default=None),
    principal=Depends(verify_trusted_device),
):
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled,
    )
    if nid == NETWORK_SOLANA_MAINNET:
        return _solana_balance(asset, address, principal)
    if nid == NETWORK_TRON_MAINNET:
        return _tron_balance(asset, address, principal)
    if nid == NETWORK_MONERO_MAINNET:
        return _xmr_balance(asset, principal)
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        if not is_receive_enabled(nid):
            return _network_not_enabled_envelope(
                network_id=nid, asset=asset, capability="balance",
            )
        return get_wallet_balance(asset, address, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
        return _get_mainnet_balance(asset, address)
    return _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="balance",
    )


def _get_mainnet_balance(
    asset: str, address: Optional[str],
) -> dict[str, Any]:


    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, is_receive_enabled, token_contract_for,
    )
    from evm_rpc import (
        EvmRpcError, erc20_balance_of_at_url,
        eth_get_balance_wei_at_url, is_valid_eth_address,
    )
    from vault_config import (
        ethereum_mainnet_erc20_receive_enabled,
        ethereum_mainnet_rpc_url,
        ethereum_mainnet_token_decimals,
        ethereum_mainnet_token_unit,
    )
    norm = _normalize_asset(asset)
    is_eth = norm == "ETH"
    is_token = norm in ERC20_TOKEN_ASSETS

    if not is_eth and not is_token:
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         "Ethereum Mainnet",
            "publicAddress":   address or "",
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            None,
            "updatedAt":       None,
            "reason":          "asset_not_enabled_on_mainnet",
        }

                                                                  
    if is_eth and not is_receive_enabled(NETWORK_ETHEREUM_MAINNET):
        return _network_not_enabled_envelope(
            network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
            capability="balance",
        )
    if is_token and not ethereum_mainnet_erc20_receive_enabled():
        body = _network_not_enabled_envelope(
            network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
            capability="balance",
        )
        body["wallet_engine"] = "token_receive_disabled"
        return body

    token_unit = (
        ethereum_mainnet_token_unit(norm) if is_token else "ETH"
    )

    def _unavailable(reason: str) -> dict[str, Any]:
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         "Ethereum Mainnet",
            "publicAddress":   address or "",
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            token_unit if is_token else None,
            "updatedAt":       None,
            "reason":          reason,
        }

    if not address or not is_valid_eth_address(address):
        return _unavailable("invalid_address")
    rpc_url = ethereum_mainnet_rpc_url()
    if not rpc_url:
        return _unavailable("rpc_not_configured")

    if is_token:
        contract = token_contract_for(NETWORK_ETHEREUM_MAINNET, norm)
        if not contract or not is_valid_eth_address(contract):
            return _unavailable("token_contract_not_configured")
        decimals = ethereum_mainnet_token_decimals(norm)
        try:
            base_units = erc20_balance_of_at_url(
                rpc_url,
                token_contract_address=contract,
                holder_address=address,
            )
        except EvmRpcError as exc:
            return _unavailable(exc.code)
        scale = Decimal(10) ** decimals
        token_value = (Decimal(base_units) / scale).normalize()
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         "Ethereum Mainnet",
            "publicAddress":   address,
            "balanceStatus":   WALLET_BALANCE_STATUS_AVAILABLE,
            "availableAmount": format(token_value, "f"),
            "unit":            token_unit,
            "updatedAt":       None,
            "baseUnits":       str(base_units),
            "tokenContract":   contract,
            "decimals":        decimals,
        }

    try:
        wei = eth_get_balance_wei_at_url(rpc_url, address)
    except EvmRpcError as exc:
        return _unavailable(exc.code)
    eth_value = (Decimal(wei) / Decimal(WEI_PER_ETH)).normalize()
    return {
        "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
        "asset":           norm,
        "network":         "Ethereum Mainnet",
        "publicAddress":   address,
        "balanceStatus":   WALLET_BALANCE_STATUS_AVAILABLE,
        "availableAmount": format(eth_value, "f"),
        "unit":            "ETH",
        "updatedAt":       None,
        "weiAmount":       str(wei),
    }


@router.get("/crypto/wallet/network/{network}/{asset}/transactions")
def list_wallet_transactions_network(
    network: str,
    asset: str,
    limit: int = 20,
    principal=Depends(verify_trusted_device),
):
    if not crypto_wallet_engine_enabled():
        body = _engine_off_response()
        body["transactions"] = []
        return body
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        err["transactions"] = []
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled,
    )
    if nid == NETWORK_SOLANA_MAINNET:
        return _solana_transactions(asset, limit, principal)
    if nid == NETWORK_TRON_MAINNET:
        return _tron_transactions(asset, limit, principal)
    if nid == NETWORK_MONERO_MAINNET:
        return _xmr_transactions(asset, limit, principal)
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        if not is_receive_enabled(nid):
            body = _network_not_enabled_envelope(
                network_id=nid, asset=asset, capability="transactions",
            )
            body["transactions"] = []
            return body
        return list_wallet_transactions(asset, limit, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
        return _list_mainnet_transactions(asset, limit, principal)
    body = _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="transactions",
    )
    body["transactions"] = []
    return body


def _list_mainnet_transactions(
    asset: str, limit: int, principal: dict[str, Any],
) -> dict[str, Any]:


    from evm_networks import NETWORK_ETHEREUM_MAINNET, is_receive_enabled
    from evm_transaction_history import (
        list_eth_transactions, list_erc20_transactions,
    )
    from vault_config import ethereum_mainnet_erc20_receive_enabled
    norm = _normalize_asset(asset)
    is_eth = norm == "ETH"
    is_token = norm in ERC20_TOKEN_ASSETS
    if not is_eth and not is_token:
        return {
            "status":             "ok",
            "transactionsStatus": "unavailable",
            "reason":             "asset_not_enabled_on_mainnet",
            "asset":              norm,
            "network":            NETWORK_ETHEREUM_MAINNET,
            "networkLabel":       "Ethereum Mainnet",
            "transactions":       [],
            "message": (
                "Mainnet transaction history is only enabled for ETH, "
                "USDT_ERC20, and USDC_ERC20 in this build."
            ),
        }
    if is_eth and not is_receive_enabled(NETWORK_ETHEREUM_MAINNET):
        body = _network_not_enabled_envelope(
            network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
            capability="transactions",
        )
        body["transactions"] = []
        return body
    if is_token and not ethereum_mainnet_erc20_receive_enabled():
        body = _network_not_enabled_envelope(
            network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
            capability="transactions",
        )
        body["wallet_engine"] = "token_receive_disabled"
        body["transactions"] = []
        return body
                                                                 
                                                                
    record = _load_wallet_account_record_network(
        principal["vault_id"], "ETH", NETWORK_ETHEREUM_MAINNET,
    )
    if record is None:
        reason = (
            "no_wallet_yet" if is_eth
            else "create_eth_mainnet_wallet_first"
        )
        message = (
            "Create your Ethereum Mainnet wallet first. The "
            "Activity feed loads from the mainnet indexer using "
            "your public mainnet wallet address."
            if is_eth
            else (
                "Create your Ethereum Mainnet wallet first. ERC20 "
                "tokens share the same Ethereum Mainnet address — "
                "Activity loads from the mainnet indexer once the "
                "address exists."
            )
        )
        return {
            "status":             "ok",
            "transactionsStatus": "unavailable",
            "reason":             reason,
            "asset":              norm,
            "network":            NETWORK_ETHEREUM_MAINNET,
            "networkLabel":       "Ethereum Mainnet",
            "transactions":       [],
            "message":            message,
        }
    if is_token:
        return list_erc20_transactions(
            record.get("publicAddress"),
            asset=norm, limit=int(limit),
            network_id=NETWORK_ETHEREUM_MAINNET,
        )
    return list_eth_transactions(
        record.get("publicAddress"), limit=int(limit),
        network_id=NETWORK_ETHEREUM_MAINNET,
    )


@router.post("/crypto/wallet/network/{network}/{asset}/create")
def create_wallet_account_network(
    network: str,
    asset: str,
    payload: CreateWalletPayload,
    principal=Depends(verify_trusted_device),
):
    _refuse_plaintext_keys(payload)
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled,
    )
    if nid == NETWORK_SOLANA_MAINNET:
        return _create_solana_wallet_account(asset, payload, principal)
    if nid == NETWORK_TRON_MAINNET:
        return _create_tron_wallet_account(asset, payload, principal)
    if nid == NETWORK_MONERO_MAINNET:
        return _create_xmr_wallet_account(asset, payload, principal)
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        if not is_receive_enabled(nid):
            return _network_not_enabled_envelope(
                network_id=nid, asset=asset, capability="create",
            )
        return create_wallet_account(asset, payload, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
        return _create_mainnet_wallet_account(asset, payload, principal)
    return _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="create",
    )


def _create_mainnet_wallet_account(
    asset: str,
    payload: "CreateWalletPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:


    from ethereum_sepolia_proxy import is_valid_eth_address
    from evm_networks import NETWORK_ETHEREUM_MAINNET, is_receive_enabled
    from vault_config import ethereum_mainnet_erc20_receive_enabled
    norm = _normalize_asset(asset)
    if norm in ERC20_TOKEN_ASSETS:
        if not ethereum_mainnet_erc20_receive_enabled():
            body = _network_not_enabled_envelope(
                network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
                capability="create",
            )
            body["wallet_engine"] = "token_receive_disabled"
            return body
        existing_eth = _load_wallet_account_record_network(
            principal["vault_id"], "ETH", NETWORK_ETHEREUM_MAINNET,
        )
        if existing_eth is None:
            return {
                "wallet_engine":   "create_eth_mainnet_wallet_first",
                "asset":           norm,
                "network":         "Ethereum Mainnet",
                "underlyingAsset": "ETH",
                "message": (
                    "Mainnet ERC20 tokens use your existing Ethereum "
                    "Mainnet wallet address. Create an Ethereum "
                    "Mainnet wallet from the ETH card first; the same "
                    "address holds USDT and USDC on Ethereum Mainnet."
                ),
            }
        return {
            "wallet_engine":   "token_uses_eth_address",
            "asset":           norm,
            "network":         "Ethereum Mainnet",
            "underlyingAsset": "ETH",
            "publicAddress":   existing_eth.get("publicAddress"),
            "message": (
                "USDT and USDC on Ethereum Mainnet reuse your "
                "Ethereum Mainnet wallet address. No separate token "
                "wallet is created."
            ),
        }
    if not is_receive_enabled(NETWORK_ETHEREUM_MAINNET):
        return _network_not_enabled_envelope(
            network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
            capability="create",
        )
    if norm != "ETH":
        return _network_not_enabled_envelope(
            network_id=NETWORK_ETHEREUM_MAINNET, asset=norm,
            capability="create",
        )
                                                                
                                                                  
    if not is_valid_eth_address(payload.publicAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_public_address",
                "message": (
                    "The public address must be 0x + 40 hex chars "
                    "for an Ethereum Mainnet wallet."
                ),
            },
        )
    vault_id = principal["vault_id"]
                                                              
                                                                 
    existing = _load_wallet_account_record_network(
        vault_id, norm, NETWORK_ETHEREUM_MAINNET,
    )
    if existing is not None:
        return {
            "wallet_engine": "account_exists",
            "message": (
                "An Ethereum Mainnet wallet account already exists in "
                "this vault. Open the existing account instead of "
                "creating a new one."
            ),
            "account": _summarize_for_listing(existing),
        }
    record = {
        "schema":                SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
        "asset":                 norm,
                                                                  
                                                                    
        "network":               NETWORK_ETHEREUM_MAINNET,
        "walletLabel":           payload.walletLabel,
        "publicAddress":         payload.publicAddress,
        "encryptedWalletSecret": payload.encryptedWalletSecret,
        "keyOrigin":             KEY_ORIGIN_GENERATED_CLIENT_SIDE,
        "signingMode":           SIGNING_MODE_CLIENT_SIDE,
        "backupStatus":          BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
    }
    _insert_wallet_account_record_network(
        vault_id, norm, NETWORK_ETHEREUM_MAINNET, record,
    )
    logger.info(
        "[WALLET-ENGINE] mainnet_created vault=%s asset=%s",
        str(vault_id)[:8] + "…", norm,
    )
    return {
        "wallet_engine": "created",
        "account":       _summarize_for_listing(record),
    }


@router.post("/crypto/wallet/network/{network}/{asset}/send/draft")
def create_send_draft_network(
    network: str,
    asset: str,
    payload: SendDraftPayload,
    principal=Depends(verify_trusted_device),
):
    _refuse_plaintext_keys(payload)
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_send_enabled,
    )
    if nid == NETWORK_SOLANA_MAINNET:
        return _solana_send_dispatch(asset, payload, principal)
    if nid == NETWORK_TRON_MAINNET:
        return _tron_send_dispatch(asset, payload, principal)
    if nid == NETWORK_MONERO_MAINNET:
        return _xmr_send_not_enabled_envelope(asset)
    if not is_send_enabled(nid):
        if nid == NETWORK_ETHEREUM_MAINNET:
            return _mainnet_send_disabled_envelope(asset)
        return _network_not_enabled_envelope(
            network_id=nid, asset=asset, capability="send_draft",
        )
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        return create_send_draft(asset, payload, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
        return _create_mainnet_send_draft(asset, payload, principal)
    return _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="send_draft",
    )


def _create_mainnet_send_draft(
    asset: str,
    payload: "SendDraftPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:


    from evm_networks import NETWORK_ETHEREUM_MAINNET, chain_id_for
    from evm_rpc import (
        EvmRpcError, encode_erc20_transfer_calldata,
        eth_estimate_gas_at_url, eth_gas_price_wei_at_url,
        eth_get_transaction_count_at_url, is_valid_eth_address,
    )
    from vault_config import (
        ethereum_mainnet_rpc_url,
        ethereum_mainnet_send_paused,
        ethereum_mainnet_token_decimals,
        ethereum_mainnet_token_unit,
    )
    norm = _normalize_asset(asset)
                                                                     
                                                                    
    if ethereum_mainnet_send_paused():
        return _mainnet_send_paused_envelope(norm)
    is_eth = norm == "ETH"
    is_token = norm in ERC20_TOKEN_ASSETS
    if not is_eth and not is_token:
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "reason":  "asset_not_enabled_on_mainnet",
            "message": (
                "Mainnet send is only enabled for ETH, USDT_ERC20, "
                "and USDC_ERC20 in this build."
            ),
        }

    if not is_valid_eth_address(payload.fromAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_from_address",
                "message": (
                    "The from address must be 0x + 40 hex chars."
                ),
            },
        )
    if not is_valid_eth_address(payload.destinationAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_destination_address",
                "message": (
                    "The destination address must be 0x + 40 hex "
                    "chars."
                ),
            },
        )

    if is_token:
        decimals = ethereum_mainnet_token_decimals(norm)
        try:
            base_units = _parse_amount_to_base_units(
                payload.amountEth, decimals,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "wallet_engine": "invalid_amount",
                    "message":       str(exc),
                },
            )
        value_wei = 0
    else:
        try:
            value_wei = _parse_amount_eth_to_wei(payload.amountEth)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "wallet_engine": "invalid_amount",
                    "message":       str(exc),
                },
            )
        base_units = value_wei

    if payload.fromAddress.lower() == payload.destinationAddress.lower():
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "self_send_refused",
                "message": (
                    "The destination address matches the from "
                    "address. Refusing to draft a self-send."
                ),
            },
        )

    rpc_url = ethereum_mainnet_rpc_url()
    if not rpc_url:
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "reason":  "rpc_not_configured",
            "message": (
                "Cannot draft a mainnet send: the operator has not "
                "configured an Ethereum Mainnet RPC endpoint."
            ),
        }

    token_contract = ""
    data_hex = "0x"
    if is_token:
        from evm_networks import token_contract_for
        token_contract = token_contract_for(
            NETWORK_ETHEREUM_MAINNET, norm,
        )
        if not token_contract or not is_valid_eth_address(token_contract):
            return {
                "status":  "draft_unavailable",
                "asset":   norm,
                "network": "Ethereum Mainnet",
                "reason":  "token_contract_not_configured",
                "message": (
                    "Cannot draft a mainnet token send: the operator "
                    "has not configured the ERC20 contract address "
                    "for this token on Ethereum Mainnet."
                ),
            }
        try:
            data_hex = encode_erc20_transfer_calldata(
                destination_address=payload.destinationAddress,
                amount_base_units=base_units,
            )
        except EvmRpcError as exc:
            return {
                "status":  "draft_unavailable",
                "asset":   norm,
                "network": "Ethereum Mainnet",
                "reason":  exc.code,
                "message": (
                    "Cannot encode the token transfer calldata."
                ),
            }

    transaction_to = (
        token_contract if is_token else payload.destinationAddress
    )

    try:
        nonce = eth_get_transaction_count_at_url(
            rpc_url, payload.fromAddress,
        )
        gas_price = eth_gas_price_wei_at_url(rpc_url)
        gas_limit = eth_estimate_gas_at_url(
            rpc_url,
            from_address=payload.fromAddress,
            to_address=transaction_to,
            value_wei=value_wei,
            data_hex=data_hex if is_token else "0x",
        )
    except EvmRpcError as exc:
        logger.warning(
            "[WALLET-ENGINE] mainnet_draft_unavailable vault=%s "
            "asset=%s reason=%s",
            str(principal["vault_id"])[:8] + "…", norm, exc.code,
        )
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "reason":  exc.code,
            "message": (
                "Cannot draft a mainnet send: the upstream Ethereum "
                "Mainnet RPC returned an error."
            ),
        }

    logger.info(
        "[WALLET-ENGINE] mainnet_draft_ok vault=%s asset=%s",
        str(principal["vault_id"])[:8] + "…", norm,
    )

    mainnet_chain_id = chain_id_for(NETWORK_ETHEREUM_MAINNET)

    if is_token:
        token_unit = ethereum_mainnet_token_unit(norm)
        return {
            "status":              "draft_ready",
            "asset":               norm,
            "network":             "Ethereum Mainnet",
            "fromAddress":         payload.fromAddress,
            "destinationAddress":  payload.destinationAddress,
            "amount":              payload.amountEth,
            "amountBaseUnits":     str(base_units),
            "unit":                token_unit,
            "tokenContract":       token_contract,
            "decimals":            ethereum_mainnet_token_decimals(norm),
            "transactionTo":       token_contract,
            "transactionValueWei": "0",
            "dataHex":             data_hex,
            "nonce":               str(nonce),
            "gasLimit":            str(gas_limit),
            "gasPrice":            str(gas_price),
            "chainId":             mainnet_chain_id,
            "feeUnit":             "ETH",
            "realFundsWarning": (
                "This sends real tokens on Ethereum Mainnet. Gas is "
                "paid in ETH. Transactions cannot be reversed."
            ),
        }

    return {
        "status":             "draft_ready",
        "asset":              norm,
        "network":            "Ethereum Mainnet",
        "fromAddress":        payload.fromAddress,
        "destinationAddress": payload.destinationAddress,
        "amountEth":          payload.amountEth,
        "amountWei":          str(value_wei),
        "nonce":              str(nonce),
        "gasLimit":           str(gas_limit),
        "gasPrice":           str(gas_price),
        "chainId":            mainnet_chain_id,
        "feeUnit":            "ETH",
        "realFundsWarning": (
            "This sends real ETH on Ethereum Mainnet. Transactions "
            "cannot be reversed."
        ),
    }


@router.post("/crypto/wallet/network/{network}/{asset}/send/broadcast")
def broadcast_signed_transaction_network(
    network: str,
    asset: str,
    payload: SendBroadcastPayload,
    principal=Depends(verify_trusted_device),
):
    _refuse_plaintext_keys(payload)
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_send_enabled,
    )
    if nid == NETWORK_SOLANA_MAINNET:
        return _solana_broadcast_dispatch(
            asset, payload, principal,
        )
    if nid == NETWORK_TRON_MAINNET:
        return _tron_broadcast_dispatch(
            asset, payload, principal,
        )
    if nid == NETWORK_MONERO_MAINNET:
        return _xmr_send_not_enabled_envelope(asset)
    if not is_send_enabled(nid):
        if nid == NETWORK_ETHEREUM_MAINNET:
            return _mainnet_send_disabled_envelope(asset)
        return _network_not_enabled_envelope(
            network_id=nid, asset=asset, capability="send_broadcast",
        )
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        return broadcast_signed_transaction(asset, payload, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
        return _broadcast_mainnet_signed_transaction(
            asset, payload, principal,
        )
    return _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="send_broadcast",
    )


def _broadcast_mainnet_signed_transaction(
    asset: str,
    payload: "SendBroadcastPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:


    from evm_rpc import (
        EvmRpcError, eth_send_raw_transaction_at_url,
        is_valid_signed_tx_hex,
    )
    from vault_config import (
        ethereum_mainnet_rpc_url,
        ethereum_mainnet_send_paused,
    )
    norm = _normalize_asset(asset)
    vault_id = principal["vault_id"]
                         
    if ethereum_mainnet_send_paused():
        return _mainnet_send_paused_envelope(norm)
                                      
    if norm != "ETH" and norm not in ERC20_TOKEN_ASSETS:
        return {
            "status":  "broadcast_unavailable",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "reason":  "asset_not_enabled_on_mainnet",
            "message": (
                "Mainnet broadcast is only enabled for ETH, "
                "USDT_ERC20, and USDC_ERC20 in this build."
            ),
        }
    if not is_valid_signed_tx_hex(payload.signedTransaction):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_signed_tx",
                "message": (
                    "The signed transaction must be a 0x-prefixed "
                    "hex string of plausible length."
                ),
            },
        )
                         
    rpc_url = ethereum_mainnet_rpc_url()
    if not rpc_url:
        return {
            "status":  "broadcast_unavailable",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "reason":  "rpc_not_configured",
            "message": (
                "Cannot broadcast the mainnet transaction: the "
                "operator has not configured an Ethereum Mainnet "
                "RPC endpoint."
            ),
        }
                                                                
                                                               
    idem_key = _validate_idempotency_key(
        getattr(payload, "idempotencyKey", None),
    )
    if idem_key:
        cached, conflict = _lookup_idempotent_broadcast(
            vault_id, idem_key, payload.signedTransaction,
        )
        if conflict:
            logger.warning(
                "[WALLET-ENGINE] mainnet_broadcast_idem_conflict "
                "vault=%s asset=%s",
                str(vault_id)[:8] + "…", norm,
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "wallet_engine": "idempotency_conflict",
                    "message": (
                        "This idempotency key was already used for a "
                        "different signed transaction. Generate a "
                        "fresh key for a new send attempt."
                    ),
                },
            )
        if cached is not None:
            logger.info(
                "[WALLET-ENGINE] mainnet_broadcast_idem_hit "
                "vault=%s asset=%s",
                str(vault_id)[:8] + "…", norm,
            )
            return cached
                              
    rate_blocked = _check_mainnet_broadcast_rate_limit(vault_id)
    if rate_blocked is not None:
        raise HTTPException(
            status_code=429,
            detail=rate_blocked["envelope"],
            headers={
                "Retry-After": str(rate_blocked["retry_after"]),
            },
        )
                        
    try:
        tx_hash = eth_send_raw_transaction_at_url(
            rpc_url, payload.signedTransaction,
        )
    except EvmRpcError as exc:
        logger.warning(
            "[WALLET-ENGINE] mainnet_broadcast_unavailable vault=%s "
            "asset=%s reason=%s",
            str(vault_id)[:8] + "…", norm, exc.code,
        )
        return {
            "status":  "broadcast_unavailable",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "reason":  exc.code,
            "message": (
                "Cannot broadcast the mainnet transaction: the "
                "upstream Ethereum Mainnet RPC returned an error."
            ),
        }
    logger.info(
        "[WALLET-ENGINE] mainnet_broadcast_ok vault=%s asset=%s "
        "txHashPrefix=%s",
        str(vault_id)[:8] + "…", norm,
        (tx_hash or "")[:10],
    )
    envelope = {
        "status":  "submitted",
        "asset":   norm,
        "network": "Ethereum Mainnet",
        "txHash":  tx_hash,
    }
                                                                    
                                                                    
    _record_idempotent_broadcast(
        vault_id, idem_key or "", payload.signedTransaction, envelope,
    )
    return envelope


@router.get(
    "/crypto/wallet/network/{network}/{asset}/transaction/{tx_hash}",
)
def get_transaction_status_network(
    network: str,
    asset: str,
    tx_hash: str,
    principal=Depends(verify_trusted_device),
):
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled, is_send_enabled,
    )
    if nid == NETWORK_SOLANA_MAINNET:
        return _solana_transaction_status(asset, tx_hash)
    if nid == NETWORK_TRON_MAINNET:
        return _tron_transaction_status(asset, tx_hash)
    if nid == NETWORK_MONERO_MAINNET:
        return _xmr_send_not_enabled_envelope(asset)
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        if not is_receive_enabled(nid):
            return _network_not_enabled_envelope(
                network_id=nid, asset=asset,
                capability="transaction_status",
            )
        return get_transaction_status(asset, tx_hash, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
                                                                    
                                                                   
        from vault_config import ethereum_mainnet_erc20_receive_enabled
        if not (
            is_receive_enabled(nid)
            or is_send_enabled(nid)
            or ethereum_mainnet_erc20_receive_enabled()
        ):
            return _network_not_enabled_envelope(
                network_id=nid, asset=asset,
                capability="transaction_status",
            )
        return _get_mainnet_transaction_status(asset, tx_hash)
    return _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="transaction_status",
    )


def _get_mainnet_transaction_status(
    asset: str, tx_hash: str,
) -> dict[str, Any]:


    from evm_rpc import (
        EvmRpcError, eth_get_transaction_receipt_at_url,
        is_valid_tx_hash,
    )
    from vault_config import ethereum_mainnet_rpc_url
    norm = _normalize_asset(asset)

    if not is_valid_tx_hash(tx_hash):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_tx_hash",
                "message": (
                    "The transaction hash must be 0x + 64 hex chars."
                ),
            },
        )

    rpc_url = ethereum_mainnet_rpc_url()
    if not rpc_url:
        return {
            "status":  "unavailable",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "txHash":  tx_hash,
            "reason":  "rpc_not_configured",
        }

    try:
        receipt = eth_get_transaction_receipt_at_url(rpc_url, tx_hash)
    except EvmRpcError as exc:
        return {
            "status":  "unavailable",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "txHash":  tx_hash,
            "reason":  exc.code,
        }

    if receipt is None:
        return {
            "status":  "pending",
            "asset":   norm,
            "network": "Ethereum Mainnet",
            "txHash":  tx_hash,
        }

    raw_status = receipt.get("status")
    if raw_status == "0x1":
        status_str = "confirmed"
    elif raw_status == "0x0":
        status_str = "failed"
    else:
        status_str = "unknown"

    block_number_hex = receipt.get("blockNumber")
    block_number: Optional[int] = None
    if isinstance(block_number_hex, str) and block_number_hex.startswith("0x"):
        try:
            block_number = int(block_number_hex, 16)
        except ValueError:
            block_number = None

    return {
        "status":      status_str,
        "asset":       norm,
        "network":     "Ethereum Mainnet",
        "txHash":      tx_hash,
        "blockNumber": block_number,
    }


@router.get(
    "/crypto/wallet/network/{network}/{asset}/encrypted-secret",
)
def get_encrypted_wallet_secret_network(
    network: str,
    asset: str,
    principal=Depends(verify_trusted_device),
):
    if not crypto_wallet_engine_enabled():
        return _engine_off_response()
    nid, err = _resolve_network_for_route(network)
    if err is not None:
        return err
    from evm_networks import (
        NETWORK_ETHEREUM_MAINNET, NETWORK_ETHEREUM_SEPOLIA,
        is_receive_enabled, is_send_enabled,
    )
    if nid == NETWORK_SOLANA_MAINNET:
        return _solana_encrypted_secret(asset, principal)
    if nid == NETWORK_TRON_MAINNET:
        return _tron_encrypted_secret(asset, principal)
    if nid == NETWORK_MONERO_MAINNET:
        return _xmr_send_not_enabled_envelope(asset)
    if nid == NETWORK_ETHEREUM_SEPOLIA:
        if not is_receive_enabled(nid):
            return _network_not_enabled_envelope(
                network_id=nid, asset=asset,
                capability="encrypted_secret",
            )
        return get_encrypted_wallet_secret(asset, principal)
    if nid == NETWORK_ETHEREUM_MAINNET:
        from vault_config import ethereum_mainnet_erc20_receive_enabled
        norm = _normalize_asset(asset)
                                                                   
                                                                  
        if norm == "ETH":
            if not (is_receive_enabled(nid) or is_send_enabled(nid)):
                return _network_not_enabled_envelope(
                    network_id=nid, asset=norm,
                    capability="encrypted_secret",
                )
        elif norm in ERC20_TOKEN_ASSETS:
            if not (
                ethereum_mainnet_erc20_receive_enabled()
                or is_send_enabled(nid)
            ):
                body = _network_not_enabled_envelope(
                    network_id=nid, asset=norm,
                    capability="encrypted_secret",
                )
                body["wallet_engine"] = "token_receive_disabled"
                return body
        else:
            return _network_not_enabled_envelope(
                network_id=nid, asset=norm,
                capability="encrypted_secret",
            )
                                                                        
                                                                    
        record = _load_wallet_account_record_network(
            principal["vault_id"], "ETH", NETWORK_ETHEREUM_MAINNET,
        )
        if record is None:
            if norm in ERC20_TOKEN_ASSETS:
                return {
                    "status":          "create_eth_mainnet_wallet_first",
                    "asset":           norm,
                    "network":         "Ethereum Mainnet",
                    "underlyingAsset": "ETH",
                }
            return {
                "status":  "no_account",
                "asset":   norm,
                "network": "Ethereum Mainnet",
            }
        secret = record.get("encryptedWalletSecret")
        if not secret:
            return {
                "status":  "no_account",
                "asset":   norm,
                "network": "Ethereum Mainnet",
            }
        return {
            "status":                "encrypted_secret_ready",
            "asset":                 norm,
            "network":               "Ethereum Mainnet",
            "encryptedWalletSecret": secret,
        }
    return _network_not_enabled_envelope(
        network_id=nid, asset=asset, capability="encrypted_secret",
    )


_SOLANA_ASSET: str = "SOL"
_SOLANA_NETWORK_LABEL: str = "solana_mainnet"


def _solana_disabled_envelope(
    asset: str, capability: str,
) -> dict[str, Any]:
    return {
        "wallet_engine": "solana_not_enabled",
        "asset":         _normalize_asset(asset),
        "network":       _SOLANA_NETWORK_LABEL,
        "capability":    capability,
        "message":       "Solana is temporarily unavailable.",
    }


def _solana_send_not_enabled_envelope(asset: str) -> dict[str, Any]:
    return {
        "wallet_engine": "solana_send_not_enabled",
        "asset":         _normalize_asset(asset),
        "network":       _SOLANA_NETWORK_LABEL,
        "message":       "Solana sending is not enabled yet.",
    }


def _solana_receive(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import solana_enabled
    norm = _normalize_asset(asset)
    if norm != _SOLANA_ASSET:
        return _network_not_enabled_envelope(
            network_id=NETWORK_SOLANA_MAINNET, asset=norm,
            capability="receive",
        )
    if not solana_enabled():
        return _solana_disabled_envelope(norm, "receive")
    record = _load_wallet_account_record_network(
        principal["vault_id"], norm, NETWORK_SOLANA_MAINNET,
    )
    if record is None:
        return {
            "wallet_engine": "create_solana_wallet_first",
            "asset":         norm,
            "network":       _SOLANA_NETWORK_LABEL,
            "networkLabel":  "Solana",
            "message": (
                "No Solana wallet exists yet. Create one on this "
                "device to get a real Solana receive address. The "
                "Solana wallet uses a separate key from your "
                "Ethereum wallets."
            ),
        }
    return {
        "wallet_engine": "receive_ready",
        "asset":         norm,
        "network":       _SOLANA_NETWORK_LABEL,
        "networkLabel":  "Solana",
        "walletLabel":   record.get("walletLabel"),
        "publicAddress": record.get("publicAddress"),
        "warning": (
            "Only send SOL on Solana to this address."
        ),
    }


def _solana_balance(
    asset: str, address: Optional[str], principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import solana_enabled, solana_rpc_url
    from solana_rpc import (
        SolanaRpcError, is_valid_solana_address,
        lamports_to_sol_string, sol_get_balance_lamports_at_url,
    )
    norm = _normalize_asset(asset)
    if norm != _SOLANA_ASSET:
        return _network_not_enabled_envelope(
            network_id=NETWORK_SOLANA_MAINNET, asset=norm,
            capability="balance",
        )
    if not solana_enabled():
        return _solana_disabled_envelope(norm, "balance")

    resolved_address = (address or "").strip()
    if not resolved_address:
        record = _load_wallet_account_record_network(
            principal["vault_id"], norm, NETWORK_SOLANA_MAINNET,
        )
        if record is None:
            return {
                "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
                "asset":           norm,
                "network":         _SOLANA_NETWORK_LABEL,
                "publicAddress":   "",
                "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
                "availableAmount": None,
                "unit":            None,
                "updatedAt":       None,
                "reason":          "no_wallet_yet",
            }
        resolved_address = (record.get("publicAddress") or "").strip()

    if not resolved_address or not is_valid_solana_address(
        resolved_address,
    ):
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         _SOLANA_NETWORK_LABEL,
            "publicAddress":   "",
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            None,
            "updatedAt":       None,
            "reason":          "invalid_address",
        }

    rpc_url = solana_rpc_url()
    if not rpc_url:
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         _SOLANA_NETWORK_LABEL,
            "publicAddress":   resolved_address,
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            None,
            "updatedAt":       None,
            "reason":          "rpc_not_configured",
        }
    try:
        lamports = sol_get_balance_lamports_at_url(
            rpc_url, resolved_address,
        )
    except SolanaRpcError as exc:
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         _SOLANA_NETWORK_LABEL,
            "publicAddress":   resolved_address,
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            None,
            "updatedAt":       None,
            "reason":          exc.code,
        }

    return {
        "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
        "asset":           norm,
        "network":         _SOLANA_NETWORK_LABEL,
        "publicAddress":   resolved_address,
        "balanceStatus":   WALLET_BALANCE_STATUS_AVAILABLE,
        "availableAmount": lamports_to_sol_string(lamports),
        "unit":            "SOL",
        "updatedAt":       None,
        "lamports":        str(lamports),
    }


SCHEMA_SOLANA_TX_STATUS_V1: str = "crypto_wallet_transaction_status_v1"


def _solana_transactions(
    asset: str,
    limit: int,
    principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import solana_enabled, solana_rpc_url
    from solana_rpc import (
        SolanaRpcError,
        sol_get_signatures_for_address_at_url,
    )
    norm = _normalize_asset(asset)
    if not solana_enabled():
        body = _solana_disabled_envelope(norm, "transactions")
        body["transactions"] = []
        return body

    record = _load_wallet_account_record_network(
        principal["vault_id"], norm, NETWORK_SOLANA_MAINNET,
    )
    if record is None:
        return {
            "schema":              "crypto_wallet_transaction_list_v1",
            "asset":               norm,
            "network":             _SOLANA_NETWORK_LABEL,
            "transactionsStatus":  "unavailable",
            "reason":              "no_wallet_yet",
            "message": (
                "Create your Solana wallet first. The activity "
                "feed loads from Solana RPC using your public "
                "wallet address."
            ),
            "transactions":        [],
        }

    address = (record.get("publicAddress") or "").strip()
    rpc_url = solana_rpc_url()
    if not rpc_url:
        return {
            "schema":              "crypto_wallet_transaction_list_v1",
            "asset":               norm,
            "network":             _SOLANA_NETWORK_LABEL,
            "transactionsStatus":  "unavailable",
            "reason":              "rpc_not_configured",
            "message": (
                "Solana activity is not connected yet."
            ),
            "transactions":        [],
        }

    safe_limit = min(max(int(limit or 20), 1), 50)
    try:
        rows = sol_get_signatures_for_address_at_url(
            rpc_url, address, limit=safe_limit,
        )
    except SolanaRpcError as exc:
        return {
            "schema":              "crypto_wallet_transaction_list_v1",
            "asset":               norm,
            "network":             _SOLANA_NETWORK_LABEL,
            "transactionsStatus":  "unavailable",
            "reason":              exc.code,
            "message": (
                "Solana activity temporarily unavailable."
            ),
            "transactions":        [],
        }

    transactions = []
    for row in rows:
        sig = row.get("signature") or ""
        err = row.get("err")
        confirmation = row.get("confirmationStatus") or ""
        if err is not None:
            normalized = "failed"
        elif confirmation in ("confirmed", "finalized"):
            normalized = "confirmed"
        elif confirmation == "processed":
            normalized = "pending"
        else:
            normalized = "unknown"
        transactions.append({
            "schema":        "crypto_wallet_transaction_v1",
            "asset":         norm,
            "network":       "solana_mainnet",
            "networkLabel":  "Solana",
            "txHash":        sig,
            "direction":     "unknown",
            "amount":        None,
            "unit":          "SOL",
            "status":        normalized,
            "confirmations": None,
            "timestamp":     row.get("blockTime"),
            "source":        "rpc_signatures",
        })

    return {
        "schema":             "crypto_wallet_transaction_list_v1",
        "asset":              norm,
        "network":            _SOLANA_NETWORK_LABEL,
        "transactionsStatus": "available",
        "returned":           len(transactions),
        "limit":              safe_limit,
        "transactions":       transactions,
    }


def _solana_transaction_status(
    asset: str, signature_b58: str,
) -> dict[str, Any]:
    from vault_config import solana_enabled, solana_rpc_url
    from solana_rpc import (
        SolanaRpcError, is_valid_solana_signature,
        sol_get_signature_status_at_url,
    )
    norm = _normalize_asset(asset)
    if norm != _SOLANA_ASSET:
        return _network_not_enabled_envelope(
            network_id=NETWORK_SOLANA_MAINNET, asset=norm,
            capability="transaction_status",
        )
    if not solana_enabled():
        return _solana_disabled_envelope(norm, "transaction_status")

    sig = (signature_b58 or "").strip()
    if not is_valid_solana_signature(sig):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_signature",
                "message": (
                    "The signature must be a valid Solana "
                    "base58-encoded signature."
                ),
            },
        )
    rpc_url = solana_rpc_url()
    if not rpc_url:
        return {
            "status":             "ok",
            "schema":             SCHEMA_SOLANA_TX_STATUS_V1,
            "asset":              norm,
            "network":            _SOLANA_NETWORK_LABEL,
            "networkLabel":       "Solana",
            "signature":          sig,
            "transactionStatus":  "unavailable",
            "reason":             "rpc_not_configured",
            "slot":               None,
            "confirmations":      None,
            "confirmationStatus": None,
        }
    try:
        st = sol_get_signature_status_at_url(rpc_url, sig)
    except SolanaRpcError as exc:
        return {
            "status":             "ok",
            "schema":             SCHEMA_SOLANA_TX_STATUS_V1,
            "asset":              norm,
            "network":            _SOLANA_NETWORK_LABEL,
            "networkLabel":       "Solana",
            "signature":          sig,
            "transactionStatus":  "unavailable",
            "reason":             exc.code,
            "slot":               None,
            "confirmations":      None,
            "confirmationStatus": None,
        }
    return {
        "status":             "ok",
        "schema":             SCHEMA_SOLANA_TX_STATUS_V1,
        "asset":              norm,
        "network":            _SOLANA_NETWORK_LABEL,
        "networkLabel":       "Solana",
        "signature":          sig,
        "transactionStatus":  st.get("status") or "unavailable",
        "slot":               st.get("slot"),
        "confirmations":      st.get("confirmations"),
        "confirmationStatus": st.get("confirmationStatus"),
    }


def _create_solana_wallet_account(
    asset: str,
    payload: "CreateWalletPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import solana_enabled
    from solana_rpc import is_valid_solana_address
    norm = _normalize_asset(asset)
    if norm != _SOLANA_ASSET:
        return _network_not_enabled_envelope(
            network_id=NETWORK_SOLANA_MAINNET, asset=norm,
            capability="create",
        )
    if not solana_enabled():
        return _solana_disabled_envelope(norm, "create")

    if not is_valid_solana_address(payload.publicAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_public_address",
                "message": (
                    "The public address must be a valid base58-encoded "
                    "Solana address for a Solana wallet."
                ),
            },
        )
    vault_id = principal["vault_id"]
    existing = _load_wallet_account_record_network(
        vault_id, norm, NETWORK_SOLANA_MAINNET,
    )
    if existing is not None:
        return {
            "wallet_engine": "account_exists",
            "message": (
                "A Solana wallet account already exists in this "
                "vault. Open the existing account instead of "
                "creating a new one."
            ),
            "account": _summarize_for_listing(existing),
        }
    record = {
        "schema":                SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
        "asset":                 norm,
        "network":               _SOLANA_NETWORK_LABEL,
        "networkLabel":          "Solana",
        "walletLabel":           payload.walletLabel,
        "publicAddress":         payload.publicAddress,
        "encryptedWalletSecret": payload.encryptedWalletSecret,
        "keyOrigin":             KEY_ORIGIN_GENERATED_CLIENT_SIDE,
        "signingMode":           SIGNING_MODE_CLIENT_SIDE,
        "backupStatus":          BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
    }
    _insert_wallet_account_record_network(
        vault_id, norm, NETWORK_SOLANA_MAINNET, record,
    )
    logger.info(
        "[WALLET-ENGINE] solana_created vault=%s asset=%s",
        str(vault_id)[:8] + "…", norm,
    )
    return {
        "wallet_engine": "created",
        "account":       _summarize_for_listing(record),
    }


SCHEMA_SOLANA_SEND_DRAFT_V1: str = "crypto_wallet_send_draft_v1"


def _solana_encrypted_secret(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import (
        solana_enabled, solana_send_enabled,
    )
    norm = _normalize_asset(asset)
    if norm != _SOLANA_ASSET:
        return _network_not_enabled_envelope(
            network_id=NETWORK_SOLANA_MAINNET, asset=norm,
            capability="encrypted_secret",
        )
    if not solana_enabled():
        return _solana_disabled_envelope(norm, "encrypted_secret")
    if not solana_send_enabled():
        return _solana_send_not_enabled_envelope(norm)
    record = _load_wallet_account_record_network(
        principal["vault_id"], norm, NETWORK_SOLANA_MAINNET,
    )
    if record is None:
        return {
            "wallet_engine": "no_account",
            "asset":         norm,
            "network":       _SOLANA_NETWORK_LABEL,
            "message": (
                "No Solana wallet exists yet."
            ),
        }
    secret = record.get("encryptedWalletSecret")
    if not isinstance(secret, str) or not secret:
        return {
            "wallet_engine": "no_encrypted_secret",
            "asset":         norm,
            "network":       _SOLANA_NETWORK_LABEL,
            "message": (
                "The stored Solana wallet record has no encrypted "
                "secret. Recreate the wallet to enable sending."
            ),
        }
    return {
        "wallet_engine":         "encrypted_secret_ready",
        "asset":                 norm,
        "network":               _SOLANA_NETWORK_LABEL,
        "encryptedWalletSecret": secret,
    }


def _solana_send_paused_envelope(asset: str) -> dict[str, Any]:
    return {
        "wallet_engine": "solana_send_paused",
        "asset":         _normalize_asset(asset),
        "network":       _SOLANA_NETWORK_LABEL,
        "message": (
            "Solana sending is temporarily paused."
        ),
    }


def _parse_sol_amount_to_lamports(amount_str: str) -> int:
    if not isinstance(amount_str, str):
        raise ValueError("Amount must be a decimal string.")
    s = amount_str.strip()
    if not s:
        raise ValueError("Amount must not be empty.")
    if not re.match(r"^\d+(?:\.\d+)?$", s):
        raise ValueError(
            "Amount must be a non-negative decimal like 0.1 or 5.",
        )
    from solana_rpc import LAMPORTS_PER_SOL
    if "." in s:
        whole_part, frac_part = s.split(".", 1)
    else:
        whole_part, frac_part = s, ""
    if len(frac_part) > 9:
        raise ValueError(
            "Solana amounts support at most 9 decimal places.",
        )
    frac_padded = frac_part.ljust(9, "0")
    whole = int(whole_part) if whole_part else 0
    frac = int(frac_padded) if frac_padded else 0
    lamports = whole * LAMPORTS_PER_SOL + frac
    if lamports <= 0:
        raise ValueError(
            "Amount must be greater than zero.",
        )
    return lamports


def _check_solana_broadcast_rate_limit(
    vault_id: str,
) -> Optional[dict[str, Any]]:
    from vault_config import (
        solana_broadcast_rate_limit,
        solana_broadcast_rate_window_secs,
    )
    cap = solana_broadcast_rate_limit()
    window = solana_broadcast_rate_window_secs()
    if cap <= 0:
        return None
    now = _now_secs()
    horizon = now - window
    with _SOLANA_SAFETY_LOCK:
        events = _SOLANA_BROADCAST_TIMES.setdefault(vault_id, deque())
        while events and events[0] < horizon:
            events.popleft()
        if len(events) >= cap:
            oldest = events[0]
            retry_after = max(1, int(window - (now - oldest)) + 1)
            logger.warning(
                "[WALLET-ENGINE] solana_broadcast_rate_limited "
                "vault=%s count=%d retry_after=%ds",
                str(vault_id)[:8] + "…", len(events), retry_after,
            )
            return {
                "envelope": {
                    "wallet_engine":     "rate_limited",
                    "status":            "rate_limited",
                    "network":           _SOLANA_NETWORK_LABEL,
                    "message": (
                        "Too many recent Solana broadcast attempts. "
                        "Wait a moment before retrying."
                    ),
                    "retryAfterSeconds": retry_after,
                },
                "retry_after": retry_after,
            }
        events.append(now)
    return None


def _lookup_solana_idempotent_broadcast(
    vault_id: str, idempotency_key: str, signed_tx_str: str,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not idempotency_key:
        return None, None
    sig_hash = _hash_signed_tx(signed_tx_str)
    with _SOLANA_SAFETY_LOCK:
        now = _now_secs()
        expired = [
            k for k, v in _SOLANA_IDEMPOTENCY_CACHE.items()
            if v.get("expires_at", 0) <= now
        ]
        for k in expired:
            _SOLANA_IDEMPOTENCY_CACHE.pop(k, None)
        entry = _SOLANA_IDEMPOTENCY_CACHE.get(
            (vault_id, idempotency_key),
        )
        if entry is None:
            return None, None
        if entry.get("hash") != sig_hash:
            return None, "idempotency_conflict"
        return dict(entry.get("envelope") or {}), None


def _record_solana_idempotent_broadcast(
    vault_id: str,
    idempotency_key: str,
    signed_tx_str: str,
    envelope: dict[str, Any],
) -> None:
    if not idempotency_key:
        return
    with _SOLANA_SAFETY_LOCK:
        _SOLANA_IDEMPOTENCY_CACHE[(vault_id, idempotency_key)] = {
            "hash":       _hash_signed_tx(signed_tx_str),
            "envelope":   dict(envelope),
            "expires_at": _now_secs() + _IDEMPOTENCY_TTL_SECS,
        }


def _solana_send_dispatch(
    asset: str,
    payload: "SendDraftPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import (
        solana_enabled, solana_rpc_url, solana_send_enabled,
        solana_send_paused,
    )
    from solana_rpc import (
        LAMPORTS_PER_SOL, SolanaRpcError,
        is_valid_solana_address, lamports_to_sol_string,
        sol_get_latest_blockhash_at_url,
    )
    norm = _normalize_asset(asset)
    if norm != _SOLANA_ASSET:
        return _network_not_enabled_envelope(
            network_id=NETWORK_SOLANA_MAINNET, asset=norm,
            capability="send_draft",
        )
    if not solana_enabled():
        return _solana_disabled_envelope(norm, "send_draft")
    if not solana_send_enabled():
        return _solana_send_not_enabled_envelope(norm)
    if solana_send_paused():
        return _solana_send_paused_envelope(norm)

    from_addr = (payload.fromAddress or "").strip()
    dest_addr = (payload.destinationAddress or "").strip()
    if not is_valid_solana_address(from_addr):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_from_address",
                "message": (
                    "The from address must be a valid Solana "
                    "base58-encoded address."
                ),
            },
        )
    if not is_valid_solana_address(dest_addr):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_destination_address",
                "message": (
                    "The destination address must be a valid Solana "
                    "base58-encoded address."
                ),
            },
        )
    if from_addr == dest_addr:
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "self_send_refused",
                "message": (
                    "The destination address matches the from "
                    "address. Refusing to draft a self-send."
                ),
            },
        )
    try:
        lamports = _parse_sol_amount_to_lamports(
            payload.amountSol or "",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_amount",
                "message":       str(exc),
            },
        )

    rpc_url = solana_rpc_url()
    if not rpc_url:
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": _SOLANA_NETWORK_LABEL,
            "reason":  "rpc_not_configured",
            "message": (
                "Cannot draft a Solana send: the operator has not "
                "configured a Solana RPC endpoint."
            ),
        }

    try:
        blockhash_result = sol_get_latest_blockhash_at_url(rpc_url)
    except SolanaRpcError as exc:
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": _SOLANA_NETWORK_LABEL,
            "reason":  exc.code,
            "message": (
                "Solana RPC did not return a fresh blockhash. "
                "Try again in a moment."
            ),
        }

    from solana_rpc import (
        build_sol_transfer_message_bytes,
        sol_get_fee_for_message_at_url,
    )
    import base64 as _base64
    fee_lamports: int = 5000
    fee_source: str = "default_lamports"
    try:
        msg_bytes = build_sol_transfer_message_bytes(
            from_address_b58=from_addr,
            to_address_b58=dest_addr,
            lamports=lamports,
            recent_blockhash_b58=blockhash_result["blockhash"],
        )
        msg_b64 = _base64.b64encode(msg_bytes).decode("ascii")
        rpc_fee = sol_get_fee_for_message_at_url(rpc_url, msg_b64)
        if rpc_fee > 0:
            fee_lamports = rpc_fee
            fee_source = "rpc_getFeeForMessage"
    except SolanaRpcError:
        pass
    except Exception:
        pass
    fee_sol = lamports_to_sol_string(fee_lamports)

    return {
        "status":              "draft_ready",
        "schema":              SCHEMA_SOLANA_SEND_DRAFT_V1,
        "wallet_engine":       "draft_ready",
        "asset":               norm,
        "network":             _SOLANA_NETWORK_LABEL,
        "networkLabel":        "Solana",
        "fromAddress":         from_addr,
        "destinationAddress":  dest_addr,
        "amountSol":           lamports_to_sol_string(lamports),
        "lamports":            str(lamports),
        "recentBlockhash":     blockhash_result["blockhash"],
        "lastValidBlockHeight": (
            blockhash_result.get("lastValidBlockHeight")
        ),
        "feeLamports":         fee_lamports,
        "feeSol":              fee_sol,
        "feeSource":           fee_source,
        "warning": (
            "Review carefully. Solana transactions cannot be "
            "reversed."
        ),
    }


def _solana_broadcast_dispatch(
    asset: str,
    payload: "SendBroadcastPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import (
        solana_enabled, solana_rpc_url, solana_send_enabled,
        solana_send_paused,
    )
    from solana_rpc import (
        REASON_INVALID_SIGNED_TX, SolanaRpcError,
        sol_send_signed_transaction_at_url,
    )
    norm = _normalize_asset(asset)
    if norm != _SOLANA_ASSET:
        return _network_not_enabled_envelope(
            network_id=NETWORK_SOLANA_MAINNET, asset=norm,
            capability="send_broadcast",
        )
    if not solana_enabled():
        return _solana_disabled_envelope(norm, "send_broadcast")
    if not solana_send_enabled():
        return _solana_send_not_enabled_envelope(norm)
    if solana_send_paused():
        return _solana_send_paused_envelope(norm)

    signed_tx = (payload.signedTransaction or "").strip()
    if not signed_tx:
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_signed_transaction",
                "message": (
                    "The signedTransaction field is required for "
                    "Solana broadcast."
                ),
            },
        )

    idempotency_key = (payload.idempotencyKey or "").strip()
    if idempotency_key and not _IDEMPOTENCY_KEY_RE.match(idempotency_key):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_idempotency_key",
                "message": (
                    "idempotencyKey must be 8–128 chars from the "
                    "alphabet [A-Za-z0-9._-]."
                ),
            },
        )

    vault_id = principal["vault_id"]

    if idempotency_key:
        cached, conflict = _lookup_solana_idempotent_broadcast(
            vault_id, idempotency_key, signed_tx,
        )
        if conflict is not None:
            return {
                "wallet_engine":  "idempotency_conflict",
                "status":         "idempotency_conflict",
                "network":        _SOLANA_NETWORK_LABEL,
                "message": (
                    "This idempotencyKey has already been used with a "
                    "different signed transaction."
                ),
            }
        if cached is not None:
            return cached

    rate_limit = _check_solana_broadcast_rate_limit(vault_id)
    if rate_limit is not None:
        return rate_limit["envelope"]

    rpc_url = solana_rpc_url()
    if not rpc_url:
        return {
            "wallet_engine": "rpc_not_configured",
            "status":        "broadcast_unavailable",
            "network":       _SOLANA_NETWORK_LABEL,
            "message": (
                "Cannot broadcast: the operator has not configured a "
                "Solana RPC endpoint."
            ),
        }

    try:
        signature = sol_send_signed_transaction_at_url(
            rpc_url, signed_tx,
        )
    except SolanaRpcError as exc:
        reason = exc.code
        logger.warning(
            "[WALLET-ENGINE] solana_broadcast_rpc_error "
            "vault=%s reason=%s",
            str(vault_id)[:8] + "…", reason,
        )
        if reason == REASON_INVALID_SIGNED_TX:
            raise HTTPException(
                status_code=422,
                detail={
                    "wallet_engine": "invalid_signed_transaction",
                    "message": (
                        "The signedTransaction field is not a valid "
                        "base64-encoded Solana transaction."
                    ),
                },
            )
        return {
            "wallet_engine": "broadcast_failed",
            "status":        "broadcast_failed",
            "network":       _SOLANA_NETWORK_LABEL,
            "reason":        reason,
            "message": (
                "Solana broadcast failed. Try again."
            ),
        }

    envelope = {
        "wallet_engine":         "broadcast_submitted",
        "status":                "submitted",
        "network":               _SOLANA_NETWORK_LABEL,
        "networkLabel":          "Solana",
        "asset":                 norm,
        "signature":             signature,
        "signaturePrefix":       signature[:8] + "…",
    }
    _record_solana_idempotent_broadcast(
        vault_id, idempotency_key, signed_tx, envelope,
    )
    logger.info(
        "[WALLET-ENGINE] solana_broadcast_ok vault=%s sig_prefix=%s",
        str(vault_id)[:8] + "…",
        signature[:8] + "…" if signature else "",
    )
    return envelope


_TRON_NETWORK_LABEL: str = "tron_mainnet"
_TRON_ASSET_USDT_TRC20: str = "USDT_TRC20"
SCHEMA_TRON_TX_STATUS_V1: str = "crypto_wallet_transaction_status_v1"


def _tron_disabled_envelope(
    asset: str, capability: str,
) -> dict[str, Any]:
    return {
        "wallet_engine": "tron_not_enabled",
        "asset":         _normalize_asset(asset),
        "network":       _TRON_NETWORK_LABEL,
        "networkLabel":  "TRON",
        "capability":    capability,
        "message":       "USDT TRC20 is temporarily unavailable.",
    }


def _tron_send_not_enabled_envelope(asset: str) -> dict[str, Any]:
    return {
        "wallet_engine": "tron_send_not_enabled",
        "asset":         _normalize_asset(asset),
        "network":       _TRON_NETWORK_LABEL,
        "networkLabel":  "TRON",
        "message":       "USDT TRC20 sending is not enabled yet.",
    }


def _tron_supported_asset(norm: str) -> bool:
    return norm == _TRON_ASSET_USDT_TRC20


def _tron_account_detail(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import tron_enabled
    norm = _normalize_asset(asset)
    if not _tron_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_TRON_MAINNET, asset=norm,
            capability="account_detail",
        )
    if not tron_enabled():
        return _tron_disabled_envelope(norm, "account_detail")
    record = _load_wallet_account_record_network(
        principal["vault_id"], norm, NETWORK_TRON_MAINNET,
    )
    if record is None:
        return {
            "wallet_engine": "no_account",
            "asset":         norm,
            "network":       _TRON_NETWORK_LABEL,
            "networkLabel":  "TRON",
            "tokenStandard": "TRC20",
            "message": (
                "No TRON wallet exists yet. Create one on this device "
                "to receive USDT on TRON."
            ),
        }
    return {
        "wallet_engine": "account_ready",
        "account":       _summarize_for_listing(record),
    }


def _tron_receive(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import tron_enabled
    norm = _normalize_asset(asset)
    if not _tron_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_TRON_MAINNET, asset=norm,
            capability="receive",
        )
    if not tron_enabled():
        return _tron_disabled_envelope(norm, "receive")
    record = _load_wallet_account_record_network(
        principal["vault_id"], norm, NETWORK_TRON_MAINNET,
    )
    if record is None:
        return {
            "wallet_engine": "create_tron_wallet_first",
            "asset":         norm,
            "network":       _TRON_NETWORK_LABEL,
            "networkLabel":  "TRON",
            "tokenStandard": "TRC20",
            "message": (
                "No TRON wallet exists yet. Create one on this device "
                "to get a real TRON receive address. The TRON wallet "
                "uses a separate key from your Ethereum and Solana "
                "wallets."
            ),
        }
    return {
        "wallet_engine": "receive_ready",
        "asset":         norm,
        "network":       _TRON_NETWORK_LABEL,
        "networkLabel":  "TRON",
        "tokenStandard": "TRC20",
        "unit":          "USDT",
        "walletLabel":   record.get("walletLabel"),
        "publicAddress": record.get("publicAddress"),
        "warning": (
            "Only send USDT TRC20 on TRON to this address. Sending on "
            "the wrong network or a different token may result in "
            "irreversible loss."
        ),
        "gasNote": (
            "Sending from this address later will require TRX for "
            "network fees."
        ),
    }


def _tron_dev_log(
    *,
    configured: bool,
    api_key_present: bool,
    contract_configured: bool,
    status: str,
    reason: str,
) -> None:




    try:
        import logging
        logger = logging.getLogger("crypto_wallet_routes")
        logger.info(
            "tron_balance_check asset=USDT_TRC20 "
            "configured=%s api_key_present=%s "
            "contract_configured=%s status=%s reason=%s",
            "true" if configured else "false",
            "true" if api_key_present else "false",
            "true" if contract_configured else "false",
            status, reason,
        )
    except Exception:
        pass


def _tron_balance(
    asset: str, address: Optional[str], principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import (
        tron_api_base_url, tron_api_key,
        tron_enabled, tron_usdt_contract_address,
        tron_usdt_decimals,
    )
    from tron_rpc import (
        TronRpcError, base_units_to_decimal_string,
        is_valid_tron_address, tron_get_trc20_balance_at_url,
        USDT_TRC20_UNIT,
    )
    norm = _normalize_asset(asset)
    if not _tron_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_TRON_MAINNET, asset=norm,
            capability="balance",
        )
    if not tron_enabled():
        return _tron_disabled_envelope(norm, "balance")

    resolved_address = (address or "").strip()
    if not resolved_address:
        record = _load_wallet_account_record_network(
            principal["vault_id"], norm, NETWORK_TRON_MAINNET,
        )
        if record is None:
            return {
                "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
                "asset":           norm,
                "network":         _TRON_NETWORK_LABEL,
                "publicAddress":   "",
                "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
                "availableAmount": None,
                "unit":            None,
                "updatedAt":       None,
                "reason":          "no_wallet_yet",
            }
        resolved_address = (record.get("publicAddress") or "").strip()

    if not resolved_address or not is_valid_tron_address(
        resolved_address,
    ):
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         _TRON_NETWORK_LABEL,
            "publicAddress":   "",
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            None,
            "updatedAt":       None,
            "reason":          "invalid_address",
        }

    base_url = tron_api_base_url()
    if not base_url:
        _tron_dev_log(
            configured=False, api_key_present=bool(tron_api_key()),
            contract_configured=bool(tron_usdt_contract_address()),
            status=WALLET_BALANCE_STATUS_UNAVAILABLE,
            reason="tron_api_not_configured",
        )
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         _TRON_NETWORK_LABEL,
            "publicAddress":   resolved_address,
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            USDT_TRC20_UNIT,
            "updatedAt":       None,
            "reason":          "tron_api_not_configured",
        }

    contract = tron_usdt_contract_address()
    if not contract or not is_valid_tron_address(contract):
        _tron_dev_log(
            configured=True, api_key_present=bool(tron_api_key()),
            contract_configured=False,
            status=WALLET_BALANCE_STATUS_UNAVAILABLE,
            reason="tron_contract_not_configured",
        )
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         _TRON_NETWORK_LABEL,
            "publicAddress":   resolved_address,
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            USDT_TRC20_UNIT,
            "updatedAt":       None,
            "reason":          "tron_contract_not_configured",
        }

    decimals = tron_usdt_decimals()
    try:
        base_units = tron_get_trc20_balance_at_url(
            base_url, tron_api_key(),
            contract_address_b58=contract,
            holder_address_b58=resolved_address,
        )
    except TronRpcError as exc:
        _tron_dev_log(
            configured=True, api_key_present=bool(tron_api_key()),
            contract_configured=True,
            status=WALLET_BALANCE_STATUS_UNAVAILABLE,
            reason=exc.code,
        )
        return {
            "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
            "asset":           norm,
            "network":         _TRON_NETWORK_LABEL,
            "publicAddress":   resolved_address,
            "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
            "availableAmount": None,
            "unit":            USDT_TRC20_UNIT,
            "updatedAt":       None,
            "reason":          exc.code,
        }

    _tron_dev_log(
        configured=True, api_key_present=bool(tron_api_key()),
        contract_configured=True,
        status=WALLET_BALANCE_STATUS_AVAILABLE,
        reason="ready",
    )
    return {
        "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
        "asset":           norm,
        "network":         _TRON_NETWORK_LABEL,
        "publicAddress":   resolved_address,
        "balanceStatus":   WALLET_BALANCE_STATUS_AVAILABLE,
        "availableAmount": base_units_to_decimal_string(
            base_units, decimals,
        ),
        "unit":            USDT_TRC20_UNIT,
        "updatedAt":       None,
        "baseUnits":       str(base_units),
        "decimals":        decimals,
        "tokenStandard":   "TRC20",
    }


def _tron_transactions(
    asset: str, limit: int, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import tron_enabled
    norm = _normalize_asset(asset)
    if not tron_enabled():
        body = _tron_disabled_envelope(norm, "transactions")
        body["transactions"] = []
        return body
    return {
        "schema":              "crypto_wallet_transaction_list_v1",
        "asset":               norm,
        "network":             _TRON_NETWORK_LABEL,
        "networkLabel":        "TRON",
        "transactionsStatus":  "unavailable",
        "reason":              "tron_activity_not_connected",
        "message": (
            "USDT TRC20 activity is not connected yet."
        ),
        "transactions":        [],
    }


def _tron_transaction_status(
    asset: str, tx_hash: str,
) -> dict[str, Any]:
    from vault_config import (
        tron_api_base_url, tron_api_key, tron_enabled,
    )
    from tron_rpc import (
        TronRpcError, is_valid_txid_hex,
        tron_get_transaction_info_at_url,
    )
    norm = _normalize_asset(asset)
    if not _tron_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_TRON_MAINNET, asset=norm,
            capability="transaction_status",
        )
    if not tron_enabled():
        return _tron_disabled_envelope(norm, "transaction_status")

    txid = (tx_hash or "").strip().lower()
    if not is_valid_txid_hex(txid):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_txid",
                "message": (
                    "The transaction id must be 64 lowercase hex chars."
                ),
            },
        )

    base_url = tron_api_base_url()
    if not base_url:
        return {
            "status":            "ok",
            "schema":            SCHEMA_TRON_TX_STATUS_V1,
            "asset":             norm,
            "network":           _TRON_NETWORK_LABEL,
            "networkLabel":      "TRON",
            "txHash":            txid,
            "transactionStatus": "unavailable",
            "reason":            "rpc_not_configured",
        }
    try:
        info = tron_get_transaction_info_at_url(
            base_url, tron_api_key(), txid,
        )
    except TronRpcError as exc:
        return {
            "status":            "ok",
            "schema":            SCHEMA_TRON_TX_STATUS_V1,
            "asset":             norm,
            "network":           _TRON_NETWORK_LABEL,
            "networkLabel":      "TRON",
            "txHash":            txid,
            "transactionStatus": "unavailable",
            "reason":            exc.code,
        }
    return {
        "status":            "ok",
        "schema":            SCHEMA_TRON_TX_STATUS_V1,
        "asset":             norm,
        "network":           _TRON_NETWORK_LABEL,
        "networkLabel":      "TRON",
        "txHash":            txid,
        "transactionStatus": info.get("status") or "unavailable",
        "blockNumber":       info.get("blockNumber"),
        "blockTimeStamp":    info.get("blockTimeStamp"),
        "contractResult":    info.get("contractResult"),
    }


def _create_tron_wallet_account(
    asset: str,
    payload: "CreateWalletPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import tron_enabled
    from tron_rpc import is_valid_tron_address
    norm = _normalize_asset(asset)
    if not _tron_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_TRON_MAINNET, asset=norm,
            capability="create",
        )
    if not tron_enabled():
        return _tron_disabled_envelope(norm, "create")

    if not is_valid_tron_address(payload.publicAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_public_address",
                "message": (
                    "The public address must be a valid TRON "
                    "Base58Check address starting with T for a TRON "
                    "wallet."
                ),
            },
        )
    vault_id = principal["vault_id"]
    existing = _load_wallet_account_record_network(
        vault_id, norm, NETWORK_TRON_MAINNET,
    )
    if existing is not None:
        return {
            "wallet_engine": "account_exists",
            "message": (
                "A TRON wallet account already exists in this vault. "
                "Open the existing account instead of creating a new "
                "one."
            ),
            "account": _summarize_for_listing(existing),
        }
    record = {
        "schema":                SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
        "asset":                 norm,
        "network":               _TRON_NETWORK_LABEL,
        "networkLabel":          "TRON",
        "tokenStandard":         "TRC20",
        "walletLabel":           payload.walletLabel,
        "publicAddress":         payload.publicAddress,
        "encryptedWalletSecret": payload.encryptedWalletSecret,
        "keyOrigin":             KEY_ORIGIN_GENERATED_CLIENT_SIDE,
        "signingMode":           SIGNING_MODE_CLIENT_SIDE,
        "backupStatus":          BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
    }
    _insert_wallet_account_record_network(
        vault_id, norm, NETWORK_TRON_MAINNET, record,
    )
    logger.info(
        "[WALLET-ENGINE] tron_created vault=%s asset=%s",
        str(vault_id)[:8] + "…", norm,
    )
    return {
        "wallet_engine": "created",
        "account":       _summarize_for_listing(record),
    }


SCHEMA_TRON_SEND_DRAFT_V1: str = "crypto_wallet_send_draft_v1"


def _tron_send_paused_envelope(asset: str) -> dict[str, Any]:
    return {
        "wallet_engine": "tron_send_paused",
        "asset":         _normalize_asset(asset),
        "network":       _TRON_NETWORK_LABEL,
        "networkLabel":  "TRON",
        "message": (
            "USDT TRC20 sending is temporarily paused."
        ),
    }


def _parse_usdt_amount_to_base_units(amount_str: str) -> int:
    if not isinstance(amount_str, str):
        raise ValueError("Amount must be a decimal string.")
    s = amount_str.strip()
    if not s:
        raise ValueError("Amount must not be empty.")
    if not re.match(r"^\d+(?:\.\d+)?$", s):
        raise ValueError(
            "Amount must be a non-negative decimal like 5 or 12.5.",
        )
    if "." in s:
        whole_part, frac_part = s.split(".", 1)
    else:
        whole_part, frac_part = s, ""
    if len(frac_part) > 6:
        raise ValueError(
            "USDT TRC20 amounts support at most 6 decimal places.",
        )
    frac_padded = frac_part.ljust(6, "0")
    whole = int(whole_part) if whole_part else 0
    frac = int(frac_padded) if frac_padded else 0
    base_units = whole * 1_000_000 + frac
    if base_units <= 0:
        raise ValueError("Amount must be greater than zero.")
    return base_units


def _check_tron_broadcast_rate_limit(
    vault_id: str,
) -> Optional[dict[str, Any]]:
    from vault_config import (
        tron_broadcast_rate_limit,
        tron_broadcast_rate_window_secs,
    )
    cap = tron_broadcast_rate_limit()
    window = tron_broadcast_rate_window_secs()
    if cap <= 0:
        return None
    now = _now_secs()
    horizon = now - window
    with _TRON_SAFETY_LOCK:
        events = _TRON_BROADCAST_TIMES.setdefault(vault_id, deque())
        while events and events[0] < horizon:
            events.popleft()
        if len(events) >= cap:
            oldest = events[0]
            retry_after = max(1, int(window - (now - oldest)) + 1)
            logger.warning(
                "[WALLET-ENGINE] tron_broadcast_rate_limited "
                "vault=%s count=%d retry_after=%ds",
                str(vault_id)[:8] + "…", len(events), retry_after,
            )
            return {
                "envelope": {
                    "wallet_engine":     "rate_limited",
                    "status":            "rate_limited",
                    "network":           _TRON_NETWORK_LABEL,
                    "message": (
                        "Too many recent TRON broadcast attempts. "
                        "Wait a moment before retrying."
                    ),
                    "retryAfterSeconds": retry_after,
                },
                "retry_after": retry_after,
            }
        events.append(now)
    return None


def _hash_signed_tron_tx(signed: Any) -> str:
    payload = json.dumps(signed, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _lookup_tron_idempotent_broadcast(
    vault_id: str, idempotency_key: str, signed_tx: Any,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if not idempotency_key:
        return None, None
    sig_hash = _hash_signed_tron_tx(signed_tx)
    with _TRON_SAFETY_LOCK:
        now = _now_secs()
        expired = [
            k for k, v in _TRON_IDEMPOTENCY_CACHE.items()
            if v.get("expires_at", 0) <= now
        ]
        for k in expired:
            _TRON_IDEMPOTENCY_CACHE.pop(k, None)
        entry = _TRON_IDEMPOTENCY_CACHE.get(
            (vault_id, idempotency_key),
        )
        if entry is None:
            return None, None
        if entry.get("hash") != sig_hash:
            return None, "idempotency_conflict"
        return dict(entry.get("envelope") or {}), None


def _record_tron_idempotent_broadcast(
    vault_id: str, idempotency_key: str,
    signed_tx: Any, envelope: dict[str, Any],
) -> None:
    if not idempotency_key:
        return
    with _TRON_SAFETY_LOCK:
        _TRON_IDEMPOTENCY_CACHE[(vault_id, idempotency_key)] = {
            "hash":       _hash_signed_tron_tx(signed_tx),
            "envelope":   dict(envelope),
            "expires_at": _now_secs() + _IDEMPOTENCY_TTL_SECS,
        }


def _tron_encrypted_secret(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import tron_enabled, tron_send_enabled
    norm = _normalize_asset(asset)
    if not _tron_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_TRON_MAINNET, asset=norm,
            capability="encrypted_secret",
        )
    if not tron_enabled():
        return _tron_disabled_envelope(norm, "encrypted_secret")
    if not tron_send_enabled():
        return _tron_send_not_enabled_envelope(norm)
    record = _load_wallet_account_record_network(
        principal["vault_id"], norm, NETWORK_TRON_MAINNET,
    )
    if record is None:
        return {
            "wallet_engine": "no_account",
            "asset":         norm,
            "network":       _TRON_NETWORK_LABEL,
            "message": (
                "No TRON wallet exists yet."
            ),
        }
    secret = record.get("encryptedWalletSecret")
    if not isinstance(secret, str) or not secret:
        return {
            "wallet_engine": "no_encrypted_secret",
            "asset":         norm,
            "network":       _TRON_NETWORK_LABEL,
            "message": (
                "The stored TRON wallet record has no encrypted "
                "secret. Recreate the wallet to enable sending."
            ),
        }
    return {
        "wallet_engine":         "encrypted_secret_ready",
        "asset":                 norm,
        "network":               _TRON_NETWORK_LABEL,
        "encryptedWalletSecret": secret,
    }


def _tron_send_dispatch(
    asset: str,
    payload: "SendDraftPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import (
        tron_api_base_url, tron_api_key,
        tron_enabled, tron_low_trx_threshold_sun,
        tron_send_enabled, tron_send_fee_limit_sun,
        tron_send_paused, tron_usdt_contract_address,
        tron_usdt_decimals,
    )
    from tron_rpc import (
        TronRpcError, base_units_to_decimal_string,
        is_valid_tron_address, sun_to_trx_string,
        tron_create_trc20_transfer_at_url,
        tron_get_account_resource_at_url,
        tron_get_trx_balance_sun_at_url,
    )
    norm = _normalize_asset(asset)
    if not _tron_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_TRON_MAINNET, asset=norm,
            capability="send_draft",
        )
    if not tron_enabled():
        return _tron_disabled_envelope(norm, "send_draft")
    if not tron_send_enabled():
        return _tron_send_not_enabled_envelope(norm)
    if tron_send_paused():
        return _tron_send_paused_envelope(norm)

    from_addr = (payload.fromAddress or "").strip()
    dest_addr = (payload.destinationAddress or "").strip()
    if not is_valid_tron_address(from_addr):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_from_address",
                "message": (
                    "The from address must be a valid TRON "
                    "Base58Check address."
                ),
            },
        )
    if not is_valid_tron_address(dest_addr):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_destination_address",
                "message": (
                    "The destination address must be a valid TRON "
                    "Base58Check address."
                ),
            },
        )
    if from_addr == dest_addr:
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "self_send_refused",
                "message": (
                    "The destination address matches the from "
                    "address. Refusing to draft a self-send."
                ),
            },
        )
    try:
        base_units = _parse_usdt_amount_to_base_units(
            payload.amountUsdt or "",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_amount",
                "message":       str(exc),
            },
        )

    base_url = tron_api_base_url()
    if not base_url:
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": _TRON_NETWORK_LABEL,
            "reason":  "rpc_not_configured",
            "message": (
                "Cannot draft a TRON send: the operator has not "
                "configured a TRON API endpoint."
            ),
        }
    contract = tron_usdt_contract_address()
    if not contract or not is_valid_tron_address(contract):
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": _TRON_NETWORK_LABEL,
            "reason":  "token_contract_not_configured",
            "message": (
                "Cannot draft a TRON send: the operator has not "
                "configured the USDT TRC20 contract address."
            ),
        }

    fee_limit_sun = tron_send_fee_limit_sun()
    api_key = tron_api_key()
    try:
        draft = tron_create_trc20_transfer_at_url(
            base_url, api_key,
            contract_address_b58=contract,
            owner_address_b58=from_addr,
            destination_address_b58=dest_addr,
            amount_base_units=base_units,
            fee_limit_sun=fee_limit_sun,
        )
    except TronRpcError as exc:
        logger.warning(
            "[WALLET-ENGINE] tron_draft_unavailable vault=%s reason=%s",
            str(principal["vault_id"])[:8] + "…", exc.code,
        )
        return {
            "status":  "draft_unavailable",
            "asset":   norm,
            "network": _TRON_NETWORK_LABEL,
            "reason":  exc.code,
            "message": (
                "TRON provider did not return an unsigned transaction. "
                "Try again in a moment."
            ),
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_amount",
                "message":       str(exc),
            },
        )

    trx_sun: Optional[int] = None
    try:
        trx_sun = tron_get_trx_balance_sun_at_url(
            base_url, api_key, from_addr,
        )
    except TronRpcError:
        trx_sun = None

    resource_status = "unavailable"
    resource_info: dict[str, Any] = {}
    try:
        resource_info = tron_get_account_resource_at_url(
            base_url, api_key, from_addr,
        )
    except TronRpcError:
        resource_info = {}

    threshold_sun = tron_low_trx_threshold_sun()
    if trx_sun is None:
        resource_status = "unavailable"
    elif trx_sun < threshold_sun:
        resource_status = "low_trx"
    else:
        resource_status = "ready"

    trx_balance_str = (
        sun_to_trx_string(trx_sun) if trx_sun is not None else None
    )

    return {
        "status":              "draft_ready",
        "schema":              SCHEMA_TRON_SEND_DRAFT_V1,
        "wallet_engine":       "draft_ready",
        "asset":               norm,
        "network":             _TRON_NETWORK_LABEL,
        "networkLabel":        "TRON",
        "tokenStandard":       "TRC20",
        "fromAddress":         from_addr,
        "destinationAddress":  dest_addr,
        "amountUsdt":          base_units_to_decimal_string(
            base_units, tron_usdt_decimals(),
        ),
        "amountBaseUnits":     str(base_units),
        "unsignedTransaction": draft["unsignedTransaction"],
        "txID":                draft["txID"],
        "rawDataHex":          draft["rawDataHex"],
        "feeLimitSun":         fee_limit_sun,
        "feeLimitTrx":         sun_to_trx_string(fee_limit_sun),
        "feeStatus":           "estimated",
        "trxBalanceSun":       trx_sun,
        "trxBalance":          trx_balance_str,
        "resourceStatus":      resource_status,
        "resourceInfo":        resource_info,
        "feeWarning": (
            "USDT TRC20 transfers require TRX for TRON network fees."
        ),
        "warning": (
            "Review carefully. TRON transactions cannot be reversed."
        ),
    }


def _tron_broadcast_dispatch(
    asset: str,
    payload: "SendBroadcastPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import (
        tron_api_base_url, tron_api_key,
        tron_enabled, tron_send_enabled, tron_send_paused,
    )
    from tron_rpc import (
        REASON_INVALID_SIGNED_TX, TronRpcError,
        is_valid_tron_signed_transaction,
        tron_broadcast_signed_transaction_at_url,
    )
    norm = _normalize_asset(asset)
    if not _tron_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_TRON_MAINNET, asset=norm,
            capability="send_broadcast",
        )
    if not tron_enabled():
        return _tron_disabled_envelope(norm, "send_broadcast")
    if not tron_send_enabled():
        return _tron_send_not_enabled_envelope(norm)
    if tron_send_paused():
        return _tron_send_paused_envelope(norm)

    signed_tx = payload.signedTransaction
    if not is_valid_tron_signed_transaction(signed_tx):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_signed_transaction",
                "message": (
                    "The signedTransaction must be a full TRON "
                    "transaction object with txID, raw_data_hex, and a "
                    "non-empty signature array of hex strings."
                ),
            },
        )

    idempotency_key = _validate_idempotency_key(
        getattr(payload, "idempotencyKey", None),
    ) or ""

    vault_id = principal["vault_id"]

    if idempotency_key:
        cached, conflict = _lookup_tron_idempotent_broadcast(
            vault_id, idempotency_key, signed_tx,
        )
        if conflict is not None:
            logger.warning(
                "[WALLET-ENGINE] tron_broadcast_idem_conflict "
                "vault=%s",
                str(vault_id)[:8] + "…",
            )
            return {
                "wallet_engine": "idempotency_conflict",
                "status":        "idempotency_conflict",
                "network":       _TRON_NETWORK_LABEL,
                "message": (
                    "This idempotencyKey has already been used with a "
                    "different signed transaction."
                ),
            }
        if cached is not None:
            logger.info(
                "[WALLET-ENGINE] tron_broadcast_idem_hit vault=%s",
                str(vault_id)[:8] + "…",
            )
            return cached

    rate_blocked = _check_tron_broadcast_rate_limit(vault_id)
    if rate_blocked is not None:
        return rate_blocked["envelope"]

    base_url = tron_api_base_url()
    if not base_url:
        return {
            "wallet_engine": "rpc_not_configured",
            "status":        "broadcast_unavailable",
            "network":       _TRON_NETWORK_LABEL,
            "message": (
                "Cannot broadcast: the operator has not configured a "
                "TRON API endpoint."
            ),
        }

    try:
        txid = tron_broadcast_signed_transaction_at_url(
            base_url, tron_api_key(), signed_tx,
        )
    except TronRpcError as exc:
        logger.warning(
            "[WALLET-ENGINE] tron_broadcast_rpc_error vault=%s reason=%s",
            str(vault_id)[:8] + "…", exc.code,
        )
        if exc.code == REASON_INVALID_SIGNED_TX:
            raise HTTPException(
                status_code=422,
                detail={
                    "wallet_engine": "invalid_signed_transaction",
                    "message": (
                        "The signedTransaction is not a valid TRON "
                        "signed transaction object."
                    ),
                },
            )
        return {
            "wallet_engine": "broadcast_failed",
            "status":        "broadcast_failed",
            "network":       _TRON_NETWORK_LABEL,
            "reason":        exc.code,
            "message": (
                "TRON broadcast failed. Try again."
            ),
        }

    envelope = {
        "wallet_engine":  "broadcast_submitted",
        "status":         "submitted",
        "network":        _TRON_NETWORK_LABEL,
        "networkLabel":   "TRON",
        "asset":          norm,
        "txHash":         txid,
        "txHashPrefix":   txid[:10] + "…",
    }
    _record_tron_idempotent_broadcast(
        vault_id, idempotency_key, signed_tx, envelope,
    )
    logger.info(
        "[WALLET-ENGINE] tron_broadcast_ok vault=%s tx_prefix=%s",
        str(vault_id)[:8] + "…",
        txid[:10] + "…" if txid else "",
    )
    return envelope


_MONERO_ASSET: str = "XMR"
_MONERO_NETWORK_LABEL: str = "monero_mainnet"


def _xmr_disabled_envelope(
    asset: str, capability: str,
) -> dict[str, Any]:
    return {
        "wallet_engine": "xmr_privacy_wallet_later",
        "asset":         _normalize_asset(asset),
        "network":       _MONERO_NETWORK_LABEL,
        "networkLabel":  "Monero",
        "capability":    capability,
        "message":       "Monero privacy wallet support is planned.",
    }


def _xmr_send_not_enabled_envelope(asset: str) -> dict[str, Any]:
    return {
        "wallet_engine": "xmr_send_not_enabled",
        "asset":         _normalize_asset(asset),
        "network":       _MONERO_NETWORK_LABEL,
        "networkLabel":  "Monero",
        "message":       "Monero sending is not enabled yet.",
    }


def _xmr_supported_asset(norm: str) -> bool:
    return norm == _MONERO_ASSET


def _xmr_scanner_message() -> str:
    return (
        "Monero balance and activity require wallet scanning. "
        "Scanning is not enabled yet."
    )


def _xmr_account_detail(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import monero_enabled
    norm = _normalize_asset(asset)
    if not _xmr_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_MONERO_MAINNET, asset=norm,
            capability="account_detail",
        )
    if not monero_enabled():
        return _xmr_disabled_envelope(norm, "account_detail")
    record = _load_wallet_account_record_network(
        principal["vault_id"], norm, NETWORK_MONERO_MAINNET,
    )
    if record is None:
        return {
            "wallet_engine": "no_account",
            "asset":         norm,
            "network":       _MONERO_NETWORK_LABEL,
            "networkLabel":  "Monero",
            "message": (
                "No Monero wallet exists yet. Create one on this "
                "device to receive XMR."
            ),
        }
    return {
        "wallet_engine": "account_ready",
        "account":       _summarize_for_listing(record),
    }


def _xmr_receive(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import monero_enabled
    norm = _normalize_asset(asset)
    if not _xmr_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_MONERO_MAINNET, asset=norm,
            capability="receive",
        )
    if not monero_enabled():
        return _xmr_disabled_envelope(norm, "receive")
    record = _load_wallet_account_record_network(
        principal["vault_id"], norm, NETWORK_MONERO_MAINNET,
    )
    if record is None:
        return {
            "wallet_engine": "create_xmr_wallet_first",
            "asset":         norm,
            "network":       _MONERO_NETWORK_LABEL,
            "networkLabel":  "Monero",
            "message": (
                "No Monero wallet exists yet. Create one on this "
                "device to get a real Monero receive address. The "
                "Monero wallet uses a separate key from your other "
                "wallets."
            ),
        }
    return {
        "wallet_engine": "receive_ready",
        "asset":         norm,
        "network":       _MONERO_NETWORK_LABEL,
        "networkLabel":  "Monero",
        "walletLabel":   record.get("walletLabel"),
        "publicAddress": record.get("publicAddress"),
        "restoreHeight": record.get("restoreHeight"),
        "warning": (
            "Only send XMR on Monero to this address."
        ),
        "privacyNote": _xmr_scanner_message(),
    }


def _xmr_balance(
    asset: str, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import monero_enabled
    norm = _normalize_asset(asset)
    if not _xmr_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_MONERO_MAINNET, asset=norm,
            capability="balance",
        )
    if not monero_enabled():
        return _xmr_disabled_envelope(norm, "balance")
    return {
        "schema":          SCHEMA_CRYPTO_WALLET_BALANCE_V1,
        "asset":           norm,
        "network":         _MONERO_NETWORK_LABEL,
        "publicAddress":   "",
        "balanceStatus":   WALLET_BALANCE_STATUS_UNAVAILABLE,
        "availableAmount": None,
        "unit":            None,
        "updatedAt":       None,
        "reason":          "xmr_scanner_not_enabled",
        "message":         _xmr_scanner_message(),
    }


def _xmr_transactions(
    asset: str, limit: int, principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import monero_enabled
    norm = _normalize_asset(asset)
    if not monero_enabled():
        body = _xmr_disabled_envelope(norm, "transactions")
        body["transactions"] = []
        return body
    return {
        "schema":             "crypto_wallet_transaction_list_v1",
        "asset":              norm,
        "network":            _MONERO_NETWORK_LABEL,
        "networkLabel":       "Monero",
        "transactionsStatus": "unavailable",
        "reason":             "xmr_scanner_not_enabled",
        "message":            _xmr_scanner_message(),
        "transactions":       [],
    }


def _create_xmr_wallet_account(
    asset: str,
    payload: "CreateWalletPayload",
    principal: dict[str, Any],
) -> dict[str, Any]:
    from vault_config import monero_enabled, monero_scanner_mode
    from monero_address import is_valid_monero_primary_or_subaddress
    norm = _normalize_asset(asset)
    if not _xmr_supported_asset(norm):
        return _network_not_enabled_envelope(
            network_id=NETWORK_MONERO_MAINNET, asset=norm,
            capability="create",
        )
    if not monero_enabled():
        return _xmr_disabled_envelope(norm, "create")

    if not is_valid_monero_primary_or_subaddress(payload.publicAddress):
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_public_address",
                "message": (
                    "The public address must be a valid Monero "
                    "mainnet primary or subaddress (95 base58 chars, "
                    "correct prefix and checksum)."
                ),
            },
        )

    restore_height = payload.restoreHeight
    if restore_height is not None:
        if not isinstance(restore_height, int) or restore_height < 0:
            raise HTTPException(
                status_code=422,
                detail={
                    "wallet_engine": "invalid_restore_height",
                    "message": (
                        "restoreHeight must be a non-negative integer."
                    ),
                },
            )

    requested_scanner_mode = payload.scannerMode
    if requested_scanner_mode is not None and \
            requested_scanner_mode != "none":
        raise HTTPException(
            status_code=422,
            detail={
                "wallet_engine": "invalid_scanner_mode",
                "message": (
                    "This slice only accepts scannerMode='none'. "
                    "Backend view-only scanning is not enabled."
                ),
            },
        )
    active_scanner_mode = monero_scanner_mode()

    vault_id = principal["vault_id"]
    existing = _load_wallet_account_record_network(
        vault_id, norm, NETWORK_MONERO_MAINNET,
    )
    if existing is not None:
        return {
            "wallet_engine": "account_exists",
            "message": (
                "A Monero wallet account already exists in this "
                "vault. Open the existing account instead of "
                "creating a new one."
            ),
            "account": _summarize_for_listing(existing),
        }
    record = {
        "schema":                SCHEMA_CRYPTO_WALLET_ACCOUNT_V1,
        "asset":                 norm,
        "network":               _MONERO_NETWORK_LABEL,
        "networkLabel":          "Monero",
        "walletLabel":           payload.walletLabel,
        "publicAddress":         payload.publicAddress,
        "restoreHeight":         restore_height,
        "encryptedWalletSecret": payload.encryptedWalletSecret,
        "keyOrigin":             KEY_ORIGIN_GENERATED_CLIENT_SIDE,
        "signingMode":           SIGNING_MODE_CLIENT_SIDE,
        "scannerMode":           active_scanner_mode,
        "backupStatus":          BACKUP_STATUS_ENCRYPTED_BACKUP_SAVED,
    }
    _insert_wallet_account_record_network(
        vault_id, norm, NETWORK_MONERO_MAINNET, record,
    )
    logger.info(
        "[WALLET-ENGINE] xmr_created vault=%s asset=%s scanner=%s",
        str(vault_id)[:8] + "…", norm, active_scanner_mode,
    )
    return {
        "wallet_engine": "created",
        "account":       _summarize_for_listing(record),
    }


__all__ = [
    "router",
    "ITEM_TYPE_WALLET_ACCOUNT",
    "NETWORK_SOLANA_MAINNET",
    "NETWORK_TRON_MAINNET",
    "NETWORK_MONERO_MAINNET",
    "SCHEMA_SOLANA_SEND_DRAFT_V1",
    "SCHEMA_TRON_SEND_DRAFT_V1",
    "SCHEMA_TRON_TX_STATUS_V1",
    "reset_mainnet_safety_state_for_tests",
    "reset_solana_safety_state_for_tests",
    "reset_tron_safety_state_for_tests",
]
