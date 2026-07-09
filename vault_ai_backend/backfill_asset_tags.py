

from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from psycopg2.extras import RealDictCursor

from asset_tagger import (
    classify_tags,
    _delete_tags_for_file,
    _delete_tags_for_item,
    _insert_tags_for_file,
    _insert_tags_for_item,
)
from vault_core import get_db


logger = logging.getLogger(__name__)


def _backfill_user(user_id: str, prune: bool) -> int:
    written = 0
    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute(
            """
            SELECT id, vault_name, file_name, saved_name, asset_type,
                   content_type, detected_service
            FROM uploaded_files
            WHERE user_id = %s
            """,
            (user_id,),
        )
        for row in cur.fetchall() or []:
            tags = classify_tags(
                file_name=row["file_name"],
                saved_name=row["saved_name"],
                asset_type=row["asset_type"],
                content_type=row["content_type"],
                detected_service=row["detected_service"],
            )
            with conn.cursor() as wcur:
                if prune:
                    _delete_tags_for_file(wcur, user_id, row["vault_name"], row["id"])
                if tags:
                    _insert_tags_for_file(wcur, user_id, row["vault_name"], row["id"], tags)
                    written += len(tags)
            conn.commit()

        cur.execute(
            """
            SELECT id, vault_name, service, item_type
            FROM vault_items
            WHERE user_id = %s
            """,
            (user_id,),
        )
        for row in cur.fetchall() or []:
            tags = classify_tags(service=row["service"], item_type=row["item_type"])
            with conn.cursor() as wcur:
                if prune:
                    _delete_tags_for_item(wcur, user_id, row["vault_name"], row["id"])
                if tags:
                    _insert_tags_for_item(wcur, user_id, row["vault_name"], row["id"], tags)
                    written += len(tags)
            conn.commit()
    finally:
        conn.close()
    return written


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill deterministic tags for all vault assets.",
    )
    parser.add_argument(
        "--prune", action="store_true",
        help="Delete existing tags per visited row before reinserting.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    conn = get_db()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT DISTINCT user_id FROM vault_names ORDER BY user_id;")
        users = [r["user_id"] for r in cur.fetchall() or []]
    finally:
        conn.close()

    total = 0
    for uid in users:
        n = _backfill_user(uid, prune=args.prune)
        total += n
        print(f"  user={uid} tags_written={n}")
    print(f"backfill complete: {len(users)} users, {total} tag rows. "
          f"prune={args.prune}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
