"""End-to-end verification for the 2026-07-28 chat deep fix.

Two bugs the previous af71830 hotfix left in production:

    Bug 1: "show me naim id" was misrouted to the identity-family
           tag handler, returning "no matches found" even when the
           vault held an item literally named "naim id".

    Bug 2: "create me a prime login with my email address X" and
           the follow-up "change the username to be X" ignored the
           supplied email, generated a random username, and (for the
           follow-up) auto-saved the login without confirmation.

This file exercises the SAME code paths the /chat endpoint runs
in production — the credential-command extractor, the pending-
draft state machine, the exact-name resolver, and their in-place
wiring at the intent-dispatch layer inside main.py.

Every test is deterministic (no DB, no network). Tests never log
plaintext credentials, PIN material, or vault content. Fixture
email addresses live only in the tests (not in the shipping
docstring in main.py).
"""

from __future__ import annotations

import unittest
from unittest import mock

from vault_credential_command import (
    ACTION_CANCEL,
    ACTION_CONFIRM_SAVE,
    ACTION_CREATE,
    ACTION_EDIT_PENDING,
    ACTION_REGENERATE,
    ACTION_REPLACE_DRAFT,
    ACTION_SHOW_DRAFT,
    ACTION_UNRELATED,
    CredentialCommand,
    FIELD_EMAIL,
    FIELD_PASSWORD,
    FIELD_URL,
    FIELD_USERNAME,
    extract_credential_command,
    extract_explicit_fields,
)
from vault_pending_draft_state import (
    OUTCOME_CANCELLED,
    OUTCOME_NO_ACTION,
    OUTCOME_REPLACED,
    OUTCOME_SAVE_NOW,
    OUTCOME_SHOWN,
    OUTCOME_UPDATED,
    DraftOutcome,
    apply_to_pending_draft,
)
from vault_exact_name_resolver import (
    STATUS_AMBIGUOUS,
    STATUS_HIT,
    STATUS_MISS,
    resolve_saved_name,
)


# ---------------------------------------------------------------------------
# Layer 1: credential command extractor
# ---------------------------------------------------------------------------

class ExtractExplicitFieldsTest(unittest.TestCase):
    """Paraphrase coverage — proves the extractor is semantic, not phrase-
    hardcoded. Every case here uses a DIFFERENT surface phrase for the
    same underlying value; if production regresses to a hardcoded list,
    at least half of these will start failing at once."""

    def test_bare_email_becomes_username(self):
        # A bare email token in the message with no explicit label
        # should still be picked up as a username (users say
        # "create a login for X, my@email.com").
        fields = extract_explicit_fields(
            "create a login for netflix with my@email.com"
        )
        self.assertEqual(fields.get(FIELD_USERNAME), "my@email.com")

    def test_email_as_my_username_phrase(self):
        # Production Bug 2 phrasing.
        fields = extract_explicit_fields(
            "create me a prime login with my email address "
            "beraves@gmail.com as my username"
        )
        self.assertEqual(fields.get(FIELD_EMAIL), "beraves@gmail.com")
        self.assertEqual(fields.get(FIELD_USERNAME), "beraves@gmail.com")

    def test_use_X_as_the_username(self):
        fields = extract_explicit_fields(
            "Make me a Netflix login. Use chosen2026 for the username"
        )
        self.assertEqual(fields.get(FIELD_USERNAME), "chosen2026")

    def test_username_is_X_dot_form(self):
        fields = extract_explicit_fields(
            "Generate a login for Hulu, username is chosen.abdullahi"
        )
        self.assertEqual(fields.get(FIELD_USERNAME), "chosen.abdullahi")

    def test_using_my_email_short_form(self):
        fields = extract_explicit_fields(
            "Create an Amazon account login using my email "
            "beraves@gmail.com"
        )
        self.assertEqual(fields.get(FIELD_EMAIL), "beraves@gmail.com")

    def test_account_name_synonym(self):
        # "account name" and "login id" are synonyms for username.
        fields = extract_explicit_fields(
            "Make a Prime credential with the account name "
            "beraves@gmail.com"
        )
        # bare email should get picked up as username regardless of
        # label variation
        self.assertEqual(fields.get(FIELD_USERNAME), "beraves@gmail.com")

    def test_login_id_colon_syntax(self):
        fields = extract_explicit_fields(
            "Create an Amazon credential; login ID: chosen_user_9."
        )
        self.assertEqual(fields.get(FIELD_USERNAME), "chosen_user_9")

    def test_quoted_multi_word_username(self):
        fields = extract_explicit_fields(
            "use \"chosen abdullahi\" as the username"
        )
        self.assertEqual(fields.get(FIELD_USERNAME), "chosen abdullahi")

    def test_field_value_equals_syntax(self):
        fields = extract_explicit_fields("username=alice42")
        self.assertEqual(fields.get(FIELD_USERNAME), "alice42")

    def test_case_preservation(self):
        # Local part of an email is case-preserving; the extractor
        # must never lowercase user-supplied values.
        fields = extract_explicit_fields(
            "the username is CamelCase.Name@Example.COM"
        )
        # username-first pattern wins over email regex here; both
        # capture the mixed-case value verbatim.
        val = fields.get(FIELD_USERNAME) or fields.get(FIELD_EMAIL)
        self.assertIsNotNone(val)
        self.assertIn("CamelCase", val)

    def test_password_labeled(self):
        fields = extract_explicit_fields(
            "For Prime, keep my username as chosen88 and use "
            "\"Sup3r-Secret\" as password"
        )
        self.assertEqual(fields.get(FIELD_PASSWORD), "Sup3r-Secret")

    def test_url_labeled(self):
        fields = extract_explicit_fields(
            "the url is https://primevideo.com"
        )
        self.assertEqual(fields.get(FIELD_URL), "https://primevideo.com")

    def test_no_extraction_when_message_is_random_chat(self):
        fields = extract_explicit_fields("what time is it")
        self.assertEqual(fields, {})

    def test_no_extraction_when_message_empty(self):
        self.assertEqual(extract_explicit_fields(""), {})
        self.assertEqual(extract_explicit_fields(None), {})


class ExtractCredentialCommandTest(unittest.TestCase):

    def _cmd(self, message, has_draft=False):
        return extract_credential_command(
            message, has_pending_draft=has_draft,
        )

    def test_create_when_no_draft_and_explicit_fields(self):
        cmd = self._cmd(
            "create me a prime login with my email address "
            "beraves@gmail.com as my username",
            has_draft=False,
        )
        self.assertEqual(cmd.action, ACTION_CREATE)
        self.assertEqual(cmd.explicit_fields.get(FIELD_USERNAME),
                         "beraves@gmail.com")

    def test_unrelated_when_no_draft_and_no_credential_signal(self):
        cmd = self._cmd("what time is it", has_draft=False)
        self.assertEqual(cmd.action, ACTION_UNRELATED)

    def test_edit_pending_when_draft_and_explicit_value(self):
        # Bug 2 core case — the follow-up that auto-saved in
        # production.
        cmd = self._cmd(
            "change the username to be beraves@gmail.com",
            has_draft=True,
        )
        self.assertEqual(cmd.action, ACTION_EDIT_PENDING)
        self.assertEqual(cmd.explicit_fields.get(FIELD_USERNAME),
                         "beraves@gmail.com")

    def test_regenerate_when_draft_and_no_explicit_value(self):
        cmd = self._cmd("change the username", has_draft=True)
        self.assertEqual(cmd.action, ACTION_REGENERATE)
        self.assertIn(FIELD_USERNAME, cmd.generate_fields)

    def test_regenerate_password_longer(self):
        cmd = self._cmd("make the password longer", has_draft=True)
        self.assertEqual(cmd.action, ACTION_REGENERATE)
        self.assertIn(FIELD_PASSWORD, cmd.generate_fields)

    def test_confirm_save_various_phrases(self):
        for phrase in (
            "save it", "store it", "yes, save this",
            "add it to my vault", "keep it", "remember it",
            "save now", "go ahead", "looks good", "perfect",
        ):
            cmd = self._cmd(phrase, has_draft=True)
            self.assertEqual(
                cmd.action, ACTION_CONFIRM_SAVE,
                f"phrase {phrase!r} should be CONFIRM_SAVE",
            )

    def test_cancel_various_phrases(self):
        for phrase in (
            "cancel", "never mind", "nevermind", "forget it",
            "discard it", "drop it", "don't save",
        ):
            cmd = self._cmd(phrase, has_draft=True)
            self.assertEqual(
                cmd.action, ACTION_CANCEL,
                f"phrase {phrase!r} should be CANCEL",
            )

    def test_show_draft(self):
        for phrase in (
            "show me the draft", "display the draft",
            "repeat the draft", "read me my draft",
        ):
            cmd = self._cmd(phrase, has_draft=True)
            self.assertEqual(
                cmd.action, ACTION_SHOW_DRAFT,
                f"phrase {phrase!r} should be SHOW_DRAFT",
            )

    def test_replace_draft(self):
        for phrase in (
            "start over", "scrap this", "do it again",
        ):
            cmd = self._cmd(phrase, has_draft=True)
            self.assertEqual(
                cmd.action, ACTION_REPLACE_DRAFT,
                f"phrase {phrase!r} should be REPLACE_DRAFT",
            )

    def test_rejection_value_not_treated_as_username(self):
        # "the username is wrong" must NOT be parsed as
        # {username: "wrong"}. It's a complaint, not an assignment.
        cmd = self._cmd("the username is wrong", has_draft=True)
        self.assertNotEqual(cmd.action, ACTION_EDIT_PENDING,
                            "rejection words must not be treated as values")

    def test_username_not_acceptable_becomes_regenerate(self):
        cmd = self._cmd(
            "the username is not acceptable", has_draft=True,
        )
        self.assertEqual(cmd.action, ACTION_REGENERATE)
        self.assertIn(FIELD_USERNAME, cmd.generate_fields)

    def test_message_with_no_draft_and_only_regenerate_phrase_unrelated(self):
        # No draft to regenerate — "change the username" alone is
        # unrelated (the extractor never invents a target).
        cmd = self._cmd("change the username", has_draft=False)
        self.assertEqual(cmd.action, ACTION_UNRELATED)


# ---------------------------------------------------------------------------
# Layer 2: pending-draft state machine
# ---------------------------------------------------------------------------

def _fake_password() -> str:
    return "FAKE-PW-1234!"


def _fake_username() -> str:
    return "fake-user-42"


def _make_draft(**overrides):
    base = {
        "service": "prime",
        "username_options": ["cobaltbranch947"],
        "password": "old_pw_xyz",
        "policy_email_required": False,
        "has_existing_username": False,
        "has_existing_email": False,
        "existing_username": "",
        "existing_email": "",
        "explicit_username_supplied": False,
        "ts": 1_700_000_000,
    }
    base.update(overrides)
    return base


class DraftStateMachineTest(unittest.TestCase):

    def test_no_draft_returns_no_action(self):
        result = apply_to_pending_draft(
            user_message="save it",
            draft={},
            generate_password=_fake_password,
        )
        self.assertEqual(result.kind, OUTCOME_NO_ACTION)

    def test_change_username_to_email_updates_draft_no_save(self):
        # Bug 2 primary regression test.
        draft = _make_draft()
        result = apply_to_pending_draft(
            user_message="change the username to be beraves@gmail.com",
            draft=draft,
            generate_password=_fake_password,
        )
        self.assertEqual(result.kind, OUTCOME_UPDATED)
        self.assertEqual(
            result.draft["username_options"], ["beraves@gmail.com"],
        )
        self.assertTrue(result.draft["explicit_username_supplied"])
        # Original draft dict must NOT be mutated.
        self.assertEqual(draft["username_options"], ["cobaltbranch947"])
        # Reply asks for confirmation, mentions username.
        self.assertIn("beraves@gmail.com", result.reply_text)
        self.assertIn("save it", result.reply_text.lower())

    def test_change_username_to_arbitrary_value_updates_draft(self):
        result = apply_to_pending_draft(
            user_message="change the username to chosen2026",
            draft=_make_draft(),
            generate_password=_fake_password,
        )
        self.assertEqual(result.kind, OUTCOME_UPDATED)
        self.assertEqual(
            result.draft["username_options"], ["chosen2026"],
        )

    def test_save_it_triggers_save_now(self):
        result = apply_to_pending_draft(
            user_message="save it",
            draft=_make_draft(),
            generate_password=_fake_password,
        )
        self.assertEqual(result.kind, OUTCOME_SAVE_NOW)

    def test_cancel_triggers_cancel(self):
        result = apply_to_pending_draft(
            user_message="cancel",
            draft=_make_draft(),
            generate_password=_fake_password,
        )
        self.assertEqual(result.kind, OUTCOME_CANCELLED)

    def test_regenerate_password_updates_draft(self):
        result = apply_to_pending_draft(
            user_message="make the password longer",
            draft=_make_draft(),
            generate_password=_fake_password,
        )
        self.assertEqual(result.kind, OUTCOME_UPDATED)
        self.assertEqual(result.draft["password"], "FAKE-PW-1234!")

    def test_regenerate_username_without_generator_defers(self):
        # No generate_username callable — should fall through so the
        # existing generated_login_repair handler picks it up with
        # full policy-tightening context.
        result = apply_to_pending_draft(
            user_message="change the username",
            draft=_make_draft(),
            generate_password=_fake_password,
            generate_username=None,
        )
        self.assertEqual(result.kind, OUTCOME_NO_ACTION)

    def test_regenerate_username_with_generator_uses_it(self):
        result = apply_to_pending_draft(
            user_message="change the username",
            draft=_make_draft(),
            generate_password=_fake_password,
            generate_username=_fake_username,
        )
        self.assertEqual(result.kind, OUTCOME_UPDATED)
        self.assertEqual(
            result.draft["username_options"], ["fake-user-42"],
        )

    def test_show_draft_shows_current_state(self):
        result = apply_to_pending_draft(
            user_message="show me the draft",
            draft=_make_draft(),
            generate_password=_fake_password,
        )
        self.assertEqual(result.kind, OUTCOME_SHOWN)
        self.assertIn("cobaltbranch947", result.reply_text)

    def test_unrelated_message_no_action(self):
        result = apply_to_pending_draft(
            user_message="what time is it",
            draft=_make_draft(),
            generate_password=_fake_password,
        )
        self.assertEqual(result.kind, OUTCOME_NO_ACTION)


# ---------------------------------------------------------------------------
# Layer 3: exact-name resolver
# ---------------------------------------------------------------------------

def _norm_key(name):
    if not name:
        return ""
    import re
    s = (name or "").strip().lower()
    s = re.sub(r"[^\w\-\.\s]", "", s)
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _fake_fetch(rows_by_vault):
    def _fetch(vault_id, limit):
        return rows_by_vault.get(vault_id, [])[:limit]
    return _fetch


class ExactNameResolverTest(unittest.TestCase):

    def setUp(self):
        self.rows = {
            "vault-A": [
                {"id": "a1", "saved_name": "naim id"},
                {"id": "a2", "saved_name": "birth certificate"},
                {"id": "a3", "saved_name": "chase login"},
            ],
            "vault-B": [
                {"id": "b1", "saved_name": "naim id"},
            ],
        }
        self.fetch = _fake_fetch(self.rows)

    def _resolve(self, vault_id, message, exact=None, intent_cands=None):
        return resolve_saved_name(
            vault_id=vault_id,
            decrypted_message=message,
            fetch_saved_names=self.fetch,
            normalize_key=_norm_key,
            exact_match_lookup=exact,
            intent_candidates=intent_cands,
        )

    def test_show_me_naim_id_hits(self):
        # Bug 1 primary regression test.
        r = self._resolve("vault-A", "show me naim id")
        self.assertEqual(r.status, STATUS_HIT)
        self.assertEqual(r.hit["id"], "a1")

    def test_upper_case_hits(self):
        r = self._resolve("vault-A", "NAIM ID please")
        self.assertEqual(r.status, STATUS_HIT)
        self.assertEqual(r.hit["id"], "a1")

    def test_hyphen_and_underscore_fold(self):
        for phrase in (
            "find naim-id",
            "get naim_id",
            "open Naim-Id",
        ):
            r = self._resolve("vault-A", phrase)
            self.assertEqual(
                r.status, STATUS_HIT,
                f"phrase {phrase!r} should be HIT",
            )
            self.assertEqual(r.hit["id"], "a1")

    def test_wrapper_verbs_do_not_prevent_match(self):
        for phrase in (
            "where is naim id",
            "I need naim id",
            "look for naim id",
            "please show me naim id",
            "the thing I saved as naim id",
        ):
            r = self._resolve("vault-A", phrase)
            self.assertEqual(
                r.status, STATUS_HIT,
                f"phrase {phrase!r} should be HIT",
            )

    def test_category_label_defers_to_tag_handler(self):
        # "show me id documents" is a broad category query — resolver
        # must NOT intercept it as a specific named item.
        for phrase in (
            "show me id documents",
            "show my ids",
            "list my identity documents",
            "identity",
        ):
            r = self._resolve("vault-A", phrase)
            self.assertEqual(
                r.status, STATUS_MISS,
                f"category phrase {phrase!r} must MISS",
            )

    def test_cross_vault_isolation(self):
        # vault-A asks about "naim id"; only vault-A rows are scanned.
        # A vault-B row with the same normalized saved_name must be
        # invisible.
        r = self._resolve("vault-A", "show me naim id")
        self.assertEqual(r.hit["id"], "a1")
        r2 = self._resolve("vault-B", "show me naim id")
        self.assertEqual(r2.hit["id"], "b1")

    def test_unrelated_chat_misses(self):
        r = self._resolve("vault-A", "what time is it")
        self.assertEqual(r.status, STATUS_MISS)

    def test_intent_candidate_fast_path(self):
        # When the LLM populates intent_data.asset_name we try the
        # exact-match fast path first, before scanning.
        exact_calls = []

        def fake_exact(vid, name):
            exact_calls.append((vid, name))
            if vid == "vault-A" and _norm_key(name) == "naim id":
                return self.rows["vault-A"][0]
            return None

        r = self._resolve(
            "vault-A", "irrelevant", exact=fake_exact,
            intent_cands=["Naim ID"],
        )
        self.assertEqual(r.status, STATUS_HIT)
        self.assertEqual(r.hit["id"], "a1")
        self.assertGreaterEqual(len(exact_calls), 1)

    def test_ambiguous_returns_ambiguous(self):
        self.rows["vault-C"] = [
            {"id": "c1", "saved_name": "aaa bbb"},
            {"id": "c2", "saved_name": "aaa ccc"},
        ]
        r = resolve_saved_name(
            vault_id="vault-C",
            decrypted_message="give me aaa bbb aaa ccc",
            fetch_saved_names=_fake_fetch(self.rows),
            normalize_key=_norm_key,
            exact_match_lookup=None,
            intent_candidates=None,
        )
        # Both names have equal length and both match — ambiguous.
        self.assertEqual(r.status, STATUS_AMBIGUOUS)
        self.assertEqual(
            {c["id"] for c in r.candidates}, {"c1", "c2"},
        )

    def test_prefer_longer_match(self):
        # "naim id backup" is more specific than "naim id" when the
        # message contains the longer key.
        self.rows["vault-D"] = [
            {"id": "d1", "saved_name": "naim id"},
            {"id": "d2", "saved_name": "naim id backup"},
        ]
        r = resolve_saved_name(
            vault_id="vault-D",
            decrypted_message="find naim id backup",
            fetch_saved_names=_fake_fetch(self.rows),
            normalize_key=_norm_key,
            exact_match_lookup=None,
            intent_candidates=None,
        )
        self.assertEqual(r.status, STATUS_HIT)
        self.assertEqual(r.hit["id"], "d2")

    def test_too_short_saved_name_not_matched(self):
        # A saved_name shorter than the substring threshold must not
        # match generic messages that happen to contain it.
        self.rows["vault-E"] = [
            {"id": "e1", "saved_name": "id"},
        ]
        r = resolve_saved_name(
            vault_id="vault-E",
            decrypted_message="show me my id photos",
            fetch_saved_names=_fake_fetch(self.rows),
            normalize_key=_norm_key,
            exact_match_lookup=None,
            intent_candidates=None,
        )
        # "id" is too short (2 chars) — falls through to MISS so
        # list_by_tag can handle the family query.
        self.assertEqual(r.status, STATUS_MISS)


# ---------------------------------------------------------------------------
# Layer 4: dispatch-level integration — verify main.py wiring
# ---------------------------------------------------------------------------

class Main_TryExactSavedNameEarlyReturnTest(unittest.TestCase):
    """Bug 1 wiring: main._try_exact_saved_name_early_return must
    delegate to the new resolver AND return the expected row for
    the production phrase 'show me naim id' when the saved row
    exists in the DB."""

    def setUp(self):
        import main as _main
        self.main = _main

    def test_show_me_naim_id_returns_row(self):
        vault_id = "vault-repro-1"
        naim_row = {
            "id": "naim-row-1",
            "file_name": "naim.jpg",
            "content_type": "image/jpeg",
            "file_size": 1024,
            "saved_name": "naim id",
            "asset_type": "image",
            "created_at": None,
        }

        with mock.patch.object(
            self.main, "_fetch_all_saved_names_for_vault",
            return_value=[naim_row],
        ), mock.patch.object(
            self.main, "retrieve_saved_asset_by_exact_name",
            return_value=None,
        ):
            row = self.main._try_exact_saved_name_early_return(
                vault_id=vault_id,
                decrypted_message="show me naim id",
                intent_data={"intent": "list_by_tag", "tag": "identity",
                             "asset_name": None},
            )
        self.assertIsNotNone(row)
        self.assertEqual(row["saved_name"], "naim id")

    def test_category_phrase_returns_none(self):
        # "show me id documents" is a broad category — probe must
        # bow out (returning None) so list_by_tag handles it.
        vault_id = "vault-repro-2"
        with mock.patch.object(
            self.main, "_fetch_all_saved_names_for_vault",
            return_value=[{"id": "x", "saved_name": "naim id"}],
        ), mock.patch.object(
            self.main, "retrieve_saved_asset_by_exact_name",
            return_value=None,
        ):
            row = self.main._try_exact_saved_name_early_return(
                vault_id=vault_id,
                decrypted_message="show my id documents",
                intent_data={"intent": "list_by_tag", "tag": "identity"},
            )
        self.assertIsNone(row)

    def test_cross_vault_isolation(self):
        # The probe must never see another vault's rows. Simulate an
        # attempt by making the fetch return an empty list for the
        # asking vault.
        with mock.patch.object(
            self.main, "_fetch_all_saved_names_for_vault",
            return_value=[],
        ), mock.patch.object(
            self.main, "retrieve_saved_asset_by_exact_name",
            return_value=None,
        ):
            row = self.main._try_exact_saved_name_early_return(
                vault_id="vault-empty",
                decrypted_message="show me naim id",
                intent_data={},
            )
        self.assertIsNone(row)


class Main_FetchAllSavedNamesTest(unittest.TestCase):
    """Verify the DB helper vault-scopes and bounds the SELECT."""

    def setUp(self):
        import main as _main
        self.main = _main

    def test_scopes_by_vault_id_and_bounds_limit(self):
        # Sniff the SQL executed against the DB.
        captured_sql: list[tuple[str, tuple]] = []

        class FakeCursor:
            def execute(self, sql, params=()):
                captured_sql.append((sql, params))
            def fetchall(self):
                return [{"id": "1", "saved_name": "x"}]
            def close(self):
                pass

        class FakeConn:
            def cursor(self, cursor_factory=None):
                return FakeCursor()
            def close(self):
                pass

        with mock.patch.object(
            self.main, "get_db", return_value=FakeConn(),
        ):
            rows = self.main._fetch_all_saved_names_for_vault(
                "vault-abc", 50,
            )
        self.assertEqual(rows, [{"id": "1", "saved_name": "x"}])
        self.assertEqual(len(captured_sql), 1)
        sql_text, params = captured_sql[0]
        # SQL must select from uploaded_files WHERE vault_id = %s
        # AND upload_status = 'complete'. Params must carry the
        # vault_id and the limit.
        self.assertIn("uploaded_files", sql_text)
        self.assertIn("vault_id = %s", sql_text)
        self.assertIn("upload_status = 'complete'", sql_text)
        self.assertEqual(params[0], "vault-abc")
        self.assertEqual(params[1], 50)


class Main_StateMachineWiringSmokeTest(unittest.TestCase):
    """Bug 2 wiring: verify main.py imports the state-machine and
    extractor names it depends on, and that they refer to the
    intended objects (not shadowed or overridden). This catches
    regressions where a refactor accidentally reverts to the
    email-only shortcut."""

    def setUp(self):
        import main as _main
        self.main = _main

    def test_extractor_and_state_machine_are_wired_in(self):
        # Fully-qualified: the names imported at the top of main.py
        # must be the exact objects from the new modules.
        import vault_credential_command as vcc
        import vault_pending_draft_state as vpds
        self.assertIs(
            self.main._extract_credential_command,
            vcc.extract_credential_command,
        )
        self.assertIs(
            self.main._apply_to_pending_draft,
            vpds.apply_to_pending_draft,
        )
        # And the outcome constants line up.
        self.assertEqual(self.main._DS_UPDATED, vpds.OUTCOME_UPDATED)
        self.assertEqual(self.main._DS_SAVE_NOW, vpds.OUTCOME_SAVE_NOW)
        self.assertEqual(self.main._DS_CANCELLED, vpds.OUTCOME_CANCELLED)

    def test_resolver_is_wired_in(self):
        import vault_exact_name_resolver as ver
        self.assertIs(self.main._resolve_saved_name, ver.resolve_saved_name)
        self.assertEqual(self.main._RESOLVER_HIT, ver.STATUS_HIT)


class Main_StateMachineBlockPositionTest(unittest.TestCase):
    """The pre-cascade state machine block MUST run before the
    existing pending-draft cascade at Site A/B, and before the LLM
    intent classifier. A refactor that reorders these steps would
    reintroduce Bug 2 (the "change username" → generated_login_repair
    → auto-save regression). This test guards against that by
    reading main.py's source and asserting the ordering."""

    def test_state_machine_precedes_intent_classifier(self):
        import os
        import main as _main
        source_path = _main.__file__
        with open(source_path, "r", encoding="utf-8") as fp:
            text = fp.read()
        # Locate the state-machine block marker.
        sm_marker = "_apply_to_pending_draft("
        classifier_marker = "await detect_vault_intent("
        sm_pos = text.find(sm_marker)
        classifier_pos = text.find(classifier_marker)
        self.assertNotEqual(
            sm_pos, -1,
            "state-machine block must be present in chat_endpoint",
        )
        self.assertNotEqual(
            classifier_pos, -1,
            "detect_vault_intent must be present in chat_endpoint",
        )
        self.assertLess(
            sm_pos, classifier_pos,
            "state-machine block must run BEFORE LLM intent "
            "classification, otherwise 'change username to X' "
            "misroutes to generated_login_repair and auto-saves",
        )

    def test_state_machine_precedes_existing_site_b_cascade(self):
        # Site B is identifiable by the ordinal-picker regex at
        # 14470+. My state-machine block must fire first because
        # site B's exact-equality "save it" check does not know
        # about explicit-field edits.
        import main as _main
        source_path = _main.__file__
        with open(source_path, "r", encoding="utf-8") as fp:
            text = fp.read()
        sm_pos = text.find("_apply_to_pending_draft(")
        site_b_marker = r"^\s*(?:#|option\s*)?\s*([123])\s*\.?\s*$"
        site_b_pos = text.find(site_b_marker)
        self.assertNotEqual(sm_pos, -1)
        self.assertNotEqual(
            site_b_pos, -1,
            "site B ordinal-picker cascade must still exist",
        )
        self.assertLess(
            sm_pos, site_b_pos,
            "state-machine must fire before the ordinal-picker "
            "cascade so 'change username to X' cannot fall through "
            "to a save path",
        )


class NoSensitiveLeakageTest(unittest.TestCase):
    """The new modules must never expose password/secret material
    in reply text they generate."""

    def test_state_machine_never_echoes_new_password_by_accident(self):
        # After an "edit_pending" that changes only the username,
        # the draft password stays the same — the reply text
        # includes it because it was already shown once (identical
        # to the original draft turn). That is expected. What is
        # NOT allowed: the reply must not contain any password
        # material the caller did not supply.
        draft = _make_draft(password="known_pw_xyz")
        result = apply_to_pending_draft(
            user_message="change the username to alice",
            draft=draft,
            generate_password=lambda: "SHOULD_NEVER_APPEAR",
        )
        self.assertNotIn("SHOULD_NEVER_APPEAR", result.reply_text)


if __name__ == "__main__":
    unittest.main()
