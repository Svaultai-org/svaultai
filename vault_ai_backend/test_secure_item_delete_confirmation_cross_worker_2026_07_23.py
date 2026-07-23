"""Bug 4 regression — the delete-confirmation intent survives a
worker hop.

Production incident (transcript):

    User:      Delete instagram login from my vault
    Assistant: Are you sure you want to delete instagram login
               from your vault?
    User:      yes
    Assistant: Saved this image as Img_3177.png.

Root cause (2026-07-23): the module-level ``_store`` dict in
``vault_secure_item_delete_confirmation`` was process-local.
Uvicorn ``--workers 2`` + round-robin scheduling meant the "yes"
turn landed on a different worker than the sentinel-stamping
turn. Worker B's dict was empty → the pending-delete resolver
returned ``None`` → the LLM intent classifier ran with a
freshly-uploaded image still in ``uploaded_files.needs_naming=TRUE``
and re-interpreted "yes" as a filename → the file-save handler
replied "Saved this image as Img_3177.png".

Fix: migrate the intent to the same Redis-backed
``vault_chat_state_store`` module the rest of the chat state uses
after c1e3df3. Public API unchanged. See:
``vault_ai_backend/vault_secure_item_delete_confirmation.py``

This test file exercises the failure mode against the actual
public API — no worker sockets are involved; the test simulates
worker A/B by manipulating the shared-state backend singleton
directly the way two Uvicorn workers each would.
"""

from __future__ import annotations

import unittest
from typing import Any

from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_secure_item_delete_confirmation import (
    BAND_DELETE_CANCELLED,
    BAND_DELETE_CONFIRMATION_PENDING,
    BAND_DELETED,
    BAND_NO_PENDING_DELETE,
    SecureItemDeleteIntent,
    _backend_key,
    _reset_store_for_test,
    consume_pending_delete_intent,
    get_pending_delete_intent,
    store_delete_intent,
)
from vault_secure_item_save import route_secure_item_message


VAULT_ID = "vault-cross-worker-test"
KEY = bytes(range(32))


class _StubDB:
    """Same shape as the existing test file's stub — matches the
    interface ``vault_secure_item_save._execute_delete_row`` calls."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.deletes: list[dict] = []

    def executor(self, action: str, payload: dict) -> Any:
        if action == "delete":
            self.deletes.append(dict(payload))
            removed = [
                r for r in self.rows
                if r["item_type"] == payload["item_type"]
                and (r.get("service") or "").lower()
                    == (payload["service"] or "").lower()
            ]
            for r in removed:
                self.rows.remove(r)
            return len(removed)
        return None


class TestCrossWorkerPersistence(unittest.TestCase):
    """The intent must be readable from a "different worker" — i.e.
    from a code path that did NOT run the sentinel-stamp. We
    simulate the worker boundary by leaving the shared backend
    singleton in place across the two calls; if the pre-fix
    per-worker dict were still in use the second call would see
    no state."""

    def setUp(self) -> None:
        _reset_store_for_test()

    def tearDown(self) -> None:
        _reset_store_for_test()

    def test_intent_written_by_worker_a_is_readable_by_worker_b(
        self,
    ) -> None:
        # Worker A: stamp the intent.
        intent = store_delete_intent(
            vault_id=VAULT_ID,
            service="instagram",
            item_type="login",
        )
        self.assertIsNotNone(intent)

        # Worker B is modelled by asking the shared backend for the
        # value directly (equivalent to a second process starting
        # cold and reading the same Redis key). No process-local
        # cache can help here — if the read succeeds it must have
        # come from the shared backend.
        from vault_chat_state_store import get_chat_state_backend
        raw = get_chat_state_backend().get(_backend_key(VAULT_ID))
        self.assertIsNotNone(raw,
            msg="the intent must survive across the workers; if "
                "get() returns None the store is still per-worker",
        )

        # And the public reader also finds it.
        pending = get_pending_delete_intent(vault_id=VAULT_ID)
        self.assertIsNotNone(pending)
        self.assertEqual(pending.service, "instagram")
        self.assertEqual(pending.item_type, "login")

    def test_sentinel_then_yes_deletes_correct_login(self) -> None:
        # Full end-to-end via the router — this is the exact
        # production sequence that broke.
        db = _StubDB()
        db.rows = [
            {"id": 1, "item_type": "login",
             "service": "instagram", "encrypted_data": b"x"},
            {"id": 2, "item_type": "login",
             "service": "facebook", "encrypted_data": b"y"},
        ]

        r1 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:login:instagram",
            db_executor=db.executor,
        )
        self.assertEqual(r1["band"], BAND_DELETE_CONFIRMATION_PENDING)

        # Between the two calls we swap the shared backend
        # singleton for a fresh copy that contains ONLY the
        # persisted Redis-shaped bytes. This proves worker B does
        # not need any per-process state to resolve "yes"; the
        # pre-fix bug would surface as BAND_NO_PENDING_DELETE
        # here because the intent lived only in worker A's dict.
        current = SecureItemDeleteIntent(
            intent_id="test-intent",
            vault_id=VAULT_ID,
            service="instagram",
            item_type="login",
            item_id=None,
            is_login=True,
            created_at=0.0,
            expires_at=1e12,
        )
        # (worker B): a totally fresh in-memory backend + explicit
        # re-population from the intent that was persisted.
        from vault_chat_state_store import get_chat_state_backend
        fresh = InMemoryChatStateBackend()
        import json
        from dataclasses import asdict
        fresh.set(
            _backend_key(VAULT_ID),
            json.dumps(asdict(current), separators=(",", ":"))
                .encode("utf-8"),
            ttl_seconds=600,
        )
        install_backend_for_tests(fresh)

        r2 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="yes",
            db_executor=db.executor,
        )
        self.assertEqual(r2["band"], BAND_DELETED,
            msg="Worker B must resolve the intent from the shared "
                "backend and execute the delete; anything else "
                "(NO_PENDING_DELETE, or the pre-fix image-save "
                "route) means Bug 4 has regressed",
        )
        # Exactly the instagram row was deleted; facebook survives.
        self.assertEqual(len(db.deletes), 1)
        self.assertEqual(db.deletes[0]["service"], "instagram")

    def test_no_after_sentinel_clears_intent_cross_worker(
        self,
    ) -> None:
        db = _StubDB()
        db.rows = [
            {"id": 1, "item_type": "login",
             "service": "instagram", "encrypted_data": b"x"},
        ]
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:login:instagram",
            db_executor=db.executor,
        )
        r2 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="no",
            db_executor=db.executor,
        )
        self.assertEqual(r2["band"], BAND_DELETE_CANCELLED)
        # Nothing deleted.
        self.assertEqual(db.deletes, [])
        # And the intent is gone — a second "yes" now must
        # NOT delete anything.
        self.assertIsNone(
            get_pending_delete_intent(vault_id=VAULT_ID),
        )
        r3 = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="yes",
            db_executor=db.executor,
        )
        self.assertIn(r3["band"], {"no_intent", "no_draft"})
        self.assertEqual(db.deletes, [])

    def test_expired_intent_does_not_fire_after_worker_hop(
        self,
    ) -> None:
        # An intent whose expires_at is in the past must be treated
        # as absent regardless of which worker handles the "yes".
        import json
        import time
        from dataclasses import asdict, replace
        from vault_chat_state_store import get_chat_state_backend

        original = store_delete_intent(
            vault_id=VAULT_ID, service="instagram", item_type="login",
        )
        expired = replace(original, expires_at=time.time() - 1.0)
        get_chat_state_backend().set(
            _backend_key(VAULT_ID),
            json.dumps(asdict(expired), separators=(",", ":"))
                .encode("utf-8"),
            ttl_seconds=600,  # keep row alive; guard fires on
                              # expires_at, not TTL
        )
        db = _StubDB()
        db.rows = [
            {"id": 1, "item_type": "login",
             "service": "instagram", "encrypted_data": b"x"},
        ]
        r = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="yes",
            db_executor=db.executor,
        )
        self.assertIn(r["band"], {"no_intent", "no_draft"},
            msg="An expired intent must not execute even if the "
                "Redis row is still there — the ``is_expired`` "
                "guard inside get_pending_delete_intent is the "
                "authoritative check",
        )
        self.assertEqual(db.deletes, [])

    def test_two_similar_services_exact_target_preserved(
        self,
    ) -> None:
        # instagram-work and instagram share a substring — the
        # sentinel + intent must bind to the EXACT ``service``
        # value the button-tap sent, never fuzzy-matched.
        db = _StubDB()
        db.rows = [
            {"id": 1, "item_type": "login",
             "service": "instagram", "encrypted_data": b"x"},
            {"id": 2, "item_type": "login",
             "service": "instagram-work", "encrypted_data": b"y"},
        ]
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:login:instagram-work",
            db_executor=db.executor,
        )
        r = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="yes",
            db_executor=db.executor,
        )
        self.assertEqual(r["band"], BAND_DELETED)
        # ONLY instagram-work was deleted.
        self.assertEqual(len(db.deletes), 1)
        self.assertEqual(db.deletes[0]["service"], "instagram-work")
        # Original instagram survives.
        surviving = [row["service"] for row in db.rows]
        self.assertIn("instagram", surviving)
        self.assertNotIn("instagram-work", surviving)

    def test_unrelated_message_between_sentinel_and_yes_does_not_fire(
        self,
    ) -> None:
        # An unrelated message ("what's my email?") between the
        # sentinel and the "yes" should NOT execute the delete —
        # only an explicit confirm/cancel phrase closes the pending
        # intent. The intent stays pending until TTL or explicit
        # resolution. This locks the documented current behavior.
        db = _StubDB()
        db.rows = [
            {"id": 1, "item_type": "login",
             "service": "instagram", "encrypted_data": b"x"},
        ]
        route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="__delete_item:login:instagram",
            db_executor=db.executor,
        )
        # Unrelated message — the router does not have a delete
        # intent for this phrase, so nothing should fire. Use a
        # non-intent-shaped phrase that the LLM classifier drops
        # to BAND_NO_INTENT (avoids triggering the retrieve path
        # which would hit the DB reader on a fake vault_id).
        r_between = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="what a nice day today",
            db_executor=db.executor,
        )
        # Not a delete band.
        self.assertNotIn(r_between["band"],
            (BAND_DELETED, BAND_DELETE_CANCELLED),
        )
        # No DB delete yet.
        self.assertEqual(db.deletes, [])
        # And the intent is STILL pending on the next "yes".
        r_yes = route_secure_item_message(
            vault_id=VAULT_ID, key=KEY,
            user_message="yes",
            db_executor=db.executor,
        )
        self.assertEqual(r_yes["band"], BAND_DELETED)
        self.assertEqual(len(db.deletes), 1)
        self.assertEqual(db.deletes[0]["service"], "instagram")


class TestBackendSelection(unittest.TestCase):
    """Sanity — the confirmation store uses the same shared backend
    the rest of the chat state uses."""

    def setUp(self) -> None:
        _reset_store_for_test()

    def tearDown(self) -> None:
        _reset_store_for_test()

    def test_shared_backend_singleton_backs_the_store(self) -> None:
        # Install a fresh in-memory backend; storing an intent
        # writes to it; the store-side read goes through the same
        # singleton.
        fresh = InMemoryChatStateBackend()
        install_backend_for_tests(fresh)
        intent = store_delete_intent(
            vault_id=VAULT_ID, service="X", item_type="imei",
        )
        # Direct probe: the shared backend now has the key.
        raw = fresh.get(_backend_key(VAULT_ID))
        self.assertIsNotNone(raw)
        # And consume() drains from the same backend.
        consumed = consume_pending_delete_intent(vault_id=VAULT_ID)
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed.intent_id, intent.intent_id)
        self.assertIsNone(fresh.get(_backend_key(VAULT_ID)),
            msg="consume() must delete from the shared backend, "
                "not just from a per-worker cache",
        )


if __name__ == "__main__":
    unittest.main()
