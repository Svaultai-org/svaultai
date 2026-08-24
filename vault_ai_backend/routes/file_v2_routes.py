from __future__ import annotations
import base64, binascii, os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg2.extras import RealDictCursor
from auth_local import SessionPrincipal, verify_session_token
from vault_core import get_db
from zk_migration_flags import ZkMigrationFlags
from subscription_entitlement import require_content_write, require_file_read

router = APIRouter()
FORBIDDEN = ('filename','filename_plaintext','file_content','file_content_plaintext',
 'content_type_plaintext','mime_plaintext','relative_path_plaintext','extracted_text',
 'ocr_text','document_text','thumbnail_plaintext','PIN','MVK','file_key','decryption_key')

def _enabled(write=False):
    f = ZkMigrationFlags.from_environment(os.environ)
    f.validate_dependencies()
    if not (f.file_write_enabled if write else f.file_read_enabled):
        raise HTTPException(404, detail='file_v2_disabled')

def _decode(v: str) -> bytes:
    try: return base64.urlsafe_b64decode(v + '=' * (-len(v) % 4))
    except (binascii.Error, ValueError) as e: raise HTTPException(400, detail='invalid_base64url') from e

class Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_id: str = Field(min_length=1, max_length=128)
    crypto_version: str = Field(pattern='^client_mvk_v2$')
    manifest_ciphertext: str = Field(min_length=1)
    total_bytes: int = Field(ge=0)
    chunk_size: int = Field(gt=0)
    chunk_count: int = Field(ge=0)

class Chunk(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_id: str
    chunk_index: int = Field(ge=0)
    ciphertext: str = Field(min_length=1)

def _reject(data: dict):
    leaked = [k for k in FORBIDDEN if k in data]
    if leaked: raise HTTPException(400, detail='file_v2_plaintext_field_rejected')

@router.post('/vault/file-v2/manifest')
def create_manifest(payload: Manifest, principal: SessionPrincipal = Depends(verify_session_token)):
    require_content_write(principal)
    _enabled(True); _reject(payload.model_dump())
    ct = _decode(payload.manifest_ciphertext)
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute('''INSERT INTO file_v2_records(file_id,vault_id,crypto_version,manifest_ciphertext,total_bytes,chunk_size,chunk_count)
                       VALUES(%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (file_id) DO NOTHING
                       RETURNING file_id''', (payload.file_id, principal['vault_id'], payload.crypto_version, ct, payload.total_bytes, payload.chunk_size, payload.chunk_count))
        inserted = cur.fetchone()
        if inserted is None:
            # Idempotent retry is allowed only for the exact same logical
            # manifest owned by the same vault. Never let a caller claim or
            # overwrite another vault's record.
            cur.execute('''SELECT 1 FROM file_v2_records
                           WHERE file_id=%s AND vault_id=%s
                             AND crypto_version=%s AND total_bytes=%s
                             AND chunk_size=%s AND chunk_count=%s''',
                        (payload.file_id, principal['vault_id'],
                         payload.crypto_version, payload.total_bytes,
                         payload.chunk_size, payload.chunk_count))
            if cur.fetchone() is None:
                conn.rollback()
                raise HTTPException(409, detail='file_v2_manifest_conflict')
        conn.commit()
    finally: conn.close()
    return {'file_id': payload.file_id, 'crypto_version': payload.crypto_version}

@router.put('/vault/file-v2/chunk')
def put_chunk(payload: Chunk, principal: SessionPrincipal = Depends(verify_session_token)):
    require_content_write(principal)
    _enabled(True); _reject(payload.model_dump()); ct = _decode(payload.ciphertext)
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute('SELECT 1 FROM file_v2_records WHERE file_id=%s AND vault_id=%s', (payload.file_id, principal['vault_id']))
        if not cur.fetchone(): raise HTTPException(404, detail='file_v2_not_found')
        cur.execute('''INSERT INTO file_v2_chunks(file_id,chunk_index,ciphertext) VALUES(%s,%s,%s)
                       ON CONFLICT(file_id,chunk_index) DO UPDATE SET ciphertext=EXCLUDED.ciphertext''', (payload.file_id, payload.chunk_index, ct)); conn.commit()
    finally: conn.close()
    return {'file_id': payload.file_id, 'chunk_index': payload.chunk_index}

@router.get('/vault/file-v2')
def list_files(principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled(False); conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # A tab/process can disappear without running the client's abort path.
        # Reap only stale, incomplete manifests; never touch a recent upload or
        # a record whose declared chunks are all present.
        cur.execute('''DELETE FROM file_v2_records r
                       WHERE r.vault_id=%s
                         AND r.created_at < NOW() - INTERVAL '30 minutes'
                         AND (SELECT COUNT(*) FROM file_v2_chunks c
                              WHERE c.file_id=r.file_id) < r.chunk_count''',
                    (principal['vault_id'],))
        conn.commit()
        cur.execute('''SELECT file_id,crypto_version,total_bytes,chunk_size,chunk_count,lifecycle_state,verification_state,created_at FROM file_v2_records WHERE vault_id=%s ORDER BY created_at DESC''', (principal['vault_id'],)); return {'files':[dict(r) for r in cur.fetchall()]}
    finally: conn.close()

@router.get('/vault/file-v2/{file_id}/manifest')
def get_manifest(file_id: str, principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled(False); conn = get_db(); cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute('''SELECT file_id,crypto_version,manifest_ciphertext,total_bytes,chunk_size,chunk_count,lifecycle_state,verification_state FROM file_v2_records WHERE file_id=%s AND vault_id=%s''', (file_id, principal['vault_id'])); r=cur.fetchone()
        if not r: raise HTTPException(404, detail='file_v2_not_found')
        require_file_read(principal, int(r['total_bytes']))
        r['manifest_ciphertext']=base64.urlsafe_b64encode(bytes(r['manifest_ciphertext'])).decode().rstrip('='); return dict(r)
    finally: conn.close()

@router.get('/vault/file-v2/{file_id}/chunk/{chunk_index}')
def get_chunk(file_id: str, chunk_index: int, principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled(False); conn=get_db(); cur=conn.cursor()
    try:
        cur.execute('''SELECT c.ciphertext,r.total_bytes FROM file_v2_chunks c JOIN file_v2_records r ON r.file_id=c.file_id WHERE c.file_id=%s AND c.chunk_index=%s AND r.vault_id=%s''',(file_id,chunk_index,principal['vault_id'])); r=cur.fetchone()
        if not r: raise HTTPException(404, detail='file_v2_chunk_not_found')
        require_file_read(principal, int(r[1]))
        return {'file_id':file_id,'chunk_index':chunk_index,'ciphertext':base64.urlsafe_b64encode(bytes(r[0])).decode().rstrip('=')}
    finally: conn.close()

@router.delete('/vault/file-v2/{file_id}')
def delete_file(file_id: str, principal: SessionPrincipal = Depends(verify_session_token)):
    _enabled(True); conn=get_db(); cur=conn.cursor()
    try:
        cur.execute('DELETE FROM file_v2_records WHERE file_id=%s AND vault_id=%s',(file_id,principal['vault_id']));
        if cur.rowcount != 1: conn.rollback(); raise HTTPException(404, detail='file_v2_not_found')
        conn.commit(); return {'file_id':file_id,'deleted':True}
    finally: conn.close()
