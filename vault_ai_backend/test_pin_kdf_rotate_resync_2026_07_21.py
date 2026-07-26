# Root-cause repro for the c2f917e production regression:
#
#   Sign in -> Enter PIN -> Vault unlocks -> Send any first chat
#   message -> "Your vault unlock session expired or no longer
#   matches this vault. Please enter your PIN again."
#
# Enter the PIN a second time and every chat request afterward
# works. The second unlock fixes it because the pin_salt DB write
# committed during the first /rotate-vault-kdf; the second unlock's
# /vault-meta returns the post-rotation salt so the client derives
# a matching key. But the FIRST unlock's derive uses the
# pre-rotation salt and the rotate response's re-derive branch is
# fragile — any failure there leaves the client key out of sync
# with the DB, and the very first /chat POST fails
# server-side at `decrypt_message(payload.encrypted_message, key)`
# with "Invalid PIN or corrupted data" (raised in
# vault_core.decrypt_message, mapped to
# InvalidVaultUnlockException on the client).
#
# THIS backend suite locks in the two contracts the frontend fix
# will rely on:
#
#   1. /rotate-vault-kdf ALWAYS returns a valid pin_salt +
#      kdf_iterations for the CURRENT DB row, in BOTH the
#      rotated=true and rotated=false branches. The client can
#      therefore use the response fields as authoritative without
#      gating on the `rotated` flag (which was the fragile step —
#      any client-side type-coercion / null-parse failure caused
#      the guarded re-derive to be silently skipped by the
#      `try { ... } catch (_) {}` wrapper at main.dart:1652-1671).
#
#   2. After a successful rotation, /vault-meta returns the
#      POST-rotation salt/iter. This is the recovery path the
#      client's `refetch /vault-meta after rotate` fix relies on
#      to catch a "server committed but response was malformed"
#      race.
#
# We use the same in-memory PG fake pattern as
# test_auth_login_case_insensitive_2026_07_20 so this runs without
# a real DB.

from __future__ import annotations

import copy
import json
import os
import unittest
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")

# Force a low KDF target so tests aren't dominated by PBKDF2 time.
# vault_core reads this at import time — must be set BEFORE.
os.environ["KDF_TARGET_ITERATIONS"] = "1000"

import vault_core
import durable_personal_memory as dpm
from vault_core import (
    KDF_TARGET_ITERATIONS,
    PIN_VERIFIER_PLAINTEXT,
    decrypt_message,
    derive_key,
    encrypt_message,
    generate_pin_salt,
    rotate_vault_kdf_if_needed,
    verify_vault_pin,
)


# ---------------------------------------------------------------------------
# Minimal in-memory PG fake — only the SQL that vault_core.rotate_vault_kdf_if_needed
# and vault_core.verify_vault_pin issue.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, db: "InMemoryVaultDb") -> None:
        self.db = db
        self._pending: list[dict[str, Any]] = []

    def execute(self, sql: str, params=None) -> None:
        params = params if params is not None else ()
        norm = " ".join(sql.split()).strip().lower()

        # verify_vault_pin's read
        if norm.startswith("select pin_salt, pin_verifier"):
            (vault_id,) = params
            row = self.db.vaults.get(vault_id)
            if row is None:
                self._pending = []
                return
            self._pending = [dict(row)]
            return

        # verify_vault_pin's NOW() lockout check
        if norm.startswith("select now()"):
            self._pending = [{"now": datetime.now(timezone.utc)}]
            return

        # verify_vault_pin's success bookkeeping UPDATE
        if norm.startswith("update vaults set failed_pin_attempts = 0"):
            (vault_id,) = params
            row = self.db.vaults.get(vault_id)
            if row is not None:
                row["failed_pin_attempts"] = 0
                row["locked_until"] = None
            self._pending = []
            return

        # rotate's own initial read
        if norm.startswith("select pin_salt, kdf_iterations from vaults"):
            (vault_id,) = params
            row = self.db.vaults.get(vault_id)
            if row is None:
                self._pending = []
                return
            self._pending = [{
                "pin_salt": row["pin_salt"],
                "kdf_iterations": row["kdf_iterations"],
            }]
            return

        # /vault-meta read
        if norm.startswith("select vault_id, vault_name, pin_salt"):
            (vault_id,) = params
            row = self.db.vaults.get(vault_id)
            if row is None:
                self._pending = []
                return
            self._pending = [{
                "vault_id":       row["vault_id"],
                "vault_name":     row["vault_name"],
                "pin_salt":       row["pin_salt"],
                "total_bytes":    row.get("total_bytes", 0),
                "created_at":     row.get("created_at",
                                          datetime.now(timezone.utc)),
                "kdf_iterations": row["kdf_iterations"],
            }]
            return

        # vault_items scan (rotate re-encrypt loop)
        if norm.startswith("select id, encrypted_data from vault_items"):
            (vault_id,) = params
            items = [it for it in self.db.items.values()
                     if it["vault_id"] == vault_id]
            self._pending = [dict(it) for it in items]
            return

        # uploaded_files scan
        if norm.startswith("select id, encrypted_file_data, extracted_text"):
            (vault_id,) = params
            files = [f for f in self.db.files.values()
                     if f["vault_id"] == vault_id]
            self._pending = [dict(f) for f in files]
            return

        if norm.startswith("select id, payload_ciphertext from vault_ai_memory"):
            (vault_id,) = params
            memories = [
                m for m in self.db.memories.values()
                if m["vault_id"] == vault_id
                and m.get("payload_ciphertext") is not None
                and m.get("memory_key") is None
                and m.get("memory_value") is None
            ]
            self._pending = [dict(m) for m in memories]
            return

        # UPDATE vault_items
        if norm.startswith("update vault_items set encrypted_data"):
            new_data, item_id = params
            self.db.items[item_id]["encrypted_data"] = new_data
            self._pending = []
            return

        # UPDATE uploaded_files
        if norm.startswith("update uploaded_files"):
            self._pending = []
            return

        if norm.startswith("update vault_ai_memory set payload_ciphertext"):
            payload_ct, lookup_hash, memory_id, vault_id = params
            row = self.db.memories.get(memory_id)
            if row is not None and row["vault_id"] == vault_id:
                row["payload_ciphertext"] = payload_ct
                row["memory_lookup_hash"] = lookup_hash
            self._pending = []
            return

        # UPDATE vaults (rotation writeback)
        if norm.startswith("update vaults set pin_salt = %s"):
            new_salt, new_verifier, new_iterations, vault_id = params
            row = self.db.vaults.get(vault_id)
            if row is None:
                self._pending = []
                return
            row["pin_salt"] = new_salt
            row["pin_verifier"] = new_verifier
            row["kdf_iterations"] = new_iterations
            self._pending = []
            return

        raise AssertionError(
            f"unexpected SQL in fake: {norm!r} params={params!r}"
        )

    def fetchone(self):
        return self._pending.pop(0) if self._pending else None

    def fetchall(self):
        rows = list(self._pending)
        self._pending.clear()
        return rows


class _FakeConn:
    def __init__(self, db: "InMemoryVaultDb") -> None:
        self.db = db
        self._cursor = _FakeCursor(db)
        self.committed = False
        self.rolled_back = False

    def cursor(self, *_args, **_kwargs) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        pass


class InMemoryVaultDb:
    def __init__(self) -> None:
        self.vaults: dict[str, dict[str, Any]] = {}
        self.items:  dict[int, dict[str, Any]] = {}
        self.files:  dict[int, dict[str, Any]] = {}
        self.memories: dict[int, dict[str, Any]] = {}


def _add_vault(db: InMemoryVaultDb, *, pin: str,
               iterations: int) -> str:
    vault_id = str(uuid.uuid4())
    salt = generate_pin_salt()
    key = derive_key(pin, salt, iterations=iterations)
    verifier = encrypt_message(PIN_VERIFIER_PLAINTEXT, key)
    db.vaults[vault_id] = {
        "vault_id":       vault_id,
        "vault_name":     "Alexa",
        "pin_salt":       salt,
        "pin_verifier":   verifier,
        "kdf_iterations": iterations,
        "total_bytes":    0,
        "created_at":     datetime.now(timezone.utc),
    }
    return vault_id


class RotateResponseAuthoritativeTests(unittest.TestCase):
    # The core contract the client will rely on.

    def setUp(self) -> None:
        self.db = InMemoryVaultDb()
        self._saved_get_db = vault_core.get_db
        vault_core.get_db = lambda: _FakeConn(self.db)

    def tearDown(self) -> None:
        vault_core.get_db = self._saved_get_db

    def test_rotate_returns_current_salt_iter_when_no_rotation_needed(
        self,
    ) -> None:
        # A vault already at target iterations should report
        # rotated=False AND pin_salt/kdf_iterations reflecting the
        # DB row exactly as-is. The client must be able to trust
        # these fields regardless of the flag.
        vault_id = _add_vault(
            self.db, pin="123456", iterations=KDF_TARGET_ITERATIONS,
        )
        row_before = copy.deepcopy(self.db.vaults[vault_id])

        old_key = verify_vault_pin(vault_id, "123456")
        result = rotate_vault_kdf_if_needed(vault_id, "123456", old_key)

        self.assertEqual(result["rotated"], False)
        self.assertEqual(
            result["pin_salt"], row_before["pin_salt"],
            "rotated=False response must carry the current DB salt "
            "so the client can trust it authoritatively",
        )
        self.assertEqual(
            result["kdf_iterations"], row_before["kdf_iterations"],
            "rotated=False response must carry the current DB "
            "kdf_iterations authoritatively",
        )

    def test_rotate_returns_new_salt_iter_after_rotation(self) -> None:
        # A vault below target iterations gets rotated: the
        # response's pin_salt/kdf_iterations must reflect the
        # NEWLY WRITTEN DB row values, so the client's client-side
        # PBKDF2 with those fields produces a key that matches the
        # server's future re-derive on the next request.
        vault_id = _add_vault(
            self.db, pin="123456",
            iterations=100,  # below target=1000 in this test env
        )
        pre_salt = self.db.vaults[vault_id]["pin_salt"]
        pre_iter = self.db.vaults[vault_id]["kdf_iterations"]

        old_key = verify_vault_pin(vault_id, "123456")
        result = rotate_vault_kdf_if_needed(vault_id, "123456", old_key)

        self.assertTrue(result["rotated"])
        # DB row was rewritten atomically.
        post_row = self.db.vaults[vault_id]
        self.assertNotEqual(post_row["pin_salt"], pre_salt)
        self.assertNotEqual(post_row["kdf_iterations"], pre_iter)
        # Response reflects the NEW row exactly.
        self.assertEqual(result["pin_salt"], post_row["pin_salt"])
        self.assertEqual(
            result["kdf_iterations"], post_row["kdf_iterations"],
        )
        self.assertEqual(
            result["kdf_iterations"], KDF_TARGET_ITERATIONS,
        )

    def test_rotation_reencrypts_ciphertext_personal_memories(self) -> None:
        vault_id = _add_vault(
            self.db, pin="123456", iterations=100,
        )
        old_key = verify_vault_pin(vault_id, "123456")
        payload = {
            "record_type": "personal_memory",
            "canonical_key": "mother:birthday",
            "display_value": "January 30, 1965",
            "normalized_value": "1965-01-30",
            "status": "active",
        }
        old_ciphertext = dpm._encrypted_payload(payload, old_key)
        old_lookup_hash = dpm._lookup_hash(old_key, "mother:birthday")
        self.db.memories[1] = {
            "id": 1,
            "vault_id": vault_id,
            "payload_ciphertext": old_ciphertext,
            "memory_lookup_hash": old_lookup_hash,
            "memory_key": None,
            "memory_value": None,
        }

        result = rotate_vault_kdf_if_needed(vault_id, "123456", old_key)
        self.assertTrue(result["rotated"])

        row = self.db.memories[1]
        self.assertNotEqual(row["payload_ciphertext"], old_ciphertext)
        self.assertNotEqual(row["memory_lookup_hash"], old_lookup_hash)
        self.assertEqual(
            row["memory_lookup_hash"],
            dpm._lookup_hash(result["new_key"], "mother:birthday"),
        )
        ciphertext = row["payload_ciphertext"].decode("utf-8")
        decoded = json.loads(
            decrypt_message(ciphertext, result["new_key"])
        )
        self.assertEqual(decoded["display_value"], "January 30, 1965")
        with self.assertRaises(Exception):
            decrypt_message(ciphertext, old_key)

    def test_key_from_rotate_response_fields_decrypts_new_verifier(
        self,
    ) -> None:
        # THE key invariant. If a client derives PBKDF2 with the
        # rotate response's pin_salt + kdf_iterations, the resulting
        # key MUST decrypt the DB's new pin_verifier. This is what
        # /chat's `verify_vault_pin(vault_id, pin)` implicitly
        # requires — if the client encrypted with a different key,
        # the server's re-derive on the same pin + current DB salt
        # will produce a mismatched key and decrypt_message will
        # raise "Invalid PIN or corrupted data".
        vault_id = _add_vault(
            self.db, pin="123456", iterations=100,
        )
        old_key = verify_vault_pin(vault_id, "123456")
        result = rotate_vault_kdf_if_needed(vault_id, "123456", old_key)
        self.assertTrue(result["rotated"])

        # Client derives with the response's fields.
        client_key = derive_key(
            "123456", result["pin_salt"],
            iterations=result["kdf_iterations"],
        )

        # Server, on the next request, re-derives from the DB
        # (which now has the rotated salt/iter) via verify_vault_pin.
        server_key = verify_vault_pin(vault_id, "123456")

        self.assertEqual(client_key, server_key, (
            "client key derived from rotate response fields MUST "
            "equal server key re-derived from DB. If they diverge, "
            "the first /chat POST will fail with "
            "'Invalid PIN or corrupted data' and the user will see "
            "'unlock session expired'."
        ))


class VaultMetaMatchesDbAfterRotationTests(unittest.TestCase):
    # The second-safety-net contract the client fix relies on: a
    # /vault-meta refetch AFTER /rotate-vault-kdf will report the
    # post-rotation salt/iter. So even if the rotate response were
    # malformed / lost / silently swallowed, the client's refetch
    # gives it authoritative state.

    def setUp(self) -> None:
        self.db = InMemoryVaultDb()
        self._saved_get_db = vault_core.get_db
        vault_core.get_db = lambda: _FakeConn(self.db)

    def tearDown(self) -> None:
        vault_core.get_db = self._saved_get_db

    def test_vault_meta_reads_post_rotation_state(self) -> None:
        vault_id = _add_vault(
            self.db, pin="123456", iterations=100,
        )
        old_key = verify_vault_pin(vault_id, "123456")
        rotate_vault_kdf_if_needed(vault_id, "123456", old_key)

        # Simulate what /vault-meta reads (see main.py:8431).
        conn = vault_core.get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT vault_id, vault_name, pin_salt, total_bytes, "
            "created_at, kdf_iterations FROM vaults WHERE vault_id = %s "
            "LIMIT 1",
            (vault_id,),
        )
        meta_row = cursor.fetchone()

        self.assertIsNotNone(meta_row)
        # Post-rotation authoritative values must be reported.
        db_row = self.db.vaults[vault_id]
        self.assertEqual(meta_row["pin_salt"], db_row["pin_salt"])
        self.assertEqual(
            meta_row["kdf_iterations"], db_row["kdf_iterations"],
        )
        self.assertEqual(
            meta_row["kdf_iterations"], KDF_TARGET_ITERATIONS,
        )


if __name__ == "__main__":
    unittest.main()
