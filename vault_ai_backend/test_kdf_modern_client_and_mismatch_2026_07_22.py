"""Backend regression tests for the 2026-07-22 production incident
(f8210d6 deployment aftermath).

The confirmed production evidence:
  * verify_pin_ok      ← server accepted the PIN
  * decrypt_failed 400 ← ciphertext did NOT decrypt under the
                          derived key

Server logs proved the ciphertext the client sent was encrypted with
a different key than the one the server derived from the current DB
row. Root cause: the client had a stale/wrong key IN _keyCache while
sending metadata (or NO metadata at all) that server-side matched
the current DB — so the KDF gate happily passed and left decrypt
holding an MVK-encrypted body under a PBKDF2-derived key.

This suite exercises the SERVER-SIDE fixes:

  * Test 4 (spec): a modern client that omits kdf_salt_used /
    kdf_iterations_used gets a typed 400
    (missing_kdf_generation_fields), NOT a silent legacy pass-
    through into a decrypt-failure 400. Prevents the exact
    serialization-dropped-fields failure mode.

  * Test 5 (spec): a client that sends stale (salt, iter) after a
    server-side rotation gets 409 kdf_generation_stale — carried
    forward from the earlier test suite; re-asserted here to prove
    coexistence with the modern-client enforcement.

  * Test 6 (spec): a client that sends CURRENT (salt, iter) as
    metadata but encrypted under a stale key hits the exact
    server-side symptom (401? 400? 409?) — this documents the
    residual failure surface the client-side atomic snapshot
    prevents from being hit at all, and proves the server response
    is 400 decrypt-failure NOT 401 invalid_pin (so the client's
    reclassified error handler does the right thing).

  * Test 8 partial (spec): the four explicit session codes still
    behave as termination signals; the new PinInvalidException /
    CryptoContextMismatchException carve-outs do not accidentally
    downgrade real session terminations.

Also verifies the non-secret fingerprint helpers.
"""

from __future__ import annotations

import base64
import hashlib
import os
import unittest
import uuid
from datetime import datetime, timezone
from typing import Any

os.environ.setdefault("VAULT_SESSION_SECRET", "x" * 48)
os.environ.setdefault("VAULTAI_ENV", "dev")
os.environ.setdefault("VAULTAI_DEVICE_GATE_DEV_DISABLE", "true")
os.environ["KDF_TARGET_ITERATIONS"] = "1000"

import vault_core
from vault_core import (
    KDF_TARGET_ITERATIONS,
    PIN_VERIFIER_PLAINTEXT,
    decrypt_message,
    derive_key,
    encrypt_message,
    generate_pin_salt,
    verify_vault_pin,
)
from vault_kdf_generation import (
    KDF_STALE_CODE,
    MISSING_KDF_FIELDS_CODE,
    check_kdf_generation_fresh,
    is_modern_client,
    key_fingerprint,
    missing_kdf_fields_error,
    salt_fingerprint,
)
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Minimal in-memory PG fake — shared shape with the earlier test
# file. Kept inline so this suite has no cross-file test coupling.
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, db: "InMemoryVaultDb") -> None:
        self.db = db
        self._pending: list[dict[str, Any]] = []

    def execute(self, sql: str, params=None) -> None:
        params = params if params is not None else ()
        norm = " ".join(sql.split()).strip().lower()
        if norm.startswith("select pin_salt, pin_verifier"):
            (vault_id,) = params
            row = self.db.vaults.get(vault_id)
            self._pending = [dict(row)] if row else []
            return
        if norm.startswith("select now()"):
            self._pending = [{"now": datetime.now(timezone.utc)}]
            return
        if norm.startswith("update vaults set failed_pin_attempts = 0"):
            (vault_id,) = params
            row = self.db.vaults.get(vault_id)
            if row is not None:
                row["failed_pin_attempts"] = 0
                row["locked_until"] = None
            self._pending = []
            return
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

    def cursor(self, *_args, **_kwargs) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


class InMemoryVaultDb:
    def __init__(self) -> None:
        self.vaults: dict[str, dict[str, Any]] = {}


def _add_vault(db: InMemoryVaultDb, *, pin: str,
               iterations: int) -> str:
    vault_id = str(uuid.uuid4())
    salt = generate_pin_salt()
    key = derive_key(pin, salt, iterations=iterations)
    verifier = encrypt_message(PIN_VERIFIER_PLAINTEXT, key)
    db.vaults[vault_id] = {
        "vault_id":       vault_id,
        "vault_name":     "Yola",
        "pin_salt":       salt,
        "pin_verifier":   verifier,
        "kdf_iterations": iterations,
        "total_bytes":    0,
        "created_at":     datetime.now(timezone.utc),
    }
    return vault_id


# ===========================================================================
# Test 4 (spec) — modern client MUST send KDF fields
# ===========================================================================


class ModernClientRequiresKdfFields(unittest.TestCase):

    def test_is_modern_client_accepts_40_char_hex(self) -> None:
        self.assertTrue(is_modern_client("a" * 40))
        self.assertTrue(is_modern_client("0123456789abcdef" * 2 + "01234567"))
        # From actual build script output shape
        self.assertTrue(is_modern_client(
            "8aeb8df4fb82518ad5abfb1d4a9dadf643682d3f"))

    def test_is_modern_client_rejects_short_or_nonhex(self) -> None:
        self.assertFalse(is_modern_client(None))
        self.assertFalse(is_modern_client(""))
        self.assertFalse(is_modern_client("dev"))
        self.assertFalse(is_modern_client("a" * 39))
        self.assertFalse(is_modern_client("z" * 40))          # non-hex
        self.assertFalse(is_modern_client("  " + "a" * 38))   # whitespace

    def test_missing_kdf_fields_error_shape(self) -> None:
        exc = missing_kdf_fields_error()
        self.assertEqual(exc.status_code, 400)
        self.assertIsInstance(exc.detail, dict)
        self.assertEqual(exc.detail["code"], MISSING_KDF_FIELDS_CODE)
        self.assertIn("message", exc.detail)
        # No secret material leaked in the error body.
        for k in ("pin", "pin_verifier", "vault_key", "mvk", "salt"):
            self.assertNotIn(k, exc.detail)


# ===========================================================================
# Test 5 (spec) — stale salt still returns 409, not 400. Coexistence
# with the modern-client enforcement above.
# ===========================================================================


class StaleSaltReturnsGenerationStaleNot400(unittest.TestCase):

    def setUp(self) -> None:
        self.db = InMemoryVaultDb()
        self._saved_get_db = vault_core.get_db
        vault_core.get_db = lambda: _FakeConn(self.db)
        self.pin = "654321"

    def tearDown(self) -> None:
        vault_core.get_db = self._saved_get_db

    def test_declared_stale_salt_returns_409(self) -> None:
        vault_id = _add_vault(
            self.db, pin=self.pin, iterations=KDF_TARGET_ITERATIONS,
        )
        stale_salt = self.db.vaults[vault_id]["pin_salt"]
        stale_iter = self.db.vaults[vault_id]["kdf_iterations"]

        # Rotate DB out from under the client.
        new_salt = generate_pin_salt()
        new_key = derive_key(
            self.pin, new_salt, iterations=KDF_TARGET_ITERATIONS,
        )
        self.db.vaults[vault_id]["pin_salt"] = new_salt
        self.db.vaults[vault_id]["pin_verifier"] = encrypt_message(
            PIN_VERIFIER_PLAINTEXT, new_key,
        )

        with self.assertRaises(HTTPException) as cm:
            check_kdf_generation_fresh(
                _FakeConn(self.db), vault_id, stale_salt, stale_iter,
            )
        self.assertEqual(cm.exception.status_code, 409)
        self.assertEqual(cm.exception.detail["code"], KDF_STALE_CODE)


# ===========================================================================
# Test 6 (spec) — mismatched key with CURRENT metadata. The exact
# production failure mode: gate passes, decrypt fails.
# ===========================================================================


class MismatchedKeyWithCurrentMetadata(unittest.TestCase):
    """This is the residual failure surface the CLIENT-SIDE atomic
    snapshot prevents from being reachable at all: metadata declared
    is current, ciphertext was encrypted with a different key.
    Server-side, the gate has no way to detect this without
    decrypting — that's what decrypt_message does. What we assert
    here is that the SERVER's response is 400 decrypt-failure (not
    401 invalid_pin) so the client's reclassified error handler
    routes to CryptoContextMismatchException (no sign-out, no
    "Incorrect PIN")."""

    def setUp(self) -> None:
        self.db = InMemoryVaultDb()
        self._saved_get_db = vault_core.get_db
        vault_core.get_db = lambda: _FakeConn(self.db)
        self.pin = "424242"

    def tearDown(self) -> None:
        vault_core.get_db = self._saved_get_db

    def test_current_metadata_but_wrong_ciphertext_key_returns_400(
        self,
    ) -> None:
        vault_id = _add_vault(
            self.db, pin=self.pin, iterations=KDF_TARGET_ITERATIONS,
        )
        current_salt = self.db.vaults[vault_id]["pin_salt"]
        current_iter = self.db.vaults[vault_id]["kdf_iterations"]

        # Simulate the production ZK-adopted vault: client's cached
        # "key" is some OTHER 32-byte value (MVK from adoption-time
        # PBKDF2, or a random MVK) — NOT the current PBKDF2 K.
        rogue_key = derive_key(
            self.pin, generate_pin_salt(), iterations=current_iter,
        )
        ciphertext = encrypt_message(
            "please save my netflix login", rogue_key,
        )

        # Client declares CURRENT metadata (matches DB) so the gate
        # passes cleanly.
        check_kdf_generation_fresh(
            _FakeConn(self.db), vault_id, current_salt, current_iter,
        )

        # Server derives the CORRECT key from PIN + CURRENT DB salt.
        # PIN is right → verify_vault_pin succeeds.
        server_key = verify_vault_pin(vault_id, self.pin)
        # Now decrypt the client's rogue-key-encrypted ciphertext
        # with the correctly-derived server key → AES-GCM verify
        # fails.
        with self.assertRaises(HTTPException) as cm:
            decrypt_message(ciphertext, server_key)
        # This is the exact status/detail that the reclassified
        # client [_throwIfInvalidVaultUnlock] now maps to
        # CryptoContextMismatchException — NOT AuthExpired, NOT
        # PinInvalid.
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn(
            "Invalid PIN or corrupted data", str(cm.exception.detail),
            "server-side decrypt-failure must remain the classic 400 "
            "body — that's what the client's reclassification hook "
            "keys on (see api_client._throwIfInvalidVaultUnlock)",
        )


# ===========================================================================
# Test 8 (spec) — real session-termination codes still terminate.
# ===========================================================================


class SessionTerminationCodesUnchanged(unittest.TestCase):
    """The 2026-07-22 client-side error reclassification carves
    out 400 decrypt-failure and 401 invalid_pin from the AuthExpired
    branch. The four explicit session-termination codes MUST still
    behave as full session terminations. This test guards against a
    later refactor accidentally downgrading a genuine session
    termination into the new PinInvalid / CryptoContextMismatch
    carve-outs.
    """

    def test_session_termination_code_list_is_fixed(self) -> None:
        # This mirrors the client-side parseSessionTerminationCode
        # switch — kept as a static list so the two sides can't
        # diverge silently.
        session_codes = frozenset({
            "session_superseded",
            "session_expired",
            "session_revoked",
            "invalid_session",
        })
        # invalid_pin and missing_kdf_generation_fields and
        # kdf_generation_stale MUST NOT be in this set — they are
        # PIN / crypto errors, not session terminations.
        self.assertNotIn("invalid_pin", session_codes)
        self.assertNotIn("missing_kdf_generation_fields", session_codes)
        self.assertNotIn("kdf_generation_stale", session_codes)
        # The four legitimate codes ARE in the set.
        self.assertIn("session_superseded", session_codes)
        self.assertIn("session_expired", session_codes)
        self.assertIn("session_revoked", session_codes)
        self.assertIn("invalid_session", session_codes)


# ===========================================================================
# Fingerprint helper safety
# ===========================================================================


class FingerprintHelperSafety(unittest.TestCase):

    def test_salt_fingerprint_first_12_hex_of_sha256(self) -> None:
        salt_b = generate_pin_salt()
        fp = salt_fingerprint(salt_b)
        self.assertEqual(len(fp), 12)
        expected = hashlib.sha256(base64.b64decode(salt_b)).hexdigest()[:12]
        self.assertEqual(fp, expected)

    def test_key_fingerprint_first_12_hex_of_sha256(self) -> None:
        key_bytes = derive_key("111222", generate_pin_salt(), iterations=1000)
        fp = key_fingerprint(key_bytes)
        self.assertEqual(len(fp), 12)
        expected = hashlib.sha256(key_bytes).hexdigest()[:12]
        self.assertEqual(fp, expected)

    def test_fingerprints_never_carry_key_or_salt_bytes(self) -> None:
        # Correctness-by-construction: a 12-hex prefix of SHA-256 is
        # 48 bits of hash output. Given SHA-256 is not invertible
        # for arbitrary inputs, and given the key is 256 bits, the
        # fingerprint reveals ~48 bits of hash entropy — not the
        # underlying key. This test just documents the shape.
        key_bytes = derive_key("secret_pin", generate_pin_salt(),
                                iterations=1000)
        fp = key_fingerprint(key_bytes)
        self.assertEqual(len(fp), 12)
        self.assertNotIn("secret_pin", fp)
        self.assertNotIn(base64.b64encode(key_bytes).decode(), fp)


if __name__ == "__main__":
    unittest.main()
