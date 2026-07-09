

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredChunk:


    chunk_id: str
    vault_id: str
    file_id: str
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    extraction_source: str


def write_chunks(
    *,
    vault_id: str,
    file_id: str,
    chunks: list,
    key: bytes,
) -> int:


    if not vault_id or not file_id:
        return 0
    if not chunks:
                                                                    
                                                         
        _delete_chunks_for_file(vault_id=vault_id, file_id=file_id)
        return 0

    from vault_core import get_db, encrypt_message

    encrypted_rows: list[tuple] = []
    for c in chunks:
                                                                    
                                                                     
        encrypted = encrypt_message(c.text, key)
        encrypted_rows.append((
            vault_id,
            file_id,
            int(c.chunk_index),
            encrypted,
            int(c.char_start),
            int(c.char_end),
            str(c.extraction_source),
        ))

    conn = get_db()
    try:
        cur = conn.cursor()
                                                                
                                                  
        cur.execute(
            "DELETE FROM vault_content_chunks "
            "WHERE vault_id = %s AND file_id = %s",
            (vault_id, file_id),
        )
        cur.executemany(
            """
            INSERT INTO vault_content_chunks (
                vault_id, file_id, chunk_index,
                encrypted_chunk_text, chunk_text_encrypted,
                char_start, char_end, extraction_source
            ) VALUES (
                %s, %s, %s,
                %s, TRUE,
                %s, %s, %s
            )
            """,
            encrypted_rows,
        )
        conn.commit()
        return len(encrypted_rows)
    except Exception:
        conn.rollback()
        logger.exception(
            "[CHUNK-STORE] write failed vault=%s file=%s n=%d",
            _short(vault_id), _short(file_id), len(encrypted_rows),
        )
        return 0
    finally:
        conn.close()


def _delete_chunks_for_file(*, vault_id: str, file_id: str) -> int:

    if not vault_id or not file_id:
        return 0
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM vault_content_chunks "
            "WHERE vault_id = %s AND file_id = %s",
            (vault_id, file_id),
        )
        affected = int(cur.rowcount or 0)
        conn.commit()
        return affected
    finally:
        conn.close()


def fetch_chunks_for_file(
    *,
    vault_id: str,
    file_id: str,
    key: bytes,
) -> list[StoredChunk]:


    if not vault_id or not file_id:
        return []
    from vault_core import get_db, decrypt_message
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT chunk_id, chunk_index, encrypted_chunk_text,
                   char_start, char_end, extraction_source
            FROM vault_content_chunks
            WHERE vault_id = %s AND file_id = %s
            ORDER BY chunk_index ASC
            """,
            (vault_id, file_id),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    out: list[StoredChunk] = []
    for chunk_id, chunk_index, encrypted_text, char_start, char_end, source in rows:
        try:
            plaintext = decrypt_message(encrypted_text, key)
        except Exception:
                                                                    
                                                   
            logger.warning(
                "[CHUNK-STORE] decrypt failed vault=%s file=%s "
                "chunk_index=%d",
                _short(vault_id), _short(file_id), int(chunk_index),
            )
            continue
        out.append(StoredChunk(
            chunk_id=str(chunk_id),
            vault_id=vault_id,
            file_id=file_id,
            chunk_index=int(chunk_index),
            text=plaintext,
            char_start=int(char_start),
            char_end=int(char_end),
            extraction_source=str(source),
        ))
    return out


def fetch_chunks_by_id(
    *,
    vault_id: str,
    chunk_ids: Iterable[str],
    key: bytes,
) -> list[StoredChunk]:


    ids = [str(x) for x in chunk_ids if x]
    if not vault_id or not ids:
        return []
    from vault_core import get_db, decrypt_message
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT chunk_id, file_id, chunk_index, encrypted_chunk_text,
                   char_start, char_end, extraction_source
            FROM vault_content_chunks
            WHERE vault_id = %s AND chunk_id::text = ANY(%s)
            """,
            (vault_id, ids),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()
    out: list[StoredChunk] = []
    for chunk_id, file_id, chunk_index, encrypted_text, char_start, char_end, source in rows:
        try:
            plaintext = decrypt_message(encrypted_text, key)
        except Exception:
            logger.warning(
                "[CHUNK-STORE] decrypt failed vault=%s file=%s "
                "chunk_index=%d",
                _short(vault_id), _short(str(file_id)), int(chunk_index),
            )
            continue
        out.append(StoredChunk(
            chunk_id=str(chunk_id),
            vault_id=vault_id,
            file_id=str(file_id),
            chunk_index=int(chunk_index),
            text=plaintext,
            char_start=int(char_start),
            char_end=int(char_end),
            extraction_source=str(source),
        ))
    return out


def file_has_chunks(*, vault_id: str, file_id: str) -> bool:


    if not vault_id or not file_id:
        return False
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM vault_content_chunks "
            "WHERE vault_id = %s AND file_id = %s "
            "LIMIT 1",
            (vault_id, file_id),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def count_chunks_for_vault(vault_id: str) -> dict:


    if not vault_id:
        return {"total": 0, "embedded": 0, "unembedded": 0}
    from vault_core import get_db
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE embedding IS NOT NULL) AS embedded
            FROM vault_content_chunks
            WHERE vault_id = %s
            """,
            (vault_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    total = int(row[0] or 0)
    embedded = int(row[1] or 0)
    return {
        "total":      total,
        "embedded":   embedded,
        "unembedded": total - embedded,
    }


def _short(s: str) -> str:


    if not s:
        return ""
    return s[:8] + "…" if len(s) > 8 else s


__all__ = [
    "StoredChunk",
    "write_chunks",
    "fetch_chunks_for_file",
    "fetch_chunks_by_id",
    "file_has_chunks",
    "count_chunks_for_vault",
]
