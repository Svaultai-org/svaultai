"""Memory V2 preparation against an explicit disposable loopback database."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from device_gate import verify_trusted_device
from auth_local import PIN_FREE_SAVED_ITEM_MUTATION_OFFER
from legacy_source_snapshot import source_snapshot
from routes import legacy_ciphertext_export_routes as export
from routes import legacy_memory_v2_copy_routes as copy
from vault_core import decrypt_message, encrypt_message


def _dsn():
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("dbname") == "svault_memory_copy_qa"
    assert dsn == os.environ["DATABASE_URL"]
    return dsn


def test_memory_copy_flag_off_before_database(monkeypatch):
    monkeypatch.delenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", raising=False)
    monkeypatch.setattr(copy, "get_db", lambda: pytest.fail("database opened"))
    with pytest.raises(HTTPException) as exc:
        copy.stage_legacy_memory_copy(
            1,
            copy.LegacyMemoryCopyStageRequest(
                source_snapshot="A" * 43,
                payload_ciphertext=base64.urlsafe_b64encode(
                    b"\x01" + b"x" * 28,
                ).decode().rstrip("="),
                zk_proof_token="synthetic-proof",
                client_verified_source=True,
            ),
            {"vault_id": str(uuid4())},
        )
    assert exc.value.status_code == 404


def test_saved_item_offer_does_not_expose_memory_export(monkeypatch):
    monkeypatch.delenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", raising=False)
    monkeypatch.delenv("VAULTAI_ZK_LEGACY_EXPORT_ENABLED", raising=False)
    monkeypatch.setattr(export, "get_db", lambda: pytest.fail("database opened"))
    with pytest.raises(HTTPException) as exc:
        export.legacy_export_page(
            export.LegacyExportPageRequest(
                export_token="synthetic", sequence=0,
                mode="list_memories",
            ),
            {"pin_free_read_offers": PIN_FREE_SAVED_ITEM_MUTATION_OFFER},
        )
    assert exc.value.status_code == 404


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_owner_copy_is_source_bound_and_keeps_legacy_active(monkeypatch):
    dsn = _dsn()
    monkeypatch.chdir(Path(__file__).parent)
    command.upgrade(Config(str(Path(__file__).with_name("alembic.ini"))), "head")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_EXPORT_ENABLED", "true")
    monkeypatch.setattr(copy, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(copy, "require_content_write", lambda _p: None)
    monkeypatch.setattr(export, "get_db", lambda: psycopg2.connect(dsn))

    def consume_proof(proof, principal, cur):
        cur.execute(
            "DELETE FROM qa_memory_proofs WHERE proof=%s AND vault_id=%s "
            "RETURNING proof",
            (proof, principal["vault_id"]),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=401, detail="invalid_proof")

    monkeypatch.setattr(copy, "consume_recent_zk_proof_on_cursor", consume_proof)
    vault_id, other_id = str(uuid4()), str(uuid4())
    principal = {"vault_id": vault_id, "device_id": "synthetic-device",
                 "token_id": str(uuid4()), "zk_registered": True}
    old_json = json.dumps({
        "schema": "vault_personal_memory_v1",
        "status": "active",
        "title": "Synthetic title",
        "value": "Synthetic private memory",
        "memory_type": "note",
    })
    legacy_key = secrets.token_bytes(32)
    old_ciphertext = encrypt_message(old_json, legacy_key).encode()
    new_ciphertext = b"\x01" + secrets.token_bytes(12 + 32 + 16)
    encoded_copy = base64.urlsafe_b64encode(new_ciphertext).decode().rstrip("=")
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS qa_memory_proofs "
                    "(proof TEXT PRIMARY KEY,vault_id UUID NOT NULL)")
        cur.execute("DELETE FROM qa_memory_proofs")
        for owner in (vault_id, other_id):
            cur.execute(
                "INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier,"
                "kdf_iterations,vault_handle,opaque_registration_record,wrapped_mvk) "
                "VALUES (%s,%s,'synthetic-salt','synthetic-verifier',600000,%s,%s,%s)",
                (owner, f"vault-{owner.replace('-', '')}",
                 secrets.token_bytes(15), secrets.token_bytes(32),
                 secrets.token_bytes(48)),
            )
        cur.execute(
            "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
            "memory_value,payload_ciphertext) VALUES(%s,'note',NULL,NULL,%s) "
            "RETURNING id", (vault_id, old_ciphertext),
        )
        memory_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
            "memory_value,payload_ciphertext) VALUES(%s,'note',NULL,NULL,%s) "
            "RETURNING id", (other_id, old_ciphertext),
        )
        other_memory_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
            "memory_value,payload_ciphertext) VALUES(%s,'note',NULL,NULL,%s)",
            (vault_id, b""),
        )
        cur.execute(
            "INSERT INTO vault_ai_memory(vault_id,memory_type,memory_key,"
            "memory_value,payload_ciphertext) VALUES(%s,'note',NULL,NULL,%s)",
            (vault_id, new_ciphertext),
        )
    with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT payload_ciphertext,memory_type,memory_record_id,"
                    "memory_lookup_hash FROM vault_ai_memory WHERE id=%s",
                    (memory_id,))
        source = cur.fetchone()
        listed = export._list_memories(cur, vault_id,
            export.LegacyExportPageRequest(
                export_token="synthetic", sequence=0, mode="list_memories",
            ))
        assert listed["records"] == [{
            "memory_id": memory_id, "memory_type": "note",
            "ciphertext_chars": len(old_ciphertext),
        }]
        opened = export._read_memory(cur, vault_id,
            export.LegacyExportPageRequest(
                export_token="synthetic", sequence=0, mode="read_memory",
                memory_id=memory_id,
            ))
        assert opened["ciphertext_chunk"] == old_ciphertext.decode()
        assert opened["source_metadata"] == {"memory_type": "note"}
    snapshot = source_snapshot("memory", source, vault_id=vault_id,
                               record_id=memory_id)
    assert opened["source_snapshot"] == snapshot
    app = FastAPI()
    app.include_router(copy.router)
    app.dependency_overrides[verify_trusted_device] = lambda: principal
    path = f"/vault/memory/legacy-copy/{memory_id}"
    body = {"source_snapshot": snapshot, "payload_ciphertext": encoded_copy,
            "zk_proof_token": "synthetic-memory-proof",
            "client_verified_source": True}
    with TestClient(app) as client:
        denied = client.post(path + "/stage", json={**body, "pin": "000000"})
        assert denied.status_code == 422
        denied = client.post(path + "/stage", json={
            **body, "source_snapshot": "X" * 43,
        })
        assert denied.status_code == 409
        assert denied.json()["detail"] == "legacy_memory_changed"
        denied = client.post(
            f"/vault/memory/legacy-copy/{other_memory_id}/stage", json=body,
        )
        assert denied.status_code == 404
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO qa_memory_proofs(proof,vault_id) VALUES(%s,%s)",
                ("synthetic-memory-proof", vault_id),
            )
        staged = client.post(path + "/stage", json=body)
        assert staged.status_code == 200, staged.text[:200]
        assert staged.json() == {"memory_id": memory_id, "prepared": True,
                                 "active_legacy_unchanged": True}
        readback = client.get(path + "/readback")
        assert readback.status_code == 200, readback.text[:200]
        assert readback.json() == {
            "memory_id": memory_id, "source_snapshot": snapshot,
            "memory_record_id": f"memory-migrated-{memory_id}",
            "memory_type": "note", "payload_ciphertext": encoded_copy,
        }
        assert readback.headers["cache-control"] == "no-store"
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload_ciphertext,memory_record_id "
                        "FROM vault_ai_memory WHERE id=%s", (memory_id,))
            active = cur.fetchone()
            assert bytes(active[0]) == old_ciphertext
            assert active[1] is None
            # A metadata-only write does not invalidate the exact source.
            cur.execute("UPDATE vault_ai_memory SET updated_at=NOW() "
                        "WHERE id=%s", (memory_id,))
        assert client.get(path + "/readback").status_code == 200
        new_json = json.dumps({
            **json.loads(old_json), "value": "Synthetic edited memory",
        })
        changed_ciphertext = encrypt_message(new_json, legacy_key).encode()
        # A rolled-back old-client write must preserve both source and copy.
        rollback_conn = psycopg2.connect(dsn)
        try:
            with rollback_conn.cursor() as cur:
                cur.execute("UPDATE vault_ai_memory SET payload_ciphertext=%s "
                            "WHERE id=%s", (changed_ciphertext, memory_id))
            rollback_conn.rollback()
        finally:
            rollback_conn.close()
        assert client.get(path + "/readback").status_code == 200
        # A committed old-client write still succeeds; only its now-stale
        # prepared copy is invalidated in the same transaction.
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("UPDATE vault_ai_memory SET payload_ciphertext=%s "
                        "WHERE id=%s", (changed_ciphertext, memory_id))
        changed = client.get(path + "/readback")
        assert changed.status_code == 404
        assert changed.json()["detail"] == "memory_copy_not_found"
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload_ciphertext FROM vault_ai_memory "
                        "WHERE id=%s", (memory_id,))
            active = bytes(cur.fetchone()[0])
            assert active == changed_ciphertext
            assert decrypt_message(active.decode(), legacy_key) == new_json
            cur.execute("SELECT COUNT(*) FROM memory_v2_prepared_copies "
                        "WHERE legacy_memory_id=%s", (memory_id,))
            assert cur.fetchone()[0] == 0
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM vaults WHERE vault_id IN (%s,%s)",
                    (vault_id, other_id))
