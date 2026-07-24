"""Tests for the first-class Draft state module.

Covers:
    * closed-schema field validation
    * DRAFT_LOGIN rejects raw-password-shaped values for password_ref
    * Draft round-trip serialization
    * to_prompt_dict redacts secret-shaped fields
    * storage: put/get/list/cancel/consume
    * TTL: expired drafts are not returned
    * per-session visibility
"""

from __future__ import annotations

import time
import unittest

import vault_chat_draft as vd
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


VAULT = "vault-draft-test"
SESSION = "sess-draft-test"


def _login_fields_ok(now=1_700_000_000.0):
    return {
        "service": vd.DraftField(
            value="Netflix", source=vd.SOURCE_USER_EXPLICIT,
            turn_id="t1", at=now,
        ),
        "username": vd.DraftField(
            value="alice@example.org", source=vd.SOURCE_USER_EXPLICIT,
            turn_id="t1", at=now,
        ),
        "password_ref": vd.DraftField(
            value="memory:pending_login_draft:password",
            source=vd.SOURCE_GENERATED, turn_id="t1", at=now,
        ),
    }


class SchemaValidationTest(unittest.TestCase):

    def test_login_schema_has_expected_fields(self):
        schema = vd.schema_for(vd.DRAFT_LOGIN)
        for name in ("service", "username", "password_ref", "url", "notes"):
            self.assertIn(name, schema)

    def test_unknown_draft_kind_raises(self):
        with self.assertRaises(ValueError):
            vd.schema_for("secure_item")

    def test_is_allowed_field(self):
        self.assertTrue(vd.is_allowed_field(vd.DRAFT_LOGIN, "service"))
        self.assertFalse(vd.is_allowed_field(vd.DRAFT_LOGIN, "password"))
        self.assertFalse(vd.is_allowed_field(vd.DRAFT_LOGIN, "totally_unknown"))

    def test_validate_service_name_passes(self):
        for good in ("Netflix", "Disney+", "GitHub", "Chase Bank", "a.b_c-d"):
            with self.subTest(value=good):
                out = vd.validate_field_value(vd.DRAFT_LOGIN, "service", good)
                self.assertEqual(out, good)

    def test_validate_service_name_rejects(self):
        for bad in ("", "  ", "\x00Netflix", "!bad", "toolong" * 30):
            with self.subTest(value=bad):
                with self.assertRaises(vd.FieldFormatError):
                    vd.validate_field_value(vd.DRAFT_LOGIN, "service", bad)

    def test_validate_username_accepts_email_and_handle(self):
        for good in ("alice@example.org", "alice", "alice.bob_1"):
            with self.subTest(value=good):
                out = vd.validate_field_value(vd.DRAFT_LOGIN, "username", good)
                self.assertEqual(out, good)

    def test_validate_username_rejects_bad(self):
        for bad in ("", "hi there", "alice@", "@no", "x" * 400):
            with self.subTest(value=bad):
                with self.assertRaises(vd.FieldFormatError):
                    vd.validate_field_value(vd.DRAFT_LOGIN, "username", bad)


class PasswordRefRejectsRawPasswordTest(unittest.TestCase):
    """Draft schema rejects raw password storage.

    The password_ref field is a colon-delimited opaque reference,
    not a place to store a real password.
    """

    def test_accepts_opaque_ref(self):
        for good in (
            "memory:pending_login_draft:password",
            "bag:abcd_ef01:pw",
            "vault_ref:x1:y2:z3",
        ):
            with self.subTest(value=good):
                self.assertEqual(
                    vd.validate_field_value(
                        vd.DRAFT_LOGIN, "password_ref", good,
                    ),
                    good,
                )

    def test_rejects_raw_password_shaped_strings(self):
        for bad in (
            "MyStrongPassword123!",
            "Tr0ub4dor&3",
            "correct horse battery staple",
            "abc",              # too short + no colon
            "no_colons_here",   # no colon segment
            "Upper:Case",       # uppercase
            "1leading:digit",   # leading digit
            "space in:ref",     # space
            "",                 # empty
            "just:!",           # invalid segment chars
        ):
            with self.subTest(value=bad):
                with self.assertRaises(vd.FieldFormatError):
                    vd.validate_field_value(
                        vd.DRAFT_LOGIN, "password_ref", bad,
                    )

    def test_draft_construction_rejects_bad_password_ref(self):
        fields = _login_fields_ok()
        fields["password_ref"] = vd.DraftField(
            value="ActualPasswordString1!",
            source=vd.SOURCE_GENERATED, turn_id="t1", at=1_700_000_000.0,
        )
        with self.assertRaises(vd.FieldFormatError):
            vd.new_draft(
                vault_id=VAULT, session_id=SESSION,
                draft_kind=vd.DRAFT_LOGIN,
                initial_fields=fields, origin_turn_id="t1",
            )

    def test_draft_construction_rejects_unknown_field(self):
        fields = _login_fields_ok()
        fields["password"] = vd.DraftField(
            value="not-allowed",
            source=vd.SOURCE_GENERATED, turn_id="t1", at=1_700_000_000.0,
        )
        with self.assertRaises(vd.FieldFormatError):
            vd.new_draft(
                vault_id=VAULT, session_id=SESSION,
                draft_kind=vd.DRAFT_LOGIN,
                initial_fields=fields, origin_turn_id="t1",
            )


class DraftLifecycleTest(unittest.TestCase):

    def test_new_draft_starts_editable(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(), origin_turn_id="t1",
        )
        self.assertEqual(d.status, vd.STATUS_EDITABLE)

    def test_with_status_transitions_and_refreshes_ttl(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(now=1000.0),
            origin_turn_id="t1", now=1000.0,
        )
        d2 = vd.with_status(
            d, vd.STATUS_PRESENTED_FOR_CONFIRMATION,
            touch_turn_id="t2", now=1100.0,
        )
        self.assertEqual(d2.status, vd.STATUS_PRESENTED_FOR_CONFIRMATION)
        self.assertEqual(d2.last_touch_turn_id, "t2")
        self.assertGreater(d2.expires_at, d.expires_at)
        # Immutability of the original
        self.assertEqual(d.status, vd.STATUS_EDITABLE)

    def test_with_status_can_avoid_ttl_refresh(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(now=1000.0),
            origin_turn_id="t1", now=1000.0,
        )
        d2 = vd.with_status(
            d, vd.STATUS_PRESENTED_FOR_CONFIRMATION,
            touch_turn_id="t2", now=1100.0, refresh_ttl=False,
        )
        self.assertEqual(d2.expires_at, d.expires_at)


class PromptViewRedactionTest(unittest.TestCase):

    def test_prompt_view_hides_password_ref_value(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(), origin_turn_id="t1",
        )
        view = d.to_prompt_dict()
        self.assertIn("password_ref", view["fields"])
        pw = view["fields"]["password_ref"]
        self.assertNotIn("value", pw)
        self.assertTrue(pw["present"])
        self.assertEqual(pw["source"], vd.SOURCE_GENERATED)

    def test_prompt_view_exposes_non_secret_values(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(), origin_turn_id="t1",
        )
        view = d.to_prompt_dict()
        self.assertEqual(view["fields"]["service"]["value"], "Netflix")
        self.assertEqual(
            view["fields"]["username"]["value"], "alice@example.org",
        )


class DraftJsonRoundTripTest(unittest.TestCase):

    def test_round_trip_preserves_all_fields(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(), origin_turn_id="t1",
            now=1_700_000_000.0,
        )
        d2 = vd.Draft.from_json(d.to_json())
        self.assertEqual(d.draft_id, d2.draft_id)
        self.assertEqual(d.vault_id, d2.vault_id)
        self.assertEqual(d.session_id, d2.session_id)
        self.assertEqual(d.draft_kind, d2.draft_kind)
        self.assertEqual(d.status, d2.status)
        for name in ("service", "username", "password_ref"):
            self.assertEqual(d.fields[name].value, d2.fields[name].value)
            self.assertEqual(d.fields[name].source, d2.fields[name].source)


class StorageTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_store_and_get(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(), origin_turn_id="t1",
        )
        vd.store_draft(d)
        d2 = vd.get_draft(VAULT, d.draft_id)
        self.assertIsNotNone(d2)
        self.assertEqual(d2.draft_id, d.draft_id)

    def test_get_missing_returns_none(self):
        self.assertIsNone(vd.get_draft(VAULT, "no-such-id"))

    def test_cancel_deletes(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(), origin_turn_id="t1",
        )
        vd.store_draft(d)
        removed = vd.cancel_draft(VAULT, d.draft_id)
        self.assertTrue(removed)
        self.assertIsNone(vd.get_draft(VAULT, d.draft_id))

    def test_consume_returns_and_deletes(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(), origin_turn_id="t1",
        )
        vd.store_draft(d)
        got = vd.consume_draft(VAULT, d.draft_id)
        self.assertIsNotNone(got)
        self.assertEqual(got.draft_id, d.draft_id)
        self.assertIsNone(vd.get_draft(VAULT, d.draft_id))

    def test_list_live_drafts_orders_by_updated_at(self):
        now = time.time()
        d1 = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(now=now),
            origin_turn_id="t1", now=now,
        )
        d2 = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(now=now + 10),
            origin_turn_id="t2", now=now + 10,
        )
        vd.store_draft(d1)
        vd.store_draft(d2)
        lst = vd.list_live_drafts(VAULT, session_id=SESSION)
        self.assertEqual(len(lst), 2)
        self.assertEqual(lst[0].draft_id, d2.draft_id)   # newer first

    def test_list_live_drafts_hides_other_session(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(), origin_turn_id="t1",
        )
        vd.store_draft(d)
        self.assertEqual(
            vd.list_live_drafts(VAULT, session_id="OTHER_SESSION"),
            [],
        )
        self.assertEqual(len(vd.list_live_drafts(VAULT, session_id=SESSION)), 1)


class ExpiryTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_expired_draft_not_returned_by_get(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(now=1000.0),
            origin_turn_id="t1", now=1000.0,
            ttl_seconds=1,
        )
        vd.store_draft(d)
        # advance the clock past expiry
        self.assertIsNone(vd.get_draft(VAULT, d.draft_id, now=2000.0))

    def test_expired_draft_absent_from_list(self):
        d = vd.new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=vd.DRAFT_LOGIN,
            initial_fields=_login_fields_ok(now=1000.0),
            origin_turn_id="t1", now=1000.0,
            ttl_seconds=1,
        )
        vd.store_draft(d)
        lst = vd.list_live_drafts(VAULT, session_id=SESSION, now=2000.0)
        self.assertEqual(lst, [])


if __name__ == "__main__":
    unittest.main()
