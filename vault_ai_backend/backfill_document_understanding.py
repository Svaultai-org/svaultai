

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Optional

from psycopg2.extras import RealDictCursor

from document_understanding import (
    METADATA_JSON_MAX_BYTES,
    is_enabled,
    understand_document,
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
                   content_type, detected_service, extracted_text,
                   extracted_text_encrypted
            FROM uploaded_files
            WHERE user_id = %s
            """,
            (user_id,),
        )
        for row in cur.fetchall() or []:
            result = understand_document(
                file_name=row["file_name"],
                saved_name=row["saved_name"],
                asset_type=row["asset_type"],
                content_type=row["content_type"],
                detected_service=row["detected_service"],
                extracted_text=row["extracted_text"],
                extracted_text_encrypted=bool(row["extracted_text_encrypted"]),
            )
            with conn.cursor() as wcur:
                if prune:
                    wcur.execute(
                        """DELETE FROM vault_document_metadata
                           WHERE user_id=%s AND uploaded_file_id=%s""",
                        (user_id, row["id"]),
                    )
                if result:
                    payload = json.dumps(result["metadata"])
                    if len(payload.encode("utf-8")) > METADATA_JSON_MAX_BYTES:
                                                                         
                        continue
                    wcur.execute(
                        """
                        INSERT INTO vault_document_metadata
                            (user_id, vault_name, uploaded_file_id,
                             doc_type, metadata_json, confidence)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (user_id, uploaded_file_id) DO UPDATE SET
                            doc_type      = EXCLUDED.doc_type,
                            metadata_json = EXCLUDED.metadata_json,
                            confidence    = EXCLUDED.confidence,
                            vault_name    = EXCLUDED.vault_name,
                            updated_at    = NOW()
                        """,
                        (user_id, row["vault_name"], row["id"],
                         result["doc_type"], payload, result["confidence"]),
                    )
                    written += 1
            conn.commit()
    finally:
        conn.close()
    return written


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill deterministic doc-metadata for all files.",
    )
    parser.add_argument(
        "--prune", action="store_true",
        help="Delete existing metadata per visited row before reinserting.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)

    if not is_enabled():
        print("VAULTAI_DOCUMENT_UNDERSTANDING_ENABLED=false; nothing to do.")
        return 0

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
        print(f"  user={uid} docs_written={n}")
    print(f"backfill complete: {len(users)} users, {total} doc rows. "
          f"prune={args.prune}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
