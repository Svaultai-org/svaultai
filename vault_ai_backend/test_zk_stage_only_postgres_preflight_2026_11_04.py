"""Opt-in disposable PostgreSQL preflight for the stage-only rollout.

Run only against a loopback database whose name contains ``stage_full_qa``.
The caller applies migrations through 0053 before running this test.
No production credentials, PINs, content, or external services are used.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import uuid

import psycopg2
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from device_gate import verify_trusted_device
from routes import (
    file_v2_routes,
    legacy_ciphertext_export_routes as export_routes,
    legacy_ciphertext_migration_routes as migration_routes,
    login_routes,
    vault_manage_routes,
)
from vault_core import (
    PIN_VERIFIER_PLAINTEXT,
    decrypt_bytes,
    decrypt_message,
    derive_key,
    encrypt_bytes,
    encrypt_message,
    generate_pin_salt,
)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _encrypted(key: bytes, raw: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, raw, None)


def _assert_reply(reply, status=200):
    assert reply.status_code == status, (reply.status_code, reply.text[:500])
    return reply.json()


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires an explicitly configured disposable loopback PostgreSQL DB",
)
def test_stage_only_full_postgres_and_legacy_compatibility(monkeypatch):
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    assert dsn == os.environ["DATABASE_URL"]
    assert "127.0.0.1" in dsn and "stage_full_qa" in dsn

    monkeypatch.setenv("VAULTAI_ZK_LEGACY_EXPORT_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_ITEM_RETIRE_ENABLED", "false")
    monkeypatch.setenv("VAULTAI_ZK_LEGACY_FILE_RETIRE_ENABLED", "false")
    monkeypatch.setenv("FILE_V2_READ_ENABLED", "true")
    monkeypatch.setenv("FILE_V2_WRITE_ENABLED", "true")
    monkeypatch.setenv("VAULTAI_ZK_NEW_FILE_V2_ENABLED", "false")
    monkeypatch.setenv("VAULTAI_ZK_FILE_V2_RENAME_ENABLED", "false")
    monkeypatch.setenv("VAULTAI_ZK_RAW_PIN_CONTENT_DISABLED", "false")

    vault_id = str(uuid.uuid4())
    token_id = str(uuid.uuid4())
    file_id = f"synthetic-stage-{uuid.uuid4().hex}"
    pin = "123456"  # Synthetic only; never a real account credential.
    salt = generate_pin_salt()
    key = derive_key(pin, salt, iterations=100_000)
    mvk = secrets.token_bytes(32)
    item_value = {"category": "login", "title": "Synthetic Site", "fields": {"username": "synthetic"}}
    file_value = b"synthetic legacy file bytes for stage-only QA"
    principal = {"vault_id": vault_id, "token_id": token_id,
                 "vault_name": "synthetic", "device_id": "synthetic-device"}

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            assert cur.fetchone()[0] == "0053_file_v2_legacy_stage_marker"
            cur.execute("DROP TRIGGER IF EXISTS synthetic_stage_rename_fail ON uploaded_files")
            cur.execute("DROP FUNCTION IF EXISTS synthetic_stage_rename_fail()")
            cur.execute(
                """INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier,
                       kdf_iterations,vault_handle,opaque_registration_record,wrapped_mvk)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (vault_id, f"vault-{vault_id.replace('-', '')}", salt,
                 encrypt_message(PIN_VERIFIER_PLAINTEXT, key), 100_000,
                 secrets.token_bytes(15), secrets.token_bytes(32),
                 secrets.token_bytes(48)),
            )
            cur.execute(
                """INSERT INTO vault_items(vault_id,item_type,service,encrypted_data)
                   VALUES (%s,%s,%s,%s) RETURNING id""",
                (vault_id, "login", "Synthetic Site", encrypt_message(json.dumps(item_value), key)),
            )
            item_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO uploaded_files(id,vault_id,file_name,saved_name,
                       content_type,file_size,encrypted_file_data,storage_mode,upload_status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,'inline','complete')""",
                (file_id, vault_id, "synthetic.txt", "Original name", "text/plain",
                 len(file_value), encrypt_bytes(file_value, key)),
            )

    app = FastAPI()
    for router in (export_routes.router, migration_routes.router,
                   file_v2_routes.router, login_routes.router,
                   vault_manage_routes.router):
        app.include_router(router)
    app.dependency_overrides[verify_trusted_device] = lambda: principal
    consumed_proofs = set()

    def consume(proof, subject):
        assert subject["vault_id"] == vault_id
        if proof in consumed_proofs or not proof.startswith("synthetic-proof-"):
            raise HTTPException(401, detail="invalid_recent_proof")
        consumed_proofs.add(proof)

    monkeypatch.setattr(export_routes, "consume_recent_zk_proof", consume)
    monkeypatch.setattr(migration_routes, "consume_recent_zk_proof", consume)

    with TestClient(app, raise_server_exceptions=False) as client:
        proof_counter = 0

        def start_export():
            nonlocal proof_counter
            proof_counter += 1
            result = _assert_reply(client.post(
                "/vault/legacy-ciphertext/export/start",
                json={"zk_proof_token": f"synthetic-proof-{proof_counter}"},
            ))
            return result["export_token"], result["next_sequence"]

        token, sequence = start_export()

        def page(mode, **kwargs):
            nonlocal sequence, token
            result = _assert_reply(client.post(
                "/vault/legacy-ciphertext/export/page",
                json={"export_token": token, "sequence": sequence,
                      "mode": mode, **kwargs},
            ))
            sequence = result["next_sequence"]
            return result

        listed_items = page("list_items")["records"]
        listed_files = page("list_files")["records"]
        assert [row["item_id"] for row in listed_items] == [item_id]
        assert [row["file_id"] for row in listed_files] == [file_id]
        source_item = page("read_item", item_id=item_id)
        source_file = page("read_file", file_id=file_id)
        assert source_item["done"] and source_file["done"]
        assert decrypt_message(source_item["ciphertext_chunk"], key) == json.dumps(item_value)
        assert decrypt_bytes(source_file["ciphertext_chunk"], key) == file_value

        item_ct = tuple(_encrypted(mvk, raw) for raw in (
            b"login", b"Synthetic Site", json.dumps(item_value).encode(),
        ))
        staged_item = _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/item-stage",
            json={"item_id": item_id, "item_type_ciphertext": _b64(item_ct[0]),
                  "service_ciphertext": _b64(item_ct[1]),
                  "payload_ciphertext": _b64(item_ct[2]),
                  "source_snapshot": source_item["source_snapshot"]},
        ))
        item_readback = _assert_reply(client.get(
            f"/vault/legacy-ciphertext/migrate/item-staged/{item_id}",
        ))
        assert item_readback["source_snapshot"] == staged_item["source_snapshot"]
        assert tuple(base64.urlsafe_b64decode(item_readback[name] + "==")
                     for name in ("item_type_ciphertext", "service_ciphertext",
                                  "payload_ciphertext")) == item_ct
        assert AESGCM(mvk).decrypt(item_ct[2][:12], item_ct[2][12:], None) == json.dumps(item_value).encode()

        file_chunk = _encrypted(mvk, file_value)
        manifest = _encrypted(mvk, b'{"name":"Original name"}')
        _assert_reply(client.post("/vault/file-v2/manifest", json={
            "file_id": file_id, "crypto_version": "client_mvk_v2",
            "manifest_ciphertext": _b64(manifest),
            "total_bytes": len(file_value), "chunk_size": len(file_value),
            "chunk_count": 1, "migrating_legacy": True,
            "source_snapshot": source_file["source_snapshot"],
        }))
        _assert_reply(client.put("/vault/file-v2/chunk", json={
            "file_id": file_id, "chunk_index": 0, "ciphertext": _b64(file_chunk),
        }))
        file_readback = _assert_reply(client.get(
            f"/vault/legacy-ciphertext/migrate/file-staged/{file_id}",
        ))
        chunk_readback = _assert_reply(client.get(
            f"/vault/file-v2/{file_id}/chunk/0",
        ))
        assert file_readback["source_snapshot"] == source_file["source_snapshot"]
        assert base64.urlsafe_b64decode(chunk_readback["ciphertext"] + "==") == file_chunk
        assert AESGCM(mvk).decrypt(file_chunk[:12], file_chunk[12:], None) == file_value

        # Recovery is separately disabled, rejects stale source state and PIN
        # fields, then clears only unfinished V2 copies after fresh proofs.
        item_reset_body = {"item_id": item_id,
                           "source_snapshot": staged_item["source_snapshot"],
                           "zk_proof_token": "synthetic-proof-2"}
        file_reset_body = {"file_id": file_id,
                           "source_snapshot": source_file["source_snapshot"],
                           "zk_proof_token": "synthetic-proof-3"}
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/item-reset-stage",
            json=item_reset_body,
        ), 404)
        monkeypatch.setenv("VAULTAI_ZK_LEGACY_STAGE_RECOVERY_ENABLED", "true")
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/item-reset-stage",
            json={**item_reset_body, "source_snapshot": source_item["source_snapshot"]},
        ), 409)
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/file-reset-stage",
            json={**file_reset_body, "source_snapshot": "A" * 43},
        ), 409)
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/item-reset-stage",
            json={**item_reset_body, "pin": pin},
        ), 422)
        other = {**principal, "vault_id": str(uuid.uuid4())}
        app.dependency_overrides[verify_trusted_device] = lambda: other
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/item-reset-stage",
            json=item_reset_body,
        ), 404)
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/file-reset-stage",
            json=file_reset_body,
        ), 409)
        app.dependency_overrides[verify_trusted_device] = lambda: principal
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE file_v2_records SET verification_state='client_verified'
                    WHERE file_id=%s""", (file_id,))
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/file-reset-stage",
            json=file_reset_body,
        ), 409)
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE file_v2_records SET verification_state='not_verified'
                    WHERE file_id=%s""", (file_id,))
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/item-reset-stage",
            json={**item_reset_body, "zk_proof_token": "invalid"},
        ), 401)
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/item-reset-stage",
            json=item_reset_body,
        ))
        _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/file-reset-stage",
            json=file_reset_body,
        ))
        _assert_reply(client.get(
            f"/vault/legacy-ciphertext/migrate/item-staged/{item_id}"), 409)
        _assert_reply(client.get(
            f"/vault/legacy-ciphertext/migrate/file-staged/{file_id}"), 409)
        staged_item = _assert_reply(client.post(
            "/vault/legacy-ciphertext/migrate/item-stage",
            json={"item_id": item_id,
                  "item_type_ciphertext": _b64(item_ct[0]),
                  "service_ciphertext": _b64(item_ct[1]),
                  "payload_ciphertext": _b64(item_ct[2]),
                  "source_snapshot": staged_item["source_snapshot"]},
        ))
        _assert_reply(client.post("/vault/file-v2/manifest", json={
            "file_id": file_id, "crypto_version": "client_mvk_v2",
            "manifest_ciphertext": _b64(manifest),
            "total_bytes": len(file_value), "chunk_size": len(file_value),
            "chunk_count": 1, "migrating_legacy": True,
            "source_snapshot": source_file["source_snapshot"],
        }))
        _assert_reply(client.put("/vault/file-v2/chunk", json={
            "file_id": file_id, "chunk_index": 0,
            "ciphertext": _b64(file_chunk),
        }))

        # A failed legacy rename must roll back the staged-sidecar invalidation.
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE OR REPLACE FUNCTION synthetic_stage_rename_fail()
                    RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'synthetic rollback check'; END $$""")
                cur.execute("""CREATE TRIGGER synthetic_stage_rename_fail
                    BEFORE UPDATE OF saved_name ON uploaded_files
                    FOR EACH ROW EXECUTE FUNCTION synthetic_stage_rename_fail()""")
        failed = client.patch("/file", json={"vault_name": "synthetic",
            "file_id": file_id, "saved_name": "Should roll back", "pin": pin})
        assert failed.status_code == 500
        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TRIGGER synthetic_stage_rename_fail ON uploaded_files")
                cur.execute("DROP FUNCTION synthetic_stage_rename_fail()")
        _assert_reply(client.get(
            f"/vault/legacy-ciphertext/migrate/file-staged/{file_id}",
        ))

        # Existing clients can edit and rename after stage. The unfinished V2
        # copy is invalidated, while the original PIN-derived copy stays usable.
        _assert_reply(client.post("/update-secure-item", json={
            "old_service": "Synthetic Site", "item_type": "login", "pin": pin,
            "new_service": "Synthetic Updated", "fields": {"note": "edited"},
            "item_id": item_id,
        }))
        _assert_reply(client.patch("/file", json={
            "vault_name": "synthetic", "file_id": file_id,
            "saved_name": "Renamed by old client", "pin": pin,
        }))
        _assert_reply(client.get(
            f"/vault/legacy-ciphertext/migrate/item-staged/{item_id}"), 409)
        _assert_reply(client.get(
            f"/vault/legacy-ciphertext/migrate/file-staged/{file_id}"), 409)
        stale = client.post("/vault/legacy-ciphertext/migrate/item-stage", json={
            "item_id": item_id, "item_type_ciphertext": _b64(item_ct[0]),
            "service_ciphertext": _b64(item_ct[1]),
            "payload_ciphertext": _b64(item_ct[2]),
            "source_snapshot": staged_item["source_snapshot"],
        })
        _assert_reply(stale, 409)

        with psycopg2.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT encrypted_data,payload_ciphertext,service
                    FROM vault_items WHERE id=%s""", (item_id,))
                legacy_item_ct, staged_payload, item_title = cur.fetchone()
                assert staged_payload is None and item_title == "Synthetic Updated"
                assert json.loads(decrypt_message(legacy_item_ct, key))["fields"]["note"] == "edited"
                cur.execute("""SELECT encrypted_file_data,saved_name
                    FROM uploaded_files WHERE id=%s""", (file_id,))
                legacy_file_ct, saved_name = cur.fetchone()
                assert decrypt_bytes(legacy_file_ct, key) == file_value
                assert saved_name == "renamed by old client"
                cur.execute("SELECT COUNT(*) FROM file_v2_records WHERE file_id=%s", (file_id,))
                assert cur.fetchone()[0] == 0

        # Roll back the staged feature flags. Both legacy copies remain readable.
        monkeypatch.setenv("VAULTAI_ZK_LEGACY_EXPORT_ENABLED", "false")
        monkeypatch.setenv("VAULTAI_ZK_LEGACY_MIGRATION_STAGE_ENABLED", "false")
        _assert_reply(client.post("/list-secure-items", json={
            "vault_name": "synthetic", "pin": pin,
        }))
        _assert_reply(client.get(
            f"/vault/legacy-ciphertext/migrate/item-staged/{item_id}"), 404)

    assert len(consumed_proofs) == 3
