"""Regression tests for the 2026-07-24 production-readiness fix
that closes the residual stale-attachment path in the legacy
save cascade.

Prior to this fix, the legacy save cascade in ``main.py:13624``
called ``get_pending_named_file(vault_id)`` directly. That call
returned any ``uploaded_files.needs_naming=TRUE`` row for the
vault, regardless of whether the row was owned by the current
session or bound by a fresh upload binding. Combined with the
narrow "save this" / "save it" / "save now" confirm regex, an
explicit save phrase from an unrelated context could still
auto-save a stale unnamed file.

The fix wraps ``get_pending_named_file`` in a session/binding-
scoped helper (``get_pending_named_file_for_session``) and
replaces every chat-endpoint caller so the DB row is only
returned when:

    * a fresh (<= 5 min) upload binding exists in the shared
      chat-state store,
    * the binding belongs to the caller's session_id (the same
      auth token that produced the chat request),
    * the binding was for THIS specific file_id,
    * the row is still eligible (needs_naming = TRUE, and the
      binding lookup didn't return None because
      resolve_active_upload lazily verifies liveness).

This test file locks all nine required regression scenarios.
"""

from __future__ import annotations

import time
import unittest
from typing import Optional
from unittest import mock

from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)
from vault_chat_upload_binding import (
    ATTACHMENT_BINDING_TTL_SECONDS,
    bind_upload,
    clear_binding,
)


VAULT_A = "vault-save-cascade-A"
VAULT_B = "vault-save-cascade-B"
SESSION_A = "sess-A"
SESSION_B = "sess-B"


# --------------------------------------------------------------------
# Fixture: mock main.get_pending_named_file so we can simulate DB rows
# without hitting Postgres. All tests exercise the WRAPPER
# get_pending_named_file_for_session, which internally calls the
# mocked base function.
# --------------------------------------------------------------------

class _RowFixture:
    """Stub for main.get_pending_named_file. Multiple rows may
    coexist in the fake DB; the newest one is returned to match
    the real SELECT ... ORDER BY created_at DESC LIMIT 1."""
    def __init__(self):
        self.rows_by_vault: dict[str, list[dict]] = {}

    def add_row(self, vault_id: str, file_id: str,
                file_name: str = "attachment",
                content_type: str = "image/jpeg",
                needs_naming: bool = True):
        rows = self.rows_by_vault.setdefault(vault_id, [])
        rows.append({
            "id": file_id,
            "file_name": file_name,
            "content_type": content_type,
            "created_at": time.time() + len(rows) * 0.001,
            "needs_naming": needs_naming,
            "upload_status": "complete",
        })

    def newest_pending(self, vault_id: str) -> Optional[dict]:
        rows = [
            r for r in self.rows_by_vault.get(vault_id, [])
            if r.get("needs_naming")
        ]
        if not rows:
            return None
        return sorted(rows, key=lambda r: r["created_at"])[-1]


class _CascadeGuardTestBase(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        self.fixture = _RowFixture()
        # Patch main.get_pending_named_file (the base DB read) so
        # we don't need Postgres. The wrapper we're testing goes
        # through main.get_pending_named_file_for_session which
        # calls the base function.
        import main as _m
        self._m = _m
        self._patcher = mock.patch.object(
            _m, "get_pending_named_file",
            side_effect=lambda vault_id: self.fixture.newest_pending(vault_id),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        reset_chat_state_backend_for_tests()

    def _guarded_lookup(self, vault_id: str, session_id: Optional[str]):
        return self._m.get_pending_named_file_for_session(
            vault_id, session_id,
        )


# ====================================================================
# 1. An old unbound needs_naming=TRUE upload cannot be saved with
#    "save this". The wrapper returns None when no binding exists.
# ====================================================================

class TestUnboundStaleRowRefused(_CascadeGuardTestBase):

    def test_stale_row_without_any_binding_is_not_returned(self):
        # A row exists in the DB but there's no upload binding.
        self.fixture.add_row(
            VAULT_A, "file-old", "old_photo.jpg", "image/jpeg",
        )
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        # The wrapper refuses to hand the row to the save cascade.
        self.assertIsNone(result)

    def test_stale_row_without_binding_still_readable_by_base_fn(self):
        # Sanity: the base function still returns the row. The
        # WRAPPER is what filters it out. This ensures we haven't
        # accidentally broken the base helper.
        self.fixture.add_row(
            VAULT_A, "file-old", "old_photo.jpg", "image/jpeg",
        )
        raw = self._m.get_pending_named_file(VAULT_A)
        self.assertIsNotNone(raw)
        self.assertEqual(raw["id"], "file-old")


# ====================================================================
# 2. A binding from another session cannot authorize a save.
# ====================================================================

class TestCrossSessionBindingRefused(_CascadeGuardTestBase):

    def test_binding_from_another_session_does_not_authorize(self):
        # File was uploaded and bound by session A.
        self.fixture.add_row(
            VAULT_A, "file-A", "photo.jpg", "image/jpeg",
        )
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="turn-1", uploaded_file_id="file-A",
            filename="photo.jpg", content_type="image/jpeg",
        )
        # Session B tries to save-cascade.
        result = self._guarded_lookup(VAULT_A, SESSION_B)
        self.assertIsNone(result)

    def test_binding_visible_only_to_stamping_session(self):
        # Same setup, but session A should still see the row.
        self.fixture.add_row(
            VAULT_A, "file-A", "photo.jpg", "image/jpeg",
        )
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="turn-1", uploaded_file_id="file-A",
            filename="photo.jpg", content_type="image/jpeg",
        )
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "file-A")


# ====================================================================
# 3. An expired upload binding cannot authorize a save.
# ====================================================================

class TestExpiredBindingRefused(_CascadeGuardTestBase):

    def test_expired_binding_is_invisible_to_wrapper(self):
        # Bind an upload, then force the binding to be past its
        # freshness window by monkey-patching resolve_active_upload
        # to inspect a future clock. In real production this
        # happens automatically once ATTACHMENT_BINDING_TTL_SECONDS
        # elapses.
        self.fixture.add_row(
            VAULT_A, "file-A", "photo.jpg", "image/jpeg",
        )
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="turn-1", uploaded_file_id="file-A",
            filename="photo.jpg", content_type="image/jpeg",
        )
        # Verify the wrapper returns the row NOW.
        self.assertIsNotNone(
            self._guarded_lookup(VAULT_A, SESSION_A),
            "sanity: fresh binding should be honored",
        )
        # Advance time past the TTL by patching resolve_active_upload
        # to force a max_age_seconds check that the current binding
        # cannot satisfy.
        with mock.patch(
            "vault_chat_upload_binding.resolve_active_upload",
            side_effect=lambda **kw: None,
        ):
            result = self._guarded_lookup(VAULT_A, SESSION_A)
            self.assertIsNone(result)

    def test_ttl_matches_documented_5_minute_window(self):
        # Not strictly a save-cascade test, but locks the TTL the
        # wrapper implicitly relies on.
        self.assertEqual(ATTACHMENT_BINDING_TTL_SECONDS, 300)


# ====================================================================
# 4. A binding for another uploaded file cannot authorize a stale row.
# ====================================================================

class TestFileMismatchRefused(_CascadeGuardTestBase):

    def test_binding_for_different_file_refuses_stale_row(self):
        # Newest DB row is for file-B; binding is for file-A.
        self.fixture.add_row(
            VAULT_A, "file-A-old", "old.jpg", "image/jpeg",
        )
        self.fixture.add_row(
            VAULT_A, "file-B-new", "new.jpg", "image/jpeg",
        )
        # Binding covers ONLY file-A-old.
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="turn-1", uploaded_file_id="file-A-old",
            filename="old.jpg", content_type="image/jpeg",
        )
        # get_pending_named_file returns file-B-new (newest); the
        # binding is for file-A-old; wrapper refuses because the
        # bound file id and the DB row id do not match.
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        self.assertIsNone(result)


# ====================================================================
# 5. A valid current-session upload binding still allows the normal
#    attachment-save flow.
# ====================================================================

class TestNormalFlowStillWorks(_CascadeGuardTestBase):

    def test_fresh_session_bound_upload_returns_row(self):
        self.fixture.add_row(
            VAULT_A, "file-fresh", "photo.jpg", "image/jpeg",
        )
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="turn-1", uploaded_file_id="file-fresh",
            filename="photo.jpg", content_type="image/jpeg",
        )
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "file-fresh")
        self.assertEqual(result["file_name"], "photo.jpg")


# ====================================================================
# 6. Multiple stale unnamed uploads cannot cause the wrong attachment
#    to be selected.
# ====================================================================

class TestMultipleStaleUploadsCannotBeConfused(_CascadeGuardTestBase):

    def test_multiple_stale_unbound_rows_all_refused(self):
        # Three stale rows in DB, no binding.
        for i in range(3):
            self.fixture.add_row(
                VAULT_A, f"stale-{i}", f"stale{i}.jpg", "image/jpeg",
            )
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        self.assertIsNone(result)

    def test_binding_only_authorizes_its_file_when_others_exist(self):
        # Two stale rows and one properly bound row.
        self.fixture.add_row(
            VAULT_A, "stale-1", "s1.jpg", "image/jpeg",
        )
        self.fixture.add_row(
            VAULT_A, "stale-2", "s2.jpg", "image/jpeg",
        )
        self.fixture.add_row(
            VAULT_A, "bound-3", "b3.jpg", "image/jpeg",
        )
        # Bind only "bound-3".
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="turn-1", uploaded_file_id="bound-3",
            filename="b3.jpg", content_type="image/jpeg",
        )
        # The DB helper returns the newest row, which is "bound-3"
        # (last added), and the binding matches → row is returned.
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "bound-3")

    def test_binding_older_than_newest_stale_row_refused(self):
        # Binding was for an OLDER file, but a newer stale row has
        # been added since. Wrapper refuses because the newest
        # needs_naming row does not match the binding's file id.
        self.fixture.add_row(
            VAULT_A, "bound-old", "old.jpg", "image/jpeg",
        )
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="turn-1", uploaded_file_id="bound-old",
            filename="old.jpg", content_type="image/jpeg",
        )
        # Later a NEW stale row appears in the DB (e.g. another
        # upload path added it without a binding).
        self.fixture.add_row(
            VAULT_A, "new-stale", "unbound.jpg", "image/jpeg",
        )
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        # get_pending_named_file returns the NEWER "new-stale"
        # row; the binding is for the OLDER "bound-old" row —
        # mismatch, refuse.
        self.assertIsNone(result)


# ====================================================================
# 7. The original delete-confirmation protections remain unchanged.
# ====================================================================

class TestDeleteConfirmationUnchanged(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_delete_intent_store_still_works_end_to_end(self):
        from vault_secure_item_delete_confirmation import (
            consume_pending_delete_intent, get_pending_delete_intent,
            store_delete_intent,
        )
        # Sentinel-style stamping still stores the intent.
        stamped = store_delete_intent(
            vault_id="vault-del", service="Instagram",
            item_type="login",
        )
        self.assertIsNotNone(stamped)
        # Get returns the same intent.
        got = get_pending_delete_intent(vault_id="vault-del")
        self.assertIsNotNone(got)
        self.assertEqual(got.intent_id, stamped.intent_id)
        # Consume returns it and clears the store.
        consumed = consume_pending_delete_intent(vault_id="vault-del")
        self.assertIsNotNone(consumed)
        self.assertIsNone(get_pending_delete_intent(vault_id="vault-del"))


# ====================================================================
# 8. The bare yes/no destructive safety fallback still passes.
# ====================================================================

class TestSafetyFallbackUnchanged(unittest.TestCase):
    """Locks that the deterministic safety classifier from Phase I
    still resolves bare confirmations and cancellations. This
    ensures the residual-path fix here did not perturb the
    Phase I safety layer."""

    def test_bare_yes_recognized(self):
        from vault_chat_destructive_safety_fallback import (
            SAFETY_CONFIRM, classify_destructive_message,
        )
        for phrase in ("yes", "yeah", "yep", "yup", "ok", "confirm"):
            self.assertEqual(
                classify_destructive_message(phrase), SAFETY_CONFIRM,
                f"{phrase!r} must still be SAFETY_CONFIRM",
            )

    def test_bare_no_recognized(self):
        # The Phase I classifier is intentionally narrow: bare
        # single-word negations + short synonyms. Compound forms
        # like "never mind" are the semantic decider's job; when
        # the decider is unavailable, they fall through to the
        # clarification prompt (which is safer than guessing).
        from vault_chat_destructive_safety_fallback import (
            SAFETY_CANCEL, classify_destructive_message,
        )
        for phrase in ("no", "nope", "cancel", "don't", "stop", "nah"):
            self.assertEqual(
                classify_destructive_message(phrase), SAFETY_CANCEL,
                f"{phrase!r} must still be SAFETY_CANCEL",
            )

    def test_unclear_still_returns_unclear(self):
        from vault_chat_destructive_safety_fallback import (
            SAFETY_UNCLEAR, classify_destructive_message,
        )
        for phrase in ("kinda yes maybe", "hi there", "delete my chase login"):
            self.assertEqual(
                classify_destructive_message(phrase), SAFETY_UNCLEAR,
                f"{phrase!r} must still be SAFETY_UNCLEAR",
            )


# ====================================================================
# 9. The previous video-hijack regression is still closed.
# ====================================================================

class TestVideoHijackStillClosed(_CascadeGuardTestBase):

    def test_stale_video_row_cannot_be_saved_by_save_this(self):
        # This is the exact incident timeline. A video was uploaded
        # in some earlier session (or expired session), leaving a
        # needs_naming=TRUE row. In a later chat turn from a fresh
        # session the user types "save this" (which still matches
        # the narrow legacy confirm regex).
        #
        # BEFORE this fix: main.py:13624 called
        # get_pending_named_file(vault_id) and would have found the
        # stale video row and auto-saved it as "Video_XXXXX.webm".
        #
        # AFTER this fix: the wrapper refuses because no fresh
        # session-scoped binding exists for the stale video.
        self.fixture.add_row(
            VAULT_A, "video-stale", "Video_1784619049782.webm",
            "video/webm",
        )
        # No binding for this file (or any other) in this session.
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        self.assertIsNone(
            result,
            "video-hijack path must remain closed — stale unnamed "
            "video must not be returned to the save cascade",
        )

    def test_video_hijack_closed_even_when_binding_is_for_other_file(self):
        # Belt-and-braces: even if some OTHER binding exists for
        # this session (an unrelated file the user really wanted
        # to save), the stale video row cannot piggyback on it.
        self.fixture.add_row(
            VAULT_A, "video-stale", "Video_1784619049782.webm",
            "video/webm",
        )
        self.fixture.add_row(
            VAULT_A, "wanted-photo", "beach.jpg", "image/jpeg",
        )
        bind_upload(
            vault_id=VAULT_A, session_id=SESSION_A,
            turn_id="turn-photo", uploaded_file_id="wanted-photo",
            filename="beach.jpg", content_type="image/jpeg",
        )
        # get_pending_named_file returns the newest row, which is
        # "wanted-photo"; the binding matches; wrapper returns it.
        # Critically the STALE VIDEO row is not returned. The user
        # gets what they asked for (beach.jpg), not the hijack.
        result = self._guarded_lookup(VAULT_A, SESSION_A)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "wanted-photo")
        self.assertNotIn("Video_", result["file_name"])


if __name__ == "__main__":
    unittest.main()
