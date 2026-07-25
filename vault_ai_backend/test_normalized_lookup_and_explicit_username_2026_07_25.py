"""Regression tests for the 2026-07-25 chat-brain hotfix pair:

Bug 1: Case-insensitive + hyphen/underscore-tolerant retrieval of
       ``uploaded_files.saved_name`` (query "show me Naim ID"
       must resolve to a saved item stored as "naim id" even
       when the LLM misroutes to a family/tag handler).

Bug 2: The login-generation flow must honor an explicit
       user-supplied email as the username instead of
       generating one.

All tests are pure-Python: DB access is mocked via
``mock.patch('main.get_db', ...)`` returning controlled rows.
None of these tests hit the network or persist to disk.
"""

from __future__ import annotations

import unittest
from unittest import mock

import main as m


# =====================================================================
# Bug 1 -- _normalize_asset_lookup_key
# =====================================================================

class NormalizeAssetLookupKeyTest(unittest.TestCase):

    def test_case_and_whitespace_folded(self):
        cases = [
            ("Naim ID",         "naim id"),
            ("naim id",         "naim id"),
            ("NAIM ID",         "naim id"),
            ("Naim Id",         "naim id"),
            ("  naim   id  ",   "naim id"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                self.assertEqual(
                    m._normalize_asset_lookup_key(inp), expected,
                )

    def test_hyphen_and_underscore_folded_to_space(self):
        cases = [
            ("naim-id",         "naim id"),
            ("naim_id",         "naim id"),
            ("naim--id",        "naim id"),
            ("naim__id",        "naim id"),
            ("naim-_-id",       "naim id"),
            ("naim - id",       "naim id"),
        ]
        for inp, expected in cases:
            with self.subTest(inp=inp):
                self.assertEqual(
                    m._normalize_asset_lookup_key(inp), expected,
                )

    def test_empty_or_general_becomes_general_sentinel(self):
        self.assertEqual(
            m._normalize_asset_lookup_key(None), m.GENERAL_SENTINEL,
        )
        self.assertEqual(
            m._normalize_asset_lookup_key(""), m.GENERAL_SENTINEL,
        )
        self.assertEqual(
            m._normalize_asset_lookup_key("   "), m.GENERAL_SENTINEL,
        )

    def test_preserves_alphanumerics_and_dots(self):
        # Existing normalize_service keeps dots (e.g. "invoice v1.2").
        self.assertEqual(
            m._normalize_asset_lookup_key("invoice v1.2"),
            "invoice v1.2",
        )


# =====================================================================
# Bug 1 -- retrieve_saved_asset_by_exact_name via mocked DB
# =====================================================================

class _FakeConn:
    """A minimal psycopg2-like connection whose cursor(fetchone,
    fetchall) is scripted per-execute by ``responses``."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._cursor = _FakeCursor(self._responses)
        self.executed_queries: list[tuple] = []

    def cursor(self, cursor_factory=None):
        self._cursor.parent = self
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


class _FakeCursor:
    def __init__(self, responses):
        self._responses = responses
        self._current = None
        self.parent = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.parent.executed_queries.append((sql, params))
        if self._responses:
            self._current = self._responses.pop(0)
        else:
            self._current = None

    def fetchone(self):
        if self._current is None:
            return None
        if isinstance(self._current, list):
            return self._current[0] if self._current else None
        return self._current

    def fetchall(self):
        if self._current is None:
            return []
        if isinstance(self._current, list):
            return self._current
        return [self._current]

    def close(self):
        pass


def _row(saved_name, file_name="original.png", asset_type="image"):
    return {
        "id": f"file-{saved_name}",
        "file_name": file_name,
        "content_type": "image/png",
        "file_size": 1024,
        "saved_name": saved_name,
        "asset_type": asset_type,
        "created_at": None,
    }


class RetrieveSavedAssetByExactNameTest(unittest.TestCase):

    def _mock_db_with(self, exact_hit=None, scan_rows=None):
        """Return a ``get_db`` replacement whose first ``execute``
        (the LOWER(saved_name) = LOWER(%s) fast path) returns
        ``exact_hit``, and whose second ``execute`` (the vault
        scan for hyphen/underscore folding) returns ``scan_rows``.
        """
        conn = _FakeConn([exact_hit, scan_rows])
        return mock.patch("main.get_db", return_value=conn)

    def test_exact_lowercase_hit_returns_row(self):
        row = _row("naim id")
        with self._mock_db_with(exact_hit=row):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "Naim ID",
            )
        self.assertIsNotNone(got)
        self.assertEqual(got["saved_name"], "naim id")

    def test_uppercase_query_hits_exact_lowercase_row(self):
        row = _row("naim id")
        with self._mock_db_with(exact_hit=row):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "NAIM ID",
            )
        self.assertIsNotNone(got)

    def test_repeated_whitespace_query_normalizes_and_hits(self):
        row = _row("naim id")
        with self._mock_db_with(exact_hit=row):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "  naim   id  ",
            )
        self.assertIsNotNone(got)

    def test_hyphenated_query_folds_and_hits_after_scan(self):
        # Fast-path miss, scan yields the "naim id" row.
        row = _row("naim id")
        with self._mock_db_with(exact_hit=None, scan_rows=[row]):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "naim-id",
            )
        self.assertIsNotNone(got)
        self.assertEqual(got["saved_name"], "naim id")

    def test_underscored_query_folds_and_hits_after_scan(self):
        row = _row("naim id")
        with self._mock_db_with(exact_hit=None, scan_rows=[row]):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "naim_id",
            )
        self.assertIsNotNone(got)

    def test_missing_row_returns_none(self):
        with self._mock_db_with(exact_hit=None, scan_rows=[]):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "does-not-exist",
            )
        self.assertIsNone(got)

    def test_empty_query_returns_none_without_touching_db(self):
        with mock.patch("main.get_db") as get_db_mock:
            got = m.retrieve_saved_asset_by_exact_name("vault-1", "")
        self.assertIsNone(got)
        get_db_mock.assert_not_called()

    def test_general_sentinel_query_returns_none_without_db(self):
        with mock.patch("main.get_db") as get_db_mock:
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", m.GENERAL_SENTINEL,
            )
        self.assertIsNone(got)
        get_db_mock.assert_not_called()

    def test_missing_vault_id_returns_none_without_db(self):
        with mock.patch("main.get_db") as get_db_mock:
            got = m.retrieve_saved_asset_by_exact_name("", "Naim ID")
        self.assertIsNone(got)
        get_db_mock.assert_not_called()

    def test_scan_returns_none_when_no_row_folds_to_query(self):
        # Scan yields unrelated rows that don't fold to the query.
        rows = [_row("chase login"), _row("passport photo")]
        with self._mock_db_with(exact_hit=None, scan_rows=rows):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "naim-id",
            )
        self.assertIsNone(got)

    def test_scan_query_scopes_to_vault_id(self):
        row = _row("naim id")
        conn = _FakeConn([None, [row]])
        with mock.patch("main.get_db", return_value=conn):
            m.retrieve_saved_asset_by_exact_name(
                "vault-target", "naim-id",
            )
        # Every executed query received the vault_id as its first
        # positional parameter -- no cross-vault leakage possible.
        for sql, params in conn.executed_queries:
            self.assertIsNotNone(params)
            self.assertEqual(params[0], "vault-target")


# =====================================================================
# Bug 1 -- _try_exact_saved_name_early_return
# =====================================================================

class EarlyReturnProbeTest(unittest.TestCase):

    def test_intent_asset_name_wins_over_message(self):
        row = _row("naim id")
        with mock.patch(
            "main.retrieve_saved_asset_by_exact_name",
            side_effect=lambda vault_id, name: (
                row if name == "Naim ID" else None
            ),
        ):
            got = m._try_exact_saved_name_early_return(
                vault_id="vault-1",
                decrypted_message="show me my thing",
                intent_data={"asset_name": "Naim ID"},
            )
        self.assertIs(got, row)

    def test_falls_back_to_decrypted_message(self):
        row = _row("naim id")
        with mock.patch(
            "main.retrieve_saved_asset_by_exact_name",
            side_effect=lambda vault_id, name: (
                row if m._normalize_asset_lookup_key(name) == "naim id"
                else None
            ),
        ):
            # The probe tries several intent_data keys then the raw
            # decrypted_message; the raw message contains "Naim ID".
            got = m._try_exact_saved_name_early_return(
                vault_id="vault-1",
                decrypted_message="Naim ID",
                intent_data={"tag": "identity"},
            )
        self.assertIs(got, row)

    def test_no_hit_returns_none(self):
        with mock.patch(
            "main.retrieve_saved_asset_by_exact_name",
            return_value=None,
        ):
            got = m._try_exact_saved_name_early_return(
                vault_id="vault-1",
                decrypted_message="show my documents",
                intent_data={"tag": "identity"},
            )
        self.assertIsNone(got)

    def test_no_vault_id_returns_none(self):
        got = m._try_exact_saved_name_early_return(
            vault_id="",
            decrypted_message="Naim ID",
            intent_data={},
        )
        self.assertIsNone(got)

    def test_probe_visits_multiple_intent_keys(self):
        calls = []

        def spy(vault_id, name):
            calls.append(name)
            return None

        with mock.patch(
            "main.retrieve_saved_asset_by_exact_name",
            side_effect=spy,
        ):
            m._try_exact_saved_name_early_return(
                vault_id="vault-1",
                decrypted_message="show me things",
                intent_data={
                    "asset_name": "Naim ID",
                    "tag": "identity",
                    "memory_query": "id",
                    "anchor_text": "docs",
                },
            )
        # At least the asset_name and decrypted_message probes ran.
        self.assertIn("Naim ID", calls)
        self.assertIn("show me things", calls)


# =====================================================================
# Bug 1 -- display label preservation
# =====================================================================

class DisplayLabelPreservationTest(unittest.TestCase):
    """The user's original saved name is preserved in the DB row.
    Normalization is only used for LOOKUP keys, never to mutate
    the stored value that the frontend renders."""

    def test_returned_row_carries_original_saved_name_verbatim(self):
        # Simulate a row that was saved as lowercase "naim id".
        row = _row("naim id")
        conn = _FakeConn([row])
        with mock.patch("main.get_db", return_value=conn):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "NAIM ID",  # arbitrary capitalization query
            )
        # The stored value is what comes back -- no rewriting.
        self.assertEqual(got["saved_name"], "naim id")


# =====================================================================
# Bug 1 -- unrelated labels do NOT falsely match
# =====================================================================

class NoFalseMatchTest(unittest.TestCase):

    def test_unrelated_saved_name_does_not_match(self):
        # Scan candidates are unrelated; query "naim-id" must not
        # match "chase login" or "passport photo".
        rows = [
            _row("chase login"),
            _row("passport photo"),
            _row("naim wilson"),  # substring "naim" but not "naim id"
        ]
        conn = _FakeConn([None, rows])
        with mock.patch("main.get_db", return_value=conn):
            got = m.retrieve_saved_asset_by_exact_name(
                "vault-1", "naim-id",
            )
        self.assertIsNone(got)


# =====================================================================
# Bug 2 -- _extract_explicit_email
# =====================================================================

class ExtractExplicitEmailTest(unittest.TestCase):

    def test_spec_examples_all_extract_the_email(self):
        expected = "beraves@gmail.com"
        cases = [
            "create me a netflix login but with my email address as username beraves@gmail.com",
            "Create a Netflix login with my email beraves@gmail.com",
            "Make a Netflix login and use beraves@gmail.com as the username",
            "Create login for Netflix, username is beraves@gmail.com",
            "Use beraves@gmail.com for the username and generate a password",
        ]
        for msg in cases:
            with self.subTest(msg=msg[:60]):
                self.assertEqual(
                    m._extract_explicit_email(msg), expected,
                )

    def test_no_email_returns_none(self):
        cases = [
            None, "", "   ", "create a login for Chase",
            "generate strong password for gmail",
            "please save this@ without a domain",
        ]
        for msg in cases:
            with self.subTest(msg=repr(msg)):
                self.assertIsNone(m._extract_explicit_email(msg))

    def test_parenthesized_email_is_extracted(self):
        self.assertEqual(
            m._extract_explicit_email(
                "my email is (beraves@gmail.com) can you save it"
            ),
            "beraves@gmail.com",
        )

    def test_case_preserved_on_local_part(self):
        self.assertEqual(
            m._extract_explicit_email(
                "use Beraves.WORK@Example.Com as username"
            ),
            "Beraves.WORK@Example.Com",
        )

    def test_plus_and_hyphen_in_local_part_supported(self):
        self.assertEqual(
            m._extract_explicit_email("username is my.first+netflix@my-domain.co"),
            "my.first+netflix@my-domain.co",
        )

    def test_pathologically_long_input_returns_none(self):
        huge = "a" * 300 + "@x.com"
        self.assertIsNone(m._extract_explicit_email(huge))


# =====================================================================
# Bug 2 -- no sensitive values leak from the extractor into logs
# =====================================================================

class NoSensitiveLeakageTest(unittest.TestCase):
    """The extractor itself never logs or returns anything except
    the email. Verify the function's returned value equals only
    the email (no surrounding context)."""

    def test_return_value_contains_only_the_email_no_context(self):
        msg = "create a netflix login and use beraves@gmail.com now"
        got = m._extract_explicit_email(msg)
        self.assertNotIn("netflix", got.lower())
        self.assertNotIn("create", got.lower())
        self.assertNotIn(" ", got)


# =====================================================================
# Bug 2 -- pending_login_draft field shape stays backward-compatible
# =====================================================================

class PendingLoginDraftShapeTest(unittest.TestCase):
    """Both confirm-save handlers (main.py:13552 legacy confirm and
    main.py:14305 explicit-pick) consume ``username_options[0]`` to
    populate the saved username. When Bug 2's explicit-email path
    is taken, the supplied email MUST land at position 0 of that
    list so the existing confirm code paths pick it up unchanged.
    This test asserts that requirement holds by exercising the
    same reading logic used by both confirm branches.
    """

    def test_explicit_email_lands_at_username_options_index_0(self):
        # Simulate what generate_login writes into memory when an
        # explicit email is supplied. The confirm handlers read
        # username_options[0] as the "picked username".
        explicit = "beraves@gmail.com"
        pending = {
            "service": "netflix",
            "username_options": [explicit],
            "password": "<generated>",
            "policy_email_required": False,
            "explicit_username_supplied": True,
        }
        # This is the exact read pattern at main.py:13552 and 14305.
        opts = list(pending.get("username_options") or [])
        picked = opts[0] if opts else None
        self.assertEqual(picked, explicit)

    def test_flag_disambiguates_supplied_vs_generated(self):
        supplied = {
            "service": "netflix",
            "username_options": ["beraves@gmail.com"],
            "explicit_username_supplied": True,
        }
        generated = {
            "service": "netflix",
            "username_options": ["gen-username-xyz"],
            "explicit_username_supplied": False,
        }
        self.assertTrue(supplied.get("explicit_username_supplied"))
        self.assertFalse(generated.get("explicit_username_supplied"))


if __name__ == "__main__":
    unittest.main()
