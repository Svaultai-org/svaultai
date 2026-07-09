

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from device_gate import verify_trusted_device
from semantic_embedder import (
    ALLOWED_KINDS,
    EMBED_DIM,
    embed_text,
    is_enabled,
    upsert_uploaded_file_inline,
    upsert_vault_item_inline,
)
from vault_core import get_db


logger = logging.getLogger(__name__)

router = APIRouter()


MAX_LIMIT = int(os.getenv("VAULTAI_SEMANTIC_MAX_LIMIT", "50"))
RATE_PER_MIN = int(os.getenv("VAULTAI_SEMANTIC_RATE_PER_MIN", "30"))
LOG_QUERIES = os.getenv("VAULTAI_SEMANTIC_LOG_QUERIES", "false").lower() == "true"
REINDEX_COOLDOWN_SEC = 300


_query_rate: "OrderedDict[str, list[float]]" = OrderedDict()
_reindex_last: dict[str, float] = {}


def _rate_limit_query(vault_id: str) -> None:
    now = time.time()
    window = [t for t in _query_rate.get(vault_id, []) if now - t < 60.0]
    if len(window) >= RATE_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail="Semantic search rate limit exceeded. Try again shortly.",
        )
    window.append(now)
    _query_rate[vault_id] = window
    if len(_query_rate) > 4096:
        _query_rate.popitem(last=False)


class SemanticQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    kinds: Optional[list[str]] = None
    limit: int = 20


class SemanticReindexRequest(BaseModel):
    kinds: Optional[list[str]] = None


def _resolve_kinds(requested: Optional[list[str]]) -> list[str]:
    if not requested:
        return sorted(ALLOWED_KINDS)
    filtered = [k for k in requested if k in ALLOWED_KINDS]
    return filtered or sorted(ALLOWED_KINDS)


@router.post("/semantic-search/query")
async def semantic_query(
    payload: SemanticQueryRequest,
    request: Request,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    if not is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Semantic search is disabled on this server.",
        )
    _rate_limit_query(vault_id)
    if LOG_QUERIES:
                                                                       
        logger.debug("semantic query vault=%s text=%r", vault_id, payload.query)

    kinds = _resolve_kinds(payload.kinds)
    limit = max(1, min(payload.limit, MAX_LIMIT))

                                                                       
    from main import client as openai_client

    try:
        vec = await embed_text(openai_client, payload.query)
    except Exception as e:
        logger.warning("semantic query embed failed: %s", e)
        raise HTTPException(status_code=502, detail="Embedding service error.")
    if vec is None:
        raise HTTPException(status_code=503, detail="Semantic search is disabled.")

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT source_kind,
                   uploaded_file_id,
                   vault_item_id,
                   1 - (embedding <=> %s::vector) AS score
            FROM semantic_index
            WHERE vault_id = %s
              AND source_kind = ANY(%s)
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (vec, vault_id, kinds, vec, limit),
        )
        rows = cur.fetchall() or []
    finally:
        conn.close()

    return {
        "results": [
            {
                "source_kind": r["source_kind"],
                "source_id": (
                    r["uploaded_file_id"]
                    if r["uploaded_file_id"] is not None
                    else r["vault_item_id"]
                ),
                "score": float(r["score"]),
            }
            for r in rows
        ]
    }


@router.post("/semantic-search/reindex")
async def semantic_reindex(
    payload: SemanticReindexRequest,
    principal=Depends(verify_trusted_device),
):


    vault_id = principal["vault_id"]
    if not is_enabled():
        raise HTTPException(
            status_code=503,
            detail="Semantic search is disabled on this server.",
        )

    now = time.time()
    last = _reindex_last.get(vault_id, 0.0)
    if now - last < REINDEX_COOLDOWN_SEC:
        wait = int(REINDEX_COOLDOWN_SEC - (now - last))
        raise HTTPException(
            status_code=429,
            detail=f"Reindex cooldown: try again in {wait}s.",
        )
    _reindex_last[vault_id] = now

    from main import client as openai_client

    kinds = set(_resolve_kinds(payload.kinds))
    file_kinds = kinds & {"file_name", "saved_name", "asset_type", "detected_service"}
    item_kinds = kinds & {"item_service", "item_type"}

    embedded = 0
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if file_kinds:
            cur.execute(
                """
                SELECT id, file_name, saved_name, asset_type, detected_service
                FROM uploaded_files
                WHERE vault_id = %s
                """,
                (vault_id,),
            )
            for row in cur.fetchall() or []:
                for kind, col in (
                    ("file_name", "file_name"),
                    ("saved_name", "saved_name"),
                    ("asset_type", "asset_type"),
                    ("detected_service", "detected_service"),
                ):
                    if kind in file_kinds and row[col]:
                        try:
                            await upsert_uploaded_file_inline(
                                openai_client, conn, vault_id, row["id"], kind, row[col]
                            )
                            embedded += 1
                        except Exception as e:
                            logger.warning(
                                "reindex file upsert failed vault=%s file=%s kind=%s: %s",
                                vault_id, row["id"], kind, e,
                            )

        if item_kinds:
            cur.execute(
                """
                SELECT id, service, item_type
                FROM vault_items
                WHERE vault_id = %s
                """,
                (vault_id,),
            )
            for row in cur.fetchall() or []:
                if "item_service" in item_kinds and row["service"]:
                    try:
                        await upsert_vault_item_inline(
                            openai_client, conn, vault_id, row["id"],
                            "item_service", row["service"],
                        )
                        embedded += 1
                    except Exception as e:
                        logger.warning(
                            "reindex item upsert (service) failed vault=%s item=%s: %s",
                            vault_id, row["id"], e,
                        )
                if "item_type" in item_kinds and row["item_type"]:
                    try:
                        await upsert_vault_item_inline(
                            openai_client, conn, vault_id, row["id"],
                            "item_type", row["item_type"],
                        )
                        embedded += 1
                    except Exception as e:
                        logger.warning(
                            "reindex item upsert (type) failed vault=%s item=%s: %s",
                            vault_id, row["id"], e,
                        )
    finally:
        conn.close()

    return {"embedded": embedded, "kinds": sorted(kinds)}
