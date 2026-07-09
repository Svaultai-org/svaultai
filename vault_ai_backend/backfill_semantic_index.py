

from __future__ import annotations

import asyncio
import logging
import os

from psycopg2.extras import RealDictCursor

from semantic_embedder import (
    is_enabled,
    upsert_uploaded_file_inline,
    upsert_vault_item_inline,
)
from vault_core import get_db


logger = logging.getLogger(__name__)


async def _backfill_user(openai_client, user_id: str) -> int:
    embedded = 0
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, file_name, saved_name, asset_type, detected_service
            FROM uploaded_files WHERE user_id = %s
            """,
            (user_id,),
        )
        for row in cur.fetchall() or []:
            for kind, col in (
                ("file_name", "file_name"),
                ("saved_name", "saved_name"),
                ("asset_type", "asset_type"),
                ("detected_service", "detected_service"),
            ):
                if row[col]:
                    try:
                        await upsert_uploaded_file_inline(
                            openai_client, conn, user_id, row["id"], kind, row[col]
                        )
                        embedded += 1
                    except Exception as e:
                        logger.warning(
                            "backfill file user=%s file=%s kind=%s: %s",
                            user_id, row["id"], kind, e,
                        )

        cur.execute(
            """
            SELECT id, service, item_type
            FROM vault_items WHERE user_id = %s
            """,
            (user_id,),
        )
        for row in cur.fetchall() or []:
            if row["service"]:
                try:
                    await upsert_vault_item_inline(
                        openai_client, conn, user_id, row["id"],
                        "item_service", row["service"],
                    )
                    embedded += 1
                except Exception as e:
                    logger.warning(
                        "backfill item.service user=%s item=%s: %s",
                        user_id, row["id"], e,
                    )
            if row["item_type"]:
                try:
                    await upsert_vault_item_inline(
                        openai_client, conn, user_id, row["id"],
                        "item_type", row["item_type"],
                    )
                    embedded += 1
                except Exception as e:
                    logger.warning(
                        "backfill item.type user=%s item=%s: %s",
                        user_id, row["id"], e,
                    )
    finally:
        conn.close()
    return embedded


async def main() -> None:
    if not is_enabled():
        print("VAULTAI_SEMANTIC_SEARCH_ENABLED=false; nothing to do.")
        return

                                                                         
    from main import client as openai_client

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT DISTINCT user_id FROM vault_names ORDER BY user_id;")
        user_ids = [r["user_id"] for r in cur.fetchall() or []]
    finally:
        conn.close()

    total = 0
    for uid in user_ids:
        n = await _backfill_user(openai_client, uid)
        total += n
        print(f"  user={uid} embedded={n}")
    print(f"backfill complete: {len(user_ids)} users, {total} rows embedded.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
