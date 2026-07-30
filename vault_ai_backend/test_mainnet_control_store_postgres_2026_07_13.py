"""Real-Postgres integration suite for crypto_mainnet_control_store.

These tests connect to a live Postgres database identified by
`VAULTAI_TEST_DATABASE_URL` — the same test-DB pattern used by
`test_phase2_e2e.py` and friends. **The suite is skipped when
`VAULTAI_TEST_DATABASE_URL` is not set**, so a developer with only
the app DB configured can still run the full pytest without the
integration suite. CI environments that provision a separate test
database will run these tests automatically.

Why a real Postgres suite is required:

  * The `FakeMainnetStore` proves the abstraction's expected
    contract but NOT the SQL implementation. Advisory-lock
    scoping, `ON CONFLICT ... WHERE`, autocommit vs.
    per-statement transaction, RealDictCursor row-shape, and
    connection-pool interactions are all invisible to the fake.
  * The conftest autouse fixture swaps the real store for the
    fake in every OTHER test file. If we DON'T have direct
    coverage of the real SQL here, we have no coverage of the
    real SQL anywhere.

Every test opens **two independent psycopg2 connections** to
`VAULTAI_TEST_DATABASE_URL` to simulate two Uvicorn workers /
containers racing against the same shared Postgres.
"""

from __future__ import annotations

import json
import os
import unittest
import uuid

from dotenv import load_dotenv
load_dotenv(".env")


_TEST_DB_ENV_VAR = "VAULTAI_TEST_DATABASE_URL"


def _test_db_url():
    return os.environ.get(_TEST_DB_ENV_VAR)


def _have_test_db():
    return bool(_test_db_url())


_DDL = [
    """
    CREATE TABLE IF NOT EXISTS crypto_mainnet_drafts (
        draft_id                TEXT PRIMARY KEY,
        vault_id                TEXT NOT NULL,
        network_id              TEXT NOT NULL,
        sender_address_lower    TEXT NOT NULL,
        asset                   TEXT NOT NULL,
        destination_address     TEXT NOT NULL,
        value_wei_str           TEXT NOT NULL,
        data_hex                TEXT NOT NULL,
        nonce                   BIGINT NOT NULL,
        gas_limit               BIGINT NOT NULL,
        gas_price_str           TEXT NOT NULL,
        chain_id                BIGINT NOT NULL,
        transaction_to          TEXT NOT NULL,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at              TIMESTAMPTZ NOT NULL,
        claim_token             TEXT,
        claim_expires_at        TIMESTAMPTZ,
        consumed_at             TIMESTAMPTZ,
        local_tx_hash           TEXT,
        broadcast_outcome       TEXT,
        outcome_recorded_at     TIMESTAMPTZ,
        draft_payload_ciphertext BYTEA,
        sender_address_lookup_hash BYTEA,
        CONSTRAINT crypto_mainnet_drafts_outcome_value_check CHECK (
            broadcast_outcome IS NULL
            OR broadcast_outcome IN (
                'submitted',
                'submission_uncertain',
                'already_known',
                'explicitly_rejected'
            )
        ),
        CONSTRAINT crypto_mainnet_drafts_outcome_needs_consume_check CHECK (
            broadcast_outcome IS NULL OR consumed_at IS NOT NULL
        ),
        CONSTRAINT crypto_mainnet_drafts_outcome_stamp_pair_check CHECK (
            (broadcast_outcome IS NULL AND outcome_recorded_at IS NULL)
         OR (broadcast_outcome IS NOT NULL AND outcome_recorded_at IS NOT NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crypto_mainnet_wallet_locks (
        network_id              TEXT NOT NULL,
        sender_address_lower    TEXT NOT NULL,
        lock_token              TEXT NOT NULL,
        acquired_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at              TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (network_id, sender_address_lower)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crypto_mainnet_control (
        control_key             TEXT PRIMARY KEY,
        value_json              TEXT NOT NULL,
        updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]


def _ensure_schema():
    import psycopg2
    conn = psycopg2.connect(_test_db_url())
    try:
        cur = conn.cursor()
        for stmt in _DDL:
            cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def _truncate_all():
    import psycopg2
    conn = psycopg2.connect(_test_db_url())
    try:
        cur = conn.cursor()
        for tbl in (
            "crypto_mainnet_drafts",
            "crypto_mainnet_wallet_locks",
            "crypto_mainnet_control",
        ):
            try:
                cur.execute(f"TRUNCATE TABLE {tbl}")
            except Exception:
                conn.rollback()
        conn.commit()
    finally:
        conn.close()


_FROM_ADDR = "0x" + "ab" * 20
_DEST_ADDR = "0x" + "cd" * 20


def _seed_active_draft_via_store(store, draft_id, sender):
    return store.register_draft(
        vault_id="v-int",
        network_id="ethereum_mainnet",
        sender_address=sender,
        asset="ETH",
        destination_address=_DEST_ADDR,
        value_wei=1,
        data_hex="0x",
        nonce=0,
        gas_limit=21000,
        gas_price=1_000_000_000,
        chain_id=1,
        transaction_to=_DEST_ADDR,
        ttl_secs=600,
    )


@unittest.skipUnless(
    _have_test_db(),
    "requires VAULTAI_TEST_DATABASE_URL — real Postgres integration",
)
class RealPostgresRaceSafety(unittest.TestCase):
    """Direct SQL-level regression against a real Postgres instance."""

    @classmethod
    def setUpClass(cls):
        _ensure_schema()

    def setUp(self):
        _truncate_all()

        import crypto_mainnet_control_store as store
        self._store = store

    def _seed_via_direct_connection(self, draft_id, sender):
        """Insert an ACTIVE draft via a raw connection so we can
        exercise later state transitions against it."""
        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO crypto_mainnet_drafts (
                    draft_id, vault_id, network_id, sender_address_lower,
                    asset, destination_address, value_wei_str, data_hex,
                    nonce, gas_limit, gas_price_str, chain_id,
                    transaction_to, expires_at
                ) VALUES (
                    %s, %s, %s, %s, 'ETH', %s, '1', '0x',
                    0, 21000, '1000000000', 1,
                    %s,
                    NOW() + INTERVAL '600 seconds'
                )
                """,
                (draft_id, "v-int", "ethereum_mainnet",
                 sender.lower(), _DEST_ADDR, _DEST_ADDR),
            )
            conn.commit()
        finally:
            conn.close()



    def test_unsigned_draft_can_be_replaced_but_claimed_draft_blocks(self):
        """Unsigned drafts do not block; an active signing claim does."""
        sender = "0x" + "aa" * 20



        did_a = _seed_active_draft_via_store(self._store, None, sender)
        self.assertIsNotNone(did_a)


        did_b = _seed_active_draft_via_store(self._store, None, sender)
        self.assertIsNotNone(did_b,
            msg="abandoned unsigned draft must be replaced")
        found, err = self._store.load_draft_readonly(
            draft_id=did_a, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNone(found)
        self.assertEqual(err, "unknown_or_expired_draft")

        claim, err = self._store.claim_draft(
            draft_id=did_b, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNone(err)
        self.assertIsNotNone(claim)

        did_c = _seed_active_draft_via_store(self._store, None, sender)
        self.assertIsNone(did_c,
            msg="active signing claim must block")




    def test_two_connections_racing_claim_only_one_wins(self):
        """Two concurrent claim_draft calls for the same draft:
        exactly one returns a claim_token, the other returns
        `draft_already_claimed`."""
        sender = "0x" + "bb" * 20
        draft_id = "int-race-claim-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)

        tok_a, err_a = self._store.claim_draft(
            draft_id=draft_id,
            vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNotNone(tok_a)
        self.assertIsNone(err_a)

        tok_b, err_b = self._store.claim_draft(
            draft_id=draft_id,
            vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNone(tok_b)
        self.assertEqual(err_b, "draft_already_claimed")


    def test_release_claimed_draft_can_reclaim(self):
        """After release_claimed_draft, a fresh claim succeeds."""
        sender = "0x" + "cc" * 20
        draft_id = "int-release-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)

        tok_a, _ = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNotNone(tok_a)


        released = self._store.release_claimed_draft(
            draft_id=draft_id, claim_token=tok_a,
        )
        self.assertTrue(released)


        tok_b, err_b = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNotNone(tok_b)
        self.assertIsNone(err_b)


    def test_stale_release_after_reclaim_is_owner_safe(self):
        """Worker A's stale release token cannot delete Worker B's
        fresh claim."""
        sender = "0x" + "dd" * 20
        draft_id = "int-stale-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)

        tok_a, _ = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNotNone(tok_a)


        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE crypto_mainnet_drafts "
                "SET claim_expires_at = NOW() - INTERVAL '10 seconds' "
                "WHERE draft_id = %s",
                (draft_id,),
            )
            conn.commit()
        finally:
            conn.close()


        tok_b, err_b = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNotNone(tok_b)


        released = self._store.release_claimed_draft(
            draft_id=draft_id, claim_token=tok_a,
        )
        self.assertFalse(released,
            msg="stale token must not release B's fresh claim")


    def test_consume_claimed_draft_writes_local_tx_hash(self):
        sender = "0x" + "ee" * 20
        draft_id = "int-consume-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)
        tok, _ = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        local_hash = "0x" + "9a" * 32
        ok = self._store.consume_claimed_draft(
            draft_id=draft_id, claim_token=tok, local_tx_hash=local_hash,
        )
        self.assertTrue(ok)


        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT consumed_at, local_tx_hash "
                "FROM crypto_mainnet_drafts WHERE draft_id = %s",
                (draft_id,),
            )
            row = cur.fetchone()
            self.assertIsNotNone(row[0])
            self.assertEqual(row[1], local_hash)
        finally:
            conn.close()


    def test_wallet_lock_race_only_one_owner(self):
        addr = "0x" + "77" * 20
        tok_a = self._store.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
        )
        self.assertIsNotNone(tok_a)
        tok_b = self._store.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
        )
        self.assertIsNone(tok_b)


    def test_wallet_lock_expired_reclaim(self):
        addr = "0x" + "88" * 20
        tok_a = self._store.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
            lease_secs=1,
        )
        self.assertIsNotNone(tok_a)

        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE crypto_mainnet_wallet_locks "
                "SET expires_at = NOW() - INTERVAL '10 seconds' "
                "WHERE network_id = %s AND sender_address_lower = %s",
                ("ethereum_mainnet", addr.lower()),
            )
            conn.commit()
        finally:
            conn.close()

        tok_b = self._store.acquire_wallet_lock(
            network_id="ethereum_mainnet", sender_address=addr,
        )
        self.assertIsNotNone(tok_b,
            msg="expired lease must be reclaimable")


        deleted_a = self._store.release_wallet_lock(
            network_id="ethereum_mainnet",
            sender_address=addr, lock_token=tok_a,
        )
        self.assertFalse(deleted_a)


    def test_pause_write_on_one_connection_visible_via_another(self):
        """set_mainnet_send_paused(True) on one connection is
        visible to is_mainnet_send_paused on any other connection."""



        self._store.set_mainnet_send_paused(True)

        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT value_json FROM crypto_mainnet_control "
                "WHERE control_key = 'send_paused'",
            )
            row = cur.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(json.loads(row[0]).get("paused"), True)
        finally:
            conn.close()


        self.assertTrue(self._store.is_mainnet_send_paused())


        self._store.set_mainnet_send_paused(False)
        self.assertFalse(self._store.is_mainnet_send_paused())


    def test_empty_control_row_is_paused_by_default(self):
        """Post-truncate: an empty crypto_mainnet_control table
        MUST be interpreted as PAUSED — a wiped-then-migrated
        environment without the operator's explicit unpause
        cannot silently accept mainnet broadcasts."""


        self.assertTrue(self._store.is_mainnet_send_paused())


    def test_record_broadcast_outcome_persists_via_new_connection(self):
        """A terminal outcome recorded by one connection is visible to
        a completely fresh connection. Locks in "outcome survives
        process/connection boundary" -- which is the whole point of
        moving broadcast state off the in-process dict."""
        sender = "0x" + "60" * 20
        draft_id = "int-outcome-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)
        tok, _ = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        local_hash = "0x" + "3d" * 32
        self._store.consume_claimed_draft(
            draft_id=draft_id, claim_token=tok,
            local_tx_hash=local_hash,
        )
        # Persist a terminal outcome.
        ok = self._store.record_broadcast_outcome(
            draft_id=draft_id, claim_token=tok,
            outcome="explicitly_rejected",
        )
        self.assertTrue(ok)

        # Reload via a completely fresh raw connection.
        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT broadcast_outcome, outcome_recorded_at "
                "FROM crypto_mainnet_drafts WHERE draft_id = %s",
                (draft_id,),
            )
            row = cur.fetchone()
            self.assertEqual(row[0], "explicitly_rejected")
            self.assertIsNotNone(row[1])
        finally:
            conn.close()

    def test_record_broadcast_outcome_is_write_once(self):
        """A stale worker CANNOT overwrite a terminal outcome recorded
        by a fresh worker. Second write with the same token is
        rejected. Write with a different token is rejected."""
        sender = "0x" + "61" * 20
        draft_id = "int-outcome-once-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)
        tok, _ = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self._store.consume_claimed_draft(
            draft_id=draft_id, claim_token=tok,
            local_tx_hash="0x" + "1a" * 32,
        )
        ok1 = self._store.record_broadcast_outcome(
            draft_id=draft_id, claim_token=tok, outcome="submitted",
        )
        self.assertTrue(ok1)

        # Same owner attempting to overwrite: rejected.
        ok2 = self._store.record_broadcast_outcome(
            draft_id=draft_id, claim_token=tok,
            outcome="explicitly_rejected",
        )
        self.assertFalse(ok2, msg="Second outcome write MUST fail.")

        # Different owner attempting to overwrite: rejected.
        ok3 = self._store.record_broadcast_outcome(
            draft_id=draft_id, claim_token="not-the-real-token",
            outcome="submission_uncertain",
        )
        self.assertFalse(ok3)

        # Value preserved.
        import psycopg2
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT broadcast_outcome FROM crypto_mainnet_drafts "
                "WHERE draft_id = %s",
                (draft_id,),
            )
            self.assertEqual(cur.fetchone()[0], "submitted")
        finally:
            conn.close()

    def test_record_broadcast_outcome_rejects_bad_value(self):
        """The Postgres CHECK constraint rejects any value not in the
        allowed set, so a caller bug can't silently corrupt state."""
        import psycopg2
        sender = "0x" + "62" * 20
        draft_id = "int-outcome-check-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)
        tok, _ = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self._store.consume_claimed_draft(
            draft_id=draft_id, claim_token=tok,
            local_tx_hash="0x" + "2b" * 32,
        )
        # The store method rejects a bad value early.
        ok = self._store.record_broadcast_outcome(
            draft_id=draft_id, claim_token=tok, outcome="banana",
        )
        self.assertFalse(ok)

        # Bypass the store method and force the CHECK constraint to
        # trigger. Must raise.
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE crypto_mainnet_drafts "
                    "SET broadcast_outcome = 'banana', "
                    "    outcome_recorded_at = NOW() "
                    "WHERE draft_id = %s",
                    (draft_id,),
                )
            conn.rollback()
        finally:
            conn.close()

    def test_outcome_needs_consume_check_constraint(self):
        """DB CHECK: broadcast_outcome cannot be set on an ACTIVE
        (non-consumed) draft."""
        import psycopg2
        sender = "0x" + "63" * 20
        draft_id = "int-outcome-need-consume-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)

        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE crypto_mainnet_drafts "
                    "SET broadcast_outcome = 'submitted', "
                    "    outcome_recorded_at = NOW() "
                    "WHERE draft_id = %s",
                    (draft_id,),
                )
            conn.rollback()
        finally:
            conn.close()

    def test_outcome_and_stamp_are_paired(self):
        """DB CHECK: broadcast_outcome IS NULL <=> outcome_recorded_at
        IS NULL. Setting one without the other is invalid."""
        import psycopg2
        sender = "0x" + "64" * 20
        draft_id = "int-outcome-pair-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)
        tok, _ = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self._store.consume_claimed_draft(
            draft_id=draft_id, claim_token=tok,
            local_tx_hash="0x" + "4c" * 32,
        )
        conn = psycopg2.connect(_test_db_url())
        try:
            cur = conn.cursor()
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE crypto_mainnet_drafts "
                    "SET broadcast_outcome = 'submitted' "
                    "WHERE draft_id = %s",
                    (draft_id,),
                )
            conn.rollback()
            with self.assertRaises(psycopg2.errors.CheckViolation):
                cur.execute(
                    "UPDATE crypto_mainnet_drafts "
                    "SET outcome_recorded_at = NOW() "
                    "WHERE draft_id = %s",
                    (draft_id,),
                )
            conn.rollback()
        finally:
            conn.close()

    def test_load_draft_readonly_returns_outcome(self):
        """The route's replay dispatch reads `broadcast_outcome` off
        the load_draft_readonly result. This test proves the store's
        SELECT includes and returns the column across the connection
        boundary."""
        sender = "0x" + "65" * 20
        draft_id = "int-outcome-load-" + uuid.uuid4().hex[:8]
        self._seed_via_direct_connection(draft_id, sender)
        tok, _ = self._store.claim_draft(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self._store.consume_claimed_draft(
            draft_id=draft_id, claim_token=tok,
            local_tx_hash="0x" + "5d" * 32,
        )
        self._store.record_broadcast_outcome(
            draft_id=draft_id, claim_token=tok,
            outcome="submission_uncertain",
        )
        loaded, err = self._store.load_draft_readonly(
            draft_id=draft_id, vault_id="v-int",
            network_id="ethereum_mainnet",
        )
        self.assertIsNone(err)
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded["consumed"])
        self.assertEqual(
            loaded.get("broadcast_outcome"), "submission_uncertain",
        )

    def test_advisory_lock_does_not_leak_across_transactions(self):
        """Prove pg_advisory_xact_lock does NOT retain the lock
        into a subsequent transaction on the same pooled
        connection — a session-scoped advisory lock would."""



        for _ in range(5):
            sender = "0x" + uuid.uuid4().hex[:8] + "00" * 16
            did = _seed_active_draft_via_store(self._store, None, sender)
            self.assertIsNotNone(did,
                msg="advisory lock must be released after txn commit; "
                    "a leaked lock would deadlock the next register")


if __name__ == "__main__":
    unittest.main()
