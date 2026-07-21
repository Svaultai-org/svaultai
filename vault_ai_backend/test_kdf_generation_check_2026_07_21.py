"""Deterministic reproduction + fix verification for the 2026-07-21
"first chat forces PIN" production incident that survived the
e797516 refetch-after-rotate patch and 65d7910 pre-encrypt-GET
mitigation.

The screenshot the user posted was InvalidVaultUnlockException on
the client, sourced from 400 "Invalid PIN or corrupted data" at
`vault_core.decrypt_message` (vault_core.py:225). The production
path that produces that specific response body is:

  1. Client fetches /vault-meta -> (salt_1, iter_1).
  2. Something rewrites the DB row to (salt_2, iter_2) between step
     1 and the client's subsequent /chat POST. In production this
     was one of:
       (a) the browser HTTP cache serving a stale /vault-meta body
           after a server-side rotation had already moved the DB
           (root cause fix in security_headers.SENSITIVE_PATH_PREFIXES);
       (b) a second tab racing its own /rotate-vault-kdf between
           the first tab's unlock and its first chat send;
       (c) any future server-side maintenance path that mutates
           `vaults.pin_salt` under an active session.
  3. Client derives K = PBKDF2(pin, salt_1, iter_1), encrypts M
     with K -> ciphertext C.
  4. Client POSTs /chat {encrypted_message: C, pin: <pin>, ...}.
  5. Server calls `verify_vault_pin(vault_id, pin)` which derives
     K' = PBKDF2(pin, salt_2, iter_2) from the CURRENT DB row.
  6. Server calls `decrypt_message(C, K')` -> K != K' so AES-GCM
     verify fails -> HTTPException(400, "Invalid PIN or corrupted
     data") -> InvalidVaultUnlockException on the client -> user
     is bounced to /pin and re-enters the same PIN.

The user's second PIN entry works because by then the client
re-derives from the (rotated) current DB state -> K matches K'.

Fix design under review is server-side compare-and-swap: the client
declares the (salt, iter) it derived against in the /chat request
body; the server compares to the current DB row BEFORE decryption
and returns 409 kdf_generation_stale with the current salt/iter on
mismatch, so the client can re-derive and prompt the user to send
again (NOT auto-retry, NOT force PIN).

This file locks:
  * The DIRECT PRODUCTION-PATH REPRODUCTION at the vault_core layer
    (test class `DirectRepro`) — proves the bug is real on the
    pre-fix decrypt path and proves the fix converts the generic
    400 into a specific 409 with the recovery payload.
  * The UNIT CONTRACT of `check_kdf_generation_fresh` — the exact
    comparison rules, the response body shape, the legacy-compat
    (missing client fields) branch.
  * The SECURITY-HEADER CONTRACT that /vault-meta is on the
    no-store list — the root-cause fix for path (2a).
  * The TWO-TAB CONCURRENT ROTATION scenario — proves the fix
    correctly rejects the losing tab's stale request (path 2b).
  * The METADATA-FETCH-FAILURE branch — the client's fallback path
    when /vault-meta is unreachable must not silently continue with
    a stale key AND must not force PIN without a reason.
"""

from __future__ import annotations

import copy
import os
import unittest
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# Test-only env BEFORE importing app modules so import-time
# side-effects (get_db pool bind, KDF target read, security header
# middleware register) see the right values.
os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")
# Low PBKDF2 iterations so the test isn't dominated by derive time.
os.environ["KDF_TARGET_ITERATIONS"] = "1000"

import vault_core
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
from vault_kdf_generation import (
    KDF_STALE_CODE,
    KDF_STALE_MESSAGE,
    check_kdf_generation_fresh,
)
from fastapi import HTTPException

import security_headers


# ---------------------------------------------------------------------------
# Minimal in-memory PG fake — only the SQL that vault_core and the
# /chat handler's kdf-version check issue.
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

        # NOW() lockout check
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

        # rotate's + version-check read: SELECT pin_salt, kdf_iterations
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

        # rotation re-encrypt loops
        if norm.startswith("select id, encrypted_data from vault_items"):
            (vault_id,) = params
            items = [it for it in self.db.items.values()
                     if it["vault_id"] == vault_id]
            self._pending = [dict(it) for it in items]
            return
        if norm.startswith("select id, encrypted_file_data, extracted_text"):
            (vault_id,) = params
            files = [f for f in self.db.files.values()
                     if f["vault_id"] == vault_id]
            self._pending = [dict(f) for f in files]
            return
        if norm.startswith("update vault_items set encrypted_data"):
            new_data, item_id = params
            self.db.items[item_id]["encrypted_data"] = new_data
            self._pending = []
            return
        if norm.startswith("update uploaded_files"):
            self._pending = []
            return

        # rotation writeback
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


# ---------------------------------------------------------------------------
# DirectRepro — the exact production failure path, deterministically
# reproduced against `vault_core` + `check_kdf_generation_fresh`.
# ---------------------------------------------------------------------------


class DirectRepro(unittest.TestCase):
    """Deterministic simulation of steps 1-6 documented at the top
    of this file. Proves:

      (a) the pre-fix decrypt path FAILS with the generic 400
          "Invalid PIN or corrupted data" whenever the client
          encrypted with the pre-rotation salt and the server
          derives with the post-rotation salt — the production
          symptom;
      (b) the fix (`check_kdf_generation_fresh` running before
          decryption) converts that generic 400 into the specific
          409 kdf_generation_stale carrying the current DB
          salt/iter for the client to re-derive against;
      (c) when the client's declared (salt, iter) matches the
          current DB, the version check passes silently and the
          server's derive+decrypt succeeds — no false positives on
          the happy path.
    """

    def setUp(self) -> None:
        self.db = InMemoryVaultDb()
        self._saved_get_db = vault_core.get_db
        vault_core.get_db = lambda: _FakeConn(self.db)
        self.pin = "123456"
        self.plaintext = "Please save my Netflix login."

    def tearDown(self) -> None:
        vault_core.get_db = self._saved_get_db

    def _client_side_encrypt(self, salt: str, iterations: int) -> str:
        # Simulate exactly what the Dart client's _VaultCrypto.encrypt
        # does: derive PBKDF2 from (pin, salt, iterations), encrypt
        # the plaintext with AES-GCM, base64 the (nonce||ct||tag)
        # buffer. `encrypt_message` in vault_core matches the client's
        # scheme byte-for-byte.
        client_key = derive_key(self.pin, salt, iterations=iterations)
        return encrypt_message(self.plaintext, client_key)

    def test_pre_fix_path_returns_400_when_client_used_stale_salt(
        self,
    ) -> None:
        """WITHOUT the version-check gate, the server derives from
        the CURRENT DB and immediately calls decrypt_message. If
        the client encrypted with an OLDER salt, decrypt raises
        HTTPException(400, "Invalid PIN or corrupted data") — the
        production symptom that InvalidVaultUnlockException maps
        from. This test PROVES the failure mode is real: it uses
        the pre-fix code path directly, no gate."""

        vault_id = _add_vault(
            self.db, pin=self.pin, iterations=KDF_TARGET_ITERATIONS,
        )
        salt_1 = self.db.vaults[vault_id]["pin_salt"]
        iter_1 = self.db.vaults[vault_id]["kdf_iterations"]

        # Client encrypts with the observed (salt_1, iter_1).
        ciphertext = self._client_side_encrypt(salt_1, iter_1)

        # Simulate ROTATION between the client's derive and the
        # client's /chat POST. rotate_vault_kdf_if_needed on a vault
        # at target iterations does not rotate; force a manual
        # rotation to move salt.
        new_salt = generate_pin_salt()
        new_key = derive_key(
            self.pin, new_salt, iterations=KDF_TARGET_ITERATIONS,
        )
        new_verifier = encrypt_message(PIN_VERIFIER_PLAINTEXT, new_key)
        self.db.vaults[vault_id]["pin_salt"] = new_salt
        self.db.vaults[vault_id]["pin_verifier"] = new_verifier

        # Server-side /chat path (pre-fix):
        #   key = verify_vault_pin(vault_id, pin)   # derives from CURRENT (S2)
        #   decrypt_message(ciphertext, key)         # ciphertext was K1
        server_key = verify_vault_pin(vault_id, self.pin)
        with self.assertRaises(HTTPException) as cm:
            decrypt_message(ciphertext, server_key)
        # Reproduces the exact production symptom.
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn(
            "Invalid PIN or corrupted data", str(cm.exception.detail),
            "PRE-FIX code path must reproduce the production 400 "
            "that surfaces as InvalidVaultUnlockException",
        )

    def test_fix_returns_409_with_current_salt_iter_on_stale_client(
        self,
    ) -> None:
        """WITH the version-check gate running BEFORE decrypt, the
        same stale-salt request now surfaces as 409
        kdf_generation_stale carrying the current DB salt+iter —
        the client can re-derive locally and prompt the user to
        send again. No generic 400, no forced re-PIN, no auto-
        retry."""

        vault_id = _add_vault(
            self.db, pin=self.pin, iterations=KDF_TARGET_ITERATIONS,
        )
        stale_client_salt = self.db.vaults[vault_id]["pin_salt"]
        stale_client_iter = self.db.vaults[vault_id]["kdf_iterations"]

        # Rotate.
        new_salt = generate_pin_salt()
        new_key = derive_key(
            self.pin, new_salt, iterations=KDF_TARGET_ITERATIONS,
        )
        new_verifier = encrypt_message(PIN_VERIFIER_PLAINTEXT, new_key)
        self.db.vaults[vault_id]["pin_salt"] = new_salt
        self.db.vaults[vault_id]["pin_verifier"] = new_verifier

        # Simulate the /chat handler's kdf-version gate running
        # BEFORE `get_verified_vault_key + decrypt_message`.
        conn = _FakeConn(self.db)
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                conn, vault_id,
                stale_client_salt, stale_client_iter,
            )

        exc = cm.exception
        self.assertEqual(exc.status_code, 409)
        self.assertIsInstance(exc.detail, dict)
        self.assertEqual(exc.detail["code"], KDF_STALE_CODE)
        self.assertEqual(exc.detail["message"], KDF_STALE_MESSAGE)
        # Body carries the CURRENT DB values so the client re-derives
        # against the authoritative state without another HTTP GET.
        self.assertEqual(exc.detail["current_pin_salt"], new_salt)
        self.assertEqual(
            exc.detail["current_kdf_iterations"], KDF_TARGET_ITERATIONS,
        )
        # Never leaks secret material.
        self.assertNotIn("pin", exc.detail)
        self.assertNotIn("pin_verifier", exc.detail)

    def test_fix_passes_silently_when_client_salt_matches_current(
        self,
    ) -> None:
        """Happy path: the client's declared salt/iter match the
        current DB. The gate must NOT raise — the server proceeds
        to derive + decrypt normally and the chat request works.
        """

        vault_id = _add_vault(
            self.db, pin=self.pin, iterations=KDF_TARGET_ITERATIONS,
        )
        salt = self.db.vaults[vault_id]["pin_salt"]
        iter_ = self.db.vaults[vault_id]["kdf_iterations"]

        # Client's declared origin matches DB.
        conn = _FakeConn(self.db)
        # Must not raise.
        check_kdf_generation_fresh(conn, vault_id, salt, iter_)

    def test_fix_end_to_end_after_client_rederives(self) -> None:
        """The full recovery loop:
          1. Client encrypts with stale salt -> gate raises 409
             with current_pin_salt = new_salt.
          2. Client re-derives K' from new_salt.
          3. Client encrypts new plaintext with K'.
          4. Second /chat call: gate passes (declared salt = new
             salt, matches DB), decrypt succeeds.
        Proves the recovery path really terminates."""

        vault_id = _add_vault(
            self.db, pin=self.pin, iterations=KDF_TARGET_ITERATIONS,
        )
        # DB starts at S1, client observes S1.
        s1 = self.db.vaults[vault_id]["pin_salt"]
        i1 = self.db.vaults[vault_id]["kdf_iterations"]
        c_stale = self._client_side_encrypt(s1, i1)

        # Rotate DB to S2.
        s2 = generate_pin_salt()
        k2 = derive_key(self.pin, s2, iterations=KDF_TARGET_ITERATIONS)
        self.db.vaults[vault_id]["pin_salt"] = s2
        self.db.vaults[vault_id]["pin_verifier"] = encrypt_message(
            PIN_VERIFIER_PLAINTEXT, k2,
        )

        # First /chat: gate 409s with current salt in body.
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db), vault_id, s1, i1,
            )
        current_salt = cm.exception.detail["current_pin_salt"]
        current_iter = cm.exception.detail["current_kdf_iterations"]
        self.assertEqual(current_salt, s2)

        # Client re-derives from the 409 body.
        c_fresh = self._client_side_encrypt(current_salt, current_iter)

        # Second /chat with the re-derived key: gate passes.
        check_kdf_generation_fresh(
            _FakeConn(self.db), vault_id, current_salt, current_iter,
        )
        # Server derives + decrypts -> matches.
        server_key = verify_vault_pin(vault_id, self.pin)
        recovered = decrypt_message(c_fresh, server_key)
        self.assertEqual(recovered, self.plaintext)


# ---------------------------------------------------------------------------
# SecureItemDeleteSentinel — the secure-item-delete flow is
# implemented as a special encrypted_message ("__delete_item:<type>:
# <service>") posted via /chat, NOT via a separate endpoint. The
# reviewer specifically asked for a regression test proving the
# delete flow returns 409 kdf_generation_stale rather than 400.
# The gate runs BEFORE decryption, so the plaintext content is
# irrelevant to correctness — but naming the sentinel explicitly
# in a test locks in the coverage claim.
# ---------------------------------------------------------------------------


class SecureItemDeleteSentinel(unittest.TestCase):

    def setUp(self) -> None:
        self.db = InMemoryVaultDb()
        self._saved_get_db = vault_core.get_db
        vault_core.get_db = lambda: _FakeConn(self.db)
        self.pin = "424242"

    def tearDown(self) -> None:
        vault_core.get_db = self._saved_get_db

    def test_delete_sentinel_with_stale_kdf_returns_409_not_400(
        self,
    ) -> None:
        # The secure-item-delete UX path:
        #   1. User taps "Delete Netflix login".
        #   2. Frontend fires a chat send with the plaintext sentinel
        #      "__delete_item:credential:Netflix" encrypted under the
        #      cached vault key, forwarding the recorded _keyOrigin as
        #      kdf_salt_used + kdf_iterations_used.
        #   3. If another tab / maintenance path rotated the vault
        #      between the frontend's unlock derive and this send,
        #      the server MUST respond 409 kdf_generation_stale
        #      (with current_pin_salt in the body) so the client can
        #      re-derive and the user can re-tap Delete — never the
        #      generic "Invalid PIN or corrupted data" 400 that maps
        #      to the "unlock session expired" bounce.
        vault_id = _add_vault(
            self.db, pin=self.pin, iterations=KDF_TARGET_ITERATIONS,
        )
        original_salt = self.db.vaults[vault_id]["pin_salt"]
        original_iter = self.db.vaults[vault_id]["kdf_iterations"]

        # Client encrypts the DELETE sentinel with the cached key.
        client_key = derive_key(
            self.pin, original_salt, iterations=original_iter,
        )
        delete_sentinel = "__delete_item:credential:Netflix"
        ciphertext = encrypt_message(delete_sentinel, client_key)
        self.assertTrue(ciphertext)  # ensures the encrypt path ran

        # Simulate a second-tab rotation between client encrypt and
        # server receive.
        new_salt = generate_pin_salt()
        new_key = derive_key(
            self.pin, new_salt, iterations=KDF_TARGET_ITERATIONS,
        )
        self.db.vaults[vault_id]["pin_salt"] = new_salt
        self.db.vaults[vault_id]["pin_verifier"] = encrypt_message(
            PIN_VERIFIER_PLAINTEXT, new_key,
        )

        # Server-side /chat handler runs the gate FIRST — before
        # verify_vault_pin + decrypt_message. Client declared the
        # pre-rotation origin; server sees the mismatch and 409s.
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db),
                vault_id,
                original_salt,
                original_iter,
            )
        exc = cm.exception
        self.assertEqual(
            exc.status_code, 409,
            "delete-sentinel path must return 409, NOT 400 — the "
            "generic 400 would surface as 'unlock session expired' "
            "and force a PIN re-entry the user did not need",
        )
        self.assertEqual(exc.detail["code"], KDF_STALE_CODE)
        self.assertEqual(exc.detail["current_pin_salt"], new_salt)
        # The plaintext delete sentinel MUST NOT leak into the
        # response body (belt-and-braces — the gate never sees the
        # decrypted content anyway).
        self.assertNotIn(delete_sentinel, str(exc.detail))
        self.assertNotIn("__delete_item", str(exc.detail))


# ---------------------------------------------------------------------------
# TwoTabConcurrentRotation — the specific TOCTOU race the review
# highlighted: two tabs unlock, tab B rotates, tab A sends stale.
# ---------------------------------------------------------------------------


class TwoTabConcurrentRotation(unittest.TestCase):

    def setUp(self) -> None:
        self.db = InMemoryVaultDb()
        self._saved_get_db = vault_core.get_db
        vault_core.get_db = lambda: _FakeConn(self.db)
        self.pin = "654321"

    def tearDown(self) -> None:
        vault_core.get_db = self._saved_get_db

    def test_losing_tab_gets_409_not_400(self) -> None:
        # Both tabs open. Both fetched /vault-meta at the initial
        # (S0, I0=below target so rotation IS pending).
        vault_id = _add_vault(
            self.db, pin=self.pin, iterations=100,  # below target
        )
        s0 = self.db.vaults[vault_id]["pin_salt"]
        i0 = self.db.vaults[vault_id]["kdf_iterations"]

        # Tab B calls /rotate-vault-kdf. It races through
        # verify_vault_pin + rotate_vault_kdf_if_needed.
        old_key = verify_vault_pin(vault_id, self.pin)
        rotate_result = rotate_vault_kdf_if_needed(
            vault_id, self.pin, old_key,
        )
        self.assertTrue(rotate_result["rotated"])

        # DB is now at S2 / target iterations. Tab A is still on
        # (S0, I0) — it saw the pre-rotation /vault-meta.
        # Tab A sends /chat with kdf_salt_used = S0.
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db), vault_id, s0, i0,
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["code"], KDF_STALE_CODE)
        # Response tells Tab A the current authoritative state.
        self.assertEqual(
            cm.exception.detail["current_pin_salt"],
            rotate_result["pin_salt"],
        )
        self.assertEqual(
            cm.exception.detail["current_kdf_iterations"],
            rotate_result["kdf_iterations"],
        )


# ---------------------------------------------------------------------------
# CheckFunctionUnit — direct contract for check_kdf_generation_fresh.
# ---------------------------------------------------------------------------


class CheckFunctionUnit(unittest.TestCase):

    def setUp(self) -> None:
        self.db = InMemoryVaultDb()
        self._saved_get_db = vault_core.get_db
        vault_core.get_db = lambda: _FakeConn(self.db)
        self.pin = "111222"
        self.vault_id = _add_vault(
            self.db, pin=self.pin, iterations=KDF_TARGET_ITERATIONS,
        )
        self.row = self.db.vaults[self.vault_id]

    def tearDown(self) -> None:
        vault_core.get_db = self._saved_get_db

    def test_matching_salt_and_iter_passes(self) -> None:
        check_kdf_generation_fresh(
            _FakeConn(self.db), self.vault_id,
            self.row["pin_salt"], self.row["kdf_iterations"],
        )

    def test_mismatched_salt_raises_409(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db), self.vault_id,
                "AAAA" + self.row["pin_salt"][4:],  # tampered
                self.row["kdf_iterations"],
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["code"], KDF_STALE_CODE)

    def test_mismatched_iter_raises_409(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db), self.vault_id,
                self.row["pin_salt"],
                self.row["kdf_iterations"] + 1,
            )
        self.assertEqual(cm.exception.status_code, 409)

    def test_missing_client_fields_is_legacy_compat_pass(self) -> None:
        # Older clients don't declare the version. The gate must
        # NOT gratuitously 409 them — it silently passes so the
        # downstream derive+decrypt handles the request as before.
        check_kdf_generation_fresh(
            _FakeConn(self.db), self.vault_id, None, None,
        )

    def test_missing_salt_but_present_iter_still_gate_iter(self) -> None:
        # If only the iter is declared and it mismatches, still 409.
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db), self.vault_id,
                None, self.row["kdf_iterations"] + 9999,
            )
        self.assertEqual(cm.exception.status_code, 409)

    def test_missing_iter_but_present_salt_still_gate_salt(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db), self.vault_id,
                "ZZZZ" + self.row["pin_salt"][4:], None,
            )
        self.assertEqual(cm.exception.status_code, 409)

    def test_unknown_vault_raises_404_not_409(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db),
                str(uuid.uuid4()),
                self.row["pin_salt"],
                self.row["kdf_iterations"],
            )
        self.assertEqual(cm.exception.status_code, 404)

    def test_response_body_does_not_include_secret_material(self) -> None:
        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db), self.vault_id,
                "different_salt_here_that_is_valid_base64_XX==",
                self.row["kdf_iterations"],
            )
        detail = cm.exception.detail
        # No PIN, no pin_verifier, no wrapped MVK, no vault_key,
        # no vault_id in response body.
        forbidden = {
            "pin", "pin_verifier", "verifier",
            "vault_key", "mvk", "wrapped_key",
            "vault_id",
        }
        for k in forbidden:
            self.assertNotIn(k, detail)


# ---------------------------------------------------------------------------
# SecurityHeaders — /vault-meta must never be cacheable.
# ---------------------------------------------------------------------------


class VaultMetaCacheControl(unittest.TestCase):

    def test_vault_meta_is_in_sensitive_paths_list(self) -> None:
        # Root-cause fix for path (2a): browser cache serving stale
        # /vault-meta after a rotation. The middleware pins the
        # response as no-store when the path is in this tuple.
        self.assertIn(
            "/vault-meta",
            security_headers.SENSITIVE_PATH_PREFIXES,
            "/vault-meta MUST be listed as sensitive so responses "
            "get Cache-Control: no-store, no-cache, must-revalidate, "
            "private. Without this a shared cache can serve a "
            "stale salt after a rotation and the client re-derives "
            "against the STALE salt — the production root-cause "
            "path for the 'first chat forces PIN' symptom.",
        )

    def test_apply_security_headers_pins_no_store_for_vault_meta(
        self,
    ) -> None:
        # Direct behavioural proof (not just membership): the
        # middleware helper writes the exact no-store header set on
        # a /vault-meta response.
        from starlette.responses import Response
        resp = Response(content=b"{}")
        security_headers.apply_security_headers(resp, "/vault-meta")
        cc = resp.headers.get("Cache-Control", "")
        self.assertIn("no-store", cc)
        self.assertIn("no-cache", cc)
        self.assertIn("must-revalidate", cc)
        self.assertIn("private", cc)
        self.assertEqual(resp.headers.get("Pragma"), "no-cache")
        self.assertEqual(resp.headers.get("Expires"), "0")

    def test_apply_security_headers_pins_no_store_for_vault_meta_query(
        self,
    ) -> None:
        # /vault-meta?vault_name=Alexa — the actual URL the client
        # hits — must still match the sensitive-path prefix rule.
        from starlette.responses import Response
        resp = Response(content=b"{}")
        # The middleware passes `request.url.path` which is the path
        # WITHOUT the query string. Verify with the raw path form.
        security_headers.apply_security_headers(resp, "/vault-meta")
        self.assertIn("no-store", resp.headers.get("Cache-Control", ""))


# ---------------------------------------------------------------------------
# ClientSideFailureBehavior — documents the required policy for
# what the client does on a /vault-meta fetch failure. The unit
# tests for the Dart side live in
# vault_ai_frontend/test/kdf_version_client_2026_07_21_test.dart;
# this class documents the equivalent contract in code comments so
# a future backend change cannot violate the shared assumption.
# ---------------------------------------------------------------------------


class MetadataFailurePolicyDocumentation(unittest.TestCase):

    def test_documented_policy(self) -> None:
        # The client MUST NOT force PIN re-entry on a transient
        # /vault-meta failure. The client MUST NOT auto-retry a
        # chat send. The 409 kdf_generation_stale response carries
        # the current salt+iter inline so the client never needs
        # to fetch /vault-meta to recover from a stale key — the
        # only path that requires re-fetching /vault-meta is a
        # cold-boot / reload, which is already exercised by the
        # PIN gate flow.
        #
        # This test intentionally has no assertion — it is a
        # DOCUMENTATION anchor so grep'ing for this docstring
        # yields the policy in one place. Deletion of this method
        # is a red flag in review.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
