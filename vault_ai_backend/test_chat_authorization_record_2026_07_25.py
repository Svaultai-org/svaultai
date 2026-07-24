"""Tests for AuthorizationRecord — the single-use, atomic-consume
security primitive that prevents replay of a user's confirmation.

Covers:
    * mint & non-consuming read
    * atomic consume validates target_kind, target_id, action,
      vault_id, session_id, expiry, and authorizing_user_turn_id
      — each mismatch returns its typed reason without consuming
    * a valid consume returns consumed=True exactly once
    * a duplicate consume returns not_found (record is gone)
    * expired records refuse and are removed
    * action/target_kind compatibility guard
    * under concurrent threading, exactly one consumer wins the race
"""

from __future__ import annotations

import threading
import unittest

import vault_chat_authorization_record as vauth
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


VAULT = "vault-auth-test"
SESSION = "sess-auth-test"


def _mint_valid(*, action=vauth.AUTH_ACTION_SAVE,
                target_kind=vauth.AUTH_TARGET_DRAFT,
                target_id="draft-123",
                authorizing_user_turn_id="ut-1",
                confidence=0.9,
                ttl_seconds=60,
                now=1_700_000_000.0):
    return vauth.mint_authorization(
        vault_id=VAULT,
        session_id=SESSION,
        target_kind=target_kind,
        target_id=target_id,
        action=action,
        authorizing_user_turn_id=authorizing_user_turn_id,
        preceding_assistant_turn_id="at-1",
        confidence=confidence,
        ttl_seconds=ttl_seconds,
        now=now,
    )


def _consume_ok(rec, *, action=None, target_kind=None,
                target_id=None, session_id=None, vault_id=None,
                authorizing_user_turn_id=None, now=1_700_000_030.0):
    return vauth.atomic_consume_authorization(
        auth_id=rec.auth_id,
        expected_vault_id=vault_id or rec.vault_id,
        expected_session_id=session_id if session_id is not None else rec.session_id,
        expected_target_kind=target_kind or rec.target_kind,
        expected_target_id=target_id or rec.target_id,
        expected_action=action or rec.action,
        expected_authorizing_user_turn_id=(
            authorizing_user_turn_id or rec.authorizing_user_turn_id
        ),
        now=now,
    )


class ConstructionValidationTest(unittest.TestCase):

    def test_action_target_incompatibility_rejected(self):
        # DELETE + DRAFT target is not a valid combination
        with self.assertRaises(ValueError):
            vauth.AuthorizationRecord(
                auth_id="a", vault_id=VAULT, session_id=SESSION,
                target_kind=vauth.AUTH_TARGET_DRAFT,
                target_id="d1",
                action=vauth.AUTH_ACTION_DELETE,
                authorizing_user_turn_id="u1",
                preceding_assistant_turn_id="a1",
                confidence=0.9,
                created_at=1.0, expires_at=61.0,
            )

    def test_confidence_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            vauth.AuthorizationRecord(
                auth_id="a", vault_id=VAULT, session_id=SESSION,
                target_kind=vauth.AUTH_TARGET_DRAFT,
                target_id="d1",
                action=vauth.AUTH_ACTION_SAVE,
                authorizing_user_turn_id="u1",
                preceding_assistant_turn_id="a1",
                confidence=1.5,
                created_at=1.0, expires_at=61.0,
            )


class MintAndReadTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_mint_returns_record_and_persists(self):
        rec = _mint_valid()
        self.assertTrue(rec.auth_id)
        # Read with a `now` inside the record's live window; the
        # helper mints at fixed epoch 1_700_000_000 with 60s TTL,
        # so default read (time.time()) would treat it as expired.
        got = vauth.read_authorization(
            auth_id=rec.auth_id, vault_id=VAULT, now=1_700_000_030.0,
        )
        self.assertIsNotNone(got)
        self.assertEqual(got.target_id, "draft-123")

    def test_read_missing_returns_none(self):
        self.assertIsNone(
            vauth.read_authorization(auth_id="no-such", vault_id=VAULT),
        )


class AtomicConsumeSuccessTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_valid_consume_succeeds_once(self):
        rec = _mint_valid()
        r = _consume_ok(rec)
        self.assertTrue(r.consumed)
        self.assertEqual(r.reason, vauth.REASON_CONSUMED)
        self.assertIsNotNone(r.record)
        self.assertEqual(r.record.auth_id, rec.auth_id)

    def test_second_consume_returns_not_found(self):
        rec = _mint_valid()
        _consume_ok(rec)
        r2 = _consume_ok(rec)
        self.assertFalse(r2.consumed)
        self.assertEqual(r2.reason, vauth.REASON_NOT_FOUND)

    def test_read_after_consume_returns_none(self):
        rec = _mint_valid()
        _consume_ok(rec)
        self.assertIsNone(
            vauth.read_authorization(auth_id=rec.auth_id, vault_id=VAULT),
        )


class MismatchTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_action_mismatch_refuses(self):
        rec = _mint_valid(action=vauth.AUTH_ACTION_SAVE)
        r = _consume_ok(rec, action=vauth.AUTH_ACTION_SAVE_ATTACHMENT)
        self.assertFalse(r.consumed)
        self.assertEqual(r.reason, vauth.REASON_ACTION_MISMATCH)
        # And the record is NOT consumed — the correct consumer can
        # still spend it
        r2 = _consume_ok(rec)
        self.assertTrue(r2.consumed)

    def test_target_kind_mismatch_refuses(self):
        rec = _mint_valid(target_kind=vauth.AUTH_TARGET_DRAFT)
        r = _consume_ok(rec, target_kind=vauth.AUTH_TARGET_PENDING_ACTION)
        self.assertFalse(r.consumed)
        self.assertEqual(r.reason, vauth.REASON_TARGET_KIND_MISMATCH)

    def test_target_id_mismatch_refuses(self):
        rec = _mint_valid(target_id="draft-123")
        r = _consume_ok(rec, target_id="draft-999")
        self.assertFalse(r.consumed)
        self.assertEqual(r.reason, vauth.REASON_TARGET_ID_MISMATCH)

    def test_vault_mismatch_refuses(self):
        rec = _mint_valid()
        r = _consume_ok(rec, vault_id="different-vault")
        self.assertFalse(r.consumed)
        # different vault → different key → not_found (correct: an
        # attacker with a different vault_id cannot even locate the
        # record)
        self.assertEqual(r.reason, vauth.REASON_NOT_FOUND)

    def test_session_mismatch_refuses(self):
        rec = _mint_valid()
        r = _consume_ok(rec, session_id="OTHER_SESSION")
        self.assertFalse(r.consumed)
        self.assertEqual(r.reason, vauth.REASON_SESSION_MISMATCH)

    def test_turn_mismatch_refuses(self):
        rec = _mint_valid(authorizing_user_turn_id="ut-1")
        r = _consume_ok(rec, authorizing_user_turn_id="ut-DIFFERENT")
        self.assertFalse(r.consumed)
        self.assertEqual(r.reason, vauth.REASON_TURN_MISMATCH)


class ExpiryTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_expired_record_refuses_and_removed(self):
        rec = _mint_valid(ttl_seconds=1, now=1000.0)
        r = _consume_ok(rec, now=2000.0)
        self.assertFalse(r.consumed)
        self.assertEqual(r.reason, vauth.REASON_EXPIRED)
        # Subsequent consume: gone
        r2 = _consume_ok(rec, now=2001.0)
        self.assertEqual(r2.reason, vauth.REASON_NOT_FOUND)


class ActionTargetCompatibilityTest(unittest.TestCase):

    def test_save_compatible_with_draft(self):
        self.assertTrue(vauth.is_action_compatible_with_target(
            vauth.AUTH_ACTION_SAVE, vauth.AUTH_TARGET_DRAFT,
        ))

    def test_delete_not_compatible_with_draft(self):
        self.assertFalse(vauth.is_action_compatible_with_target(
            vauth.AUTH_ACTION_DELETE, vauth.AUTH_TARGET_DRAFT,
        ))

    def test_save_attachment_not_compatible_with_draft(self):
        self.assertFalse(vauth.is_action_compatible_with_target(
            vauth.AUTH_ACTION_SAVE_ATTACHMENT, vauth.AUTH_TARGET_DRAFT,
        ))


class ConcurrencyTest(unittest.TestCase):
    """Simulate the same single-consumer semantics under
    concurrency, per design memo §4.5. Uses the in-memory
    backend + module-level threading.Lock in the auth module."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_exactly_one_thread_wins_the_consume_race(self):
        rec = _mint_valid()
        N = 24
        results: list[vauth.ConsumeResult] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(N)

        def worker():
            # All threads line up at the barrier and start together.
            barrier.wait()
            r = _consume_ok(rec)
            with results_lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        consumed = [r for r in results if r.consumed]
        not_found = [r for r in results if r.reason == vauth.REASON_NOT_FOUND]
        # Exactly one consumer sees consumed=True; every other
        # consumer sees not_found (because the record was already
        # deleted by the winner).
        self.assertEqual(len(consumed), 1)
        self.assertEqual(len(not_found), N - 1)


class AuthSchemaVersionTest(unittest.TestCase):
    """Strict schema-version discipline (design memo rev 4)."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_to_json_includes_schema_version(self):
        import json
        rec = _mint_valid()
        payload = json.loads(rec.to_json())
        self.assertEqual(payload["schema_version"], vauth.AUTH_SCHEMA_VERSION)

    def test_from_json_rejects_missing_schema_version(self):
        import json
        rec = _mint_valid()
        payload = json.loads(rec.to_json())
        payload.pop("schema_version", None)
        with self.assertRaises(ValueError):
            vauth.AuthorizationRecord.from_json(json.dumps(payload))

    def test_from_json_rejects_unknown_version(self):
        import json
        rec = _mint_valid()
        payload = json.loads(rec.to_json())
        payload["schema_version"] = 42
        with self.assertRaises(ValueError):
            vauth.AuthorizationRecord.from_json(json.dumps(payload))

    def test_constructor_rejects_unknown_schema_version(self):
        with self.assertRaises(ValueError):
            vauth.AuthorizationRecord(
                auth_id="a", vault_id=VAULT, session_id=SESSION,
                target_kind=vauth.AUTH_TARGET_DRAFT,
                target_id="d1",
                action=vauth.AUTH_ACTION_SAVE,
                authorizing_user_turn_id="u1",
                preceding_assistant_turn_id="a1",
                confidence=0.9,
                created_at=1.0, expires_at=61.0,
                schema_version=99,
            )

    def test_current_version_constant_is_one(self):
        self.assertEqual(vauth.AUTH_SCHEMA_VERSION, 1)


if __name__ == "__main__":
    unittest.main()
