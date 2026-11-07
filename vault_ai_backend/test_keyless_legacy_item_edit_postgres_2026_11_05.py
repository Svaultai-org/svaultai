"""PIN-free legacy item edit against explicit disposable loopback PostgreSQL.

The test uses synthetic vaults, ciphertext and an in-database one-use proof
stub. It never connects to production or uses a real owner's PIN.
"""

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
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from auth_local import reset_secret_for_tests
from device_gate import verify_trusted_device
from legacy_source_snapshot import source_snapshot
from routes import legacy_ciphertext_migration_routes as edit
from routes import login_routes as old_client
from vault_core import decrypt_message, encrypt_message


FLAG = "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_EDIT"
RENAME_FLAG = "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_RENAME"
DELETE_FLAG = "VAULTAI_ENABLE_KEYLESS_LEGACY_ITEM_DELETE"


def _json(response, status=200):
    assert response.status_code == status, (
        response.status_code, response.text[:350],
    )
    return response.json()


def _dsn():
    dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed.get("host") == "127.0.0.1"
    assert parsed.get("dbname") == "svault_keyless_item_edit_qa"
    assert dsn == os.environ["DATABASE_URL"]
    return dsn


def test_keyless_item_edit_flag_off_before_database_use(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)
    monkeypatch.setattr(edit, "get_db", lambda: pytest.fail("database opened"))
    with pytest.raises(HTTPException) as failure:
        edit.stage_legacy_item_edit(
            1,
            edit.LegacyItemEditStageRequest(
                source_snapshot="A" * 43,
                candidate_encrypted_data="A" * 40,
            ),
            {"vault_id": str(uuid4())},
        )
    assert failure.value.status_code == 404


def test_keyless_item_rename_and_delete_flags_off_before_database_use(monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.delenv(RENAME_FLAG, raising=False)
    monkeypatch.delenv(DELETE_FLAG, raising=False)
    monkeypatch.setattr(edit, "get_db", lambda: pytest.fail("database opened"))
    with pytest.raises(HTTPException) as rename:
        edit.stage_legacy_item_edit(
            1,
            edit.LegacyItemEditStageRequest(
                source_snapshot="A" * 43,
                candidate_encrypted_data=base64.b64encode(b"x" * 30).decode(),
                new_service_ciphertext=edit._b64(b"\x01" + b"x" * 29),
                new_title_lookup_hash=edit._b64(b"h" * 32),
            ),
            {"vault_id": str(uuid4())},
        )
    assert rename.value.status_code == 404
    with pytest.raises(HTTPException) as deletion:
        edit.delete_legacy_item_without_pin(
            1,
            edit.LegacyItemDeleteRequest(
                source_snapshot="A" * 43,
                zk_proof_token="synthetic-proof",
                confirm=True,
            ),
            {"vault_id": str(uuid4())},
        )
    assert deletion.value.status_code == 404


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_keyless_item_edit_preserves_old_source_and_proof_atomicity(monkeypatch):
    dsn = _dsn()
    monkeypatch.chdir(Path(__file__).parent)
    command.upgrade(Config(str(Path(__file__).with_name("alembic.ini"))), "head")
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setenv(
        "VAULT_SESSION_SECRET", "synthetic_keyless_item_edit_secret_1234567890",
    )
    reset_secret_for_tests()
    monkeypatch.setattr(edit, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(edit, "require_content_write", lambda _p: None)

    def consume_proof(proof, principal, cur):
        cur.execute(
            "DELETE FROM qa_edit_proofs WHERE proof=%s AND vault_id=%s "
            "RETURNING proof",
            (proof, principal["vault_id"]),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=401, detail="invalid_proof")

    monkeypatch.setattr(edit, "consume_recent_zk_proof_on_cursor", consume_proof)
    vault_id, other_id, token_id = (str(uuid4()) for _ in range(3))
    principal = {"vault_id": vault_id, "token_id": token_id,
                 "device_id": "synthetic-device", "zk_registered": True}
    key = secrets.token_bytes(32)
    old_record = {"category": "login", "title": "Synthetic Alpha",
                  "fields": {"username": "synthetic-user"}, "notes": None}
    old_ciphertext = encrypt_message(json.dumps(old_record), key)
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        assert cur.fetchone() == ("0059_keyless_legacy_item_rename",)
        cur.execute(
            "CREATE TABLE IF NOT EXISTS qa_edit_proofs "
            "(proof TEXT PRIMARY KEY,vault_id UUID NOT NULL)"
        )
        cur.execute("DELETE FROM qa_edit_proofs")
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
            "INSERT INTO auth_sessions(token_id,vault_id,device_id,auth_method,expires_at) "
            "VALUES(%s,%s,'synthetic-device','opaque',NOW()+INTERVAL '1 hour')",
            (token_id, vault_id),
        )
        cur.execute(
            "INSERT INTO vault_items(vault_id,item_type,service,encrypted_data) "
            "VALUES(%s,'login','Synthetic Alpha',%s) RETURNING id",
            (vault_id, old_ciphertext),
        )
        item_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO vault_items(vault_id,item_type,service,encrypted_data) "
            "VALUES(%s,'login','Synthetic Other',%s) RETURNING id",
            (other_id, old_ciphertext),
        )
        other_item_id = cur.fetchone()[0]
        cur.execute(
            "SELECT encrypted_data,item_type,service,item_type_ciphertext,"
            "service_ciphertext,created_at FROM vault_items WHERE id=%s",
            (item_id,),
        )
        columns = ("encrypted_data", "item_type", "service",
                   "item_type_ciphertext", "service_ciphertext", "created_at")
        source = dict(zip(columns, cur.fetchone(), strict=True))
        created_at = source["created_at"]
    snapshot = source_snapshot(
        "item", source, vault_id=vault_id, record_id=item_id,
    )

    app = FastAPI()
    app.include_router(edit.router)
    app.include_router(old_client.router)
    app.dependency_overrides[verify_trusted_device] = lambda: principal
    monkeypatch.setattr(old_client, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(old_client, "verify_vault_pin", lambda _vault, _pin: key)
    path = f"/vault/items/legacy-ciphertext/{item_id}/replace"
    candidate_record = {**old_record,
                        "fields": {"username": "synthetic-user",
                                   "password": "synthetic-secret"}}
    candidate_ciphertext = encrypt_message(json.dumps(candidate_record), key)
    stage_body = {
        "source_snapshot": snapshot,
        "candidate_encrypted_data": candidate_ciphertext,
    }

    with TestClient(app) as client:
        # New route rejects raw PIN fields, malformed ciphertext, and other owners.
        _json(client.post(path + "/stage", json={**stage_body, "pin": "000000"}), 422)
        _json(client.post(path + "/stage", json={
            **stage_body, "new_service": "Synthetic Beta",
        }), 422)
        _json(client.post(path + "/stage", json={
            **stage_body, "candidate_encrypted_data": "not-base64!",
        }), 422)
        assert _json(client.post(
            f"/vault/items/legacy-ciphertext/{other_item_id}/replace/stage",
            json=stage_body,
        ), 404)["detail"] == "legacy_item_not_found"
        assert _json(client.post(path + "/stage", json=stage_body)) == {
            "item_id": item_id, "staged": True, "active_item_unchanged": True,
        }
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT encrypted_data,service FROM vault_items WHERE id=%s", (item_id,))
            assert cur.fetchone() == (old_ciphertext, "Synthetic Alpha")

        readback = _json(client.get(path + "/staged"))
        assert readback["candidate_encrypted_data"] == candidate_ciphertext
        assert readback["source_snapshot"] == snapshot
        assert readback["new_service"] is None
        assert json.loads(decrypt_message(readback["candidate_encrypted_data"], key)) == candidate_record

        # An old-client edit wins over the pending candidate; promotion does
        # not consume proof, change the active bytes, or write history.
        old_client_edit = encrypt_message(json.dumps(old_record), key)
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE vault_items SET encrypted_data=%s WHERE id=%s",
                (old_client_edit, item_id),
            )
            cur.execute(
                "INSERT INTO qa_edit_proofs(proof,vault_id) VALUES(%s,%s)",
                ("synthetic-proof-stale", vault_id),
            )
        assert _json(client.post(path + "/promote", json={
            "source_snapshot": snapshot,
            "readback_receipt": readback["readback_receipt"],
            "zk_proof_token": "synthetic-proof-stale",
            "client_verified_exact_content": True,
        }), 404)["detail"] == "item_edit_not_staged"
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM qa_edit_proofs WHERE proof='synthetic-proof-stale'")
            assert cur.fetchone() == (1,)
            cur.execute("SELECT count(*) FROM legacy_item_edit_history WHERE item_id=%s", (item_id,))
            assert cur.fetchone() == (0,)

        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT encrypted_data,item_type,service,item_type_ciphertext,"
                "service_ciphertext FROM vault_items WHERE id=%s",
                (item_id,),
            )
            current = cur.fetchone()
        fresh_snapshot = source_snapshot(
            "item", current, vault_id=vault_id, record_id=item_id,
        )
        _json(client.post(path + "/stage", json={
            **stage_body, "source_snapshot": fresh_snapshot,
        }))
        fresh_readback = _json(client.get(path + "/staged"))
        assert json.loads(decrypt_message(
            fresh_readback["candidate_encrypted_data"], key,
        )) == candidate_record
        # The legacy snapshot does not cover V2 payload bytes. A DB trigger
        # invalidates the candidate on any source change, and a separate base
        # digest protects the same invariant if trigger behavior ever drifts.
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE vault_items SET payload_ciphertext=%s WHERE id=%s",
                (b"synthetic-v2-stage-after-readback", item_id),
            )
            cur.execute(
                "INSERT INTO qa_edit_proofs(proof,vault_id) VALUES(%s,%s)",
                ("synthetic-proof-v2-stale", vault_id),
            )
        assert _json(client.post(path + "/promote", json={
            "source_snapshot": fresh_snapshot,
            "readback_receipt": fresh_readback["readback_receipt"],
            "zk_proof_token": "synthetic-proof-v2-stale",
            "client_verified_exact_content": True,
        }), 409)["detail"] == "item_requires_dedicated_edit"
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM qa_edit_proofs WHERE proof='synthetic-proof-v2-stale'")
            assert cur.fetchone() == (1,)
            cur.execute("SELECT count(*) FROM legacy_item_edit_candidates WHERE item_id=%s", (item_id,))
            assert cur.fetchone() == (0,)
            cur.execute(
                "UPDATE vault_items SET payload_ciphertext=NULL WHERE id=%s",
                (item_id,),
            )
        _json(client.post(path + "/stage", json={
            **stage_body, "source_snapshot": fresh_snapshot,
        }))
        fresh_readback = _json(client.get(path + "/staged"))
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO qa_edit_proofs(proof,vault_id) VALUES(%s,%s)",
                ("synthetic-proof-promote", vault_id),
            )

        # A failed active UPDATE rolls back both the proof and history.
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE FUNCTION qa_fail_item_edit() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN
                    RAISE EXCEPTION 'qa_injected_failure';
                END; $$
            """)
            cur.execute(
                "CREATE TRIGGER qa_fail_item_edit BEFORE UPDATE ON vault_items "
                "FOR EACH ROW EXECUTE FUNCTION qa_fail_item_edit()"
            )
        try:
            with pytest.raises(Exception, match="qa_injected_failure"):
                client.post(path + "/promote", json={
                    "source_snapshot": fresh_snapshot,
                    "readback_receipt": fresh_readback["readback_receipt"],
                    "zk_proof_token": "synthetic-proof-promote",
                    "client_verified_exact_content": True,
                })
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 FROM qa_edit_proofs WHERE proof='synthetic-proof-promote'")
                assert cur.fetchone() == (1,)
                cur.execute("SELECT count(*) FROM legacy_item_edit_history WHERE item_id=%s", (item_id,))
                assert cur.fetchone() == (0,)
                cur.execute("SELECT encrypted_data FROM vault_items WHERE id=%s", (item_id,))
                assert cur.fetchone() == (old_client_edit,)
                cur.execute("SELECT total_bytes FROM vaults WHERE vault_id=%s", (vault_id,))
                assert cur.fetchone() == (0,)
        finally:
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("DROP TRIGGER IF EXISTS qa_fail_item_edit ON vault_items")
                cur.execute("DROP FUNCTION IF EXISTS qa_fail_item_edit()")

        result = _json(client.post(path + "/promote", json={
            "source_snapshot": fresh_snapshot,
            "readback_receipt": fresh_readback["readback_receipt"],
            "zk_proof_token": "synthetic-proof-promote",
            "client_verified_exact_content": True,
        }))
        assert result == {
            "item_id": item_id, "id": item_id, "service": "Synthetic Alpha",
            "item_type": "login", "updated": True, "created": False,
            "original_preserved_in_history": True,
            "renamed": False, "service_ciphertext": None,
        }
        # Existing old-client title listing and encrypted item fetch still
        # find the same ID and decrypt with the same synthetic legacy key.
        names = _json(client.post(
            "/list-login-names", json={"pin": "synthetic-test-pin"},
        ))["logins"]
        assert {"id": item_id, "service": "Synthetic Alpha"} in names
        old_get = _json(client.post("/get-login", json={
            "service": "Synthetic Alpha", "item_id": item_id,
            "pin": "synthetic-test-pin",
        }))
        assert old_get["id"] == item_id
        assert json.loads(decrypt_message(old_get["encrypted_data"], key)) == candidate_record
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT encrypted_data,service,payload_ciphertext,title_revision,"
                "created_at "
                "FROM vault_items WHERE id=%s", (item_id,),
            )
            encrypted, service, payload_v2, title_revision, post_created_at = cur.fetchone()
            assert (encrypted, service, payload_v2, title_revision, post_created_at) == (
                candidate_ciphertext, "Synthetic Alpha", None, 1, created_at,
            )
            assert json.loads(decrypt_message(encrypted, key)) == candidate_record
            cur.execute(
                "SELECT prior_encrypted_data,prior_service,prior_payload_ciphertext "
                "FROM "
                "legacy_item_edit_history WHERE item_id=%s",
                (item_id,),
            )
            previous = cur.fetchone()
            assert previous[:2] == (old_client_edit, "Synthetic Alpha")
            assert previous[2] is None
            cur.execute("SELECT count(*) FROM legacy_item_edit_candidates WHERE item_id=%s", (item_id,))
            assert cur.fetchone() == (0,)
            cur.execute("SELECT count(*) FROM qa_edit_proofs WHERE proof='synthetic-proof-promote'")
            assert cur.fetchone() == (0,)
            cur.execute("SELECT total_bytes FROM vaults WHERE vault_id=%s", (vault_id,))
            assert cur.fetchone() == (
                len(candidate_ciphertext) - len(old_client_edit),
            )
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM vaults WHERE vault_id IN (%s,%s)", (vault_id, other_id))


@pytest.mark.skipif(
    not os.getenv("VAULTAI_TEST_DATABASE_URL"),
    reason="requires explicit disposable loopback PostgreSQL",
)
def test_encrypted_rename_reedit_and_proof_bound_delete(monkeypatch):
    dsn = _dsn()
    monkeypatch.chdir(Path(__file__).parent)
    command.upgrade(Config(str(Path(__file__).with_name("alembic.ini"))), "head")
    for flag in (FLAG, RENAME_FLAG, DELETE_FLAG):
        monkeypatch.setenv(flag, "true")
    monkeypatch.setenv(
        "VAULT_SESSION_SECRET", "synthetic_item_rename_secret_1234567890",
    )
    reset_secret_for_tests()
    monkeypatch.setattr(edit, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(edit, "require_content_write", lambda _p: None)
    monkeypatch.setattr(old_client, "get_db", lambda: psycopg2.connect(dsn))
    monkeypatch.setattr(old_client, "verify_vault_pin", lambda _v, _p: key)
    monkeypatch.setattr(old_client, "require_content_write", lambda _p: None)

    def consume_proof(proof, principal, cur):
        cur.execute(
            "DELETE FROM qa_edit_proofs WHERE proof=%s AND vault_id=%s "
            "RETURNING proof", (proof, principal["vault_id"]),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=401, detail="invalid_proof")

    monkeypatch.setattr(edit, "consume_recent_zk_proof_on_cursor", consume_proof)
    vault_id, token_id = str(uuid4()), str(uuid4())
    principal = {"vault_id": vault_id, "token_id": token_id,
                 "device_id": "synthetic-device", "zk_registered": True}
    key = secrets.token_bytes(32)
    meta_key = secrets.token_bytes(32)
    new_title = "Synthetic Private Title"
    nonce = secrets.token_bytes(12)
    title_ct = b"\x01" + nonce + AESGCM(meta_key).encrypt(
        nonce, new_title.encode(), None,
    )
    title_ct_encoded = base64.urlsafe_b64encode(title_ct).decode().rstrip("=")
    title_hash = secrets.token_bytes(32)
    hash_encoded = base64.urlsafe_b64encode(title_hash).decode().rstrip("=")
    original = {"category": "login", "title": "Synthetic Old",
                "fields": {"username": "old-user"}}
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS qa_edit_proofs "
            "(proof TEXT PRIMARY KEY,vault_id UUID NOT NULL)"
        )
        cur.execute(
            "INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier,"
            "kdf_iterations,vault_handle,opaque_registration_record,wrapped_mvk) "
            "VALUES (%s,%s,'synthetic-salt','synthetic-verifier',600000,%s,%s,%s)",
            (vault_id, f"vault-{vault_id.replace('-', '')}",
             secrets.token_bytes(15), secrets.token_bytes(32),
             secrets.token_bytes(48)),
        )
        cur.execute(
            "INSERT INTO auth_sessions(token_id,vault_id,device_id,auth_method,expires_at) "
            "VALUES(%s,%s,'synthetic-device','opaque',NOW()+INTERVAL '1 hour')",
            (token_id, vault_id),
        )
        cur.execute(
            "INSERT INTO vault_items(vault_id,item_type,service,encrypted_data) "
            "VALUES(%s,'login','Synthetic Old',%s) RETURNING id",
            (vault_id, encrypt_message(json.dumps(original), key)),
        )
        item_id = cur.fetchone()[0]
    original["item_id"] = item_id
    renamed = {**original, "title": new_title,
               "fields": {"username": "renamed-user"}}
    renamed_ct = encrypt_message(json.dumps(renamed), key)

    def snapshot() -> str:
        with psycopg2.connect(dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT encrypted_data,item_type,service,item_type_ciphertext,"
                "service_ciphertext FROM vault_items WHERE id=%s", (item_id,),
            )
            row = cur.fetchone()
        return source_snapshot("item", row, vault_id=vault_id, record_id=item_id)

    def insert_proof(label: str) -> None:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO qa_edit_proofs(proof,vault_id) VALUES(%s,%s)",
                (label, vault_id),
            )

    app = FastAPI()
    app.include_router(edit.router)
    app.include_router(old_client.router)
    app.dependency_overrides[verify_trusted_device] = lambda: principal
    base = f"/vault/items/legacy-ciphertext/{item_id}"
    try:
        with TestClient(app) as client:
            first_snapshot = snapshot()
            stage = {"source_snapshot": first_snapshot,
                     "candidate_encrypted_data": renamed_ct,
                     "new_service_ciphertext": title_ct_encoded,
                     "new_title_lookup_hash": hash_encoded}
            assert new_title not in json.dumps(stage)
            _json(client.post(base + "/replace/stage", json=stage))
            readback = _json(client.get(base + "/replace/staged"))
            assert readback["candidate_encrypted_data"] == renamed_ct
            assert readback["new_service_ciphertext"] == title_ct_encoded
            assert readback["new_title_lookup_hash"] == hash_encoded
            assert readback["new_service"] is None
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT service FROM vault_items WHERE id=%s", (item_id,))
                assert cur.fetchone() == ("Synthetic Old",)
            insert_proof("synthetic-rename-proof")
            promote_body = {
                "source_snapshot": first_snapshot,
                "readback_receipt": readback["readback_receipt"],
                "zk_proof_token": "synthetic-rename-proof",
                "client_verified_exact_content": True,
            }
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO vault_items(vault_id,item_type,service,encrypted_data,"
                    "title_lookup_hash) VALUES(%s,'login','Synthetic Other',%s,%s) "
                    "RETURNING id",
                    (vault_id, encrypt_message(json.dumps(original), key), title_hash),
                )
                collision_id = cur.fetchone()[0]
            assert _json(client.post(
                base + "/replace/promote", json=promote_body,
            ), 409)["detail"] == "duplicate_saved_item"
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT encrypted_data FROM vault_items WHERE id=%s", (item_id,))
                assert cur.fetchone()[0] != renamed_ct
                cur.execute(
                    "SELECT 1 FROM qa_edit_proofs WHERE proof='synthetic-rename-proof'"
                )
                assert cur.fetchone() == (1,)
                cur.execute("DELETE FROM vault_items WHERE id=%s", (collision_id,))
            promoted = _json(client.post(
                base + "/replace/promote", json=promote_body,
            ))
            assert promoted["renamed"] is True
            assert promoted["service_ciphertext"] == title_ct_encoded
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT encrypted_data,service,service_ciphertext,"
                    "title_lookup_hash,legacy_item_rename_active,payload_ciphertext "
                    "FROM vault_items WHERE id=%s", (item_id,),
                )
                active = cur.fetchone()
                assert active[:2] == (renamed_ct, "Synthetic Old")
                assert bytes(active[2]) == title_ct
                assert bytes(active[3]) == title_hash
                assert active[4:] == (True, None)
                cur.execute(
                    "SELECT encrypted_rename,prior_encrypted_data "
                    "FROM legacy_item_edit_history WHERE item_id=%s", (item_id,),
                )
                assert cur.fetchone()[0] is True
            assert json.loads(decrypt_message(_json(client.post(
                "/get-login", json={"service": "Synthetic Old",
                                    "item_id": item_id, "pin": "synthetic-pin"},
            ))["encrypted_data"], key)) == renamed

            second_snapshot = snapshot()
            edited = {**renamed, "fields": {"username": "edited-again"}}
            edited_ct = encrypt_message(json.dumps(edited), key)
            _json(client.post(base + "/replace/stage", json={
                "source_snapshot": second_snapshot,
                "candidate_encrypted_data": edited_ct,
            }))
            second_readback = _json(client.get(base + "/replace/staged"))
            insert_proof("synthetic-field-proof")
            result = _json(client.post(base + "/replace/promote", json={
                "source_snapshot": second_snapshot,
                "readback_receipt": second_readback["readback_receipt"],
                "zk_proof_token": "synthetic-field-proof",
                "client_verified_exact_content": True,
            }))
            assert result["renamed"] is False
            assert result["service_ciphertext"] == title_ct_encoded
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT legacy_item_rename_active,title_revision "
                    "FROM vault_items WHERE id=%s", (item_id,),
                )
                assert cur.fetchone() == (True, 2)
                cur.execute(
                    "SELECT count(*) FROM legacy_item_edit_history WHERE item_id=%s",
                    (item_id,),
                )
                assert cur.fetchone() == (2,)

            insert_proof("synthetic-delete-proof")
            delete_body = {"source_snapshot": second_snapshot,
                           "zk_proof_token": "synthetic-delete-proof",
                           "confirm": True}
            _json(client.post(base + "/delete", json={**delete_body, "pin": "000000"}), 422)
            assert _json(client.post(base + "/delete", json=delete_body), 409)["detail"] == "legacy_source_changed"
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM qa_edit_proofs WHERE proof='synthetic-delete-proof'"
                )
                assert cur.fetchone() == (1,)
            delete_body["source_snapshot"] = snapshot()
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("""
                    CREATE FUNCTION qa_fail_item_delete() RETURNS trigger
                    LANGUAGE plpgsql AS $$ BEGIN
                        RAISE EXCEPTION 'qa_injected_delete_failure';
                    END; $$
                """)
                cur.execute(
                    "CREATE TRIGGER qa_fail_item_delete BEFORE DELETE ON vault_items "
                    "FOR EACH ROW EXECUTE FUNCTION qa_fail_item_delete()"
                )
            try:
                with pytest.raises(Exception, match="qa_injected_delete_failure"):
                    client.post(base + "/delete", json=delete_body)
                with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM vault_items WHERE id=%s", (item_id,))
                    assert cur.fetchone() == (1,)
                    cur.execute(
                        "SELECT count(*) FROM legacy_item_edit_history WHERE item_id=%s",
                        (item_id,),
                    )
                    assert cur.fetchone() == (2,)
                    cur.execute(
                        "SELECT 1 FROM qa_edit_proofs WHERE proof='synthetic-delete-proof'"
                    )
                    assert cur.fetchone() == (1,)
            finally:
                with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                    cur.execute("DROP TRIGGER qa_fail_item_delete ON vault_items")
                    cur.execute("DROP FUNCTION qa_fail_item_delete()")
            assert _json(client.post(base + "/delete", json=delete_body)) == {
                "status": "deleted", "item_id": item_id,
            }
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM vault_items WHERE id=%s", (item_id,))
                assert cur.fetchone() == (0,)
                cur.execute(
                    "SELECT count(*) FROM legacy_item_edit_history WHERE item_id=%s",
                    (item_id,),
                )
                assert cur.fetchone() == (0,)
                cur.execute(
                    "SELECT 1 FROM qa_edit_proofs WHERE proof='synthetic-delete-proof'"
                )
                assert cur.fetchone() is None

            # An older client still edits a renamed item through its old
            # plaintext label; that write drops the stale encrypted override.
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO vault_items(vault_id,item_type,service,encrypted_data,"
                    "service_ciphertext,title_lookup_hash,legacy_item_rename_active) "
                    "VALUES(%s,'login','Synthetic Old',%s,%s,%s,TRUE) RETURNING id",
                    (vault_id, edited_ct, title_ct, title_hash),
                )
                old_client_id = cur.fetchone()[0]
            _json(client.post("/update-secure-item", json={
                "old_service": "Synthetic Old", "item_type": "login",
                "item_id": old_client_id, "pin": "synthetic-pin",
                "fields": {"username": "older-client"},
            }))
            with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT service_ciphertext,title_lookup_hash,"
                    "legacy_item_rename_active,title_revision "
                    "FROM vault_items WHERE id=%s", (old_client_id,),
                )
                assert cur.fetchone() == (None, None, False, 1)
    finally:
        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM vaults WHERE vault_id=%s", (vault_id,))
