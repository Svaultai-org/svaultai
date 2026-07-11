"""Pagination + stable-ID disambiguation for the 2026-07-12 fixes.

Covers:

  * File list pagination is deterministic — no duplicates or skips
    across pages regardless of ties on `created_at`.
  * The "show more" pronoun follow-up recognizes the intent.
  * The active-entity system accepts ENTITY_FILE_LIST + ACTION_MORE
    so the follow-up dispatcher can pass its ``entity_matches_action``
    guard.
  * ChatRequest accepts a ``selection_hint`` field so a row tap can
    pin a specific login/file id without embedding it in prose.
  * ``_fetch_vault_items(item_id=...)`` bypasses the ILIKE search and
    returns exactly the requested row — the ID-based disambiguation
    path used when two rows share a title.
"""

from __future__ import annotations

import datetime as _dt
import json
import unittest

from main import (
    _build_vault_file_list_envelope,
    _sort_files_for_pagination,
    ChatRequest,
)
from vault_chat_active_entity import (
    ACTION_MORE,
    ALLOWED_ACTIONS,
    ENTITY_FILE_LIST,
    ENTITY_TYPES,
    _reset_store_for_test,
    entity_matches_action,
    get_active_entity,
    set_active_entity,
)
from vault_chat_pronoun_followup import detect_pronoun_followup


def _rows(n, tie_all_at_zero=False):
    """Return n uploaded_files-shaped rows. If ``tie_all_at_zero`` is
    True, all rows share the same created_at so the sort has to
    tie-break on id — the exact case that could cause
    non-deterministic pagination."""
    ts = _dt.datetime(2026, 7, 12, 10, 0, 0)
    return [
        {
            "id": f"id{i:04d}",
            "file_name": f"f{i}.pdf",
            "content_type": "application/pdf",
            "file_size": 1000,
            "created_at": ts if tie_all_at_zero
                          else _dt.datetime(2026, 7, 12, 10, i % 60, 0),
        }
        for i in range(n)
    ]


class FileListPaginationBoundaries(unittest.TestCase):

    def _env(self, rows, **kw):
        return json.loads(_build_vault_file_list_envelope(rows, "t", **kw))

    def test_zero_files(self):
        env = self._env([])
        self.assertEqual(env["count"], 0)
        self.assertEqual(env["total_count"], 0)
        self.assertFalse(env["has_more"])
        self.assertEqual(env["next_offset"], 0)

    def test_fewer_than_25(self):
        env = self._env(_rows(10))
        self.assertEqual(env["count"], 10)
        self.assertEqual(env["total_count"], 10)
        self.assertFalse(env["has_more"])

    def test_exactly_25(self):
        env = self._env(_rows(25))
        self.assertEqual(env["count"], 25)
        self.assertEqual(env["total_count"], 25)
        self.assertEqual(env["next_offset"], 25)
        self.assertFalse(env["has_more"])

    def test_more_than_25(self):
        env = self._env(_rows(26))
        self.assertEqual(env["count"], 25)
        self.assertEqual(env["total_count"], 26)
        self.assertEqual(env["next_offset"], 25)
        self.assertTrue(env["has_more"])

    def test_page_2_returns_remaining(self):
        env = self._env(_rows(50), offset=25)
        self.assertEqual(env["count"], 25)
        self.assertEqual(env["offset"], 25)
        self.assertEqual(env["next_offset"], 50)
        self.assertFalse(env["has_more"])

    def test_end_of_results(self):
        env = self._env(_rows(50), offset=50)
        self.assertEqual(env["count"], 0)
        self.assertFalse(env["has_more"])

    def test_pages_never_overlap_or_skip(self):
        rows = _rows(75)
        p1 = self._env(rows, offset=0)
        p2 = self._env(rows, offset=25)
        p3 = self._env(rows, offset=50)
        ids1 = [f["file_id"] for f in p1["files"]]
        ids2 = [f["file_id"] for f in p2["files"]]
        ids3 = [f["file_id"] for f in p3["files"]]
        self.assertEqual(len(set(ids1) & set(ids2)), 0)
        self.assertEqual(len(set(ids2) & set(ids3)), 0)
        self.assertEqual(len(set(ids1) & set(ids3)), 0)
        # All 75 ids covered without a gap.
        all_ids = set(ids1) | set(ids2) | set(ids3)
        self.assertEqual(len(all_ids), 75)

    def test_pagination_deterministic_when_created_at_ties(self):
        """When every row shares created_at, the tie-break on id keeps
        the order stable — running the same slice twice yields the
        same ids."""
        rows = _rows(60, tie_all_at_zero=True)
        p1 = self._env(rows, offset=0)
        p2 = self._env(rows, offset=0)  # same call
        self.assertEqual(
            [f["file_id"] for f in p1["files"]],
            [f["file_id"] for f in p2["files"]],
        )
        # And pages across the same tied set are non-overlapping.
        p1_ids = {f["file_id"] for f in p1["files"]}
        p2_ids = {f["file_id"] for f in self._env(rows, offset=25)["files"]}
        self.assertEqual(len(p1_ids & p2_ids), 0)


class ShowMorePronoun(unittest.TestCase):
    def test_show_more(self):
        self.assertEqual(
            detect_pronoun_followup("show more"), {"verb": "more"},
        )

    def test_more(self):
        self.assertEqual(
            detect_pronoun_followup("more"), {"verb": "more"},
        )

    def test_next(self):
        self.assertEqual(
            detect_pronoun_followup("next"), {"verb": "more"},
        )

    def test_next_page(self):
        self.assertEqual(
            detect_pronoun_followup("next page"), {"verb": "more"},
        )

    def test_load_more(self):
        self.assertEqual(
            detect_pronoun_followup("load more"), {"verb": "more"},
        )

    def test_show_more_files(self):
        self.assertEqual(
            detect_pronoun_followup("show more files"),
            {"verb": "more"},
        )

    def test_question_shape_rejected(self):
        self.assertIsNone(detect_pronoun_followup("show more?"))


class FileListEntityAcceptsMore(unittest.TestCase):

    def setUp(self):
        _reset_store_for_test()

    def test_entity_type_exists(self):
        self.assertIn(ENTITY_FILE_LIST, ENTITY_TYPES)

    def test_action_more_exists(self):
        self.assertIn(ACTION_MORE, ALLOWED_ACTIONS)

    def test_file_list_entity_accepts_more(self):
        set_active_entity(
            "vault-xyz",
            entity_type=ENTITY_FILE_LIST,
            entity_ref={"offset": 25, "page_size": 25,
                        "total_count": 90},
            display_label="All files",
            allowed_actions=(ACTION_MORE,),
            session_id="tok-1",
        )
        rec = get_active_entity("vault-xyz", session_id="tok-1")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["entity_type"], ENTITY_FILE_LIST)
        self.assertEqual(rec["entity_ref"]["offset"], 25)
        self.assertTrue(entity_matches_action(rec, "more"))


class ChatRequestAcceptsSelectionHint(unittest.TestCase):

    def test_hint_field_present(self):
        r = ChatRequest(
            encrypted_message="x",
            vault_name="v",
            pin="1234",
            selection_hint={"kind": "login", "id": "abc-uuid"},
        )
        self.assertEqual(r.selection_hint,
                         {"kind": "login", "id": "abc-uuid"})

    def test_hint_optional(self):
        r = ChatRequest(
            encrypted_message="x",
            vault_name="v",
            pin="1234",
        )
        self.assertIsNone(r.selection_hint)


class BuildLoginDetailDataByItemId(unittest.TestCase):
    """Two logins with the same title MUST resolve to different rows
    when disambiguated by item_id. This test does not touch the DB —
    it patches ``_fetch_vault_items`` and asserts the flow prefers
    id over the ILIKE query."""

    def test_pinned_id_bypasses_ilike(self):
        # We patch the fetcher to return DIFFERENT rows depending on
        # whether the caller supplied item_id or service_ilike, then
        # invoke build_login_detail_data twice — once with each id —
        # and assert the two calls returned distinct login rows.
        from unittest.mock import patch

        # Both fake rows have title="Gmail" but different ids/usernames.
        row_alice = {
            "id": "id-A",
            "service": "Gmail",
            "encrypted_data": json.dumps({
                "title": "Gmail",
                "service": "Gmail",
                "fields": {
                    "username": "alice@example.com",
                    "password": "pw-alice",
                },
            }).encode(),
            "created_at": _dt.datetime(2026, 7, 12),
        }
        row_bob = {
            "id": "id-B",
            "service": "Gmail",
            "encrypted_data": json.dumps({
                "title": "Gmail",
                "service": "Gmail",
                "fields": {
                    "username": "bob@example.com",
                    "password": "pw-bob",
                },
            }).encode(),
            "created_at": _dt.datetime(2026, 7, 12),
        }

        def fake_fetch(vault_id, item_type, limit,
                       *, service_ilike=None, item_id=None):
            if item_id == "id-A":
                return [row_alice]
            if item_id == "id-B":
                return [row_bob]
            # Search path — return BOTH so the chooser view fires
            # when no id is pinned.
            return [row_alice, row_bob]

        # We also need to bypass encryption on the plain fields.
        def fake_decrypt(blob, key):
            return json.loads(blob)

        with patch(
            "vault_chat_card_data._fetch_vault_items",
            side_effect=fake_fetch,
        ), patch(
            "vault_chat_card_data._decrypt_row_json",
            side_effect=fake_decrypt,
        ):
            from vault_chat_card_data import build_login_detail_data
            a = build_login_detail_data(
                "v", b"k" * 32, query="Gmail", item_id="id-A",
            )
            b = build_login_detail_data(
                "v", b"k" * 32, query="Gmail", item_id="id-B",
            )
            multi = build_login_detail_data(
                "v", b"k" * 32, query="Gmail",
            )

        # Pinned id returns the DETAIL view for the matching row.
        self.assertEqual(a["view"], "detail")
        self.assertEqual(b["view"], "detail")
        self.assertIn("alice@", a["login"]["username"])
        self.assertIn("bob@", b["login"]["username"])
        self.assertNotEqual(a["login"]["username"],
                            b["login"]["username"])
        # Without a pin the chooser view surfaces both.
        self.assertEqual(multi["view"], "chooser")
        self.assertEqual(len(multi["logins"]), 2)


if __name__ == "__main__":
    unittest.main()
