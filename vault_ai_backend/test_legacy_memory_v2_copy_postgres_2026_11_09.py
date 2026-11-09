"""Memory V2 preparation against an explicit disposable loopback database."""

from __future__ import annotations

import base64
import ast
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from starlette.requests import Request
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from device_gate import verify_trusted_device
from auth_local import PIN_FREE_SAVED_ITEM_MUTATION_OFFER
from legacy_source_snapshot import source_snapshot
from routes import legacy_ciphertext_export_routes as export
from routes import legacy_memory_v2_copy_routes as copy
from routes import auth_zk_routes as auth_zk
from routes import vault_ciphertext_write_routes as v2_memory
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


def test_active_memory_routes_flag_off_before_database(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", "true")
    monkeypatch.delenv("VAULTAI_ZK_LEGACY_MEMORY_ACTIVE_ENABLED", raising=False)
    monkeypatch.setattr(copy, "get_db", lambda: pytest.fail("database opened"))
    with pytest.raises(HTTPException) as exc:
        copy.list_active_legacy_memory_copies(
            None, principal={"vault_id": str(uuid4())},
        )
    assert exc.value.status_code == 404


def test_active_memory_header_allowed_for_browser_preflight():
    source = ast.parse(Path(__file__).with_name("main.py").read_text())
    allowed = next(node.value for node in source.body
                   if isinstance(node, ast.Assign) and any(
                       isinstance(target, ast.Name) and
                       target.id == "CORS_ALLOWED_HEADERS"
                       for target in node.targets))
    assert "X-SVaultAI-Memory-Active-Copy" in ast.literal_eval(allowed)


def test_signed_memory_offer_requires_exact_active_source_copy(monkeypatch):
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_COPY_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_ACTIVE_ENABLED", "true")
    vault_id = str(uuid4())
    row = {
        "id": 42,
        "payload_ciphertext": b"Q" * 50,
        "memory_type": "note",
        "memory_record_id": None,
        "memory_lookup_hash": None,
        "copy_record_id": "memory-migrated-42",
        "copy_type": "note",
        "copy_ciphertext": b"\x01" + b"x" * 28,
        "owner_verified_edit": False,
        "owner_verified_stage": False,
    }
    row["source_snapshot"] = source_snapshot(
        "memory", row, vault_id=vault_id, record_id=42,
    )

    class Cursor:
        def execute(self, _query, _params):
            pass

        def fetchall(self):
            return [row]

        def fetchone(self):
            return (False,)

    class Connection:
        def cursor(self, **_kwargs):
            return Cursor()

    assert auth_zk._memory_v2_offer_ready(
        Connection(), vault_id, allow_prepared=True,
    ) is False
    row["owner_verified_stage"] = True
    assert auth_zk._memory_v2_offer_ready(
        Connection(), vault_id, allow_prepared=True,
    ) is True
    # Older clients do not advertise active-copy read/edit support.
    assert auth_zk._memory_v2_offer_ready(Connection(), vault_id) is False
    row["payload_ciphertext"] = b"R" * 50
    assert auth_zk._memory_v2_offer_ready(
        Connection(), vault_id, allow_prepared=True,
    ) is False
    row["source_snapshot"] = source_snapshot(
        "memory", row, vault_id=vault_id, record_id=42,
    )
    row["copy_ciphertext"] = None
    assert auth_zk._memory_v2_offer_ready(
        Connection(), vault_id, allow_prepared=True,
    ) is False


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
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MEMORY_ACTIVE_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_EXPORT_ENABLED", "true")
    monkeypatch.setattr(copy, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(v2_memory, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(v2_memory, "_memory_v2_route_enabled", lambda *_args, **_kwargs: True)
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
            "memory_value,payload_ciphertext) VALUES(%s,'note',NULL,NULL,%s) "
            "RETURNING id",
            (vault_id, b""),
        )
        empty_id = cur.fetchone()[0]
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
        listed_copies = client.get("/vault/memory/legacy-copy/list")
        assert listed_copies.status_code == 200
        assert listed_copies.headers["cache-control"] == "no-store"
        assert listed_copies.json() == {
            "copies": [{
                "legacy_memory_id": memory_id,
                "source_snapshot": snapshot,
                "memory_record_id": f"memory-migrated-{memory_id}",
                "memory_type": "note",
                "payload_ciphertext": encoded_copy,
            }],
            "unavailable_count": 1,
            "has_more": False,
            "next_after_memory_id": empty_id,
        }
        first_page = client.get("/vault/memory/legacy-copy/list?limit=1")
        assert first_page.status_code == 200
        assert first_page.json() == {
            "copies": listed_copies.json()["copies"],
            "unavailable_count": 0,
            "has_more": True,
            "next_after_memory_id": memory_id,
        }
        second_page = client.get(
            f"/vault/memory/legacy-copy/list?limit=1&after_memory_id={memory_id}",
        )
        assert second_page.json() == {
            "copies": [], "unavailable_count": 1,
            "has_more": False, "next_after_memory_id": empty_id,
        }
        native_v2 = v2_memory.ai_memory_ciphertext_list(
            request=Request({"type": "http", "headers": [
                (b"x-svaultai-memory-active-copy", b"1"),
            ]}), http_response=Response(), memory_lookup_hash=None,
            principal=principal,
        )
        assert len(native_v2) == 1
        assert native_v2[0].payload_ciphertext == encoded_copy
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
        listed_copies = client.get("/vault/memory/legacy-copy/list")
        assert listed_copies.json() == {
            "copies": [], "unavailable_count": 2,
            "has_more": False, "next_after_memory_id": empty_id,
        }
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload_ciphertext FROM vault_ai_memory "
                        "WHERE id=%s", (memory_id,))
            active = bytes(cur.fetchone()[0])
            assert active == changed_ciphertext
            assert decrypt_message(active.decode(), legacy_key) == new_json
            cur.execute("SELECT COUNT(*) FROM memory_v2_prepared_copies "
                        "WHERE legacy_memory_id=%s", (memory_id,))
            assert cur.fetchone()[0] == 0
        # Owner re-prepares after an older writer changed the source.
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT payload_ciphertext,memory_type,memory_record_id,"
                        "memory_lookup_hash FROM vault_ai_memory WHERE id=%s",
                        (memory_id,))
            snapshot2 = source_snapshot("memory", cur.fetchone(),
                                        vault_id=vault_id, record_id=memory_id)
            cur.execute("INSERT INTO qa_memory_proofs(proof,vault_id) "
                        "VALUES(%s,%s)", ("reprepare-proof", vault_id))
        restaged = client.post(path + "/stage", json={
            **body, "source_snapshot": snapshot2,
            "zk_proof_token": "reprepare-proof",
        })
        assert restaged.status_code == 200, restaged.text[:200]
        third_json = json.dumps({
            **json.loads(new_json), "value": "Synthetic private edit",
        })
        third_legacy_ct = encrypt_message(third_json, legacy_key).encode()
        assert third_legacy_ct != changed_ciphertext
        third_v2_ct = b"\x01" + secrets.token_bytes(12 + 32 + 16)
        third_v2_encoded = base64.urlsafe_b64encode(third_v2_ct).decode().rstrip("=")
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT memory_inventory_generation FROM vaults "
                        "WHERE vault_id=%s", (vault_id,))
            edit_generation = cur.fetchone()[0]
        edit_body = {
            "source_snapshot": snapshot2, "memory_type": "note",
            "legacy_payload_ciphertext": third_legacy_ct.decode(),
            "payload_ciphertext": third_v2_encoded,
            "expected_memory_generation": str(edit_generation),
            "zk_proof_token": "edit-proof", "client_verified_source": True,
        }
        assert client.post(path + "/edit", json={**edit_body,
            "pin": "123456"}).status_code == 422
        assert client.post(path + "/edit", json={**edit_body,
            "source_snapshot": snapshot}).status_code == 409
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO qa_memory_proofs(proof,vault_id) "
                        "VALUES(%s,%s)", ("edit-proof", vault_id))
            # Another old-client write after the owner's title preflight
            # must roll back both ciphertext formats and preserve the proof.
            cur.execute("UPDATE vault_ai_memory SET updated_at=NOW() "
                        "WHERE id=%s", (empty_id,))
        stale_edit = client.post(path + "/edit", json=edit_body)
        assert stale_edit.status_code == 409
        assert stale_edit.json()["detail"] == "memory_inventory_changed"
        assert client.get(path + "/readback").json()["source_snapshot"] == snapshot2
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM qa_memory_proofs "
                        "WHERE proof='edit-proof'")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT memory_inventory_generation FROM vaults "
                        "WHERE vault_id=%s", (vault_id,))
            edit_body["expected_memory_generation"] = str(cur.fetchone()[0])
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("""CREATE OR REPLACE FUNCTION qa_reject_memory_copy_insert()
                          RETURNS trigger LANGUAGE plpgsql AS $$
                          BEGIN RAISE EXCEPTION 'synthetic_copy_failure';
                          END; $$""")
            cur.execute("""CREATE TRIGGER qa_reject_memory_copy_insert
                          BEFORE INSERT ON memory_v2_prepared_copies
                          FOR EACH ROW EXECUTE FUNCTION
                          qa_reject_memory_copy_insert()""")
        # If the replacement V2 write fails after the 0064 trigger removes
        # the previous copy, the old row, its copy, and the proof all roll back.
        try:
            with pytest.raises(Exception, match="synthetic_copy_failure"):
                client.post(path + "/edit", json=edit_body)
            assert client.get(path + "/readback").json() == {
                "memory_id": memory_id, "source_snapshot": snapshot2,
                "memory_record_id": f"memory-migrated-{memory_id}",
                "memory_type": "note", "payload_ciphertext": encoded_copy,
            }
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT payload_ciphertext FROM vault_ai_memory "
                            "WHERE id=%s", (memory_id,))
                assert bytes(cur.fetchone()[0]) == changed_ciphertext
                cur.execute("SELECT COUNT(*) FROM qa_memory_proofs "
                            "WHERE proof='edit-proof'")
                assert cur.fetchone()[0] == 1
        finally:
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("DROP TRIGGER IF EXISTS qa_reject_memory_copy_insert "
                            "ON memory_v2_prepared_copies")
                cur.execute("DROP FUNCTION IF EXISTS qa_reject_memory_copy_insert()")
        edited = client.post(path + "/edit", json=edit_body)
        assert edited.status_code == 200, edited.text[:200]
        snapshot3 = edited.json()["source_snapshot"]
        assert snapshot3 != snapshot2
        assert edited.json()["active_legacy_updated"] is True
        after_edit = client.get(path + "/readback")
        assert after_edit.status_code == 200
        assert after_edit.json()["payload_ciphertext"] == third_v2_encoded
        assert after_edit.json()["source_snapshot"] == snapshot3
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload_ciphertext,superseded_at "
                        "FROM vault_ai_memory WHERE id=%s", (memory_id,))
            old_client_row = cur.fetchone()
            assert old_client_row[1] is None
            assert decrypt_message(bytes(old_client_row[0]).decode(), legacy_key) == third_json
            cur.execute("SELECT owner_verified_edit FROM memory_v2_prepared_copies "
                        "WHERE legacy_memory_id=%s", (memory_id,))
            assert cur.fetchone()[0] is True
        # An older client may read the dual-written source, but must not
        # silently replace it and invalidate the owner's committed V2 edit.
        for statement, params in (
            ("UPDATE vault_ai_memory SET payload_ciphertext=%s WHERE id=%s",
             (changed_ciphertext, memory_id)),
            ("DELETE FROM vault_ai_memory WHERE id=%s", (memory_id,)),
        ):
            old_conn = psycopg2.connect(dsn)
            try:
                with old_conn.cursor() as cur:
                    with pytest.raises(psycopg2.errors.CheckViolation) as rejected:
                        cur.execute(statement, params)
                assert (rejected.value.diag.constraint_name ==
                        "memory_v2_verified_edit_fence")
            finally:
                old_conn.rollback()
                old_conn.close()
        assert client.get(path + "/readback").json()["payload_ciphertext"] == third_v2_encoded
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload_ciphertext FROM vault_ai_memory "
                        "WHERE id=%s", (memory_id,))
            assert bytes(cur.fetchone()[0]) == third_legacy_ct
            cur.execute("INSERT INTO qa_memory_proofs(proof,vault_id) "
                        "VALUES(%s,%s)", ("restage-after-edit", vault_id))
        reused_stage = client.post(path + "/stage", json={
            **body, "source_snapshot": snapshot3,
            "zk_proof_token": "restage-after-edit",
        })
        assert reused_stage.status_code == 200
        assert reused_stage.json()["reused_verified_copy"] is True
        assert client.get(path + "/readback").json()["payload_ciphertext"] == third_v2_encoded
        # Soft deletion hides the old-client row while retaining its bytes.
        delete_body = {"source_snapshot": snapshot3,
                       "zk_proof_token": "delete-proof",
                       "client_confirmed_delete": True}
        assert client.post(path + "/delete", json={**delete_body,
            "pin": "123456"}).status_code == 422
        assert client.post(path + "/delete", json={**delete_body,
            "client_confirmed_delete": False}).status_code == 400
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO qa_memory_proofs(proof,vault_id) "
                        "VALUES(%s,%s)", ("delete-proof", vault_id))
        deleted = client.post(path + "/delete", json=delete_body)
        assert deleted.status_code == 200, deleted.text[:200]
        assert client.get(path + "/readback").status_code == 404
        assert client.get("/vault/memory/legacy-copy/list").json() == {
            "copies": [], "unavailable_count": 1,
            "has_more": False, "next_after_memory_id": empty_id,
        }
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload_ciphertext,superseded_at "
                        "FROM vault_ai_memory WHERE id=%s", (memory_id,))
            old_client_row = cur.fetchone()
            assert bytes(old_client_row[0]) == third_legacy_ct
            assert old_client_row[1] is not None
            cur.execute("SELECT COUNT(*) FROM memory_v2_prepared_copies "
                        "WHERE legacy_memory_id=%s", (memory_id,))
            assert cur.fetchone()[0] == 0
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM vaults WHERE vault_id IN (%s,%s)",
                    (vault_id, other_id))
