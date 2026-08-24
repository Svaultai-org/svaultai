"""Regression tests for the 2026-07-20 username lookup correction.

Design
------
Client-derived 32-byte identifier

    lookup_v1 = SHA-256(
        b"vaultai.username_lookup.v1|"
        || nfkc_casefolded_utf8_username
    )

No server-side pepper, no HMAC, no VAULTAI_USERNAME_BLIND_INDEX_PEPPER
env var. The server sees only 32 opaque bytes on the wire and
enforces a partial UNIQUE on the non-NULL subset. Same visibility
properties as vault_handle. Legacy random-handle rows retain
username_lookup_v1 = NULL until their owner logs in with the fixed
client (conflict-detected opportunistic backfill).

Coverage in this file
---------------------
* Pure-Python derivation and normalization mirror.
* Request models accept ``username_lookup`` (b64url), reject the
  wrong-length or malformed values.
* Copy invariants for duplicate + auth-failure messages.
* Optional Postgres integration: concurrent duplicate registration
  really produces exactly one row (skipped when no live DB is
  available — the exact command to run it is in the class docstring).
"""

from __future__ import annotations

import base64
import concurrent.futures as cf
import os

import pytest


class TestUsernameLookupV1Derivation:
    def test_derivation_is_deterministic(self):
        from vault_handle import derive_username_lookup_v1
        a = derive_username_lookup_v1("Alexa")
        b = derive_username_lookup_v1("Alexa")
        assert a == b
        assert len(a) == 32

    def test_normalized_variants_of_alexa_all_collide(self):
        """The whole point of the identifier: mixed-case,
        whitespace-padded, or NFKC-decomposed variants of the same
        canonical username produce the SAME 32 bytes. A second
        registration for any of these hits the partial UNIQUE at
        INSERT time and returns 409.
        """
        from vault_handle import derive_username_lookup_v1
        base = derive_username_lookup_v1("Alexa")
        for variant in [
            "alexa",
            "ALEXA",
            "  Alexa  ",
            " alexa ",
            "Alexa ",
            "  ALEXA  ",
        ]:
            assert derive_username_lookup_v1(variant) == base, variant

    def test_visually_distinct_usernames_do_not_collide(self):
        from vault_handle import derive_username_lookup_v1
        a = derive_username_lookup_v1("Alexa")
        b = derive_username_lookup_v1("Alex")
        c = derive_username_lookup_v1("Bob")
        assert len({a, b, c}) == 3

    def test_derivation_is_separate_from_vault_handle(self):
        """The two salts are different on purpose so a future
        change to either derivation does not invalidate accounts
        on the other. Should the two ever collide by accident,
        this test flips.
        """
        from vault_handle import derive_from_username, derive_username_lookup_v1
        handle_bytes = derive_from_username("Alexa")
        lookup_bytes = derive_username_lookup_v1("Alexa")
        # vault_handle is 15 bytes and lookup is 32 bytes; even the
        # first 15 bytes must differ (both are SHA-256 outputs under
        # different domain separators).
        assert lookup_bytes[:15] != handle_bytes


class TestNoPepperEnvVar:
    def test_no_pepper_env_var_referenced(self):
        """The 2026-07-20 first-draft used
        VAULTAI_USERNAME_BLIND_INDEX_PEPPER as a server-side secret.
        The corrected design does not use any env-based pepper.
        This test locks that surface so no future patch reintroduces
        the leaky pattern silently.
        """
        from pathlib import Path
        src = Path(__file__).parent / "routes" / "auth_zk_routes.py"
        text = src.read_text(encoding="utf-8")
        assert "VAULTAI_USERNAME_BLIND_INDEX_PEPPER" not in text
        assert "_compute_username_blind_index" not in text
        assert "_username_blind_index_pepper" not in text
        # Server must never re-normalize a raw username string that
        # arrived on the wire — because such a string must never
        # arrive.
        assert "normalize_username(payload." not in text


class TestRequestModelsCarryUsernameLookup:
    def _valid_b64url_32(self):
        return base64.urlsafe_b64encode(b"\x01" * 32).decode("ascii").rstrip("=")

    def test_zk_register_init_accepts_username_lookup(self):
        from routes.auth_zk_routes import ZkRegisterInitRequest
        req = ZkRegisterInitRequest(
            vault_handle="VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX",
            ke1="AAAA",
            username_lookup=self._valid_b64url_32(),
        )
        assert req.username_lookup == self._valid_b64url_32()

    def test_zk_register_init_no_normalized_username_field(self):
        """The prior draft had a ``normalized_username`` field that
        leaked the raw username to the app server. It must be gone.
        """
        from routes.auth_zk_routes import ZkRegisterInitRequest
        assert "normalized_username" not in ZkRegisterInitRequest.model_fields

    def test_zk_register_finalize_no_normalized_username_field(self):
        from routes.auth_zk_routes import ZkRegisterFinalizeRequest
        assert (
            "normalized_username"
            not in ZkRegisterFinalizeRequest.model_fields
        )

    def test_zk_login_init_no_normalized_username_field(self):
        from routes.auth_zk_routes import ZkLoginInitRequest
        assert "normalized_username" not in ZkLoginInitRequest.model_fields

    def test_zk_login_init_accepts_username_lookup(self):
        from routes.auth_zk_routes import ZkLoginInitRequest
        req = ZkLoginInitRequest(
            vault_handle="VLT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX",
            ke1="AAAA",
            username_lookup=self._valid_b64url_32(),
        )
        assert req.username_lookup == self._valid_b64url_32()


class TestLookupDecoderRejectsBadInput:
    def test_wrong_length_rejected(self):
        from routes.auth_zk_routes import _decode_lookup_v1_or_400
        from fastapi import HTTPException
        # 31 bytes instead of 32.
        raw = base64.urlsafe_b64encode(b"\x00" * 31).decode("ascii").rstrip("=")
        with pytest.raises(HTTPException) as excinfo:
            _decode_lookup_v1_or_400(raw)
        assert excinfo.value.status_code == 400

    def test_correct_length_accepted(self):
        from routes.auth_zk_routes import _decode_lookup_v1_or_400
        raw = base64.urlsafe_b64encode(b"\x00" * 32).decode("ascii").rstrip("=")
        result = _decode_lookup_v1_or_400(raw)
        assert result == b"\x00" * 32

    def test_non_base64_rejected(self):
        from routes.auth_zk_routes import _decode_lookup_v1_or_400
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            _decode_lookup_v1_or_400("!!!not base64!!!")


class TestLegacyRandomHandleLookupRecovery:
    """Username login must reach OPAQUE for pre-index adopted vaults."""

    @staticmethod
    def _row(vault_id: str, vault_name: str) -> dict:
        return {
            "vault_id": vault_id,
            "vault_name": vault_name,
            "vault_handle": b"random-handle",
            "opaque_registration_record": b"opaque-record",
            "username_lookup_v1": None,
        }

    def test_unique_stored_name_match_recovers_legacy_random_handle(self):
        from routes.auth_zk_routes import (
            _match_legacy_username_lookup_candidate,
        )
        from vault_handle import derive_username_lookup_v1

        expected = self._row("vault-expected", "Synthetic Legacy Vault")
        other = self._row("vault-other", "Different Synthetic Vault")
        row, count = _match_legacy_username_lookup_candidate(
            [other, expected],
            derive_username_lookup_v1(" synthetic legacy vault "),
        )

        assert count == 1
        assert row is expected

    def test_nonmatching_lookup_does_not_select_a_vault(self):
        from routes.auth_zk_routes import (
            _match_legacy_username_lookup_candidate,
        )
        from vault_handle import derive_username_lookup_v1

        row, count = _match_legacy_username_lookup_candidate(
            [self._row("vault-other", "Different Synthetic Vault")],
            derive_username_lookup_v1("Synthetic Legacy Vault"),
        )

        assert count == 0
        assert row is None

    def test_canonical_name_collision_fails_closed(self):
        from routes.auth_zk_routes import (
            _match_legacy_username_lookup_candidate,
        )
        from vault_handle import derive_username_lookup_v1

        row, count = _match_legacy_username_lookup_candidate(
            [
                self._row("vault-a", "Synthetic Legacy Vault"),
                self._row("vault-b", "  SYNTHETIC LEGACY VAULT  "),
            ],
            derive_username_lookup_v1("synthetic legacy vault"),
        )

        assert count == 2
        assert row is None

    def test_invalid_stored_name_is_ignored(self):
        from routes.auth_zk_routes import (
            _match_legacy_username_lookup_candidate,
        )
        from vault_handle import derive_username_lookup_v1

        row, count = _match_legacy_username_lookup_candidate(
            [self._row("vault-invalid", "bad\u0000name")],
            derive_username_lookup_v1("Synthetic Legacy Vault"),
        )

        assert count == 0
        assert row is None

    def test_login_init_recovers_then_backfills_before_opaque(self, monkeypatch):
        """Exercise the endpoint order that failed in production.

        The deterministic handle and direct blind-index lookups miss, the
        stored-name compatibility scan finds exactly one complete ZK row, and
        the existing conflict gate backfills the opaque lookup before OPAQUE
        starts with the row's stored random handle.
        """
        import asyncio

        from routes import auth_zk_routes as zk
        from vault_handle import derive_username_lookup_v1, to_display

        lookup = derive_username_lookup_v1("Synthetic Legacy Vault")
        stored_handle = b"\x02" * 15
        stored_record = b"synthetic-opaque-record"
        candidate = {
            "vault_id": "vault-legacy-random-handle",
            "vault_name": "Synthetic Legacy Vault",
            "vault_handle": stored_handle,
            "opaque_registration_record": stored_record,
            "username_lookup_v1": None,
        }

        class FakeCursor:
            def __init__(self, *, lookup_phase: bool):
                self.lookup_phase = lookup_phase
                self.one = None
                self.many = []
                self.backfill_params = None
                self.slot_params = None

            def execute(self, sql, params=None):
                compact = " ".join(sql.split())
                self.one = None
                self.many = []
                if "WHERE vault_handle = %s" in compact:
                    return
                if (
                    "WHERE username_lookup_v1 = %s" in compact
                    and "vault_id <> %s" not in compact
                ):
                    return
                if "WHERE username_lookup_v1 IS NULL" in compact:
                    self.many = [candidate]
                    return
                if "SELECT vault_id FROM vaults" in compact:
                    return
                if "SET username_lookup_v1 = %s" in compact:
                    self.backfill_params = params
                    return
                if "INSERT INTO vault_zk_login_slots" in compact:
                    self.slot_params = params
                    return
                raise AssertionError(f"unexpected SQL: {compact}")

            def fetchone(self):
                return self.one

            def fetchall(self):
                return self.many

        class FakeConnection:
            def __init__(self, cursor):
                self.fake_cursor = cursor
                self.commits = 0
                self.closed = False

            def cursor(self, *args, **kwargs):
                return self.fake_cursor

            def commit(self):
                self.commits += 1

            def close(self):
                self.closed = True

        lookup_cursor = FakeCursor(lookup_phase=True)
        slot_cursor = FakeCursor(lookup_phase=False)
        connections = iter(
            [FakeConnection(lookup_cursor), FakeConnection(slot_cursor)],
        )
        monkeypatch.setattr(zk, "get_db", lambda: next(connections))
        monkeypatch.setattr(zk, "enforce_login_rate_limit", lambda request: None)
        monkeypatch.setattr(zk.secrets, "token_urlsafe", lambda size: "slot-id")

        opaque_call = {}

        def fake_opaque_login_start(record, ke1, credential_id):
            opaque_call.update(
                record=record,
                ke1=ke1,
                credential_id=credential_id,
            )
            return b"ke2", b"server-state"

        monkeypatch.setattr(zk, "opaque_login_start", fake_opaque_login_start)

        request = zk.ZkLoginInitRequest(
            vault_handle=to_display(b"\x01" * 15),
            ke1=base64.urlsafe_b64encode(b"ke1").decode().rstrip("="),
            username_lookup=base64.urlsafe_b64encode(lookup).decode().rstrip("="),
        )
        response = asyncio.run(zk.zk_login_init(request, object()))

        assert response.slot_id == "slot-id"
        assert lookup_cursor.backfill_params == (
            lookup,
            "vault-legacy-random-handle",
        )
        assert opaque_call["record"] == stored_record
        assert opaque_call["ke1"] == b"ke1"
        assert slot_cursor.slot_params[1] == "vault-legacy-random-handle"


class TestCopyInvariants:
    def test_duplicate_username_error(self):
        from routes.auth_zk_routes import DUPLICATE_USERNAME_ERROR
        assert DUPLICATE_USERNAME_ERROR == (
            "That username is already taken. Please choose another."
        )

    def test_generic_auth_error(self):
        from routes.auth_zk_routes import GENERIC_ZK_AUTH_ERROR
        assert GENERIC_ZK_AUTH_ERROR == "Wrong username or PIN."


@pytest.mark.skipif(
    not os.environ.get("VAULTAI_TEST_DATABASE_URL"),
    reason=(
        "Postgres concurrency test needs VAULTAI_TEST_DATABASE_URL. "
        "Run inside the Docker builder stage OR after "
        "\n"
        "    docker run --rm -d --name vaultai-pg-test -e POSTGRES_PASSWORD=t "
        "-p 55432:5432 postgres:16\n"
        "    export VAULTAI_TEST_DATABASE_URL=postgresql://postgres:t@localhost:55432/postgres\n"
        "    alembic -c vault_ai_backend/alembic.ini upgrade head\n"
        "    pytest vault_ai_backend/test_username_blind_index_2026_07_20.py::TestConcurrentRegistration -v"
    ),
)
class TestConcurrentRegistration:
    """Prove that two simultaneous ZK registrations for the SAME
    canonical username produce EXACTLY ONE row — the partial UNIQUE
    on username_lookup_v1 is the atomic authority, not the
    preflight query at zk-register-init.

    Runs only when a real Postgres is reachable via
    VAULTAI_TEST_DATABASE_URL. The Docker builder stage sets this
    up automatically; a local dev run is documented in the skipif
    reason above.
    """

    def test_two_workers_racing_same_username_produce_one_vault(self):
        import psycopg2

        dsn = os.environ["VAULTAI_TEST_DATABASE_URL"]
        lookup_bytes = os.urandom(32)

        def try_insert(handle_suffix: int) -> tuple[bool, str]:
            conn = psycopg2.connect(dsn)
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO accounts (account_id, account_type, sales_channel)
                    VALUES (gen_random_uuid(), 'individual', 'self_service')
                    RETURNING account_id
                    """,
                )
                (account_id,) = cur.fetchone()
                try:
                    cur.execute(
                        """
                        INSERT INTO vaults (
                          vault_id, pin_salt, pin_verifier, kdf_iterations,
                          vault_handle, opaque_registration_record,
                          wrapped_mvk, wrapped_sk_vault, pk_vault_public,
                          display_name_ciphertext,
                          account_id, acknowledged_irrecoverable,
                          vault_name, username_lookup_v1
                        )
                        VALUES (
                          gen_random_uuid(), %s, %s, 600000,
                          %s, %s,
                          %s, %s, %s,
                          %s,
                          %s, TRUE,
                          encode(gen_random_bytes(16),'hex'),
                          %s
                        )
                        """,
                        (
                            "salt", "verifier",
                            # Distinct random handles per attempt so
                            # ONLY the lookup_v1 partial UNIQUE can
                            # be the collision — matching real
                            # concurrent registrations under two
                            # different derivation-version clients.
                            os.urandom(15),
                            os.urandom(64),
                            os.urandom(64), os.urandom(64), os.urandom(32),
                            os.urandom(64),
                            account_id,
                            lookup_bytes,
                        ),
                    )
                    conn.commit()
                    return True, "inserted"
                except psycopg2.errors.UniqueViolation as exc:
                    conn.rollback()
                    return False, str(exc)
            finally:
                conn.close()

        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(try_insert, range(8)))
        successes = [ok for ok, _ in results if ok]
        assert len(successes) == 1, (
            f"expected exactly one row from 8 concurrent inserts, "
            f"got {len(successes)}"
        )

        # Verify only one row survives at rest.
        conn = psycopg2.connect(dsn)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT count(*) FROM vaults WHERE username_lookup_v1 = %s",
                (lookup_bytes,),
            )
            (n,) = cur.fetchone()
            assert n == 1
            cur.execute(
                "DELETE FROM vaults WHERE username_lookup_v1 = %s",
                (lookup_bytes,),
            )
            conn.commit()
        finally:
            conn.close()
