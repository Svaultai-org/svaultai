"""Tests for the executor adapters (commit 6).

Covers the required matrix from the commit-5b review:

    * registry classifies every EXECUTOR_REQUIRED action kind
    * complete production registry passes readiness
    * missing adapter fails readiness
    * each adapter invokes exactly one underlying primitive
    * target is reloaded before execution (TOC/TOU)
    * stale target prevents primitive invocation
    * wrong vault / wrong session / action mismatch prevents
      primitive invocation
    * draft save resolves password_ref without exposing it
    * raw password is never stored back into a Draft
    * successful draft save consumes draft afterward
    * failed draft save leaves held secret intact + draft retryable
    * pending delete passes db_executor
    * pending delete does not duplicate _execute_pending_delete
    * attachment save retains strict target binding
    * executor exception maps to normalized failure code
    * adapter result contains no reply text
    * telemetry metadata rejects sensitive or unknown keys

Plus integration ordering:
    * authorization minted -> consumed -> adapter invoked ->
      success/failure focus update applied -> deferred reply
    * adapter never runs when mint fails
    * adapter never runs when consume fails
    * adapter runs exactly once after successful consume
"""

from __future__ import annotations

import time
import unittest
from types import MappingProxyType
from typing import Any, Optional
from unittest import mock

import vault_chat_executor_adapters_v2 as adapters
import vault_chat_integration_v2 as vi
from vault_chat_authorization_record import AUTH_ACTION_SAVE
from vault_chat_decision_router_v2 import (
    ACTION_KIND_CANCEL_PENDING,
    ACTION_KIND_CONFIRM_DELETE,
    ACTION_KIND_CONFIRM_SAVE,
    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
    ExecutionPlanV2,
    FocusUpdate,
    FOCUS_ACTION_SET,
    NEXT_STATE_EXECUTE,
    PRESERVE_FOCUS,
    REPLY_KIND_EXECUTION_REQUIRED,
    RouterResultV2,
)
from vault_chat_draft import (
    DRAFT_LOGIN, DraftField, SOURCE_GENERATED, SOURCE_USER_EXPLICIT,
    get_draft, new_draft, store_draft,
)
from vault_chat_focus import (
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION, FOCUS_KIND_DRAFT,
)
from vault_chat_pending_action import (
    KIND_DELETE_SECURE_ITEM, KIND_SAVE_ATTACHMENT,
    KIND_SAVE_LOGIN_DRAFT,
    PendingAction, SOURCE_MEMORY_LOGIN_DRAFT,
    SOURCE_SECURE_DELETE_INTENT, SOURCE_UPLOADED_FILE,
)
from vault_chat_policy_v2 import (
    AuthorizationIntent, PolicySnapshotV2, REASON_ALLOWED,
)
from vault_chat_semantic_decision_v2 import (
    ACTION_DELETE, ACTION_SAVE, ACTION_SAVE_ATTACHMENT,
    FieldPatchItem, TARGET_KIND_DRAFT, TARGET_KIND_PENDING_ACTION,
)
from vault_chat_state_store import (
    InMemoryChatStateBackend, install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


VAULT = "vault-adapt-test"
SESSION = "sess-adapt-test"
KEY_32 = b"\x01" * 32


# =====================================================================
# Shared helpers
# =====================================================================

class _FakeSavedDict:
    """Stands in for chat_memory.SavedDict. Just a dict with
    .get/.pop that also records reads/pops for assertions."""

    def __init__(self, initial: Optional[dict] = None):
        self._d = dict(initial or {})
        self.pop_calls: list[str] = []

    def get(self, key, default=None):
        return self._d.get(key, default)

    def pop(self, key, default=None):
        self.pop_calls.append(key)
        return self._d.pop(key, default)

    def __contains__(self, key):
        return key in self._d


def _snap() -> PolicySnapshotV2:
    return PolicySnapshotV2(
        vault_id=VAULT, session_id=SESSION,
        current_user_turn_id="u-1",
        preceding_assistant_turn_id="a-0",
        now=time.time(),
    )


_ACTION_KIND_TO_REPLY_KEY: dict[str, str] = {
    ACTION_KIND_CONFIRM_SAVE:            "save_draft",
    ACTION_KIND_CONFIRM_DELETE:          "delete_pending",
    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT: "save_attachment_pending",
    ACTION_KIND_CANCEL_PENDING:          "cancel_pending",
}


def _plan(
    *, action_kind: str, target_kind: str,
    target_id: Optional[str], validated_patch=None,
    authorization_intent: Optional[AuthorizationIntent] = None,
) -> ExecutionPlanV2:
    key = _ACTION_KIND_TO_REPLY_KEY.get(action_kind, "save_draft")
    return ExecutionPlanV2(
        action_kind=action_kind, target_kind=target_kind,
        target_id=target_id, authorization_intent=authorization_intent,
        validated_patch=validated_patch,
        success_focus_update=PRESERVE_FOCUS,
        failure_focus_update=PRESERVE_FOCUS,
        success_reply_key=key,
        failure_reply_key=key,
    )


def _ctx_from_plan(
    plan: ExecutionPlanV2, *,
    memory: Any = None, key: bytes = KEY_32,
    db_executor: Optional[Any] = None,
) -> adapters.ExecutorContextV2:
    return adapters.ExecutorContextV2(
        vault_id=VAULT, session_id=SESSION,
        user_turn_id="u-1",
        target_kind=plan.target_kind,
        target_id=plan.target_id,
        validated_patch=plan.validated_patch,
        db_executor=db_executor, key=key, memory=memory,
        plan=plan, snapshot=_snap(),
    )


# =====================================================================
# ExecutorOutcomeV2 shape + telemetry allowlist
# =====================================================================

class OutcomeShapeTest(unittest.TestCase):

    def test_success_outcome(self):
        o = adapters.ExecutorOutcomeV2(
            success=True, result_code=adapters.RESULT_SUCCESS,
        )
        self.assertTrue(o.success)

    def test_success_flag_must_match_code(self):
        with self.assertRaises(ValueError):
            adapters.ExecutorOutcomeV2(
                success=False, result_code=adapters.RESULT_SUCCESS,
            )
        with self.assertRaises(ValueError):
            adapters.ExecutorOutcomeV2(
                success=True, result_code=adapters.RESULT_NOT_FOUND,
            )

    def test_unknown_result_code_rejected(self):
        with self.assertRaises(ValueError):
            adapters.ExecutorOutcomeV2(
                success=False, result_code="MYSTERY",
            )

    def test_telemetry_rejects_unknown_key(self):
        with self.assertRaises(adapters.TelemetryValidationError):
            adapters.ExecutorOutcomeV2(
                success=True, result_code=adapters.RESULT_SUCCESS,
                telemetry_metadata=MappingProxyType({"password": "shh"}),
            )

    def test_telemetry_rejects_pii_shaped_key(self):
        for bad in ("username", "raw_id", "vault_id", "session_id"):
            with self.assertRaises(adapters.TelemetryValidationError):
                adapters.ExecutorOutcomeV2(
                    success=True, result_code=adapters.RESULT_SUCCESS,
                    telemetry_metadata=MappingProxyType({bad: "x"}),
                )

    def test_telemetry_accepts_allowlisted_keys(self):
        o = adapters.ExecutorOutcomeV2(
            success=True, result_code=adapters.RESULT_SUCCESS,
            telemetry_metadata=MappingProxyType({
                "underlying_band": "ok",
                "action_kind": "confirm_save",
            }),
        )
        self.assertIn("underlying_band", o.telemetry_metadata)


# =====================================================================
# ALREADY_CANCELLED result code (commit 6a-1)
# =====================================================================

class AlreadyCancelledCodeTest(unittest.TestCase):
    """SUCCESS and ALREADY_CANCELLED must be distinguishable at
    the result-code level, not overloaded on a single SUCCESS."""

    def test_already_cancelled_is_a_successful_code(self):
        self.assertIn(
            adapters.RESULT_ALREADY_CANCELLED,
            adapters.SUCCESSFUL_RESULT_CODES,
        )
        self.assertIn(
            adapters.RESULT_ALREADY_CANCELLED,
            adapters.RESULT_CODES,
        )

    def test_ok_factory_accepts_already_cancelled(self):
        o = adapters._ok(
            result_code=adapters.RESULT_ALREADY_CANCELLED,
            cancel_kind="already_gone",
        )
        self.assertTrue(o.success)
        self.assertEqual(
            o.result_code, adapters.RESULT_ALREADY_CANCELLED,
        )

    def test_ok_factory_rejects_non_successful_code(self):
        with self.assertRaises(ValueError):
            adapters._ok(result_code=adapters.RESULT_TARGET_STALE)

    def test_fail_factory_rejects_successful_code(self):
        with self.assertRaises(ValueError):
            adapters._fail(adapters.RESULT_SUCCESS)
        with self.assertRaises(ValueError):
            adapters._fail(adapters.RESULT_ALREADY_CANCELLED)

    def test_outcome_success_true_rejects_pure_failure_code(self):
        # success=True + result_code=TARGET_STALE should still raise.
        with self.assertRaises(ValueError):
            adapters.ExecutorOutcomeV2(
                success=True, result_code=adapters.RESULT_TARGET_STALE,
            )

    def test_outcome_success_false_rejects_successful_code(self):
        with self.assertRaises(ValueError):
            adapters.ExecutorOutcomeV2(
                success=False,
                result_code=adapters.RESULT_ALREADY_CANCELLED,
            )


# =====================================================================
# Deterministic telemetry ordering (commit 6a-5)
# =====================================================================

class TelemetryOrderingTest(unittest.TestCase):
    """Same set of telemetry keys must iterate in the same order
    (alphabetical) regardless of caller insertion order. This makes
    rollout log analysis grep-stable."""

    def test_same_keys_different_insertion_order_same_iteration(self):
        a = adapters._ok(
            action_kind="confirm_save",
            underlying_band="ok",
            source_kind="credential_draft",
        )
        b = adapters._ok(
            source_kind="credential_draft",
            underlying_band="ok",
            action_kind="confirm_save",
        )
        self.assertEqual(
            list(a.telemetry_metadata.keys()),
            list(b.telemetry_metadata.keys()),
        )
        # And it's canonical (sorted).
        self.assertEqual(
            list(a.telemetry_metadata.keys()),
            sorted(a.telemetry_metadata.keys()),
        )

    def test_fail_telemetry_also_alphabetical(self):
        o = adapters._fail(
            adapters.RESULT_EXECUTOR_EXCEPTION,
            underlying_band="db_error",
            action_kind="confirm_delete",
        )
        self.assertEqual(
            list(o.telemetry_metadata.keys()),
            sorted(o.telemetry_metadata.keys()),
        )


# =====================================================================
# Registry factory
# =====================================================================

class RegistryFactoryTest(unittest.TestCase):

    def test_factory_produces_complete_registry(self):
        registry = adapters.build_production_executor_registry()
        # Every EXECUTOR_REQUIRED kind is mapped to a callable.
        for kind in vi.EXECUTOR_REQUIRED_ACTION_KINDS:
            self.assertIsNotNone(registry.get(kind))

    def test_factory_passes_readiness(self):
        registry = adapters.build_production_executor_registry()
        ready, missing = vi.validate_v2_runtime_readiness(registry)
        self.assertTrue(ready)
        self.assertEqual(missing, [])

    def test_missing_adapter_fails_readiness(self):
        # Simulate a missing adapter by handing back an empty
        # registry via monkey-patch. Confirm the readiness guard
        # reports missing adapters clearly.
        empty = vi.ExecutorRegistry()
        ready, missing = vi.validate_v2_runtime_readiness(empty)
        self.assertFalse(ready)
        self.assertEqual(
            sorted(missing), sorted(vi.EXECUTOR_REQUIRED_ACTION_KINDS),
        )


# =====================================================================
# Static wiring failure vs runtime dependency failure (6a-2)
# =====================================================================

class FailFastRegistryConstructionTest(unittest.TestCase):
    """Static wiring failures (import missing, symbol renamed)
    MUST raise RegistryConstructionError at build time -- not
    surface as DEPENDENCY_UNAVAILABLE per-call at runtime. The
    application must not advertise itself v2-ready if the
    registry cannot be assembled."""

    def test_import_probe_lists_expected_primitives(self):
        # The probe table should cover every V1 primitive the
        # adapters reach for. If a maintainer adds a new adapter
        # they must also add its imports here.
        probes = dict(adapters._STATIC_IMPORT_PROBES)
        # Expect at least these modules present in the probe map.
        for expected_module in (
            "main",
            "vault_secure_item_save",
            "vault_credential_draft",
            "vault_chat_upload_binding",
            "vault_secure_item_draft",
        ):
            self.assertIn(expected_module, probes)

    def test_probe_success_returns_empty_failures(self):
        failures = adapters._probe_static_imports()
        self.assertEqual(failures, [])

    def test_probe_reports_missing_module(self):
        original = adapters._STATIC_IMPORT_PROBES
        try:
            adapters._STATIC_IMPORT_PROBES = original + (
                ("this_module_does_not_exist_xyzzy", ("foo",)),
            )
            failures = adapters._probe_static_imports()
            self.assertTrue(any(
                "this_module_does_not_exist_xyzzy" in f
                for f in failures
            ))
        finally:
            adapters._STATIC_IMPORT_PROBES = original

    def test_probe_reports_renamed_symbol(self):
        original = adapters._STATIC_IMPORT_PROBES
        try:
            # "main" exists but pick a symbol that doesn't.
            adapters._STATIC_IMPORT_PROBES = original + (
                ("main", ("nonexistent_symbol_qqq",)),
            )
            failures = adapters._probe_static_imports()
            self.assertTrue(any(
                "nonexistent_symbol_qqq" in f and "symbol missing" in f
                for f in failures
            ))
        finally:
            adapters._STATIC_IMPORT_PROBES = original

    def test_construction_raises_when_probe_fails(self):
        original = adapters._STATIC_IMPORT_PROBES
        try:
            adapters._STATIC_IMPORT_PROBES = original + (
                ("this_module_does_not_exist_xyzzy2", ("foo",)),
            )
            with self.assertRaises(adapters.RegistryConstructionError) as cm:
                adapters.build_production_executor_registry()
            self.assertIn(
                "this_module_does_not_exist_xyzzy2", str(cm.exception),
            )
        finally:
            adapters._STATIC_IMPORT_PROBES = original


# =====================================================================
# Shadow / authoritative action-inventory parity (6a-3)
# =====================================================================

class ShadowAuthoritativeParityTest(unittest.TestCase):
    """Shadow mode's observable inventory must equal what a
    complete authoritative registry can handle. Otherwise shadow
    could silently miss an action_kind that only exists in
    authoritative mode (or vice versa)."""

    def test_shadow_inventory_equals_action_kinds(self):
        from vault_chat_decision_router_v2 import ACTION_KINDS
        self.assertEqual(
            vi.get_shadow_observable_inventory(), ACTION_KINDS,
        )

    def test_v2_action_inventory_is_action_kinds(self):
        from vault_chat_decision_router_v2 import ACTION_KINDS
        self.assertEqual(vi.get_v2_action_inventory(), ACTION_KINDS)

    def test_complete_production_registry_has_parity_with_shadow(self):
        registry = adapters.build_production_executor_registry()
        is_parity, diff = vi.assert_shadow_authoritative_parity(registry)
        self.assertTrue(
            is_parity, msg=f"parity broken: symmetric diff={diff}",
        )
        self.assertEqual(diff, [])

    def test_empty_registry_breaks_parity(self):
        empty = vi.ExecutorRegistry()
        is_parity, diff = vi.assert_shadow_authoritative_parity(empty)
        self.assertFalse(is_parity)
        # The diff should be exactly the EXECUTOR_REQUIRED kinds
        # (shadow can observe them; authoritative cannot handle
        # them without wired executors).
        self.assertEqual(
            sorted(diff), sorted(vi.EXECUTOR_REQUIRED_ACTION_KINDS),
        )

    def test_authoritative_inventory_includes_non_executor_natively(self):
        # Even with only some EXECUTOR_REQUIRED wired,
        # NON_EXECUTOR_ACTION_KINDS must be present in the
        # authoritative inventory (integration handles them
        # natively).
        registry = vi.ExecutorRegistry(
            confirm_save=lambda **kw: None,
        )
        auth_inv = vi.get_authoritative_action_inventory(registry)
        for kind in vi.NON_EXECUTOR_ACTION_KINDS:
            self.assertIn(kind, auth_inv)


# =====================================================================
# TOC/TOU checks: action_kind and target_kind mismatch
# =====================================================================

class ContractGuardTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_confirm_save_rejects_wrong_action_kind(self):
        plan = _plan(
            action_kind=ACTION_KIND_CONFIRM_DELETE,
            target_kind=TARGET_KIND_DRAFT, target_id="d-1",
        )
        ctx = _ctx_from_plan(plan)
        with self.assertRaises(vi.ExecutorError):
            adapters.adapter_confirm_save_login(ctx)
        self.assertIsNotNone(ctx.outcome)
        self.assertEqual(
            ctx.outcome.result_code,
            adapters.RESULT_AUTHORIZATION_CONTEXT_INVALID,
        )

    def test_confirm_save_rejects_wrong_target_kind(self):
        plan = _plan(
            action_kind=ACTION_KIND_CONFIRM_SAVE,
            target_kind=TARGET_KIND_PENDING_ACTION, target_id="p-1",
        )
        ctx = _ctx_from_plan(plan)
        with self.assertRaises(vi.ExecutorError):
            adapters.adapter_confirm_save_login(ctx)
        self.assertEqual(
            ctx.outcome.result_code,
            adapters.RESULT_AUTHORIZATION_CONTEXT_INVALID,
        )

    def test_confirm_delete_rejects_wrong_action_kind(self):
        plan = _plan(
            action_kind=ACTION_KIND_CONFIRM_SAVE,
            target_kind=TARGET_KIND_PENDING_ACTION, target_id="p-1",
        )
        ctx = _ctx_from_plan(plan)
        with self.assertRaises(vi.ExecutorError):
            adapters.adapter_confirm_delete(ctx)
        self.assertEqual(
            ctx.outcome.result_code,
            adapters.RESULT_AUTHORIZATION_CONTEXT_INVALID,
        )

    def test_cancel_pending_rejects_wrong_target_kind(self):
        plan = _plan(
            action_kind=ACTION_KIND_CANCEL_PENDING,
            target_kind=TARGET_KIND_DRAFT, target_id="d-1",
        )
        ctx = _ctx_from_plan(plan)
        with self.assertRaises(vi.ExecutorError):
            adapters.adapter_cancel_pending(ctx)
        self.assertEqual(
            ctx.outcome.result_code,
            adapters.RESULT_AUTHORIZATION_CONTEXT_INVALID,
        )


# =====================================================================
# confirm_save (login) adapter
# =====================================================================

class ConfirmSaveLoginAdapterTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def _seed_v2_draft(self):
        now = time.time()
        d = new_draft(
            vault_id=VAULT, session_id=SESSION, draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Netflix", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=now,
                ),
                "username": DraftField(
                    value="alice@example.org",
                    source=SOURCE_USER_EXPLICIT, turn_id="t0", at=now,
                ),
                "password_ref": DraftField(
                    value="memory:pending_login_draft:password",
                    source=SOURCE_GENERATED, turn_id="t0", at=now,
                ),
            },
            origin_turn_id="t0", now=now,
        )
        store_draft(d)
        return d

    def _plan_confirm_save(self, target_id):
        return _plan(
            action_kind=ACTION_KIND_CONFIRM_SAVE,
            target_kind=TARGET_KIND_DRAFT, target_id=target_id,
        )

    def test_success_calls_save_secret_tool_exactly_once_and_clears_secret(self):
        d = self._seed_v2_draft()
        mem = _FakeSavedDict({
            "pending_login_draft": {
                "service": "Netflix",
                "username": "alice@example.org",
                "password": "REAL-PW-value",
                "ts": time.time(),
            },
        })
        called: list[tuple] = []

        def fake_save(vault_id, args, key, *, generated=False):
            called.append((vault_id, args, key, generated))
            # Simulate the real function returning a string reply.
            return "Saved your Netflix login."

        with mock.patch("main.save_secret_tool", new=fake_save):
            ctx = _ctx_from_plan(
                self._plan_confirm_save(d.draft_id),
                memory=mem,
            )
            adapters.adapter_confirm_save_login(ctx)

        self.assertEqual(len(called), 1)
        vid, args, key_arg, generated = called[0]
        self.assertEqual(vid, VAULT)
        self.assertEqual(args["service"], "Netflix")
        self.assertEqual(args["username"], "alice@example.org")
        self.assertEqual(args["password"], "REAL-PW-value")
        self.assertEqual(key_arg, KEY_32)
        self.assertTrue(generated)
        # Held secret cleared exactly once.
        self.assertEqual(mem.pop_calls, ["pending_login_draft"])
        # v2 draft is gone.
        self.assertIsNone(get_draft(VAULT, d.draft_id))
        # Outcome recorded and successful.
        self.assertTrue(ctx.outcome.success)
        self.assertEqual(ctx.outcome.result_code, adapters.RESULT_SUCCESS)

    def test_stale_target_prevents_save_call(self):
        # No v2 draft seeded -> target stale.
        mem = _FakeSavedDict({
            "pending_login_draft": {
                "service": "Netflix", "username": "alice@example.org",
                "password": "REAL-PW-value",
            },
        })
        called: list = []

        def fake_save(*a, **kw): called.append(1)

        with mock.patch("main.save_secret_tool", new=fake_save):
            ctx = _ctx_from_plan(
                self._plan_confirm_save("d-does-not-exist"),
                memory=mem,
            )
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_save_login(ctx)

        self.assertEqual(len(called), 0)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_TARGET_STALE)
        # Held secret NOT cleared on failure -- retryable.
        self.assertEqual(mem.pop_calls, [])

    def test_wrong_vault_prevents_save_call(self):
        d = self._seed_v2_draft()
        mem = _FakeSavedDict({
            "pending_login_draft": {
                "service": "Netflix", "username": "alice@example.org",
                "password": "REAL-PW-value",
            },
        })
        called: list = []

        def fake_save(*a, **kw): called.append(1)

        with mock.patch("main.save_secret_tool", new=fake_save):
            # Simulate wrong vault by constructing context with a
            # different vault_id; the TOC/TOU re-read will find
            # nothing.
            plan = self._plan_confirm_save(d.draft_id)
            ctx = adapters.ExecutorContextV2(
                vault_id="different-vault",  # WRONG
                session_id=SESSION, user_turn_id="u-1",
                target_kind=plan.target_kind,
                target_id=plan.target_id,
                validated_patch=plan.validated_patch,
                db_executor=None, key=KEY_32, memory=mem,
                plan=plan, snapshot=_snap(),
            )
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_save_login(ctx)
        self.assertEqual(len(called), 0)
        self.assertIn(
            ctx.outcome.result_code,
            {adapters.RESULT_TARGET_STALE,
             adapters.RESULT_AUTHORIZATION_CONTEXT_INVALID},
        )
        self.assertEqual(mem.pop_calls, [])

    def test_missing_held_secret_returns_not_found(self):
        d = self._seed_v2_draft()
        mem = _FakeSavedDict({})  # no pending_login_draft
        called: list = []

        def fake_save(*a, **kw): called.append(1)

        with mock.patch("main.save_secret_tool", new=fake_save):
            ctx = _ctx_from_plan(
                self._plan_confirm_save(d.draft_id),
                memory=mem,
            )
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_save_login(ctx)
        self.assertEqual(len(called), 0)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_NOT_FOUND)

    def test_bad_password_ref_shape_returns_validation_failed(self):
        # Seed a draft where password_ref is NOT the expected
        # phase-1 shape (adversarial input).
        now = time.time()
        d = new_draft(
            vault_id=VAULT, session_id=SESSION, draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Netflix", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=now,
                ),
                "username": DraftField(
                    value="alice", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=now,
                ),
                "password_ref": DraftField(
                    value="something:else:entirely",
                    source=SOURCE_GENERATED, turn_id="t0", at=now,
                ),
            },
            origin_turn_id="t0", now=now,
        )
        store_draft(d)
        called: list = []

        def fake_save(*a, **kw): called.append(1)

        with mock.patch("main.save_secret_tool", new=fake_save):
            ctx = _ctx_from_plan(
                self._plan_confirm_save(d.draft_id),
                memory=_FakeSavedDict({"pending_login_draft": {
                    "password": "x",
                }}),
            )
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_save_login(ctx)
        self.assertEqual(len(called), 0)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_VALIDATION_FAILED)

    def test_save_exception_preserves_held_secret_and_draft(self):
        d = self._seed_v2_draft()
        mem = _FakeSavedDict({
            "pending_login_draft": {
                "service": "Netflix", "username": "alice",
                "password": "PW",
            },
        })

        def fake_save(*a, **kw):
            raise RuntimeError("db down")

        with mock.patch("main.save_secret_tool", new=fake_save):
            ctx = _ctx_from_plan(
                self._plan_confirm_save(d.draft_id),
                memory=mem,
            )
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_save_login(ctx)

        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_EXECUTOR_EXCEPTION)
        # Held secret NOT popped -- retry still possible.
        self.assertEqual(mem.pop_calls, [])
        # v2 draft NOT consumed -- retry still possible.
        self.assertIsNotNone(get_draft(VAULT, d.draft_id))

    def test_raw_password_never_appears_in_telemetry(self):
        d = self._seed_v2_draft()
        pw = "S3CR3T_PW_MUST_NOT_APPEAR_IN_TELEMETRY"
        mem = _FakeSavedDict({
            "pending_login_draft": {
                "service": "Netflix", "username": "alice",
                "password": pw,
            },
        })

        def fake_save(vault_id, args, key, *, generated=False):
            return "Saved."

        with mock.patch("main.save_secret_tool", new=fake_save):
            ctx = _ctx_from_plan(
                self._plan_confirm_save(d.draft_id),
                memory=mem,
            )
            adapters.adapter_confirm_save_login(ctx)
        for k, v in ctx.outcome.telemetry_metadata.items():
            self.assertNotIn(pw, str(v))
            self.assertNotEqual(k, "password")

    def test_raw_password_never_written_back_into_draft(self):
        d = self._seed_v2_draft()
        pw = "another-secret-value"
        mem = _FakeSavedDict({
            "pending_login_draft": {
                "service": "Netflix", "username": "alice",
                "password": pw,
            },
        })

        def fake_save(vault_id, args, key, *, generated=False):
            # Even if the underlying save succeeded, the adapter
            # must not persist the raw password back into any
            # Draft record.
            return "Saved."

        with mock.patch("main.save_secret_tool", new=fake_save):
            ctx = _ctx_from_plan(
                self._plan_confirm_save(d.draft_id),
                memory=mem,
            )
            adapters.adapter_confirm_save_login(ctx)

        # v2 draft is consumed on success; check the state store
        # backend directly to confirm no fresh draft contains
        # the raw password.
        import vault_chat_state_store as st
        backend = st.get_chat_state_backend()
        # Scan every stored key for the password string.
        # (InMemoryChatStateBackend gives us direct access.)
        for k, v in getattr(backend, "_store", {}).items():
            if isinstance(v, (bytes, bytearray)):
                self.assertNotIn(
                    pw.encode(), v,
                    msg=f"raw password leaked into state key {k!r}",
                )


# =====================================================================
# confirm_delete adapter
# =====================================================================

class ConfirmDeleteAdapterTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def _plan(self, target_id="p-del-1"):
        return _plan(
            action_kind=ACTION_KIND_CONFIRM_DELETE,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=target_id,
        )

    def _seed_pending(self, action_id="p-del-1"):
        pa = PendingAction(
            kind=KIND_DELETE_SECURE_ITEM,
            action_id=action_id,
            source_kind=SOURCE_SECURE_DELETE_INTENT,
            target_label="Netflix login",
            created_at=time.time(),
            expires_at=time.time() + 600,
            vault_id=VAULT, session_id=None,
            is_destructive=True,
            metadata={"item_type": "login", "is_login": True,
                       "item_id": "i-1"},
        )
        return pa

    def test_success_calls_execute_pending_delete_with_db_executor(self):
        pa = self._seed_pending()
        called: list[dict] = []

        def fake_execute(*, vault_id, key, db_executor):
            called.append({
                "vault_id": vault_id, "key": key,
                "db_executor": db_executor,
            })
            return {"band": "deleted", "count": 1,
                    "title": "Netflix", "type": "login",
                    "is_login": True}

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ), mock.patch(
            "vault_secure_item_save._execute_pending_delete",
            new=fake_execute,
        ):
            sentinel_db_executor = object()
            ctx = _ctx_from_plan(
                self._plan(pa.action_id),
                db_executor=sentinel_db_executor,
            )
            adapters.adapter_confirm_delete(ctx)

        self.assertEqual(len(called), 1)
        self.assertEqual(called[0]["vault_id"], VAULT)
        self.assertEqual(called[0]["key"], KEY_32)
        # db_executor was threaded through (Bug C fix requirement).
        self.assertIs(called[0]["db_executor"], sentinel_db_executor)
        self.assertTrue(ctx.outcome.success)
        self.assertEqual(
            ctx.outcome.telemetry_metadata.get("underlying_band"),
            "deleted",
        )

    def test_stale_target_never_calls_execute_pending_delete(self):
        called: list = []

        def fake_execute(**kw): called.append(1)

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [],
        ), mock.patch(
            "vault_secure_item_save._execute_pending_delete",
            new=fake_execute,
        ):
            ctx = _ctx_from_plan(self._plan("p-gone"))
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_delete(ctx)
        self.assertEqual(len(called), 0)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_TARGET_STALE)

    def test_wrong_kind_pending_prevents_call(self):
        # Live pending action exists but is a save, not a delete.
        pa = PendingAction(
            kind=KIND_SAVE_LOGIN_DRAFT, action_id="p-not-a-delete",
            source_kind=SOURCE_MEMORY_LOGIN_DRAFT,
            target_label="Netflix login",
            created_at=time.time(), expires_at=time.time() + 60,
            vault_id=VAULT, session_id=None,
        )
        called: list = []

        def fake_execute(**kw): called.append(1)

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ), mock.patch(
            "vault_secure_item_save._execute_pending_delete",
            new=fake_execute,
        ):
            ctx = _ctx_from_plan(self._plan(pa.action_id))
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_delete(ctx)
        self.assertEqual(len(called), 0)

    def test_bad_key_returns_dependency_unavailable(self):
        pa = self._seed_pending()

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ):
            ctx = _ctx_from_plan(self._plan(pa.action_id), key=b"tooshort")
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_delete(ctx)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_DEPENDENCY_UNAVAILABLE)

    def test_underlying_band_no_pending_maps_to_stale(self):
        pa = self._seed_pending()

        def fake_execute(**kw):
            return {"band": "no_pending_delete", "message": ""}

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ), mock.patch(
            "vault_secure_item_save._execute_pending_delete",
            new=fake_execute,
        ):
            ctx = _ctx_from_plan(self._plan(pa.action_id))
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_delete(ctx)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_TARGET_STALE)

    def test_underlying_band_db_error_maps_to_dependency_unavailable(self):
        pa = self._seed_pending()

        def fake_execute(**kw):
            return {"band": "db_error", "message": "oops"}

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ), mock.patch(
            "vault_secure_item_save._execute_pending_delete",
            new=fake_execute,
        ):
            ctx = _ctx_from_plan(self._plan(pa.action_id))
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_delete(ctx)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_DEPENDENCY_UNAVAILABLE)

    def test_unknown_band_maps_to_executor_exception_not_swallowed(self):
        # An unknown band from the underlying primitive must NOT
        # be treated as success. This is the "no swallowing"
        # requirement.
        pa = self._seed_pending()

        def fake_execute(**kw):
            return {"band": "some_new_band_we_do_not_know", "message": ""}

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ), mock.patch(
            "vault_secure_item_save._execute_pending_delete",
            new=fake_execute,
        ):
            ctx = _ctx_from_plan(self._plan(pa.action_id))
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_delete(ctx)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_EXECUTOR_EXCEPTION)


# =====================================================================
# confirm_save_attachment adapter
# =====================================================================

class ConfirmSaveAttachmentAdapterTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def _pending(self, upload_id="u-1"):
        return PendingAction(
            kind=KIND_SAVE_ATTACHMENT, action_id=upload_id,
            source_kind=SOURCE_UPLOADED_FILE,
            target_label="video: xxx.webm",
            created_at=time.time(), expires_at=time.time() + 300,
            vault_id=VAULT, session_id=SESSION,
            is_destructive=False,
            metadata={"uploaded_file_id": upload_id,
                       "content_type": "video/webm",
                       "filename": "xxx.webm"},
        )

    def _plan(self, upload_id="u-1", name="My Kayak Video"):
        patch = MappingProxyType({
            "name": FieldPatchItem(op="replace", value=name),
        })
        return _plan(
            action_kind=ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=upload_id, validated_patch=patch,
        )

    def test_success_calls_save_named_uploaded_asset(self):
        pa = self._pending()
        called: list = []

        def fake_save(vault_id, file_id, saved_name, key=None):
            called.append((vault_id, file_id, saved_name, key))
            return {"saved_name": saved_name,
                    "asset_type": "video", "file_name": "xxx.webm"}

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ), mock.patch("main.save_named_uploaded_asset", new=fake_save), \
                mock.patch("vault_chat_upload_binding.clear_binding",
                             new=lambda **kw: True):
            ctx = _ctx_from_plan(self._plan(pa.action_id))
            adapters.adapter_confirm_save_attachment(ctx)

        self.assertEqual(len(called), 1)
        self.assertEqual(called[0][0], VAULT)
        self.assertEqual(called[0][1], pa.action_id)
        self.assertEqual(called[0][2], "My Kayak Video")
        self.assertTrue(ctx.outcome.success)

    def test_stale_target_never_calls_save(self):
        called: list = []

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [],  # no live pending
        ), mock.patch("main.save_named_uploaded_asset",
                       new=lambda *a, **kw: called.append(1)):
            ctx = _ctx_from_plan(self._plan("u-gone"))
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_save_attachment(ctx)
        self.assertEqual(len(called), 0)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_TARGET_STALE)

    def test_missing_name_patch_returns_validation_failed(self):
        pa = self._pending()
        called: list = []

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ), mock.patch("main.save_named_uploaded_asset",
                       new=lambda *a, **kw: called.append(1)):
            plan = _plan(
                action_kind=ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id=pa.action_id, validated_patch=None,
            )
            ctx = _ctx_from_plan(plan)
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_confirm_save_attachment(ctx)
        self.assertEqual(len(called), 0)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_VALIDATION_FAILED)


# =====================================================================
# cancel_pending adapter (per source_kind dispatch)
# =====================================================================

class CancelPendingAdapterTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def _plan(self, target_id="p-1"):
        return _plan(
            action_kind=ACTION_KIND_CANCEL_PENDING,
            target_kind=TARGET_KIND_PENDING_ACTION, target_id=target_id,
        )

    def test_absent_pending_is_already_cancelled_not_success(self):
        # 6a-1: idempotent no-op reports ALREADY_CANCELLED, not
        # SUCCESS. The outcome.success flag is still True (nothing
        # for the user to retry), but the result_code distinguishes
        # rollout-quality signal.
        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [],
        ):
            ctx = _ctx_from_plan(self._plan("p-gone"))
            adapters.adapter_cancel_pending(ctx)
        self.assertTrue(ctx.outcome.success)
        self.assertEqual(
            ctx.outcome.result_code, adapters.RESULT_ALREADY_CANCELLED,
        )
        self.assertNotEqual(
            ctx.outcome.result_code, adapters.RESULT_SUCCESS,
        )
        self.assertEqual(
            ctx.outcome.telemetry_metadata.get("cancel_kind"),
            "already_gone",
        )

    def test_secure_delete_dispatches_to_cancel_pending_delete(self):
        pa = PendingAction(
            kind=KIND_DELETE_SECURE_ITEM, action_id="p-del",
            source_kind=SOURCE_SECURE_DELETE_INTENT,
            target_label="x", created_at=time.time(),
            expires_at=time.time() + 60, vault_id=VAULT,
        )
        called: list = []

        def fake(*, vault_id):
            called.append(vault_id)
            return {"band": "delete_cancelled", "message": ""}

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ), mock.patch(
            "vault_secure_item_save._cancel_pending_delete", new=fake,
        ):
            ctx = _ctx_from_plan(self._plan("p-del"))
            adapters.adapter_cancel_pending(ctx)
        self.assertEqual(called, [VAULT])
        self.assertTrue(ctx.outcome.success)
        self.assertEqual(
            ctx.outcome.telemetry_metadata.get("source_kind"),
            SOURCE_SECURE_DELETE_INTENT,
        )

    def test_memory_login_draft_dispatches_to_memory_pop(self):
        pa = PendingAction(
            kind=KIND_SAVE_LOGIN_DRAFT, action_id="memlogin:netflix",
            source_kind=SOURCE_MEMORY_LOGIN_DRAFT,
            target_label="Netflix login", created_at=time.time(),
            expires_at=time.time() + 60, vault_id=VAULT,
        )
        mem = _FakeSavedDict({
            "pending_login_draft": {"service": "Netflix"},
        })

        with mock.patch(
            "vault_chat_executor_adapters_v2.read_all_pending",
            new=lambda **kw: [pa],
        ):
            ctx = _ctx_from_plan(self._plan("memlogin:netflix"),
                                  memory=mem)
            adapters.adapter_cancel_pending(ctx)
        self.assertEqual(mem.pop_calls, ["pending_login_draft"])
        self.assertTrue(ctx.outcome.success)

    def test_wrong_vault_pending_refused(self):
        pa = PendingAction(
            kind=KIND_DELETE_SECURE_ITEM, action_id="p-del",
            source_kind=SOURCE_SECURE_DELETE_INTENT,
            target_label="x", created_at=time.time(),
            expires_at=time.time() + 60,
            vault_id="different-vault",
        )
        # Even if _find_pending_by_id happens to return it (bad
        # search implementation), our adapter's own vault check
        # rejects. read_all_pending won't return it because it's
        # scoped to VAULT, so we actually get TARGET_STALE via the
        # empty-live path (idempotent success). To exercise the
        # wrong-vault branch we bypass the search:
        with mock.patch(
            "vault_chat_executor_adapters_v2._find_pending_by_id",
            new=lambda ctx, tid: pa,
        ):
            ctx = _ctx_from_plan(self._plan("p-del"))
            with self.assertRaises(vi.ExecutorError):
                adapters.adapter_cancel_pending(ctx)
        self.assertEqual(ctx.outcome.result_code,
                          adapters.RESULT_AUTHORIZATION_CONTEXT_INVALID)


# =====================================================================
# Adapter contract: no reply text
# =====================================================================

class NoReplyTextTest(unittest.TestCase):

    def test_outcome_has_no_reply_text_field(self):
        # ExecutorOutcomeV2 has no reply_text field at all -- reply
        # rendering is the router/integration boundary's job.
        o = adapters.ExecutorOutcomeV2(
            success=True, result_code=adapters.RESULT_SUCCESS,
        )
        for attr in ("reply_text", "message", "user_message", "text"):
            self.assertFalse(
                hasattr(o, attr),
                msg=f"ExecutorOutcomeV2 must not expose {attr!r}",
            )


# =====================================================================
# Integration ordering: mint -> consume -> adapter -> focus -> reply
# =====================================================================

class IntegrationOrderingTest(unittest.TestCase):
    """apply_router_result_v2 must invoke the adapter EXACTLY ONCE
    and only AFTER successful mint + consume. Focus and reply key
    are applied AFTER the adapter returns."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def _plan_with_auth(self, target_id):
        return ExecutionPlanV2(
            action_kind=ACTION_KIND_CANCEL_PENDING,
            target_kind=TARGET_KIND_PENDING_ACTION,
            target_id=target_id,
            authorization_intent=AuthorizationIntent(
                target_kind=TARGET_KIND_PENDING_ACTION,
                target_id=target_id,
                action=ACTION_SAVE,  # any known action
                authorizing_user_turn_id="u-1",
                preceding_assistant_turn_id="a-0",
                confidence=0.99,
            ),
            validated_patch=None,
            success_focus_update=FocusUpdate(
                action=FOCUS_ACTION_SET,
                kind=FOCUS_KIND_DRAFT, id="d-success",
                assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            ),
            failure_focus_update=PRESERVE_FOCUS,
            success_reply_key="cancel_pending",
            failure_reply_key="cancel_pending",
        )

    def _rr(self, plan):
        return RouterResultV2(
            handled=True,
            reply_kind=REPLY_KIND_EXECUTION_REQUIRED,
            reply_text="",
            focus_update=PRESERVE_FOCUS,
            execution_plan=plan,
            next_state=NEXT_STATE_EXECUTE,
            normalized_intent="cancel_pending_action",
            reason_code=REASON_ALLOWED,
        )

    def test_adapter_runs_once_after_successful_consume(self):
        adapter_calls: list = []

        def fake_adapter(**kw):
            adapter_calls.append(kw)

        registry = vi.ExecutorRegistry(cancel_pending=fake_adapter)
        plan = self._plan_with_auth("p-1")
        result = vi.apply_router_result_v2(
            router_result=self._rr(plan),
            snapshot=_snap(),
            executor_registry=registry,
        )
        self.assertEqual(len(adapter_calls), 1)
        self.assertEqual(result.execution_status, vi.STATUS_SUCCESS)

    def test_adapter_never_runs_when_mint_fails(self):
        import vault_chat_state_store as st

        class TrapSet(st.SharedStateBackend):
            def get(self, key): return None
            def set(self, key, value, ttl_seconds):
                raise RuntimeError("mint down")
            def delete(self, key): pass
            def sadd(self, key, member, ttl_seconds): pass
            def smembers(self, key): return set()
            def srem(self, key, member): pass
            def sclear(self, key): pass
            def health(self): return True

        st.install_backend_for_tests(TrapSet())
        try:
            adapter_calls: list = []

            def fake_adapter(**kw):
                adapter_calls.append(kw)

            registry = vi.ExecutorRegistry(cancel_pending=fake_adapter)
            plan = self._plan_with_auth("p-1")
            result = vi.apply_router_result_v2(
                router_result=self._rr(plan),
                snapshot=_snap(),
                executor_registry=registry,
            )
            self.assertEqual(len(adapter_calls), 0)
            self.assertEqual(
                result.execution_status, vi.STATUS_AUTHORIZATION_FAILED,
            )
        finally:
            st.reset_chat_state_backend_for_tests()

    def test_adapter_never_runs_when_consume_fails(self):
        # Wrap mint to atomically pre-consume, so the integration's
        # own consume returns not_found.
        import vault_chat_authorization_record as vauth

        original_mint = vauth.mint_authorization

        def racy_mint(**kwargs):
            rec = original_mint(**kwargs)
            vauth.atomic_consume_authorization(
                auth_id=rec.auth_id,
                expected_vault_id=rec.vault_id,
                expected_session_id=rec.session_id,
                expected_target_kind=rec.target_kind,
                expected_target_id=rec.target_id,
                expected_action=rec.action,
                expected_authorizing_user_turn_id=(
                    rec.authorizing_user_turn_id
                ),
            )
            return rec

        vi.mint_authorization = racy_mint  # type: ignore[assignment]
        try:
            adapter_calls: list = []

            def fake_adapter(**kw):
                adapter_calls.append(kw)

            registry = vi.ExecutorRegistry(cancel_pending=fake_adapter)
            plan = self._plan_with_auth("p-1")
            result = vi.apply_router_result_v2(
                router_result=self._rr(plan),
                snapshot=_snap(),
                executor_registry=registry,
            )
            self.assertEqual(len(adapter_calls), 0)
            self.assertEqual(
                result.execution_status, vi.STATUS_CONSUME_FAILED,
            )
        finally:
            vi.mint_authorization = original_mint  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main()
