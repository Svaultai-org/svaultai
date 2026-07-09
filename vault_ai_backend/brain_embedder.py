

from __future__ import annotations

import logging
from typing import Optional


logger = logging.getLogger(__name__)


try:
    from vault_config import ai as _ai_cfg
    _a = _ai_cfg()
    EMBED_MODEL = _a.embedding_model
    EMBED_DIM = _a.embedding_dim
    MAX_INPUT_CHARS = _a.brain_query_embed_cap_chars
except Exception:
    EMBED_MODEL = "text-embedding-3-small"
    EMBED_DIM = 1536
                                                                           
                                                                          
    MAX_INPUT_CHARS = 8000


async def embed_for_brain(
    openai_client,
    text: str,
) -> Optional[list[float]]:


    if openai_client is None:
        return None
    if not text or not str(text).strip():
        return None
    payload = str(text)[:MAX_INPUT_CHARS]
    try:
        resp = await openai_client.embeddings.create(
            model=EMBED_MODEL,
            input=payload,
        )
    except Exception as exc:
                                                                   
        logger.warning(
            "[brain-embedder] embed call raised len=%d cls=%s",
            len(payload), type(exc).__name__,
        )
        raise
    vec = list(resp.data[0].embedding)
    if len(vec) != EMBED_DIM:
        logger.warning(
            "[brain-embedder] dim mismatch got=%d want=%d",
            len(vec), EMBED_DIM,
        )
        return None
    return vec


def make_query_embed_fn(openai_client):


    async def _embed(text: str) -> Optional[list[float]]:
        return await embed_for_brain(openai_client, text)
    return _embed


__all__ = [
    "EMBED_MODEL",
    "EMBED_DIM",
    "MAX_INPUT_CHARS",
    "embed_for_brain",
    "make_query_embed_fn",
]
