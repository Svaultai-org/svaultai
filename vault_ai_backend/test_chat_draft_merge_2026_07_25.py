"""Tests for the pure Draft merge function.

Covers the mandatory rule matrix from the design memo:

    * newer explicit replaces older explicit
    * generated cannot overwrite explicit
    * omitted field remains unchanged
    * op=clear differs from an absent patch
    * op=regenerate replaces a generated password reference
    * op=regenerate refuses an explicitly supplied password
    * unknown field rejects the entire patch (no partial mutation)
    * op=unchanged is a no-op
"""

from __future__ import annotations

import unittest

import vault_chat_draft as vd
from vault_chat_draft_merge import PatchError, merge


VAULT = "vault-merge-test"
SESSION = "sess-merge-test"


def _login_draft(fields, *, now=1_700_000_000.0, origin_turn_id="t1"):
    return vd.new_draft(
        vault_id=VAULT, session_id=SESSION,
        draft_kind=vd.DRAFT_LOGIN,
        initial_fields=fields, origin_turn_id=origin_turn_id, now=now,
    )


def _explicit(value, *, turn, at=1_700_000_000.0):
    return vd.DraftField(
        value=value, source=vd.SOURCE_USER_EXPLICIT,
        turn_id=turn, at=at,
    )


def _generated(value, *, turn, at=1_700_000_000.0):
    return vd.DraftField(
        value=value, source=vd.SOURCE_GENERATED,
        turn_id=turn, at=at,
    )


def _base_draft(now=1_700_000_000.0):
    return _login_draft({
        "service":      _explicit("Netflix", turn="t1", at=now),
        "username":     _explicit("old@gmail.com", turn="t1", at=now),
        "password_ref": _generated(
            "memory:pending_login_draft:password", turn="t1", at=now,
        ),
    }, now=now)


class NewerExplicitReplacesOlderExplicitTest(unittest.TestCase):

    def test_second_explicit_username_replaces_first_explicit(self):
        d = _base_draft(now=1000.0)
        patched = merge(
            d,
            {"username": {"op": "replace", "value": "new@gmail.com"}},
            patch_source=vd.SOURCE_USER_EXPLICIT,
            patch_turn_id="t2",
            now=1010.0,
        )
        self.assertEqual(patched.fields["username"].value, "new@gmail.com")
        self.assertEqual(
            patched.fields["username"].source, vd.SOURCE_USER_EXPLICIT,
        )
        self.assertEqual(patched.fields["username"].turn_id, "t2")

    def test_same_turn_explicit_is_allowed_idempotent(self):
        d = _base_draft(now=1000.0)
        patched = merge(
            d,
            {"username": {"op": "replace", "value": "old@gmail.com"}},
            patch_source=vd.SOURCE_USER_EXPLICIT,
            patch_turn_id="t1",
            now=1010.0,
        )
        self.assertEqual(patched.fields["username"].value, "old@gmail.com")


class GeneratedCannotOverwriteExplicitTest(unittest.TestCase):

    def test_generated_over_explicit_rejects(self):
        d = _base_draft()
        with self.assertRaises(PatchError) as ctx:
            merge(
                d,
                {"username": {"op": "replace", "value": "handle_x"}},
                patch_source=vd.SOURCE_GENERATED,
                patch_turn_id="t2",
            )
        self.assertIn("generated", str(ctx.exception))

    def test_original_draft_unchanged_after_rejection(self):
        d = _base_draft()
        try:
            merge(
                d,
                {"username": {"op": "replace", "value": "handle_x"}},
                patch_source=vd.SOURCE_GENERATED,
                patch_turn_id="t2",
            )
        except PatchError:
            pass
        self.assertEqual(d.fields["username"].value, "old@gmail.com")

    def test_generated_can_overwrite_generated(self):
        d = _base_draft()
        # Regeneration would use op=regenerate; direct replace of a
        # generated value by another generated value is allowed as
        # long as no explicit exists in that slot.
        patched = merge(
            d,
            {"password_ref": {
                "op": "replace",
                "value": "memory:pending_login_draft:password",
            }},
            patch_source=vd.SOURCE_GENERATED,
            patch_turn_id="t2",
        )
        self.assertEqual(
            patched.fields["password_ref"].source, vd.SOURCE_GENERATED,
        )


class OmittedFieldsUnchangedTest(unittest.TestCase):

    def test_omitted_fields_are_preserved(self):
        d = _base_draft()
        patched = merge(
            d,
            {"notes": {"op": "replace", "value": "family plan"}},
            patch_source=vd.SOURCE_USER_EXPLICIT,
            patch_turn_id="t2",
        )
        self.assertEqual(patched.fields["service"].value, "Netflix")
        self.assertEqual(patched.fields["username"].value, "old@gmail.com")
        self.assertEqual(patched.fields["notes"].value, "family plan")


class ClearVsAbsentTest(unittest.TestCase):

    def test_op_clear_replaces_value_with_CLEARED(self):
        d = _base_draft()
        patched = merge(
            d,
            {"notes": {"op": "replace", "value": "some note"}},
            patch_source=vd.SOURCE_USER_EXPLICIT,
            patch_turn_id="t2",
        )
        patched2 = merge(
            patched,
            {"notes": {"op": "clear"}},
            patch_source=vd.SOURCE_USER_EXPLICIT,
            patch_turn_id="t3",
        )
        self.assertIn("notes", patched2.fields)
        self.assertEqual(patched2.fields["notes"].value, vd.CLEARED)

    def test_op_clear_forbids_value_field(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d,
                {"notes": {"op": "clear", "value": "should not be here"}},
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )

    def test_op_clear_refused_for_non_user_explicit_source(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d,
                {"notes": {"op": "clear"}},
                patch_source=vd.SOURCE_GENERATED,
                patch_turn_id="t2",
            )


class RegenerateTest(unittest.TestCase):

    def test_regenerate_replaces_generated_password_ref(self):
        d = _base_draft()
        patched = merge(
            d,
            {"password_ref": {"op": "regenerate"}},
            patch_source=vd.SOURCE_USER_EXPLICIT,
            patch_turn_id="t2",
        )
        self.assertEqual(
            patched.fields["password_ref"].value, vd.PENDING_GENERATION,
        )
        self.assertEqual(
            patched.fields["password_ref"].source, vd.SOURCE_USER_EXPLICIT,
        )

    def test_regenerate_refuses_explicit_password_ref(self):
        d = _login_draft({
            "service":  _explicit("Netflix", turn="t1"),
            "username": _explicit("me@example.org", turn="t1"),
            "password_ref": _explicit(
                "vault_ref:existing:handle", turn="t1",
            ),
        })
        with self.assertRaises(PatchError):
            merge(
                d,
                {"password_ref": {"op": "regenerate"}},
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )

    def test_regenerate_refused_on_non_regeneratable_field(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d,
                {"username": {"op": "regenerate"}},
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )

    def test_regenerate_forbids_value(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d,
                {"password_ref": {
                    "op": "regenerate",
                    "value": "should not be here",
                }},
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )


class UnknownFieldRejectsPatchTest(unittest.TestCase):

    def test_unknown_field_rejects_whole_patch(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d,
                {
                    "username": {"op": "replace", "value": "new@gmail.com"},
                    "totally_unknown_field": {
                        "op": "replace", "value": "x",
                    },
                },
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )
        # The original draft is unchanged.
        self.assertEqual(d.fields["username"].value, "old@gmail.com")

    def test_unknown_op_rejects(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d,
                {"username": {"op": "explode", "value": "x"}},
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )


class NoPartialUpdateOnFailureTest(unittest.TestCase):

    def test_invalid_patch_produces_no_partial_update(self):
        d = _base_draft()
        # One valid change and one invalid — the whole thing must fail
        # and the original draft must be unchanged.
        try:
            merge(
                d,
                {
                    "username": {"op": "replace", "value": "new@gmail.com"},
                    "service":  {"op": "replace", "value": ""},  # invalid
                },
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )
            self.fail("expected PatchError")
        except PatchError:
            pass
        self.assertEqual(d.fields["username"].value, "old@gmail.com")
        self.assertEqual(d.fields["service"].value, "Netflix")

    def test_password_shaped_replace_value_rejected_no_partial(self):
        d = _base_draft()
        try:
            merge(
                d,
                {
                    "username": {"op": "replace", "value": "new@gmail.com"},
                    "password_ref": {
                        "op": "replace",
                        "value": "ActualPassword1!",  # not an opaque_ref
                    },
                },
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )
            self.fail("expected PatchError")
        except PatchError:
            pass
        self.assertEqual(d.fields["username"].value, "old@gmail.com")


class UnchangedOpTest(unittest.TestCase):

    def test_op_unchanged_is_noop(self):
        d = _base_draft(now=1000.0)
        patched = merge(
            d,
            {"username": {"op": "unchanged"}},
            patch_source=vd.SOURCE_USER_EXPLICIT,
            patch_turn_id="t2",
            now=1010.0,
        )
        self.assertEqual(
            patched.fields["username"].value,
            d.fields["username"].value,
        )
        # But the draft touched metadata IS updated
        self.assertEqual(patched.last_touch_turn_id, "t2")


class PatchShapeTest(unittest.TestCase):

    def test_patch_source_must_be_known(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d,
                {"username": {"op": "replace", "value": "x"}},
                patch_source="mystery",
                patch_turn_id="t2",
            )

    def test_empty_patch_turn_id_rejected(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d,
                {"username": {"op": "replace", "value": "x"}},
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="",
            )

    def test_patch_must_be_mapping(self):
        d = _base_draft()
        with self.assertRaises(PatchError):
            merge(
                d, ["not", "a", "mapping"],
                patch_source=vd.SOURCE_USER_EXPLICIT,
                patch_turn_id="t2",
            )


if __name__ == "__main__":
    unittest.main()
