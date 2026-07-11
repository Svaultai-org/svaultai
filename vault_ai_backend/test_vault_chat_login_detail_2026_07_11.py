"""Pytest coverage for the login DETAIL card path (product decision
2026-07-11).

Product decision:
  When a user is authenticated + unlocked and explicitly asks to show/
  open a specific saved login, VaultAI returns the DETAIL card
  populated with plaintext username + password + website + notes.
  No confirmation prompt, no second PIN, no trusted-device gate.

Every other path (login list, login search with multiple matches,
duplicates, id-document reveal) still uses the blacklist/mask
projections. These tests lock those invariants down.

The plaintext exception is enforced by:

  - vault_chat_card_data._sanitize_login_detail_payload — a positive
    allowlist that admits only ``schema, available, view, query,
    login, count, pending_action`` at the payload level and only
    ``id, title, service, username, password, domain, website, notes,
    updated_at, generated`` at the login level. Any other key is
    silently dropped.
  - populate_vault_chat_card_data — the ONLY code path that runs the
    allowlist sanitizer, and only when ``intent in (LOGIN_SEARCH,
    LOGIN_REVEAL, LOGIN_COPY)`` AND ``data.view == 'detail'``.
"""

from __future__ import annotations

import json
import os
import secrets
import unittest

os.environ.setdefault("SKIP_HEAVY_STARTUP_INIT", "1")

from vault_chat_card_data import (
    LOGIN_VIEW_CHOOSER,
    LOGIN_VIEW_DETAIL,
    LOGIN_VIEW_LIST,
    LOGIN_VIEW_NOT_FOUND,
    _project_login_row,
    _project_login_row_detail,
    _sanitize_login_detail_payload,
    build_login_detail_data,
    build_login_list_data,
    populate_vault_chat_card_data,
)
from vault_chat_router import (
    INTENT_LOGIN_COPY,
    INTENT_LOGIN_LIST,
    INTENT_LOGIN_REVEAL,
    INTENT_LOGIN_SEARCH,
    build_vault_chat_envelope,
)
from vault_core import encrypt_message




_KEY = secrets.token_bytes(32)


def _encrypt(fields: dict) -> str:
    return encrypt_message(json.dumps(fields), _KEY)


def _row(id_: str, service: str, username: str, password: str,
         notes: str = "", title: str = "") -> dict:
    body = {
        "title": title or service,
        "service": service,
        "fields": {"username": username, "password": password},
    }
    if notes:
        body["fields"]["notes"] = notes
    return {
        "id": id_,
        "service": service,
        "encrypted_data": _encrypt(body),
        "created_at": "2026-07-01T00:00:00Z",
    }


def _patch_fetch(monkeypatch, rows_by_query):
    def fake_fetch(vault_id, item_type, limit, *, service_ilike=None):
        if service_ilike is None:
            all_rows = []
            for rs in rows_by_query.values():
                all_rows.extend(rs)
            return all_rows[:limit]
        for pat, rs in rows_by_query.items():
            if pat.lower() in service_ilike.lower():
                return rs[:limit]
        return []
    import vault_chat_card_data as vccd
    monkeypatch.setattr(vccd, "_fetch_vault_items", fake_fetch)




class SanitizerAllowsOnlyKnownKeys(unittest.TestCase):

    def test_sanitizer_drops_unknown_top_level_keys(self):
        raw = {
            "schema": "x", "available": True, "view": "detail",
            "query": "q", "login": {}, "count": 1, "pending_action": "edit",

            "raw_password": "leaked",
            "encrypted_data": "leaked",
            "kdf_iterations": 100000,
            "server_stack_trace": "leaked",
        }
        out = _sanitize_login_detail_payload(raw)
        self.assertIn("schema", out)
        self.assertIn("view", out)
        self.assertIn("login", out)
        self.assertIn("pending_action", out)
        self.assertNotIn("raw_password", out)
        self.assertNotIn("encrypted_data", out)
        self.assertNotIn("kdf_iterations", out)
        self.assertNotIn("server_stack_trace", out)

    def test_sanitizer_drops_unknown_login_keys(self):
        raw = {
            "schema": "x", "available": True, "view": "detail",
            "query": "q", "count": 1,
            "login": {
                "id": "1", "title": "T", "service": "S",
                "username": "u", "password": "p",
                "domain": "d", "website": "w",
                "notes": "n", "updated_at": "2026-07-01T00:00:00Z",
                "generated": False,

                "salt": "leaked-salt",
                "pin": "leaked-pin",
                "encrypted_data": "leaked-blob",
                "raw_username": "leaked",
            },
        }
        out = _sanitize_login_detail_payload(raw)
        login = out["login"]
        self.assertEqual(login["username"], "u")
        self.assertEqual(login["password"], "p")
        self.assertNotIn("salt", login)
        self.assertNotIn("pin", login)
        self.assertNotIn("encrypted_data", login)
        self.assertNotIn("raw_username", login)

    def test_sanitizer_on_none_returns_empty(self):
        self.assertEqual(_sanitize_login_detail_payload({}), {})




class DetailProjectorReturnsPlaintext(unittest.TestCase):

    def test_project_login_row_detail_emits_plaintext(self):
        row = _row(
            "l-1", "AFCU", "ada@example.com", "hunter2!",
            title="American First Credit Union",
        )
        proj = _project_login_row_detail(row, _KEY)
        self.assertEqual(proj["id"], "l-1")
        self.assertEqual(proj["service"], "AFCU")
        self.assertEqual(proj["title"], "American First Credit Union")
        self.assertEqual(proj["username"], "ada@example.com")
        self.assertEqual(proj["password"], "hunter2!")
        self.assertTrue(proj["website"])

    def test_project_login_row_list_still_masks(self):
        row = _row("l-1", "AFCU", "ada@example.com", "hunter2!")
        proj = _project_login_row(row, _KEY)

        self.assertNotIn("password", proj)
        self.assertNotIn("hunter2", str(proj))

        self.assertNotEqual(proj["username_masked"], "ada@example.com")
        self.assertTrue(proj["has_username"])




class BuilderRoutesByMatchCount(unittest.TestCase):
    def setUp(self):
        self.rows_by_query = {
            "afcu": [
                _row("l-1", "AFCU", "ada@example.com", "hunter2!",
                     title="American First Credit Union"),
            ],
            "bank": [
                _row("l-2", "Bank of A", "a@example.com", "p1"),
                _row("l-3", "Bank of B", "b@example.com", "p2"),
            ],
        }

    def test_zero_matches_returns_not_found(self):
        import pytest
        with pytest.MonkeyPatch.context() as m:
            _patch_fetch(m, self.rows_by_query)
            out = build_login_detail_data(
                "v", _KEY, query="nonexistent", limit=20,
            )
        self.assertEqual(out["view"], LOGIN_VIEW_NOT_FOUND)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["query"], "nonexistent")

    def test_single_match_returns_detail(self):
        import pytest
        with pytest.MonkeyPatch.context() as m:
            _patch_fetch(m, self.rows_by_query)
            out = build_login_detail_data(
                "v", _KEY, query="afcu", limit=20,
            )
        self.assertEqual(out["view"], LOGIN_VIEW_DETAIL)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["login"]["username"], "ada@example.com")
        self.assertEqual(out["login"]["password"], "hunter2!")

    def test_multi_match_returns_chooser_without_plaintext(self):
        import pytest
        with pytest.MonkeyPatch.context() as m:
            _patch_fetch(m, self.rows_by_query)
            out = build_login_detail_data(
                "v", _KEY, query="bank", limit=20,
            )
        self.assertEqual(out["view"], LOGIN_VIEW_CHOOSER)
        self.assertEqual(out["count"], 2)
        chooser_rows = out["logins"]
        for cr in chooser_rows:

            self.assertNotIn("password", cr)
            self.assertNotIn("username", cr)

            self.assertIn("username_masked", cr)

    def test_empty_query_falls_back_to_list_view(self):
        import pytest
        with pytest.MonkeyPatch.context() as m:
            _patch_fetch(m, self.rows_by_query)
            out = build_login_detail_data(
                "v", _KEY, query=None, limit=20,
            )
        self.assertEqual(out["view"], LOGIN_VIEW_LIST)

    def test_missing_key_returns_unavailable(self):
        out = build_login_detail_data("v", b"", query="afcu", limit=20)
        self.assertFalse(out["available"])
        self.assertEqual(out["unavailable_reason"], "vault_locked")




class PopulateAppliesAllowlistOnDetailOnly(unittest.TestCase):

    def _fake_populate(self, monkeypatch, intent, view, query):
        rows = [
            _row("l-1", "AFCU", "ada@example.com", "hunter2!",
                 title="American First Credit Union"),
        ]
        rows_by_query = {"afcu": rows}
        _patch_fetch(monkeypatch, rows_by_query)

        envelope = {
            "schema": "vault_chat_response_v1",
            "intent": intent,
            "card": {
                "cardType": "vault_login_card",
                "view":     view,
                "query":    query,
            },
        }
        return populate_vault_chat_card_data(
            envelope, vault_id="v", key=_KEY,
        )

    def test_login_search_detail_carries_plaintext_password(self):
        import pytest
        with pytest.MonkeyPatch.context() as m:
            env = self._fake_populate(
                m, INTENT_LOGIN_SEARCH, "detail", "afcu",
            )
        data = env["card"]["data"]
        self.assertEqual(data["view"], "detail")
        self.assertEqual(data["login"]["password"], "hunter2!")
        self.assertEqual(data["login"]["username"], "ada@example.com")

    def test_login_reveal_detail_carries_plaintext_password(self):
        import pytest
        with pytest.MonkeyPatch.context() as m:
            env = self._fake_populate(
                m, INTENT_LOGIN_REVEAL, "detail", "afcu",
            )
        data = env["card"]["data"]
        self.assertEqual(data["login"]["password"], "hunter2!")

    def test_login_copy_detail_carries_plaintext_password(self):
        import pytest
        with pytest.MonkeyPatch.context() as m:
            env = self._fake_populate(
                m, INTENT_LOGIN_COPY, "detail", "afcu",
            )
        data = env["card"]["data"]
        self.assertEqual(data["login"]["password"], "hunter2!")

    def test_login_list_never_carries_plaintext_password(self):
        rows = [
            _row("l-1", "AFCU", "ada@example.com", "hunter2!",
                 title="American First Credit Union"),
        ]
        import pytest
        with pytest.MonkeyPatch.context() as m:
            _patch_fetch(m, {"afcu": rows})
            envelope = {
                "intent": INTENT_LOGIN_LIST,
                "card": {"cardType": "vault_login_card", "view": "list"},
            }
            env = populate_vault_chat_card_data(
                envelope, vault_id="v", key=_KEY,
            )
        data_str = json.dumps(env["card"]["data"])
        self.assertNotIn("hunter2", data_str)
        self.assertNotIn('"password"', data_str)




class RouterDispatchesToDetailNotConfirmation(unittest.TestCase):
    def test_show_me_my_login_dispatches_detail(self):
        env = build_vault_chat_envelope(
            "show me my American First Credit Union login",
        )
        self.assertEqual(env["intent"], INTENT_LOGIN_SEARCH)
        self.assertEqual(env["card"]["cardType"], "vault_login_card")
        self.assertEqual(env["card"].get("view"), "detail")

    def test_reveal_my_password_dispatches_detail(self):
        env = build_vault_chat_envelope("Reveal my Netflix password")
        self.assertEqual(env["intent"], INTENT_LOGIN_REVEAL)
        self.assertEqual(env["card"]["cardType"], "vault_login_card")
        self.assertEqual(env["card"].get("view"), "detail")

    def test_copy_my_password_dispatches_detail(self):
        env = build_vault_chat_envelope("Copy my Chase password")
        self.assertEqual(env["intent"], INTENT_LOGIN_COPY)
        self.assertEqual(env["card"]["cardType"], "vault_login_card")
        self.assertEqual(env["card"].get("view"), "detail")

    def test_router_shell_never_carries_plaintext_password(self):
        for phrase in (
            "show me my Netflix login",
            "Reveal my Netflix password",
            "Copy my Netflix password",
        ):
            env = build_vault_chat_envelope(phrase)
            card = env["card"]
            for banned in (
                "password", "password_value", "raw_password",
                "clearPassword",
            ):
                self.assertNotIn(banned, card, msg=phrase)




class ListPathStillMasks(unittest.TestCase):
    def test_generic_list_returns_masked_usernames_only(self):
        rows = [
            _row("l-1", "Netflix", "a@example.com", "p1"),
            _row("l-2", "Gmail",   "b@example.com", "p2"),
        ]
        import pytest
        with pytest.MonkeyPatch.context() as m:
            _patch_fetch(m, {"": rows})
            out = build_login_list_data("v", _KEY, view="list", limit=20)
        for row in out["logins"]:
            self.assertNotIn("password", row)
            self.assertIn("username_masked", row)


if __name__ == "__main__":
    unittest.main()
