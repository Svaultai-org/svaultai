from __future__ import annotations
import base64, binascii, os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg2.extras import RealDictCursor
from auth_local import SessionPrincipal
from device_gate import verify_trusted_device
from routes.auth_zk_routes import consume_recent_zk_proof
from vault_core import get_db, is_vault_zk_adopted
from legacy_source_snapshot import (
    FILE_SOURCE_FIELDS, MAX_SOURCE_CIPHERTEXT_CHARS,
    source_snapshot as legacy_source_snapshot,
)
from zk_migration_flags import ZkMigrationFlags
from subscription_entitlement import require_content_write, require_file_read

router = APIRouter()
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_CHUNK_BYTES = 1024 * 1024
MAX_CHUNKS = 4096
MAX_MANIFEST_CIPHERTEXT_BYTES = 64 * 1024
MAX_EXTRA_MANIFEST_CIPHERTEXT_BYTES = 512 * 1024
MAX_EXTRA_V3_MANIFEST_CIPHERTEXT_BYTES = 2 * 1024 * 1024
MAX_ENCRYPTED_SAVED_NAME_BYTES = 4096
# vault_key_hierarchy.aesGcmWrap emits version(1) || nonce(12) ||
# ciphertext || tag(16). The version byte is part of every client V2 chunk.
GCM_FRAMING_BYTES = 1 + 12 + 16
FORBIDDEN = ('filename','filename_plaintext','file_content','file_content_plaintext',
 'content_type_plaintext','mime_plaintext','relative_path_plaintext','extracted_text',
 'ocr_text','document_text','thumbnail_plaintext','PIN','MVK','file_key','decryption_key')

def _enabled(write=False):
    f = ZkMigrationFlags.from_environment(os.environ)
    f.validate_dependencies()
    if not (f.file_write_enabled if write else f.file_read_enabled):
        raise HTTPException(404, detail='file_v2_disabled')

def _new_files_enabled():
    return os.getenv('VAULTAI_ZK_NEW_FILE_V2_ENABLED', '').strip().lower() == 'true'

def _v2_rename_enabled():
    return os.getenv('VAULTAI_ZK_FILE_V2_RENAME_ENABLED', '').strip().lower() == 'true'

def _extra_file_stage_enabled():
    return os.getenv('VAULTAI_ZK_LEGACY_FILE_EXTRA_STAGE_ENABLED', '').strip().lower() == 'true'

def _extra_file_v3_enabled():
    return os.getenv('VAULTAI_ZK_LEGACY_FILE_EXTRA_V3_ENABLED', '').strip().lower() == 'true'

def reject_legacy_zk_file_rename(principal: SessionPrincipal) -> None:
    """Prevent plaintext/PIN rename paths from bypassing an enabled V2 path."""
    if _v2_rename_enabled() and is_vault_zk_adopted(principal['vault_id']):
        raise HTTPException(409, detail='zk_v2_rename_required')


def remove_unverified_legacy_stage_for_file_delete(
    cur, vault_id: str, file_id: str,
) -> bool:
    """Remove only an unfinished copy of the file being explicitly deleted.

    The caller holds the per-file advisory lock and commits this deletion in
    the same transaction as `uploaded_files`. A failed legacy delete must
    roll back this V2 removal too. Published/retired V2 and unmarked new-file
    uploads always require their separate confirmed delete routes.
    """
    cur.execute(
        "SELECT storage_mode = 'inline' AND encrypted_file_data IS NOT NULL "
        "AS has_legacy_inline FROM uploaded_files "
        "WHERE id = %s AND vault_id = %s FOR UPDATE",
        (file_id, vault_id),
    )
    legacy = cur.fetchone()
    cur.execute(
        "SELECT migrating_legacy, lifecycle_state, verification_state "
        "FROM file_v2_records WHERE file_id = %s AND vault_id = %s FOR UPDATE",
        (file_id, vault_id),
    )
    v2 = cur.fetchone()
    if v2 is None:
        return False
    if (not legacy or not legacy["has_legacy_inline"] or
            v2["migrating_legacy"] is not True or
            v2["lifecycle_state"] != "file_v2_written" or
            v2["verification_state"] != "not_verified"):
        raise HTTPException(
            status_code=409,
            detail="file_v2_migration_requires_confirmed_delete",
        )
    cur.execute(
        "DELETE FROM file_v2_records WHERE file_id = %s AND vault_id = %s "
        "AND migrating_legacy = TRUE "
        "AND lifecycle_state = 'file_v2_written' "
        "AND verification_state = 'not_verified' RETURNING file_id",
        (file_id, vault_id),
    )
    if cur.fetchone() is None:
        raise HTTPException(status_code=409, detail="file_v2_stage_changed")
    return True


def invalidate_unverified_legacy_stage_for_file_mutation(
    cur, vault_id: str, file_id: str,
) -> bool:
    """Discard an unfinished sidecar before changing its legacy source.

    The caller must take the per-file advisory lock first and commit this
    invalidation with the legacy metadata update. A ready or unmarked V2 file
    cannot be silently changed through an old route.
    """
    cur.execute(
        "SELECT migrating_legacy, lifecycle_state, verification_state "
        "FROM file_v2_records WHERE file_id = %s AND vault_id = %s FOR UPDATE",
        (file_id, vault_id),
    )
    state = cur.fetchone()
    if state is None:
        return False
    if isinstance(state, dict):
        migrating = state["migrating_legacy"]
        lifecycle = state["lifecycle_state"]
        verification = state["verification_state"]
    else:
        migrating, lifecycle, verification = state
    if not (migrating is True and lifecycle == "file_v2_written" and
            verification == "not_verified"):
        raise HTTPException(409, detail="file_v2_rename_requires_ready_path")
    cur.execute(
        "DELETE FROM file_v2_records WHERE file_id = %s AND vault_id = %s "
        "AND migrating_legacy = TRUE AND lifecycle_state = 'file_v2_written' "
        "AND verification_state = 'not_verified' RETURNING file_id",
        (file_id, vault_id),
    )
    if cur.fetchone() is None:
        raise HTTPException(409, detail="file_v2_stage_changed")
    return True

def _decode(v: str) -> bytes:
    try: return base64.b64decode(v + '=' * (-len(v) % 4), altchars=b'-_', validate=True)
    except (binascii.Error, ValueError) as e: raise HTTPException(400, detail='invalid_base64url') from e

class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_id: str = Field(min_length=1, max_length=128)
    crypto_version: str = Field(pattern='^client_mvk_v2$')
    manifest_ciphertext: str = Field(min_length=1, max_length=2_800_000)
    total_bytes: int = Field(ge=0, le=MAX_FILE_BYTES)
    chunk_size: int = Field(gt=0, le=MAX_CHUNK_BYTES)
    chunk_count: int = Field(ge=0, le=MAX_CHUNKS)
    migrating_legacy: bool = False
    source_snapshot: str | None = Field(default=None, min_length=43, max_length=43)
    migration_metadata_version: int = Field(default=1, ge=1, le=3)

    @model_validator(mode='after')
    def validate_framing(self):
        expected = (self.total_bytes + self.chunk_size - 1) // self.chunk_size
        if self.chunk_count != expected:
            raise ValueError('file_v2_chunk_count_mismatch')
        if self.migration_metadata_version in (2, 3) and not self.migrating_legacy:
            raise ValueError('file_v2_legacy_metadata_requires_migration')
        if self.migration_metadata_version < 3 and len(self.manifest_ciphertext) > 700_000:
            raise ValueError('file_v2_manifest_too_large')
        return self

class Chunk(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_id: str = Field(min_length=1, max_length=128)
    chunk_index: int = Field(ge=0, lt=MAX_CHUNKS)
    ciphertext: str = Field(min_length=1, max_length=1_400_000)

class ConfirmedFileDelete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    zk_proof_token: str = Field(min_length=1, max_length=128)
    confirm: bool

class EncryptedFileRename(BaseModel):
    model_config = ConfigDict(extra='forbid')
    zk_proof_token: str = Field(min_length=1, max_length=128)
    expected_name_version: int = Field(ge=0)
    saved_name_ciphertext: str = Field(min_length=1, max_length=5500)

def _reject(data: dict):
    leaked = [k for k in FORBIDDEN if k in data]
    if leaked: raise HTTPException(400, detail='file_v2_plaintext_field_rejected')

@router.post('/vault/file-v2/manifest')
def create_manifest(payload: Manifest, principal: SessionPrincipal = Depends(verify_trusted_device)):
    if payload.migration_metadata_version in (2, 3) and not _extra_file_stage_enabled():
        raise HTTPException(404, detail='file_v2_extra_stage_disabled')
    if payload.migration_metadata_version == 3 and not _extra_file_v3_enabled():
        raise HTTPException(404, detail='file_v2_extra_v3_disabled')
    require_content_write(principal)
    _enabled(True); _reject(payload.model_dump())
    if not payload.migrating_legacy and not _new_files_enabled():
        raise HTTPException(404, detail='new_file_v2_disabled')
    if payload.migrating_legacy and payload.source_snapshot is None:
        raise HTTPException(400, detail='legacy_source_snapshot_required')
    if not payload.migrating_legacy and payload.source_snapshot is not None:
        raise HTTPException(400, detail='unexpected_source_snapshot')
    ct = _decode(payload.manifest_ciphertext)
    manifest_limit = (
        MAX_EXTRA_V3_MANIFEST_CIPHERTEXT_BYTES
        if payload.migration_metadata_version == 3 else
        MAX_EXTRA_MANIFEST_CIPHERTEXT_BYTES
        if payload.migration_metadata_version == 2 else
        MAX_MANIFEST_CIPHERTEXT_BYTES
    )
    if len(ct) > manifest_limit:
        raise HTTPException(413, detail='file_v2_manifest_too_large')
    conn = get_db(); cur = conn.cursor()
    try:
        # Coordinate with the legacy deletion paths. Without this lock, a
        # manifest could be inserted after their empty V2 precheck but before
        # they delete the legacy row, leaving an unverified orphan.
        cur.execute(
            'SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))',
            (principal['vault_id'], payload.file_id),
        )
        if payload.migrating_legacy:
            cur.execute(
                'SELECT LENGTH(encrypted_file_data), '
                'OCTET_LENGTH(extracted_text), OCTET_LENGTH(relative_path) '
                'FROM uploaded_files '
                'WHERE id=%s AND vault_id=%s '
                "AND storage_mode='inline' AND encrypted_file_data IS NOT NULL "
                'FOR UPDATE',
                (payload.file_id, principal['vault_id']),
            )
            length_row = cur.fetchone()
            if length_row is None:
                conn.rollback()
                raise HTTPException(409, detail='legacy_file_source_missing')
            if int(length_row[0]) > MAX_SOURCE_CIPHERTEXT_CHARS:
                conn.rollback()
                raise HTTPException(413, detail='file_migration_streaming_required')
            if payload.migration_metadata_version == 3 and (
                length_row[1] is None or
                not 64 * 1024 < int(length_row[1]) <= 256 * 1024 or
                int(length_row[2] or 0) > 4096
            ):
                conn.rollback()
                raise HTTPException(413, detail='file_extra_v3_size_required')
            cur.execute(
                f'SELECT {", ".join(FILE_SOURCE_FIELDS)} FROM uploaded_files '
                'WHERE id=%s AND vault_id=%s '
                "AND storage_mode='inline' AND encrypted_file_data IS NOT NULL FOR UPDATE",
                (payload.file_id, principal['vault_id']),
            )
            source = cur.fetchone()
            if source is None:
                conn.rollback()
                raise HTTPException(409, detail='legacy_file_source_missing')
            source_values = dict(zip(FILE_SOURCE_FIELDS, source))
            if payload.migration_metadata_version == 3 and (
                source_values.get('extracted_text') is None or
                not 64 * 1024 < len(source_values['extracted_text'].encode('utf-8')) <= 256 * 1024 or
                len((source_values.get('relative_path') or '').encode('utf-8')) > 4096
            ):
                conn.rollback()
                raise HTTPException(413, detail='file_extra_v3_size_required')
            if legacy_source_snapshot(
                'file', source_values,
                vault_id=principal['vault_id'], record_id=payload.file_id,
            ) != payload.source_snapshot:
                conn.rollback()
                raise HTTPException(409, detail='legacy_source_changed')
        cur.execute('''INSERT INTO file_v2_records(file_id,vault_id,crypto_version,manifest_ciphertext,total_bytes,chunk_size,chunk_count,migrating_legacy,migration_metadata_version)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (file_id) DO NOTHING
                       RETURNING file_id''', (payload.file_id, principal['vault_id'], payload.crypto_version, ct, payload.total_bytes, payload.chunk_size, payload.chunk_count, payload.migrating_legacy, payload.migration_metadata_version))
        inserted = cur.fetchone()
        if inserted is None:
            # Idempotent retry is allowed only for the exact same logical
            # manifest owned by the same vault. Never let a caller claim or
            # overwrite another vault's record.
            cur.execute('''SELECT 1 FROM file_v2_records
                           WHERE file_id=%s AND vault_id=%s
                             AND crypto_version=%s AND total_bytes=%s
                             AND chunk_size=%s AND chunk_count=%s
                             AND migrating_legacy=%s
                             AND migration_metadata_version=%s
                             AND manifest_ciphertext=%s''',
                        (payload.file_id, principal['vault_id'],
                         payload.crypto_version, payload.total_bytes,
                         payload.chunk_size, payload.chunk_count,
                         payload.migrating_legacy,
                         payload.migration_metadata_version, ct))
            if cur.fetchone() is None:
                conn.rollback()
                raise HTTPException(409, detail='file_v2_manifest_conflict')
        conn.commit()
    finally: conn.close()
    return {'file_id': payload.file_id, 'crypto_version': payload.crypto_version}

@router.put('/vault/file-v2/chunk')
def put_chunk(payload: Chunk, principal: SessionPrincipal = Depends(verify_trusted_device)):
    require_content_write(principal)
    _enabled(True); _reject(payload.model_dump()); ct = _decode(payload.ciphertext)
    if len(ct) > MAX_CHUNK_BYTES + GCM_FRAMING_BYTES:
        raise HTTPException(413, detail='file_v2_chunk_too_large')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute('SELECT verification_state, lifecycle_state, chunk_size, chunk_count, total_bytes FROM file_v2_records WHERE file_id=%s AND vault_id=%s FOR UPDATE', (payload.file_id, principal['vault_id']))
        record = cur.fetchone()
        if not record: conn.rollback(); raise HTTPException(404, detail='file_v2_not_found')
        if record[0] == 'client_verified' or record[1] in ('legacy_migration_retired', 'client_v2_ready'):
            conn.rollback()
            raise HTTPException(409, detail='file_v2_verified_immutable')
        chunk_size, chunk_count, total_bytes = map(int, record[2:5])
        if payload.chunk_index >= chunk_count:
            conn.rollback(); raise HTTPException(400, detail='file_v2_chunk_index_out_of_range')
        plain_bytes = min(chunk_size, total_bytes - payload.chunk_index * chunk_size)
        if len(ct) != plain_bytes + GCM_FRAMING_BYTES:
            conn.rollback(); raise HTTPException(400, detail='file_v2_chunk_length_mismatch')
        cur.execute('''INSERT INTO file_v2_chunks(file_id,chunk_index,ciphertext) VALUES(%s,%s,%s)
                       ON CONFLICT(file_id,chunk_index) DO NOTHING
                       RETURNING chunk_index''', (payload.file_id, payload.chunk_index, ct))
        if cur.fetchone() is None:
            cur.execute('SELECT 1 FROM file_v2_chunks WHERE file_id=%s AND chunk_index=%s AND ciphertext=%s',
                        (payload.file_id, payload.chunk_index, ct))
            if cur.fetchone() is None:
                conn.rollback(); raise HTTPException(409, detail='file_v2_chunk_conflict')
        conn.commit()
    finally: conn.close()
    return {'file_id': payload.file_id, 'chunk_index': payload.chunk_index}

@router.get('/vault/file-v2')
def list_files(principal: SessionPrincipal = Depends(verify_trusted_device)):
    _enabled(False); conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Listing must be read-only. The previous best-effort stale-upload
        # deletion compared uploaded_files.vault_id (UUID) with
        # file_v2_records.vault_id (TEXT), so PostgreSQL rejected every list
        # with "operator does not exist: uuid = text". More importantly, a
        # GET must not delete an unfinished upload or a migration sidecar as
        # a side effect of opening Files.
        cur.execute('''SELECT file_id,crypto_version,total_bytes,chunk_size,chunk_count,lifecycle_state,verification_state,created_at FROM file_v2_records WHERE vault_id=%s ORDER BY created_at DESC''', (principal['vault_id'],)); return {'files':[dict(r) for r in cur.fetchall()]}
    finally: conn.close()

@router.get('/vault/file-v2/{file_id}/manifest')
def get_manifest(file_id: str, principal: SessionPrincipal = Depends(verify_trusted_device)):
    _enabled(False); conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute('''SELECT file_id,crypto_version,manifest_ciphertext,total_bytes,chunk_size,chunk_count,lifecycle_state,verification_state,saved_name_override_ciphertext,name_version,migration_metadata_version FROM file_v2_records WHERE file_id=%s AND vault_id=%s''', (file_id, principal['vault_id'])); r=cur.fetchone()
        if not r: raise HTTPException(404, detail='file_v2_not_found')
        require_file_read(principal, int(r['total_bytes']))
        r['manifest_ciphertext']=base64.urlsafe_b64encode(bytes(r['manifest_ciphertext'])).decode().rstrip('=')
        override = r['saved_name_override_ciphertext']
        r['saved_name_override_ciphertext'] = (
            base64.urlsafe_b64encode(bytes(override)).decode().rstrip('=')
            if override is not None else None
        )
        return dict(r)
    finally: conn.close()

@router.post('/vault/file-v2/{file_id}/rename')
def rename_ready_file(
    file_id: str,
    payload: EncryptedFileRename,
    principal: SessionPrincipal = Depends(verify_trusted_device),
):
    """CAS an opaque saved-name override; the immutable manifest/chunks stay put."""
    if not _v2_rename_enabled():
        raise HTTPException(404, detail='file_v2_rename_disabled')
    _enabled(True)
    require_content_write(principal)
    if not is_vault_zk_adopted(principal['vault_id']):
        raise HTTPException(409, detail='zk_vault_required')
    if not file_id or len(file_id) > 128:
        raise HTTPException(400, detail='invalid_file_id')
    name_ct = _decode(payload.saved_name_ciphertext)
    if not GCM_FRAMING_BYTES < len(name_ct) <= MAX_ENCRYPTED_SAVED_NAME_BYTES:
        raise HTTPException(400, detail='invalid_encrypted_saved_name')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute(
            'SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))',
            (principal['vault_id'], file_id),
        )
        cur.execute(
            'SELECT verification_state,lifecycle_state,name_version '
            'FROM file_v2_records WHERE file_id=%s AND vault_id=%s FOR UPDATE',
            (file_id, principal['vault_id']),
        )
        state = cur.fetchone()
        if state is None:
            raise HTTPException(404, detail='file_v2_not_found')
        if state[0] != 'client_verified' or state[1] not in (
            'legacy_migration_retired', 'client_v2_ready',
        ):
            raise HTTPException(409, detail='file_v2_not_ready')
        if int(state[2]) != payload.expected_name_version:
            raise HTTPException(409, detail='file_v2_name_version_conflict')
        cur.execute(
            'SELECT 1 FROM uploaded_files WHERE id=%s AND vault_id=%s FOR UPDATE',
            (file_id, principal['vault_id']),
        )
        if cur.fetchone() is None:
            raise HTTPException(409, detail='file_v2_marker_missing')
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            'UPDATE file_v2_records SET saved_name_override_ciphertext=%s, '
            'name_version=name_version+1 '
            'WHERE file_id=%s AND vault_id=%s AND name_version=%s '
            "AND verification_state='client_verified' "
            "AND lifecycle_state IN ('legacy_migration_retired','client_v2_ready') "
            'RETURNING name_version',
            (name_ct, file_id, principal['vault_id'], payload.expected_name_version),
        )
        updated = cur.fetchone()
        if updated is None:
            raise HTTPException(409, detail='file_v2_name_version_conflict')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    try:
        from vault_tool_result_cache import invalidate_for_event
        invalidate_for_event(vault_id=principal['vault_id'], event='file_renamed')
    except Exception:
        pass
    return {'file_id': file_id, 'name_version': int(updated[0]), 'renamed': True}

@router.get('/vault/file-v2/{file_id}/chunk/{chunk_index}')
def get_chunk(file_id: str, chunk_index: int, principal: SessionPrincipal = Depends(verify_trusted_device)):
    _enabled(False); conn=get_db(); cur=conn.cursor()
    try:
        cur.execute('''SELECT c.ciphertext,r.total_bytes FROM file_v2_chunks c JOIN file_v2_records r ON r.file_id=c.file_id WHERE c.file_id=%s AND c.chunk_index=%s AND r.vault_id=%s''',(file_id,chunk_index,principal['vault_id'])); r=cur.fetchone()
        if not r: raise HTTPException(404, detail='file_v2_chunk_not_found')
        require_file_read(principal, int(r[1]))
        return {'file_id':file_id,'chunk_index':chunk_index,'ciphertext':base64.urlsafe_b64encode(bytes(r[0])).decode().rstrip('=')}
    finally: conn.close()

@router.delete('/vault/file-v2/{file_id}')
def delete_file(file_id: str, principal: SessionPrincipal = Depends(verify_trusted_device)):
    _enabled(True); conn=get_db(); cur=conn.cursor()
    try:
        cur.execute('SELECT verification_state, lifecycle_state FROM file_v2_records WHERE file_id=%s AND vault_id=%s FOR UPDATE',(file_id,principal['vault_id']))
        record = cur.fetchone()
        if not record: conn.rollback(); raise HTTPException(404, detail='file_v2_not_found')
        if record[0] == 'client_verified' or record[1] in ('legacy_migration_retired', 'client_v2_ready'):
            conn.rollback(); raise HTTPException(409, detail='file_v2_verified_delete_requires_confirmed_path')
        cur.execute('DELETE FROM file_v2_records WHERE file_id=%s AND vault_id=%s',(file_id,principal['vault_id']));
        if cur.rowcount != 1: conn.rollback(); raise HTTPException(404, detail='file_v2_not_found')
        conn.commit(); return {'file_id':file_id,'deleted':True}
    finally: conn.close()


@router.post('/vault/file-v2/{file_id}/delete-confirm')
def delete_verified_file(
    file_id: str,
    payload: ConfirmedFileDelete,
    principal: SessionPrincipal = Depends(verify_trusted_device),
):
    """Delete a migrated V2 file only after explicit OPAQUE re-verification."""
    _enabled(True)
    require_content_write(principal)
    if not file_id or len(file_id) > 128:
        raise HTTPException(400, detail='invalid_file_id')
    if not payload.confirm:
        raise HTTPException(400, detail='file_delete_confirmation_required')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute(
            'SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))',
            (principal['vault_id'], file_id),
        )
        cur.execute(
            'SELECT verification_state, lifecycle_state FROM file_v2_records '
            'WHERE file_id=%s AND vault_id=%s FOR UPDATE',
            (file_id, principal['vault_id']),
        )
        state = cur.fetchone()
        if not state:
            raise HTTPException(404, detail='file_v2_not_found')
        if state[0] != 'client_verified' or state[1] != 'legacy_migration_retired':
            raise HTTPException(409, detail='file_v2_not_retired')
        cur.execute(
            'SELECT file_size, encrypted_file_data IS NOT NULL FROM uploaded_files '
            'WHERE id=%s AND vault_id=%s FOR UPDATE',
            (file_id, principal['vault_id']),
        )
        legacy = cur.fetchone()
        if legacy is None:
            raise HTTPException(409, detail='legacy_file_marker_missing')
        if legacy[1]:
            raise HTTPException(409, detail='legacy_file_still_present')
        consume_recent_zk_proof(payload.zk_proof_token, principal)
        cur.execute(
            'DELETE FROM file_v2_records WHERE file_id=%s AND vault_id=%s',
            (file_id, principal['vault_id']),
        )
        if cur.rowcount != 1:
            raise HTTPException(409, detail='file_v2_delete_conflict')
        cur.execute(
            'DELETE FROM uploaded_files WHERE id=%s AND vault_id=%s '
            'AND encrypted_file_data IS NULL',
            (file_id, principal['vault_id']),
        )
        if cur.rowcount != 1:
            raise HTTPException(409, detail='legacy_file_marker_changed')
        cur.execute(
            'UPDATE vaults SET total_bytes = GREATEST(total_bytes - %s, 0) '
            'WHERE vault_id = %s',
            (int(legacy[0] or 0), principal['vault_id']),
        )
        if cur.rowcount != 1:
            raise HTTPException(409, detail='vault_quota_update_conflict')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    try:
        from billing import bump_account_total_bytes, get_account_id_for_vault
        account_id = get_account_id_for_vault(principal['vault_id'])
        if account_id is not None:
            bump_account_total_bytes(account_id, -int(legacy[0] or 0))
    except Exception:
        # Vault quota was updated transactionally; account totals have their
        # existing periodic reconciliation path if this auxiliary update fails.
        pass
    # Preserve the same derived-state cleanup as the legacy delete paths.
    try:
        from vault_relationship_graph import cleanup_relationships_for_file
        cleanup_relationships_for_file(principal['vault_id'], file_id)
    except Exception:
        pass
    try:
        from vault_chat_active_entity import clear_active_entity_if_matches_file
        clear_active_entity_if_matches_file(principal['vault_id'], file_id)
    except Exception:
        pass
    try:
        from vault_tool_result_cache import invalidate_for_event
        invalidate_for_event(vault_id=principal['vault_id'], event='file_deleted')
    except Exception:
        pass
    return {'file_id': file_id, 'deleted': True}
