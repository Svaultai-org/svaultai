"""Two-phase, client-verified migration from PIN ciphertext to MVK v2.

Stage never removes the legacy copy. Readback returns only client-supplied V2
ciphertext and a short-lived receipt bound to the current legacy and V2 bytes.
Retirement is a separate, default-disabled, one-time OPAQUE proof-gated step.
The client must decrypt readback and compare exact content before requesting
retirement; the server cannot verify plaintext without breaking ZK.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor

from auth_local import SessionPrincipal, _get_secret
from device_gate import verify_trusted_device
from legacy_source_snapshot import (
    FILE_SOURCE_FIELDS, MAX_SOURCE_CIPHERTEXT_CHARS,
    source_snapshot as legacy_source_snapshot,
)
from routes.auth_zk_routes import (
    consume_recent_zk_proof,
    consume_recent_zk_proof_on_cursor,
)
from subscription_entitlement import require_content_write
from vault_core import get_db


router = APIRouter()

RECEIPT_TTL_SECONDS = 10 * 60
MAX_ITEM_CIPHERTEXT_BYTES = 128 * 1024
MAX_FILE_MIGRATION_CIPHERTEXT_BYTES = 64 * 1024 * 1024
MAX_FILE_MIGRATION_CHUNKS = 4096
MAX_FILE_EXTRA_BYTES = 64 * 1024
MAX_FILE_EXTRA_V3_BYTES = 256 * 1024
MAX_FILE_V2_EXTRA_MANIFEST_BYTES = 512 * 1024
MAX_FILE_V3_EXTRA_MANIFEST_BYTES = 2 * 1024 * 1024
FILE_EXTRA_V3_FLAG = "VAULTAI_ZK_LEGACY_FILE_EXTRA_V3_ENABLED"


def _file_extra_limits(version: int) -> tuple[int, int]:
    if version == 3:
        return MAX_FILE_EXTRA_V3_BYTES, MAX_FILE_V3_EXTRA_MANIFEST_BYTES
    if version == 2:
        return MAX_FILE_EXTRA_BYTES, MAX_FILE_V2_EXTRA_MANIFEST_BYTES
    if version == 1:
        return MAX_FILE_EXTRA_BYTES, MAX_ITEM_CIPHERTEXT_BYTES
    raise HTTPException(status_code=409, detail="file_metadata_version_unsupported")


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _require_flag(name: str) -> None:
    if not _flag(name):
        raise HTTPException(status_code=404, detail="not_found")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value: str, *, field: str, max_bytes: int) -> bytes:
    if len(value) > max_bytes * 2:
        raise HTTPException(status_code=413, detail=f"{field}_too_large")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail=f"{field}_invalid")
    if not raw or len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail=f"{field}_invalid")
    return raw


def _feed_digest(hasher, value: object) -> None:
    if value is None:
        raw = b""
    elif isinstance(value, (str, int)):
        raw = str(value).encode("utf-8")
    else:
        raw = bytes(value)
    hasher.update(len(raw).to_bytes(8, "big"))
    hasher.update(raw)


def _item_digest(row: dict) -> bytes:
    hasher = hashlib.sha256(b"legacy-item-migration/v1\x00")
    for field in (
        "encrypted_data", "item_type", "service",
        "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
    ):
        _feed_digest(hasher, row.get(field))
    return hasher.digest()


def _legacy_item_edit_digest(candidate: dict) -> bytes:
    hasher = hashlib.sha256(b"legacy-item-edit-candidate/v1\x00")
    for field in (
        "candidate_id", "source_snapshot", "base_item_digest",
        "encrypted_data",
    ):
        value = candidate.get(field)
        _feed_digest(hasher, str(value) if field == "candidate_id" else value)
    if candidate.get("new_service_ciphertext") is not None:
        _feed_digest(hasher, b"encrypted-rename/v1")
        _feed_digest(hasher, candidate["new_service_ciphertext"])
        _feed_digest(hasher, candidate["new_title_lookup_hash"])
    return hasher.digest()


def _legacy_item_edit_base_digest(row: dict) -> bytes:
    """Include V2 staging and title index fields outside the legacy snapshot."""
    hasher = hashlib.sha256(b"legacy-item-edit-base/v1\x00")
    _feed_digest(hasher, _item_digest(row))
    _feed_digest(hasher, row.get("title_lookup_hash"))
    _feed_digest(hasher, row.get("title_revision"))
    return hasher.digest()


def _receipt_tag(
    domain: bytes,
    principal: SessionPrincipal,
    record_id: str,
    digest: bytes,
    expiry: int,
) -> bytes:
    message = (
        domain
        + uuid.UUID(str(principal["vault_id"])).bytes
        + uuid.UUID(str(principal["token_id"])).bytes
        + expiry.to_bytes(8, "big")
        + len(record_id).to_bytes(2, "big")
        + record_id.encode("utf-8")
        + digest
    )
    return hmac.new(_get_secret(), message, hashlib.sha256).digest()


def _new_receipt(
    kind: str, principal: SessionPrincipal,
    record_id: str, digest: bytes,
) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=RECEIPT_TTL_SECONDS,
    )
    expiry = int(expires_at.timestamp())
    domain = f"legacy-{kind}-readback/v1\x00".encode("ascii")
    tag = _receipt_tag(domain, principal, record_id, digest, expiry)
    return (f"{kind}r1.{expiry}.{_b64(digest)}.{_b64(tag)}", expires_at)


def _receipt_valid(
    receipt: str, kind: str, principal: SessionPrincipal,
    record_id: str, digest: bytes, *, now_ts: Optional[int] = None,
) -> bool:
    try:
        version, expiry_text, digest_text, tag_text = receipt.split(".")
        if version != f"{kind}r1":
            return False
        expiry = int(expiry_text)
        now = int(time.time()) if now_ts is None else now_ts
        if expiry <= now or expiry > now + RECEIPT_TTL_SECONDS:
            return False
        encoded_digest = base64.urlsafe_b64decode(
            digest_text + "=" * (-len(digest_text) % 4),
        )
        tag = base64.urlsafe_b64decode(
            tag_text + "=" * (-len(tag_text) % 4),
        )
        if len(encoded_digest) != 32 or len(tag) != 32:
            return False
        if not hmac.compare_digest(encoded_digest, digest):
            return False
        domain = f"legacy-{kind}-readback/v1\x00".encode("ascii")
        expected = _receipt_tag(domain, principal, record_id, digest, expiry)
        return hmac.compare_digest(tag, expected)
    except (ValueError, OverflowError, KeyError, binascii.Error):
        return False


class ItemStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(..., gt=0)
    item_type_ciphertext: str = Field(..., min_length=1)
    service_ciphertext: str = Field(..., min_length=1)
    payload_ciphertext: str = Field(..., min_length=1)
    source_snapshot: str = Field(..., min_length=43, max_length=43)


class ItemRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(..., gt=0)
    readback_receipt: str = Field(..., min_length=1, max_length=256)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    source_snapshot: str = Field(..., min_length=43, max_length=43)


class LegacyItemEditStageRequest(BaseModel):
    """Complete legacy ciphertext assembled and encrypted on the device."""

    model_config = ConfigDict(extra="forbid")
    source_snapshot: str = Field(..., min_length=43, max_length=43)
    candidate_encrypted_data: str = Field(..., min_length=40, max_length=174764)
    new_service_ciphertext: Optional[str] = Field(default=None, min_length=40, max_length=5500)
    new_title_lookup_hash: Optional[str] = Field(default=None, min_length=43, max_length=43)


class LegacyItemEditPromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot: str = Field(..., min_length=43, max_length=43)
    readback_receipt: str = Field(..., min_length=1, max_length=256)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    client_verified_exact_content: bool


class LegacyItemDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_snapshot: str = Field(..., min_length=43, max_length=43)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    confirm: bool


class FileRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str = Field(..., min_length=1, max_length=128)
    readback_receipt: str = Field(..., min_length=1, max_length=256)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)
    client_verified_exact_bytes: bool
    client_verified_extra_fields: bool = False
    source_snapshot: str = Field(..., min_length=43, max_length=43)


class ItemStageResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: int = Field(..., gt=0)
    source_snapshot: str = Field(..., min_length=43, max_length=43)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)


class FileStageResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str = Field(..., min_length=1, max_length=128)
    source_snapshot: str = Field(..., min_length=43, max_length=43)
    zk_proof_token: str = Field(..., min_length=1, max_length=128)


_ITEM_COLUMNS = (
    "encrypted_data, item_type, service, item_type_ciphertext, "
    "service_ciphertext, payload_ciphertext, title_lookup_hash, "
    "title_revision, created_at, legacy_item_rename_active"
)


def _load_item_locked(cur, vault_id: str, item_id: int) -> dict:
    cur.execute(
        f"SELECT {_ITEM_COLUMNS} FROM vault_items "
        "WHERE vault_id = %s AND id = %s FOR UPDATE",
        (vault_id, item_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="legacy_item_not_found")
    return row


def _item_v2_complete(row: dict) -> bool:
    return all(row.get(field) is not None for field in (
        "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
    ))


def _legacy_item_edit_ciphertext(value: str) -> None:
    """Reject noncanonical or truncated legacy AES-GCM framing, not plaintext."""
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="candidate_ciphertext_invalid")
    if (len(raw) < 29 or len(raw) > MAX_ITEM_CIPHERTEXT_BYTES or
            base64.b64encode(raw).decode("ascii") != value):
        raise HTTPException(status_code=400, detail="candidate_ciphertext_invalid")


def _legacy_item_rename_fields(payload: LegacyItemEditStageRequest) -> tuple[bytes | None, bytes | None]:
    encrypted = payload.new_service_ciphertext
    lookup = payload.new_title_lookup_hash
    if (encrypted is None) != (lookup is None):
        raise HTTPException(status_code=400, detail="encrypted_title_incomplete")
    if encrypted is None:
        return None, None
    _require_flag("VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_RENAME")
    raw = _decode(encrypted, field="new_service_ciphertext", max_bytes=4096)
    if _b64(raw) != encrypted or len(raw) < 30 or raw[0] != 1:
        raise HTTPException(status_code=400, detail="encrypted_title_invalid")
    title_hash = _decode(lookup, field="new_title_lookup_hash", max_bytes=32)
    if len(title_hash) != 32 or _b64(title_hash) != lookup:
        raise HTTPException(status_code=400, detail="title_lookup_invalid")
    return raw, title_hash


def _require_live_legacy_item_edit_session(cur, principal: SessionPrincipal) -> None:
    """Recheck live OPAQUE registration and this session inside the transaction."""
    token_id = principal.get("token_id")
    if not token_id:
        raise HTTPException(status_code=401, detail="session_expired")
    cur.execute(
        "SELECT opaque_registration_record IS NOT NULL AS zk_registered "
        "FROM vaults WHERE vault_id=%s",
        (principal["vault_id"],),
    )
    vault = cur.fetchone()
    if vault is None:
        raise HTTPException(status_code=404, detail="vault_not_found")
    if not vault["zk_registered"]:
        raise HTTPException(status_code=409, detail="zk_registration_required")
    cur.execute(
        "SELECT 1 FROM auth_sessions WHERE token_id=%s AND vault_id=%s "
        "AND auth_method='opaque' AND revoked_at IS NULL "
        "AND expires_at>NOW() FOR SHARE",
        (token_id, principal["vault_id"]),
    )
    if cur.fetchone() is None:
        raise HTTPException(status_code=401, detail="session_expired")


def _require_legacy_item_editable(row: dict) -> None:
    if row.get("encrypted_data") is None:
        raise HTTPException(status_code=409, detail="item_not_legacy")
    active_rename = row.get("legacy_item_rename_active") is True
    rename_shape = (
        row.get("service_ciphertext") is not None and
        row.get("title_lookup_hash") is not None and
        row.get("item_type_ciphertext") is None and
        row.get("payload_ciphertext") is None
    )
    if (row.get("item_type") in (None, "crypto_wallet_account") or
            row.get("item_type_ciphertext") is not None or
            row.get("payload_ciphertext") is not None or
            (active_rename and not rename_shape) or
            (row.get("service_ciphertext") is not None and not active_rename) or
            (row.get("title_lookup_hash") is not None and not active_rename)):
        raise HTTPException(status_code=409, detail="item_requires_dedicated_edit")


def _require_legacy_item_deletable(row: dict) -> None:
    if row.get("encrypted_data") is None:
        raise HTTPException(status_code=409, detail="item_not_legacy")
    if (row.get("item_type") in (None, "crypto_wallet_account") or
            row.get("item_type_ciphertext") is not None or
            row.get("payload_ciphertext") is not None):
        raise HTTPException(status_code=409, detail="item_requires_dedicated_delete")
    # An active encrypted rename has only a service sidecar and its lookup
    # hash. A partial V2 stage or malformed sidecar must not be deleted here.
    active_rename = row.get("legacy_item_rename_active") is True
    if (active_rename != (row.get("service_ciphertext") is not None) or
            active_rename != (row.get("title_lookup_hash") is not None)):
        raise HTTPException(status_code=409, detail="item_requires_dedicated_delete")


def _legacy_item_edit_candidate(cur, vault_id: str, item_id: int) -> dict:
    cur.execute(
        "SELECT candidate_id,source_snapshot,encrypted_data,"
        "base_item_digest,candidate_sha256,new_service_ciphertext,"
        "new_title_lookup_hash FROM legacy_item_edit_candidates "
        "WHERE vault_id=%s AND item_id=%s FOR UPDATE",
        (vault_id, item_id),
    )
    candidate = cur.fetchone()
    if candidate is None:
        raise HTTPException(status_code=404, detail="item_edit_not_staged")
    try:
        candidate_bytes = candidate["encrypted_data"].encode("ascii")
    except UnicodeEncodeError:
        raise HTTPException(status_code=409, detail="item_edit_candidate_changed")
    if not hmac.compare_digest(
        bytes(candidate["candidate_sha256"]), hashlib.sha256(candidate_bytes).digest(),
    ):
        raise HTTPException(status_code=409, detail="item_edit_candidate_changed")
    return candidate


@router.post("/vault/items/legacy-ciphertext/{item_id}/replace/stage")
def stage_legacy_item_edit(
    item_id: int,
    payload: LegacyItemEditStageRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Keep an encrypted proposed edit separate from the active legacy item."""
    _require_flag("VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_EDIT")
    require_content_write(principal)
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_item_id")
    _legacy_item_edit_ciphertext(payload.candidate_encrypted_data)
    new_service_ct, new_title_hash = _legacy_item_rename_fields(payload)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _require_live_legacy_item_edit_session(cur, principal)
        row = _load_item_locked(cur, principal["vault_id"], item_id)
        _require_legacy_item_editable(row)
        snapshot = legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"], record_id=item_id,
        )
        if snapshot != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        candidate_id = str(uuid.uuid4())
        candidate_sha256 = hashlib.sha256(
            payload.candidate_encrypted_data.encode("ascii"),
        ).digest()
        cur.execute(
            """INSERT INTO legacy_item_edit_candidates
                   (item_id,vault_id,candidate_id,source_snapshot,
                    encrypted_data,base_item_digest,candidate_sha256,
                    new_service_ciphertext,new_title_lookup_hash)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (item_id) DO UPDATE SET
                   candidate_id=EXCLUDED.candidate_id,
                   source_snapshot=EXCLUDED.source_snapshot,
                   encrypted_data=EXCLUDED.encrypted_data,
                   base_item_digest=EXCLUDED.base_item_digest,
                   candidate_sha256=EXCLUDED.candidate_sha256,
                   new_service_ciphertext=EXCLUDED.new_service_ciphertext,
                   new_title_lookup_hash=EXCLUDED.new_title_lookup_hash,
                   staged_at=NOW()
               WHERE legacy_item_edit_candidates.vault_id=EXCLUDED.vault_id
               RETURNING item_id""",
            (item_id, principal["vault_id"], candidate_id, snapshot,
             payload.candidate_encrypted_data,
             _legacy_item_edit_base_digest(row), candidate_sha256,
             new_service_ct, new_title_hash),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="item_owner_changed")
        conn.commit()
        return {"item_id": item_id, "staged": True,
                "active_item_unchanged": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/vault/items/legacy-ciphertext/{item_id}/replace/staged")
def readback_legacy_item_edit(
    item_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Return exactly the candidate the client must decrypt before promotion."""
    _require_flag("VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_EDIT")
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_item_id")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _require_live_legacy_item_edit_session(cur, principal)
        row = _load_item_locked(cur, principal["vault_id"], item_id)
        _require_legacy_item_editable(row)
        candidate = _legacy_item_edit_candidate(
            cur, principal["vault_id"], item_id,
        )
        snapshot = legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"], record_id=item_id,
        )
        if snapshot != candidate["source_snapshot"]:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        if not hmac.compare_digest(
            bytes(candidate["base_item_digest"]),
            _legacy_item_edit_base_digest(row),
        ):
            raise HTTPException(status_code=409, detail="item_stage_changed")
        receipt, expires_at = _new_receipt(
            "ie", principal, str(item_id), _legacy_item_edit_digest(candidate),
        )
        return {
            "item_id": item_id,
            "source_snapshot": snapshot,
            "candidate_encrypted_data": candidate["encrypted_data"],
            "new_service": None,
            "new_service_ciphertext": (
                _b64(bytes(candidate["new_service_ciphertext"]))
                if candidate["new_service_ciphertext"] is not None else None
            ),
            "new_title_lookup_hash": (
                _b64(bytes(candidate["new_title_lookup_hash"]))
                if candidate["new_title_lookup_hash"] is not None else None
            ),
            "readback_receipt": receipt,
            "receipt_expires_at": expires_at,
        }
    finally:
        conn.close()


@router.post("/vault/items/legacy-ciphertext/{item_id}/replace/promote")
def promote_legacy_item_edit(
    item_id: int,
    payload: LegacyItemEditPromoteRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Atomically promote a verified candidate, retaining the prior source."""
    _require_flag("VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_EDIT")
    require_content_write(principal)
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_item_id")
    if not payload.client_verified_exact_content:
        raise HTTPException(status_code=400, detail="client_readback_required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _require_live_legacy_item_edit_session(cur, principal)
        row = _load_item_locked(cur, principal["vault_id"], item_id)
        _require_legacy_item_editable(row)
        candidate = _legacy_item_edit_candidate(
            cur, principal["vault_id"], item_id,
        )
        snapshot = legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"], record_id=item_id,
        )
        if snapshot != candidate["source_snapshot"] or snapshot != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        if not hmac.compare_digest(
            bytes(candidate["base_item_digest"]),
            _legacy_item_edit_base_digest(row),
        ):
            raise HTTPException(status_code=409, detail="item_stage_changed")
        if not _receipt_valid(
            payload.readback_receipt, "ie", principal, str(item_id),
            _legacy_item_edit_digest(candidate),
        ):
            raise HTTPException(status_code=409, detail="readback_required")
        rename = candidate["new_service_ciphertext"] is not None
        if rename:
            _require_flag("VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_RENAME")
            if candidate["new_title_lookup_hash"] is None:
                raise HTTPException(status_code=409, detail="encrypted_title_incomplete")
        service_ct = (
            candidate["new_service_ciphertext"] if rename
            else row["service_ciphertext"]
        )
        title_hash = (
            candidate["new_title_lookup_hash"] if rename
            else row["title_lookup_hash"]
        )
        active_rename = rename or row["legacy_item_rename_active"]
        service = row["service"]
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        # Count only the active legacy blob, as the existing saved-item quota
        # does. Commit its delta with the edit so a failed write cannot drift.
        delta = (
            len(candidate["encrypted_data"].encode("ascii")) -
            len(row["encrypted_data"].encode("utf-8"))
        )
        if delta:
            cur.execute(
                "UPDATE vaults SET total_bytes=GREATEST(total_bytes+%s,0) "
                "WHERE vault_id=%s",
                (delta, principal["vault_id"]),
            )
            if cur.rowcount != 1:
                raise HTTPException(status_code=404, detail="vault_not_found")
        cur.execute(
            """INSERT INTO legacy_item_edit_history
                   (vault_id,item_id,prior_source_snapshot,prior_item_type,
                    prior_service,prior_encrypted_data,
                    prior_item_type_ciphertext,prior_service_ciphertext,
                    prior_payload_ciphertext,prior_title_lookup_hash,
                    prior_title_revision,prior_created_at,
                    promoted_candidate_sha256,encrypted_rename)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (principal["vault_id"], item_id, snapshot, row["item_type"],
             row["service"], row["encrypted_data"],
             row["item_type_ciphertext"], row["service_ciphertext"],
             row["payload_ciphertext"], row["title_lookup_hash"],
             row["title_revision"], row["created_at"],
             candidate["candidate_sha256"], rename),
        )
        cur.execute(
            """UPDATE vault_items
                  SET service=%s, encrypted_data=%s,
                      item_type_ciphertext=NULL,
                      service_ciphertext=%s,
                      payload_ciphertext=NULL,
                      title_lookup_hash=%s,
                      legacy_item_rename_active=%s,
                      title_revision=title_revision+1
                WHERE vault_id=%s AND id=%s AND encrypted_data IS NOT NULL""",
            (service, candidate["encrypted_data"], service_ct, title_hash,
             active_rename, principal["vault_id"], item_id),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        cur.execute(
            "DELETE FROM legacy_item_edit_candidates WHERE vault_id=%s "
            "AND item_id=%s",
            (principal["vault_id"], item_id),
        )
        conn.commit()
        try:
            from vault_tool_result_cache import invalidate_for_event
            event = (
                "credential_edited" if row["item_type"] in ("login", "credential")
                else "secure_item_edited"
            )
            invalidate_for_event(vault_id=principal["vault_id"], event=event)
        except Exception:
            pass
        return {"item_id": item_id, "id": item_id, "service": service,
                "item_type": row["item_type"], "updated": True,
                "created": False, "original_preserved_in_history": True,
                "renamed": rename,
                "service_ciphertext": (
                    _b64(bytes(service_ct)) if service_ct is not None else None
                )}
    except UniqueViolation as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail="duplicate_saved_item") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/items/legacy-ciphertext/{item_id}/delete")
def delete_legacy_item_without_pin(
    item_id: int,
    payload: LegacyItemDeleteRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Delete an owner-confirmed source and retained edit history atomically."""
    _require_flag("VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_DELETE")
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_item_id")
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="delete_confirmation_required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        _require_live_legacy_item_edit_session(cur, principal)
        row = _load_item_locked(cur, principal["vault_id"], item_id)
        _require_legacy_item_deletable(row)
        snapshot = legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"], record_id=item_id,
        )
        if snapshot != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        consume_recent_zk_proof_on_cursor(payload.zk_proof_token, principal, cur)
        cur.execute(
            "DELETE FROM legacy_item_edit_history WHERE vault_id=%s AND item_id=%s",
            (principal["vault_id"], item_id),
        )
        cur.execute(
            "DELETE FROM concierge_monitors WHERE vault_id=%s AND source_item_id=%s",
            (principal["vault_id"], str(item_id)),
        )
        cur.execute(
            "DELETE FROM vault_items WHERE vault_id=%s AND id=%s "
            "AND encrypted_data IS NOT NULL RETURNING id",
            (principal["vault_id"], item_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        cur.execute(
            "UPDATE vaults SET total_bytes=GREATEST(total_bytes-%s,0) "
            "WHERE vault_id=%s",
            (len(row["encrypted_data"].encode("utf-8")), principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=404, detail="vault_not_found")
        conn.commit()
        try:
            from vault_tool_result_cache import invalidate_for_event
            event = (
                "credential_deleted" if row["item_type"] in ("login", "credential")
                else "secure_item_deleted"
            )
            invalidate_for_event(vault_id=principal["vault_id"], event=event)
        except Exception:
            pass
        return {"status": "deleted", "item_id": item_id}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/legacy-ciphertext/migrate/item-stage")
def stage_legacy_item(
    payload: ItemStageRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED")
    require_content_write(principal)
    ciphertexts = (
        _decode(payload.item_type_ciphertext, field="item_type_ciphertext",
                max_bytes=MAX_ITEM_CIPHERTEXT_BYTES),
        _decode(payload.service_ciphertext, field="service_ciphertext",
                max_bytes=MAX_ITEM_CIPHERTEXT_BYTES),
        _decode(payload.payload_ciphertext, field="payload_ciphertext",
                max_bytes=MAX_ITEM_CIPHERTEXT_BYTES),
    )
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_item_locked(cur, principal["vault_id"], payload.item_id)
        if row.get("encrypted_data") is None:
            raise HTTPException(status_code=409, detail="item_not_legacy")
        if legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"],
            record_id=payload.item_id,
        ) != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        existing = tuple(row.get(field) for field in (
            "item_type_ciphertext", "service_ciphertext", "payload_ciphertext",
        ))
        if row.get("payload_ciphertext") is not None:
            if not _item_v2_complete(row) or tuple(
                bytes(value) for value in existing
            ) != ciphertexts:
                raise HTTPException(status_code=409, detail="staged_item_conflict")
            conn.commit()
            return {"item_id": payload.item_id, "staged": True,
                    "created": False,
                    "source_snapshot": payload.source_snapshot}
        cur.execute(
            """
            UPDATE vault_items
               SET item_type_ciphertext = %s,
                   service_ciphertext = %s,
                   payload_ciphertext = %s,
                   legacy_item_rename_active = FALSE
             WHERE id = %s AND vault_id = %s AND encrypted_data IS NOT NULL
            """,
            (*ciphertexts, payload.item_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="item_changed_during_stage")
        row.update(zip(("item_type_ciphertext", "service_ciphertext",
                        "payload_ciphertext"), ciphertexts))
        post_stage_snapshot = legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"],
            record_id=payload.item_id,
        )
        conn.commit()
        return {"item_id": payload.item_id, "staged": True, "created": True,
                "source_snapshot": post_stage_snapshot}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/vault/legacy-ciphertext/migrate/item-staged/{item_id}")
def readback_staged_item(
    item_id: int,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED")
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="invalid_item_id")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"SELECT {_ITEM_COLUMNS} FROM vault_items "
            "WHERE vault_id = %s AND id = %s",
            (principal["vault_id"], item_id),
        )
        row = cur.fetchone()
        if row is None or row.get("encrypted_data") is None:
            raise HTTPException(status_code=404, detail="legacy_item_not_found")
        if not _item_v2_complete(row):
            raise HTTPException(status_code=409, detail="item_not_staged")
        receipt, expires_at = _new_receipt(
            "i", principal, str(item_id), _item_digest(row),
        )
        return {
            "item_id": item_id,
            "source_snapshot": legacy_source_snapshot(
                "item", row, vault_id=principal["vault_id"],
                record_id=item_id,
            ),
            "item_type_ciphertext": _b64(bytes(row["item_type_ciphertext"])),
            "service_ciphertext": _b64(bytes(row["service_ciphertext"])),
            "payload_ciphertext": _b64(bytes(row["payload_ciphertext"])),
            "readback_receipt": receipt,
            "receipt_expires_at": expires_at,
        }
    finally:
        conn.close()


@router.post("/vault/legacy-ciphertext/migrate/item-reset-stage")
def reset_legacy_item_stage(
    payload: ItemStageResetRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Discard only an unfinished item copy after a legacy client changed it.

    The old PIN-derived ciphertext stays in place. A fresh source snapshot and
    one-time OPAQUE proof are required before the owner can export and restage.
    """
    _require_flag("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED")
    _require_flag("VAULTAI_ZK_LEGACY_STAGE_RECOVERY_ENABLED")
    require_content_write(principal)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_item_locked(cur, principal["vault_id"], payload.item_id)
        if row.get("encrypted_data") is None or not _item_v2_complete(row):
            raise HTTPException(409, detail="item_stage_not_resettable")
        if legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"],
            record_id=payload.item_id,
        ) != payload.source_snapshot:
            raise HTTPException(409, detail="legacy_source_changed")
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            """UPDATE vault_items SET payload_ciphertext=NULL
                 WHERE id=%s AND vault_id=%s AND encrypted_data IS NOT NULL
                   AND payload_ciphertext IS NOT NULL
                   RETURNING id""",
            (payload.item_id, principal["vault_id"]),
        )
        if cur.fetchone() is None:
            raise HTTPException(409, detail="item_stage_changed")
        conn.commit()
        return {"item_id": payload.item_id, "stage_reset": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/legacy-ciphertext/migrate/item-retire")
def retire_legacy_item(
    payload: ItemRetireRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_ITEM_RETIRE_ENABLED")
    require_content_write(principal)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_item_locked(cur, principal["vault_id"], payload.item_id)
        if row.get("encrypted_data") is None and _item_v2_complete(row):
            conn.commit()
            return {"item_id": payload.item_id, "retired": True,
                    "already_retired": True}
        if row.get("encrypted_data") is None or not _item_v2_complete(row):
            raise HTTPException(status_code=409, detail="item_not_ready")
        digest = _item_digest(row)
        if legacy_source_snapshot(
            "item", row, vault_id=principal["vault_id"],
            record_id=payload.item_id,
        ) != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        if not _receipt_valid(
            payload.readback_receipt, "i", principal, str(payload.item_id), digest,
        ):
            raise HTTPException(status_code=409, detail="readback_required")
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            """
            UPDATE vault_items
               SET encrypted_data = NULL, item_type = NULL, service = NULL
             WHERE id = %s AND vault_id = %s
               AND encrypted_data IS NOT NULL
               AND item_type_ciphertext IS NOT NULL
               AND service_ciphertext IS NOT NULL
               AND payload_ciphertext IS NOT NULL
            """,
            (payload.item_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="item_changed_during_retire")
        conn.commit()
        return {"item_id": payload.item_id, "retired": True,
                "already_retired": False}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_FILE_COLUMNS = """
    u.id, u.file_size, u.file_name, u.saved_name, u.content_type,
    u.detected_type, u.detected_service, u.asset_type,
    u.extracted_text, u.relative_path, u.encrypted_file_data,
    u.file_name_ciphertext, u.saved_name_ciphertext,
    u.content_type_ciphertext, u.detected_type_ciphertext,
    u.detected_service_ciphertext, u.asset_type_ciphertext,
    r.manifest_ciphertext, r.total_bytes, r.chunk_size, r.chunk_count,
    r.crypto_version, r.verification_state, r.migration_metadata_version
"""


def _load_file_pair(cur, vault_id: str, file_id: str, *, locked: bool) -> dict:
    # Bound the legacy inline blob before reading it into the process. Future
    # larger files need a streamed migration path; never silently skip them.
    cur.execute(
        """
        SELECT LENGTH(encrypted_file_data) AS legacy_chars,
               OCTET_LENGTH(extracted_text) AS text_bytes,
               OCTET_LENGTH(relative_path) AS path_bytes
          FROM uploaded_files
         WHERE id = %s AND vault_id = %s AND storage_mode = 'inline'
        """,
        (file_id, vault_id),
    )
    legacy = cur.fetchone()
    if legacy is None:
        raise HTTPException(status_code=404, detail="legacy_file_not_found")
    if (legacy.get("legacy_chars") or 0) > MAX_FILE_MIGRATION_CIPHERTEXT_BYTES:
        raise HTTPException(status_code=413, detail="file_migration_streaming_required")
    cur.execute(
        "SELECT OCTET_LENGTH(manifest_ciphertext) AS manifest_bytes, "
        "migration_metadata_version "
        "FROM file_v2_records WHERE file_id = %s AND vault_id = %s",
        (file_id, vault_id),
    )
    manifest_size = cur.fetchone()
    if manifest_size is None:
        raise HTTPException(status_code=409, detail="file_v2_not_staged")
    metadata_version = int(manifest_size.get("migration_metadata_version") or 1)
    text_limit, manifest_limit = _file_extra_limits(metadata_version)
    if ((legacy.get("text_bytes") or 0) > text_limit or
            (legacy.get("path_bytes") or 0) > 4096):
        raise HTTPException(status_code=413, detail="file_extra_migration_streaming_required")
    if int(manifest_size["manifest_bytes"]) > manifest_limit:
        raise HTTPException(status_code=413, detail="file_manifest_too_large")

    cur.execute(
        f"SELECT {_FILE_COLUMNS} FROM uploaded_files u "
        "JOIN file_v2_records r ON r.file_id = u.id AND r.vault_id = %s "
        "WHERE u.id = %s AND u.vault_id = %s AND u.storage_mode = 'inline' "
        + ("FOR UPDATE OF u, r" if locked else ""),
        (vault_id, file_id, vault_id),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail="file_v2_not_staged")
    # Readback may race a legacy update between preflight and the full read.
    # Recheck the version and byte ceilings against the actual source row.
    if int(row.get("migration_metadata_version") or 1) != metadata_version:
        raise HTTPException(status_code=409, detail="file_metadata_version_changed")
    if (len((row.get("extracted_text") or "").encode("utf-8")) > text_limit or
            len((row.get("relative_path") or "").encode("utf-8")) > 4096):
        raise HTTPException(status_code=413, detail="file_extra_migration_streaming_required")
    if len(bytes(row["manifest_ciphertext"])) > manifest_limit:
        raise HTTPException(status_code=413, detail="file_manifest_too_large")
    if row["crypto_version"] != "client_mvk_v2":
        raise HTTPException(status_code=409, detail="file_v2_crypto_version_mismatch")
    if int(row["total_bytes"]) != int(row["file_size"]):
        raise HTTPException(status_code=409, detail="file_v2_size_mismatch")
    return row


def _file_digest_and_v2_hash(
    cur, file_id: str, row: dict, *, locked: bool,
) -> tuple[bytes, str]:
    if (row.get("extracted_text") is not None or
            row.get("relative_path") is not None) and int(
                row.get("migration_metadata_version") or 1
            ) not in (2, 3):
        raise HTTPException(status_code=409, detail="file_extra_legacy_data_requires_migration")
    legacy_ciphertext = row.get("encrypted_file_data")
    if legacy_ciphertext is None:
        raise HTTPException(status_code=409, detail="file_already_retired")

    if int(row["chunk_count"]) > MAX_FILE_MIGRATION_CHUNKS:
        raise HTTPException(status_code=413, detail="file_migration_streaming_required")
    cur.execute(
        "SELECT COUNT(*) AS chunk_count, "
        "COALESCE(SUM(OCTET_LENGTH(ciphertext)), 0) AS ciphertext_bytes "
        "FROM file_v2_chunks WHERE file_id = %s",
        (file_id,),
    )
    aggregate = cur.fetchone() or {}
    if int(aggregate.get("chunk_count") or 0) != int(row["chunk_count"]):
        raise HTTPException(status_code=409, detail="file_v2_chunks_incomplete")
    if int(aggregate.get("ciphertext_bytes") or 0) > MAX_FILE_MIGRATION_CIPHERTEXT_BYTES:
        raise HTTPException(status_code=413, detail="file_migration_streaming_required")
    cur.execute(
        "SELECT chunk_index, ciphertext FROM file_v2_chunks "
        "WHERE file_id = %s ORDER BY chunk_index "
        + ("FOR UPDATE" if locked else ""),
        (file_id,),
    )
    chunks = cur.fetchall() or []
    expected_count = int(row["chunk_count"])
    if len(chunks) != expected_count:
        raise HTTPException(status_code=409, detail="file_v2_chunks_incomplete")
    if any(int(chunk["chunk_index"]) != index or not chunk["ciphertext"]
           for index, chunk in enumerate(chunks)):
        raise HTTPException(status_code=409, detail="file_v2_chunks_incomplete")
    v2_bytes = len(bytes(row["manifest_ciphertext"])) + sum(
        len(bytes(chunk["ciphertext"])) for chunk in chunks
    )
    if v2_bytes > MAX_FILE_MIGRATION_CIPHERTEXT_BYTES:
        raise HTTPException(status_code=413, detail="file_migration_streaming_required")

    v2_hasher = hashlib.sha256(b"file-v2-readback/v1\x00")
    _feed_digest(v2_hasher, row["manifest_ciphertext"])
    for index, chunk in enumerate(chunks):
        _feed_digest(v2_hasher, index.to_bytes(8, "big"))
        _feed_digest(v2_hasher, chunk["ciphertext"])

    hasher = hashlib.sha256(b"legacy-file-migration/v1\x00")
    for field in (
        "encrypted_file_data", "file_name", "saved_name", "content_type",
        "detected_type", "detected_service", "asset_type", "file_size",
        "extracted_text", "relative_path", "migration_metadata_version",
        "file_name_ciphertext", "saved_name_ciphertext",
        "content_type_ciphertext", "detected_type_ciphertext",
        "detected_service_ciphertext", "asset_type_ciphertext",
    ):
        _feed_digest(hasher, row.get(field))
    _feed_digest(hasher, v2_hasher.digest())
    return hasher.digest(), v2_hasher.hexdigest()


@router.get("/vault/legacy-ciphertext/migrate/file-staged/{file_id}")
def readback_staged_file(
    file_id: str,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED")
    if not file_id or len(file_id) > 128:
        raise HTTPException(status_code=400, detail="invalid_file_id")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        row = _load_file_pair(cur, principal["vault_id"], file_id, locked=False)
        digest, v2_hash = _file_digest_and_v2_hash(
            cur, file_id, row, locked=False,
        )
        receipt, expires_at = _new_receipt(
            "f", principal, file_id, digest,
        )
        return {
            "file_id": file_id,
            "source_snapshot": legacy_source_snapshot(
                "file", row, vault_id=principal["vault_id"],
                record_id=file_id,
            ),
            "manifest_ciphertext": _b64(bytes(row["manifest_ciphertext"])),
            "chunk_count": int(row["chunk_count"]),
            "total_bytes": int(row["total_bytes"]),
            "migration_metadata_version": int(row["migration_metadata_version"]),
            "v2_ciphertext_sha256": v2_hash,
            "readback_receipt": receipt,
            "receipt_expires_at": expires_at,
        }
    finally:
        conn.close()


@router.post("/vault/legacy-ciphertext/migrate/file-reset-stage")
def reset_legacy_file_stage(
    payload: FileStageResetRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    """Discard only an unfinished, marked V2 sidecar under the file lock."""
    _require_flag("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED")
    _require_flag("VAULTAI_ZK_LEGACY_STAGE_RECOVERY_ENABLED")
    require_content_write(principal)
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            (principal["vault_id"], payload.file_id),
        )
        cur.execute(
            "SELECT LENGTH(encrypted_file_data) AS legacy_chars "
            "FROM uploaded_files WHERE id=%s AND vault_id=%s "
            "AND storage_mode='inline' AND upload_status='complete' "
            "FOR UPDATE",
            (payload.file_id, principal["vault_id"]),
        )
        length_row = cur.fetchone()
        if length_row is None or length_row["legacy_chars"] is None:
            raise HTTPException(409, detail="legacy_file_not_resettable")
        if int(length_row["legacy_chars"]) > MAX_SOURCE_CIPHERTEXT_CHARS:
            raise HTTPException(413, detail="file_migration_streaming_required")
        cur.execute(
            f"SELECT {', '.join(FILE_SOURCE_FIELDS)} FROM uploaded_files "
            "WHERE id=%s AND vault_id=%s AND storage_mode='inline' "
            "AND upload_status='complete' FOR UPDATE",
            (payload.file_id, principal["vault_id"]),
        )
        source = cur.fetchone()
        if source is None or source.get("encrypted_file_data") is None:
            raise HTTPException(409, detail="legacy_file_not_resettable")
        if legacy_source_snapshot(
            "file", source, vault_id=principal["vault_id"],
            record_id=payload.file_id,
        ) != payload.source_snapshot:
            raise HTTPException(409, detail="legacy_source_changed")
        cur.execute(
            "SELECT migrating_legacy,lifecycle_state,verification_state,"
            "saved_name_override_ciphertext,name_version "
            "FROM file_v2_records WHERE file_id=%s AND vault_id=%s FOR UPDATE",
            (payload.file_id, principal["vault_id"]),
        )
        stage = cur.fetchone()
        if (stage is None or stage["migrating_legacy"] is not True or
                stage["lifecycle_state"] != "file_v2_written" or
                stage["verification_state"] != "not_verified" or
                stage["saved_name_override_ciphertext"] is not None or
                int(stage["name_version"]) != 0):
            raise HTTPException(409, detail="file_stage_not_resettable")
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            "DELETE FROM file_v2_records WHERE file_id=%s AND vault_id=%s "
            "AND migrating_legacy=TRUE AND lifecycle_state='file_v2_written' "
            "AND verification_state='not_verified' RETURNING file_id",
            (payload.file_id, principal["vault_id"]),
        )
        if cur.fetchone() is None:
            raise HTTPException(409, detail="file_stage_changed")
        conn.commit()
        return {"file_id": payload.file_id, "stage_reset": True}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/vault/legacy-ciphertext/migrate/file-retire")
def retire_legacy_file(
    payload: FileRetireRequest,
    principal: SessionPrincipal = Depends(verify_trusted_device),
) -> dict:
    _require_flag("VAULTAI_ZK_LEGACY_FILE_RETIRE_ENABLED")
    require_content_write(principal)
    if not payload.client_verified_exact_bytes:
        raise HTTPException(status_code=400, detail="client_readback_required")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            (principal["vault_id"], payload.file_id),
        )
        row = _load_file_pair(cur, principal["vault_id"], payload.file_id,
                              locked=True)
        has_extra = (row.get("extracted_text") is not None or
                     row.get("relative_path") is not None)
        if row.get("encrypted_file_data") is None:
            if row.get("verification_state") == "client_verified":
                conn.commit()
                return {"file_id": payload.file_id, "retired": True,
                        "already_retired": True}
            raise HTTPException(status_code=409, detail="file_retire_state_conflict")
        if (int(row.get("migration_metadata_version") or 1) == 3 and
                not _flag(FILE_EXTRA_V3_FLAG)):
            raise HTTPException(status_code=409, detail="file_extra_v3_retire_disabled")
        if has_extra and not _flag("VAULTAI_ZK_LEGACY_FILE_EXTRA_RETIRE_ENABLED"):
            raise HTTPException(status_code=409, detail="file_extra_retire_disabled")
        if has_extra and not payload.client_verified_extra_fields:
            raise HTTPException(status_code=400, detail="client_extra_readback_required")
        digest, _ = _file_digest_and_v2_hash(
            cur, payload.file_id, row, locked=True,
        )
        if legacy_source_snapshot(
            "file", row, vault_id=principal["vault_id"],
            record_id=payload.file_id,
        ) != payload.source_snapshot:
            raise HTTPException(status_code=409, detail="legacy_source_changed")
        if not _receipt_valid(
            payload.readback_receipt, "f", principal, payload.file_id, digest,
        ):
            raise HTTPException(status_code=409, detail="readback_required")
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            """
            UPDATE uploaded_files
               SET encrypted_file_data = NULL,
                   file_name = NULL, saved_name = NULL,
                   content_type = NULL, detected_type = NULL,
                   detected_service = NULL, asset_type = NULL,
                   extracted_text = NULL, relative_path = NULL
             WHERE id = %s AND vault_id = %s
               AND storage_mode = 'inline' AND encrypted_file_data IS NOT NULL
            """,
            (payload.file_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="file_changed_during_retire")
        cur.execute(
            """
            UPDATE file_v2_records
               SET verification_state = 'client_verified',
                   lifecycle_state = 'legacy_migration_retired'
             WHERE file_id = %s AND vault_id = %s
            """,
            (payload.file_id, principal["vault_id"]),
        )
        if cur.rowcount != 1:
            raise HTTPException(status_code=409, detail="file_v2_changed_during_retire")
        conn.commit()
        return {"file_id": payload.file_id, "retired": True,
                "already_retired": False}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
