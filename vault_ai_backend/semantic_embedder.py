

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from typing import Optional

from vault_core import get_db


logger = logging.getLogger(__name__)


try:
    from vault_config import ai as _ai_cfg
    _a = _ai_cfg()
    EMBED_MODEL = _a.embedding_model
    EMBED_DIM = _a.embedding_dim
    MAX_INPUT_CHARS = _a.metadata_embed_cap_chars
except Exception:
    EMBED_MODEL = "text-embedding-3-small"
    EMBED_DIM = 1536
    MAX_INPUT_CHARS = 256                                                    

                                                                    
ALLOWED_FILE_KINDS = {
    "file_name", "saved_name", "asset_type", "detected_service",
    "semantic_profile",
}
ALLOWED_ITEM_KINDS = {"item_service", "item_type"}
ALLOWED_KINDS = ALLOWED_FILE_KINDS | ALLOWED_ITEM_KINDS


def build_semantic_profile_text(
    *,
    saved_name: Optional[str] = None,
    asset_type: Optional[str] = None,
    doc_type: Optional[str] = None,
    doc_family: Optional[str] = None,
    tags: Optional[list[str]] = None,
    file_name: Optional[str] = None,
) -> str:


    parts: list[str] = []
    seen: set[str] = set()

    def _add(value: Optional[str]) -> None:
        if not value:
            return
        norm = str(value).strip().lower()
        if not norm or norm in seen:
            return
        seen.add(norm)
        parts.append(norm)

    _add(saved_name)
    _add(doc_type)
    _add(asset_type)
    _add(doc_family)
    for tag in (tags or []):
        _add(tag)
    _add(file_name)
    return " ".join(parts)


def is_enabled() -> bool:
    return os.getenv("VAULTAI_SEMANTIC_SEARCH_ENABLED", "false").lower() == "true"


def content_hash(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


async def embed_text(openai_client, text: str) -> Optional[list[float]]:


    if not is_enabled() or not text:
        return None
    trimmed = text[:MAX_INPUT_CHARS]
    resp = await openai_client.embeddings.create(model=EMBED_MODEL, input=trimmed)
    return list(resp.data[0].embedding)


async def upsert_uploaded_file_inline(
    openai_client,
    conn,
    vault_id: str,
    file_id: str,
    kind: str,
    text: str,
) -> None:
    if not is_enabled() or not text or kind not in ALLOWED_FILE_KINDS:
        return
    # ZK/adopted vault: skip the server-side plaintext SHA-256
    # content_hash entirely. The unlocked client is expected to
    # compute keyed_content_hash locally (HKDF-derived semantic
    # lookup subkey the backend never sees) and POST to
    # /vault/ciphertext/semantic-index. Silent skip is the correct
    # tradeoff — if the client never finalizes, the row is simply
    # not embedded, and the readable text never touches the DB.
    try:
        from vault_core import is_vault_zk_adopted
        if is_vault_zk_adopted(vault_id):
            return
    except Exception:
        pass
    vec = await embed_text(openai_client, text)
    if vec is None:
        return
    h = content_hash(text)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO semantic_index
                (vault_id, source_kind, uploaded_file_id, embedding, content_hash)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (vault_id, source_kind, uploaded_file_id)
            WHERE uploaded_file_id IS NOT NULL
            DO UPDATE SET embedding = EXCLUDED.embedding,
                          content_hash = EXCLUDED.content_hash,
                          updated_at = NOW()
            WHERE semantic_index.content_hash <> EXCLUDED.content_hash;
            """,
            (vault_id, kind, file_id, vec, h),
        )
    conn.commit()


async def upsert_vault_item_inline(
    openai_client,
    conn,
    vault_id: str,
    item_id: int,
    kind: str,
    text: str,
) -> None:
    if not is_enabled() or not text or kind not in ALLOWED_ITEM_KINDS:
        return
    try:
        from vault_core import is_vault_zk_adopted
        if is_vault_zk_adopted(vault_id):
            return
    except Exception:
        pass
    vec = await embed_text(openai_client, text)
    if vec is None:
        return
    h = content_hash(text)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO semantic_index
                (vault_id, source_kind, vault_item_id, embedding, content_hash)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (vault_id, source_kind, vault_item_id)
            WHERE vault_item_id IS NOT NULL
            DO UPDATE SET embedding = EXCLUDED.embedding,
                          content_hash = EXCLUDED.content_hash,
                          updated_at = NOW()
            WHERE semantic_index.content_hash <> EXCLUDED.content_hash;
            """,
            (vault_id, kind, item_id, vec, h),
        )
    conn.commit()


async def _run_uploaded_file_embedding(
    openai_client, vault_id: str, file_id: str, kind: str, text: str
) -> None:
    try:
        if not is_enabled() or not text or kind not in ALLOWED_FILE_KINDS:
            return
        try:
            from vault_core import is_vault_zk_adopted
            if is_vault_zk_adopted(vault_id):
                return
        except Exception:
            pass
        vec = await embed_text(openai_client, text)
        if vec is None:
            return
        h = content_hash(text)
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO semantic_index
                        (vault_id, source_kind, uploaded_file_id, embedding, content_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (vault_id, source_kind, uploaded_file_id)
                    WHERE uploaded_file_id IS NOT NULL
                    DO UPDATE SET embedding = EXCLUDED.embedding,
                                  content_hash = EXCLUDED.content_hash,
                                  updated_at = NOW()
                    WHERE semantic_index.content_hash <> EXCLUDED.content_hash;
                    """,
                    (vault_id, kind, file_id, vec, h),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "semantic upsert (uploaded_file vault=%s file=%s kind=%s) failed: %s",
            vault_id, file_id, kind, e,
        )


async def _run_vault_item_embedding(
    openai_client, vault_id: str, item_id: int, kind: str, text: str
) -> None:
    try:
        if not is_enabled() or not text or kind not in ALLOWED_ITEM_KINDS:
            return
        try:
            from vault_core import is_vault_zk_adopted
            if is_vault_zk_adopted(vault_id):
                return
        except Exception:
            pass
        vec = await embed_text(openai_client, text)
        if vec is None:
            return
        h = content_hash(text)
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO semantic_index
                        (vault_id, source_kind, vault_item_id, embedding, content_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (vault_id, source_kind, vault_item_id)
                    WHERE vault_item_id IS NOT NULL
                    DO UPDATE SET embedding = EXCLUDED.embedding,
                                  content_hash = EXCLUDED.content_hash,
                                  updated_at = NOW()
                    WHERE semantic_index.content_hash <> EXCLUDED.content_hash;
                    """,
                    (vault_id, kind, item_id, vec, h),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(
            "semantic upsert (vault_item vault=%s item=%s kind=%s) failed: %s",
            vault_id, item_id, kind, e,
        )


def enqueue_uploaded_file_embedding(
    openai_client, vault_id: str, file_id: str, kind: str, text: Optional[str]
) -> None:


    if not is_enabled() or not text or kind not in ALLOWED_FILE_KINDS:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(
                _run_uploaded_file_embedding(openai_client, vault_id, file_id, kind, text)
            )
    except RuntimeError:
                                                                           
        pass
    except Exception as e:
        logger.warning("enqueue_uploaded_file_embedding scheduling failed: %s", e)


def enqueue_vault_item_embedding(
    openai_client, vault_id: str, item_id: int, kind: str, text: Optional[str]
) -> None:


    if not is_enabled() or not text or kind not in ALLOWED_ITEM_KINDS:
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(
                _run_vault_item_embedding(openai_client, vault_id, item_id, kind, text)
            )
    except RuntimeError:
        pass
    except Exception as e:
        logger.warning("enqueue_vault_item_embedding scheduling failed: %s", e)
