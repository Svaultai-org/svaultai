"""Regression tests for the 2026-07-12 product fixes:

  * "show me all my files" (and variants) must classify to the new
    INTENT_VAULT_FILE_LIST_ALL intent, NOT fall through to a prose
    dump.
  * File rows in the structured file-list envelope must carry a
    human-readable size_display and a downloadable flag.
  * The pronoun-followup classifier recognizes "download it" and
    variants.
  * The active-entity system exposes ACTION_DOWNLOAD.
"""

from __future__ import annotations

import unittest

from vault_chat_router import (
    INTENT_VAULT_FILE_LIST_ALL,
    build_vault_chat_envelope,
)
from vault_chat_pronoun_followup import detect_pronoun_followup
from vault_chat_active_entity import ACTION_DOWNLOAD, ALLOWED_ACTIONS


class ShowAllFilesRoutesToStructuredIntent(unittest.TestCase):
    """Whole-vault list phrases must never fall back to prose."""

    def _expect(self, phrase, intent=INTENT_VAULT_FILE_LIST_ALL):
        env = build_vault_chat_envelope(phrase)
        self.assertIsNotNone(
            env, msg=f"router returned None for {phrase!r}",
        )
        self.assertEqual(
            env["intent"], intent,
            msg=f"{phrase!r} should classify as {intent!r}, "
                f"got {env['intent']!r}",
        )

    def test_show_me_all_my_files(self):
        self._expect("show me all my files")

    def test_all_my_files(self):
        self._expect("all my files")

    def test_list_my_files(self):
        self._expect("list my files")

    def test_list_all_files(self):
        self._expect("list all files")

    def test_show_my_files(self):
        self._expect("show my files")

    def test_what_files_do_i_have(self):
        self._expect("what files do i have")

    def test_everything_in_my_vault(self):
        self._expect("show me everything in my vault")


class StructuredFileRowSchema(unittest.TestCase):
    """The structured row a chat card renders MUST include the
    human-readable size + downloadable flag + optional uploaded_at."""

    def test_serialize_file_carries_size_display_and_downloadable(self):
        from main import _serialize_file_for_list_card
        row = {
            "id": "abc",
            "file_name": "video.webm",
            "content_type": "video/webm",
            "file_size": 47_600_000,
        }
        out = _serialize_file_for_list_card(row)
        self.assertEqual(out["file_id"], "abc")
        self.assertEqual(out["size_bytes"], 47_600_000)
        self.assertIn("size_display", out)
        self.assertTrue(out["size_display"].endswith("MB"),
                        msg=f"expected MB unit, got {out['size_display']}")
        self.assertTrue(out["downloadable"])

    def test_serialize_file_size_units(self):
        from main import _format_bytes_human
        self.assertEqual(_format_bytes_human(0), "0 B")
        self.assertEqual(_format_bytes_human(500), "500 B")
        self.assertEqual(_format_bytes_human(2048), "2.0 KB")
        self.assertEqual(_format_bytes_human(250_000), "244.1 KB")
        self.assertTrue(
            _format_bytes_human(47_600_000).startswith("45."),
        )
        self.assertTrue(
            _format_bytes_human(4_294_967_296).endswith("GB"),
        )

    def test_serialize_file_carries_uploaded_at_if_present(self):
        import datetime as _dt
        from main import _serialize_file_for_list_card
        row = {
            "id": "u1",
            "file_name": "x.pdf",
            "content_type": "application/pdf",
            "file_size": 100,
            "uploaded_at": _dt.datetime(2026, 7, 12, 10, 30, 0),
        }
        out = _serialize_file_for_list_card(row)
        self.assertIn("uploaded_at", out)
        self.assertTrue(out["uploaded_at"].startswith("2026-07-12"))


class DownloadItPronounRecognised(unittest.TestCase):

    def test_download_it(self):
        self.assertEqual(
            detect_pronoun_followup("download it"),
            {"verb": "download"},
        )

    def test_download_that(self):
        self.assertEqual(
            detect_pronoun_followup("download that"),
            {"verb": "download"},
        )

    def test_download_the_file(self):
        self.assertEqual(
            detect_pronoun_followup("download the file"),
            {"verb": "download"},
        )

    def test_download_that_one(self):
        self.assertEqual(
            detect_pronoun_followup("download that one"),
            {"verb": "download"},
        )

    def test_question_shape_rejected(self):
        self.assertIsNone(detect_pronoun_followup("download it?"))

    def test_open_it_still_works(self):
        self.assertEqual(
            detect_pronoun_followup("open it"),
            {"verb": "open"},
        )


class ActiveEntityAllowsDownload(unittest.TestCase):

    def test_action_download_is_in_allowed_set(self):
        self.assertIn(ACTION_DOWNLOAD, ALLOWED_ACTIONS)


if __name__ == "__main__":
    unittest.main()
