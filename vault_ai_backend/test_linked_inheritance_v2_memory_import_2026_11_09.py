"""Synthetic old-link Memory copy checks on a dedicated loopback database."""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException, Response
from pydantic import ValidationError
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from legacy_source_snapshot import source_snapshot
from routes import linked_inheritance_v2_memory_import_routes as memories


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_memory_import_is_off_and_rejects_plaintext_fields(monkeypatch):
    monkeypatch.delenv(memories.FLAG_NAME, raising=False)
    monkeypatch.setattr(memories, "get_db", lambda: pytest.fail("database opened"))
    with pytest.raises(HTTPException) as denied:
        memories.export_linked_v2_memories(1, Response(), {"vault_id": str(uuid4())})
    assert denied.value.status_code == 404
    body = {
        "beneficiary_link_id": 1,
        "source_memory_id": 2,
        "stage_revision": 1,
        "offer_commitment": "A" * 43,
        "source_inventory_sha256": "B" * 43,
        "source_row_sha256": "C" * 43,
        "beneficiary_memory_record_id": "inherited-1-2",
        "memory_type": "note",
        "memory_lookup_hash": "D" * 43,
        "payload_ciphertext": "E" * 40,
        "content_scope": "memory_only",
        "zk_proof_token": "synthetic-proof",
    }
    for forbidden in ("pin", "memory_value", "owner_mvk"):
        with pytest.raises(ValidationError):
            memories.CopyLinkedV2Memory.model_validate({
                **body, forbidden: "synthetic secret",
            })


def test_memory_context_requires_release_and_prior_readback_receipt(monkeypatch):
    link = {"passer_vault_id": str(uuid4()),
            "beneficiary_vault_id": str(uuid4())}
    monkeypatch.setattr(
        memories, "_load_releasable_old_link",
        lambda *_args, **_kwargs: (link, {}, "approved"),
    )
    with pytest.raises(HTTPException) as unreleased:
        memories._context(None, link_id=41,
                          beneficiary_vault_id=link["beneficiary_vault_id"])
    assert unreleased.value.detail == "release_not_complete"
    monkeypatch.setattr(
        memories, "_load_releasable_old_link",
        lambda *_args, **_kwargs: (link, {}, "released"),
    )
    monkeypatch.setattr(memories, "_offer_commitment", lambda *_args: "A" * 43)
    monkeypatch.setattr(
        memories, "_verified_release_stage",
        lambda *_args, **_kwargs: {
            "stage_revision": 2,
            "owner_readback_public_key": b"p" * 32,
            "owner_readback_revision": 2,
            "owner_readback_commitment": "A" * 43,
            "beneficiary_readback_revision": None,
            "beneficiary_readback_at": None,
        },
    )
    with pytest.raises(HTTPException) as unproven:
        memories._context(None, link_id=41,
                          beneficiary_vault_id=link["beneficiary_vault_id"])
    assert unproven.value.detail == "readback_receipt_required"


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_source_bound_memory_copy_preserves_owner_and_requires_fence(monkeypatch):
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("port") == "55432"
    assert parsed.get("dbname") == "svault_inheritance_memory_qa"
    assert dsn == os.environ["DATABASE_URL"]
    monkeypatch.chdir(Path(__file__).parent)
    command.upgrade(Config(str(Path(__file__).with_name("alembic.ini"))), "head")
    monkeypatch.setenv(memories.FLAG_NAME, "true")
    monkeypatch.setattr(memories, "_readback_proof_enabled", lambda: None)
    monkeypatch.setattr(memories, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(memories, "require_content_write", lambda _p: None)
    monkeypatch.setattr(memories, "enforce_export_rate_limit", lambda **_kw: None)
    consumed = []
    monkeypatch.setattr(
        memories, "consume_recent_zk_proof_on_cursor",
        lambda proof, _principal, _cur: consumed.append(proof),
    )
    monkeypatch.setattr(memories, "_offer_commitment", lambda *_args: "A" * 43)
    owner_id = str(uuid4())
    beneficiary_id = str(uuid4())
    principal = {"vault_id": beneficiary_id}
    owner_source = b"\x01" + secrets.token_bytes(48)
    destination = b"\x01" + secrets.token_bytes(48)
    link_id = None
    memory_id = None
    try:
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            for vault_id in (owner_id, beneficiary_id):
                cur.execute(
                    "INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier,"
                    "kdf_iterations,vault_handle,opaque_registration_record,wrapped_mvk) "
                    "VALUES (%s,%s,'synthetic-salt','synthetic-verifier',600000,%s,%s,%s)",
                    (vault_id, f"vault-{vault_id.replace('-', '')}",
                     secrets.token_bytes(15), secrets.token_bytes(32),
                     secrets.token_bytes(48)),
                )
            cur.execute(
                "INSERT INTO beneficiary_links(passer_vault_id,beneficiary_vault_id,"
                "wrapped_vault_key,status,pairing_state) "
                "VALUES (%s,%s,'synthetic-wrapped','linked','released') RETURNING id",
                (owner_id, beneficiary_id),
            )
            link_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
                "memory_value,memory_record_id,memory_lookup_hash,payload_ciphertext) "
                "VALUES (%s,'note',NULL,NULL,'owner-synthetic-memory',%s,%s) "
                "RETURNING id",
                (owner_id, secrets.token_bytes(32), owner_source),
            )
            memory_id = cur.fetchone()["id"]
        monkeypatch.setattr(
            memories, "_context",
            lambda _cur, **_kw: (
                {"passer_vault_id": owner_id,
                 "beneficiary_vault_id": beneficiary_id},
                {"stage_revision": 2},
            ),
        )
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
                "memory_value,payload_ciphertext) "
                "VALUES (%s,'note',NULL,NULL,%s) RETURNING id",
                (owner_id, b"Q" * 40),
            )
            unverified_id = cur.fetchone()["id"]
            cur.execute(
                "SELECT id,payload_ciphertext,memory_type,memory_record_id,"
                "memory_lookup_hash FROM vault_ai_memory WHERE id=%s",
                (unverified_id,),
            )
            snapshot = source_snapshot(
                "memory", cur.fetchone(), vault_id=owner_id,
                record_id=unverified_id,
            )
            cur.execute(
                "INSERT INTO memory_v2_prepared_copies(legacy_memory_id,"
                "vault_id,source_snapshot,memory_record_id,memory_type,"
                "payload_ciphertext) VALUES(%s,%s,%s,%s,'note',%s)",
                (unverified_id, owner_id, snapshot,
                 f"memory-migrated-{unverified_id}",
                 b"\x01" + secrets.token_bytes(48)),
            )
        with pytest.raises(HTTPException) as unverified:
            memories.export_linked_v2_memories(link_id, Response(), principal)
        assert unverified.value.detail == "owner_memory_copy_unverified"
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vault_ai_memory WHERE id=%s",
                        (unverified_id,))
        exported = memories.export_linked_v2_memories(link_id, Response(), principal)
        assert exported["memory_count"] == 1
        assert exported["memories"][0]["payload_ciphertext"] == _b64(owner_source)
        assert "memory_value" not in exported["memories"][0]
        payload = memories.CopyLinkedV2Memory(
            beneficiary_link_id=link_id,
            source_memory_id=memory_id,
            stage_revision=2,
            offer_commitment="A" * 43,
            source_inventory_sha256=exported["source_inventory_sha256"],
            source_row_sha256=exported["memories"][0]["source_row_sha256"],
            beneficiary_memory_record_id=f"inherited-{link_id}-{memory_id}",
            memory_type="note",
            memory_lookup_hash=_b64(secrets.token_bytes(32)),
            payload_ciphertext=_b64(destination),
            content_scope="memory_only",
            zk_proof_token="synthetic-opaque-proof",
        )
        with pytest.raises(HTTPException) as unfenced:
            memories.copy_linked_v2_memory(payload, principal)
        assert unfenced.value.detail == "beneficiary_memory_fence_required"
        assert consumed == []
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE vaults SET memory_mixed_title_fence_enabled=TRUE "
                "WHERE vault_id=%s", (beneficiary_id,),
            )
            # An older writer can still create a Memory before the first V2
            # record. The copy must re-check after its own insert trigger has
            # acquired the vault lock, and roll back rather than mixing titles.
            cur.execute(
                "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
                "memory_value,payload_ciphertext) "
                "VALUES (%s,'note',NULL,NULL,%s) RETURNING id",
                (beneficiary_id, b"L" * 40),
            )
            older_recipient_id = cur.fetchone()[0]
        with pytest.raises(HTTPException) as mixed:
            memories.copy_linked_v2_memory(payload, principal)
        assert mixed.value.detail == "beneficiary_memory_not_private_ready"
        # The real proof consumption is in the rolled-back transaction; this
        # list mock has no rollback and records the attempted call separately.
        assert consumed == ["synthetic-opaque-proof"]
        consumed.clear()
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM linked_inheritance_v2_memory_copies "
                "WHERE old_link_id=%s", (link_id,),
            )
            assert cur.fetchone()[0] == 0
            cur.execute("DELETE FROM vault_ai_memory WHERE id=%s",
                        (older_recipient_id,))
        written = memories.copy_linked_v2_memory(payload, principal)
        assert written["created"] is True
        assert consumed == ["synthetic-opaque-proof"]
        readback = memories.readback_linked_v2_memory_copies(
            link_id, Response(), exported["source_inventory_sha256"], principal,
        )
        assert readback["all_memories_copied"] is True
        assert readback["copies"][0]["payload_ciphertext"] == _b64(destination)
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT payload_ciphertext,memory_record_id FROM vault_ai_memory "
                "WHERE id=%s", (memory_id,),
            )
            owner = cur.fetchone()
            assert bytes(owner["payload_ciphertext"]) == owner_source
            assert owner["memory_record_id"] == "owner-synthetic-memory"
            cur.execute(
                "SELECT COUNT(*) AS n FROM linked_inheritance_v2_memory_copies "
                "WHERE old_link_id=%s", (link_id,),
            )
            assert cur.fetchone()["n"] == 1
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE vault_ai_memory SET payload_ciphertext=%s WHERE id=%s",
                (b"\x01" + secrets.token_bytes(48),
                 written["beneficiary_memory_id"]),
            )
        with pytest.raises(HTTPException) as changed:
            memories.readback_linked_v2_memory_copies(
                link_id, Response(), exported["source_inventory_sha256"],
                principal,
            )
        assert changed.value.detail == "memory_copy_mismatch"
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id IN (%s,%s)",
                        (owner_id, beneficiary_id))
