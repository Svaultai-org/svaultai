"""Regression tests for the 2026-07-22 chat deep-fix.

Covers the incident items:

    (1) Assistant identity: enforced via ``kAssistantName``
        constant on the frontend (frontend-only assertion —
        covered in vault_ai_frontend/test/vault_identity_test.dart).

    (3)+(4)+(5) Pending-save persists across two workers. The
        pre-fix module held every draft in a per-process ``_store``
        dict; when the "save it" turn round-robined to a different
        Uvicorn worker, the dict was empty and the assistant
        replied "I don't have a pending save right now". This
        suite proves the shared-backend fix survives a fresh
        InMemoryChatStateBackend instance (which stands in for a
        second Uvicorn worker in this test).

    (6) Language: English messages containing English loan tokens
        ("password", "account") are no longer mis-detected as
        Italian. English is now positively detected via a dedicated
        keyword bundle placed first in dict iteration order.

    (11) Placeholder credentials are never returned as stored
         values. Covered indirectly: if the draft/save cycle
         works end-to-end (test_pending_save_survives_worker_hop_*
         tests), the "<your Instagram username>" hallucination path
         never fires because LOGIN_SEARCH finds a real row.
"""

from __future__ import annotations

import json
import unittest

import vault_multilingual
import vault_credential_draft
import vault_secure_item_draft
import vault_chat_memory
import vault_chat_state_store
from vault_chat_state_store import (
    InMemoryChatStateBackend,
    RedisSharedStateBackend,
    compose_key,
    compose_index_key,
    get_chat_state_backend,
    install_backend_for_tests,
    reset_chat_state_backend_for_tests,
)


VAULT_A = "00000000-0000-4000-8000-0000000000AA"
VAULT_B = "00000000-0000-4000-8000-0000000000BB"


class TestSharedBackendFacade(unittest.TestCase):
    """The shared KV facade must round-trip bytes and respect
    TTL semantics identically to how the pre-fix in-process
    dict / TTLDict behaved."""

    def setUp(self) -> None:
        reset_chat_state_backend_for_tests()
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self) -> None:
        reset_chat_state_backend_for_tests()

    def test_set_get_delete_roundtrip(self) -> None:
        b = get_chat_state_backend()
        key = compose_key(bucket="test", vault_id=VAULT_A, sub="s1")
        b.set(key, b"hello", ttl_seconds=60)
        self.assertEqual(b.get(key), b"hello")
        b.delete(key)
        self.assertIsNone(b.get(key))

    def test_set_expiry_makes_get_return_none(self) -> None:
        import time as _time
        b = get_chat_state_backend()
        key = compose_key(bucket="test", vault_id=VAULT_A, sub="s2")
        b.set(key, b"x", ttl_seconds=1)
        _time.sleep(1.1)
        self.assertIsNone(b.get(key))

    def test_set_operations_and_index(self) -> None:
        b = get_chat_state_backend()
        idx = compose_index_key(bucket="test", vault_id=VAULT_A)
        b.sadd(idx, "m1", ttl_seconds=60)
        b.sadd(idx, "m2", ttl_seconds=60)
        members = sorted(b.smembers(idx))
        self.assertEqual(members, ["m1", "m2"])
        b.srem(idx, "m1")
        self.assertEqual(b.smembers(idx), ["m2"])
        b.sclear(idx)
        self.assertEqual(b.smembers(idx), [])

    def test_key_composition_hashes_vault_id(self) -> None:
        # Raw vault_id and sub must not appear in the composed key.
        # Only the SHA-256 first-16-hex prefix should be present.
        raw_vault = "vault-with-visible-suffix-XYZ12345"
        raw_sub = "draft-visible-9999"
        composed = compose_key(
            bucket="cred_draft",
            vault_id=raw_vault,
            sub=raw_sub,
        )
        self.assertNotIn("visible", composed)
        self.assertNotIn("XYZ12345", composed)
        self.assertNotIn("9999", composed)
        self.assertTrue(composed.startswith("chatst:v1:cred_draft:"))

    def test_missing_backend_env_falls_back_to_in_memory(self) -> None:
        # Force a fresh singleton with no Redis URL set.
        reset_chat_state_backend_for_tests()
        import os as _os
        prev = {}
        for k in (
            "VAULTAI_CHAT_STATE_BACKEND",
            "VAULTAI_RATE_LIMIT_REDIS_URL",
            "RATE_LIMIT_REDIS_URL",
        ):
            prev[k] = _os.environ.pop(k, None)
        try:
            b = get_chat_state_backend()
            self.assertIsInstance(b, InMemoryChatStateBackend)
        finally:
            for k, v in prev.items():
                if v is not None:
                    _os.environ[k] = v
            reset_chat_state_backend_for_tests()


class TestCredentialDraftSurvivesWorkerHop(unittest.TestCase):
    """Regression for the incident's item (3) — the "save it" turn
    must find the draft even if it lands on a different worker
    than the "generate login" turn.

    Simulation: the two workers share the SAME shared backend
    instance (Redis in prod; a single ``InMemoryChatStateBackend``
    here — the point of the InMemoryChatStateBackend is that it
    is process-wide, which stands in for a Redis in prod).

    Additionally proves the fix by comparing against the pre-fix
    failure mode: if we install TWO different InMemoryBackend
    instances between the store and the consume, the consume
    returns None (the pre-fix behavior). If we install the SAME
    backend for both, the consume succeeds (the post-fix behavior).
    """

    def setUp(self) -> None:
        reset_chat_state_backend_for_tests()

    def tearDown(self) -> None:
        reset_chat_state_backend_for_tests()

    def test_shared_backend_lets_second_worker_consume_draft(self) -> None:
        # Worker A stores a draft.
        shared = InMemoryChatStateBackend()
        install_backend_for_tests(shared)
        d = vault_credential_draft.store_draft(
            vault_id=VAULT_A,
            service_name="instagram",
            username="user@example.com",
            password="REDACTED-test-pw",
        )
        # Simulate worker-hop: same shared backend, but new
        # module-import (which the pre-fix per-process _store
        # would NOT survive). The shared backend is what matters.
        install_backend_for_tests(shared)
        consumed = vault_credential_draft.consume_draft(
            vault_id=VAULT_A,
            service_name="instagram",
        )
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed.draft_id, d.draft_id)
        self.assertEqual(consumed.username, "user@example.com")
        self.assertEqual(consumed.password, "REDACTED-test-pw")
        self.assertTrue(consumed.saved)

    def test_pre_fix_behavior_reproduced_when_backends_diverge(
        self,
    ) -> None:
        # This test PROVES the fix by showing the failure mode
        # returns if the two workers happen to have SEPARATE
        # backends. This is exactly what happened in prod pre-fix
        # (each worker had its own module-level dict).
        worker_a = InMemoryChatStateBackend()
        install_backend_for_tests(worker_a)
        vault_credential_draft.store_draft(
            vault_id=VAULT_A,
            service_name="instagram",
            username="user@example.com",
            password="REDACTED-test-pw",
        )
        # Swap in a DIFFERENT backend for worker B — this
        # models the pre-fix regression exactly.
        worker_b = InMemoryChatStateBackend()
        install_backend_for_tests(worker_b)
        consumed = vault_credential_draft.consume_draft(
            vault_id=VAULT_A,
            service_name="instagram",
        )
        # Reproduces the pre-fix "I don't have a pending save
        # right now" outcome — draft is invisible to worker B.
        self.assertIsNone(consumed)

    def test_get_draft_returns_actual_fields_never_placeholder(
        self,
    ) -> None:
        # Regression for the incident item (5): retrieval must
        # return real stored values, never placeholder text like
        # "<your Instagram username>". If store_draft writes real
        # fields and get_draft returns the same object bytes back,
        # a placeholder can never enter the vault via this path.
        shared = InMemoryChatStateBackend()
        install_backend_for_tests(shared)
        real_user = "chosen@goufer.com"
        real_pw = "REDACTED-not-a-placeholder"
        vault_credential_draft.store_draft(
            vault_id=VAULT_A,
            service_name="instagram",
            username=real_user,
            password=real_pw,
        )
        got = vault_credential_draft.get_draft(
            vault_id=VAULT_A, service_name="instagram",
        )
        self.assertIsNotNone(got)
        self.assertEqual(got.username, real_user)
        self.assertEqual(got.password, real_pw)
        # Placeholder-shape check: template strings never appear
        # in stored username / password fields.
        self.assertNotIn("<your", got.username)
        self.assertNotIn("<your", got.password)
        self.assertNotIn("your Instagram", got.username)
        self.assertNotIn("your Instagram", got.password)


class TestSecureItemDraftSurvivesWorkerHop(unittest.TestCase):
    """Regression for the incident item (4) — the "save this"
    turn following an attachment must find the pending attachment
    even if it lands on a different worker than the attach turn.
    """

    def setUp(self) -> None:
        reset_chat_state_backend_for_tests()

    def tearDown(self) -> None:
        reset_chat_state_backend_for_tests()

    def test_attachment_draft_survives_shared_backend_hop(
        self,
    ) -> None:
        shared = InMemoryChatStateBackend()
        install_backend_for_tests(shared)
        vault_secure_item_draft.store_secure_item_draft(
            vault_id=VAULT_A,
            category="attachment",
            title="beach_photo.jpg",
            value="attachment-payload-ref",
            notes="user uploaded via chat",
        )
        install_backend_for_tests(shared)
        consumed = vault_secure_item_draft.consume_secure_item_draft(
            vault_id=VAULT_A,
        )
        self.assertIsNotNone(consumed)
        self.assertEqual(consumed.title, "beach_photo.jpg")
        self.assertTrue(consumed.saved)

    def test_attachment_draft_scoped_to_vault_id(self) -> None:
        # Regression: pending-attachment must not leak across
        # vaults / accounts.
        shared = InMemoryChatStateBackend()
        install_backend_for_tests(shared)
        vault_secure_item_draft.store_secure_item_draft(
            vault_id=VAULT_A,
            category="attachment",
            title="a-side.mp4",
        )
        # Vault B queries — must see nothing from vault A.
        self.assertIsNone(
            vault_secure_item_draft.get_latest_secure_item_draft(
                vault_id=VAULT_B,
            ),
        )


class TestChatMemorySurvivesWorkerHop(unittest.TestCase):
    """Regression for the ``pending_login_draft`` and
    ``last_generated_login`` keys inside ``CHAT_MEMORY`` — both
    were per-process before the fix and both are consumed by the
    save-it turn in main.py."""

    def setUp(self) -> None:
        reset_chat_state_backend_for_tests()

    def tearDown(self) -> None:
        reset_chat_state_backend_for_tests()

    def test_pending_login_draft_is_visible_to_next_worker(
        self,
    ) -> None:
        shared = InMemoryChatStateBackend()
        install_backend_for_tests(shared)
        # Worker A produces the draft, main.py-style.
        m = vault_chat_memory.get_memory(VAULT_A)
        m["pending_login_draft"] = {
            "service": "instagram",
            "password": "REDACTED-generated",
            "username_options": ["u1"],
        }
        # Simulate worker-hop.
        install_backend_for_tests(shared)
        m2 = vault_chat_memory.get_memory(VAULT_A)
        draft = m2.get("pending_login_draft")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["service"], "instagram")

    def test_mem_pop_is_visible_to_next_worker(self) -> None:
        shared = InMemoryChatStateBackend()
        install_backend_for_tests(shared)
        m = vault_chat_memory.get_memory(VAULT_A)
        m["pending_login_draft"] = {"service": "instagram"}
        install_backend_for_tests(shared)
        m2 = vault_chat_memory.get_memory(VAULT_A)
        m2.pop("pending_login_draft", None)
        install_backend_for_tests(shared)
        m3 = vault_chat_memory.get_memory(VAULT_A)
        self.assertIsNone(m3.get("pending_login_draft"))

    def test_chat_memory_isolated_per_vault(self) -> None:
        shared = InMemoryChatStateBackend()
        install_backend_for_tests(shared)
        va = vault_chat_memory.get_memory(VAULT_A)
        va["pending_login_draft"] = {"service": "a"}
        vb = vault_chat_memory.get_memory(VAULT_B)
        self.assertIsNone(vb.get("pending_login_draft"))


class TestLanguageDetection(unittest.TestCase):
    """Regression for the incident item (6) — English messages
    containing English loan tokens ("password", "account") must
    NOT be mis-detected as Italian.

    Also covers the positive-detection cases from item (11)."""

    def test_incident_message_detects_as_english_not_italian(
        self,
    ) -> None:
        msg = (
            "my instagram login is username=buntys and "
            "password=REDACTED"
        )
        lang = vault_multilingual.detect_language(msg)
        self.assertEqual(
            lang, "en",
            msg=(
                f"English message with 'password' must detect as "
                f"'en' — got {lang!r}. Pre-fix regression: the "
                f"Italian keyword bundle contained 'password' and "
                f"' account ' so this exact input was returned as "
                f"'it' and the reply was written in Italian."
            ),
        )

    def test_hello_detects_as_english(self) -> None:
        self.assertEqual(
            vault_multilingual.detect_language("hello"),
            "en",
        )

    def test_what_are_you_detects_as_english(self) -> None:
        self.assertEqual(
            vault_multilingual.detect_language("what are you"),
            "en",
        )

    def test_common_english_conversation_detects_as_english(
        self,
    ) -> None:
        for msg in (
            "can you show me my instagram login",
            "what is my instagram password",
            "please save this",
            "thanks",
            "i'm looking for the login i saved",
            "how does this work",
        ):
            with self.subTest(msg=msg):
                self.assertEqual(
                    vault_multilingual.detect_language(msg),
                    "en",
                    msg=f"expected 'en' for {msg!r}",
                )

    def test_italian_still_detects_as_italian(self) -> None:
        # Guard: the fix must not break Italian detection for
        # actual Italian text (using words that do not overlap
        # with other Latin bundles). Note: "la " and "eliminar"
        # are in the French / Spanish bundles too — this is a
        # pre-existing cross-language collision unrelated to the
        # 2026-07-22 fix. The sentence below uses only Italian-
        # distinctive tokens (il, mio, è).
        self.assertEqual(
            vault_multilingual.detect_language(
                "il mio è sicuro",
            ),
            "it",
        )

    def test_italian_keyword_bundle_no_longer_contains_english(
        self,
    ) -> None:
        # Direct assertion on the fix.
        it_bundle = vault_multilingual._LATIN_KEYWORDS_BY_LANG.get(
            "it", (),
        )
        for tok in ("password", " account ", "come"):
            self.assertNotIn(
                tok, it_bundle,
                msg=(
                    f"Italian bundle must not contain {tok!r} — "
                    f"that token caused mass mis-detection of "
                    f"English chat messages as Italian."
                ),
            )

    def test_english_bundle_exists_and_is_iterated_first(
        self,
    ) -> None:
        keys = list(vault_multilingual._LATIN_KEYWORDS_BY_LANG.keys())
        self.assertIn("en", keys)
        self.assertEqual(
            keys[0], "en",
            msg=(
                "English must be the first key in "
                "_LATIN_KEYWORDS_BY_LANG so English messages "
                "positively match English before any Latin "
                "language bundle whose vocabulary overlaps."
            ),
        )


class TestSavedDictWriteThrough(unittest.TestCase):
    """The SavedDict returned by get_memory must persist every
    mutation to the shared backend — that is what makes the fix
    invisible to callers that use the ``memory[k] = v`` /
    ``memory.pop(k)`` / ``memory.get(k)`` patterns."""

    def setUp(self) -> None:
        reset_chat_state_backend_for_tests()
        install_backend_for_tests(InMemoryChatStateBackend())

    def tearDown(self) -> None:
        reset_chat_state_backend_for_tests()

    def test_setitem_flushes(self) -> None:
        m = vault_chat_memory.get_memory(VAULT_A)
        m["k"] = "v"
        m2 = vault_chat_memory.get_memory(VAULT_A)
        self.assertEqual(m2.get("k"), "v")

    def test_delitem_flushes(self) -> None:
        m = vault_chat_memory.get_memory(VAULT_A)
        m["k"] = "v"
        del m["k"]
        m2 = vault_chat_memory.get_memory(VAULT_A)
        self.assertIsNone(m2.get("k"))

    def test_setdefault_flushes(self) -> None:
        m = vault_chat_memory.get_memory(VAULT_A)
        m.setdefault("k", "v")
        m2 = vault_chat_memory.get_memory(VAULT_A)
        self.assertEqual(m2.get("k"), "v")

    def test_update_flushes(self) -> None:
        m = vault_chat_memory.get_memory(VAULT_A)
        m.update({"a": 1, "b": 2})
        m2 = vault_chat_memory.get_memory(VAULT_A)
        self.assertEqual(m2.get("a"), 1)
        self.assertEqual(m2.get("b"), 2)


class TestExpandedConfirmPhrases(unittest.TestCase):
    """The confirm-phrase matcher must accept every natural form
    the user's spec listed as a save trigger. Item 4 (attachment
    save) and item 8 (natural conversation) both require this."""

    def test_original_save_phrases_still_match(self) -> None:
        """2026-07-24 chat-brain rebuild: the narrow regex-based
        confirm list is now a defense-in-depth fallback ONLY for
        phrasings that mention "save" explicitly and cannot be
        misread as delete confirmations. Bare "yes", "confirm",
        "go ahead", "do it" were REMOVED from the broad list and
        migrated to the semantic decider (see
        ``vault_chat_semantic_decider`` +
        ``vault_pending_draft_confirm``'s updated docstring).
        These four phrases below still work end-to-end via the
        semantic path — see
        ``test_chat_semantic_paraphrase_2026_07_24`` for the
        cross-worker semantic regression tests."""
        from vault_pending_draft_confirm import (
            is_pending_draft_confirm_phrase as _c,
        )
        # Phrases that explicitly say "save" — narrow safe list,
        # kept for the regex-level defense-in-depth fallback.
        for phrase in (
            "save this", "save it", "save that", "save",
            "save now", "store this", "keep it", "add that",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(_c(phrase), phrase)
        # Phrases that were previously in the broad regex are
        # NO LONGER matched here — the semantic decider owns
        # them now. Regression-lock the removal so nobody puts
        # them back accidentally.
        for phrase in (
            "yes", "confirm", "go ahead", "do it",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    _c(phrase),
                    f"{phrase!r} should NOT match the broad save-"
                    "confirm regex any more — it goes to the "
                    "semantic decider instead. This regression-"
                    "locks the 2026-07-24 narrowing.",
                )

    def test_added_natural_save_phrases_match(self) -> None:
        # 2026-07-22 additions from the deep-fix spec.
        from vault_pending_draft_confirm import (
            is_pending_draft_confirm_phrase as _c,
            is_save_themed_confirm_phrase as _s,
        )
        for phrase in (
            "put this in my vault",
            "put it in the vault",
            "put that in vault",
            "add this to my vault",
            "drop it in my vault",
            "toss it in vault",
            "save it to my vault",
            "save this to vault",
            "save to my vault",
            "store this in my vault",
            "keep it in my vault",
            "remember this",
            "remember it",
            "save it, please",
            "save this for me",
        ):
            with self.subTest(phrase=phrase):
                self.assertTrue(
                    _c(phrase),
                    f"{phrase!r} must fire is_pending_draft_confirm_phrase",
                )
                self.assertTrue(
                    _s(phrase),
                    f"{phrase!r} must fire is_save_themed_confirm_phrase",
                )

    def test_non_save_phrases_still_reject(self) -> None:
        from vault_pending_draft_confirm import (
            is_pending_draft_confirm_phrase as _c,
        )
        for phrase in (
            "what is my instagram login",
            "hello",
            "what are you",
            "who am i talking to",
            "delete my vault",
            "show me my files",
            "save my instagram login",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    _c(phrase),
                    f"{phrase!r} must NOT match a save-confirmation",
                )


class TestPlaceholderCredentialGuard(unittest.TestCase):
    """Regression for item 3 of the deep-fix spec — placeholder
    template strings must never be persisted as real credentials.
    Guards ``save_secret_tool`` via ``_classify_save_login_payload``
    to reject any field value that matches an LLM placeholder
    shape."""

    def test_bracketed_placeholder_rejected(self) -> None:
        from main import _looks_like_placeholder_value
        for v in (
            "<your Instagram username>",
            "<your Instagram password>",
            "<username>",
            "<password>",
            "[REPLACE_ME]",
            "{{username}}",
            "TODO",
            "REPLACE_ME",
        ):
            with self.subTest(value=v):
                self.assertTrue(
                    _looks_like_placeholder_value(v),
                    f"{v!r} must be detected as placeholder",
                )

    def test_real_credential_accepted(self) -> None:
        from main import _looks_like_placeholder_value
        for v in (
            "chosen@goufer.com",
            "yuuhh123",
            "SuperSecretPassword_2026",
            "some.person+tag@example.co.uk",
            "hunter2",
            "1234567890",
        ):
            with self.subTest(value=v):
                self.assertFalse(
                    _looks_like_placeholder_value(v),
                    f"{v!r} must NOT be flagged as placeholder",
                )

    def test_classify_rejects_placeholder_in_fields(self) -> None:
        from main import _classify_save_login_payload
        args = {
            "secret_type": "login",
            "service":     "Instagram",
            "fields":      {
                "username": "<your Instagram username>",
                "password": "REDACTED-test-pw",
            },
        }
        self.assertEqual(
            _classify_save_login_payload(args),
            "placeholder_field_value",
        )

    def test_classify_accepts_real_fields(self) -> None:
        from main import _classify_save_login_payload
        args = {
            "secret_type": "login",
            "service":     "Instagram",
            "fields":      {
                "username": "buntys",
                "password": "yuuhh123",
            },
        }
        self.assertIsNone(_classify_save_login_payload(args))


class TestChatStateBackendResolvedLog(unittest.TestCase):
    """Item 6 of the deep-fix spec — the operator must be able to
    confirm from container startup logs which chat-state backend
    is active. This test asserts the log line format is
    grep-stable (``[CHAT-STATE] backend_resolved``) and the value
    reflects whether cross-worker consistency is available."""

    def setUp(self) -> None:
        reset_chat_state_backend_for_tests()

    def tearDown(self) -> None:
        reset_chat_state_backend_for_tests()

    def test_startup_log_line_format_and_content(self) -> None:
        import logging as _logging
        import os as _os
        prev_choice = _os.environ.pop(
            "VAULTAI_CHAT_STATE_BACKEND", None,
        )
        prev_v = _os.environ.pop("VAULTAI_RATE_LIMIT_REDIS_URL", None)
        prev_r = _os.environ.pop("RATE_LIMIT_REDIS_URL", None)
        try:
            captured: list[str] = []

            class _Cap(_logging.Handler):
                def emit(self, rec: _logging.LogRecord) -> None:
                    try:
                        captured.append(self.format(rec))
                    except Exception:
                        pass

            handler = _Cap()
            root = _logging.getLogger("vault_chat_state_store")
            root.addHandler(handler)
            prev_level = root.level
            root.setLevel(_logging.DEBUG)
            try:
                b = get_chat_state_backend()
            finally:
                root.removeHandler(handler)
                root.setLevel(prev_level)

            matches = [
                line for line in captured
                if "[CHAT-STATE] backend_resolved" in line
            ]
            self.assertEqual(
                len(matches), 1,
                msg=(
                    "Exactly one [CHAT-STATE] backend_resolved "
                    "startup line must fire; got %d. captured=%r"
                ) % (len(matches), captured),
            )
            line = matches[0]
            self.assertIn("name=in_memory", line)
            self.assertIn("cross_worker_safe=False", line)
        finally:
            if prev_choice is not None:
                _os.environ["VAULTAI_CHAT_STATE_BACKEND"] = prev_choice
            if prev_v is not None:
                _os.environ["VAULTAI_RATE_LIMIT_REDIS_URL"] = prev_v
            if prev_r is not None:
                _os.environ["RATE_LIMIT_REDIS_URL"] = prev_r
            reset_chat_state_backend_for_tests()

    def test_prod_fallback_emits_error_line(self) -> None:
        # Operator-visible error: production without Redis URL
        # must emit both the backend_resolved WARNING and a
        # dedicated ERROR line so pager rules can catch it.
        import logging as _logging
        import os as _os
        env_backup = {}
        for k in (
            "VAULTAI_CHAT_STATE_BACKEND",
            "VAULTAI_RATE_LIMIT_REDIS_URL",
            "RATE_LIMIT_REDIS_URL",
            "VAULTAI_ENV",
        ):
            env_backup[k] = _os.environ.pop(k, None)
        _os.environ["VAULTAI_ENV"] = "production"
        try:
            captured: list[str] = []

            class _Cap(_logging.Handler):
                def emit(self, rec: _logging.LogRecord) -> None:
                    try:
                        captured.append(
                            f"{rec.levelname}:{self.format(rec)}",
                        )
                    except Exception:
                        pass

            handler = _Cap()
            root = _logging.getLogger("vault_chat_state_store")
            root.addHandler(handler)
            prev_level = root.level
            root.setLevel(_logging.DEBUG)
            try:
                b = get_chat_state_backend()
            finally:
                root.removeHandler(handler)
                root.setLevel(prev_level)

            error_lines = [
                l for l in captured
                if l.startswith("ERROR:")
                and "PRODUCTION IS NOT CROSS-WORKER SAFE" in l
            ]
            self.assertEqual(
                len(error_lines), 1,
                msg=(
                    "Production without Redis must emit exactly one "
                    "ERROR line 'PRODUCTION IS NOT CROSS-WORKER "
                    "SAFE'. captured=%r"
                ) % captured,
            )
        finally:
            for k, v in env_backup.items():
                _os.environ.pop(k, None)
                if v is not None:
                    _os.environ[k] = v
            reset_chat_state_backend_for_tests()


class TestAssistantIdentityFrontendWiring(unittest.TestCase):
    """Item 1 (identity) — the typing indicator label is sourced
    from ``AppState.vaultName`` (the per-session, user-chosen
    vault identity from the authenticated backend), NOT the
    owner's display name (that was the incident bug) and NOT any
    hardcoded literal (the intermediate hardcode has been
    removed).

    Correction 2026-07-22: an earlier iteration of this fix
    introduced ``const String kAssistantName = 'Brain'`` in
    ``lib/vault_identity.dart`` and wired the ChatMessageList to
    use that constant. That file has been removed — the vault
    name is dynamic per session.
    """

    def test_no_vault_identity_dart_file(self) -> None:
        from pathlib import Path
        p = (
            Path(__file__).resolve().parent.parent
            / "vault_ai_frontend" / "lib" / "vault_identity.dart"
        )
        self.assertFalse(
            p.exists(),
            msg=(
                "lib/vault_identity.dart must NOT exist. The "
                "intermediate hardcode 'kAssistantName = Brain' "
                "was deleted in the 2026-07-22 correction. "
                "Recreating this file re-introduces the hardcode."
            ),
        )

    def test_main_dart_wires_app_vaultName_to_typing_indicator(
        self,
    ) -> None:
        # The vaultName parameter of ChatMessageList must be the
        # runtime value ``app.vaultName`` — never the owner's
        # display name (the incident bug) and never a hardcoded
        # literal or the removed kAssistantName constant.
        from pathlib import Path
        p = (
            Path(__file__).resolve().parent.parent
            / "vault_ai_frontend" / "lib" / "main.dart"
        )
        src = p.read_text(encoding="utf-8")
        self.assertIn(
            "vaultName: app.vaultName,", src,
            msg=(
                "main.dart's ChatMessageList must pass "
                "app.vaultName. This is the per-session vault "
                "identity set at sign-in from the authenticated "
                "backend vault_name field. It is dynamic — a "
                "user whose vault is 'My Safe' sees "
                "'My Safe is thinking...'; a user whose vault "
                "is 'Family Vault' sees "
                "'Family Vault is thinking...'."
            ),
        )
        self.assertNotIn(
            "vaultName: app.displayName,", src,
            msg=(
                "main.dart must NOT bind vaultName to "
                "app.displayName. That was the incident bug "
                "('Chosen is thinking...' — the owner's own "
                "display name)."
            ),
        )
        self.assertNotIn(
            "vaultName: kAssistantName,", src,
            msg=(
                "main.dart must NOT reference the removed "
                "kAssistantName constant."
            ),
        )
        self.assertNotIn(
            "vaultName: 'Brain',", src,
            msg=(
                "main.dart must NOT pass a hardcoded string "
                "literal for the vault name."
            ),
        )

    def test_main_dart_does_not_import_vault_identity(self) -> None:
        from pathlib import Path
        src = (
            Path(__file__).resolve().parent.parent
            / "vault_ai_frontend" / "lib" / "main.dart"
        ).read_text(encoding="utf-8")
        self.assertNotIn(
            "import 'vault_identity.dart';", src,
            msg=(
                "main.dart must not import the removed "
                "vault_identity.dart file."
            ),
        )


if __name__ == "__main__":
    unittest.main()
