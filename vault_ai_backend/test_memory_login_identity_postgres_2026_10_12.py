"""Opt-in actual PostgreSQL identity/race tests, synthetic fixtures only.

Requires the fresh QA launcher under work/. No production/default DSN is ever
accepted. Every connection checks DB, user, loopback, port, data directory and
actual migrated head before any fixture operation. No HTTP/provider calls.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from routes import login_routes as logins
from routes import vault_ciphertext_write_routes as memories
from vault_core import decrypt_message, encrypt_message

DSN = "postgresql://svaultai_memory_login_qa@127.0.0.1:55439/svaultai_memory_login_qa"
IDENTITY = ("svaultai_memory_login_qa", "svaultai_memory_login_qa", "127.0.0.1", 55439)
HEAD = "0049_kag_encrypted_draft_binding"
_ENABLED = os.getenv("VAULTAI_MEMORY_LOGIN_TEST_DATABASE_URL", "")
_CLUSTER = os.getenv("VAULTAI_MEMORY_LOGIN_TEST_CLUSTER_DIR", "")
KEY = b"K" * 32  # Public synthetic test key, never a user's vault key.
pytestmark = pytest.mark.skipif(not _ENABLED, reason="Explicit fresh local QA launcher required")


def _connect():
    if _ENABLED != DSN:
        pytest.fail("Refusing any non-isolated QA database URL")
    cluster = Path(_CLUSTER).resolve()
    if cluster.parent != Path("/private/tmp") or not cluster.name.startswith("svaultai-memory-login-pg."):
        pytest.fail("Refusing any non-disposable test cluster")
    conn = psycopg2.connect(DSN, connect_timeout=3)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port(),current_setting('data_directory')")
            identity = cur.fetchone()
            assert identity[:4] == IDENTITY
            assert Path(identity[4]).resolve() == cluster / "data"
            cur.execute("SELECT version_num FROM alembic_version")
            assert cur.fetchone() == (HEAD,)
            cur.execute("SET statement_timeout=5000")
            cur.execute("SET lock_timeout=5000")
        conn.commit()
        return conn
    except BaseException:
        conn.close()
        raise


class _Cursor:
    def __init__(self, cursor, barrier, mode):
        self.cursor = cursor
        self.barrier = barrier
        self.mode = mode
        self.used = False

    def execute(self, query, params=()):
        result = self.cursor.execute(query, params)
        text = " ".join(query.lower().split())
        memory_read = text.startswith("select id, memory_record_id from vault_ai_memory")
        login_read = text.startswith("select id from vault_items")
        if not self.used and self.barrier is not None and (
            (self.mode == "memory" and memory_read) or (self.mode == "login" and login_read)
        ):
            self.used = True
            # Both actual READ COMMITTED transactions finish the initial
            # absence check before competing on real unique-index INSERT/UPDATE.
            self.barrier.wait(timeout=5)
        return result

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class _Connection:
    def __init__(self, connection, barrier, mode):
        self.connection = connection
        self.barrier = barrier
        self.mode = mode

    def cursor(self, *args, **kwargs):
        return _Cursor(self.connection.cursor(*args, **kwargs), self.barrier, self.mode)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class _Fixture:
    def __init__(self):
        self.vaults = [str(uuid4()), str(uuid4())]
        self.barrier = None
        self.mode = None
        with _connect() as conn:
            with conn.cursor() as cur:
                for vault in self.vaults:
                    cur.execute("""INSERT INTO vaults(vault_id,vault_name,pin_salt,pin_verifier)
                                   VALUES (%s,%s,%s,%s)""",
                                (vault, "vault-" + vault.replace("-", ""), "synthetic-only", "synthetic-only"))
                cur.execute("""INSERT INTO vault_items(vault_id,item_type_ciphertext,service_ciphertext,payload_ciphertext)
                               VALUES (%s,%s,%s,%s) RETURNING id""",
                            (self.vaults[0], b"protected-type", b"protected-label", b"protected-unrelated-ciphertext"))
                self.protected_id = cur.fetchone()[0]

    @property
    def vault(self):
        return self.vaults[0]

    def connect(self):
        return _Connection(_connect(), self.barrier, self.mode)

    def memory_rows(self):
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT memory_record_id,memory_lookup_hash,payload_ciphertext,memory_key,memory_value
                               FROM vault_ai_memory WHERE vault_id=%s ORDER BY memory_record_id""", (self.vault,))
                return [(r[0], bytes(r[1]), bytes(r[2]), r[3], r[4]) for r in cur.fetchall()]

    def add_memory(self, record, lookup, ciphertext):
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO vault_ai_memory(vault_id,memory_record_id,memory_type,
                               memory_key,memory_value,memory_lookup_hash,payload_ciphertext)
                               VALUES (%s,%s,'note',NULL,NULL,%s,%s)""", (self.vault, record, lookup, ciphertext))

    def add_login(self, password, *, vault=None, title="Duplicate"):
        blob = encrypt_message(json.dumps({"fields": {"password": password}}), KEY)
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO vault_items(vault_id,item_type,service,encrypted_data)
                               VALUES (%s,'login',%s,%s) RETURNING id""", (vault or self.vault, title, blob))
                return cur.fetchone()[0]

    def login_rows(self):
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id,service,encrypted_data FROM vault_items WHERE vault_id=%s AND item_type='login' ORDER BY id",
                            (self.vault,))
                return cur.fetchall()

    def item_row(self, item_id):
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT id,item_type,service,encrypted_data,item_type_ciphertext,
                               service_ciphertext,payload_ciphertext FROM vault_items
                               WHERE vault_id=%s AND id=%s""", (self.vault, item_id))
                row = cur.fetchone()
                return None if row is None else tuple(bytes(v) if isinstance(v, memoryview) else v for v in row)

    def cleanup(self):
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT item_type,service,encrypted_data,item_type_ciphertext,service_ciphertext,payload_ciphertext
                               FROM vault_items WHERE vault_id=%s AND id=%s""", (self.vault, self.protected_id))
                protected = cur.fetchone()
                assert protected[:3] == (None, None, None)
                assert tuple(bytes(v) for v in protected[3:]) == (
                    b"protected-type", b"protected-label", b"protected-unrelated-ciphertext")
                # Only this test's generated UUID fixtures; no TRUNCATE/broad delete.
                cur.execute("DELETE FROM vaults WHERE vault_id=ANY(%s::uuid[])", (self.vaults,))


@pytest.fixture
def pg(monkeypatch):
    assert len(KEY) == 32
    fixture = _Fixture()
    monkeypatch.setenv("MEMORY_V2_READ_ENABLED", "true")
    monkeypatch.setenv("MEMORY_V2_WRITE_ENABLED", "true")
    # Strict-mode safety is opt-in only after both corrected native apps are
    # publicly available. Separate tests below prove staged compatibility.
    monkeypatch.setenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", "true")
    monkeypatch.delenv("QA_CHAT_PRIVACY_DIAGNOSTICS", raising=False)
    monkeypatch.setattr(memories, "get_db", fixture.connect)
    monkeypatch.setattr(memories, "require_content_write", lambda _principal: None)
    monkeypatch.setattr(logins, "get_db", fixture.connect)
    monkeypatch.setattr(logins, "require_content_write", lambda _principal: None)
    monkeypatch.setattr(logins, "verify_vault_pin", lambda _vault, _pin: KEY)
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(get_db=fixture.connect,
                        bump_vault_total_bytes=lambda *_args: None))
    monkeypatch.setitem(sys.modules, "vault_tool_result_cache", SimpleNamespace(invalidate_for_event=lambda **_kwargs: None))
    try:
        yield fixture
    finally:
        fixture.barrier = None
        fixture.cleanup()


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _memory(pg, record, *, lookup=b"A" * 32, value=b"synthetic-opaque", edit=False):
    payload = memories.AiMemoryCiphertextRequest(memory_id=record, memory_type="note",
                memory_lookup_hash=_b64(lookup), payload_ciphertext=_b64(value), replace_existing=edit)
    try:
        return memories.ai_memory_ciphertext_upsert(payload, principal={"vault_id": pg.vault})
    except HTTPException as error:
        return error


def _parallel(pg, actions, *, mode="memory"):
    pg.barrier, pg.mode = threading.Barrier(2), mode
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(action) for action in actions]
            return [future.result(timeout=10) for future in futures]
    finally:
        pg.barrier = None


def test_real_pg_different_identity_create_race_preserves_one_winner(pg):
    results = _parallel(pg, [lambda: _memory(pg, "one", value=b"first-ciphertext"),
                             lambda: _memory(pg, "two", value=b"second-ciphertext")])
    errors = [r for r in results if isinstance(r, HTTPException)]
    assert len(errors) == 1 and errors[0].status_code == 409
    rows = pg.memory_rows()
    assert len(rows) == 1
    assert rows[0][:3] in (("one", b"A" * 32, b"first-ciphertext"), ("two", b"A" * 32, b"second-ciphertext"))
    assert rows[0][3:] == (None, None)


def test_real_pg_same_identity_create_retry_is_idempotent(pg):
    results = _parallel(pg, [lambda: _memory(pg, "same", value=b"first-nonce"),
                             lambda: _memory(pg, "same", value=b"retry-nonce")])
    assert all(not isinstance(result, HTTPException) for result in results)
    assert sum(result.duplicate for result in results) == 1
    before = pg.memory_rows()
    assert len(before) == 1 and before[0][2] in (b"first-nonce", b"retry-nonce")
    assert _memory(pg, "same", value=b"later-retry").duplicate is True
    assert pg.memory_rows() == before


def test_real_pg_concurrent_renames_have_one_winner_and_loser_rollback(pg):
    pg.add_memory("one", b"A" * 32, b"original-one")
    pg.add_memory("two", b"B" * 32, b"original-two")
    results = _parallel(pg, [lambda: _memory(pg, "one", lookup=b"C" * 32, value=b"changed-one", edit=True),
                             lambda: _memory(pg, "two", lookup=b"C" * 32, value=b"changed-two", edit=True)])
    errors = [r for r in results if isinstance(r, HTTPException)]
    assert len(errors) == 1 and errors[0].status_code == 409
    rows = {r[0]: r[1:3] for r in pg.memory_rows()}
    assert rows in ({"one": (b"C" * 32, b"changed-one"), "two": (b"B" * 32, b"original-two")},
                    {"one": (b"A" * 32, b"original-one"), "two": (b"C" * 32, b"changed-two")})


def test_real_pg_rename_onto_another_record_never_overwrites(pg):
    pg.add_memory("one", b"A" * 32, b"original-one")
    pg.add_memory("two", b"B" * 32, b"original-two")
    before = pg.memory_rows()
    error = _memory(pg, "two", lookup=b"A" * 32, value=b"replacement", edit=True)
    assert isinstance(error, HTTPException) and error.status_code == 409
    assert pg.memory_rows() == before


def test_real_pg_missing_selected_edit_returns404_without_insert(pg):
    result = _memory(pg, "deleted", edit=True)
    assert isinstance(result, HTTPException) and result.status_code == 404
    assert pg.memory_rows() == []


def test_real_pg_exact_login_id_get_edit_delete_preserves_duplicate_peer(pg):
    first = pg.add_login("first-synthetic")
    second = pg.add_login("second-synthetic")
    original = pg.login_rows()[0]
    principal = {"vault_id": pg.vault}
    found = logins.get_secure_item(logins.GetSecureItemRequest(service="Duplicate", item_type="login", pin="test", item_id=second), principal)
    assert found["id"] == second and found["fields"]["password"] == "second-synthetic"
    logins.update_secure_item(logins.UpdateSecureItemRequest(old_service="Duplicate", item_type="login", pin="test",
                             item_id=second, fields={"password": "changed-synthetic"}), principal)
    assert pg.login_rows()[0] == original
    removed = logins.delete_secure_item(logins.DeleteSecureItemRequest(service="Duplicate", item_type="login", pin="test", item_id=second), principal)
    assert removed["count"] == 1
    assert pg.login_rows() == [original] and original[0] == first


@pytest.mark.parametrize("operation", ["read", "edit", "delete"])
def test_real_pg_ambiguous_old_client_title_cannot_mutate_duplicates(pg, operation):
    pg.add_login("one")
    pg.add_login("two")
    before = pg.login_rows()
    with pytest.raises(HTTPException) as error:
        if operation == "read":
            logins.get_secure_item(logins.GetSecureItemRequest(service="Duplicate", item_type="login", pin="test"), {"vault_id": pg.vault})
        elif operation == "edit":
            logins.update_secure_item(logins.UpdateSecureItemRequest(old_service="Duplicate", item_type="login", pin="test", fields={"password": "replacement"}), {"vault_id": pg.vault})
        else:
            logins.delete_secure_item(logins.DeleteSecureItemRequest(service="Duplicate", item_type="login", pin="test"), {"vault_id": pg.vault})
    assert error.value.status_code == 409
    assert pg.login_rows() == before


def test_real_pg_foreign_login_id_cannot_fall_back_to_title(pg):
    pg.add_login("own")
    foreign = pg.add_login("foreign", vault=pg.vaults[1])
    before = pg.login_rows()
    with pytest.raises(HTTPException) as error:
        logins.delete_secure_item(logins.DeleteSecureItemRequest(service="Duplicate", item_type="login", pin="test", item_id=foreign), {"vault_id": pg.vault})
    assert error.value.status_code == 404 and pg.login_rows() == before


def test_real_pg_create_only_race_retains_distinct_rows_never_overwrites(pg):
    def create(value):
        return logins.update_secure_item(logins.UpdateSecureItemRequest(old_service="Parallel", item_type="login", pin="test",
                    fields={"password": value}, create_only=True), {"vault_id": pg.vault})
    results = _parallel(pg, [lambda: create("one"), lambda: create("two")], mode="login")
    # There is intentionally no plaintext-title unique constraint: two concurrent
    # legacy creates may retain distinct visible rows, but cannot replace either.
    assert all(result["created"] is True for result in results)
    assert len({result["id"] for result in results}) == 2
    rows = pg.login_rows()
    assert len(rows) == 2
    assert {json.loads(decrypt_message(row[2], KEY))["fields"]["password"] for row in rows} == {"one", "two"}


def test_real_pg_natural_language_save_cannot_replace_existing_login(pg):
    import vault_secure_item_save as writer
    pg.add_login("original")
    before = pg.login_rows()
    result = writer._encrypt_and_write(vault_id=pg.vault, key=KEY,
                args={"secret_type": "login", "service": "Duplicate", "fields": {"password": "replacement"}},
                field=None, value=None, notes=None, db_executor=None)
    assert result["band"] != writer.BAND_SAVED
    assert pg.login_rows() == before


def test_real_pg_natural_delete_requires_exact_db_id_for_duplicates(pg):
    import vault_secure_item_save as writer
    pg.add_login("original-one")
    selected = pg.add_login("original-two")
    before = pg.login_rows()
    payload = {"vault_id": pg.vault, "item_type": "login", "service": "Duplicate"}
    for item in (payload, {**payload, "item_id": uuid4().hex}):
        with pytest.raises(writer.SavedItemTitleConflict):
            writer._default_delete(item)
        assert pg.login_rows() == before
    assert writer._default_delete({**payload, "item_id": str(selected)}) == 1
    assert pg.login_rows() == [before[0]]


def test_real_pg_old_login_routes_refuse_ambiguity_and_accept_selected_id(pg):
    pg.add_login("original-one")
    selected = pg.add_login("original-two")
    before = pg.login_rows()
    principal = {"vault_id": pg.vault}
    for route, model in ((logins.get_login, logins.GetLoginRequest),
                         (logins.delete_login, logins.DeleteLoginRequest)):
        with pytest.raises(HTTPException) as error:
            route(model(service="Duplicate", pin="test"), principal)
        assert error.value.status_code == 409 and pg.login_rows() == before
    found = logins.get_login(logins.GetLoginRequest(service="Duplicate", pin="test", item_id=selected), principal)
    assert found["id"] == selected
    logins.delete_login(logins.DeleteLoginRequest(service="Duplicate", pin="test", item_id=selected), principal)
    assert pg.login_rows() == [before[0]]


def test_real_pg_ciphertext_item_update_requires_own_exact_id(pg):
    def request(item_id, value):
        return memories.VaultItemUpsertRequest(item_id=item_id,
            mutation_intent="create" if item_id is None else "edit",
            item_type_ciphertext=_b64(b"opaque-type"), service_ciphertext=_b64(b"opaque-label"),
            payload_ciphertext=_b64(value))
    created = memories.vault_item_upsert_ciphertext(request(None, b"first-opaque"), principal={"vault_id": pg.vault})
    with pytest.raises(HTTPException) as error:
        memories.vault_item_upsert_ciphertext(request(created.item_id, b"foreign-overwrite"), principal={"vault_id": pg.vaults[1]})
    assert error.value.status_code == 404
    updated = memories.vault_item_upsert_ciphertext(request(created.item_id, b"selected-update"), principal={"vault_id": pg.vault})
    assert updated.item_id == created.item_id and updated.created is False
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT item_type,service,encrypted_data,payload_ciphertext FROM vault_items WHERE id=%s AND vault_id=%s",
                        (created.item_id, pg.vault))
            row = cur.fetchone()
            assert row[:3] == (None, None, None) and bytes(row[3]) == b"selected-update"


@pytest.mark.parametrize("intent", [None, "create"])
def test_real_pg_old_or_create_intent_cannot_update_existing_ciphertext_id(pg, intent):
    created = memories.vault_item_upsert_ciphertext(memories.VaultItemUpsertRequest(
        item_type_ciphertext=_b64(b"opaque-type"), service_ciphertext=_b64(b"opaque-label"),
        payload_ciphertext=_b64(b"original-opaque")), principal={"vault_id": pg.vault})
    before = pg.item_row(created.item_id)
    request = memories.VaultItemUpsertRequest(item_id=created.item_id,
        item_type_ciphertext=_b64(b"replacement-type"), service_ciphertext=_b64(b"replacement-label"),
        payload_ciphertext=_b64(b"unsafe-replacement"),
        **({} if intent is None else {"mutation_intent": intent}))
    with pytest.raises(HTTPException) as error:
        memories.vault_item_upsert_ciphertext(request, principal={"vault_id": pg.vault})
    assert error.value.status_code == 409
    assert pg.item_row(created.item_id) == before


@pytest.mark.parametrize("item_type", ["login", "credential"])
def test_real_pg_old_unique_title_update_requires_explicit_selected_id(pg, item_type):
    selected = pg.add_login("original-synthetic")
    if item_type != "login":
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE vault_items SET item_type=%s WHERE vault_id=%s AND id=%s",
                            (item_type, pg.vault, selected))
    before = pg.item_row(selected)
    # This is the old Create/Edit upsert shape: no selected id or create flag.
    request = logins.UpdateSecureItemRequest(old_service="Duplicate", item_type=item_type,
                                            pin="test", fields={"password": "unsafe-replacement"})
    with pytest.raises(HTTPException) as error:
        logins.update_secure_item(request, principal={"vault_id": pg.vault})
    assert error.value.status_code == 409 and pg.item_row(selected) == before
    safe = request.model_copy(update={"item_id": selected})
    assert logins.update_secure_item(safe, principal={"vault_id": pg.vault})["id"] == selected


def test_real_pg_missing_old_title_never_falls_back_to_overwriting_new_title(pg):
    selected = pg.add_login("existing-original")
    before = pg.item_row(selected)
    request = logins.UpdateSecureItemRequest(old_service="Missing Old Label", new_service="Duplicate",
                item_type="login", pin="test", fields={"password": "new-distinct-payload"})
    result = logins.update_secure_item(request, principal={"vault_id": pg.vault})
    assert result["created"] is True and result["id"] != selected
    assert pg.item_row(selected) == before and len(pg.login_rows()) == 2


def _staged_mode(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", raising=False)
    else:
        monkeypatch.setenv("VAULTAI_SAVED_ITEM_MUTATION_INTENT_REQUIRED", value)


@pytest.mark.parametrize("value", [None, "false"])
def test_real_pg_staged_default_preserves_old_unique_edit_compatibility(pg, monkeypatch, value):
    _staged_mode(monkeypatch, value)
    selected = pg.add_login("old-original")
    request = logins.UpdateSecureItemRequest(old_service="Duplicate", item_type="login", pin="test",
                                            fields={"password": "old-explicit-edit"})
    result = logins.update_secure_item(request, principal={"vault_id": pg.vault})
    assert result["id"] == selected and result["created"] is False
    assert json.loads(decrypt_message(pg.item_row(selected)[3], KEY))["fields"]["password"] == "old-explicit-edit"
    # An older ciphertext writer omits the new marker altogether. Compatibility
    # intentionally remains enabled here; this is NOT proof old Create is safe.
    created = memories.vault_item_upsert_ciphertext(memories.VaultItemUpsertRequest(
        item_type_ciphertext=_b64(b"opaque-type"), service_ciphertext=_b64(b"opaque-label"),
        payload_ciphertext=_b64(b"old-original")), principal={"vault_id": pg.vault})
    updated = memories.vault_item_upsert_ciphertext(memories.VaultItemUpsertRequest(item_id=created.item_id,
        item_type_ciphertext=_b64(b"opaque-type"), service_ciphertext=_b64(b"opaque-label"),
        payload_ciphertext=_b64(b"old-edit")), principal={"vault_id": pg.vault})
    assert updated.item_id == created.item_id and updated.created is False
    assert pg.item_row(created.item_id)[6] == b"old-edit"


@pytest.mark.parametrize("value", [None, "false"])
def test_real_pg_explicit_conflicting_create_marker_always_refused(pg, monkeypatch, value):
    _staged_mode(monkeypatch, value)
    created = memories.vault_item_upsert_ciphertext(memories.VaultItemUpsertRequest(
        item_type_ciphertext=_b64(b"opaque-type"), service_ciphertext=_b64(b"opaque-label"),
        payload_ciphertext=_b64(b"original")), principal={"vault_id": pg.vault})
    before = pg.item_row(created.item_id)
    with pytest.raises(HTTPException) as error:
        memories.vault_item_upsert_ciphertext(memories.VaultItemUpsertRequest(item_id=created.item_id,
            mutation_intent="create", item_type_ciphertext=_b64(b"opaque-type"),
            service_ciphertext=_b64(b"opaque-label"), payload_ciphertext=_b64(b"invalid-create")),
            principal={"vault_id": pg.vault})
    assert error.value.status_code == 409 and pg.item_row(created.item_id) == before


def test_real_pg_edit_marker_without_selected_id_always_refused(pg, monkeypatch):
    _staged_mode(monkeypatch, "false")
    with pytest.raises(HTTPException) as error:
        memories.vault_item_upsert_ciphertext(memories.VaultItemUpsertRequest(mutation_intent="edit",
            item_type_ciphertext=_b64(b"opaque-type"), service_ciphertext=_b64(b"opaque-label"),
            payload_ciphertext=_b64(b"invalid-edit")), principal={"vault_id": pg.vault})
    assert error.value.status_code == 400
