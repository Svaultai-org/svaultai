"""Regression tests for the /chat fast-path guard.

Locks in:

  * The closed set of intents that skip drains.
  * The router peek returns a deterministic envelope for FAQ,
    delete-vault FAQ, crypto Vault, vault overview, billing,
    storage, logins, secure items, and ID document questions —
    without ever touching a drain.
  * File-search / document-summary / cross-vault-search /
    unrecognized intents still go through the drains.
  * A slow drain mock does not delay a FAQ response.
  * The timing log line format is a closed set and refuses to
    include raw prompts, filenames, passwords, or crypto secrets.
  * Existing FAQ / delete / crypto / safety tests still pass
    (verified by the full suite in test_security_hardening + FAQ
    completeness suites — this file only tests the fast-path
    module).
"""

from __future__ import annotations

import logging
import re
import time
import unittest
from unittest import mock

import chat_fast_path as cfp


class TestSafeIntentSet(unittest.TestCase):

    def test_faq_is_safe_without_drains(self):
        self.assertIn(
            cfp.INTENT_FAQ, cfp.INTENTS_SAFE_WITHOUT_DRAINS,
        )

    def test_refusal_intents_are_safe_without_drains(self):
        for i in (
            cfp.INTENT_REFUSAL_SECRET_MATERIAL,
            cfp.INTENT_REFUSAL_EXCHANGE_ACTION,
            cfp.INTENT_REFUSAL_BYPASS_PIN,
            cfp.INTENT_REFUSAL_EXPORT_ALL,
            cfp.INTENT_REFUSAL_MASS_REVEAL,
            cfp.INTENT_REFUSAL_AUTO_SEND,
        ):
            with self.subTest(intent=i):
                self.assertIn(i, cfp.INTENTS_SAFE_WITHOUT_DRAINS)

    def test_deterministic_data_intents_are_safe(self):
        for i in (
            cfp.INTENT_VAULT_OVERVIEW,
            cfp.INTENT_LOGIN_LIST,
            cfp.INTENT_LOGIN_SEARCH,
            cfp.INTENT_SECURE_ITEM_LIST,
            cfp.INTENT_SECURE_ITEM_SEARCH,
            cfp.INTENT_ID_DOCUMENT_LIST,
            cfp.INTENT_BILLING_STATUS,
            cfp.INTENT_STORAGE_USAGE,
            cfp.INTENT_ACTIVITY_RECENT,
            cfp.INTENT_CRYPTO_DELEGATED,
        ):
            with self.subTest(intent=i):
                self.assertIn(i, cfp.INTENTS_SAFE_WITHOUT_DRAINS)

    def test_generated_login_create_draft_never_fast_paths(self):
        self.assertNotIn(
            cfp.INTENT_GENERATED_LOGIN_CREATE_DRAFT,
            cfp.INTENTS_SAFE_WITHOUT_DRAINS,
        )

    def test_file_search_and_llm_still_need_drains(self):
        for i in (
            "vault_file_search",
            "vault_document_summary",
            "vault_cross_vault_search",
            "vault_unrecognized",
        ):
            with self.subTest(intent=i):
                self.assertNotIn(
                    i, cfp.INTENTS_SAFE_WITHOUT_DRAINS,
                )
                self.assertIn(i, cfp.INTENTS_NEEDING_DRAINS)

    def test_disjoint_safe_and_drain_sets(self):
        self.assertEqual(
            cfp.INTENTS_SAFE_WITHOUT_DRAINS
            & cfp.INTENTS_NEEDING_DRAINS,
            frozenset(),
        )


class TestPeekIntentWithoutSideEffects(unittest.TestCase):

    def test_delete_sentinel_bypasses_login_search_fast_path(self):
        called: list[str] = []

        def build(text: str) -> dict:
            called.append(text)
            return {
                "intent": cfp.INTENT_LOGIN_SEARCH,
                "card": {"query": "__delete_item wife"},
            }

        env = cfp.peek_intent_without_side_effects(
            "__delete_item:login:wife",
            build_envelope=build,
        )

        self.assertIsNone(env)
        self.assertEqual(called, [])

    def test_delete_sentinel_bypasses_credential_creation_parser(self):
        from vault_credential_command import (
            ACTION_UNRELATED,
            extract_credential_command,
        )

        command = extract_credential_command(
            "__delete_item:login:qa-wifi-22181689",
            has_pending_draft=False,
        )

        self.assertEqual(command.action, ACTION_UNRELATED)
        self.assertEqual(command.explicit_fields, {})

    def test_complete_credential_assertion_bypasses_lookup_fast_path(self):
        called: list[str] = []

        def build(text: str) -> dict:
            called.append(text)
            return {"intent": "vault_login_search", "card": {}}

        env = cfp.peek_intent_without_side_effects(
            "username audit-user password Audit-pass! "
            "is my AuditService login",
            build_envelope=build,
        )

        self.assertIsNone(env)
        self.assertEqual(called, [])

    def test_router_peek_calls_build_envelope_once(self):
        called: list[str] = []

        def build(text: str) -> dict:
            called.append(text)
            return {"intent": cfp.INTENT_FAQ, "card": {}}

        env = cfp.peek_intent_without_side_effects(
            "how do i delete my vault", build_envelope=build,
        )
        self.assertEqual(len(called), 1)
        self.assertEqual(called[0], "how do i delete my vault")
        self.assertEqual(env["intent"], cfp.INTENT_FAQ)

    def test_peek_returns_none_on_empty(self):
        env = cfp.peek_intent_without_side_effects(
            "", build_envelope=lambda t: {"intent": "x"},
        )
        self.assertIsNone(env)

    def test_peek_swallows_router_exceptions(self):
        def broken(text: str) -> dict:
            raise RuntimeError("router blew up")

        env = cfp.peek_intent_without_side_effects(
            "how do i delete my vault", build_envelope=broken,
        )
        self.assertIsNone(env)


class TestCanSkipDrainsDecision(unittest.TestCase):

    def test_faq_intent_skips_drains(self):
        env = {"intent": cfp.INTENT_FAQ, "card": {}}
        self.assertTrue(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_pending_confirm_forces_slow_path(self):
        env = {"intent": cfp.INTENT_FAQ, "card": {}}
        self.assertFalse(cfp.can_skip_drains(
            env,
            is_pending_confirm=True,
            has_active_context=False,
        ))

    def test_active_context_forces_slow_path(self):
        env = {"intent": cfp.INTENT_FAQ, "card": {}}
        self.assertFalse(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=True,
        ))

    def test_file_search_intent_does_not_skip(self):
        env = {"intent": "vault_file_search", "card": {}}
        self.assertFalse(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_generated_login_create_draft_does_not_skip(self):
        env = {
            "intent": cfp.INTENT_GENERATED_LOGIN_CREATE_DRAFT,
            "card": {
                "cardType": "vault_generated_login_card",
                "view": "create_draft",
            },
        }
        self.assertFalse(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_unrecognized_intent_does_not_skip(self):
        env = {"intent": "vault_unrecognized", "card": {}}
        self.assertFalse(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_missing_envelope_does_not_skip(self):
        self.assertFalse(cfp.can_skip_drains(
            None,
            is_pending_confirm=False,
            has_active_context=False,
        ))


class TestSlowDrainDoesNotDelayFaqResponse(unittest.TestCase):
    """The whole point — a slow drain must not block a FAQ card."""

    def test_faq_message_short_circuits_before_drain(self):

        drain_calls: list[str] = []

        def slow_drain(**_kw):
            drain_calls.append("drain")
            time.sleep(0.5)

        from vault_faq_router import build_faq_envelope
        env = cfp.peek_intent_without_side_effects(
            "How do I delete my vault?",
            build_envelope=lambda t: {
                "intent": cfp.INTENT_FAQ, "card": {},
            },
        )
        can_skip = cfp.can_skip_drains(
            env, is_pending_confirm=False, has_active_context=False,
        )

        started = time.monotonic()
        if not can_skip:
            slow_drain()
        elapsed_ms = int((time.monotonic() - started) * 1000)

        self.assertTrue(can_skip)
        self.assertEqual(drain_calls, [])

        self.assertLess(elapsed_ms, 100)

    def test_delete_vault_faq_message_short_circuits(self):
        from vault_faq_router import build_faq_envelope
        env = build_faq_envelope("How do I delete my vault?")
        self.assertIsNotNone(env)
        self.assertEqual(env["intent"], "vault_faq")
        env_full = {
            "intent": cfp.INTENT_FAQ,
            "card": env["card"],
        }
        self.assertTrue(cfp.can_skip_drains(
            env_full,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_crypto_delegated_short_circuits(self):

        env = {
            "intent": cfp.INTENT_CRYPTO_DELEGATED,
            "card": {"cardType": "vault_crypto_delegated_card"},
        }
        self.assertTrue(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_vault_overview_short_circuits(self):
        env = {"intent": cfp.INTENT_VAULT_OVERVIEW, "card": {}}
        self.assertTrue(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_billing_status_short_circuits(self):
        env = {"intent": cfp.INTENT_BILLING_STATUS, "card": {}}
        self.assertTrue(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))

    def test_storage_usage_short_circuits(self):
        env = {"intent": cfp.INTENT_STORAGE_USAGE, "card": {}}
        self.assertTrue(cfp.can_skip_drains(
            env,
            is_pending_confirm=False,
            has_active_context=False,
        ))


class TestEmitSpanSafety(unittest.TestCase):
    """Timing logs must never carry a raw prompt, filename,
    password, or crypto secret."""

    def test_emit_span_writes_prefixed_line(self):
        with self.assertLogs(
            "chat_fast_path", level="INFO",
        ) as cap:
            cfp.emit_span(
                cfp.SPAN_REQUEST_START,
                vault_id="vault-abc",
                message_len_bytes=42,
            )
        joined = "\n".join(cap.output)
        self.assertIn("[CHAT-PERF]", joined)
        self.assertIn("span=chat.request.start", joined)
        self.assertIn("msg_bytes=42", joined)

        self.assertNotIn("vault-abc", joined)

    def test_emit_span_hashes_vault_id(self):
        with self.assertLogs(
            "chat_fast_path", level="INFO",
        ) as cap:
            cfp.emit_span(
                cfp.SPAN_FAST_ROUTER_START,
                vault_id="vault-12345",
            )
        joined = "\n".join(cap.output)

        m = re.search(r"vault=([0-9a-f]+)", joined)
        self.assertIsNotNone(m)
        self.assertEqual(len(m.group(1)), 12)

    def test_emit_span_drops_extra_with_pin_stopword(self):
        with self.assertLogs(
            "chat_fast_path", level="INFO",
        ) as cap:
            cfp.emit_span(
                cfp.SPAN_RESPONSE_READY,
                vault_id="v",
                extra="pin=123456 was used",
            )
        joined = "\n".join(cap.output)
        self.assertNotIn("pin=123456", joined)
        self.assertNotIn("extra=", joined)

    def test_emit_span_drops_extra_with_seed_stopword(self):
        with self.assertLogs(
            "chat_fast_path", level="INFO",
        ) as cap:
            cfp.emit_span(
                cfp.SPAN_RESPONSE_READY,
                vault_id="v",
                extra="user asked about seed phrase",
            )
        joined = "\n".join(cap.output)
        self.assertNotIn("seed", joined)

    def test_emit_span_drops_extra_with_bearer_stopword(self):
        for stop in (
            "Bearer abc.def",
            "authorization: header",
            "api_key",
            "auth_token",
            "encrypted_data",
            "mnemonic",
            "private_key",
            "pin_verifier",
        ):
            with self.subTest(stop=stop):
                with self.assertLogs(
                    "chat_fast_path", level="INFO",
                ) as cap:
                    cfp.emit_span(
                        cfp.SPAN_RESPONSE_READY,
                        vault_id="v",
                        extra=stop,
                    )
                joined = "\n".join(cap.output)

                self.assertNotIn("extra=", joined)

    def test_emit_span_allows_safe_extra(self):
        with self.assertLogs(
            "chat_fast_path", level="INFO",
        ) as cap:
            cfp.emit_span(
                cfp.SPAN_RESPONSE_READY,
                vault_id="v",
                extra="fast_path=1",
            )
        joined = "\n".join(cap.output)
        self.assertIn("extra=fast_path=1", joined)

    def test_emit_span_rejects_unknown_span(self):

        with self.assertLogs(
            "chat_fast_path", level="WARNING",
        ) as cap:
            cfp.emit_span(
                "chat.totally.made.up",
                vault_id="v",
            )
        joined = "\n".join(cap.output)
        self.assertIn("unknown span", joined)

    def test_emit_span_never_includes_message_body_text(self):

        with self.assertLogs(
            "chat_fast_path", level="INFO",
        ) as cap:
            cfp.emit_span(
                cfp.SPAN_FAST_ROUTER_DONE,
                vault_id="v",
                message_len_bytes=1024,
                intent=cfp.INTENT_FAQ,
            )
        joined = "\n".join(cap.output)

        self.assertNotRegex(
            joined,
            r"\bmessage\s*=\s*",
        )
        self.assertNotRegex(
            joined,
            r"\bprompt\s*=\s*",
        )
        self.assertNotRegex(
            joined,
            r"\bfilename\s*=\s*",
        )


class TestMainWiring(unittest.TestCase):
    """Guard tests: the fast-path check MUST live before the drain
    block in main.py. If someone reorders it after the drains, the
    perf win is silently gone."""

    def test_main_imports_chat_fast_path(self):
        from pathlib import Path
        src = (
            Path(__file__).parent / "main.py"
        ).read_text(encoding="utf-8")
        self.assertIn("import chat_fast_path", src)

    def test_fast_path_check_precedes_drain_text_extraction(self):
        from pathlib import Path
        src = (
            Path(__file__).parent / "main.py"
        ).read_text(encoding="utf-8")

        idx_can_skip = src.find("can_skip_drains")
        idx_drain = src.find("drain_text_extraction")
        self.assertGreater(idx_can_skip, 0)
        self.assertGreater(idx_drain, 0)
        self.assertLess(
            idx_can_skip, idx_drain,
            msg=(
                "the fast-path check MUST be before the first drain "
                "call, otherwise the whole perf win is lost"
            ),
        )

    def test_fast_path_check_precedes_drain_ocr(self):
        from pathlib import Path
        src = (
            Path(__file__).parent / "main.py"
        ).read_text(encoding="utf-8")
        idx_can_skip = src.find("can_skip_drains")
        idx_drain = src.find("drain_ocr")
        self.assertGreater(idx_can_skip, 0)
        self.assertGreater(idx_drain, 0)
        self.assertLess(idx_can_skip, idx_drain)

    def test_fast_path_check_precedes_drain_relationship_building(self):
        from pathlib import Path
        src = (
            Path(__file__).parent / "main.py"
        ).read_text(encoding="utf-8")
        idx_can_skip = src.find("can_skip_drains")
        idx_drain = src.find("drain_relationship_building")
        self.assertGreater(idx_can_skip, 0)
        self.assertGreater(idx_drain, 0)
        self.assertLess(idx_can_skip, idx_drain)


class TestModuleSourceHygiene(unittest.TestCase):

    def test_module_source_never_logs_prompt_or_message(self):
        from pathlib import Path
        src = (
            Path(__file__).parent / "chat_fast_path.py"
        ).read_text(encoding="utf-8")

        for banned in (
            "logger.info(message)",
            "logger.info(prompt)",
            "logger.info(decrypted)",
            "logger.warning(prompt)",
            "print(message)",
            "print(decrypted)",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, src)

    def test_module_declares_closed_set_of_spans(self):
        self.assertGreaterEqual(len(cfp.ALL_SPANS), 6)
        for span in cfp.ALL_SPANS:
            self.assertRegex(span, r"^chat\.[a-z_]+(\.[a-z_]+)?$")


if __name__ == "__main__":
    unittest.main()
