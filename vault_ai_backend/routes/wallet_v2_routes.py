"""Opaque WalletV2 persistence. Signing and decryption are client-only."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2 import IntegrityError
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from vault_core import get_db
from zk_migration_flags import ZkMigrationFlags
from subscription_entitlement import require_content_write, require_crypto_access
from legacy_source_snapshot import source_snapshot as legacy_source_snapshot
from routes.auth_zk_routes import consume_recent_zk_proof
from routes.legacy_ciphertext_migration_routes import _new_receipt, _receipt_valid

router = APIRouter(tags=["wallet-v2"])
CHAINS = {"evm", "solana", "tron", "monero"}
NEW_WALLET_SLOTS = {
    ("evm", "ethereum_mainnet", "ETH"),
    ("evm", "ethereum_sepolia", "ETH"),
    ("solana", "solana_mainnet", "SOL"),
    ("tron", "tron_mainnet", "USDT_TRC20"),
    ("monero", "monero_mainnet", "XMR"),
}


def _enabled(*, write: bool = False) -> None:
    flags = ZkMigrationFlags.from_environment(os.environ)
    flags.validate_dependencies()
    enabled = flags.wallet_write_enabled if write else flags.wallet_read_enabled
    if not enabled:
        raise HTTPException(status_code=404, detail="wallet_v2_disabled")


def _decode(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_base64url") from exc
    if not decoded:
        raise HTTPException(status_code=400, detail="empty_ciphertext")
    if len(decoded) > 64 * 1024:
        raise HTTPException(status_code=413, detail="wallet_ciphertext_too_large")
    return decoded


class WalletV2CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wallet_record_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    chain: str
    network: str = Field(min_length=1, max_length=80)
    asset: str = Field(min_length=1, max_length=40)
    public_address: str = Field(min_length=1, max_length=200)
    wallet_label: str = Field(min_length=1, max_length=80)
    payload_ciphertext: str = Field(min_length=1)
    envelope_version: str = Field(pattern=r"^v2$")
    # A new wallet is unusable until the owner reads back and verifies the
    # exact MVK envelope and its derived public address on the client.
    migration_state: str = Field(default="migration_pending", pattern=r"^migration_pending$")


class WalletV2PublishNewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readback_receipt: str = Field(min_length=1, max_length=256)
    client_verified_exact_bytes: bool


class WalletV2MigrationStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    legacy_item_id: int = Field(gt=0)
    source_snapshot: str = Field(min_length=43, max_length=43)
    wallet_record_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    chain: str
    network: str = Field(min_length=1, max_length=80)
    asset: str = Field(min_length=1, max_length=40)
    public_address: str = Field(min_length=1, max_length=200)
    wallet_label: str = Field(min_length=1, max_length=80)
    payload_ciphertext: str = Field(min_length=1)
    envelope_version: str = Field(pattern=r"^v2$")


class WalletV2MigrationRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    legacy_item_id: int = Field(gt=0)
    wallet_record_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    source_snapshot: str = Field(min_length=43, max_length=43)
    readback_receipt: str = Field(min_length=1, max_length=256)
    zk_proof_token: str = Field(min_length=1, max_length=128)
    client_verified_exact_bytes: bool


_LEGACY_COLUMNS = (
    "encrypted_data,item_type,service,item_type_ciphertext,"
    "service_ciphertext,payload_ciphertext"
)


def _migration_enabled() -> None:
    flags = ZkMigrationFlags.from_environment(os.environ)
    flags.validate_dependencies()
    if not flags.wallet_migration_enabled:
        raise HTTPException(status_code=404, detail="wallet_migration_disabled")


def _preparation_enabled() -> None:
    """Allow owner-verified pending copies before old wallet writes stop.

    Retirement still requires the full wallet migration gate. This separate
    stage gate lets existing apps keep creating and using older wallets while
    an owner prepares an exact V2 copy for a later coordinated cutover.
    """
    flags = ZkMigrationFlags.from_environment(os.environ)
    flags.validate_dependencies()
    if flags.wallet_migration_enabled:
        return
    enabled = os.getenv("WALLET_V2_PREPARE_ENABLED", "false").strip().lower()
    if enabled not in {"1", "true", "yes", "on"} or not flags.wallet_read_enabled:
        raise HTTPException(status_code=404, detail="wallet_preparation_disabled")


def _load_legacy_wallet_locked(cur, vault_id: str, item_id: int) -> dict:
    cur.execute(
        f"SELECT {_LEGACY_COLUMNS} FROM vault_items "
        "WHERE vault_id=%s AND id=%s FOR UPDATE", (vault_id, item_id),
    )
    row = cur.fetchone()
    if not row or row.get("encrypted_data") is None:
        raise HTTPException(status_code=409, detail="legacy_wallet_missing")
    if row.get("item_type") != "crypto_wallet_account" or any(
        row.get(field) is not None for field in (
            "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
        )
    ):
        raise HTTPException(status_code=409, detail="legacy_wallet_state_conflict")
    return row


def _wallet_digest(row: dict) -> bytes:
    h = hashlib.sha256(b"wallet-v2-migration-readback/v1\x00")
    for field in (
        "wallet_record_id", "chain", "network", "asset", "public_address",
        "wallet_label", "payload_ciphertext", "migration_state",
        "legacy_item_id", "legacy_source_snapshot",
    ):
        value = row.get(field)
        raw = b"" if value is None else (
            value.encode("utf-8") if isinstance(value, str) else
            bytes(value) if not isinstance(value, int) else str(value).encode("ascii")
        )
        h.update(len(raw).to_bytes(8, "big"))
        h.update(raw)
    return h.digest()


def _check_wallet_engine_outer_json(
    row: dict, payload: WalletV2MigrationStageRequest,
) -> None:
    outer = row["encrypted_data"]
    if not isinstance(outer, str) or not outer.lstrip().startswith("{"):
        # Separately identified historical items may wrap the whole record.
        # The owner validates their decrypted schema and identity locally.
        return
    try:
        legacy = json.loads(outer)
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail="legacy_wallet_malformed")
    from routes.crypto_wallet_routes import _record_matches_network
    stored_network = legacy.get("network") if isinstance(legacy, dict) else None
    if not isinstance(legacy, dict) or any((
        legacy.get("schema") != "crypto_wallet_account_v1",
        legacy.get("asset") != payload.asset,
        not isinstance(stored_network, str) or
        not _record_matches_network(stored_network, payload.network),
        legacy.get("publicAddress") != payload.public_address,
        legacy.get("walletLabel") != payload.wallet_label,
        not isinstance(legacy.get("encryptedWalletSecret"), str),
    )):
        raise HTTPException(status_code=409, detail="legacy_wallet_identity_changed")


def _assert_zk_vault(cur, vault_id: str) -> None:
    cur.execute("SELECT vault_handle FROM vaults WHERE vault_id=%s", (vault_id,))
    row = cur.fetchone()
    if not row or not row.get("vault_handle"):
        raise HTTPException(status_code=403, detail="private_vault_required")


@router.post("/vault/wallet-v2/migrate/stage")
def stage_legacy_wallet(payload: WalletV2MigrationStageRequest,
                        principal: SessionPrincipal = Depends(verify_trusted_device)):
    _preparation_enabled()
    require_content_write(principal)
    require_crypto_access(principal)
    if (payload.chain, payload.network, payload.asset) not in NEW_WALLET_SLOTS:
        raise HTTPException(status_code=400, detail="unsupported_wallet_slot")
    ciphertext = _decode(payload.payload_ciphertext)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _assert_zk_vault(cur, principal["vault_id"])
        legacy = _load_legacy_wallet_locked(
            cur, principal["vault_id"], payload.legacy_item_id,
        )
        snapshot = legacy_source_snapshot(
            "item", legacy, vault_id=principal["vault_id"],
            record_id=payload.legacy_item_id,
        )
        if snapshot != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        _check_wallet_engine_outer_json(legacy, payload)
        cur.execute(
            "SELECT wallet_record_id,chain,network,asset,public_address,"
            "wallet_label,payload_ciphertext,migration_state,legacy_item_id,"
            "legacy_source_snapshot FROM wallet_v2_records "
            "WHERE vault_id=%s AND legacy_item_id=%s FOR UPDATE",
            (principal["vault_id"], payload.legacy_item_id),
        )
        existing = cur.fetchone()
        if existing:
            if (existing.get("wallet_record_id") != payload.wallet_record_id or
                    existing.get("migration_state") != "migration_pending"):
                raise HTTPException(status_code=409, detail="wallet_stage_conflict")
            if existing.get("legacy_source_snapshot") != snapshot:
                # A legacy client changed the source after the previous
                # stage. Replace only this still-pending copy while the
                # source row is locked; any earlier receipt becomes invalid.
                cur.execute(
                    "UPDATE wallet_v2_records SET chain=%s,network=%s,asset=%s,"
                    "public_address=%s,wallet_label=%s,payload_ciphertext=%s,"
                    "legacy_source_snapshot=%s,updated_at=NOW() WHERE vault_id=%s "
                    "AND legacy_item_id=%s AND wallet_record_id=%s "
                    "AND migration_state='migration_pending'",
                    (payload.chain, payload.network, payload.asset,
                     payload.public_address, payload.wallet_label, ciphertext,
                     snapshot, principal["vault_id"], payload.legacy_item_id,
                     payload.wallet_record_id),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=409, detail="wallet_stage_changed")
            elif any((
                existing.get("chain") != payload.chain,
                existing.get("network") != payload.network,
                existing.get("asset") != payload.asset,
                existing.get("public_address") != payload.public_address,
                existing.get("wallet_label") != payload.wallet_label,
                bytes(existing.get("payload_ciphertext") or b"") != ciphertext,
            )):
                raise HTTPException(status_code=409, detail="wallet_stage_conflict")
        else:
            cur.execute(
                "INSERT INTO wallet_v2_records "
                "(vault_id,wallet_record_id,chain,network,asset,public_address,"
                "wallet_label,payload_ciphertext,envelope_version,migration_state,"
                "legacy_item_id,legacy_source_snapshot) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'v2','migration_pending',%s,%s)",
                (principal["vault_id"], payload.wallet_record_id, payload.chain,
                 payload.network, payload.asset, payload.public_address,
                 payload.wallet_label, ciphertext, payload.legacy_item_id, snapshot),
            )
        conn.commit()
        return {"wallet_record_id": payload.wallet_record_id,
                "migration_state": "migration_pending"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/wallet-v2")
def create_wallet_v2(payload: WalletV2CreateRequest,
                     principal: SessionPrincipal = Depends(verify_trusted_device)):
    require_content_write(principal)
    require_crypto_access(principal)
    _enabled(write=True)
    if (payload.chain, payload.network, payload.asset) not in NEW_WALLET_SLOTS:
        raise HTTPException(status_code=400, detail="unsupported_wallet_slot")
    ciphertext = _decode(payload.payload_ciphertext)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _assert_zk_vault(cur, principal["vault_id"])
        from routes.crypto_wallet_routes import _service_key_for_network
        cur.execute(
            "SELECT 1 FROM vault_items WHERE vault_id=%s "
            "AND item_type='crypto_wallet_account' AND service=%s "
            "AND encrypted_data IS NOT NULL LIMIT 1",
            (principal["vault_id"], _service_key_for_network(
                payload.asset, payload.network,
            )),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="legacy_wallet_exists")
        cur.execute(
            "SELECT wallet_record_id,chain,network,asset,public_address,"
            "wallet_label,payload_ciphertext,migration_state,legacy_item_id "
            "FROM wallet_v2_records WHERE vault_id=%s AND wallet_record_id=%s "
            "FOR UPDATE",
            (principal["vault_id"], payload.wallet_record_id),
        )
        existing = cur.fetchone()
        if existing:
            expected = {
                "chain": payload.chain, "network": payload.network,
                "asset": payload.asset, "public_address": payload.public_address,
                "wallet_label": payload.wallet_label,
                "payload_ciphertext": ciphertext,
                "migration_state": "migration_pending", "legacy_item_id": None,
            }
            if any(existing.get(key) != value for key, value in expected.items()):
                raise HTTPException(status_code=409, detail="wallet_stage_conflict")
            return {"wallet_record_id": payload.wallet_record_id,
                    "envelope_version": "v2", "migration_state": "migration_pending"}
        cur.execute("""INSERT INTO wallet_v2_records
          (vault_id,wallet_record_id,chain,network,asset,public_address,wallet_label,
           payload_ciphertext,envelope_version,migration_state)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (principal["vault_id"], payload.wallet_record_id, payload.chain,
           payload.network, payload.asset, payload.public_address, payload.wallet_label,
           ciphertext, payload.envelope_version, payload.migration_state))
        conn.commit()
        return {"wallet_record_id": payload.wallet_record_id,
                "envelope_version": "v2", "migration_state": "migration_pending"}
    except IntegrityError as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail="wallet_account_exists") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/vault/wallet-v2")
def list_wallet_v2(principal: SessionPrincipal = Depends(verify_trusted_device)):
    require_crypto_access(principal)
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT wallet_record_id,chain,network,asset,public_address,
          wallet_label,envelope_version,migration_state,created_at,updated_at
          FROM wallet_v2_records WHERE vault_id=%s AND migration_state='v2_verified'
          ORDER BY created_at DESC""",
          (principal["vault_id"],))
        return {"wallets": [dict(row) for row in cur.fetchall()]}
    finally:
        conn.close()


@router.get("/vault/wallet-v2/pending")
def list_pending_wallet_v2(principal: SessionPrincipal = Depends(verify_trusted_device)):
    """Owner-only metadata for resuming an interrupted stage.

    Pending ciphertext is retrieved through the exact record readback route;
    this listing never presents a pending wallet as available for receiving.
    """
    require_crypto_access(principal)
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT wallet_record_id,chain,network,asset,public_address,
          wallet_label,migration_state,legacy_item_id,legacy_source_snapshot
          FROM wallet_v2_records WHERE vault_id=%s
            AND migration_state='migration_pending'
          ORDER BY created_at DESC""", (principal["vault_id"],))
        return {"wallets": [dict(row) for row in cur.fetchall()]}
    finally:
        conn.close()


@router.get("/vault/wallet-v2/{wallet_record_id}")
def read_wallet_v2(wallet_record_id: str,
                   principal: SessionPrincipal = Depends(verify_trusted_device)):
    require_crypto_access(principal)
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT wallet_record_id,chain,network,asset,public_address,
          wallet_label,payload_ciphertext,envelope_version,migration_state,
          legacy_item_id,legacy_source_snapshot,created_at,updated_at
          FROM wallet_v2_records WHERE vault_id=%s AND wallet_record_id=%s""",
          (principal["vault_id"], wallet_record_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="wallet_v2_not_found")
        row["payload_ciphertext"] = base64.urlsafe_b64encode(
            bytes(row["payload_ciphertext"])).decode().rstrip("=")
        if row["migration_state"] == "migration_pending":
            purpose = "w" if row.get("legacy_item_id") else "wn"
            receipt, expires = _new_receipt(
                purpose, principal, wallet_record_id,
                _wallet_digest({**row, "payload_ciphertext": _decode(row["payload_ciphertext"])}),
            )
            row["readback_receipt"] = receipt
            row["receipt_expires_at"] = expires
        return dict(row)
    finally:
        conn.close()


@router.post("/vault/wallet-v2/{wallet_record_id}/publish-new")
def publish_new_wallet_v2(wallet_record_id: str,
                          payload: WalletV2PublishNewRequest,
                          principal: SessionPrincipal = Depends(verify_trusted_device)):
    require_content_write(principal)
    require_crypto_access(principal)
    _enabled(write=True)
    if not payload.client_verified_exact_bytes:
        raise HTTPException(status_code=409, detail="client_readback_required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _assert_zk_vault(cur, principal["vault_id"])
        cur.execute(
            "SELECT wallet_record_id,chain,network,asset,public_address,"
            "wallet_label,payload_ciphertext,migration_state,legacy_item_id,"
            "legacy_source_snapshot FROM wallet_v2_records WHERE vault_id=%s "
            "AND wallet_record_id=%s FOR UPDATE",
            (principal["vault_id"], wallet_record_id),
        )
        staged = cur.fetchone()
        if not staged or staged.get("migration_state") != "migration_pending" or \
                staged.get("legacy_item_id") is not None:
            raise HTTPException(status_code=409, detail="wallet_stage_not_ready")
        if not _receipt_valid(
            payload.readback_receipt, "wn", principal, wallet_record_id,
            _wallet_digest(staged),
        ):
            raise HTTPException(status_code=409, detail="wallet_readback_required")
        cur.execute(
            "UPDATE wallet_v2_records SET migration_state='v2_verified', "
            "updated_at=NOW() WHERE vault_id=%s AND wallet_record_id=%s "
            "AND migration_state='migration_pending' AND legacy_item_id IS NULL",
            (principal["vault_id"], wallet_record_id),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="wallet_stage_changed")
        conn.commit()
        return {"wallet_record_id": wallet_record_id, "migration_state": "v2_verified"}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/wallet-v2/migrate/retire")
def retire_legacy_wallet(payload: WalletV2MigrationRetireRequest,
                         principal: SessionPrincipal = Depends(verify_trusted_device)):
    _migration_enabled()
    require_content_write(principal)
    require_crypto_access(principal)
    if not payload.client_verified_exact_bytes:
        raise HTTPException(status_code=409, detail="client_readback_required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _assert_zk_vault(cur, principal["vault_id"])
        legacy = _load_legacy_wallet_locked(
            cur, principal["vault_id"], payload.legacy_item_id,
        )
        snapshot = legacy_source_snapshot(
            "item", legacy, vault_id=principal["vault_id"],
            record_id=payload.legacy_item_id,
        )
        if snapshot != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        cur.execute(
            "SELECT wallet_record_id,chain,network,asset,public_address,"
            "wallet_label,payload_ciphertext,migration_state,legacy_item_id,"
            "legacy_source_snapshot FROM wallet_v2_records WHERE vault_id=%s "
            "AND wallet_record_id=%s FOR UPDATE",
            (principal["vault_id"], payload.wallet_record_id),
        )
        staged = cur.fetchone()
        if not staged or staged.get("migration_state") != "migration_pending" or \
                staged.get("legacy_item_id") != payload.legacy_item_id or \
                staged.get("legacy_source_snapshot") != snapshot:
            raise HTTPException(status_code=409, detail="wallet_stage_not_ready")
        if (staged.get("chain"), staged.get("network"),
                staged.get("asset")) not in NEW_WALLET_SLOTS:
            raise HTTPException(status_code=409, detail="wallet_stage_slot_invalid")
        if not _receipt_valid(
            payload.readback_receipt, "w", principal,
            payload.wallet_record_id, _wallet_digest(staged),
        ):
            raise HTTPException(status_code=409, detail="wallet_readback_required")
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            "DELETE FROM vault_items WHERE vault_id=%s AND id=%s "
            "AND item_type='crypto_wallet_account' AND encrypted_data IS NOT NULL",
            (principal["vault_id"], payload.legacy_item_id),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="legacy_wallet_changed")
        cur.execute(
            "UPDATE wallet_v2_records SET migration_state='v2_verified', "
            "updated_at=NOW() WHERE vault_id=%s AND wallet_record_id=%s "
            "AND migration_state='migration_pending'",
            (principal["vault_id"], payload.wallet_record_id),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="wallet_stage_changed")
        conn.commit()
        return {"wallet_record_id": payload.wallet_record_id, "retired": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.delete("/vault/wallet-v2/{wallet_record_id}")
def delete_wallet_v2(wallet_record_id: str,
                     principal: SessionPrincipal = Depends(verify_trusted_device)):
    _enabled(write=True)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT legacy_item_id FROM wallet_v2_records "
            "WHERE vault_id=%s AND wallet_record_id=%s FOR UPDATE",
            (principal["vault_id"], wallet_record_id),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="wallet_v2_not_found")
        # New, migrated, and pending wallet rows all retain unique secret
        # material. No generic delete is safe until a separate proof-gated
        # flow defines recovery and loss-of-funds behavior.
        raise HTTPException(status_code=409, detail="wallet_delete_proof_required")
    finally:
        conn.close()
