"""Opaque WalletV2 persistence. Signing and decryption are client-only."""
from __future__ import annotations

import base64
import binascii
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal, verify_session_token
from vault_core import get_db
from zk_migration_flags import ZkMigrationFlags
from subscription_entitlement import require_content_write, require_crypto_access

router = APIRouter(tags=["wallet-v2"])
CHAINS = {"evm", "solana", "tron", "monero"}


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
    migration_state: str = Field(default="v2_verified", pattern=r"^(migration_pending|v2_verified|migration_failed)$")


@router.post("/vault/wallet-v2")
def create_wallet_v2(payload: WalletV2CreateRequest,
                     principal: SessionPrincipal = Depends(verify_session_token)):
    require_content_write(principal)
    require_crypto_access(principal)
    _enabled(write=True)
    if payload.chain not in CHAINS:
        raise HTTPException(status_code=400, detail="unsupported_chain")
    ciphertext = _decode(payload.payload_ciphertext)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO wallet_v2_records
          (vault_id,wallet_record_id,chain,network,asset,public_address,wallet_label,
           payload_ciphertext,envelope_version,migration_state)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
          (principal["vault_id"], payload.wallet_record_id, payload.chain,
           payload.network, payload.asset, payload.public_address, payload.wallet_label,
           ciphertext, payload.envelope_version, payload.migration_state))
        conn.commit()
        return {"wallet_record_id": payload.wallet_record_id, "envelope_version": "v2"}
    finally:
        conn.close()


@router.get("/vault/wallet-v2")
def list_wallet_v2(principal: SessionPrincipal = Depends(verify_session_token)):
    require_crypto_access(principal)
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT wallet_record_id,chain,network,asset,public_address,
          wallet_label,envelope_version,migration_state,created_at,updated_at
          FROM wallet_v2_records WHERE vault_id=%s ORDER BY created_at DESC""",
          (principal["vault_id"],))
        return {"wallets": [dict(row) for row in cur.fetchall()]}
    finally:
        conn.close()


@router.get("/vault/wallet-v2/{wallet_record_id}")
def read_wallet_v2(wallet_record_id: str,
                   principal: SessionPrincipal = Depends(verify_session_token)):
    require_crypto_access(principal)
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT wallet_record_id,chain,network,asset,public_address,
          wallet_label,payload_ciphertext,envelope_version,migration_state,created_at,updated_at
          FROM wallet_v2_records WHERE vault_id=%s AND wallet_record_id=%s""",
          (principal["vault_id"], wallet_record_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="wallet_v2_not_found")
        row["payload_ciphertext"] = base64.urlsafe_b64encode(
            bytes(row["payload_ciphertext"])).decode().rstrip("=")
        return dict(row)
    finally:
        conn.close()


@router.delete("/vault/wallet-v2/{wallet_record_id}")
def delete_wallet_v2(wallet_record_id: str,
                     principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled(write=True)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM wallet_v2_records WHERE vault_id=%s AND wallet_record_id=%s",
                    (principal["vault_id"], wallet_record_id))
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="wallet_v2_not_found")
        conn.commit()
        return {"wallet_record_id": wallet_record_id, "deleted": True}
    finally:
        conn.close()
