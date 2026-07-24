"""Tests for SemanticDecisionV2 — dataclasses, validator, parser.

Structural validation only. Semantic checks that require the
snapshot (focus binding, per-draft_kind field allowlist,
confidence-threshold execution) belong to the policy layer
(commit 3) and are not exercised here.
"""

from __future__ import annotations

import json
import unittest

import vault_chat_semantic_decision_v2 as sd


def _valid_decision_dict(**overrides):
    base = {
        "schema_version": sd.SEMANTIC_DECISION_V2_SCHEMA_VERSION,
        "intent":         sd.INTENT_EDIT_DRAFT,
        "target":         {"kind": sd.TARGET_KIND_DRAFT, "id": "d-1"},
        "field_patch": {
            "username": {"op": sd.OP_REPLACE, "value": "alice@example.org"},
        },
        "requested_operations": [],
        "authorization":        {"granted": False},
        "confidence":           0.9,
        "reason":               "user changed the username",
    }
    for k, v in overrides.items():
        if v is None and k in base:
            del base[k]
        else:
            base[k] = v
    return base


# =====================================================================
# Dataclass validation
# =====================================================================

class TargetRefTest(unittest.TestCase):

    def test_none_kind_rejects_id(self):
        with self.assertRaises(ValueError):
            sd.TargetRef(kind=sd.TARGET_KIND_NONE, id="oops")

    def test_kind_draft_requires_id(self):
        with self.assertRaises(ValueError):
            sd.TargetRef(kind=sd.TARGET_KIND_DRAFT, id=None)

    def test_unknown_kind_rejects(self):
        with self.assertRaises(ValueError):
            sd.TargetRef(kind="bogus", id="d-1")

    def test_valid_target(self):
        t = sd.TargetRef(kind=sd.TARGET_KIND_DRAFT, id="d-1")
        self.assertEqual(t.kind, "draft")


class FieldPatchItemTest(unittest.TestCase):

    def test_replace_requires_value(self):
        with self.assertRaises(ValueError):
            sd.FieldPatchItem(op=sd.OP_REPLACE)

    def test_clear_forbids_value(self):
        with self.assertRaises(ValueError):
            sd.FieldPatchItem(op=sd.OP_CLEAR, value="x")

    def test_regenerate_forbids_value(self):
        with self.assertRaises(ValueError):
            sd.FieldPatchItem(op=sd.OP_REGENERATE, value="x")

    def test_unchanged_forbids_value(self):
        with self.assertRaises(ValueError):
            sd.FieldPatchItem(op=sd.OP_UNCHANGED, value="x")

    def test_replace_with_value(self):
        item = sd.FieldPatchItem(op=sd.OP_REPLACE, value="hello")
        self.assertEqual(item.value, "hello")

    def test_clear_bare(self):
        item = sd.FieldPatchItem(op=sd.OP_CLEAR)
        self.assertEqual(item.op, "clear")

    def test_unknown_op_rejects(self):
        with self.assertRaises(ValueError):
            sd.FieldPatchItem(op="explode")


class RequestedOperationTest(unittest.TestCase):

    def test_generate_password_on_password_ref_ok(self):
        ro = sd.RequestedOperation(
            operation=sd.OPERATION_GENERATE_PASSWORD, field="password_ref",
        )
        self.assertIsNone(ro.policy_hint)

    def test_generate_password_on_wrong_field_rejects(self):
        with self.assertRaises(ValueError):
            sd.RequestedOperation(
                operation=sd.OPERATION_GENERATE_PASSWORD, field="username",
            )

    def test_unknown_operation_rejects(self):
        with self.assertRaises(ValueError):
            sd.RequestedOperation(operation="steal_password", field="password_ref")


class AuthorizationTest(unittest.TestCase):

    def test_granted_requires_scope(self):
        with self.assertRaises(ValueError):
            sd.Authorization(granted=True, scope=None)

    def test_ungranted_can_omit_scope(self):
        a = sd.Authorization(granted=False)
        self.assertIsNone(a.scope)

    def test_scope_action_must_be_known(self):
        with self.assertRaises(ValueError):
            sd.AuthorizationScope(target_id="d-1", action="drop_table")


class SemanticDecisionV2SchemaVersionTest(unittest.TestCase):

    def test_current_version_is_one(self):
        self.assertEqual(sd.SEMANTIC_DECISION_V2_SCHEMA_VERSION, 1)

    def test_constructor_rejects_unknown_version(self):
        with self.assertRaises(ValueError):
            sd.SemanticDecisionV2(
                schema_version=99,
                intent=sd.INTENT_CHAT,
                target=sd.TargetRef(kind=sd.TARGET_KIND_NONE, id=None),
                field_patch={},
                requested_operations=(),
                authorization=sd.Authorization(granted=False),
                confidence=0.5,
                reason="",
            )


# =====================================================================
# validate_semantic_decision_v2
# =====================================================================

class ValidatorTopLevelTest(unittest.TestCase):

    def test_happy_path(self):
        decision = sd.validate_semantic_decision_v2(
            _valid_decision_dict(),
        )
        self.assertEqual(decision.intent, sd.INTENT_EDIT_DRAFT)
        self.assertEqual(decision.target.id, "d-1")
        self.assertIn("username", decision.field_patch)
        self.assertEqual(decision.confidence, 0.9)

    def test_rejects_non_object_payload(self):
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2("not a dict")

    def test_rejects_unknown_top_level_key(self):
        d = _valid_decision_dict()
        d["extra_key"] = 42
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_rejects_unknown_schema_version(self):
        d = _valid_decision_dict()
        d["schema_version"] = 99
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_rejects_missing_schema_version(self):
        d = _valid_decision_dict()
        del d["schema_version"]
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_rejects_unknown_intent(self):
        d = _valid_decision_dict(intent="explode")
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_rejects_bool_confidence(self):
        d = _valid_decision_dict(confidence=True)
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_rejects_confidence_out_of_range(self):
        for bad in (-0.1, 1.1, "0.9", None):
            with self.subTest(confidence=bad):
                d = _valid_decision_dict(confidence=bad)
                with self.assertRaises(sd.SemanticDecisionValidationError):
                    sd.validate_semantic_decision_v2(d)


class ValidatorTargetTest(unittest.TestCase):

    def test_target_not_object_rejects(self):
        d = _valid_decision_dict(target="d-1")
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_target_unknown_kind_rejects(self):
        d = _valid_decision_dict(target={"kind": "bogus", "id": "x"})
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_target_none_with_id_rejects(self):
        d = _valid_decision_dict(target={"kind": "none", "id": "leftover"})
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_target_id_membership_check_optional(self):
        # Without known_target_ids, id is not cross-checked.
        d = _valid_decision_dict(target={"kind": "draft", "id": "d-99"})
        sd.validate_semantic_decision_v2(d)   # no raise

    def test_target_id_membership_check_when_provided(self):
        d = _valid_decision_dict(target={"kind": "draft", "id": "d-99"})
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(
                d, known_target_ids=frozenset({"d-1", "d-2"}),
            )

    def test_target_id_membership_check_passes_when_present(self):
        d = _valid_decision_dict(target={"kind": "draft", "id": "d-1"})
        sd.validate_semantic_decision_v2(
            d, known_target_ids=frozenset({"d-1", "d-2"}),
        )  # no raise


class ValidatorFieldPatchTest(unittest.TestCase):

    def test_field_patch_on_non_draft_intent_rejects(self):
        d = _valid_decision_dict(intent=sd.INTENT_CHAT)
        # chat intent doesn't allow field_patch, but the default
        # dict has one entry — should fail
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_field_patch_absent_is_ok(self):
        d = _valid_decision_dict(
            intent=sd.INTENT_CHAT, field_patch=None,
        )
        # Also clear the requested_operations; default is empty [].
        sd.validate_semantic_decision_v2(d)  # no raise

    def test_field_patch_item_unknown_op_rejects(self):
        d = _valid_decision_dict(
            field_patch={"username": {"op": "explode", "value": "x"}},
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_field_patch_replace_missing_value_rejects(self):
        d = _valid_decision_dict(
            field_patch={"username": {"op": sd.OP_REPLACE}},
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_field_patch_clear_with_value_rejects(self):
        d = _valid_decision_dict(
            field_patch={"username": {"op": sd.OP_CLEAR, "value": "x"}},
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_field_patch_unknown_item_key_rejects(self):
        d = _valid_decision_dict(field_patch={
            "username": {
                "op": sd.OP_REPLACE, "value": "x", "extra": "y",
            },
        })
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)


class ValidatorRequestedOperationsTest(unittest.TestCase):

    def test_requested_ops_on_non_draft_intent_rejects(self):
        d = _valid_decision_dict(
            intent=sd.INTENT_CHAT, field_patch=None,
            requested_operations=[
                {"operation": sd.OPERATION_GENERATE_PASSWORD,
                 "field": "password_ref"},
            ],
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_requested_ops_duplicate_rejects(self):
        d = _valid_decision_dict(requested_operations=[
            {"operation": sd.OPERATION_GENERATE_PASSWORD,
             "field": "password_ref"},
            {"operation": sd.OPERATION_GENERATE_PASSWORD,
             "field": "password_ref"},
        ])
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_requested_ops_unknown_operation_rejects(self):
        d = _valid_decision_dict(requested_operations=[
            {"operation": "steal", "field": "password_ref"},
        ])
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_requested_ops_wrong_field_rejects(self):
        d = _valid_decision_dict(requested_operations=[
            {"operation": sd.OPERATION_GENERATE_PASSWORD,
             "field": "username"},
        ])
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)


class ValidatorAuthorizationTest(unittest.TestCase):

    def _confirm_draft_dict(self, **overrides):
        base = _valid_decision_dict(
            intent=sd.INTENT_CONFIRM_DRAFT,
            target={"kind": sd.TARGET_KIND_DRAFT, "id": "d-1"},
            field_patch=None,
            authorization={
                "granted": True,
                "scope": {"target_id": "d-1", "action": "save"},
            },
        )
        for k, v in overrides.items():
            base[k] = v
        return base

    def test_confirm_draft_happy_path(self):
        d = self._confirm_draft_dict()
        sd.validate_semantic_decision_v2(d)  # no raise

    def test_grant_on_non_confirm_intent_rejects(self):
        d = _valid_decision_dict(
            intent=sd.INTENT_CHAT, field_patch=None,
            authorization={
                "granted": True,
                "scope": {"target_id": "d-1", "action": "save"},
            },
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_grant_without_scope_rejects(self):
        d = self._confirm_draft_dict(
            authorization={"granted": True},
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_scope_target_id_mismatch_rejects(self):
        d = self._confirm_draft_dict(
            authorization={
                "granted": True,
                "scope": {"target_id": "d-DIFFERENT", "action": "save"},
            },
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_scope_missing_action_rejects_when_granted(self):
        d = self._confirm_draft_dict(
            authorization={
                "granted": True,
                "scope": {"target_id": "d-1"},
            },
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)

    def test_action_incompatible_with_target_kind_rejects(self):
        # delete on a draft target is not compatible
        d = self._confirm_draft_dict(
            authorization={
                "granted": True,
                "scope": {"target_id": "d-1", "action": "delete"},
            },
        )
        with self.assertRaises(sd.SemanticDecisionValidationError):
            sd.validate_semantic_decision_v2(d)


class ValidatorHappyIntentsTest(unittest.TestCase):
    """Each intent that carries no patch/ops/auth can be produced
    with a minimal decision that passes structural validation."""

    def _minimal(self, intent):
        return {
            "schema_version": 1,
            "intent":         intent,
            "target":         {"kind": "none", "id": None},
            "field_patch":    {},
            "requested_operations": [],
            "authorization":  {"granted": False},
            "confidence":     0.9,
            "reason":         "",
        }

    def test_answer_question(self):
        sd.validate_semantic_decision_v2(self._minimal(sd.INTENT_ANSWER_QUESTION))

    def test_ask_clarification(self):
        sd.validate_semantic_decision_v2(self._minimal(sd.INTENT_ASK_CLARIFICATION))

    def test_chat(self):
        sd.validate_semantic_decision_v2(self._minimal(sd.INTENT_CHAT))

    def test_fallthrough(self):
        sd.validate_semantic_decision_v2(self._minimal(sd.INTENT_FALLTHROUGH))


# =====================================================================
# parse_semantic_decision_v2
# =====================================================================

class ParserTest(unittest.TestCase):

    def test_empty_text_becomes_fallthrough_with_error(self):
        r = sd.parse_semantic_decision_v2("")
        self.assertTrue(r.is_fallthrough())
        self.assertEqual(r.error, "empty_content")

    def test_non_json_becomes_fallthrough(self):
        r = sd.parse_semantic_decision_v2("hello world, no json here")
        self.assertTrue(r.is_fallthrough())
        self.assertEqual(r.error, "json_parse_failed")

    def test_valid_json_parses_ok(self):
        r = sd.parse_semantic_decision_v2(
            json.dumps(_valid_decision_dict()),
        )
        self.assertFalse(r.is_fallthrough())
        self.assertEqual(r.intent, sd.INTENT_EDIT_DRAFT)

    def test_valid_json_in_fenced_block_parses(self):
        text = "```json\n" + json.dumps(_valid_decision_dict()) + "\n```"
        r = sd.parse_semantic_decision_v2(text)
        self.assertFalse(r.is_fallthrough())

    def test_valid_json_with_leading_prose_parses(self):
        text = "Here you go: " + json.dumps(_valid_decision_dict())
        r = sd.parse_semantic_decision_v2(text)
        self.assertFalse(r.is_fallthrough())

    def test_structural_failure_becomes_fallthrough_with_error(self):
        bad = _valid_decision_dict()
        bad["intent"] = "explode"
        r = sd.parse_semantic_decision_v2(json.dumps(bad))
        self.assertTrue(r.is_fallthrough())
        self.assertTrue(r.error.startswith("unknown_intent"))

    def test_unknown_target_id_with_known_set_becomes_fallthrough(self):
        r = sd.parse_semantic_decision_v2(
            json.dumps(_valid_decision_dict(
                target={"kind": "draft", "id": "d-DIFFERENT"},
            )),
            known_target_ids=frozenset({"d-1"}),
        )
        self.assertTrue(r.is_fallthrough())
        self.assertEqual(r.error, "unknown_target_id")


class FallthroughFactoryTest(unittest.TestCase):

    def test_make_fallthrough_shape(self):
        r = sd.make_fallthrough(error="some_reason", confidence=0.1)
        self.assertEqual(r.intent, sd.INTENT_FALLTHROUGH)
        self.assertEqual(r.target.kind, sd.TARGET_KIND_NONE)
        self.assertIsNone(r.target.id)
        self.assertEqual(len(r.field_patch), 0)
        self.assertEqual(r.error, "some_reason")
        self.assertFalse(r.authorization.granted)


# =====================================================================
# Cross-module sanity — action/target compatibility mirrors
# vault_chat_authorization_record. If these ever diverge, this
# test loudly fails; keep them in sync.
# =====================================================================

class ActionCompatibilityMirrorTest(unittest.TestCase):

    def test_action_target_kind_compatibility_matches_auth_record(self):
        import vault_chat_authorization_record as vauth
        # Draft-compatible actions
        for action in ("save",):
            self.assertTrue(
                vauth.is_action_compatible_with_target(action, "draft"),
                f"auth says {action}+draft NOT compatible; sd disagrees",
            )
        # Draft-incompatible actions
        for action in ("delete", "save_attachment"):
            self.assertFalse(
                vauth.is_action_compatible_with_target(action, "draft"),
                f"auth says {action}+draft compatible; sd disagrees",
            )


if __name__ == "__main__":
    unittest.main()
