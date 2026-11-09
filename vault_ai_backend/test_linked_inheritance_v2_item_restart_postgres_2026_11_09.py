"""Destructive restart transaction against an explicit disposable PostgreSQL.

Only VAULTAI_TEST_DATABASE_URL=DATABASE_URL on loopback with the exact QA
database name runs this test. It never connects to production by default.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from routes import linked_inheritance_v2_item_import_routes as items


def _dsn() -> str:
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("dbname") == "svault_item_restart_qa"
    assert dsn == os.environ["DATABASE_URL"]
    return dsn


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_restart_sql_atomic_copy_and_owner_preservation(monkeypatch):
    dsn = _dsn()
    backend = Path(__file__).parent
    monkeypatch.chdir(backend)
    command.upgrade(Config(str(backend / "alembic.ini")), "head")
    for name in (
        "VAULTAI_ZK_LINKED_BENEFICIARY_ITEM_IMPORT_ENABLED",
        "VAULTAI_ZK_LINKED_BENEFICIARY_ITEM_RESTART_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setattr(items, "_readback_proof_enabled", lambda: None)
    monkeypatch.setattr(items, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(items, "require_content_write", lambda _p: None)
    monkeypatch.setattr(items, "enforce_export_rate_limit", lambda **_kw: None)
    monkeypatch.setattr(
        items, "consume_recent_zk_proof_on_cursor",
        lambda proof, principal, cursor: None,
    )
    monkeypatch.setattr(items, "_offer_commitment", lambda _id, _stage: "A" * 43)
    owner_id, beneficiary_id = str(uuid4()), str(uuid4())
    principal = {"vault_id": beneficiary_id}
    stage = {"stage_revision": 1}
    link_id = None
    try:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            for vault_id in (owner_id, beneficiary_id):
                cur.execute(
                    "INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier,"
                    "kdf_iterations,vault_handle,opaque_registration_record,"
                    "wrapped_mvk) VALUES (%s,%s,'qa-salt','qa-verifier',600000,"
                    "%s,%s,%s)",
                    (vault_id, f"vault-{vault_id.replace('-', '')}",
                     os.urandom(15), os.urandom(32), os.urandom(48)),
                )
            cur.execute(
                "INSERT INTO beneficiary_links(passer_vault_id,passer_label,"
                "beneficiary_vault_id,wrapped_vault_key,status) "
                "VALUES (%s,'qa',%s,'qa-wrap','linked') RETURNING id",
                (owner_id, beneficiary_id),
            )
            link_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO vault_items(vault_id,item_type,service,"
                "encrypted_data,item_type_ciphertext,service_ciphertext,"
                "payload_ciphertext) VALUES (%s,NULL,NULL,NULL,%s,%s,%s) "
                "RETURNING id",
                (owner_id, b"\x01" + b"a" * 39,
                 b"\x01" + b"b" * 39, b"\x01" + b"c" * 39),
            )
            source_id = cur.fetchone()[0]

        def context(cur, *, link_id: int, beneficiary_vault_id: str):
            cur.execute(
                "SELECT passer_vault_id,beneficiary_vault_id FROM "
                "beneficiary_links WHERE id=%s AND beneficiary_vault_id=%s "
                "FOR UPDATE",
                (link_id, beneficiary_vault_id),
            )
            link = cur.fetchone()
            assert link is not None
            return link, stage

        monkeypatch.setattr(items, "_context", context)
        exported = items.export_linked_v2_items(link_id, principal)
        source = exported["items"][0]
        payload = items.CopyLinkedV2Item(
            beneficiary_link_id=link_id,
            source_item_id=source_id,
            stage_revision=1,
            offer_commitment="A" * 43,
            source_inventory_sha256=exported["source_inventory_sha256"],
            source_row_sha256=source["source_row_sha256"],
            item_type_ciphertext=items._b64(b"\x01" + b"d" * 39),
            service_ciphertext=items._b64(b"\x01" + b"e" * 39),
            payload_ciphertext=items._b64(b"\x01" + b"f" * 39),
            title_lookup_hash=items._b64(os.urandom(32)),
            content_scope="saved_items_only",
        )
        copied = items.copy_linked_v2_item(payload, principal)
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE vault_items SET payload_ciphertext=%s WHERE id=%s",
                (b"\x01" + b"g" * 39, source_id),
            )
        preview = items.prepare_linked_v2_item_restart(link_id, principal)
        confirmation = items.ConfirmLinkedV2ItemRestart(
            beneficiary_link_id=link_id,
            restart_token=preview["restart_token"],
            stage_revision=1,
            offer_commitment="A" * 43,
            old_source_inventory_sha256=preview["old_source_inventory_sha256"],
            current_source_inventory_sha256=preview["current_source_inventory_sha256"],
            copies_sha256=preview["copies_sha256"],
            copy_count=1,
            confirmation="DELETE_UNCHANGED_INHERITED_COPIES",
            zk_proof_token="qa-one-use-proof",
        )
        outcome = items.confirm_linked_v2_item_restart(confirmation, principal)
        assert outcome["removed_unchanged_beneficiary_items"] == 1
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM vault_items WHERE id IN (%s,%s)",
                        (source_id, copied["beneficiary_item_id"]))
            assert [row["id"] for row in cur.fetchall()] == [source_id]
            cur.execute(
                "SELECT count(*) AS n FROM linked_inheritance_v2_item_copies "
                "WHERE old_link_id=%s", (link_id,),
            )
            assert cur.fetchone()["n"] == 0
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id IN (%s,%s)",
                        (owner_id, beneficiary_id))
