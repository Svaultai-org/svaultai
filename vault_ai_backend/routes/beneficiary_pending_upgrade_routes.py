"""Owner-approved replacement of an unpaired legacy beneficiary invitation.

The old PIN-wrapped link survives staging and client readback. Only a fresh
OPAQUE proof plus a session-bound readback receipt can retire that exact old
row. Linked links and links with inheritance packages need a separate
two-party ceremony and are deliberately outside this route.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from inheritance_protocol import ZK_BENEFICIARY_V2_MARKER, zk_beneficiary_v2_enabled
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from routes.legacy_ciphertext_migration_routes import _new_receipt, _receipt_valid
from subscription_entitlement import require_content_write
from vault_core import (
    PAIRING_CODE_TTL_MINUTES, generate_pairing_code, get_db, hash_pairing_code,
)


router = APIRouter(tags=["beneficiary-pending-upgrade"])
_OLD_COLUMNS = """id,passer_vault_id,beneficiary_vault_id,passer_label,
  passer_label_ciphertext,wrapped_vault_key,status,pairing_state,
  pairing_code_hash,pairing_expires_at,transfer_requested_at,
  transfer_executes_at,access_requested_at,cooldown_ends_at,decision_at"""
_NEW_COLUMNS = """id,passer_vault_id,beneficiary_vault_id,
  passer_label_ciphertext,wrapped_vault_key,status,pairing_state,
  pairing_code_hash,pairing_expires_at"""


class PendingUpgradeStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_link_id: int = Field(gt=0)
    passer_label_ciphertext: str = Field(min_length=40, max_length=4096)
    zk_proof_token: str = Field(min_length=1, max_length=128)


class PendingUpgradeRetire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_link_id: int = Field(gt=0)
    new_link_id: int = Field(gt=0)
    old_source_snapshot: str = Field(min_length=43, max_length=43)
    readback_receipt: str = Field(min_length=1, max_length=256)
    client_verified_exact_bytes: bool
    zk_proof_token: str = Field(min_length=1, max_length=128)


class PendingUpgradeAbort(BaseModel):
    model_config = ConfigDict(extra="forbid")
    old_link_id: int = Field(gt=0)
    zk_proof_token: str = Field(min_length=1, max_length=128)


def _enabled() -> None:
    if (os.getenv("VAULTAI_ZK_LEGACY_BENEFICIARY_UPGRADE_ENABLED", "false")
            .strip().lower() != "true" or
            os.getenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", "false")
            .strip().lower() != "true" or
            not zk_beneficiary_v2_enabled()):
        raise HTTPException(status_code=404, detail="not_found")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _label_bytes(encoded: str) -> bytes:
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
           for ch in encoded):
        raise HTTPException(status_code=400, detail="invalid_label_ciphertext")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="invalid_label_ciphertext") from exc
    if (len(raw) < 29 or len(raw) > 3072 or _b64(raw) != encoded):
        raise HTTPException(status_code=400, detail="invalid_label_ciphertext")
    return raw


def _feed(h, value: object) -> None:
    if value is None:
        raw = b""
    elif isinstance(value, bytes):
        raw = value
    else:
        raw = str(value).encode("utf-8")
    h.update(len(raw).to_bytes(8, "big"))
    h.update(raw)


def _old_snapshot(row: dict) -> str:
    h = hashlib.sha256(b"beneficiary-pending-old/v1\x00")
    for key in (
        "id", "passer_vault_id", "beneficiary_vault_id", "passer_label",
        "passer_label_ciphertext", "wrapped_vault_key", "status",
        "pairing_state", "pairing_code_hash", "pairing_expires_at",
        "transfer_requested_at", "transfer_executes_at",
        "access_requested_at", "cooldown_ends_at", "decision_at",
    ):
        _feed(h, row.get(key))
    return _b64(h.digest())


def _readback_digest(old_snapshot: str, new: dict) -> bytes:
    h = hashlib.sha256(b"beneficiary-pending-readback/v1\x00")
    _feed(h, old_snapshot)
    for key in (
        "id", "passer_vault_id", "beneficiary_vault_id",
        "passer_label_ciphertext", "wrapped_vault_key", "status",
        "pairing_state", "pairing_code_hash", "pairing_expires_at",
    ):
        _feed(h, new.get(key))
    return h.digest()


def _require_zk_owner(cur, vault_id: str) -> None:
    cur.execute("""SELECT vault_handle,opaque_registration_record,
      wrapped_mvk,pk_vault_public FROM vaults WHERE vault_id=%s""", (vault_id,))
    row = cur.fetchone()
    if (not row or row.get("vault_handle") is None or
            row.get("opaque_registration_record") is None or
            row.get("wrapped_mvk") is None or
            row.get("pk_vault_public") is None or
            len(bytes(row["pk_vault_public"])) != 32):
        raise HTTPException(status_code=409, detail="zk_owner_required")


def _load_old(cur, vault_id: str, old_link_id: int, *, lock: bool) -> dict:
    cur.execute(
        f"SELECT {_OLD_COLUMNS} FROM beneficiary_links "
        "WHERE id=%s AND passer_vault_id=%s" + (" FOR UPDATE" if lock else ""),
        (old_link_id, vault_id),
    )
    row = cur.fetchone()
    if (not row or row["wrapped_vault_key"] == ZK_BENEFICIARY_V2_MARKER or
            row["status"] != "pairing_pending" or
            row["beneficiary_vault_id"] is not None or
            row.get("pairing_state") not in (None, "paired_no_credentials") or
            any(row.get(field) is not None for field in (
                "transfer_requested_at", "transfer_executes_at",
                "access_requested_at", "cooldown_ends_at", "decision_at",
            ))):
        raise HTTPException(status_code=409, detail="old_link_not_pending")
    cur.execute("""SELECT 1 FROM inheritance_credentials
      WHERE beneficiary_link_id=%s LIMIT 1""", (old_link_id,))
    if cur.fetchone():
        raise HTTPException(status_code=409, detail="old_link_has_package")
    return row


def _load_binding(cur, vault_id: str, old_link_id: int, *, lock: bool) -> dict:
    cur.execute("""SELECT old_link_id,new_link_id,owner_vault_id,
      old_source_snapshot FROM beneficiary_pending_upgrades
      WHERE old_link_id=%s AND owner_vault_id=%s""" +
      (" FOR UPDATE" if lock else ""), (old_link_id, vault_id))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="upgrade_not_found")
    return row


def _load_new(cur, vault_id: str, new_link_id: int, *, lock: bool,
              require_unexpired: bool = True) -> dict:
    cur.execute(
        f"SELECT {_NEW_COLUMNS} FROM beneficiary_links "
        "WHERE id=%s AND passer_vault_id=%s" + (" FOR UPDATE" if lock else ""),
        (new_link_id, vault_id),
    )
    row = cur.fetchone()
    if (not row or row["wrapped_vault_key"] != ZK_BENEFICIARY_V2_MARKER or
            row["status"] != "pairing_pending" or
            row["beneficiary_vault_id"] is not None or
            row.get("pairing_state") not in (None, "paired_no_credentials") or
            row.get("pairing_code_hash") is None or
            row.get("pairing_expires_at") is None or
            (require_unexpired and
             row["pairing_expires_at"] <= datetime.now(timezone.utc))):
        raise HTTPException(status_code=409, detail="new_link_not_pending")
    return row


@router.post("/beneficiary/zk-upgrade-pending/stage")
def stage_pending_upgrade(payload: PendingUpgradeStage,
                          principal: SessionPrincipal = Depends(verify_trusted_device)) -> dict:
    _enabled()
    require_content_write(principal)
    label = _label_bytes(payload.passer_label_ciphertext)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _require_zk_owner(cur, principal["vault_id"])
        old = _load_old(cur, principal["vault_id"], payload.old_link_id, lock=True)
        cur.execute("SELECT new_link_id FROM beneficiary_pending_upgrades WHERE old_link_id=%s",
                    (payload.old_link_id,))
        prior = cur.fetchone()
        if prior:
            # A lost response or failed readback may leave a staged but
            # undisclosed code. A fresh owner proof can replace that pending
            # invitation without touching the old link. A code already
            # claimed by a beneficiary must never be silently replaced.
            _load_new(cur, principal["vault_id"], prior["new_link_id"],
                      lock=True, require_unexpired=False)
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        if prior:
            cur.execute("DELETE FROM beneficiary_links WHERE id=%s AND passer_vault_id=%s",
                        (prior["new_link_id"], principal["vault_id"]))
            if cur.rowcount != 1:
                raise HTTPException(status_code=409, detail="prior_stage_changed")
        code = generate_pairing_code()
        expires = datetime.now(timezone.utc) + timedelta(
            minutes=PAIRING_CODE_TTL_MINUTES,
        )
        cur.execute("""INSERT INTO beneficiary_links
          (passer_vault_id,passer_label,passer_label_ciphertext,
           pairing_code_hash,pairing_expires_at,wrapped_vault_key,status)
          VALUES (%s,NULL,%s,%s,%s,%s,'pairing_pending') RETURNING id""",
          (principal["vault_id"], label, hash_pairing_code(code), expires,
           ZK_BENEFICIARY_V2_MARKER))
        new_id = cur.fetchone()["id"]
        snapshot = _old_snapshot(old)
        cur.execute("""INSERT INTO beneficiary_pending_upgrades
          (old_link_id,new_link_id,owner_vault_id,old_source_snapshot)
          VALUES (%s,%s,%s,%s)""",
          (payload.old_link_id, new_id, principal["vault_id"], snapshot))
        conn.commit()
        return {"old_link_id": payload.old_link_id, "new_link_id": new_id,
                "old_source_snapshot": snapshot, "pairing_code": code}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/beneficiary/zk-upgrade-pending/{old_link_id}/readback")
def readback_pending_upgrade(old_link_id: int,
                             principal: SessionPrincipal = Depends(verify_trusted_device)) -> dict:
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        old = _load_old(cur, principal["vault_id"], old_link_id, lock=False)
        binding = _load_binding(cur, principal["vault_id"], old_link_id, lock=False)
        if binding["old_source_snapshot"] != _old_snapshot(old):
            raise HTTPException(status_code=409, detail="old_link_changed")
        new = _load_new(cur, principal["vault_id"], binding["new_link_id"], lock=False)
        receipt, expires = _new_receipt(
            "bp", principal, f"{old_link_id}:{new['id']}",
            _readback_digest(binding["old_source_snapshot"], new),
        )
        return {"old_link_id": old_link_id, "new_link_id": new["id"],
                "old_source_snapshot": binding["old_source_snapshot"],
                "passer_label_ciphertext": _b64(bytes(new["passer_label_ciphertext"])),
                "pairing_code_hash": new["pairing_code_hash"],
                "pairing_expires_at": new["pairing_expires_at"].isoformat(),
                "pairing_protocol": "zk-beneficiary-v2",
                "status": new["status"],
                "beneficiary_vault_id": new["beneficiary_vault_id"],
                "readback_receipt": receipt,
                "receipt_expires_at": expires.isoformat()}
    finally:
        conn.close()


@router.post("/beneficiary/zk-upgrade-pending/retire")
def retire_pending_upgrade(payload: PendingUpgradeRetire,
                           principal: SessionPrincipal = Depends(verify_trusted_device)) -> dict:
    _enabled()
    require_content_write(principal)
    if not payload.client_verified_exact_bytes:
        raise HTTPException(status_code=409, detail="client_readback_required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        old = _load_old(cur, principal["vault_id"], payload.old_link_id, lock=True)
        binding = _load_binding(cur, principal["vault_id"], payload.old_link_id, lock=True)
        if (binding["new_link_id"] != payload.new_link_id or
                binding["old_source_snapshot"] != payload.old_source_snapshot or
                _old_snapshot(old) != payload.old_source_snapshot):
            raise HTTPException(status_code=409, detail="old_link_changed")
        new = _load_new(cur, principal["vault_id"], payload.new_link_id, lock=True)
        if not _receipt_valid(
            payload.readback_receipt, "bp", principal,
            f"{payload.old_link_id}:{payload.new_link_id}",
            _readback_digest(payload.old_source_snapshot, new),
        ):
            raise HTTPException(status_code=409, detail="readback_required")
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        cur.execute("DELETE FROM beneficiary_links WHERE id=%s AND passer_vault_id=%s",
                    (payload.old_link_id, principal["vault_id"]))
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="old_link_changed")
        conn.commit()
        return {"old_link_id": payload.old_link_id,
                "new_link_id": payload.new_link_id, "retired": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/beneficiary/zk-upgrade-pending/abort")
def abort_pending_upgrade(payload: PendingUpgradeAbort,
                          principal: SessionPrincipal = Depends(verify_trusted_device)) -> dict:
    _enabled()
    require_content_write(principal)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _load_old(cur, principal["vault_id"], payload.old_link_id, lock=True)
        binding = _load_binding(cur, principal["vault_id"], payload.old_link_id, lock=True)
        _load_new(cur, principal["vault_id"], binding["new_link_id"],
                  lock=True, require_unexpired=False)
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        cur.execute("DELETE FROM beneficiary_links WHERE id=%s AND passer_vault_id=%s",
                    (binding["new_link_id"], principal["vault_id"]))
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="new_link_changed")
        conn.commit()
        return {"old_link_id": payload.old_link_id, "aborted": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
