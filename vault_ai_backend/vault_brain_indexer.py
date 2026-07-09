

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


logger = logging.getLogger(__name__)


try:
    from vault_config import ai as _ai_cfg, brain as _brain_cfg
    _a = _ai_cfg()
    EMBEDDING_DIM = _a.embedding_dim
    EMBED_MODEL = _a.embedding_model
    DEFAULT_INDEXER_BATCH = _brain_cfg().indexer_batch
except Exception:
    EMBEDDING_DIM = 1536
    EMBED_MODEL = "text-embedding-3-small"
                                                                         
                                                         
    DEFAULT_INDEXER_BATCH = 8


@dataclass(frozen=True)
class IndexerReport:

    chunks_seen:    int = 0
    chunks_embedded: int = 0
    chunks_failed:  int = 0
    error:          Optional[str] = None


EmbedFn = Callable[[str], Awaitable[Optional[list[float]]]]


async def index_chunks_for_file(
    *,
    vault_id: str,
    file_id: str,
    embed_fn: EmbedFn,
    batch_limit: int = DEFAULT_INDEXER_BATCH,
    key: Optional[bytes] = None,
) -> IndexerReport:


    if not vault_id or not file_id:
        return IndexerReport(error="empty_scope")
    if key is None:
        return IndexerReport(error="no_key")

    from vault_chunk_store import StoredChunk
    from vault_core import get_db, decrypt_message

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT chunk_id, chunk_index, encrypted_chunk_text
            FROM vault_content_chunks
            WHERE vault_id = %s AND file_id = %s
              AND embedding IS NULL
            ORDER BY chunk_index ASC
            LIMIT %s
            """,
            (vault_id, file_id, int(batch_limit)),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    if not rows:
        return IndexerReport(chunks_seen=0)

    embedded = 0
    failed = 0
    for chunk_id, chunk_index, encrypted_text in rows:
        try:
            plaintext = decrypt_message(encrypted_text, key)
        except Exception:
            logger.warning(
                "[BRAIN-INDEX] decrypt failed vault=%s file=%s idx=%d",
                _short(vault_id), _short(file_id), int(chunk_index),
            )
            failed += 1
            continue
        try:
            vec = await embed_fn(plaintext)
        except Exception:
            logger.warning(
                "[BRAIN-INDEX] embed call failed vault=%s file=%s "
                "idx=%d",
                _short(vault_id), _short(file_id), int(chunk_index),
            )
            failed += 1
            continue
        if vec is None:
                                                                   
            failed += 1
            continue
        if len(vec) != EMBEDDING_DIM:
            logger.warning(
                "[BRAIN-INDEX] dim mismatch vault=%s file=%s idx=%d "
                "got=%d want=%d",
                _short(vault_id), _short(file_id),
                int(chunk_index), len(vec), EMBEDDING_DIM,
            )
            failed += 1
            continue
        if not _write_embedding(
            chunk_id=str(chunk_id),
            vault_id=vault_id,
            file_id=file_id,
            vector=vec,
        ):
            failed += 1
            continue
        embedded += 1

    return IndexerReport(
        chunks_seen=len(rows),
        chunks_embedded=embedded,
        chunks_failed=failed,
    )


def _write_embedding(
    *,
    chunk_id: str,
    vault_id: str,
    file_id: str,
    vector: list[float],
) -> bool:


    if not chunk_id or not vault_id:
        return False
    from vault_core import get_db
                                                                      
    vec_literal = "[" + ",".join(f"{x:.7f}" for x in vector) + "]"
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE vault_content_chunks
            SET embedding = %s::vector,
                embedding_model = %s,
                embedding_dim = %s,
                embedded_at = NOW(),
                updated_at = NOW()
            WHERE chunk_id::text = %s
              AND vault_id = %s
              AND file_id = %s
            """,
            (vec_literal, EMBED_MODEL, EMBEDDING_DIM,
             chunk_id, vault_id, file_id),
        )
        affected = int(cur.rowcount or 0)
        conn.commit()
        return affected == 1
    except Exception:
        conn.rollback()
        logger.warning(
            "[BRAIN-INDEX] embedding write failed vault=%s file=%s "
            "chunk=%s",
            _short(vault_id), _short(file_id), _short(chunk_id),
        )
        return False
    finally:
        conn.close()


def _short(s: str) -> str:
    if not s:
        return ""
    return s[:8] + "…" if len(s) > 8 else s


__all__ = [
    "EMBEDDING_DIM",
    "EMBED_MODEL",
    "DEFAULT_INDEXER_BATCH",
    "IndexerReport",
    "index_chunks_for_file",
]
