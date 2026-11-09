"""Default-off staging of an owner-MVK envelope for a linked legacy link.

This route cannot switch, release, or retire a legacy link. The old wrapped
key, credential package, status, and countdown remain authoritative until a
separate beneficiary-verified ceremony is implemented.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from inheritance_protocol import ZK_BENEFICIARY_V2_MARKER, zk_beneficiary_v2_enabled
from routes.auth_zk_routes import consume_recent_zk_proof_on_cursor
from subscription_entitlement import require_content_write
from vault_core import get_db


router = APIRouter(tags=["linked-inheritance-v2-upgrade"])
FLAG_NAME = "VAULTAI_ZK_LINKED_BENEFICIARY_V2_STAGE_ENABLED"


class StageLinkedV2Package(BaseModel):
    model_config = ConfigDict(extra="forbid")
    beneficiary_link_id: int = Field(gt=0)
    crypto_version: Literal[2]
    expected_beneficiary_pk_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_stage_revision: int | None = Field(default=None, gt=0)
    zk_proof_token: str = Field(min_length=1, max_length=128)
    encrypted_payload: str = Field(min_length=1)
    payload_nonce: str = Field(min_length=1)
    wrapped_key: str = Field(min_length=1)
    wrapping_ephemeral_pk: str = Field(min_length=1)
    wrapping_nonce: str = Field(min_length=1)


_LINK_FIELDS = (
    "id", "passer_vault_id", "beneficiary_vault_id", "passer_label",
    "passer_label_ciphertext", "wrapped_vault_key", "status",
    "pairing_state", "transfer_requested_at", "transfer_executes_at",
    "access_requested_at", "cooldown_ends_at", "decision_at",
)
_CREDENTIAL_FIELDS = (
    "id", "crypto_version", "encrypted_payload", "payload_nonce",
    "wrapped_key", "wrapping_ephemeral_pk", "wrapping_nonce", "state",
)
_ENVELOPE_FIELDS = (
    "encrypted_payload", "payload_nonce", "wrapped_key",
    "wrapping_ephemeral_pk", "wrapping_nonce",
)


def _enabled() -> None:
    if (os.getenv(FLAG_NAME, "false").strip().lower() != "true" or
            os.getenv("VAULTAI_ZK_BENEFICIARY_PROOF_ENABLED", "false")
            .strip().lower() != "true" or
            not zk_beneficiary_v2_enabled()):
        raise HTTPException(status_code=404, detail="not_found")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str, *, low: int, high: int) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise HTTPException(status_code=400, detail="invalid_v2_envelope")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="invalid_v2_envelope") from exc
    if not low <= len(raw) <= high or _b64(raw) != value:
        raise HTTPException(status_code=400, detail="invalid_v2_envelope")
    return raw


def _envelope(payload: StageLinkedV2Package) -> dict[str, bytes]:
    return {
        "encrypted_payload": _decode(payload.encrypted_payload, low=32, high=65536),
        "payload_nonce": _decode(payload.payload_nonce, low=12, high=12),
        "wrapped_key": _decode(payload.wrapped_key, low=32, high=4096),
        "wrapping_ephemeral_pk": _decode(
            payload.wrapping_ephemeral_pk, low=32, high=32,
        ),
        "wrapping_nonce": _decode(payload.wrapping_nonce, low=12, high=12),
    }


def _feed(h, value: object) -> None:
    if value is None:
        raw = b""
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
    else:
        raw = str(value).encode("utf-8")
    h.update(len(raw).to_bytes(8, "big"))
    h.update(raw)


def _source_snapshot(link: dict, credential: dict | None) -> str:
    h = hashlib.sha256(b"linked-inheritance-v2-old-source/v1\x00")
    for name in _LINK_FIELDS:
        _feed(h, link.get(name))
    for name in _CREDENTIAL_FIELDS:
        _feed(h, credential.get(name) if credential else None)
    return _b64(h.digest())


def _load_old_link(cur, *, link_id: int, owner_vault_id: str, lock: bool) -> tuple[dict, dict | None]:
    suffix = "FOR UPDATE" if lock else "FOR SHARE"
    cur.execute(
        f"SELECT {', '.join(_LINK_FIELDS)} FROM beneficiary_links "
        f"WHERE id=%s AND passer_vault_id=%s {suffix}",
        (link_id, owner_vault_id),
    )
    link = cur.fetchone()
    if (not link or
            not isinstance(link["wrapped_vault_key"], str) or
            not link["wrapped_vault_key"] or
            link["wrapped_vault_key"] == ZK_BENEFICIARY_V2_MARKER or
            link["beneficiary_vault_id"] is None or
            str(link["beneficiary_vault_id"]) == str(owner_vault_id) or
            link["status"] != "linked" or
            link.get("pairing_state") not in
            (None, "paired_no_credentials", "credentials_saved") or
            any(link.get(name) is not None for name in (
                "transfer_requested_at", "transfer_executes_at",
                "access_requested_at", "cooldown_ends_at", "decision_at",
            ))):
        raise HTTPException(status_code=409, detail="old_link_not_idle_and_linked")
    cur.execute(
        """SELECT id,crypto_version,encrypted_payload,payload_nonce,
                  wrapped_key,wrapping_ephemeral_pk,wrapping_nonce,state
             FROM inheritance_credentials
            WHERE beneficiary_link_id=%s AND deleted_at IS NULL
            FOR SHARE""",
        (link_id,),
    )
    credential = cur.fetchone()
    if credential and int(credential["crypto_version"]) != 1:
        raise HTTPException(status_code=409, detail="old_link_package_protocol_changed")
    if ((credential is None and link.get("pairing_state") == "credentials_saved") or
            (credential is not None and
             (link.get("pairing_state") == "paired_no_credentials" or
              credential.get("state") != "credentials_saved"))):
        raise HTTPException(status_code=409, detail="old_link_package_state_changed")
    return link, credential


def _beneficiary_pk(cur, beneficiary_vault_id: str) -> bytes:
    cur.execute(
        """SELECT pk_vault_public,vault_handle,opaque_registration_record,
                  wrapped_mvk FROM vaults WHERE vault_id=%s FOR SHARE""",
        (beneficiary_vault_id,),
    )
    row = cur.fetchone()
    if (not row or row.get("pk_vault_public") is None or
            row.get("vault_handle") is None or
            row.get("opaque_registration_record") is None or
            row.get("wrapped_mvk") is None):
        raise HTTPException(status_code=409, detail="beneficiary_private_key_required")
    pk = bytes(row["pk_vault_public"])
    if len(pk) != 32:
        raise HTTPException(status_code=409, detail="beneficiary_private_key_required")
    return pk


def _stage_response(link_id: int, prior: dict, snapshot: str, pk_hash: bytes) -> dict:
    return {
        "beneficiary_link_id": link_id,
        "crypto_version": 2,
        "stage_revision": int(prior["stage_revision"]),
        "old_source_snapshot": snapshot,
        "beneficiary_pk_sha256": pk_hash.hex(),
        "state": "staged",
        "legacy_link_unchanged": True,
    }


@router.post("/inheritance/old-link-v2/stage")
def stage_linked_v2_package(
    payload: StageLinkedV2Package,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    require_content_write(principal)
    envelope = _envelope(payload)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, credential = _load_old_link(
            cur, link_id=payload.beneficiary_link_id,
            owner_vault_id=principal["vault_id"], lock=True,
        )
        pk_hash = hashlib.sha256(
            _beneficiary_pk(cur, str(link["beneficiary_vault_id"])),
        ).digest()
        if pk_hash.hex() != payload.expected_beneficiary_pk_sha256:
            raise HTTPException(status_code=409, detail="beneficiary_key_changed")
        snapshot = _source_snapshot(link, credential)
        cur.execute(
            """SELECT owner_vault_id,beneficiary_vault_id,
                      old_source_snapshot,beneficiary_pk_sha256,
                      encrypted_payload,payload_nonce,wrapped_key,
                      wrapping_ephemeral_pk,wrapping_nonce,
                      stage_revision,state
                 FROM beneficiary_link_v2_upgrades
                WHERE old_link_id=%s FOR UPDATE""",
            (payload.beneficiary_link_id,),
        )
        prior = cur.fetchone()
        if prior and (str(prior["owner_vault_id"]) != str(principal["vault_id"]) or
                      str(prior["beneficiary_vault_id"]) !=
                      str(link["beneficiary_vault_id"]) or
                      prior["state"] != "staged"):
            raise HTTPException(status_code=409, detail="old_link_upgrade_changed")
        same = bool(prior and prior["old_source_snapshot"] == snapshot and
                    bytes(prior["beneficiary_pk_sha256"]) == pk_hash and
                    all(bytes(prior[name]) == envelope[name]
                        for name in _ENVELOPE_FIELDS))
        if prior and not same and (
                payload.expected_stage_revision != int(prior["stage_revision"])):
            raise HTTPException(status_code=409, detail="stage_revision_required")
        if not prior and payload.expected_stage_revision is not None:
            raise HTTPException(status_code=409, detail="stage_revision_changed")
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        if prior is None:
            cur.execute(
                """INSERT INTO beneficiary_link_v2_upgrades (
                      old_link_id,owner_vault_id,beneficiary_vault_id,
                      old_source_snapshot,beneficiary_pk_sha256,
                      encrypted_payload,payload_nonce,wrapped_key,
                      wrapping_ephemeral_pk,wrapping_nonce)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING stage_revision""",
                (payload.beneficiary_link_id, principal["vault_id"],
                 link["beneficiary_vault_id"], snapshot, pk_hash,
                 *(envelope[name] for name in _ENVELOPE_FIELDS)),
            )
            revision = int(cur.fetchone()["stage_revision"])
        elif same:
            revision = int(prior["stage_revision"])
        else:
            cur.execute(
                """UPDATE beneficiary_link_v2_upgrades
                      SET old_source_snapshot=%s,beneficiary_pk_sha256=%s,
                          encrypted_payload=%s,payload_nonce=%s,
                          wrapped_key=%s,wrapping_ephemeral_pk=%s,
                          wrapping_nonce=%s,stage_revision=stage_revision+1,
                          updated_at=NOW()
                    WHERE old_link_id=%s AND owner_vault_id=%s
                      AND stage_revision=%s AND state='staged'
                    RETURNING stage_revision""",
                (snapshot, pk_hash,
                 *(envelope[name] for name in _ENVELOPE_FIELDS),
                 payload.beneficiary_link_id, principal["vault_id"],
                 payload.expected_stage_revision),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=409, detail="stage_revision_changed")
            revision = int(row["stage_revision"])
        conn.commit()
        return _stage_response(
            payload.beneficiary_link_id,
            {"stage_revision": revision}, snapshot, pk_hash,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/inheritance/old-link-v2/{link_id}/readback")
def readback_linked_v2_package(
    link_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _enabled()
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        link, credential = _load_old_link(
            cur, link_id=link_id, owner_vault_id=principal["vault_id"],
            lock=False,
        )
        snapshot = _source_snapshot(link, credential)
        pk_hash = hashlib.sha256(
            _beneficiary_pk(cur, str(link["beneficiary_vault_id"])),
        ).digest()
        cur.execute(
            """SELECT beneficiary_vault_id,old_source_snapshot,beneficiary_pk_sha256,
                      encrypted_payload,payload_nonce,wrapped_key,
                      wrapping_ephemeral_pk,wrapping_nonce,
                      stage_revision,state
                 FROM beneficiary_link_v2_upgrades
                WHERE old_link_id=%s AND owner_vault_id=%s""",
            (link_id, principal["vault_id"]),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="upgrade_not_staged")
        if (row["state"] != "staged" or
                str(row["beneficiary_vault_id"]) !=
                str(link["beneficiary_vault_id"]) or
                row["old_source_snapshot"] != snapshot or
                bytes(row["beneficiary_pk_sha256"]) != pk_hash):
            raise HTTPException(status_code=409, detail="old_link_or_key_changed")
        return {
            **_stage_response(link_id, row, snapshot, pk_hash),
            **{name: _b64(bytes(row[name])) for name in _ENVELOPE_FIELDS},
        }
    finally:
        conn.close()
