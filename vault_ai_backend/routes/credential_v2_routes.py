"""Feature-gated opaque credential-v2 data API.

The request models intentionally have no PIN, MVK, key, or plaintext fields.
The backend validates framing and ownership, stores opaque strings, and returns
them unchanged.  There is deliberately no decrypt or legacy fallback helper.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg2.extras import Json, RealDictCursor

from auth_local import SessionPrincipal, verify_session_token
from vault_core import get_db
from zk_migration_flags import ZkMigrationFlags
from vault_credential_draft import consume_draft, get_draft


router = APIRouter(prefix="/vault/v2/credentials", tags=["credential-v2"])

MAX_CIPHERTEXT_BYTES = 128 * 1024
_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_INDEX_NAMES = {"service", "username", "url_host"}


def _decode_b64url(value: str, *, field: str, expected: int | None = None) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise ValueError(f"{field} must be base64url") from exc
    if not raw:
        raise ValueError(f"{field} must not be empty")
    if expected is not None and len(raw) != expected:
        raise ValueError(f"{field} must decode to {expected} bytes")
    return raw


def _flags() -> ZkMigrationFlags:
    flags = ZkMigrationFlags.from_environment(os.environ)
    flags.validate_dependencies()
    return flags


def _require(name: Literal["read", "write", "migration"]) -> None:
    flags = _flags()
    if not getattr(flags, f"{name}_enabled"):
        raise HTTPException(status_code=404, detail="credential v2 path is disabled")


class CredentialV2WriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(..., min_length=1, max_length=128)
    crypto_version: Literal["client_mvk_v2"]
    cipher_suite: Literal["aes_256_gcm_v1"]
    key_domain: Literal["credential"]
    nonce: str = Field(..., min_length=1, max_length=64)
    ciphertext: str = Field(..., min_length=1, max_length=180_000)
    authentication_tag: str = Field(..., min_length=1, max_length=64)
    blind_indexes: dict[str, str] = Field(default_factory=dict)
    migration_operation_id: UUID | None = None

    @field_validator("record_id")
    @classmethod
    def validate_record_id(cls, value: str) -> str:
        if not _RECORD_ID.fullmatch(value):
            raise ValueError("record_id has invalid format")
        return value

    @field_validator("nonce")
    @classmethod
    def validate_nonce(cls, value: str) -> str:
        _decode_b64url(value, field="nonce", expected=12)
        return value

    @field_validator("authentication_tag")
    @classmethod
    def validate_tag(cls, value: str) -> str:
        _decode_b64url(value, field="authentication_tag", expected=16)
        return value

    @field_validator("ciphertext")
    @classmethod
    def validate_ciphertext(cls, value: str) -> str:
        raw = _decode_b64url(value, field="ciphertext")
        if len(raw) > MAX_CIPHERTEXT_BYTES:
            raise ValueError("ciphertext exceeds size limit")
        return value

    @field_validator("blind_indexes")
    @classmethod
    def validate_indexes(cls, value: dict[str, str]) -> dict[str, str]:
        if not set(value).issubset(_INDEX_NAMES):
            raise ValueError("unsupported blind-index name")
        for token in value.values():
            _decode_b64url(token, field="blind index", expected=32)
        return value


class CredentialV2EnvelopeResponse(BaseModel):
    record_id: str
    crypto_version: Literal["client_mvk_v2"]
    cipher_suite: Literal["aes_256_gcm_v1"]
    key_domain: Literal["credential"]
    nonce: str
    ciphertext: str
    authentication_tag: str
    blind_indexes: dict[str, str]
    migration_state: str
    verification_state: str


class GeneratedDraftFinalizeResponse(BaseModel):
    status: Literal["finalized", "already_finalized"]
    record_id: str
    draft_id: str


@router.post("/generated-drafts/{draft_id}/cancel", response_model=dict)
def cancel_generated_draft_v2(
    draft_id: str,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    _require("write")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", draft_id):
        raise HTTPException(status_code=400, detail="draft_id has invalid format")
    consume_draft(vault_id=str(principal["vault_id"]), draft_id=draft_id)
    return {"status": "cancelled", "draft_id": draft_id}


def _response(row: dict) -> CredentialV2EnvelopeResponse:
    return CredentialV2EnvelopeResponse(
        record_id=row["record_id"],
        crypto_version=row["crypto_version"],
        cipher_suite=row["cipher_suite"],
        key_domain=row["key_domain"],
        nonce=row["nonce_b64"],
        ciphertext=row["ciphertext_b64"],
        authentication_tag=row["authentication_tag_b64"],
        blind_indexes=dict(row.get("blind_indexes") or {}),
        migration_state=row["migration_state"],
        verification_state=row["verification_state"],
    )


@router.post(
    "/{record_id}/generated-drafts/{draft_id}/finalize",
    response_model=GeneratedDraftFinalizeResponse,
)
def finalize_generated_draft_v2(
    record_id: str,
    draft_id: str,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> GeneratedDraftFinalizeResponse:
    """Clear a transient draft only after its opaque v2 record exists.

    No generated values are accepted by this endpoint. Repeating the request
    after a successful finalize is safe and cannot create a second record.
    """
    _require("write")
    if not _RECORD_ID.fullmatch(record_id):
        raise HTTPException(status_code=400, detail="record_id has invalid format")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", draft_id):
        raise HTTPException(status_code=400, detail="draft_id has invalid format")

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1 FROM vault_crypto_envelopes
             WHERE vault_id = %s AND record_domain = 'credential'
               AND record_id = %s AND crypto_version = 'client_mvk_v2'
               AND migration_state <> 'rolled_back'
               AND deleted_at IS NULL
            """,
            (principal["vault_id"], record_id),
        )
        if cur.fetchone() is None:
            raise HTTPException(
                status_code=409,
                detail="opaque v2 credential must exist before draft finalize",
            )
    finally:
        conn.close()

    current = get_draft(vault_id=str(principal["vault_id"]), draft_id=draft_id)
    if current is None:
        return GeneratedDraftFinalizeResponse(
            status="already_finalized", record_id=record_id, draft_id=draft_id,
        )
    consumed = consume_draft(
        vault_id=str(principal["vault_id"]), draft_id=draft_id,
    )
    if consumed is None:
        return GeneratedDraftFinalizeResponse(
            status="already_finalized", record_id=record_id, draft_id=draft_id,
        )
    return GeneratedDraftFinalizeResponse(
        status="finalized", record_id=record_id, draft_id=draft_id,
    )


@router.put("/{record_id}", response_model=CredentialV2EnvelopeResponse)
def write_credential_v2(
    record_id: str,
    payload: CredentialV2WriteRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> CredentialV2EnvelopeResponse:
    _require("write")
    if record_id != payload.record_id:
        raise HTTPException(status_code=400, detail="record_id mismatch")
    if payload.migration_operation_id is not None:
        _require("migration")

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        state = "migration_pending" if payload.migration_operation_id else "v2_written"
        cur.execute(
            """
            INSERT INTO vault_crypto_envelopes (
                vault_id, record_domain, record_id, crypto_version,
                cipher_suite, key_domain, nonce_b64, ciphertext_b64,
                authentication_tag_b64, blind_indexes, migration_state,
                verification_state, deleted_at
            ) VALUES (%s, 'credential', %s, 'client_mvk_v2',
                      'aes_256_gcm_v1', 'credential', %s, %s, %s, %s,
                      %s, 'not_verified', NULL)
            ON CONFLICT (vault_id, record_domain, record_id, crypto_version)
            DO UPDATE SET
                nonce_b64 = EXCLUDED.nonce_b64,
                ciphertext_b64 = EXCLUDED.ciphertext_b64,
                authentication_tag_b64 = EXCLUDED.authentication_tag_b64,
                blind_indexes = EXCLUDED.blind_indexes,
                migration_state = EXCLUDED.migration_state,
                verification_state = 'not_verified',
                migrated_at = NULL,
                deleted_at = NULL,
                updated_at = NOW()
            RETURNING *
            """,
            (
                principal["vault_id"], record_id, payload.nonce,
                payload.ciphertext, payload.authentication_tag,
                Json(payload.blind_indexes), state,
            ),
        )
        row = cur.fetchone()
        if payload.migration_operation_id is not None:
            cur.execute(
                """
                INSERT INTO vault_crypto_migration_journal (
                    operation_id, vault_id, record_domain, record_id,
                    source_version, target_version, migration_state,
                    verification_state, envelope_id, legacy_retained
                ) VALUES (%s, %s, 'credential', %s, 'legacy_v1',
                          'client_mvk_v2', 'v2_written', 'not_verified',
                          %s, TRUE)
                ON CONFLICT (vault_id, record_domain, record_id, operation_id)
                DO UPDATE SET updated_at = NOW()
                """,
                (
                    payload.migration_operation_id, principal["vault_id"],
                    record_id, row["id"],
                ),
            )
        conn.commit()
        return _response(row)
    finally:
        conn.close()


@router.get("/{record_id}", response_model=CredentialV2EnvelopeResponse)
def read_credential_v2(
    record_id: str,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> CredentialV2EnvelopeResponse:
    _require("read")
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT * FROM vault_crypto_envelopes
             WHERE vault_id = %s AND record_domain = 'credential'
               AND record_id = %s AND crypto_version = 'client_mvk_v2'
               AND migration_state <> 'rolled_back'
               AND deleted_at IS NULL
            """,
            (principal["vault_id"], record_id),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="v2 credential not found")
        return _response(row)
    finally:
        conn.close()


@router.get("", response_model=list[CredentialV2EnvelopeResponse])
def list_credentials_v2(
    blind_index_name: str | None = Query(default=None),
    blind_index_token: str | None = Query(default=None),
    principal: SessionPrincipal = Depends(verify_session_token),
) -> list[CredentialV2EnvelopeResponse]:
    _require("read")
    if (blind_index_name is None) != (blind_index_token is None):
        raise HTTPException(status_code=400, detail="both blind-index parameters are required")
    if blind_index_name is not None:
        if blind_index_name not in _INDEX_NAMES:
            raise HTTPException(status_code=400, detail="unsupported blind-index name")
        try:
            _decode_b64url(blind_index_token or "", field="blind index", expected=32)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        params: list[object] = [principal["vault_id"]]
        where = ""
        if blind_index_name is not None:
            where = " AND blind_indexes @> %s"
            params.append(Json({blind_index_name: blind_index_token}))
        cur.execute(
            """
            SELECT * FROM vault_crypto_envelopes
             WHERE vault_id = %s AND record_domain = 'credential'
               AND crypto_version = 'client_mvk_v2'
               AND migration_state <> 'rolled_back' AND deleted_at IS NULL
            """ + where + " ORDER BY created_at, record_id",
            params,
        )
        return [_response(row) for row in cur.fetchall()]
    finally:
        conn.close()


class ClientVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    semantic_equality_verified: bool


@router.post("/{record_id}/verify", response_model=dict)
def verify_credential_v2(
    record_id: str,
    payload: ClientVerificationRequest,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    _require("migration")
    conn = get_db()
    try:
        cur = conn.cursor()
        if not payload.semantic_equality_verified:
            cur.execute(
                """
                UPDATE vault_crypto_migration_journal
                   SET migration_state = 'verification_failed',
                       verification_state = 'verification_failed',
                       error_category = 'client_semantic_mismatch',
                       updated_at = NOW()
                 WHERE operation_id = %s AND vault_id = %s
                   AND record_domain = 'credential' AND record_id = %s
                   AND migration_state IN ('v2_written', 'verification_failed')
                """,
                (payload.operation_id, principal["vault_id"], record_id),
            )
            if cur.rowcount != 1:
                conn.rollback()
                raise HTTPException(
                    status_code=409, detail="migration is not verifiable"
                )
            cur.execute(
                """
                UPDATE vault_crypto_envelopes
                   SET migration_state = 'verification_failed',
                       verification_state = 'verification_failed',
                       updated_at = NOW()
                 WHERE vault_id = %s AND record_domain = 'credential'
                   AND record_id = %s AND crypto_version = 'client_mvk_v2'
                """,
                (principal["vault_id"], record_id),
            )
            conn.commit()
            return {"status": "verification_failed", "record_id": record_id}
        cur.execute(
            """
            UPDATE vault_crypto_migration_journal
               SET migration_state = 'v2_verified',
                   verification_state = 'client_verified', updated_at = NOW()
             WHERE operation_id = %s AND vault_id = %s
               AND record_domain = 'credential' AND record_id = %s
               AND migration_state IN ('v2_written', 'v2_verified')
            """,
            (payload.operation_id, principal["vault_id"], record_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=409, detail="migration is not verifiable")
        cur.execute(
            """
            UPDATE vault_crypto_envelopes
               SET migration_state = 'v2_verified',
                   verification_state = 'client_verified',
                   migrated_at = NOW(), updated_at = NOW()
             WHERE vault_id = %s AND record_domain = 'credential'
               AND record_id = %s AND crypto_version = 'client_mvk_v2'
            """,
            (principal["vault_id"], record_id),
        )
        conn.commit()
        return {"status": "v2_verified", "record_id": record_id}
    finally:
        conn.close()


@router.post("/{record_id}/rollback", response_model=dict)
def rollback_credential_v2(
    record_id: str,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    _require("migration")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_crypto_migration_journal
               SET migration_state = 'rolled_back',
                   verification_state = 'not_verified', updated_at = NOW()
             WHERE vault_id = %s AND record_domain = 'credential'
               AND record_id = %s AND legacy_retained = TRUE
               AND migration_state <> 'rolled_back'
            """,
            (principal["vault_id"], record_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="rollback requires a retained legacy migration",
            )
        cur.execute(
            """
            UPDATE vault_crypto_envelopes
               SET migration_state = 'rolled_back',
                   verification_state = 'not_verified', updated_at = NOW()
             WHERE vault_id = %s AND record_domain = 'credential'
               AND record_id = %s AND crypto_version = 'client_mvk_v2'
            """,
            (principal["vault_id"], record_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="v2 credential not found")
        conn.commit()
        return {"status": "rolled_back", "record_id": record_id}
    finally:
        conn.close()


@router.delete("/{record_id}", response_model=dict)
def delete_credential_v2(
    record_id: str,
    principal: SessionPrincipal = Depends(verify_session_token),
) -> dict:
    _require("write")
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_crypto_envelopes SET deleted_at = NOW(), updated_at = NOW()
             WHERE vault_id = %s AND record_domain = 'credential'
               AND record_id = %s AND crypto_version = 'client_mvk_v2'
               AND deleted_at IS NULL
            """,
            (principal["vault_id"], record_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            raise HTTPException(status_code=404, detail="v2 credential not found")
        conn.commit()
        return {"status": "deleted", "record_id": record_id}
    finally:
        conn.close()


__all__ = ["router"]
