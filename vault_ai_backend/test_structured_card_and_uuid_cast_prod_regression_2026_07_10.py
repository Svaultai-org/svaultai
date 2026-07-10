r"""Regression tests for the second batch of production issues.

Covers three distinct incidents that landed together in production:

  A. Structured `vault_chat_card` envelopes rendering as raw JSON in
     the chat UI when the user asks e.g.
     "generate me a login for American first credit union".
  B. Deterministic router misclassifying "generate me a login for X"
     as `vault_login_search` (the LOGIN_SEARCH regex
     ``login for \S+`` was catching the message before the
     GENERATED_LOGIN_CREATE patterns had a chance).
  C. PostgreSQL `operator does not exist: text = uuid` errors in
     `vault_understanding.py` and `vault_relationship_graph.py`
     because JOINs were casting the TEXT side (`uploaded_files.id`)
     to text and comparing against the UUID side.

The tests here are pure unit and source-inspection tests — they do
NOT hit a real database, do NOT reach OpenAI, and do NOT talk to a
frontend build. They lock the invariants in place so a refactor
cannot silently re-open any of the three regressions.
"""

from __future__ import annotations

import inspect
import unittest




class GenerateLoginRoutesToGeneratedLoginCreateDraft(unittest.TestCase):

    def test_natural_generate_phrasing_hits_generated_login_create(self):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_GENERATED_LOGIN_CREATE_DRAFT,
            INTENT_LOGIN_SEARCH,
        )
        cases = (
            "generate me a login for American first credit union",
            "generate a login for chase",
            "generate a new login for Gmail",
            "create me a login for Google",
            "create a login for Amazon",
            "make me a login for GitHub",
        )
        for phrase in cases:
            with self.subTest(phrase=phrase):
                out = classify_and_build_vault_intent(phrase)
                self.assertEqual(
                    out.get("intent"),
                    INTENT_GENERATED_LOGIN_CREATE_DRAFT,
                    msg=(
                        f"{phrase!r} must route to "
                        "vault_generated_login_create_draft, not "
                        f"{out.get('intent')!r}"
                    ),
                )
                self.assertNotEqual(
                    out.get("intent"), INTENT_LOGIN_SEARCH,
                )

    def test_search_phrasing_still_hits_login_search(self):
        from vault_chat_router import (
            classify_and_build_vault_intent,
            INTENT_LOGIN_SEARCH,
        )
        for phrase in (
            "find my Gmail login",
            "search logins for chase",
            "login for gmail",
        ):
            with self.subTest(phrase=phrase):
                out = classify_and_build_vault_intent(phrase)
                self.assertEqual(
                    out.get("intent"), INTENT_LOGIN_SEARCH, phrase,
                )




class ChatEnvelopeShapeIsFrontendCompatible(unittest.TestCase):

    def test_envelope_has_type_schema_intent_message_card(self):
        from vault_chat_router import (
            build_vault_chat_envelope,
        )
        env = build_vault_chat_envelope(
            "generate me a login for chase",
        )
        self.assertIsInstance(env, dict)


        for key in ("type", "schema", "intent", "message", "card"):
            self.assertIn(key, env, key)


        self.assertEqual(env["type"], "vault_chat_card")
        self.assertEqual(env["schema"], "vault_chat_response_v1")

    def test_login_search_envelope_still_valid_shape(self):
        from vault_chat_router import (
            build_vault_chat_envelope,
        )
        env = build_vault_chat_envelope("find my gmail login")
        self.assertIsInstance(env, dict)
        self.assertEqual(env["type"], "vault_chat_card")

    def test_unrecognized_message_returns_none(self):

        from vault_chat_router import (
            build_vault_chat_envelope,
        )
        self.assertIsNone(
            build_vault_chat_envelope("chosenid"),
            msg=(
                "A bare-name reply must NOT match any router pattern "
                "so the naming continuation path can handle it."
            ),
        )




class RawJsonNeverShownFrontendGuard(unittest.TestCase):

    def _main_dart(self) -> str:
        import pathlib
        here = pathlib.Path(__file__).resolve().parent
        return (
            here.parent
            / "vault_ai_frontend"
            / "lib"
            / "main.dart"
        ).read_text(encoding="utf-8")

    def test_vault_chat_card_type_handled(self):
        src = self._main_dart()
        self.assertIn("type == 'vault_chat_card'", src)


        self.assertIn("kind: 'vault_chat_card'", src)

    def test_unknown_type_returns_safe_fallback_not_raw_json(self):

        src = self._main_dart()




        self.assertIn(
            "no matching renderer or fallback message",
            src,
        )


        self.assertIn(
            "up to date",
            src,
        )

    def test_json_shaped_payload_returns_safe_fallback_when_type_absent(
        self,
    ):

        src = self._main_dart()



        self.assertRegex(src, r"trimmed\.contains\('\"cardType\"'\)")
        self.assertRegex(src, r"trimmed\.contains\('\"schema\"'\)")

    def test_debug_log_when_structured_message_falls_back(self):

        src = self._main_dart()
        self.assertIn("[structured_message_parse]", src)




class UUIDTextCastSafetyInUnderstandingModule(unittest.TestCase):

    def test_stale_understanding_join_casts_uuid_to_text(self):
        import vault_understanding
        src = inspect.getsource(
            vault_understanding.mark_stale_understandings_for_changed_text,
        )


        self.assertNotIn(
            "u.id::text = v.file_id", src,
            msg=(
                "u.id is TEXT, v.file_id is UUID. Casting the TEXT "
                "side to text is a no-op — the comparison is still "
                "TEXT = UUID, which PostgreSQL rejects with "
                "`operator does not exist: text = uuid`. The fix "
                "casts the UUID side down to text."
            ),
        )
        self.assertIn("u.id = v.file_id::text", src)

    def test_stale_embeddings_join_casts_uuid_to_text(self):
        import vault_understanding
        src = inspect.getsource(
            vault_understanding.mark_stale_embeddings_for_changed_text,
        )
        self.assertNotIn("u.id::text = e.file_id", src)
        self.assertIn("u.id = e.file_id::text", src)

    def test_backfill_archive_signals_join_casts_uuid_to_text(self):
        import vault_understanding
        src = inspect.getsource(
            vault_understanding.backfill_archive_signals,
        )
        self.assertIn("v.file_id::text = u.id", src)
        self.assertNotIn(" v.file_id  = u.id::text", src)
        self.assertNotIn(" v.file_id = u.id::text", src)




class UUIDTextCastSafetyInRelationshipGraph(unittest.TestCase):

    def test_load_file_facts_casts_uuid_join_to_text(self):
        import vault_relationship_graph
        src = inspect.getsource(
            vault_relationship_graph.load_file_facts_for_vault,
        )
        self.assertIn("v.file_id::text = u.id", src)
        self.assertIn("e.file_id::text = u.id", src)


        self.assertNotIn(" v.file_id = u.id::text", src)
        self.assertNotIn(" e.file_id = u.id::text", src)

    def test_cleanup_stale_relationships_casts_uuid_join_to_text(self):
        import vault_relationship_graph
        src = inspect.getsource(
            vault_relationship_graph.cleanup_stale_relationships_for_vault,
        )
        self.assertIn("f.id = r.file_a_id::text", src)
        self.assertIn("f.id = r.file_b_id::text", src)


        self.assertNotIn("f.id::text = r.file_a_id", src)
        self.assertNotIn("f.id::text = r.file_b_id", src)




class UUIDTextCastSafetyInUnderstandingSearch(unittest.TestCase):

    def test_understanding_search_facts_join_casts_uuid(self):
        import vault_understanding_search
        src = inspect.getsource(vault_understanding_search)
        self.assertIn("v.file_id::text = u.id", src)
        self.assertIn("e.file_id::text = u.id", src)




class GetPendingNamedFileIsInstrumented(unittest.TestCase):

    def test_pending_lookup_logs_row_shape(self):
        import main
        src = inspect.getsource(main.get_pending_named_file)


        self.assertIn("[CHAT-DEBUG] pending_file_lookup", src)


        self.assertIn("needs_naming", src)
        self.assertIn("upload_status", src)


        self.assertIn("pending_naming", src)
        self.assertIn("in_flight", src)

    def test_get_pending_returns_needs_naming_and_upload_status(self):

        import main
        src = inspect.getsource(main.get_pending_named_file)
        self.assertRegex(
            src,
            r"SELECT id, file_name, content_type, created_at,\s*needs_naming, upload_status",
        )




class ChatEnvelopeIsLoggedBeforeReturn(unittest.TestCase):

    def test_vault_chat_router_response_logs_envelope_shape(self):
        import main
        src = inspect.getsource(main)


        i = src.index('logger.info(\n                    "[CHAT-TRACE] vault_chat_router')
        window = src[i:i + 1000]


        self.assertIn("envelope_type=", window)
        self.assertIn("envelope_schema=", window)


        self.assertIn("intent=", window)
        self.assertIn("card_type=", window)




class NameFileOverrideAppliesEvenWhenLlmGuessedRetrievalIntent(
    unittest.TestCase,
):

    def test_bare_name_beats_retrieve_file_llm_guess(self):
        import main
        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="retrieve_file",
            message="chosenid",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file", (intent, applied, reason))
        self.assertTrue(applied)
        self.assertIsNone(reason)

    def test_bare_name_beats_search_files_about_llm_guess(self):
        import main
        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent="search_files_about",
            message="graduation photo",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)

    def test_bare_name_beats_understand_document_llm_guess(self):
        import main
        intent, applied, _ = main.decide_pending_file_intent_override(
            llm_intent="understand_document",
            message="passport",
            pending_file_present=True,
        )
        self.assertEqual(intent, "name_file")
        self.assertTrue(applied)

    def test_explicit_login_query_from_chat_bucket_downgrades(self):




        import main
        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="show my saved logins",
            pending_file_present=True,
        )
        self.assertEqual(intent, "list_logins")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_logins_intent_downgrade")

    def test_llm_specific_intent_is_trusted_when_message_signals_verb(self):




        import main
        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="retrieve_file",
            message="show my saved logins",
            pending_file_present=True,
        )
        self.assertEqual(intent, "retrieve_file")
        self.assertFalse(applied)
        self.assertEqual(reason, "llm_explicit_other_intent")

    def test_explicit_different_intent_from_chat_bucket_wins(self):

        import main
        intent, applied, reason = main.decide_pending_file_intent_override(
            llm_intent="general_chat",
            message="delete my notes",
            pending_file_present=True,
        )
        self.assertNotEqual(intent, "name_file")
        self.assertFalse(applied)
        self.assertEqual(reason, "explicit_different_intent")


if __name__ == "__main__":
    unittest.main()
