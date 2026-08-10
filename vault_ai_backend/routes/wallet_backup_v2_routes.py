"""Opaque WalletBackupV2 persistence. This module intentionally has no decrypt primitive."""
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

router = APIRouter(tags=["wallet-backup-v2"])
SUPPORTED_SECRET_TYPES = {"private_key", "seed_phrase", "recovery_phrase"}


def _enabled(*, write: bool = False) -> None:
    flags = ZkMigrationFlags.from_environment(os.environ)
    flags.validate_dependencies()
    enabled = flags.wallet_backup_write_enabled if write else flags.wallet_backup_read_enabled
    if not enabled:
        raise HTTPException(status_code=404, detail="wallet_backup_v2_disabled")


def _decode(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_base64url") from exc
    if not decoded:
        raise HTTPException(status_code=400, detail="empty_ciphertext")
    return decoded


class WalletBackupV2CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backup_record_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    secret_type: str
    payload_ciphertext: str = Field(min_length=1)
    envelope_version: str = Field(pattern=r"^client_mvk_v2$")


@router.post("/vault/wallet-backup-v2")
def create_wallet_backup_v2(payload: WalletBackupV2CreateRequest,
                            principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled(write=True)
    if payload.secret_type not in SUPPORTED_SECRET_TYPES:
        raise HTTPException(status_code=400, detail="unsupported_secret_type")
    ciphertext = _decode(payload.payload_ciphertext)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO wallet_backup_v2_records
          (vault_id,backup_record_id,secret_type,payload_ciphertext,envelope_version)
          VALUES(%s,%s,%s,%s,%s)""", (principal["vault_id"], payload.backup_record_id,
          payload.secret_type, ciphertext, payload.envelope_version))
        conn.commit()
        return {"backup_record_id": payload.backup_record_id,
                "envelope_version": payload.envelope_version}
    finally:
        conn.close()


@router.get("/vault/wallet-backup-v2")
def list_wallet_backup_v2(principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT backup_record_id,secret_type,envelope_version,created_at,updated_at
          FROM wallet_backup_v2_records WHERE vault_id=%s ORDER BY created_at DESC""",
          (principal["vault_id"],))
        return {"backups": [dict(row) for row in cur.fetchall()]}
    finally:
        conn.close()


@router.get("/vault/wallet-backup-v2/{backup_record_id}")
def read_wallet_backup_v2(backup_record_id: str,
                          principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""SELECT backup_record_id,secret_type,payload_ciphertext,envelope_version,
          created_at,updated_at FROM wallet_backup_v2_records
          WHERE vault_id=%s AND backup_record_id=%s""",
          (principal["vault_id"], backup_record_id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="wallet_backup_v2_not_found")
        row["payload_ciphertext"] = base64.urlsafe_b64encode(
            bytes(row["payload_ciphertext"])).decode().rstrip("=")
        return dict(row)
    finally:
        conn.close()


@router.delete("/vault/wallet-backup-v2/{backup_record_id}")
def delete_wallet_backup_v2(backup_record_id: str,
                            principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled(write=True)
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM wallet_backup_v2_records WHERE vault_id=%s AND backup_record_id=%s",
                    (principal["vault_id"], backup_record_id))
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="wallet_backup_v2_not_found")
        conn.commit()
        return {"backup_record_id": backup_record_id, "deleted": True}
    finally:
        conn.close()
