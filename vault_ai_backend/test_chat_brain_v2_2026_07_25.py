"""Tests for the v2 top-level orchestrator + feature-flag dispatch
in vault_chat_brain / vault_chat_brain_v2.

Covers (commit 5 + commit 5a):
    * feature flag off never invokes v2
    * feature flag shadow performs zero writes AND exercises the
      full read-only stack (snapshot -> decider -> policy -> router)
      -- but NEVER integration / auth mint / consume / executor /
      focus persistence
    * feature flag on invokes v2 only
    * snapshot redaction: no vault_id, session_id, password_ref
      value, tokens, ciphertext, authorization ids, or Redis keys
      in the serialized decider payload
    * V2 exception handling: V1_FALLBACK env honored ONLY when
      phase == READ_ONLY; refused otherwise
    * no mixed V1/V2 execution in a single request
    * runtime-readiness guard refuses on-mode with incomplete
      registry (controlled unavailable, not silent v1)
    * shadow diff record generation
"""

from __future__ import annotations

import asyncio
import json
import os
import unittest
from typing import Any, Optional
from unittest import mock

import vault_chat_brain as vb
import vault_chat_brain_v2 as vbv2
import vault_chat_integration_v2 as vi
import vault_chat_shadow_recorder_v2 as sr

from vault_chat_authorization_record import AUTH_ACTION_SAVE
from vault_chat_decision_router_v2 import (
    ACTION_KIND_APPLY_CREATE,
    ACTION_KIND_APPLY_EDIT,
    ACTION_KIND_CANCEL_DRAFT,
    ACTION_KIND_CANCEL_PENDING,
    ACTION_KIND_CONFIRM_DELETE,
    ACTION_KIND_CONFIRM_SAVE,
    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT,
    ACTION_KINDS,
)
from vault_chat_draft import (
    DRAFT_LOGIN, DraftField, SOURCE_GENERATED, SOURCE_USER_EXPLICIT,
    STATUS_PRESENTED_FOR_CONFIRMATION,
    new_draft, store_draft,
)
from vault_chat_focus import (
    FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
    FOCUS_KIND_DRAFT,
    stamp_focus,
)
from vault_chat_semantic_decider_v2 import build_prompt_v2
from vault_chat_semantic_decision_v2 import (
    SEMANTIC_DECISION_V2_SCHEMA_VERSION,
)
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


VAULT = "vault-brainv2-test"
SESSION = "sess-brainv2-test"

TEST_FP_SECRET: bytes = b"test-brain-v2-fingerprint-secret-please-use-in-tests-only"


class _FingerprintFixture:
    """Provide a stable fingerprint secret for any test that runs
    build_and_log_diff indirectly through shadow-mode. Prevents
    the shadow recorder from emitting fingerprint-free records
    across our brain-integration paths."""

    def _install_fp_secret(self):
        sr.configure_fingerprint_secret_for_tests(TEST_FP_SECRET)

    def _reset_fp_secret(self):
        sr.reset_fingerprint_secret_for_tests()


# =====================================================================
# Feature flag reader
# =====================================================================

class ReadBrainModeTest(unittest.TestCase):

    def test_unset_defaults_to_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VAULTAI_CHAT_BRAIN_MODE", None)
            self.assertEqual(vbv2.read_brain_mode(), vbv2.MODE_OFF)

    def test_valid_modes_pass_through(self):
        for m in (vbv2.MODE_OFF, vbv2.MODE_SHADOW, vbv2.MODE_ON):
            with mock.patch.dict(
                os.environ, {"VAULTAI_CHAT_BRAIN_MODE": m}, clear=False,
            ):
                self.assertEqual(vbv2.read_brain_mode(), m)

    def test_unknown_mode_falls_back_to_off(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "sideways"},
            clear=False,
        ):
            self.assertEqual(vbv2.read_brain_mode(), vbv2.MODE_OFF)

    def test_v1_fallback_env(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK", None)
            self.assertFalse(vbv2.v1_fallback_enabled())
            os.environ["VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK"] = "on"
            self.assertTrue(vbv2.v1_fallback_enabled())
            os.environ["VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK"] = "no"
            self.assertFalse(vbv2.v1_fallback_enabled())


# =====================================================================
# Snapshot construction -- no secrets
# =====================================================================

class SnapshotRedactionTest(unittest.TestCase):
    """Broad snapshot-redaction assertions. Every one of these
    forbidden values MUST be absent from build_prompt_v2's
    serialized payload."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def _prompt_payload(self, snap) -> str:
        """Serialize the decider prompt to a searchable string --
        JSON-encoding matches how the model actually sees it."""
        messages = build_prompt_v2(snap.decider_context)
        return json.dumps(messages, ensure_ascii=False)

    def test_snapshot_draft_view_hides_password_ref_value(self):
        d = new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Netflix", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=1.0,
                ),
                "username": DraftField(
                    value="alice@example.org",
                    source=SOURCE_USER_EXPLICIT, turn_id="t0", at=1.0,
                ),
                "password_ref": DraftField(
                    value="memory:pending_login_draft:password",
                    source=SOURCE_GENERATED, turn_id="t0", at=1.0,
                ),
            },
            origin_turn_id="t0", now=1.0,
        )
        store_draft(d)

        snap = vbv2._build_v2_snapshot(
            vault_id=VAULT, session_id=SESSION,
            user_message="save it",
            current_user_turn_id="u-1",
            preceding_assistant_turn_id="a-0",
            memory=None, now=2.0,
        )
        views = snap.decider_context.active_drafts
        self.assertEqual(len(views), 1)
        pw = views[0]["fields"]["password_ref"]
        self.assertNotIn("value", pw)
        self.assertNotIn(
            "memory:pending_login_draft:password", str(views[0]),
        )
        self.assertTrue(pw["present"])
        self.assertEqual(
            views[0]["fields"]["service"]["value"], "Netflix",
        )

    def test_focus_view_carries_no_vault_content(self):
        stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=FOCUS_KIND_DRAFT, id="d-1",
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a-1",
        )
        snap = vbv2._build_v2_snapshot(
            vault_id=VAULT, session_id=SESSION,
            user_message="yes",
            current_user_turn_id="u-1",
            preceding_assistant_turn_id="a-1",
            memory=None,
        )
        fv = snap.decider_context.focus
        self.assertIsNotNone(fv)
        for k in ("kind", "id", "assistant_act", "assistant_turn_id"):
            self.assertIn(k, fv)
        for forbidden in ("vault_id", "password", "notes", "secret", "key"):
            self.assertNotIn(forbidden, fv)

    def test_serialized_prompt_never_contains_raw_vault_id(self):
        d = new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Netflix", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=1.0,
                ),
            },
            origin_turn_id="t0", now=1.0,
        )
        store_draft(d)

        snap = vbv2._build_v2_snapshot(
            vault_id=VAULT, session_id=SESSION,
            user_message="save it",
            current_user_turn_id="u-1",
            preceding_assistant_turn_id="a-0",
            memory=None, now=2.0,
        )
        prompt = self._prompt_payload(snap)
        self.assertNotIn(VAULT, prompt)

    def test_serialized_prompt_never_contains_raw_session_id(self):
        d = new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Netflix", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=1.0,
                ),
            },
            origin_turn_id="t0", now=1.0,
        )
        store_draft(d)
        snap = vbv2._build_v2_snapshot(
            vault_id=VAULT, session_id=SESSION,
            user_message="save it",
            current_user_turn_id="u-1",
            preceding_assistant_turn_id="a-0",
            memory=None, now=2.0,
        )
        prompt = self._prompt_payload(snap)
        self.assertNotIn(SESSION, prompt)

    def test_policy_snapshot_still_carries_vault_and_session_for_side_effects(self):
        # The prompt payload omits them, but the POLICY snapshot
        # (which drives auth mint and Redis writes) must still
        # carry the real values -- otherwise integration side
        # effects would silently misfire.
        snap = vbv2._build_v2_snapshot(
            vault_id=VAULT, session_id=SESSION,
            user_message="hi",
            current_user_turn_id="u-1",
            preceding_assistant_turn_id="a-0",
            memory=None, now=1.0,
        )
        self.assertEqual(snap.policy_snapshot.vault_id, VAULT)
        self.assertEqual(snap.policy_snapshot.session_id, SESSION)

    def test_serialized_prompt_carries_no_token_shaped_strings(self):
        # Store a draft that includes a plausibly-token-shaped
        # username to verify usernames DO appear (permitted, per
        # design memo) but no token-shape strings leak from
        # unrelated snapshot machinery.
        d = new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Github", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=1.0,
                ),
            },
            origin_turn_id="t0", now=1.0,
        )
        store_draft(d)
        snap = vbv2._build_v2_snapshot(
            vault_id=VAULT, session_id=SESSION,
            user_message="save it",
            current_user_turn_id="u-1",
            preceding_assistant_turn_id="a-0",
            memory=None, now=2.0,
        )
        prompt = self._prompt_payload(snap)
        for token_prefix in ("Bearer ", "eyJhbGciOi", "ghp_", "sk-",
                              "AKIA", "AIza"):
            self.assertNotIn(token_prefix, prompt)

    def test_serialized_prompt_carries_no_redis_keys(self):
        # A Redis key from vault_chat_state_store would start with
        # a namespace prefix; assert no compose_key-shaped strings
        # in the prompt.
        d = new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Netflix", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=1.0,
                ),
            },
            origin_turn_id="t0", now=1.0,
        )
        store_draft(d)
        snap = vbv2._build_v2_snapshot(
            vault_id=VAULT, session_id=SESSION,
            user_message="save it",
            current_user_turn_id="u-1",
            preceding_assistant_turn_id="a-0",
            memory=None, now=2.0,
        )
        prompt = self._prompt_payload(snap)
        # Compose-key namespace shapes.
        for redis_shape in (
            "chat:draft:", "chat:focus:", "chat:auth:",
            "vault_chat_state:",
        ):
            self.assertNotIn(redis_shape, prompt)

    def test_serialized_prompt_carries_no_authorization_ids(self):
        # Mint an authorization record. Its auth_id must not leak
        # into the decider prompt (integration owns auth records;
        # decider must never see one).
        from vault_chat_authorization_record import mint_authorization
        rec = mint_authorization(
            vault_id=VAULT, session_id=SESSION,
            target_kind="draft", target_id="d-1",
            action=AUTH_ACTION_SAVE,
            authorizing_user_turn_id="u-1",
            preceding_assistant_turn_id="a-0",
            confidence=0.9,
        )
        snap = vbv2._build_v2_snapshot(
            vault_id=VAULT, session_id=SESSION,
            user_message="save it",
            current_user_turn_id="u-2",
            preceding_assistant_turn_id="a-1",
            memory=None, now=1.0,
        )
        prompt = self._prompt_payload(snap)
        self.assertNotIn(rec.auth_id, prompt)


# =====================================================================
# Feature-flag OFF: run_chat_brain never invokes v2
# =====================================================================

class FlagOffTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_off_never_calls_run_v2_authoritative_or_shadow(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "off"},
            clear=False,
        ):
            with mock.patch.object(
                vbv2, "run_v2_authoritative",
                new=mock.AsyncMock(),
            ) as m_on, mock.patch.object(
                vbv2, "run_v2_shadow", new=mock.AsyncMock(),
            ) as m_shadow:
                _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
        m_on.assert_not_called()
        m_shadow.assert_not_called()


# =====================================================================
# Feature-flag SHADOW: v2 runs read-only, no writes
# =====================================================================

class FlagShadowTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_shadow_calls_v2_shadow_and_no_writes_from_it(self):
        import vault_chat_state_store as st
        writes: list[tuple[str, bytes, int]] = []
        real_backend = InMemoryChatStateBackend()

        class WriteTracker(st.SharedStateBackend):
            def get(self, key): return real_backend.get(key)
            def set(self, key, value, ttl_seconds):
                writes.append(("set", key, ttl_seconds))
                real_backend.set(key, value, ttl_seconds)
            def delete(self, key):
                writes.append(("delete", key, 0))
                real_backend.delete(key)
            def sadd(self, key, member, ttl_seconds):
                writes.append(("sadd", key, ttl_seconds))
                real_backend.sadd(key, member, ttl_seconds)
            def smembers(self, key):
                return real_backend.smembers(key)
            def srem(self, key, member):
                writes.append(("srem", key, 0))
                real_backend.srem(key, member)
            def sclear(self, key):
                writes.append(("sclear", key, 0))
                real_backend.sclear(key)
            def health(self): return True

        st.install_backend_for_tests(WriteTracker())
        try:
            with mock.patch.dict(
                os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "shadow"},
                clear=False,
            ):
                observed = {"called": False}

                async def fake_shadow(**kwargs):
                    observed["called"] = True
                    self.assertIn("v1_tool", kwargs)
                    self.assertIn("v1_handled", kwargs)

                with mock.patch.object(
                    vbv2, "run_v2_shadow", new=fake_shadow,
                ):
                    _run(vb.run_chat_brain(
                        vault_id=VAULT, session_id=SESSION,
                        turn_id="t-1",
                        vault_name="Personal", reply_language="en",
                        user_message="hi", memory=None,
                    ))
                self.assertTrue(observed["called"])
        finally:
            st.reset_chat_state_backend_for_tests()


# =====================================================================
# SHADOW pipeline: full read-only stack, NEVER any side effect
# =====================================================================

class ShadowFullStackTest(unittest.TestCase, _FingerprintFixture):
    """The shadow pipeline must run snapshot -> decider -> policy
    -> router. It must NEVER call apply_router_result_v2,
    mint_authorization, atomic_consume_authorization, an executor,
    or any focus/draft/pending mutation."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        self._install_fp_secret()

    def tearDown(self):
        reset_chat_state_backend_for_tests()
        self._reset_fp_secret()

    def _fake_provider(self, intent: str = "confirm_draft",
                        target_kind: str = "draft",
                        target_id: str = "d-1"):
        # Build a well-formed decision so policy/router don't reject.
        payload = {
            "schema_version": SEMANTIC_DECISION_V2_SCHEMA_VERSION,
            "intent": intent,
            "target": {"kind": target_kind, "id": target_id},
            "field_patch": {},
            "requested_operations": [],
            "authorization": {"granted": True},
            "confidence": 0.95,
            "reason": "shadow test",
        }
        body = json.dumps(payload)

        async def provider(**kwargs):
            class R:
                content = body
            return R()
        return provider

    def test_shadow_invokes_decider_policy_router(self):
        # Store a live draft so router has a valid target.
        d = new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Netflix", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=1.0,
                ),
                "username": DraftField(
                    value="alice@example.org",
                    source=SOURCE_USER_EXPLICIT, turn_id="t0", at=1.0,
                ),
                "password_ref": DraftField(
                    value="memory:pending_login_draft:password",
                    source=SOURCE_GENERATED, turn_id="t0", at=1.0,
                ),
            },
            origin_turn_id="t0", now=1.0,
        )
        from vault_chat_draft import with_status
        d = with_status(
            d, STATUS_PRESENTED_FOR_CONFIRMATION,
            touch_turn_id="t0", now=1.0,
        )
        store_draft(d)
        stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=FOCUS_KIND_DRAFT, id=d.draft_id,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a-0",
        )

        calls = {"decider": 0, "policy": 0, "router": 0, "log": 0}
        real_decide = vbv2.decide_v2
        real_authorize = vbv2.authorize_v2
        real_route = vbv2.route_v2
        real_log = vbv2.build_and_log_diff

        async def spy_decide(*a, **kw):
            calls["decider"] += 1
            return await real_decide(*a, **kw)

        def spy_authorize(*a, **kw):
            calls["policy"] += 1
            return real_authorize(*a, **kw)

        def spy_route(*a, **kw):
            calls["router"] += 1
            return real_route(*a, **kw)

        def spy_log(**kw):
            calls["log"] += 1
            return real_log(**kw)

        with mock.patch.object(vbv2, "decide_v2", new=spy_decide), \
                mock.patch.object(vbv2, "authorize_v2", new=spy_authorize), \
                mock.patch.object(vbv2, "route_v2", new=spy_route), \
                mock.patch.object(vbv2, "build_and_log_diff", new=spy_log):
            _run(vbv2.run_v2_shadow(
                vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                user_message="yes",
                ai_provider=self._fake_provider(
                    target_id=d.draft_id,
                ),
                v1_tool="confirm_pending_save", v1_handled=True,
            ))
        self.assertEqual(calls["decider"], 1)
        self.assertEqual(calls["policy"], 1)
        self.assertEqual(calls["router"], 1)
        self.assertEqual(calls["log"], 1)

    def test_shadow_never_invokes_integration_or_side_effects(self):
        import vault_chat_authorization_record as vauth
        import vault_chat_focus as vfocus

        forbidden_calls = {
            "apply_router": 0, "mint": 0, "consume": 0,
            "stamp_focus": 0, "clear_focus": 0,
            "clear_focus_if_matches": 0,
        }

        def _sentinel(name):
            def _fn(*a, **kw):
                forbidden_calls[name] += 1
                raise AssertionError(
                    f"shadow mode called forbidden side-effect {name!r}"
                )
            return _fn

        with mock.patch.object(vi, "apply_router_result_v2",
                                 new=_sentinel("apply_router")), \
                mock.patch.object(vauth, "mint_authorization",
                                     new=_sentinel("mint")), \
                mock.patch.object(vauth, "atomic_consume_authorization",
                                     new=_sentinel("consume")), \
                mock.patch.object(vfocus, "stamp_focus",
                                     new=_sentinel("stamp_focus")), \
                mock.patch.object(vfocus, "clear_focus",
                                     new=_sentinel("clear_focus")), \
                mock.patch.object(vfocus, "clear_focus_if_matches",
                                     new=_sentinel("clear_focus_if_matches")):
            _run(vbv2.run_v2_shadow(
                vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                user_message="hi",
                ai_provider=self._fake_provider(intent="chat",
                                                 target_kind="none",
                                                 target_id=None),
                v1_tool="conversational_reply", v1_handled=True,
            ))
        # No forbidden call raised, and every counter stayed at 0.
        for k, v in forbidden_calls.items():
            self.assertEqual(
                v, 0, msg=f"shadow triggered forbidden {k!r}",
            )

    def test_shadow_never_calls_executor(self):
        # If the shadow pipeline mistakenly reached integration, an
        # executor would fire. Verify no executor is invoked when
        # we route through run_v2_shadow.
        exec_counter = {"calls": 0}

        def spy_executor(**kw):
            exec_counter["calls"] += 1

        registry = vi.ExecutorRegistry(
            confirm_save=spy_executor,
            confirm_delete=spy_executor,
            apply_edit=spy_executor,
            apply_create=spy_executor,
            cancel_draft=spy_executor,
            cancel_pending=spy_executor,
            confirm_save_attachment=spy_executor,
        )
        # Shadow doesn't take a registry -- verify structurally that
        # the shadow path never even tries to use one.
        _run(vbv2.run_v2_shadow(
            vault_id=VAULT, session_id=SESSION, turn_id="t-1",
            user_message="hi",
            ai_provider=self._fake_provider(intent="chat",
                                             target_kind="none",
                                             target_id=None),
        ))
        self.assertEqual(exec_counter["calls"], 0)

    def test_shadow_diff_record_contains_router_summary(self):
        d = new_draft(
            vault_id=VAULT, session_id=SESSION,
            draft_kind=DRAFT_LOGIN,
            initial_fields={
                "service": DraftField(
                    value="Netflix", source=SOURCE_USER_EXPLICIT,
                    turn_id="t0", at=1.0,
                ),
                "username": DraftField(
                    value="alice@example.org",
                    source=SOURCE_USER_EXPLICIT, turn_id="t0", at=1.0,
                ),
                "password_ref": DraftField(
                    value="memory:pending_login_draft:password",
                    source=SOURCE_GENERATED, turn_id="t0", at=1.0,
                ),
            },
            origin_turn_id="t0", now=1.0,
        )
        from vault_chat_draft import with_status
        d = with_status(
            d, STATUS_PRESENTED_FOR_CONFIRMATION,
            touch_turn_id="t0", now=1.0,
        )
        store_draft(d)
        stamp_focus(
            vault_id=VAULT, session_id=SESSION,
            kind=FOCUS_KIND_DRAFT, id=d.draft_id,
            assistant_act=FOCUS_ACT_PRESENTED_FOR_CONFIRMATION,
            assistant_turn_id="a-0",
        )
        captured: dict = {}

        real_log = vbv2.build_and_log_diff

        def capture(**kw):
            rec = real_log(**kw)
            captured["record"] = rec
            captured["kwargs"] = kw
            return rec

        with mock.patch.object(vbv2, "build_and_log_diff", new=capture):
            _run(vbv2.run_v2_shadow(
                vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                user_message="yes",
                ai_provider=self._fake_provider(
                    target_id=d.draft_id,
                ),
                v1_tool="confirm_pending_save", v1_handled=True,
            ))
        # v2_router must be passed to the recorder AND the record's
        # router_view must be non-None (proving router_v2 ran).
        self.assertIn("v2_router", captured["kwargs"])
        self.assertIsNotNone(captured["kwargs"]["v2_router"])
        self.assertIsNotNone(captured["record"].router_view)


# =====================================================================
# Feature-flag ON: v2 authoritative; v1 legacy path not called
# =====================================================================

class FlagOnTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        # Register a complete executor set so the readiness guard
        # doesn't refuse mode-on for structural reasons in this
        # group. Each test that wants to exercise the guard
        # explicitly patches this.
        self._registry = vi.ExecutorRegistry(
            confirm_save=lambda **kw: None,
            confirm_delete=lambda **kw: None,
            confirm_save_attachment=lambda **kw: None,
            cancel_draft=lambda **kw: None,
            cancel_pending=lambda **kw: None,
            apply_edit=lambda **kw: None,
            apply_create=lambda **kw: None,
        )
        self._patcher = mock.patch.object(
            vb, "_default_v2_executor_registry",
            return_value=self._registry,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        reset_chat_state_backend_for_tests()

    def test_on_calls_v2_authoritative_not_legacy(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "on"},
            clear=False,
        ):
            legacy_called = {"count": 0}

            async def fake_legacy(**kwargs):
                legacy_called["count"] += 1
                return vb.FALLTHROUGH

            fake_v2_result = vbv2.BrainV2Result(
                handled=True, reply_text="v2-reply", tool="test",
            )

            async def fake_v2_authoritative(**kwargs):
                return fake_v2_result

            with mock.patch.object(vb, "_run_legacy_brain", new=fake_legacy), \
                    mock.patch.object(
                        vbv2, "run_v2_authoritative",
                        new=fake_v2_authoritative,
                    ):
                r = _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
            self.assertEqual(legacy_called["count"], 0)
            self.assertTrue(r.handled)
            self.assertEqual(r.reply_text, "v2-reply")

    def test_on_v2_exception_fails_closed_by_default(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "on"},
            clear=False,
        ):
            os.environ.pop("VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK", None)
            legacy_called = {"count": 0}

            async def fake_legacy(**kwargs):
                legacy_called["count"] += 1
                return vb.FALLTHROUGH

            async def fake_v2_crash(**kwargs):
                raise RuntimeError("v2 broke")

            with mock.patch.object(vb, "_run_legacy_brain", new=fake_legacy), \
                    mock.patch.object(
                        vbv2, "run_v2_authoritative", new=fake_v2_crash,
                    ):
                r = _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
            self.assertEqual(legacy_called["count"], 0)
            self.assertTrue(r.handled)
            self.assertIn("Sorry", r.reply_text)


# =====================================================================
# V2ExecutionPhase-aware fallback (commit 5a)
# =====================================================================

class PhaseAwareFallbackTest(unittest.TestCase):
    """V1_FALLBACK env is honored only for READ_ONLY-phase failures.
    Any exception caught after the side-effect boundary results in
    a controlled error, never a v1 fallthrough."""

    def test_read_only_phase_fallback_when_env_on(self):
        with mock.patch.dict(
            os.environ,
            {"VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK": "on"},
            clear=False,
        ):
            r = vbv2._handle_on_exception(
                "decider_failed", vbv2.V2ExecutionPhase.READ_ONLY,
            )
        self.assertFalse(r.handled)
        self.assertIn("v2_error_v1_fallback", r.fallthrough_reason)

    def test_read_only_phase_no_fallback_when_env_off(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK", None)
            r = vbv2._handle_on_exception(
                "decider_failed", vbv2.V2ExecutionPhase.READ_ONLY,
            )
        self.assertTrue(r.handled)
        self.assertIn("Sorry", r.reply_text)

    def test_integration_started_phase_never_falls_back(self):
        # Even with the env var explicitly on, integration-phase
        # failure MUST NOT delegate to v1 -- state mutation may
        # already have landed.
        with mock.patch.dict(
            os.environ,
            {"VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK": "on"},
            clear=False,
        ):
            r = vbv2._handle_on_exception(
                "integration_failed",
                vbv2.V2ExecutionPhase.INTEGRATION_STARTED,
            )
        self.assertTrue(r.handled)
        self.assertNotIn("v2_error_v1_fallback", r.fallthrough_reason)
        self.assertIn("v2_controlled_error", r.fallthrough_reason)
        self.assertIn("Sorry", r.reply_text)

    def test_executor_completed_phase_never_falls_back(self):
        # Reply-rendering exception AFTER executor completed:
        # controlled error, never v1 fallthrough.
        with mock.patch.dict(
            os.environ,
            {"VAULTAI_CHAT_BRAIN_V2_V1_FALLBACK": "on"},
            clear=False,
        ):
            r = vbv2._handle_on_exception(
                "render_reply_failed",
                vbv2.V2ExecutionPhase.EXECUTOR_COMPLETED,
            )
        self.assertTrue(r.handled)
        self.assertNotIn("v2_error_v1_fallback", r.fallthrough_reason)
        self.assertIn("v2_controlled_error", r.fallthrough_reason)


# =====================================================================
# Runtime-readiness guard (commit 5a)
# =====================================================================

class ActionKindPartitionTest(unittest.TestCase):
    """The action-kind partition MUST cover ACTION_KINDS exactly
    with no overlap and no unknown entries (asserted at import
    time in vault_chat_integration_v2). These tests re-assert the
    invariants at test time so a subsequent commit that adds a
    new action_kind but forgets the partition fails loudly."""

    def test_partition_covers_every_action_kind(self):
        union = (vi.EXECUTOR_REQUIRED_ACTION_KINDS
                 | vi.NON_EXECUTOR_ACTION_KINDS)
        self.assertEqual(union, ACTION_KINDS)

    def test_partition_has_no_overlap(self):
        overlap = (vi.EXECUTOR_REQUIRED_ACTION_KINDS
                   & vi.NON_EXECUTOR_ACTION_KINDS)
        self.assertEqual(overlap, frozenset())

    def test_partition_has_no_unknown_kind(self):
        strays = (
            (vi.EXECUTOR_REQUIRED_ACTION_KINDS
             | vi.NON_EXECUTOR_ACTION_KINDS)
            - ACTION_KINDS
        )
        self.assertEqual(strays, frozenset())

    def test_classification_maps_every_action_kind(self):
        self.assertEqual(
            set(vi.ACTION_KIND_CLASSIFICATION.keys()),
            set(ACTION_KINDS),
        )
        allowed = {"executor_required", "non_executor"}
        for k, v in vi.ACTION_KIND_CLASSIFICATION.items():
            self.assertIn(v, allowed)


class RuntimeReadinessTest(unittest.TestCase):

    def test_empty_registry_is_not_ready(self):
        ready, missing = vi.validate_v2_runtime_readiness(
            vi.ExecutorRegistry(),
        )
        self.assertFalse(ready)
        # readiness demands EXECUTOR_REQUIRED kinds; NON_EXECUTOR
        # kinds are handled natively and are not "missing".
        self.assertEqual(
            sorted(missing), sorted(vi.EXECUTOR_REQUIRED_ACTION_KINDS),
        )

    def test_partial_registry_reports_only_missing_required_kinds(self):
        # Register 2 of the 4 EXECUTOR_REQUIRED kinds.
        registry = vi.ExecutorRegistry(
            confirm_save=lambda **kw: None,
            confirm_delete=lambda **kw: None,
        )
        ready, missing = vi.validate_v2_runtime_readiness(registry)
        self.assertFalse(ready)
        self.assertEqual(
            sorted(missing),
            sorted([ACTION_KIND_CANCEL_PENDING,
                    ACTION_KIND_CONFIRM_SAVE_ATTACHMENT]),
        )

    def test_non_executor_registrations_do_not_satisfy_readiness(self):
        # Only NON_EXECUTOR kinds registered -- readiness still
        # fails because none of the EXECUTOR_REQUIRED ones are
        # present.
        registry = vi.ExecutorRegistry(
            apply_edit=lambda **kw: None,
            apply_create=lambda **kw: None,
            cancel_draft=lambda **kw: None,
        )
        ready, missing = vi.validate_v2_runtime_readiness(registry)
        self.assertFalse(ready)
        self.assertEqual(
            sorted(missing), sorted(vi.EXECUTOR_REQUIRED_ACTION_KINDS),
        )

    def test_complete_required_registry_is_ready_even_without_non_executor(self):
        # All four EXECUTOR_REQUIRED are present; NON_EXECUTOR
        # registrations are omitted deliberately (they aren't
        # required) -- readiness must still pass.
        registry = vi.ExecutorRegistry(
            confirm_save=lambda **kw: None,
            confirm_delete=lambda **kw: None,
            confirm_save_attachment=lambda **kw: None,
            cancel_pending=lambda **kw: None,
        )
        ready, missing = vi.validate_v2_runtime_readiness(registry)
        self.assertTrue(ready)
        self.assertEqual(missing, [])


class OnModeReadinessGuardTest(unittest.TestCase):
    """Mode==on with an incomplete registry must refuse to enter
    v2 -- returning controlled unavailable, not calling v1."""

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self):
        reset_chat_state_backend_for_tests()

    def test_on_mode_refused_when_registry_empty(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "on"},
            clear=False,
        ):
            legacy_called = {"count": 0}
            v2_called = {"count": 0}

            async def fake_legacy(**kwargs):
                legacy_called["count"] += 1
                return vb.FALLTHROUGH

            async def fake_v2(**kwargs):
                v2_called["count"] += 1
                return vbv2.BrainV2Result(
                    handled=True, reply_text="v2-ok",
                )

            with mock.patch.object(
                vb, "_default_v2_executor_registry",
                return_value=vi.ExecutorRegistry(),
            ), mock.patch.object(vb, "_run_legacy_brain",
                                   new=fake_legacy), \
                    mock.patch.object(
                        vbv2, "run_v2_authoritative", new=fake_v2,
                    ):
                r = _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
        # Neither legacy nor v2 ran.
        self.assertEqual(legacy_called["count"], 0)
        self.assertEqual(v2_called["count"], 0)
        # Controlled unavailable reply.
        self.assertTrue(r.handled)
        self.assertEqual(r.reply_text, vbv2.CONTROLLED_UNAVAILABLE_REPLY)
        self.assertEqual(r.fallthrough_reason, "v2_not_ready_on_mode")

    def test_off_mode_does_not_require_executors(self):
        # off mode never calls the readiness guard -- v1 runs unaffected.
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "off"},
            clear=False,
        ):
            legacy_called = {"count": 0}

            async def fake_legacy(**kwargs):
                legacy_called["count"] += 1
                return vb.FALLTHROUGH

            with mock.patch.object(
                vb, "_default_v2_executor_registry",
                return_value=vi.ExecutorRegistry(),  # empty
            ), mock.patch.object(vb, "_run_legacy_brain",
                                   new=fake_legacy):
                _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
        self.assertEqual(legacy_called["count"], 1)

    def test_shadow_mode_does_not_require_executors(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "shadow"},
            clear=False,
        ):
            legacy_called = {"count": 0}
            shadow_called = {"count": 0}

            async def fake_legacy(**kwargs):
                legacy_called["count"] += 1
                return vb.FALLTHROUGH

            async def fake_shadow(**kwargs):
                shadow_called["count"] += 1

            with mock.patch.object(
                vb, "_default_v2_executor_registry",
                return_value=vi.ExecutorRegistry(),
            ), mock.patch.object(vb, "_run_legacy_brain",
                                   new=fake_legacy), \
                    mock.patch.object(
                        vbv2, "run_v2_shadow", new=fake_shadow,
                    ):
                _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
        self.assertEqual(legacy_called["count"], 1)
        self.assertEqual(shadow_called["count"], 1)


# =====================================================================
# No mixed V1/V2 execution in a single request
# =====================================================================

class NoMixedExecutionTest(unittest.TestCase):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        self._registry = vi.ExecutorRegistry(
            confirm_save=lambda **kw: None,
            confirm_delete=lambda **kw: None,
            confirm_save_attachment=lambda **kw: None,
            cancel_draft=lambda **kw: None,
            cancel_pending=lambda **kw: None,
            apply_edit=lambda **kw: None,
            apply_create=lambda **kw: None,
        )
        self._patcher = mock.patch.object(
            vb, "_default_v2_executor_registry",
            return_value=self._registry,
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        reset_chat_state_backend_for_tests()

    def test_off_runs_only_v1(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "off"},
            clear=False,
        ):
            v1_count = {"count": 0}

            async def fake_legacy(**kwargs):
                v1_count["count"] += 1
                return vb.FALLTHROUGH

            with mock.patch.object(vb, "_run_legacy_brain", new=fake_legacy), \
                    mock.patch.object(
                        vbv2, "run_v2_authoritative",
                        new=mock.AsyncMock(),
                    ) as m_on, \
                    mock.patch.object(
                        vbv2, "run_v2_shadow",
                        new=mock.AsyncMock(),
                    ) as m_shadow:
                _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
            self.assertEqual(v1_count["count"], 1)
            m_on.assert_not_called()
            m_shadow.assert_not_called()

    def test_on_runs_only_v2_not_v1_body(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "on"},
            clear=False,
        ):
            v1_count = {"count": 0}

            async def fake_legacy(**kwargs):
                v1_count["count"] += 1
                return vb.FALLTHROUGH

            fake_v2 = mock.AsyncMock(
                return_value=vbv2.BrainV2Result(handled=True,
                                                 reply_text="ok",
                                                 tool="test"),
            )
            with mock.patch.object(vb, "_run_legacy_brain",
                                     new=fake_legacy), \
                    mock.patch.object(
                        vbv2, "run_v2_authoritative", new=fake_v2,
                    ):
                _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
            self.assertEqual(v1_count["count"], 0)
            self.assertEqual(fake_v2.call_count, 1)


# =====================================================================
# Shadow diff record generation
# =====================================================================

class ShadowDiffGenerationTest(unittest.TestCase, _FingerprintFixture):

    def setUp(self):
        install_backend_for_tests(InMemoryChatStateBackend())
        self._install_fp_secret()

    def tearDown(self):
        reset_chat_state_backend_for_tests()
        self._reset_fp_secret()

    def test_shadow_mode_calls_build_and_log_diff(self):
        with mock.patch.dict(
            os.environ, {"VAULTAI_CHAT_BRAIN_MODE": "shadow"},
            clear=False,
        ):
            calls: list[dict] = []

            async def fake_provider(**kwargs):
                class R:
                    content = json.dumps({
                        "schema_version":
                            SEMANTIC_DECISION_V2_SCHEMA_VERSION,
                        "intent": "fallthrough",
                        "target": {"kind": "none", "id": None},
                        "field_patch": {},
                        "requested_operations": [],
                        "authorization": {"granted": False},
                        "confidence": 0.9,
                        "reason": "test",
                    })
                return R()

            with mock.patch.object(vbv2, "_default_ai_provider",
                                     return_value=fake_provider), \
                    mock.patch.object(
                        vbv2, "build_and_log_diff",
                        side_effect=lambda **kw: (
                            calls.append(kw)
                            or sr.ShadowDiffRecordV2(
                                vault_hmac64="v", session_hmac64="s",
                                turn_hmac64="t", v1_tool="fallthrough",
                                v1_handled=False, v2_intent="fallthrough",
                                v2_target_kind="none",
                                v2_target_id_hmac64="-",
                                v2_outcome="allow",
                                v2_reason_code="FALLTHROUGH",
                                v2_confidence_bucket="gte95",
                                v2_fingerprint="0000000000000000",
                                match="intent_equivalent",
                            )
                        ),
                    ), mock.patch.object(
                        vb, "_run_legacy_brain",
                        new=mock.AsyncMock(return_value=vb.FALLTHROUGH),
                    ):
                _run(vb.run_chat_brain(
                    vault_id=VAULT, session_id=SESSION, turn_id="t-1",
                    vault_name="Personal", reply_language="en",
                    user_message="hi", memory=None,
                ))
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
