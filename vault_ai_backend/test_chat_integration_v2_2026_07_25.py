"""Tests for the integration layer (IntegrationResultV2 + ExecutorRegistry
+ apply_router_result_v2).

Covers the four required IntegrationResult statuses:
    * SUCCESS
    * EXECUTOR_FAILED
    * AUTHORIZATION_FAILED
    * CONSUME_FAILED
plus INTERNAL_ERROR and NO_EXECUTION.

Uses injected fake executors — no real save/delete happens. Uses
InMemoryChatStateBackend so real auth-record mint + CAS-consume
run against an isolated in-memory store.
"""

from __future__ import annotations

import unittest
from types import MappingProxyType
from typing import Any, Optional

import vault_chat_integration_v2 as vi
from vault_chat_authorization_record import atomic_consume_authorization
from vault_chat_decision_router_v2 import (
    ACTION_KIND_APPLY_CREATE,
    ACTION_KIND_APPLY_EDIT,
    ACTION_KIND_CANCEL_DRAFT,
    ACTION_KIND_CONFIRM_SAVE,
    ExecutionPlanV2,
    FOCUS_ACTION_CLEAR,
    FOCUS_ACTION_CLEAR_IF_MATCHES,
    FOCUS_ACTION_PRESERVE,
    FOCUS_ACTION_SET,
    FOCUS_ACTION_SET_ON_CREATE,
    FocusUpdate,
    NEXT_STATE_APPLY_CANCEL,
    NEXT_STATE_APPLY_CREATE,
    NEXT_STATE_APPLY_PATCH,
    NEXT_STATE_EXECUTE,
    PRESERVE_FOCUS,
    REPLY_KIND_EXECUTION_REQUIRED,
    RouterResultV2,
)
from vault_chat_focus import (
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
    FOCUS_KIND_DRAFT,
    read_focus,
    stamp_focus,
)
from vault_chat_policy_v2 import (
    AuthorizationIntent,
    PolicySnapshotV2,
    REASON_ALLOWED,
)
from vault_chat_semantic_decision_v2 import (
    ACTION_SAVE,
    TARGET_KIND_DRAFT,
)
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


VAULT = "vault-int-test"
SESSION = "sess-int-test"


# =====================================================================
# Helpers
# =====================================================================

def _snap(now: float = 1.0) -> PolicySnapshotV2:
    return PolicySnapshotV2(
        vault_id=VAULT, session_id=SESSION,
        current_user_turn_id="u-1",
        preceding_assistant_turn_id="a-0",
        now=now,
    )


def _auth_intent(target_id="d-1") -> AuthorizationIntent:
    return AuthorizationIntent(
        target_kind=TARGET_KIND_DRAFT, target_id=target_id,
        action=ACTION_SAVE,
        authorizing_user_turn_id="u-1",
        preceding_assistant_turn_id="a-0",
        confidence=0.9,
    )


def _plan_confirm_save(target_id="d-1",
                        with_auth=True) -> ExecutionPlanV2:
    return ExecutionPlanV2(
        action_kind=ACTION_KIND_CONFIRM_SAVE,
        target_kind=TARGET_KIND_DRAFT, target_id=target_id,
        authorization_intent=_auth_intent(target_id) if with_auth else None,
        validated_patch=None,
        success_focus_update=FocusUpdate(
            action=FOCUS_ACTION_CLEAR_IF_MATCHES,
            kind=FOCUS_KIND_DRAFT, id=target_id,
        ),
        failure_focus_update=FocusUpdate(
            action=FOCUS_ACTION_SET,
            kind=FOCUS_KIND_DRAFT, id=target_id,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        ),
        success_reply_key="save_draft",
        failure_reply_key="save_draft",
    )


def _plan_apply_edit(target_id="d-1") -> ExecutionPlanV2:
    return ExecutionPlanV2(
        action_kind=ACTION_KIND_APPLY_EDIT,
        target_kind=TARGET_KIND_DRAFT, target_id=target_id,
        authorization_intent=None, validated_patch=None,
        success_focus_update=FocusUpdate(
            action=FOCUS_ACTION_SET,
            kind=FOCUS_KIND_DRAFT, id=target_id,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        ),
        failure_focus_update=PRESERVE_FOCUS,
        success_reply_key="apply_edit", failure_reply_key="apply_edit",
    )


def _router_execution_required(plan: ExecutionPlanV2,
                                next_state: str = NEXT_STATE_EXECUTE) -> RouterResultV2:
    return RouterResultV2(
        handled=True,
        reply_kind=REPLY_KIND_EXECUTION_REQUIRED,
        reply_text="",
        focus_update=PRESERVE_FOCUS,
        execution_plan=plan,
        next_state=next_state,
        normalized_intent="confirm_draft",
        reason_code=REASON_ALLOWED,
    )


class _ExecutorCallCounter:
    def __init__(self, *, raises: Optional[BaseException] = None):
        self.calls: list[dict] = []
        self._raises = raises

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises


# =====================================================================
# NO_EXECUTION path (router with no execution_plan)
# =====================================================================

class NoExecutionPathTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_router_with_no_plan_returns_no_execution(self):
        rr = RouterResultV2(
            handled=True,
            reply_kind="clarification",
            reply_text="clarify?",
            focus_update=PRESERVE_FOCUS,
            execution_plan=None,
            next_state="await_user",
            normalized_intent="confirm_draft",
            reason_code=REASON_ALLOWED,
        )
        result = vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=vi.ExecutorRegistry(),
        )
        self.assertEqual(result.execution_status, vi.STATUS_NO_EXECUTION)
        self.assertIsNone(result.executed_action_kind)
        self.assertIsNone(result.reply_key)


# =====================================================================
# SUCCESS path
# =====================================================================

class SuccessPathTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_confirm_save_success(self):
        counter = _ExecutorCallCounter()
        registry = vi.ExecutorRegistry(confirm_save=counter)
        rr = _router_execution_required(_plan_confirm_save())
        result = vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=registry,
        )
        self.assertEqual(result.execution_status, vi.STATUS_SUCCESS)
        self.assertEqual(
            result.executed_action_kind, ACTION_KIND_CONFIRM_SAVE,
        )
        self.assertEqual(result.reply_key, "save_draft")
        self.assertEqual(len(counter.calls), 1)

    def test_apply_edit_success_no_auth(self):
        counter = _ExecutorCallCounter()
        registry = vi.ExecutorRegistry(apply_edit=counter)
        rr = _router_execution_required(
            _plan_apply_edit(), next_state=NEXT_STATE_APPLY_PATCH,
        )
        result = vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=registry,
        )
        self.assertEqual(result.execution_status, vi.STATUS_SUCCESS)
        self.assertEqual(
            result.executed_action_kind, ACTION_KIND_APPLY_EDIT,
        )


# =====================================================================
# EXECUTOR_FAILED path
# =====================================================================

class ExecutorFailedPathTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_executor_error_returns_executor_failed(self):
        counter = _ExecutorCallCounter(
            raises=vi.ExecutorError("save vault backend down"),
        )
        registry = vi.ExecutorRegistry(confirm_save=counter)
        rr = _router_execution_required(_plan_confirm_save())
        result = vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=registry,
        )
        self.assertEqual(result.execution_status, vi.STATUS_EXECUTOR_FAILED)
        self.assertEqual(result.reply_key, "save_draft")
        self.assertTrue(result.telemetry_reason.startswith("executor:"))

    def test_uncontrolled_exception_returns_executor_failed(self):
        counter = _ExecutorCallCounter(raises=RuntimeError("db oops"))
        registry = vi.ExecutorRegistry(confirm_save=counter)
        rr = _router_execution_required(_plan_confirm_save())
        result = vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=registry,
        )
        self.assertEqual(result.execution_status, vi.STATUS_EXECUTOR_FAILED)
        self.assertIn("executor_exception", result.telemetry_reason)


# =====================================================================
# AUTHORIZATION_FAILED path
# =====================================================================

class AuthorizationFailedPathTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_mint_failure_returns_authorization_failed(self):
        # Force mint failure by patching the backend to raise on set.
        import vault_chat_state_store as st

        class TrapSet(st.SharedStateBackend):
            def get(self, key): return None
            def set(self, key, value, ttl_seconds):
                raise RuntimeError("mint backend down")
            def delete(self, key): pass
            def sadd(self, key, member, ttl_seconds): pass
            def smembers(self, key): return set()
            def srem(self, key, member): pass
            def sclear(self, key): pass
            def health(self): return True

        st.install_backend_for_tests(TrapSet())
        try:
            counter = _ExecutorCallCounter()
            registry = vi.ExecutorRegistry(confirm_save=counter)
            rr = _router_execution_required(_plan_confirm_save())
            result = vi.apply_router_result_v2(
                router_result=rr, snapshot=_snap(),
                executor_registry=registry,
            )
            self.assertEqual(
                result.execution_status, vi.STATUS_AUTHORIZATION_FAILED,
            )
            # Executor MUST NOT have been called.
            self.assertEqual(len(counter.calls), 0)
        finally:
            st.reset_chat_state_backend_for_tests()


# =====================================================================
# CONSUME_FAILED path
# =====================================================================

class ConsumeFailedPathTest(unittest.TestCase):
    """The record is minted; then a *concurrent* consumer wipes it
    before our own CAS-consume runs. Second consume gets not_found
    → CONSUME_FAILED and executor is never called."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_consume_failure_when_record_already_consumed(self):
        # Wrap mint_authorization so we can steal + consume the
        # record between mint and consume.
        import vault_chat_integration_v2 as vi_mod
        import vault_chat_authorization_record as vauth

        original_mint = vauth.mint_authorization

        def racy_mint(**kwargs):
            rec = original_mint(**kwargs)
            # Race: consume it before the integration's consume.
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

        vi_mod.mint_authorization = racy_mint  # type: ignore[assignment]
        try:
            counter = _ExecutorCallCounter()
            registry = vi.ExecutorRegistry(confirm_save=counter)
            rr = _router_execution_required(_plan_confirm_save())
            result = vi.apply_router_result_v2(
                router_result=rr, snapshot=_snap(),
                executor_registry=registry,
            )
            self.assertEqual(
                result.execution_status, vi.STATUS_CONSUME_FAILED,
            )
            self.assertEqual(len(counter.calls), 0)
        finally:
            vi_mod.mint_authorization = original_mint  # type: ignore[assignment]


# =====================================================================
# INTERNAL_ERROR path (no executor mapped)
# =====================================================================

class InternalErrorPathTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_no_executor_for_action_kind_returns_internal_error(self):
        # Plan has no auth so mint/consume are skipped; go straight
        # to executor dispatch which finds no callable.
        plan = ExecutionPlanV2(
            action_kind=ACTION_KIND_CANCEL_DRAFT,
            target_kind=TARGET_KIND_DRAFT, target_id="d-1",
            authorization_intent=None, validated_patch=None,
            success_focus_update=PRESERVE_FOCUS,
            failure_focus_update=PRESERVE_FOCUS,
            success_reply_key="cancel_draft",
            failure_reply_key="cancel_draft",
        )
        rr = _router_execution_required(plan, next_state=NEXT_STATE_APPLY_CANCEL)
        result = vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=vi.ExecutorRegistry(),  # empty
        )
        self.assertEqual(result.execution_status, vi.STATUS_INTERNAL_ERROR)
        self.assertTrue(result.telemetry_reason.startswith("no_executor:"))


# =====================================================================
# Focus persistence side effects
# =====================================================================

class FocusPersistenceTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_success_applies_success_focus_update(self):
        # Pre-stamp focus that clear_if_matches should clear.
        stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a-0",
        )
        counter = _ExecutorCallCounter()
        registry = vi.ExecutorRegistry(confirm_save=counter)
        rr = _router_execution_required(_plan_confirm_save())
        vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=registry,
            assistant_turn_id="a-1",
        )
        self.assertIsNone(
            read_focus(vault_id=VAULT, session_id=SESSION),
            msg="success_focus_update should have cleared matching focus",
        )

    def test_failure_applies_failure_focus_update(self):
        counter = _ExecutorCallCounter(
            raises=vi.ExecutorError("save failed"),
        )
        registry = vi.ExecutorRegistry(confirm_save=counter)
        rr = _router_execution_required(_plan_confirm_save())
        vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=registry,
            assistant_turn_id="a-1",
        )
        # failure_focus_update is SET(draft, d-1, presented_for_confirmation)
        # — restoring the presented focus so the user can retry.
        focus = read_focus(vault_id=VAULT, session_id=SESSION)
        self.assertIsNotNone(focus)
        self.assertEqual(focus.id, "d-1")
        self.assertEqual(
            focus.assistant_act, FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
        )

    def test_set_on_create_uses_created_target_id_override(self):
        plan = ExecutionPlanV2(
            action_kind=ACTION_KIND_APPLY_CREATE,
            target_kind=TARGET_KIND_DRAFT, target_id=None,
            authorization_intent=None, validated_patch=None,
            success_focus_update=FocusUpdate(
                action=FOCUS_ACTION_SET_ON_CREATE,
                kind=FOCUS_KIND_DRAFT,
                assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            ),
            failure_focus_update=PRESERVE_FOCUS,
            success_reply_key="apply_create",
            failure_reply_key="apply_create",
        )
        rr = _router_execution_required(plan,
                                         next_state=NEXT_STATE_APPLY_CREATE)
        counter = _ExecutorCallCounter()
        registry = vi.ExecutorRegistry(apply_create=counter)
        vi.apply_router_result_v2(
            router_result=rr, snapshot=_snap(),
            executor_registry=registry,
            assistant_turn_id="a-1",
            created_target_id="d-FRESH",
        )
        focus = read_focus(vault_id=VAULT, session_id=SESSION)
        self.assertIsNotNone(focus)
        self.assertEqual(focus.id, "d-FRESH")


class IntegrationResultShapeTest(unittest.TestCase):

    def test_unknown_status_rejected(self):
        with self.assertRaises(ValueError):
            vi.IntegrationResultV2(execution_status="MYSTERY")


if __name__ == "__main__":
    unittest.main()
